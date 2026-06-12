"""Tests for Luma scraper."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion.sources.luma import LumaSource
from app.ingestion.sources.luma import TESTABLE


def test_luma_testable() -> None:
    assert TESTABLE is True


def test_luma_extracts_events_from_embedded_next_data() -> None:
    """Spec prefers structured payloads: events in __NEXT_DATA__ carry real start times."""
    source = LumaSource()
    html = """
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"events":[
      {"name":"SF Demo Night","start_at":"2026-06-12T01:30:00.000Z",
       "url":"https://luma.com/sf-demo-night",
       "geo_address_info":{"full_address":"995 Market St, San Francisco, CA"},
       "guest_count":371},
      {"name":"AI Builders Breakfast","start_at":"2026-06-12T15:00:00.000Z",
       "url":"https://luma.com/ai-builders-breakfast",
       "guest_count":42}
    ]}}}
    </script>
    </body></html>
    """
    candidates = source._extract_candidates_from_html(html)
    assert len(candidates) == 2

    normalized = [source.normalize_raw(c) for c in candidates]
    assert all(event is not None for event in normalized)
    by_title = {event.title: event for event in normalized}
    demo = by_title["SF Demo Night"]
    assert demo.start_time == datetime(2026, 6, 12, 1, 30, tzinfo=timezone.utc)
    assert demo.social_signals.attendee_count == 371
    assert str(demo.source.source_url) == "https://luma.com/sf-demo-night"


def test_luma_anchor_fallback_uses_date_from_context() -> None:
    """Without structured data, a date visible near the event link must be used."""
    source = LumaSource()
    html = """
    <h2>Thursday, June 11, 2026</h2>
    <a href="https://luma.com/sf-demo-night">SF Demo Night</a>
    6:00 PM
    By The AI Collective
    San Francisco, California
    +371
    """
    candidates = source._extract_candidates_from_html(html)
    assert len(candidates) >= 1
    ev = next((c for c in candidates if "Demo" in c.get("title", "")), candidates[0])
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    # June 11 2026 6:00 PM PDT == 2026-06-12 01:00 UTC
    assert normalized.start_time == datetime(2026, 6, 12, 1, 0, tzinfo=timezone.utc)
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "luma"
    assert payload["source_tier"] == 2


def test_luma_drops_events_without_an_extractable_date() -> None:
    """Events whose date cannot be determined must be dropped, never fabricated."""
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
    assert source.normalize_raw(ev) is None
