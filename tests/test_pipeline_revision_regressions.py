from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio
import re
import struct

import pytest
from sqlalchemy import Column, MetaData, String, Table, event as sa_event
from sqlmodel import SQLModel, Session, create_engine, select

from app.models.event import Event
from app.services.data_pipeline import DataPipelineService
from app.models.source_record import EventSourceRecord
from app.models.vibe_tag_cache import VibeTagCache


class NoTags:
    async def generate_vibe_tags(self, description):
        return []


def payload(**changes):
    raw = dict(
        title="Community Yoga", start_at=datetime(2026, 10, 1, 19, tzinfo=timezone.utc),
        source_name="ticketmaster", source_tier=1, source_event_id="tm-123",
        external_url="https://example.test/event/123", venue_name="Venue A",
        location="POINT(-122.4 37.7)", location_confidence=0.9,
        description="A social yoga class", status="scheduled", price=Decimal("10"),
        currency="USD",
    )
    raw.update(changes)
    return DataPipelineService(vibe_tagger=NoTags())._normalize_event_payload(raw)


def test_cancellation_and_price_only_changes_are_significant():
    service = DataPipelineService(vibe_tagger=NoTags())
    original = payload()
    stored = Event(**original)
    assert service.has_significant_new_information(
        existing_event=stored, incoming_event={**original, "status": "cancelled"}
    )
    assert service.has_significant_new_information(
        existing_event=stored, incoming_event={**original, "price": Decimal("20")}
    )


def test_same_source_revision_replaces_schedule_and_price():
    service = DataPipelineService(vibe_tagger=NoTags())
    original = payload()
    changed = payload(start_at=original["start_at"] + timedelta(days=1), price=Decimal("20"))
    assert service._is_duplicate(original, changed)
    merged = service._merge_event_payloads(primary=original, secondary=changed)
    assert merged["start_at"] == changed["start_at"]
    assert merged["price"] == Decimal("20")


def test_generic_titles_at_conflicting_venues_remain_distinct():
    service = DataPipelineService(vibe_tagger=NoTags())
    original = payload()
    elsewhere = payload(source_event_id="tm-456", external_url="https://example.test/456", venue_name="Venue B")
    assert len(service.deduplicate_events([original, elsewhere])) == 2


def test_coordinate_and_confidence_stay_paired_in_both_orders():
    service = DataPipelineService(vibe_tagger=NoTags())
    trusted = payload()
    centroid = payload(source_name="reddit", source_tier=3, source_event_id="reddit-999999",
                       location="POINT(-122.419400 37.774900)", location_confidence=0.3)
    for first, second in ((trusted, centroid), (centroid, trusted)):
        merged = service._merge_event_payloads(primary=first, secondary=second)
        assert merged["location"] == trusted["location"]
        assert merged["location_confidence"] == 0.9
        assert (merged["source_name"], merged["source_event_id"]) == ("ticketmaster", "tm-123")


def test_city_survives_normalization_for_geocoding():
    assert payload(city="Oakland")["city"] == "Oakland"


@pytest.fixture
def database():
    """Exercise real SQL/transactions; spatial behavior is outside these tests."""
    engine = create_engine("sqlite://")

    @sa_event.listens_for(engine, "connect")
    def geometry_functions(connection, _record):
        def geometry(value):
            if isinstance(value, bytes):
                return value
            lon, lat = map(float, re.search(r"POINT\(([^ ]+) ([^)]+)\)", value).groups())
            return struct.pack("<BIdd", 1, 1, lon, lat)
        connection.create_function("GeomFromEWKT", 1, geometry)
        connection.create_function("AsEWKB", 1, lambda value: value)

    metadata = MetaData()
    Table("events", metadata, *[
        Column(column.name, String() if column.name == "location" else column.type,
               primary_key=column.primary_key, nullable=column.nullable,
               server_default=column.server_default)
        for column in Event.__table__.columns
    ])
    metadata.create_all(engine)
    SQLModel.metadata.create_all(engine, tables=[EventSourceRecord.__table__, VibeTagCache.__table__])
    yield engine
    engine.dispose()


class CountingTags:
    cache_identity = "test-model:prompt-v1"
    last_call_succeeded = True

    def __init__(self):
        self.calls = []

    async def generate_vibe_tags(self, description):
        self.calls.append(description)
        return ["#social"]


@pytest.mark.anyio
async def test_source_aliases_survive_cross_source_merge_and_later_reschedule(database):
    service = DataPipelineService(vibe_tagger=NoTags())
    original = payload()
    curator = payload(source_name="meetup", source_event_id="meetup-987654321", source_tier=2)
    with Session(database) as session:
        first = await service.process_raw_events(session=session, raw_events=[curator, original])
        assert first["inserted"] == 1
        aliases = session.exec(select(EventSourceRecord)).all()
        assert {(r.source_name, r.source_event_id) for r in aliases} == {
            ("ticketmaster", "tm-123"), ("meetup", "meetup-987654321")
        }
        event_id = aliases[0].event_id

    with Session(database) as session:
        revised = payload(start_at=original["start_at"] + timedelta(days=1), price=Decimal("25"), status="cancelled")
        summary = await service.process_raw_events(session=session, raw_events=[revised])
        assert summary["updated"] == 1
        saved = session.get(Event, event_id)
        assert saved.status == "cancelled"
        assert saved.price == Decimal("25")
        assert saved.start_at.replace(tzinfo=timezone.utc) == revised["start_at"]
        assert len(session.exec(select(Event)).all()) == 1
        # Resolve the other source's preserved identity, despite a date far
        # outside the fuzzy window and a canonical owner from another provider.
        other = service._find_existing_event(session=session, incoming_event=curator)
        assert other.id == event_id


@pytest.mark.anyio
async def test_tag_cache_survives_new_pipeline_and_is_versioned(database):
    first_tags = CountingTags()
    with Session(database) as session:
        await DataPipelineService(vibe_tagger=first_tags).process_raw_events(session=session, raw_events=[payload()])
    second_tags = CountingTags()
    with Session(database) as session:
        result = await DataPipelineService(vibe_tagger=second_tags).process_raw_events(session=session, raw_events=[payload()])
    assert len(first_tags.calls) == 1
    assert second_tags.calls == []
    assert result["skipped"] == 1
    second_tags.cache_identity = "test-model:prompt-v2"
    with Session(database) as session:
        await DataPipelineService(vibe_tagger=second_tags).process_raw_events(session=session, raw_events=[payload()])
    assert len(second_tags.calls) == 1


@pytest.mark.anyio
async def test_tagging_budget_and_input_limit_are_enforced(database):
    tagger = CountingTags()
    raws = [payload(source_event_id=f"tm-{i}", start_at=payload()["start_at"] + timedelta(days=i), description=str(i) * 20000) for i in range(3)]
    service = DataPipelineService(vibe_tagger=tagger, max_tagging_calls_per_run=2)
    with Session(database) as session:
        result = await service.process_raw_events(session=session, raw_events=raws + [{"invalid": True}])
    assert result["inserted"] == 3
    assert result["rejected"] == 1
    assert len(tagger.calls) == 2
    assert all(len(text) == 8000 for text in tagger.calls)
    with Session(database) as session:
        await service.process_raw_events(session=session, raw_events=raws)
    assert len(tagger.calls) == 3  # The deferred row gets its turn next cycle.


@pytest.mark.anyio
async def test_failed_tagging_is_not_cached(database):
    tagger = CountingTags()
    tagger.last_call_succeeded = False
    with Session(database) as session:
        await DataPipelineService(vibe_tagger=tagger).process_raw_events(session=session, raw_events=[payload()])
        assert session.exec(select(VibeTagCache)).all() == []


@pytest.mark.anyio
@pytest.mark.parametrize("alias_tier, expected_source", [(1, "eventbrite"), (2, "ticketmaster")])
async def test_changed_alias_updates_without_unchanged_replay_oscillation(database, alias_tier, expected_source):
    service = DataPipelineService(vibe_tagger=NoTags())
    primary = payload()
    alias = payload(source_name="eventbrite", source_event_id="eb-456", source_tier=alias_tier)
    with Session(database) as session:
        result = await service.process_raw_events(session=session, raw_events=[primary, alias])
        assert result["inserted"] == 1
    revised = {**alias, "start_at": alias["start_at"] + timedelta(hours=3), "price": Decimal("25")}
    with Session(database) as session:
        await service.process_raw_events(session=session, raw_events=[revised])
    for replay in ([primary, revised], [revised, primary]):
        with Session(database) as session:
            await service.process_raw_events(session=session, raw_events=replay)
            saved = session.exec(select(Event)).one()
            expected = revised if alias_tier == 1 else primary
            assert saved.start_at.replace(tzinfo=timezone.utc) == expected["start_at"]
            assert saved.price == expected["price"]
            assert saved.source_name == expected_source
            assert saved.source_event_id == expected["source_event_id"]


@pytest.mark.anyio
@pytest.mark.parametrize("source,key", [
    ("19hz", "https://19hz.info/eventlisting_BayArea.php"),
    ("luma", "luma-Weekly Social Meetup"),
    ("dothebay", "weekly-dance-party"),
    ("eddies_list", "https://example.test/venue/calendar"),
])
async def test_reused_weak_identifiers_do_not_collapse_separate_nights(database, source, key):
    service = DataPipelineService(vibe_tagger=NoTags())
    first = payload(source_name=source, source_event_id=key)
    second = {**first, "start_at": first["start_at"] + timedelta(days=7)}
    with Session(database) as session:
        result = await service.process_raw_events(session=session, raw_events=[first, second])
        assert result["inserted"] == 2
        assert len(session.exec(select(Event)).all()) == 2
        assert session.exec(select(EventSourceRecord)).all() == []


@pytest.mark.anyio
@pytest.mark.parametrize("estimated", [False, True])
async def test_reschedule_without_end_discards_the_old_end_and_preserves_time_certainty(database, estimated):
    service = DataPipelineService(vibe_tagger=NoTags())
    original = payload()
    original["end_at"] = original["start_at"] + timedelta(hours=2)
    revised = {**original, "start_at": original["start_at"] + timedelta(days=1),
               "end_at": None, "start_time_is_estimated": estimated}
    with Session(database) as session:
        await service.process_raw_events(session=session, raw_events=[original])
    with Session(database) as session:
        await service.process_raw_events(session=session, raw_events=[revised])
        saved = session.exec(select(Event)).one()
        assert saved.start_at.replace(tzinfo=timezone.utc) == revised["start_at"]
        assert saved.end_at is None
        assert saved.start_time_is_estimated is estimated


@pytest.mark.anyio
async def test_authoritative_coordinate_only_revision_is_applied_before_hash_advances(database):
    service = DataPipelineService(vibe_tagger=NoTags())
    original = payload()
    revised = {**original, "location": "POINT(-122.41 37.71)"}
    with Session(database) as session:
        await service.process_raw_events(session=session, raw_events=[original])
    for _ in range(2):
        with Session(database) as session:
            await service.process_raw_events(session=session, raw_events=[revised])
            saved = session.exec(select(Event)).one()
            _, _, lon, lat = struct.unpack("<BIdd", bytes(saved.location.data))
            assert (lon, lat) == (-122.41, 37.71)


@pytest.mark.anyio
async def test_concurrent_cache_fill_does_not_rollback_unrelated_events(database):
    class RacingTags(CountingTags):
        def __init__(self):
            self.entered = 0
            self.ready = asyncio.Event()

        async def generate_vibe_tags(self, description):
            self.entered += 1
            if self.entered == 2:
                self.ready.set()
            await self.ready.wait()
            return ["#social"]

    tagger = RacingTags()

    async def ingest(number):
        with Session(database) as session:
            return await DataPipelineService(vibe_tagger=tagger).process_raw_events(
                session=session,
                raw_events=[payload(source_event_id=f"tm-{number}", venue_name=f"Venue {number}")],
            )

    results = await asyncio.gather(ingest(1), ingest(2))
    assert all(result["inserted"] == 1 for result in results)
    with Session(database) as session:
        assert len(session.exec(select(Event)).all()) == 2
        assert len(session.exec(select(VibeTagCache)).all()) == 1


@pytest.mark.anyio
async def test_unchanged_alias_cannot_restore_coordinates_from_previous_venue(database):
    service = DataPipelineService(vibe_tagger=NoTags())
    original = payload(raw_address="Old Venue Address")
    alias = {**original, "source_name": "eventbrite", "source_event_id": "eb-456"}
    moved = {**original, "venue_name": "New Venue", "raw_address": "New Venue Address",
             "location": "POINT(-122.42 37.77)", "location_confidence": 0.3}
    for batch in ([original, alias], [moved], [alias]):
        with Session(database) as session:
            await service.process_raw_events(session=session, raw_events=batch)
    with Session(database) as session:
        saved = session.exec(select(Event)).one()
        _, _, lon, lat = struct.unpack("<BIdd", bytes(saved.location.data))
        assert saved.venue_name == "New Venue"
        assert saved.location_confidence == 0.3
        assert (lon, lat) == (-122.42, 37.77)
