from argus_services.events import make_event
from argus_services.hermes_plugin import register
from argus_services.policy import RedactionPolicy
from argus_services.store import InMemoryEventStore


class FakeHermesContext:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, handler):
        self.hooks[name] = handler


def test_hermes_hook_registration_and_behavior():
    ctx = FakeHermesContext()
    store = InMemoryEventStore()
    event = store.add(
        make_event(
            "perception.note",
            {"summary": "Reviewed pricing with sam@example.com"},
        )
    )

    result = register(ctx, store=store, policy=RedactionPolicy(approval_token="ok"))

    assert "pre_llm_call" in ctx.hooks
    assert "pre_tool_call" in ctx.hooks
    assert "server" in result

    context = ctx.hooks["pre_llm_call"]()
    assert "sam@example.com" not in context["context"]
    assert "[REDACTED_EMAIL]" in context["context"]

    blocked = ctx.hooks["pre_tool_call"](
        tool_name="sensor_expand_event",
        arguments={"event_id": event.event_id, "raw_mode": "full"},
    )
    allowed = ctx.hooks["pre_tool_call"](
        tool_name="sensor_expand_event",
        arguments={"event_id": event.event_id, "raw_mode": "full", "approval_token": "ok"},
    )

    assert blocked["block"] is True
    assert allowed is None
