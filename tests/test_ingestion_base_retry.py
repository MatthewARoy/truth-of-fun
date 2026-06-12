"""BaseSource._get_json retries 429/5xx responses with exponential backoff."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.ingestion.base import BaseSource


class _ProbeSource(BaseSource):
    source_name = "probe"
    source_tier = 1

    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []


def _client_with_responses(status_codes: list[int]) -> tuple[httpx.AsyncClient, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = status_codes[min(len(calls), len(status_codes) - 1)]
        calls.append(status)
        body = {"ok": True} if status == 200 else {"error": status}
        return httpx.Response(status, json=body)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport), calls


def test_get_json_retries_429_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.ingestion.base.asyncio.sleep", fake_sleep)

    client, calls = _client_with_responses([429, 429, 200])
    source = _ProbeSource(client=client)

    payload = asyncio.run(source._get_json("https://api.example.com/events"))

    assert payload == {"ok": True}
    assert calls == [429, 429, 200]
    # Exponential: each retry waits longer than the previous one.
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0] > 0


def test_get_json_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("app.ingestion.base.asyncio.sleep", fake_sleep)

    client, calls = _client_with_responses([429])
    source = _ProbeSource(client=client)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(source._get_json("https://api.example.com/events"))
    assert len(calls) >= 3  # original attempt plus retries


def test_get_json_does_not_retry_client_errors() -> None:
    client, calls = _client_with_responses([404])
    source = _ProbeSource(client=client)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(source._get_json("https://api.example.com/events"))
    assert calls == [404]
