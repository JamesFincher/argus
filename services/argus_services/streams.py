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


@dataclass(frozen=True)
class StreamMessage:
    stream: str
    redis_id: str
    fields: dict[str, str]

    @property
    def event_id(self) -> str:
        return self.fields.get("event_id", "")


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
        "schema_version": data["schema_version"],
        "source_device_id": data["source_device_id"],
        "source_platform": data["source_platform"],
        "sensor_id": data["sensor_id"],
        "sensor_version": data["sensor_version"],
        "observed_at": data["observed_at"],
        "ingested_at": data["ingested_at"],
        "session_id": data["session_id"] or "",
        "dedupe_key": data["dedupe_key"] or "",
        "sensitivity": data["sensitivity"],
        "raw_scope": data["raw_scope"],
        "payload_json": json.dumps(data["payload"], sort_keys=True, separators=(",", ":")),
        "redactions_json": json.dumps(data["redactions"], sort_keys=True, separators=(",", ":")),
        "relationships_json": json.dumps(data["relationships"], sort_keys=True, separators=(",", ":")),
        "tags_json": json.dumps(data["tags"], sort_keys=True, separators=(",", ":")),
    }


def event_from_stream_fields(fields: dict[str, str]) -> EventEnvelope:
    return EventEnvelope.from_dict(
        {
            "event_id": fields["event_id"],
            "event_type": fields["event_type"],
            "schema_version": fields.get("schema_version", "2026-05-11"),
            "source_device_id": fields.get("source_device_id", "unknown"),
            "source_platform": fields["source_platform"],
            "sensor_id": fields["sensor_id"],
            "sensor_version": fields.get("sensor_version", "0.1.0"),
            "observed_at": fields["observed_at"],
            "ingested_at": fields.get("ingested_at") or fields["observed_at"],
            "session_id": fields.get("session_id") or None,
            "dedupe_key": fields.get("dedupe_key") or None,
            "sensitivity": fields["sensitivity"],
            "raw_scope": fields["raw_scope"],
            "payload": json.loads(fields["payload_json"]),
            "redactions": json.loads(fields["redactions_json"]),
            "relationships": json.loads(fields["relationships_json"]),
            "tags": json.loads(fields["tags_json"]),
        }
    )


class StreamPublisher(Protocol):
    def publish(self, stream: str, event: EventEnvelope) -> str:
        ...


class RedisCommandExecutor(Protocol):
    def execute(self, command: list[str]) -> Any:
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

    def execute(self, command: list[str]) -> Any:
        with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
            sock.sendall(_encode_resp(command))
            return _read_resp(sock)


@dataclass(frozen=True)
class RedisStreamConsumer:
    group: str
    consumer_name: str
    executor: RedisCommandExecutor | None = None
    publisher: RedisStreamPublisher | None = None
    max_attempts: int = 5

    def __post_init__(self) -> None:
        if self.executor is None:
            object.__setattr__(self, "executor", self.publisher or RedisStreamPublisher())

    def ensure_group(self, stream: str, start_id: str = "0") -> None:
        assert self.executor is not None
        try:
            self.executor.execute(["XGROUP", "CREATE", stream, self.group, start_id, "MKSTREAM"])
        except RuntimeError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def read(self, streams: list[str], *, count: int = 10, block_ms: int = 0) -> list[StreamMessage]:
        assert self.executor is not None
        response = self.executor.execute(
            [
                "XREADGROUP",
                "GROUP",
                self.group,
                self.consumer_name,
                "COUNT",
                str(count),
                "BLOCK",
                str(block_ms),
                "STREAMS",
                *streams,
                *((">" for _ in streams)),
            ]
        )
        return parse_xreadgroup(response)

    def ack(self, stream: str, *redis_ids: str) -> int:
        if not redis_ids:
            return 0
        assert self.executor is not None
        response = self.executor.execute(["XACK", stream, self.group, *redis_ids])
        return int(response)

    def pending(self, stream: str, *, count: int = 10) -> list[dict[str, Any]]:
        assert self.executor is not None
        response = self.executor.execute(
            [
                "XPENDING",
                stream,
                self.group,
                "-",
                "+",
                str(count),
                self.consumer_name,
            ]
        )
        return parse_xpending(response)

    def reclaim_stale(
        self,
        stream: str,
        *,
        min_idle_ms: int,
        count: int = 10,
    ) -> list[StreamMessage]:
        pending = self.pending(stream, count=count)
        retry_ids = [
            item["redis_id"]
            for item in pending
            if item["delivery_count"] < self.max_attempts
        ]
        dlq_ids = [
            item["redis_id"]
            for item in pending
            if item["delivery_count"] >= self.max_attempts
        ]

        if dlq_ids:
            self.dead_letter(stream, *dlq_ids, reason="max_attempts_exceeded")

        if not retry_ids:
            return []

        assert self.executor is not None
        response = self.executor.execute(
            [
                "XAUTOCLAIM",
                stream,
                self.group,
                self.consumer_name,
                str(min_idle_ms),
                "0-0",
                "COUNT",
                str(count),
            ]
        )
        return parse_xautoclaim(stream, response)

    def dead_letter(self, stream: str, *redis_ids: str, reason: str) -> list[str]:
        if not redis_ids:
            return []
        assert self.executor is not None
        dlq_entries = []
        for redis_id in redis_ids:
            response = self.executor.execute(
                [
                    "XADD",
                    DLQ_STREAM,
                    "*",
                    "source_stream",
                    stream,
                    "source_redis_id",
                    redis_id,
                    "group",
                    self.group,
                    "reason",
                    reason,
                ]
            )
            dlq_entries.append(str(response))
        self.ack(stream, *redis_ids)
        return dlq_entries


def _encode_resp(values: list[str]) -> bytes:
    chunks = [f"*{len(values)}\r\n".encode("utf-8")]
    for value in values:
        data = value.encode("utf-8")
        chunks.append(f"${len(data)}\r\n".encode("utf-8"))
        chunks.append(data)
        chunks.append(b"\r\n")
    return b"".join(chunks)


def parse_xreadgroup(response: Any) -> list[StreamMessage]:
    if response in (None, []):
        return []
    messages: list[StreamMessage] = []
    for stream_name, entries in response:
        for redis_id, pairs in entries:
            messages.append(
                StreamMessage(
                    stream=stream_name,
                    redis_id=redis_id,
                    fields=fields_from_pairs(pairs),
                )
            )
    return messages


def parse_xpending(response: Any) -> list[dict[str, Any]]:
    return [
        {
            "redis_id": item[0],
            "consumer": item[1],
            "idle_ms": int(item[2]),
            "delivery_count": int(item[3]),
        }
        for item in response or []
    ]


def parse_xautoclaim(stream: str, response: Any) -> list[StreamMessage]:
    if response in (None, []):
        return []
    entries = response[1] if isinstance(response, list) and len(response) > 1 else []
    return [
        StreamMessage(stream=stream, redis_id=redis_id, fields=fields_from_pairs(pairs))
        for redis_id, pairs in entries
    ]


def fields_from_pairs(pairs: list[str]) -> dict[str, str]:
    return {
        str(pairs[index]): str(pairs[index + 1])
        for index in range(0, len(pairs), 2)
    }


def _read_resp(sock: socket.socket) -> Any:
    prefix = sock.recv(1)
    if prefix == b"+":
        return _read_line(sock)
    if prefix == b":":
        return int(_read_line(sock))
    if prefix == b"$":
        length = int(_read_line(sock))
        if length == -1:
            return None
        data = _read_exact(sock, length)
        _read_exact(sock, 2)
        return data.decode("utf-8")
    if prefix == b"*":
        length = int(_read_line(sock))
        if length == -1:
            return None
        return [_read_resp(sock) for _ in range(length)]
    if prefix == b"-":
        raise RuntimeError(_read_line(sock))
    if prefix == b"":
        raise RuntimeError("redis connection closed")
    raise RuntimeError(f"unexpected redis response prefix: {prefix!r}")


def _read_resp_string(sock: socket.socket) -> str:
    response = _read_resp(sock)
    if isinstance(response, str):
        return response
    raise RuntimeError(f"expected redis string response, got {response!r}")


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
