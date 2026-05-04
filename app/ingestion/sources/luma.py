"""Luma scraper - SF startup/tech events. Uses Playwright for JS-rendered content."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import SocialSignalsModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import DEFAULT_SF_LAT, DEFAULT_SF_LON, SF_TZ
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
        stealth = Stealth()
        stealth.use_async(playwright)

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
        """Extract event candidates from Luma page HTML."""
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

            candidates.append(
                {
                    "title": link_text,
                    "source_url": url,
                    "source_record_id": url.rstrip("/").split("/")[-1] or url,
                    "attendee_count": attendee_count,
                    "location_text": location_text,
                    "organizer_name": organizer_text,
                }
            )

        # Alternative: look for event card structures (Luma may use specific classes)
        # Pattern for "By X, Y & Z" organizer line
        by_pattern = re.compile(r"\bBy\s+([^\n]+?)(?:\s+@\s+|\s*\n|$)")
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

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = raw_item.get("title")
        source_url = raw_item.get("source_url")
        if not isinstance(title, str) or not title.strip() or not source_url:
            return None

        # Luma events often don't have explicit date in listing; use placeholder
        now = datetime.now(SF_TZ)
        start_time = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        start_time = start_time.astimezone(timezone.utc)

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
