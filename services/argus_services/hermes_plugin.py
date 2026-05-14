"""Hermes plugin hooks for Argus ambient context and tool policy."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import os
from typing import Any

from .audit import InMemoryAuditLog
from .mcp import LocalMCPServer
from .mcp_stdio import local_mcp_server_from_env
from .policy import RedactionPolicy
from .store import InMemoryEventStore

ENTRY_POINT_GROUP = "hermes_agent.plugins"
LEGACY_ENTRY_POINT_GROUP = "hermes.plugins"
ENTRY_POINT_GROUPS = (ENTRY_POINT_GROUP, LEGACY_ENTRY_POINT_GROUP)
ENTRY_POINT_NAME = "argus"
ENTRY_POINT_VALUE = "argus_services.hermes_plugin:register"


@dataclass(frozen=True)
class HermesPluginConfig:
    """Runtime configuration advertised to Hermes plugin loaders."""

    timeline_db_path: str | None = None
    lancedb_path: str | None = None
    approval_token: str | None = None

    @classmethod
    def from_env(cls, *, approval_token: str | None = None) -> "HermesPluginConfig":
        return cls(
            timeline_db_path=os.environ.get("ARGUS_TIMELINE_DB_PATH"),
            lancedb_path=os.environ.get("ARGUS_LANCEDB_PATH"),
            approval_token=approval_token or os.environ.get("ARGUS_APPROVAL_TOKEN"),
        )

    def to_hermes_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if self.timeline_db_path:
            env["ARGUS_TIMELINE_DB_PATH"] = self.timeline_db_path
        if self.lancedb_path:
            env["ARGUS_LANCEDB_PATH"] = self.lancedb_path
        if self.approval_token:
            env["ARGUS_APPROVAL_TOKEN"] = self.approval_token
        return env


@dataclass(frozen=True)
class HermesPluginDescriptor:
    name: str
    group: str
    value: str

    @classmethod
    def from_entry_point(cls, entry_point: metadata.EntryPoint) -> "HermesPluginDescriptor":
        return cls(
            name=entry_point.name,
            group=entry_point.group,
            value=entry_point.value,
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "group": self.group, "value": self.value}


def discover_plugins(group: str = ENTRY_POINT_GROUP) -> list[HermesPluginDescriptor]:
    """Discover installed Hermes plugin entry points without importing them."""

    entry_points = metadata.entry_points()
    selected = entry_points.select(group=group)
    return [HermesPluginDescriptor.from_entry_point(entry_point) for entry_point in selected]


def load_plugin(
    name: str = ENTRY_POINT_NAME,
    *,
    group: str | None = None,
) -> Any:
    """Load a Hermes plugin hook registrar from package entry point metadata."""

    entry_points = metadata.entry_points()
    groups = (group,) if group is not None else ENTRY_POINT_GROUPS
    for candidate_group in groups:
        matches = [
            entry_point
            for entry_point in entry_points.select(group=candidate_group, name=name)
        ]
        if matches:
            return matches[0].load()
    searched = ", ".join(f"{candidate_group}:{name}" for candidate_group in groups)
    raise LookupError(f"Hermes plugin entry point not found: {searched}")


def plugin_metadata(config: HermesPluginConfig | None = None) -> dict[str, Any]:
    """Return the package-level Hermes plugin descriptor and runtime config."""

    effective_config = config or HermesPluginConfig.from_env()
    return {
        "name": ENTRY_POINT_NAME,
        "entry_point_group": ENTRY_POINT_GROUP,
        "entry_point_groups": list(ENTRY_POINT_GROUPS),
        "entry_point": ENTRY_POINT_VALUE,
        "env": effective_config.to_hermes_env(),
    }


def _block(message: str) -> dict[str, str]:
    return {"action": "block", "message": message}


def _is_sensor_expand_tool(tool_name: str | None) -> bool:
    if tool_name == "sensor_expand_event":
        return True
    return bool(tool_name and tool_name.endswith("_sensor_expand_event"))


def register(
    ctx: Any,
    *,
    store: InMemoryEventStore | None = None,
    policy: RedactionPolicy | None = None,
    audit_log: InMemoryAuditLog | None = None,
    approval_token: str | None = None,
) -> dict[str, Any]:
    """Register Hermes hooks.

    The ctx object only needs the Hermes-style ``register_hook(name, fn)`` method,
    which keeps this skeleton testable without importing Hermes.
    """

    config = HermesPluginConfig.from_env(approval_token=approval_token)
    effective_policy = policy or RedactionPolicy(approval_token=config.approval_token)
    if store is None and audit_log is None:
        env_server = local_mcp_server_from_env()
        server = LocalMCPServer(
            store=env_server.store,
            policy=effective_policy,
            audit_log=env_server.audit_log,
            note_index=env_server.note_index,
            graph=env_server.graph,
        )
    else:
        server = LocalMCPServer(
            store=store or InMemoryEventStore(),
            policy=effective_policy,
            audit_log=audit_log,
        )

    def pre_llm_call(session_id: str | None = None, **_: Any) -> dict[str, str]:
        return server.call_tool("sensor_get_recent_notes", limit=5, actor=session_id or "hermes")

    def pre_tool_call(
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any] | None:
        arguments = arguments or {}
        if not _is_sensor_expand_tool(tool_name):
            scan = effective_policy.redact_value(arguments)
            if scan.sensitivity in {"high", "blocked"}:
                return _block("tool arguments contain raw sensitive material")
            return None

        if arguments.get("raw_mode") == "full":
            event_id = arguments.get("event_id")
            event = server.store.get(event_id) if isinstance(event_id, str) else None
            if event is None:
                return _block("raw event expansion requires known event_id")
            decision = effective_policy.evaluate_raw_access(
                event,
                approval_token=arguments.get("approval_token"),
                raw_mode="full",
            )
            if not decision.allowed:
                return _block(decision.reason)
        return None

    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    return {
        "server": server,
        "policy": effective_policy,
        "config": config,
        "metadata": plugin_metadata(config),
    }
