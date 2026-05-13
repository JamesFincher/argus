from argus_services.canonicalizer import SignalCanonicalizer, canonical_group_key
from argus_services.events import make_event
from argus_services.perception import PerceptionWorker


def overlapping(event_type, payload=None, *, event_id, dedupe_key="sha256:shared", observed_at="2026-05-13T18:00:00Z"):
    return make_event(
        event_type,
        payload or {},
        event_id=event_id,
        dedupe_key=dedupe_key,
        observed_at=observed_at,
        ingested_at=observed_at,
    )


def test_canonicalizer_uses_payload_scope_before_dedupe_key():
    event = overlapping(
        "activity.browser_page",
        {"canonical_scope": " Vendor.Example/Plan "},
        event_id="browser",
        dedupe_key="sha256:other",
    )

    assert canonical_group_key(event) == "canonical_scope:vendor.example/plan"

    no_scope = overlapping("activity.browser_page", event_id="no-scope", dedupe_key=None)
    no_scope.dedupe_key = None
    assert canonical_group_key(no_scope) == "event:no-scope"


def test_canonicalizer_applies_spec_precedence_for_overlapping_signals():
    cases = [
        ("activity.browser_page", "activity.screen_frame_ocr"),
        ("activity.focused_field", "activity.screen_frame_ocr"),
        ("activity.mail_metadata", "activity.screen_frame_ocr"),
        ("activity.calendar_item", "activity.screen_frame_ocr"),
        ("activity.health_summary", "activity.watch_annotation"),
    ]
    canonicalizer = SignalCanonicalizer()

    for preferred_type, suppressed_type in cases:
        preferred = overlapping(preferred_type, event_id=f"preferred-{preferred_type}")
        suppressed = overlapping(suppressed_type, event_id=f"suppressed-{suppressed_type}")

        result = canonicalizer.canonicalize([suppressed, preferred])

        assert [event.event_id for event in result.selected] == [preferred.event_id]
        assert result.suppressed_event_ids == [suppressed.event_id]
        assert preferred_type in result.suppressed[0].reason
        assert suppressed_type in result.suppressed[0].reason


def test_canonicalizer_keeps_unrelated_events_and_prefers_newer_tie():
    older = overlapping(
        "activity.browser_page",
        event_id="older",
        observed_at="2026-05-13T18:00:00Z",
    )
    newer = overlapping(
        "activity.browser_page",
        event_id="newer",
        observed_at="2026-05-13T18:00:01Z",
    )
    unrelated = overlapping(
        "activity.screen_frame_ocr",
        event_id="unrelated",
        dedupe_key="sha256:other",
    )

    result = SignalCanonicalizer().canonicalize([older, unrelated, newer])

    assert [event.event_id for event in result.selected] == ["unrelated", "newer"]
    assert result.suppressed_event_ids == ["older"]


def test_perception_worker_batch_canonicalizes_before_emitting_notes():
    browser = overlapping("activity.browser_page", {"title": "Pricing"}, event_id="browser")
    ocr = overlapping("activity.screen_frame_ocr", {"text": "Pricing"}, event_id="ocr")

    outputs = PerceptionWorker().process_batch([ocr, browser])

    assert len(outputs) == 1
    assert outputs[0].source_event.event_id == "browser"
    assert outputs[0].derived_note is not None
    assert outputs[0].derived_note.payload["evidence_event_ids"] == ["browser"]
