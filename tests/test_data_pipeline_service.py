from datetime import datetime, timedelta, timezone

from app.services.data_pipeline import DataPipelineService


def _event(
    *,
    title: str,
    start_at: datetime,
    description: str | None = None,
    end_at: datetime | None = None,
    source_name: str = "ticketmaster",
    source_tier: int = 1,
    location: str = "POINT(-122.4194 37.7749)",
    tags: list[str] | None = None,
    categories: list[str] | None = None,
) -> dict:
    return {
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": end_at,
        "source_name": source_name,
        "source_tier": source_tier,
        "source_event_id": None,
        "external_url": None,
        "venue_name": None,
        "raw_address": None,
        "location": location,
        "categories": categories or [],
        "tags": tags or [],
        "price": None,
        "currency": None,
        "image_url": None,
        "status": "scheduled",
    }


def test_deduplicate_merges_high_similarity_within_two_hours() -> None:
    service = DataPipelineService()
    base = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)

    raw_events = [
        _event(
            title="Sunset Yoga in Dolores Park",
            start_at=base,
            description="Outdoor yoga flow with live ambient DJ set.",
            tags=["#Outdoor"],
            categories=["Wellness"],
        ),
        _event(
            title="Sunset Yoga @ Dolores Park",
            start_at=base + timedelta(minutes=50),
            description=(
                "Outdoor yoga flow with live ambient DJ set. Bring a mat and light jacket."
            ),
            tags=["#Chill"],
            categories=["Fitness"],
        ),
    ]

    deduped = service.deduplicate_events(raw_events)

    assert len(deduped) == 1
    merged = deduped[0]
    assert merged["start_at"] == base
    assert merged["description"] is not None
    assert "Bring a mat" in merged["description"]
    assert set(merged["tags"]) == {"#Outdoor", "#Chill"}
    assert set(merged["categories"]) == {"Wellness", "Fitness"}


def test_deduplicate_does_not_merge_if_start_times_too_far_apart() -> None:
    service = DataPipelineService()
    base = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)

    raw_events = [
        _event(title="Mission District Night Market", start_at=base),
        _event(
            title="Mission District Night Market",
            start_at=base + timedelta(hours=3, minutes=1),
        ),
    ]

    deduped = service.deduplicate_events(raw_events)
    assert len(deduped) == 2


def test_deduplicate_does_not_merge_if_title_similarity_is_low() -> None:
    service = DataPipelineService()
    base = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)

    raw_events = [
        _event(title="Techno Warehouse Party", start_at=base),
        _event(title="Poetry Reading at the Library", start_at=base + timedelta(minutes=30)),
    ]

    deduped = service.deduplicate_events(raw_events)
    assert len(deduped) == 2


def test_title_similarity_threshold_behavior() -> None:
    service = DataPipelineService()

    similar = service._title_similarity(
        "Golden Gate Park Picnic Concert",
        "Golden Gate Pk Picnic Concert",
    )
    dissimilar = service._title_similarity(
        "Golden Gate Park Picnic Concert",
        "Midnight Silent Disco Downtown",
    )

    assert similar > 85.0
    assert dissimilar < 85.0


def test_merge_prefers_authoritative_tier_for_times() -> None:
    """Trust hierarchy: a Tier 1 record's time beats a Tier 3 record's time."""
    service = DataPipelineService()
    tm_start = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
    tm_end = tm_start + timedelta(hours=2)

    tier3_first = service.deduplicate_events([
        _event(
            title="Phoebe Bridgers Reunion Tour",
            start_at=tm_start - timedelta(hours=1),  # reddit guessed early
            end_at=tm_start + timedelta(hours=4),  # and a too-late end
            source_name="reddit",
            source_tier=3,
        ),
        _event(
            title="Phoebe Bridgers — Reunion Tour",
            start_at=tm_start,
            end_at=tm_end,
            source_name="ticketmaster",
            source_tier=1,
        ),
    ])
    assert len(tier3_first) == 1
    assert tier3_first[0]["start_at"] == tm_start
    assert tier3_first[0]["end_at"] == tm_end

    tier1_first = service.deduplicate_events([
        _event(
            title="Phoebe Bridgers — Reunion Tour",
            start_at=tm_start,
            end_at=tm_end,
            source_name="ticketmaster",
            source_tier=1,
        ),
        _event(
            title="Phoebe Bridgers Reunion Tour",
            start_at=tm_start - timedelta(hours=1),
            end_at=tm_start + timedelta(hours=4),
            source_name="reddit",
            source_tier=3,
        ),
    ])
    assert len(tier1_first) == 1
    assert tier1_first[0]["start_at"] == tm_start
    assert tier1_first[0]["end_at"] == tm_end


def test_merge_same_tier_keeps_earliest_start_latest_end() -> None:
    service = DataPipelineService()
    base = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)

    deduped = service.deduplicate_events([
        _event(title="Gallery Night", start_at=base + timedelta(minutes=30),
               end_at=base + timedelta(hours=2), source_name="dothebay", source_tier=2),
        _event(title="Gallery Night", start_at=base,
               end_at=base + timedelta(hours=3), source_name="sfstation", source_tier=2),
    ])
    assert len(deduped) == 1
    assert deduped[0]["start_at"] == base
    assert deduped[0]["end_at"] == base + timedelta(hours=3)


def test_merge_escalates_status_severity_in_batch() -> None:
    """Status only escalates (scheduled < postponed < cancelled < past), in either order."""
    service = DataPipelineService()
    base = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)

    cancelled_second = [
        _event(title="Warehouse Rave", start_at=base),
        {**_event(title="Warehouse Rave", start_at=base), "status": "cancelled"},
    ]
    deduped = service.deduplicate_events(cancelled_second)
    assert len(deduped) == 1
    assert deduped[0]["status"] == "cancelled"

    cancelled_first = [
        {**_event(title="Warehouse Rave", start_at=base), "status": "cancelled"},
        _event(title="Warehouse Rave", start_at=base),
    ]
    deduped = service.deduplicate_events(cancelled_first)
    assert len(deduped) == 1
    assert deduped[0]["status"] == "cancelled"


def test_pipeline_preserves_organizer_signals_and_confidence() -> None:
    service = DataPipelineService()
    base = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)
    raw = _event(title="Gallery Opening", start_at=base)
    raw.update(
        {
            "organizer_name": "Minnesota Street Project",
            "attendee_count": 120,
            "location_confidence": 0.9,
            "is_free": True,
        }
    )

    deduped = service.deduplicate_events([raw])

    assert len(deduped) == 1
    normalized = deduped[0]
    assert normalized["organizer_name"] == "Minnesota Street Project"
    assert normalized["attendee_count"] == 120
    assert normalized["location_confidence"] == 0.9
    assert normalized["is_free"] is True


def test_merge_keeps_best_signals() -> None:
    service = DataPipelineService()
    base = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)
    sparse = _event(title="Gallery Opening", start_at=base, source_name="sfstation", source_tier=2)
    rich = _event(title="Gallery Opening", start_at=base, source_name="dothebay", source_tier=2)
    rich.update(
        {
            "organizer_name": "Minnesota Street Project",
            "attendee_count": 120,
            "location_confidence": 0.9,
            "is_free": True,
        }
    )

    deduped = service.deduplicate_events([sparse, rich])

    assert len(deduped) == 1
    merged = deduped[0]
    assert merged["organizer_name"] == "Minnesota Street Project"
    assert merged["attendee_count"] == 120
    # The sparse record omitted confidence (treated as trusted 1.0); merge keeps the max.
    assert merged["location_confidence"] == 1.0
    assert merged["is_free"] is True
