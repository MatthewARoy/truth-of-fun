"""Password reset, session revocation, data export and account deletion."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import get_session
from app.main import app
from app.models.event import Event
from app.models.password_reset import PasswordResetToken
from app.models.user import User

PASSWORD = "correct horse battery"
NEW_PASSWORD = "an entirely new passphrase"


@pytest.fixture
def db():
    engine = create_engine(get_settings().database_url)
    try:
        connection = engine.connect()
    except Exception:
        engine.dispose()
        pytest.skip("Postgres is required for the account lifecycle")
    transaction = connection.begin()
    session = Session(bind=connection)
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def client(db) -> TestClient:
    return TestClient(app)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    sent: list[dict] = []

    def fake_send(**kwargs) -> bool:
        sent.append(kwargs)
        return True

    monkeypatch.setattr("app.api.auth.send_email", fake_send)
    monkeypatch.setattr(get_settings(), "public_web_url", "https://fun.example")
    return sent


def _register(client: TestClient, email: str = "pat@example.com") -> dict:
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _reset_token(outbox: list[dict]) -> str:
    match = re.search(r"https://fun\.example/reset-password\?token=([\w-]+)", outbox[-1]["body"])
    assert match, outbox[-1]["body"]
    return match.group(1)


def test_reset_request_answers_identically_for_unknown_and_known_addresses(client, outbox) -> None:
    _register(client)
    known = client.post("/auth/password-reset/request", json={"email": "pat@example.com"})
    unknown = client.post("/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(outbox) == 1 and outbox[0]["to"] == "pat@example.com"


def test_reset_link_sets_a_new_password_once_and_signs_out_old_sessions(client, db, outbox) -> None:
    old = _register(client)
    client.post("/auth/password-reset/request", json={"email": "PAT@example.com"})
    token = _reset_token(outbox)
    # Only a hash is stored: a database leak does not hand out working links.
    stored = db.exec(select(PasswordResetToken)).one()
    assert token not in stored.token_hash and len(stored.token_hash) == 64

    confirmed = client.post(
        "/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert confirmed.status_code == 200, confirmed.text
    fresh = confirmed.json()["access_token"]

    assert client.get("/users/me", headers=_auth(old["access_token"])).status_code == 401
    assert client.get("/users/me", headers=_auth(fresh)).status_code == 200
    assert client.post(
        "/auth/login", json={"email": "pat@example.com", "password": PASSWORD}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "pat@example.com", "password": NEW_PASSWORD}
    ).status_code == 200
    # Single use.
    replay = client.post(
        "/auth/password-reset/confirm", json={"token": token, "new_password": "yet another passphrase"}
    )
    assert replay.status_code == 400


def test_expired_and_unknown_reset_tokens_are_refused(client, db, outbox) -> None:
    _register(client)
    client.post("/auth/password-reset/request", json={"email": "pat@example.com"})
    token = _reset_token(outbox)
    db.execute(text("UPDATE password_reset_tokens SET expires_at = now() - interval '1 minute'"))
    for candidate in (token, "x" * 43):
        response = client.post(
            "/auth/password-reset/confirm", json={"token": candidate, "new_password": NEW_PASSWORD}
        )
        assert response.status_code == 400
    assert client.post(
        "/auth/login", json={"email": "pat@example.com", "password": PASSWORD}
    ).status_code == 200


def test_reset_requests_cannot_flood_a_mailbox(client, outbox) -> None:
    _register(client)
    for _ in range(6):
        assert client.post(
            "/auth/password-reset/request", json={"email": "pat@example.com"}
        ).status_code == 202
    assert len(outbox) == 3


def test_weak_new_password_is_rejected(client, outbox) -> None:
    _register(client)
    client.post("/auth/password-reset/request", json={"email": "pat@example.com"})
    response = client.post(
        "/auth/password-reset/confirm", json={"token": _reset_token(outbox), "new_password": "short"}
    )
    assert response.status_code == 422


def test_change_password_requires_the_current_one_and_rotates_the_session(client) -> None:
    account = _register(client)
    headers = _auth(account["access_token"])
    wrong = client.post(
        "/users/me/password",
        json={"current_password": "not my password!!", "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert wrong.status_code == 400
    changed = client.post(
        "/users/me/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert changed.status_code == 200
    assert client.get("/users/me", headers=headers).status_code == 401
    assert client.get("/users/me", headers=_auth(changed.json()["access_token"])).status_code == 200


def test_logout_revokes_existing_tokens_but_not_future_logins(client) -> None:
    account = _register(client)
    headers = _auth(account["access_token"])
    assert client.post("/auth/logout", headers=headers).status_code == 204
    revoked = client.get("/users/me", headers=headers)
    assert revoked.status_code == 401 and "revoked" in revoked.json()["detail"]
    # Public discovery tolerates the stale token rather than failing the page.
    assert client.get("/events", headers=headers).status_code == 200
    again = client.post("/auth/login", json={"email": "pat@example.com", "password": PASSWORD})
    assert client.get("/users/me", headers=_auth(again.json()["access_token"])).status_code == 200


def test_email_is_one_account_regardless_of_case(client) -> None:
    _register(client, "Pat@Example.com")
    duplicate = client.post(
        "/auth/register", json={"email": "pat@example.com", "password": PASSWORD}
    )
    assert duplicate.status_code == 409
    assert client.post(
        "/auth/login", json={"email": "PAT@EXAMPLE.COM", "password": PASSWORD}
    ).status_code == 200


def _seed_activity(client: TestClient, db: Session, token: str) -> int:
    start = datetime.now(timezone.utc) + timedelta(days=3)
    event = Event(
        title="Lifecycle fixture show", start_at=start, source_name="test-account",
        source_tier=2, location="POINT(-122.2712 37.8048)", status="scheduled",
    )
    db.add(event)
    db.flush()
    headers = _auth(token)
    assert client.post(
        "/users/me/interests", json={"event_id": event.id, "action": "save"}, headers=headers
    ).status_code == 200
    folder = client.post("/folders", json={"name": "Weekend"}, headers=headers)
    assert folder.status_code in (200, 201), folder.text
    folder_id = folder.json()["id"]
    assert client.post(
        f"/folders/{folder_id}/items", json={"event_id": event.id}, headers=headers
    ).status_code in (200, 201)
    return int(event.id)


def test_export_contains_the_users_data_and_no_credentials(client, db) -> None:
    account = _register(client)
    event_id = _seed_activity(client, db, account["access_token"])
    response = client.get("/users/me/export", headers=_auth(account["access_token"]))
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["account"]["email"] == "pat@example.com"
    assert data["saved_events"] == [{"event_id": event_id, "title": "Lifecycle fixture show"}]
    assert data["folders_owned"][0]["name"] == "Weekend"
    assert data["folders_owned"][0]["items"][0]["event_id"] == event_id
    assert any(signal["type"] == "save" for signal in data["activity_signals"])
    assert "hashed_password" not in response.text and "token_hash" not in response.text


def test_delete_requires_password_then_removes_the_account_and_its_data(client, db) -> None:
    account = _register(client)
    other = _register(client, "friend@example.com")
    event_id = _seed_activity(client, db, account["access_token"])
    headers = _auth(account["access_token"])

    refused = client.post("/users/me/delete", json={"password": "wrong password!!"}, headers=headers)
    assert refused.status_code == 400
    assert client.get("/users/me", headers=headers).status_code == 200

    deleted = client.post("/users/me/delete", json={"password": PASSWORD}, headers=headers)
    assert deleted.status_code == 204
    assert client.get("/users/me", headers=headers).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "pat@example.com", "password": PASSWORD}
    ).status_code == 401

    user_id = account["user_id"]
    for table, column in [
        ("users", "id"), ("user_signals", "user_id"), ("vibe_folders", "user_id"),
        ("agent_tokens", "user_id"), ("saved_itineraries", "user_id"),
        ("folder_votes", "user_id"), ("folder_members", "user_id"),
    ]:
        count = db.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :id"), {"id": user_id}
        ).scalar_one()
        assert count == 0, table
    # The catalog and other people are untouched.
    assert db.get(Event, event_id) is not None
    assert db.get(User, other["user_id"]) is not None
    # The address can be used again.
    assert client.post(
        "/auth/register", json={"email": "pat@example.com", "password": PASSWORD}
    ).status_code == 201


def test_agent_tokens_cannot_manage_the_account(client) -> None:
    account = _register(client)
    minted = client.post(
        "/users/me/tokens",
        json={"name": "bot", "scopes": ["events:read", "profile:read"], "expires_in_days": 7},
        headers=_auth(account["access_token"]),
    )
    assert minted.status_code == 201, minted.text
    pat = _auth(minted.json()["token"])
    assert client.get("/users/me/export", headers=pat).status_code == 401
    assert client.post("/users/me/delete", json={"password": PASSWORD}, headers=pat).status_code == 401
    assert client.post("/auth/logout", headers=pat).status_code == 401
