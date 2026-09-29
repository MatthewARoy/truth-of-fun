from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
_REDIS_RETRY_SECONDS = 30.0
_store_lock = threading.Lock()

# Each transition is atomic with respect to usage reporters and quota resets.
# An ordinary HGET/HSET sequence can overwrite an operator's concurrent disable.
_REPORT_USAGE_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
local usage = redis.call('HINCRBY', KEYS[1], 'usage_count', ARGV[1])
local quota = tonumber(redis.call('HGET', KEYS[1], 'quota_limit')) or tonumber(ARGV[2])
local status = redis.call('HGET', KEYS[1], 'status') or 'active'
if ARGV[3] == '1' or status == 'disabled' then
    status = 'disabled'
elseif quota > 0 and usage >= quota then
    status = 'exhausted'
end
redis.call('HSET', KEYS[1], 'status', status, 'last_status', ARGV[4],
    'last_error', ARGV[5], 'updated_at_epoch', ARGV[6])
return 1
"""

_RESET_EXHAUSTED_LUA = """
if redis.call('HGET', KEYS[1], 'status') ~= 'exhausted' then return 0 end
local updated = tonumber(redis.call('HGET', KEYS[1], 'updated_at_epoch')) or 0
if tonumber(ARGV[1]) - updated < tonumber(ARGV[2]) then return 0 end
redis.call('HSET', KEYS[1], 'usage_count', 0, 'status', 'active',
    'last_error', '', 'updated_at_epoch', ARGV[1])
return 1
"""


@dataclass
class KeyLease:
    provider: str
    key_id: str
    api_key: str
    usage_count: int
    quota_limit: int
    status: str
    source: str


@dataclass
class KeyHealth:
    key_id: str
    usage_count: int
    quota_limit: int
    status: str
    last_status: int | None
    last_error: str | None
    updated_at_epoch: int


class SecretsStore:
    """Redis-backed API key store with simple least-used rotation semantics."""

    def __init__(self, *, settings: Settings | None = None, redis_client: Redis | None = None) -> None:
        self._settings = settings or get_settings()
        self._prefix = self._settings.aaim_redis_prefix
        self._redis = redis_client or Redis.from_url(
            self._settings.redis_url, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )

    def _ids_key(self, provider: str) -> str:
        return f"{self._prefix}:keys:{provider}:ids"

    def _key_hash(self, provider: str, key_id: str) -> str:
        return f"{self._prefix}:keys:{provider}:{key_id}"

    def _default_quota(self, provider: str) -> int:
        if provider == "ticketmaster":
            return self._settings.aaim_ticketmaster_quota_limit
        return self._settings.aaim_ticketmaster_quota_limit

    def _coerce_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def seed_key(self, *, provider: str, key_id: str, api_key: str, quota_limit: int | None = None) -> None:
        normalized_provider = provider.strip().lower()
        normalized_key_id = key_id.strip()
        if not normalized_provider or not normalized_key_id or not api_key:
            raise ValueError("provider, key_id, and api_key are required")
        if normalized_key_id.startswith("env-"):
            raise ValueError("env- key identifiers are reserved for environment telemetry")

        quota = quota_limit if quota_limit is not None else self._default_quota(normalized_provider)
        now = int(time.time())
        key_hash = self._key_hash(normalized_provider, normalized_key_id)
        self._redis.sadd(self._ids_key(normalized_provider), normalized_key_id)
        self._redis.hset(
            key_hash,
            mapping={
                "api_key": api_key,
                "usage_count": 0,
                "quota_limit": quota,
                "status": "active",
                "last_status": "",
                "last_error": "",
                "updated_at_epoch": now,
            },
        )

    def _fallback_env_key(self, provider: str) -> KeyLease | None:
        if not self._settings.aaim_fallback_to_env:
            return None
        if provider == "ticketmaster" and self._settings.ticketmaster_api_key:
            usage, status = 0, "active"
            if self._redis is not None:
                # Track fallback usage without copying the environment secret
                # into Redis or adding it to the rotation inventory. HSETNX
                # leaves concurrent reporters and deliberate disables intact.
                key_hash = self._key_hash(provider, "env-ticketmaster")
                for field, value in {"usage_count": 0, "quota_limit": self._default_quota(provider), "status": "active"}.items():
                    self._redis.hsetnx(key_hash, field, value)
                payload = self._redis.hgetall(key_hash)
                usage = self._coerce_int(payload.get("usage_count"))
                status = payload.get("status", "active")
                quota = self._coerce_int(payload.get("quota_limit"), self._default_quota(provider))
                if status != "active" or (quota > 0 and usage >= quota):
                    return None
            return KeyLease(
                provider=provider,
                key_id="env-ticketmaster",
                api_key=self._settings.ticketmaster_api_key,
                usage_count=usage,
                quota_limit=self._default_quota(provider),
                status="active",
                source="env",
            )
        return None

    def get_active_key(self, provider: str) -> KeyLease:
        normalized_provider = provider.strip().lower()
        key_ids = sorted(self._redis.smembers(self._ids_key(normalized_provider)))
        lease_candidates: list[KeyLease] = []

        for key_id in key_ids:
            payload = self._redis.hgetall(self._key_hash(normalized_provider, key_id))
            if not payload:
                continue
            api_key = payload.get("api_key")
            if not api_key:
                continue
            status = payload.get("status", "active")
            usage_count = self._coerce_int(payload.get("usage_count"), 0)
            quota_limit = self._coerce_int(payload.get("quota_limit"), self._default_quota(normalized_provider))

            if status != "active":
                continue
            if quota_limit > 0 and usage_count >= quota_limit:
                continue

            lease_candidates.append(
                KeyLease(
                    provider=normalized_provider,
                    key_id=key_id,
                    api_key=api_key,
                    usage_count=usage_count,
                    quota_limit=quota_limit,
                    status=status,
                    source="redis",
                )
            )

        if lease_candidates:
            lease_candidates.sort(key=lambda item: (item.usage_count, item.key_id))
            return lease_candidates[0]

        # A configured inventory with disabled/exhausted keys must fail closed;
        # using the environment key here would bypass the same quota/disable.
        if not key_ids:
            fallback = self._fallback_env_key(normalized_provider)
            if fallback is not None:
                return fallback
        raise RuntimeError(f"No active API keys available for provider '{normalized_provider}'.")

    def report_usage(
        self,
        *,
        provider: str,
        key_id: str,
        calls: int = 1,
        last_status: int | None = None,
        last_error: str | None = None,
        disable: bool = False,
    ) -> None:
        normalized_provider = provider.strip().lower()
        normalized_key_id = key_id.strip()
        if not normalized_provider or not normalized_key_id:
            raise ValueError("provider and key_id are required")
        key_hash = self._key_hash(normalized_provider, normalized_key_id)
        updated = self._redis.eval(
            _REPORT_USAGE_LUA, 1, key_hash,
            max(0, int(calls)), self._default_quota(normalized_provider),
            "1" if disable else "0",
            "" if last_status is None else str(last_status),
            last_error or "", int(time.time()),
        )
        if not updated:
            raise KeyError(f"Unknown key_id '{normalized_key_id}' for provider '{normalized_provider}'.")

    def reset_exhausted_keys(
        self, provider: str, *, window_seconds: int, now: int | None = None
    ) -> list[str]:
        """Reactivate keys whose quota window has elapsed since they exhausted.

        Quota limits are rate windows (e.g. a daily cap), so an exhausted key
        becomes usable again once the window rolls over. We treat
        ``updated_at_epoch`` as the moment of exhaustion (an exhausted key is no
        longer leased, so its timestamp stops advancing). Only ``exhausted`` keys
        are eligible — ``disabled`` keys were turned off deliberately and are left
        alone. Returns the key_ids that were reactivated.
        """
        if window_seconds <= 0:
            return []
        normalized_provider = provider.strip().lower()
        current = now if now is not None else int(time.time())
        reset_ids: list[str] = []
        key_ids = set(self._redis.smembers(self._ids_key(normalized_provider)))
        if self._redis.exists(self._key_hash(normalized_provider, "env-ticketmaster")):
            key_ids.add("env-ticketmaster")
        for key_id in sorted(key_ids):
            key_hash = self._key_hash(normalized_provider, key_id)
            if self._redis.eval(_RESET_EXHAUSTED_LUA, 1, key_hash, current, window_seconds):
                reset_ids.append(key_id)
        return reset_ids

    def health(self, provider: str, *, key_id: str | None = None) -> list[KeyHealth]:
        normalized_provider = provider.strip().lower()
        # Usage telemetry needs only its reported key; avoid one Redis read per
        # inventory entry on every API report. Operator/cycle health reads all.
        key_ids = (
            [key_id.strip()] if key_id is not None
            else sorted(self._redis.smembers(self._ids_key(normalized_provider)))
        )
        if key_id is None and self._redis.exists(self._key_hash(normalized_provider, "env-ticketmaster")):
            key_ids = sorted(set(key_ids) | {"env-ticketmaster"})
        results: list[KeyHealth] = []
        for key_id in key_ids:
            payload = self._redis.hgetall(self._key_hash(normalized_provider, key_id))
            if not payload:
                continue
            last_status_raw = payload.get("last_status")
            last_status = self._coerce_int(last_status_raw, 0) if last_status_raw else None
            results.append(
                KeyHealth(
                    key_id=key_id,
                    usage_count=self._coerce_int(payload.get("usage_count"), 0),
                    quota_limit=self._coerce_int(
                        payload.get("quota_limit"),
                        self._default_quota(normalized_provider),
                    ),
                    status=payload.get("status", "active"),
                    last_status=last_status,
                    last_error=payload.get("last_error") or None,
                    updated_at_epoch=self._coerce_int(payload.get("updated_at_epoch"), 0),
                )
            )
        return results


class NoopSecretsStore(SecretsStore):
    """Fallback secrets store used when Redis is unavailable."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._prefix = self._settings.aaim_redis_prefix
        self._redis = None
        self.retry_at = time.monotonic() + _REDIS_RETRY_SECONDS

    def seed_key(self, *, provider: str, key_id: str, api_key: str, quota_limit: int | None = None) -> None:
        raise RuntimeError("Cannot seed keys: Redis is unavailable.")

    def get_active_key(self, provider: str) -> KeyLease:
        fallback = self._fallback_env_key(provider.strip().lower())
        if fallback is not None:
            return fallback
        raise RuntimeError("No active keys available and Redis is unavailable.")

    def report_usage(
        self,
        *,
        provider: str,
        key_id: str,
        calls: int = 1,
        last_status: int | None = None,
        last_error: str | None = None,
        disable: bool = False,
    ) -> None:
        return

    def reset_exhausted_keys(
        self, provider: str, *, window_seconds: int, now: int | None = None
    ) -> list[str]:
        return []

    def health(self, provider: str, *, key_id: str | None = None) -> list[KeyHealth]:
        return []


@lru_cache(maxsize=1)
def _cached_secrets_store() -> SecretsStore:
    settings = get_settings()
    try:
        store = SecretsStore(settings=settings)
        store._redis.ping()
        return store
    except RedisError:
        logger.warning("Redis secrets store unavailable; retrying initialization in 30 seconds.")
        return NoopSecretsStore(settings=settings)


def get_secrets_store() -> SecretsStore:
    # Serialize failed initialization retries across API threads. Successful
    # clients reconnect normally through redis-py's connection pool.
    with _store_lock:
        store = _cached_secrets_store()
        if isinstance(store, NoopSecretsStore) and time.monotonic() >= store.retry_at:
            _cached_secrets_store.cache_clear()
            store = _cached_secrets_store()
        return store
