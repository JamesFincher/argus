from argus_services.audit import AuditRecord
from argus_services.events import make_event
from argus_services.graph import GraphConfig
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
        "sensor_find_workflow_patterns",
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


def test_timeline_search_uses_embedding_note_index_and_redacts_summary():
    server = LocalMCPServer(policy=RedactionPolicy())
    note = server.add_event(
        make_event(
            "perception.note",
            {
                "summary": "Vendor pricing review with alex@example.com",
                "evidence_event_ids": ["source-1"],
            },
        )
    )

    result = server.call_tool("sensor_timeline_search", query="vendor pricing", actor="hermes")

    assert result["ok"] is True
    assert result["matches"][0]["event_id"] == note.event_id
    assert "alex@example.com" not in result["matches"][0]["summary"]
    assert "[REDACTED_EMAIL]" in result["matches"][0]["summary"]
    assert result["matches"][0]["source_event_ids"] == ["source-1"]


def test_workflow_patterns_use_local_timeline_when_graph_disabled():
    server = LocalMCPServer(policy=RedactionPolicy())
    server.add_event(
        make_event(
            "activity.frontmost_window",
            {"summary": "Safari"},
            observed_at="2026-05-13T14:00:00Z",
        )
    )
    server.add_event(
        make_event(
            "activity.browser_page",
            {"summary": "Pricing"},
            observed_at="2026-05-13T14:01:00Z",
        )
    )
    server.add_event(
        make_event(
            "activity.frontmost_window",
            {"summary": "CRM"},
            observed_at="2026-05-13T14:02:00Z",
        )
    )
    server.add_event(
        make_event(
            "activity.browser_page",
            {"summary": "Pricing again"},
            observed_at="2026-05-13T14:03:00Z",
        )
    )

    result = server.call_tool("sensor_find_workflow_patterns", limit=2, actor="hermes")

    assert result["ok"] is True
    assert result["graph_enabled"] is False
    assert result["source"] == "local_timeline"
    assert result["patterns"][0] == {
        "from_event_type": "activity.frontmost_window",
        "to_event_type": "activity.browser_page",
        "count": 2,
    }
    assert server.audit_log.records[-1].tool == "sensor_find_workflow_patterns"
    assert "sanitized_patterns" in server.audit_log.records[-1].details


def test_graph_config_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ARGUS_NEO4J_ENABLED", raising=False)

    config = GraphConfig.from_env()

    assert config.enabled is False
    assert config.uri == "bolt://127.0.0.1:7687"


def test_forget_scope_purges_events_and_tombstones_raw_audit():
    store = InMemoryEventStore()
    event = store.add(
        make_event(
            "activity.browser_page",
            {"title": "Pricing", "domain": "vendor.example"},
        )
    )
    server = LocalMCPServer(store=store, policy=RedactionPolicy())
    server.audit_log.record(
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

    result = server.call_tool("sensor_forget_scope", scope="vendor.example", actor="hermes")

    assert result["ok"] is True
    assert result["status"] == "forgotten"
    assert result["events_removed"] == 1
    assert result["audit_records_tombstoned"] == 1
    assert store.get(event.event_id) is None
    assert server.audit_log.records[0].details["raw_event"]["tombstoned"] is True
    assert server.audit_log.records[-1].tool == "sensor_forget_scope"
    assert server.audit_log.records[-1].event_count == 1


def test_forget_scope_removes_embedding_notes():
    server = LocalMCPServer(policy=RedactionPolicy())
    note = server.add_event(
        make_event(
            "perception.note",
            {"summary": "Vendor.example pricing", "evidence_event_ids": ["source-1"]},
        )
    )

    result = server.call_tool("sensor_forget_scope", scope="vendor.example", actor="hermes")
    search = server.call_tool("sensor_timeline_search", query="vendor", actor="hermes")

    assert result["events_removed"] == 1
    assert result["embedding_notes_removed"] == 1
    assert result["graph_nodes_removed"] == 0
    assert server.store.get(note.event_id) is None
    assert search["matches"] == []


def test_operator_control_and_export_tools_are_audited_with_sanitized_details():
    server = LocalMCPServer(policy=RedactionPolicy())
    server.add_event(
        make_event(
            "perception.note",
            {"summary": "Email alex@example.com about launch"},
        )
    )

    pause = server.call_tool("sensor_pause_scope", scope="macos", actor="operator")
    brief = server.call_tool("sensor_export_session_brief", limit=5, actor="operator")

    assert pause == {"ok": True, "scope": "macos", "status": "pause_requested"}
    assert brief["ok"] is True
    assert "alex@example.com" not in brief["brief"]
    records = server.audit_log.records[-2:]
    assert records[0].tool == "sensor_pause_scope"
    assert records[0].actor == "operator"
    assert records[0].scope == "macos"
    assert records[0].allowed is True
    assert records[0].details == {"requested_scope": "macos"}
    assert records[1].tool == "sensor_export_session_brief"
    assert records[1].event_count == 1
    assert records[1].details["sanitized_brief"].count("[REDACTED_EMAIL]") == 1
