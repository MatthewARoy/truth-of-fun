"""Tests for SF Station scraper."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion.sources.sfstation import SFStationSource
from app.ingestion.sources.sfstation import TESTABLE

# Trimmed from the live schema.org markup at sfstation.com/calendar/bay-area.
CALENDAR_HTML = """
<ul>
  <li class="main-calendar-nav">
    <a href="/calendar">EVENTS</a>
    <ul class="child-calendar-menu">
      <li><a href="/calendar/06-11-2026">TODAY</a></li>
      <li><a href="/calendar/free-events">FREE EVENTS</a></li>
      <li><a href="https://www.sfstation.com/music/">Music in the Bay Area</a></li>
    </ul>
  </li>
</ul>
<div class="events_cont">
  <div class="event-wrapper" itemscope itemtype="http://schema.org/Event">
<div class="event-date hidden" itemprop="startDate" content="2026-06-11">2026-06-11</div>
<div class="event-date hidden" itemprop="endDate" content="2026-06-11">2026-06-11</div>
<div class="event-time hidden">12:30pm - 1:30pm: Camellia Boutros</div>
<div class="row row-auth ev  multi_ev ">
    <div class="col-xs-12 col-sm-7">
        <div class="ev_in ev_mobile_c">
            <h4>
                <a href="/yerba-buena-gardens-festival-2026-e1024101"><span itemprop="name">Yerba Buena Gardens Festival 2026</span></a>
            </h4>
            <div class="info">
                <span itemprop="location" itemscope itemtype="http://schema.org/Place">
                    at <span><a href="/yerba-buena-gardens-b6842"><span itemprop="name">Yerba Buena Gardens</span></a></span>
                    <span class="hidden" itemprop="url">https://www.sfstation.com/yerba-buena-gardens-b6842</span>
                    <span>(12:30pm - 1:30pm: Camellia Boutros)</span>
                    <span class="address hidden" itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
                        <span itemprop="streetAddress">Yerba Buena Gardens</span><br>
                        <span itemprop="addressLocality">San Francisco</span>,
                        <span itemprop="addressRegion">CA</span>
                    </span>
                </span>
                <br><br>
                <span class="green">FREE</span>
            </div>
        </div>
    </div>
</div>
  </div>
  <div class="event-wrapper" itemscope itemtype="http://schema.org/Event">
<div class="event-date hidden" itemprop="startDate" content="2026-06-11">2026-06-11</div>
<div class="event-date hidden" itemprop="endDate" content="2026-06-11">2026-06-11</div>
<div class="event-time hidden">5pm - 10pm</div>
<div class="row row-auth ev  multi_ev ">
    <div class="col-xs-12 col-sm-7">
        <div class="ev_in ev_mobile_c">
            <h4>
                <a href="/valencia-live-e15770821"><span itemprop="name">Valencia LIVE!</span></a>
            </h4>
            <div class="info">
                <span itemprop="location" itemscope itemtype="http://schema.org/Place">
                    at <span><a href="/valencia-street-b99999"><span itemprop="name">Valencia Street</span></a></span>
                    <span class="address hidden" itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
                        <span itemprop="streetAddress">Valencia Street</span><br>
                        <span itemprop="addressLocality">San Francisco</span>,
                        <span itemprop="addressRegion">CA</span>
                    </span>
                </span>
            </div>
        </div>
    </div>
</div>
  </div>
  <div class="event-wrapper" itemscope itemtype="http://schema.org/Event">
<div class="event-time hidden">8pm - 11pm</div>
<div class="row row-auth ev  multi_ev ">
    <div class="col-xs-12 col-sm-7">
        <div class="ev_in ev_mobile_c">
            <h4>
                <a href="/mystery-show-e7777777"><span itemprop="name">Mystery Show With No Date</span></a>
            </h4>
        </div>
    </div>
</div>
  </div>
</div>
"""


def test_sfstation_testable() -> None:
    assert TESTABLE is True


def test_sfstation_extract_and_normalize() -> None:
    source = SFStationSource()
    candidates = source._extract_candidates(CALENDAR_HTML)
    assert len(candidates) == 2

    ev = candidates[0]
    assert ev["title"] == "Yerba Buena Gardens Festival 2026"
    # Deep link to the event detail page, not the venue page.
    assert ev["source_url"] == (
        "https://www.sfstation.com/yerba-buena-gardens-festival-2026-e1024101"
    )
    assert ev["date_iso"] == "2026-06-11"
    assert ev["venue_name"] == "Yerba Buena Gardens"
    assert ev["address"] == "Yerba Buena Gardens"
    assert ev["price_text"] == "Free"

    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # 12:30pm America/Los_Angeles (PDT) on 2026-06-11 == 19:30 UTC.
    assert normalized.start_time == datetime(2026, 6, 11, 19, 30, tzinfo=timezone.utc)
    assert normalized.offers.is_free is True
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "sfstation"
    assert payload["source_tier"] == 2
    assert "Yerba Buena" in payload["title"]
    # No fabricated tags.
    assert payload["categories"] == []

    second = candidates[1]
    assert second["title"] == "Valencia LIVE!"
    assert second["source_url"] == "https://www.sfstation.com/valencia-live-e15770821"
    assert second["venue_name"] == "Valencia Street"


def test_sfstation_drops_events_without_explicit_date() -> None:
    source = SFStationSource()
    candidates = source._extract_candidates(CALENDAR_HTML)
    titles = {c["title"] for c in candidates}
    # The wrapper without a startDate must be dropped, never given a guessed date.
    assert "Mystery Show With No Date" not in titles
    assert all(c["date_iso"] for c in candidates)


def test_sfstation_ignores_nav_and_venue_links() -> None:
    source = SFStationSource()
    candidates = source._extract_candidates(CALENDAR_HTML)
    titles = {c["title"] for c in candidates}
    assert "Music in the Bay Area" not in titles
    assert "TODAY" not in titles
    for candidate in candidates:
        assert "/calendar" not in candidate["source_url"]
        # Event detail pages use -e<id> slugs; venue pages use -b<id>.
        assert "-e" in candidate["source_url"].rsplit("/", 1)[-1]
