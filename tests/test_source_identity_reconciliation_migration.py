"""Non-destructive identity reconciliation on disposable PostgreSQL."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from conftest import _require_disposable_database


def test_reconciliation_preserves_existing_owners_events_and_references():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL")
    _require_disposable_database(url)
    path = Path(__file__).parents[1] / "alembic/versions/202609290003_reconcile_legacy_source_identities.py"
    spec = importlib.util.spec_from_file_location("identity_reconciliation", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(url)
    schema = f"identity_migration_{uuid4().hex}"
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f"CREATE SCHEMA {schema}"))
                connection.execute(text(f"SET LOCAL search_path TO {schema}"))
                connection.execute(text("CREATE TABLE events (id integer PRIMARY KEY, source_name text, source_event_id text)"))
                connection.execute(text("""CREATE TABLE event_source_records (
                    source_name text, source_event_id text, event_id integer REFERENCES events(id),
                    content_hash text, PRIMARY KEY (source_name, source_event_id))"""))
                connection.execute(text("CREATE TABLE saved_references (event_id integer REFERENCES events(id))"))
                connection.execute(text("""INSERT INTO events VALUES
                    (1, 'ticketmaster', 'duplicate'), (2, 'ticketmaster', 'duplicate'),
                    (3, 'meetup', 'known'), (4, 'meetup', 'known'),
                    (5, '19hz', 'shared-calendar'), (6, '19hz', 'shared-calendar')"""))
                connection.execute(text("INSERT INTO saved_references VALUES (1), (2), (4), (6)"))
                connection.execute(text("INSERT INTO event_source_records VALUES ('meetup', 'known', 4, 'existing-hash')"))
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
                migration.upgrade()  # Replays retain established ownership.
                owners = connection.execute(text("SELECT source_name, source_event_id, event_id, content_hash FROM event_source_records ORDER BY source_name")).all()
                assert owners == [("meetup", "known", 4, "existing-hash"), ("ticketmaster", "duplicate", 1, None)]
                assert connection.execute(text("SELECT count(*) FROM events")).scalar_one() == 6
                assert connection.execute(text("SELECT event_id FROM saved_references ORDER BY event_id")).scalars().all() == [1, 2, 4, 6]
                migration.downgrade()
                assert connection.execute(text("SELECT count(*) FROM event_source_records")).scalar_one() == 2
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
