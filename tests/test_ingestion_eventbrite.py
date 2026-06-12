from __future__ import annotations

from app.ingestion.sources.eventbrite import EventbriteSource


def test_eventbrite_extract_candidates_and_normalize() -> None:
    source = EventbriteSource()
    html = """
    <div class="search-event-card-wrapper">
      <a href="https://www.eventbrite.com/e/sf-ai-night-123"
         aria-label="SF AI Night">
         Sat, Jan 17, 2026, 7:00 PM | San Francisco, CA | Starts at $20 | By SF AI Collective
      </a>
    </div>
    """
    candidates = source._extract_listing_candidates(html)
    assert len(candidates) == 1
    assert candidates[0]["organizer_name"] == "SF AI Collective"

    event = source.normalize_raw(candidates[0])
    assert event is not None
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "eventbrite"
    assert payload["source_tier"] == 1
    assert payload["title"] == "SF AI Night"
    assert payload["external_url"] == "https://www.eventbrite.com/e/sf-ai-night-123"
    assert payload["price"] == 20.0
    assert payload["start_at"].year == 2026
    # Organizer captured per the source spec.
    assert event.organizer.name == "SF AI Collective"
    # No fabricated blanket tags - only data actually on the page.
    assert payload["categories"] == []


def test_eventbrite_no_organizer_on_card() -> None:
    source = EventbriteSource()
    html = """
    <a href="https://www.eventbrite.com/e/quiet-show-456"
       aria-label="Quiet Show">
       Sun, Feb 8, 2026, 6:00 PM | San Francisco, CA | Free
    </a>
    """
    candidates = source._extract_listing_candidates(html)
    assert len(candidates) == 1

    event = source.normalize_raw(candidates[0])
    assert event is not None
    # Organizer absent from the card => left empty, never invented.
    assert event.organizer.name is None
    assert event.category_tags == []


def test_eventbrite_skips_non_event_links() -> None:
    source = EventbriteSource()
    html = """
    <a href="https://www.eventbrite.com/signin/">Sign in</a>
    <a href="https://www.eventbrite.com/help/en-us/">Help Center</a>
    <a href="/d/ca--san-francisco/music--events/">Music events</a>
    """
    candidates = source._extract_listing_candidates(html)
    assert candidates == []
