"""Real Redis script/concurrency checks; only an explicit disposable test URL is used."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from redis import Redis

from app.core.config import Settings
from app.services.secrets_store import SecretsStore


@pytest.fixture
def store():
    url = os.environ.get('TEST_REDIS_URL')
    if not url:
        pytest.skip('Set TEST_REDIS_URL to a disposable Redis to verify atomic scripts')
    prefix = f'truth-review-{uuid4().hex}'
    redis = Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    redis.ping()
    settings = Settings(_env_file=None, aaim_redis_prefix=prefix, aaim_fallback_to_env=False)
    instance = SecretsStore(settings=settings, redis_client=redis)
    try:
        yield instance
    finally:
        keys = list(redis.scan_iter(match=f'{prefix}:*'))
        if keys:
            redis.delete(*keys)
        redis.close()


def test_concurrent_reports_preserve_all_increments_and_disabled_state(store):
    store.seed_key(provider='fixture', key_id='key', api_key='fake', quota_limit=10)
    def report(index):
        store.report_usage(provider='fixture', key_id='key', calls=1, disable=index == 5)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(report, range(80)))
    health = store.health('fixture')[0]
    assert health.usage_count == 80
    assert health.status == 'disabled'
    assert store.reset_exhausted_keys('fixture', window_seconds=1, now=health.updated_at_epoch+2) == []


def test_quota_reset_cannot_overwrite_concurrent_disable(store):
    for _ in range(16):
        store.seed_key(provider='fixture', key_id='key', api_key='fake', quota_limit=1)
        store.report_usage(provider='fixture', key_id='key', calls=1)
        store._redis.hset(store._key_hash('fixture', 'key'), 'updated_at_epoch', 0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reset = pool.submit(store.reset_exhausted_keys, 'fixture', window_seconds=1, now=int(time.time()))
            disable = pool.submit(store.report_usage, provider='fixture', key_id='key', calls=0, disable=True)
            reset.result()
            disable.result()
        assert store.health('fixture')[0].status == 'disabled'


def test_unknown_key_does_not_create_a_partial_inventory_record(store):
    with pytest.raises(KeyError):
        store.report_usage(provider='fixture', key_id='missing', calls=1)
    assert not store._redis.exists(store._key_hash('fixture', 'missing'))


def test_concurrent_environment_usage_is_durable_and_never_copies_secret(store):
    store._settings = store._settings.model_copy(update={"aaim_fallback_to_env": True, "ticketmaster_api_key": "private-environment-fixture"})
    def report(index):
        lease = store.get_active_key('ticketmaster')
        store.report_usage(provider='ticketmaster', key_id=lease.key_id, calls=1)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(report, range(80)))
    health = store.health('ticketmaster')[0]
    assert health.key_id == 'env-ticketmaster'
    assert health.usage_count == 80
    assert store._redis.smembers(store._ids_key('ticketmaster')) == set()
    assert 'private-environment-fixture' not in str(store._redis.hgetall(store._key_hash('ticketmaster', 'env-ticketmaster')))
