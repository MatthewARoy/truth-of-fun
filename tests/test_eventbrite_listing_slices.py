"""Eventbrite listing crawl: sliced, paginated, bounded.

The unfiltered SF listing ignores ``?page=`` (page 2 repeated page 1, all 32
events, when captured 2026-09-12) and 301s a date filter to ``/all-events/``,
so the old single GET was the whole fetch. Filtered listings do paginate and
report their own ``page_count``. The pages below keep the live shape (JSON-LD
ItemList plus the results' pagination block) and are served through
``httpx.MockTransport``; nothing touches the live site.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.ingestion.sources.eventbrite import EventbriteSource
from app.services.categories import CANONICAL_CATEGORIES

pytestmark = pytest.mark.anyio

TODAY = date(2026, 9, 12)
WINDOW = "start_date=2026-09-12&end_date=2026-09-25"
BASE = "https://www.eventbrite.com/d/ca--san-francisco"


def _listing_page(
    event_ids: list[int], *, page_count: int, page_number: int = 1
) -> str:
    items = [
        {
            "position": position,
            "@type": "ListItem",
            "item": {
                "@type": "Event",
                "name": f"Show {event_id}",
                "url": f"https://www.eventbrite.com/e/show-{event_id}-tickets-{event_id}",
                "startDate": "2026-09-13",
                "endDate": "2026-09-13",
                "location": {
                    "@type": "Place",
                    "name": "Cheaper Than Therapy",
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "533 Sutter Street",
                        "addressLocality": "San Francisco",
                        "addressRegion": "CA",
                    },
                    "geo": {
                        "@type": "GeoCoordinates",
                        "latitude": "37.7893",
                        "longitude": "-122.4101",
                    },
                },
            },
        }
        for position, event_id in enumerate(event_ids, start=1)
    ]
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": items,
    }
    server_data = {
        "search_data": {
            "events": {
                "pagination": {
                    "object_count": len(event_ids) * page_count,
                    "page_count": page_count,
                    "page_number": page_number,
                    "page_size": 20,
                }
            }
        }
    }
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(item_list)
        + "</script></head><body><script>window.__SERVER_DATA__ = "
        + json.dumps(server_data)
        + ";</script></body></html>"
    )


def _source(
    pages: dict[str, str], **overrides: object
) -> tuple[EventbriteSource, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url in pages:
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404, text="not found")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = EventbriteSource(client=client, max_requests_per_second=1000)
    for name, value in overrides.items():
        setattr(source, name, value)
    return source, requested


def test_every_slice_category_is_canonical() -> None:
    labels = {category for _, category in EventbriteSource.listing_slices if category}
    assert labels <= set(CANONICAL_CATEGORIES)


def test_default_slices_never_use_the_unfiltered_listing() -> None:
    # /d/ca--san-francisco/events/ ignores ?page= and 301s a date filter (and
    # httpx raises on a redirect), so every slice must be a filtered path.
    for slug, _ in EventbriteSource.listing_slices:
        assert slug == "all-events" or slug.endswith("--events")


async def test_crawls_each_slice_to_its_last_page_and_labels_categories() -> None:
    comedy_p1 = f"{BASE}/comedy--events/?{WINDOW}"
    comedy_p2 = f"{BASE}/comedy--events/?{WINDOW}&page=2"
    music_p1 = f"{BASE}/music--events/?{WINDOW}"
    all_p1 = f"{BASE}/all-events/?{WINDOW}"
    source, requested = _source(
        {
            comedy_p1: _listing_page([1, 2], page_count=2),
            comedy_p2: _listing_page([3], page_count=2, page_number=2),
            music_p1: _listing_page([4], page_count=1),
            # The unfiltered slice repeats a comedy show and adds one of its own.
            all_p1: _listing_page([1, 5], page_count=1),
        },
        listing_slices=(
            ("comedy--events", "Comedy"),
            ("music--events", "Music"),
            ("all-events", None),
        ),
    )

    candidates = await source.discover_candidates(today=TODAY)

    assert requested == [comedy_p1, comedy_p2, music_p1, all_p1]
    assert {c["title"]: c["categories"] for c in candidates} == {
        "Show 1": ["Comedy"],
        "Show 2": ["Comedy"],
        "Show 3": ["Comedy"],
        "Show 4": ["Music"],
        "Show 5": [],
    }
    assert source.last_fetch_error is None


async def test_slice_category_reaches_the_event_payload() -> None:
    url = f"{BASE}/comedy--events/?{WINDOW}"
    source, _ = _source(
        {url: _listing_page([7], page_count=1)},
        listing_slices=(("comedy--events", "Comedy"),),
    )

    payloads = await source.fetch_events(today=TODAY)

    assert len(payloads) == 1
    assert payloads[0]["categories"] == ["Comedy"]


async def test_a_deep_slice_stops_at_the_per_slice_page_cap() -> None:
    urls = [f"{BASE}/all-events/?{WINDOW}"] + [
        f"{BASE}/all-events/?{WINDOW}&page={n}" for n in range(2, 10)
    ]
    pages = {
        url: _listing_page([100 + n], page_count=49, page_number=n + 1)
        for n, url in enumerate(urls)
    }
    source, requested = _source(
        pages, listing_slices=(("all-events", None),), max_pages_per_slice=5
    )

    candidates = await source.discover_candidates(today=TODAY)

    assert requested == urls[:5]
    assert len(candidates) == 5

    assert source.last_fetch_error is not None
    assert "cap" in source.last_fetch_error.lower()


async def test_a_page_that_repeats_the_previous_one_ends_the_slice() -> None:
    p1 = f"{BASE}/nightlife--events/?{WINDOW}"
    p2 = f"{BASE}/nightlife--events/?{WINDOW}&page=2"
    same = _listing_page([8, 9], page_count=22)
    source, requested = _source(
        {p1: same, p2: same}, listing_slices=(("nightlife--events", "Nightlife"),)
    )

    candidates = await source.discover_candidates(today=TODAY)

    assert requested == [p1, p2]
    assert len(candidates) == 2


async def test_the_run_wide_request_budget_caps_all_slices_together() -> None:
    pages: dict[str, str] = {}
    event_id = 0
    for slug in ("comedy--events", "music--events"):
        for n in range(1, 6):
            event_id += 1
            url = f"{BASE}/{slug}/?{WINDOW}" + ("" if n == 1 else f"&page={n}")
            pages[url] = _listing_page([event_id], page_count=5, page_number=n)
    source, requested = _source(
        pages,
        listing_slices=(("comedy--events", "Comedy"), ("music--events", "Music")),
        max_requests=7,
    )

    await source.discover_candidates(today=TODAY)

    assert len(requested) == 7
    assert requested[-1] == f"{BASE}/music--events/?{WINDOW}&page=2"


async def test_a_failed_later_page_keeps_earlier_events_and_reports_a_partial_fetch() -> (
    None
):
    p1 = f"{BASE}/comedy--events/?{WINDOW}"
    source, requested = _source(
        {p1: _listing_page([1, 2], page_count=3)},
        listing_slices=(("comedy--events", "Comedy"), ("all-events", None)),
    )

    candidates = await source.discover_candidates(today=TODAY)

    assert [c["title"] for c in candidates] == ["Show 1", "Show 2"]
    assert requested == [p1, f"{BASE}/comedy--events/?{WINDOW}&page=2"]
    assert source.last_fetch_error is not None
    assert "HTTPStatusError" in source.last_fetch_error


async def test_a_failed_first_page_raises_so_the_worker_marks_the_source_failing() -> (
    None
):
    source, _ = _source({}, listing_slices=(("comedy--events", "Comedy"),))

    with pytest.raises(httpx.HTTPStatusError):
        await source.discover_candidates(today=TODAY)
