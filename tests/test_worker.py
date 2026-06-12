from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import pytest

from app.worker import IngestionWorker

pytestmark = pytest.mark.anyio


class _FakeSource:
    def __init__(self, *, source_name: str, events: list[dict[str, Any]]) -> None:
        self.source_name = source_name
        self._events = events
        self.closed = False

    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._events)

    async def close(self) -> None:
        self.closed = True

    def set_events(self, events: list[dict[str, Any]]) -> None:
        self._events = events


class _FakeRegistry:
    def __init__(self, sources: dict[str, _FakeSource]) -> None:
        self._sources = sources

    def list_sources(self) -> list[str]:
        return sorted(self._sources.keys())

    def create(self, name: str) -> _FakeSource:
        return self._sources[name]


class _FakePipeline:
    def __init__(self) -> None:
        self.last_raw_events: list[dict[str, Any]] | None = None

    async def process_raw_events(
        self, *, session: object, raw_events: list[dict[str, Any]]
    ) -> dict[str, int]:
        self.last_raw_events = raw_events
        return {
            "inserted": len(raw_events),
            "updated": 0,
            "skipped": 0,
            "deduped_count": len(raw_events),
        }


def _event(title: str) -> dict[str, Any]:
    return {"title": title}


async def test_worker_run_once_processes_all_sources() -> None:
    source_a = _FakeSource(source_name="alpha", events=[_event("a1"), _event("a2")])
    source_b = _FakeSource(source_name="beta", events=[_event("b1")])
    registry = _FakeRegistry({"alpha": source_a, "beta": source_b})
    pipeline = _FakePipeline()
    worker = IngestionWorker(
        source_registry=registry,
        pipeline_service=pipeline,
        session_factory=lambda: nullcontext(object()),
        run_interval_seconds=1,
    )

    result = await worker.run_once()

    assert result.total_events_fetched == 3
    assert result.per_source_counts == {"alpha": 2, "beta": 1}
    assert result.pipeline_summary["inserted"] == 3
    assert pipeline.last_raw_events is not None
    assert len(pipeline.last_raw_events) == 3
    assert source_a.closed is True
    assert source_b.closed is True


async def test_worker_canary_logs_critical_when_drop_to_zero(caplog: Any) -> None:
    source = _FakeSource(source_name="alpha", events=[_event(str(i)) for i in range(12)])
    registry = _FakeRegistry({"alpha": source})
    worker = IngestionWorker(
        source_registry=registry,
        pipeline_service=_FakePipeline(),
        session_factory=lambda: nullcontext(object()),
        run_interval_seconds=1,
    )

    await worker.run_once()

    source.set_events([])
    with caplog.at_level("CRITICAL"):
        await worker.run_once()

    assert "CANARY ALERT" in caplog.text


async def test_worker_logs_quota_warning_when_only_one_key_active(caplog: Any, monkeypatch: Any) -> None:
    source = _FakeSource(source_name="ticketmaster", events=[_event("x")])
    registry = _FakeRegistry({"ticketmaster": source})
    worker = IngestionWorker(
        source_registry=registry,
        pipeline_service=_FakePipeline(),
        session_factory=lambda: nullcontext(object()),
        run_interval_seconds=1,
    )

    class _FakeSecretsStore:
        def health(self, provider: str) -> list[Any]:
            class _Health:
                def __init__(self, status: str) -> None:
                    self.status = status

            return [_Health(status="active"), _Health(status="exhausted")]

    monkeypatch.setattr("app.worker.get_secrets_store", lambda: _FakeSecretsStore())

    with caplog.at_level("WARNING"):
        await worker.run_once()

    assert "AAIM quota health warning" in caplog.text


async def test_worker_persists_source_health_to_database() -> None:
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.models.source_health import SourceHealthRecord

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine, tables=[SourceHealthRecord.__table__]
    )

    source_ok = _FakeSource(source_name="alpha", events=[_event("a1")])
    source_empty = _FakeSource(source_name="beta", events=[])
    registry = _FakeRegistry({"alpha": source_ok, "beta": source_empty})
    worker = IngestionWorker(
        source_registry=registry,
        pipeline_service=_FakePipeline(),
        session_factory=lambda: Session(engine),
        run_interval_seconds=1,
    )

    await worker.run_once()

    with Session(engine) as session:
        records = {r.source_name: r for r in session.exec(select(SourceHealthRecord)).all()}
    assert records["alpha"].status == "healthy"
    assert records["alpha"].last_event_count == 1
    assert records["beta"].status == "degraded"
    assert records["beta"].consecutive_zeros == 1
