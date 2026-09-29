"""Backfilling coordinates for events already in the database.

The ingestion hook only reaches events a source re-emits. Events whose
listing has already rolled off the feed keep the centroid they were stored
with and stay invisible to radius search forever. This script is what moves
the rows that are stuck.
"""

from __future__ import annotations

import pytest

from app.services.geocoding import GeocodeResult, worth_writing
from scripts.backfill_geocode import GeocodeCandidate, plan_backfill

pytestmark = pytest.mark.anyio

RESOLVED = GeocodeResult(
    lat=37.8446, lon=-122.2560, confidence=0.85, precision="poi", provider="stub"
)
AREA = GeocodeResult(
    lat=37.8044, lon=-122.2712, confidence=0.4, precision="area", provider="stub"
)


class _StubGeocoder:
    def __init__(self, result: GeocodeResult | None = RESOLVED) -> None:
        self.result = result
        self.calls: list[str | None] = []

    def reset_run_budget(self) -> None:
        return None

    async def resolve(self, *, session, venue_name, raw_address, city):
        self.calls.append(raw_address or venue_name)
        return self.result


def _candidate(**overrides) -> GeocodeCandidate:
    fields = {
        "event_id": 1,
        "title": "Backyard set",
        "venue_name": "Local Economy",
        "raw_address": "6028 College Ave, Oakland, CA",
        "location_confidence": 0.4,
    }
    fields.update(overrides)
    return GeocodeCandidate(**fields)


def test_a_precise_answer_is_worth_writing_over_a_centroid() -> None:
    assert worth_writing(RESOLVED, 0.4) is True


def test_an_area_answer_is_the_fallback_the_row_already_has() -> None:
    assert worth_writing(AREA, 0.4) is False


def test_nothing_is_written_when_the_provider_resolved_nothing() -> None:
    assert worth_writing(None, 0.4) is False


async def test_a_stuck_centroid_row_gets_a_planned_coordinate() -> None:
    changes = await plan_backfill(
        session=None, geocoder=_StubGeocoder(), candidates=[_candidate()]
    )

    assert len(changes) == 1
    assert changes[0].event_id == 1
    assert changes[0].result == RESOLVED


async def test_a_row_that_cannot_be_resolved_is_left_alone() -> None:
    changes = await plan_backfill(
        session=None, geocoder=_StubGeocoder(None), candidates=[_candidate()]
    )

    assert changes == []


async def test_an_already_searchable_row_is_never_geocoded() -> None:
    """Spending a rate-limited lookup to reconfirm a hand-verified venue is
    budget taken from a row that actually needs it."""
    geocoder = _StubGeocoder()

    changes = await plan_backfill(
        session=None,
        geocoder=geocoder,
        candidates=[_candidate(location_confidence=0.9)],
    )

    assert geocoder.calls == []
    assert changes == []
