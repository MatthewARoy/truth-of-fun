"""FuncheapSF crawl: day indexes, their /page/N/ pages, and the JSON-LD they embed.

Each dated index (sf.funcheap.com/2026/09/13/) is paginated with rel="next"
and embeds its events as a JSON-LD array carrying the title, start and end
with an offset, venue, address, price and eventStatus: everything the
per-event detail scrape collects. Fixtures are trimmed from the index for
Sun 2026-09-13 (captured 2026-09-12). Playwright is replaced by a fake page.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.ingestion.sources.funcheap_sf import FuncheapSFSource

pytestmark = pytest.mark.anyio

DAY = "https://sf.funcheap.com/2026/09/13/"
NEXT_DAY = "https://sf.funcheap.com/2026/09/14/"

# Trimmed from the live index: HTML entities inside the JSON strings and
# escaped slashes are how the site serves it.
LIVE_INDEX_JSONLD = (
    '<script type="application/ld+json">[{"@context":"http:\\/\\/schema.org","@type":"Event",'
    '"name":"&#8220;HellaSecret&#8221; Speakeasy Comedy Show &#038; Cocktail Night (Oakland)",'
    '"description":"Secret pop-up comedy show at a new bar in Temescal in Oakland ...",'
    '"startDate":"2026-09-13T18:00:00-07:00","endDate":"2026-09-13T19:30:00-07:00",'
    '"url":"https:\\/\\/sf.funcheap.com\\/hellasecret-speakeasy-comedy-show-cocktail-night-oakland-34\\/",'
    '"eventStatus":"https:\\/\\/schema.org\\/EventScheduled",'
    '"location":{"@type":"Place","name":"Mesa Maguey","address":"4031 Broadway, Oakland, CA"},'
    '"offers":{"price":0}}]</script>'
)


def _ld_event(
    slug: str,
    *,
    start: str,
    end: str | None = None,
    price: Any = 0,
    status: str = "EventScheduled",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "@context": "http://schema.org",
        "@type": "Event",
        "name": slug.replace("-", " ").title(),
        "startDate": start,
        "url": f"https://sf.funcheap.com/{slug}/",
        "eventStatus": f"https://schema.org/{status}",
        "location": {
            "@type": "Place",
            "name": "The Function SF",
            "address": "1414 Market St, San Francisco, CA",
        },
        "offers": {"price": price},
    }
    if end:
        item["endDate"] = end
    return item


def _index_page(
    day_url: str,
    items: list[dict[str, Any]],
    *,
    next_url: str | None = None,
    links: tuple[str, ...] = (),
) -> str:
    head = (
        '<script type="application/ld+json" class="yoast-schema-graph">'
        '{"@context":"https://schema.org","@graph":[{"@type":"CollectionPage"}]}</script>'
    )
    if next_url:
        head += f'<link rel="next" href="{next_url}" />'
    events = (
        f'<script type="application/ld+json">{json.dumps(items)}</script>'
        if items
        else ""
    )
    anchors = "".join(f'<a href="{href}">listing</a>' for href in links)
    return f"<html><head>{head}</head><body>{anchors}{events}</body></html>"


class _FakePage:
    """The slice of Playwright's Page that the index crawl uses."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self._current: str | None = None
        self.visited: list[str] = []

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.visited.append(url)
        if url not in self._pages:
            raise PlaywrightTimeoutError(
                f"Timeout 30000ms exceeded navigating to {url}"
            )
        self._current = url

    async def wait_for_selector(self, selector: str, **kwargs: Any) -> None:
        return None

    async def content(self) -> str:
        assert self._current is not None
        return self._pages[self._current]


async def _crawl(page: _FakePage, **overrides: Any) -> list[dict[str, Any]]:
    options: dict[str, Any] = {
        "horizon_days": 1,
        "max_index_pages_per_day": 3,
        "max_events": 1000,
        "max_detail_pages": 100,
        "today": date(2026, 9, 13),
    }
    options.update(overrides)
    source = FuncheapSFSource(proxy=None, page_delay_seconds=0)
    return await source._crawl_day_indexes(page, **options)


def test_index_jsonld_maps_to_an_event_payload() -> None:
    source = FuncheapSFSource(proxy=None)

    [payload] = source._events_from_index_html(
        f"<html><body>{LIVE_INDEX_JSONLD}</body></html>"
    )

    assert (
        payload["title"]
        == "“HellaSecret” Speakeasy Comedy Show & Cocktail Night (Oakland)"
    )
    assert payload["external_url"] == (
        "https://sf.funcheap.com/hellasecret-speakeasy-comedy-show-cocktail-night-oakland-34/"
    )
    assert (
        payload["source_event_id"]
        == "hellasecret-speakeasy-comedy-show-cocktail-night-oakland-34"
    )
    # 6:00pm PDT is 01:00 UTC the next day, and the published end is kept.
    assert payload["start_at"] == datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    assert payload["end_at"] == datetime(2026, 9, 14, 2, 30, tzinfo=timezone.utc)
    assert payload["start_time_is_estimated"] is False
    assert payload["venue_name"] == "Mesa Maguey"
    assert payload["raw_address"] == "4031 Broadway, Oakland, CA"
    assert (payload["price"], payload["currency"], payload["is_free"]) == (
        0.0,
        "USD",
        True,
    )
    assert payload["status"] == "scheduled"
    assert (payload["source_name"], payload["source_tier"]) == ("funcheap_sf", 2)


def test_index_jsonld_prices_statuses_and_dates() -> None:
    source = FuncheapSFSource(proxy=None)
    not_an_event = _ld_event("day-index", start="2026-09-13T12:00:00-07:00")
    not_an_event["url"] = DAY
    items = [
        _ld_event("priced-show", start="2026-09-13T19:30:00-07:00", price="15"),
        _ld_event(
            "postponed-show", start="2026-09-13T20:00:00-07:00", status="EventPostponed"
        ),
        _ld_event(
            "cancelled-show", start="2026-09-13T20:00:00-07:00", status="EventCancelled"
        ),
        _ld_event("all-day-fair", start="2026-09-13"),
        _ld_event("undated-listing", start=""),
        not_an_event,
    ]

    payloads = {
        p["source_event_id"]: p
        for p in source._events_from_index_html(_index_page(DAY, items))
    }

    assert set(payloads) == {
        "priced-show",
        "postponed-show",
        "cancelled-show",
        "all-day-fair",
    }
    assert (payloads["priced-show"]["price"], payloads["priced-show"]["is_free"]) == (
        15.0,
        False,
    )
    assert payloads["postponed-show"]["status"] == "postponed"
    assert payloads["cancelled-show"]["status"] == "cancelled"
    # A bare date is a real date with no published time: kept, and flagged.
    assert payloads["all-day-fair"]["start_at"] == datetime(
        2026, 9, 13, 7, 0, tzinfo=timezone.utc
    )
    assert payloads["all-day-fair"]["start_time_is_estimated"] is True


async def test_crawl_follows_each_days_pages_across_the_horizon() -> None:
    comedy = _ld_event(
        "free-sunday-comedy-night-in-downtown-sf-15", start="2026-09-13T19:00:00-07:00"
    )
    page = _FakePage(
        {
            DAY: _index_page(
                DAY,
                [_ld_event("flower-piano", start="2026-09-13T10:00:00-07:00"), comedy],
                next_url=f"{DAY}page/2/",
            ),
            # Multi-day listings repeat across a day's pages; they are kept once.
            f"{DAY}page/2/": _index_page(
                DAY,
                [comedy, _ld_event("whales-tail", start="2026-09-13T12:00:00-07:00")],
            ),
            NEXT_DAY: _index_page(
                NEXT_DAY,
                [_ld_event("monday-trivia", start="2026-09-14T19:00:00-07:00")],
            ),
        }
    )

    payloads = await _crawl(page, horizon_days=2)

    assert page.visited == [DAY, f"{DAY}page/2/", NEXT_DAY]
    assert [p["source_event_id"] for p in payloads] == [
        "flower-piano",
        "free-sunday-comedy-night-in-downtown-sf-15",
        "whales-tail",
        "monday-trivia",
    ]


async def test_index_pagination_stops_at_the_per_day_cap() -> None:
    pages = {
        DAY: _index_page(
            DAY,
            [_ld_event("event-1", start="2026-09-13T10:00:00-07:00")],
            next_url=f"{DAY}page/2/",
        )
    }
    for n in range(2, 7):
        pages[f"{DAY}page/{n}/"] = _index_page(
            DAY,
            [_ld_event(f"event-{n}", start="2026-09-13T10:00:00-07:00")],
            next_url=f"{DAY}page/{n + 1}/",
        )
    page = _FakePage(pages)

    payloads = await _crawl(page, max_index_pages_per_day=3)

    assert page.visited == [DAY, f"{DAY}page/2/", f"{DAY}page/3/"]
    assert len(payloads) == 3


async def test_a_next_link_to_another_day_is_not_followed_as_a_page() -> None:
    page = _FakePage(
        {
            DAY: _index_page(
                DAY,
                [_ld_event("event-1", start="2026-09-13T10:00:00-07:00")],
                next_url=NEXT_DAY,
            )
        }
    )

    await _crawl(page)

    assert page.visited == [DAY]


async def test_a_day_that_fails_to_load_does_not_sink_the_horizon() -> None:
    page = _FakePage(
        {
            NEXT_DAY: _index_page(
                NEXT_DAY,
                [_ld_event("monday-trivia", start="2026-09-14T19:00:00-07:00")],
            )
        }
    )

    payloads = await _crawl(page, horizon_days=2)

    assert page.visited == [DAY, NEXT_DAY]
    assert [p["source_event_id"] for p in payloads] == ["monday-trivia"]


async def test_an_index_without_jsonld_falls_back_to_detail_pages(monkeypatch) -> None:
    page = _FakePage(
        {
            DAY: _index_page(
                DAY,
                [],
                links=(
                    "https://sf.funcheap.com/free-sunday-comedy-night-in-downtown-sf-15/",
                    "https://sf.funcheap.com/2026/09/14/",
                    "https://sf.funcheap.com/events/",
                    "https://sf.funcheap.com/whales-tail/",
                ),
            )
        }
    )
    source = FuncheapSFSource(proxy=None, page_delay_seconds=0)
    scraped: list[str] = []

    async def fake_detail(page_obj: Any, url: str) -> dict[str, Any]:
        scraped.append(url)
        return {"external_url": url, "title": url}

    monkeypatch.setattr(source, "_scrape_event_detail", fake_detail)

    payloads = await source._crawl_day_indexes(
        page,
        horizon_days=1,
        max_index_pages_per_day=3,
        max_events=1000,
        max_detail_pages=1,
        today=date(2026, 9, 13),
    )

    # Day indexes and nav pages are not events, and the detail budget holds.
    assert scraped == [
        "https://sf.funcheap.com/free-sunday-comedy-night-in-downtown-sf-15/"
    ]
    assert len(payloads) == 1


# Live, 2026-09-12: /2026/09/13/page/3/ said this, carried no event JSON-LD, and
# still linked rel="next" to /page/4/. Its only event links were the sidebar's.
NOTHING_LISTED = (
    "<p>Sorry, we don't have any Funcheap events listed for this day yet</p>"
)
SIDEBAR_LINK = (
    "https://sf.funcheap.com/sfs-chinatown-autumn-moon-festival-2026-sept-19-20/"
)


def _nothing_listed_page(day_url: str, *, next_url: str | None = None) -> str:
    return _index_page(day_url, [], next_url=next_url, links=(SIDEBAR_LINK,)).replace(
        "<body>", f"<body>{NOTHING_LISTED}"
    )


def _recording_detail_scraper(source: FuncheapSFSource, monkeypatch) -> list[str]:
    scraped: list[str] = []

    async def fake_detail(page_obj: Any, url: str) -> dict[str, Any]:
        scraped.append(url)
        return {"external_url": url, "title": url}

    monkeypatch.setattr(source, "_scrape_event_detail", fake_detail)
    return scraped


async def test_an_empty_page_past_the_last_ends_the_day_without_fallback(
    monkeypatch,
) -> None:
    page = _FakePage(
        {
            DAY: _index_page(
                DAY,
                [_ld_event("event-1", start="2026-09-13T10:00:00-07:00")],
                next_url=f"{DAY}page/2/",
            ),
            f"{DAY}page/2/": _nothing_listed_page(DAY, next_url=f"{DAY}page/3/"),
            NEXT_DAY: _index_page(
                NEXT_DAY,
                [_ld_event("monday-trivia", start="2026-09-14T19:00:00-07:00")],
            ),
        }
    )
    source = FuncheapSFSource(proxy=None, page_delay_seconds=0)
    scraped = _recording_detail_scraper(source, monkeypatch)

    payloads = await source._crawl_day_indexes(
        page,
        horizon_days=2,
        max_index_pages_per_day=3,
        max_events=1000,
        max_detail_pages=100,
        today=date(2026, 9, 13),
    )

    assert page.visited == [DAY, f"{DAY}page/2/", NEXT_DAY]
    assert scraped == []
    assert [p["source_event_id"] for p in payloads] == ["event-1", "monday-trivia"]


async def test_a_day_with_nothing_listed_is_not_a_template_change(monkeypatch) -> None:
    page = _FakePage({DAY: _nothing_listed_page(DAY)})
    source = FuncheapSFSource(proxy=None, page_delay_seconds=0)
    scraped = _recording_detail_scraper(source, monkeypatch)

    payloads = await source._crawl_day_indexes(
        page,
        horizon_days=1,
        max_index_pages_per_day=3,
        max_events=1000,
        max_detail_pages=100,
        today=date(2026, 9, 13),
    )

    assert scraped == []
    assert payloads == []
