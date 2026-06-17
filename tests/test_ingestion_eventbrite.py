from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion.sources.eventbrite import EventbriteSource

# Trimmed snippet of the REAL live Eventbrite San Francisco listing page
# (https://www.eventbrite.com/d/ca--san-francisco/events/), captured 2026-06-15.
# The current page server-renders a schema.org ItemList of events in an
# application/ld+json <script> block; the legacy "search-event-card" HTML cards
# are gone. Years are pinned so the suite stays deterministic.
LIVE_LDJSON_HTML = """
<!doctype html><html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "position": 1,
      "@type": "ListItem",
      "item": {
        "startDate": "2026-06-20",
        "endDate": "2026-06-20",
        "description": "All-White rooftop daytimer with an international guest DJ.",
        "url": "https://www.eventbrite.com/e/chai-rave-sf-all-white-daytimer-620-jones-tickets-1988862230470",
        "location": {
          "address": {
            "addressCountry": "US",
            "addressLocality": "San Francisco",
            "addressRegion": "CA",
            "streetAddress": "620 Jones Street",
            "postalCode": "94102",
            "@type": "PostalAddress"
          },
          "geo": {
            "latitude": "37.787177",
            "@type": "GeoCoordinates",
            "longitude": "-122.412987"
          },
          "@type": "Place",
          "name": "620 Jones"
        },
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "@type": "Event",
        "name": "CHAI RAVE SF: ALL-WHITE DAYTIMER @ 620 JONES ROOFTOP!"
      }
    },
    {
      "position": 2,
      "@type": "ListItem",
      "item": {
        "startDate": "2026-06-21",
        "endDate": "2026-06-21",
        "description": "Half Marathon - 10k - 5k",
        "url": "https://www.eventbrite.com/e/2026-presidio-half-marathon-registration-1344497922479",
        "location": {
          "address": {
            "addressCountry": "US",
            "addressLocality": "San Francisco",
            "addressRegion": "CA",
            "streetAddress": "610 Old Mason St.",
            "postalCode": "94129",
            "@type": "PostalAddress"
          },
          "geo": {
            "latitude": "37.8028839",
            "@type": "GeoCoordinates",
            "longitude": "-122.4591279"
          },
          "@type": "Place",
          "name": "Crissy Field across from the Sports Basement"
        },
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "@type": "Event",
        "name": "2026 Presidio Half Marathon"
      }
    },
    {
      "position": 3,
      "@type": "ListItem",
      "item": {
        "startDate": "2026-06-16",
        "endDate": "2026-06-16",
        "description": "Online training session, attend from anywhere.",
        "url": "https://www.eventbrite.co.uk/e/prevent-in-education-early-years-training-tickets-1535652510999",
        "location": {
          "url": "https://www.eventbrite.co.uk/e/prevent-in-education-early-years-training-tickets-1535652510999",
          "@type": "VirtualLocation"
        },
        "eventAttendanceMode": "https://schema.org/OnlineEventAttendanceMode",
        "@type": "Event",
        "name": "Prevent in Education - Early Years Training"
      }
    }
  ]
}
</script>
</head><body></body></html>
"""


def test_eventbrite_extract_candidates_and_normalize() -> None:
    source = EventbriteSource()
    candidates = source._extract_listing_candidates(LIVE_LDJSON_HTML)

    # The two physical Place events are kept; the VirtualLocation (no geo) is dropped.
    assert len(candidates) == 2

    by_title = {c["title"]: c for c in candidates}
    rave = by_title["CHAI RAVE SF: ALL-WHITE DAYTIMER @ 620 JONES ROOFTOP!"]
    assert rave["source_url"].endswith("tickets-1988862230470")
    assert rave["start_date"] == "2026-06-20"
    assert rave["venue_name"] == "620 Jones"
    assert rave["lat"] == "37.787177"
    assert rave["lon"] == "-122.412987"

    event = source.normalize_raw(rave)
    assert event is not None
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "eventbrite"
    assert payload["source_tier"] == 1
    assert payload["title"] == "CHAI RAVE SF: ALL-WHITE DAYTIMER @ 620 JONES ROOFTOP!"
    assert payload["external_url"].endswith("tickets-1988862230470")
    # The calendar date is explicit on the page; only the wall-clock time
    # defaults (to a 19:00 SF-local evening slot). Stored in UTC, that is
    # 2026-06-21 02:00Z - the date is never fabricated.
    assert payload["start_at"] == datetime(2026, 6, 21, 2, 0, tzinfo=timezone.utc)
    # Real coordinates straight from the page geo block - never fabricated.
    assert event.location.lat == 37.787177
    assert event.location.lon == -122.412987
    assert event.location.location_confidence == 0.9
    # No price/organizer on the listing block - left empty, never invented.
    assert event.offers.price_min is None
    assert event.organizer.name is None
    # No fabricated blanket tags - only data actually on the page.
    assert payload["categories"] == []


def test_eventbrite_drops_virtual_events_without_coordinates() -> None:
    source = EventbriteSource()
    candidates = source._extract_listing_candidates(LIVE_LDJSON_HTML)
    titles = {c["title"] for c in candidates}
    # Online (VirtualLocation) events have no real coordinates and are not
    # physically in SF - dropped rather than stamped with fabricated coords.
    assert "Prevent in Education - Early Years Training" not in titles


def test_eventbrite_drops_event_without_explicit_date() -> None:
    source = EventbriteSource()
    # An event card with real coords but no startDate must be dropped, never
    # defaulted to "today".
    raw_item = {
        "title": "Mystery Event",
        "source_url": "https://www.eventbrite.com/e/mystery-event-tickets-999",
        "source_record_id": "https://www.eventbrite.com/e/mystery-event-tickets-999",
        "start_date": "",
        "venue_name": "Somewhere",
        "lat": "37.7749",
        "lon": "-122.4194",
    }
    assert source.normalize_raw(raw_item) is None


def test_eventbrite_skips_non_event_links() -> None:
    source = EventbriteSource()
    # Page chrome with no ld+json ItemList yields no candidates (no crash).
    html = """
    <a href="https://www.eventbrite.com/signin/">Sign in</a>
    <a href="https://www.eventbrite.com/help/en-us/">Help Center</a>
    <a href="/d/ca--san-francisco/music--events/">Music events</a>
    """
    candidates = source._extract_listing_candidates(html)
    assert candidates == []
