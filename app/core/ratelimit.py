"""Inbound per-client rate limiting for abuse-prone endpoints.

The limits guard three things: LLM spend (concierge/onboarding call Anthropic
per request), credential stuffing (login/register), and excessive snapshot row
creation (itinerary sharing). Behind a reverse proxy the client address is
only correct when uvicorn runs with --proxy-headers.

Two backends, chosen by ``RATE_LIMIT_BACKEND``:

- ``memory`` (default): windows live in the process. Correct for one API
  process; with N uvicorn workers or replicas every client gets N times the
  cap, and a restart forgets everything.
- ``redis``: one sliding window per client in Redis (``REDIS_URL``), shared by
  every process. If Redis is unreachable the request falls back to the
  in-process window rather than failing or going unlimited — a degraded cap
  is better than either an outage or an open LLM bill.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from functools import lru_cache
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Atomic sliding window on a sorted set scored by arrival time (ms).
# KEYS[1] window key; ARGV: now_ms, window_ms, limit, unique member.
# Returns 0 when the hit is admitted, else milliseconds until a slot frees.
_REDIS_SLIDING_WINDOW = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return math.max(1, tonumber(oldest[2]) + window - now)
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return 0
"""


class SlidingWindowLimiter:
    """Sliding-window counter keyed by client address. A limit of 0 disables."""

    _registry: list["SlidingWindowLimiter"] = []

    def __init__(self, *, name: str, limit: int, window_seconds: float) -> None:
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = 0.0
        SlidingWindowLimiter._registry.append(self)

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Record one request; return None if allowed, else seconds to wait."""
        if self.limit <= 0:
            return None
        if now is None:
            now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            self._sweep(cutoff, now)
            window = self._hits.setdefault(key, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.limit:
                return window[0] + self.window_seconds - now
            window.append(now)
            return None

    def _sweep(self, cutoff: float, now: float) -> None:
        # Drop idle clients so the map doesn't grow without bound.
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        stale = [key for key, window in self._hits.items() if not window or window[-1] <= cutoff]
        for key in stale:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    @classmethod
    def reset_all(cls) -> None:
        for limiter in cls._registry:
            limiter.reset()


@lru_cache(maxsize=1)
def get_llm_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        name="llm",
        limit=get_settings().rate_limit_llm_per_hour,
        window_seconds=3600,
    )


@lru_cache(maxsize=1)
def get_share_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        name="share",
        limit=get_settings().rate_limit_share_per_hour,
        window_seconds=3600,
    )


@lru_cache(maxsize=1)
def get_auth_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        name="auth",
        limit=get_settings().rate_limit_auth_per_quarter_hour,
        window_seconds=15 * 60,
    )


@lru_cache(maxsize=1)
def _redis_client() -> Any | None:
    """Shared Redis handle for rate limiting, or None for the memory backend."""
    settings = get_settings()
    if settings.rate_limit_backend != "redis":
        return None
    from redis import Redis

    # Short timeouts: this sits in front of every limited request, and a slow
    # Redis must degrade to the in-process window, not stall logins.
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


_redis_unavailable_logged_at = 0.0


def _redis_hit(client: Any, limiter: SlidingWindowLimiter, key: str) -> float | None:
    """Record one hit in the shared window; None if allowed, else seconds to wait."""
    prefix = get_settings().rate_limit_redis_prefix
    wait_ms = client.eval(
        _REDIS_SLIDING_WINDOW,
        1,
        f"{prefix}:{limiter.name}:{key}",
        int(time.time() * 1000),
        int(limiter.window_seconds * 1000),
        limiter.limit,
        uuid4().hex,
    )
    return None if not wait_ms else float(wait_ms) / 1000.0


def _hit(limiter: SlidingWindowLimiter, key: str) -> float | None:
    global _redis_unavailable_logged_at
    client = _redis_client() if limiter.limit > 0 else None
    if client is not None:
        try:
            return _redis_hit(client, limiter, key)
        except Exception as exc:
            # Once a minute is enough to notice; every request would bury it.
            now = time.monotonic()
            if now - _redis_unavailable_logged_at > 60:
                _redis_unavailable_logged_at = now
                logger.warning(
                    "Rate-limit Redis unavailable (%s); using in-process windows.",
                    type(exc).__name__,
                )
    return limiter.hit(key)


def _enforce(limiter: SlidingWindowLimiter, request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    retry_after = _hit(limiter, key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later.",
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )


def llm_rate_limit(request: Request) -> None:
    _enforce(get_llm_limiter(), request)


def share_rate_limit(request: Request) -> None:
    _enforce(get_share_limiter(), request)


def auth_rate_limit(request: Request) -> None:
    _enforce(get_auth_limiter(), request)
