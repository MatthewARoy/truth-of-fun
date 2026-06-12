"""DoTheBay scraper - lifestyle curation and popularity signals."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OffersModel
from app.ingestion.contracts import SocialSignalsModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import (
    DEFAULT_SF_LAT,
    DEFAULT_SF_LON,
    SF_TZ,
    parse_12h_to_24h,
    parse_price,
    strip_html_tags,
)
from app.ingestion.venue_cache import lookup_venue_coordinates

# Testable without API keys - public scraper
TESTABLE = True


class DoTheBaySource(InputAgentSource):
    """Scraper for DoTheBay Bay Area events with vote/popularity extraction."""

    source_name = "dothebay"
    source_tier = 2
    base_url = "https://dothebay.com"
    events_url = "https://dothebay.com/events"

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        html = kwargs.get("html")
        if isinstance(html, str):
            return self._extract_candidates(html)

        await self._limiter.acquire()
        response = await self._get_client().get(self.events_url)
        response.raise_for_status()
        return self._extract_candidates(response.text)

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = raw_item.get("title")
        source_url = raw_item.get("source_url")
        if not isinstance(title, str) or not title.strip() or not source_url:
            return None

        start_time = self._parse_datetime(raw_item.get("date_text"), raw_item.get("time_text"))
        if start_time is None:
            return None

        price_text = raw_item.get("price_text", "")
        price_min, is_free = parse_price(price_text)
        vote_count = self._coerce_int(raw_item.get("vote_count")) or 0

        venue_name = raw_item.get("venue_name")
        coords = lookup_venue_coordinates(venue_name)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON
        confidence = 0.9 if coords else (0.5 if venue_name else 0.3)

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="dothebay",
                source_record_id=raw_item.get("source_record_id") or source_url,
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="scrape",
                crawl_job_id=f"dothebay-{int(self.utc_now().timestamp())}",
            ),
            title=title.strip(),
            start_time=start_time,
            location=LocationModel(
                venue_name=venue_name,
                address_line1=raw_item.get("address"),
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
                price_text=price_text or None,
            ),
            social_signals=SocialSignalsModel(
                vote_count=vote_count,
                popularity_score=min(float(vote_count) / 100.0, 1.0) if vote_count else 0.0,
            ),
            category_tags=raw_item.get("category_tags", []),
        )

    def _extract_candidates(self, html: str) -> list[dict[str, Any]]:
        """Extract event candidates from listing HTML."""
        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        # Event links: /events/2026/2/13/... or /events/weekly/...
        event_link_pattern = re.compile(
            r'<a\s+[^>]*href=["\'](https?://(?:www\.)?dothebay\.com/events/[^"\']+)["\'][^>]*>([^<]+)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in event_link_pattern.finditer(html):
            url = match.group(1).strip()
            title = strip_html_tags(match.group(2))
            if not title or url in seen_urls:
                continue
            if "/venues/" in url or "/users/" in url or "/events/sports" in url or "/events/recreation" in url:
                continue
            seen_urls.add(url)

            # Try to find venue and time in surrounding context (next ~500 chars)
            start = match.end()
            context = html[start : start + 800]
            venue_name = self._extract_venue_from_context(context)
            time_text = self._extract_time_from_context(context)
            date_text = self._extract_date_from_url(url) or self._extract_date_from_context(context)
            price_text = self._extract_price_from_context(context)
            vote_count = self._extract_vote_from_context(context)

            candidates.append(
                {
                    "title": title,
                    "source_url": url,
                    "source_record_id": url.rstrip("/").split("/")[-1] or url,
                    "venue_name": venue_name,
                    "date_text": date_text,
                    "time_text": time_text,
                    "price_text": price_text,
                    "vote_count": vote_count,
                    "category_tags": [],
                }
            )

        return candidates[:80]

    def _extract_venue_from_context(self, context: str) -> str | None:
        """Extract venue from venue link in context."""
        venue_match = re.search(
            r'<a\s+[^>]*href=["\']https?://[^"\']*dothebay\.com/venues/[^"\']+["\'][^>]*>([^<]+)</a>',
            context,
            re.IGNORECASE,
        )
        if venue_match:
            return strip_html_tags(venue_match.group(1))
        return None

    def _extract_time_from_context(self, context: str) -> str | None:
        """Extract time like 7:00PM, 6:00PM (doors)."""
        time_match = re.search(
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)(?:\s*\([^)]*\))?",
            context,
            re.IGNORECASE,
        )
        if time_match:
            return time_match.group(0).strip()
        return None

    def _extract_date_from_url(self, url: str) -> str | None:
        """Extract date from dated event URLs like /events/2026/3/2/...."""
        m = re.search(r"/events/(\d{4})/(\d{1,2})/(\d{1,2})/", url)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                return None
        return None

    def _extract_date_from_context(self, context: str) -> str | None:
        """Extract date from schema.org datetime attributes or 'Through Mar 28' text."""
        attr = re.search(r'(?:datetime|content)=["\'](\d{4}-\d{1,2}-\d{1,2})', context, re.IGNORECASE)
        if attr:
            return attr.group(1)
        through = re.search(r"Through\s+([A-Za-z]{3}\s+\d{1,2}(?:,\s*\d{4})?)", context, re.IGNORECASE)
        if through:
            return through.group(1).strip()
        return None

    def _extract_price_from_context(self, context: str) -> str | None:
        """Extract Free or price from context."""
        if re.search(r"\bFree\b", context, re.IGNORECASE):
            return "Free"
        price_match = re.search(r"\$\s*\d+(?:\.\d{2})?", context)
        if price_match:
            return price_match.group(0)
        return None

    def _extract_vote_from_context(self, context: str) -> int | None:
        """Extract vote count only when clearly vote-labeled - never guess from stray digits."""
        labeled = re.search(
            r'class=["\'][^"\']*vote[^"\']*["\'][^>]*>\s*(\d{1,6})\b',
            context,
            re.IGNORECASE,
        )
        if labeled:
            return self._coerce_int(labeled.group(1))
        labeled = re.search(r"\b(\d{1,6})\s+votes?\b", context, re.IGNORECASE)
        if labeled:
            return self._coerce_int(labeled.group(1))
        return None

    def _parse_datetime(self, date_text: str | None, time_text: str | None) -> datetime | None:
        """Parse date and time into UTC datetime. No parseable date => None, never fabricate."""
        base_date = None

        if date_text:
            iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(date_text))
            md = re.search(
                r"([A-Za-z]{3})\s+(\d{1,2})(?:,\s*(\d{4}))?",
                str(date_text),
                re.IGNORECASE,
            )
            if iso:
                try:
                    base_date = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
                except ValueError:
                    base_date = None
            elif md:
                from app.ingestion.scraper_utils import MONTH_ABBREV

                m = MONTH_ABBREV.get(md.group(1).lower()[:3])
                if m is not None:
                    d = int(md.group(2))
                    y = int(md.group(3)) if md.group(3) else datetime.now(SF_TZ).year
                    try:
                        base_date = date(y, m, d)
                    except ValueError:
                        base_date = None

        if base_date is None:
            return None

        hour, minute = 19, 0
        if time_text:
            tm = re.search(
                r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
                str(time_text),
                re.IGNORECASE,
            )
            if tm:
                hour = parse_12h_to_24h(int(tm.group(1)), tm.group(3))
                minute = int(tm.group(2) or 0)

        try:
            local_dt = datetime(
                base_date.year, base_date.month, base_date.day, hour, minute, 0, tzinfo=SF_TZ
            )
            return local_dt.astimezone(timezone.utc)
        except ValueError:
            return None

    def _coerce_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
