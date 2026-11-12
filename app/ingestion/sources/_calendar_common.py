"""Helpers shared by the official-calendar connectors (Localist, BiblioCommons, LiveWhale).

These sources are public institutional calendars read through their own JSON
feeds, so they share a few rules: an honest User-Agent, short plain-text
descriptions, all-day events that never grow an invented clock time, and
coordinates that are either the feed's own or an explicitly low-confidence
centroid.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, time, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.venue_cache import lookup_venue_coordinates

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

#: Truthful and descriptive: these are institutional calendars, not adversaries.
USER_AGENT = (
    "truth-of-fun/0.1 (event discovery; +https://github.com/MatthewARoy/truth-of-fun)"
)
JSON_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

MAX_DESCRIPTION_CHARS = 600

#: Coordinates published by the feed for the event's own venue.
FEED_COORDINATE_CONFIDENCE = 0.9
#: A campus / city centroid standing in for an unknown venue. Must stay below
#: DEFAULT_MIN_LOCATION_CONFIDENCE (0.5, app.api.discovery) so radius search
#: never treats the guess as the event's real location.
CENTROID_CONFIDENCE = 0.3

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_BREAK_RE = re.compile(r"<\s*(?:br|/p|/div|/li|/h[1-6])\b[^>]*>", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def plain_text(value: Any) -> str:
    """HTML or text -> one line of plain text (tags dropped, entities decoded)."""
    if not isinstance(value, str):
        return ""
    text = _BLOCK_BREAK_RE.sub(" ", value)
    text = html.unescape(_TAG_RE.sub(" ", text))
    return _WHITESPACE_RE.sub(" ", text.replace(" ", " ")).strip()


def short_description(value: Any, limit: int = MAX_DESCRIPTION_CHARS) -> str | None:
    """Plain-text description cut at a word boundary, or None when empty."""
    text = plain_text(value)
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"


def clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _WHITESPACE_RE.sub(" ", value).strip()
    return cleaned or None


def to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def feed_coordinates(lat: Any, lon: Any) -> tuple[float, float] | None:
    """A usable (lat, lon) pair from feed values, or None.

    (0, 0) and out-of-range values are how feeds spell "not geocoded".
    """
    lat_f, lon_f = to_float(lat), to_float(lon)
    if lat_f is None or lon_f is None:
        return None
    if lat_f == 0.0 and lon_f == 0.0:
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return None
    return lat_f, lon_f


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = radians(a[0]), radians(a[1]), radians(b[0]), radians(b[1])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def nearby_venue_coordinates(
    venue_name: str | None,
    *,
    near: tuple[float, float],
    max_km: float = 15.0,
) -> tuple[float, float] | None:
    """``lookup_venue_coordinates`` restricted to hits near the institution.

    The venue cache matches by substring and is mostly San Francisco venues,
    so a campus room called "Mezzanine" or "Audio Lab" would resolve to a SoMa
    nightclub at full confidence. A hit far from the campus/library is a name
    collision, not a location.
    """
    coords = lookup_venue_coordinates(venue_name)
    if coords is None or distance_km(coords, near) > max_km:
        return None
    return coords


def postal_address(
    street: str | None,
    city: str | None,
    region: str | None = "CA",
    postal_code: str | None = None,
) -> str | None:
    """``"541 Lasuen Mall, Stanford, CA 94305"`` - street, city, state, zip.

    The stored city/region of an event is derived downstream
    (app/services/regions.py): from coordinates when they are trusted, and
    for centroid-fallback rows from a city written in exactly this postal
    form. So the city goes into the address whenever it is known.
    """
    tail = " ".join(part for part in (region, postal_code) if part)
    parts = [part for part in (street, city, tail) if part]
    return ", ".join(parts) if city or street else None


def all_day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC (start, end) of a local calendar day: 00:00 to 23:59 Pacific."""
    start = datetime.combine(day, time(0, 0), tzinfo=LOCAL_TZ)
    end = datetime.combine(day, time(23, 59), tzinfo=LOCAL_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def parse_local_datetime(value: Any) -> datetime | None:
    """ISO timestamp -> aware UTC datetime; a naive stamp is Pacific wall clock."""
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(timezone.utc)


def parse_iso_date(value: Any) -> date | None:
    """The calendar date at the head of an ISO date or timestamp."""
    if not isinstance(value, str):
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    if not match:
        return None
    try:
        return date(*(int(group) for group in match.groups()))
    except ValueError:
        return None


def within_horizon(day: date, *, today: date, horizon_days: int) -> bool:
    """True for ``today`` .. ``today + horizon_days`` inclusive."""
    return today <= day <= today + timedelta(days=horizon_days)


def summarize_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()) if count)
