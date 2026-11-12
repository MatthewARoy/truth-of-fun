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


def test_offers_omit_currency_when_no_price_is_known() -> None:
    """A currency without an amount is meaningless metadata (regression for #19)."""
    source = EventbriteSource()
    candidates = source._extract_listing_candidates(LIVE_LDJSON_HTML)
    event = source.normalize_raw(candidates[0])

    assert event is not None
    assert event.offers.price_min is None
    assert event.offers.currency is None


def test_eventbrite_flags_the_defaulted_wall_clock_time() -> None:
    """A date-only listing gets a placeholder hour - and says so."""
    source = EventbriteSource()
    candidates = source._extract_listing_candidates(LIVE_LDJSON_HTML)
    event = source.normalize_raw(candidates[0])

    assert event is not None
    assert event.start_time_is_estimated is True
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["start_time_is_estimated"] is True


def test_eventbrite_keeps_an_explicit_start_time_unflagged() -> None:
    """schema.org startDate may carry a real time; when it does, use it."""
    source = EventbriteSource()
    raw_item = {
        "title": "Sunset Rooftop Session",
        "source_url": "https://www.eventbrite.com/e/sunset-rooftop-tickets-321",
        "source_record_id": "https://www.eventbrite.com/e/sunset-rooftop-tickets-321",
        "start_date": "2026-06-20T14:30:00-07:00",
        "venue_name": "620 Jones",
        "lat": "37.787177",
        "lon": "-122.412987",
    }

    event = source.normalize_raw(raw_item)

    assert event is not None
    assert event.start_time_is_estimated is False
    assert event.start_time == datetime(2026, 6, 20, 21, 30, tzinfo=timezone.utc)


def test_eventbrite_candidate_preserves_the_time_component() -> None:
    """The listing parser must not truncate a real timestamp to a bare date."""
    source = EventbriteSource()
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Event",
     "name":"Sunset Rooftop Session",
     "url":"https://www.eventbrite.com/e/sunset-rooftop-tickets-321",
     "startDate":"2026-06-20T14:30:00-07:00",
     "location":{"@type":"Place","name":"620 Jones",
       "geo":{"@type":"GeoCoordinates","latitude":"37.787177","longitude":"-122.412987"}}}
    </script>
    """
    candidates = source._extract_listing_candidates(html)

    assert len(candidates) == 1
    assert candidates[0]["start_date"] == "2026-06-20T14:30:00-07:00"


# Trimmed from the REAL Oakland and San Jose listing pages
# (https://www.eventbrite.com/d/ca--oakland/all-events/ and
# .../d/ca--san-jose/all-events/), captured 2026-11-12. A location listing is
# a metro-radius search: the Oakland page carried San Francisco events and the
# San Jose page a Mountain View one, so the city must be read from each
# event's own address rather than from the listing it appeared on.
LIVE_EAST_AND_SOUTH_BAY_LDJSON_HTML = """
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
 {"position": 1, "@type": "ListItem", "item": {
   "@type": "Event",
   "name": "Choir Rehearsal with Friends - OAKLAND",
   "description": "\\"It's a Choir Rehearsal with your FRIENDS\\"",
   "startDate": "2026-11-21", "endDate": "2026-11-21",
   "url": "https://www.eventbrite.com/e/choir-rehearsal-with-friends-oakland-tickets-1997751337027",
   "location": {"@type": "Place", "name": "Evergreen Missionary Baptist Church",
     "address": {"@type": "PostalAddress", "addressRegion": "CA",
       "streetAddress": "408 West MacArthur Boulevard", "addressLocality": "Oakland",
       "addressCountry": "US", "postalCode": "94609"},
     "geo": {"@type": "GeoCoordinates", "latitude": "37.825626", "longitude": "-122.2622634"}},
   "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}},
 {"position": 2, "@type": "ListItem", "item": {
   "@type": "Event",
   "name": "Bhangra & Beats Night Market-Official City of SF Diwali Celebration",
   "description": "A free night market series in downtown SF.",
   "startDate": "2026-11-13", "endDate": "2026-11-13",
   "url": "https://www.eventbrite.com/e/bhangra-beats-night-market-official-city-of-sf-diwali-celebration-tickets-1996185713204",
   "location": {"@type": "Place", "name": "Yerba Buena Gardens",
     "address": {"@type": "PostalAddress", "addressRegion": "CA",
       "streetAddress": "750 Howard Street", "addressLocality": "San Francisco",
       "addressCountry": "US", "postalCode": "94103"},
     "geo": {"@type": "GeoCoordinates", "latitude": "37.7849884", "longitude": "-122.4023514"}},
   "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}},
 {"position": 3, "@type": "ListItem", "item": {
   "@type": "Event",
   "name": "NOV 13 | FRI | HABIBI PLEASE 2.0 \\u2014 A MIDDLE EASTERN PARTY | MOUNTAIN VIEW",
   "description": "Habibi Please returns to bay area.",
   "startDate": "2026-11-13", "endDate": "2026-11-14",
   "url": "https://www.eventbrite.com/e/nov-13-fri-habibi-please-20-a-middle-eastern-party-mountain-view-tickets-1998925436791",
   "location": {"@type": "Place", "name": "Opal nightlcub",
     "address": {"@type": "PostalAddress", "addressRegion": "CA",
       "streetAddress": "251 castro st.", "addressLocality": "Mountain View",
       "addressCountry": "US", "postalCode": "94105"},
     "geo": {"@type": "GeoCoordinates", "latitude": "37.3931085", "longitude": "-122.0790175"}},
   "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}}
]}
</script>
"""


def test_eventbrite_city_is_the_events_own_address_locality() -> None:
    source = EventbriteSource()
    candidates = source._extract_listing_candidates(LIVE_EAST_AND_SOUTH_BAY_LDJSON_HTML)
    # As the crawl would: all three cards were found on the Oakland listing.
    for candidate in candidates:
        candidate["listing_city"] = "Oakland"

    events = [source.normalize_raw(candidate) for candidate in candidates]

    assert all(event is not None for event in events)
    assert [event.location.city for event in events] == [
        "Oakland",
        "San Francisco",
        "Mountain View",
    ]
    oakland = events[0]
    assert oakland.location.address_line1 == "408 West MacArthur Boulevard"
    assert oakland.location.postal_code == "94609"
    assert (oakland.location.lat, oakland.location.lon) == (37.825626, -122.2622634)
    assert oakland.location.location_confidence == 0.9


def test_eventbrite_never_defaults_an_unknown_city_to_san_francisco() -> None:
    source = EventbriteSource()
    raw_item = {
        "title": "Lakeside Session",
        "source_url": "https://www.eventbrite.com/e/lakeside-session-tickets-654",
        "start_date": "2026-11-21",
        "venue_name": "Lakeside Park",
        "lat": "37.8080",
        "lon": "-122.2500",
    }

    unknown = source.normalize_raw(dict(raw_item))
    listed = source.normalize_raw({**raw_item, "listing_city": "Oakland"})

    assert unknown is not None and listed is not None
    # No locality and no listing context: blank, which the pipeline stores as
    # "unknown" - not the LocationModel default of San Francisco.
    assert unknown.location.city == ""
    # Found on the Oakland listing, with no locality of its own.
    assert listed.location.city == "Oakland"
