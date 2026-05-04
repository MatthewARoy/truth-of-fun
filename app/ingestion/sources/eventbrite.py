from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import ComplianceModel
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OffersModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.venue_cache import lookup_venue_coordinates

SF_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194


class EventbriteSource(InputAgentSource):
    source_name = "eventbrite"
    source_tier = 1
    listing_url = "https://www.eventbrite.com/d/ca--san-francisco/events/"

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        html = kwargs.get("html")
        if isinstance(html, str):
            return self._extract_listing_candidates(html)

        await self._limiter.acquire()
        response = await self._get_client().get(self.listing_url)
        response.raise_for_status()
        return self._extract_listing_candidates(response.text)

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = self._pick_first_str(raw_item, "title")
        source_url = self._pick_first_str(raw_item, "source_url")
        if not title or not source_url:
            return None

        start_time = self._parse_listing_datetime(raw_item.get("date_text"))
        if start_time is None:
            return None

        price_text = self._pick_first_str(raw_item, "price_text")
        price_min, is_free = self._parse_price(price_text)
        location_text = self._pick_first_str(raw_item, "location_text")

        coords = lookup_venue_coordinates(location_text)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON
        confidence = 0.9 if coords else (0.5 if location_text else 0.3)

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="eventbrite",
                source_record_id=self._pick_first_str(raw_item, "source_record_id")
                or source_url,
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="scrape",
                crawl_job_id=f"eventbrite-{int(self.utc_now().timestamp())}",
            ),
            title=title,
            description=None,
            start_time=start_time,
            location=LocationModel(
                venue_name=location_text,
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
            compliance=ComplianceModel(
                retention_policy="metadata_only",
                tos_risk="medium",
                copyright_risk="medium",
                notes="Scraped listing metadata only; deep-link to Eventbrite source.",
            ),
            category_tags=["creator-economy", "community"],
        )

    def _extract_listing_candidates(self, html: str) -> list[dict[str, str]]:
        cards = re.findall(
            r"<a(?P<attrs>[^>]*)href=[\"'](?P<href>https?://[^\"']*eventbrite[^\"']+|/[^\"']+)[\"'](?P<attrs2>[^>]*)>(?P<body>.*?)</a>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        candidates: list[dict[str, str]] = []
        for attrs_pre, href, attrs_post, body in cards:
            source_url = href if href.startswith("http") else f"https://www.eventbrite.com{href}"
            if "/e/" not in source_url and "/d/" in source_url:
                continue

            body_clean = self._strip_tags(body)
            if not body_clean:
                continue
            title = self._extract_title(f"{attrs_pre} {attrs_post}", body_clean, source_url)
            if not title:
                continue
            date_text = self._extract_date_text(body_clean)
            price_text = self._extract_price_text(body_clean)
            location_text = self._extract_location_text(body_clean)

            candidates.append(
                {
                    "title": title,
                    "source_url": source_url,
                    "source_record_id": source_url,
                    "date_text": date_text or "",
                    "price_text": price_text or "",
                    "location_text": location_text or "",
                }
            )
        return candidates

    def _extract_title(self, raw_attrs: str, body_clean: str, source_url: str) -> str | None:
        title_match = re.search(
            r"(?:aria-label|title)=[\"']([^\"']+)[\"']",
            raw_attrs,
            flags=re.IGNORECASE,
        )
        if title_match:
            return title_match.group(1).strip()
        lines = [line.strip() for line in body_clean.split("|") if line.strip()]
        if lines:
            first = lines[0]
            if not re.search(r"\b(am|pm)\b", first, flags=re.IGNORECASE):
                return first
        slug = source_url.rstrip("/").split("/")[-1]
        if slug:
            return slug.replace("-", " ").strip().title()
        return None

    def _extract_date_text(self, body_clean: str) -> str | None:
        match = re.search(
            r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+[A-Za-z]{3,9}\s+\d{1,2}(?:,\s*\d{4})?(?:,\s*\d{1,2}:\d{2}\s*[AP]M)?",
            body_clean,
            flags=re.IGNORECASE,
        )
        return match.group(0).strip() if match else None

    def _extract_price_text(self, body_clean: str) -> str | None:
        free_match = re.search(r"\bfree\b", body_clean, flags=re.IGNORECASE)
        if free_match:
            return "Free"
        money_match = re.search(
            r"(Starts at\s*)?\$\s*\d+(?:\.\d{2})?",
            body_clean,
            flags=re.IGNORECASE,
        )
        return money_match.group(0).strip() if money_match else None

    def _extract_location_text(self, body_clean: str) -> str | None:
        separators = ["|", " · ", " - "]
        for sep in separators:
            parts = [part.strip() for part in body_clean.split(sep)]
            for part in parts:
                if "san francisco" in part.lower() or "oakland" in part.lower():
                    return part
        return None

    def _parse_listing_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip()
        text = re.sub(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*", "", text, flags=re.IGNORECASE)

        date_match = re.search(
            r"(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?(?:,\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>[AP]M))?",
            text,
            flags=re.IGNORECASE,
        )
        if not date_match:
            return None

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
        month = months.get(date_match.group("month")[:3].lower())
        if month is None:
            return None
        day = int(date_match.group("day"))
        now = datetime.now(SF_TZ)
        year = int(date_match.group("year")) if date_match.group("year") else now.year

        hour = int(date_match.group("hour") or 19)
        minute = int(date_match.group("minute") or 0)
        ampm = (date_match.group("ampm") or "PM").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0

        try:
            local_dt = datetime(year, month, day, hour, minute, tzinfo=SF_TZ)
        except ValueError:
            return None
        return local_dt.astimezone(timezone.utc)

    def _parse_price(self, price_text: str | None) -> tuple[float | None, bool]:
        if not price_text:
            return None, False
        if "free" in price_text.lower():
            return 0.0, True
        match = re.search(r"\$\s*(\d+(?:\.\d{2})?)", price_text)
        if not match:
            return None, False
        return float(match.group(1)), False

    def _strip_tags(self, value: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", value)
        collapsed = re.sub(r"\s+", " ", without_tags).strip()
        return collapsed

    def _pick_first_str(self, obj: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
