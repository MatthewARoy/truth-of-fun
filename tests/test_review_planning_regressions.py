import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api.discovery import _apply_time_preset
from app.core.localtime import LOCAL_TZ
from app.services.concierge import ClaudeIntentParser, _resolve_timeframe_window, parse_intent_async, sequence_itinerary


@pytest.mark.parametrize("day", [2, 3, 4])
def test_current_weekend_is_shared_by_search_and_planner(day):
    now = datetime(2026, 10, day, 18, tzinfo=LOCAL_TZ)
    search = _apply_time_preset(time_preset="this_weekend", now=now)
    planner = _resolve_timeframe_window("this_weekend", now=now)
    assert search == planner
    assert search[0] <= now <= search[1]
    assert search[1].astimezone(LOCAL_TZ).date().isoformat() == "2026-10-05"


def test_named_today_window_does_not_include_finished_events():
    now = datetime(2026, 10, 4, 23, tzinfo=LOCAL_TZ)
    start, end = _resolve_timeframe_window("this_sunday", now=now)
    assert start == now
    assert end > now


def _event(event_id, start, end, **extra):
    return SimpleNamespace(id=event_id, title=str(event_id), start_at=start, end_at=end,
                           source_tier=2, venue_name="Venue", external_url=None,
                           start_time_is_estimated=extra.get("estimated", False))


def test_sequence_requires_published_end_and_travel_buffer():
    start = datetime(2026, 10, 3, 19, tzinfo=LOCAL_TZ)
    anchor = _event(1, start, start + timedelta(hours=3))
    support = [
        _event(2, start + timedelta(minutes=30), start + timedelta(hours=2)),
        _event(3, start + timedelta(hours=3, minutes=15), start + timedelta(hours=4)),
        _event(4, start + timedelta(hours=3, minutes=30), start + timedelta(hours=4)),
        _event(5, start - timedelta(hours=1), start + timedelta(minutes=10)),
        _event(6, start - timedelta(hours=2), start - timedelta(minutes=30)),
    ]
    stops = sequence_itinerary(anchor=anchor, support_events=support)
    assert [stop.event_id for stop in stops] == [6, 1, 4]
    assert [stop.kind for stop in stops] == ["before_event", "main_event", "after_event"]
    assert stops[0].travel_buffer_minutes_before == 0


def test_unknown_or_estimated_times_do_not_create_false_sequence():
    start = datetime(2026, 10, 3, 19, tzinfo=LOCAL_TZ)
    anchor = _event(1, start, None)
    supports = [_event(2, start - timedelta(hours=1), None),
                _event(3, start + timedelta(hours=3), start + timedelta(hours=4))]
    assert [x.event_id for x in sequence_itinerary(anchor=anchor, support_events=supports)] == [1]
    anchor.start_time_is_estimated = True
    assert [x.event_id for x in sequence_itinerary(anchor=anchor, support_events=supports)] == [1]


def test_supports_stay_on_the_same_outing_night():
    start = datetime(2026, 10, 3, 19, tzinfo=LOCAL_TZ)
    anchor = _event(1, start, start + timedelta(hours=2))
    supports = [_event(2, start - timedelta(days=1), start - timedelta(hours=23)),
                _event(3, start + timedelta(days=1), start + timedelta(hours=25))]
    assert [x.event_id for x in sequence_itinerary(anchor=anchor, support_events=supports)] == [1]


def test_invalid_published_duration_cannot_be_a_following_stop():
    start = datetime(2026, 10, 3, 19, tzinfo=LOCAL_TZ)
    anchor = _event(1, start, start + timedelta(hours=2))
    invalid = _event(2, start + timedelta(hours=3), start - timedelta(hours=1))
    assert [stop.event_id for stop in sequence_itinerary(anchor=anchor, support_events=[invalid])] == [1]
    invalid_anchor = _event(3, start, start - timedelta(hours=1))
    assert sequence_itinerary(anchor=invalid_anchor, support_events=[])[0].end_at is None


@pytest.mark.parametrize("payload", [
    {"intent": [], "timeframe": "tonight"},
    {"intent": "date_night", "timeframe": {}},
    {"intent": "date_night", "timeframe": "tonight", "geography": []},
])
def test_malformed_llm_types_use_keyword_fallback(payload):
    parser = ClaudeIntentParser(api_key="fake-test-key")
    async def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])
    parser._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    parsed = asyncio.run(parse_intent_async("date night in Oakland tonight", parser=parser,
                                           now=datetime(2026, 10, 3, 18, tzinfo=LOCAL_TZ)))
    assert parsed.intent == "date_night"
    assert parsed.geography == "oakland"
    assert parsed.timeframe_label == "tonight"
