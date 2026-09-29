from datetime import datetime, timezone
from typing import Any

import pytest

from app.ingestion import ticketmaster as tm_module
from app.ingestion.registry import SourceRegistry
from app.ingestion.ticketmaster import TicketmasterSource


def test_source_registry_registers_ticketmaster() -> None:
    registry = SourceRegistry()
    registry.register("ticketmaster", TicketmasterSource)

    assert registry.list_sources() == ["ticketmaster"]
    assert registry.get("ticketmaster") is TicketmasterSource


def test_ticketmaster_mapping_to_canonical_event_payload() -> None:
    source = TicketmasterSource(api_key="test-key")
    raw_event = {
        "id": "tm_123",
        "name": "Bay Lights Festival",
        "url": "https://ticketmaster.example/events/tm_123",
        "info": "A waterfront music and arts event.",
        "dates": {
            "start": {"dateTime": "2026-06-01T02:00:00Z"},
            "end": {"dateTime": "2026-06-01T05:00:00Z"},
            "status": {"code": "onsale"},
            "timezone": "America/Los_Angeles",
        },
        "priceRanges": [{"min": 45.00, "currency": "USD"}],
        "images": [
            {"url": "https://img.example/small.jpg", "width": 320, "height": 180},
            {"url": "https://img.example/large.jpg", "width": 1920, "height": 1080},
        ],
        "classifications": [
            {
                "segment": {"name": "Music"},
                "genre": {"name": "Rock"},
                "subGenre": {"name": "Alternative"},
            }
        ],
        "_embedded": {
            "venues": [
                {
                    "name": "Pier 70",
                    "address": {"line1": "420 22nd St"},
                    "city": {"name": "San Francisco"},
                    "state": {"stateCode": "CA"},
                    "postalCode": "94107",
                    "country": {"name": "United States"},
                    "location": {"latitude": "37.7577", "longitude": "-122.3872"},
                }
            ],
            "attractions": [{"name": "Headliner Artist"}],
        },
    }

    mapped = source._map_ticketmaster_event(raw_event)
    assert mapped is not None
    assert mapped["source_name"] == "ticketmaster"
    assert mapped["source_tier"] == 1
    assert mapped["source_event_id"] == "tm_123"
    assert mapped["title"] == "Bay Lights Festival"
    assert mapped["location"] == "POINT(-122.3872 37.7577)"
    assert "Music" in mapped["categories"]
    # Performer names are not vibes; they must not pollute the tag space.
    assert mapped["tags"] == []
    assert mapped["status"] == "scheduled"


def test_ticketmaster_skips_events_without_coordinates() -> None:
    source = TicketmasterSource(api_key="test-key")
    raw_event = {
        "name": "No Geo Event",
        "dates": {"start": {"dateTime": "2026-06-01T02:00:00Z"}},
        "_embedded": {"venues": [{"name": "Unknown Venue"}]},
    }

    mapped = source._map_ticketmaster_event(raw_event)
    assert mapped is None


# --- Event status ------------------------------------------------------------
#
# The `dates` blocks below are copied from real Discovery API responses for the
# Bay Area DMA (382), fetched 2026-09-12.

# Dan and Phil at the Palace of Fine Arts (G5vYZ_ukh_5Ol). Postponing without a
# new date blanks `dates.start`; the original date survives only as
# `initialStartDate`.
_POSTPONED_WITHOUT_NEW_DATE = {
    "start": {
        "dateTBD": False,
        "dateTBA": True,
        "timeTBA": False,
        "noSpecificTime": False,
    },
    "initialStartDate": {
        "localDate": "2026-09-13",
        "localTime": "19:30:00",
        "dateTime": "2026-09-14T02:30:00Z",
    },
    "timezone": "America/Los_Angeles",
    "status": {"code": "postponed"},
    "spanMultipleDays": False,
}


def _listing(
    *, dates: dict[str, Any], event_id: str = "G5vYZ_ukh_5Ol"
) -> dict[str, Any]:
    return {
        "id": event_id,
        "name": "Dan and Phil: Hard Launch World Tour",
        "url": f"https://www.ticketmaster.com/event/{event_id}",
        "dates": dates,
        "_embedded": {
            "venues": [
                {
                    "name": "Palace of Fine Arts",
                    "location": {
                        "latitude": "37.80188400",
                        "longitude": "-122.44824900",
                    },
                }
            ]
        },
    }


def _dated(code: str) -> dict[str, Any]:
    return {
        "start": {
            "localDate": "2026-09-13",
            "localTime": "19:30:00",
            "dateTime": "2026-09-14T02:30:00Z",
        },
        "timezone": "America/Los_Angeles",
        "status": {"code": code},
    }


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("onsale", "scheduled"),
        ("postponed", "postponed"),
        # A rescheduled event carries its firm new date in `dates.start` (the
        # old one moves to `initialStartDate`), so the show is on, at that date.
        ("rescheduled", "scheduled"),
        ("cancelled", "cancelled"),
        # Offsale means Ticketmaster isn't selling tickets right now (sold out,
        # sales closed, box office only), not that the show is off. Of the 80
        # rows stored as cancelled on 2026-09-12, Ticketmaster reported 27 as
        # offsale and 3 as back onsale.
        ("offsale", "scheduled"),
    ],
)
def test_ticketmaster_status_codes_map_to_event_status(
    code: str, expected: str
) -> None:
    source = TicketmasterSource(api_key="test-key")

    mapped = source._map_ticketmaster_event(_listing(dates=_dated(code)))

    assert mapped is not None
    assert mapped["status"] == expected


def test_postponed_event_with_no_new_date_keeps_its_original_date() -> None:
    """Dropping a dateless event meant the postponement never reached the row.

    The stored row went on saying the show was happening. The original date is
    still published, and it is exactly what the stored row holds, so it is also
    what lets the pipeline find that row.
    """
    source = TicketmasterSource(api_key="test-key")

    mapped = source._map_ticketmaster_event(_listing(dates=_POSTPONED_WITHOUT_NEW_DATE))

    assert mapped is not None
    assert mapped["status"] == "postponed"
    assert mapped["start_at"] == datetime(2026, 9, 14, 2, 30, tzinfo=timezone.utc)


def test_rescheduled_event_is_stored_at_its_new_date() -> None:
    """Gimme Gimme Disco (G5vYZ_GzP0DLP) moved from 2026-07-31 to 2026-09-12."""
    source = TicketmasterSource(api_key="test-key")
    dates = {
        "start": {
            "localDate": "2026-09-12",
            "localTime": "20:30:00",
            "dateTime": "2026-09-13T03:30:00Z",
            "dateTBD": False,
            "dateTBA": False,
            "timeTBA": False,
            "noSpecificTime": False,
        },
        "initialStartDate": {
            "localDate": "2026-07-31",
            "localTime": "20:30:00",
            "dateTime": "2026-08-01T03:30:00Z",
        },
        "timezone": "America/Los_Angeles",
        "status": {"code": "rescheduled"},
    }

    mapped = source._map_ticketmaster_event(
        _listing(dates=dates, event_id="G5vYZ_GzP0DLP")
    )

    assert mapped is not None
    assert mapped["status"] == "scheduled"
    assert mapped["start_at"] == datetime(2026, 9, 13, 3, 30, tzinfo=timezone.utc)


def test_original_date_is_not_borrowed_for_a_listing_that_is_not_postponed() -> None:
    """Only a postponement makes the original date the honest one to store.

    Same shape as Dan and Phil with the code swapped: an onsale listing whose
    date was withdrawn has no date we can present as its date.
    """
    source = TicketmasterSource(api_key="test-key")
    dates = {**_POSTPONED_WITHOUT_NEW_DATE, "status": {"code": "onsale"}}

    assert source._map_ticketmaster_event(_listing(dates=dates)) is None


def _page(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "page": {"totalPages": 1, "totalElements": len(events)},
        "_embedded": {"events": events},
    }


@pytest.mark.anyio
async def test_fetch_reads_postponed_events_the_default_search_hides(
    tmp_path, monkeypatch
) -> None:
    """Discovery search leaves out date-TBA events unless asked (`includeTBA`).

    A show postponed without a new date is one, so the connector never saw Dan
    and Phil again after the postponement. On 2026-09-12 the Bay Area had 12
    such events, 9 of them postponed: one extra call.
    """
    monkeypatch.setattr(tm_module, "_SYNC_STATE_PATH", tmp_path / "sync_state.json")
    source = TicketmasterSource(api_key="test-key")

    async def _fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        if params.get("includeTBA") == "only":
            return _page([_listing(dates=_POSTPONED_WITHOUT_NEW_DATE)])
        return _page([_listing(dates=_dated("onsale"), event_id="G5vYZ_63xglaS")])

    monkeypatch.setattr(source, "_fetch_page", _fetch_page)

    events = await source.fetch_events()

    assert sorted((event["source_event_id"], event["status"]) for event in events) == [
        ("G5vYZ_63xglaS", "scheduled"),
        ("G5vYZ_ukh_5Ol", "postponed"),
    ]


@pytest.mark.anyio
async def test_failed_postponed_pass_does_not_advance_the_cursor(
    tmp_path, monkeypatch
) -> None:
    """Same rule as a failed page: a window only partly read is re-read next run."""
    monkeypatch.setattr(tm_module, "_SYNC_STATE_PATH", tmp_path / "sync_state.json")
    source = TicketmasterSource(api_key="test-key")

    async def _fetch_page(params: dict[str, Any]) -> dict[str, Any]:
        if params.get("includeTBA") == "only":
            raise TimeoutError("upstream timed out")
        return _page([_listing(dates=_dated("onsale"), event_id="G5vYZ_63xglaS")])

    monkeypatch.setattr(source, "_fetch_page", _fetch_page)

    events = await source.fetch_events()

    assert [event["source_event_id"] for event in events] == ["G5vYZ_63xglaS"]
    assert tm_module._load_last_sync_timestamp() is None
    assert source.last_fetch_error is not None


@pytest.mark.anyio
async def test_date_tbd_postponements_are_read_without_date_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(tm_module, "_SYNC_STATE_PATH", tmp_path / "sync.json")
    source = TicketmasterSource(api_key="fixture")
    calls = []
    async def page(params):
        calls.append(params)
        if params.get("includeTBD") == "only":
            assert "startDateTime" not in params and "endDateTime" not in params
            dates = {**_POSTPONED_WITHOUT_NEW_DATE, "start": {"dateTBD": True}}
            return _page([_listing(dates=dates, event_id="tm-tbd")])
        return _page([])
    monkeypatch.setattr(source, "_fetch_page", page)
    events = await source.fetch_events()
    assert [(event["source_event_id"], event["status"]) for event in events] == [("tm-tbd", "postponed")]
    assert source.last_fetch_error is None
    assert len(calls) == 3


@pytest.mark.anyio
async def test_usage_errors_do_not_store_credential_bearing_request_urls(monkeypatch):
    import httpx
    source = TicketmasterSource(api_key="SUPERSECRET")
    source._aaim_enabled = True
    reports = []
    class Store:
        def report_usage(self, **kwargs):
            reports.append(kwargs)
    monkeypatch.setattr(tm_module, "get_secrets_store", lambda: Store())
    source._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(401, request=request)
    ))
    with pytest.raises(httpx.HTTPStatusError):
        await source._fetch_page({"page": 0})
    assert reports[0]["last_status"] == 401
    assert reports[0]["last_error"] == "HTTPStatusError"
    assert "SUPERSECRET" not in str(reports)
    await source.close()


@pytest.mark.anyio
async def test_usage_counts_each_http_retry(monkeypatch):
    import httpx
    reports = []
    statuses = iter([429, 503, 200])
    class Store:
        def report_usage(self, **kwargs):
            reports.append(kwargs)
    monkeypatch.setattr(tm_module, "get_secrets_store", lambda: Store())
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(next(statuses), json={}, request=request)
    )) as client:
        source = TicketmasterSource(api_key="private", client=client)
        source._aaim_enabled = True
        source.BACKOFF_BASE_SECONDS = 0
        assert await source._fetch_page({}) == {}
    assert len(reports) == 3
    assert [r["last_status"] for r in reports] == [429, 503, 200]
    assert all(r["calls"] == 1 for r in reports)
    assert "private" not in str(reports)
