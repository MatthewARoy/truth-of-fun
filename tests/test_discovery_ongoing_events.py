"""An event in progress is not a past event.

Discovery filtered on ``start_at`` alone, so anything that had already begun
disappeared from "what's on" — a festival running 10:15–16:00 was invisible
at 15:00, which is exactly when someone asks. Needs a real Postgres+PostGIS;
skips automatically when the database is unreachable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.main import app

SF_LAT, SF_LNG = 37.7749, -122.4194
SOURCE = "test-ongoing"


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
    """One event still running, one that genuinely finished."""
    engine = create_engine(get_settings().database_url)
    now = datetime.now(timezone.utc)
    rows = [
        ("ongoing-festival", now - timedelta(hours=2), now + timedelta(hours=2)),
        ("finished-festival", now - timedelta(hours=6), now - timedelta(hours=2)),
    ]
    with engine.begin() as connection:
        for title, start_at, end_at in rows:
            connection.execute(
                text(
                    "INSERT INTO events (title, start_at, end_at, source_name,"
                    " source_tier, location, categories, tags, status,"
                    " attendee_count, location_confidence, is_free, created_at,"
                    " updated_at) VALUES (:title, :start_at, :end_at, :source, 2,"
                    " ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), '[]', '[]',"
                    " 'scheduled', 0, 1.0, false, now(), now())"
                ),
                {
                    "title": title,
                    "start_at": start_at,
                    "end_at": end_at,
                    "source": SOURCE,
                    "lat": SF_LAT,
                    "lng": SF_LNG,
                },
            )
    yield
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM events WHERE source_name = :s"), {"s": SOURCE}
        )
    engine.dispose()


def _titles(response) -> set[str]:
    return {event["title"] for event in response.json()}


def test_event_in_progress_is_still_listed(seeded_events) -> None:
    client = TestClient(app)
    response = client.get("/events", params={"limit": 200})

    assert response.status_code == 200
    assert "ongoing-festival" in _titles(response)


def test_event_that_already_ended_is_not_listed(seeded_events) -> None:
    client = TestClient(app)
    response = client.get("/events", params={"limit": 200})

    assert response.status_code == 200
    assert "finished-festival" not in _titles(response)


def test_window_predicate_includes_event_in_progress(seeded_events) -> None:
    """A window query must include an event that began before the window and
    is still running inside it — the concierge's 'this afternoon' case."""
    from sqlmodel import Session, select

    from app.api.discovery import overlaps_window
    from app.core.database import engine
    from app.models.event import Event

    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        rows = session.exec(
            select(Event).where(
                Event.source_name == SOURCE,
                overlaps_window(now, now + timedelta(hours=4)),
            )
        ).all()

    titles = {row.title for row in rows}
    assert "ongoing-festival" in titles
    assert "finished-festival" not in titles
