import asyncio
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.ingestion.rate_limiter import AsyncRateLimiter


class BaseSource(ABC):
    """Common async ingestion source behavior."""

    source_name: str
    source_tier: int

    # Exponential backoff for transient upstream failures (429 / 5xx).
    MAX_RETRIES = 2
    BACKOFF_BASE_SECONDS = 1.0

    #: Request rate used when the caller does not pass one. A listing scraper
    #: that walks many pages per run lowers it so the crawl stays a trickle.
    default_max_requests_per_second: int = 5

    #: Set by a source that recovered from a partial failure rather than
    #: raising — e.g. paginated fetches that return the pages they did get.
    #: The worker reads this after ``fetch_events`` so a partial fetch is
    #: reported as failing instead of looking like a healthy small result.
    #: Sources that raise on failure can leave it None.
    last_fetch_error: str | None = None

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
        max_requests_per_second: int | None = None,
    ) -> None:
        self.last_fetch_error = None
        self._client = client
        self._owns_client = client is None
        self._timeout_seconds = timeout_seconds
        self._limiter = AsyncRateLimiter(
            max_calls=max_requests_per_second or self.default_max_requests_per_second,
            period_seconds=1.0,
        )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "BaseSource":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
        return self._client

    async def _get_with_retry(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            await self._limiter.acquire()
            try:
                response = await self._get_client().get(url, params=params, headers=headers)
            except Exception as exc:
                self._record_request_usage(status_code=None, error_type=type(exc).__name__)
                raise
            self._record_request_usage(
                status_code=response.status_code,
                error_type="HTTPStatusError" if response.is_error else None,
            )
            if (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt < self.MAX_RETRIES:
                await asyncio.sleep(self.BACKOFF_BASE_SECONDS * (2**attempt))
                attempt += 1
                continue
            response.raise_for_status()
            return response

    def _record_request_usage(self, *, status_code: int | None, error_type: str | None) -> None:
        """Optional provider telemetry, once per attempted HTTP request (including retries)."""

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = (await self._get_with_retry(url, params=params)).json()
        if not isinstance(payload, dict):
            raise ValueError(
                f"Expected object JSON from {self.source_name}, got {type(payload)}"
            )
        return payload

    async def _get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        """GET a listing page through the rate limiter, with the same retries."""
        return (await self._get_with_retry(url, headers=headers)).text

    @abstractmethod
    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch events mapped to canonical Event payloads."""
