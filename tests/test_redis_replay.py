from dataclasses import dataclass, field

from argus_services.event_gateway import EventGateway
from argus_services.events import make_event


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
