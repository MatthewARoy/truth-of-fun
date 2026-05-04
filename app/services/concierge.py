from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EventLike(Protocol):
    id: int | None
    title: str
    start_at: datetime
    end_at: datetime | None
    source_tier: int
    venue_name: str | None
    external_url: str | None


@dataclass
class ParsedIntent:
    intent: str
    geography: str | None
    timeframe_label: str
    window_start: datetime
    window_end: datetime


@dataclass
class SequencedStop:
    kind: str
    event_id: int
    title: str
    start_at: datetime
    end_at: datetime | None
    venue_name: str | None
    external_url: str | None
    travel_buffer_minutes_before: int


def parse_intent_prompt(prompt: str, *, now: datetime | None = None) -> ParsedIntent:
    now = now or datetime.now(timezone.utc)
    text = (prompt or "").strip().lower()
    if not text:
        return ParsedIntent(
            intent="general_night_out",
            geography=None,
            timeframe_label="upcoming_week",
            window_start=now,
            window_end=now + timedelta(days=7),
        )

    intent = "general_night_out"
    if "date night" in text:
        intent = "date_night"
    elif "out-of-town" in text or "visiting" in text or "guests" in text:
        intent = "out_of_town_guests"
    elif "bar crawl" in text:
        intent = "bar_crawl"

    geography = _extract_geography(text)
    timeframe_label, window_start, window_end = _extract_timeframe(text, now=now)
    return ParsedIntent(
        intent=intent,
        geography=geography,
        timeframe_label=timeframe_label,
        window_start=window_start,
        window_end=window_end,
    )


def sequence_itinerary(
    *,
    anchor: EventLike,
    support_events: list[EventLike],
) -> list[SequencedStop]:
    sorted_support = sorted(support_events, key=lambda e: e.start_at)
    pre_candidates = [
        event
        for event in sorted_support
        if event.start_at <= (anchor.start_at - timedelta(minutes=30))
    ]
    post_candidates = [
        event
        for event in sorted_support
        if event.start_at >= (anchor.start_at + timedelta(minutes=30))
    ]

    pre_event = pre_candidates[-1] if pre_candidates else None
    post_event = post_candidates[0] if post_candidates else None

    stops: list[SequencedStop] = []
    if pre_event is not None:
        stops.append(_build_stop(kind="pre_event_drink", event=pre_event, travel_buffer_minutes_before=0))

    stops.append(_build_stop(kind="main_event", event=anchor, travel_buffer_minutes_before=30))

    if post_event is not None:
        stops.append(_build_stop(kind="late_night_snack", event=post_event, travel_buffer_minutes_before=30))

    return stops


def _build_stop(*, kind: str, event: EventLike, travel_buffer_minutes_before: int) -> SequencedStop:
    return SequencedStop(
        kind=kind,
        event_id=int(event.id or 0),
        title=event.title,
        start_at=event.start_at,
        end_at=event.end_at,
        venue_name=event.venue_name,
        external_url=event.external_url,
        travel_buffer_minutes_before=travel_buffer_minutes_before,
    )


def _extract_geography(text: str) -> str | None:
    geographies = [
        "oakland",
        "san francisco",
        "sf",
        "berkeley",
        "mission",
        "soma",
        "south bay",
        "san jose",
    ]
    for geography in geographies:
        if geography in text:
            return geography
    return None


def _extract_timeframe(
    text: str,
    *,
    now: datetime,
) -> tuple[str, datetime, datetime]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "tonight" in text:
        return "tonight", day_start.replace(hour=18), day_start + timedelta(days=1, hours=3)
    if "tomorrow" in text:
        tomorrow = day_start + timedelta(days=1)
        return "tomorrow", tomorrow.replace(hour=10), tomorrow + timedelta(hours=16)
    if "this saturday" in text:
        days_until_sat = (5 - day_start.weekday()) % 7
        saturday = day_start + timedelta(days=days_until_sat)
        return "this_saturday", saturday.replace(hour=10), saturday + timedelta(hours=16)
    if "this weekend" in text:
        days_until_sat = (5 - day_start.weekday()) % 7
        saturday = day_start + timedelta(days=days_until_sat)
        sunday_end = saturday + timedelta(days=1, hours=23, minutes=59)
        return "this_weekend", saturday.replace(hour=10), sunday_end
    return "upcoming_week", now, now + timedelta(days=7)


# ---------------------------------------------------------------------------
# LLM-driven intent parsing (with keyword fallback)
# ---------------------------------------------------------------------------


_KNOWN_INTENTS = {
    "date_night",
    "out_of_town_guests",
    "bar_crawl",
    "general_night_out",
}

_KNOWN_TIMEFRAMES = {
    "tonight",
    "tomorrow",
    "this_saturday",
    "this_weekend",
    "upcoming_week",
}


class IntentParser(Protocol):
    async def parse(self, prompt: str, *, now: datetime) -> ParsedIntent | None:
        """Return a ParsedIntent or None if the parser could not handle the prompt."""


class ClaudeIntentParser:
    """LLM-backed intent parser. Returns None on any failure so callers can fall back."""

    _SYSTEM = (
        "Extract structured intent from a user's event-planning request. "
        "Return ONLY valid JSON matching this schema:\n"
        '{"intent": one of ["date_night","out_of_town_guests","bar_crawl","general_night_out"],\n'
        ' "geography": neighborhood/city string in lowercase or null,\n'
        ' "timeframe": one of ["tonight","tomorrow","this_saturday","this_weekend","upcoming_week"]}'
    )

    def __init__(self, *, api_key: str | None = None, model: str = "claude-haiku-4-5-20250901") -> None:
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key) if self._api_key else None

    async def parse(self, prompt: str, *, now: datetime) -> ParsedIntent | None:
        if self._client is None or not prompt or not prompt.strip():
            return None
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=200,
                system=self._SYSTEM,
                messages=[{"role": "user", "content": prompt.strip()}],
            )
        except Exception:
            logger.warning("Claude intent parse failed; falling back to keyword parser.", exc_info=True)
            return None

        content = response.content[0].text if response.content else ""
        payload = self._extract_json(content)
        if payload is None:
            return None

        intent = payload.get("intent")
        if intent not in _KNOWN_INTENTS:
            intent = "general_night_out"

        timeframe = payload.get("timeframe")
        if timeframe not in _KNOWN_TIMEFRAMES:
            timeframe = "upcoming_week"

        geography_raw = payload.get("geography")
        geography = geography_raw.strip().lower() if isinstance(geography_raw, str) and geography_raw.strip() else None

        window_start, window_end = _resolve_timeframe_window(timeframe, now=now)
        return ParsedIntent(
            intent=intent,
            geography=geography,
            timeframe_label=timeframe,
            window_start=window_start,
            window_end=window_end,
        )

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any] | None:
        if not raw:
            return None
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        candidate = match.group(0) if match else raw
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


def _resolve_timeframe_window(label: str, *, now: datetime) -> tuple[datetime, datetime]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if label == "tonight":
        return day_start.replace(hour=18), day_start + timedelta(days=1, hours=3)
    if label == "tomorrow":
        tomorrow = day_start + timedelta(days=1)
        return tomorrow.replace(hour=10), tomorrow + timedelta(hours=16)
    if label == "this_saturday":
        days_until_sat = (5 - day_start.weekday()) % 7
        saturday = day_start + timedelta(days=days_until_sat)
        return saturday.replace(hour=10), saturday + timedelta(hours=16)
    if label == "this_weekend":
        days_until_sat = (5 - day_start.weekday()) % 7
        saturday = day_start + timedelta(days=days_until_sat)
        return saturday.replace(hour=10), saturday + timedelta(days=1, hours=23, minutes=59)
    return now, now + timedelta(days=7)


async def parse_intent_async(
    prompt: str,
    *,
    now: datetime | None = None,
    parser: IntentParser | None = None,
) -> ParsedIntent:
    """LLM-first intent parsing with deterministic keyword fallback."""
    now = now or datetime.now(timezone.utc)
    parser = parser if parser is not None else ClaudeIntentParser()
    parsed = await parser.parse(prompt, now=now)
    if parsed is not None:
        return parsed
    return parse_intent_prompt(prompt, now=now)
