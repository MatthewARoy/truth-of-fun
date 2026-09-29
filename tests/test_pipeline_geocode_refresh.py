"""A better coordinate is new information.

The pipeline only rewrites an existing row when the incoming payload has
"significant new information". Location confidence was not part of that
test, so an event stored on a city-centroid guess kept that guess forever
— even after its venue became resolvable. The centroid then stays below
the radius-search threshold and the event is permanently invisible to
distance queries.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.event import Event
from app.services.data_pipeline import DataPipelineService

START = datetime(2026, 9, 6, 19, 0, tzinfo=timezone.utc)


def _existing(confidence: float) -> Event:
    return Event(
        title="Show at a newly cached venue",
        start_at=START,
        source_name="dothebay",
        source_tier=3,
        venue_name="Cafe du Nord",
        location="SRID=4326;POINT(-122.4194 37.7749)",
        categories=[],
        tags=[],
        status="scheduled",
        attendee_count=0,
        location_confidence=confidence,
        is_free=False,
    )


def _incoming(confidence: float) -> dict:
    return {
        "title": "Show at a newly cached venue",
        "start_at": START,
        "source_name": "dothebay",
        "source_tier": 3,
        "venue_name": "Cafe du Nord",
        "location": "SRID=4326;POINT(-122.4295 37.7669)",
        "categories": [],
        "tags": [],
        "status": "scheduled",
        "attendee_count": 0,
        "location_confidence": confidence,
        "is_free": False,
    }


def test_a_resolved_venue_replaces_a_stored_centroid_guess() -> None:
    service = DataPipelineService()

    assert service.has_significant_new_information(
        existing_event=_existing(0.4), incoming_event=_incoming(0.9)
    )


def test_an_equally_confident_coordinate_is_not_new_information() -> None:
    """Don't rewrite rows on every cycle just because the numbers match."""
    service = DataPipelineService()

    assert not service.has_significant_new_information(
        existing_event=_existing(0.9), incoming_event=_incoming(0.9)
    )


def test_a_worse_coordinate_never_replaces_a_better_one() -> None:
    service = DataPipelineService()

    assert not service.has_significant_new_information(
        existing_event=_existing(0.9), incoming_event=_incoming(0.4)
    )


CENTROID = "SRID=4326;POINT(-122.4194 37.7749)"
CAFE_DU_NORD = "SRID=4326;POINT(-122.4295 37.7669)"


def test_merge_takes_the_coordinate_that_earned_the_confidence() -> None:
    """location and location_confidence have to travel together.

    Taking max(confidence) while keeping the other payload's coordinate
    stamps a high confidence onto a centroid guess — which then passes the
    radius filter, making the data worse than leaving it alone.
    """
    service = DataPipelineService()
    low = {**_incoming(0.4), "location": CENTROID}
    high = {**_incoming(0.9), "location": CAFE_DU_NORD}

    merged = service._merge_event_payloads(primary=low, secondary=high)

    assert merged["location_confidence"] == 0.9
    assert merged["location"] == CAFE_DU_NORD


def test_merge_keeps_the_better_coordinate_when_it_is_already_primary() -> None:
    service = DataPipelineService()
    high = {**_incoming(0.9), "location": CAFE_DU_NORD}
    low = {**_incoming(0.4), "location": CENTROID}

    merged = service._merge_event_payloads(primary=high, secondary=low)

    assert merged["location_confidence"] == 0.9
    assert merged["location"] == CAFE_DU_NORD
