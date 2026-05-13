import pytest

from argus_services.events import make_event
from argus_services.streams import (
    DLQ_STREAM,
    RedisStreamConsumer,
    RedisStreamPublisher,
    StreamMessage,
    _encode_resp,
    _read_resp,
    _read_resp_string,
    fields_from_pairs,
    parse_xpending,
    parse_xreadgroup,
)


class FakeSocket:
    def __init__(self, response: bytes = b""):
        self.response = bytearray(response)
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def sendall(self, data):
        self.sent += data

    def recv(self, count):
        if not self.response:
            return b""
        data = bytes(self.response[:count])
        del self.response[:count]
        return data


class RecordingExecutor:
    def __init__(self, responses=None):
        self.commands = []
        self.responses = list(responses or [])

    def execute(self, command):
        self.commands.append(command)
        if not self.responses:
            return "OK"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_resp_encoding_and_reader_cover_redis_wire_shapes():
    encoded = _encode_resp(["PING", "hello"])
    assert encoded == b"*2\r\n$4\r\nPING\r\n$5\r\nhello\r\n"
    assert _read_resp(FakeSocket(b"+OK\r\n")) == "OK"
    assert _read_resp(FakeSocket(b":7\r\n")) == 7
    assert _read_resp(FakeSocket(b"$5\r\nhello\r\n")) == "hello"
    assert _read_resp(FakeSocket(b"$-1\r\n")) is None
    assert _read_resp(FakeSocket(b"*-1\r\n")) is None
    assert _read_resp(FakeSocket(b"*2\r\n+OK\r\n:3\r\n")) == ["OK", 3]

    with pytest.raises(RuntimeError, match="ERR bad"):
        _read_resp(FakeSocket(b"-ERR bad\r\n"))
    with pytest.raises(RuntimeError, match="connection closed"):
        _read_resp(FakeSocket(b""))
    with pytest.raises(RuntimeError, match="unexpected redis response prefix"):
        _read_resp(FakeSocket(b"?"))
    with pytest.raises(RuntimeError, match="expected redis string response"):
        _read_resp_string(FakeSocket(b":1\r\n"))


def test_resp_reader_reports_closed_line_and_bulk_string():
    with pytest.raises(RuntimeError, match="reading line"):
        _read_resp(FakeSocket(b"+OK"))
    with pytest.raises(RuntimeError, match="bulk string"):
        _read_resp(FakeSocket(b"$5\r\nhe"))


def test_redis_publisher_sends_xadd_and_execute_commands(monkeypatch):
    first = FakeSocket(b"+1778682000000-0\r\n")
    second = FakeSocket(b"+PONG\r\n")
    sockets = [first, second]

    def fake_create_connection(address, timeout):
        assert address == ("127.0.0.1", 6379)
        assert timeout == 2.0
        return sockets.pop(0)

    monkeypatch.setattr("argus_services.streams.socket.create_connection", fake_create_connection)
    publisher = RedisStreamPublisher(maxlen=99)
    event = make_event("activity.browser_page", {"title": "Redis"}, source_platform="macos")

    redis_id = publisher.publish("stream:raw:macos", event)
    pong = publisher.execute(["PING"])

    assert redis_id == "1778682000000-0"
    assert pong == "PONG"
    assert b"XADD" in first.sent
    assert b"MAXLEN" in first.sent
    assert b"PING" in second.sent


def test_consumer_edge_paths_for_groups_ack_pending_reclaim_and_dlq():
    executor = RecordingExecutor(
        [
            RuntimeError("NOAUTH"),
            [],
            [],
            "1778682000001-0",
            1,
        ]
    )
    consumer = RedisStreamConsumer("cg", "worker", executor=executor, max_attempts=3)

    with pytest.raises(RuntimeError, match="NOAUTH"):
        consumer.ensure_group("stream:raw:macos")
    assert consumer.ack("stream:raw:macos") == 0
    assert consumer.pending("stream:raw:macos") == []
    assert consumer.reclaim_stale("stream:raw:macos", min_idle_ms=1000) == []
    assert consumer.dead_letter("stream:raw:macos", "1-0", reason="bad") == ["1778682000001-0"]
    assert consumer.dead_letter("stream:raw:macos", reason="bad") == []
    assert executor.commands[-2][:3] == ["XADD", DLQ_STREAM, "*"]
    assert executor.commands[-1] == ["XACK", "stream:raw:macos", "cg", "1-0"]


def test_consumer_defaults_to_publisher_executor():
    publisher = RedisStreamPublisher()
    consumer = RedisStreamConsumer("cg", "worker", publisher=publisher)

    assert consumer.executor is publisher


def test_stream_parser_helpers_cover_empty_pairs_and_pending_rows():
    assert parse_xreadgroup([]) == []
    assert parse_xreadgroup(
        [["stream:raw:macos", [["1-0", ["event_id", "evt", "event_type", "activity"]]]]]
    ) == [StreamMessage("stream:raw:macos", "1-0", {"event_id": "evt", "event_type": "activity"})]
    assert parse_xpending([["1-0", "worker", "42", "2"]]) == [
        {"redis_id": "1-0", "consumer": "worker", "idle_ms": 42, "delivery_count": 2}
    ]
    assert fields_from_pairs(["a", "b", "c", 3]) == {"a": "b", "c": "3"}
