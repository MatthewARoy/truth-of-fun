"""Folder invites must be consumable: accepted members can view and vote.

Regression tests for the write-only invite tokens and owner-only voting that
made the marketed group-planning flow impossible.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.models.social import FolderInvite, FolderItem, FolderVote, VibeFolder
from app.models.user import User


@contextmanager
def _build_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # geoalchemy2 wraps geometry columns in AsEWKB() on SELECT; sqlite needs a stub.
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(engine, "connect")
    def _register_geo_stub(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.create_function("AsEWKB", 1, lambda value: value)

    from app.models.social import FolderMember

    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            VibeFolder.__table__,
            FolderItem.__table__,
            FolderVote.__table__,
            FolderInvite.__table__,
            FolderMember.__table__,
        ],
    )
    # Minimal stand-in for the PostGIS-backed events table (sqlite can't
    # create the geometry column; folder flows only read scalar fields).
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR NOT NULL,
                    description VARCHAR,
                    start_at TIMESTAMP NOT NULL,
                    end_at TIMESTAMP,
                    source_name VARCHAR NOT NULL,
                    source_tier INTEGER NOT NULL,
                    source_event_id VARCHAR,
                    external_url VARCHAR,
                    venue_name VARCHAR,
                    raw_address VARCHAR,
                    location BLOB,
                    categories JSON NOT NULL DEFAULT '[]',
                    tags JSON NOT NULL DEFAULT '[]',
                    price NUMERIC,
                    currency VARCHAR,
                    image_url VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'scheduled',
                    organizer_name VARCHAR,
                    attendee_count INTEGER NOT NULL DEFAULT 0,
                    location_confidence FLOAT NOT NULL DEFAULT 1.0,
                    is_free BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO events (id, title, start_at, source_name, source_tier)"
                " VALUES (1, 'Test Show', '2026-07-01 03:00:00', 'ticketmaster', 1)"
            )
        )
        conn.commit()

    def _override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _register(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/register", json={"email": email, "password": "hunter2hunter2"}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_folder_with_item(client: TestClient, headers: dict[str, str]) -> tuple[int, int]:
    folder = client.post("/folders", json={"name": "Friday plans"}, headers=headers).json()
    detail = client.post(
        f"/folders/{folder['id']}/items", json={"event_id": 1}, headers=headers
    ).json()
    return int(folder["id"]), int(detail["items"][0]["folder_item_id"])


def test_invite_accept_grants_view_and_vote() -> None:
    with _build_client() as client:
        owner = _register(client, "owner@example.com")
        friend = _register(client, "friend@example.com")
        folder_id, item_id = _create_folder_with_item(client, owner)

        invite = client.post(f"/folders/{folder_id}/invite", headers=owner).json()
        token = invite["invite_token"]

        # Before accepting, the friend has no access.
        assert client.get(f"/folders/{folder_id}", headers=friend).status_code == 403

        accept = client.post(f"/folders/invites/{token}/accept", headers=friend)
        assert accept.status_code == 200, accept.text
        assert accept.json()["id"] == folder_id

        # Member can now view ...
        assert client.get(f"/folders/{folder_id}", headers=friend).status_code == 200

        # ... and vote; owner + friend votes both count.
        client.post(
            f"/folders/{folder_id}/votes",
            json={"folder_item_id": item_id, "vote_value": 1},
            headers=owner,
        )
        response = client.post(
            f"/folders/{folder_id}/votes",
            json={"folder_item_id": item_id, "vote_value": 1},
            headers=friend,
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["vote_score"] == 2


def test_member_folders_appear_in_folder_list() -> None:
    with _build_client() as client:
        owner = _register(client, "owner@example.com")
        friend = _register(client, "friend@example.com")
        folder_id, _ = _create_folder_with_item(client, owner)
        token = client.post(f"/folders/{folder_id}/invite", headers=owner).json()[
            "invite_token"
        ]
        client.post(f"/folders/invites/{token}/accept", headers=friend)

        listed = client.get("/folders", headers=friend).json()
        assert [f["id"] for f in listed] == [folder_id]


def test_strangers_still_cannot_vote() -> None:
    with _build_client() as client:
        owner = _register(client, "owner@example.com")
        stranger = _register(client, "stranger@example.com")
        folder_id, item_id = _create_folder_with_item(client, owner)

        response = client.post(
            f"/folders/{folder_id}/votes",
            json={"folder_item_id": item_id, "vote_value": 1},
            headers=stranger,
        )
        assert response.status_code == 403


def test_invalid_or_inactive_invite_tokens_are_rejected() -> None:
    with _build_client() as client:
        friend = _register(client, "friend@example.com")
        response = client.post(
            "/folders/invites/not-a-real-token/accept", headers=friend
        )
        assert response.status_code == 404
