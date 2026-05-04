"""Tests for Luma scraper."""

from __future__ import annotations

from app.ingestion.sources.luma import LumaSource
from app.ingestion.sources.luma import TESTABLE


def test_luma_testable() -> None:
    assert TESTABLE is True


def test_luma_extract_from_html_and_normalize() -> None:
    source = LumaSource()
    html = """
    <a href="https://luma.com/sf-demo-night">SF Demo Night</a>
    By The AI Collective
    San Francisco, California
    +371
    """
    candidates = source._extract_candidates_from_html(html)
    assert len(candidates) >= 1
    ev = next((c for c in candidates if "Demo" in c.get("title", "")), candidates[0])
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "luma"
    assert payload["source_tier"] == 2
