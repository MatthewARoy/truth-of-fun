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
from app.models.event import Event


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

    On a Sunday that is *today*. The parser clock is fixed to that morning
    below, so evening fixtures stay upcoming even when CI runs Sunday night.
    """
    now_local = datetime.now(LOCAL_TZ)
    days_until = (6 - now_local.weekday()) % 7
    target = (now_local + timedelta(days=days_until)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return target.astimezone(timezone.utc)


@pytest.fixture(autouse=True)
def _stable_parser_clock(monkeypatch):
    from app.services import concierge

    morning = _next_sunday_at(8)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return morning.astimezone(tz) if tz else morning.replace(tzinfo=None)

    monkeypatch.setattr(concierge, "datetime", Clock)


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
                    "INSERT INTO events (title, start_at, end_at, source_name, source_tier,"
                    " location, categories, tags, status, attendee_count,"
                    " location_confidence, is_free, venue_name, raw_address,"
                    " created_at, updated_at)"
                    " VALUES (:title, :start_at, :end_at, 'test-anchor', 2,"
                    " ST_SetSRID(ST_MakePoint(-122.4194, 37.7749), 4326), '[]', '[]',"
                    " 'scheduled', 0, 1.0, false, 'Test Venue',"
                    " 'Test Venue, San Francisco, CA', now(), now())"
                ),
                {"title": title, "start_at": start_at, "end_at": start_at + timedelta(hours=1)},
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
                    "INSERT INTO events (title, start_at, end_at, source_name, source_tier,"
                    " location, categories, tags, status, attendee_count,"
                    " location_confidence, is_free, venue_name, raw_address,"
                    " created_at, updated_at)"
                    " VALUES (:title, :start_at, :end_at, 'test-concierge-content', :source_tier,"
                    " ST_SetSRID(ST_MakePoint(:longitude, 37.7749), 4326), '[]',"
                    " CAST(:tags AS json), 'scheduled', 0, 1.0, false,"
                    " 'San Francisco Content Test', 'San Francisco Content Test',"
                    " now(), now())"
                ),
                {
                    "title": title,
                    "start_at": start_at,
                    "end_at": start_at + timedelta(hours=1),
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
                "INSERT INTO events (title, start_at, end_at, source_name, source_tier,"
                " location, categories, tags, status, attendee_count,"
                " location_confidence, is_free, venue_name, raw_address,"
                " created_at, updated_at)"
                " VALUES ('support-inner-radius', :start_at, :end_at,"
                " 'test-concierge-content', 3,"
                " ST_SetSRID(ST_MakePoint(-122.415, 37.7749), 4326), '[]', '[]',"
                " 'scheduled', 0, 1.0, false, 'San Francisco Content Test',"
                " 'San Francisco Content Test', now(), now())"
            ),
            {"start_at": _next_sunday_at(18, 30), "end_at": _next_sunday_at(19, 30)},
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


def _sf_event(
    *,
    title: str,
    start_at: datetime,
    tags: list[str] | None = None,
    source_tier: int = 2,
) -> Event:
    """A San Francisco event, positioned so the geography filter keeps it.

    Tier 2 by default, so it is an anchor candidate; pass ``source_tier=3``
    for a support stop.
    """
    now = datetime.now(timezone.utc)
    return Event(
        title=title,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        source_name="test-anchor-candidates",
        source_tier=source_tier,
        location="POINT(-122.4194 37.7749)",
        categories=[],
        tags=tags or [],
        status="scheduled",
        attendee_count=0,
        location_confidence=1.0,
        is_free=False,
        venue_name="San Francisco Candidate Test",
        raw_address="San Francisco Candidate Test, San Francisco, CA",
        created_at=now,
        updated_at=now,
    )


def test_a_late_strong_vibe_match_outranks_the_earliest_candidates(
    isolated_events_session,
) -> None:
    """Vibe ranking must see every candidate, not just the earliest ``limit``.

    The anchor query applied the payload's ``limit`` in SQL, ordered by start
    time, *before* ``score_events`` ran. Anything past the tenth-earliest
    candidate could never win the anchor slot however well it matched the
    intent — here, the only event tagged for a date night starts last.
    """
    session = isolated_events_session
    for minute in range(0, 60, 5):
        session.add(
            _sf_event(title=f"decoy-{minute:02d}", start_at=_next_sunday_at(18, minute))
        )
    session.add(
        _sf_event(
            title="late-quiet-jazz-date",
            start_at=_next_sunday_at(22),
            tags=["#Date", "#Chill", "#Jazz"],
        )
    )
    session.flush()
    # Postgres computes the geometry; expire so reads return EWKB, not our WKT.
    session.expire_all()

    client = TestClient(app)
    response = client.post(
        "/concierge/itinerary",
        json={"query": "date night in San Francisco Sunday", "limit": 10},
    )

    assert response.status_code == 200
    assert _anchor_title(response.json()) == "late-quiet-jazz-date"


def test_a_post_anchor_stop_survives_a_small_itinerary_limit(
    isolated_events_session,
) -> None:
    """Sequencing must see support events on *both* sides of the anchor.

    The support query took the earliest ``limit`` rows in SQL, but
    ``sequence_itinerary`` brackets the anchor — the last stop before it and
    the first one after. Given more pre-anchor candidates than ``limit``,
    every post-anchor one was cut before sequencing ever ran, and the night
    silently ended at the main event.
    """
    session = isolated_events_session
    session.add(
        _sf_event(
            title="anchor-quiet-jazz-date",
            start_at=_next_sunday_at(20),
            tags=["#Date", "#Chill", "#Jazz"],
        )
    )
    for hour, minute in ((17, 0), (17, 30), (18, 0)):
        session.add(
            _sf_event(
                title=f"support-before-{hour}{minute:02d}",
                start_at=_next_sunday_at(hour, minute),
                source_tier=3,
            )
        )
    session.add(
        _sf_event(
            title="support-after-2200",
            start_at=_next_sunday_at(22),
            source_tier=3,
        )
    )
    session.flush()
    # Postgres computes the geometry; expire so reads return EWKB, not our WKT.
    session.expire_all()

    client = TestClient(app)
    response = client.post(
        "/concierge/itinerary",
        # The old code clamped `limit` to a floor of 3 and applied it in
        # SQL; the three pre-anchor stops above are exactly enough to fill
        # that quota and starve the post-anchor one.
        json={"query": "date night in San Francisco Sunday", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [stop["kind"] for stop in payload["itinerary"]] == [
        "before_event",
        "main_event",
        "after_event",
    ]
    assert payload["itinerary"][-1]["title"] == "support-after-2200"


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


def test_uncertain_anchor_location_does_not_invent_a_nearby_route(isolated_events_session):
    session = isolated_events_session
    anchor = _sf_event(title="Unresolved jazz venue", start_at=_next_sunday_at(20), tags=["#date", "#jazz"])
    anchor.location_confidence = 0.3
    session.add(anchor)
    session.add(_sf_event(title="Near the guessed centroid", start_at=_next_sunday_at(18), source_tier=3))
    session.commit()
    response = TestClient(app).post(
        "/concierge/itinerary", json={"query": "date night in San Francisco Sunday", "limit": 10}
    )
    assert response.status_code == 200
    assert [stop["title"] for stop in response.json()["itinerary"]] == ["Unresolved jazz venue"]


@pytest.mark.parametrize("query,label", [("date night in the sunset Sunday", "Sunset district"),
    ("date night near ocean beach Sunday", "Near Ocean Beach"),
    ("date night on the west side Sunday", "West side of San Francisco")])
def test_spatial_plan_constrains_anchor_and_support(isolated_events_session, query, label):
    session = isolated_events_session
    def row(title, lat, lng, tier=2, confidence=0.9, hour=20):
        event = Event(title=title, start_at=_next_sunday_at(hour), end_at=_next_sunday_at(hour+1),
            source_name="test-spatial", source_tier=tier, location=f"POINT({lng} {lat})",
            location_confidence=confidence, tags=["#date"], venue_name=title)
        session.add(event)
        session.flush()
        return event
    downtown = row("Downtown anchor",37.79,-122.4)
    low = row("Untrusted west anchor",37.76,-122.50,confidence=0.3)
    west = row("West anchor",37.76,-122.50)
    nearby = row("West support",37.7601,-122.5001,tier=3,hour=18)
    row("Outside support",37.79,-122.4,tier=3,hour=18)
    row("Untrusted support",37.7602,-122.50,tier=3,confidence=0.45,hour=22)
    session.expire_all()
    response = TestClient(app).post("/concierge/itinerary", json={"query":query})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["resolved_area"]["label"] == label
    assert data["anchor_event_id"] == west.id
    assert {stop["event_id"] for stop in data["itinerary"]} == {west.id, nearby.id}
    assert downtown.id != low.id


def test_origin_changes_equal_anchor_ranking_and_routes(isolated_events_session):
    session = isolated_events_session
    for name, lng in [("Downtown",-122.40),("West",-122.50)]:
        session.add(Event(title=name, start_at=_next_sunday_at(20), source_name="test-origin", source_tier=2,
            location=f"POINT({lng} 37.76)", location_confidence=0.9, venue_name=name, raw_address="San Francisco",
            created_at=_next_sunday_at(8)))
    session.flush()
    session.expire_all()
    response = TestClient(app).post("/concierge/itinerary", json={"query":"date night in San Francisco Sunday",
        "origin":{"name":"Ocean Beach", "lat":37.76, "lng":-122.50}, "travel_mode":"walking"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["itinerary"][0]["title"] == "West"
    assert data["resolved_area"] is None
    assert "origin=37.76%2C-122.5" in data["itinerary"][0]["links"]["directions_url"]
    assert "travelmode=walking" in data["itinerary"][0]["links"]["directions_url"]
