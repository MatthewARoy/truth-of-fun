from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.ingestion.sources.reddit import RedditSource


def _post(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "abc123",
        "subreddit": "AskSF",
        "title": "Weekend happenings thread",
        "selftext": "My band is playing at The Knockout this Friday 8pm. Come through!",
        "permalink": "/r/AskSF/comments/abc123/weekend_happenings/",
        "created_utc": datetime(2026, 1, 14, 20, 0, tzinfo=timezone.utc).timestamp(),
        "score": 42,
        "num_comments": 12,
    }
    base.update(overrides)
    return base


def test_reddit_normalize_raw_from_comment_text() -> None:
    source = RedditSource()
    event = source.normalize_raw(_post())
    assert event is not None
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "reddit"
    assert payload["source_tier"] == 3
    assert payload["source_event_id"] == "abc123"
    assert payload["external_url"].startswith("https://www.reddit.com/r/AskSF/comments/abc123/")
    assert payload["title"].startswith("My band is playing at The Knockout")
    assert payload["venue_name"] == "The Knockout"


def test_heuristic_path_records_honest_provenance() -> None:
    """Without an LLM, records must not claim llm_extract provenance."""
    source = RedditSource()
    event = source.normalize_raw(_post())
    assert event is not None
    assert event.source.capture_mode == "api"
    assert event.quality.llm_extracted is False


def test_heuristic_path_geocodes_known_venues() -> None:
    source = RedditSource()
    event = source.normalize_raw(_post())
    assert event is not None
    # "the knockout" is in the static venue cache; must not be city-center.
    assert (event.location.lat, event.location.lon) == (37.7454, -122.4214)


def test_question_posts_are_not_events() -> None:
    """'What to do this weekend?' is a question, not an event."""
    source = RedditSource()
    post = _post(
        selftext="What to do this weekend? Looking for fun stuff in the city.",
        title="What to do this weekend?",
    )
    assert source.normalize_raw(post) is None


def test_posts_without_venue_or_time_are_dropped() -> None:
    source = RedditSource()
    post = _post(selftext="I love this city so much, the fog is amazing on saturday mornings.")
    assert source.normalize_raw(post) is None


class _FakeLLMClient:
    """Mimics anthropic.AsyncAnthropic for messages.create."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

        async def _create(**kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(self._reply))]
            )

        self.messages = SimpleNamespace(create=_create)


def test_llm_extraction_path_produces_event_with_llm_provenance() -> None:
    client = _FakeLLMClient(
        {
            "is_event": True,
            "confidence": 0.9,
            "title": "Secret loft show at The Chapel",
            "venue": "The Chapel",
            "date_phrase": "this friday",
            "time": "8pm",
        }
    )
    source = RedditSource(llm_client=client)

    raw = asyncio.run(source.extract_candidate(_post()))
    assert raw is not None
    event = source.normalize_raw(raw)
    assert event is not None
    assert event.source.capture_mode == "llm_extract"
    assert event.quality.llm_extracted is True
    assert event.title == "Secret loft show at The Chapel"
    assert event.location.venue_name == "The Chapel"
    # geocoded from the venue cache
    assert (event.location.lat, event.location.lon) == (37.7608, -122.4214)
    assert len(client.calls) == 1


def test_llm_rejection_drops_the_post() -> None:
    client = _FakeLLMClient({"is_event": False, "confidence": 0.95})
    source = RedditSource(llm_client=client)

    raw = asyncio.run(source.extract_candidate(_post()))
    assert raw is None or source.normalize_raw(raw) is None
