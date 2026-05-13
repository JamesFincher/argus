"""Minimal MCP-style local tool registry for Hermes sensor access."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .audit import AuditRecord, InMemoryAuditLog
from .events import EventEnvelope
from .policy import RedactionPolicy
from .store import InMemoryEventStore

ToolCallable = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: ToolCallable


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, name: str, description: str, handler: ToolCallable) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = Tool(name=name, description=description, handler=handler)

    def list_tools(self) -> list[dict[str, str]]:
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self._tools.values()
        ]

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name].handler(**kwargs)


class LocalMCPServer:
    """Loopback-only in-process stand-in for Hermes MCP tool discovery."""

    def __init__(
        self,
        store: InMemoryEventStore | None = None,
        policy: RedactionPolicy | None = None,
        audit_log: InMemoryAuditLog | None = None,
    ) -> None:
        self.store = store or InMemoryEventStore()
        self.policy = policy or RedactionPolicy()
        self.audit_log = audit_log or InMemoryAuditLog()
        self.registry = ToolRegistry()
        self._register_default_tools()

    def add_event(self, event: EventEnvelope) -> EventEnvelope:
        return self.store.add(event)

    def list_tools(self) -> list[dict[str, str]]:
        return self.registry.list_tools()

    def call_tool(self, name: str, **kwargs: Any) -> dict[str, Any]:
        return self.registry.call(name, **kwargs)

    def _register_default_tools(self) -> None:
        self.registry.register(
            "sensor_get_recent_notes",
            "Return a concise redacted ambient summary from local Argus events.",
            self.sensor_get_recent_notes,
        )
        self.registry.register(
            "sensor_expand_event",
            "Fetch a redacted event or gated raw event by event_id.",
            self.sensor_expand_event,
        )
        self.registry.register(
            "sensor_timeline_search",
            "Search local Argus timeline summaries without exposing raw payloads.",
            self.sensor_timeline_search,
        )
        self.registry.register(
            "sensor_pause_scope",
            "Record an operator request to pause a local sensing scope.",
            self.sensor_pause_scope,
        )
        self.registry.register(
            "sensor_forget_scope",
            "Record an operator request to forget local data for a scope.",
            self.sensor_forget_scope,
        )
        self.registry.register(
            "sensor_export_session_brief",
            "Export a concise redacted session brief from recent local events.",
            self.sensor_export_session_brief,
        )

    def sensor_get_recent_notes(self, limit: int = 5, actor: str = "hermes") -> dict[str, Any]:
        events = self.store.recent(limit=limit)
        self.audit_log.record(
            AuditRecord(
                actor=actor,
                tool="sensor_get_recent_notes",
                scope="recent_notes",
                event_count=len(events),
                redactions_applied=[],
                allowed=True,
                reason="redacted summary retrieval",
            )
        )
        return {
            "ok": True,
            "context": self.store.ambient_summary(policy=self.policy, limit=limit),
        }

    def sensor_expand_event(
        self,
        event_id: str,
        raw_mode: str = "redacted",
        approval_token: str | None = None,
        actor: str = "hermes",
    ) -> dict[str, Any]:
        event = self.store.get(event_id)
        if event is None:
            self.audit_log.record(
                AuditRecord(
                    actor=actor,
                    tool="sensor_expand_event",
                    scope=raw_mode,
                    event_count=0,
                    redactions_applied=[],
                    allowed=False,
                    reason="event not found",
                )
            )
            return {"ok": False, "error": "event not found", "event_id": event_id}

        if raw_mode == "full":
            decision = self.policy.evaluate_raw_access(
                event,
                approval_token=approval_token,
                raw_mode=raw_mode,
            )
            if not decision.allowed:
                self.audit_log.record(
                    AuditRecord(
                        actor=actor,
                        tool="sensor_expand_event",
                        scope="full",
                        event_count=1,
                        redactions_applied=[],
                        allowed=False,
                        reason=decision.reason,
                    )
                )
                return {
                    "ok": False,
                    "error": decision.reason,
                    "sensitivity": decision.sensitivity,
                    "event_id": event_id,
                }
            self.audit_log.record(
                AuditRecord(
                    actor=actor,
                    tool="sensor_expand_event",
                    scope="full",
                    event_count=1,
                    redactions_applied=[],
                    allowed=True,
                    reason=decision.reason,
                )
            )
            return {"ok": True, "event": event.to_dict(), "raw_mode": "full"}

        redacted = self.policy.redact_event(event)
        self.audit_log.record(
            AuditRecord(
                actor=actor,
                tool="sensor_expand_event",
                scope="redacted",
                event_count=1,
                redactions_applied=[redaction.kind for redaction in redacted.redactions],
                allowed=True,
                reason="redacted event expansion",
            )
        )
        return {
            "ok": True,
            "event": redacted.to_dict(),
            "raw_mode": "redacted",
        }

    def sensor_timeline_search(
        self,
        query: str,
        limit: int = 10,
        actor: str = "hermes",
    ) -> dict[str, Any]:
        query_lower = query.lower()
        matches = []
        if hasattr(self.store, "search"):
            candidate_events = self.store.search(query, limit=limit)
        else:
            candidate_events = self.store.recent(limit=max(limit * 3, limit))

        for event in candidate_events:
            redacted = self.policy.redact_event(event)
            text = self.store.summary_for(redacted)
            if hasattr(self.store, "search") or query_lower in text.lower():
                matches.append(
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "summary": text,
                        "sensitivity": redacted.sensitivity,
                    }
                )
            if len(matches) >= limit:
                break

        self.audit_log.record(
            AuditRecord(
                actor=actor,
                tool="sensor_timeline_search",
                scope=query,
                event_count=len(matches),
                redactions_applied=[],
                allowed=True,
                reason="redacted timeline search",
            )
        )
        return {"ok": True, "matches": matches}

    def sensor_pause_scope(self, scope: str, actor: str = "hermes") -> dict[str, Any]:
        self.audit_log.record(
            AuditRecord(
                actor=actor,
                tool="sensor_pause_scope",
                scope=scope,
                event_count=0,
                redactions_applied=[],
                allowed=True,
                reason="pause scope requested",
            )
        )
        return {"ok": True, "scope": scope, "status": "pause_requested"}

    def sensor_forget_scope(self, scope: str, actor: str = "hermes") -> dict[str, Any]:
        self.audit_log.record(
            AuditRecord(
                actor=actor,
                tool="sensor_forget_scope",
                scope=scope,
                event_count=0,
                redactions_applied=[],
                allowed=True,
                reason="forget scope requested",
            )
        )
        return {"ok": True, "scope": scope, "status": "forget_requested"}

    def sensor_export_session_brief(
        self,
        limit: int = 20,
        actor: str = "hermes",
    ) -> dict[str, Any]:
        notes = self.store.ambient_summary(policy=self.policy, limit=limit)
        self.audit_log.record(
            AuditRecord(
                actor=actor,
                tool="sensor_export_session_brief",
                scope="session_brief",
                event_count=len(self.store.recent(limit=limit)),
                redactions_applied=[],
                allowed=True,
                reason="redacted session brief export",
            )
        )
        return {"ok": True, "brief": notes}
