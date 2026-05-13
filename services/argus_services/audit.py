"""Audit records for Argus agent-facing access."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .events import utc_now_iso
from .purge import tombstone_raw_event_details


@dataclass(frozen=True)
class AuditRecord:
    actor: str
    tool: str
    scope: str
    event_count: int
    redactions_applied: list[str]
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "actor": self.actor,
            "tool": self.tool,
            "scope": self.scope,
            "event_count": self.event_count,
            "redactions_applied": list(self.redactions_applied),
            "allowed": self.allowed,
            "reason": self.reason,
            "details": dict(self.details),
            "recorded_at": self.recorded_at,
        }


@dataclass
class InMemoryAuditLog:
    records: list[AuditRecord] = field(default_factory=list)

    def record(self, record: AuditRecord) -> AuditRecord:
        self.records.append(record)
        return record

    def recent(self, limit: int = 20) -> list[AuditRecord]:
        return list(reversed(self.records[-limit:]))

    def tombstone_scope(self, scope: str) -> int:
        tombstoned = 0
        updated_records: list[AuditRecord] = []
        for record in self.records:
            details, changed = tombstone_raw_event_details(record.details, scope)
            if changed:
                tombstoned += 1
                updated_records.append(replace(record, details=details))
            else:
                updated_records.append(record)
        self.records = updated_records
        return tombstoned
