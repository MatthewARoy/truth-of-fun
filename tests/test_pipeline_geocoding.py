"""Geocoding enrichment inside the ingestion pipeline.

Sources resolve venues against a static table and fall back to a city
centroid at ``location_confidence`` 0.4, which radius search excludes. This
step gives the pipeline one more chance at a real coordinate before the row
is written — and, because the pipeline already treats a confidence bump as
significant new information, it also upgrades rows stored on a centroid the
next time the source re-emits them.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.data_pipeline import DataPipelineService
from app.services.geocoding import GeocodeResult

pytestmark = pytest.mark.anyio

START = datetime(2026, 9, 6, 19, 0, tzinfo=timezone.utc)
SF_CENTROID = "POINT(-122.4194 37.7749)"
RESOLVED = GeocodeResult(
    lat=37.8446, lon=-122.2560, confidence=0.85, precision="poi", provider="stub"
)


def _payload(**overrides) -> dict:
    payload = {
        "title": "Backyard set at an unlisted space",
        "start_at": START,
        "source_name": "eddies_list",
        "source_tier": 3,
        "venue_name": "Local Economy",
        "raw_address": "6028 College Ave, Oakland, CA",
        "location": SF_CENTROID,
        "categories": [],
        "tags": [],
        "status": "scheduled",
        "attendee_count": 0,
        "location_confidence": 0.4,
        "is_free": False,
    }
    payload.update(overrides)
    return payload


class _StubGeocoder:
    def __init__(self, result: GeocodeResult | None = RESOLVED) -> None:
        self.result = result
        self.calls: list[dict] = []

    def reset_run_budget(self) -> None:
        return None

    async def resolve(self, *, session, venue_name, raw_address, city) -> GeocodeResult | None:
        self.calls.append({"venue_name": venue_name, "raw_address": raw_address, "city": city})
        return self.result


def _service(geocoder=None) -> DataPipelineService:
    return DataPipelineService(vibe_tagger=_NoTags(), geocoder=geocoder)


class _NoTags:
    async def generate_vibe_tags(self, description):
        return []


async def test_a_centroid_row_gets_the_geocoded_coordinate_and_confidence() -> None:
    service = _service(_StubGeocoder())

    enriched = await service.enrich_locations(session=None, events=[_payload()])

    assert enriched[0]["location"] == f"POINT({RESOLVED.lon} {RESOLVED.lat})"
    assert enriched[0]["location_confidence"] == RESOLVED.confidence


async def test_an_already_precise_row_is_not_geocoded() -> None:
    """A venue the static table resolved is better than any provider answer,
    and spending a rate-limited lookup to confirm it is pure waste."""
    geocoder = _StubGeocoder()

    await _service(geocoder).enrich_locations(
        session=None, events=[_payload(location_confidence=0.9)]
    )

    assert geocoder.calls == []


async def test_an_area_level_answer_does_not_replace_the_centroid() -> None:
    """Resolving only to the city is the fallback the row already has.
    Rewriting the coordinate gains nothing and loses the city centroid the
    repair script can recognise."""
    area = GeocodeResult(
        lat=37.8044, lon=-122.2712, confidence=0.4, precision="area", provider="stub"
    )
    enriched = await _service(_StubGeocoder(area)).enrich_locations(
        session=None, events=[_payload()]
    )

    assert enriched[0]["location"] == SF_CENTROID
    assert enriched[0]["location_confidence"] == 0.4


async def test_no_geocoder_leaves_every_payload_exactly_as_it_was() -> None:
    """The unconfigured deployment must behave precisely as it does today."""
    original = _payload()
    enriched = await _service(None).enrich_locations(session=None, events=[dict(original)])

    assert enriched == [original]


async def test_a_geocoder_failure_leaves_the_payload_on_its_centroid() -> None:
    """An unreachable provider degrades to today's behaviour, it does not
    take the ingestion cycle down with it."""

    class _Exploding:
        def reset_run_budget(self) -> None:
            return None

        async def resolve(self, **kwargs):
            raise RuntimeError("provider on fire")

    original = _payload()
    enriched = await _service(_Exploding()).enrich_locations(
        session=None, events=[dict(original)]
    )

    assert enriched == [original]


async def test_the_geocoder_is_given_the_address_and_city_it_needs() -> None:
    geocoder = _StubGeocoder()
    await _service(geocoder).enrich_locations(
        session=None, events=[_payload(raw_address="84 Serrano Dr, Atherton")]
    )

    assert geocoder.calls == [
        {
            "venue_name": "Local Economy",
            "raw_address": "84 Serrano Dr, Atherton",
            "city": None,
        }
    ]


async def test_the_per_run_lookup_budget_refreshes_each_ingestion_cycle() -> None:
    """The ceiling bounds one cycle. A worker that lives for weeks must not
    spend its budget on the first cycle and never geocode again."""
    from app.services.geocoding import VenueGeocoder

    class _Provider:
        name = "stub"

        def __init__(self) -> None:
            self.queries: list[str] = []

        async def lookup(self, query: str) -> GeocodeResult | None:
            self.queries.append(query)
            return RESOLVED

    provider = _Provider()
    service = _service(VenueGeocoder(provider=provider, max_lookups_per_run=1))

    await service.enrich_locations(session=None, events=[_payload()])
    await service.enrich_locations(
        session=None, events=[_payload(raw_address="84 Serrano Dr, Atherton")]
    )

    assert len(provider.queries) == 2
