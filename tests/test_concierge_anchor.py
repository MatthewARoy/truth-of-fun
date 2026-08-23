"""Integration check: the concierge anchor respects the parsed intent.

Needs a real Postgres (the anchor query runs in SQL), so it skips when the
database is unreachable — same pattern as ``test_health_db.py``.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.localtime import LOCAL_TZ
from app.main import app


def _database_reachable() -> bool:
    engine = create_engine(
        get_settings().database_url, connect_args={"connect_timeout": 2}
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


pytestmark = pytest.mark.skipif(
    not _database_reachable(),
    reason=(
        "Postgres is not reachable at DATABASE_URL — "
        "start it with `make db-up` to run this integration test"
    ),
)


def _next_sunday_at(hour: int, minute: int = 0) -> datetime:
    """The Sunday the concierge will target, at ``hour`` SF-local, as UTC.

    On a Sunday that is *today*: the app resolves "Sunday" to the current day
    (concierge ``_resolve_window`` uses ``% 7`` with no bump), so the fixture
    must too, or every anchor test goes red on Sundays. The anchor query
    bounds on the intent window rather than ``now()``, so an event earlier
    the same day still qualifies whenever CI runs.
    """
    now_local = datetime.now(LOCAL_TZ)
    days_until = (6 - now_local.weekday()) % 7
    target = (now_local + timedelta(days=days_until)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return target.astimezone(timezone.utc)


@pytest.fixture
def sunday_events():
    """A Sunday morning workshop and a Sunday evening show, both tier 2."""
    engine = create_engine(get_settings().database_url)
    rows = [
        ("anchor-morning-workshop", _next_sunday_at(10)),
        ("anchor-evening-show", _next_sunday_at(20)),
    ]
    with engine.begin() as connection:
        for title, start_at in rows:
            connection.execute(
                text(
                    "INSERT INTO events (title, start_at, source_name, source_tier,"
                    " location, categories, tags, status, attendee_count,"
                    " location_confidence, is_free, venue_name, raw_address,"
                    " created_at, updated_at)"
                    " VALUES (:title, :start_at, 'test-anchor', 2,"
                    " ST_SetSRID(ST_MakePoint(-122.4194, 37.7749), 4326), '[]', '[]',"
                    " 'scheduled', 0, 1.0, false, 'Test Venue',"
                    " 'Test Venue, San Francisco, CA', now(), now())"
                ),
                {"title": title, "start_at": start_at},
            )
    yield
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM events WHERE source_name = 'test-anchor'"))
    engine.dispose()


@pytest.fixture
def content_rank_and_outer_support_events():
    """Two content anchors plus a tier-3 stop between 0.5 and 1 mile away."""
    engine = create_engine(get_settings().database_url)
    rows = [
        (
            "anchor-quiet-jazz-date",
            _next_sunday_at(20),
            2,
            -122.4194,
            '["#Date", "#Chill", "#Jazz"]',
        ),
        (
            "anchor-high-energy-night-out",
            _next_sunday_at(20, 5),
            2,
            -122.4194,
            '["#NightOut", "#HighEnergy", "#Social"]',
        ),
        (
            "support-outer-radius",
            _next_sunday_at(18),
            3,
            -122.4057,
            "[]",
        ),
    ]
    with engine.begin() as connection:
        for title, start_at, source_tier, longitude, tags in rows:
            connection.execute(
                text(
                    "INSERT INTO events (title, start_at, source_name, source_tier,"
                    " location, categories, tags, status, attendee_count,"
                    " location_confidence, is_free, venue_name, raw_address,"
                    " created_at, updated_at)"
                    " VALUES (:title, :start_at, 'test-concierge-content', :source_tier,"
                    " ST_SetSRID(ST_MakePoint(:longitude, 37.7749), 4326), '[]',"
                    " CAST(:tags AS json), 'scheduled', 0, 1.0, false,"
                    " 'San Francisco Content Test', 'San Francisco Content Test',"
                    " now(), now())"
                ),
                {
                    "title": title,
                    "start_at": start_at,
                    "source_tier": source_tier,
                    "longitude": longitude,
                    "tags": tags,
                },
            )
    yield engine
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM events WHERE source_name = 'test-concierge-content'")
        )
    engine.dispose()


def _anchor_title(payload: dict) -> str | None:
    for stop in payload["itinerary"]:
        if stop["kind"] == "main_event":
            return stop["title"]
    return None


def test_date_night_does_not_anchor_on_a_morning_event(sunday_events) -> None:
    """A 10am workshop is never the main event of a date night (see #20).

    The anchor was "earliest tier<=2 event in the window", so date_night and
    general_night_out returned byte-identical morning itineraries.
    """
    client = TestClient(app)
    response = client.post(
        "/concierge/itinerary",
        json={"query": "date night in San Francisco Sunday", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["timeframe"] == "this_sunday"
    assert _anchor_title(payload) != "anchor-morning-workshop"


def test_out_of_town_guests_can_still_anchor_in_the_morning(sunday_events) -> None:
    """Daytime intents keep the full day available."""
    client = TestClient(app)
    response = client.post(
        "/concierge/itinerary",
        json={
            "query": "showing out of town guests around San Francisco Sunday",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    assert response.json()["timeframe"] == "this_sunday"


def test_anonymous_evening_intents_choose_different_content_anchors(
    content_rank_and_outer_support_events,
) -> None:
    client = TestClient(app)

    date_response = client.post(
        "/concierge/itinerary",
        json={"query": "date night in San Francisco Sunday", "limit": 10},
    )
    general_response = client.post(
        "/concierge/itinerary",
        json={"query": "night out in San Francisco Sunday", "limit": 10},
    )

    assert date_response.status_code == 200
    assert general_response.status_code == 200
    assert _anchor_title(date_response.json()) == "anchor-quiet-jazz-date"
    assert _anchor_title(general_response.json()) == "anchor-high-energy-night-out"


def test_support_search_falls_back_to_one_mile_when_half_mile_is_empty(
    content_rank_and_outer_support_events,
) -> None:
    client = TestClient(app)

    response = client.post(
        "/concierge/itinerary",
        json={"query": "date night in San Francisco Sunday", "limit": 10},
    )

    assert response.status_code == 200
    assert "support-outer-radius" in {
        stop["title"] for stop in response.json()["itinerary"]
    }


def test_support_search_keeps_half_mile_primary_when_it_has_a_result(
    content_rank_and_outer_support_events,
) -> None:
    engine = content_rank_and_outer_support_events
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO events (title, start_at, source_name, source_tier,"
                " location, categories, tags, status, attendee_count,"
                " location_confidence, is_free, venue_name, raw_address,"
                " created_at, updated_at)"
                " VALUES ('support-inner-radius', :start_at,"
                " 'test-concierge-content', 3,"
                " ST_SetSRID(ST_MakePoint(-122.415, 37.7749), 4326), '[]', '[]',"
                " 'scheduled', 0, 1.0, false, 'San Francisco Content Test',"
                " 'San Francisco Content Test', now(), now())"
            ),
            {"start_at": _next_sunday_at(18, 30)},
        )
    client = TestClient(app)

    response = client.post(
        "/concierge/itinerary",
        json={"query": "date night in San Francisco Sunday", "limit": 10},
    )

    titles = {stop["title"] for stop in response.json()["itinerary"]}
    assert response.status_code == 200
    assert "support-inner-radius" in titles
    assert "support-outer-radius" not in titles


@pytest.fixture
def sunday_estimated_and_real_evening_events():
    """Two Sunday evening candidates: one real 8pm show, one 7pm placeholder."""
    engine = create_engine(get_settings().database_url)
    rows = [
        ("anchor-estimated-brunch", _next_sunday_at(19), True),
        ("anchor-real-evening-show", _next_sunday_at(20), False),
    ]
    with engine.begin() as connection:
        for title, start_at, estimated in rows:
            connection.execute(
                text(
                    "INSERT INTO events (title, start_at, start_time_is_estimated,"
                    " source_name, source_tier, location, categories, tags, status,"
                    " attendee_count, location_confidence, is_free, venue_name,"
                    " raw_address, created_at, updated_at)"
                    " VALUES (:title, :start_at, :estimated, 'test-anchor-estimated', 2,"
                    " ST_SetSRID(ST_MakePoint(-122.4194, 37.7749), 4326), '[]', '[]',"
                    " 'scheduled', 0, 1.0, false, 'Test Venue',"
                    " 'Test Venue, San Francisco, CA', now(), now())"
                ),
                {"title": title, "start_at": start_at, "estimated": estimated},
            )
    yield
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM events WHERE source_name = 'test-anchor-estimated'")
        )
    engine.dispose()


def test_intent_hours_do_not_anchor_on_a_placeholder_time(
    sunday_estimated_and_real_evening_events,
) -> None:
    """A defaulted 19:00 lands inside every evening range without earning it.

    The Eventbrite connector stamps 19:00 when a listing publishes no time, so
    an R&B brunch would out-rank a show that genuinely starts in the evening.
    """
    client = TestClient(app)
    response = client.post(
        "/concierge/itinerary",
        json={"query": "date night in San Francisco Sunday", "limit": 10},
    )

    assert response.status_code == 200
    assert _anchor_title(response.json()) != "anchor-estimated-brunch"


def test_the_api_reports_an_estimated_start_time(
    sunday_estimated_and_real_evening_events,
) -> None:
    """Clients need the flag to avoid rendering the placeholder as a clock time."""
    client = TestClient(app)
    # Bounded to the fixture's own Sunday evening: the shared dev database
    # holds thousands of rows, so an unbounded page would not reach these.
    response = client.get(
        "/events",
        params={
            "start_at": _next_sunday_at(18).isoformat(),
            "end_at": _next_sunday_at(21).isoformat(),
            "limit": 100,
        },
    )

    assert response.status_code == 200
    by_title = {event["title"]: event for event in response.json()}
    assert by_title["anchor-estimated-brunch"]["start_time_is_estimated"] is True
    assert by_title["anchor-real-evening-show"]["start_time_is_estimated"] is False
