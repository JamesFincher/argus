import io
import json
import tomllib

from argus_services.events import make_event
from argus_services.mcp import LocalMCPServer
from argus_services import mcp_stdio
from argus_services.mcp_stdio import MCP_PROTOCOL_VERSION, MCPStdioServer, TOOL_INPUT_SCHEMAS
from argus_services.policy import RedactionPolicy
from argus_services.store import InMemoryEventStore


def request(method, params=None, request_id=1):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def test_initialize_returns_mcp_server_capabilities():
    transport = MCPStdioServer()

    response = transport.handle_request(
        request("initialize", {"protocolVersion": "2024-11-05", "clientInfo": {"name": "test"}})
    )

    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["serverInfo"]["name"] == "argus"
    assert response["result"]["capabilities"]["tools"] == {"listChanged": False}


def test_initialize_uses_default_protocol_version_when_client_omits_it():
    transport = MCPStdioServer()

    response = transport.handle_request(request("initialize", {}))

    assert response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION


def test_tools_list_exposes_all_local_tools_with_input_schemas():
    transport = MCPStdioServer()

    response = transport.handle_request(request("tools/list"))

    tools = response["result"]["tools"]
    by_name = {tool["name"]: tool for tool in tools}
    assert set(TOOL_INPUT_SCHEMAS) <= set(by_name)
    assert by_name["sensor_expand_event"]["inputSchema"]["required"] == ["event_id"]
    assert "query" in by_name["sensor_timeline_search"]["inputSchema"]["properties"]
    assert "scope" in by_name["sensor_forget_scope"]["inputSchema"]["properties"]


def test_tools_call_invokes_local_mcp_server_and_returns_structured_content():
    store = InMemoryEventStore()
    event = store.add(
        make_event(
            "perception.note",
            {"summary": "Discussed vendor quote with alex@example.com"},
        )
    )
    local = LocalMCPServer(store=store, policy=RedactionPolicy())
    transport = MCPStdioServer(server=local)

    response = transport.handle_request(
        request(
            "tools/call",
            {
                "name": "sensor_expand_event",
                "arguments": {"event_id": event.event_id, "actor": "hermes-test"},
            },
        )
    )

    result = response["result"]
    content = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert result["structuredContent"]["ok"] is True
    assert content["event"]["event_id"] == event.event_id
    assert "alex@example.com" not in content["event"]["payload"]["summary"]
    assert "[REDACTED_EMAIL]" in content["event"]["payload"]["summary"]
    assert local.audit_log.records[-1].actor == "hermes-test"


def test_tools_call_marks_tool_level_failures_as_mcp_errors_without_crashing():
    transport = MCPStdioServer()

    response = transport.handle_request(
        request(
            "tools/call",
            {"name": "sensor_expand_event", "arguments": {"event_id": "missing"}},
        )
    )

    assert "error" not in response
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"] == "event not found"


def test_handler_reports_json_rpc_errors_for_bad_requests():
    transport = MCPStdioServer()

    unknown_method = transport.handle_request(request("missing/method"))
    bad_json = transport.handle_line("{")
    non_object = transport.handle_line("[]")
    bad_jsonrpc = transport.handle_request({"jsonrpc": "1.0", "id": 2, "method": "tools/list"})
    bad_method = transport.handle_request({"jsonrpc": "2.0", "id": 3, "method": ""})
    bad_params = transport.handle_request(
        request("tools/call", {"name": "sensor_get_recent_notes", "arguments": []})
    )
    bad_params_shape = transport.handle_request(request("tools/list", []))
    missing_tool_name = transport.handle_request(request("tools/call", {"arguments": {}}))

    assert unknown_method["error"]["code"] == -32601
    assert bad_json["error"]["code"] == -32700
    assert non_object["error"]["code"] == -32600
    assert bad_jsonrpc["error"]["code"] == -32600
    assert bad_method["error"]["code"] == -32600
    assert bad_params["error"]["code"] == -32602
    assert bad_params_shape["error"]["code"] == -32602
    assert missing_tool_name["error"]["code"] == -32602


def test_tools_call_reports_dispatch_exceptions_as_json_rpc_errors():
    local = LocalMCPServer()
    transport = MCPStdioServer(server=local)

    type_error = transport.handle_request(
        request(
            "tools/call",
            {"name": "sensor_get_recent_notes", "arguments": {"unexpected": True}},
        )
    )
    key_error = transport.handle_request(
        request("tools/call", {"name": "missing_tool", "arguments": {}})
    )

    def raise_runtime_error():
        raise RuntimeError("boom")

    local.registry.register("boom", "raise a runtime error", raise_runtime_error)
    internal_error = transport.handle_request(
        request("tools/call", {"name": "boom", "arguments": {}})
    )

    assert type_error["error"]["code"] == -32602
    assert key_error["error"]["code"] == -32602
    assert internal_error["error"]["code"] == -32603


def test_initialized_notification_returns_no_response():
    transport = MCPStdioServer()

    response = transport.handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )

    assert response is None


def test_unknown_notification_returns_method_not_found_error():
    transport = MCPStdioServer()

    response = transport.handle_request({"jsonrpc": "2.0", "method": "notifications/missing"})

    assert response["id"] is None
    assert response["error"]["code"] == -32601


def test_serve_processes_finite_stdin_without_endless_loop():
    transport = MCPStdioServer()
    stdin = io.StringIO("\n" + json.dumps(request("tools/list")) + "\n")
    stdout = io.StringIO()

    transport.serve(stdin=stdin, stdout=stdout)

    response = json.loads(stdout.getvalue())
    assert response["id"] == 1
    assert response["result"]["tools"][0]["name"] == "sensor_get_recent_notes"


def test_main_invokes_stdio_server(monkeypatch):
    called = {}

    class FakeServer:
        def serve(self):
            called["serve"] = True

    monkeypatch.setattr(mcp_stdio, "MCPStdioServer", FakeServer)

    mcp_stdio.main()

    assert called["serve"] is True


def test_pyproject_registers_stdio_entry_point():
    with open("pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == ["services"]
    assert pyproject["project"]["scripts"]["argus-mcp-stdio"] == "argus_services.mcp_stdio:main"
    assert pyproject["project"]["scripts"]["argus-sensor-mcp"] == "argus_services.mcp_stdio:main"
    assert pyproject["project"]["scripts"]["hermes-sensor-mcp"] == "argus_services.mcp_stdio:main"
    assert pyproject["project"]["scripts"]["argus-native-host"] == "argus_services.native_messaging:main"
    assert pyproject["project"]["scripts"]["argus-mvp-smoke"] == "argus_services.mvp_smoke:main"


def test_stdio_server_uses_env_configured_sqlite_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_TIMELINE_DB_PATH", str(tmp_path / "timeline.db"))

    transport = MCPStdioServer()
    event = transport.server.add_event(
        make_event("perception.note", {"summary": "Persistent vendor note"})
    )
    response = transport.handle_request(
        request(
            "tools/call",
            {"name": "sensor_timeline_search", "arguments": {"query": "vendor"}},
        )
    )

    try:
        assert response["result"]["structuredContent"]["matches"][0]["event_id"] == event.event_id
    finally:
        transport.server.store.close()
        transport.server.audit_log.close()
