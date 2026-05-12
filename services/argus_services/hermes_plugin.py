"""Hermes plugin hooks for Argus ambient context and tool policy."""

from __future__ import annotations

from typing import Any

from .audit import InMemoryAuditLog
from .mcp import LocalMCPServer
from .policy import RedactionPolicy
from .store import InMemoryEventStore


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

    effective_policy = policy or RedactionPolicy(approval_token=approval_token)
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
        if tool_name != "sensor_expand_event":
            scan = effective_policy.redact_value(arguments)
            if scan.sensitivity in {"high", "blocked"}:
                return {
                    "block": True,
                    "reason": "tool arguments contain raw sensitive material",
                }
            return None

        if arguments.get("raw_mode") == "full":
            event_id = arguments.get("event_id")
            event = server.store.get(event_id) if isinstance(event_id, str) else None
            if event is None:
                return {"block": True, "reason": "raw event expansion requires known event_id"}
            decision = effective_policy.evaluate_raw_access(
                event,
                approval_token=arguments.get("approval_token"),
                raw_mode="full",
            )
            if not decision.allowed:
                return {"block": True, "reason": decision.reason}
        return None

    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    return {"server": server, "policy": effective_policy}
