"""Redis Streams to SQLite timeline worker."""

from __future__ import annotations

from dataclasses import dataclass

from .sqlite_store import SQLiteTimelineStore
from .streams import RAW_STREAMS, RedisStreamConsumer, StreamMessage, event_from_stream_fields


@dataclass
class RedisToSQLiteWorker:
    consumer: RedisStreamConsumer
    store: SQLiteTimelineStore
    streams: list[str] | None = None

    def __post_init__(self) -> None:
        if self.streams is None:
            self.streams = list(RAW_STREAMS.values())

    def ensure_groups(self) -> None:
        assert self.streams is not None
        for stream in self.streams:
            self.consumer.ensure_group(stream)

    def process_once(self, *, count: int = 10, block_ms: int = 0) -> int:
        assert self.streams is not None
        messages = self.consumer.read(self.streams, count=count, block_ms=block_ms)
        stored = 0
        for message in messages:
            if self._store_message(message):
                stored += 1
        return stored

    def _store_message(self, message: StreamMessage) -> bool:
        try:
            event = event_from_stream_fields(message.fields)
            self.store.add(event)
        except Exception as exc:
            self.consumer.dead_letter(message.stream, message.redis_id, reason=str(exc))
            return False
        self.consumer.ack(message.stream, message.redis_id)
        return True
