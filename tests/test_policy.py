from argus_services.events import make_event
from argus_services.policy import RedactionPolicy


def test_redacts_credentials_and_personal_identifiers():
    event = make_event(
        "activity.focused_field",
        {
            "text": "email james@example.com token sk-abcdefghijklmnopqrstuvwxyz phone 415-555-1212",
        },
    )

    redacted = RedactionPolicy().redact_event(event)

    text = redacted.payload["text"]
    assert "james@example.com" not in text
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in text
    assert "415-555-1212" not in text
    assert "[REDACTED_EMAIL]" in text
    assert "[REDACTED_API_KEY]" in text
    assert redacted.sensitivity == "high"
    assert {item.kind for item in redacted.redactions} >= {"email", "openai_api_key", "phone"}


def test_sensitive_surface_blocks_raw_surface():
    event = make_event(
        "activity.browser_page",
        {"domain": "accounts.google.com", "title": "Sign in"},
    )

    decision = RedactionPolicy(approval_token="ok").evaluate_raw_access(
        event,
        approval_token="ok",
        raw_mode="full",
    )

    assert not decision.allowed
    assert decision.sensitivity == "blocked"
