from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.concierge import parse_intent_prompt, sequence_itinerary


@dataclass
class _Event:
    id: int
    title: str
    start_at: datetime
    end_at: datetime | None
    source_tier: int
    venue_name: str | None = None
    external_url: str | None = None


def test_parse_intent_extracts_fields() -> None:
    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    parsed = parse_intent_prompt("Plan a date night in Oakland this Saturday", now=now)

    assert parsed.intent == "date_night"
    assert parsed.geography == "oakland"
    assert parsed.timeframe_label == "this_saturday"
    assert parsed.window_start < parsed.window_end


def test_itinerary_sequencing_with_travel_buffers() -> None:
    base = datetime(2026, 3, 7, 20, 0, tzinfo=timezone.utc)
    anchor = _Event(id=10, title="Main Concert", start_at=base, end_at=None, source_tier=1)
    support = [
        _Event(
            id=1,
            title="Pre Drinks",
            start_at=base - timedelta(hours=1),
            end_at=None,
            source_tier=3,
        ),
        _Event(
            id=2,
            title="Late Snacks",
            start_at=base + timedelta(hours=2),
            end_at=None,
            source_tier=3,
        ),
    ]

    itinerary = sequence_itinerary(anchor=anchor, support_events=support)
    assert [stop.kind for stop in itinerary] == [
        "pre_event_drink",
        "main_event",
        "late_night_snack",
    ]
    assert itinerary[1].travel_buffer_minutes_before == 30
    assert itinerary[2].travel_buffer_minutes_before == 30
