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

from .events import EventEnvelope
from .policy import RedactionPolicy
from .sqlite_store import SQLiteTimelineStore
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


class EventGateway:
    def __init__(
        self,
        *,
        store: InMemoryEventStore | None = None,
        policy: RedactionPolicy | None = None,
        publisher: StreamPublisher | None = None,
    ) -> None:
        self.store = store or InMemoryEventStore()
        self.policy = policy or RedactionPolicy()
        self.publisher = publisher or RedisStreamPublisher()

    def ingest_dict(self, data: dict[str, Any]) -> IngestResult:
        event = EventEnvelope.from_dict(data)
        return self.ingest(event)

    def ingest(self, event: EventEnvelope) -> IngestResult:
        policy_surface = self.policy.evaluate_surface(event)
        event_dict = event.to_dict()
        if not policy_surface.allowed:
            event_dict["sensitivity"] = "blocked"
            event_dict["tags"] = [*event.tags, "policy_blocked_surface"]
            event = EventEnvelope.from_dict(event_dict)

        stream = stream_for_event(event)
        self.store.add(event)
        redis_id = self.publisher.publish(stream, event)
        return IngestResult(
            event_id=event.event_id,
            stream=stream,
            redis_id=redis_id,
            sensitivity=event.sensitivity,
        )


def make_handler(gateway: EventGateway) -> type[BaseHTTPRequestHandler]:
    class ArgusEventGatewayHandler(BaseHTTPRequestHandler):
        server_version = "ArgusEventGateway/0.1"

        def do_GET(self) -> None:
            if self.path == "/health":
                self._write_json(200, {"ok": True})
                return
            self._write_json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/events":
                self._write_json(404, {"ok": False, "error": "not found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                result = gateway.ingest_dict(payload)
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

    return ArgusEventGatewayHandler


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"Argus event gateway only binds to loopback hosts, got {host!r}")
    gateway = EventGateway(store=store_from_env())
    server = ThreadingHTTPServer((host, port), make_handler(gateway))
    server.serve_forever()


def store_from_env() -> InMemoryEventStore | SQLiteTimelineStore:
    db_path = os.environ.get("ARGUS_TIMELINE_DB_PATH")
    if not db_path:
        return InMemoryEventStore()
    return SQLiteTimelineStore(db_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
