from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings


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
        self._redis = redis_client or Redis.from_url(self._settings.redis_url, decode_responses=True)

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
            return KeyLease(
                provider=provider,
                key_id="env-ticketmaster",
                api_key=self._settings.ticketmaster_api_key,
                usage_count=0,
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
        if normalized_key_id.startswith("env-"):
            return

        key_hash = self._key_hash(normalized_provider, normalized_key_id)
        if not self._redis.exists(key_hash):
            raise KeyError(f"Unknown key_id '{normalized_key_id}' for provider '{normalized_provider}'.")

        # HINCRBY is atomic, so concurrent reporters (worker + API bots) never
        # lose increments the way a read-modify-write would.
        next_usage = int(self._redis.hincrby(key_hash, "usage_count", max(0, int(calls))))
        quota_limit = self._coerce_int(
            self._redis.hget(key_hash, "quota_limit"), self._default_quota(normalized_provider)
        )
        next_status = self._redis.hget(key_hash, "status") or "active"

        if disable:
            next_status = "disabled"
        elif quota_limit > 0 and next_usage >= quota_limit:
            next_status = "exhausted"

        self._redis.hset(
            key_hash,
            mapping={
                "status": next_status,
                "last_status": "" if last_status is None else str(last_status),
                "last_error": last_error or "",
                "updated_at_epoch": int(time.time()),
            },
        )

    def health(self, provider: str) -> list[KeyHealth]:
        normalized_provider = provider.strip().lower()
        key_ids = sorted(self._redis.smembers(self._ids_key(normalized_provider)))
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

    def health(self, provider: str) -> list[KeyHealth]:
        return []


@lru_cache(maxsize=1)
def get_secrets_store() -> SecretsStore:
    settings = get_settings()
    try:
        store = SecretsStore(settings=settings)
        store._redis.ping()
        return store
    except RedisError:
        return NoopSecretsStore(settings=settings)
