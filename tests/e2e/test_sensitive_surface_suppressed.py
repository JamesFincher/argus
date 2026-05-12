from dataclasses import dataclass, field

from argus_services.event_gateway import EventGateway
from argus_services.events import make_event
from argus_services.mcp import LocalMCPServer
from argus_services.perception import PerceptionWorker
from argus_services.policy import RedactionPolicy


@dataclass
class RecordingPublisher:
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def publish(self, stream, event):
        self.calls.append((stream, event.event_id, event.sensitivity))
        return "1700000001000-0"


def test_sensitive_surface_is_suppressed_before_agent_context_or_raw_fetch():
    policy = RedactionPolicy(approval_token="approve")
    publisher = RecordingPublisher()
    gateway = EventGateway(policy=policy, publisher=publisher)
    source_event = make_event(
        "activity.browser_page",
        {
            "domain": "accounts.google.com",
            "title": "Sign in",
            "text": "verification code 123456 and password reset token sk-abcdefghijklmnopqrstuvwxyz",
        },
        source_platform="macos",
        sensor_id="argus-sensor-mac",
    )

    gateway_result = gateway.ingest(source_event)
    stored_source = gateway.store.get(source_event.event_id)
    perception_output = PerceptionWorker(policy=policy).process(source_event)
    if perception_output.blocked_event is not None:
        gateway.ingest(perception_output.blocked_event)

    server = LocalMCPServer(store=gateway.store, policy=policy)
    context = server.call_tool("sensor_get_recent_notes", actor="hermes-e2e")
    blocked_raw = server.call_tool(
        "sensor_expand_event",
        event_id=source_event.event_id,
        raw_mode="full",
        approval_token="approve",
        actor="hermes-e2e",
    )

    assert gateway_result.stream == "stream:policy:blocked"
    assert stored_source is not None
    assert stored_source.sensitivity == "blocked"
    assert perception_output.derived_note is None
    assert perception_output.blocked_event is not None
    assert publisher.calls[0] == ("stream:policy:blocked", source_event.event_id, "blocked")
    assert publisher.calls[1][0] == "stream:policy:blocked"

    assert context["ok"] is True
    assert "verification code 123456" not in context["context"]
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in context["context"]
    assert blocked_raw["ok"] is False
    assert blocked_raw["sensitivity"] == "blocked"
    assert "blocked domain surface" in blocked_raw["error"]

    audit = server.audit_log.records
    assert audit[0].tool == "sensor_get_recent_notes"
    assert audit[0].allowed is True
    assert audit[1].tool == "sensor_expand_event"
    assert audit[1].scope == "full"
    assert audit[1].allowed is False
