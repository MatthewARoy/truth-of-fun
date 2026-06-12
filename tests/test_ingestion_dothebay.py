"""Tests for DoTheBay scraper."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ingestion.sources.dothebay import DoTheBaySource
from app.ingestion.sources.dothebay import TESTABLE


def test_dothebay_testable() -> None:
    assert TESTABLE is True


def test_dothebay_extract_and_normalize() -> None:
    source = DoTheBaySource()
    html = """
    <a href="https://dothebay.com/events/2026/3/2/junny-null-tour-tickets">MRG Live Presents: Junny Tour</a>
    <a href="https://dothebay.com/venues/the-independent">The Independent</a>
    8:00PM
    2
    15
    """
    candidates = source._extract_candidates(html)
    assert len(candidates) >= 1
    ev = next((c for c in candidates if "Junny" in c.get("title", "")), None)
    assert ev is not None
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # Date must come from the URL (/events/2026/3/2/), never default to today:
    # 8:00PM PST on 2026-03-02 = 4:00AM UTC on 2026-03-03
    assert normalized.start_time == datetime(2026, 3, 3, 4, 0, tzinfo=timezone.utc)
    # Stray digits ("2", "15", the 8 in "8:00PM") must not be reported as votes
    assert normalized.social_signals.vote_count == 0
    assert normalized.social_signals.popularity_score == 0.0
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "dothebay"
    assert payload["source_tier"] == 2
    assert "Junny" in payload["title"]


def test_dothebay_undated_event_dropped() -> None:
    """Cards with no extractable date must be dropped, never dated 'today'."""
    source = DoTheBaySource()
    html = """
    <a href="https://dothebay.com/events/weekly/trivia-night">Weekly Trivia Night</a>
    <a href="https://dothebay.com/venues/some-bar">Some Bar</a>
    7:00PM
    """
    candidates = source._extract_candidates(html)
    ev = next((c for c in candidates if "Trivia" in c.get("title", "")), None)
    assert ev is not None
    assert ev["date_text"] is None
    assert source.normalize_raw(ev) is None


def test_dothebay_through_date_parsed() -> None:
    """'Through Mon DD, YYYY' context still dates ongoing events."""
    source = DoTheBaySource()
    html = """
    <a href="https://dothebay.com/events/weekly/immersive-exhibit">Immersive Exhibit</a>
    Through Mar 28, 2026
    """
    candidates = source._extract_candidates(html)
    ev = next((c for c in candidates if "Immersive" in c.get("title", "")), None)
    assert ev is not None
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # Mar 28, 2026 at the 7pm default, PDT (UTC-7) = 2:00AM UTC on 2026-03-29
    assert normalized.start_time == datetime(2026, 3, 29, 2, 0, tzinfo=timezone.utc)


def test_dothebay_meta_startdate_parsed() -> None:
    """schema.org startDate attribute in the card supplies the date for undated URLs."""
    source = DoTheBaySource()
    html = """
    <a href="https://dothebay.com/events/weekly/jazz-series">Jazz Series</a>
    <meta itemprop="startDate" content="2026-03-28T20:00:00-08:00">
    8:00PM
    """
    candidates = source._extract_candidates(html)
    ev = next((c for c in candidates if "Jazz" in c.get("title", "")), None)
    assert ev is not None
    assert ev["date_text"] == "2026-03-28"
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # 8:00PM PDT on 2026-03-28 = 3:00AM UTC on 2026-03-29
    assert normalized.start_time == datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc)


def test_dothebay_vote_extraction_only_when_labeled() -> None:
    """Vote counts come only from clearly vote-labeled markup, never stray digits."""
    source = DoTheBaySource()
    assert source._extract_vote_from_context('<span class="ds-vote-count">42</span>') == 42
    assert source._extract_vote_from_context("42 votes") == 42
    # Times, day-of-month, and address numbers are not votes
    assert source._extract_vote_from_context("8:00PM 2 15 123 Main St") is None
