"""Small local event store used by tests and the local MCP surface."""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import EventEnvelope
from .policy import RedactionPolicy


@dataclass
class InMemoryEventStore:
    events: list[EventEnvelope] = field(default_factory=list)

    def add(self, event: EventEnvelope) -> EventEnvelope:
        self.events.append(event)
        return event

    def get(self, event_id: str) -> EventEnvelope | None:
        return next((event for event in self.events if event.event_id == event_id), None)

    def recent(self, *, limit: int = 5, event_type_prefix: str | None = None) -> list[EventEnvelope]:
        candidates = self.events
        if event_type_prefix:
            candidates = [
                event for event in candidates
                if event.event_type.startswith(event_type_prefix)
            ]
        return list(reversed(candidates[-limit:]))

    def ambient_summary(self, *, policy: RedactionPolicy, limit: int = 5) -> str:
        notes = []
        for event in self.recent(limit=limit):
            redacted = policy.redact_event(event)
            summary = self.summary_for(redacted)
            if summary:
                notes.append(f"- {summary}")
        if not notes:
            return "Recent ambient context: no local sensor notes available."
        return "Recent ambient context:\n" + "\n".join(notes)

    def summary_for(self, event: EventEnvelope) -> str:
        return _event_summary(event)


def _event_summary(event: EventEnvelope) -> str:
    payload = event.payload
    if isinstance(payload.get("summary"), str):
        return payload["summary"]
    if isinstance(payload.get("title"), str) and isinstance(payload.get("domain"), str):
        return f"{payload['title']} on {payload['domain']}"
    if isinstance(payload.get("app"), dict):
        app_name = payload["app"].get("name") or payload["app"].get("bundle_id")
        if app_name:
            return f"{event.event_type} from {app_name}"
    if isinstance(payload.get("text"), str):
        text = payload["text"].strip()
        if text:
            return text[:180]
    return f"{event.event_type} from {event.sensor_id}"
