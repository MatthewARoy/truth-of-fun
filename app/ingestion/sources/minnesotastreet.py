"""Minnesota Street Project scraper - gallery exhibitions and opening receptions."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import (
    DEFAULT_SF_LAT,
    DEFAULT_SF_LON,
    SF_TZ,
    parse_date_range,
    parse_datetime_flexible,
    strip_html_tags,
)
from app.ingestion.venue_cache import lookup_venue_coordinates

# Testable without API keys - public scraper
TESTABLE = True

# Event kinds per spec: exhibition_window vs opening_reception (stored in category_tags)
EVENT_KIND_EXHIBITION = "exhibition_window"
EVENT_KIND_RECEPTION = "opening_reception"


class MinnesotaStreetSource(InputAgentSource):
    """Scraper for Minnesota Street Project exhibitions and events."""

    source_name = "minnesotastreet"
    source_tier = 2
    base_url = "https://minnesotastreetproject.com"
    events_url = "https://minnesotastreetproject.com/events/all"
    exhibitions_url = "https://minnesotastreetproject.com/exhibitions"

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        candidates: list[dict[str, Any]] = []

        for url, kind in [
            (self.events_url, EVENT_KIND_RECEPTION),
            (self.exhibitions_url, EVENT_KIND_EXHIBITION),
        ]:
            html = kwargs.get("html") if url == self.events_url and "html" in kwargs else None
            if html is None and url == self.exhibitions_url and "exhibitions_html" in kwargs:
                html = kwargs.get("exhibitions_html")
            if not isinstance(html, str):
                await self._limiter.acquire()
                response = await self._get_client().get(url)
                response.raise_for_status()
                html = response.text
            candidates.extend(self._extract_candidates(html, event_kind=kind))

        return candidates

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = raw_item.get("title")
        source_url = raw_item.get("source_url")
        if not isinstance(title, str) or not title.strip() or not source_url:
            return None

        event_kind = raw_item.get("event_kind", EVENT_KIND_EXHIBITION)
        start_time, end_time = None, None
        all_day = event_kind == EVENT_KIND_EXHIBITION

        if event_kind == EVENT_KIND_RECEPTION:
            # Point-in-time: "Sat, Mar 14, 5PM-7PM"
            time_text = raw_item.get("time_text", "")
            start_time = parse_datetime_flexible(
                time_text,
                default_hour=17,
                default_minute=0,
            )
            if start_time:
                end_time = start_time.replace(hour=19, minute=0, second=0)
                start_time = start_time.astimezone(timezone.utc)
                end_time = end_time.astimezone(timezone.utc)
        else:
            # Exhibition window: "Feb 14–Mar 28, 2026"
            date_range = raw_item.get("date_range", "")
            start_dt, end_dt = parse_date_range(date_range)
            if start_dt and end_dt:
                start_time = start_dt.astimezone(timezone.utc)
                end_time = end_dt.astimezone(timezone.utc)

        if start_time is None:
            return None

        venue_text = raw_item.get("venue_text", "")
        gallery = raw_item.get("gallery", "")

        venue_display = venue_text or "Minnesota Street Project"
        coords = lookup_venue_coordinates(venue_display)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON
        confidence = 0.9 if coords else 0.3

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="minnesotastreet",
                source_record_id=raw_item.get("source_record_id") or source_url,
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="scrape",
                crawl_job_id=f"minnesotastreet-{int(self.utc_now().timestamp())}",
            ),
            title=title.strip(),
            start_time=start_time,
            end_time=end_time,
            all_day=all_day,
            location=LocationModel(
                venue_name=venue_display,
                address_line1=venue_text,
                city="San Francisco",
                region="CA",
                lat=lat,
                lon=lon,
                location_confidence=confidence,
            ),
            organizer=OrganizerModel(name=gallery or "Minnesota Street Project"),
            category_tags=[event_kind, "arts", "gallery"],
        )

    def _extract_candidates(
        self, html: str, *, event_kind: str = EVENT_KIND_EXHIBITION
    ) -> list[dict[str, Any]]:
        """Extract event/exhibition candidates from HTML."""
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        if event_kind == EVENT_KIND_RECEPTION:
            # Events page: "Opening Reception: No Coward Soul" "Sat, Mar 14, 5PM-7PM" "1275 Minnesota St" "Hashimoto Contemporary"
            # Pattern: ### Opening Reception: Title, then date/time, venue, gallery
            reception_pattern = re.compile(
                r"(?:Opening\s+Reception:\s+)?([^\n#]+?)\s*\n\s*(?:Sat|Sun|Mon|Tue|Wed|Thu|Fri)[a-z]*,\s*([^\n]+?)\s*\n\s*(\d+\s+[^\n]+?)\s*\n\s*([^\n]+)",
                re.IGNORECASE,
            )
            for m in reception_pattern.finditer(html):
                title = strip_html_tags(m.group(1)).strip()
                time_text = m.group(2).strip()
                venue = m.group(3).strip()
                gallery = m.group(4).strip()
                if not title or len(title) < 3:
                    continue
                key = f"{title}|{time_text}"
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "title": title,
                        "source_url": f"{self.base_url}/events/all",
                        "source_record_id": f"reception-{title[:40]}",
                        "event_kind": EVENT_KIND_RECEPTION,
                        "time_text": time_text,
                        "venue_text": venue,
                        "gallery": gallery,
                        "date_range": None,
                    }
                )

            # Simpler: ### Title followed by date
            alt = re.compile(
                r"###\s+([^\n]+)\s*\n\s*[^\n]*?(Sat|Sun|Mon|Tue|Wed|Thu|Fri)[a-z]*,\s*([^\n]+)",
                re.IGNORECASE,
            )
            for m in alt.finditer(html):
                title = strip_html_tags(m.group(1)).strip()
                if "Opening Reception" in title:
                    title = title.replace("Opening Reception:", "").replace("Opening Reception", "").strip()
                time_text = f"{m.group(2)}, {m.group(3)}"
                if not title or len(title) < 3:
                    continue
                key = f"{title}|{time_text}"
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "title": title,
                        "source_url": f"{self.base_url}/events/all",
                        "source_record_id": f"reception-{title[:40]}",
                        "event_kind": EVENT_KIND_RECEPTION,
                        "time_text": time_text,
                        "venue_text": "1275 Minnesota St",
                        "gallery": "",
                        "date_range": None,
                    }
                )
        else:
            # Exhibitions: "Dialogues 2026" "Feb 14–Mar 28, 2026" "1275 Minnesota St / SFArtsED"
            # ### Title, then date range, then venue/gallery
            exh_pattern = re.compile(
                r"###\s+([^\n]+)\s*\n\s*([A-Za-z]{3}\s+\d{1,2}[–\-][^\n]+?)\s*\n\s*([^\n]+)",
                re.IGNORECASE,
            )
            for m in exh_pattern.finditer(html):
                title = strip_html_tags(m.group(1)).strip()
                date_range = m.group(2).strip()
                venue_gallery = m.group(3).strip()
                if not title or len(title) < 3:
                    continue
                key = f"{title}|{date_range}"
                if key in seen:
                    continue
                seen.add(key)
                parts = venue_gallery.split("/")
                venue = parts[0].strip() if parts else venue_gallery
                gallery = parts[1].strip() if len(parts) > 1 else ""
                candidates.append(
                    {
                        "title": title,
                        "source_url": f"{self.base_url}/exhibitions",
                        "source_record_id": f"exhibition-{title[:40]}",
                        "event_kind": EVENT_KIND_EXHIBITION,
                        "time_text": None,
                        "venue_text": venue,
                        "gallery": gallery,
                        "date_range": date_range,
                    }
                )

        return candidates[:40]
