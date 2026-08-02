"""A plan you can carry: map links and a pasteable text rendering.

Covers the two things that make an itinerary portable rather than just
readable — links that open the right place in Maps, and a plain-text version
that survives being pasted into a message.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from dataclasses import dataclass

from app.services.itinerary import (
    StopLinks,
    StopLocation,
    build_stop_links,
    directions_url,
    format_local_day,
    format_local_time,
    itinerary_title,
    map_url,
    nearby_search_url,
    render_itinerary_text,
)

CHAPEL = StopLocation(
    venue_name="The Chapel",
    address="777 Valencia St, San Francisco, CA",
    lat=37.7599,
    lng=-122.4214,
    location_confidence=0.9,
)

TRUE_LAUREL = StopLocation(
    venue_name="True Laurel",
    address="753 Alabama St, San Francisco, CA",
    lat=37.7601,
    lng=-122.4118,
    location_confidence=0.9,
)


def _query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_directions_route_from_the_previous_stop() -> None:
    url = directions_url(destination=CHAPEL, origin=TRUE_LAUREL)
    params = _query_params(url)
    assert params["destination"] == ["37.7599,-122.4214"]
    assert params["origin"] == ["37.7601,-122.4118"]
    assert params["travelmode"] == ["driving"]


def test_first_stop_routes_from_wherever_the_phone_is() -> None:
    """No origin means Maps starts from current location, which is the point."""
    url = directions_url(destination=CHAPEL)
    assert "origin" not in _query_params(url)
    assert _query_params(url)["destination"] == ["37.7599,-122.4214"]


def test_nearby_searches_center_on_the_venue() -> None:
    for term in ("restaurants", "bars", "parking"):
        url = nearby_search_url(CHAPEL, term)
        assert url == f"https://www.google.com/maps/search/{term}/@37.7599,-122.4214,16z"


def test_nearby_search_falls_back_to_text_without_coordinates() -> None:
    location = StopLocation(venue_name="Some Bar", address="123 Fake St")
    url = nearby_search_url(location, "parking")
    assert _query_params(url)["query"] == ["parking near 123 Fake St"]


def test_low_confidence_coordinates_do_not_drive_navigation() -> None:
    """A city-centroid fallback must not become a turn-by-turn destination."""
    approximate = StopLocation(
        venue_name="Mystery Warehouse",
        address="Oakland, CA",
        lat=37.8044,
        lng=-122.2712,
        location_confidence=0.3,
    )
    params = _query_params(directions_url(destination=approximate))
    assert params["destination"] == ["Mystery Warehouse, Oakland, CA"]


def test_precise_coordinates_are_preferred_over_a_partial_address() -> None:
    params = _query_params(directions_url(destination=CHAPEL))
    assert params["destination"] == ["37.7599,-122.4214"]


def test_a_stop_with_no_location_gets_no_links() -> None:
    links = build_stop_links(
        location=StopLocation(), tickets_url="https://example.com/tickets"
    )
    assert links.tickets_url == "https://example.com/tickets"
    assert links.map_url is None
    assert links.directions_url is None
    assert links.parking_url is None


def test_build_stop_links_ignores_an_unlocatable_origin() -> None:
    """Directions from nowhere are worse than directions from current location."""
    links = build_stop_links(location=CHAPEL, previous_location=StopLocation())
    assert "origin" not in _query_params(links.directions_url)


def test_map_url_drops_a_pin_on_the_venue() -> None:
    assert _query_params(map_url(CHAPEL))["query"] == ["37.7599,-122.4214"]


def test_titles_name_the_occasion_place_and_day() -> None:
    title = itinerary_title(
        intent="date_night",
        geography="mission",
        starts_at=datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc),
    )
    # 22:00 UTC is 3 PM Saturday in SF.
    assert title == "Date night in Mission — Sat, Aug 8"


def test_times_render_in_venue_local_time() -> None:
    # 03:00 UTC Sunday is still Saturday night at the venue.
    late = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)
    assert format_local_time(late) == "8:00 PM"
    assert format_local_day(late) == "Sat, Aug 8"


@dataclass
class _Stop:
    """Minimal stand-in for the API's stop model, which is what ships in prod."""

    kind: str
    title: str
    start_at: datetime
    end_at: datetime | None
    venue_name: str | None
    address: str | None
    travel_buffer_minutes_before: int
    links: StopLinks


def _renderable(**overrides) -> _Stop:
    defaults = dict(
        kind="main_event",
        title="Julien Baker",
        start_at=datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc),
        end_at=None,
        venue_name=CHAPEL.venue_name,
        address=CHAPEL.address,
        travel_buffer_minutes_before=30,
        links=build_stop_links(location=CHAPEL, tickets_url="https://tix.example/1"),
    )
    defaults.update(overrides)
    return _Stop(**defaults)


def test_text_rendering_carries_every_link_and_the_share_url() -> None:
    text = render_itinerary_text(
        title="Date night in Mission — Sat, Aug 8",
        stops=[_renderable()],
        share_url="https://truthoffun.example/itinerary/abc",
    )
    assert "1. 8:00 PM · Main event" in text
    assert "Julien Baker" in text
    assert "The Chapel — 777 Valencia St, San Francisco, CA" in text
    assert "Leave ~30 min ahead" in text
    assert "Tickets: https://tix.example/1" in text
    assert "Parking: https://www.google.com/maps/search/parking/" in text
    assert "Food nearby: https://www.google.com/maps/search/restaurants/" in text
    assert "Drinks nearby: https://www.google.com/maps/search/bars/" in text
    assert text.rstrip().endswith("Full plan: https://truthoffun.example/itinerary/abc")


def test_text_rendering_numbers_stops_in_order() -> None:
    text = render_itinerary_text(
        title="Night out",
        stops=[
            _renderable(
                kind="pre_event_drink",
                title="Happy hour",
                start_at=datetime(2026, 8, 9, 1, 0, tzinfo=timezone.utc),
                travel_buffer_minutes_before=0,
            ),
            _renderable(),
        ],
    )
    assert text.index("1. 6:00 PM · Before") < text.index("2. 8:00 PM · Main event")
    # A zero buffer is silence, not "Leave ~0 min ahead".
    assert "Leave ~0 min" not in text


def test_empty_itinerary_renders_without_crashing() -> None:
    assert "No stops yet." in render_itinerary_text(title="Night out", stops=[])


def test_stop_links_omits_nothing_it_can_build() -> None:
    links = build_stop_links(location=CHAPEL, previous_location=TRUE_LAUREL)
    assert isinstance(links, StopLinks)
    assert all(
        value is not None
        for value in (
            links.map_url,
            links.directions_url,
            links.food_url,
            links.drinks_url,
            links.parking_url,
        )
    )
