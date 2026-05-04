from collections import deque
import asyncio
import time


class AsyncRateLimiter:
    """Simple sliding-window limiter for async requests."""

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self._max_calls = max_calls
        self._period_seconds = period_seconds
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._calls and (now - self._calls[0]) >= self._period_seconds:
                    self._calls.popleft()

                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return

                wait_for = self._period_seconds - (now - self._calls[0])

            await asyncio.sleep(max(wait_for, 0))
