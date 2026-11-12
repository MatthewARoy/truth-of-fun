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
        # This SQLite test targets admission, not PostGIS neighborhood filtering.
        payload = {"query": "date night Saturday"}
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


class TestRedisBackend:
    """The shared window is what makes limits hold across API processes."""

    @pytest.fixture
    def redis_backend(self, monkeypatch: pytest.MonkeyPatch):
        import os
        from uuid import uuid4

        from redis import Redis

        from app.core import ratelimit
        from app.core.config import get_settings

        url = os.environ.get("TEST_REDIS_URL")
        if not url:
            pytest.skip("Set TEST_REDIS_URL to a disposable Redis to verify shared windows")
        client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        prefix = f"tof-test-ratelimit-{uuid4().hex}"
        monkeypatch.setattr(get_settings(), "rate_limit_redis_prefix", prefix)
        monkeypatch.setattr(ratelimit, "_redis_client", lambda: client)
        try:
            yield client
        finally:
            keys = list(client.scan_iter(match=f"{prefix}:*"))
            if keys:
                client.delete(*keys)
            client.close()

    def test_window_is_shared_between_limiter_instances(self, redis_backend) -> None:
        from app.core.ratelimit import _hit

        # Two instances stand in for two API processes: same name, separate
        # in-process state. Only a shared store can make the second one refuse.
        first = SlidingWindowLimiter(name="shared", limit=2, window_seconds=60)
        second = SlidingWindowLimiter(name="shared", limit=2, window_seconds=60)
        assert _hit(first, "203.0.113.9") is None
        assert _hit(second, "203.0.113.9") is None
        retry_after = _hit(first, "203.0.113.9")
        assert retry_after is not None and 0 < retry_after <= 60
        assert _hit(second, "203.0.113.9") is not None
        assert _hit(second, "203.0.113.10") is None

    def test_window_expires_from_redis(self, redis_backend) -> None:
        import time as _time

        from app.core.ratelimit import _hit

        limiter = SlidingWindowLimiter(name="short", limit=1, window_seconds=0.2)
        assert _hit(limiter, "a") is None
        assert _hit(limiter, "a") is not None
        _time.sleep(0.3)
        assert _hit(limiter, "a") is None

    def test_unreachable_redis_degrades_to_process_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core import ratelimit

        class Broken:
            def eval(self, *args: object, **kwargs: object) -> None:
                raise ConnectionError("redis down")

        monkeypatch.setattr(ratelimit, "_redis_client", lambda: Broken())
        limiter = SlidingWindowLimiter(name="fallback", limit=1, window_seconds=60)
        assert ratelimit._hit(limiter, "a") is None
        # Still limited — neither an outage nor an unlimited endpoint.
        assert ratelimit._hit(limiter, "a") is not None


class TestGeneralLimit:
    """One client cannot occupy the API through endpoints with no limit of their own."""

    def _request(self, host: str):
        from starlette.requests import Request

        return Request({"type": "http", "client": (host, 1234), "headers": []})

    def test_ipv6_clients_are_keyed_by_their_slash_64(self) -> None:
        from app.core.ratelimit import client_key

        a = client_key(self._request("2001:db8:1:2:aaaa::1"))
        b = client_key(self._request("2001:db8:1:2:bbbb::9"))
        other = client_key(self._request("2001:db8:1:3::1"))
        assert a == b != other
        assert client_key(self._request("8.8.4.4")) == "8.8.4.4"
        assert client_key(self._request("::ffff:8.8.4.4")) == "8.8.4.4"

    def test_public_client_is_capped_and_internal_callers_are_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi import HTTPException

        from app.core import ratelimit

        limiter = SlidingWindowLimiter(name="general-test", limit=3, window_seconds=60)
        monkeypatch.setattr(ratelimit, "get_general_limiter", lambda: limiter)
        public = self._request("8.8.8.8")
        for _ in range(3):
            ratelimit.general_rate_limit(public)
        with pytest.raises(HTTPException) as refused:
            ratelimit.general_rate_limit(public)
        assert refused.value.status_code == 429
        assert int(refused.value.headers["Retry-After"]) >= 1
        # The web container's server-side rendering and health probes.
        for host in ("127.0.0.1", "172.28.0.5", "10.0.0.8"):
            for _ in range(10):
                ratelimit.general_rate_limit(self._request(host))

    def test_every_route_is_behind_the_general_limit(self) -> None:
        from app.core.ratelimit import general_rate_limit

        assert any(
            dependency.dependency is general_rate_limit for dependency in app.router.dependencies
        )
