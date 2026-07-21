"""The incremental sync cursor must not advance past events we never read.

Ticketmaster is the tier-1 source and its fetch is paginated with a
``modifiedDate`` cursor. If a page fails and the cursor still advances, every
event on the pages we did not reach is filtered out of the next run — and every
run after that. The loss is silent and permanent.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ingestion import ticketmaster as tm_module
from app.ingestion.ticketmaster import TicketmasterSource

pytestmark = pytest.mark.anyio


@pytest.fixture
def sync_state(tmp_path, monkeypatch):
    """Redirect the on-disk sync cursor into a temp file."""
    path = tmp_path / "sync_state.json"
    monkeypatch.setattr(tm_module, "_SYNC_STATE_PATH", path)
    return path


def _page(events: list[dict[str, Any]], *, total_pages: int) -> dict[str, Any]:
    return {
        "page": {"totalPages": total_pages, "totalElements": total_pages * len(events)},
        "_embedded": {"events": events},
    }


def _raw_event(event_id: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "name": f"Event {event_id}",
        "url": f"https://ticketmaster.example/{event_id}",
        "dates": {
            "start": {"dateTime": "2026-08-01T02:00:00Z"},
            "status": {"code": "onsale"},
        },
        "_embedded": {
            "venues": [
                {
                    "name": "Venue",
                    "location": {"latitude": "37.7577", "longitude": "-122.3872"},
                }
            ]
        },
    }


async def test_cursor_advances_when_every_page_succeeds(sync_state, monkeypatch) -> None:
    source = TicketmasterSource(api_key="test-key")

    async def _fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        return _page([_raw_event(f"tm_{params['page']}")], total_pages=2)

    monkeypatch.setattr(source, "_fetch_page", _fetch_page)

    events = await source.fetch_events()

    assert len(events) == 2
    assert source.last_fetch_error is None
    assert tm_module._load_last_sync_timestamp() is not None


async def test_cursor_does_not_advance_when_a_page_fails(sync_state, monkeypatch) -> None:
    """The whole point: a partial read must be re-read next run, not skipped."""
    source = TicketmasterSource(api_key="test-key")

    async def _fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        if params["page"] == 0:
            return _page([_raw_event("tm_0")], total_pages=3)
        raise TimeoutError("upstream timed out")

    monkeypatch.setattr(source, "_fetch_page", _fetch_page)

    events = await source.fetch_events()

    # The events we did read are still returned — a partial result beats none.
    assert len(events) == 1
    # But the cursor stays put, so the missed pages are re-read next run.
    assert tm_module._load_last_sync_timestamp() is None
    assert source.last_fetch_error is not None
    assert "TimeoutError" in source.last_fetch_error


async def test_partial_failure_preserves_a_previous_cursor(sync_state, monkeypatch) -> None:
    """A failure must not advance the cursor, but must not lose it either."""
    tm_module._save_last_sync_timestamp("2026-07-01T00:00:00Z")
    source = TicketmasterSource(api_key="test-key")

    async def _fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(source, "_fetch_page", _fetch_page)

    await source.fetch_events()

    assert tm_module._load_last_sync_timestamp() == "2026-07-01T00:00:00Z"


async def test_partial_failure_error_text_is_redacted(sync_state, monkeypatch) -> None:
    """The recorded reason reaches GET /health/sources — it must carry no key."""
    source = TicketmasterSource(api_key="test-key")

    async def _fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(
            "GET https://app.ticketmaster.com/discovery/v2/events.json"
            "?apikey=SUPERSECRETVALUE1234 -> 401"
        )

    monkeypatch.setattr(source, "_fetch_page", _fetch_page)

    await source.fetch_events()

    assert source.last_fetch_error is not None
    assert "SUPERSECRETVALUE1234" not in source.last_fetch_error


async def test_worker_reports_a_partial_fetch_as_failing() -> None:
    """A half-read window must not look like a healthy small result."""
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.models.source_health import SourceHealthRecord
    from app.worker import IngestionWorker, _source_health_state

    _source_health_state.clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[SourceHealthRecord.__table__])

    class _PartiallyFailingSource:
        source_name = "ticketmaster"
        last_fetch_error = "TimeoutError on page 2: upstream timed out"

        async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"title": "one event we did get"}]

        async def close(self) -> None:
            return None

    class _Registry:
        def list_sources(self) -> list[str]:
            return ["ticketmaster"]

        def create(self, name: str) -> Any:
            return _PartiallyFailingSource()

    class _Pipeline:
        async def process_raw_events(
            self, *, session: object, raw_events: list[dict[str, Any]]
        ) -> dict[str, int]:
            return {"inserted": len(raw_events), "updated": 0, "skipped": 0}

    worker = IngestionWorker(
        source_registry=_Registry(),
        pipeline_service=_Pipeline(),
        session_factory=lambda: Session(engine),
        run_interval_seconds=1,
    )

    await worker.run_once()

    with Session(engine) as session:
        record = session.exec(select(SourceHealthRecord)).one()

    assert record.status == "failing"
    assert record.last_error is not None
    assert "TimeoutError" in record.last_error
    # The events it did return still counted.
    assert record.last_event_count == 1
