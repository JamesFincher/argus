"""Redis Streams to SQLite timeline worker."""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .sqlite_store import SQLiteTimelineStore
from .streams import RAW_STREAMS, RedisStreamConsumer, StreamMessage, event_from_stream_fields


DEFAULT_TIMELINE_DB_PATH = "~/Library/Application Support/Argus/timeline.db"


@dataclass(frozen=True)
class StorageWorkerConfig:
    timeline_db_path: str
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    group: str = "cg-storage"
    consumer_name: str = "argus-storage-worker"
    streams: tuple[str, ...] = tuple(RAW_STREAMS.values())
    count: int = 25
    block_ms: int = 1_000
    idle_sleep_seconds: float = 0.25

    @classmethod
    def from_env(cls) -> "StorageWorkerConfig":
        streams = tuple(
            stream.strip()
            for stream in os.environ.get("ARGUS_STORAGE_WORKER_STREAMS", ",".join(RAW_STREAMS.values())).split(",")
            if stream.strip()
        )
        return cls(
            timeline_db_path=os.path.expanduser(
                os.environ.get("ARGUS_TIMELINE_DB_PATH", DEFAULT_TIMELINE_DB_PATH)
            ),
            redis_host=os.environ.get("ARGUS_REDIS_HOST", "127.0.0.1"),
            redis_port=int(os.environ.get("ARGUS_REDIS_PORT", "6379")),
            group=os.environ.get("ARGUS_STORAGE_WORKER_GROUP", "cg-storage"),
            consumer_name=os.environ.get("ARGUS_STORAGE_WORKER_CONSUMER", "argus-storage-worker"),
            streams=streams,
            count=int(os.environ.get("ARGUS_STORAGE_WORKER_COUNT", "25")),
            block_ms=int(os.environ.get("ARGUS_STORAGE_WORKER_BLOCK_MS", "1000")),
            idle_sleep_seconds=float(os.environ.get("ARGUS_STORAGE_WORKER_IDLE_SLEEP", "0.25")),
        )


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


def worker_from_config(config: StorageWorkerConfig) -> RedisToSQLiteWorker:
    from .streams import RedisStreamPublisher

    publisher = RedisStreamPublisher(host=config.redis_host, port=config.redis_port)
    consumer = RedisStreamConsumer(
        group=config.group,
        consumer_name=config.consumer_name,
        publisher=publisher,
    )
    store = SQLiteTimelineStore(Path(config.timeline_db_path))
    return RedisToSQLiteWorker(
        consumer=consumer,
        store=store,
        streams=list(config.streams),
    )


def run_worker(
    worker: RedisToSQLiteWorker,
    *,
    count: int,
    block_ms: int,
    idle_sleep_seconds: float,
    once: bool = False,
    ensure_groups: bool = True,
) -> int:
    if ensure_groups:
        worker.ensure_groups()

    processed_total = 0
    while True:
        processed = worker.process_once(count=count, block_ms=block_ms)
        processed_total += processed
        if once:
            return processed_total
        if processed == 0:
            time.sleep(idle_sleep_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one read batch and exit.")
    parser.add_argument("--no-ensure-groups", action="store_true", help="Skip XGROUP CREATE startup.")
    args = parser.parse_args(argv)

    config = StorageWorkerConfig.from_env()
    worker = worker_from_config(config)
    try:
        processed = run_worker(
            worker,
            count=config.count,
            block_ms=config.block_ms,
            idle_sleep_seconds=config.idle_sleep_seconds,
            once=args.once,
            ensure_groups=not args.no_ensure_groups,
        )
        if args.once:
            print(f"processed={processed}")
    finally:
        worker.store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
