from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource

DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194


class MeetupSource(InputAgentSource):
    source_name = "meetup"
    source_tier = 1
    graphql_url = "https://api.meetup.com/gql-ext"

    def __init__(
        self,
        *,
        api_token: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._api_token = api_token or os.getenv("MEETUP_API_TOKEN")

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        first = int(kwargs.get("first", 20))
        topic = str(kwargs.get("topic", "bay area events"))
        return await self._search_events(topic=topic, first=first)

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        title = self._pick_first_str(raw_item, "title", "name")
        start_time = self._parse_datetime(
            self._pick_first_str(raw_item, "dateTime", "startTime", "start_date")
        )
        if not title or start_time is None:
            return None

        url = self._pick_first_str(raw_item, "eventUrl", "url", "link") or "https://www.meetup.com/"
        venue = raw_item.get("venue") if isinstance(raw_item.get("venue"), dict) else {}
        venue_name = self._pick_first_str(venue, "name", "venueName")
        address = self._pick_first_str(venue, "address", "address1")
        city = self._pick_first_str(venue, "city") or "San Francisco"
        lat = self._to_float(venue.get("lat")) if isinstance(venue, dict) else None
        lon = self._to_float(venue.get("lon")) if isinstance(venue, dict) else None
        if lat is None or lon is None:
            lat = DEFAULT_SF_LAT
            lon = DEFAULT_SF_LON

        group = raw_item.get("group") if isinstance(raw_item.get("group"), dict) else {}
        organizer = OrganizerModel(
            name=self._pick_first_str(group, "name"),
            organizer_url=self._pick_first_str(group, "url"),
        )

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="meetup",
                source_record_id=self._pick_first_str(raw_item, "id"),
                source_url=url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="api",
                crawl_job_id=f"meetup-{int(self.utc_now().timestamp())}",
            ),
            title=title,
            description=self._pick_first_str(raw_item, "description"),
            start_time=start_time,
            end_time=self._parse_datetime(
                self._pick_first_str(raw_item, "endTime", "end_date")
            ),
            location=LocationModel(
                venue_name=venue_name,
                address_line1=address,
                city=city,
                lat=lat,
                lon=lon,
                location_confidence=0.85 if venue_name else 0.6,
            ),
            organizer=organizer,
            category_tags=self._coerce_tags(raw_item.get("topics")),
            vibe_tags=["Social"],
        )

    async def _search_events(self, *, topic: str, first: int) -> list[dict[str, Any]]:
        query = """
        query SearchEvents($query: String!, $first: Int!) {
          keywordSearch(query: $query, first: $first) {
            edges {
              node {
                ... on Event {
                  id
                  title
                  eventUrl
                  dateTime
                  endTime
                  description
                  venue {
                    name
                    address
                    city
                    lat
                    lon
                  }
                  group {
                    name
                    url
                  }
                }
              }
            }
          }
        }
        """
        payload = await self._post_graphql(
            query=query,
            variables={"query": topic, "first": first},
        )
        return self._extract_events(payload)

    async def _post_graphql(
        self, *, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        await self._limiter.acquire()
        response = await self._get_client().post(
            self.graphql_url,
            json={"query": query, "variables": variables},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected object response from Meetup GraphQL.")
        return payload

    def _extract_events(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        keyword_search = data.get("keywordSearch")
        if not isinstance(keyword_search, dict):
            return []
        edges = keyword_search.get("edges")
        if not isinstance(edges, list):
            return []

        events: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if isinstance(node, dict):
                events.append(node)
        return events

    def _coerce_tags(self, topics: Any) -> list[str]:
        if not isinstance(topics, list):
            return []
        tags: list[str] = []
        for item in topics:
            if isinstance(item, str) and item.strip():
                tags.append(item.strip())
            elif isinstance(item, dict):
                name = self._pick_first_str(item, "name")
                if name:
                    tags.append(name)
        return list(dict.fromkeys(tags))

    def _pick_first_str(self, obj: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None

    def _to_float(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
