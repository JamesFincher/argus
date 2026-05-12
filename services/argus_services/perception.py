"""Rules-first Argus perception worker.

This module intentionally keeps model summarization behind a tiny interface.
The default summarizer is deterministic so redaction and policy order are
testable before any local model is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .events import EventEnvelope, Relationship, make_event
from .policy import RedactionPolicy
from .streams import POLICY_BLOCKED_STREAM, stream_for_event


class Summarizer(Protocol):
    def summarize(self, event: EventEnvelope) -> str:
        ...


@dataclass(frozen=True)
class TemplateSummarizer:
    max_chars: int = 240

    def summarize(self, event: EventEnvelope) -> str:
        payload = event.payload
        if isinstance(payload.get("summary"), str):
            return _compact(payload["summary"], self.max_chars)
        if event.event_type.endswith("frontmost_window"):
            app = payload.get("app_name") or _nested(payload, "app", "name")
            title = payload.get("window_title") or payload.get("title")
            return _compact(
                "User focused "
                + (str(app) if app else "an app")
                + (f" window {title}" if title else ""),
                self.max_chars,
            )
        if event.event_type.endswith("browser_page"):
            title = payload.get("title") or "a page"
            domain = payload.get("domain") or _nested(payload, "browser", "domain")
            return _compact(
                f"User viewed {title}" + (f" on {domain}" if domain else ""),
                self.max_chars,
            )
        if isinstance(payload.get("text"), str):
            return _compact(payload["text"], self.max_chars)
        return _compact(f"{event.event_type} from {event.sensor_id}", self.max_chars)


@dataclass(frozen=True)
class PerceptionOutput:
    source_event: EventEnvelope
    redacted_event: EventEnvelope
    derived_note: EventEnvelope | None
    blocked_event: EventEnvelope | None
    stream: str


@dataclass
class PerceptionWorker:
    policy: RedactionPolicy = field(default_factory=RedactionPolicy)
    summarizer: Summarizer = field(default_factory=TemplateSummarizer)

    def process(self, event: EventEnvelope) -> PerceptionOutput:
        normalized = self.normalize(event)
        redacted = self.policy.redact_event(normalized)
        surface = self.policy.evaluate_surface(normalized)

        blocked_event: EventEnvelope | None = None
        if not surface.allowed or redacted.sensitivity == "blocked":
            blocked_event = self._policy_block(normalized, redacted, surface.reason)
            return PerceptionOutput(
                source_event=normalized,
                redacted_event=redacted,
                derived_note=None,
                blocked_event=blocked_event,
                stream=POLICY_BLOCKED_STREAM,
            )

        note = self._derived_note(redacted)
        return PerceptionOutput(
            source_event=normalized,
            redacted_event=redacted,
            derived_note=note,
            blocked_event=None,
            stream=stream_for_event(note),
        )

    def normalize(self, event: EventEnvelope) -> EventEnvelope:
        payload = _normalize_payload(event.payload)
        event_type = event.event_type.strip().lower().replace(" ", "_")
        tags = sorted(set(event.tags + ["normalized"]))
        return EventEnvelope.from_dict(
            {
                **event.to_dict(),
                "event_type": event_type,
                "payload": payload,
                "tags": tags,
            }
        )

    def _derived_note(self, event: EventEnvelope) -> EventEnvelope:
        summary = self.summarizer.summarize(event)
        return make_event(
            "perception.note",
            {
                "summary": summary,
                "evidence_event_ids": [event.event_id],
                "source_event_type": event.event_type,
                "redactions_applied": [redaction.kind for redaction in event.redactions],
            },
            source_device_id=event.source_device_id,
            source_platform=event.source_platform,
            sensor_id="argus-perception",
            sensitivity=event.sensitivity,
            raw_scope="none",
            relationships=[Relationship(kind="summarizes", target_event_id=event.event_id)],
            tags=sorted(set(event.tags + ["derived_note"])),
        )

    def _policy_block(
        self,
        original: EventEnvelope,
        redacted: EventEnvelope,
        reason: str,
    ) -> EventEnvelope:
        return make_event(
            "policy.blocked",
            {
                "reason": reason,
                "source_event_id": original.event_id,
                "source_event_type": original.event_type,
                "redactions_applied": [redaction.kind for redaction in redacted.redactions],
            },
            source_device_id=original.source_device_id,
            source_platform=original.source_platform,
            sensor_id="argus-policy",
            sensitivity="blocked",
            raw_scope="none",
            relationships=[Relationship(kind="blocks", target_event_id=original.event_id)],
            tags=sorted(set(original.tags + ["policy_block"])),
        )


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key).strip().lower().replace(" ", "_"): _normalize_payload(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_normalize_payload(child) for child in value]
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def _nested(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _compact(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."
