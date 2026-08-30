"""The operator health surface must not be readable by anonymous callers.

`/health/sources` and `/health/summary` enumerate which scrapers are broken,
when each last ran, and what the last error was. `/health`, `/health/live` and
`/health/ready` stay public — orchestrators, load balancers and the compose
healthcheck need them without credentials.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import OPS_TOKEN_HEADER
from app.main import app

OPS_TOKEN = "o" * 48

PUBLIC_PATHS = ["/health", "/health/live", "/health/ready"]
GATED_PATHS = ["/health/sources", "/health/summary"]


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "j" * 48)


@pytest.mark.parametrize("path", GATED_PATHS)
def test_operator_endpoints_are_refused_without_a_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    _production(monkeypatch)
    monkeypatch.setenv("OPS_TOKEN", OPS_TOKEN)

    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", GATED_PATHS)
def test_operator_endpoints_are_refused_with_the_wrong_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    _production(monkeypatch)
    monkeypatch.setenv("OPS_TOKEN", OPS_TOKEN)

    response = client.get(path, headers={OPS_TOKEN_HEADER: "n" * 48})
    assert response.status_code == 403


@pytest.mark.parametrize("path", GATED_PATHS)
def test_operator_endpoints_open_with_the_right_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    _production(monkeypatch)
    monkeypatch.setenv("OPS_TOKEN", OPS_TOKEN)

    response = client.get(path, headers={OPS_TOKEN_HEADER: OPS_TOKEN})
    assert response.status_code != 403


@pytest.mark.parametrize("path", GATED_PATHS)
def test_unconfigured_production_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """The default for a deployment that forgot to set OPS_TOKEN is *shut*.

    Defaulting to open would mean the endpoints stay public exactly in the
    deployments whose operator never thought about them.
    """
    _production(monkeypatch)
    monkeypatch.delenv("OPS_TOKEN", raising=False)

    assert client.get(path).status_code == 403


@pytest.mark.parametrize("path", GATED_PATHS)
def test_development_without_a_token_stays_open(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """`make demo` and the local admin page must work with no setup."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("OPS_TOKEN", raising=False)

    assert client.get(path).status_code != 403


@pytest.mark.parametrize("path", GATED_PATHS)
def test_development_with_a_token_still_enforces_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """So an operator can verify the gate locally before deploying."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OPS_TOKEN", "short-dev-token")

    assert client.get(path).status_code == 403
    assert (
        client.get(path, headers={OPS_TOKEN_HEADER: "short-dev-token"}).status_code
        != 403
    )


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_probe_endpoints_stay_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Gating a probe would take the service down, not secure it.

    The compose healthcheck hits `/health`; orchestrators hit `/live` and
    `/ready`. None of them can carry a token.
    """
    _production(monkeypatch)
    monkeypatch.setenv("OPS_TOKEN", OPS_TOKEN)

    assert client.get(path).status_code != 403


def test_production_rejects_a_weak_ops_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch)
    monkeypatch.setenv("OPS_TOKEN", "too-short")

    with pytest.raises(RuntimeError, match="OPS_TOKEN must be at least 32 bytes"):
        get_settings()


def test_production_accepts_a_strong_ops_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _production(monkeypatch)
    monkeypatch.setenv("OPS_TOKEN", OPS_TOKEN)

    assert get_settings().ops_token == OPS_TOKEN
