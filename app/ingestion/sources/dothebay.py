"""DoTheBay scraper - lifestyle curation and popularity signals."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

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
    describe_fetch_error,
    find_next_page_url,
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
    # The source spec asks for an unaggressive cadence; a run walks a week of pages.
    default_max_requests_per_second = 1

    #: /events shows today only. Each dated day page lists that day's events,
    #: 25 cards a page, paginated with rel="next".
    day_path = "/events/{year}/{month}/{day}"
    horizon_days = 7
    max_pages_per_day = 3
    #: Hard caps per run, across every day.
    max_requests = 21
    max_candidates = 600

    #: DoTheBay's own card category (``ds-event-category-<slug>``) mapped onto
    #: canonical categories (see app/services/categories.py). Slugs with no
    #: clear canonical home (dance, variety, shopping) stay unmapped rather
    #: than guessed.
    CARD_CATEGORIES: dict[str, str] = {
        "comedy": "Comedy",
        "music": "Music",
        "dj-parties": "Nightlife",
        "film": "Film",
        "food-drink": "Food",
        "sports": "Sports",
        "outdoor-recreation": "Outdoors",
        "the-arts": "Arts & Theatre",
        "theatre-performing-arts": "Arts & Theatre",
    }

    # DoTheBay serves a normal anti-bot-friendly UA the same markup, but send a
    # browser UA so we are a well-behaved client and not silently rate-limited.
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        html = kwargs.get("html")
        if isinstance(html, str):
            return self._extract_candidates(html)

        today = kwargs.get("today") or datetime.now(SF_TZ).date()
        return await self._crawl_day_pages(today)

    async def _crawl_day_pages(self, today: date) -> list[dict[str, Any]]:
        """Follow each day's rel="next" pages, merging cards by event URL."""
        merged: dict[str, dict[str, Any]] = {}
        requests_made = 0
        try:
            for offset in range(self.horizon_days):
                day = today + timedelta(days=offset)
                day_url = self.base_url + self.day_path.format(
                    year=day.year, month=day.month, day=day.day
                )
                url = day_url
                for _ in range(self.max_pages_per_day):
                    if requests_made >= self.max_requests:
                        self.last_fetch_error = "Request cap reached; crawl incomplete"
                        break
                    requests_made += 1
                    html = await self._get_text(url, headers=self.REQUEST_HEADERS)
                    for candidate in self._extract_candidates(html):
                        # Ongoing events repeat on every day they run.
                        merged.setdefault(candidate["source_url"], candidate)
                    next_url = find_next_page_url(html, url)
                    # Only this day's own pages; never wander off via a nav link.
                    if not next_url or not next_url.startswith(f"{day_url}?"):
                        break
                    url = next_url
                else:
                    self.last_fetch_error = "Day page cap reached; crawl incomplete"
        except httpx.HTTPError as exc:
            if not merged:
                raise
            # Keep the pages already read, but report the crawl as partial.
            self.last_fetch_error = describe_fetch_error(exc)
        if len(merged) > self.max_candidates:
            self.last_fetch_error = "Candidate cap reached; crawl incomplete"
        return list(merged.values())[: self.max_candidates]

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
        # An unresolved venue lands on the SF centroid, so it must stay under
        # DEFAULT_MIN_LOCATION_CONFIDENCE or radius search treats that guess
        # as the event's real location.
        confidence = 0.9 if coords else (0.4 if venue_name else 0.3)

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

    # DoTheBay renders one schema.org Event per card:
    #   <div class="ds-listing event-card ..." data-permalink="/events/..." ...>
    # We split the listing on that opening tag and parse each card's microdata
    # rather than scanning a fixed-size window around bare <a> links.
    _CARD_SPLIT_RE = re.compile(r'(?=<div\s+class=["\']ds-listing\s+event-card)')

    def _extract_candidates(self, html: str) -> list[dict[str, Any]]:
        """Extract event candidates from listing HTML, one per event-card."""
        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for card in self._CARD_SPLIT_RE.split(html):
            if 'class="ds-listing event-card' not in card and "class='ds-listing event-card" not in card:
                continue

            url = self._extract_card_url(card)
            if not url or url in seen_urls:
                continue
            title = self._extract_card_title(card)
            if not title:
                continue
            seen_urls.add(url)

            venue_name = self._extract_venue_from_card(card)
            time_text = self._extract_time_from_card(card)
            date_text = self._extract_date_from_card(card) or self._extract_date_from_url(url)
            price_text = self._extract_price_from_card(card)
            vote_count = self._extract_vote_from_context(card)
            address = self._extract_address_from_card(card)

            candidates.append(
                {
                    "title": title,
                    "source_url": url,
                    "source_record_id": url.rstrip("/").split("/")[-1] or url,
                    "venue_name": venue_name,
                    "address": address,
                    "date_text": date_text,
                    "time_text": time_text,
                    "price_text": price_text,
                    "vote_count": vote_count,
                    "category_tags": self._extract_categories_from_card(card),
                }
            )

        # A day page holds 25 cards; the per-run cap lives in the crawl.
        return candidates

    def _extract_categories_from_card(self, card: str) -> list[str]:
        """Canonical categories from the card's own ``ds-event-category-*`` class."""
        opening = re.search(
            r"<div\s+class=[\"']ds-listing event-card([^\"']*)[\"']", card
        )
        slugs = (
            re.findall(r"ds-event-category-([a-z0-9-]+)", opening.group(1))
            if opening
            else []
        )
        categories: list[str] = []
        for slug in slugs:
            category = self.CARD_CATEGORIES.get(slug)
            if category and category not in categories:
                categories.append(category)
        return categories

    def _resolve_url(self, href: str) -> str:
        """Resolve a possibly-relative event href to an absolute dothebay.com URL."""
        href = href.strip()
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if not href.startswith("/"):
            href = "/" + href
        return self.base_url + href

    def _extract_card_url(self, card: str) -> str | None:
        """Prefer the data-permalink attribute, falling back to the title anchor href."""
        perm = re.search(r'data-permalink=["\'](/events/[^"\']+)["\']', card, re.IGNORECASE)
        if perm:
            return self._resolve_url(perm.group(1))
        anchor = re.search(
            r'<a\s+[^>]*href=["\']([^"\']*/events/[^"\']+)["\'][^>]*itemprop=["\']url["\']',
            card,
            re.IGNORECASE,
        )
        if anchor:
            return self._resolve_url(anchor.group(1))
        return None

    def _extract_card_title(self, card: str) -> str | None:
        """Extract the event title from the schema.org name span."""
        name = re.search(
            r'class=["\']ds-listing-event-title-text["\']\s+itemprop=["\']name["\']>([^<]+)<',
            card,
            re.IGNORECASE,
        )
        if name:
            return strip_html_tags(name.group(1))
        # Fallback: any itemprop="name" inside the title anchor.
        name = re.search(
            r'ds-listing-event-title[^>]*>.*?itemprop=["\']name["\']>([^<]+)<',
            card,
            re.IGNORECASE | re.DOTALL,
        )
        if name:
            return strip_html_tags(name.group(1))
        return None

    def _extract_venue_from_card(self, card: str) -> str | None:
        """Extract venue name from the schema.org Place block."""
        place = re.search(
            r'class=["\']ds-venue-name["\'].*?<a\s+[^>]*href=["\'][^"\']*/venues/[^"\']+["\'][^>]*>'
            r'\s*<span\s+itemprop=["\']name["\']>([^<]+)</span>',
            card,
            re.IGNORECASE | re.DOTALL,
        )
        if place:
            return strip_html_tags(place.group(1))
        return None

    def _extract_address_from_card(self, card: str) -> str | None:
        """Extract the street address from schema.org PostalAddress microdata."""
        street = re.search(
            r'itemprop=["\']streetAddress["\']\s+content=["\']([^"\']+)["\']',
            card,
            re.IGNORECASE,
        )
        if street:
            value = strip_html_tags(street.group(1))
            return value or None
        return None

    def _extract_time_from_card(self, card: str) -> str | None:
        """Extract the start time from the ds-event-time block, e.g. '4:20PM (doors)'."""
        block = re.search(
            r'class=["\']ds-event-time[^"\']*["\']>(.*?)</div>',
            card,
            re.IGNORECASE | re.DOTALL,
        )
        haystack = block.group(1) if block else card
        time_match = re.search(
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
            haystack,
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

    def _extract_date_from_card(self, card: str) -> str | None:
        """Extract date from the schema.org startDate meta or 'Through Mar 28' text."""
        start_date = re.search(
            r'itemprop=["\']startDate["\'][^>]*(?:datetime|content)=["\'](\d{4}-\d{1,2}-\d{1,2})',
            card,
            re.IGNORECASE,
        )
        if start_date:
            return start_date.group(1)
        through = re.search(r"Through\s+([A-Za-z]{3}\s+\d{1,2}(?:,\s*\d{4})?)", card, re.IGNORECASE)
        if through:
            return through.group(1).strip()
        return None

    def _extract_price_from_card(self, card: str) -> str | None:
        """Extract Free (from the banner) or an explicit price; never invent one."""
        # The listing marks free events with a "Free" banner pill.
        if re.search(r'ds-listing-soldout["\'][^>]*>.*?>\s*Free\s*<', card, re.IGNORECASE | re.DOTALL):
            return "Free"
        price_meta = re.search(
            r'itemprop=["\']price["\']\s+content=["\']\s*(\d+(?:\.\d{2})?)["\']',
            card,
            re.IGNORECASE,
        )
        if price_meta:
            return "$" + price_meta.group(1)
        price_match = re.search(r"\$\s*\d+(?:\.\d{2})?", card)
        if price_match:
            return price_match.group(0)
        return None

    def _extract_vote_from_context(self, context: str) -> int | None:
        """Extract vote count only when clearly vote-labeled - never guess from stray digits.

        On the live listing votes live in the ds-btn-container-upvote block as an
        ds-icon-text number. The ds-listing-attendee-count number is NOT a vote.
        """
        upvote = re.search(
            r'ds-btn-container-upvote.*?class=["\']ds-icon-text["\']>\s*(\d{1,6})\b',
            context,
            re.IGNORECASE | re.DOTALL,
        )
        if upvote:
            return self._coerce_int(upvote.group(1))
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
