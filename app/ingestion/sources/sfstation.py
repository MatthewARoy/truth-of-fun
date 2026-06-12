"""SF Station scraper - arts + nightlife legacy listings."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OffersModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import (
    DEFAULT_SF_LAT,
    DEFAULT_SF_LON,
    SF_TZ,
    parse_datetime_flexible,
    parse_price,
    pick_first_str,
)
from app.ingestion.venue_cache import lookup_venue_coordinates

# Testable without API keys - public scraper
TESTABLE = True


class SFStationSource(InputAgentSource):
    """Scraper for SF Station Bay Area events calendar."""

    source_name = "sfstation"
    source_tier = 2
    base_url = "https://www.sfstation.com"
    calendar_url = "https://www.sfstation.com/calendar/bay-area"

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        html = kwargs.get("html")
        if isinstance(html, str):
            return self._extract_candidates(html)

        await self._limiter.acquire()
        response = await self._get_client().get(self.calendar_url)
        response.raise_for_status()
        return self._extract_candidates(response.text)

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = pick_first_str(raw_item, "title")
        source_url = pick_first_str(raw_item, "source_url")
        if not title or not source_url:
            return None

        start_time = self._parse_datetime(
            pick_first_str(raw_item, "date_iso"),
            pick_first_str(raw_item, "time_text"),
        )
        if start_time is None:
            return None

        price_text = pick_first_str(raw_item, "price_text")
        price_min, is_free = parse_price(price_text)
        venue_name = pick_first_str(raw_item, "venue_name")
        address = pick_first_str(raw_item, "address")

        coords = lookup_venue_coordinates(venue_name)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON
        confidence = 0.9 if coords else (0.5 if venue_name else 0.3)

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="sfstation",
                source_record_id=pick_first_str(raw_item, "source_record_id") or source_url,
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="scrape",
                crawl_job_id=f"sfstation-{int(self.utc_now().timestamp())}",
            ),
            title=title,
            start_time=start_time,
            location=LocationModel(
                venue_name=venue_name,
                address_line1=address,
                city="San Francisco",
                region="CA",
                lat=lat,
                lon=lon,
                location_confidence=confidence,
            ),
            offers=OffersModel(
                is_free=is_free,
                price_min=price_min,
                price_max=price_min,
                currency="USD",
                price_text=price_text,
            ),
            category_tags=raw_item.get("category_tags", []),
        )

    def _extract_candidates(self, html: str) -> list[dict[str, Any]]:
        """Extract event candidates from calendar HTML.

        The calendar renders each event as a schema.org Event block:
            <div class="event-wrapper" itemscope itemtype="http://schema.org/Event">
              <div class="event-date hidden" itemprop="startDate" content="2026-06-11">...
              <div class="event-time hidden">12:30pm - 1:30pm</div>
              <h4><a href="/slug-e1024101"><span itemprop="name">Title</span></a></h4>
              at ... <a href="/venue-b6842"><span itemprop="name">Venue</span></a> ...
        Event detail pages use -e<id> slugs; venue pages use -b<id> slugs.
        Blocks without an explicit startDate are dropped - dates are never guessed.
        """
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        block_starts = [m.start() for m in re.finditer(r'<div class="event-wrapper"[^>]*>', html)]
        for i, start in enumerate(block_starts):
            end = block_starts[i + 1] if i + 1 < len(block_starts) else len(html)
            block = html[start:end]

            date_match = re.search(
                r'itemprop="startDate"\s+content="(\d{4}-\d{2}-\d{2})"', block
            )
            if not date_match:
                continue  # No explicit date on the card - drop, never fabricate
            date_iso = date_match.group(1)

            title_match = re.search(
                r'<h4>\s*<a\s+href="(/[^"]*-e\d+)"[^>]*>\s*<span itemprop="name">([^<]+)</span>',
                block,
            )
            if not title_match:
                continue
            href = title_match.group(1).strip()
            title = title_match.group(2).strip()
            if not title:
                continue

            key = f"{href}|{date_iso}"
            if key in seen:
                continue
            seen.add(key)

            time_match = re.search(r'<div class="event-time hidden">([^<]*)</div>', block)
            time_text = time_match.group(1).strip() if time_match else ""

            venue_match = re.search(
                r'<a\s+href="/[^"]*-b\d+"[^>]*>\s*<span itemprop="name">([^<]+)</span>',
                block,
            )
            venue_name = venue_match.group(1).strip() if venue_match else None

            addr_match = re.search(r'itemprop="streetAddress">([^<]+)<', block)
            address = addr_match.group(1).strip() if addr_match else None

            price_text = None
            if re.search(r"\bFREE\b", block):
                price_text = "Free"
            else:
                price_match = re.search(
                    r'class="event-price"[^>]*content="(\d+(?:\.\d{2})?)"', block
                )
                if price_match:
                    price_text = f"${price_match.group(1)}"

            candidates.append(
                {
                    "title": title,
                    "source_url": f"{self.base_url}{href}",
                    "source_record_id": f"{date_iso}-{href.rstrip('/').split('/')[-1]}",
                    "date_iso": date_iso,
                    "time_text": time_text,
                    "venue_name": venue_name,
                    "address": address,
                    "price_text": price_text,
                    "category_tags": [],
                }
            )

        return candidates[:60]

    def _parse_datetime(self, date_iso: str | None, time_text: str | None) -> datetime | None:
        """Parse ISO date and time text into UTC datetime."""
        if not date_iso:
            return None
        combined = date_iso
        if time_text:
            combined = f"{date_iso} {time_text}"
        dt = parse_datetime_flexible(combined, default_hour=19, default_minute=0)
        if dt:
            return dt.astimezone(timezone.utc)
        return None
