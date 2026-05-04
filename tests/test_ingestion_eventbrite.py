from __future__ import annotations

from app.ingestion.sources.eventbrite import EventbriteSource


def test_eventbrite_extract_candidates_and_normalize() -> None:
    source = EventbriteSource()
    html = """
    <div class="search-event-card-wrapper">
      <a href="https://www.eventbrite.com/e/sf-ai-night-123"
         aria-label="SF AI Night">
         Sat, Jan 17, 7:00 PM | San Francisco, CA | Starts at $20
      </a>
    </div>
    """
    candidates = source._extract_listing_candidates(html)
    assert len(candidates) == 1

    event = source.normalize_raw(candidates[0])
    assert event is not None
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "eventbrite"
    assert payload["source_tier"] == 1
    assert payload["title"] == "SF AI Night"
    assert payload["external_url"] == "https://www.eventbrite.com/e/sf-ai-night-123"
    assert payload["price"] == 20.0
