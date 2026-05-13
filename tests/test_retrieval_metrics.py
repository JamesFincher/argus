import json
from pathlib import Path

from argus_services.events import make_event
from argus_services.metrics import METRIC_NAMES, MetricsRegistry
from argus_services.retrieval import HashEmbeddingModel, InMemoryNoteIndex, LanceDBNoteIndex


ROOT = Path(__file__).resolve().parents[1]


def test_lancedb_schema_excludes_raw_payloads_and_defaults_top_five():
    schema = json.loads((ROOT / "storage/lancedb/schemas/notes.json").read_text())

    assert schema["table"] == "argus_notes"
    assert schema["policy"]["raw_payloads_allowed"] is False
    assert schema["policy"]["blocked_sensitivity_excluded"] is True
    assert schema["policy"]["top_k_default"] == 5
    assert "embedding" in {column["name"] for column in schema["columns"]}


def test_note_index_retrieves_policy_safe_notes_only():
    index = InMemoryNoteIndex()
    note = make_event(
        "perception.note",
        {
            "summary": "Compared vendor pricing",
            "evidence_event_ids": ["source-1"],
            "redactions_applied": ["email"],
        },
        sensitivity="medium",
    )
    blocked = make_event(
        "perception.note",
        {"summary": "blocked password text", "evidence_event_ids": ["source-2"]},
        sensitivity="blocked",
    )

    assert index.add_event(note) is not None
    assert index.add_event(blocked) is None
    results = index.search("vendor pricing")

    assert len(results) == 1
    assert results[0].summary == "Compared vendor pricing"
    assert results[0].source_event_ids == ["source-1"]
    assert len(results[0].embedding) == 768


def test_note_index_forget_scope_removes_matching_notes():
    index = InMemoryNoteIndex()
    kept = make_event("perception.note", {"summary": "Deployment checklist"})
    purged = make_event("perception.note", {"summary": "Vendor.example pricing"})

    index.add_event(kept)
    index.add_event(purged)

    assert index.forget_scope("vendor.example") == 1
    assert [note.summary for note in index.search("", top_k=5)] == ["Deployment checklist"]


def test_hash_embedding_model_is_deterministic_and_normalized():
    model = HashEmbeddingModel(dimension=32)

    left = model.embed("vendor pricing")
    right = model.embed("vendor pricing")

    assert left == right
    assert round(sum(value * value for value in left), 6) == 1.0


def test_lancedb_note_index_persists_policy_safe_records_only(tmp_path):
    database = FakeLanceDatabase()
    index = LanceDBNoteIndex(path=tmp_path, database=database)
    note = make_event(
        "perception.note",
        {
            "summary": "Compared vendor pricing",
            "evidence_event_ids": ["source-1"],
            "redactions_applied": ["email"],
            "raw_payload": "should not be stored",
        },
        sensitivity="medium",
    )
    blocked = make_event(
        "perception.note",
        {"summary": "blocked password text", "evidence_event_ids": ["source-2"]},
        sensitivity="blocked",
    )

    assert index.add_event(note) is not None
    assert index.add_event(blocked) is None
    rows = database.tables["argus_notes"].rows
    results = index.search("vendor pricing")

    assert len(rows) == 1
    assert "raw_payload" not in rows[0]
    assert rows[0]["summary"] == "Compared vendor pricing"
    assert results[0].note_id == note.event_id
    assert index.forget_scope("vendor") == 1
    assert database.tables["argus_notes"].rows == []


def test_metrics_registry_renders_required_prometheus_names():
    registry = MetricsRegistry()
    registry.increment("events_ingested_total", 2)
    registry.increment("policy_blocks_total")
    output = registry.render_prometheus()

    assert {
        "events_ingested_total",
        "redactions_applied_total",
        "mcp_tool_calls_total",
        "policy_blocks_total",
    } <= METRIC_NAMES
    assert "argus_events_ingested_total 2" in output
    assert "argus_policy_blocks_total 1" in output


class FakeLanceDatabase:
    def __init__(self):
        self.tables = {}

    def table_names(self):
        return list(self.tables)

    def create_table(self, name, data):
        table = FakeLanceTable(data)
        self.tables[name] = table
        return table

    def open_table(self, name):
        return self.tables[name]


class FakeLanceTable:
    def __init__(self, rows):
        self.rows = list(rows)

    def add(self, rows):
        self.rows.extend(rows)

    def search(self, _embedding):
        return FakeLanceQuery(self.rows)

    def to_list(self):
        return list(self.rows)

    def delete_note_ids(self, note_ids):
        self.rows = [
            row for row in self.rows
            if row["note_id"] not in set(note_ids)
        ]


class FakeLanceQuery:
    def __init__(self, rows):
        self.rows = rows
        self.count = 5

    def limit(self, count):
        self.count = count
        return self

    def to_list(self):
        return list(self.rows[: self.count])
