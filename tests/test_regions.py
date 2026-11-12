"""Bay Area geography: events are filterable by where they actually are."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.models.event import Event
from app.services.regions import (
    BEYOND,
    CITIES_BY_REGION,
    REGION_LABELS,
    assign_missing_places,
    canonical_city,
    canonical_region,
    city_in_address,
    locate_event,
    locate_point,
    parse_point,
    place_for_event,
)


@pytest.mark.parametrize(
    ("name", "lat", "lon", "city", "region"),
    [
        ("Ocean Beach", 37.7594, -122.5107, "San Francisco", "sf"),
        ("Fort Mason", 37.8063, -122.4315, "San Francisco", "sf"),
        ("Chase Center", 37.7680, -122.3877, "San Francisco", "sf"),
        ("Fox Theater", 37.8048, -122.2712, "Oakland", "east_bay"),
        ("Greek Theatre", 37.8739, -122.2541, "Berkeley", "east_bay"),
        ("Concord Pavilion", 37.9603, -121.9397, "Concord", "east_bay"),
        ("Frost Amphitheater", 37.4318, -122.1661, "Stanford", "peninsula"),
        ("Shoreline Amphitheatre", 37.4269, -122.0808, "Mountain View", "south_bay"),
        ("Levi's Stadium", 37.4033, -121.9694, "Santa Clara", "south_bay"),
        ("SAP Center", 37.3327, -121.9010, "San Jose", "south_bay"),
        ("Muir Woods", 37.8912, -122.5717, "Mill Valley", "north_bay"),
        ("The Catalyst", 36.9741, -122.0272, "Santa Cruz", "beyond"),
    ],
)
def test_known_venues_land_in_their_city_and_region(name, lat, lon, city, region) -> None:
    place = locate_point(lat, lon)
    assert (place.city, place.region) == (city, region), name


def test_far_away_coordinates_are_not_guessed() -> None:
    reno = locate_point(39.5296, -119.8138)
    assert reno.city is None and reno.region is None


def test_every_region_has_cities_and_ids_resolve() -> None:
    for region, label in REGION_LABELS.items():
        assert CITIES_BY_REGION[region], region
        assert canonical_region(region) == region
        assert canonical_region(label) == region
    assert canonical_region("marin") == "north_bay"
    assert canonical_region("Mission") is None
    assert canonical_city("  oakland ") == "Oakland"
    assert canonical_city("Atlantis") is None


def test_city_is_read_only_from_postal_position() -> None:
    assert city_in_address("1807 Telegraph Ave, Oakland, CA 94612") == "Oakland"
    assert city_in_address("400 S 1st St, San Jose, California 95113") == "San Jose"
    # A venue named after a place is not evidence of being there.
    assert city_in_address("Sonoma Wine Bar") is None
    assert city_in_address("Richmond District Tavern") is None


def test_low_confidence_centroid_defers_to_the_written_address() -> None:
    # Several connectors park an unresolved venue on the San Francisco
    # centroid; the address is the only thing that still knows it is Oakland.
    place = locate_event(
        lat=37.7749, lon=-122.4194, location_confidence=0.4,
        venue_name="Some New Gallery", raw_address="123 Broadway, Oakland, CA",
    )
    assert (place.city, place.region) == ("Oakland", "east_bay")
    # Trusted coordinates win over text.
    trusted = locate_event(
        lat=37.7749, lon=-122.4194, location_confidence=0.9,
        raw_address="123 Broadway, Oakland, CA",
    )
    assert trusted.city == "San Francisco"


def test_parse_point_and_unplaceable_events() -> None:
    assert parse_point("POINT(-122.2712 37.8048)") == (37.8048, -122.2712)
    assert parse_point(None) is None
    assert place_for_event({"location": "POINT(-119.8138 39.5296)"}).region == BEYOND
    assert place_for_event({"location": "POINT(-122.2712 37.8048)"}).city == "Oakland"


def _event(title: str, lon: float, lat: float, **extra) -> Event:
    start = datetime.now(timezone.utc) + timedelta(days=2)
    return Event(
        title=title, start_at=start, end_at=start + timedelta(hours=2),
        source_name="test-regions", source_tier=2, location=f"POINT({lon} {lat})",
        categories=["Music"], tags=[], status="scheduled", **extra,
    )


@pytest.fixture
def bay_events(isolated_events_session):
    session = isolated_events_session
    session.add_all([
        _event("sf-show", -122.4193, 37.7793, is_free=True),
        _event("oakland-show", -122.2712, 37.8048),
        _event("berkeley-free", -122.2541, 37.8739, is_free=True),
        _event("san-jose-show", -121.9010, 37.3327),
        _event("palo-alto-talk", -122.1430, 37.4419),
        _event("sausalito-walk", -122.4853, 37.8591),
        _event("santa-cruz-show", -122.0272, 36.9741),
    ])
    session.flush()
    return session


def _titles(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {event["title"] for event in response.json()}


def test_events_filter_by_region_and_city(bay_events) -> None:
    client = TestClient(app)
    assert _titles(client.get("/events", params={"region": "east_bay"})) == {"oakland-show", "berkeley-free"}
    assert _titles(client.get("/events", params={"region": "peninsula"})) == {"palo-alto-talk"}
    assert _titles(client.get("/events", params={"region": "north_bay"})) == {"sausalito-walk"}
    assert _titles(client.get("/events", params={"city": "berkeley"})) == {"berkeley-free"}
    # The legacy preset now means "in Oakland", not "mentions Oakland".
    assert _titles(client.get("/events", params={"location_preset": "oakland"})) == {"oakland-show"}
    # Unfiltered results still include out-of-area listings.
    assert "santa-cruz-show" in _titles(client.get("/events"))


def test_events_carry_city_and_region_and_filter_free(bay_events) -> None:
    client = TestClient(app)
    free = client.get("/events", params={"is_free": "true", "region": "east_bay"})
    assert _titles(free) == {"berkeley-free"}
    event = free.json()[0]
    assert (event["city"], event["region"]) == ("Berkeley", "east_bay")
    paid = _titles(client.get("/events", params={"is_free": "false", "region": "sf"}))
    assert paid == set()


def test_unknown_city_is_a_client_error(bay_events) -> None:
    response = TestClient(app).get("/events", params={"city": "Atlantis"})
    assert response.status_code == 400
    assert response.headers.get("x-request-id")


def test_regions_endpoint_lists_all_regions_with_counts(bay_events) -> None:
    response = TestClient(app).get("/regions")
    assert response.status_code == 200
    assert "max-age" in response.headers["cache-control"]
    regions = response.json()["regions"]
    assert [region["id"] for region in regions] == list(REGION_LABELS)
    by_id = {region["id"]: region for region in regions}
    assert by_id["east_bay"]["upcoming_count"] == 2
    assert {city["name"] for city in by_id["east_bay"]["cities"]} == {"Oakland", "Berkeley"}
    assert by_id["south_bay"]["cities"] == [{"name": "San Jose", "upcoming_count": 1}]
    # "beyond" is stored but never offered as a filter.
    assert all(region["id"] != "beyond" for region in regions)


def test_rows_written_outside_the_orm_are_assigned_by_the_backfill(isolated_events_session) -> None:
    session = isolated_events_session
    session.execute(text(
        "INSERT INTO events (title, start_at, source_name, source_tier, location, venue_name,"
        " raw_address, location_confidence, created_at, updated_at) VALUES"
        " ('raw-oakland', now() + interval '1 day', 'test-regions', 2,"
        "  ST_SetSRID(ST_MakePoint(-122.2712, 37.8048), 4326), 'Fox Theater', NULL, 0.9, now(), now()),"
        " ('raw-centroid', now() + interval '1 day', 'test-regions', 2,"
        "  ST_SetSRID(ST_MakePoint(-122.4194, 37.7749), 4326), 'New Spot',"
        "  '5 Main St, San Jose, CA', 0.4, now(), now()),"
        " ('raw-reno', now() + interval '1 day', 'test-regions', 2,"
        "  ST_SetSRID(ST_MakePoint(-119.8138, 39.5296), 4326), 'Casino', NULL, 0.9, now(), now())"
    ))
    # Until assigned, a city filter still finds the row by its text.
    client = TestClient(app)
    assert "raw-centroid" in _titles(client.get("/events", params={"city": "San Jose"}))

    assert assign_missing_places(session, batch_size=2) == 3
    rows = dict(
        (title, (city, region))
        for title, city, region in session.execute(
            text("SELECT title, city, region FROM events WHERE source_name = 'test-regions'")
        )
    )
    assert rows == {
        "raw-oakland": ("Oakland", "east_bay"),
        "raw-centroid": ("San Jose", "south_bay"),
        "raw-reno": (None, "beyond"),
    }
    assert assign_missing_places(session) == 0
