"""FuncheapSF Tier 2 scraper using Playwright with stealth."""

import asyncio
import html as html_lib
import json
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
from app.ingestion.scraper_utils import find_next_page_url
from app.ingestion.venue_cache import lookup_venue_coordinates

logger = logging.getLogger(__name__)

SF_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194
# What a day index says when nothing is listed, including on a page past the
# day's last one (which still links rel="next").
_EMPTY_DAY_RE = re.compile(
    r"don(?:'|\u2019|&#8217;|&#039;)t have any Funcheap events listed", re.IGNORECASE
)


class FuncheapSFSource(BaseSource):
    """Tier 2 scraper for FuncheapSF using Playwright with stealth."""

    source_name = "funcheap_sf"
    source_tier = 2
    base_url = "https://funcheapsf.com"
    day_index_url_template = "https://sf.funcheap.com/%Y/%m/%d/"

    # Section and nav slugs that share the single-segment shape of event URLs.
    _NAV_SLUGS = frozenset(
        {
            "events",
            "free-events",
            "today",
            "weekend",
            "win",
            "subscribe",
            "submit-form",
            "about",
            "privacy-policy",
            "terms-service",
            "dmca-requests",
            "contact",
            "advertise",
            "newsletter",
            "free-museum-days",
            "add-event",
            "category",
            "venue",
            "region",
            "city-guide",
            "feed",
        }
    )

    def __init__(
        self,
        *,
        headless: bool = True,
        proxy: str | None = None,
        page_delay_seconds: float = 1.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._headless = headless
        self._proxy = proxy
        self._page_delay_seconds = page_delay_seconds
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

    def _day_index_urls(
        self,
        *,
        horizon_days: int,
        today: date | None = None,
    ) -> list[str]:
        """Per-day index URLs covering ``horizon_days`` from ``today`` (SF-local).

        The homepage only promotes the next day or two, so crawling it alone
        silently caps coverage well short of the weekend people are planning
        for. The dated index pages are the complete listing for each day.
        """
        start = today or datetime.now(SF_TZ).date()
        return [
            (start + timedelta(days=offset)).strftime(self.day_index_url_template)
            for offset in range(horizon_days)
        ]

    def _is_event_url(self, url: str) -> bool:
        """True for single-segment event detail pages on sf.funcheap.com.

        Day indexes (``/2026/08/02/``) are crawl entry points rather than
        events, and the section/nav slugs below never carry a single-event
        date, so they would be dropped downstream anyway.
        """
        match = re.match(r"^https?://sf\.funcheap\.com/([^/?#]+)/?$", url)
        if not match:
            return False
        slug = match.group(1)
        if slug.isdigit() or slug.startswith("wp-"):
            return False
        return slug not in self._NAV_SLUGS

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
        max_events: int = 1000,
        max_detail_pages: int = 100,
        horizon_days: int = 10,
        max_index_pages_per_day: int = 3,
    ) -> list[dict[str, Any]]:
        """Crawl per-day index pages over the horizon, return canonical Event payloads.

        ``horizon_days`` defaults to 10 so the crawl always spans the next two
        weekends. Each day index is paginated (``/page/2/``) and embeds its
        events as a JSON-LD array, so the horizon costs ~20-30 page loads;
        detail pages are only visited for an index page without that JSON-LD.
        """
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
            return await self._crawl_day_indexes(
                page,
                horizon_days=horizon_days,
                max_index_pages_per_day=max_index_pages_per_day,
                max_events=max_events,
                max_detail_pages=max_detail_pages,
            )
        finally:
            await context.close()

    async def _crawl_day_indexes(
        self,
        page: Any,
        *,
        horizon_days: int,
        max_index_pages_per_day: int,
        max_events: int,
        max_detail_pages: int,
        today: date | None = None,
    ) -> list[dict[str, Any]]:
        self.last_fetch_error = None
        payloads: dict[str, dict[str, Any]] = {}
        fallback_links: dict[str, None] = {}
        loads = 0

        for day_url in self._day_index_urls(horizon_days=horizon_days, today=today):
            url: str | None = day_url
            for page_number in range(1, max_index_pages_per_day + 1):
                if url is None:
                    break
                if loads:
                    await self._pause()
                loads += 1
                html = await self._load_index_page(page, url)
                if html is None:
                    self.last_fetch_error = "Index page failed; crawl incomplete"
                    # One bad day page (anti-bot challenge, transient failure) must
                    # not sink the whole horizon. Skip that day; never fabricate.
                    break
                events = self._events_from_index_html(html)
                for payload in events:
                    # Multi-day listings repeat across a day's pages.
                    payloads.setdefault(payload["external_url"], payload)
                if not events:
                    # Past a day's last page the site serves its "no events listed"
                    # page, still linking rel="next", so an empty page ends the day.
                    # Only a first page with no JSON-LD and no such notice means the
                    # template changed: then fall back to the detail pages rather
                    # than silently losing the day.
                    if page_number == 1 and not _EMPTY_DAY_RE.search(html):
                        for href in self._event_links_from_html(html):
                            fallback_links.setdefault(href, None)
                    break
                url = self._next_index_page_url(html, day_url, page_number)
            else:
                if url is not None:
                    self.last_fetch_error = "Index page cap reached; crawl incomplete"

        if not payloads and not fallback_links:
            logger.warning(
                "funcheap_sf: no events found across %s day pages.", horizon_days
            )
            return []

        detail_budget = max_detail_pages
        for href in fallback_links:
            if href in payloads:
                continue
            if len(payloads) >= max_events or detail_budget <= 0:
                self.last_fetch_error = "Detail/event cap reached; crawl incomplete"
                logger.warning(
                    "funcheap_sf: detail-page fallback stopped at its cap (%s pages).",
                    max_detail_pages,
                )
                break
            detail_budget -= 1
            await self._pause()
            try:
                payload = await self._scrape_event_detail(page, href)
            except Exception:
                continue
            if payload:
                payloads[href] = payload

        if len(payloads) > max_events:
            self.last_fetch_error = "Event cap reached; crawl incomplete"
        return list(payloads.values())[:max_events]

    async def _load_index_page(self, page: Any, url: str) -> str | None:
        """Return a day index page's HTML, or None when it would not load."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # FuncheapSF runs ads/trackers/long-polling that never let the
            # network go idle, so we wait for the actual content to appear
            # instead of "networkidle" and treat any settle timeout as
            # best-effort (proceed, never abort).
            await self._wait_for_content(page, "a[href*='funcheap.com']", timeout=15000)
            return await page.content()
        except PlaywrightTimeoutError as exc:
            logger.warning(
                "funcheap_sf: could not load %s (%s); skipping the rest of that day.",
                url,
                exc,
            )
            return None

    async def _pause(self) -> None:
        """Space out page loads; the source spec asks to respect crawl frequency."""
        if self._page_delay_seconds > 0:
            await asyncio.sleep(self._page_delay_seconds)

    @staticmethod
    def _next_index_page_url(html: str, day_url: str, page_number: int) -> str | None:
        """The day's next index page, only if the page itself links to it."""
        expected = f"{day_url}page/{page_number + 1}/"
        return expected if find_next_page_url(html, day_url) == expected else None

    def _event_links_from_html(self, html: str) -> list[str]:
        links: dict[str, None] = {}
        for href in re.findall(
            r"href=[\"'](https?://sf\.funcheap\.com/[^\"'#?]+)[\"']", html
        ):
            if self._is_event_url(href):
                links.setdefault(href, None)
        return list(links)

    def _events_from_index_html(self, html: str) -> list[dict[str, Any]]:
        """Event payloads from the JSON-LD array a day index page embeds."""
        payloads: list[dict[str, Any]] = []
        for block in re.findall(
            r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                data = json.loads(block.strip())
            except ValueError:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "Event":
                    payload = self._payload_from_ld_event(item)
                    if payload is not None:
                        payloads.append(payload)
        return payloads

    _LD_STATUSES: dict[str, str] = {
        "eventcancelled": "cancelled",
        "eventpostponed": "postponed",
    }

    def _payload_from_ld_event(self, item: dict[str, Any]) -> dict[str, Any] | None:
        title = self._ld_text(item.get("name"))
        url = self._ld_text(item.get("url"))
        if not title or not url or not self._is_event_url(url):
            return None

        start = self._parse_ld_datetime(item.get("startDate"))
        if start is None:
            # No real date evidence - never fabricate one, drop the event.
            return None
        start_at, start_time_is_estimated = start
        end = self._parse_ld_datetime(item.get("endDate"))
        end_at = end[0] if end and not end[1] and end[0] > start_at else None

        location = (
            item.get("location") if isinstance(item.get("location"), dict) else {}
        )
        venue_name = self._ld_text(location.get("name")) or None
        raw_address = self._ld_address(location.get("address"))
        if not raw_address and venue_name:
            raw_address = f"{venue_name}, San Francisco, CA"

        coords = lookup_venue_coordinates(venue_name)
        lat, lon = coords if coords else (DEFAULT_SF_LAT, DEFAULT_SF_LON)

        status_name = str(item.get("eventStatus") or "").rstrip("/").split("/")[-1]
        cost_fields = self._ld_offer_fields(item.get("offers"))

        return {
            "title": title,
            "description": self._ld_text(item.get("description")) or None,
            "start_at": start_at,
            "start_time_is_estimated": start_time_is_estimated,
            "end_at": end_at,
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "source_event_id": url.rstrip("/").split("/")[-1] or url,
            "external_url": url,
            "venue_name": venue_name,
            "raw_address": raw_address,
            "location": f"POINT({lon} {lat})",
            # Knowing the venue's name doesn't locate it: without a cache hit
            # this is still the SF centroid, so it must stay below the radius
            # search threshold rather than claiming 0.5.
            "location_confidence": 0.9 if coords else 0.4,
            "categories": [],
            "tags": [],
            "price": cost_fields["price"],
            "currency": cost_fields["currency"],
            "is_free": cost_fields["is_free"],
            "image_url": None,
            "status": self._LD_STATUSES.get(status_name.lower(), "scheduled"),
        }

    @staticmethod
    def _ld_text(value: Any) -> str:
        """JSON-LD strings arrive HTML-escaped (``&#8220;``, ``&#038;``)."""
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()

    def _ld_address(self, value: Any) -> str | None:
        if isinstance(value, dict):
            parts = (
                self._ld_text(value.get(key))
                for key in (
                    "streetAddress",
                    "addressLocality",
                    "addressRegion",
                    "postalCode",
                )
            )
            return ", ".join(part for part in parts if part) or None
        return self._ld_text(value) or None

    @staticmethod
    def _parse_ld_datetime(value: Any) -> tuple[datetime, bool] | None:
        """Parse a JSON-LD date into (UTC datetime, time_is_estimated).

        The index publishes full offsets (``2026-09-13T19:00:00-07:00``). A bare
        date is still a real date, so it is kept at SF midnight and flagged as
        having no published time.
        """
        if not isinstance(value, str) or not re.match(
            r"\d{4}-\d{2}-\d{2}", value.strip()
        ):
            return None
        text = value.strip()
        if "T" not in text:
            try:
                day = date.fromisoformat(text[:10])
            except ValueError:
                return None
            midnight = datetime(day.year, day.month, day.day, tzinfo=SF_TZ)
            return midnight.astimezone(timezone.utc), True
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SF_TZ)
        return parsed.astimezone(timezone.utc), False

    @staticmethod
    def _ld_offer_fields(offers: Any) -> dict[str, Any]:
        """price/currency/is_free from JSON-LD ``offers``; an unknown price stays null.

        The index publishes whole dollars here (11 for a "$11.59" listing), which
        is close enough to rank and filter on, and 0 exactly for its FREE events.
        """
        if isinstance(offers, list):
            offers = next((offer for offer in offers if isinstance(offer, dict)), None)
        if not isinstance(offers, dict) or offers.get("price") in (None, ""):
            return {"price": None, "currency": None, "is_free": False}
        try:
            value = float(str(offers["price"]).replace("$", "").strip())
        except ValueError:
            return {"price": None, "currency": None, "is_free": False}
        currency = offers.get("priceCurrency")
        if not isinstance(currency, str) or not currency.strip():
            currency = "USD"
        return {"price": value, "currency": currency.strip(), "is_free": value == 0.0}

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

        cost_fields = self._cost_fields(cost_text, detail_text)

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
            # Knowing the venue's name doesn't locate it: without a cache hit
            # this is still the SF centroid, so it must stay below the radius
            # search threshold rather than claiming 0.5.
            "location_confidence": 0.9 if coords else 0.4,
            "categories": [],
            "tags": [],
            "price": cost_fields["price"],
            "currency": cost_fields["currency"],
            "is_free": cost_fields["is_free"],
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
            base_date.year,
            base_date.month,
            base_date.day,
            hour,
            minute,
            0,
            tzinfo=SF_TZ,
        )
        start_utc = start_dt.astimezone(timezone.utc)

        # Look for an end time only AFTER the start time, behind an explicit separator,
        # so the start time itself can never be re-matched as the end time.
        end_at = None
        end_match = None
        if time_match:
            end_match = re.search(
                r"(?:to|until|[-–])\s*(?:(\d{1,2}):(\d{2})\s*(am|pm)?|(\d{1,2})\s*(am|pm))",
                full_text[time_match.end() :],
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
                    base_date.year,
                    base_date.month,
                    base_date.day,
                    eh,
                    em,
                    0,
                    tzinfo=SF_TZ,
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
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
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

    _NO_COST: dict[str, Any] = {"price": None, "currency": None, "is_free": False}

    def _cost_fields(self, *texts: str) -> dict[str, Any]:
        """Extract price/currency/is_free from the first informative text.

        Candidates are tried in order because the site splits the label from
        the value: the ``.cost`` element is frequently just ``" | Cost:"``
        while the real figure sits in the detail block, so a plain
        ``cost_text or detail_text`` picks the useless one.

        Within a candidate, scope to the ``Cost:`` label when present. The
        detail block also carries date, venue and address, so a bare "is there
        a ``$`` anywhere" test misreads free events that merely mention a price
        nearby ("Cost: FREE | $1 Beer after").
        """
        for text in texts:
            if not text:
                continue
            fields = self._cost_fields_from(text)
            if fields != self._NO_COST:
                return fields
        return dict(self._NO_COST)

    def _cost_fields_from(self, text: str) -> dict[str, Any]:
        label = re.search(r"cost:\s*([^|\n]*)", text, flags=re.IGNORECASE)
        scope = label.group(1) if label else text

        # "FREE*" is the site's free-with-conditions marker; still free.
        if re.search(r"\bfree\b", scope, flags=re.IGNORECASE) and "$" not in scope:
            return {"price": 0.0, "currency": "USD", "is_free": True}

        amount = re.search(r"\$\s*(\d+(?:\.\d{2})?)", scope)
        if amount:
            try:
                value = float(amount.group(1))
            except ValueError:
                return dict(self._NO_COST)
            return {"price": value, "currency": "USD", "is_free": value == 0.0}

        return dict(self._NO_COST)

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
