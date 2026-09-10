"""An unresolved venue must not claim a searchable location.

When a venue name can't be geocoded the scrapers fall back to the SF
centroid. That coordinate is a guess about the city, not the event, so it
has to stay below the discovery radius filter's default
``min_location_confidence`` of 0.5 — otherwise the event is returned as if
it were at the exact centre of San Francisco.
"""

from __future__ import annotations

import pytest

from app.api.discovery import DEFAULT_MIN_LOCATION_CONFIDENCE
from app.ingestion.sources.dothebay import DoTheBaySource
from app.ingestion.sources.luma import LumaSource
from app.ingestion.sources.sfstation import SFStationSource

UNKNOWN_VENUE = "Totally Unknown Warehouse No One Has Cached"


@pytest.mark.parametrize(
    ("source", "raw_item"),
    [
        (
            DoTheBaySource(),
            {
                "title": "unresolved venue",
                "date_text": "2026-09-06",
                "time_text": "7:00PM",
                "venue_name": UNKNOWN_VENUE,
                "source_url": "https://dothebay.com/events/x",
                "source_record_id": "x",
            },
        ),
        (
            SFStationSource(),
            {
                "title": "unresolved venue",
                "date_iso": "2026-09-06",
                "time_text": "7:00PM",
                "venue_name": UNKNOWN_VENUE,
                "source_url": "https://www.sfstation.com/x",
                "source_record_id": "x",
            },
        ),
        (
            LumaSource(),
            {
                "title": "unresolved venue",
                "start_iso": "2026-09-06T19:00:00-07:00",
                "location_text": UNKNOWN_VENUE,
                "source_url": "https://lu.ma/x",
                "source_record_id": "x",
            },
        ),
    ],
    ids=["dothebay", "sfstation", "luma"],
)
def test_unresolved_venue_stays_below_radius_search_threshold(source, raw_item) -> None:
    event = source.normalize_raw(raw_item)

    assert event is not None
    assert event.location.location_confidence < DEFAULT_MIN_LOCATION_CONFIDENCE
