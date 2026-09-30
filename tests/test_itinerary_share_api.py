"""Sharing a plan produces a link that keeps working.

Exercises the round trip a phone actually takes: freeze the itinerary you are
looking at, then open the resulting public URL cold with no auth.
"""

from __future__ import annotations

import struct
import pytest
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.auth import _create_access_token
from app.core.config import get_settings
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
def _build_client(*, authenticated: bool = True) -> Generator[tuple[TestClient, Session], None, None]:
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
            headers = _user_headers(session, "owner@example.com") if authenticated else {}
            yield TestClient(app, headers=headers), session
        finally:
            app.dependency_overrides.pop(get_session, None)


def _user_headers(session: Session, email: str) -> dict[str, str]:
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email)
        session.add(user)
        session.commit()
        session.refresh(user)
    return {"Authorization": f"Bearer {_create_access_token(user=user, settings=get_settings())}"}


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

        client.headers.pop("Authorization")
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
    """A share remains bounded even when its owner is authenticated."""
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


@pytest.mark.parametrize("confidence", [0.0, 0.3])
def test_low_confidence_coordinates_fall_back_to_the_address(confidence) -> None:
    """A centroid guess must not become a turn-by-turn destination."""
    with _build_client() as (client, session):
        event_id = _insert_event(
            session,
            title="Warehouse party",
            starts_in_days=2,
            venue_name="Undisclosed Warehouse",
            address="Oakland, CA",
            coordinates=(37.8044, -122.2712),
            location_confidence=confidence,
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
        # Nearby searches use the address rather than the uncertain point.
        assert "@37.8044,-122.2712" not in body["itinerary"][0]["links"]["parking_url"]
        assert "Oakland%2C%20CA" in body["itinerary"][0]["links"]["parking_url"]
        shared = client.get(f"/shared/itineraries/{body['share_token']}").json()
        assert shared["itinerary"][0]["links"]["directions_url"] == directions


def test_anonymous_creation_requires_auth_without_writing_a_snapshot():
    with _build_client(authenticated=False) as (client, session):
        drinks_id, show_id = _seed_night(session)
        response = client.post('/concierge/itinerary/share', json=_share_payload(drinks_id, show_id))
        assert response.status_code == 401
        assert 'no-store' in response.headers['Cache-Control']
        assert session.exec(select(SavedItinerary)).all() == []


def test_new_and_legacy_queries_never_reach_public_json_or_text():
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        payload = _share_payload(drinks_id, show_id)
        private_query = 'Private surprise for Alex after their medical appointment'
        payload['query'] = private_query
        response = client.post('/concierge/itinerary/share', json=payload)
        assert response.status_code == 200
        assert 'query' not in response.json()
        assert private_query not in response.text
        assert 'no-store' in response.headers['Cache-Control']
        saved = session.exec(select(SavedItinerary)).one()
        assert saved.query == ''
        saved.query = private_query  # A record written before this rollout.
        session.add(saved)
        session.commit()
        client.headers.pop('Authorization')
        public = client.get(f'/shared/itineraries/{saved.share_token}')
        assert public.status_code == 200
        assert 'query' not in public.json()
        assert private_query not in public.text
        assert 'no-store' in public.headers['Cache-Control']


@pytest.mark.parametrize('days', [0, 31, -1, 1.5])
def test_share_expiry_is_bounded(days):
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        payload = _share_payload(drinks_id, show_id) | {'expires_in_days': days}
        response = client.post('/concierge/itinerary/share', json=payload)
        assert response.status_code == 422
        assert 'no-store' in response.headers['Cache-Control']
        assert session.exec(select(SavedItinerary)).all() == []


def test_default_and_custom_expiry_and_exact_boundary(monkeypatch):
    from app.api import discovery
    instant = datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant
    monkeypatch.setattr(discovery, 'datetime', Clock)
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        payload = _share_payload(drinks_id, show_id)
        default = client.post('/concierge/itinerary/share', json=payload).json()
        custom = client.post('/concierge/itinerary/share', json=payload | {'expires_in_days': 30}).json()
        assert datetime.fromisoformat(default['expires_at']) == instant + timedelta(days=14)
        assert datetime.fromisoformat(custom['expires_at']) == instant + timedelta(days=30)
        token = default['share_token']
        instant += timedelta(days=14, microseconds=-1)
        assert client.get(f'/shared/itineraries/{token}').status_code == 200
        instant += timedelta(microseconds=1)
        expired = client.get(f'/shared/itineraries/{token}')
        unknown = client.get('/shared/itineraries/' + 'z' * 32)
        assert expired.status_code == unknown.status_code == 404
        assert expired.json() == unknown.json() == {'detail': 'Itinerary not found'}
        assert 'no-store' in expired.headers['Cache-Control']
        assert 'no-store' in unknown.headers['Cache-Control']


def test_owners_can_list_and_revoke_only_their_own_links():
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        token = client.post('/concierge/itinerary/share', json=_share_payload(drinks_id, show_id)).json()['share_token']
        other = _user_headers(session, 'other@example.com')
        assert client.get('/users/me/itineraries', headers=other).json() == []
        denied = client.delete(f'/users/me/itineraries/{token}', headers=other)
        assert denied.status_code == 404
        assert client.get(f'/shared/itineraries/{token}').status_code == 200
        listed = client.get('/users/me/itineraries')
        assert 'private' in listed.headers['Cache-Control']
        assert 'no-store' in listed.headers['Cache-Control']
        assert [item['share_token'] for item in listed.json()] == [token]
        assert listed.json()[0]['status'] == 'active'
        assert 'query' not in listed.json()[0]
        first = client.delete(f'/users/me/itineraries/{token}')
        assert first.status_code == 204 and first.content == b''
        revoked_at = client.get('/users/me/itineraries').json()[0]['revoked_at']
        assert client.delete(f'/users/me/itineraries/{token}').status_code == 204
        item = client.get('/users/me/itineraries').json()[0]
        assert item['status'] == 'revoked' and item['revoked_at'] == revoked_at
        client.headers.pop('Authorization')
        assert client.get('/users/me/itineraries').status_code == 401
        assert client.delete(f'/users/me/itineraries/{token}').status_code == 401
        public = client.get(f'/shared/itineraries/{token}')
        assert public.status_code == 404
        assert 'no-store' in public.headers['Cache-Control']


def test_owner_list_paginates_and_includes_expired_records():
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        payload = _share_payload(drinks_id, show_id)
        first = client.post('/concierge/itinerary/share', json=payload).json()['share_token']
        second = client.post('/concierge/itinerary/share', json=payload).json()['share_token']
        expired = session.exec(select(SavedItinerary).where(SavedItinerary.share_token == first)).one()
        expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.add(expired)
        session.commit()
        assert [row['share_token'] for row in client.get('/users/me/itineraries?limit=1').json()] == [second]
        rows = client.get('/users/me/itineraries?limit=1&offset=1').json()
        assert rows[0]['share_token'] == first and rows[0]['status'] == 'expired'
        assert client.get('/users/me/itineraries?limit=101').status_code == 422
        assert client.get('/users/me/itineraries?offset=-1').status_code == 422


def test_legacy_anonymous_link_is_readable_but_cannot_be_claimed_or_revoked():
    with _build_client() as (client, session):
        drinks_id, show_id = _seed_night(session)
        token = client.post('/concierge/itinerary/share', json=_share_payload(drinks_id, show_id)).json()['share_token']
        saved = session.exec(select(SavedItinerary)).one()
        saved.user_id = None  # Legacy snapshots predate required ownership.
        session.add(saved)
        session.commit()
        assert client.get('/users/me/itineraries').json() == []
        assert client.delete(f'/users/me/itineraries/{token}').status_code == 404
        client.headers.pop('Authorization')
        assert client.get(f'/shared/itineraries/{token}').status_code == 200


def test_share_rate_limit_keeps_retry_header_and_never_caches_failure():
    from app.core.ratelimit import get_share_limiter
    limiter = get_share_limiter()
    previous = limiter.limit
    limiter.limit = 1
    limiter.reset()
    try:
        with _build_client() as (client, session):
            drinks_id, show_id = _seed_night(session)
            payload = _share_payload(drinks_id, show_id)
            assert client.post('/concierge/itinerary/share', json=payload).status_code == 200
            limited = client.post('/concierge/itinerary/share', json=payload)
            assert limited.status_code == 429
            assert int(limited.headers['Retry-After']) >= 1
            assert 'no-store' in limited.headers['Cache-Control']
            assert len(session.exec(select(SavedItinerary)).all()) == 1
    finally:
        limiter.limit = previous
        limiter.reset()


def test_snapshot_retains_end_time_after_source_event_changes():
    with _build_client() as (client, session):
        _, show_id = _seed_night(session)
        event = session.get(Event, show_id)
        event.end_at = event.start_at + timedelta(hours=2)
        session.add(event)
        session.commit()
        shared = client.post('/concierge/itinerary/share', json={'stops': [{'kind':'main_event', 'event_id':show_id}]}).json()
        original_end = shared['itinerary'][0]['end_at']
        event.end_at += timedelta(hours=1)
        session.add(event)
        session.commit()
        assert client.get(f"/shared/itineraries/{shared['share_token']}").json()['itinerary'][0]['end_at'] == original_end



def _user_stop(**overrides):
    base = {"kind":"meeting", "title":"Meet at Java Beach Cafe", "place":{"name":"Java Beach Cafe", "lat":37.760, "lng":-122.50},
            "start_at":"2026-10-01T17:00:00-07:00", "end_at":"2026-10-01T17:15:00-07:00"}
    return {**base, **overrides}


def test_mixed_share_preserves_planner_provenance_origin_and_mode():
    with _build_client() as (client, session):
        _, show_id = _seed_night(session)
        payload = {"origin":{"name":"Ocean Beach", "lat":37.76,"lng":-122.509}, "travel_mode":"transit",
            "stops":[{"kind":"meeting", "user_stop":_user_stop()},
            {"kind":"walk", "user_stop":_user_stop(kind="walk", title="Stroll the coastal trail",start_at="2026-10-01T17:20:00-07:00",end_at=None)},
            {"kind":"main_event", "event_id":show_id, "title":"Injected event override"}]}
        response = client.post("/concierge/itinerary/share", json=payload)
        assert response.status_code == 200, response.text
        shared = response.json()
        public = client.get("/shared/itineraries/" + shared["share_token"]).json()
        assert public["origin"] == shared["origin"]
        assert public["travel_mode"] == "transit"
        assert [stop["provenance"] for stop in public["itinerary"]] == ["planner","planner","event"]
        assert public["itinerary"][0]["event_id"] is None
        assert public["itinerary"][0]["links"]["tickets_url"] is None
        assert public["itinerary"][2]["title"] == "Julien Baker at The Chapel"
        assert all("travelmode=transit" in stop["links"]["directions_url"] for stop in public["itinerary"])
        assert "Added by the planner" in public["text"]
        assert "Leave by ~" in public["text"]
        saved = session.exec(select(SavedItinerary)).one()
        assert saved.query == ""
        assert saved.planning_context["travel_mode"] == "transit"


@pytest.mark.parametrize("bad", ["<script>alert(1)</script>","https://evil.example", "www.evil.example", "javascript:alert(1)", "x"*10000, "safe\nInjected line", "hidden\u202eoverride"])
def test_hostile_user_stop_cannot_be_shared(bad):
    with _build_client() as (client, session):
        response = client.post("/concierge/itinerary/share", json={"stops":[{"kind":"meeting", "user_stop":_user_stop(title=bad)}]})
        assert response.status_code == 422
        assert session.exec(select(SavedItinerary)).all() == []


@pytest.mark.parametrize("bad_place", [{"name":"<img src=x>"}, {"address":"https://evil.example"}, {"lat":37.7}, {"lat":999,"lng":-122}])
def test_invalid_place_rejected(bad_place):
    with _build_client() as (client, session):
        assert client.post("/concierge/itinerary/share", json={"stops":[{"kind":"meeting", "user_stop":_user_stop(place=bad_place)}]}).status_code == 422
