"""A Ticketmaster event id identifies the listing, wherever its date moves.

``_find_existing_event`` otherwise matches on time first: a rescheduled show
whose new date is months away falls outside the two-hour window, so it was
inserted as a second row while the old one kept its stale status.

Only sources whose ids really are per-event get this. 19hz uses a promoter's
Instagram post URL as the id, and one post covers up to nine different nights.

Needs a real Postgres -- skips when the database is unreachable, same pattern
as ``test_data_pipeline_estimated_times_db.py``. Rows carry a
``test-listing-identity-`` id prefix and sit in 2031, clear of the dev corpus.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.core.config import get_settings
from app.services.data_pipeline import DataPipelineService

ID_PREFIX = "test-listing-identity-"
ORIGINAL_START = datetime(2031, 3, 1, 3, 30, tzinfo=timezone.utc)


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
def engine():
    engine = create_engine(get_settings().database_url)
    cleanup = text("DELETE FROM events WHERE source_event_id LIKE :prefix")
    with engine.begin() as connection:
        connection.execute(cleanup, {"prefix": f"{ID_PREFIX}%"})
    yield engine
    with engine.begin() as connection:
        connection.execute(cleanup, {"prefix": f"{ID_PREFIX}%"})
    engine.dispose()


def _insert_event(
    engine, *, source_name: str, source_event_id: str, title: str
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO events (title, start_at, start_time_is_estimated,"
                " source_name, source_tier, source_event_id, location, categories,"
                " tags, status, attendee_count, location_confidence, is_free,"
                " venue_name, created_at, updated_at)"
                " VALUES (:title, :start_at, false, :source_name, 1, :source_event_id,"
                " ST_SetSRID(ST_MakePoint(-122.4482, 37.8019), 4326), '[]', '[]',"
                " 'postponed', 0, 1.0, false, 'Palace of Fine Arts', now(), now())"
            ),
            {
                "title": title,
                "start_at": ORIGINAL_START,
                "source_name": source_name,
                "source_event_id": source_event_id,
            },
        )


def _incoming(
    *, source_name: str, source_event_id: str, title: str, start_at: datetime
) -> dict:
    return {
        "title": title,
        "start_at": start_at,
        "start_time_is_estimated": False,
        "venue_name": "Palace of Fine Arts",
        "external_url": None,
        "source_name": source_name,
        "source_event_id": source_event_id,
    }


def test_a_rescheduled_ticketmaster_listing_finds_its_row_months_away(engine) -> None:
    """Title drift too: seven Ticketmaster ids already hold two rows each."""
    listing_id = f"{ID_PREFIX}dan-and-phil"
    _insert_event(
        engine,
        source_name="ticketmaster",
        source_event_id=listing_id,
        title="Dan and Phil: Hard Launch World Tour",
    )

    with Session(engine) as session:
        found = DataPipelineService()._find_existing_event(
            session=session,
            incoming_event=_incoming(
                source_name="ticketmaster",
                source_event_id=listing_id,
                title="Dan and Phil: Hard Launch World Tour (Rescheduled)",
                start_at=ORIGINAL_START + timedelta(days=120),
            ),
        )

    assert found is not None
    assert found.source_event_id == listing_id


def test_the_same_id_under_another_source_is_not_that_listing(engine) -> None:
    listing_id = f"{ID_PREFIX}shared-value"
    _insert_event(
        engine,
        source_name="eventbrite",
        source_event_id=listing_id,
        title="Dan and Phil: Hard Launch World Tour",
    )

    with Session(engine) as session:
        found = DataPipelineService()._find_existing_event(
            session=session,
            incoming_event=_incoming(
                source_name="ticketmaster",
                source_event_id=listing_id,
                title="Dan and Phil: Hard Launch World Tour",
                start_at=ORIGINAL_START + timedelta(days=120),
            ),
        )

    assert found is None


def test_a_shared_post_url_is_not_identity_across_nights(engine) -> None:
    """19hz: one Instagram post id, a different party each weekend."""
    post_id = f"{ID_PREFIX}https://www.instagram.com/p/Dc0IobgAZRB/"
    _insert_event(
        engine,
        source_name="19hz",
        source_event_id=post_id,
        title="Dan and Phil: Hard Launch World Tour",
    )

    with Session(engine) as session:
        found = DataPipelineService()._find_existing_event(
            session=session,
            incoming_event=_incoming(
                source_name="19hz",
                source_event_id=post_id,
                title="Dan and Phil: Hard Launch World Tour",
                start_at=ORIGINAL_START + timedelta(days=7),
            ),
        )

    assert found is None
