"""Add-to-calendar files are valid iCalendar and never invent a clock time."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models.event import Event
from app.services.calendar_export import event_to_ics


def _unfold(ics: str) -> list[str]:
    return ics.replace("\r\n ", "").strip().split("\r\n")


def test_timed_event_has_utc_start_and_end_and_escaped_text() -> None:
    ics = event_to_ics(
        uid="event-7@truth-of-fun",
        title="Jazz; Blues, and more",
        start_at=datetime(2026, 11, 14, 4, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 11, 14, 6, 30, tzinfo=timezone.utc),
        location="SFJAZZ Center, 201 Franklin St",
        description="Line one\nLine two",
        url="https://example.com/tickets",
    )
    assert ics.endswith("\r\n") and "\n" not in ics.replace("\r\n", "")
    lines = _unfold(ics)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    assert "DTSTART:20261114T040000Z" in lines
    assert "DTEND:20261114T063000Z" in lines
    assert "SUMMARY:Jazz\; Blues\\, and more" in lines
    assert "LOCATION:SFJAZZ Center\\, 201 Franklin St" in lines
    assert "URL:https://example.com/tickets" in lines
    assert any(line.startswith("DESCRIPTION:Line one\\nLine two") for line in lines)
    assert "STATUS:CONFIRMED" in lines


def test_estimated_time_becomes_an_all_day_entry_on_the_pacific_date() -> None:
    # 03:00 UTC on the 15th is 19:00 Pacific on the 14th.
    ics = event_to_ics(
        uid="x", title="Street fair",
        start_at=datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc), all_day=True,
    )
    lines = _unfold(ics)
    assert "DTSTART;VALUE=DATE:20261114" in lines
    assert "DTEND;VALUE=DATE:20261115" in lines
    assert not any(line.startswith("DTSTART:") for line in lines)


def test_missing_end_gets_a_default_duration_and_long_lines_are_folded() -> None:
    ics = event_to_ics(
        uid="x", title="T" * 200,
        start_at=datetime(2026, 11, 14, 4, 0, tzinfo=timezone.utc), cancelled=True,
    )
    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n"))
    lines = _unfold(ics)
    assert "DTEND:20261114T060000Z" in lines
    assert "STATUS:CANCELLED" in lines
    assert f"SUMMARY:{'T' * 200}" in lines


def test_calendar_endpoint_serves_a_download(isolated_events_session) -> None:
    session = isolated_events_session
    event = Event(
        title="Calendar fixture", start_at=datetime(2026, 12, 5, 4, 0, tzinfo=timezone.utc),
        source_name="test-ics", source_tier=2, location="POINT(-122.2712 37.8048)",
        venue_name="Fox Theater", external_url="https://example.com/e/1",
    )
    session.add(event)
    session.flush()
    client = TestClient(app)
    response = client.get(f"/events/{event.id}/calendar.ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert f'filename="event-{event.id}.ics"' in response.headers["content-disposition"]
    assert "SUMMARY:Calendar fixture" in response.text
    assert "LOCATION:Fox Theater" in response.text
    assert client.get("/events/999999999/calendar.ics").status_code == 404


def test_copied_plan_links_are_absolute_when_the_public_url_is_configured(monkeypatch) -> None:
    from app.api import discovery
    from app.core.config import get_settings

    assert discovery._absolute_web_url("/itinerary/abc") == "/itinerary/abc"
    monkeypatch.setattr(get_settings(), "public_web_url", "https://fun.example/")
    assert discovery._absolute_web_url("/itinerary/abc") == "https://fun.example/itinerary/abc"
