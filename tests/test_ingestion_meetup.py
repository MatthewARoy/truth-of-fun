from __future__ import annotations

from app.ingestion.sources.meetup import MeetupSource


def test_meetup_normalize_raw_to_canonical_payload() -> None:
    source = MeetupSource(api_token="test-token")
    raw = {
        "id": "m_123",
        "title": "SF Builders Meetup",
        "eventUrl": "https://www.meetup.com/sf-builders/events/123/",
        "dateTime": "2026-06-01T01:00:00Z",
        "endTime": "2026-06-01T03:00:00Z",
        "description": "A meetup for founders and builders.",
        "venue": {
            "name": "SoMa Hub",
            "address": "123 Howard St",
            "city": "San Francisco",
            "lat": 37.789,
            "lon": -122.397,
        },
        "group": {"name": "SF Builders", "url": "https://www.meetup.com/sf-builders/"},
        "topics": ["startup", "networking"],
    }

    event = source.normalize_raw(raw)
    assert event is not None
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "meetup"
    assert payload["source_tier"] == 1
    assert payload["source_event_id"] == "m_123"
    assert payload["title"] == "SF Builders Meetup"
    assert payload["location"] == "POINT(-122.397 37.789)"
