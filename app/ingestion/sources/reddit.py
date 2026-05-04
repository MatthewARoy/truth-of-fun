from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import QualityModel
from app.ingestion.contracts import SocialSignalsModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource

SF_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194


class RedditSource(InputAgentSource):
    source_name = "reddit"
    source_tier = 3
    keywords = ("weekend events", "what to do", "happenings")
    subreddits = ("AskSF", "bayarea", "sanfrancisco")

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        comments = kwargs.get("comments")
        if isinstance(comments, list):
            return [item for item in comments if isinstance(item, dict)]

        candidates: list[dict[str, Any]] = []
        for subreddit in self.subreddits:
            for keyword in self.keywords:
                candidates.extend(await self._search_subreddit(subreddit=subreddit, keyword=keyword))
        return candidates

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        text = self._pick_first_str(raw_item, "selftext", "body", "title")
        if not text:
            return None

        created_utc = self._parse_created_utc(raw_item.get("created_utc")) or self.utc_now()
        parsed = self._extract_event_hint(text=text, reference_date=created_utc.astimezone(SF_TZ))
        if parsed is None:
            return None

        permalink = self._pick_first_str(raw_item, "permalink")
        source_url = (
            f"https://www.reddit.com{permalink}" if permalink and permalink.startswith("/") else permalink
        ) or "https://www.reddit.com/"
        title = parsed["title"]
        venue_name = parsed.get("venue")
        subreddit = self._pick_first_str(raw_item, "subreddit")
        score = self._coerce_int(raw_item.get("score")) or 0
        num_comments = self._coerce_int(raw_item.get("num_comments")) or 0

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="reddit",
                source_record_id=self._pick_first_str(raw_item, "id") or source_url,
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="llm_extract",
                crawl_job_id=f"reddit-{int(self.utc_now().timestamp())}",
            ),
            title=title,
            description=text,
            start_time=parsed["start_time"],
            location=LocationModel(
                venue_name=venue_name,
                city="San Francisco",
                region="CA",
                lat=DEFAULT_SF_LAT,
                lon=DEFAULT_SF_LON,
                location_confidence=0.45 if venue_name else 0.3,
            ),
            social_signals=SocialSignalsModel(
                popularity_score=float(score),
                comment_count=num_comments,
            ),
            category_tags=["community", "social"],
            organizer={"name": f"r/{subreddit}"} if subreddit else {"name": "reddit"},
            quality=QualityModel(
                record_confidence=0.6 if venue_name else 0.5,
                llm_extracted=True,
                needs_review=venue_name is None,
                validation_errors=[],
            ),
        )

    async def _search_subreddit(self, *, subreddit: str, keyword: str) -> list[dict[str, Any]]:
        await self._limiter.acquire()
        response = await self._get_client().get(
            f"https://www.reddit.com/r/{subreddit}/search.json",
            params={
                "q": keyword,
                "restrict_sr": "on",
                "sort": "new",
                "t": "week",
                "limit": 25,
            },
            headers={"User-Agent": "truth-of-fun/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        children = data.get("children", []) if isinstance(data, dict) else []
        results: list[dict[str, Any]] = []
        for child in children:
            if not isinstance(child, dict):
                continue
            item = child.get("data")
            if isinstance(item, dict):
                results.append(item)
        return results

    def _extract_event_hint(
        self, *, text: str, reference_date: datetime
    ) -> dict[str, datetime | str | None] | None:
        cleaned = " ".join(text.split())
        venue = None
        venue_match = re.search(
            r"\bat\s+([A-Z][A-Za-z0-9&' .-]{2,80}?)(?=\s+(?:this|next|on|tonight|tomorrow)\b|[,.!]|$)",
            cleaned,
        )
        if venue_match:
            venue = venue_match.group(1).strip().rstrip(".,")

        title = cleaned.split(".")[0][:120].strip()
        if not title:
            return None

        day_offset = 0
        weekdays = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        lowered = cleaned.lower()
        matched_weekday = None
        for name, value in weekdays.items():
            if name in lowered:
                matched_weekday = value
                break
        if matched_weekday is not None:
            today_idx = reference_date.weekday()
            day_offset = (matched_weekday - today_idx) % 7
            if day_offset == 0 and "next " in lowered:
                day_offset = 7
        elif "tomorrow" in lowered:
            day_offset = 1

        hour = 19
        minute = 0
        time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            ampm = time_match.group(3)
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0

        start_local_date = (reference_date + timedelta(days=day_offset)).date()
        start_local = datetime(
            start_local_date.year,
            start_local_date.month,
            start_local_date.day,
            hour,
            minute,
            tzinfo=SF_TZ,
        )
        return {
            "title": title,
            "venue": venue,
            "start_time": start_local.astimezone(timezone.utc),
        }

    def _parse_created_utc(self, value: Any) -> datetime | None:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        return None

    def _coerce_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _pick_first_str(self, obj: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
