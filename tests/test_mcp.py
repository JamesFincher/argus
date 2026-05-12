from argus_services.events import make_event
from argus_services.mcp import LocalMCPServer
from argus_services.policy import RedactionPolicy
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
