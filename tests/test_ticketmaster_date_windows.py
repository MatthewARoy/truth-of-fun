"""Ticketmaster fetch by date window, under the Discovery API's deep-paging cap.

The API will not page past the 1000th result of a query (page * size < 1000).
The Bay Area DMA held 2958 events when checked 2026-09-12, and the old
open-ended, date-sorted query stopped at exactly 1000 (its latest event
2026-10-15, its earliest from 2025-11). These tests run the fetch against a
fake API that enforces the cap; nothing reaches Ticketmaster.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.ingestion import ticketmaster as tm_module
from app.ingestion.ticketmaster import TicketmasterSource

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 12, 17, 0, tzinfo=timezone.utc)
API_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"


@pytest.fixture(autouse=True)
def sync_state(tmp_path, monkeypatch):
    """Keep the on-disk sync cursor out of the checkout."""
    path = tmp_path / "sync_state.json"
    monkeypatch.setattr(tm_module, "_SYNC_STATE_PATH", path)
    return path


def _raw_event(event_id: str, start: datetime) -> dict[str, Any]:
    return {
        "id": event_id,
        "name": f"Event {event_id}",
        "url": f"https://ticketmaster.example/{event_id}",
        "dates": {
            "start": {"dateTime": start.strftime(API_TIMESTAMP)},
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


class _FakeDiscoveryApi:
    """Filters on startDateTime/endDateTime and refuses to page past 1000."""

    def __init__(self, starts: list[datetime]) -> None:
        events = [
            (start, _raw_event(f"tm_{i}", start)) for i, start in enumerate(starts)
        ]
        self._events = sorted(events, key=lambda pair: pair[0])
        self.calls: list[dict[str, Any]] = []

    async def fetch_page(self, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(params))
        if params.get("includeTBA") == "only":
            return {"page": {"totalElements": 0, "totalPages": 0}}
        size, page = params["size"], params["page"]
        if page * size >= 1000:
            raise RuntimeError(
                "DIS1035: deep paging beyond 1000 results is not supported"
            )
        window_start = datetime.strptime(
            params["startDateTime"], API_TIMESTAMP
        ).replace(tzinfo=timezone.utc)
        window_end = datetime.strptime(params["endDateTime"], API_TIMESTAMP).replace(
            tzinfo=timezone.utc
        )
        # Inclusive at both ends, so adjacent windows overlap on their boundary.
        matching = [
            raw for start, raw in self._events if window_start <= start <= window_end
        ]
        return {
            "page": {
                "size": size,
                "number": page,
                "totalElements": len(matching),
                "totalPages": math.ceil(len(matching) / size),
            },
            "_embedded": {"events": matching[page * size : (page + 1) * size]},
        }


def _source(monkeypatch, api: _FakeDiscoveryApi) -> TicketmasterSource:
    source = TicketmasterSource(api_key="test-key")
    monkeypatch.setattr(source, "_fetch_page", api.fetch_page)
    return source


async def test_every_event_in_the_horizon_is_read_despite_the_deep_paging_cap(
    monkeypatch,
) -> None:
    # 2958 events over the next ~170 days, plus one exactly on the first split.
    starts = [NOW + timedelta(minutes=83 * i) for i in range(2958)]
    starts.append(NOW + timedelta(days=90))
    api = _FakeDiscoveryApi(starts)
    source = _source(monkeypatch, api)

    events = await source.fetch_events(now=NOW)

    ids = [event["source_event_id"] for event in events]
    assert len(ids) == len(set(ids)) == 2959
    assert source.last_fetch_error is None
    assert all(call["page"] * call["size"] < 1000 for call in api.calls)
    # Comfortably inside a ~5000/day quota at four runs a day.
    assert len(api.calls) <= 40
    start_times = [event["start_at"] for event in events]
    assert start_times == sorted(start_times)


async def test_a_window_under_the_cap_is_read_whole_starting_now(monkeypatch) -> None:
    api = _FakeDiscoveryApi([NOW + timedelta(hours=i) for i in range(300)])
    source = _source(monkeypatch, api)

    events = await source.fetch_events(now=NOW)

    assert len(events) == 300
    assert [(c["startDateTime"], c["endDateTime"], c["page"]) for c in api.calls if "startDateTime" in c] == [
        ("2026-09-12T17:00:00Z", "2027-03-11T17:00:00Z", 0),
        ("2026-09-12T17:00:00Z", "2027-03-11T17:00:00Z", 1),
    ]


async def test_a_day_over_the_cap_returns_what_is_reachable_and_says_so(
    monkeypatch, caplog
) -> None:
    api = _FakeDiscoveryApi([NOW + timedelta(seconds=i) for i in range(1200)])
    source = _source(monkeypatch, api)

    events = await source.fetch_events(now=NOW)

    assert len(events) == 1000
    assert source.last_fetch_error is not None
    source.acknowledge_persisted()
    assert tm_module._load_last_sync_timestamp() is None
    assert "only the first 1000 are reachable" in caplog.text
    assert len(api.calls) <= 40


async def test_running_out_of_request_budget_is_reported_as_a_partial_fetch(
    monkeypatch,
) -> None:
    monkeypatch.setattr(tm_module, "_MAX_REQUESTS_PER_RUN", 3)
    api = _FakeDiscoveryApi([NOW + timedelta(hours=i) for i in range(900)])
    source = _source(monkeypatch, api)

    events = await source.fetch_events(now=NOW)

    assert len(api.calls) == 3
    assert len(events) == 600
    assert source.last_fetch_error is not None
    assert "budget" in source.last_fetch_error
    assert tm_module._load_last_sync_timestamp() is None
