from __future__ import annotations

from collections import defaultdict

from app.core.config import Settings
from app.services.secrets_store import SecretsStore


class _FakeRedis:
    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = defaultdict(set)
        self._hashes: dict[str, dict[str, str | int]] = defaultdict(dict)

    def ping(self) -> bool:
        return True

    def sadd(self, key: str, value: str) -> None:
        self._sets[key].add(value)

    def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    def hset(self, key: str, mapping: dict[str, str | int]) -> None:
        self._hashes[key].update(mapping)

    def hsetnx(self, key, field, value):
        if field not in self._hashes[key]:
            self._hashes[key][field] = value
            return 1
        return 0

    def hgetall(self, key: str) -> dict[str, str | int]:
        return dict(self._hashes.get(key, {}))

    def hget(self, key: str, field: str) -> str | int | None:
        return self._hashes.get(key, {}).get(field)

    def hincrby(self, key: str, field: str, amount: int) -> int:
        current = int(self._hashes[key].get(field, 0) or 0)
        self._hashes[key][field] = current + int(amount)
        return current + int(amount)

    def exists(self, key: str) -> int:
        return 1 if self._hashes.get(key) else 0


    def eval(self, script, numkeys, key, *args):
        """Transport double; actual script/concurrency tests use TEST_REDIS_URL."""
        from app.services.secrets_store import _REPORT_USAGE_LUA, _RESET_EXHAUSTED_LUA, _SYNC_ENV_QUOTA_LUA
        assert numkeys == 1
        if script == _SYNC_ENV_QUOTA_LUA:
            quota = int(args[0])
            self.hsetnx(key, 'usage_count', 0)
            self.hsetnx(key, 'status', 'active')
            self.hset(key, {'quota_limit': quota})
            if self.hget(key, 'status') != 'disabled':
                status = 'exhausted' if quota > 0 and int(self.hget(key, 'usage_count')) >= quota else 'active'
                self.hset(key, {'status': status})
            return 1
        if script == _REPORT_USAGE_LUA:
            if not self.exists(key):
                return 0
            calls, default_quota, disable, last_status, last_error, now = args
            usage = self.hincrby(key, 'usage_count', int(calls))
            quota = int(self.hget(key, 'quota_limit') or default_quota)
            status = self.hget(key, 'status') or 'active'
            if disable == '1' or status == 'disabled':
                status = 'disabled'
            elif quota > 0 and usage >= quota:
                status = 'exhausted'
            self.hset(key, {'status':status, 'last_status':last_status,
                'last_error':last_error, 'updated_at_epoch':now})
            return 1
        assert script == _RESET_EXHAUSTED_LUA
        now, window = args
        if self.hget(key, 'status') != 'exhausted':
            return 0
        if int(now) - int(self.hget(key, 'updated_at_epoch') or 0) < int(window):
            return 0
        self.hset(key, {'usage_count':0, 'status':'active', 'last_error':'', 'updated_at_epoch':now})
        return 1


def _settings(**overrides: object) -> Settings:
    payload = {
        "aaim_fallback_to_env": True,
        "ticketmaster_api_key": "env-key",
        "aaim_ticketmaster_quota_limit": 10,
        "aaim_redis_prefix": "aaim-test",
    }
    payload.update(overrides)
    return Settings.model_validate(payload)


def test_least_used_active_key_is_selected() -> None:
    store = SecretsStore(settings=_settings(), redis_client=_FakeRedis())
    store.seed_key(provider="ticketmaster", key_id="key-a", api_key="api-a", quota_limit=10)
    store.seed_key(provider="ticketmaster", key_id="key-b", api_key="api-b", quota_limit=10)
    store.report_usage(provider="ticketmaster", key_id="key-a", calls=5)
    store.report_usage(provider="ticketmaster", key_id="key-b", calls=2)

    lease = store.get_active_key("ticketmaster")

    assert lease.key_id == "key-b"
    assert lease.api_key == "api-b"


def test_exhausted_key_is_skipped() -> None:
    store = SecretsStore(settings=_settings(), redis_client=_FakeRedis())
    store.seed_key(provider="ticketmaster", key_id="key-a", api_key="api-a", quota_limit=3)
    store.seed_key(provider="ticketmaster", key_id="key-b", api_key="api-b", quota_limit=10)
    store.report_usage(provider="ticketmaster", key_id="key-a", calls=3)

    lease = store.get_active_key("ticketmaster")

    assert lease.key_id == "key-b"


def test_env_fallback_used_when_redis_empty() -> None:
    store = SecretsStore(settings=_settings(ticketmaster_api_key="fallback-key"), redis_client=_FakeRedis())

    lease = store.get_active_key("ticketmaster")

    assert lease.source == "env"
    assert lease.api_key == "fallback-key"


def test_environment_usage_is_metered_without_storing_the_credential():
    import pytest
    redis = _FakeRedis()
    store = SecretsStore(settings=_settings(), redis_client=redis)
    lease = store.get_active_key("ticketmaster")
    store.report_usage(provider="ticketmaster", key_id=lease.key_id, calls=10, last_status=200)
    row = store.health("ticketmaster")[0]
    assert row.key_id == "env-ticketmaster"
    assert row.usage_count == 10
    assert row.status == "exhausted"
    assert row.last_status == 200
    assert "env-key" not in repr(redis._hashes)
    assert redis.smembers(store._ids_key("ticketmaster")) == set()
    with pytest.raises(RuntimeError):
        store.get_active_key("ticketmaster")
    assert store.reset_exhausted_keys("ticketmaster", window_seconds=1, now=row.updated_at_epoch+2) == ["env-ticketmaster"]
    assert store.get_active_key("ticketmaster").usage_count == 0


def test_targeted_health_does_not_enumerate_other_keys(monkeypatch):
    redis = _FakeRedis()
    store = SecretsStore(settings=_settings(), redis_client=redis)
    store.seed_key(provider='ticketmaster', key_id='key-a', api_key='fixture-a')
    store.seed_key(provider='ticketmaster', key_id='key-b', api_key='fixture-b')
    def no_inventory_scan(*args):
        raise AssertionError('Targeted telemetry must not scan the key inventory')
    monkeypatch.setattr(redis, 'smembers', no_inventory_scan)
    assert [item.key_id for item in store.health('ticketmaster', key_id=' key-a ')] == ['key-a']
    assert store.health('ticketmaster', key_id='missing') == []


class _SpyRedis(_FakeRedis):
    """Records calls so tests can assert usage counting is atomic (HINCRBY)."""

    def __init__(self) -> None:
        super().__init__()
        self.hincrby_calls: list[tuple[str, str, int]] = []
        self.hset_usage_writes: int = 0

    def hincrby(self, key: str, field: str, amount: int) -> int:
        self.hincrby_calls.append((key, field, amount))
        return super().hincrby(key, field, amount)

    def hset(self, key: str, mapping: dict[str, str | int]) -> None:
        if "usage_count" in mapping:
            self.hset_usage_writes += 1
        super().hset(key, mapping)


def test_report_usage_increments_atomically() -> None:
    """usage_count must go through HINCRBY, not read-modify-write via HSET."""
    redis = _SpyRedis()
    store = SecretsStore(settings=_settings(), redis_client=redis)
    store.seed_key(provider="ticketmaster", key_id="key-a", api_key="api-a", quota_limit=10)
    seed_writes = redis.hset_usage_writes

    store.report_usage(provider="ticketmaster", key_id="key-a", calls=2)
    store.report_usage(provider="ticketmaster", key_id="key-a", calls=3)

    health = {item.key_id: item for item in store.health("ticketmaster")}
    assert health["key-a"].usage_count == 5
    assert len(redis.hincrby_calls) == 2
    # No read-modify-write of usage_count after seeding.
    assert redis.hset_usage_writes == seed_writes


def test_report_usage_marks_exhausted_when_crossing_quota() -> None:
    redis = _SpyRedis()
    store = SecretsStore(settings=_settings(), redis_client=redis)
    store.seed_key(provider="ticketmaster", key_id="key-a", api_key="api-a", quota_limit=3)

    store.report_usage(provider="ticketmaster", key_id="key-a", calls=3)

    health = {item.key_id: item for item in store.health("ticketmaster")}
    assert health["key-a"].status == "exhausted"


def test_reset_exhausted_keys_reactivates_after_quota_window() -> None:
    store = SecretsStore(settings=_settings(), redis_client=_FakeRedis())
    store.seed_key(provider="ticketmaster", key_id="key-a", api_key="api-a", quota_limit=3)
    store.report_usage(provider="ticketmaster", key_id="key-a", calls=3)

    exhausted_at = {h.key_id: h for h in store.health("ticketmaster")}["key-a"].updated_at_epoch
    window = 3600

    # Still inside the quota window: nothing is reset.
    assert (
        store.reset_exhausted_keys(
            "ticketmaster", window_seconds=window, now=exhausted_at + window - 1
        )
        == []
    )
    assert {h.key_id: h.status for h in store.health("ticketmaster")}["key-a"] == "exhausted"

    # Window has elapsed: the key reactivates with its usage cleared.
    reset = store.reset_exhausted_keys(
        "ticketmaster", window_seconds=window, now=exhausted_at + window
    )
    assert reset == ["key-a"]
    refreshed = {h.key_id: h for h in store.health("ticketmaster")}
    assert refreshed["key-a"].status == "active"
    assert refreshed["key-a"].usage_count == 0
    # And it can be leased again.
    assert store.get_active_key("ticketmaster").key_id == "key-a"


def test_reset_exhausted_keys_leaves_disabled_keys_untouched() -> None:
    store = SecretsStore(settings=_settings(), redis_client=_FakeRedis())
    store.seed_key(provider="ticketmaster", key_id="key-a", api_key="api-a", quota_limit=10)
    # Deliberately disabled keys must not be auto-reactivated by quota windows.
    store.report_usage(provider="ticketmaster", key_id="key-a", disable=True)
    disabled_at = {h.key_id: h for h in store.health("ticketmaster")}["key-a"].updated_at_epoch

    reset = store.reset_exhausted_keys(
        "ticketmaster", window_seconds=1, now=disabled_at + 10_000
    )

    assert reset == []
    assert {h.key_id: h.status for h in store.health("ticketmaster")}["key-a"] == "disabled"


def test_delayed_usage_cannot_reenable_an_intentionally_disabled_key():
    store = SecretsStore(settings=_settings(), redis_client=_FakeRedis())
    store.seed_key(provider='ticketmaster', key_id='key-a', api_key='fixture', quota_limit=3)
    store.report_usage(provider='ticketmaster', key_id='key-a', calls=1, disable=True)
    store.report_usage(provider='ticketmaster', key_id='key-a', calls=2)
    row = store.health('ticketmaster')[0]
    assert row.status == 'disabled'
    assert store.reset_exhausted_keys('ticketmaster', window_seconds=1, now=row.updated_at_epoch+2) == []


def test_disabled_inventory_does_not_fall_back_to_unmetered_environment_key():
    import pytest
    store = SecretsStore(settings=_settings(), redis_client=_FakeRedis())
    store.seed_key(provider='ticketmaster', key_id='key-a', api_key='fixture')
    store.report_usage(provider='ticketmaster', key_id='key-a', disable=True)
    with pytest.raises(RuntimeError, match='No active API keys'):
        store.get_active_key('ticketmaster')


def test_failed_store_initialization_recovers_after_bounded_retry(monkeypatch):
    from redis.exceptions import ConnectionError
    from app.services import secrets_store as module
    clock = [100.0]
    redis = _FakeRedis()
    pings = []
    def ping():
        pings.append(1)
        if len(pings) == 1:
            raise ConnectionError('fixture outage')
        return True
    redis.ping = ping
    monkeypatch.setattr(module, 'get_settings', lambda: _settings())
    monkeypatch.setattr(module.Redis, 'from_url', lambda *args, **kwargs: redis)
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    clear_cache = getattr(module, '_cached_secrets_store', module.get_secrets_store).cache_clear
    clear_cache()
    try:
        assert isinstance(module.get_secrets_store(), module.NoopSecretsStore)
        assert isinstance(module.get_secrets_store(), module.NoopSecretsStore)
        assert len(pings) == 1
        clock[0] += 31
        assert not isinstance(module.get_secrets_store(), module.NoopSecretsStore)
        assert len(pings) == 2
    finally:
        clear_cache()


def test_env_quota_configuration_changes_preserve_usage_and_disable():
    import pytest
    store = SecretsStore(settings=_settings(), redis_client=_FakeRedis())
    store.get_active_key('ticketmaster')
    store.report_usage(provider='ticketmaster', key_id='env-ticketmaster', calls=5)
    store._settings = _settings(aaim_ticketmaster_quota_limit=4)
    with pytest.raises(RuntimeError):
        store.get_active_key('ticketmaster')
    assert store.health('ticketmaster')[0].quota_limit == 4
    store._settings = _settings(aaim_ticketmaster_quota_limit=8)
    assert store.get_active_key('ticketmaster').usage_count == 5
    store.report_usage(provider='ticketmaster', key_id='env-ticketmaster', calls=0, disable=True)
    store._settings = _settings(aaim_ticketmaster_quota_limit=100)
    with pytest.raises(RuntimeError):
        store.get_active_key('ticketmaster')
    assert store.health('ticketmaster')[0].status == 'disabled'
