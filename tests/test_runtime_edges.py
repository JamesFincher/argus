from datetime import datetime, timezone
import sys
from types import SimpleNamespace

import pytest

from argus_services import event_gateway, storage_worker
from argus_services.audit import InMemoryAuditLog
from argus_services.dashboard import dashboard_state, redis_status, sensor_health_state
from argus_services.event_gateway import (
    EventGateway,
    audit_log_from_env,
    store_from_env,
)
from argus_services.events import make_event
from argus_services.graph import (
    DisabledGraphAdapter,
    GraphConfig,
    Neo4jGraphAdapter,
    graph_from_config,
)
from argus_services.metrics import MetricsRegistry
from argus_services.mcp import LocalMCPServer, ToolRegistry, local_workflow_patterns
from argus_services.perception import PerceptionWorker, TemplateSummarizer
from argus_services.policy import RedactionPolicy, _looks_like_card
from argus_services.purge import (
    host_values,
    normalize_scope,
    scope_matches_event,
    tombstone_raw_event_details,
)
from argus_services.retrieval import (
    HashEmbeddingModel,
    InMemoryNoteIndex,
    LanceDBNoteIndex,
    cosine_similarity,
    note_from_event,
    note_from_record,
    note_matches_scope,
    sql_quote,
    table_rows,
)
from argus_services.sqlite_store import SQLiteAuditLog, SQLiteTimelineStore
from argus_services.streams import RAW_STREAMS
from argus_services.storage_worker import (
    RedisToSQLiteWorker,
    StorageWorkerConfig,
    worker_from_config,
)
from argus_services.store import InMemoryEventStore


class FakeSession:
    def __init__(self):
        self.runs = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def run(self, query, **kwargs):
        self.runs.append((query, kwargs))
        return [
            {
                "from_event_type": "activity.frontmost_window",
                "to_event_type": "activity.browser_page",
                "count": 3,
            }
        ]


class FakeDriver:
    def __init__(self):
        self.sessions = []

    def session(self, **kwargs):
        session = FakeSession()
        self.sessions.append((kwargs, session))
        return session


class FakeStore:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeWorker:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.ensure_count = 0
        self.calls = []
        self.store = FakeStore()

    def ensure_groups(self):
        self.ensure_count += 1

    def process_once(self, *, count, block_ms):
        self.calls.append((count, block_ms))
        if not self.outputs:
            raise StopIteration
        return self.outputs.pop(0)


class FakePandas:
    def to_dict(self, mode):
        assert mode == "records"
        return [{"note_id": "n1", "summary": "Vendor", "sensitivity": "low"}]


class FakePandasTable:
    def to_pandas(self):
        return FakePandas()


class EmptyLanceDatabase:
    def table_names(self):
        return []


class ExistingLanceDatabase:
    def __init__(self):
        self.table = AppendableLanceTable()

    def table_names(self):
        return ["argus_notes"]

    def open_table(self, name):
        assert name == "argus_notes"
        return self.table


class AppendableLanceTable:
    def __init__(self):
        self.rows = []

    def add(self, rows):
        self.rows.extend(rows)

    def search(self, _embedding):
        return FakeLanceQuery(self.rows)

    def to_list(self):
        return list(self.rows)


class FakeLanceQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.count = len(rows)

    def limit(self, count):
        self.count = count
        return self

    def to_list(self):
        return self.rows[: self.count]


class DeleteOnlyTable:
    def __init__(self):
        self.deleted = []

    def to_list(self):
        return [
            {
                "note_id": "note-1",
                "source_event_ids": [],
                "summary": "Vendor scope",
                "sensitivity": "low",
                "redactions_applied": [],
                "embedding": [],
            }
        ]

    def delete(self, expression):
        self.deleted.append(expression)


class RecordingPublisher:
    def publish(self, _stream, _event):
        return "1778682000000-0"


class BrokenRedisStatus:
    def execute(self, _command):
        raise RuntimeError("redis down")


class EnabledGraph:
    enabled = True

    def __init__(self):
        self.forgot = []

    def workflow_patterns(self, *, limit):
        return {"patterns": [{"from_event_type": "a", "to_event_type": "b", "count": limit}]}

    def forget_scope(self, scope):
        self.forgot.append(scope)
        return 4


class StaticNoteIndex:
    def search(self, _query, *, top_k):
        assert top_k == 1
        return [
            note_from_record({"note_id": "note-1", "summary": "First", "sensitivity": "low"}),
            note_from_record({"note_id": "note-2", "summary": "Second", "sensitivity": "low"}),
        ]


def test_event_gateway_forget_export_metrics_and_env_paths(tmp_path, monkeypatch):
    event = make_event(
        "activity.browser_page",
        {"summary": "Vendor page alex@example.com", "domain": "vendor.example"},
    )
    gateway = EventGateway(metrics=MetricsRegistry(), publisher=RecordingPublisher())
    gateway.ingest(event)
    export = gateway.export_session_brief(limit=5)
    forgot = gateway.forget_scope("vendor.example")

    assert "[REDACTED_EMAIL]" in export["brief"]
    assert forgot["events_removed"] == 1
    assert gateway.metrics.values["events_ingested_total"] == 1
    assert gateway.metrics.values["sensor_bytes_written_total"] > 0
    assert gateway.store.get(event.event_id) is None

    monkeypatch.delenv("ARGUS_TIMELINE_DB_PATH", raising=False)
    assert store_from_env().__class__.__name__ == "InMemoryEventStore"
    assert isinstance(audit_log_from_env(), InMemoryAuditLog)

    db_path = tmp_path / "timeline.db"
    monkeypatch.setenv("ARGUS_TIMELINE_DB_PATH", str(db_path))
    store = store_from_env()
    audit_log = audit_log_from_env()
    try:
        assert isinstance(store, SQLiteTimelineStore)
        assert isinstance(audit_log, SQLiteAuditLog)
    finally:
        store.close()
        audit_log.close()

    original_run = event_gateway.run
    calls = []
    monkeypatch.setattr(event_gateway, "run", lambda **kwargs: calls.append(kwargs))
    assert event_gateway.main(["--host", "localhost", "--port", "9999"]) == 0
    assert calls == [{"host": "localhost", "port": 9999}]

    class StoppingHTTPServer:
        def __init__(self, address, handler):
            self.address = address
            self.handler = handler

        def serve_forever(self):
            raise StopIteration

    monkeypatch.setattr(event_gateway, "ThreadingHTTPServer", StoppingHTTPServer)
    monkeypatch.setattr(event_gateway, "store_from_env", lambda: InMemoryEventStore())
    monkeypatch.setattr(event_gateway, "audit_log_from_env", lambda: InMemoryAuditLog())
    with pytest.raises(StopIteration):
        original_run(host="127.0.0.1", port=0)


def test_dashboard_redis_errors_and_paused_health_rollups():
    assert redis_status(BrokenRedisStatus())["ping"] == "error"

    older_permission = make_event(
        "system.permission_state",
        {"accessibility_trusted": False},
        observed_at="2026-05-13T14:00:00Z",
    )
    newer_permission = make_event(
        "system.permission_state",
        {"accessibility_trusted": True},
        observed_at="2026-05-13T14:01:00Z",
    )
    heartbeat = make_event(
        "system.sensor_heartbeat",
        {"sensor_id": "argus-sensor-mac"},
        sensor_id="argus-sensor-mac",
        source_platform="macos",
        observed_at="2026-05-13T14:01:00Z",
    )

    health = sensor_health_state(
        [newer_permission, older_permission, heartbeat],
        paused_scopes={"macos"},
        now=datetime(2026, 5, 13, 14, 2, tzinfo=timezone.utc),
    )

    assert health["heartbeats"][0]["status"] == "paused"
    assert health["permissions"]["macos"]["payload"] == {"accessibility_trusted": True}

    state = dashboard_state(
        store=InMemoryEventStore([heartbeat]),
        audit_log=InMemoryAuditLog(),
        policy=RedactionPolicy(),
        publisher=BrokenRedisStatus(),
        paused_scopes={"macos"},
    )
    assert state["redis"]["error"] == "redis down"


def test_in_memory_store_prefix_forget_and_text_summary_edges():
    keep = make_event("system.sensor_heartbeat", {"summary": "heartbeat"})
    remove = make_event("activity.browser_page", {"summary": "Vendor page"})
    long_text = make_event("activity.focused_field", {"text": "x" * 220})
    store = InMemoryEventStore([keep, remove, long_text])

    assert [event.event_id for event in store.recent(limit=2, event_type_prefix="activity.")] == [
        long_text.event_id,
        remove.event_id,
    ]
    assert store.forget_scope("missing") == 0
    assert store.get(keep.event_id) is keep
    assert store.summary_for(long_text) == "x" * 180


def test_tool_registry_rejects_duplicate_and_unknown_tools():
    registry = ToolRegistry()
    registry.register("one", "desc", lambda: {"ok": True})

    with pytest.raises(ValueError, match="already registered"):
        registry.register("one", "desc", lambda: {"ok": True})
    with pytest.raises(KeyError, match="unknown tool"):
        registry.call("missing")


def test_mcp_raw_paths_graph_enabled_and_store_summaries():
    graph = EnabledGraph()
    store = InMemoryEventStore()
    server = LocalMCPServer(
        store=store,
        policy=RedactionPolicy(approval_token="ok"),
        graph=graph,
    )
    event = server.add_event(make_event("activity.focused_field", {"text": "hello"}))

    missing = server.call_tool("sensor_expand_event", event_id="missing")
    full = server.call_tool(
        "sensor_expand_event",
        event_id=event.event_id,
        raw_mode="full",
        approval_token="ok",
    )
    patterns = server.call_tool("sensor_find_workflow_patterns", limit=7)
    forgotten = server.call_tool("sensor_forget_scope", scope="hello")

    assert missing["ok"] is False
    assert missing["error"] == "event not found"
    assert full["ok"] is True
    assert full["raw_mode"] == "full"
    assert patterns["source"] == "neo4j"
    assert patterns["patterns"][0]["count"] == 7
    assert forgotten["graph_nodes_removed"] == 4
    assert graph.forgot == ["hello"]

    title = make_event("activity.browser_page", {"title": "Pricing", "domain": "vendor.example"})
    app = make_event("activity.frontmost_window", {"app": {"bundle_id": "com.example.App"}})
    text = make_event("activity.focused_field", {"text": "  "})
    fallback = make_event("activity.unknown", {})

    assert store.summary_for(title) == "Pricing on vendor.example"
    assert store.summary_for(app) == "activity.frontmost_window from com.example.App"
    assert store.summary_for(text) == "activity.focused_field from argus"
    assert store.summary_for(fallback) == "activity.unknown from argus"

    pause = server.call_tool("sensor_pause_scope", scope="macos")
    brief = server.call_tool("sensor_export_session_brief", limit=1)
    limited = LocalMCPServer(note_index=StaticNoteIndex()).call_tool(
        "sensor_timeline_search",
        query="anything",
        limit=1,
    )

    assert pause["status"] == "pause_requested"
    assert brief["ok"] is True
    assert len(limited["matches"]) == 1

    fallback_search = LocalMCPServer(note_index=object())
    fallback_search.add_event(make_event("activity.browser_page", {"summary": "Vendor A"}))
    fallback_search.add_event(make_event("activity.browser_page", {"summary": "Vendor B"}))
    limited_fallback = fallback_search.call_tool("sensor_timeline_search", query="vendor", limit=1)
    assert len(limited_fallback["matches"]) == 1


def test_local_workflow_patterns_skip_system_events():
    patterns = local_workflow_patterns(
        [
            make_event("activity.a", {}, observed_at="2026-05-13T14:00:00Z"),
            make_event("system.sensor_heartbeat", {}, observed_at="2026-05-13T14:01:00Z"),
            make_event("activity.b", {}, observed_at="2026-05-13T14:02:00Z"),
            make_event("activity.c", {}, observed_at="2026-05-13T14:03:00Z"),
        ]
    )

    assert patterns == [
        {"from_event_type": "activity.b", "to_event_type": "activity.c", "count": 1}
    ]


def test_metrics_registry_rejects_unknown_and_wrong_type_updates():
    registry = MetricsRegistry()

    with pytest.raises(KeyError, match="unknown metric"):
        registry.increment("missing")
    with pytest.raises(KeyError, match="unknown metric"):
        registry.set_gauge("missing", 1)
    with pytest.raises(ValueError, match="not a gauge"):
        registry.set_gauge("events_ingested_total", 1)


def test_graph_config_adapters_and_neo4j_query(monkeypatch):
    monkeypatch.setenv("ARGUS_NEO4J_ENABLED", "yes")
    monkeypatch.setenv("ARGUS_NEO4J_URI", "bolt://127.0.0.1:9999")
    monkeypatch.setenv("ARGUS_NEO4J_DATABASE", "argus")
    config = GraphConfig.from_env()

    assert config.enabled is True
    assert config.uri == "bolt://127.0.0.1:9999"
    assert config.database == "argus"
    assert isinstance(graph_from_config(GraphConfig(enabled=False)), DisabledGraphAdapter)

    constructed = []

    class FakeNeo4jGraphAdapter:
        def __init__(self, config):
            constructed.append(config)
            self.enabled = True

    monkeypatch.setattr("argus_services.graph.Neo4jGraphAdapter", FakeNeo4jGraphAdapter)
    enabled_adapter = graph_from_config(GraphConfig(enabled=True, uri="bolt://patched"))
    assert enabled_adapter.enabled is True
    assert constructed[0].uri == "bolt://patched"

    lazy_driver = FakeDriver()
    monkeypatch.setitem(
        sys.modules,
        "neo4j",
        SimpleNamespace(GraphDatabase=SimpleNamespace(driver=lambda uri: lazy_driver)),
    )
    lazy_adapter = Neo4jGraphAdapter(config=GraphConfig(enabled=True, uri="bolt://lazy"))
    assert lazy_adapter.driver is lazy_driver

    disabled = DisabledGraphAdapter(reason="off")
    assert disabled.workflow_patterns(limit=1) == {"enabled": False, "reason": "off", "patterns": []}
    assert disabled.forget_scope("all") == 0

    driver = FakeDriver()
    adapter = Neo4jGraphAdapter(config=config, driver=driver)
    result = adapter.workflow_patterns(limit=3)

    assert result["enabled"] is True
    assert result["patterns"][0]["count"] == 3
    assert driver.sessions[0][0] == {"database": "argus"}
    assert driver.sessions[0][1].runs[0][1] == {"limit": 3}
    assert adapter.forget_scope("vendor") == 0


def test_storage_worker_factory_main_and_idle_loop(tmp_path, monkeypatch, capsys):
    config = StorageWorkerConfig(
        timeline_db_path=str(tmp_path / "timeline.db"),
        streams=("stream:raw:macos",),
    )
    worker = worker_from_config(config)
    try:
        assert isinstance(worker, RedisToSQLiteWorker)
        assert worker.consumer.group == "cg-storage"
        assert worker.streams == ["stream:raw:macos"]
    finally:
        worker.store.close()

    original_run_worker = storage_worker.run_worker
    fake_worker = FakeWorker([2])
    monkeypatch.setattr(storage_worker, "worker_from_config", lambda _config: fake_worker)
    monkeypatch.setattr(
        storage_worker,
        "run_worker",
        lambda worker, **_kwargs: worker.process_once(count=9, block_ms=8),
    )
    assert storage_worker.main(["--once", "--no-ensure-groups"]) == 0
    assert "processed=2" in capsys.readouterr().out
    assert fake_worker.store.closed is True

    sleeper_worker = FakeWorker([0])

    def stop_sleep(seconds):
        assert seconds == 0.5
        raise StopIteration

    monkeypatch.setattr(storage_worker.time, "sleep", stop_sleep)
    with pytest.raises(StopIteration):
        original_run_worker(
            sleeper_worker,
            count=1,
            block_ms=0,
            idle_sleep_seconds=0.5,
            once=False,
            ensure_groups=False,
        )
    assert sleeper_worker.calls == [(1, 0)]

    default_stream_worker = RedisToSQLiteWorker(consumer=object(), store=FakeStore())
    assert default_stream_worker.streams == list(RAW_STREAMS.values())


def test_retrieval_edges_for_embeddings_tables_and_records(tmp_path, monkeypatch):
    assert HashEmbeddingModel(dimension=4).embed("   ") == [0.0, 0.0, 0.0, 0.0]
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert sql_quote("vendor's") == "'vendor''s'"
    assert table_rows(FakePandasTable()) == [{"note_id": "n1", "summary": "Vendor", "sensitivity": "low"}]
    assert table_rows(object()) == []
    assert note_from_record({"note_id": "n1", "summary": "S", "sensitivity": "low"}).source_event_ids == []
    assert note_from_event(make_event("activity.browser_page", {"summary": "no"}), HashEmbeddingModel()) is None
    assert note_from_event(
        make_event("perception.note", {"text": "missing summary"}),
        HashEmbeddingModel(),
    ) is None
    note = note_from_event(
        make_event("perception.note", {"summary": "x", "evidence_event_ids": "bad", "redactions_applied": "bad"}),
        HashEmbeddingModel(dimension=4),
    )
    assert note is not None
    assert note.source_event_ids == []
    assert note.redactions_applied == []

    index = InMemoryNoteIndex()
    assert index.search("", top_k=1) == []
    empty_index = LanceDBNoteIndex(path="/tmp/unused", database=EmptyLanceDatabase())
    assert empty_index.search("vendor") == []
    assert empty_index.forget_scope("vendor") == 0

    lazy_path = tmp_path / "lance"
    monkeypatch.setitem(
        sys.modules,
        "lancedb",
        SimpleNamespace(connect=lambda path: EmptyLanceDatabase()),
    )
    lazy_index = LanceDBNoteIndex(path=lazy_path)
    assert lazy_index.table is None
    assert lazy_path.is_dir()

    existing_index = LanceDBNoteIndex(path="/tmp/unused", database=ExistingLanceDatabase())
    note_event = make_event("perception.note", {"summary": "Vendor note"})
    assert existing_index.add_event(note_event) is not None
    assert existing_index.search("Vendor", top_k=1)[0].note_id == note_event.event_id
    assert existing_index.forget_scope("missing") == 0

    table = DeleteOnlyTable()
    lancedb_index = LanceDBNoteIndex(path="/tmp/unused", database=object(), table=table)
    assert lancedb_index.forget_scope("vendor") == 1
    assert table.deleted == ["note_id IN ('note-1')"]
    exact = note_from_record({"note_id": "n2", "summary": "Exact", "sensitivity": "low"})
    assert note_matches_scope(exact, "all") is True
    assert note_matches_scope(exact, "n2") is True

    class FakeDigest:
        def __init__(self, sign_byte):
            self.sign_byte = sign_byte

        def digest(self):
            return b"\0\0\0\0" + bytes([self.sign_byte]) + b"\0\0\0"

    signs = iter([0, 1])
    monkeypatch.setattr(
        "argus_services.retrieval.hashlib.blake2b",
        lambda *_args, **_kwargs: FakeDigest(next(signs)),
    )
    assert HashEmbeddingModel(dimension=1).embed("one two") == [0.0]


def test_perception_template_branches_and_compaction():
    summarizer = TemplateSummarizer(max_chars=80)

    assert summarizer.summarize(
        make_event("activity.frontmost_window", {"app": {"name": "Safari"}, "title": "Pricing"})
    ) == "User focused Safari window Pricing"
    assert summarizer.summarize(
        make_event("activity.browser_page", {"browser": {"domain": "vendor.example"}})
    ) == "User viewed a page on vendor.example"
    assert summarizer.summarize(make_event("activity.focused_field", {"text": "hello"})) == "hello"
    assert summarizer.summarize(make_event("activity.unknown", {})) == "activity.unknown from argus"
    assert TemplateSummarizer(max_chars=8).summarize(
        make_event("perception.note", {"summary": "this summary is too long"})
    ) == "this sum..."
    assert summarizer.summarize(make_event("activity.frontmost_window", {"app": "broken"})) == (
        "User focused an app"
    )

    normalized = PerceptionWorker().normalize(
        make_event("Activity Mixed", {"Nested Key": ["  A   B  ", {"Number": 7}]})
    )
    assert normalized.event_type == "activity_mixed"
    assert normalized.payload == {"nested_key": ["A B", {"number": 7}]}


def test_policy_low_raw_access_blocked_apps_and_card_validation():
    policy = RedactionPolicy(approval_token="ok")
    low = make_event("activity.browser_page", {"title": "Docs"})
    blocked = make_event("activity.frontmost_window", {"app": {"bundle_id": "com.apple.keychainaccess"}})
    card = make_event("activity.focused_field", {"text": "card 4242 4242 4242 4242 fake 1234 5678 9012"})

    assert policy.evaluate_raw_access(low).allowed is True
    assert policy.evaluate_surface(blocked).allowed is False
    redacted = policy.redact_event(card)

    assert "[REDACTED_CARD]" in redacted.payload["text"]
    assert "1234 5678 9012" in redacted.payload["text"]
    assert _looks_like_card("123") is False
    assert _looks_like_card("4012 8888 8888 1881") is True


def test_purge_scope_matching_and_tombstone_edges():
    event = make_event(
        "activity.browser_page",
        {
            "url": "https://www.sub.vendor.example/path",
            "nested": [{"project": "Alpha"}, 7, True],
        },
        tags=["tagged"],
    )

    assert normalize_scope("  WWW.Vendor.Example  ") == "vendor.example"
    assert host_values("https://www.sub.vendor.example/path") == {
        "sub.vendor.example",
        "vendor.example",
    }
    assert scope_matches_event(event, "all") is True
    assert scope_matches_event(event, "vendor.example") is True
    assert scope_matches_event(event, "alpha") is True
    assert scope_matches_event(event, "missing") is False
    assert scope_matches_event(make_event("activity.browser_page", {"host": "deep.vendor.example"}), "vendor.example")
    assert scope_matches_event(make_event("activity.browser_page", {}, tags=["   "]), "missing") is False
    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_scope("  ")

    details, changed = tombstone_raw_event_details({"raw_event": "bad"}, "vendor")
    assert changed is False
    assert details == {"raw_event": "bad"}
    details, changed = tombstone_raw_event_details({"raw_event": {"event_id": "broken"}}, "vendor")
    assert changed is False
    details, changed = tombstone_raw_event_details({"raw_event": event.to_dict()}, "other")
    assert changed is False
