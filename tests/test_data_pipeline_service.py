from datetime import datetime, timedelta, timezone

from app.models.event import Event
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
    venue_name: str | None = None,
    external_url: str | None = None,
) -> dict:
    return {
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": end_at,
        "source_name": source_name,
        "source_tier": source_tier,
        "source_event_id": None,
        "external_url": external_url,
        "venue_name": venue_name,
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
    # Tags are canonicalized at write: "#Outdoor" folds onto "#outdoors".
    assert set(merged["tags"]) == {"#outdoors", "#chill"}
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


# Real duplicate pairs observed in the feed for Sunday 2026-08-02 (see #18).
# Whole-title Levenshtein scored these 62.9, 72.4 and 80.6 — all under the
# 85.0 threshold — so the same show appeared two and three times.

def test_deduplicate_merges_rotating_lineup_titles_at_one_venue() -> None:
    """Headliner order rotates between sources; it is still one show."""
    service = DataPipelineService()
    start = datetime(2026, 8, 2, 19, 30, tzinfo=timezone.utc)
    events = [
        _event(
            title="Bird and Byron W/ ZG Smith, Hero Magnus Live At Brick & Mortar (San FR",
            start_at=start,
            venue_name="Brick & Mortar Music Hall",
        ),
        _event(
            title="Hero Magnus W/ Bird and Byron Live At Brick & Mortar (San Francisco, C",
            start_at=start,
            venue_name="Brick & Mortar Music Hall",
        ),
    ]

    assert len(service.deduplicate_events(events)) == 1


def test_deduplicate_merges_when_support_acts_are_appended() -> None:
    """One source lists five artists, another eight — same party at The Stud."""
    service = DataPipelineService()
    start = datetime(2026, 8, 2, 21, 0, tzinfo=timezone.utc)
    events = [
        _event(
            title="Sweet Tooth Fest: Paydayloan, Bootyjuice, Buku FM, DJ Black Woman, Uni Yasmin",
            start_at=start,
            venue_name="The Stud (San Francisco) afrobeats, house",
        ),
        _event(
            title=(
                "Sweet Tooth Festival: Padayl0an, Booty Juice, BUKU FM, DJ Black Woman, "
                "Uni Yasmin, After Thought, Alien Mac Kitty, LBXX"
            ),
            start_at=start,
            venue_name="The Stud (San Francisco) hip-hop, r&b, house",
        ),
    ]

    assert len(service.deduplicate_events(events)) == 1


def test_deduplicate_merges_on_identical_external_url() -> None:
    """The same ticketing URL is the same event, whatever the titles say."""
    service = DataPipelineService()
    url = "https://www.ticketweb.com/event/bird-and-byron-w-zg-brick-and-mortar-tickets/14860143"
    events = [
        _event(
            title="Bird and Byron W/ ZG Smith Live At Brick & Mortar (San Francisco, Ca)",
            start_at=datetime(2026, 8, 2, 20, 0, tzinfo=timezone.utc),
            external_url=url,
        ),
        _event(
            title="Bird and Byron W/ ZG Smith, Hero Magnus Live At Brick & Mortar (San FR",
            start_at=datetime(2026, 8, 2, 19, 30, tzinfo=timezone.utc),
            external_url=url,
        ),
    ]

    assert len(service.deduplicate_events(events)) == 1


def test_deduplicate_keeps_different_shows_at_the_same_venue() -> None:
    """Sharing a venue and a night is not enough — distinct bills stay distinct."""
    service = DataPipelineService()
    events = [
        _event(
            title="Sweet Tooth Fest: Paydayloan, Bootyjuice",
            start_at=datetime(2026, 8, 2, 21, 0, tzinfo=timezone.utc),
            venue_name="The Stud (San Francisco)",
        ),
        _event(
            title="Sindustry Sundays: Ming, Jeff Straw",
            start_at=datetime(2026, 8, 2, 22, 0, tzinfo=timezone.utc),
            venue_name="The Stud (San Francisco)",
        ),
    ]

    assert len(service.deduplicate_events(events)) == 2


def test_find_existing_event_matches_a_stored_rotating_lineup(monkeypatch) -> None:
    """The DB path must use the same rule as in-batch dedupe (see #18).

    Otherwise a duplicate that survives one ingestion cycle is re-inserted on
    the next one, because the stored title never scores 85 against the
    incoming variant.
    """
    service = DataPipelineService()
    start = datetime(2026, 8, 2, 19, 30, tzinfo=timezone.utc)
    stored = Event(
        title="Bird and Byron W/ ZG Smith, Hero Magnus Live At Brick & Mortar (San FR",
        start_at=start,
        source_name="ticketmaster",
        source_tier=1,
        venue_name="Brick & Mortar Music Hall",
        location="POINT(-122.4194 37.7749)",
    )

    class _FakeSession:
        def exec(self, _stmt):
            class _Result:
                def all(self_inner):
                    return [stored]

            return _Result()

    incoming = _event(
        title="Hero Magnus W/ Bird and Byron Live At Brick & Mortar (San Francisco, C",
        start_at=start,
        venue_name="Brick & Mortar Music Hall",
    )

    assert service._find_existing_event(session=_FakeSession(), incoming_event=incoming) is stored


# Codex review of PR #22 found the two rules below were over-broad.

def test_shared_listing_url_does_not_merge_events_on_different_nights() -> None:
    """A venue calendar URL is not an event identity (review P1).

    Sources fall back to a listing/profile URL when a row has no event-specific
    link: 8 Kips Berkeley events across 8 different nights all carry
    https://www.instagram.com/kipsberkeley/. Matching on URL alone, before the
    time window, collapsed all of them into one.
    """
    service = DataPipelineService()
    url = "https://www.instagram.com/kipsberkeley/"
    events = [
        _event(
            title="College Thursday",
            start_at=datetime(2026, 7, 30, 22, 0, tzinfo=timezone.utc),
            external_url=url,
        ),
        _event(
            title="Friday Party",
            start_at=datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc),
            external_url=url,
        ),
    ]

    assert len(service.deduplicate_events(events)) == 2


def test_token_subset_titles_at_different_venues_are_not_merged() -> None:
    """token_set_ratio returns 100 for a subset, which is not identity (review P1).

    "Comedy Night" scores 100 against "Free Sunday Comedy Night in Downtown SF".
    Without venue or URL corroboration that merged unrelated events an hour
    apart and silently dropped one.
    """
    service = DataPipelineService()
    events = [
        _event(
            title="Comedy Night",
            start_at=datetime(2026, 8, 2, 19, 0, tzinfo=timezone.utc),
            venue_name="The Punch Line",
        ),
        _event(
            title="Free Sunday Comedy Night in Downtown SF",
            start_at=datetime(2026, 8, 2, 20, 0, tzinfo=timezone.utc),
            venue_name="The Function",
        ),
    ]

    assert len(service.deduplicate_events(events)) == 2
