"""Loopback-only Argus event gateway.

The gateway accepts normalized local sensor envelopes, applies deterministic
policy metadata, stores a local copy for MCP/Hermes reads, and publishes the
event to the Redis Streams fabric from the spec.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

from .audit import AuditRecord, InMemoryAuditLog
from .dashboard import dashboard_state, render_dashboard_html
from .events import EventEnvelope
from .policy import RedactionPolicy
from .purge import ScopePurgeResult
from .sqlite_store import SQLiteAuditLog, SQLiteTimelineStore
from .store import InMemoryEventStore
from .streams import RedisStreamPublisher, StreamPublisher, stream_for_event


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass
class IngestResult:
    event_id: str
    stream: str
    redis_id: str
    sensitivity: str

    def to_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "stream": self.stream,
            "redis_id": self.redis_id,
            "sensitivity": self.sensitivity,
        }


class PausedScopeError(RuntimeError):
    def __init__(self, scope: str) -> None:
        super().__init__(f"sensor ingest paused for scope: {scope}")
        self.scope = scope


class EventGateway:
    def __init__(
        self,
        *,
        store: InMemoryEventStore | None = None,
        policy: RedactionPolicy | None = None,
        publisher: StreamPublisher | None = None,
        audit_log: InMemoryAuditLog | SQLiteAuditLog | None = None,
    ) -> None:
        self.store = store or InMemoryEventStore()
        self.policy = policy or RedactionPolicy()
        self.publisher = publisher or RedisStreamPublisher()
        self.audit_log = audit_log or InMemoryAuditLog()
        self.paused_scopes: set[str] = set()

    def ingest_dict(self, data: dict[str, Any]) -> IngestResult:
        event = EventEnvelope.from_dict(data)
        return self.ingest(event)

    def ingest(self, event: EventEnvelope) -> IngestResult:
        if self.is_paused(event.source_platform):
            raise PausedScopeError(event.source_platform)

        policy_surface = self.policy.evaluate_surface(event)
        event_dict = event.to_dict()
        if not policy_surface.allowed:
            event_dict["sensitivity"] = "blocked"
            event_dict["tags"] = [*event.tags, "policy_blocked_surface"]
            event = EventEnvelope.from_dict(event_dict)

        stream = stream_for_event(event)
        self.store.add(event)
        redis_id = self.publisher.publish(stream, event)
        self.audit_log.record(
            AuditRecord(
                actor="argus-event-gateway",
                tool="sensor_ingest_raw",
                scope=stream,
                event_count=1,
                redactions_applied=[redaction.kind for redaction in event.redactions],
                allowed=True,
                reason="raw event stored locally and published to redis",
                details={
                    "redis_id": redis_id,
                    "raw_event": event.to_dict(),
                    "raw_data_local_only": True,
                },
            )
        )
        return IngestResult(
            event_id=event.event_id,
            stream=stream,
            redis_id=redis_id,
            sensitivity=event.sensitivity,
        )

    def pause_scope(self, scope: str = "macos") -> None:
        self.paused_scopes.add(scope)
        self.audit_log.record(
            AuditRecord(
                actor="argus-dashboard",
                tool="sensor_pause_scope",
                scope=scope,
                event_count=0,
                redactions_applied=[],
                allowed=True,
                reason="operator paused sensor ingest",
                details={"requested_scope": scope},
            )
        )

    def resume_scope(self, scope: str = "macos") -> None:
        self.paused_scopes.discard(scope)
        self.audit_log.record(
            AuditRecord(
                actor="argus-dashboard",
                tool="sensor_resume_scope",
                scope=scope,
                event_count=0,
                redactions_applied=[],
                allowed=True,
                reason="operator resumed sensor ingest",
                details={"requested_scope": scope},
            )
        )

    def is_paused(self, scope: str) -> bool:
        return "all" in self.paused_scopes or scope in self.paused_scopes

    def forget_scope(self, scope: str) -> dict[str, Any]:
        events_removed = (
            self.store.forget_scope(scope)
            if hasattr(self.store, "forget_scope")
            else 0
        )
        audit_records_tombstoned = (
            self.audit_log.tombstone_scope(scope)
            if hasattr(self.audit_log, "tombstone_scope")
            else 0
        )
        result = ScopePurgeResult(
            scope=scope,
            events_removed=events_removed,
            audit_records_tombstoned=audit_records_tombstoned,
        )
        self.audit_log.record(
            AuditRecord(
                actor="argus-dashboard",
                tool="sensor_forget_scope",
                scope=scope,
                event_count=events_removed,
                redactions_applied=[],
                allowed=True,
                reason="operator forgot scoped local data",
                details={
                    "requested_scope": scope,
                    "purge_result": result.to_dict(),
                    "stores": {
                        "timeline": "purged",
                        "audit_raw_payloads": "tombstoned",
                        "lancedb": "not_configured",
                        "neo4j": "not_configured",
                        "retained_blobs": "not_configured",
                    },
                },
            )
        )
        return {"ok": True, "status": "forgotten", **result.to_dict()}

    def export_session_brief(self, *, limit: int = 20) -> dict[str, Any]:
        brief = self.store.ambient_summary(policy=self.policy, limit=limit)
        event_count = len(self.store.recent(limit=limit))
        self.audit_log.record(
            AuditRecord(
                actor="argus-dashboard",
                tool="sensor_export_session_brief",
                scope="session_brief",
                event_count=event_count,
                redactions_applied=[],
                allowed=True,
                reason="operator exported redacted session brief",
                details={"sanitized_brief": brief},
            )
        )
        return {"ok": True, "brief": brief, "event_count": event_count}

    def dashboard_state(self) -> dict[str, Any]:
        return dashboard_state(
            store=self.store,
            audit_log=self.audit_log,
            policy=self.policy,
            publisher=self.publisher,
            paused_scopes=self.paused_scopes,
        )


def make_handler(gateway: EventGateway) -> type[BaseHTTPRequestHandler]:
    class ArgusEventGatewayHandler(BaseHTTPRequestHandler):
        server_version = "ArgusEventGateway/0.1"

        def do_GET(self) -> None:
            if self.path == "/health":
                self._write_json(200, {"ok": True})
                return
            if self.path == "/dashboard.json":
                self._write_json(200, gateway.dashboard_state())
                return
            if self.path == "/dashboard":
                self._write_html(200, render_dashboard_html(gateway.dashboard_state()))
                return
            self._write_json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            if self.path in {"/control/pause", "/control/resume"}:
                payload = self._read_payload()
                scope = str(payload.get("scope") or "macos")
                if self.path == "/control/pause":
                    gateway.pause_scope(scope)
                    status = "paused"
                else:
                    gateway.resume_scope(scope)
                    status = "active"
                self._write_json(200, {"ok": True, "scope": scope, "status": status})
                return

            if self.path == "/control/forget":
                payload = self._read_payload()
                scope = str(payload.get("scope") or "")
                if not scope:
                    self._write_json(400, {"ok": False, "error": "scope is required"})
                    return
                try:
                    self._write_json(200, gateway.forget_scope(scope))
                except ValueError as exc:
                    self._write_json(400, {"ok": False, "error": str(exc)})
                return

            if self.path == "/control/export":
                payload = self._read_payload()
                limit = int(payload.get("limit") or 20)
                self._write_json(200, gateway.export_session_brief(limit=limit))
                return

            try:
                if self.path != "/events":
                    self._write_json(404, {"ok": False, "error": "not found"})
                    return
                payload = self._read_payload()
                result = gateway.ingest_dict(payload)
            except PausedScopeError as exc:
                self._write_json(423, {"ok": False, "error": str(exc), "scope": exc.scope})
                return
            except Exception as exc:  # pragma: no cover - exact HTTP paths are smoke-tested externally.
                self._write_json(400, {"ok": False, "error": str(exc)})
                return

            self._write_json(202, {"ok": True, **result.to_dict()})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_html(self, status_code: int, body_text: str) -> None:
            body = body_text.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_payload(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            text = body.decode("utf-8")
            if "application/x-www-form-urlencoded" in content_type:
                return {
                    key: values[-1]
                    for key, values in parse_qs(text, keep_blank_values=True).items()
                }
            return json.loads(text)

    return ArgusEventGatewayHandler


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"Argus event gateway only binds to loopback hosts, got {host!r}")
    gateway = EventGateway(store=store_from_env(), audit_log=audit_log_from_env())
    server = ThreadingHTTPServer((host, port), make_handler(gateway))
    server.serve_forever()


def store_from_env() -> InMemoryEventStore | SQLiteTimelineStore:
    db_path = os.environ.get("ARGUS_TIMELINE_DB_PATH")
    if not db_path:
        return InMemoryEventStore()
    return SQLiteTimelineStore(db_path)


def audit_log_from_env() -> InMemoryAuditLog | SQLiteAuditLog:
    db_path = os.environ.get("ARGUS_TIMELINE_DB_PATH")
    if not db_path:
        return InMemoryAuditLog()
    return SQLiteAuditLog(db_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
