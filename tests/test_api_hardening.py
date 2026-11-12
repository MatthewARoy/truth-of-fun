"""Bad input and write races answer 4xx, and access logs never carry tokens."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import _engine_options, get_session
from app.main import app


@pytest.fixture
def pg_client():
    """Client bound to a rolled-back transaction on the disposable test database."""
    url = get_settings().database_url
    engine = create_engine(url)
    try:
        connection = engine.connect()
    except Exception:
        engine.dispose()
        pytest.skip("Postgres is required for database error mapping")
    transaction = connection.begin()
    session = Session(bind=connection)
    app.dependency_overrides[get_session] = lambda: session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_absurd_offset_is_a_validation_error_not_a_500(pg_client: TestClient) -> None:
    response = pg_client.get("/events", params={"offset": 10**19})
    assert response.status_code == 422


def test_nul_byte_in_search_is_a_client_error(pg_client: TestClient) -> None:
    response = pg_client.get("/events", params={"q": "jazz\x00"})
    assert response.status_code == 400
    assert "cannot store" in response.json()["detail"]


def test_access_log_records_route_template_not_share_token(
    pg_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "s3cr3t-share-token-value-that-must-not-be-logged"
    with caplog.at_level(logging.INFO, logger="app.access"):
        response = pg_client.get(f"/shared/itineraries/{secret}")
    assert response.status_code == 404
    lines = [record.getMessage() for record in caplog.records if record.name == "app.access"]
    assert lines, "the request should have produced an access line"
    assert all(secret not in line for line in lines)
    assert any("{" in line for line in lines), lines
    assert all(secret not in str(getattr(r, "http_path", "")) for r in caplog.records)


def test_postgres_engine_is_sized_and_hides_parameters() -> None:
    options = _engine_options()
    assert options["hide_parameters"] is True
    if get_settings().database_url.startswith("postgresql"):
        assert options["pool_size"] + options["max_overflow"] >= 30


def test_statement_timeout_reaches_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import database

    monkeypatch.setattr(database.settings, "db_statement_timeout_ms", 1234)
    options = database._engine_options()
    if "connect_args" not in options:
        pytest.skip("Postgres is required for statement_timeout")
    engine = create_engine(database.settings.database_url, **options)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "1234ms"
    except Exception as exc:  # pragma: no cover - no database available
        pytest.skip(f"Postgres unavailable: {type(exc).__name__}")
    finally:
        engine.dispose()
