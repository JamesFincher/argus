import sqlite3
from concurrent.futures import ThreadPoolExecutor

from argus_services.audit import AuditRecord
from argus_services.events import make_event
from argus_services.event_gateway import store_from_env
from argus_services.policy import RedactionPolicy
from argus_services.sqlite_store import (
    SQLiteAuditLog,
    SQLiteTimelineStore,
    ensure_column,
    fts_query,
    semantic_scope_for,
)


def test_sqlite_timeline_store_bootstraps_migration(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    try:
        tables = {
            row["name"]
            for row in store.connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }

        assert "events" in tables
        assert "event_fts" in tables
        assert "audit_records" in tables
    finally:
        store.close()


def test_sqlite_timeline_store_round_trips_and_upserts_events(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    event = make_event(
        "activity.browser_page",
        {"title": "Pricing", "domain": "vendor.example"},
        observed_at="2026-05-13T14:00:00.000Z",
        source_platform="macos",
        tags=["browser"],
    )
    updated = make_event(
        "activity.browser_page",
        {"title": "Pricing updated", "domain": "vendor.example"},
        event_id=event.event_id,
        observed_at="2026-05-13T14:01:00.000Z",
        source_platform="macos",
        tags=["browser", "updated"],
    )

    try:
        store.add(event)
        store.add(updated)
        stored = store.get(event.event_id)
        count = store.connection.execute("SELECT count(*) FROM events").fetchone()[0]

        assert count == 1
        assert stored is not None
        assert stored.event_id == event.event_id
        assert stored.payload["title"] == "Pricing updated"
        assert stored.tags == ["browser", "updated"]
    finally:
        store.close()


def test_sqlite_recent_orders_newest_first_and_filters_prefix(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    older = make_event(
        "activity.browser_page",
        {"summary": "older"},
        observed_at="2026-05-13T14:00:00.000Z",
    )
    newer = make_event(
        "perception.note",
        {"summary": "newer"},
        observed_at="2026-05-13T14:05:00.000Z",
    )

    try:
        store.add(older)
        store.add(newer)

        assert [event.event_id for event in store.recent(limit=2)] == [
            newer.event_id,
            older.event_id,
        ]
        assert store.recent(limit=2, event_type_prefix="activity.")[0].event_id == older.event_id
    finally:
        store.close()


def test_sqlite_fts_search_uses_payload_summary_title_domain_and_tags(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    pricing = make_event(
        "activity.browser_page",
        {"title": "Pricing plans", "domain": "vendor.example"},
        tags=["procurement"],
    )
    notes = make_event(
        "perception.note",
        {"summary": "Deployment discussion"},
        tags=["infra"],
    )

    try:
        store.add(pricing)
        store.add(notes)

        assert [event.event_id for event in store.search("vendor pricing")] == [pricing.event_id]
        assert [event.event_id for event in store.search("infra")] == [notes.event_id]
        assert store.search("   ", limit=1)[0].event_id == notes.event_id
    finally:
        store.close()


def test_sqlite_forget_scope_deletes_events_and_fts_rows(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    vendor = make_event(
        "activity.browser_page",
        {"title": "Pricing plans", "domain": "vendor.example"},
        tags=["procurement"],
    )
    other = make_event(
        "activity.browser_page",
        {"title": "Docs", "domain": "docs.example"},
        tags=["reference"],
    )

    try:
        store.add(vendor)
        store.add(other)

        assert store.forget_scope("vendor.example") == 1
        assert store.get(vendor.event_id) is None
        assert store.get(other.event_id) is not None
        assert store.search("vendor pricing") == []
    finally:
        store.close()


def test_sqlite_ambient_summary_redacts_policy_sensitive_text(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    event = make_event(
        "perception.note",
        {"summary": "Email alex@example.com about pricing"},
    )

    try:
        assert store.ambient_summary(policy=RedactionPolicy(), limit=1) == (
            "Recent ambient context: no local sensor notes available."
        )
        store.add(event)
        summary = store.ambient_summary(policy=RedactionPolicy(), limit=1)

        assert "alex@example.com" not in summary
        assert "[REDACTED_EMAIL]" in summary
    finally:
        store.close()


def test_gateway_store_from_env_uses_sqlite_when_configured(tmp_path, monkeypatch):
    db_path = tmp_path / "timeline.db"
    monkeypatch.setenv("ARGUS_TIMELINE_DB_PATH", str(db_path))
    store = store_from_env()

    try:
        assert isinstance(store, SQLiteTimelineStore)
        store.add(make_event("activity.frontmost_window", {"title": "Safari"}))
        with sqlite3.connect(db_path) as connection:
            assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    finally:
        store.close()


def test_sqlite_audit_log_records_and_reads_recent_entries(tmp_path):
    audit_log = SQLiteAuditLog(tmp_path / "timeline.db")
    first = AuditRecord(
        actor="hermes-session-1",
        tool="sensor_expand_event",
        scope="full",
        event_count=1,
        redactions_applied=[],
        allowed=False,
        reason="requires approval",
        recorded_at="2026-05-13T14:00:00Z",
    )
    second = AuditRecord(
        actor="hermes-session-1",
        tool="sensor_timeline_search",
        scope="pricing",
        event_count=2,
        redactions_applied=["email"],
        allowed=True,
        reason="redacted timeline search",
        recorded_at="2026-05-13T14:01:00Z",
    )

    try:
        assert audit_log.record(first) is first
        audit_log.record(second)
        recent = audit_log.recent(limit=2)

        assert [record.tool for record in recent] == [
            "sensor_timeline_search",
            "sensor_expand_event",
        ]
        assert recent[0].redactions_applied == ["email"]
        assert recent[0].allowed is True
        assert recent[1].allowed is False
    finally:
        audit_log.close()


def test_sqlite_audit_log_tombstones_matching_raw_event_details(tmp_path):
    audit_log = SQLiteAuditLog(tmp_path / "timeline.db")
    event = make_event(
        "activity.browser_page",
        {"title": "Pricing", "domain": "vendor.example"},
    )

    try:
        audit_log.record(
            AuditRecord(
                actor="argus-event-gateway",
                tool="sensor_ingest_raw",
                scope="stream:raw:macos",
                event_count=1,
                redactions_applied=[],
                allowed=True,
                reason="raw ingest",
                details={"raw_event": event.to_dict(), "raw_data_local_only": True},
            )
        )

        assert audit_log.tombstone_scope("vendor.example") == 1
        details = audit_log.recent(limit=1)[0].details

        assert details["raw_data_purged"] is True
        assert details["raw_event"]["tombstoned"] is True
        assert details["raw_event"]["event_id"] == event.event_id
        assert "payload" not in details["raw_event"]
        assert audit_log.tombstone_scope("missing") == 0
    finally:
        audit_log.close()


def test_sqlite_timeline_store_accepts_threaded_gateway_writes(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    events = [
        make_event(
            "activity.frontmost_window",
            {"title": f"Window {index}"},
            event_id=f"threaded-{index}",
        )
        for index in range(4)
    ]

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(store.add, events))

        assert store.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 4
    finally:
        store.close()


def test_sqlite_helpers_are_spec_aligned():
    assert semantic_scope_for(make_event("activity.focused_field", {})) == "focused_field"
    assert semantic_scope_for(make_event("system.permission_state", {})) == "system"
    assert fts_query('vendor "pricing"') == '"vendor" "pricing"'


def test_sqlite_schema_helper_adds_missing_columns():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("CREATE TABLE sample (id TEXT)")
        ensure_column(connection, "sample", "added", "TEXT")
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(sample)").fetchall()
        }
        assert "added" in columns
    finally:
        connection.close()
