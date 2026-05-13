"""Local-only dashboard state and rendering for Argus Sensor/Mesh."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from .audit import InMemoryAuditLog
from .policy import RedactionPolicy
from .streams import (
    DERIVED_NOTES_STREAM,
    DLQ_STREAM,
    POLICY_BLOCKED_STREAM,
    RAW_STREAMS,
    SYSTEM_METRICS_STREAM,
)


def dashboard_state(
    *,
    store: Any,
    audit_log: Any,
    policy: RedactionPolicy,
    publisher: Any | None = None,
    paused_scopes: set[str] | None = None,
    limit: int = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    raw_events = [event.to_dict() for event in store.recent(limit=limit)]
    sanitized_events = [
        policy.redact_event(event).to_dict()
        for event in store.recent(limit=limit)
    ]
    health_events = store.recent(limit=max(limit, 100))
    audit_records = [record.to_dict() for record in audit_log.recent(limit=limit)]

    return {
        "ok": True,
        "sensor_control": {
            "paused_scopes": sorted(paused_scopes or set()),
            "actions": {
                "pause": "/control/pause",
                "resume": "/control/resume",
                "forget": "/control/forget",
                "export": "/control/export",
            },
        },
        "sensor_health": sensor_health_state(
            health_events,
            paused_scopes=paused_scopes or set(),
            now=now,
        ),
        "redis": redis_status(publisher),
        "raw_events": raw_events,
        "sanitized_events": sanitized_events,
        "hermes_outputs": hermes_outputs_from_audit(audit_records),
        "audit_records": audit_records,
    }


def redis_status(publisher: Any | None) -> dict[str, Any]:
    streams = [
        *RAW_STREAMS.values(),
        DERIVED_NOTES_STREAM,
        POLICY_BLOCKED_STREAM,
        SYSTEM_METRICS_STREAM,
        DLQ_STREAM,
    ]
    status: dict[str, Any] = {
        "streams": streams,
        "ping": "not_configured",
    }
    if publisher is not None and hasattr(publisher, "execute"):
        try:
            status["ping"] = publisher.execute(["PING"])
        except Exception as exc:
            status["ping"] = "error"
            status["error"] = str(exc)
    return status


def sensor_health_state(
    events: list[Any],
    *,
    paused_scopes: set[str],
    now: datetime | None = None,
    stale_after_seconds: int = 120,
) -> dict[str, Any]:
    reference_time = now or datetime.now(timezone.utc)
    heartbeats: dict[str, dict[str, Any]] = {}
    permissions: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type == "system.sensor_heartbeat":
            sensor_id = str(event.payload.get("sensor_id") or event.sensor_id)
            observed_at = parse_event_time(event.observed_at)
            seconds_since_seen = int((reference_time - observed_at).total_seconds())
            status = str(event.payload.get("status") or "ok")
            if event.source_platform in paused_scopes or "all" in paused_scopes:
                status = "paused"
            elif seconds_since_seen > stale_after_seconds:
                status = "stale"
            current = heartbeats.get(sensor_id)
            if current is None or observed_at > parse_event_time(current["last_seen"]):
                heartbeats[sensor_id] = {
                    "sensor_id": sensor_id,
                    "source_platform": event.source_platform,
                    "status": status,
                    "last_seen": event.observed_at,
                    "seconds_since_seen": max(seconds_since_seen, 0),
                    "expected_interval_seconds": event.payload.get("interval_seconds"),
                }
        elif event.event_type == "system.permission_state":
            current_permission = permissions.get(event.source_platform)
            observed_at = parse_event_time(event.observed_at)
            if current_permission is not None and observed_at <= parse_event_time(
                current_permission["observed_at"]
            ):
                continue
            permissions[event.source_platform] = {
                "source_platform": event.source_platform,
                "observed_at": event.observed_at,
                "payload": dict(event.payload),
            }

    return {
        "stale_after_seconds": stale_after_seconds,
        "heartbeats": sorted(heartbeats.values(), key=lambda item: item["sensor_id"]),
        "permissions": permissions,
    }


def parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def hermes_outputs_from_audit(audit_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outputs = []
    detail_keys = {
        "sanitized_context",
        "sanitized_matches",
        "sanitized_event",
        "sanitized_brief",
    }
    for record in audit_records:
        details = record.get("details")
        if not isinstance(details, dict) or not detail_keys.intersection(details):
            continue
        outputs.append(
            {
                "actor": record["actor"],
                "tool": record["tool"],
                "recorded_at": record["recorded_at"],
                "details": {
                    key: details[key]
                    for key in detail_keys
                    if key in details
                },
            }
        )
    return outputs


def render_dashboard_html(state: dict[str, Any]) -> str:
    sensor_items = "\n".join(
        "<li>"
        f"<code>{html.escape(item['sensor_id'])}</code> "
        f"{html.escape(item['status'])} "
        f"last seen {html.escape(str(item['seconds_since_seen']))}s ago"
        "</li>"
        for item in state["sensor_health"]["heartbeats"][:10]
    ) or "<li>No sensor heartbeats recorded.</li>"
    permission_items = "\n".join(
        f"<li><code>{html.escape(platform)}</code> {html.escape(str(details['payload']))}</li>"
        for platform, details in sorted(state["sensor_health"]["permissions"].items())
    ) or "<li>No permission state recorded.</li>"
    raw_items = "\n".join(
        f"<li><code>{html.escape(event['event_type'])}</code> {html.escape(str(event['payload']))}</li>"
        for event in state["raw_events"][:10]
    ) or "<li>No raw events recorded.</li>"
    hermes_items = "\n".join(
        f"<li><code>{html.escape(output['tool'])}</code> {html.escape(str(output['details']))}</li>"
        for output in state["hermes_outputs"][:10]
    ) or "<li>No Hermes-facing sanitized outputs recorded.</li>"
    audit_items = "\n".join(
        f"<li><code>{html.escape(record['tool'])}</code> {html.escape(record['reason'])}</li>"
        for record in state["audit_records"][:10]
    ) or "<li>No audit records recorded.</li>"
    paused = ", ".join(state["sensor_control"]["paused_scopes"]) or "none"
    redis_ping = html.escape(str(state["redis"].get("ping")))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ArgusOS Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 24px; color: #172026; }}
    main {{ max-width: 1120px; margin: 0 auto; }}
    section {{ border-top: 1px solid #d8dee4; padding: 16px 0; }}
    h1, h2 {{ margin: 0 0 10px; }}
    button {{ margin-right: 8px; padding: 6px 10px; }}
    code {{ color: #0b5cad; }}
    li {{ margin: 6px 0; }}
  </style>
</head>
<body>
<main>
  <h1>ArgusOS Dashboard</h1>
  <section>
    <h2>System Control</h2>
    <p>Paused scopes: {html.escape(paused)}</p>
    <p>Redis ping: {redis_ping}</p>
    <form method="post" action="/control/pause">
      <input name="scope" value="macos" aria-label="Pause scope">
      <button type="submit">Pause Sensor Ingest</button>
    </form>
    <form method="post" action="/control/resume">
      <input name="scope" value="macos" aria-label="Resume scope">
      <button type="submit">Resume Sensor Ingest</button>
    </form>
    <form method="post" action="/control/forget">
      <input name="scope" placeholder="domain, app, project, or all" aria-label="Forget scope">
      <button type="submit">Forget Scope</button>
    </form>
    <form method="post" action="/control/export">
      <input name="limit" value="20" aria-label="Export limit">
      <button type="submit">Export Session Brief</button>
    </form>
  </section>
  <section>
    <h2>Sensor Health</h2>
    <ul>{sensor_items}</ul>
    <h2>Permission State</h2>
    <ul>{permission_items}</ul>
  </section>
  <section><h2>Raw Local Events</h2><ul>{raw_items}</ul></section>
  <section><h2>Sanitized Hermes Outputs</h2><ul>{hermes_items}</ul></section>
  <section><h2>Audit Trail</h2><ul>{audit_items}</ul></section>
</main>
</body>
</html>"""
