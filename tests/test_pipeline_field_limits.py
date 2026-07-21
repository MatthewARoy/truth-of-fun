"""Over-long source values must not abort the ingestion cycle.

The whole run commits in one transaction, so a single value exceeding its
column width used to raise StringDataRightTruncation and discard the events
from *every* source. This was not hypothetical: 19hz uses the event URL as its
identifier, and one Instagram share link with tracking parameters blew past
source_event_id's 255 characters and lost a 1,497-event cycle.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.data_pipeline import (
    _MAX_ORGANIZER_NAME,
    _MAX_SOURCE_EVENT_ID,
    _MAX_TITLE,
    _MAX_URL,
    _MAX_VENUE_NAME,
    DataPipelineService,
)


def _raw(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "A Show",
        "start_at": datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc),
        "location": "POINT(-122.4194 37.7749)",
        "source_name": "19hz",
        "source_tier": 2,
    }
    payload.update(overrides)
    return payload


def _normalize(**overrides: object) -> dict[str, object]:
    normalized = DataPipelineService()._normalize_event_payload(_raw(**overrides))
    assert normalized is not None
    return normalized


def test_long_source_event_id_is_clamped_to_the_column_width() -> None:
    long_id = "https://l.instagram.com/?u=" + "a" * 900

    normalized = _normalize(source_event_id=long_id)

    assert len(str(normalized["source_event_id"])) <= _MAX_SOURCE_EVENT_ID


def test_clamped_source_event_ids_stay_distinct() -> None:
    """A plain truncation would merge two different events into one id.

    source_event_id is how a later run recognises the same event, so collapsing
    two long URLs that share a prefix would make distinct events look like
    duplicates of each other.
    """
    shared_prefix = "https://l.instagram.com/?u=" + "a" * 900

    first = _normalize(source_event_id=shared_prefix + "-one")["source_event_id"]
    second = _normalize(source_event_id=shared_prefix + "-two")["source_event_id"]

    assert first != second


def test_clamping_is_stable_across_runs() -> None:
    """The same source id must map to the same stored id every cycle."""
    long_id = "https://example.test/" + "b" * 900

    assert _normalize(source_event_id=long_id)["source_event_id"] == (
        _normalize(source_event_id=long_id)["source_event_id"]
    )


def test_short_source_event_ids_are_left_untouched() -> None:
    assert _normalize(source_event_id="tm_12345")["source_event_id"] == "tm_12345"


def test_long_display_fields_are_truncated() -> None:
    normalized = _normalize(
        title="T" * (_MAX_TITLE + 200),
        venue_name="V" * (_MAX_VENUE_NAME + 200),
        organizer_name="O" * (_MAX_ORGANIZER_NAME + 200),
        external_url="https://example.test/" + "u" * (_MAX_URL + 200),
        image_url="https://example.test/" + "i" * (_MAX_URL + 200),
    )

    assert len(str(normalized["title"])) == _MAX_TITLE
    assert len(str(normalized["venue_name"])) == _MAX_VENUE_NAME
    assert len(str(normalized["organizer_name"])) == _MAX_ORGANIZER_NAME
    assert len(str(normalized["external_url"])) == _MAX_URL
    assert len(str(normalized["image_url"])) == _MAX_URL


def test_every_bounded_column_survives_an_over_long_source_value() -> None:
    """Guard the whole class of bug, not just the fields that have bitten us.

    Reads the length limits off the model, so adding a new bounded column
    without defending it in _normalize_event_payload fails here rather than in
    production — where it aborts the transaction and costs the entire cycle.
    """
    from app.models.event import Event

    bounded = {
        column.name: column.type.length
        for column in Event.__table__.columns
        if getattr(column.type, "length", None)
    }
    # Sanity: if this ever empties out, the test has stopped testing anything.
    assert bounded

    overlong = {name: "x" * (length + 500) for name, length in bounded.items()}
    # These are not free-text source fields, so feed them plausible values.
    overlong.pop("status", None)
    overlong.pop("source_name", None)

    normalized = _normalize(**overlong)

    too_long = {
        name: len(str(normalized[name]))
        for name, length in bounded.items()
        if normalized.get(name) is not None and len(str(normalized[name])) > length
    }
    assert too_long == {}, f"columns exceeding their width: {too_long} (limits: {bounded})"


def test_values_within_the_limits_are_unchanged() -> None:
    normalized = _normalize(
        title="Borgore at The Midway",
        venue_name="The Midway",
        external_url="https://themidwaysf.com/borgore",
    )

    assert normalized["title"] == "Borgore at The Midway"
    assert normalized["venue_name"] == "The Midway"
    assert normalized["external_url"] == "https://themidwaysf.com/borgore"
