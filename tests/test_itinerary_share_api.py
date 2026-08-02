"""Sharing a plan produces a link that keeps working.

Exercises the round trip a phone actually takes: freeze the itinerary you are
looking at, then open the resulting public URL cold with no auth.
"""

from __future__ import annotations

import struct
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.models.event import Event
from app.models.itinerary import SavedItinerary
from app.models.user import User

CHAPEL = (37.7599, -122.4214)
TRUE_LAUREL = (37.7601, -122.4118)


def _ewkb_hex(lat: float, lng: float) -> str:
    """A 2D POINT with an SRID, laid out the way PostGIS hands it back."""
    return (
        struct.pack("<BI", 1, 0x20000001)
        + struct.pack("<I", 4326)
        + struct.pack("<dd", lng, lat)
    ).hex()


@contextmanager
def _build_client() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # PostGIS functions the events table's geometry column leans on. AsEWKB
    # returns bytes rather than the hex string sqlite would otherwise hand
    # back, so coordinates deserialize exactly as they do against Postgres.
    @sa_event.listens_for(engine, "connect")
    def _register_geo_stubs(dbapi_conn, _record):  # noqa: ANN001
        for name, arity in (
            ("RecoverGeometryColumn", 5),
            ("DiscardGeometryColumn", 2),
            ("CreateSpatialIndex", 2),
        ):
            dbapi_conn.create_function(name, arity, lambda *_args: 1)
        dbapi_conn.create_function("AsEWKB", 1, bytes.fromhex)

    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Event.__table__, SavedItinerary.__table__],
    )

    with Session(engine) as session:
        app.dependency_overrides[get_session] = lambda: session
        try:
            yield TestClient(app), session
        finally:
            app.dependency_overrides.pop(get_session, None)


def _insert_event(
    session: Session,
    *,
    title: str,
    starts_in_days: int,
    venue_name: str,
    address: str,
    coordinates: tuple[float, float],
    location_confidence: float = 0.9,
    external_url: str | None = None,
) -> int:
    """Insert through raw SQL so the geometry lands as verbatim EWKB."""
    start_at = datetime.now(timezone.utc) + timedelta(days=starts_in_days)
    now = datetime.now(timezone.utc).isoformat()
    lat, lng = coordinates
    result = session.execute(
        text(
            "INSERT INTO events (title, start_at, source_name, source_tier,"
            " venue_name, raw_address, external_url, location, categories, tags,"
            " status, attendee_count, location_confidence, is_free, created_at,"
            " updated_at) VALUES (:title, :start_at, 'test', 2, :venue, :address,"
            " :url, :location, '[]', '[]', 'scheduled', 0, :confidence, 0, :now,"
            " :now) RETURNING id"
        ),
        {
            "title": title,
            "start_at": start_at.isoformat(),
            "venue": venue_name,
            "address": address,
            "url": external_url,
            "location": _ewkb_hex(lat, lng),
            "confidence": location_confidence,
            "now": now,
        },
    )
    event_id = int(result.scalar_one())
    session.commit()
    return event_id


def _seed_night(session: Session) -> tuple[int, int]:
    drinks_id = _insert_event(
        session,
        title="Happy hour at True Laurel",
        starts_in_days=3,
        venue_name="True Laurel",
        address="753 Alabama St, San Francisco, CA",
        coordinates=TRUE_LAUREL,
    )
    show_id = _insert_event(
        session,
        title="Julien Baker at The Chapel",
        starts_in_days=3,
        venue_name="The Chapel",
        address="777 Valencia St, San Francisco, CA",
        coordinates=CHAPEL,
        external_url="https://tickets.example/julien-baker",
    )
    return drinks_id, show_id


def _share_payload(drinks_id: int, show_id: int) -> dict:
    return {
        "query": "date night in the mission saturday",
        "intent": "date_night",
        "timeframe": "this_saturday",
        "geography": "mission",
        "anchor_event_id": show_id,
        "stops": [
            {
                "kind": "pre_event_drink",
                "event_id": drinks_id,
                "travel_buffer_minutes_before": 0,
            },
            {
                "kind": "main_event",
                "event_id": show_id,
                "travel_buffer_minutes_before": 30,
            },
        ],
    }


def test_sharing_returns_a_link_and_every_stop_carries_directions() -> None:
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)

        response = client.post(
            "/concierge/itinerary/share", json=_share_payload(drinks_id, show_id)
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["share_url"] == f"/itinerary/{body['share_token']}"
        assert body["title"].startswith("Date night in Mission")
        assert len(body["itinerary"]) == 2

        first, second = body["itinerary"]
        # The opening stop routes from wherever the phone is.
        assert "origin=" not in first["links"]["directions_url"]
        # The next leg starts from the stop before it.
        assert "origin=37.7601%2C-122.4118" in second["links"]["directions_url"]

        for stop in body["itinerary"]:
            for link in ("map_url", "directions_url", "food_url", "drinks_url", "parking_url"):
                assert stop["links"][link], f"{stop['kind']} is missing {link}"
        assert second["links"]["tickets_url"] == "https://tickets.example/julien-baker"
        assert second["address"] == "777 Valencia St, San Francisco, CA"


def test_shared_link_opens_without_auth() -> None:
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        token = client.post(
            "/concierge/itinerary/share", json=_share_payload(drinks_id, show_id)
        ).json()["share_token"]

        response = client.get(f"/shared/itineraries/{token}")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["share_token"] == token
        assert [stop["title"] for stop in body["itinerary"]] == [
            "Happy hour at True Laurel",
            "Julien Baker at The Chapel",
        ]
        assert "Full plan: /itinerary/" in body["text"]
        assert "Parking: https://www.google.com/maps/search/parking/" in body["text"]


def test_a_shared_plan_survives_its_events_disappearing() -> None:
    """The snapshot is the product: a link sent on Tuesday still reads on Friday."""
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        token = client.post(
            "/concierge/itinerary/share", json=_share_payload(drinks_id, show_id)
        ).json()["share_token"]

        session.execute(text("DELETE FROM events"))
        session.commit()

        body = client.get(f"/shared/itineraries/{token}").json()
        assert len(body["itinerary"]) == 2
        assert body["itinerary"][1]["title"] == "Julien Baker at The Chapel"
        assert body["itinerary"][1]["links"]["parking_url"]


def test_client_supplied_text_never_reaches_the_public_page() -> None:
    """Stops are re-read from the database; callers only choose which and what order."""
    with _build_client() as (client, session):
        _, show_id = _seed_night(session)
        response = client.post(
            "/concierge/itinerary/share",
            json={
                "query": "q",
                "stops": [
                    {
                        "kind": "main_event",
                        "event_id": show_id,
                        "travel_buffer_minutes_before": 0,
                        "title": "Free Bitcoin — click here",
                        "venue_name": "Definitely Not A Scam",
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        stop = response.json()["itinerary"][0]
        assert stop["title"] == "Julien Baker at The Chapel"
        assert stop["venue_name"] == "The Chapel"


def test_sharing_an_unknown_event_is_rejected() -> None:
    with _build_client() as (client, session):
        _seed_night(session)
        response = client.post(
            "/concierge/itinerary/share",
            json={
                "query": "q",
                "stops": [{"kind": "main_event", "event_id": 987654}],
            },
        )
        assert response.status_code == 404


def test_sharing_an_empty_itinerary_is_rejected() -> None:
    with _build_client() as (client, _session):
        response = client.post(
            "/concierge/itinerary/share", json={"query": "q", "stops": []}
        )
        assert response.status_code == 422


def test_an_absurd_number_of_stops_is_rejected() -> None:
    """The endpoint writes a row for anonymous callers, so the input is bounded."""
    with _build_client() as (client, session):
        _, show_id = _seed_night(session)
        response = client.post(
            "/concierge/itinerary/share",
            json={
                "query": "q",
                "stops": [
                    {"kind": "main_event", "event_id": show_id} for _ in range(50)
                ],
            },
        )
        assert response.status_code == 422


def test_unknown_and_malformed_tokens_are_both_just_not_found() -> None:
    with _build_client() as (client, _session):
        assert client.get("/shared/itineraries/short").status_code == 404
        assert client.get("/shared/itineraries/" + "z" * 32).status_code == 404


def test_low_confidence_coordinates_fall_back_to_the_address() -> None:
    """A centroid guess must not become a turn-by-turn destination."""
    with _build_client() as (client, session):
        event_id = _insert_event(
            session,
            title="Warehouse party",
            starts_in_days=2,
            venue_name="Undisclosed Warehouse",
            address="Oakland, CA",
            coordinates=(37.8044, -122.2712),
            location_confidence=0.3,
        )
        body = client.post(
            "/concierge/itinerary/share",
            json={
                "query": "q",
                "stops": [{"kind": "main_event", "event_id": event_id}],
            },
        ).json()
        directions = body["itinerary"][0]["links"]["directions_url"]
        assert "destination=Undisclosed%20Warehouse%2C%20Oakland%2C%20CA" in directions
        # The neighborhood is still good enough to look around in.
        assert "@37.8044,-122.2712" in body["itinerary"][0]["links"]["parking_url"]
