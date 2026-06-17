from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import anthropic

from app.core.config import get_settings
from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import QualityModel
from app.ingestion.contracts import SocialSignalsModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.venue_cache import lookup_venue_coordinates

logger = logging.getLogger(__name__)

SF_TZ = ZoneInfo("America/Los_Angeles")
DEFAULT_SF_LAT = 37.7749
DEFAULT_SF_LON = -122.4194

_LLM_MODEL = "claude-haiku-4-5-20251001"
_LLM_CONFIDENCE_THRESHOLD = 0.5

# Sentinel so callers can explicitly pass client_id=None to disable OAuth,
# distinct from "not provided" (fall back to settings).
_UNSET: Any = object()

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_BASE = "https://oauth.reddit.com"

_EXTRACTION_PROMPT = """\
You extract real-world event announcements from Reddit posts.

Decide whether the post below announces a specific attendable event (a show,
meetup, market, party, etc. with an actual time/place), as opposed to a
question, discussion, or recommendation request.

Respond with ONLY a JSON object, no prose:
{{"is_event": bool, "confidence": 0.0-1.0, "title": str, "venue": str|null,
 "date_phrase": str|null, "time": str|null}}

- "title": a short event title (not the whole post)
- "venue": the venue name if stated
- "date_phrase": the day reference as written ("this friday", "tomorrow", "June 12")
- "time": the start time as written ("8pm", "19:30") or null

Post:
{text}
"""


class RedditSource(InputAgentSource):
    source_name = "reddit"
    source_tier = 3
    keywords = ("weekend events", "what to do", "happenings")
    subreddits = ("AskSF", "bayarea", "sanfrancisco")

    def __init__(
        self,
        *,
        llm_client: Any | None = None,
        client_id: str | None = _UNSET,
        client_secret: str | None = _UNSET,
        user_agent: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        settings = get_settings()
        if llm_client is not None:
            self._llm_client = llm_client
        else:
            api_key = settings.anthropic_api_key
            self._llm_client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else None
        self._client_id = settings.reddit_client_id if client_id is _UNSET else client_id
        self._client_secret = (
            settings.reddit_client_secret if client_secret is _UNSET else client_secret
        )
        self._user_agent = user_agent or settings.reddit_user_agent
        self._access_token: str | None = None
        self._warned_no_creds = False

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
        """Optionally enrich the post with LLM extraction (graceful fallback to heuristics)."""
        if not isinstance(candidate, dict):
            return None
        if self._llm_client is None:
            return candidate

        text = self._pick_first_str(candidate, "selftext", "body", "title")
        if not text:
            return None

        extraction = await self._extract_with_llm(text)
        if extraction is None:
            return candidate  # LLM unavailable/failed: heuristic fallback
        if not extraction.get("is_event"):
            return None
        confidence = extraction.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < _LLM_CONFIDENCE_THRESHOLD:
            return None
        return {**candidate, "_llm_extraction": extraction}

    async def _extract_with_llm(self, text: str) -> dict[str, Any] | None:
        try:
            response = await self._llm_client.messages.create(
                model=_LLM_MODEL,
                max_tokens=300,
                messages=[
                    {"role": "user", "content": _EXTRACTION_PROMPT.format(text=text[:4000])}
                ],
                system="You extract structured event data from social media prose.",
            )
        except Exception:
            logger.debug("Reddit LLM extraction failed; falling back to heuristics.")
            return None

        raw = response.content[0].text if response.content else ""
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        text = self._pick_first_str(raw_item, "selftext", "body", "title")
        if not text:
            return None

        created_utc = self._parse_created_utc(raw_item.get("created_utc")) or self.utc_now()
        reference_date = created_utc.astimezone(SF_TZ)

        llm = raw_item.get("_llm_extraction")
        if isinstance(llm, dict):
            parsed = self._parsed_from_llm(llm, reference_date=reference_date)
            llm_extracted = True
        else:
            parsed = self._extract_event_hint(text=text, reference_date=reference_date)
            llm_extracted = False
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

        coords = lookup_venue_coordinates(venue_name)
        lat = coords[0] if coords else DEFAULT_SF_LAT
        lon = coords[1] if coords else DEFAULT_SF_LON

        return CanonicalEvent(
            source=SourceMetadata(
                source_id="reddit",
                source_record_id=self._pick_first_str(raw_item, "id") or source_url,
                source_url=source_url,
                ingested_at=self.utc_now(),
                last_seen_at=self.utc_now(),
                capture_mode="llm_extract" if llm_extracted else "api",
                crawl_job_id=f"reddit-{int(self.utc_now().timestamp())}",
            ),
            title=title,
            description=text,
            start_time=parsed["start_time"],
            location=LocationModel(
                venue_name=venue_name,
                city="San Francisco",
                region="CA",
                lat=lat,
                lon=lon,
                location_confidence=0.85 if coords else (0.45 if venue_name else 0.3),
            ),
            social_signals=SocialSignalsModel(
                popularity_score=float(score),
                comment_count=num_comments,
            ),
            category_tags=["community", "social"],
            organizer={"name": f"r/{subreddit}"} if subreddit else {"name": "reddit"},
            quality=QualityModel(
                record_confidence=0.7 if llm_extracted else (0.6 if venue_name else 0.5),
                llm_extracted=llm_extracted,
                needs_review=venue_name is None,
                validation_errors=[],
            ),
        )

    def _parsed_from_llm(
        self, llm: dict[str, Any], *, reference_date: datetime
    ) -> dict[str, datetime | str | None] | None:
        title = llm.get("title")
        if not isinstance(title, str) or not title.strip():
            return None
        date_phrase = llm.get("date_phrase") or ""
        time_phrase = llm.get("time") or ""
        start_time = self._resolve_relative_start(
            f"{date_phrase} {time_phrase}".strip().lower(), reference_date=reference_date
        )
        venue = llm.get("venue")
        return {
            "title": title.strip()[:120],
            "venue": venue.strip() if isinstance(venue, str) and venue.strip() else None,
            "start_time": start_time,
        }

    async def _get_access_token(self) -> str | None:
        """Application-only OAuth (client_credentials grant). Cached on the instance."""
        if self._access_token is not None:
            return self._access_token
        if not (self._client_id and self._client_secret):
            return None
        await self._limiter.acquire()
        response = await self._get_client().post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            headers={"User-Agent": self._user_agent},
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        self._access_token = token if isinstance(token, str) and token else None
        return self._access_token

    async def _search_subreddit(self, *, subreddit: str, keyword: str) -> list[dict[str, Any]]:
        token = await self._get_access_token()
        if token is None:
            # Anonymous Reddit access is blocked (403); without OAuth creds we
            # skip the live search rather than crashing the ingestion cycle.
            if not self._warned_no_creds:
                logger.warning(
                    "Reddit source disabled: set REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET "
                    "to enable live ingestion."
                )
                self._warned_no_creds = True
            return []

        await self._limiter.acquire()
        response = await self._get_client().get(
            f"{_OAUTH_BASE}/r/{subreddit}/search",
            params={
                "q": keyword,
                "restrict_sr": "on",
                "sort": "new",
                "t": "week",
                "limit": 25,
            },
            headers={"Authorization": f"Bearer {token}", "User-Agent": self._user_agent},
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

        first_sentence = re.split(r"(?<=[.!?])\s", cleaned, maxsplit=1)[0]
        # Question posts ("What to do this weekend?") are requests, not events.
        if first_sentence.rstrip().endswith("?"):
            return None

        venue = None
        venue_match = re.search(
            r"\bat\s+([A-Z][A-Za-z0-9&' .-]{2,80}?)(?=\s+(?:this|next|on|tonight|tomorrow)\b|[,.!]|$)",
            cleaned,
        )
        if venue_match:
            venue = venue_match.group(1).strip().rstrip(".,")

        lowered = cleaned.lower()
        time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
        # An event hint needs a concrete anchor: a venue or an explicit time.
        if venue is None and time_match is None:
            return None

        title = cleaned.split(".")[0][:120].strip()
        if not title:
            return None

        start_time = self._resolve_relative_start(lowered, reference_date=reference_date)
        return {
            "title": title,
            "venue": venue,
            "start_time": start_time,
        }

    def _resolve_relative_start(
        self, lowered_text: str, *, reference_date: datetime
    ) -> datetime:
        """Resolve 'this friday 8pm'-style phrases against the post date (SF local)."""
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
        matched_weekday = None
        for name, value in weekdays.items():
            if name in lowered_text:
                matched_weekday = value
                break
        if matched_weekday is not None:
            today_idx = reference_date.weekday()
            day_offset = (matched_weekday - today_idx) % 7
            if day_offset == 0 and "next " in lowered_text:
                day_offset = 7
        elif "tomorrow" in lowered_text:
            day_offset = 1

        hour = 19
        minute = 0
        time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered_text)
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
        return start_local.astimezone(timezone.utc)

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
