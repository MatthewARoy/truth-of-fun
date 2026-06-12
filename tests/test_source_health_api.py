"""Tests for GET /health/sources reading worker-persisted state from the database."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Generator
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.models.source_health import SourceHealthRecord
from app.worker import _source_health_state


@contextmanager
def _build_client() -> Generator[tuple[TestClient, Session], None, None]:
    # Simulate the real deployment topology: the API process has no in-process
    # worker state, only what the worker persisted to the database.
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


def test_source_health_reflects_worker_persisted_state() -> None:
    """The API process must see health reported by the separate worker process."""
    with _build_client() as (client, session):
        session.add(
            SourceHealthRecord(
                source_name="ticketmaster",
                status="healthy",
                last_event_count=420,
                consecutive_zeros=0,
                last_run_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
            )
        )
        session.commit()

        response = client.get("/health/sources")

        assert response.status_code == 200
        by_name = {s["name"]: s for s in response.json()["sources"]}
        assert by_name["ticketmaster"]["status"] == "healthy"
        assert by_name["ticketmaster"]["last_event_count"] == 420
        # Registered sources the worker has not reported on yet still appear.
        assert by_name["luma"]["status"] == "unknown"
