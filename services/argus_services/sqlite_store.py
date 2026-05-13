"""SQLite + FTS5 timeline store for local Argus events."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from .audit import AuditRecord
from .events import EventEnvelope
from .policy import RedactionPolicy
from .purge import scope_matches_event, tombstone_raw_event_details
from .store import event_summary


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATION = ROOT / "storage/sqlite/migrations/001_timeline_fts5.sql"


class SQLiteTimelineStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        migration_path: str | Path = DEFAULT_MIGRATION,
    ) -> None:
        self.db_path = Path(db_path)
        self.migration_path = Path(migration_path)
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.apply_migrations()

    def apply_migrations(self) -> None:
        with self._lock:
            self.connection.executescript(self.migration_path.read_text(encoding="utf-8"))
            ensure_column(self.connection, "audit_records", "details_json", "TEXT NOT NULL DEFAULT '{}'")
            self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def add(self, event: EventEnvelope) -> EventEnvelope:
        data = event.to_dict()
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO events (
                  event_id,
                  schema_version,
                  source_device_id,
                  sensor_id,
                  sensor_version,
                  source_platform,
                  event_type,
                  observed_at,
                  ingested_at,
                  session_id,
                  semantic_scope,
                  dedupe_key,
                  sensitivity,
                  raw_scope,
                  payload_json,
                  redactions_json,
                  relationships_json,
                  tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                  schema_version = excluded.schema_version,
                  source_device_id = excluded.source_device_id,
                  sensor_id = excluded.sensor_id,
                  sensor_version = excluded.sensor_version,
                  source_platform = excluded.source_platform,
                  event_type = excluded.event_type,
                  observed_at = excluded.observed_at,
                  ingested_at = excluded.ingested_at,
                  session_id = excluded.session_id,
                  semantic_scope = excluded.semantic_scope,
                  dedupe_key = excluded.dedupe_key,
                  sensitivity = excluded.sensitivity,
                  raw_scope = excluded.raw_scope,
                  payload_json = excluded.payload_json,
                  redactions_json = excluded.redactions_json,
                  relationships_json = excluded.relationships_json,
                  tags_json = excluded.tags_json
                """,
                (
                    data["event_id"],
                    data["schema_version"],
                    data["source_device_id"],
                    data["sensor_id"],
                    data["sensor_version"],
                    data["source_platform"],
                    data["event_type"],
                    data["observed_at"],
                    data["ingested_at"],
                    data["session_id"],
                    semantic_scope_for(event),
                    data["dedupe_key"] or "",
                    data["sensitivity"],
                    data["raw_scope"],
                    _json(data["payload"]),
                    _json(data["redactions"]),
                    _json(data["relationships"]),
                    _json(data["tags"]),
                ),
            )
            self.connection.commit()
        return event

    def get(self, event_id: str) -> EventEnvelope | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return event_from_row(row) if row is not None else None

    def recent(self, *, limit: int = 5, event_type_prefix: str | None = None) -> list[EventEnvelope]:
        parameters: list[Any] = []
        where = ""
        if event_type_prefix:
            where = "WHERE event_type LIKE ?"
            parameters.append(f"{event_type_prefix}%")
        parameters.append(limit)
        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT * FROM events
                {where}
                ORDER BY observed_at DESC, created_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [event_from_row(row) for row in rows]

    def search(self, query: str, *, limit: int = 10) -> list[EventEnvelope]:
        match_query = fts_query(query)
        if not match_query:
            return self.recent(limit=limit)
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT events.*
                FROM event_fts
                JOIN events ON events.event_id = event_fts.event_id
                WHERE event_fts MATCH ?
                ORDER BY bm25(event_fts), events.observed_at DESC
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
        return [event_from_row(row) for row in rows]

    def forget_scope(self, scope: str) -> int:
        with self._lock:
            rows = self.connection.execute("SELECT * FROM events").fetchall()
            event_ids = [
                row["event_id"]
                for row in rows
                if scope_matches_event(event_from_row(row), scope)
            ]
            if event_ids:
                placeholders = ",".join("?" for _ in event_ids)
                self.connection.execute(
                    f"DELETE FROM events WHERE event_id IN ({placeholders})",
                    event_ids,
                )
            self.connection.commit()
        return len(event_ids)

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
        return event_summary(event)


class SQLiteAuditLog:
    def __init__(
        self,
        db_path: str | Path,
        *,
        migration_path: str | Path = DEFAULT_MIGRATION,
    ) -> None:
        self.db_path = Path(db_path)
        self.migration_path = Path(migration_path)
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.apply_migrations()

    def apply_migrations(self) -> None:
        with self._lock:
            self.connection.executescript(self.migration_path.read_text(encoding="utf-8"))
            ensure_column(self.connection, "audit_records", "details_json", "TEXT NOT NULL DEFAULT '{}'")
            self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def record(self, record: AuditRecord) -> AuditRecord:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO audit_records (
                  actor,
                  tool,
                  scope,
                  event_count,
                  redactions_json,
                  allowed,
                  reason,
                  details_json,
                  recorded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.actor,
                    record.tool,
                    record.scope,
                    record.event_count,
                    _json(record.redactions_applied),
                    1 if record.allowed else 0,
                    record.reason,
                    _json(record.details),
                    record.recorded_at,
                ),
            )
            self.connection.commit()
        return record

    def recent(self, limit: int = 20) -> list[AuditRecord]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT *
                FROM audit_records
                ORDER BY recorded_at DESC, audit_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [audit_record_from_row(row) for row in rows]

    def tombstone_scope(self, scope: str) -> int:
        tombstoned = 0
        with self._lock:
            rows = self.connection.execute(
                "SELECT audit_id, details_json FROM audit_records"
            ).fetchall()
            for row in rows:
                details = json.loads(row["details_json"])
                updated, changed = tombstone_raw_event_details(details, scope)
                if not changed:
                    continue
                self.connection.execute(
                    "UPDATE audit_records SET details_json = ? WHERE audit_id = ?",
                    (_json(updated), row["audit_id"]),
                )
                tombstoned += 1
            self.connection.commit()
        return tombstoned


def event_from_row(row: sqlite3.Row) -> EventEnvelope:
    return EventEnvelope.from_dict(
        {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "schema_version": row["schema_version"],
            "source_device_id": row["source_device_id"],
            "source_platform": row["source_platform"],
            "sensor_id": row["sensor_id"],
            "sensor_version": row["sensor_version"],
            "observed_at": row["observed_at"],
            "ingested_at": row["ingested_at"],
            "session_id": row["session_id"],
            "dedupe_key": row["dedupe_key"],
            "sensitivity": row["sensitivity"],
            "raw_scope": row["raw_scope"],
            "payload": json.loads(row["payload_json"]),
            "redactions": json.loads(row["redactions_json"]),
            "relationships": json.loads(row["relationships_json"]),
            "tags": json.loads(row["tags_json"]),
        }
    )


def audit_record_from_row(row: sqlite3.Row) -> AuditRecord:
    return AuditRecord(
        actor=row["actor"],
        tool=row["tool"],
        scope=row["scope"],
        event_count=row["event_count"],
        redactions_applied=json.loads(row["redactions_json"]),
        allowed=bool(row["allowed"]),
        reason=row["reason"],
        details=json.loads(row["details_json"]),
        recorded_at=row["recorded_at"],
    )


def ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def semantic_scope_for(event: EventEnvelope) -> str:
    family, _, leaf = event.event_type.partition(".")
    if family == "activity" and leaf:
        return leaf
    return family or event.event_type


def fts_query(query: str) -> str:
    terms = [
        term.replace('"', "")
        for term in query.strip().split()
        if term.strip().replace('"', "")
    ]
    return " ".join(f'"{term}"' for term in terms)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
