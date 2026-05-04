from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.venue_cache import lookup_venue_coordinates

SF_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194


class NineteenHzSource(InputAgentSource):
    source_name = "19hz"
    source_tier = 2
    events_url = "https://19hz.info/eventlisting_BayArea.php"

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        await self._limiter.acquire()
        response = await self._get_client().get(self.events_url)
        response.raise_for_status()
        return self._extract_rows(response.text)

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = raw_item.get("title")
        if not isinstance(title, str) or not title.strip():
            return None

        start_time, end_time = self._parse_time_range(raw_item.get("time_text"))
        if start_time is None:
            return None

        venue_name = raw_item.get("venue_name")
        location_is_private = isinstance(venue_name, str) and venue_name.upper() == "TBA"
        source_url = raw_item.get("source_url") or self.events_url
        source_record_id = raw_item.get("source_record_id") or source_url

        coords = lookup_venue_coordinates(venue_name)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON
        if location_is_private:
            confidence = 0.5
        elif coords:
            confidence = 0.9
        else:
            confidence = 0.3

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="19hz",
                source_record_id=str(source_record_id),
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="scrape",
                crawl_job_id=f"19hz-{int(self.utc_now().timestamp())}",
            ),
            title=title.strip(),
            start_time=start_time,
            end_time=end_time,
            location=LocationModel(
                venue_name=venue_name,
                city="San Francisco",
                region="CA",
                lat=lat,
                lon=lon,
                location_is_private=location_is_private,
                location_confidence=confidence,
            ),
            category_tags=raw_item.get("tags", []),
            vibe_tags=["HighEnergy"],
        )

    def _extract_rows(self, html: str) -> list[dict[str, Any]]:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL)
        parsed_rows: list[dict[str, Any]] = []
        for row_html in rows:
            columns = re.findall(
                r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL
            )
            if len(columns) < 2:
                continue
            time_text = self._strip_tags(columns[0])
            event_text = self._strip_tags(columns[1])
            tags_text = self._strip_tags(columns[2]) if len(columns) >= 3 else ""
            if not time_text or not event_text:
                continue

            link_match = re.search(
                r'href=["\']([^"\']+)["\']', columns[1], flags=re.IGNORECASE
            )
            source_url = link_match.group(1).strip() if link_match else self.events_url
            if source_url.startswith("/"):
                source_url = f"https://19hz.info{source_url}"

            title, venue_name = self._split_event_and_venue(event_text)
            parsed_rows.append(
                {
                    "time_text": time_text,
                    "title": title,
                    "venue_name": venue_name,
                    "tags": self._parse_tags(tags_text),
                    "source_url": source_url,
                    "source_record_id": source_url,
                }
            )
        return parsed_rows

    def _split_event_and_venue(self, event_text: str) -> tuple[str, str | None]:
        parts = [part.strip() for part in event_text.split(" @ ", 1)]
        if len(parts) == 2:
            return parts[0], parts[1] or None
        return event_text.strip(), None

    def _parse_time_range(
        self, time_text: Any
    ) -> tuple[datetime | None, datetime | None]:
        if not isinstance(time_text, str):
            return None, None

        month_day = re.search(r"\b([A-Za-z]{3})\s+(\d{1,2})\b", time_text)
        if not month_day:
            return None, None
        month_token = month_day.group(1).lower()
        day_value = int(month_day.group(2))

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
        month_value = months.get(month_token)
        if month_value is None:
            return None, None

        year = datetime.now(SF_TZ).year
        now = datetime.now(SF_TZ)
        if now.month == 12 and month_value == 1:
            year += 1
        elif now.month == 1 and month_value == 12:
            year -= 1

        start_time_match = re.search(
            r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*-\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
            time_text,
            flags=re.IGNORECASE,
        )
        if start_time_match:
            start_hour = self._to_24h(
                int(start_time_match.group(1)),
                start_time_match.group(3).lower(),
            )
            start_min = int(start_time_match.group(2) or 0)
            end_hour = self._to_24h(
                int(start_time_match.group(4)),
                start_time_match.group(6).lower(),
            )
            end_min = int(start_time_match.group(5) or 0)
        else:
            start_hour, start_min, end_hour, end_min = 20, 0, 23, 59

        start_local = datetime(
            year, month_value, day_value, start_hour, start_min, tzinfo=SF_TZ
        )
        end_local = datetime(year, month_value, day_value, end_hour, end_min, tzinfo=SF_TZ)
        if end_local <= start_local:
            end_local = end_local + timedelta(days=1)

        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    def _parse_tags(self, text: str) -> list[str]:
        values = [part.strip() for part in text.split(",")]
        return [tag for tag in values if tag]

    def _strip_tags(self, value: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", value)
        collapsed = re.sub(r"\s+", " ", without_tags).strip()
        return collapsed

    def _to_24h(self, hour: int, meridiem: str) -> int:
        normalized = hour % 12
        if meridiem == "pm":
            normalized += 12
        return normalized
