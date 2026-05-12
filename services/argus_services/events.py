"""Canonical event envelope models and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

Sensitivity = Literal["low", "medium", "high", "blocked"]
RawScope = Literal["none", "ephemeral", "durable-by-policy"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_dedupe_key(*parts: object) -> str:
    text = "\x1f".join(str(part) for part in parts if part is not None)
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Redaction:
    kind: str
    path: str
    replacement: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "path": self.path,
            "replacement": self.replacement,
        }


@dataclass(frozen=True)
class Relationship:
    kind: str
    target_event_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "target_event_id": self.target_event_id,
        }


@dataclass
class EventEnvelope:
    event_type: str
    source_device_id: str
    source_platform: str
    sensor_id: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: uuid4().hex)
    schema_version: str = "2026-05-11"
    sensor_version: str = "0.1.0"
    observed_at: str = field(default_factory=utc_now_iso)
    ingested_at: str = field(default_factory=utc_now_iso)
    session_id: str | None = None
    dedupe_key: str | None = None
    sensitivity: Sensitivity = "low"
    raw_scope: RawScope = "ephemeral"
    redactions: list[Redaction] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.dedupe_key is None:
            self.dedupe_key = stable_dedupe_key(
                self.event_type,
                self.source_device_id,
                self.sensor_id,
                self.observed_at,
                self.payload,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "source_device_id": self.source_device_id,
            "source_platform": self.source_platform,
            "sensor_id": self.sensor_id,
            "sensor_version": self.sensor_version,
            "observed_at": self.observed_at,
            "ingested_at": self.ingested_at,
            "session_id": self.session_id,
            "dedupe_key": self.dedupe_key,
            "sensitivity": self.sensitivity,
            "raw_scope": self.raw_scope,
            "payload": self.payload,
            "redactions": [redaction.to_dict() for redaction in self.redactions],
            "relationships": [rel.to_dict() for rel in self.relationships],
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        values = dict(data)
        values["redactions"] = [
            item if isinstance(item, Redaction) else Redaction(**item)
            for item in values.get("redactions", [])
        ]
        values["relationships"] = [
            item if isinstance(item, Relationship) else Relationship(**item)
            for item in values.get("relationships", [])
        ]
        return cls(**values)


def make_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    source_device_id: str = "local",
    source_platform: str = "macos",
    sensor_id: str = "argus",
    sensitivity: Sensitivity = "low",
    tags: list[str] | None = None,
    **overrides: Any,
) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        source_device_id=source_device_id,
        source_platform=source_platform,
        sensor_id=sensor_id,
        payload=payload,
        sensitivity=sensitivity,
        tags=tags or [],
        **overrides,
    )
