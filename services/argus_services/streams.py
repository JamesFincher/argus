"""Redis stream routing for Argus event envelopes."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, Protocol

from .events import EventEnvelope


RAW_STREAMS = {
    "macos": "stream:raw:macos",
    "ios": "stream:raw:ios",
    "watchos": "stream:raw:watchos",
}

DERIVED_NOTES_STREAM = "stream:derived:notes"
POLICY_BLOCKED_STREAM = "stream:policy:blocked"
SYSTEM_METRICS_STREAM = "stream:system:metrics"
DLQ_STREAM = "stream:dlq"


def stream_for_event(event: EventEnvelope) -> str:
    if event.event_type.startswith("perception.") or event.event_type.startswith("derived."):
        return DERIVED_NOTES_STREAM
    if event.event_type.startswith("policy.") or event.sensitivity == "blocked":
        return POLICY_BLOCKED_STREAM
    if event.event_type.startswith("system."):
        return SYSTEM_METRICS_STREAM
    return RAW_STREAMS.get(event.source_platform, DLQ_STREAM)


def xadd_fields(event: EventEnvelope) -> dict[str, str]:
    data = event.to_dict()
    return {
        "event_id": data["event_id"],
        "event_type": data["event_type"],
        "source_platform": data["source_platform"],
        "sensor_id": data["sensor_id"],
        "observed_at": data["observed_at"],
        "dedupe_key": data["dedupe_key"] or "",
        "sensitivity": data["sensitivity"],
        "raw_scope": data["raw_scope"],
        "payload_json": json.dumps(data["payload"], sort_keys=True, separators=(",", ":")),
        "redactions_json": json.dumps(data["redactions"], sort_keys=True, separators=(",", ":")),
        "relationships_json": json.dumps(data["relationships"], sort_keys=True, separators=(",", ":")),
        "tags_json": json.dumps(data["tags"], sort_keys=True, separators=(",", ":")),
    }


class StreamPublisher(Protocol):
    def publish(self, stream: str, event: EventEnvelope) -> str:
        ...


@dataclass(frozen=True)
class RedisStreamPublisher:
    host: str = "127.0.0.1"
    port: int = 6379
    timeout_seconds: float = 2.0
    maxlen: int = 100_000

    def publish(self, stream: str, event: EventEnvelope) -> str:
        command: list[str] = ["XADD", stream, "MAXLEN", "~", str(self.maxlen), "*"]
        for key, value in xadd_fields(event).items():
            command.extend([key, value])

        with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
            sock.sendall(_encode_resp(command))
            return _read_resp_string(sock)


def _encode_resp(values: list[str]) -> bytes:
    chunks = [f"*{len(values)}\r\n".encode("utf-8")]
    for value in values:
        data = value.encode("utf-8")
        chunks.append(f"${len(data)}\r\n".encode("utf-8"))
        chunks.append(data)
        chunks.append(b"\r\n")
    return b"".join(chunks)


def _read_resp_string(sock: socket.socket) -> str:
    prefix = sock.recv(1)
    if prefix == b"+":
        return _read_line(sock)
    if prefix == b"$":
        length = int(_read_line(sock))
        data = _read_exact(sock, length)
        _read_exact(sock, 2)
        return data.decode("utf-8")
    if prefix == b"-":
        raise RuntimeError(_read_line(sock))
    if prefix == b"":
        raise RuntimeError("redis connection closed")
    raise RuntimeError(f"unexpected redis response prefix: {prefix!r}")


def _read_line(sock: socket.socket) -> str:
    data = bytearray()
    while True:
        char = sock.recv(1)
        if char == b"":
            raise RuntimeError("redis connection closed while reading line")
        data.extend(char)
        if data.endswith(b"\r\n"):
            return data[:-2].decode("utf-8")


def _read_exact(sock: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if chunk == b"":
            raise RuntimeError("redis connection closed while reading bulk string")
        data.extend(chunk)
    return bytes(data)
