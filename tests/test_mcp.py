from argus_services.events import make_event
from argus_services.mcp import LocalMCPServer
from argus_services.policy import RedactionPolicy
from argus_services.sqlite_store import SQLiteTimelineStore
from argus_services.store import InMemoryEventStore


def test_summary_retrieval_returns_redacted_context():
    store = InMemoryEventStore()
    store.add(
        make_event(
            "perception.note",
            {"summary": "Discussed vendor quote with alex@example.com"},
        )
    )
    server = LocalMCPServer(store=store, policy=RedactionPolicy())

    result = server.call_tool("sensor_get_recent_notes")

    assert result["ok"] is True
    assert "Recent ambient context" in result["context"]
    assert "alex@example.com" not in result["context"]
    assert "[REDACTED_EMAIL]" in result["context"]


def test_mcp_discovery_exposes_spec_tools():
    server = LocalMCPServer()
    tool_names = {tool["name"] for tool in server.list_tools()}

    assert {
        "sensor_timeline_search",
        "sensor_get_recent_notes",
        "sensor_expand_event",
        "sensor_pause_scope",
        "sensor_forget_scope",
        "sensor_export_session_brief",
    } <= tool_names


def test_raw_fetch_requires_token_for_high_sensitivity_event():
    store = InMemoryEventStore()
    event = store.add(
        make_event(
            "activity.focused_field",
            {"text": "Bearer abcdefghijklmnopqrstuvwxyz"},
        )
    )
    server = LocalMCPServer(store=store, policy=RedactionPolicy(approval_token="approve"))

    blocked = server.call_tool("sensor_expand_event", event_id=event.event_id, raw_mode="full")
    allowed = server.call_tool(
        "sensor_expand_event",
        event_id=event.event_id,
        raw_mode="full",
        approval_token="approve",
    )
    redacted = server.call_tool("sensor_expand_event", event_id=event.event_id)

    assert blocked["ok"] is False
    assert "requires valid approval token" in blocked["error"]
    assert allowed["ok"] is True
    assert "Bearer abcdefghijklmnopqrstuvwxyz" in allowed["event"]["payload"]["text"]
    assert redacted["ok"] is True
    assert "[REDACTED_BEARER_TOKEN]" in redacted["event"]["payload"]["text"]


def test_raw_fetch_audits_actor_scope_count_and_redactions():
    store = InMemoryEventStore()
    event = store.add(
        make_event(
            "activity.focused_field",
            {"text": "Bearer abcdefghijklmnopqrstuvwxyz"},
        )
    )
    server = LocalMCPServer(store=store, policy=RedactionPolicy(approval_token="approve"))

    blocked = server.call_tool(
        "sensor_expand_event",
        event_id=event.event_id,
        raw_mode="full",
        actor="hermes-session-1",
    )
    redacted = server.call_tool(
        "sensor_expand_event",
        event_id=event.event_id,
        actor="hermes-session-1",
    )

    assert blocked["ok"] is False
    assert redacted["ok"] is True
    records = server.audit_log.records
    assert records[0].actor == "hermes-session-1"
    assert records[0].tool == "sensor_expand_event"
    assert records[0].scope == "full"
    assert records[0].event_count == 1
    assert records[0].allowed is False
    assert "requires valid approval token" in records[0].reason
    assert records[1].scope == "redacted"
    assert records[1].allowed is True
    assert records[1].redactions_applied == ["bearer_token"]


def test_timeline_search_returns_redacted_matches():
    store = InMemoryEventStore()
    store.add(
        make_event(
            "perception.note",
            {"summary": "Pricing discussion with alex@example.com"},
        )
    )
    server = LocalMCPServer(store=store, policy=RedactionPolicy())

    result = server.call_tool("sensor_timeline_search", query="pricing", actor="hermes")

    assert result["ok"] is True
    assert len(result["matches"]) == 1
    assert "alex@example.com" not in result["matches"][0]["summary"]
    assert "[REDACTED_EMAIL]" in result["matches"][0]["summary"]
    assert server.audit_log.records[-1].tool == "sensor_timeline_search"


def test_timeline_search_uses_sqlite_fts_when_available(tmp_path):
    store = SQLiteTimelineStore(tmp_path / "timeline.db")
    try:
        pricing = store.add(
            make_event(
                "perception.note",
                {"summary": "Pricing discussion with alex@example.com"},
                tags=["procurement"],
            )
        )
        store.add(
            make_event(
                "perception.note",
                {"summary": "Deployment discussion"},
                tags=["infra"],
            )
        )
        server = LocalMCPServer(store=store, policy=RedactionPolicy())

        result = server.call_tool("sensor_timeline_search", query="procurement", actor="hermes")

        assert result["ok"] is True
        assert [match["event_id"] for match in result["matches"]] == [pricing.event_id]
        assert "alex@example.com" not in result["matches"][0]["summary"]
        assert "[REDACTED_EMAIL]" in result["matches"][0]["summary"]
        assert server.audit_log.records[-1].event_count == 1
    finally:
        store.close()
