import io
import json
import struct
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from argus_services import native_messaging
from argus_services.native_messaging import (
    MAX_FRAME_BYTES,
    NativeMessagingError,
    _read_json_response,
    handle_message,
    main,
    page_context_to_event,
    post_event,
    read_frame,
    run,
    validate_loopback_gateway_url,
    write_frame,
)


def framed(message: dict) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def unframe(data: bytes) -> dict:
    length = struct.unpack("<I", data[:4])[0]
    return json.loads(data[4 : 4 + length])


def test_native_messaging_reads_and_writes_little_endian_json_frames():
    stream = io.BytesIO(framed({"type": "page_context", "href": "https://example.com"}))

    assert read_frame(stream) == {"type": "page_context", "href": "https://example.com"}
    assert read_frame(stream) is None

    output = io.BytesIO()
    write_frame(output, {"ok": True, "event_id": "evt"})

    assert unframe(output.getvalue()) == {"ok": True, "event_id": "evt"}


def test_native_messaging_rejects_malformed_frames():
    with pytest.raises(NativeMessagingError, match="incomplete.*header"):
        read_frame(io.BytesIO(b"\x01"))

    with pytest.raises(NativeMessagingError, match="frame too large"):
        read_frame(io.BytesIO(struct.pack("<I", MAX_FRAME_BYTES + 1)))

    with pytest.raises(NativeMessagingError, match="incomplete.*body"):
        read_frame(io.BytesIO(struct.pack("<I", 5) + b"he"))

    with pytest.raises(NativeMessagingError, match="invalid native messaging JSON"):
        read_frame(io.BytesIO(struct.pack("<I", 1) + b"{"))

    with pytest.raises(NativeMessagingError, match="payload must be a JSON object"):
        read_frame(io.BytesIO(framed([])))


def test_page_context_payload_is_converted_to_canonical_browser_event(monkeypatch):
    monkeypatch.setenv("ARGUS_SOURCE_DEVICE_ID", "macbook-test")

    event = page_context_to_event(
        {
            "type": "page_context",
            "href": "https://vendor.example.com/pricing?plan=annual",
            "domain": "vendor.example.com",
            "title": "Pricing and plans",
            "selection": "Annual plan",
            "referrer": "https://google.com/search?q=vendor",
            "observed_at": "2026-05-13T12:00:00Z",
        }
    )

    assert event.event_type == "activity.browser_page"
    assert event.source_device_id == "macbook-test"
    assert event.source_platform == "macos"
    assert event.sensor_id == "safari_webext"
    assert event.raw_scope == "ephemeral"
    assert event.observed_at == "2026-05-13T12:00:00Z"
    assert event.payload == {
        "browser": "Safari",
        "tab_id": None,
        "url": "https://vendor.example.com/pricing?plan=annual",
        "domain": "vendor.example.com",
        "title": "Pricing and plans",
        "selection_text": "Annual plan",
        "referrer_domain": "google.com",
    }
    assert "page_context" in event.tags


def test_page_context_validation_rejects_missing_or_non_http_href():
    with pytest.raises(NativeMessagingError, match="href is required"):
        page_context_to_event({"type": "page_context"})

    with pytest.raises(NativeMessagingError, match="http\\(s\\) URL"):
        page_context_to_event({"type": "page_context", "href": "file:///tmp/report.html"})


def test_page_context_payload_preserves_non_string_browser_values():
    event = page_context_to_event(
        {
            "type": "page_context",
            "href": "https://vendor.example.com/pricing",
            "title": 123,
            "tab_id": 456,
        }
    )

    assert event.payload["title"] == "123"
    assert event.payload["tab_id"] == "456"


def test_gateway_url_validation_requires_loopback_events_endpoint():
    assert validate_loopback_gateway_url("http://127.0.0.1:8765/events") == "http://127.0.0.1:8765/events"
    assert validate_loopback_gateway_url("http://localhost:8765/events") == "http://localhost:8765/events"

    for url in [
        "https://127.0.0.1:8765/events",
        "http://example.com:8765/events",
        "http://127.0.0.1:8765/metrics",
        "http://127.0.0.1/events",
        "http://127.0.0.1:8765/events?x=1",
    ]:
        try:
            validate_loopback_gateway_url(url)
        except NativeMessagingError:
            pass
        else:
            raise AssertionError(f"{url} should have been rejected")


@dataclass
class GatewayCapture:
    requests: list[dict] = field(default_factory=list)


def test_post_event_sends_canonical_envelope_to_loopback_gateway():
    capture = GatewayCapture()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            capture.requests.append(json.loads(self.rfile.read(length)))
            body = json.dumps({"ok": True, "event_id": capture.requests[-1]["event_id"]}).encode("utf-8")
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        event = page_context_to_event(
            {
                "type": "page_context",
                "href": "https://vendor.example.com/pricing",
                "title": "Pricing",
            }
        )
        result = post_event(event, f"http://127.0.0.1:{server.server_address[1]}/events")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert result.status_code == 202
    assert result.body["ok"] is True
    assert capture.requests[0]["event_type"] == "activity.browser_page"
    assert capture.requests[0]["payload"]["url"] == "https://vendor.example.com/pricing"


def test_post_event_reports_gateway_http_rejections():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({"error": "schema rejected"}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        event = page_context_to_event(
            {"type": "page_context", "href": "https://vendor.example.com/pricing"}
        )
        with pytest.raises(NativeMessagingError, match="schema rejected"):
            post_event(event, f"http://127.0.0.1:{server.server_address[1]}/events")
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_post_event_reports_gateway_unavailability(monkeypatch):
    def raise_url_error(request, timeout):
        raise native_messaging.urllib.error.URLError("down")

    monkeypatch.setattr(native_messaging.urllib.request, "urlopen", raise_url_error)
    event = page_context_to_event(
        {"type": "page_context", "href": "https://vendor.example.com/pricing"}
    )

    with pytest.raises(NativeMessagingError, match="gateway unavailable"):
        post_event(event, "http://127.0.0.1:8765/events")


def test_handle_message_returns_success_or_error_response(monkeypatch):
    def fake_post(event, gateway_url):
        return type("Result", (), {"status_code": 202, "body": {"ok": True, "stream": "stream:raw:macos"}})()

    monkeypatch.setattr("argus_services.native_messaging.post_event", fake_post)
    success = handle_message(
        {
            "type": "page_context",
            "href": "https://vendor.example.com/pricing",
            "title": "Pricing",
        }
    )

    assert success["ok"] is True
    assert success["event_type"] == "activity.browser_page"
    assert success["gateway"]["stream"] == "stream:raw:macos"

    error = handle_message({"type": "unknown"})
    assert error["ok"] is False
    assert "unsupported native message type" in error["error"]


def test_run_processes_frames_until_eof(monkeypatch):
    def fake_handle_message(message, gateway_url):
        return {"ok": True, "href": message["href"], "gateway_url": gateway_url}

    monkeypatch.setattr(native_messaging, "handle_message", fake_handle_message)
    input_stream = io.BytesIO(
        framed({"type": "page_context", "href": "https://vendor.example.com/pricing"})
    )
    output_stream = io.BytesIO()

    exit_code = run(
        input_stream,
        output_stream,
        gateway_url="http://127.0.0.1:8765/events",
    )

    assert exit_code == 0
    assert unframe(output_stream.getvalue()) == {
        "ok": True,
        "href": "https://vendor.example.com/pricing",
        "gateway_url": "http://127.0.0.1:8765/events",
    }


def test_main_writes_framed_error_when_startup_fails(monkeypatch):
    class FakeStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

    fake_stdout = FakeStdout()

    def raise_native_error():
        raise NativeMessagingError("bad gateway")

    monkeypatch.setattr(native_messaging, "run", raise_native_error)
    monkeypatch.setattr(native_messaging.sys, "stdout", fake_stdout)

    assert main() == 1
    assert unframe(fake_stdout.buffer.getvalue()) == {"ok": False, "error": "bad gateway"}


def test_read_json_response_handles_empty_invalid_and_non_object_bodies():
    assert _read_json_response(b"") == {}
    assert _read_json_response(b"{") == {"raw": "{"}
    assert _read_json_response(b"[1, 2]") == {"value": [1, 2]}
