from datetime import datetime, timezone
from uuid import UUID

from argus_services.events import make_event, sortable_event_id


def test_sortable_event_ids_are_uuid7_and_lexically_ordered():
    same_tick_ids = [
        sortable_event_id(datetime(2026, 5, 13, 18, 0, tzinfo=timezone.utc))
        for _ in range(3)
    ]
    later_id = sortable_event_id(datetime(2026, 5, 13, 18, 0, 0, 1000, tzinfo=timezone.utc))

    assert same_tick_ids == sorted(same_tick_ids)
    assert same_tick_ids[-1] < later_id
    assert UUID(same_tick_ids[0]).version == 7


def test_sortable_event_id_accepts_naive_datetime_as_utc():
    event_id = sortable_event_id(datetime(2026, 5, 13, 18, 0))

    assert UUID(event_id).version == 7


def test_default_event_envelope_uses_sortable_event_ids():
    first = make_event("activity.browser_page", {"summary": "first"})
    second = make_event("activity.browser_page", {"summary": "second"})

    assert UUID(first.event_id).version == 7
    assert first.event_id < second.event_id
