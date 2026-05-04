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
