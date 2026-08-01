from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.localtime import LOCAL_TZ as SF_TZ
from app.models.event import Event
from app.models.user import User
from app.services.concierge import (
    _KNOWN_TIMEFRAMES,
    _extract_timeframe,
    intent_vibe_profile,
    parse_intent_prompt,
    sequence_itinerary,
)
from app.services.recommender import RecommenderService


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


def test_extract_timeframe_recognises_sunday() -> None:
    """The keyword fallback must reach Sunday, not drop to upcoming_week."""
    now = datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc)
    label, start, _ = _extract_timeframe("date night in san francisco this sunday", now=now)

    assert label == "this_sunday"
    assert start.astimezone(SF_TZ).day == 2


def test_sunday_is_an_accepted_llm_timeframe() -> None:
    """The LLM schema and the validator must agree the label exists."""
    assert "this_sunday" in _KNOWN_TIMEFRAMES


def test_anonymous_intents_rank_the_same_events_by_different_content() -> None:
    """Anonymous date and general-night requests need distinct content anchors."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1)
    events = [
        Event(
            id=1,
            title="Quiet Jazz Date",
            start_at=start,
            source_name="test",
            source_tier=2,
            location="POINT(-122.4194 37.7749)",
            tags=["#Date", "#Chill", "#Jazz"],
            categories=["music"],
            created_at=now,
            updated_at=now,
        ),
        Event(
            id=2,
            title="High Energy Night Out",
            start_at=start,
            source_name="test",
            source_tier=2,
            location="POINT(-122.4194 37.7749)",
            tags=["NightOut", "HighEnergy", "Social"],
            categories=["nightlife"],
            created_at=now,
            updated_at=now,
        ),
    ]
    service = RecommenderService()

    date_ranked = service.score_events(
        events=events,
        user=None,
        user_vibe_scores=intent_vibe_profile("date_night"),
        popularity_counts={},
    )
    night_ranked = service.score_events(
        events=events,
        user=None,
        user_vibe_scores=intent_vibe_profile("general_night_out"),
        popularity_counts={},
    )

    assert date_ranked[0].event.title == "Quiet Jazz Date"
    assert night_ranked[0].event.title == "High Energy Night Out"


def test_authenticated_preference_upgrades_the_static_intent_profile() -> None:
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1)
    events = [
        Event(
            id=1,
            title="Static Date Pick",
            start_at=start,
            source_name="test",
            source_tier=2,
            location="POINT(-122.4194 37.7749)",
            tags=["#Date"],
            created_at=now,
            updated_at=now,
        ),
        Event(
            id=2,
            title="User's Techno Pick",
            start_at=start,
            source_name="test",
            source_tier=2,
            location="POINT(-122.4194 37.7749)",
            tags=["#Techno"],
            created_at=now,
            updated_at=now,
        ),
    ]

    ranked = RecommenderService().score_events(
        events=events,
        user=User(email="listener@example.com", preferred_vibes=["#Techno"]),
        user_vibe_scores=intent_vibe_profile("date_night"),
        popularity_counts={},
    )

    assert ranked[0].event.title == "User's Techno Pick"


def test_named_weekday_wins_over_the_weekend_branch() -> None:
    """"this weekend on Sunday" must resolve to Sunday (review P2).

    The weekend branch ran first, so the deterministic parser — the path taken
    whenever the LLM is unavailable — searched the whole weekend and could
    still anchor on Saturday.
    """
    now = datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc)  # Thursday
    label, start, _ = _extract_timeframe("date night this weekend on sunday", now=now)

    assert label == "this_sunday"
    assert start.astimezone(SF_TZ).day == 2


def test_plain_weekend_request_still_resolves_to_the_weekend() -> None:
    """No weekday named means the weekend window, unchanged."""
    now = datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc)
    label, _, _ = _extract_timeframe("something fun this weekend", now=now)

    assert label == "this_weekend"
