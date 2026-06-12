from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion import registry
from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import SourceMetadata


def test_registry_includes_all_prd_sources() -> None:
    expected = {
        "ticketmaster",
        "eventbrite",
        "meetup",
        "funcheap_sf",
        "19hz",
        "luma",
        "dothebay",
        "sfstation",
        "minnesotastreet",
        "reddit",
        "eddies_list",
    }
    assert expected.issubset(set(registry.list_sources()))


def test_canonical_event_maps_to_legacy_payload() -> None:
    now = datetime.now(timezone.utc)
    canonical = CanonicalEvent(
        source=SourceMetadata(
            source_id="ticketmaster",
            source_record_id="tm_1",
            source_url="https://example.com/events/tm_1",
            ingested_at=now,
            last_seen_at=now,
            capture_mode="api",
            crawl_job_id="job-1",
        ),
        title="SF Demo Night",
        start_time=now,
        location=LocationModel(
            venue_name="Pier 70",
            address_line1="420 22nd St",
            lat=37.7577,
            lon=-122.3872,
        ),
    )

    payload = canonical.to_legacy_event_payload(source_tier=1)
    assert payload["source_name"] == "ticketmaster"
    assert payload["source_tier"] == 1
    assert payload["source_event_id"] == "tm_1"
    assert payload["location"] == "POINT(-122.3872 37.7577)"


def test_legacy_payload_carries_organizer_signals_and_confidence() -> None:
    """Spec-mandated organizer/social/confidence data must survive into the payload."""
    from app.ingestion.contracts import OffersModel, OrganizerModel, SocialSignalsModel

    now = datetime.now(timezone.utc)
    canonical = CanonicalEvent(
        source=SourceMetadata(
            source_id="luma",
            source_record_id="sf-demo-night",
            source_url="https://luma.com/sf-demo-night",
            ingested_at=now,
            last_seen_at=now,
            capture_mode="scrape",
            crawl_job_id="job-2",
        ),
        title="SF Demo Night",
        start_time=now,
        location=LocationModel(lat=37.7577, lon=-122.3872, location_confidence=0.3),
        organizer=OrganizerModel(name="The AI Collective"),
        social_signals=SocialSignalsModel(attendee_count=371),
        offers=OffersModel(is_free=True, price_min=0.0),
    )

    payload = canonical.to_legacy_event_payload(source_tier=2)
    assert payload["organizer_name"] == "The AI Collective"
    assert payload["attendee_count"] == 371
    assert payload["location_confidence"] == 0.3
    assert payload["is_free"] is True
