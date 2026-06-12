"""FuncheapSF Tier 2 scraper using Playwright with stealth."""

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from app.core.config import get_settings
from app.ingestion.base import BaseSource
from app.ingestion.venue_cache import lookup_venue_coordinates

SF_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194


class FuncheapSFSource(BaseSource):
    """Tier 2 scraper for FuncheapSF using Playwright with stealth."""

    source_name = "funcheap_sf"
    source_tier = 2
    base_url = "https://funcheapsf.com"
    events_url = "https://funcheapsf.com/events/"

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
        self._playwright = None
        self._browser = None

    def _resolve_proxy(self) -> str | None:
        if self._proxy is not None:
            return self._proxy
        return get_settings().get_proxy_for_scraper()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        await super().close()

    async def fetch_events(
        self,
        *,
        max_events: int = 50,
        max_detail_pages: int = 30,
    ) -> list[dict[str, Any]]:
        """Navigate homepage/events, extract event details, return canonical Event payloads."""
        self._playwright = await async_playwright().start()

        proxy_config = None
        proxy_url = self._resolve_proxy()
        if proxy_url:
            proxy_config = {"server": proxy_url}

        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            proxy=proxy_config,
        )
        context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        await Stealth().apply_stealth_async(context)
        page = await context.new_page()

        try:
            event_links: list[str] = []
            await page.goto(self.events_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=10000)

            links = await page.locator(
                "a[href*='sf.funcheap.com'][href*='/']"
            ).evaluate_all(
                """els => els
                    .map(a => a.href)
                    .filter(h => /sf\\.funcheap\\.com\\/[^/]+\\/?$/.test(h) && !h.includes('/category/') && !h.includes('/venue/') && !h.includes('/region/') && !h.includes('/city-guide/') && !h.includes('/wp-') && !h.includes('/2026/') && !h.includes('/feed'))
                    .filter((v, i, a) => a.indexOf(v) === i)
                    .slice(0, 50)
                """
            )
            event_links = links[:max_detail_pages]

            canonical: list[dict[str, Any]] = []
            seen_urls: set[str] = set()

            for url in event_links:
                if url in seen_urls or len(canonical) >= max_events:
                    continue
                seen_urls.add(url)

                try:
                    payload = await self._scrape_event_detail(page, url)
                    if payload:
                        canonical.append(payload)
                except Exception:
                    continue

            return canonical
        finally:
            await context.close()

    async def _scrape_event_detail(self, page: Any, url: str) -> dict[str, Any] | None:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_load_state("networkidle", timeout=8000)

        title_el = page.locator("h1.entry-title, h1.post-title, article h1").first
        title = await title_el.text_content() if await title_el.count() else None
        if not title or not title.strip():
            return None

        title = title.strip()

        date_text = ""
        date_el = page.locator(
            ".event-date, .entry-meta .date, .event-details, .event-info, .event-meta"
        ).first
        if await date_el.count():
            date_text = (await date_el.text_content()) or ""

        venue_name = None
        venue_el = page.locator(
            "a[href*='/venue/'], .venue-name, .event-venue, .location"
        ).first
        if await venue_el.count():
            venue_name = (await venue_el.text_content()) or ""
            venue_name = venue_name.strip() or None

        raw_address = None
        addr_el = page.locator(
            ".address, .event-address, .venue-address, [class*='address']"
        ).first
        if await addr_el.count():
            raw_address = (await addr_el.text_content()) or ""
            raw_address = raw_address.strip() or None
        if not raw_address and venue_name:
            raw_address = f"{venue_name}, San Francisco, CA"

        cost_text = ""
        cost_el = page.locator(
            ".cost, .event-cost, .price, [class*='cost'], [class*='price']"
        ).first
        if await cost_el.count():
            cost_text = (await cost_el.text_content()) or ""

        full_text = f"{date_text} {cost_text}"
        start_at, end_at = self._parse_date_and_time(full_text, date_text)
        if start_at is None:
            return None

        price, currency = self._parse_cost(cost_text)

        source_event_id = url.rstrip("/").split("/")[-1] or url

        coords = lookup_venue_coordinates(venue_name)
        lat, lon = coords if coords else (DEFAULT_SF_LAT, DEFAULT_SF_LON)

        return {
            "title": title,
            "description": None,
            "start_at": start_at,
            "end_at": end_at,
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "source_event_id": source_event_id,
            "external_url": url,
            "venue_name": venue_name,
            "raw_address": raw_address,
            "location": f"POINT({lon} {lat})",
            "location_confidence": 0.9 if coords else (0.5 if venue_name else 0.3),
            "categories": [],
            "tags": [],
            "price": price,
            "currency": currency,
            "image_url": None,
            "status": "scheduled",
        }

    def _parse_date_and_time(
        self, full_text: str, date_text: str
    ) -> tuple[datetime | None, datetime | None]:
        """Parse date/time, handling relative dates (Today, Tomorrow), return UTC datetimes."""
        now = datetime.now(SF_TZ).date()
        base_date = None

        date_lower = date_text.lower()

        if "today" in date_lower or "tonight" in date_lower:
            base_date = now
        elif "tomorrow" in date_lower:
            base_date = now + timedelta(days=1)
        elif "yesterday" in date_lower:
            base_date = now - timedelta(days=1)
        else:
            base_date = self._parse_absolute_date(date_text)

        if base_date is None:
            # No real date evidence on the page - never fabricate one, drop the event.
            return None, None

        time_match = re.search(
            r"(\d{1,2}):(\d{2})\s*(am|pm)?|(\d{1,2})\s*(am|pm)",
            full_text,
            re.IGNORECASE,
        )
        hour, minute = 0, 0
        if time_match:
            g = time_match.groups()
            if g[0] is not None and g[1] is not None:
                hour = int(g[0])
                minute = int(g[1])
                if g[2] and g[2].lower() == "pm" and hour < 12:
                    hour += 12
                elif g[2] and g[2].lower() == "am" and hour == 12:
                    hour = 0
            elif g[3] is not None and g[4]:
                hour = int(g[3])
                if g[4].lower() == "pm" and hour < 12:
                    hour += 12
                elif g[4].lower() == "am" and hour == 12:
                    hour = 0

        start_dt = datetime(
            base_date.year, base_date.month, base_date.day, hour, minute, 0, tzinfo=SF_TZ
        )
        start_utc = start_dt.astimezone(timezone.utc)

        # Look for an end time only AFTER the start time, behind an explicit separator,
        # so the start time itself can never be re-matched as the end time.
        end_at = None
        end_match = None
        if time_match:
            end_match = re.search(
                r"(?:to|until|[-–])\s*(?:(\d{1,2}):(\d{2})\s*(am|pm)?|(\d{1,2})\s*(am|pm))",
                full_text[time_match.end():],
                re.IGNORECASE,
            )
        if end_match:
            g = end_match.groups()
            if g[0] is not None and g[1] is not None:
                eh, em = int(g[0]), int(g[1])
                if g[2] and g[2].lower() == "pm" and eh < 12:
                    eh += 12
                elif g[2] and g[2].lower() == "am" and eh == 12:
                    eh = 0
            else:
                eh, em = int(g[3]), 0
                if g[4].lower() == "pm" and eh < 12:
                    eh += 12
                elif g[4].lower() == "am" and eh == 12:
                    eh = 0
            try:
                end_dt = datetime(
                    base_date.year, base_date.month, base_date.day, eh, em, 0, tzinfo=SF_TZ
                )
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)
                end_at = end_dt.astimezone(timezone.utc)
            except ValueError:
                end_at = None

        return start_utc, end_at

    def _parse_absolute_date(self, text: str) -> date | None:
        """Parse absolute date like 'Sunday, March 1, 2026' or 'March 1, 2026'."""
        patterns = [
            r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,\s+(\w+)\s+(\d{1,2}),\s+(\d{4})",
            r"(\w+)\s+(\d{1,2}),\s+(\d{4})",
            r"(\d{4})-(\d{2})-(\d{2})",
        ]
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                g = m.groups()
                if len(g) == 3:
                    try:
                        if g[0].isdigit():
                            y, mo, d = int(g[0]), int(g[1]), int(g[2])
                        else:
                            mo_name = g[0].lower()[:3]
                            mo = months.get(mo_name)
                            if mo is None:
                                continue
                            d, y = int(g[1]), int(g[2])
                        return date(y, mo, d)
                    except (ValueError, KeyError, IndexError):
                        continue
        return None

    def _parse_cost(self, text: str) -> tuple[float | None, str | None]:
        """Extract numeric price and currency from cost text."""
        if not text:
            return None, None
        text_lower = text.lower()
        if "free" in text_lower and "$" not in text:
            return 0.0, "USD"
        m = re.search(r"\$\s*(\d+(?:\.\d{2})?)", text)
        if m:
            try:
                return float(m.group(1)), "USD"
            except ValueError:
                pass
        return None, None
