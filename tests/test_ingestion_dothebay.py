"""Tests for DoTheBay scraper."""

from __future__ import annotations

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
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "dothebay"
    assert payload["source_tier"] == 2
    assert "Junny" in payload["title"]
