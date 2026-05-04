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
