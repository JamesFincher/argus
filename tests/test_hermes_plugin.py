from argus_services.events import make_event
from argus_services.hermes_plugin import (
    ENTRY_POINT_GROUP,
    ENTRY_POINT_NAME,
    HermesPluginConfig,
    discover_plugins,
    load_plugin,
    plugin_metadata,
    register,
)
from argus_services.policy import RedactionPolicy
from argus_services.sqlite_store import SQLiteAuditLog, SQLiteTimelineStore
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


def test_hermes_pre_llm_context_records_audit_actor():
    ctx = FakeHermesContext()
    result = register(ctx)

    ctx.hooks["pre_llm_call"](session_id="session-123")

    audit = result["server"].audit_log.records
    assert len(audit) == 1
    assert audit[0].actor == "session-123"
    assert audit[0].tool == "sensor_get_recent_notes"
    assert audit[0].scope == "recent_notes"


def test_hermes_pre_tool_blocks_sensitive_non_sensor_arguments_and_unknown_raw_event():
    ctx = FakeHermesContext()
    result = register(ctx, approval_token="ok")

    blocked_args = ctx.hooks["pre_tool_call"](
        tool_name="shell",
        arguments={"command": "export TOKEN=Bearer abcdefghijklmnopqrstuvwxyz"},
    )
    safe_args = ctx.hooks["pre_tool_call"](
        tool_name="shell",
        arguments={"command": "pwd"},
    )
    unknown_raw = ctx.hooks["pre_tool_call"](
        tool_name="sensor_expand_event",
        arguments={"event_id": "missing", "raw_mode": "full", "approval_token": "ok"},
    )

    assert result["policy"].approval_token == "ok"
    assert blocked_args == {
        "block": True,
        "reason": "tool arguments contain raw sensitive material",
    }
    assert safe_args is None
    assert unknown_raw == {
        "block": True,
        "reason": "raw event expansion requires known event_id",
    }


def test_hermes_plugin_entry_point_is_packaged_and_loadable():
    descriptors = discover_plugins()
    argus_descriptor = next(
        descriptor for descriptor in descriptors if descriptor.name == ENTRY_POINT_NAME
    )

    assert argus_descriptor.group == ENTRY_POINT_GROUP
    assert argus_descriptor.value == "argus_services.hermes_plugin:register"
    assert argus_descriptor.to_dict() == {
        "name": ENTRY_POINT_NAME,
        "group": ENTRY_POINT_GROUP,
        "value": "argus_services.hermes_plugin:register",
    }
    assert load_plugin() is register


def test_hermes_load_plugin_reports_missing_entry_point():
    try:
        load_plugin(name="missing-argus-plugin")
    except LookupError as exc:
        assert "hermes.plugins:missing-argus-plugin" in str(exc)
    else:
        raise AssertionError("missing plugin entry point should raise")


def test_hermes_plugin_metadata_exposes_runtime_config(monkeypatch, tmp_path):
    db_path = tmp_path / "timeline.db"
    lancedb_path = tmp_path / "notes.lancedb"
    monkeypatch.setenv("ARGUS_TIMELINE_DB_PATH", str(db_path))
    monkeypatch.setenv("ARGUS_LANCEDB_PATH", str(lancedb_path))

    config = HermesPluginConfig.from_env(approval_token="approve")
    metadata = plugin_metadata(config)

    assert metadata["name"] == "argus"
    assert metadata["entry_point_group"] == "hermes.plugins"
    assert metadata["entry_point"] == "argus_services.hermes_plugin:register"
    assert metadata["env"] == {
        "ARGUS_TIMELINE_DB_PATH": str(db_path),
        "ARGUS_LANCEDB_PATH": str(lancedb_path),
        "ARGUS_APPROVAL_TOKEN": "approve",
    }


def test_hermes_register_uses_env_backed_persistent_store_and_audit(monkeypatch, tmp_path):
    db_path = tmp_path / "timeline.db"
    monkeypatch.setenv("ARGUS_TIMELINE_DB_PATH", str(db_path))
    store = SQLiteTimelineStore(db_path)
    try:
        store.add(
            make_event(
                "perception.note",
                {"summary": "Call Alice at alice@example.com about launch review"},
            )
        )
    finally:
        store.close()

    ctx = FakeHermesContext()
    result = register(ctx)
    try:
        context = ctx.hooks["pre_llm_call"](session_id="hermes-session-42")

        assert "no local sensor notes available" not in context["context"]
        assert "launch review" in context["context"]
        assert "alice@example.com" not in context["context"]
        assert "[REDACTED_EMAIL]" in context["context"]

        audit = SQLiteAuditLog(db_path)
        try:
            records = audit.recent(limit=1)
        finally:
            audit.close()

        assert records[0].actor == "hermes-session-42"
        assert records[0].tool == "sensor_get_recent_notes"
        assert records[0].event_count == 1
        assert "launch review" in records[0].details["sanitized_context"]
    finally:
        for resource_name in ("store", "audit_log"):
            resource = getattr(result["server"], resource_name, None)
            if hasattr(resource, "close"):
                resource.close()
