from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth import LoginRequest, RegisterRequest
from app.api.discovery import ConciergeRequest, OnboardingRequest
from app.api.social import CreateFolderRequest, CreateInviteRequest
from app.core.config import get_settings
from app.core.request_limits import RequestBodyLimitMiddleware
from app.main import app


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_container_defaults_to_production_and_does_not_trust_every_proxy() -> None:
    repo_root = Path(__file__).parents[1]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "ENV APP_ENV=production" in dockerfile
    assert "${FORWARDED_ALLOW_IPS:-127.0.0.1}" in dockerfile
    assert "${FORWARDED_ALLOW_IPS:-*}" not in dockerfile
    assert "uv sync --frozen" in dockerfile
    assert "USER app" in dockerfile
    assert '"127.0.0.1:5433:5432"' in compose
    assert '"127.0.0.1:8000:8000"' in compose
    assert '"127.0.0.1:6379:6379"' in compose


def test_production_refuses_the_known_development_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        get_settings()


@pytest.mark.parametrize("weak_key", ["", "too-short"])
def test_production_refuses_blank_or_short_jwt_secrets(
    monkeypatch: pytest.MonkeyPatch, weak_key: str
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", weak_key)

    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        get_settings()


def test_production_rejects_credentialed_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "j" * 48)
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["*"]')

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        get_settings()


def test_production_aaim_requires_bound_issuer_and_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "j" * 48)
    monkeypatch.setenv("AAIM_ENABLED", "true")
    monkeypatch.setenv("AAIM_JWT_SHARED_SECRET", "s" * 32)
    monkeypatch.delenv("AAIM_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("AAIM_OIDC_AUDIENCE", raising=False)

    with pytest.raises(RuntimeError, match="AAIM_OIDC_ISSUER"):
        get_settings()


@pytest.mark.parametrize(
    "request_type,payload",
    [
        (RegisterRequest, {"email": "user@example.com", "password": "short"}),
        (RegisterRequest, {"email": "user@example.com", "password": "é" * 37}),
        (LoginRequest, {"email": "user@example.com", "password": "é" * 37}),
        (ConciergeRequest, {"query": "x" * 2001}),
        (OnboardingRequest, {"perfect_saturday": "x" * 2001}),
        (CreateFolderRequest, {"name": "x" * 256}),
        (CreateInviteRequest, {"expires_in_days": 366}),
    ],
)
def test_untrusted_request_fields_are_bounded(request_type: type, payload: dict) -> None:
    with pytest.raises(ValidationError):
        request_type.model_validate(payload)


@pytest.mark.parametrize(
    "query",
    [
        "lat=91",
        "lng=181",
        "radius_miles=501",
        f"q={'x' * 201}",
    ],
)
def test_event_query_rejects_expensive_or_invalid_bounds(query: str) -> None:
    with TestClient(app) as client:
        assert client.get(f"/events?{query}").status_code == 422


def test_api_rejects_oversized_declared_body_before_parsing() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            content=b"x" * 1_000_001,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413


def test_streaming_body_limit_cannot_be_bypassed_without_content_length() -> None:
    messages = [
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"456", "more_body": False},
    ]
    sent: list[dict] = []

    async def receive() -> dict:
        return messages.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    async def consume_body(_scope: dict, inner_receive, _send) -> None:
        while True:
            message = await inner_receive()
            if not message.get("more_body"):
                return

    middleware = RequestBodyLimitMiddleware(consume_body, max_bytes=5)
    scope = {"type": "http", "headers": []}
    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
