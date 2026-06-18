"""Folder invites must be revocable and must expire.

Closes the gap where invite tokens lived forever (`FolderInvite.is_active` was
never flipped and there was no `expires_at`), so a leaked link granted folder
access indefinitely with no way to cut it off.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models.social import (
    FolderInvite,
    FolderItem,
    FolderMember,
    FolderVote,
    VibeFolder,
)
from app.models.user import User


@contextmanager
def _build_client() -> Generator[tuple[TestClient, object], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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

    def _override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()


def _register(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/auth/register", json={"email": email, "password": "hunter2hunter2"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_folder(client: TestClient, headers: dict[str, str]) -> int:
    folder = client.post("/folders", json={"name": "Friday plans"}, headers=headers).json()
    return int(folder["id"])


def test_new_invite_carries_a_default_expiry() -> None:
    with _build_client() as (client, _engine):
        owner = _register(client, "owner@example.com")
        folder_id = _create_folder(client, owner)

        invite = client.post(f"/folders/{folder_id}/invite", headers=owner)
        assert invite.status_code == 200, invite.text
        body = invite.json()
        assert body["expires_at"] is not None


def test_owner_can_revoke_invite_blocking_future_acceptance() -> None:
    with _build_client() as (client, _engine):
        owner = _register(client, "owner@example.com")
        friend = _register(client, "friend@example.com")
        folder_id = _create_folder(client, owner)

        token = client.post(f"/folders/{folder_id}/invite", headers=owner).json()["invite_token"]

        revoke = client.delete(f"/folders/{folder_id}/invites/{token}", headers=owner)
        assert revoke.status_code == 204, revoke.text

        accept = client.post(f"/folders/invites/{token}/accept", headers=friend)
        assert accept.status_code == 404


def test_non_owner_cannot_revoke_invite() -> None:
    with _build_client() as (client, _engine):
        owner = _register(client, "owner@example.com")
        stranger = _register(client, "stranger@example.com")
        folder_id = _create_folder(client, owner)
        token = client.post(f"/folders/{folder_id}/invite", headers=owner).json()["invite_token"]

        revoke = client.delete(f"/folders/{folder_id}/invites/{token}", headers=stranger)
        assert revoke.status_code == 403


def test_expired_invite_is_rejected_with_410() -> None:
    with _build_client() as (client, engine):
        owner = _register(client, "owner@example.com")
        friend = _register(client, "friend@example.com")
        folder_id = _create_folder(client, owner)
        token = client.post(f"/folders/{folder_id}/invite", headers=owner).json()["invite_token"]

        # Backdate the expiry so the invite is past its window.
        with Session(engine) as session:
            invite = session.exec(
                select(FolderInvite).where(FolderInvite.invite_token == token)
            ).first()
            invite.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            session.add(invite)
            session.commit()

        accept = client.post(f"/folders/invites/{token}/accept", headers=friend)
        assert accept.status_code == 410, accept.text
