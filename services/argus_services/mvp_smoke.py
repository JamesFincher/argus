"""End-to-end MVP smoke runner for local Argus components."""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .event_gateway import EventGateway, make_handler
from .mcp import LocalMCPServer
from .mcp_stdio import MCPStdioServer
from .native_messaging import read_frame, run as run_native_host, write_frame
from .perception import PerceptionWorker
from .policy import RedactionPolicy
from .sqlite_store import SQLiteAuditLog, SQLiteTimelineStore


@dataclass
class RecordingPublisher:
    """Deterministic local publisher for smoke runs that do not require Redis."""

    calls: list[dict[str, str]] = field(default_factory=list)

    def publish(self, stream: str, event: Any) -> str:
        redis_id = f"smoke-{len(self.calls) + 1}"
        self.calls.append(
            {
                "stream": stream,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "redis_id": redis_id,
            }
        )
        return redis_id


def run_mvp_smoke(db_path: str | Path | None = None) -> dict[str, Any]:
    """Run the local MVP path and return a machine-readable verification summary."""

    if db_path is None:
        with tempfile.TemporaryDirectory(prefix="argus-mvp-smoke-") as temp_dir:
            return _run_mvp_smoke(Path(temp_dir) / "timeline.db")
    return _run_mvp_smoke(Path(db_path))


def _run_mvp_smoke(db_path: Path) -> dict[str, Any]:
    policy = RedactionPolicy(approval_token="approve-smoke")
    store = SQLiteTimelineStore(db_path)
    audit_log = SQLiteAuditLog(db_path)
    publisher = RecordingPublisher()
    gateway = EventGateway(
        store=store,
        audit_log=audit_log,
        policy=policy,
        publisher=publisher,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gateway))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        gateway_url = f"http://127.0.0.1:{server.server_address[1]}/events"
        native_response = _send_native_page_context(gateway_url)
        source_event = store.get(native_response["event_id"])
        if source_event is None:
            raise RuntimeError("native host response referenced an event that was not stored")

        perception = PerceptionWorker(policy=policy).process(source_event)
        if perception.blocked_event is not None:
            gateway.ingest(perception.blocked_event)
            derived_note_id = None
        else:
            derived_note = gateway.ingest(perception.derived_note)
            derived_note_id = derived_note.event_id

        mcp_server = LocalMCPServer(store=store, policy=policy, audit_log=audit_log)
        transport = MCPStdioServer(server=mcp_server)
        recent_notes = _call_mcp_tool(
            transport,
            "sensor_get_recent_notes",
            {"limit": 5, "actor": "hermes-smoke"},
            request_id=2,
        )
        raw_without_approval = _call_mcp_tool(
            transport,
            "sensor_expand_event",
            {
                "event_id": source_event.event_id,
                "raw_mode": "full",
                "actor": "hermes-smoke",
            },
            request_id=3,
        )

        recent_text = recent_notes["structuredContent"]["context"]
        raw_result = raw_without_approval["structuredContent"]
        audit_records = [record.to_dict() for record in audit_log.recent(limit=20)]
        raw_ingest_records = [
            record
            for record in audit_records
            if record["tool"] == "sensor_ingest_raw"
            and record["details"].get("raw_data_local_only") is True
        ]
        agent_records = [
            record
            for record in audit_records
            if record["tool"] in {"sensor_get_recent_notes", "sensor_expand_event"}
        ]

        _assert_smoke_invariants(
            native_response=native_response,
            recent_text=recent_text,
            raw_result=raw_result,
            raw_ingest_records=raw_ingest_records,
            agent_records=agent_records,
        )

        return {
            "ok": True,
            "db_path": str(db_path),
            "gateway_url": gateway_url,
            "native_response": native_response,
            "source_event_id": source_event.event_id,
            "derived_note_id": derived_note_id,
            "publisher_calls": publisher.calls,
            "recent_notes": recent_text,
            "raw_without_approval": raw_result,
            "audit_tools": [record["tool"] for record in audit_records],
            "raw_ingest_audit_count": len(raw_ingest_records),
            "agent_audit_count": len(agent_records),
            "stored_event_count": len(store.recent(limit=50)),
        }
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        store.close()
        audit_log.close()


def _send_native_page_context(gateway_url: str) -> dict[str, Any]:
    message = {
        "type": "page_context",
        "href": "https://vendor.example.com/pricing",
        "domain": "vendor.example.com",
        "title": "Vendor Pricing",
        "selection": "Contact alex@example.com about the annual plan",
        "observed_at": "2026-05-13T12:00:00Z",
    }
    input_stream = io.BytesIO()
    write_frame(input_stream, message)
    input_stream.seek(0)
    output_stream = io.BytesIO()

    exit_code = run_native_host(
        input_stream=input_stream,
        output_stream=output_stream,
        gateway_url=gateway_url,
    )
    if exit_code != 0:
        raise RuntimeError(f"native host exited with {exit_code}")
    output_stream.seek(0)
    response = read_frame(output_stream)
    if response is None:
        raise RuntimeError("native host did not write a response")
    if not response.get("ok"):
        raise RuntimeError(f"native host failed: {response}")
    return response


def _call_mcp_tool(
    transport: MCPStdioServer,
    name: str,
    arguments: dict[str, Any],
    *,
    request_id: int,
) -> dict[str, Any]:
    stdin = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        + "\n"
    )
    stdout = io.StringIO()
    transport.serve(stdin=stdin, stdout=stdout)
    response = json.loads(stdout.getvalue())
    if "error" in response:
        raise RuntimeError(f"MCP tool call failed: {response['error']}")
    return response["result"]


def _assert_smoke_invariants(
    *,
    native_response: dict[str, Any],
    recent_text: str,
    raw_result: dict[str, Any],
    raw_ingest_records: list[dict[str, Any]],
    agent_records: list[dict[str, Any]],
) -> None:
    if native_response.get("event_type") != "activity.browser_page":
        raise RuntimeError("native host did not create a browser-page event")
    if "alex@example.com" in recent_text:
        raise RuntimeError("sanitized Hermes context leaked raw email selection")
    if raw_result.get("ok") is not False:
        raise RuntimeError("raw expansion without approval was not blocked")
    if not raw_ingest_records:
        raise RuntimeError("raw local ingest audit record was not written")
    if len(agent_records) < 2:
        raise RuntimeError("agent-facing MCP audit records were not written")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        help="SQLite timeline/audit path to use. Defaults to a temporary database.",
    )
    args = parser.parse_args(argv)
    result = run_mvp_smoke(args.db_path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
