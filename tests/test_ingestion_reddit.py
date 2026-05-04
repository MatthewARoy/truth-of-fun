from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion.sources.reddit import RedditSource


def test_reddit_normalize_raw_from_comment_text() -> None:
    source = RedditSource()
    raw = {
        "id": "abc123",
        "subreddit": "AskSF",
        "title": "Weekend happenings thread",
        "selftext": "My band is playing at The Knockout this Friday 8pm. Come through!",
        "permalink": "/r/AskSF/comments/abc123/weekend_happenings/",
        "created_utc": datetime(2026, 1, 14, 20, 0, tzinfo=timezone.utc).timestamp(),
        "score": 42,
        "num_comments": 12,
    }

    event = source.normalize_raw(raw)
    assert event is not None
    payload = event.to_legacy_event_payload(source_tier=source.source_tier)
    assert payload["source_name"] == "reddit"
    assert payload["source_tier"] == 3
    assert payload["source_event_id"] == "abc123"
    assert payload["external_url"].startswith("https://www.reddit.com/r/AskSF/comments/abc123/")
    assert payload["title"].startswith("My band is playing at The Knockout")
    assert payload["venue_name"] == "The Knockout"
