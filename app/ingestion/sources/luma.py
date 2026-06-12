"""Luma scraper - SF startup/tech events. Uses Playwright for JS-rendered content."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import SocialSignalsModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import (
    DEFAULT_SF_LAT,
    DEFAULT_SF_LON,
    MONTH_ABBREV,
    SF_TZ,
    parse_datetime_flexible,
    strip_html_tags,
)
from app.ingestion.venue_cache import lookup_venue_coordinates

# Testable - uses Playwright (no API key). May need proxy for Cloudflare.
TESTABLE = True


class LumaSource(InputAgentSource):
    """
    Scraper for Luma SF events. Uses Playwright for JS-rendered content.
    Cloudflare/Turnstile may block; proxy rotation recommended.
    """

    source_name = "luma"
    source_tier = 2
    base_url = "https://luma.com"
    sf_events_url = "https://luma.com/sf"

    def __init__(
        self,
        *,
        headless: bool = True,
        proxy: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._headless = headless
        self._proxy = proxy

    def _resolve_proxy(self) -> str | None:
        if self._proxy is not None:
            return self._proxy
        return get_settings().get_proxy_for_scraper()

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        html = kwargs.get("html")
        if isinstance(html, str):
            return self._extract_candidates_from_html(html)

        # Luma is JS-rendered; use Playwright
        try:
            from playwright.async_api import async_playwright
            from playwright_stealth import Stealth
        except ImportError:
            # Fallback: try httpx (may get minimal content)
            await self._limiter.acquire()
            response = await self._get_client().get(self.sf_events_url)
            response.raise_for_status()
            return self._extract_candidates_from_html(response.text)

        playwright = await async_playwright().start()

        proxy_config = None
        proxy_url = self._resolve_proxy()
        if proxy_url:
            proxy_config = {"server": proxy_url}

        browser = await playwright.chromium.launch(
            headless=self._headless,
            proxy=proxy_config,
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        await Stealth().apply_stealth_async(context)
        page = await context.new_page()

        try:
            await page.goto(self.sf_events_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            html = await page.content()
            return self._extract_candidates_from_html(html)
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    def _extract_candidates_from_html(self, html: str) -> list[dict[str, Any]]:
        """Extract event candidates from Luma page HTML.

        Prefers the structured __NEXT_DATA__ payload (real start times); falls
        back to anchor scraping with date extraction from surrounding context.
        """
        structured = self._candidates_from_embedded_json(html)
        if structured:
            return structured[:50]

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Luma event links: luma.com/event-slug
        link_pattern = re.compile(
            r'<a\s+[^>]*href=["\'](https?://(?:www\.)?luma\.com/(?!sf\?|signin)[a-zA-Z0-9\-]+)["\'][^>]*>([^<]*)</a>',
            re.IGNORECASE,
        )
        for m in link_pattern.finditer(html):
            url = m.group(1).strip()
            link_text = m.group(2).strip()
            if not link_text or len(link_text) < 5:
                continue
            if url in seen:
                continue
            # Skip nav/utility links
            if any(skip in link_text.lower() for skip in ["submit", "sign in", "subscribe", "events"]):
                continue
            seen.add(url)

            # Extract attendee count (+371, +286, etc.) from surrounding context
            start = max(0, m.start() - 200)
            end = min(len(html), m.end() + 300)
            context = html[start:end]
            attendee_count = self._extract_attendee_count(context)
            location_text = self._extract_location_from_context(context)
            organizer_text = self._extract_organizer_from_context(context)
            date_text = self._extract_date_text_from_context(context)

            candidates.append(
                {
                    "title": link_text,
                    "source_url": url,
                    "source_record_id": url.rstrip("/").split("/")[-1] or url,
                    "attendee_count": attendee_count,
                    "location_text": location_text,
                    "organizer_name": organizer_text,
                    "date_text": date_text,
                }
            )

        # If we found few via links, try heading/text patterns
        if len(candidates) < 5:
            headings = re.findall(r"<h[2-4][^>]*>([^<]+)</h[2-4]>", html, re.IGNORECASE)
            for h in headings:
                title = re.sub(r"\s+", " ", h).strip()
                if len(title) < 10 or len(title) > 150:
                    continue
                if any(skip in title.lower() for skip in ["what's happening", "san francisco", "events", "submit"]):
                    continue
                key = f"h-{title[:60]}"
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "title": title,
                        "source_url": self.sf_events_url,
                        "source_record_id": f"luma-{title[:30]}",
                        "attendee_count": 0,
                        "location_text": None,
                        "organizer_name": None,
                    }
                )

        return candidates[:50]

    def _candidates_from_embedded_json(self, html: str) -> list[dict[str, Any]]:
        """Pull events out of the Next.js __NEXT_DATA__ JSON payload when present."""
        script_match = re.search(
            r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if not script_match:
            return []
        try:
            data = json.loads(script_match.group(1))
        except json.JSONDecodeError:
            return []

        found: list[dict[str, Any]] = []
        seen: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                title = node.get("name") or node.get("title")
                start = node.get("start_at") or node.get("startAt") or node.get("start_time")
                url = node.get("url") or node.get("event_url")
                if (
                    isinstance(title, str)
                    and title.strip()
                    and isinstance(start, str)
                    and isinstance(url, str)
                    and url not in seen
                ):
                    seen.add(url)
                    geo = node.get("geo_address_info")
                    location_text = (
                        geo.get("full_address") if isinstance(geo, dict) else None
                    )
                    guest_count = node.get("guest_count")
                    found.append(
                        {
                            "title": title.strip(),
                            "source_url": url,
                            "source_record_id": node.get("api_id")
                            or url.rstrip("/").split("/")[-1]
                            or url,
                            "start_iso": start,
                            "attendee_count": guest_count if isinstance(guest_count, int) else 0,
                            "location_text": location_text,
                            "organizer_name": None,
                        }
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)
        return found

    def _extract_date_text_from_context(self, context: str) -> str | None:
        """Find an explicit date (and optional time) near an event link."""
        text = strip_html_tags(context)

        iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
        date_part: str | None = iso_match.group(0) if iso_match else None
        if date_part is None:
            for m in re.finditer(r"\b([A-Za-z]{3,9})\.?\s+\d{1,2}(?:,\s*\d{4})?", text):
                if m.group(1)[:3].lower() in MONTH_ABBREV:
                    date_part = m.group(0)
                    break
        if date_part is None:
            return None

        time_match = re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", text, re.IGNORECASE)
        return f"{date_part} {time_match.group(0)}" if time_match else date_part

    def _extract_attendee_count(self, context: str) -> int:
        """Extract +371 style attendee count."""
        m = re.search(r"\+\s*(\d+)", context)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return 0

    def _extract_location_from_context(self, context: str) -> str | None:
        """Extract venue/location from context."""
        # "Frontier Tower @ Lounge 995 Market Street, San Francisco"
        at_match = re.search(r"@\s+([^\n]+?)(?:\s+[\+\d]|$)", context)
        if at_match:
            return at_match.group(1).strip()
        # "San Francisco, California"
        loc_match = re.search(r"(San Francisco|Oakland|Stanford)[^<]*California", context, re.IGNORECASE)
        if loc_match:
            return loc_match.group(0).strip()
        return None

    def _extract_organizer_from_context(self, context: str) -> str | None:
        """Extract organizer from 'By X, Y & Z' pattern."""
        by_match = re.search(r"\bBy\s+([^\n@]+?)(?:\s+@|\s*$)", context)
        if by_match:
            return by_match.group(1).strip()
        return None

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def _resolve_start_time(self, raw_item: dict[str, Any]) -> datetime | None:
        """Resolve a real start time from structured data or context date text."""
        start_iso = raw_item.get("start_iso")
        if isinstance(start_iso, str) and start_iso:
            try:
                parsed = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=SF_TZ)
                return parsed.astimezone(timezone.utc)

        date_text = raw_item.get("date_text")
        if isinstance(date_text, str) and date_text:
            parsed = parse_datetime_flexible(date_text)
            if parsed is not None:
                return parsed.astimezone(timezone.utc)

        return None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = raw_item.get("title")
        source_url = raw_item.get("source_url")
        if not isinstance(title, str) or not title.strip() or not source_url:
            return None

        # Events without a determinable start time are dropped, never fabricated.
        start_time = self._resolve_start_time(raw_item)
        if start_time is None:
            return None

        attendee_count = raw_item.get("attendee_count") or 0

        location_text = raw_item.get("location_text")
        coords = lookup_venue_coordinates(location_text)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON
        confidence = 0.9 if coords else (0.5 if location_text else 0.3)

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="luma",
                source_record_id=raw_item.get("source_record_id") or source_url,
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="scrape",
                crawl_job_id=f"luma-{int(self.utc_now().timestamp())}",
            ),
            title=title.strip(),
            start_time=start_time,
            location=LocationModel(
                venue_name=location_text,
                address_line1=location_text,
                city="San Francisco",
                region="CA",
                lat=lat,
                lon=lon,
                location_confidence=confidence,
            ),
            organizer=OrganizerModel(name=raw_item.get("organizer_name")),
            social_signals=SocialSignalsModel(
                attendee_count=attendee_count,
                popularity_score=min(float(attendee_count) / 500.0, 1.0) if attendee_count else 0.0,
            ),
            category_tags=["tech", "startup", "community"],
        )
