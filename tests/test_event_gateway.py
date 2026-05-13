from dataclasses import dataclass, field

from argus_services.event_gateway import EventGateway, run
from argus_services.events import make_event
from argus_services.streams import (
    POLICY_BLOCKED_STREAM,
    RAW_STREAMS,
    SYSTEM_METRICS_STREAM,
    stream_for_event,
    xadd_fields,
)


@dataclass
class RecordingPublisher:
    calls: list[tuple[str, str]] = field(default_factory=list)

    def publish(self, stream, event):
        self.calls.append((stream, event.event_id))
        return "1700000000000-0"


def test_stream_routing_matches_spec_stream_names():
    assert stream_for_event(make_event("activity.frontmost_window", {}, source_platform="macos")) == RAW_STREAMS["macos"]
    assert stream_for_event(make_event("system.permission_state", {}, source_platform="macos")) == SYSTEM_METRICS_STREAM
    blocked = make_event("activity.browser_page", {"domain": "accounts.google.com"}, sensitivity="blocked")
    assert stream_for_event(blocked) == POLICY_BLOCKED_STREAM


def test_xadd_fields_preserve_contract_values():
    event = make_event(
        "activity.frontmost_window",
        {"title": "Safari", "summary": "Frontmost app: Safari"},
        source_platform="macos",
        sensor_id="argus-sensor-mac",
    )

    fields = xadd_fields(event)

    assert fields["event_id"] == event.event_id
    assert fields["event_type"] == "activity.frontmost_window"
    assert fields["schema_version"] == "2026-05-11"
    assert fields["source_device_id"] == event.source_device_id
    assert fields["source_platform"] == "macos"
    assert fields["sensor_id"] == "argus-sensor-mac"
    assert fields["sensor_version"] == "0.1.0"
    assert fields["ingested_at"] == event.ingested_at
    assert fields["session_id"] == ""
    assert fields["payload_json"] == '{"summary":"Frontmost app: Safari","title":"Safari"}'


def test_gateway_ingests_event_and_publishes_to_raw_stream():
    publisher = RecordingPublisher()
    gateway = EventGateway(publisher=publisher)
    event = make_event("activity.frontmost_window", {"title": "Safari"}, source_platform="macos")

    result = gateway.ingest(event)

    assert result.event_id == event.event_id
    assert result.stream == "stream:raw:macos"
    assert result.redis_id == "1700000000000-0"
    assert publisher.calls == [("stream:raw:macos", event.event_id)]
    assert gateway.store.get(event.event_id) is event


def test_gateway_accepts_canonical_payload_from_swift_sensor():
    publisher = RecordingPublisher()
    gateway = EventGateway(publisher=publisher)
    payload = {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "event_type": "activity.focused_field",
        "schema_version": "2026-05-11",
        "source_device_id": "macbook-test",
        "source_platform": "macos",
        "sensor_id": "argus-sensor-mac",
        "sensor_version": "0.1.0",
        "observed_at": "1970-01-01T00:20:34.000Z",
        "ingested_at": "1970-01-01T00:20:35.000Z",
        "session_id": None,
        "dedupe_key": None,
        "sensitivity": "high",
        "raw_scope": "ephemeral",
        "payload": {
            "role": "AXTextField",
            "has_value": True,
            "summary": "Focused field: value=[REDACTED_API_KEY]",
            "sensor_source": "accessibility.focused_field",
            "swift_event_kind": "focused_field",
            "raw_reference": "local-ax-focused-field",
        },
        "redactions": [
            {"kind": "api_key", "path": "$.summary", "replacement": "[REDACTED]"},
        ],
        "relationships": [],
        "tags": ["macos", "accessibility.focused_field", "focused_field"],
    }

    result = gateway.ingest_dict(payload)
    stored = gateway.store.get(payload["event_id"])

    assert result.stream == "stream:raw:macos"
    assert result.event_id == payload["event_id"]
    assert stored is not None
    assert stored.event_type == "activity.focused_field"
    assert stored.payload["summary"] == "Focused field: value=[REDACTED_API_KEY]"
    assert stored.redactions[0].kind == "api_key"
    assert stored.dedupe_key.startswith("sha256:")
    assert publisher.calls == [("stream:raw:macos", payload["event_id"])]


def test_gateway_routes_blocked_surfaces_to_policy_stream():
    publisher = RecordingPublisher()
    gateway = EventGateway(publisher=publisher)
    event = make_event(
        "activity.browser_page",
        {"domain": "accounts.google.com", "title": "Sign in"},
        source_platform="macos",
    )

    result = gateway.ingest(event)
    stored = gateway.store.get(event.event_id)

    assert result.stream == "stream:policy:blocked"
    assert result.sensitivity == "blocked"
    assert stored is not None
    assert stored.sensitivity == "blocked"
    assert "policy_blocked_surface" in stored.tags


def test_gateway_refuses_non_loopback_bind():
    try:
        run(host="0.0.0.0", port=0)
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback bind should be rejected")
