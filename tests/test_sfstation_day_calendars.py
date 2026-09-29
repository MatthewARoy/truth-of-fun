"""SF Station crawl: dated day calendars, followed page by page.

The undated /calendar/bay-area page previews six events per day for five days
(30 events, exactly what the last run stored). The dated page for Sun
2026-09-13 listed 98 events over three rel="next" pages, with Cheaper Than
Therapy on page 2, and /comedy/calendar/09-13-2026 listed the comedy subset.
Blocks below are trimmed from those pages (captured 2026-09-12) and served
through ``httpx.MockTransport``; nothing touches the live site.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.ingestion.sources.sfstation import SFStationSource
from app.services.categories import CANONICAL_CATEGORIES

pytestmark = pytest.mark.anyio

BASE = "https://www.sfstation.com"
DAY = "/calendar/bay-area/09-13-2026"


def _event(title: str, event_id: int, date_iso: str) -> str:
    slug = "-".join(title.lower().split())
    return f"""
<div class="event-wrapper" itemscope itemtype="http://schema.org/Event">
<div class="event-date hidden" itemprop="startDate" content="{date_iso}">{date_iso}</div>
<div class="event-date hidden" itemprop="endDate" content="{date_iso}">{date_iso}</div>
<div class="event-time hidden">7:45pm</div>
<div class="row row-auth ev ">
  <div class="col-xs-12 col-sm-7"><div class="ev_in ev_mobile_c">
    <h4> <a href="/{slug}-e{event_id}"><span itemprop="name">{title}</span></a> </h4>
    <div class="info"><span itemprop="location" itemscope itemtype="http://schema.org/Place"> at
      <span><a href="/shelton-theater-b824"><span itemprop="name">Shelton Theater</span></a></span>
      <span>(7:45pm)</span>
      <span class="address hidden" itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
        <span itemprop="streetAddress">533 Sutter Street</span><br>
      </span>
    </span></div>
  </div></div>
</div>
</div>"""


def _page(path: str, events: list[str], *, next_page: int | None = None) -> str:
    nav = (
        '<ul class="child-calendar-menu">'
        '<li><a href="/calendar/bay-area/09-14-2026">MON</a></li>'
        '<li><a href="/calendar/bay-area/free-events/09-13-2026">FREE EVENTS</a></li>'
        "</ul>"
    )
    pager = ""
    if next_page is not None:
        pager = (
            f'<ul class="pagination"><li><a href="{path}?page={next_page}">{next_page}</a></li>'
            f'<li><a href="{path}?page={next_page}" rel="next" aria-label="Next &raquo;">'
            "&rsaquo;</a></li></ul>"
        )
    return f'<html><body>{nav}<div class="events_cont">{"".join(events)}</div>{pager}</body></html>'


def _source(
    pages: dict[str, str], **overrides: object
) -> tuple[SFStationSource, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url in pages:
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404, text="not found")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = SFStationSource(client=client, max_requests_per_second=1000)
    for name, value in overrides.items():
        setattr(source, name, value)
    return source, requested


def test_every_category_calendar_label_is_canonical() -> None:
    labels = {category for _, category in SFStationSource.category_calendar_paths}
    assert labels <= set(CANONICAL_CATEGORIES)


async def test_walks_each_day_calendar_and_labels_comedy_from_the_comedy_calendar() -> (
    None
):
    next_day = "/calendar/bay-area/09-14-2026"
    comedy = "/comedy/calendar/09-13-2026"
    next_comedy = "/comedy/calendar/09-14-2026"
    therapy = _event("Cheaper Than Therapy Stand-up", 2480621, "2026-09-13")
    source, requested = _source(
        {
            BASE + DAY: _page(
                DAY, [_event("Flower Piano", 1, "2026-09-13")], next_page=2
            ),
            BASE + DAY + "?page=2": _page(DAY, [therapy]),
            BASE + comedy: _page(comedy, [therapy]),
            BASE + next_day: _page(
                next_day, [_event("Haight Laughsbury", 3, "2026-09-14")]
            ),
            BASE + next_comedy: _page(next_comedy, []),
        },
        horizon_days=2,
    )

    candidates = await source.discover_candidates(today=date(2026, 9, 13))

    assert requested == [
        BASE + DAY,
        BASE + DAY + "?page=2",
        BASE + comedy,
        BASE + next_day,
        BASE + next_comedy,
    ]
    assert {c["title"]: c["category_tags"] for c in candidates} == {
        "Flower Piano": [],
        "Cheaper Than Therapy Stand-up": ["Comedy"],
        "Haight Laughsbury": [],
    }
    assert source.last_fetch_error is None


async def test_a_calendar_that_never_ends_stops_at_the_per_day_page_cap() -> None:
    pages = {BASE + DAY: _page(DAY, [_event("Show", 10, "2026-09-13")], next_page=2)}
    for n in range(2, 8):
        pages[f"{BASE}{DAY}?page={n}"] = _page(
            DAY, [_event(f"Show {n}", 10 + n, "2026-09-13")], next_page=n + 1
        )
    source, requested = _source(
        pages, horizon_days=1, category_calendar_paths=(), max_pages_per_day=4
    )

    candidates = await source.discover_candidates(today=date(2026, 9, 13))

    assert requested == [BASE + DAY] + [f"{BASE}{DAY}?page={n}" for n in range(2, 5)]
    assert len(candidates) == 4

    assert source.last_fetch_error is not None
    assert "cap" in source.last_fetch_error.lower()


async def test_a_next_link_off_the_calendar_is_not_followed() -> None:
    html = _page(DAY, [_event("Show", 10, "2026-09-13")]).replace(
        "</body>", '<a href="/calendar/free-events" rel="next">Free</a></body>'
    )
    source, requested = _source(
        {BASE + DAY: html}, horizon_days=1, category_calendar_paths=()
    )

    await source.discover_candidates(today=date(2026, 9, 13))

    assert requested == [BASE + DAY]


async def test_a_full_day_page_is_not_truncated() -> None:
    events = [_event(f"Show {n}", 100 + n, "2026-09-13") for n in range(75)]
    source, _ = _source(
        {BASE + DAY: _page(DAY, events)}, horizon_days=1, category_calendar_paths=()
    )

    candidates = await source.discover_candidates(today=date(2026, 9, 13))

    assert len(candidates) == 75


async def test_the_run_wide_request_budget_caps_every_calendar() -> None:
    source, requested = _source(
        {
            BASE + DAY: _page(DAY, [_event("Show", 1, "2026-09-13")]),
            BASE + "/comedy/calendar/09-13-2026": _page(
                "/comedy/calendar/09-13-2026", []
            ),
            BASE + "/calendar/bay-area/09-14-2026": _page(
                "/calendar/bay-area/09-14-2026", [_event("Other", 2, "2026-09-14")]
            ),
        },
        max_requests=3,
    )

    candidates = await source.discover_candidates(today=date(2026, 9, 13))

    assert len(requested) == 3
    assert len(candidates) == 2


async def test_a_failed_later_page_keeps_earlier_events_and_reports_a_partial_fetch() -> (
    None
):
    source, _ = _source(
        {BASE + DAY: _page(DAY, [_event("Show", 1, "2026-09-13")])}, horizon_days=1
    )

    candidates = await source.discover_candidates(today=date(2026, 9, 13))

    assert [c["title"] for c in candidates] == ["Show"]
    assert source.last_fetch_error is not None
    assert "/comedy/calendar/09-13-2026" in source.last_fetch_error


async def test_a_failed_first_page_raises_so_the_worker_marks_the_source_failing() -> (
    None
):
    source, _ = _source({}, horizon_days=1)

    with pytest.raises(httpx.HTTPStatusError):
        await source.discover_candidates(today=date(2026, 9, 13))
