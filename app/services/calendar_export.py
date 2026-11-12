"""iCalendar (RFC 5545) export for a single event."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.localtime import LOCAL_TZ

_DEFAULT_DURATION = timedelta(hours=2)
_MAX_DESCRIPTION = 1500


def _escape(value: str) -> str:
    """Escape TEXT per RFC 5545 §3.3.11 and drop control characters."""
    cleaned = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32)
    return (
        cleaned.replace("\\", "\\\\")
        .replace(";", "\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line at 75 octets (§3.1) without splitting a character."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: list[str] = []
    current = ""
    limit = 75
    for ch in line:
        if len((current + ch).encode("utf-8")) > limit:
            parts.append(current)
            current = ch
            limit = 74  # continuation lines start with one space
        else:
            current += ch
    parts.append(current)
    return "\r\n ".join(parts)


def _utc(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def event_to_ics(
    *,
    uid: str,
    title: str,
    start_at: datetime,
    end_at: datetime | None = None,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    url: str | None = None,
    cancelled: bool = False,
    updated_at: datetime | None = None,
) -> str:
    """Render one VEVENT.

    ``all_day`` is for events whose calendar date is real but whose clock time
    is a connector placeholder: writing the placeholder into someone's
    calendar would present a guess as a published start time, so the entry
    covers the (Pacific) day instead.
    """
    start = start_at if start_at.tzinfo else start_at.replace(tzinfo=timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Truth of Fun//Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{_escape(uid)}",
        f"DTSTAMP:{_utc(updated_at or datetime.now(timezone.utc))}",
    ]
    if all_day:
        day = start.astimezone(LOCAL_TZ).date()
        lines.append(f"DTSTART;VALUE=DATE:{day:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}")
    else:
        end = end_at if end_at and end_at > start_at else start + _DEFAULT_DURATION
        lines.append(f"DTSTART:{_utc(start)}")
        lines.append(f"DTEND:{_utc(end)}")
    lines.append(f"SUMMARY:{_escape(title)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    details = (description or "").strip()
    if len(details) > _MAX_DESCRIPTION:
        details = details[:_MAX_DESCRIPTION].rstrip() + "…"
    if url:
        details = f"{details}\n\n{url}".strip()
        if url.startswith(("http://", "https://")):
            lines.append(f"URL:{url}")
    if details:
        lines.append(f"DESCRIPTION:{_escape(details)}")
    lines.append(f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
