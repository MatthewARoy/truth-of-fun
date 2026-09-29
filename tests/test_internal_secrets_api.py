from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.internal_secrets import get_secrets_store_dependency
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import app
from app.models.api_key import ApiKeyUsageSnapshot
from app.services.secrets_store import KeyHealth, KeyLease

_TEST_SECRET = "test-secret-with-32-plus-bytes-minimum"


def _aaim_settings(**overrides: object) -> Settings:
    payload = {
        "aaim_enabled": True,
        "aaim_jwt_shared_secret": _TEST_SECRET,
        "aaim_oidc_issuer": "https://issuer.local",
        "aaim_oidc_audience": "internal-bots",
        "aaim_jwt_algorithms": ["HS256"],
    }
    payload.update(overrides)
    return Settings.model_validate(payload)


def _bot_token(scope: str = "internal:secrets:read internal:secrets:write") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "bot-1",
            "client_id": "scraper-worker",
            "iss": "https://issuer.local",
            "aud": "internal-bots",
            "scope": scope,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
        },
        _TEST_SECRET,
        algorithm="HS256",
    )


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_bot_token()}"}


class _FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.health_requests: list[str | None] = []
        self._usage = {
            "tm-1": KeyHealth(
                key_id="tm-1",
                usage_count=3,
                quota_limit=100,
                status="active",
                last_status=200,
                last_error=None,
                updated_at_epoch=1700000000,
            )
        }

    def get_active_key(self, provider: str) -> KeyLease:
        return KeyLease(
            provider=provider,
            key_id="tm-1",
            api_key="ticketmaster-test-key",
            usage_count=3,
            quota_limit=100,
            status="active",
            source="redis",
        )

    def report_usage(
        self,
        *,
        provider: str,
        key_id: str,
        calls: int = 1,
        last_status: int | None = None,
        last_error: str | None = None,
        disable: bool = False,
    ) -> None:
        self.calls.append((provider, key_id, calls))

    def health(self, provider: str, *, key_id: str | None = None) -> list[KeyHealth]:
        self.health_requests.append(key_id)
        if key_id is not None:
            item = self._usage.get(key_id.strip())
            return [item] if item else []
        return list(self._usage.values())


@contextmanager
def _build_client(settings: Settings | None = None) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[ApiKeyUsageSnapshot.__table__])

    def _override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    fake_store = _FakeStore()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_secrets_store_dependency] = lambda: fake_store
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_get_active_key_endpoint() -> None:
    with _build_client(settings=_aaim_settings()) as client:
        response = client.get(
            "/internal/secrets/ticketmaster/active-key", headers=_auth_headers()
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["key_id"] == "tm-1"
        assert payload["source"] == "redis"


def test_report_usage_endpoint() -> None:
    with _build_client(settings=_aaim_settings()) as client:
        response = client.post(
            "/internal/secrets/ticketmaster/usage",
            json={"key_id": "tm-1", "calls": 2, "last_status": 200},
            headers=_auth_headers(),
        )

        assert response.status_code == 200
        assert response.json()["updated"] is True


def test_health_endpoint() -> None:
    with _build_client(settings=_aaim_settings()) as client:
        response = client.get(
            "/internal/secrets/ticketmaster/health", headers=_auth_headers()
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "ticketmaster"
        assert payload["total_keys"] == 1


def test_endpoints_are_unreachable_when_aaim_disabled() -> None:
    """Default config (AAIM off) must never expose API keys over HTTP."""
    with _build_client() as client:
        response = client.get("/internal/secrets/ticketmaster/active-key")
        assert response.status_code == 404


def test_endpoints_require_token_when_aaim_enabled() -> None:
    with _build_client(settings=_aaim_settings()) as client:
        response = client.get("/internal/secrets/ticketmaster/active-key")
        assert response.status_code == 401


def _snapshot_rows():
    from sqlmodel import select
    generator = app.dependency_overrides[get_session]()
    try:
        session = next(generator)
        return list(session.exec(select(ApiKeyUsageSnapshot)).all())
    finally:
        generator.close()


def test_health_polling_never_persists_usage_snapshots():
    with _build_client(settings=_aaim_settings()) as client:
        for _ in range(3):
            assert client.get('/internal/secrets/ticketmaster/health', headers=_auth_headers()).status_code == 200
        assert _snapshot_rows() == []


def test_usage_snapshots_are_sampled_and_only_capture_the_reported_key():
    with _build_client(settings=_aaim_settings()) as client:
        store = app.dependency_overrides[get_secrets_store_dependency]()
        from dataclasses import replace
        store._usage['tm-2'] = replace(store._usage['tm-1'], key_id='tm-2')
        for _ in range(3):
            assert client.post('/internal/secrets/ticketmaster/usage', json={'key_id':'tm-1'}, headers=_auth_headers()).status_code == 200
        rows = _snapshot_rows()
        assert len(rows) == 1
        assert rows[0].key_id == 'tm-1'
        assert store.health_requests == ['tm-1'] * 3
        store._usage['tm-1'].status = 'disabled'
        assert client.post('/internal/secrets/ticketmaster/usage', json={'key_id':'tm-1', 'disable':True}, headers=_auth_headers()).status_code == 200
        assert len(_snapshot_rows()) == 2


def test_snapshot_sampling_prunes_expired_history_and_bounds_rows_per_key(monkeypatch):
    from app.services import key_usage_snapshots as module
    monkeypatch.setattr(module, '_MAX_SNAPSHOTS_PER_KEY', 3)
    with _build_client(settings=_aaim_settings()) as client:
        generator = app.dependency_overrides[get_session]()
        session = next(generator)
        try:
            now = datetime.now(timezone.utc)
            for i in range(5):
                session.add(ApiKeyUsageSnapshot(provider='ticketmaster', key_id='tm-1',
                    usage_count=i, quota_limit=100, status='active',
                    captured_at=now-timedelta(hours=i+2)))
            session.add(ApiKeyUsageSnapshot(provider='ticketmaster', key_id='old-key',
                usage_count=0, quota_limit=100, status='active', captured_at=now-timedelta(days=31)))
            session.commit()
        finally:
            generator.close()
        response = client.post('/internal/secrets/ticketmaster/usage', json={'key_id':'tm-1'}, headers=_auth_headers())
        assert response.status_code == 200
        rows = _snapshot_rows()
        assert len(rows) == 3
        assert {row.key_id for row in rows} == {'tm-1'}
        assert max(row.usage_count for row in rows) == 3


def test_snapshot_failure_does_not_make_clients_retry_accepted_usage(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError('fixture telemetry unavailable')
    monkeypatch.setattr('app.api.internal_secrets._snapshot_health', fail)
    with _build_client(settings=_aaim_settings()) as client:
        response = client.post('/internal/secrets/ticketmaster/usage', json={'key_id':'tm-1'}, headers=_auth_headers())
        assert response.status_code == 200
        assert response.json()['updated'] is True
        store = app.dependency_overrides[get_secrets_store_dependency]()
        assert store.calls == [('ticketmaster', 'tm-1', 1)]
