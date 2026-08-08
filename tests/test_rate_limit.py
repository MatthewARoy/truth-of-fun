"""The abuse-prone endpoints cut a client off instead of running up a bill.

The concierge and onboarding endpoints spend an Anthropic call per request and
are reachable without credentials (concierge) or with a free account
(onboarding); login/register are the credential-stuffing surface. Each must
return 429 once a client exceeds its window — before doing any work.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.core.ratelimit import (
    SlidingWindowLimiter,
    get_auth_limiter,
    get_llm_limiter,
)
from app.main import app
from app.models.event import Event
from app.models.user import User


class TestSlidingWindowLimiter:
    def test_allows_until_limit_then_blocks(self) -> None:
        limiter = SlidingWindowLimiter(name="t", limit=2, window_seconds=60)
        assert limiter.hit("a", now=0.0) is None
        assert limiter.hit("a", now=1.0) is None
        retry_after = limiter.hit("a", now=2.0)
        assert retry_after == pytest.approx(58.0)

    def test_window_slides(self) -> None:
        limiter = SlidingWindowLimiter(name="t", limit=1, window_seconds=60)
        assert limiter.hit("a", now=0.0) is None
        assert limiter.hit("a", now=30.0) is not None
        assert limiter.hit("a", now=61.0) is None

    def test_clients_are_independent(self) -> None:
        limiter = SlidingWindowLimiter(name="t", limit=1, window_seconds=60)
        assert limiter.hit("a", now=0.0) is None
        assert limiter.hit("b", now=0.0) is None

    def test_zero_limit_disables(self) -> None:
        limiter = SlidingWindowLimiter(name="t", limit=0, window_seconds=60)
        for i in range(50):
            assert limiter.hit("a", now=float(i)) is None


@contextmanager
def _build_client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Stubs for the PostGIS/Postgres functions the events table and the
    # concierge anchor query lean on (same trick as test_itinerary_share_api;
    # `timezone` only has to exist — the table stays empty).
    @sa_event.listens_for(engine, "connect")
    def _register_geo_stubs(dbapi_conn, _record):  # noqa: ANN001
        for name, arity in (
            ("RecoverGeometryColumn", 5),
            ("DiscardGeometryColumn", 2),
            ("CreateSpatialIndex", 2),
        ):
            dbapi_conn.create_function(name, arity, lambda *_args: 1)
        dbapi_conn.create_function("AsEWKB", 1, bytes.fromhex)
        dbapi_conn.create_function("timezone", 2, lambda _tz, value: value)

    SQLModel.metadata.create_all(engine, tables=[User.__table__, Event.__table__])
    with Session(engine) as session:
        app.dependency_overrides[get_session] = lambda: session
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.pop(get_session, None)


@contextmanager
def _limit_of(limiter: SlidingWindowLimiter, limit: int) -> Generator[None, None, None]:
    original = limiter.limit
    limiter.limit = limit
    limiter.reset()
    try:
        yield
    finally:
        limiter.limit = original
        limiter.reset()


def test_concierge_returns_429_past_the_cap() -> None:
    with _build_client() as client, _limit_of(get_llm_limiter(), 2):
        payload = {"query": "date night in the Mission Saturday"}
        for _ in range(2):
            response = client.post("/concierge/itinerary", json=payload)
            assert response.status_code == 200
        response = client.post("/concierge/itinerary", json=payload)
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) >= 1


def test_login_returns_429_past_the_cap() -> None:
    with _build_client() as client, _limit_of(get_auth_limiter(), 3):
        credentials = {"email": "nobody@example.com", "password": "wrong"}
        for _ in range(3):
            response = client.post("/auth/login", json=credentials)
            assert response.status_code == 401
        response = client.post("/auth/login", json=credentials)
        assert response.status_code == 429


def test_register_shares_the_auth_window_with_login() -> None:
    with _build_client() as client, _limit_of(get_auth_limiter(), 1):
        response = client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
        )
        assert response.status_code == 401
        response = client.post(
            "/auth/register",
            json={"email": "new@example.com", "password": "hunter2hunter2"},
        )
        assert response.status_code == 429
