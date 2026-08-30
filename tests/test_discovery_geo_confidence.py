"""Integration check: radius search excludes low-confidence coordinates.

Needs a real Postgres+PostGIS (the filter is a ``ST_DWithin`` query), so it
skips automatically when the database is unreachable — same pattern as
``test_health_db.py``. Backend CI provides a PostGIS service container.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.main import app

SF_LAT, SF_LNG = 37.7749, -122.4194


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


@pytest.fixture
def seeded_events():
    """Two events on SF's centroid: one exact, one an unresolved-venue guess."""
    engine = create_engine(get_settings().database_url)
    start_at = datetime.now(timezone.utc) + timedelta(days=3)
    rows = [
        ("geo-confidence-exact", 1.0),
        ("geo-confidence-guess", 0.3),
    ]
    with engine.begin() as connection:
        for title, confidence in rows:
            connection.execute(
                text(
                    "INSERT INTO events (title, start_at, source_name, source_tier,"
                    " location, categories, tags, status, attendee_count,"
                    " location_confidence, is_free, created_at, updated_at)"
                    " VALUES (:title, :start_at, 'test', 2,"
                    " ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), '[]', '[]',"
                    " 'scheduled', 0, :confidence, false, now(), now())"
                ),
                {
                    "title": title,
                    "start_at": start_at,
                    "lat": SF_LAT,
                    "lng": SF_LNG,
                    "confidence": confidence,
                },
            )
    yield
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM events WHERE source_name = 'test'")
        )
    engine.dispose()


def _titles(response) -> set[str]:
    return {event["title"] for event in response.json()}


def test_radius_search_excludes_low_confidence_locations(seeded_events) -> None:
    """A 0.3-confidence point is a city-centroid guess, not a place to search on."""
    client = TestClient(app)
    response = client.get(
        "/events",
        params={
            "lat": SF_LAT,
            "lng": SF_LNG,
            "radius_miles": 5,
            "limit": 200,
        },
    )

    assert response.status_code == 200
    titles = _titles(response)
    assert "geo-confidence-exact" in titles
    assert "geo-confidence-guess" not in titles


def test_radius_search_can_opt_into_low_confidence_locations(seeded_events) -> None:
    """Callers that want the guesses can lower the threshold explicitly."""
    client = TestClient(app)
    response = client.get(
        "/events",
        params={
            "lat": SF_LAT,
            "lng": SF_LNG,
            "radius_miles": 5,
            "min_location_confidence": 0,
            "limit": 200,
        },
    )

    assert response.status_code == 200
    assert "geo-confidence-guess" in _titles(response)
