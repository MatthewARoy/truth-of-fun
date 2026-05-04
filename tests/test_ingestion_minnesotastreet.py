"""Tests for Minnesota Street Project scraper."""

from __future__ import annotations

from app.ingestion.sources.minnesotastreet import EVENT_KIND_EXHIBITION
from app.ingestion.sources.minnesotastreet import EVENT_KIND_RECEPTION
from app.ingestion.sources.minnesotastreet import MinnesotaStreetSource
from app.ingestion.sources.minnesotastreet import TESTABLE


def test_minnesotastreet_testable() -> None:
    assert TESTABLE is True


def test_minnesotastreet_exhibition_extract_and_normalize() -> None:
    source = MinnesotaStreetSource()
    html = """
    ### Dialogues 2026
    Feb 14–Mar 28, 2026
    1275 Minnesota St / SFArtsED
    """
    candidates = source._extract_candidates(html, event_kind=EVENT_KIND_EXHIBITION)
    assert len(candidates) >= 1
    ev = candidates[0]
    assert ev["title"] == "Dialogues 2026"
    assert ev["event_kind"] == EVENT_KIND_EXHIBITION
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    payload = normalized.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "minnesotastreet"
    assert "exhibition_window" in normalized.category_tags


def test_minnesotastreet_reception_extract_and_normalize() -> None:
    source = MinnesotaStreetSource()
    html = """
    ### Opening Reception: No Coward Soul
    Sat, Mar 14, 5PM-7PM
    1275 Minnesota St
    Hashimoto Contemporary
    """
    candidates = source._extract_candidates(html, event_kind=EVENT_KIND_RECEPTION)
    assert len(candidates) >= 1
    ev = candidates[0]
    assert "No Coward Soul" in ev.get("title", "")
    assert ev["event_kind"] == EVENT_KIND_RECEPTION
    normalized = source.normalize_raw(ev)
    assert normalized is not None
    assert "opening_reception" in normalized.category_tags
