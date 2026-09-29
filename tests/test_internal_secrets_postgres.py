"""Sampling serialization against an explicitly configured disposable PostgreSQL."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlmodel import Session, create_engine, select

from app.services.key_usage_snapshots import snapshot_key_health as _snapshot_health
from app.models.api_key import ApiKeyUsageSnapshot
from app.services.secrets_store import KeyHealth


def test_concurrent_usage_reports_emit_one_sample_per_interval():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a migrated disposable PostgreSQL')
    engine = create_engine(url)
    provider = f'review-{uuid4().hex}'
    health = KeyHealth(key_id='fixture', usage_count=1, quota_limit=100,
        status='active', last_status=200, last_error=None, updated_at_epoch=1)
    def sample(_):
        with Session(engine) as session:
            _snapshot_health(provider=provider, health_items=[health], session=session)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(sample, range(16)))
        with Session(engine) as session:
            rows = session.exec(select(ApiKeyUsageSnapshot).where(ApiKeyUsageSnapshot.provider == provider)).all()
            assert len(rows) == 1
    finally:
        with Session(engine) as session:
            session.execute(delete(ApiKeyUsageSnapshot).where(ApiKeyUsageSnapshot.provider == provider))
            session.commit()
        engine.dispose()


def test_busy_snapshot_lock_does_not_delay_accepted_usage():
    import hashlib
    import threading
    import time
    from sqlalchemy import text
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a migrated disposable PostgreSQL')
    engine = create_engine(url)
    provider = f'review-{uuid4().hex}'
    lock_id = int.from_bytes(hashlib.sha256(f'aaim-snapshot:{provider}:fixture'.encode()).digest()[:8], 'big', signed=True)
    ready = threading.Event()
    release = threading.Event()
    def hold_lock():
        with engine.begin() as connection:
            connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key':lock_id})
            ready.set()
            release.wait(timeout=1)
    health = KeyHealth(key_id='fixture', usage_count=1, quota_limit=100,
        status='active', last_status=200, last_error=None, updated_at_epoch=1)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(hold_lock)
            assert ready.wait(timeout=2)
            try:
                started = time.monotonic()
                with Session(engine) as session:
                    _snapshot_health(provider=provider, health_items=[health], session=session)
                assert time.monotonic() - started < 0.5
                with Session(engine) as session:
                    assert session.exec(select(ApiKeyUsageSnapshot).where(ApiKeyUsageSnapshot.provider == provider)).all() == []
            finally:
                release.set()
                holder.result(timeout=2)
    finally:
        with Session(engine) as session:
            session.execute(delete(ApiKeyUsageSnapshot).where(ApiKeyUsageSnapshot.provider == provider))
            session.commit()
        engine.dispose()
