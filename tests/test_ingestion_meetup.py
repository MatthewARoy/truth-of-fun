from __future__ import annotations

from app.ingestion.sources.meetup import MeetupSource
import pytest
import httpx


@pytest.mark.anyio
async def test_missing_token_is_explicit_and_does_not_call_provider(monkeypatch):
    monkeypatch.delenv("MEETUP_API_TOKEN", raising=False)
    source = MeetupSource()
    def no_client():
        raise AssertionError("Disabled source must not make requests")
    monkeypatch.setattr(source, "_get_client", no_client)
    assert await source.fetch_events() == []
    assert "disabled" in source.last_fetch_error.lower()
    assert "MEETUP_API_TOKEN" in source.last_fetch_error


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [
    {"errors": [{"message": "private secret error"}]},
    {"data": {"keywordSearch": None}},
])
async def test_graphql_errors_and_schema_failures_do_not_look_empty(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    )) as client:
        source = MeetupSource(api_token="fixture", client=client)
        with pytest.raises(ValueError):
            await source.fetch_events()


@pytest.mark.anyio
async def test_empty_graphql_edges_report_a_quiet_result():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": {"keywordSearch": {"edges": []}}})
    )) as client:
        source = MeetupSource(api_token="fixture", client=client)
        assert await source.fetch_events() == []
        assert source.last_fetch_error is None
        assert "empty" in source.last_empty_reason.lower()


def test_meetup_normalize_raw_to_canonical_payload() -> None:
    source = MeetupSource(api_token="test-token")
    raw = {
        "id": "m_123",
        "title": "SF Builders Meetup",
        "eventUrl": "https://www.meetup.com/sf-builders/events/123/",
        "dateTime": "2026-06-01T01:00:00Z",
        "endTime": "2026-06-01T03:00:00Z",
        "description": "A meetup for founders and builders.",
        "venue": {
            "name": "SoMa Hub",
            "address": "123 Howard St",
            "city": "San Francisco",
            "lat": 37.789,
            "lon": -122.397,
        },
        "group": {"name": "SF Builders", "url": "https://www.meetup.com/sf-builders/"},
        "topics": ["startup", "networking"],
    }

    event = source.normalize_raw(raw)
    assert event is not None
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "meetup"
    assert payload["source_tier"] == 1
    assert payload["source_event_id"] == "m_123"
    assert payload["title"] == "SF Builders Meetup"
    assert payload["location"] == "POINT(-122.397 37.789)"
