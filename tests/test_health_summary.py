"""Tests for the operational health surface: /health/live, /ready, /summary.

/health/summary is the "is anything broken right now?" endpoint the runbook
points at, so these tests pin the classification rules: what counts as
degraded, what counts as failing, and that every problem names its subsystem.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.health import STALE_SOURCE_AFTER
from app.core.database import get_session
from app.main import app
from app.models.source_health import SourceHealthRecord
from app.worker import _source_health_state


@contextmanager
def _build_client() -> Generator[tuple[TestClient, Session], None, None]:
    _source_health_state.clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[SourceHealthRecord.__table__])

    def _override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    with Session(engine) as seed_session, TestClient(app) as client:
        yield client, seed_session
    app.dependency_overrides.clear()


def _record(**overrides: object) -> SourceHealthRecord:
    defaults: dict[str, object] = {
        "source_name": "ticketmaster",
        "status": "healthy",
        "last_event_count": 100,
        "consecutive_zeros": 0,
        "last_run_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SourceHealthRecord(**defaults)  # type: ignore[arg-type]


def test_liveness_does_not_touch_the_database() -> None:
    """Liveness must pass even with no database override configured."""
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_reports_ready_when_the_database_answers() -> None:
    with _build_client() as (client, _):
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_summary_reports_failing_source_with_its_error_text() -> None:
    """The persisted exception is what tells an operator *what* to fix."""
    with _build_client() as (client, session):
        session.add(
            _record(
                source_name="funcheap_sf",
                status="failing",
                last_event_count=0,
                consecutive_zeros=3,
                last_error="TimeoutError: page.goto exceeded 30000ms",
            )
        )
        session.commit()

        body = client.get("/health/summary").json()

    assert body["status"] == "failing"
    problem = next(p for p in body["problems"] if "funcheap_sf" in p)
    assert "TimeoutError" in problem


def test_summary_flags_a_stale_source_even_when_its_last_status_was_healthy() -> None:
    """A stale 'healthy' row must still alert — the data behind it is old."""
    stale_run = datetime.now(timezone.utc) - STALE_SOURCE_AFTER - timedelta(hours=1)
    fresh_run = datetime.now(timezone.utc)
    with _build_client() as (client, session):
        session.add(_record(source_name="dothebay", status="healthy", last_run_at=stale_run))
        # A second, fresh source proves the worker is alive, so the stale one
        # is reported individually rather than as a worker outage.
        session.add(_record(source_name="ticketmaster", last_run_at=fresh_run))
        session.commit()

        body = client.get("/health/summary").json()

    assert body["status"] == "degraded"
    assert any("stale" in p and "dothebay" in p for p in body["problems"])
    assert body["sources"]["stale"] == 1
    assert body["sources"]["worker_stalled"] is False


def test_summary_collapses_all_sources_stale_into_one_worker_outage() -> None:
    """When every source is stale the worker stopped — say that once, not 11 times."""
    stale_run = datetime.now(timezone.utc) - STALE_SOURCE_AFTER - timedelta(hours=1)
    with _build_client() as (client, session):
        for name in ("ticketmaster", "dothebay", "sfstation"):
            session.add(_record(source_name=name, status="healthy", last_run_at=stale_run))
        session.commit()

        body = client.get("/health/summary").json()

    assert body["sources"]["worker_stalled"] is True
    worker_problems = [p for p in body["problems"] if p.startswith("worker:")]
    assert len(worker_problems) == 1
    # The per-source staleness noise is suppressed in favour of the diagnosis.
    assert not [p for p in body["problems"] if "stale" in p and p.startswith("source")]


def test_summary_treats_a_degraded_source_as_degraded_not_failing() -> None:
    with _build_client() as (client, session):
        session.add(
            _record(source_name="reddit", status="degraded", last_event_count=0, consecutive_zeros=1)
        )
        session.commit()

        body = client.get("/health/summary").json()

    assert body["status"] == "degraded"
    assert any("reddit" in p for p in body["problems"])


def test_summary_flags_an_empty_corpus_as_a_user_visible_outage() -> None:
    """An API that returns zero events is broken from the user's point of view."""
    with _build_client() as (client, _):
        body = client.get("/health/summary").json()

    assert any("corpus" in p for p in body["problems"])


def test_summary_flags_a_worker_that_has_never_run() -> None:
    """Registered-but-never-run sources must not read as 'ok' at first deploy.

    This is the moment a deployment check is most likely to be trusted, so a
    false green here is the most expensive one.
    """
    with _build_client() as (client, _):
        body = client.get("/health/summary").json()

    assert body["status"] != "ok"
    assert any(
        p.startswith("worker:") and "has ever completed" in p for p in body["problems"]
    )


def test_summary_reports_a_failed_source_health_read_rather_than_ok() -> None:
    """If the health query itself breaks, say so — never report 'no problems'."""
    with _build_client() as (client, session):
        # Simulate the schema being absent or out of date.
        session.exec(text("DROP TABLE source_health"))

        body = client.get("/health/summary").json()

    assert body["status"] != "ok"
    assert any(p.startswith("source health:") for p in body["problems"])


def test_summary_does_not_leak_credentials_from_a_source_error() -> None:
    """last_error is served publicly; a leaked DSN or API key would be exposed."""
    with _build_client() as (client, session):
        session.add(
            _record(
                source_name="ticketmaster",
                status="failing",
                last_error=(
                    "HTTPError: GET https://app.ticketmaster.com/v2/events"
                    "?apikey=SUPERSECRETKEY123456 -> 401"
                ),
            )
        )
        session.commit()

        summary = client.get("/health/summary").json()
        sources = client.get("/health/sources").json()

    assert "SUPERSECRETKEY123456" not in json.dumps(summary)
    assert "SUPERSECRETKEY123456" not in json.dumps(sources)
    # The diagnostic shape survives redaction.
    assert any("ticketmaster" in p for p in summary["problems"])


def test_source_health_exposes_error_fields() -> None:
    error_at = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    success_at = datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)
    with _build_client() as (client, session):
        session.add(
            _record(
                source_name="luma",
                status="failing",
                last_error="HTTPError: 403 Forbidden",
                last_error_at=error_at,
                last_success_at=success_at,
            )
        )
        session.commit()

        by_name = {s["name"]: s for s in client.get("/health/sources").json()["sources"]}

    assert by_name["luma"]["last_error"] == "HTTPError: 403 Forbidden"
    # SQLite has no timestamptz, so the offset is dropped on round-trip here
    # (Postgres preserves it). Assert on the instant, not the serialized text.
    assert by_name["luma"]["last_error_at"].startswith(error_at.strftime("%Y-%m-%dT%H:%M"))
    assert by_name["luma"]["last_success_at"].startswith(success_at.strftime("%Y-%m-%dT%H:%M"))
