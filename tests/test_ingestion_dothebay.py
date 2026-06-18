"""Tests for DoTheBay scraper.

Fixtures are trimmed snippets of the REAL current dothebay.com/events markup
(captured 2026-06-15): event cards are ``<div class="ds-listing event-card">``
blocks carrying schema.org microdata. Years are pinned explicitly so the
assertions are deterministic regardless of the run date.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ingestion.sources.dothebay import DoTheBaySource
from app.ingestion.sources.dothebay import TESTABLE

# A dated-URL card: permalink carries /events/2026/6/15/, a Free banner, a
# startDate microdata meta, an upvote count of 92, and an attendee count of 7
# (the attendee number must never be mistaken for votes).
CARD_DATED = """
<div class="ds-listing event-card ds-event-category-music" data-permalink="/events/2026/6/15/neal-francis-live-at-lagunitas-tickets" itemprop="event" itemscope itemtype="http://schema.org/Event">
  <ul class="ds-listing-banners">
    <li class="ds-listing-soldout"><span class="ds-icon ds-icon-ticket"></span>
      <span>Free</span>
    </li>
  </ul>
  <a href="/events/2026/6/15/neal-francis-live-at-lagunitas-tickets" itemprop="url" class="ds-listing-event-title url summary">
    <span class="ds-byline">Live at Lagunitas 2026</span>
    <span class="ds-listing-event-title-text" itemprop="name">Neal Francis</span>
  </a>
  <div class="ds-listing-details-container">
    <div class="ds-listing-details">
      <div class="ds-venue-name" itemprop="location" itemscope itemtype="http://schema.org/Place">
        <a href="/venues/lagunitas-brewing-company" itemprop="url"><span itemprop="name">Lagunitas Brewing Company</span></a>
        <span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
          <meta itemprop="streetAddress" content="1280 N. McDowell Boulevard " />
          <meta itemprop="addressLocality" content="Petaluma" />
        </span>
      </div>
      <div class="ds-event-time dtstart">
         4:20PM
         (doors)
      </div>
      <meta itemprop="startDate" datetime="2026-06-15T16:20-0700" content="2026-06-15T16:20-0700"/>
      <meta itemprop="endDate" datetime="2026-06-15T21:00-0700" content="2026-06-15T21:00-0700"/>
    </div>
    <div class="ds-listing-extra-details">
      <div class="ds-listing-attendees">
        <div class="ds-listing-attendee-count"><span class="ds-icon-person ds-icon"></span>7</div>
      </div>
      <div class="ds-listing-actions">
        <div class="ds-btn-container-upvote">
          <a href="#" class="ds-btn stretch ds-btn-large ds-btn-ical" data-ds-id="17383238">
            <span class="ds-upvote-default"><span class="ds-icon ds-icon-arrow-up ds-icon-bg"></span><span class="ds-icon-text">92</span></span>
            <span class="ds-upvote-active"><span class="ds-icon ds-icon-check ds-icon-bg"></span><span class="ds-icon-text">92</span></span>
          </a>
        </div>
      </div>
    </div>
  </div>
</div>
"""

# A weekly card: the permalink (/events/weekly/mon/...) carries NO date, so the
# only date signal is the schema.org startDate meta.
CARD_WEEKLY_WITH_META = """
<div class="ds-listing event-card ds-event-category-music" data-permalink="/events/weekly/mon/bobby-mcferrin-motion-circlesongs-tickets" itemprop="event" itemscope itemtype="http://schema.org/Event">
  <a href="/events/weekly/mon/bobby-mcferrin-motion-circlesongs-tickets" itemprop="url" class="ds-listing-event-title url summary">
    <span class="ds-listing-event-title-text" itemprop="name">Bobby McFerrin Circlesongs</span>
  </a>
  <div class="ds-listing-details-container">
    <div class="ds-listing-details">
      <div class="ds-venue-name" itemprop="location" itemscope itemtype="http://schema.org/Place">
        <a href="/venues/sfjazz-center" itemprop="url"><span itemprop="name">SFJAZZ Center</span></a>
      </div>
      <div class="ds-event-time dtstart">
         8:00PM
      </div>
      <meta itemprop="startDate" datetime="2026-03-28T20:00-0700" content="2026-03-28T20:00-0700"/>
    </div>
  </div>
</div>
"""

# A card with neither a dated URL nor a startDate meta: it must be dropped, not
# stamped with "today".
CARD_UNDATED = """
<div class="ds-listing event-card ds-event-category-recreation" data-permalink="/events/weekly/trivia-night" itemprop="event" itemscope itemtype="http://schema.org/Event">
  <a href="/events/weekly/trivia-night" itemprop="url" class="ds-listing-event-title url summary">
    <span class="ds-listing-event-title-text" itemprop="name">Weekly Trivia Night</span>
  </a>
  <div class="ds-listing-details-container">
    <div class="ds-listing-details">
      <div class="ds-venue-name" itemprop="location" itemscope itemtype="http://schema.org/Place">
        <a href="/venues/some-bar" itemprop="url"><span itemprop="name">Some Bar</span></a>
      </div>
      <div class="ds-event-time dtstart">
         7:00PM
      </div>
    </div>
  </div>
</div>
"""


def test_dothebay_testable() -> None:
    assert TESTABLE is True


def test_dothebay_extract_and_normalize() -> None:
    source = DoTheBaySource()
    candidates = source._extract_candidates(CARD_DATED)
    assert len(candidates) >= 1
    ev = next((c for c in candidates if "Neal Francis" in c.get("title", "")), None)
    assert ev is not None
    # Relative permalink must be resolved to an absolute dothebay.com URL.
    assert ev["source_url"] == (
        "https://dothebay.com/events/2026/6/15/neal-francis-live-at-lagunitas-tickets"
    )
    assert ev["venue_name"] == "Lagunitas Brewing Company"

    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # Date comes from the schema.org startDate meta (and matches the URL date),
    # never defaults to today: 4:20PM PDT on 2026-06-15 = 23:20 UTC.
    assert normalized.start_time == datetime(2026, 6, 15, 23, 20, tzinfo=timezone.utc)
    # Free banner is honored.
    assert normalized.offers.is_free is True
    # Upvotes (92) are the vote count; the attendee count (7) is NOT votes.
    assert normalized.social_signals.vote_count == 92
    assert normalized.social_signals.popularity_score == pytest.approx(0.92)

    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "dothebay"
    assert payload["source_tier"] == 2
    assert "Neal Francis" in payload["title"]


def test_dothebay_date_from_url() -> None:
    """When a card has no startDate meta, the dated URL still supplies the date."""
    source = DoTheBaySource()
    # Strip the startDate meta to force the URL-date path.
    html = CARD_DATED.replace(
        '<meta itemprop="startDate" datetime="2026-06-15T16:20-0700" content="2026-06-15T16:20-0700"/>',
        "",
    )
    candidates = source._extract_candidates(html)
    ev = next((c for c in candidates if "Neal Francis" in c.get("title", "")), None)
    assert ev is not None
    assert ev["date_text"] == "2026-06-15"
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # 4:20PM PDT on 2026-06-15 = 23:20 UTC.
    assert normalized.start_time == datetime(2026, 6, 15, 23, 20, tzinfo=timezone.utc)


def test_dothebay_undated_event_dropped() -> None:
    """Cards with no extractable date must be dropped, never dated 'today'."""
    source = DoTheBaySource()
    candidates = source._extract_candidates(CARD_UNDATED)
    ev = next((c for c in candidates if "Trivia" in c.get("title", "")), None)
    assert ev is not None
    assert ev["date_text"] is None
    assert source.normalize_raw(ev) is None


def test_dothebay_meta_startdate_parsed() -> None:
    """schema.org startDate meta supplies the date for undated (weekly) URLs."""
    source = DoTheBaySource()
    candidates = source._extract_candidates(CARD_WEEKLY_WITH_META)
    ev = next((c for c in candidates if "Bobby" in c.get("title", "")), None)
    assert ev is not None
    assert ev["date_text"] == "2026-03-28"
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # 8:00PM PDT on 2026-03-28 = 3:00AM UTC on 2026-03-29.
    assert normalized.start_time == datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc)


def test_dothebay_multiple_cards() -> None:
    """The listing splits into one candidate per event-card div."""
    source = DoTheBaySource()
    html = CARD_DATED + CARD_WEEKLY_WITH_META + CARD_UNDATED
    candidates = source._extract_candidates(html)
    titles = {c["title"] for c in candidates}
    assert {"Neal Francis", "Bobby McFerrin Circlesongs", "Weekly Trivia Night"} <= titles
    assert len(candidates) == 3


def test_dothebay_vote_extraction_only_when_labeled() -> None:
    """Vote counts come only from clearly vote-labeled markup, never stray digits."""
    source = DoTheBaySource()
    upvote = (
        '<div class="ds-btn-container-upvote"><a href="#">'
        '<span class="ds-upvote-default"><span class="ds-icon-text">42</span></span>'
        "</a></div>"
    )
    assert source._extract_vote_from_context(upvote) == 42
    assert source._extract_vote_from_context("42 votes") == 42
    # Attendee counts, times, day-of-month, and address numbers are not votes.
    attendee_only = (
        '<div class="ds-listing-attendee-count">'
        '<span class="ds-icon-person ds-icon"></span>7</div>'
    )
    assert source._extract_vote_from_context(attendee_only) is None
    assert source._extract_vote_from_context("8:00PM 2 15 123 Main St") is None
