"""Turn a sequenced itinerary into something you can carry around.

The concierge produces an ordered list of stops; this module turns each stop
into the things you actually need while standing on a sidewalk: how to drive
there, where to park, and what's nearby to eat or drink. Everything here is a
pure function over stop data — no DB, no network, no API keys — so the same
rendering backs the shared web page and the plain-text version you paste into
a message.

Nearby food/drink/parking are Google Maps *searches* centered on the venue
rather than curated picks: the event corpus has no restaurant or bar data, and
a live Maps search is never stale and never invented.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import quote

from app.core.localtime import LOCAL_TZ

_MAPS_BASE = "https://www.google.com/maps"

# Zoom level for a neighborhood-scale "what's around this venue" search. Tight
# enough to stay walkable, wide enough to return more than one option.
_NEARBY_ZOOM = 16

# Below this, a source geocoded to a city centroid rather than the venue
# (connectors emit ~0.85–0.9 for a real geocode and ~0.3–0.45 for a fallback).
# Such a point is fine for "what neighborhood is this in" but must not be
# handed to turn-by-turn navigation.
_TRUSTED_COORDINATE_CONFIDENCE = 0.7


@dataclass(frozen=True)
class StopLocation:
    """Everything needed to point a map at a stop."""

    venue_name: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    location_confidence: float = 1.0

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lng is not None

    @property
    def has_precise_coordinates(self) -> bool:
        """Whether the point is exact enough to navigate to."""
        return (
            self.has_coordinates
            and self.location_confidence >= _TRUSTED_COORDINATE_CONFIDENCE
        )

    @property
    def is_locatable(self) -> bool:
        return self.has_coordinates or bool(self.address) or bool(self.venue_name)


@dataclass(frozen=True)
class StopLinks:
    """Tap targets for a single stop."""

    tickets_url: str | None
    map_url: str | None
    directions_url: str | None
    food_url: str | None
    drinks_url: str | None
    parking_url: str | None


def _waypoint(location: StopLocation) -> str | None:
    """Address a map can resolve unambiguously.

    Trusted coordinates win over text: scraped addresses are frequently partial
    ("Valencia St" with no number) and would drop a driver on the wrong block,
    while a real geocode is exactly where the venue is. Low-confidence
    coordinates are the reverse — they're a city centroid, so even a vague
    address string beats navigating someone downtown.
    """
    if location.has_precise_coordinates:
        return f"{location.lat},{location.lng}"
    text_waypoint = ", ".join(
        part for part in (location.venue_name, location.address) if part
    )
    if text_waypoint:
        return text_waypoint
    if location.has_coordinates:
        return f"{location.lat},{location.lng}"
    return None


def map_url(location: StopLocation) -> str | None:
    """A dropped pin on the stop itself."""
    waypoint = _waypoint(location)
    if waypoint is None:
        return None
    return f"{_MAPS_BASE}/search/?api=1&query={quote(waypoint)}"


def directions_url(
    *, destination: StopLocation, origin: StopLocation | None = None
) -> str | None:
    """Driving directions to ``destination``.

    Omitting ``origin`` is deliberate rather than a fallback: Google Maps then
    routes from wherever the phone currently is, which is what the first stop
    of the night wants.
    """
    waypoint = _waypoint(destination)
    if waypoint is None:
        return None
    url = f"{_MAPS_BASE}/dir/?api=1&destination={quote(waypoint)}&travelmode=driving"
    origin_waypoint = _waypoint(origin) if origin is not None else None
    if origin_waypoint is not None:
        url += f"&origin={quote(origin_waypoint)}"
    return url


def nearby_search_url(location: StopLocation, term: str) -> str | None:
    """A Maps search for ``term`` centered on the stop.

    With coordinates this uses the ``/@lat,lng,zoom`` form so results are
    ranked around the venue. Without them it falls back to a "<term> near
    <venue>" text search, which is looser but still lands in the right area.
    """
    if location.has_coordinates:
        return (
            f"{_MAPS_BASE}/search/{quote(term)}/"
            f"@{location.lat},{location.lng},{_NEARBY_ZOOM}z"
        )
    anchor_text = location.address or location.venue_name
    if not anchor_text:
        return None
    return f"{_MAPS_BASE}/search/?api=1&query={quote(f'{term} near {anchor_text}')}"


def build_stop_links(
    *,
    location: StopLocation,
    previous_location: StopLocation | None = None,
    tickets_url: str | None = None,
) -> StopLinks:
    """The full set of tap targets for one stop."""
    if not location.is_locatable:
        return StopLinks(
            tickets_url=tickets_url,
            map_url=None,
            directions_url=None,
            food_url=None,
            drinks_url=None,
            parking_url=None,
        )

    # Only route from the previous stop if we can actually locate it; a
    # venue-less predecessor would otherwise produce directions from nowhere.
    origin = (
        previous_location
        if previous_location is not None and previous_location.is_locatable
        else None
    )
    return StopLinks(
        tickets_url=tickets_url,
        map_url=map_url(location),
        directions_url=directions_url(destination=location, origin=origin),
        food_url=nearby_search_url(location, "restaurants"),
        drinks_url=nearby_search_url(location, "bars"),
        parking_url=nearby_search_url(location, "parking"),
    )


# ---------------------------------------------------------------------------
# Human-facing labels
# ---------------------------------------------------------------------------


_STOP_KIND_LABELS = {
    "pre_event_drink": "Before",
    "main_event": "Main event",
    "late_night_snack": "After",
}

_INTENT_LABELS = {
    "date_night": "Date night",
    "out_of_town_guests": "Showing guests around",
    "bar_crawl": "Bar crawl",
    "general_night_out": "Night out",
}


def stop_kind_label(kind: str) -> str:
    return _STOP_KIND_LABELS.get(kind, kind.replace("_", " ").capitalize())


def format_local_time(value: datetime) -> str:
    """``7:30 PM`` in venue-local time, with no leading zero."""
    local = value.astimezone(LOCAL_TZ)
    return local.strftime("%I:%M %p").lstrip("0")


def format_local_day(value: datetime) -> str:
    """``Sat, Aug 8`` in venue-local time."""
    local = value.astimezone(LOCAL_TZ)
    return f"{local.strftime('%a, %b')} {local.day}"


def itinerary_title(
    *, intent: str, geography: str | None, starts_at: datetime | None
) -> str:
    """A subject line: what this is, where, and when."""
    title = _INTENT_LABELS.get(intent, "Your plan")
    if geography:
        title += f" in {geography.title()}"
    if starts_at is not None:
        title += f" — {format_local_day(starts_at)}"
    return title


# ---------------------------------------------------------------------------
# Plain-text rendering
# ---------------------------------------------------------------------------


class StopLinksLike(Protocol):
    tickets_url: str | None
    directions_url: str | None
    parking_url: str | None
    food_url: str | None
    drinks_url: str | None


class StopLike(Protocol):
    """A stop that already carries its links, whatever type holds it.

    Structural rather than concrete so the API's response model can be printed
    directly — the same reason ``concierge.EventLike`` exists. Without it the
    caller would have to decompose each stop back into a ``StopLocation`` and
    ``StopLinks`` that it had just built.
    """

    kind: str
    title: str
    start_at: datetime
    end_at: datetime | None
    venue_name: str | None
    address: str | None
    travel_buffer_minutes_before: int
    links: StopLinksLike


def location_label(*, venue_name: str | None, address: str | None) -> str | None:
    """Human-facing one-liner: venue and address, whichever exist."""
    parts = [part for part in (venue_name, address) if part]
    return " — ".join(parts) if parts else None


def render_itinerary_text(
    *,
    title: str,
    stops: Sequence[StopLike],
    share_url: str | None = None,
) -> str:
    """Render the itinerary as pasteable plain text.

    Built for a messaging app rather than a terminal: short lines, bare URLs
    that autolink, and no box drawing that would reflow into noise.
    """
    lines: list[str] = [title]
    if not stops:
        lines.append("")
        lines.append("No stops yet.")
        return "\n".join(lines)

    for index, stop in enumerate(stops, start=1):
        lines.append("")
        time_range = format_local_time(stop.start_at)
        if stop.end_at is not None:
            time_range += f"–{format_local_time(stop.end_at)}"
        lines.append(f"{index}. {time_range} · {stop_kind_label(stop.kind)}")
        lines.append(f"   {stop.title}")

        where = location_label(venue_name=stop.venue_name, address=stop.address)
        if where:
            lines.append(f"   {where}")
        if stop.travel_buffer_minutes_before > 0:
            lines.append(
                f"   Leave ~{stop.travel_buffer_minutes_before} min ahead"
            )

        for label, url in (
            ("Tickets", stop.links.tickets_url),
            ("Directions", stop.links.directions_url),
            ("Parking", stop.links.parking_url),
            ("Food nearby", stop.links.food_url),
            ("Drinks nearby", stop.links.drinks_url),
        ):
            if url:
                lines.append(f"   {label}: {url}")

    if share_url:
        lines.append("")
        lines.append(f"Full plan: {share_url}")
    return "\n".join(lines)
