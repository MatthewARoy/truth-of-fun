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


async def test_recorded_failure_reason_carries_no_credential(sync_state, monkeypatch) -> None:
    """The reason is meant to be surfaceable, so it must never quote the request."""
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
    assert "RuntimeError" in source.last_fetch_error
