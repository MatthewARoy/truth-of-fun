"""Persistent geocode cache: spend the rate-limit budget once per venue.

The unresolved tail is ~400 events across a few hundred distinct venue
strings, and the ingestion worker re-reads every feed every six hours. At
Nominatim's one request per second, re-geocoding the same names each cycle
would burn the entire budget re-deriving answers already known — and most
of those names will *never* resolve, so caching only the successes leaves
the dead ends costing full price forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session

from app.models.geocode_cache import GeocodeCacheEntry
from app.services.geocoding import GeocodeResult, VenueGeocoder

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
OAKLAND_BAR = GeocodeResult(
    lat=37.8097, lon=-122.2671, confidence=0.85, precision="poi", provider="stub"
)


class _CountingProvider:
    """Records every call so a test can assert the cache actually saved one."""

    name = "stub"

    def __init__(self, result: GeocodeResult | None = OAKLAND_BAR) -> None:
        self.result = result
        self.queries: list[str] = []

    async def lookup(self, query: str) -> GeocodeResult | None:
        self.queries.append(query)
        return self.result


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    GeocodeCacheEntry.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _geocoder(provider, *, now=NOW, **kwargs) -> VenueGeocoder:
    return VenueGeocoder(provider=provider, clock=lambda: now, **kwargs)


async def test_a_venue_already_in_the_static_table_never_reaches_the_provider() -> None:
    """The hand-maintained table is exact and free; it stays the first pass."""
    provider = _CountingProvider()
    result = await _geocoder(provider).resolve(
        session=None, venue_name="The Fillmore", raw_address=None, city="San Francisco"
    )

    assert result is not None
    assert provider.queries == []
    assert result.confidence >= 0.9


async def test_the_same_venue_is_geocoded_once_and_then_read_from_cache(session) -> None:
    provider = _CountingProvider()
    geocoder = _geocoder(provider)

    first = await geocoder.resolve(
        session=session, venue_name="Good Times Oakland", raw_address=None, city="Oakland"
    )
    second = await geocoder.resolve(
        session=session, venue_name="Good Times Oakland", raw_address=None, city="Oakland"
    )

    assert len(provider.queries) == 1
    assert first == second
    assert first is not None and (first.lat, first.lon) == (OAKLAND_BAR.lat, OAKLAND_BAR.lon)


async def test_a_failed_lookup_is_remembered_so_it_is_not_retried_every_cycle(session) -> None:
    """Most of the tail never resolves. Without negative caching those names
    consume the whole per-cycle budget, every cycle, forever."""
    provider = _CountingProvider(result=None)
    geocoder = _geocoder(provider)

    assert await geocoder.resolve(
        session=session, venue_name="Noe Valley Farm", raw_address=None, city=None
    ) is None
    assert await geocoder.resolve(
        session=session, venue_name="Noe Valley Farm", raw_address=None, city=None
    ) is None

    assert len(provider.queries) == 1


async def test_a_stale_failure_is_retried_because_the_map_gains_places(session) -> None:
    provider = _CountingProvider(result=None)
    await _geocoder(provider, failure_retry_days=30).resolve(
        session=session, venue_name="Noe Valley Farm", raw_address=None, city=None
    )

    later = NOW + timedelta(days=31)
    await _geocoder(provider, now=later, failure_retry_days=30).resolve(
        session=session, venue_name="Noe Valley Farm", raw_address=None, city=None
    )

    assert len(provider.queries) == 2


async def test_a_raw_address_is_preferred_over_the_venue_name(session) -> None:
    """Rows already carry a usable street address; it geocodes far better
    than "Local Economy" does."""
    provider = _CountingProvider()
    await _geocoder(provider).resolve(
        session=session,
        venue_name="Local Economy",
        raw_address="6028 College Ave, Oakland, CA",
        city="Oakland",
    )

    assert provider.queries == ["6028 College Ave, Oakland, CA"]


async def test_a_bare_venue_name_is_qualified_with_its_city(session) -> None:
    """"Good Times" alone is ambiguous everywhere; "Good Times, Oakland, CA"
    is not."""
    provider = _CountingProvider()
    await _geocoder(provider).resolve(
        session=session, venue_name="Good Times", raw_address=None, city="Oakland"
    )

    assert provider.queries == ["Good Times, Oakland, CA"]


async def test_lookups_stop_at_the_per_run_ceiling(session) -> None:
    """A new source dumping thousands of unknown venues must not turn one
    ingestion cycle into an hours-long serial crawl."""
    provider = _CountingProvider()
    geocoder = _geocoder(provider, max_lookups_per_run=2)

    for i in range(5):
        await geocoder.resolve(
            session=session, venue_name=f"Unknown Space {i}", raw_address=None, city=None
        )

    assert len(provider.queries) == 2


async def test_no_provider_configured_resolves_nothing_beyond_the_static_table(session) -> None:
    """Deployments without a geocoder keep exactly today's behaviour."""
    geocoder = VenueGeocoder(provider=None)

    assert await geocoder.resolve(
        session=session, venue_name="Good Times Oakland", raw_address=None, city="Oakland"
    ) is None
    assert await geocoder.resolve(
        session=session, venue_name="The Fillmore", raw_address=None, city="San Francisco"
    ) is not None


async def test_a_venue_name_that_is_really_an_address_falls_back_to_the_address(session) -> None:
    """Sources emit whole address strings in the venue field — "Local Economy,
    6028 College Ave, Oakland". Verified against Nominatim on 2026-08-23: that
    string resolves to nothing, while "6028 College Ave, Oakland" resolves to a
    building. Dropping the name prefix is the difference between a searchable
    event and an invisible one."""

    class _AddressOnly:
        name = "stub"

        def __init__(self) -> None:
            self.queries: list[str] = []

        async def lookup(self, query: str) -> GeocodeResult | None:
            self.queries.append(query)
            return OAKLAND_BAR if query.startswith("6028 College Ave") else None

    provider = _AddressOnly()
    result = await _geocoder(provider).resolve(
        session=session,
        venue_name="Local Economy, 6028 College Ave, Oakland",
        raw_address=None,
        city="Oakland",
    )

    assert result is not None
    assert provider.queries[-1].startswith("6028 College Ave")


async def test_the_whole_attempt_sequence_is_cached_as_one_answer(session) -> None:
    """A name needing two attempts must not cost two attempts every cycle."""

    class _NeverResolves:
        name = "stub"

        def __init__(self) -> None:
            self.queries: list[str] = []

        async def lookup(self, query: str) -> GeocodeResult | None:
            self.queries.append(query)
            return None

    provider = _NeverResolves()
    geocoder = _geocoder(provider)
    for _ in range(2):
        await geocoder.resolve(
            session=session,
            venue_name="Local Economy, 6028 College Ave, Oakland",
            raw_address=None,
            city="Oakland",
        )

    first_pass = len(set(provider.queries))
    assert len(provider.queries) == first_pass


async def test_a_placeholder_venue_name_is_never_geocoded(session) -> None:
    """Observed on real data 2026-08-23: an event whose venue is literally
    "TBA" geocoded to a POI near Merced at 0.85 — a fabricated location,
    shipped confidently, 100 miles from the event. A placeholder is the
    absence of a venue, not a venue with an unusual name."""
    provider = _CountingProvider()

    for placeholder in [
        "TBA",
        "tbd",
        "TBA (San Francisco)",
        "Secret Location",
        "Private Residence",
        "Various Locations",
        "Online",
    ]:
        result = await _geocoder(provider).resolve(
            session=session, venue_name=placeholder, raw_address=None, city="San Francisco"
        )
        assert result is None, f"{placeholder!r} must not resolve"

    assert provider.queries == []


async def test_a_real_address_still_resolves_when_the_venue_is_a_placeholder(session) -> None:
    """The placeholder is only the name. An address alongside it is real."""
    provider = _CountingProvider()
    result = await _geocoder(provider).resolve(
        session=session,
        venue_name="TBA",
        raw_address="6028 College Ave, Oakland, CA",
        city="Oakland",
    )

    assert result is not None
    assert provider.queries == ["6028 College Ave, Oakland, CA"]
