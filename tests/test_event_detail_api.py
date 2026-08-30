"""Tests for GET /events/{id} and the X-Total-Count pagination header.

Both exist for agent/tool callers: detail so an agent can cite a source and
qualify freshness, X-Total-Count so it knows whether to keep paging without
fetching a page to find out.

These need a real Postgres — the events table carries a PostGIS geometry column
and a tsvector index, neither of which SQLite can create — so they follow the
same skip-when-unreachable pattern as tests/test_health_db.py. Each test runs
inside a transaction that is rolled back, so the developer's corpus is left
untouched and the assertions don't depend on what is already seeded.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.main import app
from app.models.event import Event


def _database_reachable() -> bool:
    engine = create_engine(get_settings().database_url, connect_args={"connect_timeout": 2})
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

# Every event these tests create carries this tag, so filtered queries can be
# scoped to just them regardless of what else is in the database.
FIXTURE_TAG = "#PytestEventDetailFixture"


@contextmanager
def _build_client() -> Generator[tuple[TestClient, Session], None, None]:
    """Yield a client whose session is rolled back when the test finishes."""
    engine = create_engine(get_settings().database_url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    def _override_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _event(title: str, *, days_out: int = 3, **overrides: object) -> Event:
    now = datetime.now(timezone.utc)
    defaults: dict[str, object] = {
        "title": title,
        "start_at": now + timedelta(days=days_out),
        "source_name": "ticketmaster",
        "source_tier": 1,
        "status": "scheduled",
        "tags": [FIXTURE_TAG],
        "categories": [],
        "location": "SRID=4326;POINT(-122.4194 37.7749)",
        "created_at": now - timedelta(days=2),
        "updated_at": now - timedelta(days=1),
    }
    defaults.update(overrides)
    return Event(**defaults)  # type: ignore[arg-type]


def test_event_detail_returns_provenance() -> None:
    with _build_client() as (client, session):
        event = _event(
            "Punch Line Comedy",
            source_name="funcheap_sf",
            source_tier=3,
            venue_name="Punch Line",
            raw_address="444 Battery St, San Francisco",
        )
        session.add(event)
        session.flush()
        event_id = event.id

        body = client.get(f"/events/{event_id}").json()

    assert body["id"] == event_id
    assert body["title"] == "Punch Line Comedy"
    assert body["source_name"] == "funcheap_sf"
    assert body["source_tier"] == 3
    assert body["raw_address"] == "444 Battery St, San Francisco"
    assert body["first_seen_at"]
    assert body["updated_at"]
    # The ingest timestamp must never be presented as an announcement date.
    assert "created_at" not in body


def test_event_detail_resolves_coordinates_from_postgis() -> None:
    with _build_client() as (client, session):
        event = _event("Golden Gate Park Concert")
        session.add(event)
        session.flush()
        event_id = event.id
        # Until it is expired, the identity map still holds the WKT string this
        # test assigned; the endpoint must see the EWKB Postgres returns.
        session.expire_all()

        body = client.get(f"/events/{event_id}").json()

    assert body["lat"] == pytest.approx(37.7749, abs=1e-4)
    assert body["lng"] == pytest.approx(-122.4194, abs=1e-4)


def test_event_detail_404s_for_an_unknown_id() -> None:
    with _build_client() as (client, _):
        response = client.get("/events/2147483000")

    assert response.status_code == 404


def test_total_count_header_reports_matches_before_pagination() -> None:
    with _build_client() as (client, session):
        for index in range(7):
            session.add(_event(f"Fixture Show {index}", days_out=index + 1))
        session.flush()

        response = client.get("/events", params={"vibe_tag": FIXTURE_TAG, "limit": 2})

    assert len(response.json()) == 2
    # The header describes the filtered set, not the page and not the corpus.
    assert response.headers["X-Total-Count"] == "7"


def test_total_count_header_respects_filters() -> None:
    other_tag = "#PytestOtherFixture"
    with _build_client() as (client, session):
        session.add(_event("Jazz Night", tags=[FIXTURE_TAG, "#Jazz"]))
        session.add(_event("Rock Night", tags=[FIXTURE_TAG, other_tag]))
        session.add(_event("Another Jazz Night", tags=[FIXTURE_TAG, "#Jazz"]))
        session.flush()

        response = client.get("/events", params={"vibe_tag": "#Jazz", "limit": 1})

    assert response.headers["X-Total-Count"] == "2"
