"""Shared utilities for web scrapers and API fetchers."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

SF_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194

MONTH_ABBREV: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def strip_html_tags(value: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not isinstance(value, str):
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    collapsed = re.sub(r"\s+", " ", without_tags).strip()
    return collapsed


def parse_12h_to_24h(hour: int, meridiem: str) -> int:
    """Convert 12h hour + am/pm to 24h."""
    normalized = hour % 12
    if meridiem.lower() == "pm":
        normalized += 12
    return normalized % 24


def parse_price(text: str | None) -> tuple[float | None, bool]:
    """Extract numeric price and is_free from text. Returns (price, is_free)."""
    if not text or not isinstance(text, str):
        return None, False
    text_lower = text.lower()
    if "free" in text_lower and "$" not in text:
        return 0.0, True
    match = re.search(r"\$\s*(\d+(?:\.\d{2})?)", text)
    if match:
        try:
            return float(match.group(1)), False
        except ValueError:
            pass
    return None, False


def parse_datetime_flexible(
    text: str,
    *,
    reference_date: date | None = None,
    default_hour: int = 19,
    default_minute: int = 0,
    tz: ZoneInfo = SF_TZ,
) -> datetime | None:
    """
    Parse various date/time formats. Returns timezone-aware datetime in tz.
    """
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    ref = reference_date or datetime.now(tz).date()

    # ISO date: 2026-03-02
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso_match:
        try:
            y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
            base_date = date(y, m, d)
        except ValueError:
            base_date = ref
    else:
        # Month day: Mar 2, Mar 14, March 2 2026
        md_match = re.search(
            r"(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:[,\s]+(?P<year>\d{4}))?",
            text,
            re.IGNORECASE,
        )
        if md_match:
            month_token = md_match.group("month")[:3].lower()
            month = MONTH_ABBREV.get(month_token)
            if month is None:
                return None
            day = int(md_match.group("day"))
            year = int(md_match.group("year")) if md_match.group("year") else ref.year
            try:
                base_date = date(year, month, day)
            except ValueError:
                return None
        else:
            base_date = ref

    # Time: 7:15 pm, 8pm, 10:00AM - require am/pm to avoid matching date digits
    time_match = re.search(
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        text,
        re.IGNORECASE,
    )
    hour, minute = default_hour, default_minute
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = (time_match.group(3) or "pm").lower()
        hour = parse_12h_to_24h(hour, ampm)

    try:
        return datetime(base_date.year, base_date.month, base_date.day, hour, minute, 0, tzinfo=tz)
    except ValueError:
        return None


def parse_date_range(
    text: str,
    *,
    reference_date: date | None = None,
    tz: ZoneInfo = SF_TZ,
) -> tuple[datetime | None, datetime | None]:
    """
    Parse date range like "Feb 14–Mar 28, 2026" or "Mar 7–31, 2026".
    Returns (start_dt, end_dt) in tz.
    """
    if not text or not isinstance(text, str):
        return None, None
    ref = reference_date or datetime.now(tz).date()

    # Feb 14–Mar 28, 2026
    range_match = re.search(
        r"([A-Za-z]{3})\s+(\d{1,2})\s*[–\-]\s*([A-Za-z]{3})\s+(\d{1,2})(?:,\s*(\d{4}))?",
        text,
        re.IGNORECASE,
    )
    if range_match:
        m1 = MONTH_ABBREV.get(range_match.group(1).lower()[:3])
        d1 = int(range_match.group(2))
        m2 = MONTH_ABBREV.get(range_match.group(3).lower()[:3])
        d2 = int(range_match.group(4))
        year = int(range_match.group(5)) if range_match.group(5) else ref.year
        if m1 and m2:
            try:
                start_d = date(year, m1, d1)
                end_d = date(year, m2, d2)
                if end_d < start_d:
                    end_d = date(year + 1, m2, d2)
                start_dt = datetime(start_d.year, start_d.month, start_d.day, 0, 0, 0, tzinfo=tz)
                end_dt = datetime(end_d.year, end_d.month, end_d.day, 23, 59, 0, tzinfo=tz)
                return start_dt, end_dt
            except ValueError:
                pass

    # Mar 7–31, 2026 (same month)
    same_month = re.search(
        r"([A-Za-z]{3})\s+(\d{1,2})\s*[–\-]\s*(\d{1,2})(?:,\s*(\d{4}))?",
        text,
        re.IGNORECASE,
    )
    if same_month:
        m = MONTH_ABBREV.get(same_month.group(1).lower()[:3])
        d1 = int(same_month.group(2))
        d2 = int(same_month.group(3))
        year = int(same_month.group(4)) if same_month.group(4) else ref.year
        if m:
            try:
                start_d = date(year, m, d1)
                end_d = date(year, m, d2)
                start_dt = datetime(start_d.year, start_d.month, start_d.day, 0, 0, 0, tzinfo=tz)
                end_dt = datetime(end_d.year, end_d.month, end_d.day, 23, 59, 0, tzinfo=tz)
                return start_dt, end_dt
            except ValueError:
                pass

    return None, None


def pick_first_str(obj: dict[str, Any], *keys: str) -> str | None:
    """Return first non-empty string value for given keys."""
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def coerce_int(value: Any) -> int | None:
    """Safely coerce to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
