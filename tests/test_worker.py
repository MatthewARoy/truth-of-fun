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


class _FailingSource:
    """A source whose fetch raises — distinct from one that returns nothing."""

    def __init__(self, *, source_name: str, error: Exception) -> None:
        self.source_name = source_name
        self._error = error
        self.closed = False

    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        raise self._error

    async def close(self) -> None:
        self.closed = True


class _FakeRegistry:
    def __init__(self, sources: dict[str, Any]) -> None:
        self._sources = sources

    def list_sources(self) -> list[str]:
        return sorted(self._sources.keys())

    def create(self, name: str) -> Any:
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


async def test_worker_run_once_resets_quota_exhausted_keys(caplog: Any, monkeypatch: Any) -> None:
    source = _FakeSource(source_name="ticketmaster", events=[_event("x")])
    registry = _FakeRegistry({"ticketmaster": source})
    worker = IngestionWorker(
        source_registry=registry,
        pipeline_service=_FakePipeline(),
        session_factory=lambda: nullcontext(object()),
        run_interval_seconds=1,
        quota_window_hours=24,
    )

    class _FakeSecretsStore:
        def __init__(self) -> None:
            self.reset_calls: list[int] = []

        def health(self, provider: str) -> list[Any]:
            return []

        def reset_exhausted_keys(self, provider: str, *, window_seconds: int, now: Any = None) -> list[str]:
            self.reset_calls.append(window_seconds)
            return ["key-a"]

    store = _FakeSecretsStore()
    monkeypatch.setattr("app.worker.get_secrets_store", lambda: store)

    with caplog.at_level("INFO"):
        await worker.run_once()

    # The worker asked the store to roll over quota windows (24h -> 86400s) ...
    assert store.reset_calls == [24 * 3600]
    # ... and logged the recovery so operators can see it happened.
    assert "quota-window reset" in caplog.text.lower()


async def test_worker_skips_quota_reset_when_window_disabled(monkeypatch: Any) -> None:
    source = _FakeSource(source_name="ticketmaster", events=[_event("x")])
    registry = _FakeRegistry({"ticketmaster": source})
    worker = IngestionWorker(
        source_registry=registry,
        pipeline_service=_FakePipeline(),
        session_factory=lambda: nullcontext(object()),
        run_interval_seconds=1,
        quota_window_hours=0,
    )

    class _FakeSecretsStore:
        def __init__(self) -> None:
            self.reset_calls = 0

        def health(self, provider: str) -> list[Any]:
            return []

        def reset_exhausted_keys(self, provider: str, *, window_seconds: int, now: Any = None) -> list[str]:
            self.reset_calls += 1
            return []

    store = _FakeSecretsStore()
    monkeypatch.setattr("app.worker.get_secrets_store", lambda: store)

    await worker.run_once()

    assert store.reset_calls == 0


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
    assert records["alpha"].last_error is None
    assert records["alpha"].last_success_at is not None
    assert records["beta"].status == "degraded"
    assert records["beta"].consecutive_zeros == 1


async def test_worker_persists_the_exception_text_when_a_source_raises() -> None:
    """A broken scraper must be diagnosable from /health/sources, not just logs."""
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.models.source_health import SourceHealthRecord
    from app.worker import _source_health_state

    # _source_health_state is module-level and accumulates across the suite;
    # without this the persist step writes other tests' sources too.
    _source_health_state.clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[SourceHealthRecord.__table__])

    broken = _FailingSource(
        source_name="funcheap_sf", error=TimeoutError("page.goto exceeded 30000ms")
    )
    worker = IngestionWorker(
        source_registry=_FakeRegistry({"funcheap_sf": broken}),
        pipeline_service=_FakePipeline(),
        session_factory=lambda: Session(engine),
        run_interval_seconds=1,
    )

    await worker.run_once()

    with Session(engine) as session:
        record = session.exec(select(SourceHealthRecord)).one()

    # A raised exception is a harder signal than a zero count: fail immediately
    # rather than climbing the consecutive-zero ladder first.
    assert record.status == "failing"
    assert record.last_error is not None
    assert "TimeoutError" in record.last_error
    assert "page.goto exceeded" in record.last_error
    assert record.last_error_at is not None
    assert record.last_success_at is None
    assert broken.closed is True


async def test_worker_clears_the_error_once_a_source_recovers() -> None:
    """A recovered source must not keep displaying a stale failure."""
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.models.source_health import SourceHealthRecord
    from app.worker import _source_health_state

    _source_health_state.clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[SourceHealthRecord.__table__])

    sources: dict[str, Any] = {
        "alpha": _FailingSource(source_name="alpha", error=RuntimeError("boom"))
    }
    worker = IngestionWorker(
        source_registry=_FakeRegistry(sources),
        pipeline_service=_FakePipeline(),
        session_factory=lambda: Session(engine),
        run_interval_seconds=1,
    )
    await worker.run_once()

    sources["alpha"] = _FakeSource(source_name="alpha", events=[_event("a1")])
    await worker.run_once()

    with Session(engine) as session:
        record = session.exec(select(SourceHealthRecord)).one()

    assert record.status == "healthy"
    assert record.last_error is None
    assert record.last_success_at is not None
    # The failure timestamp is retained as history even though the text cleared.
    assert record.last_error_at is not None
