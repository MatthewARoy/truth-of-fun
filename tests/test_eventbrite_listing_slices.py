"""Eventbrite listing crawl: multi-city, sliced, paginated, bounded.

The crawl walks a tuple of Bay Area browse locations (``/d/ca--oakland/...``).
San Francisco keeps the full category slices; the other locations read only
``all-events``. Every location slug in the default config answered 200 with
the same page shape when checked live on 2026-11-12.

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

from app.ingestion.sources.eventbrite import ALL_EVENTS_ONLY
from app.ingestion.sources.eventbrite import EventbriteSource
from app.ingestion.sources.eventbrite import ListingLocation
from app.services.categories import CANONICAL_CATEGORIES

pytestmark = pytest.mark.anyio

TODAY = date(2026, 9, 12)
WINDOW = "start_date=2026-09-12&end_date=2026-09-25"
ROOT = "https://www.eventbrite.com/d"
BASE = f"{ROOT}/ca--san-francisco"
OAKLAND = f"{ROOT}/ca--oakland"
SAN_JOSE = f"{ROOT}/ca--san-jose"
SF_ONLY = (ListingLocation("ca--san-francisco", "San Francisco"),)


def _listing_page(
    event_ids: list[int],
    *,
    page_count: int,
    page_number: int = 1,
    city: str | None = "San Francisco",
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
                        **({"addressLocality": city} if city else {}),
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
    # The slice/pagination tests below exercise one location; the multi-city
    # tests pass their own ``listing_locations``.
    overrides.setdefault("listing_locations", SF_ONLY)
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


# ---------------------------------------------------------------------------
# Multi-city crawl
# ---------------------------------------------------------------------------


def test_default_locations_cover_the_bay_beyond_san_francisco() -> None:
    locations = EventbriteSource.listing_locations
    slugs = [location.slug for location in locations]

    assert slugs[0] == "ca--san-francisco"
    assert {"ca--oakland", "ca--berkeley", "ca--san-jose", "ca--palo-alto"} <= set(slugs)
    assert len(slugs) == len(set(slugs))
    # San Francisco keeps the full category slices; the rest stay cheap.
    assert locations[0].slices is None and locations[0].max_pages is None
    for location in locations[1:]:
        assert location.slices == ALL_EVENTS_ONLY
        assert location.max_pages is not None


def test_request_budget_covers_the_whole_default_plan_and_no_more() -> None:
    """max_requests is the sum of every location's worst case, not a guess."""
    source = EventbriteSource
    planned = sum(
        len(location.slices if location.slices is not None else source.listing_slices)
        * (
            location.max_pages
            if location.max_pages is not None
            else source.max_pages_per_slice
        )
        for location in source.listing_locations
    )
    assert source.max_requests == planned
    assert source.max_requests <= 50
    assert source.default_max_requests_per_second == 1


async def test_crawls_each_location_with_its_own_slices_and_page_cap() -> None:
    sf_comedy = f"{BASE}/comedy--events/?{WINDOW}"
    sf_all = f"{BASE}/all-events/?{WINDOW}"
    oak_p1 = f"{OAKLAND}/all-events/?{WINDOW}"
    oak_p2 = f"{OAKLAND}/all-events/?{WINDOW}&page=2"
    sj_p1 = f"{SAN_JOSE}/all-events/?{WINDOW}"
    source, requested = _source(
        {
            sf_comedy: _listing_page([1], page_count=1),
            sf_all: _listing_page([1, 2], page_count=1),
            # The Oakland listing is a metro search: it repeats an SF show.
            oak_p1: _listing_page([2, 10], page_count=2, city="Oakland"),
            oak_p2: _listing_page([11], page_count=2, page_number=2, city="Oakland"),
            sj_p1: _listing_page([20], page_count=1, city="San Jose"),
        },
        listing_slices=(("comedy--events", "Comedy"), ("all-events", None)),
        listing_locations=(
            ListingLocation("ca--san-francisco", "San Francisco"),
            ListingLocation("ca--oakland", "Oakland", ALL_EVENTS_ONLY, 3),
            ListingLocation("ca--san-jose", "San Jose", ALL_EVENTS_ONLY, 3),
        ),
    )

    payloads = await source.fetch_events(today=TODAY)

    # Category slices only for San Francisco; one slice everywhere else.
    assert requested == [sf_comedy, sf_all, oak_p1, oak_p2, sj_p1]
    assert {p["title"]: p["city"] for p in payloads} == {
        "Show 1": "San Francisco",
        # Listed under Oakland too, but its own address says San Francisco.
        "Show 2": "San Francisco",
        "Show 10": "Oakland",
        "Show 11": "Oakland",
        "Show 20": "San Jose",
    }
    assert source.last_fetch_error is None


async def test_city_comes_from_the_event_address_not_the_listing() -> None:
    url = f"{OAKLAND}/all-events/?{WINDOW}"
    source, _ = _source(
        {url: _listing_page([30], page_count=1, city="Emeryville")},
        listing_locations=(ListingLocation("ca--oakland", "Oakland", ALL_EVENTS_ONLY, 1),),
    )

    payloads = await source.fetch_events(today=TODAY)

    assert [p["city"] for p in payloads] == ["Emeryville"]


async def test_a_card_without_a_locality_takes_the_listing_city() -> None:
    url = f"{OAKLAND}/all-events/?{WINDOW}"
    source, _ = _source(
        {url: _listing_page([31], page_count=1, city=None)},
        listing_locations=(ListingLocation("ca--oakland", "Oakland", ALL_EVENTS_ONLY, 1),),
    )

    payloads = await source.fetch_events(today=TODAY)

    assert [p["city"] for p in payloads] == ["Oakland"]


def test_no_locality_and_no_listing_leaves_the_city_blank() -> None:
    """Never assume San Francisco: an unknown city stays unknown."""
    source = EventbriteSource()
    event = source.normalize_raw(
        {
            "title": "Somewhere Show",
            "source_url": "https://www.eventbrite.com/e/somewhere-show-tickets-77",
            "start_date": "2026-09-13",
            "venue_name": "Somewhere",
            "lat": "37.8044",
            "lon": "-122.2712",
        }
    )

    assert event is not None
    assert event.to_legacy_event_payload(source_tier=1)["city"] == ""


async def test_a_secondary_location_stops_at_its_own_page_cap_and_says_which() -> None:
    urls = [f"{OAKLAND}/all-events/?{WINDOW}"] + [
        f"{OAKLAND}/all-events/?{WINDOW}&page={n}" for n in range(2, 6)
    ]
    pages = {
        url: _listing_page([200 + n], page_count=49, page_number=n + 1, city="Oakland")
        for n, url in enumerate(urls)
    }
    source, requested = _source(
        pages,
        listing_locations=(ListingLocation("ca--oakland", "Oakland", ALL_EVENTS_ONLY, 2),),
    )

    candidates = await source.discover_candidates(today=TODAY)

    assert requested == urls[:2]
    assert len(candidates) == 2
    assert source.last_fetch_error is not None
    assert "cap" in source.last_fetch_error.lower()
    assert "ca--oakland/all-events" in source.last_fetch_error


async def test_the_request_budget_spans_locations_and_reports_the_unread_ones() -> None:
    sf_p1 = f"{BASE}/all-events/?{WINDOW}"
    sf_p2 = f"{BASE}/all-events/?{WINDOW}&page=2"
    oak_p1 = f"{OAKLAND}/all-events/?{WINDOW}"
    source, requested = _source(
        {
            sf_p1: _listing_page([1], page_count=2),
            sf_p2: _listing_page([2], page_count=2, page_number=2),
            oak_p1: _listing_page([3], page_count=1, city="Oakland"),
        },
        listing_slices=(("all-events", None),),
        listing_locations=(
            ListingLocation("ca--san-francisco", "San Francisco"),
            ListingLocation("ca--oakland", "Oakland", ALL_EVENTS_ONLY, 3),
        ),
        max_requests=2,
    )

    candidates = await source.discover_candidates(today=TODAY)

    # The budget ran out on San Francisco: Oakland was never requested, and
    # the run says so instead of looking like a complete small crawl.
    assert requested == [sf_p1, sf_p2]
    assert [c["title"] for c in candidates] == ["Show 1", "Show 2"]
    assert source.last_fetch_error is not None
    assert "ca--oakland/all-events" in source.last_fetch_error


async def test_a_failed_secondary_location_keeps_earlier_cities_and_reports_partial() -> None:
    sf_p1 = f"{BASE}/all-events/?{WINDOW}"
    source, requested = _source(
        {sf_p1: _listing_page([1], page_count=1)},
        listing_slices=(("all-events", None),),
        listing_locations=(
            ListingLocation("ca--san-francisco", "San Francisco"),
            ListingLocation("ca--oakland", "Oakland", ALL_EVENTS_ONLY, 3),
        ),
    )

    payloads = await source.fetch_events(today=TODAY)

    assert requested == [sf_p1, f"{OAKLAND}/all-events/?{WINDOW}"]
    assert [p["title"] for p in payloads] == ["Show 1"]
    assert source.last_fetch_error is not None
    assert "HTTPStatusError" in source.last_fetch_error
