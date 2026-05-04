from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import Settings
from app.core.security import get_internal_principal, require_internal_scope


def _make_settings(**overrides: object) -> Settings:
    payload = {
        "aaim_enabled": True,
        "aaim_jwt_shared_secret": "test-secret-with-32-plus-bytes-minimum",
        "aaim_oidc_issuer": "https://issuer.local",
        "aaim_oidc_audience": "internal-bots",
        "aaim_jwt_algorithms": ["HS256"],
    }
    payload.update(overrides)
    return Settings.model_validate(payload)


def _encode_token(secret: str, **claims: object) -> str:
    now = datetime.now(timezone.utc)
    defaults = {
        "sub": "bot-1",
        "client_id": "scraper-worker",
        "iss": "https://issuer.local",
        "aud": "internal-bots",
        "scope": "internal:secrets:read internal:secrets:write",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    defaults.update(claims)
    return jwt.encode(defaults, secret, algorithm="HS256")


def test_get_internal_principal_accepts_valid_hs256_token() -> None:
    settings = _make_settings()
    token = _encode_token("test-secret-with-32-plus-bytes-minimum")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    principal = get_internal_principal(credentials=credentials, settings=settings)

    assert principal.client_id == "scraper-worker"
    assert principal.subject == "bot-1"
    assert "internal:secrets:read" in principal.scopes


def test_get_internal_principal_rejects_invalid_audience() -> None:
    settings = _make_settings()
    token = _encode_token("test-secret-with-32-plus-bytes-minimum", aud="wrong-audience")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc:
        get_internal_principal(credentials=credentials, settings=settings)

    assert exc.value.status_code == 401


def test_require_internal_scope_raises_for_missing_scope() -> None:
    settings = _make_settings()
    token = _encode_token(
        "test-secret-with-32-plus-bytes-minimum",
        scope="internal:secrets:read",
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    principal = get_internal_principal(credentials=credentials, settings=settings)
    dependency = require_internal_scope("internal:secrets:write")

    with pytest.raises(HTTPException) as exc:
        dependency(principal)

    assert exc.value.status_code == 403


def test_auth_disabled_returns_dev_principal() -> None:
    settings = _make_settings(aaim_enabled=False, aaim_jwt_shared_secret=None)
    principal = get_internal_principal(credentials=None, settings=settings)

    assert principal.client_id == "local-dev-client"
