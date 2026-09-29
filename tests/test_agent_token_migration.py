"""Token schema upgrade preserves legacy rows and labels unknown authors honestly."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from conftest import _require_disposable_database


def test_token_migration_retains_existing_users_and_signals():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable TEST_DATABASE_URL required')
    _require_disposable_database(url)
    path = Path(__file__).parents[1]/'alembic/versions/202609290004_agent_tokens.py'
    spec = importlib.util.spec_from_file_location('agent_tokens_migration', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine(url)
    schema = 'tokens_migration_'+uuid4().hex
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA {schema}'))
                connection.execute(text(f'SET LOCAL search_path TO {schema}'))
                connection.execute(text('CREATE TABLE users (id integer PRIMARY KEY, email text NOT NULL)'))
                connection.execute(text('CREATE TABLE user_signals (id integer PRIMARY KEY, user_id integer REFERENCES users, weight float NOT NULL)'))
                connection.execute(text("INSERT INTO users VALUES (17,'existing@example.com')"))
                connection.execute(text('INSERT INTO user_signals VALUES (1,17,5.0)'))
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
                assert connection.execute(text('SELECT created_via FROM user_signals')).scalar_one() == 'legacy'
                assert connection.execute(text('SELECT count(*) FROM users')).scalar_one() == 1
                connection.execute(text("INSERT INTO agent_tokens (user_id,name,token_prefix,token_hash,scopes,expires_at) VALUES (17,'read','abcdef123456',repeat('a',64),'[\"events:read\"]',now()+interval '1 day')"))
                assert connection.execute(text('SELECT request_count FROM agent_tokens')).scalar_one() == 0
                migration.downgrade()
                assert connection.execute(text('SELECT count(*) FROM users')).scalar_one() == 1
                assert connection.execute(text('SELECT weight FROM user_signals')).scalar_one() == 5.0
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
