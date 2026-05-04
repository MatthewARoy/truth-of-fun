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
