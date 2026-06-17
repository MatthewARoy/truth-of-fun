"""FuncheapSF Tier 2 scraper using Playwright with stealth."""

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from app.core.config import get_settings
from app.ingestion.base import BaseSource
from app.ingestion.venue_cache import lookup_venue_coordinates

logger = logging.getLogger(__name__)

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

    @staticmethod
    async def _wait_for_content(page: Any, selector: str, *, timeout: int) -> None:
        """Wait for real content to appear without depending on a quiet network.

        funcheapsf.com keeps ads/trackers/long-polling requests in flight, so
        ``wait_for_load_state("networkidle")`` never resolves and used to abort the
        scrape. We wait for the content selector instead and swallow timeouts: the
        page is already at ``domcontentloaded`` from ``goto``, so proceeding on a
        timeout is safe and lets the downstream selectors do the validation.
        """
        try:
            await page.wait_for_selector(selector, timeout=timeout)
        except PlaywrightTimeoutError:
            pass

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
            try:
                await page.goto(
                    self.events_url, wait_until="domcontentloaded", timeout=30000
                )
                # FuncheapSF runs ads/trackers/long-polling that never let the network go
                # idle, so we wait for the actual content to appear instead of
                # "networkidle" and treat any settle timeout as best-effort (proceed,
                # never abort). The events URL redirects to sf.funcheap.com.
                await self._wait_for_content(
                    page, "a[href*='funcheap.com']", timeout=15000
                )

                # Single-segment slugs that are site navigation, not event pages; skip
                # them so the detail-page budget is spent on real events (they would all
                # be dropped anyway for having no single-event date).
                nav_slug_re = (
                    "/(events|free-events|today|weekend|win|subscribe|submit-form|about|"
                    "privacy-policy|terms-service|dmca-requests|contact|advertise|"
                    "newsletter|free-museum-days|add-event)/?$"
                )
                links = await page.locator(
                    "a[href*='sf.funcheap.com'][href*='/']"
                ).evaluate_all(
                    """(els, navSlug) => els
                        .map(a => a.href)
                        .filter(h => /sf\\.funcheap\\.com\\/[^/]+\\/?$/.test(h) && !h.includes('/category/') && !h.includes('/venue/') && !h.includes('/region/') && !h.includes('/city-guide/') && !h.includes('/wp-') && !h.includes('/2026/') && !h.includes('/feed') && !new RegExp(navSlug).test(h))
                        .filter((v, i, a) => a.indexOf(v) === i)
                        .slice(0, 50)
                    """,
                    nav_slug_re,
                )
            except PlaywrightTimeoutError as exc:
                # Hard navigation failure (e.g. an anti-bot challenge stealth can't pass).
                # Fail gracefully rather than raising: no fabricated events.
                logger.warning(
                    "funcheap_sf: could not load %s (%s); returning no events.",
                    self.events_url,
                    exc,
                )
                return []
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
        # The event title (an <h1>) is the cheapest reliable "page is ready" signal;
        # wait for it instead of an unsettleable networkidle (see _wait_for_content).
        await self._wait_for_content(page, "h1", timeout=10000)

        title_el = page.locator("h1.entry-title, h1.post-title, article h1, h1").first
        title = await title_el.text_content() if await title_el.count() else None
        if not title or not title.strip():
            return None

        title = title.strip()

        # The single-event detail block (date, time, cost, venue, address) lives in the
        # container that wraps the ".cost" element, e.g. <span class="left">. Reading the
        # whole block in one shot is resilient to the per-field class churn the site has
        # gone through, and listing/nav pages (no real single-event date) yield no block
        # and get dropped by _parse_date_and_time below.
        detail_text = await self._read_detail_block(page)

        venue_name = None
        venue_el = page.locator(
            "a[href*='/venue/'], .venue-name, .event-venue, .location"
        ).first
        if await venue_el.count():
            venue_name = (await venue_el.text_content()) or ""
            venue_name = venue_name.strip() or None

        raw_address = self._extract_address(detail_text)
        if not raw_address and venue_name:
            raw_address = f"{venue_name}, San Francisco, CA"

        cost_text = ""
        cost_el = page.locator(
            ".cost, .event-cost, .price, [class*='cost'], [class*='price']"
        ).first
        if await cost_el.count():
            cost_text = (await cost_el.text_content()) or ""

        # date_text drives relative-date and absolute-date detection; full_text additionally
        # carries the time/cost. The detail block holds the canonical date string.
        date_text = detail_text or cost_text
        full_text = f"{detail_text} {cost_text}"
        start_at, end_at = self._parse_date_and_time(full_text, date_text)
        if start_at is None:
            return None

        price, currency = self._parse_cost(cost_text or detail_text)

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

    @staticmethod
    async def _read_detail_block(page: Any) -> str:
        """Return the event-detail text block (date/time/cost/venue/address) as one string.

        The block is the container wrapping the ".cost" element. Returns "" when the page
        has no such block (e.g. listing/nav pages), which the caller treats as "no date".
        """
        try:
            text = await page.evaluate(
                """() => {
                    const cost = document.querySelector('.cost');
                    if (!cost) return '';
                    const block = cost.closest('span.left, .single_event_details, p, div');
                    return (block ? block.innerText : cost.innerText) || '';
                }"""
            )
        except Exception:
            return ""
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _extract_address(detail_text: str) -> str | None:
        """Pull a street address out of the detail block, e.g. '1 Market Street, ...'.

        The block formats the address as '... | <Venue> | <street>, <City>, CA ...'.
        Returns None when no street-like segment is present (never fabricated).
        """
        if not detail_text:
            return None
        # Find a segment that starts with a street number and runs to a state abbrev.
        m = re.search(
            r"(\d{1,6}\s+[^|]*?,\s*[A-Za-z .]+,\s*[A-Z]{2}(?:\s+\d{5})?)",
            detail_text,
        )
        if m:
            return m.group(1).strip()
        return None

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
