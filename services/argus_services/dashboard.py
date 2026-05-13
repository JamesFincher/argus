"""Local-only dashboard state and rendering for Argus Sensor/Mesh."""

from __future__ import annotations

import html
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
) -> dict[str, Any]:
    raw_events = [event.to_dict() for event in store.recent(limit=limit)]
    sanitized_events = [
        policy.redact_event(event).to_dict()
        for event in store.recent(limit=limit)
    ]
    audit_records = [record.to_dict() for record in audit_log.recent(limit=limit)]

    return {
        "ok": True,
        "sensor_control": {
            "paused_scopes": sorted(paused_scopes or set()),
        },
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
    <form method="post" action="/control/pause"><button type="submit">Pause macOS Sensor Ingest</button></form>
    <form method="post" action="/control/resume"><button type="submit">Resume macOS Sensor Ingest</button></form>
  </section>
  <section><h2>Raw Local Events</h2><ul>{raw_items}</ul></section>
  <section><h2>Sanitized Hermes Outputs</h2><ul>{hermes_items}</ul></section>
  <section><h2>Audit Trail</h2><ul>{audit_items}</ul></section>
</main>
</body>
</html>"""
