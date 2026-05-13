"""Canonicalization precedence for overlapping Argus sensor observations."""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import EventEnvelope


PRECEDENCE_BY_EVENT_TYPE = {
    "activity.browser_page": 90,
    "activity.browser_selection": 90,
    "activity.mail_metadata": 85,
    "activity.mail_compose": 85,
    "activity.mail_action": 85,
    "activity.calendar_item": 80,
    "activity.reminder_item": 80,
    "activity.focused_field": 75,
    "activity.health_summary": 70,
    "activity.device_activity_summary": 65,
    "activity.watch_annotation": 40,
    "activity.screen_frame_ocr": 10,
    "activity.ui_snapshot": 10,
}


@dataclass(frozen=True)
class SuppressedObservation:
    event_id: str
    canonical_event_id: str
    reason: str


@dataclass(frozen=True)
class CanonicalizationResult:
    selected: list[EventEnvelope]
    suppressed: list[SuppressedObservation] = field(default_factory=list)

    @property
    def suppressed_event_ids(self) -> list[str]:
        return [item.event_id for item in self.suppressed]


@dataclass(frozen=True)
class SignalCanonicalizer:
    precedence_by_event_type: dict[str, int] = field(default_factory=lambda: dict(PRECEDENCE_BY_EVENT_TYPE))

    def canonicalize(self, events: list[EventEnvelope]) -> CanonicalizationResult:
        grouped: dict[str, list[EventEnvelope]] = {}
        for event in events:
            grouped.setdefault(canonical_group_key(event), []).append(event)

        selected: list[EventEnvelope] = []
        suppressed: list[SuppressedObservation] = []
        for group in grouped.values():
            canonical = max(group, key=self._sort_key)
            selected.append(canonical)
            for event in group:
                if event.event_id == canonical.event_id:
                    continue
                suppressed.append(
                    SuppressedObservation(
                        event_id=event.event_id,
                        canonical_event_id=canonical.event_id,
                        reason=canonicalization_reason(canonical, event),
                    )
                )

        selected.sort(key=lambda event: (event.observed_at, event.ingested_at, event.event_id))
        suppressed.sort(key=lambda item: item.event_id)
        return CanonicalizationResult(selected=selected, suppressed=suppressed)

    def _sort_key(self, event: EventEnvelope) -> tuple[int, str, str, str]:
        return (
            self.precedence_by_event_type.get(event.event_type, 50),
            event.observed_at,
            event.ingested_at,
            event.event_id,
        )


def canonical_group_key(event: EventEnvelope) -> str:
    for key in ("canonical_scope", "semantic_scope", "dedupe_scope"):
        value = event.payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value.strip().lower()}"
    if event.dedupe_key:
        return f"dedupe:{event.dedupe_key}"
    return f"event:{event.event_id}"


def canonicalization_reason(canonical: EventEnvelope, suppressed: EventEnvelope) -> str:
    return f"{canonical.event_type} supersedes {suppressed.event_type} for overlapping observation"
