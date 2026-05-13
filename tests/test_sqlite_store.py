import sqlite3
from concurrent.futures import ThreadPoolExecutor

from argus_services.events import make_event
from argus_services.event_gateway import store_from_env
from argus_services.policy import RedactionPolicy
from argus_services.sqlite_store import SQLiteTimelineStore, fts_query, semantic_scope_for


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
    finally:
        store.close()


def test_sqlite_ambient_summary_redacts_policy_sensitive_text(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    event = make_event(
        "perception.note",
        {"summary": "Email alex@example.com about pricing"},
    )

    try:
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
