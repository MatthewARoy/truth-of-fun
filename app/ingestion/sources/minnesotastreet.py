"""Minnesota Street Project scraper - gallery exhibitions and opening receptions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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
    parse_12h_to_24h,
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
                end_local = self._parse_end_time(time_text, start_time)
                end_time = end_local.astimezone(timezone.utc) if end_local else None
                start_time = start_time.astimezone(timezone.utc)
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

    def _parse_end_time(self, time_text: str, start_local: datetime) -> datetime | None:
        """Parse the explicit end time from a range like '5PM-7PM'. None if absent."""
        times = re.findall(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", time_text, re.IGNORECASE)
        if len(times) < 2:
            return None
        hour_raw, minute_raw, meridiem = times[1]
        hour = parse_12h_to_24h(int(hour_raw), meridiem)
        minute = int(minute_raw or 0)
        end_local = start_local.replace(hour=hour, minute=minute, second=0)
        if end_local < start_local:
            end_local += timedelta(days=1)
        return end_local

    def _extract_candidates(
        self, html: str, *, event_kind: str = EVENT_KIND_EXHIBITION
    ) -> list[dict[str, Any]]:
        """Extract event/exhibition candidates from the site's Drupal HTML."""
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        if event_kind == EVENT_KIND_RECEPTION:
            # Events page rows look like:
            #   <div class="item item-row row event-row">
            #     <div class="column sm-6 md-2 font-small hidden-xs">
            #       Sat, Jun 13, 4PM-6PM <br> 1275 Minnesota St<br> Ruth Asawa Lanier, Inc.</div>
            #     ... <h3 class="font-large"><a href="/events/...">Title</a></h3> ...
            row_starts = [m.start() for m in re.finditer(r'<div class="item item-row row event-row">', html)]
            for i, start in enumerate(row_starts):
                end = row_starts[i + 1] if i + 1 < len(row_starts) else len(html)
                block = html[start:end]

                info_match = re.search(
                    r'<div class="column[^"]*font-small hidden-xs">(.*?)</div>',
                    block,
                    re.DOTALL,
                )
                title_match = re.search(
                    r'<h3 class="font-large">\s*<a\s+href="(/events/[^"]+)"[^>]*>(.*?)</a>',
                    block,
                    re.DOTALL,
                )
                if not info_match or not title_match:
                    continue

                info_lines = [
                    strip_html_tags(part)
                    for part in re.split(r"<br\s*/?>", info_match.group(1))
                ]
                info_lines = [line for line in info_lines if line]
                if not info_lines:
                    continue
                time_text = info_lines[0]
                venue = info_lines[1] if len(info_lines) > 1 else ""
                gallery = info_lines[2] if len(info_lines) > 2 else ""

                href = title_match.group(1).strip()
                title = strip_html_tags(title_match.group(2))
                if not title or len(title) < 3:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                candidates.append(
                    {
                        "title": title,
                        "source_url": f"{self.base_url}{href}",
                        "source_record_id": f"reception-{href.rstrip('/').split('/')[-1]}",
                        "event_kind": EVENT_KIND_RECEPTION,
                        "time_text": time_text,
                        "venue_text": venue,
                        "gallery": gallery,
                        "date_range": None,
                    }
                )
        else:
            # Exhibitions page items look like:
            #   <h3 class="font-large"><a href="/exhibitions/1275-minnesota-st/slug"
            #     title="Title"><span class="div-link"></span> Title</a></h3>
            #   <p class="font-small"> Jun 6–Jul 18, 2026<br> 1275 Minnesota St / re.riddle</p>
            exh_pattern = re.compile(
                r'<h3 class="font-large">\s*<a\s+href="(/exhibitions/[^"]+)"[^>]*>(.*?)</a>\s*</h3>\s*'
                r'<p class="font-small">\s*([^<]+?)\s*<br\s*/?>\s*([^<]+?)\s*</p>',
                re.DOTALL,
            )
            for m in exh_pattern.finditer(html):
                href = m.group(1).strip()
                title = strip_html_tags(m.group(2))
                date_range = m.group(3).strip()
                venue_gallery = m.group(4).strip()
                if not title or len(title) < 3:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                parts = [part.strip() for part in venue_gallery.split("/")]
                venue = parts[0] if parts else venue_gallery
                gallery = " / ".join(parts[1:]) if len(parts) > 1 else ""
                candidates.append(
                    {
                        "title": title,
                        "source_url": f"{self.base_url}{href}",
                        "source_record_id": f"exhibition-{href.rstrip('/').split('/')[-1]}",
                        "event_kind": EVENT_KIND_EXHIBITION,
                        "time_text": None,
                        "venue_text": venue,
                        "gallery": gallery,
                        "date_range": date_range,
                    }
                )

        return candidates[:40]
