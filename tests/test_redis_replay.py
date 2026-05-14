from dataclasses import dataclass, field

from argus_services.event_gateway import EventGateway
from argus_services.events import make_event
from argus_services.sqlite_store import SQLiteTimelineStore
from argus_services.storage_worker import RedisToSQLiteWorker, StorageWorkerConfig, run_worker
from argus_services.streams import (
    DLQ_STREAM,
    RedisStreamConsumer,
    StreamMessage,
    event_from_stream_fields,
    parse_xpending,
    parse_xreadgroup,
    xadd_fields,
)


@dataclass
class ReplayPublisher:
    published: list[tuple[str, str]] = field(default_factory=list)

    def publish(self, stream, event):
        redis_id = f"170000000000{len(self.published)}-0"
        self.published.append((stream, event.event_id))
        return redis_id


class ReplayConsumer:
    def __init__(self, publisher):
        self.publisher = publisher
        self.offset = 0
        self.pending: list[tuple[str, str]] = []
        self.dead_lettered: list[tuple[str, str]] = []

    def readgroup(self, count=1):
        batch = self.publisher.published[self.offset:self.offset + count]
        self.offset += len(batch)
        self.pending.extend(batch)
        return batch

    def ack(self, event_id):
        self.pending = [item for item in self.pending if item[1] != event_id]

    def reclaim_stale(self, max_attempts=1):
        stale = list(self.pending)
        self.pending.clear()
        if max_attempts <= 1:
            self.dead_lettered.extend(stale)
            return []
        self.pending.extend(stale)
        return stale


def test_redis_replay_model_covers_read_ack_reclaim_and_dlq():
    publisher = ReplayPublisher()
    gateway = EventGateway(publisher=publisher)
    first = make_event("activity.frontmost_window", {"title": "Safari"}, source_platform="macos")
    second = make_event("activity.focused_field", {"text": "hello"}, source_platform="macos")

    gateway.ingest(first)
    gateway.ingest(second)
    consumer = ReplayConsumer(publisher)

    batch = consumer.readgroup(count=2)
    consumer.ack(first.event_id)
    reclaimed = consumer.reclaim_stale(max_attempts=1)

    assert batch == [
        ("stream:raw:macos", first.event_id),
        ("stream:raw:macos", second.event_id),
    ]
    assert reclaimed == []
    assert consumer.pending == []
    assert consumer.dead_lettered == [("stream:raw:macos", second.event_id)]


class FakeRedisExecutor:
    def __init__(self):
        self.commands: list[list[str]] = []
        self.responses: list[object] = []

    def execute(self, command):
        self.commands.append(command)
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return "OK"


def test_redis_consumer_creates_groups_idempotently():
    executor = FakeRedisExecutor()
    consumer = RedisStreamConsumer("cg-perception", "worker-1", executor=executor)

    consumer.ensure_group("stream:raw:macos")
    executor.responses.append(RuntimeError("BUSYGROUP Consumer Group name already exists"))
    consumer.ensure_group("stream:raw:macos")

    assert executor.commands == [
        ["XGROUP", "CREATE", "stream:raw:macos", "cg-perception", "0", "MKSTREAM"],
        ["XGROUP", "CREATE", "stream:raw:macos", "cg-perception", "0", "MKSTREAM"],
    ]


def test_redis_consumer_reads_group_messages_and_acks():
    executor = FakeRedisExecutor()
    executor.responses.append(
        [
            [
                "stream:raw:macos",
                [
                    [
                        "1778681743795-0",
                        [
                            "event_id",
                            "evt-1",
                            "event_type",
                            "activity.window_focus",
                        ],
                    ]
                ],
            ]
        ]
    )
    executor.responses.append(1)
    consumer = RedisStreamConsumer("cg-perception", "worker-1", executor=executor)

    messages = consumer.read(["stream:raw:macos"], count=1, block_ms=25)
    acked = consumer.ack("stream:raw:macos", messages[0].redis_id)

    assert messages[0].stream == "stream:raw:macos"
    assert messages[0].redis_id == "1778681743795-0"
    assert messages[0].event_id == "evt-1"
    assert messages[0].fields["event_type"] == "activity.window_focus"
    assert acked == 1
    assert executor.commands[0] == [
        "XREADGROUP",
        "GROUP",
        "cg-perception",
        "worker-1",
        "COUNT",
        "1",
        "BLOCK",
        "25",
        "STREAMS",
        "stream:raw:macos",
        ">",
    ]
    assert executor.commands[1] == ["XACK", "stream:raw:macos", "cg-perception", "1778681743795-0"]


def test_redis_consumer_reclaims_retryable_and_dead_letters_exhausted_pending():
    executor = FakeRedisExecutor()
    executor.responses.extend(
        [
            [
                ["1778681743795-0", "worker-1", 60_000, 1],
                ["1778681743796-0", "worker-1", 60_000, 5],
            ],
            "1778681800000-0",
            1,
            [
                "0-0",
                [["1778681743795-0", ["event_id", "evt-retry"]]],
                [],
            ],
        ]
    )
    consumer = RedisStreamConsumer(
        "cg-perception",
        "worker-2",
        executor=executor,
        max_attempts=5,
    )

    reclaimed = consumer.reclaim_stale("stream:raw:macos", min_idle_ms=30_000)

    assert [message.event_id for message in reclaimed] == ["evt-retry"]
    assert executor.commands[0] == [
        "XPENDING",
        "stream:raw:macos",
        "cg-perception",
        "-",
        "+",
        "10",
        "worker-2",
    ]
    assert executor.commands[1][:7] == [
        "XADD",
        DLQ_STREAM,
        "*",
        "source_stream",
        "stream:raw:macos",
        "source_redis_id",
        "1778681743796-0",
    ]
    assert executor.commands[2] == ["XACK", "stream:raw:macos", "cg-perception", "1778681743796-0"]
    assert executor.commands[3] == [
        "XAUTOCLAIM",
        "stream:raw:macos",
        "cg-perception",
        "worker-2",
        "30000",
        "0-0",
        "COUNT",
        "10",
    ]


def test_redis_response_parsers_handle_empty_and_nested_shapes():
    assert parse_xreadgroup(None) == []
    assert parse_xpending([]) == []


def test_redis_stream_fields_round_trip_full_event_contract():
    event = make_event(
        "activity.browser_page",
        {"title": "Pricing", "domain": "vendor.example"},
        source_device_id="macbook-test",
        source_platform="macos",
        sensor_id="argus-sensor-mac",
        session_id="sess-1",
        tags=["browser"],
    )

    round_tripped = event_from_stream_fields(xadd_fields(event))

    assert round_tripped.event_id == event.event_id
    assert round_tripped.schema_version == event.schema_version
    assert round_tripped.source_device_id == "macbook-test"
    assert round_tripped.sensor_version == event.sensor_version
    assert round_tripped.ingested_at == event.ingested_at
    assert round_tripped.session_id == "sess-1"
    assert round_tripped.payload == event.payload
    assert round_tripped.tags == ["browser"]


class FakeStreamConsumer:
    def __init__(self, messages):
        self.messages = list(messages)
        self.groups = []
        self.acked = []
        self.dead_lettered = []

    def ensure_group(self, stream):
        self.groups.append(stream)

    def read(self, streams, *, count=10, block_ms=0):
        return self.messages[:count]

    def ack(self, stream, *redis_ids):
        self.acked.extend((stream, redis_id) for redis_id in redis_ids)
        return len(redis_ids)

    def dead_letter(self, stream, *redis_ids, reason):
        self.dead_lettered.extend((stream, redis_id, reason) for redis_id in redis_ids)
        return ["dlq-1"]


def test_redis_to_sqlite_worker_stores_events_and_acks(tmp_path):
    event = make_event(
        "activity.browser_page",
        {"title": "Worker stored"},
        source_platform="macos",
    )
    message = StreamMessage(
        stream="stream:raw:macos",
        redis_id="1778682379180-0",
        fields=xadd_fields(event),
    )
    consumer = FakeStreamConsumer([message])
    store = SQLiteTimelineStore(tmp_path / "timeline.db")

    try:
        worker = RedisToSQLiteWorker(
            consumer=consumer,
            store=store,
            streams=["stream:raw:macos"],
        )
        stored = worker.process_once()

        assert stored == 1
        assert store.get(event.event_id).payload["title"] == "Worker stored"
        assert consumer.acked == [("stream:raw:macos", "1778682379180-0")]
        assert consumer.dead_lettered == []
    finally:
        store.close()


def test_redis_to_sqlite_worker_dead_letters_unparseable_messages(tmp_path):
    message = StreamMessage(
        stream="stream:raw:macos",
        redis_id="bad-0",
        fields={"event_id": "missing-required-fields"},
    )
    consumer = FakeStreamConsumer([message])
    store = SQLiteTimelineStore(tmp_path / "timeline.db")

    try:
        worker = RedisToSQLiteWorker(
            consumer=consumer,
            store=store,
            streams=["stream:raw:macos"],
        )
        stored = worker.process_once()

        assert stored == 0
        assert consumer.acked == []
        assert consumer.dead_lettered[0][0:2] == ("stream:raw:macos", "bad-0")
    finally:
        store.close()


def test_storage_worker_config_reads_environment(monkeypatch):
    monkeypatch.setenv("ARGUS_TIMELINE_DB_PATH", "/tmp/argus-test.db")
    monkeypatch.setenv("ARGUS_REDIS_HOST", "127.0.0.2")
    monkeypatch.setenv("ARGUS_REDIS_PORT", "6380")
    monkeypatch.setenv("ARGUS_STORAGE_WORKER_GROUP", "cg-storage-test")
    monkeypatch.setenv("ARGUS_STORAGE_WORKER_CONSUMER", "worker-test")
    monkeypatch.setenv("ARGUS_STORAGE_WORKER_STREAMS", "stream:raw:macos,stream:raw:ios")
    monkeypatch.setenv("ARGUS_STORAGE_WORKER_COUNT", "7")
    monkeypatch.setenv("ARGUS_STORAGE_WORKER_BLOCK_MS", "50")

    config = StorageWorkerConfig.from_env()

    assert config.timeline_db_path == "/tmp/argus-test.db"
    assert config.redis_host == "127.0.0.2"
    assert config.redis_port == 6380
    assert config.group == "cg-storage-test"
    assert config.consumer_name == "worker-test"
    assert config.streams == ("stream:raw:macos", "stream:raw:ios")
    assert config.count == 7
    assert config.block_ms == 50


def test_run_worker_once_ensures_groups_and_returns_processed_count(tmp_path):
    event = make_event("activity.browser_page", {"title": "once"}, source_platform="macos")
    message = StreamMessage("stream:raw:macos", "1778682379180-0", xadd_fields(event))
    consumer = FakeStreamConsumer([message])
    store = SQLiteTimelineStore(tmp_path / "timeline.db")

    try:
        worker = RedisToSQLiteWorker(
            consumer=consumer,
            store=store,
            streams=["stream:raw:macos"],
        )
        processed = run_worker(
            worker,
            count=10,
            block_ms=0,
            idle_sleep_seconds=0,
            once=True,
        )

        assert processed == 1
        assert consumer.groups == ["stream:raw:macos"]
    finally:
        store.close()
