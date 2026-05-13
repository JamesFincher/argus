"""Scoped local purge helpers for Argus data stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .events import EventEnvelope


@dataclass(frozen=True)
class ScopePurgeResult:
    scope: str
    events_removed: int
    audit_records_tombstoned: int = 0
    embedding_notes_removed: int = 0
    graph_nodes_removed: int = 0
    retained_blob_tombstones: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "events_removed": self.events_removed,
            "audit_records_tombstoned": self.audit_records_tombstoned,
            "embedding_notes_removed": self.embedding_notes_removed,
            "graph_nodes_removed": self.graph_nodes_removed,
            "retained_blob_tombstones": self.retained_blob_tombstones,
        }


def normalize_scope(scope: str) -> str:
    normalized = " ".join(scope.strip().lower().split())
    if not normalized:
        raise ValueError("forget scope cannot be empty")
    if normalized.startswith("www."):
        return normalized[4:]
    return normalized


def scope_matches_event(event: EventEnvelope, scope: str) -> bool:
    normalized_scope = normalize_scope(scope)
    if normalized_scope == "all":
        return True

    for value in event_scope_values(event):
        normalized_value = normalize_value(value)
        if not normalized_value:
            continue
        if normalized_value == normalized_scope:
            return True
        if "." in normalized_scope and normalized_value.endswith(f".{normalized_scope}"):
            return True
        if len(normalized_scope) >= 4 and normalized_scope in normalized_value:
            return True
    return False


def event_scope_values(event: EventEnvelope) -> set[str]:
    values = {
        event.event_id,
        event.event_type,
        event.event_type.partition(".")[0],
        event.source_device_id,
        event.source_platform,
        event.sensor_id,
        event.session_id or "",
        event.dedupe_key or "",
        *event.tags,
    }
    values.update(payload_scope_values(event.payload))
    return {value for value in values if value}


def payload_scope_values(value: Any) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if isinstance(child, str):
                values.add(child)
                if key_text in {"url", "href", "link", "domain", "host"}:
                    values.update(host_values(child))
            else:
                values.update(payload_scope_values(child))
    elif isinstance(value, list):
        for child in value:
            values.update(payload_scope_values(child))
    elif isinstance(value, (str, int, float, bool)):
        values.add(str(value))
    return values


def host_values(value: str) -> set[str]:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.hostname or value
    normalized = normalize_value(host)
    if normalized.startswith("www."):
        normalized = normalized[4:]
    values = {normalized}
    parts = normalized.split(".")
    if len(parts) > 2:
        values.add(".".join(parts[-2:]))
    return values


def normalize_value(value: Any) -> str:
    text = " ".join(str(value).strip().lower().split())
    if text.startswith("www."):
        return text[4:]
    return text


def tombstone_raw_event_details(details: dict[str, Any], scope: str) -> tuple[dict[str, Any], bool]:
    raw_event = details.get("raw_event")
    if not isinstance(raw_event, dict):
        return details, False

    try:
        event = EventEnvelope.from_dict(raw_event)
    except Exception:
        return details, False

    if not scope_matches_event(event, scope):
        return details, False

    updated = dict(details)
    updated["raw_event"] = {
        "tombstoned": True,
        "purged_scope": normalize_scope(scope),
        "event_id": raw_event.get("event_id"),
        "event_type": raw_event.get("event_type"),
    }
    updated["raw_data_purged"] = True
    updated["raw_data_purged_scope"] = normalize_scope(scope)
    return updated, True
