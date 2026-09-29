"""The stored-row half of estimated-start-time dedupe.

``_find_existing_event`` prefilters candidates in SQL, so the widening that
in-batch dedupe gets for free has to be expressed as a query. Needs a real
Postgres — skips when the database is unreachable, same pattern as
``test_concierge_anchor.py``.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.core.config import get_settings
from app.core.localtime import LOCAL_TZ
from app.services.data_pipeline import DataPipelineService

SOURCE_MARKER = "test-estimated-times"


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


def _tomorrow_at(hour: int) -> datetime:
    """Tomorrow at ``hour`` SF-local, as UTC.

    Tomorrow rather than today so the fixture never straddles a local midnight
    that has already passed, and always sits inside one local calendar day.
    """
    local = (datetime.now(LOCAL_TZ) + timedelta(days=1)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return local.astimezone(timezone.utc)


@pytest.fixture
def engine():
    engine = create_engine(get_settings().database_url)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM events WHERE source_name = :marker"),
            {"marker": SOURCE_MARKER},
        )
    yield engine
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM events WHERE source_name = :marker"),
            {"marker": SOURCE_MARKER},
        )
    engine.dispose()


def _insert_event(
    engine, *, title: str, start_at: datetime, start_time_is_estimated: bool
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO events (title, start_at, start_time_is_estimated,"
                " source_name, source_tier, location, categories, tags, status,"
                " attendee_count, location_confidence, is_free, venue_name,"
                " raw_address, created_at, updated_at)"
                " VALUES (:title, :start_at, :estimated, :marker, 2,"
                " ST_SetSRID(ST_MakePoint(-122.4194, 37.7749), 4326), '[]', '[]',"
                " 'scheduled', 0, 1.0, false, 'San Francisco Zoo',"
                " 'San Francisco Zoo, San Francisco, CA', now(), now())"
            ),
            {
                "title": title,
                "start_at": start_at,
                "estimated": start_time_is_estimated,
                "marker": SOURCE_MARKER,
            },
        )


def _incoming(*, title: str, start_at: datetime, start_time_is_estimated: bool) -> dict:
    return {
        "title": title,
        "start_at": start_at,
        "start_time_is_estimated": start_time_is_estimated,
        "venue_name": "San Francisco Zoo",
        "external_url": None,
    }


def test_incoming_real_time_finds_a_stored_estimate(engine) -> None:
    """Eventbrite landed first with its 19:00 default; funcheap arrives with 13:00."""
    _insert_event(
        engine,
        title="Tea Party at the Zoo",
        start_at=_tomorrow_at(19),
        start_time_is_estimated=True,
    )
    service = DataPipelineService()

    with Session(engine) as session:
        found = service._find_existing_event(
            session=session,
            incoming_event=_incoming(
                title="Tea Party at the Zoo",
                start_at=_tomorrow_at(13),
                start_time_is_estimated=False,
            ),
        )

    assert found is not None
    assert found.title == "Tea Party at the Zoo"


def test_incoming_estimate_finds_a_stored_real_time(engine) -> None:
    """The other arrival order: the real 13:00 row is already stored."""
    _insert_event(
        engine,
        title="Tea Party at the Zoo",
        start_at=_tomorrow_at(13),
        start_time_is_estimated=False,
    )
    service = DataPipelineService()

    with Session(engine) as session:
        found = service._find_existing_event(
            session=session,
            incoming_event=_incoming(
                title="Tea Party at the Zoo",
                start_at=_tomorrow_at(19),
                start_time_is_estimated=True,
            ),
        )

    assert found is not None
    assert found.title == "Tea Party at the Zoo"


def test_two_real_times_six_hours_apart_stay_separate(engine) -> None:
    """No placeholder involved: the two-hour window still applies."""
    _insert_event(
        engine,
        title="Tea Party at the Zoo",
        start_at=_tomorrow_at(13),
        start_time_is_estimated=False,
    )
    service = DataPipelineService()

    with Session(engine) as session:
        found = service._find_existing_event(
            session=session,
            incoming_event=_incoming(
                title="Tea Party at the Zoo",
                start_at=_tomorrow_at(19),
                start_time_is_estimated=False,
            ),
        )

    assert found is None


def test_estimate_does_not_reach_into_the_next_local_day(engine) -> None:
    """Widening is bounded by the SF-local calendar day the source published."""
    _insert_event(
        engine,
        title="Tea Party at the Zoo",
        start_at=_tomorrow_at(13) + timedelta(days=1),
        start_time_is_estimated=False,
    )
    service = DataPipelineService()

    with Session(engine) as session:
        found = service._find_existing_event(
            session=session,
            incoming_event=_incoming(
                title="Tea Party at the Zoo",
                start_at=_tomorrow_at(19),
                start_time_is_estimated=True,
            ),
        )

    assert found is None
