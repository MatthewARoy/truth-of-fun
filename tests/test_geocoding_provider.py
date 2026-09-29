"""Nominatim geocoding: precision, safety bounds, and graceful failure.

An unresolved venue lands on a city centroid with a low
``location_confidence``, and the discovery radius filter drops anything
below 0.5 — so the venue is invisible to every distance query. Geocoding
is how the long tail of one-off spaces and raw address strings becomes
searchable.

The failure that matters most is not a miss but a *wrong hit*: a plausible
coordinate in the wrong place ships at full confidence and plants an event
somewhere it is not. These tests pin the guards against that.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.geocoding import (
    GeocodingUnavailable,
    MIN_SEARCHABLE_LOCATION_CONFIDENCE,
    NominatimProvider,
)

pytestmark = pytest.mark.anyio


def _response(payload: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _provider(transport: httpx.MockTransport) -> NominatimProvider:
    return NominatimProvider(client=httpx.AsyncClient(transport=transport))


POI = {
    "lat": "37.8097",
    "lon": "-122.2671",
    "place_rank": 30,
    "addresstype": "bar",
    "display_name": "Good Times, Oakland, California, United States",
}


async def test_building_level_result_is_precise_enough_for_radius_search() -> None:
    """place_rank 30 is a POI or house number — an actual address, not an area."""
    result = await _provider(_response([POI])).lookup("Good Times Oakland")

    assert result is not None
    assert (result.lat, result.lon) == (37.8097, -122.2671)
    assert result.precision == "poi"
    assert result.confidence >= 0.5


async def test_street_level_result_is_searchable_but_below_a_verified_venue() -> None:
    """A road centroid is the right block, not the right door."""
    street = {**POI, "place_rank": 26, "addresstype": "road"}
    result = await _provider(_response([street])).lookup("6028 College Ave, Oakland")

    assert result is not None
    assert result.precision == "street"
    assert MIN_SEARCHABLE_LOCATION_CONFIDENCE <= result.confidence < 0.85


async def test_city_level_result_does_not_pass_the_radius_filter() -> None:
    """Resolving only to "Oakland" is the centroid fallback in disguise.

    Handing it a searchable confidence would push a guess *through* the
    radius filter — strictly worse than leaving the event out of it.
    """
    city = {**POI, "place_rank": 16, "addresstype": "city"}
    result = await _provider(_response([city])).lookup("Noe Valley Farm")

    assert result is not None
    assert result.confidence < MIN_SEARCHABLE_LOCATION_CONFIDENCE


async def test_result_outside_northern_california_is_rejected() -> None:
    """"Good Times" matches a bar in Florida too. A confident coordinate
    2,000 miles away is worse than no coordinate at all."""
    florida = {**POI, "lat": "27.9506", "lon": "-82.4572"}
    assert await _provider(_response([florida])).lookup("Good Times") is None


async def test_empty_result_set_resolves_to_nothing() -> None:
    assert await _provider(_response([])).lookup("Noe Valley Farm") is None


async def test_provider_failure_is_distinct_from_a_genuine_no_match() -> None:
    """Ingestion must survive an unreachable provider: the event keeps its
    centroid rather than the whole cycle dying on a 503."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nominatim unreachable")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(GeocodingUnavailable):
        await provider.lookup("Local Economy, 6028 College Ave, Oakland")


async def test_http_error_status_is_reported_as_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    with pytest.raises(GeocodingUnavailable):
        await _provider(httpx.MockTransport(handler)).lookup("anywhere")


async def test_request_identifies_this_client_and_is_bounded_to_the_bay_area() -> None:
    """Nominatim's usage policy requires a descriptive User-Agent, and the
    viewbox is the cheapest defence against a same-named venue elsewhere."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["user_agent"] = request.headers.get("user-agent")
        seen["params"] = dict(request.url.params)
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[POI])

    await _provider(httpx.MockTransport(handler)).lookup("Good Times Oakland")

    assert "truth-of-fun" in str(seen["user_agent"])
    params = seen["params"]
    assert params["format"] == "jsonv2"
    assert params["countrycodes"] == "us"
    assert params["bounded"] == "1"
    assert params["viewbox"]
    assert params["q"] == "Good Times Oakland"


async def test_threshold_matches_the_discovery_radius_default() -> None:
    """These two drifting apart would silently change what geocoding is for."""
    from app.api.discovery import DEFAULT_MIN_LOCATION_CONFIDENCE

    assert MIN_SEARCHABLE_LOCATION_CONFIDENCE == DEFAULT_MIN_LOCATION_CONFIDENCE
