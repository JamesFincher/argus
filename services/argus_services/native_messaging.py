"""Native messaging host bridge for browser page-context events.

The browser native messaging protocol frames each JSON message as a
little-endian 32-bit byte length followed by UTF-8 JSON. This host accepts
Safari/WebExtension ``page_context`` messages and forwards canonical Argus event
envelopes to the loopback event gateway.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import urlparse

from .event_gateway import LOOPBACK_HOSTS
from .events import EventEnvelope, make_event, utc_now_iso

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765/events"
MAX_FRAME_BYTES = 1024 * 1024
NATIVE_HOST_NAME = "com.argus.sensor.native"


class NativeMessagingError(RuntimeError):
    """Raised for protocol, payload, or gateway failures."""


@dataclass(frozen=True)
class GatewayPostResult:
    status_code: int
    body: dict[str, Any]


def read_frame(stream: BinaryIO) -> dict[str, Any] | None:
    header = stream.read(4)
    if header == b"":
        return None
    if len(header) != 4:
        raise NativeMessagingError("incomplete native messaging frame header")

    (length,) = struct.unpack("<I", header)
    if length > MAX_FRAME_BYTES:
        raise NativeMessagingError(f"native messaging frame too large: {length}")

    body = stream.read(length)
    if len(body) != length:
        raise NativeMessagingError("incomplete native messaging frame body")

    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeMessagingError(f"invalid native messaging JSON: {exc}") from exc

    if not isinstance(message, dict):
        raise NativeMessagingError("native messaging payload must be a JSON object")
    return message


def write_frame(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
    stream.write(struct.pack("<I", len(body)))
    stream.write(body)
    stream.flush()


def validate_loopback_gateway_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http":
        raise NativeMessagingError("gateway URL must use http on loopback")
    if parsed.hostname not in LOOPBACK_HOSTS:
        raise NativeMessagingError("gateway URL must target a loopback host")
    if parsed.path != "/events":
        raise NativeMessagingError("gateway URL path must be /events")
    if parsed.params or parsed.query or parsed.fragment:
        raise NativeMessagingError("gateway URL must not include params, query, or fragment")
    if parsed.port is None:
        raise NativeMessagingError("gateway URL must include an explicit port")
    return url


def page_context_to_event(message: dict[str, Any]) -> EventEnvelope:
    if message.get("type") != "page_context":
        raise NativeMessagingError("unsupported native message type")

    href = _required_string(message, "href")
    parsed_href = urlparse(href)
    if parsed_href.scheme not in {"http", "https"} or not parsed_href.netloc:
        raise NativeMessagingError("page_context href must be an http(s) URL")

    domain = _string_or_none(message.get("domain")) or parsed_href.hostname or ""
    title = _string_or_none(message.get("title")) or ""
    selection = _string_or_none(message.get("selection"))
    referrer = _string_or_none(message.get("referrer"))
    referrer_domain = _domain_from_url(referrer) if referrer else None

    payload: dict[str, Any] = {
        "browser": _string_or_none(message.get("browser")) or "Safari",
        "tab_id": _string_or_none(message.get("tab_id")),
        "url": href,
        "domain": domain,
        "title": title,
        "selection_text": selection or None,
        "referrer_domain": referrer_domain,
    }

    observed_at = _string_or_none(message.get("observed_at")) or utc_now_iso()
    return make_event(
        "activity.browser_page",
        payload,
        source_device_id=_source_device_id(),
        source_platform="macos",
        sensor_id="safari_webext",
        sensor_version="0.1.0",
        observed_at=observed_at,
        ingested_at=utc_now_iso(),
        raw_scope="ephemeral",
        tags=["macos", "browser", "safari_webext", "page_context", domain],
    )


def post_event(event: EventEnvelope, gateway_url: str = DEFAULT_GATEWAY_URL) -> GatewayPostResult:
    target = validate_loopback_gateway_url(gateway_url)
    body = json.dumps(event.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        target,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response_body = _read_json_response(response.read())
            return GatewayPostResult(status_code=response.status, body=response_body)
    except urllib.error.HTTPError as exc:
        error_body = _read_json_response(exc.read())
        detail = error_body.get("error") if isinstance(error_body, dict) else str(exc)
        raise NativeMessagingError(f"event gateway rejected event: {detail}") from exc
    except urllib.error.URLError as exc:
        raise NativeMessagingError(f"event gateway unavailable: {exc.reason}") from exc


def handle_message(
    message: dict[str, Any],
    *,
    gateway_url: str = DEFAULT_GATEWAY_URL,
) -> dict[str, Any]:
    try:
        event = page_context_to_event(message)
        result = post_event(event, gateway_url=gateway_url)
    except NativeMessagingError as exc:
        return {"ok": False, "error": str(exc)}

    response: dict[str, Any] = {
        "ok": True,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "gateway_status": result.status_code,
    }
    if result.body:
        response["gateway"] = result.body
    return response


def run(
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
    *,
    gateway_url: str | None = None,
) -> int:
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout.buffer
    target = gateway_url or os.environ.get("ARGUS_EVENT_GATEWAY_URL") or DEFAULT_GATEWAY_URL
    validate_loopback_gateway_url(target)

    while True:
        message = read_frame(input_stream)
        if message is None:
            return 0
        write_frame(output_stream, handle_message(message, gateway_url=target))


def main() -> int:
    try:
        return run()
    except NativeMessagingError as exc:
        write_frame(sys.stdout.buffer, {"ok": False, "error": str(exc)})
        return 1


def _required_string(message: dict[str, Any], key: str) -> str:
    value = _string_or_none(message.get(key))
    if not value:
        raise NativeMessagingError(f"page_context {key} is required")
    return value


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _domain_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    return parsed.hostname


def _source_device_id() -> str:
    return os.environ.get("ARGUS_SOURCE_DEVICE_ID") or socket.gethostname() or "local-mac"


def _read_json_response(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": body.decode("utf-8", errors="replace")}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
