"""Sharing lifecycle migration against explicit disposable PostgreSQL only."""
from __future__ import annotations

import importlib.util
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_legacy_shares_receive_rollout_grace_and_survive_downgrade():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a disposable PostgreSQL')
    migration_path = Path(__file__).parents[1] / 'alembic/versions/202609290002_itinerary_share_lifecycle.py'
    spec = importlib.util.spec_from_file_location('sharing_lifecycle_migration', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(url)
    schema = f'share_migration_{uuid4().hex}'
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA {schema}'))
                connection.execute(text(f'SET LOCAL search_path TO {schema}'))
                connection.execute(text('''CREATE TABLE saved_itineraries (
                    id integer PRIMARY KEY, user_id integer, query text NOT NULL,
                    created_at timestamptz NOT NULL, stops json NOT NULL)'''))
                connection.execute(text('''INSERT INTO saved_itineraries VALUES
                    (1, NULL, 'private legacy prompt', now() - interval '1 year', '[]'),
                    (2, 17, 'private owner prompt', now() - interval '1 day', '[]')'''))
                now = connection.execute(text('SELECT now()')).scalar_one()
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
                records = connection.execute(text('SELECT * FROM saved_itineraries ORDER BY id')).mappings().all()
                assert len(records) == 2
                assert all(row['expires_at'] == now + timedelta(days=14) for row in records)
                assert all(row['revoked_at'] is None for row in records)
                assert [row['user_id'] for row in records] == [None, 17]
                assert records[0]['query'] == 'private legacy prompt'
                assert connection.execute(text('''SELECT is_nullable FROM information_schema.columns
                    WHERE table_schema=:schema AND table_name='saved_itineraries'
                    AND column_name='expires_at' '''), {'schema': schema}).scalar_one() == 'NO'
                migration.downgrade()
                restored = connection.execute(text('SELECT * FROM saved_itineraries ORDER BY id')).mappings().all()
                assert len(restored) == 2 and 'expires_at' not in restored[0]
                assert restored[0]['query'] == 'private legacy prompt'
                assert restored[0]['user_id'] is None
            finally:
                transaction.rollback()  # Includes this test's isolated schema.
    finally:
        engine.dispose()
