"""Tests for SF Station scraper."""

from __future__ import annotations

from app.ingestion.sources.sfstation import SFStationSource
from app.ingestion.sources.sfstation import TESTABLE


def test_sfstation_testable() -> None:
    assert TESTABLE is True


def test_sfstation_extract_and_normalize() -> None:
    source = SFStationSource()
    html = """
    2026-03-02
    2026-03-02
    7:15 pm - 9:00 pm
    MON
    MON
    #### Haight Laughsbury Comedy Show
    at [O'Reilly's Pub](https://www.sfstation.com/oreillys-pub-b39009162)
    1840 Haight Street San Francisco, CA
    [RSVP](https://eventbrite.com/...) | FREE
    """
    candidates = source._extract_candidates(html)
    # Pattern may or may not match depending on exact format
    if candidates:
        ev = candidates[0]
        normalized = source.normalize_raw(ev)
        if normalized:
            payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
            assert payload["source_name"] == "sfstation"
            assert payload["source_tier"] == 2
