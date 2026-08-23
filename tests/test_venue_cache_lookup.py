"""Venue coordinate lookup: punctuation, city safety and specificity.

An unresolved venue falls back to a city/SF centroid with a low
``location_confidence``, and the discovery radius filter drops anything
below ``min_location_confidence`` (default 0.5). So a lookup miss silently
removes the event from every distance-based query — and a *wrong* hit is
worse still, placing an out-of-town event in San Francisco at full
confidence.
"""

from __future__ import annotations

from app.ingestion.venue_cache import (
    CITY_COORDINATES,
    VENUE_COORDINATES,
    lookup_venue_coordinates,
)

SF = CITY_COORDINATES["san francisco"]


def test_curly_apostrophe_resolves_same_as_straight_apostrophe() -> None:
    """Scrapers emit U+2019 ('Cobb’s'); the cache stores U+0027 ('Cobb's')."""
    straight = lookup_venue_coordinates("Cobb's Comedy Club")
    curly = lookup_venue_coordinates("Cobb’s Comedy Club")
    assert straight is not None
    assert curly == straight


def test_same_named_venue_in_another_city_does_not_resolve_to_sf() -> None:
    """'Punch Line Comedy Club - Sacramento' shares a name prefix with the SF
    club. Returning the SF coordinate would place a Sacramento show in SF."""
    sf_coords = lookup_venue_coordinates("Punch Line Comedy Club - San Francisco")
    assert sf_coords is not None
    assert lookup_venue_coordinates("Punch Line Comedy Club - Sacramento") != sf_coords


def test_oakland_venue_does_not_match_sf_venue_of_similar_name() -> None:
    """'The Independent Bar & Grill, Oakland' must not resolve to SF's
    The Independent on Divisadero."""
    assert lookup_venue_coordinates("The Independent Bar & Grill, Oakland") != (
        VENUE_COORDINATES["the independent"]
    )


def test_ggp_bandshell_resolves_to_golden_gate_park() -> None:
    """The bandshell hosts the free Sunday concerts; it must not fall through
    to the SoMa nightclub 'Temple' on a loose substring match."""
    coords = lookup_venue_coordinates("Spreckels Temple of Music (GGP Bandshell)")
    assert coords is not None
    assert coords != VENUE_COORDINATES["temple nightclub"]


def test_central_corridor_venues_are_known() -> None:
    """Venues that recur in the live feed and anchor Mission/Castro nights."""
    for name in [
        "Cafe du Nord",
        "The Roxie",
        "Biscuits and Blues",
        "Madrone Art Bar",
        "The Midway",
        "Halcyon",
        "Japanese Tea Garden",
    ]:
        assert lookup_venue_coordinates(name) is not None, f"unresolved venue: {name}"
