"""Tests for Eddie's List IMAP newsletter source.

Live fetch requires IMAP credentials (NOT_TESTABLE against the real mailbox),
but the parse path is fully testable by injecting raw RFC822 messages.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage

from app.ingestion.sources.eddies_list import EddiesListSource
from app.ingestion.sources.eddies_list import REQUIRES_IMAP_CREDENTIALS
from app.ingestion.sources.eddies_list import TESTABLE

ISSUE_HTML = """\
<html><body>
<h1>Eddie's List &mdash; This Week in SF</h1>
<p>Hey friends, here's what's good this week.</p>
<h3><a href="https://eddieslist.example.com/p/this-week#jazz">Jazz at the Chapel</a></h3>
<p>Friday, June 12 @ 8pm &mdash; The Chapel, 777 Valencia St. $25. Late-night jazz
with a rotating cast of local players. Worth staying out late for.</p>
<h3><a href="https://eddieslist.example.com/p/this-week#opera">Free Opera in Dolores Park</a></h3>
<p>Saturday, June 13, 1pm &mdash; Dolores Park. Free. Bring a blanket and some snacks.</p>
<h3><a href="https://eddieslist.example.com/p/this-week#musings">Eddie's musings on fog season</a></h3>
<p>No event here, just some thoughts about Karl the Fog and the best burrito in town.</p>
</body></html>
"""


def _build_issue_email(
    *,
    sender: str = "Eddie's List <hello@eddieslist.example.com>",
    html: str = ISSUE_HTML,
    text: str | None = None,
    date_header: str = "Wed, 10 Jun 2026 09:00:00 -0700",
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "subscriber@example.com"
    message["Subject"] = "Eddie's List — This Week in SF"
    message["Date"] = date_header
    if text is not None:
        message.set_content(text)
    else:
        message.set_content("View this issue in your browser.")
        message.add_alternative(html, subtype="html")
    return message.as_bytes()


def _make_source(**kwargs) -> EddiesListSource:
    kwargs.setdefault("allowed_senders", ["eddieslist.example.com"])
    return EddiesListSource(**kwargs)


def test_eddies_list_not_testable_without_credentials() -> None:
    assert TESTABLE is False
    assert REQUIRES_IMAP_CREDENTIALS is True


def test_eddies_list_returns_empty_without_credentials() -> None:
    source = EddiesListSource()
    events = asyncio.run(source.fetch_events())
    assert events == []


def test_parses_events_from_injected_newsletter_message() -> None:
    source = _make_source()
    events = asyncio.run(source.fetch_events(messages=[_build_issue_email()]))

    assert len(events) == 2
    by_title = {event["title"]: event for event in events}
    assert set(by_title) == {"Jazz at the Chapel", "Free Opera in Dolores Park"}

    jazz = by_title["Jazz at the Chapel"]
    assert jazz["source_name"] == "eddies_list"
    assert jazz["source_tier"] == 3
    assert jazz["external_url"] == "https://eddieslist.example.com/p/this-week#jazz"
    # Friday June 12 2026 8pm PDT == 2026-06-13 03:00 UTC
    assert jazz["start_at"] == datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc)
    assert jazz["price"] == 25.0
    assert jazz["venue_name"] == "The Chapel"
    # "the chapel" is in the static venue cache; coordinates must be real, not city center
    assert jazz["location"] == "POINT(-122.4214 37.7608)"

    opera = by_title["Free Opera in Dolores Park"]
    assert opera["start_at"] == datetime(2026, 6, 13, 20, 0, tzinfo=timezone.utc)
    assert opera["price"] == 0.0


def test_skips_items_without_an_explicit_date() -> None:
    """Items with no parseable date must be dropped, never given a fabricated date."""
    source = _make_source()
    events = asyncio.run(source.fetch_events(messages=[_build_issue_email()]))
    titles = [event["title"] for event in events]
    assert "Eddie's musings on fog season" not in titles


def test_ignores_messages_from_unallowed_senders() -> None:
    source = _make_source()
    spam = _build_issue_email(sender="Totally Eddie <noreply@spam.example.net>")
    events = asyncio.run(source.fetch_events(messages=[spam]))
    assert events == []


def test_year_rolls_over_for_january_events_in_december_issue() -> None:
    html = """
    <html><body>
    <h3><a href="https://eddieslist.example.com/p/nye#show">New Year Comedy Night</a></h3>
    <p>Saturday, January 3, 8pm &mdash; Punch Line Comedy Club. $30.</p>
    </body></html>
    """
    source = _make_source()
    message = _build_issue_email(html=html, date_header="Mon, 28 Dec 2026 09:00:00 -0800")
    events = asyncio.run(source.fetch_events(messages=[message]))
    assert len(events) == 1
    assert events[0]["start_at"].astimezone(timezone.utc).year == 2027


def test_plain_text_only_issue_still_parses() -> None:
    text = (
        "EDDIE'S LIST — THIS WEEK IN SF\n\n"
        "Jazz at the Chapel\n"
        "Friday, June 12 @ 8pm — The Chapel, 777 Valencia St. $25.\n"
        "https://eddieslist.example.com/p/this-week#jazz\n\n"
        "Just some closing thoughts, no event here.\n"
    )
    source = _make_source()
    message = _build_issue_email(text=text)
    events = asyncio.run(source.fetch_events(messages=[message]))
    assert len(events) == 1
    assert events[0]["title"] == "Jazz at the Chapel"
    assert events[0]["start_at"] == datetime(2026, 6, 13, 3, 0, tzinfo=timezone.utc)


def test_normalize_enforces_metadata_only_compliance() -> None:
    """Spec: never republish full paid content; store metadata + short snippet only."""
    source = _make_source()
    long_blurb = "Friday, June 12 @ 8pm — The Chapel. " + ("A really long blurb. " * 50)
    canonical = source.normalize_raw(
        {
            "title": "Jazz at the Chapel",
            "source_url": "https://eddieslist.example.com/p/this-week#jazz",
            "blurb": long_blurb,
            "issue_date": datetime(2026, 6, 10, 16, 0, tzinfo=timezone.utc),
            "issue_subject": "Eddie's List — This Week in SF",
        }
    )
    assert canonical is not None
    assert canonical.organizer.name == "Eddie's List"
    assert canonical.compliance.retention_policy == "metadata_only"
    assert canonical.source.capture_mode == "email_ingest"
    assert canonical.description is not None
    assert len(canonical.description) <= 300
