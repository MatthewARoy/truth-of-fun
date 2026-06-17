from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import ComplianceModel
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OffersModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.venue_cache import lookup_venue_coordinates

SF_TZ = ZoneInfo("America/Los_Angeles")
# Listings expose an explicit calendar date but no wall-clock time, so we display
# a sensible evening default. The date itself is always taken from the page.
DEFAULT_EVENT_HOUR = 19


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

        start_time = self._parse_listing_date(raw_item.get("start_date"))
        if start_time is None:
            # No explicit date on the page => drop, never default to "today".
            return None

        location_text = self._pick_first_str(raw_item, "venue_name")
        lat, lon = self._resolve_coordinates(raw_item, location_text)
        if lat is None or lon is None:
            # No real coordinates (e.g. online events) => drop rather than
            # stamp the record with fabricated coordinates.
            return None
        confidence = 0.9

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
            description=self._pick_first_str(raw_item, "description"),
            start_time=start_time,
            location=LocationModel(
                venue_name=location_text,
                address_line1=self._pick_first_str(raw_item, "street_address"),
                city=self._pick_first_str(raw_item, "city") or "San Francisco",
                region=self._pick_first_str(raw_item, "region") or "CA",
                postal_code=self._pick_first_str(raw_item, "postal_code"),
                lat=lat,
                lon=lon,
                location_confidence=confidence,
            ),
            offers=OffersModel(currency="USD"),
            compliance=ComplianceModel(
                retention_policy="metadata_only",
                tos_risk="medium",
                copyright_risk="medium",
                notes="Scraped listing metadata only; deep-link to Eventbrite source.",
            ),
            organizer=OrganizerModel(name=self._pick_first_str(raw_item, "organizer_name")),
            # Only data actually present on the card; semantic tagging happens downstream.
            category_tags=[],
        )

    def _extract_listing_candidates(self, html: str) -> list[dict[str, str]]:
        """Parse the schema.org ItemList embedded as JSON-LD on the listing page.

        Eventbrite server-renders the search results into an
        ``application/ld+json`` ItemList of Event objects, each carrying an
        explicit title, URL, start date, venue and geo coordinates. This is far
        more stable than scraping the React-rendered event cards.
        """
        candidates: list[dict[str, str]] = []
        for event in self._iter_ldjson_events(html):
            candidate = self._candidate_from_event(event)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _iter_ldjson_events(self, html: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for block in re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                data = json.loads(block.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            events.extend(self._collect_events(data))
        return events

    def _collect_events(self, node: Any) -> list[dict[str, Any]]:
        """Recursively pull Event objects out of a JSON-LD node (ItemList, graph, ...)."""
        found: list[dict[str, Any]] = []
        if isinstance(node, list):
            for item in node:
                found.extend(self._collect_events(item))
        elif isinstance(node, dict):
            node_type = node.get("@type")
            if node_type == "Event" or (
                isinstance(node_type, list) and "Event" in node_type
            ):
                found.append(node)
            # ItemList wraps each event under an "item" key; also handle @graph.
            for key in ("itemListElement", "@graph", "item"):
                if key in node:
                    found.extend(self._collect_events(node[key]))
        return found

    def _candidate_from_event(self, event: dict[str, Any]) -> dict[str, str] | None:
        title = self._clean_text(event.get("name"))
        source_url = self._clean_url(event.get("url"))
        if not title or not source_url or "/e/" not in source_url:
            return None

        start_date = self._iso_date(event.get("startDate"))
        location = event.get("location")
        venue_name = ""
        street_address = city = region = postal_code = ""
        lat = lon = ""
        if isinstance(location, dict) and location.get("@type") != "VirtualLocation":
            venue_name = self._clean_text(location.get("name"))
            address = location.get("address")
            if isinstance(address, dict):
                street_address = self._clean_text(address.get("streetAddress"))
                city = self._clean_text(address.get("addressLocality"))
                region = self._clean_text(address.get("addressRegion"))
                postal_code = self._clean_text(address.get("postalCode"))
            geo = location.get("geo")
            if isinstance(geo, dict):
                lat = self._clean_text(geo.get("latitude"))
                lon = self._clean_text(geo.get("longitude"))

        # Skip online/locationless events: with no coordinates and no venue to
        # geocode, they cannot be placed on the map without fabricating data.
        if not (lat and lon) and not venue_name:
            return None

        return {
            "title": title,
            "source_url": source_url,
            "source_record_id": source_url,
            "description": self._clean_text(event.get("description")),
            "start_date": start_date or "",
            "venue_name": venue_name,
            "street_address": street_address,
            "city": city,
            "region": region,
            "postal_code": postal_code,
            "lat": lat,
            "lon": lon,
            "organizer_name": self._extract_organizer_name(event.get("organizer")),
        }

    def _extract_organizer_name(self, organizer: Any) -> str:
        if isinstance(organizer, dict):
            return self._clean_text(organizer.get("name"))
        if isinstance(organizer, list) and organizer:
            return self._extract_organizer_name(organizer[0])
        return ""

    def _resolve_coordinates(
        self, raw_item: dict[str, Any], location_text: str | None
    ) -> tuple[float | None, float | None]:
        lat = self._to_float(raw_item.get("lat"))
        lon = self._to_float(raw_item.get("lon"))
        if lat is not None and lon is not None:
            return lat, lon
        # Fall back to a known venue only when the page omitted geo data.
        coords = lookup_venue_coordinates(location_text)
        if coords:
            return coords[0], coords[1]
        return None, None

    def _parse_listing_date(self, value: Any) -> datetime | None:
        """Parse an explicit ISO date (YYYY-MM-DD[...]) into a tz-aware datetime.

        Only the wall-clock time defaults; the calendar date must be present and
        is never invented.
        """
        if not isinstance(value, str) or not value.strip():
            return None
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
        if not match:
            return None
        year, month, day = (int(group) for group in match.groups())
        try:
            local_dt = datetime(
                year, month, day, DEFAULT_EVENT_HOUR, 0, tzinfo=SF_TZ
            )
        except ValueError:
            return None
        return local_dt.astimezone(timezone.utc)

    def _clean_url(self, value: Any) -> str:
        url = self._clean_text(value)
        if not url:
            return ""
        # Drop tracking query params so source_record_id stays stable.
        return url.split("?", 1)[0]

    def _iso_date(self, value: Any) -> str:
        text = self._clean_text(value)
        match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
        return match.group(1) if match else ""

    def _to_float(self, value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None

    def _clean_text(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", value).strip()

    def _pick_first_str(self, obj: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
