from datetime import datetime, timedelta, timezone

from app.api.discovery import _serialize_event
from app.models.event import Event
from app.services.catalog_taxonomy_v1 import CANONICAL, categories_v1
from app.services.data_pipeline import DataPipelineService


def test_pipeline_separates_metadata_and_emits_only_canonical_categories():
    service = DataPipelineService()
    raw = {"title":"Published concert", "start_at":datetime(2026,10,2,tzinfo=timezone.utc),
        "source_name":"ticketmaster", "source_tier":1,"status":"scheduled","location":"POINT(-122.4 37.76)",
        "categories":["Undefined","Rock","21+","$50 | 21+","Other","Music"],
        "performers":["Headliner Artist"],"tags":["Headliner Artist","HighEnergy"],"currency":"USD"}
    result = service._normalize_event_payload(raw)
    assert result["categories"] == ["Music"]
    assert result["genres"] == ["Rock"]
    assert result["performers"] == ["Headliner Artist"]
    assert result["tags"] == ["#highenergy"]
    assert result["currency"] is None


def test_legacy_api_read_filters_unknown_categories_and_performer_vibes():
    event = Event(title="Legacy concert",start_at=datetime(2026,10,2,tzinfo=timezone.utc),source_name="test",source_tier=1,
        categories=["Undefined","Rock","$50 | 21+"],tags=["Alex Ramon","HighEnergy"], performers=["Alex Ramon"],genres=["Rock"])
    data = _serialize_event(event)
    assert data.categories == ["Music"]
    assert data.tags == ["#highenergy"]
    assert data.performers == ["Alex Ramon"]
    assert data.genres == ["Rock"]
    assert set(data.categories) <= set(CANONICAL)


def test_source_kinds_have_known_parents_without_guessing_unknowns():
    assert categories_v1(["gallery","arts","tech","community"]) == ["Arts & Theatre","Business","Social"]
    assert categories_v1(["Unknown artist", "free | 21+"]) == []


def test_performer_search_does_not_require_artist_in_title(isolated_events_session):
    from fastapi.testclient import TestClient
    from app.main import app
    session = isolated_events_session
    event = Event(title="Friday evening concert", start_at=datetime.now(timezone.utc) + timedelta(days=2),
        source_name="test", source_tier=1, performers=["Unique Headliner"], genres=["Rock"],
        categories=["Music"], tags=["#livemusic"], location="POINT(-122.4 37.76)")
    session.add(event)
    session.flush()
    response = TestClient(app).get("/events", params={"q":"Unique Headliner"})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [event.id]
    assert response.json()[0]["performers"] == ["Unique Headliner"]
    assert TestClient(app).get("/events", params={"q":"Unrelated Performer"}).json() == []


def test_published_lineup_revision_replaces_old_facts_without_guessing_erasure():
    from test_pipeline_revision_regressions import payload
    service = DataPipelineService()
    original = payload(performers=["Original Artist"], genres=["Rock"])
    revised = payload(performers=["Replacement Artist"], genres=["Pop"])
    merged = service._merge_event_payloads(primary=original, secondary=revised)
    assert merged["performers"] == ["Replacement Artist"]
    assert merged["genres"] == ["Pop"]
    unknown = payload(performers=[], genres=[])
    preserved = service._merge_event_payloads(primary=merged, secondary=unknown)
    assert preserved["performers"] == ["Replacement Artist"]
    assert preserved["genres"] == ["Pop"]


def test_unchanged_alias_metadata_does_not_trigger_redundant_update():
    from test_pipeline_revision_regressions import payload
    service = DataPipelineService()
    current = payload(performers=["Replacement Artist"], genres=["Pop"])
    old_alias = payload(source_name="meetup", source_event_id="meetup-old", source_tier=2,
                        performers=["Original Artist"], genres=["Rock"])
    old_alias["_source_unchanged"] = True
    assert not service.has_significant_new_information(existing_event=Event(**current), incoming_event=old_alias)
    merged = service._merge_event_payloads(primary=current, secondary=old_alias)
    assert merged["performers"] == ["Replacement Artist"]
    assert merged["genres"] == ["Pop"]


def test_category_filter_matches_legacy_display_and_dedicated_genre(isolated_events_session):
    from fastapi.testclient import TestClient
    from app.main import app
    session = isolated_events_session
    for title, categories, genres in [("Legacy", ["Rock", "Undefined"], []), ("New", ["Music"], ["Rock"]), ("Unrelated comedy", ["Comedy"], [])]:
        session.add(Event(title=title, start_at=datetime.now(timezone.utc)+timedelta(days=2), source_name="test",
                          source_tier=1, categories=categories, genres=genres, location="POINT(-122.4 37.76)"))
    session.flush()
    client = TestClient(app)
    for category in ("Music", "Rock"):
        response = client.get("/events", params={"category":category})
        assert response.status_code == 200
        assert {row["title"] for row in response.json()} == {"Legacy", "New"}
        assert all(row["categories"] == ["Music"] and row["genres"] == ["Rock"] for row in response.json())


def test_known_source_classification_labels_are_preserved():
    from app.services.catalog_taxonomy_v1 import legacy_genres_v1
    labels = ["Hip-Hop/Rap", "Latin", "World", "Soul", "Funk", "Indie", "Punk", "Family", "Fairs & Festivals", "Circus & Specialty Acts"]
    assert legacy_genres_v1(labels) == labels
    assert categories_v1(labels) == ["Music", "Festival", "Arts & Theatre"]



def test_category_migration_preserves_rows_and_restores_originals():
    import importlib.util
    import os
    from pathlib import Path
    from uuid import uuid4
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text
    from conftest import _require_disposable_database
    url = os.environ["TEST_DATABASE_URL"]
    _require_disposable_database(url)
    path = Path(__file__).parents[1] / "alembic/versions/202609290007_canonical_categories.py"
    spec = importlib.util.spec_from_file_location("catalog_category_migration",path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    additive_path = path.with_name("202609290006_catalog_facts.py")
    additive_spec = importlib.util.spec_from_file_location("catalog_facts_migration", additive_path)
    additive = importlib.util.module_from_spec(additive_spec)
    additive_spec.loader.exec_module(additive)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                schema = "catalog_migration_" + uuid4().hex
                connection.execute(text(f"CREATE SCHEMA {schema}"))
                connection.execute(text(f"SET LOCAL search_path TO {schema}"))
                connection.execute(text("CREATE TABLE events(id integer PRIMARY KEY, categories json NOT NULL)"))
                connection.execute(text("CREATE TABLE event_source_records(source_event_id text PRIMARY KEY, content_hash text)"))
                connection.execute(text("INSERT INTO event_source_records VALUES ('legacy','old-hash')"))
                connection.execute(text("""INSERT INTO events VALUES
                    (1,'["Undefined","Rock","21+","$50 | 21+"]'),
                    (2,'["Music"]'),
                    (3,'["Other"]')"""))
                before_addition = connection.execute(text("SELECT * FROM events ORDER BY id")).mappings().all()
                additive.op = Operations(MigrationContext.configure(connection))
                additive.upgrade()
                provenance = connection.execute(text("SELECT * FROM event_source_records")).mappings().one()
                assert provenance["content_hash"] == "old-hash" and provenance["hash_version"] == 1 and provenance["catalog_facts"] == {}
                assert connection.execute(text("SELECT count(*) FROM pg_indexes WHERE schemaname=:schema AND indexname='ix_events_performers_search'"), {"schema":schema}).scalar_one() == 1
                connection.execute(text("UPDATE events SET genres='[\"Jazz\"]' WHERE id=2"))
                original = connection.execute(text("SELECT * FROM events ORDER BY id")).mappings().all()
                assert all(row["performers"] == [] for row in original)
                module.op = Operations(MigrationContext.configure(connection)); module.upgrade()
                changed = connection.execute(text("SELECT * FROM events ORDER BY id")).mappings().all()
                assert len(changed) == 3
                assert changed[0]["categories"] == ["Music"]
                assert changed[0]["genres"] == ["Rock"]
                assert changed[1] == original[1]
                assert changed[2]["categories"] == []
                assert connection.execute(text("SELECT count(*) FROM event_category_backup_20260929")).scalar_one() == 2
                # A post-upgrade row has no backup and survives downgrade.
                connection.execute(text("INSERT INTO events VALUES (4,'[\"Music\"]','[]','[]')"))
                # Deletion cascades retire an obsolete backup before any ID reuse.
                connection.execute(text("DELETE FROM events WHERE id=3"))
                assert connection.execute(text("SELECT count(*) FROM event_category_backup_20260929")).scalar_one() == 1
                # Downgrade explicitly restores the pre-upgrade snapshot on backed-up rows.
                connection.execute(text("UPDATE events SET genres='[\"Post-upgrade Jazz\"]' WHERE id=1"))
                module.downgrade()
                restored = connection.execute(text("SELECT * FROM events ORDER BY id")).mappings().all()
                assert restored[:2] == original[:2]
                assert restored[2]["id"] == 4 and restored[2]["categories"] == ["Music"]
                connection.execute(text("DELETE FROM events WHERE id=4"))
                connection.execute(text("INSERT INTO events VALUES (3,'[\"Other\"]','[]','[]')"))
                additive.downgrade()
                assert connection.execute(text("SELECT * FROM events ORDER BY id")).mappings().all() == before_addition
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
