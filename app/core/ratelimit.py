"""Inbound per-client rate limiting for abuse-prone endpoints.

The limits guard three things: LLM spend (concierge/onboarding call Anthropic
per request), credential stuffing (login/register), and unauthenticated row
creation (itinerary sharing). Windows are in-process, so the caps apply per
API replica — the reference deployment runs one. Behind a reverse proxy the
client address is only correct when uvicorn runs with --proxy-headers.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from functools import lru_cache

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


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


def _enforce(limiter: SlidingWindowLimiter, request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    retry_after = limiter.hit(key)
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
