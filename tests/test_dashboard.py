import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from argus_services.audit import InMemoryAuditLog
from argus_services.dashboard import dashboard_state, render_dashboard_html
from argus_services.event_gateway import EventGateway, PausedScopeError, make_handler
from argus_services.events import make_event
from argus_services.mcp import LocalMCPServer
from argus_services.policy import RedactionPolicy
from argus_services.store import InMemoryEventStore


class RecordingPublisher:
    def __init__(self):
        self.calls = []

    def publish(self, stream, event):
        self.calls.append((stream, event.event_id))
        return "1778682000000-0"

    def execute(self, command):
        if command == ["PING"]:
            return "PONG"
        raise AssertionError(command)


def test_dashboard_separates_raw_events_from_sanitized_hermes_outputs():
    store = InMemoryEventStore()
    audit_log = InMemoryAuditLog()
    raw_event = store.add(
        make_event(
            "perception.note",
            {"summary": "Email alex@example.com with token sk_test_1234567890abcdef"},
        )
    )
    server = LocalMCPServer(store=store, policy=RedactionPolicy(), audit_log=audit_log)

    result = server.call_tool("sensor_get_recent_notes", actor="hermes")
    state = dashboard_state(
        store=store,
        audit_log=audit_log,
        policy=RedactionPolicy(),
        publisher=RecordingPublisher(),
    )

    assert raw_event.payload["summary"] in str(state["raw_events"])
    assert "alex@example.com" in str(state["raw_events"])
    assert "alex@example.com" not in str(state["sanitized_events"])
    assert "alex@example.com" not in str(state["hermes_outputs"])
    assert "[REDACTED_EMAIL]" in result["context"]
    assert "[REDACTED_EMAIL]" in str(state["hermes_outputs"])
    assert state["redis"]["ping"] == "PONG"


def test_event_gateway_records_raw_ingest_audit_without_hermes_output():
    publisher = RecordingPublisher()
    gateway = EventGateway(publisher=publisher)
    event = make_event(
        "activity.browser_page",
        {"title": "Raw dashboard", "domain": "argus.local"},
        source_platform="macos",
    )

    result = gateway.ingest(event)
    state = gateway.dashboard_state()

    assert result.redis_id == "1778682000000-0"
    assert publisher.calls == [("stream:raw:macos", event.event_id)]
    assert state["audit_records"][0]["tool"] == "sensor_ingest_raw"
    assert state["audit_records"][0]["details"]["raw_data_local_only"] is True
    assert state["audit_records"][0]["details"]["raw_event"]["event_id"] == event.event_id
    assert state["hermes_outputs"] == []


def test_event_gateway_pause_blocks_ingest_until_resumed():
    gateway = EventGateway(publisher=RecordingPublisher())
    event = make_event("activity.window_focus", {"title": "Safari"}, source_platform="macos")

    gateway.pause_scope("macos")
    try:
        gateway.ingest(event)
    except PausedScopeError as exc:
        assert exc.scope == "macos"
    else:
        raise AssertionError("paused gateway should reject macOS ingest")

    gateway.resume_scope("macos")
    assert gateway.ingest(event).stream == "stream:raw:macos"


def test_dashboard_http_routes_are_local_json_and_html():
    gateway = EventGateway(publisher=RecordingPublisher())
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        state = json.loads(urllib.request.urlopen(f"{base_url}/dashboard.json", timeout=5).read())
        html = urllib.request.urlopen(f"{base_url}/dashboard", timeout=5).read().decode("utf-8")

        assert state["ok"] is True
        assert "stream:raw:macos" in state["redis"]["streams"]
        assert "ArgusOS Dashboard" in html

        pause = urllib.request.Request(f"{base_url}/control/pause", data=b"{}", method="POST")
        paused = json.loads(urllib.request.urlopen(pause, timeout=5).read())
        assert paused["status"] == "paused"

        event = make_event("activity.window_focus", {"title": "Safari"}).to_dict()
        request = urllib.request.Request(
            f"{base_url}/events",
            data=json.dumps(event).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 423
        else:
            raise AssertionError("paused HTTP gateway should reject ingest")
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_dashboard_http_forget_and_export_controls_apply_policy():
    gateway = EventGateway(publisher=RecordingPublisher())
    event = make_event(
        "perception.note",
        {"summary": "Email alex@example.com about vendor.example pricing"},
        source_platform="macos",
    )
    gateway.ingest(event)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        export = urllib.request.Request(
            f"{base_url}/control/export",
            data=b"limit=10",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        brief = json.loads(urllib.request.urlopen(export, timeout=5).read())
        assert brief["ok"] is True
        assert "alex@example.com" not in brief["brief"]
        assert "[REDACTED_EMAIL]" in brief["brief"]

        forget = urllib.request.Request(
            f"{base_url}/control/forget",
            data=b"scope=vendor.example",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        purged = json.loads(urllib.request.urlopen(forget, timeout=5).read())
        state = json.loads(urllib.request.urlopen(f"{base_url}/dashboard.json", timeout=5).read())

        assert purged["status"] == "forgotten"
        assert purged["events_removed"] == 1
        assert state["raw_events"] == []
        raw_record = next(
            record for record in state["audit_records"]
            if record["tool"] == "sensor_ingest_raw"
        )
        assert raw_record["details"]["raw_event"]["tombstoned"] is True
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_dashboard_html_contains_management_sections():
    state = {
        "sensor_control": {"paused_scopes": ["macos"], "actions": {}},
        "redis": {"ping": "PONG"},
        "raw_events": [],
        "hermes_outputs": [],
        "audit_records": [],
    }

    html = render_dashboard_html(state)

    assert "Pause Sensor Ingest" in html
    assert "Forget Scope" in html
    assert "Export Session Brief" in html
    assert "Sanitized Hermes Outputs" in html
    assert "Raw Local Events" in html
