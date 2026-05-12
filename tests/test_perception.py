from argus_services.events import make_event
from argus_services.perception import PerceptionWorker


def test_perception_normalizes_before_redaction_and_summary():
    event = make_event(
        "Activity.Frontmost Window",
        {
            "App Name": "Safari",
            "Window Title": "  Vendor   Quote  ",
            "Summary": "  Compared pricing   for alex@example.com  ",
        },
    )

    output = PerceptionWorker().process(event)

    assert output.blocked_event is None
    assert output.derived_note is not None
    assert output.source_event.event_type == "activity.frontmost_window"
    assert output.redacted_event.payload["summary"] == "Compared pricing for [REDACTED_EMAIL]"
    assert output.derived_note.payload["summary"] == "Compared pricing for [REDACTED_EMAIL]"
    assert "alex@example.com" not in output.derived_note.payload["summary"]
    assert output.derived_note.payload["evidence_event_ids"] == [event.event_id]
    assert output.derived_note.raw_scope == "none"


def test_perception_blocks_sensitive_surfaces_without_derived_note():
    event = make_event(
        "activity.browser_page",
        {
            "domain": "accounts.google.com",
            "title": "Sign in",
            "text": "verification code 123456",
        },
    )

    output = PerceptionWorker().process(event)

    assert output.derived_note is None
    assert output.blocked_event is not None
    assert output.blocked_event.event_type == "policy.blocked"
    assert output.blocked_event.sensitivity == "blocked"
    assert output.blocked_event.raw_scope == "none"
    assert output.blocked_event.payload["source_event_id"] == event.event_id
    assert "blocked domain surface" in output.blocked_event.payload["reason"]
    assert output.stream == "stream:policy:blocked"


def test_perception_summary_uses_redacted_payload_for_text_events():
    event = make_event(
        "activity.focused_field",
        {"text": "Use Bearer abcdefghijklmnopqrstuvwxyz in terminal"},
    )

    output = PerceptionWorker().process(event)

    assert output.derived_note is not None
    summary = output.derived_note.payload["summary"]
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in summary
    assert "[REDACTED_BEARER_TOKEN]" in summary
    assert output.redacted_event.sensitivity == "high"
    assert output.derived_note.sensitivity == "high"


def test_perception_policy_blocks_private_keys():
    event = make_event(
        "activity.focused_field",
        {"text": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"},
    )

    output = PerceptionWorker().process(event)

    assert output.derived_note is None
    assert output.blocked_event is not None
    assert output.blocked_event.payload["source_event_id"] == event.event_id
    assert "private_key" in output.blocked_event.payload["redactions_applied"]
