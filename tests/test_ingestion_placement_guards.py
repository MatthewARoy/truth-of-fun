"""Small ingestion guards: yearless dates, venue-name matching, centroid confidence."""

from __future__ import annotations

from datetime import date

import pytest

from app.ingestion.scraper_utils import infer_listing_year
from app.ingestion.venue_cache import lookup_venue_coordinates


@pytest.mark.parametrize(
    ("month", "day", "today", "expected"),
    [
        (1, 3, date(2026, 11, 12), 2027),   # January listing seen in November
        (11, 20, date(2026, 11, 12), 2026),  # next week
        (11, 1, date(2026, 11, 12), 2026),   # just passed: still this year
        (12, 30, date(2027, 1, 2), 2026),    # lingering December listing in January
        (3, 15, date(2026, 12, 20), 2027),
        (2, 29, date(2027, 1, 10), 2027),    # impossible date: left for the caller to reject
    ],
)
def test_yearless_listing_dates_resolve_to_their_next_occurrence(month, day, today, expected) -> None:
    assert infer_listing_year(month, day, today) == expected


@pytest.mark.parametrize("name", ["Oakland", "San Jose", "Center", "SF", "Audio Visual Lab", "F8 1192 Folsom"])
def test_generic_words_and_city_names_are_not_venues(name: str) -> None:
    # Each of these used to resolve, at full confidence, to an unrelated venue
    # whose key merely contained (or was contained in) the string.
    assert lookup_venue_coordinates(name) is None


def test_known_venues_still_resolve_through_decoration_and_missing_articles() -> None:
    fillmore = lookup_venue_coordinates("The Fillmore")
    assert fillmore is not None
    assert lookup_venue_coordinates("Fillmore") == fillmore
    assert lookup_venue_coordinates("The Fillmore - San Francisco") == fillmore
    assert lookup_venue_coordinates("Audio (21+)") == lookup_venue_coordinates("Audio")
    assert lookup_venue_coordinates("SFJAZZ Center - Miner Auditorium") is not None
    # A longer, more specific key beats the venue it starts like.
    assert lookup_venue_coordinates("The Chapel of the Chimes") != lookup_venue_coordinates("The Chapel")


def test_meetup_without_venue_coordinates_is_not_a_confident_pin() -> None:
    from app.ingestion.sources.meetup import MeetupSource

    source = MeetupSource.__new__(MeetupSource)
    raw = {
        "id": "abc", "title": "Online founders chat", "dateTime": "2026-12-01T18:00:00-08:00",
        "eventUrl": "https://www.meetup.com/x/events/1/", "venue": {"name": "Online event"},
    }
    event = source.normalize_raw(raw)
    assert event is not None
    assert event.location.location_confidence < 0.5
    with_geo = source.normalize_raw({**raw, "venue": {"name": "Hall", "lat": 37.8, "lon": -122.27}})
    assert with_geo.location.location_confidence >= 0.8
