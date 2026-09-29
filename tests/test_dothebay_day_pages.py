"""DoTheBay crawl: dated day pages, followed page by page.

/events shows today only. Dated pages (/events/2026/9/13) list each day at
25 cards a page, paginated with ``rel="next"`` (class ds-next-page), and every
card names DoTheBay's own category in its class (ds-event-category-music).
Cards below keep that live markup (captured 2026-09-12) and are served through
``httpx.MockTransport``; nothing touches the live site.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.ingestion.sources.dothebay import DoTheBaySource
from app.services.categories import CANONICAL_CATEGORIES

pytestmark = pytest.mark.anyio

BASE = "https://dothebay.com"


def _card(title: str, permalink: str, *, category: str, start: str) -> str:
    return f"""
<div class="ds-listing event-card ds-event-category-{category}" data-ds-ga-label="day" data-permalink="{permalink}" itemprop="event" itemscope itemtype="http://schema.org/Event">
  <a href="{permalink}" itemprop="url" class="ds-listing-event-title url summary">
    <span class="ds-byline"></span>
    <span class="ds-listing-event-title-text" itemprop="name">{title}</span>
  </a>
  <div class="ds-listing-details-container"><div class="ds-listing-details">
    <div class="ds-venue-name" itemprop="location" itemscope itemtype="http://schema.org/Place">
      <a href="/venues/bottom-of-the-hill" itemprop="url"><span itemprop="name">Bottom Of The Hill</span></a>
      <span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
        <meta itemprop="streetAddress" content="1233 17th Street" />
      </span>
    </div>
    <div class="ds-event-time dtstart">8:00PM</div>
    <meta itemprop="startDate" datetime="{start}" content="{start}"/>
  </div></div>
</div>"""


def _page(day_path: str, cards: list[str], *, next_page: int | None = None) -> str:
    pager = ""
    if next_page is not None:
        pager = (
            f'<a href="{day_path}?page={next_page}" class="ds-next-page" rel="next" '
            f'data-traditional="true" data-ds-ga-action="updates" '
            f'data-ds-ga-label="page {next_page}">Next</a>'
        )
    return f'<html><body><div class="ds-events-group">{"".join(cards)}</div>{pager}</body></html>'


def _source(
    pages: dict[str, str], **overrides: object
) -> tuple[DoTheBaySource, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url in pages:
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404, text="not found")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = DoTheBaySource(client=client, max_requests_per_second=1000)
    for name, value in overrides.items():
        setattr(source, name, value)
    return source, requested


def test_every_card_category_maps_to_a_canonical_category() -> None:
    assert set(DoTheBaySource.CARD_CATEGORIES.values()) <= set(CANONICAL_CATEGORIES)


async def test_walks_each_day_and_its_pages_merging_repeated_cards() -> None:
    last_of_month = "/events/2026/9/30"
    first_of_month = "/events/2026/10/1"
    ongoing = _card(
        "Flower Piano",
        "/events/2026/9/10/flower-piano-tickets",
        category="music",
        start="2026-09-10",
    )
    source, requested = _source(
        {
            BASE + last_of_month: _page(
                last_of_month,
                [
                    ongoing,
                    _card(
                        "Punch Line Showcase",
                        "/events/2026/9/30/showcase-tickets",
                        category="comedy",
                        start="2026-09-30",
                    ),
                ],
                next_page=2,
            ),
            BASE + last_of_month + "?page=2": _page(
                last_of_month,
                [
                    _card(
                        "Salsa Night",
                        "/events/2026/9/30/salsa-tickets",
                        category="dance",
                        start="2026-09-30",
                    )
                ],
            ),
            BASE + first_of_month: _page(
                first_of_month,
                [
                    ongoing,
                    _card(
                        "Film Club",
                        "/events/2026/10/1/film-club-tickets",
                        category="film",
                        start="2026-10-01",
                    ),
                ],
            ),
        },
        horizon_days=2,
    )

    candidates = await source.discover_candidates(today=date(2026, 9, 30))

    # Day paths are unpadded, and the crawl rolls over the month.
    assert requested == [
        BASE + last_of_month,
        BASE + last_of_month + "?page=2",
        BASE + first_of_month,
    ]
    assert {c["title"]: c["category_tags"] for c in candidates} == {
        "Flower Piano": ["Music"],
        "Punch Line Showcase": ["Comedy"],
        # DoTheBay's "dance" has no clear canonical home, so none is guessed.
        "Salsa Night": [],
        "Film Club": ["Film"],
    }
    assert source.last_fetch_error is None


async def test_a_day_that_never_ends_stops_at_the_per_day_page_cap() -> None:
    day = "/events/2026/9/13"
    pages = {}
    for n in range(1, 7):
        url = BASE + day + ("" if n == 1 else f"?page={n}")
        pages[url] = _page(
            day,
            [
                _card(
                    f"Show {n}",
                    f"/events/2026/9/13/show-{n}-tickets",
                    category="music",
                    start="2026-09-13",
                )
            ],
            next_page=n + 1,
        )
    source, requested = _source(pages, horizon_days=1, max_pages_per_day=3)

    candidates = await source.discover_candidates(today=date(2026, 9, 13))

    assert requested == [BASE + day, BASE + day + "?page=2", BASE + day + "?page=3"]
    assert len(candidates) == 3

    assert source.last_fetch_error is not None
    assert "cap" in source.last_fetch_error.lower()


async def test_a_next_link_to_another_day_is_not_followed() -> None:
    day = "/events/2026/9/13"
    html = _page(
        day,
        [
            _card(
                "Show",
                "/events/2026/9/13/show-tickets",
                category="music",
                start="2026-09-13",
            )
        ],
    ).replace(
        "</body>", '<a href="/events/2026/9/14?page=2" rel="next">Next</a></body>'
    )
    source, requested = _source({BASE + day: html}, horizon_days=1)

    await source.discover_candidates(today=date(2026, 9, 13))

    assert requested == [BASE + day]


async def test_a_failed_later_day_keeps_earlier_events_and_reports_a_partial_fetch() -> (
    None
):
    day = "/events/2026/9/13"
    source, _ = _source(
        {
            BASE + day: _page(
                day,
                [
                    _card(
                        "Show",
                        "/events/2026/9/13/show-tickets",
                        category="music",
                        start="2026-09-13",
                    )
                ],
            )
        },
        horizon_days=2,
    )

    candidates = await source.discover_candidates(today=date(2026, 9, 13))

    assert [c["title"] for c in candidates] == ["Show"]
    assert source.last_fetch_error is not None
    assert "/events/2026/9/14" in source.last_fetch_error
