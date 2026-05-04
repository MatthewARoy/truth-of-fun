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
        """Extract event candidates from calendar HTML."""
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        # SF Station structure: date blocks with event titles and venue links
        # Pattern: 2026-03-02, time range, title, venue link, address
        # Event blocks often have structure like: <h4> or similar for title
        # Links to venue pages: /venue-name-b12345
        # Event links may be in format with date

        # Match event entries - look for date ISO + time + title + venue pattern
        # From fetched content: "2026-03-02" "7:15 pm - 9:00 pm" "Haight Laughsbury Comedy Show" at "O'Reilly's Pub"
        block_pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2})\s*\n\s*(\d{4}-\d{2}-\d{2})?\s*\n\s*([\d:apm\s\-]+)\s*\n\s*(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s*\n\s*(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s*\n\s*####\s+([^\n]+)\s*\n\s*at\s+\[([^\]]+)\]\(([^)]+)\)",
            re.IGNORECASE | re.MULTILINE,
        )
        for m in block_pattern.finditer(html):
            date_iso = m.group(1)
            time_text = m.group(3).strip()
            title = m.group(4).strip()
            venue_name = m.group(5).strip()
            venue_url = m.group(6).strip()
            if venue_url.startswith("/"):
                venue_url = f"{self.base_url}{venue_url}"
            source_url = venue_url  # Use venue as source for now; event detail may differ
            key = f"{title}|{date_iso}|{time_text}"
            if key in seen:
                continue
            seen.add(key)

            # Extract address from following content (e.g. "1840 Haight Street San Francisco, CA")
            addr_match = re.search(
                r"(\d+\s+[A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Blvd|Road|Rd|Way|Drive|Dr)\.?\s+[A-Za-z\s,]+CA)",
                html[m.end() : m.end() + 300],
            )
            address = addr_match.group(1).strip() if addr_match else None

            # Price: FREE or [Buy Tickets]| [RSVP]
            price_text = None
            price_ctx = html[m.end() : m.end() + 400]
            if re.search(r"\bFREE\b", price_ctx, re.IGNORECASE):
                price_text = "Free"
            elif re.search(r"\[Buy Tickets\]|\[Register\]|\[RSVP\]", price_ctx):
                price_text = None  # Paid, amount not in listing

            candidates.append(
                {
                    "title": title,
                    "source_url": source_url,
                    "source_record_id": f"{date_iso}-{title[:30]}",
                    "date_iso": date_iso,
                    "time_text": time_text,
                    "venue_name": venue_name,
                    "address": address,
                    "price_text": price_text,
                    "category_tags": [],
                }
            )

        # Fallback: simpler pattern for different HTML structure
        if not candidates:
            # Alternative: href to event/venue + title
            alt_pattern = re.compile(
                r'<a\s+[^>]*href=["\'](https?://(?:www\.)?sfstation\.com/[^"\']+)["\'][^>]*>([^<]+)</a>',
                re.IGNORECASE,
            )
            for m in alt_pattern.finditer(html):
                url = m.group(1)
                title = m.group(2).strip()
                if not title or len(title) < 5 or "calendar" in url or "event/add" in url:
                    continue
                if any(skip in url for skip in ["/about", "/contact", "/subscribe", "/terms"]):
                    continue
                key = f"{title}|{url}"
                if key in seen:
                    continue
                seen.add(key)
                # Try to get date from context
                ctx = html[max(0, m.start() - 300) : m.end() + 200]
                date_iso = None
                dm = re.search(r"(\d{4}-\d{2}-\d{2})", ctx)
                if dm:
                    date_iso = dm.group(1)
                candidates.append(
                    {
                        "title": title,
                        "source_url": url,
                        "source_record_id": url.rstrip("/").split("/")[-1] or url,
                        "date_iso": date_iso,
                        "time_text": "",
                        "venue_name": None,
                        "address": None,
                        "price_text": None,
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
