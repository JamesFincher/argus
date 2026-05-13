import io
from types import SimpleNamespace

import pytest

from argus_services import mvp_smoke
from argus_services.events import make_event
from argus_services.mcp_stdio import MCPStdioServer
from argus_services.mvp_smoke import (
    _assert_smoke_invariants,
    _call_mcp_tool,
    _run_mvp_smoke,
    _send_native_page_context,
    main,
    run_mvp_smoke,
)
from argus_services.native_messaging import write_frame


def test_mvp_smoke_runs_native_gateway_perception_and_mcp_paths(tmp_path):
    result = run_mvp_smoke(tmp_path / "timeline.db")

    assert result["ok"] is True
    assert result["native_response"]["gateway_status"] == 202
    assert result["native_response"]["event_type"] == "activity.browser_page"
    assert result["derived_note_id"]
    assert result["raw_without_approval"]["ok"] is False
    assert result["raw_without_approval"]["error"] == "raw access requires valid approval token"
    assert "Vendor Pricing on vendor.example.com" in result["recent_notes"]
    assert "alex@example.com" not in result["recent_notes"]
    assert result["raw_ingest_audit_count"] >= 2
    assert result["agent_audit_count"] >= 2
    assert result["stored_event_count"] == 2
    assert "stream:raw:macos" in {call["stream"] for call in result["publisher_calls"]}
    assert "stream:derived:notes" in {call["stream"] for call in result["publisher_calls"]}


def test_mvp_smoke_uses_temporary_database_when_no_path_is_given():
    result = run_mvp_smoke()

    assert result["ok"] is True
    assert result["db_path"].endswith("timeline.db")


def test_mvp_smoke_handles_policy_blocked_perception_branch(tmp_path, monkeypatch):
    class BlockingWorker:
        def __init__(self, policy):
            self.policy = policy

        def process(self, event):
            return SimpleNamespace(
                blocked_event=make_event(
                    "policy.blocked",
                    {"reason": "test block", "source_event_id": event.event_id},
                    sensor_id="argus-policy",
                    sensitivity="blocked",
                    raw_scope="none",
                ),
                derived_note=None,
            )

    monkeypatch.setattr(mvp_smoke, "PerceptionWorker", BlockingWorker)

    result = run_mvp_smoke(tmp_path / "timeline.db")

    assert result["derived_note_id"] is None
    assert "stream:policy:blocked" in {call["stream"] for call in result["publisher_calls"]}


def test_mvp_smoke_reports_missing_stored_native_event(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mvp_smoke,
        "_send_native_page_context",
        lambda gateway_url: {"ok": True, "event_id": "missing"},
    )

    with pytest.raises(RuntimeError, match="referenced an event that was not stored"):
        _run_mvp_smoke(tmp_path / "timeline.db")


def test_send_native_page_context_reports_host_failures(monkeypatch):
    monkeypatch.setattr(mvp_smoke, "run_native_host", lambda **kwargs: 1)
    with pytest.raises(RuntimeError, match="native host exited with 1"):
        _send_native_page_context("http://127.0.0.1:8765/events")

    def write_no_response(**kwargs):
        return 0

    monkeypatch.setattr(mvp_smoke, "run_native_host", write_no_response)
    with pytest.raises(RuntimeError, match="did not write a response"):
        _send_native_page_context("http://127.0.0.1:8765/events")

    def write_error(output_stream: io.BytesIO, **kwargs):
        write_frame(output_stream, {"ok": False, "error": "bad frame"})
        return 0

    monkeypatch.setattr(mvp_smoke, "run_native_host", write_error)
    with pytest.raises(RuntimeError, match="native host failed"):
        _send_native_page_context("http://127.0.0.1:8765/events")


def test_call_mcp_tool_reports_json_rpc_errors():
    with pytest.raises(RuntimeError, match="MCP tool call failed"):
        _call_mcp_tool(MCPStdioServer(), "", {}, request_id=99)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "native_response": {"event_type": "activity.other"},
                "recent_text": "",
                "raw_result": {"ok": False},
                "raw_ingest_records": [{}],
                "agent_records": [{}, {}],
            },
            "browser-page event",
        ),
        (
            {
                "native_response": {"event_type": "activity.browser_page"},
                "recent_text": "alex@example.com",
                "raw_result": {"ok": False},
                "raw_ingest_records": [{}],
                "agent_records": [{}, {}],
            },
            "leaked raw email",
        ),
        (
            {
                "native_response": {"event_type": "activity.browser_page"},
                "recent_text": "",
                "raw_result": {"ok": True},
                "raw_ingest_records": [{}],
                "agent_records": [{}, {}],
            },
            "raw expansion",
        ),
        (
            {
                "native_response": {"event_type": "activity.browser_page"},
                "recent_text": "",
                "raw_result": {"ok": False},
                "raw_ingest_records": [],
                "agent_records": [{}, {}],
            },
            "raw local ingest audit",
        ),
        (
            {
                "native_response": {"event_type": "activity.browser_page"},
                "recent_text": "",
                "raw_result": {"ok": False},
                "raw_ingest_records": [{}],
                "agent_records": [{}],
            },
            "MCP audit records",
        ),
    ],
)
def test_smoke_invariant_failures_are_explicit(kwargs, message):
    with pytest.raises(RuntimeError, match=message):
        _assert_smoke_invariants(**kwargs)


def test_mvp_smoke_main_prints_machine_readable_summary(tmp_path, capsys):
    exit_code = main(["--db-path", str(tmp_path / "timeline.db")])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"ok": true' in output
    assert '"raw_without_approval"' in output
