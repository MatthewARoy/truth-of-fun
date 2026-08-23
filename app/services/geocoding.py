"""Geocoding for venues the static coordinate table cannot resolve.

``app.ingestion.venue_cache`` is a hand-maintained table of well-known Bay
Area venues. It is fast, offline and exact, but it only ever covers names
somebody typed in. The remainder is a long tail of one-off spaces, private
addresses and raw address strings, and a miss there is not cosmetic: the
event falls back to a city centroid with a low ``location_confidence`` and
the discovery radius filter then drops it from every distance query.

This module adds a real geocoder behind that table. The static table stays
the first pass; the provider is consulted only on a miss.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.ingestion.rate_limiter import AsyncRateLimiter
from app.ingestion.venue_cache import lookup_venue_coordinates, normalize_place_text
from app.models.geocode_cache import GeocodeCacheEntry

logger = logging.getLogger(__name__)

# Mirrors ``DEFAULT_MIN_LOCATION_CONFIDENCE`` in app.api.discovery: below
# this, radius search excludes the event. A geocoded coordinate is only
# worth writing if it clears the bar, so the mapping below is expressed in
# terms of it. tests/test_geocoding_provider.py pins the two together.
MIN_SEARCHABLE_LOCATION_CONFIDENCE = 0.5


@dataclass(frozen=True)
class GeocodeResult:
    """A resolved coordinate plus how precisely the provider resolved it."""

    lat: float
    lon: float
    confidence: float
    precision: str
    provider: str


# Nominatim's ``place_rank`` is an address-hierarchy rank, not a score:
# 30 is a POI or house number, 26-27 a street, and anything coarser is an
# area — a suburb, town or city. See nominatim.org "Ranking".
_RANK_POI = 30
_RANK_STREET = 26


def _precision_for_rank(place_rank: int) -> tuple[str, float]:
    """Map a provider rank onto a precision label and a confidence.

    Deliberately capped below the 0.9 the curated table claims: a geocoder
    guess is good, but a coordinate somebody verified by hand is better.
    """
    if place_rank >= _RANK_POI:
        return "poi", 0.85
    if place_rank >= _RANK_STREET:
        return "street", 0.7
    # A town or city rank is the centroid fallback wearing a provider's
    # name. It must stay under the radius threshold rather than dress a
    # guess up as a location.
    return "area", 0.4


# A generous box around Northern California, matching the reach of the
# static venue table. Sent to the provider as a hard bound *and* re-checked
# on the way back: "Good Times" matches a bar in Florida, and a confident
# coordinate in the wrong state is worse than no coordinate at all.
NORCAL_BOUNDS = (36.0, 40.0, -124.5, -119.0)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


# A house number followed by a street name: "6028 College Ave".
_STREET_ADDRESS = re.compile(r"^\d{1,6}\s+\S")


def _street_address_within(value: str | None) -> str | None:
    """The address embedded in a comma-separated string, if there is one.

    "Local Economy, 6028 College Ave, Oakland" carries a real address behind
    a venue name the geocoder has never heard of.
    """
    if not value:
        return None
    parts = [part.strip() for part in value.split(",")]
    for index, part in enumerate(parts):
        if _STREET_ADDRESS.match(part):
            if index == 0:
                return None  # already leads with the address; not a variant
            return ", ".join(parts[index:])
    return None


def _within_norcal(lat: float, lon: float) -> bool:
    min_lat, max_lat, min_lon, max_lon = NORCAL_BOUNDS
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


class NominatimProvider:
    """Geocoder backed by OpenStreetMap's public Nominatim service.

    Nominatim is free and needs no key, which is why it is the default: an
    unconfigured deployment still gets better coordinates. In exchange its
    usage policy caps callers at one request per second and requires a
    descriptive User-Agent, both enforced here.
    """

    name = "nominatim"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        user_agent: str | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        base_url: str = NOMINATIM_SEARCH_URL,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url
        self._user_agent = user_agent or get_settings().geocoding_user_agent
        # Nominatim's public instance permits one request per second. Going
        # over it gets the whole deployment blocked, not throttled.
        self._rate_limiter = rate_limiter or AsyncRateLimiter(1, 1.0)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
        return self._client

    async def lookup(self, query: str) -> GeocodeResult | None:
        await self._rate_limiter.acquire()

        min_lat, max_lat, min_lon, max_lon = NORCAL_BOUNDS
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": "1",
            "countrycodes": "us",
            # viewbox is <lon>,<lat>,<lon>,<lat>; bounded=1 makes it a filter
            # rather than a preference.
            "viewbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
            "bounded": "1",
        }

        try:
            response = await self._get_client().get(
                self._base_url,
                params=params,
                headers={"User-Agent": self._user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            # Ingestion must survive an unreachable or angry provider: the
            # caller keeps its centroid fallback and the cycle continues.
            logger.warning("geocoding lookup failed for %r", query, exc_info=True)
            return None

        if not isinstance(payload, list) or not payload:
            return None

        return self._to_result(payload[0])

    def _to_result(self, top: dict) -> GeocodeResult | None:
        try:
            lat = float(top["lat"])
            lon = float(top["lon"])
            place_rank = int(top.get("place_rank", 0))
        except (KeyError, TypeError, ValueError):
            return None

        if not _within_norcal(lat, lon):
            logger.info("discarding out-of-region geocode result at (%s, %s)", lat, lon)
            return None

        precision, confidence = _precision_for_rank(place_rank)
        return GeocodeResult(
            lat=lat,
            lon=lon,
            confidence=confidence,
            precision=precision,
            provider=self.name,
        )

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


# The static table is verified by hand, so it outranks anything a provider
# returns. Sources already stamp 0.9 for a table hit; this keeps a standalone
# resolve (the backfill script) consistent with them.
STATIC_TABLE_CONFIDENCE = 0.9


def worth_writing(result: GeocodeResult | None, current_confidence: float) -> bool:
    """Whether a provider answer beats what the row already carries.

    An answer that only resolves to an area *is* the centroid fallback the
    row already has: writing it trades a recognisable city-centre guess for
    an unrecognisable one and still fails the radius filter. Shared by the
    ingestion hook and the backfill script so the two cannot drift.
    """
    if result is None:
        return False
    if result.confidence < MIN_SEARCHABLE_LOCATION_CONFIDENCE:
        return False
    return result.confidence > current_confidence


class GeocodeProvider(Protocol):
    """A geocoder. ``lookup`` never raises: an unavailable provider returns
    ``None`` so the caller keeps its centroid fallback."""

    name: str

    async def lookup(self, query: str) -> GeocodeResult | None: ...


class VenueGeocoder:
    """Resolve a venue: static table first, then a rate-limited provider.

    Provider answers are cached in Postgres, successes and failures alike,
    so a venue costs one lookup rather than one per ingestion cycle.
    """

    def __init__(
        self,
        *,
        provider: GeocodeProvider | None,
        max_lookups_per_run: int | None = None,
        failure_retry_days: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        settings = get_settings()
        self._provider = provider
        self._max_lookups_per_run = (
            settings.geocoding_max_lookups_per_run
            if max_lookups_per_run is None
            else max_lookups_per_run
        )
        self._failure_retry_days = (
            settings.geocoding_failure_retry_days
            if failure_retry_days is None
            else failure_retry_days
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lookups_this_run = 0

    @property
    def provider(self) -> GeocodeProvider | None:
        return self._provider

    @property
    def max_lookups_per_run(self) -> int:
        return self._max_lookups_per_run

    @property
    def failure_retry_days(self) -> int:
        return self._failure_retry_days

    @property
    def lookups_this_run(self) -> int:
        return self._lookups_this_run

    def reset_run_budget(self) -> None:
        self._lookups_this_run = 0

    async def resolve(
        self,
        *,
        session: Session | None,
        venue_name: str | None,
        raw_address: str | None,
        city: str | None,
    ) -> GeocodeResult | None:
        coords = lookup_venue_coordinates(venue_name)
        if coords is not None:
            return GeocodeResult(
                lat=coords[0],
                lon=coords[1],
                confidence=STATIC_TABLE_CONFIDENCE,
                precision="venue",
                provider="venue_cache",
            )

        if self._provider is None:
            return None

        attempts = self._query_variants(
            venue_name=venue_name, raw_address=raw_address, city=city
        )
        if not attempts:
            return None

        # Keyed on the first (most specific) attempt: the fallbacks are an
        # implementation detail, so a name needing two calls still costs one
        # cache entry and is not retried next cycle.
        key = normalize_place_text(attempts[0])
        cached = self._read_cache(session, key)
        if cached is not None:
            return cached.result

        result: GeocodeResult | None = None
        for query in attempts:
            if self._lookups_this_run >= self._max_lookups_per_run:
                logger.info(
                    "geocoding budget of %d lookups exhausted for this run; %r deferred",
                    self._max_lookups_per_run,
                    query,
                )
                return None
            self._lookups_this_run += 1
            result = await self._provider.lookup(query)
            if result is not None:
                break

        self._write_cache(session, key=key, result=result)
        return result

    @classmethod
    def _query_variants(
        cls, *, venue_name: str | None, raw_address: str | None, city: str | None
    ) -> list[str]:
        """The queries to try, most specific first.

        Many rows already carry a usable ``raw_address`` that nothing was
        reading, so it leads. A bare name is qualified with its city —
        "Good Times" is ambiguous everywhere, "Good Times, Oakland, CA" is
        not. Finally, sources emit whole address strings in the venue field
        ("Local Economy, 6028 College Ave, Oakland"): checked against
        Nominatim, that string resolves to nothing while the address inside
        it resolves to a building, so the name prefix is worth dropping.
        """
        attempts: list[str] = []

        def add(candidate: str | None) -> None:
            if candidate and candidate.strip() and candidate.strip() not in attempts:
                attempts.append(candidate.strip())

        add(cls._qualify(raw_address, city))
        add(cls._qualify(venue_name, city))
        for source in (raw_address, venue_name):
            add(cls._qualify(_street_address_within(source), city))

        return attempts

    @staticmethod
    def _qualify(value: str | None, city: str | None) -> str | None:
        """Append the city unless the string already names it."""
        if not value or not value.strip():
            return None
        text = value.strip()
        if city and city.strip() and city.strip().lower() not in text.lower():
            return f"{text}, {city.strip()}, CA"
        return text

    def _read_cache(self, session: Session | None, key: str) -> _CacheHit | None:
        if session is None:
            return None
        entry = session.get(GeocodeCacheEntry, key)
        if entry is None:
            return None

        if entry.resolved:
            return _CacheHit(
                GeocodeResult(
                    lat=float(entry.lat or 0.0),
                    lon=float(entry.lon or 0.0),
                    confidence=float(entry.confidence or 0.0),
                    precision=entry.precision or "unknown",
                    provider=entry.provider,
                )
            )

        # A cached failure expires: the map gains places, and a venue that
        # was unknown last quarter may be on it now.
        looked_up_at = entry.looked_up_at
        if looked_up_at.tzinfo is None:
            looked_up_at = looked_up_at.replace(tzinfo=timezone.utc)
        if self._clock() - looked_up_at >= timedelta(days=self._failure_retry_days):
            return None
        return _CacheHit(None)

    def _write_cache(
        self, session: Session | None, *, key: str, result: GeocodeResult | None
    ) -> None:
        if session is None:
            return
        entry = session.get(GeocodeCacheEntry, key) or GeocodeCacheEntry(query_key=key)
        entry.provider = result.provider if result else getattr(self._provider, "name", "unknown")
        entry.lat = result.lat if result else None
        entry.lon = result.lon if result else None
        entry.confidence = result.confidence if result else None
        entry.precision = result.precision if result else None
        entry.resolved = result is not None
        entry.looked_up_at = self._clock()
        session.add(entry)


@dataclass(frozen=True)
class _CacheHit:
    """Distinguishes "cached as unresolvable" from "not cached at all"."""

    result: GeocodeResult | None


def build_geocoder(settings: Settings | None = None) -> VenueGeocoder:
    """Assemble the geocoder a deployment's settings ask for.

    An unset or unrecognised ``geocoding_provider`` yields a geocoder with no
    provider rather than ``None``: it still answers from the static venue
    table, and every caller has one code path instead of two. A typo in an
    env var costs resolution, never the ingestion run.
    """
    settings = settings or get_settings()
    name = (settings.geocoding_provider or "").strip().lower()

    provider: GeocodeProvider | None = None
    if name == "nominatim":
        provider = NominatimProvider(user_agent=settings.geocoding_user_agent)
    elif name:
        logger.warning(
            "unknown geocoding_provider %r; geocoding disabled. Known providers: nominatim",
            settings.geocoding_provider,
        )

    return VenueGeocoder(
        provider=provider,
        max_lookups_per_run=settings.geocoding_max_lookups_per_run,
        failure_retry_days=settings.geocoding_failure_retry_days,
    )
