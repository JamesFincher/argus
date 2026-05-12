import json
from pathlib import Path

from argus_services.events import make_event
from argus_services.metrics import METRIC_NAMES, MetricsRegistry
from argus_services.retrieval import InMemoryNoteIndex


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
