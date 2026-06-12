"""Saves, likes, and onboarding vibes must actually persist to the database.

Regression tests for the untracked-JSON-column-mutation bug: in-place
``list.append`` on a plain JSON column never marks the attribute dirty, so
commits silently wrote nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models.user import User
from app.models.user_signal import UserSignal


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[User.__table__, UserSignal.__table__])
    return engine


@contextmanager
def _build_client() -> Generator[tuple[TestClient, object], None, None]:
    engine = _make_engine()

    def _override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()


def _register(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={"email": "fan@example.com", "password": "hunter2hunter2"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_in_place_append_to_saved_event_ids_persists() -> None:
    """The endpoints mutate the JSON list in place; the commit must include it."""
    engine = _make_engine()
    with Session(engine) as session:
        session.add(User(email="fan@example.com"))
        session.commit()

    with Session(engine) as session:
        user = session.exec(select(User)).one()
        user.saved_event_ids.append(42)
        session.add(user)
        session.commit()

    with Session(engine) as session:
        user = session.exec(select(User)).one()
        assert user.saved_event_ids == [42]


def test_like_persists_preferred_vibe_through_api() -> None:
    with _build_client() as (client, engine):
        headers = _register(client)

        response = client.post(
            "/users/me/interests",
            json={"action": "like", "vibe_tag": "Chill"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["preferred_vibes"] == ["#Chill"]

        with Session(engine) as session:
            user = session.exec(select(User)).one()
            assert user.preferred_vibes == ["#Chill"]
