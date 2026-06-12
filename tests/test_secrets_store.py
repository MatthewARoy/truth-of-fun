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
