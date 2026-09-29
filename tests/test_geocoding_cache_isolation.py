"""A broken geocode cache must not take the ingestion cycle with it.

Postgres aborts the *whole* transaction on a failed statement: every later
command errors until rollback. So a cache read against a missing or broken
``geocode_cache`` table does not merely lose caching — it poisons the
session the pipeline is about to insert events into, and the entire
cycle's events are discarded on commit.

That is not a hypothetical: a deployment that sets GEOCODING_PROVIDER
before applying the migration is exactly this state.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.core.config import get_settings
from app.services.geocoding import GeocodeResult, VenueGeocoder

pytestmark = pytest.mark.anyio

RESOLVED = GeocodeResult(
    lat=37.8097, lon=-122.2671, confidence=0.85, precision="poi", provider="stub"
)


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


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not _database_reachable(),
        reason=(
            "needs real Postgres: only Postgres aborts a transaction on a failed "
            "statement, which is the failure mode under test"
        ),
    ),
]


class _Provider:
    name = "stub"

    async def lookup(self, query: str) -> GeocodeResult | None:
        return RESOLVED


@pytest.fixture()
def blind_session():
    """A session that cannot see ``geocode_cache``, whatever the schema holds.

    ``pg_temp`` is empty by construction, so this reproduces the missing
    table deterministically rather than depending on migration state.
    """
    engine = create_engine(get_settings().database_url)
    with Session(engine) as session:
        session.begin()
        session.execute(text("SET LOCAL search_path TO pg_temp"))
        yield session
        session.rollback()
    engine.dispose()


async def test_an_unusable_cache_still_returns_the_geocoded_answer(blind_session) -> None:
    result = await VenueGeocoder(provider=_Provider()).resolve(
        session=blind_session,
        venue_name="Good Times",
        raw_address=None,
        city="Oakland",
    )

    assert result == RESOLVED


async def test_an_unusable_cache_leaves_the_session_able_to_write_events(
    blind_session,
) -> None:
    """The assertion that matters: the pipeline inserts events into this same
    session immediately afterwards. An aborted transaction loses all of them."""
    await VenueGeocoder(provider=_Provider()).resolve(
        session=blind_session,
        venue_name="Good Times",
        raw_address=None,
        city="Oakland",
    )

    blind_session.execute(text("CREATE TEMP TABLE probe (id int)"))
    blind_session.execute(text("INSERT INTO probe (id) VALUES (1)"))

    assert blind_session.execute(text("SELECT count(*) FROM probe")).scalar() == 1
