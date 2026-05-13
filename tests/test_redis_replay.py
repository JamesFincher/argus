from dataclasses import dataclass, field

from argus_services.event_gateway import EventGateway
from argus_services.events import make_event
from argus_services.streams import DLQ_STREAM, RedisStreamConsumer, parse_xpending, parse_xreadgroup


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
                ["1778681743796-0", "worker-1", 60_000, 3],
            ],
            "1778681800000-0",
            1,
            [["1778681743795-0", ["event_id", "evt-retry"]]],
        ]
    )
    consumer = RedisStreamConsumer(
        "cg-perception",
        "worker-2",
        executor=executor,
        max_attempts=3,
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
        "XCLAIM",
        "stream:raw:macos",
        "cg-perception",
        "worker-2",
        "30000",
        "1778681743795-0",
    ]


def test_redis_response_parsers_handle_empty_and_nested_shapes():
    assert parse_xreadgroup(None) == []
    assert parse_xpending([]) == []
