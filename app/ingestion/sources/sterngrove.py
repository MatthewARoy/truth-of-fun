"""Stern Grove Festival lineup scraper."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OffersModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import (
    DEFAULT_SF_LAT,
    DEFAULT_SF_LON,
    SF_TZ,
    parse_datetime_flexible,
)
from app.ingestion.venue_cache import lookup_venue_coordinates

# Testable without API keys - public scraper
TESTABLE = True

_DATE_PATTERN = re.compile(
    r"^(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*"
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})\b",
    re.IGNORECASE,
)
_TIME_PATTERN = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.IGNORECASE)
_SUPPORT_PATTERN = re.compile(r"(?:with|featuring)\s+(.+)", re.IGNORECASE)
_LOTTERY_PATTERN = re.compile(
    r"(?:lottery|sold out|table sales|on sale)", re.IGNORECASE
)
# A concert card is headliner + support. Anything past that inside a block is
# page furniture — the final block runs to the end of the document.
_CARD_LINES = 2


class SternGroveSource(InputAgentSource):
    """Scraper for the annual Stern Grove Festival concert lineup."""

    source_name = "sterngrove"
    source_tier = 2
    base_url = "https://www.sterngrove.org"
    venue_name = "Sigmund Stern Grove"
    venue_address = "19th Avenue and Sloat Boulevard, San Francisco, CA 94132"

    def __init__(self, *, season_year: int | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.season_year = season_year or datetime.now(SF_TZ).year
        self.lineup_url = f"{self.base_url}/lineup{self.season_year}"

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        html = kwargs.get("html")
        if not isinstance(html, str):
            await self._limiter.acquire()
            response = await self._get_client().get(self.lineup_url)
            response.raise_for_status()
            html = response.text
        return self._extract_candidates(html)

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = raw_item.get("title")
        date_iso = raw_item.get("date_iso")
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(date_iso, str)
        ):
            return None

        time_text = raw_item.get("time_text")
        start_local = None
        if isinstance(time_text, str) and time_text:
            start_local = parse_datetime_flexible(f"{date_iso} {time_text}")
        if start_local is None:
            parsed_date = datetime.strptime(date_iso, "%Y-%m-%d")
            # sterngrove.org publishes no times. The 14:00 local fallback is
            # sourced from SFStation's already-ingested 2026 festival listing.
            start_local = parsed_date.replace(hour=14, tzinfo=SF_TZ)

        opening_acts = raw_item.get("opening_acts")
        description_parts = []
        if isinstance(opening_acts, str) and opening_acts:
            description_parts.append(f"Opening acts: {opening_acts}.")
        description_parts.append(
            "Admission is free, but attendance requires winning the advance GA lottery."
        )

        coords = lookup_venue_coordinates(self.venue_name)
        lat, lon = coords or (DEFAULT_SF_LAT, DEFAULT_SF_LON)
        source_url = raw_item.get("source_url") or self.lineup_url
        date_key = date_iso.replace("-", "")

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="sterngrove",
                source_record_id=f"sterngrove-{date_key}",
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="scrape",
                crawl_job_id=f"sterngrove-{int(self.utc_now().timestamp())}",
            ),
            title=title,
            description=" ".join(description_parts),
            start_time=start_local.astimezone(timezone.utc),
            end_time=None,
            location=LocationModel(
                venue_name=self.venue_name,
                address_line1=self.venue_address,
                city="San Francisco",
                region="CA",
                postal_code="94132",
                lat=lat,
                lon=lon,
                location_confidence=0.9 if coords else 0.3,
            ),
            offers=OffersModel(
                is_free=True,
                price_min=0.0,
                price_max=0.0,
                currency="USD",
                price_text="Free admission via advance GA lottery",
            ),
            organizer=OrganizerModel(name="Stern Grove Festival"),
            category_tags=["music", "festival"],
        )

    @staticmethod
    def _visible_lines(html: str) -> list[str]:
        """Flatten the page to non-empty visible text lines.

        Squarespace renders the whole body inside a single <article>, so there
        are no per-concert elements to key off — the season arrives as one flat
        run of blocks and the structure has to come from the text itself.
        """
        text = re.sub(
            r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = unescape(text)
        lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
        return [line for line in lines if line]

    def _extract_candidates(self, html: str) -> list[dict[str, Any]]:
        # The season we asked for is authoritative. Scanning the markup for a
        # year instead picks up whatever appears first — a copyright line, a
        # canonical link, a nav entry for a past season — and every concert
        # then lands in the wrong year. Because the weekday check below rejects
        # dates whose weekday no longer matches, that misfires as an empty
        # result rather than a visibly wrong one.
        year = self.season_year

        lines = self._visible_lines(html)
        # A concert block runs from its date line to the next one. Date lines
        # are anchored so the "Lottery opens June 21" that follows every
        # concert can't be read as another concert date.
        date_indexes = [
            index for index, line in enumerate(lines) if _DATE_PATTERN.match(line)
        ]

        candidates: list[dict[str, Any]] = []
        for position, start_index in enumerate(date_indexes):
            end_index = (
                date_indexes[position + 1]
                if position + 1 < len(date_indexes)
                else len(lines)
            )
            block = lines[start_index:end_index]
            date_match = _DATE_PATTERN.match(block[0])
            if date_match is None:
                continue
            try:
                event_date = datetime.strptime(
                    f"{date_match.group('month')} {date_match.group('day')} {year}",
                    "%B %d %Y",
                ).date()
            except ValueError:
                continue
            # The published weekday is a free integrity check on the season
            # year: if they disagree, we are about to emit a wrong date.
            if (
                event_date.strftime("%A").casefold()
                != date_match.group("weekday").casefold()
            ):
                continue

            body = [line for line in block[1:] if not _LOTTERY_PATTERN.match(line)]
            if not body:
                continue

            opening_acts = None
            for line in body[1:]:
                support_match = _SUPPORT_PATTERN.match(line)
                if support_match:
                    opening_acts = support_match.group(1).strip()
                    break

            # Only the card's own lines — headliner and support — can carry a
            # time. The last block runs to the end of the page, so scanning all
            # of it picks up the trailing lottery prose ("@ 10am") and makes
            # that the concert's start time.
            time_match = _TIME_PATTERN.search("\n".join(body[:_CARD_LINES]))

            candidates.append(
                {
                    "title": body[0],
                    "date_iso": event_date.isoformat(),
                    "time_text": time_match.group(0) if time_match else None,
                    "opening_acts": opening_acts,
                    "source_url": self.lineup_url,
                }
            )

        return candidates
