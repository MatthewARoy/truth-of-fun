"""BiblioCommons connector - public-library event calendars (Oakland, San José).

BiblioCommons hosts the events calendars of many public libraries behind one
gateway. The search endpoint takes a date window and returns the matching
occurrences, soonest first, with every referenced entity alongside::

    GET https://gateway.bibliocommons.com/v2/libraries/<library>/events/search
        ?startDate=2026-11-12&endDate=2026-11-26&limit=50&page=1

    {"events": {"results": [ids], "pagination": {"count", "page", "pages", "limit"}},
     "entities": {"events": {id: {...}}, "locations": {...}, "places": {...},
                  "eventTypes": {...}, "eventAudiences": {...}, "images": {...}}}

Things learned by probing the live API on 2026-11-12:

* ``/events`` (no ``/search``) ignores ``startDate``/``endDate`` and is not
  sorted; only ``/events/search`` honours the window.
* ``limit`` is capped at 50 rows by the server, but the pagination block
  echoes whatever was asked for: ``limit=100`` returned 50 rows and reported
  ``pages`` as if there were 100 per page, so following it would silently
  skip every second 50. ``page_size`` therefore must not exceed 50, and the
  crawl compares rows read against ``count``.
* Online programmes carry ``definition.isVirtual: true`` and no location id
  (all four locationless San José rows in a live run were these); some
  libraries also expose a ``BC_VIRTUAL`` pseudo-branch.
* The public page for an event is ``https://<library>.bibliocommons.com/v2/events/<id>``
  (``/events/<id>`` 302s there).
* San Francisco Public Library is not on this gateway (403).

A library calendar is dominated by weekly storytimes and drop-in sessions
(Oakland: 257 rows in 14 days, about 85% recurring; San José: 961). By default
only one-off events are ingested, capped per library.

One class, parameterised by a ``BiblioCommonsLibrary``; each library is its own
registered source so health is tracked per calendar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.ingestion.contracts import CanonicalEvent
from app.ingestion.contracts import LocationModel
from app.ingestion.contracts import OffersModel
from app.ingestion.contracts import OrganizerModel
from app.ingestion.contracts import SourceMetadata
from app.ingestion.input_agent import InputAgentSource
from app.ingestion.scraper_utils import describe_fetch_error
from app.ingestion.sources._calendar_common import CENTROID_CONFIDENCE
from app.ingestion.sources._calendar_common import FEED_COORDINATE_CONFIDENCE
from app.ingestion.sources._calendar_common import JSON_HEADERS
from app.ingestion.sources._calendar_common import LOCAL_TZ
from app.ingestion.sources._calendar_common import all_day_bounds
from app.ingestion.sources._calendar_common import clean_str
from app.ingestion.sources._calendar_common import feed_coordinates
from app.ingestion.sources._calendar_common import nearby_venue_coordinates
from app.ingestion.sources._calendar_common import parse_iso_date
from app.ingestion.sources._calendar_common import parse_local_datetime
from app.ingestion.sources._calendar_common import postal_address
from app.ingestion.sources._calendar_common import short_description
from app.ingestion.sources._calendar_common import summarize_counts
from app.ingestion.sources._calendar_common import within_horizon
from app.ingestion.venue_cache import lookup_city_coordinates

# Testable without API keys - public JSON gateway
TESTABLE = True

GATEWAY_URL = "https://gateway.bibliocommons.com/v2/libraries"

#: Library event type (matched on its name) -> canonical categories
#: (app/services/categories.py) and vibe tags (app/services/tags.py). Only
#: existing vocabulary: the pipeline drops anything else. Matched by keyword
#: because every library names its own types ("Crafts & DIY", "Crafts &
#: Hobbies", "Arts and Crafts"). First matching rule per type name wins.
_TYPE_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...], tuple[str, ...]], ...] = (
    (re.compile(r"\bfilm|\bmovie|screening", re.I), ("Film",), ("film",)),
    (re.compile(r"\bmusic\b|\bconcert", re.I), ("Music",), ()),
    (re.compile(r"\bperformance|\bdance\b|\btheat", re.I), ("Arts & Theatre",), ()),
    (re.compile(r"\barts?\b|\bcrafts?\b|\bexhibit", re.I), ("Arts & Theatre",), ("art",)),
    (re.compile(r"\bfitness\b|\bexercise\b", re.I), ("Fitness",), ()),
    (re.compile(r"\bwellness\b", re.I), ("Wellness",), ("wellness",)),
    (re.compile(r"\boutdoors?\b|\bgarden|\bnature\b", re.I), ("Outdoors",), ("outdoors",)),
    (re.compile(r"\bcooking\b|\bfood\b", re.I), ("Food",), ("foodanddrink",)),
    (re.compile(r"\bjobs?\b|\bbusiness\b|\bcareer", re.I), ("Business",), ()),
    (
        re.compile(r"\bauthor|\btalks?\b|\blecture|\bpresentation|\bhistory\b|\bdiscussion", re.I),
        ("Miscellaneous",),
        ("intellectual",),
    ),
    (
        re.compile(r"\bsteam\b|\bstem\b|\bcoding\b|\bhands-on\b|\bworkshop", re.I),
        ("Miscellaneous",),
        ("workshop",),
    ),
)
#: A library programme with no more specific bucket is a community gathering.
_DEFAULT_CATEGORIES: tuple[str, ...] = ("Social",)

#: Audiences that make an event children's / family programming.
_FAMILY_AUDIENCE_RE = re.compile(
    r"\bkids?\b|\bchild|\btoddler|\bbab(y|ies)\b|\bpreschool|\bbirth to\b|\bfamil"
    r"|\bgrade school|\btweens?\b|\bpre-?teens?\b",
    re.I,
)
#: "Family" is not a canonical category; the pipeline keeps it as a genre
#: (catalog_taxonomy_v1._LEGACY_GENRES), and "familyfriendly" is the vibe the
#: product filters on.
_FAMILY_LABEL = "Family"
_FAMILY_TAG = "familyfriendly"

_VIRTUAL_NAME_RE = re.compile(r"\b(online|virtual)\b", re.I)


@dataclass(frozen=True)
class BiblioCommonsLibrary:
    """Everything that differs between two BiblioCommons calendars."""

    source_id: str
    #: Gateway id and site subdomain, e.g. ``oaklandlibrary``.
    library_id: str
    name: str
    #: City used when a location entity carries no address.
    default_city: str
    #: City centre; only ever used with CENTROID_CONFIDENCE.
    centroid: tuple[float, float]

    @property
    def site_url(self) -> str:
        return f"https://{self.library_id}.bibliocommons.com"


OAKLAND = BiblioCommonsLibrary(
    source_id="oakland_library",
    library_id="oaklandlibrary",
    name="Oakland Public Library",
    default_city="Oakland",
    centroid=(37.8044, -122.2712),
)

SAN_JOSE = BiblioCommonsLibrary(
    source_id="san_jose_library",
    library_id="sjpl",
    name="San José Public Library",
    default_city="San Jose",
    centroid=(37.3382, -121.8863),
)


class BiblioCommonsSource(InputAgentSource):
    """One-off public events from one library's BiblioCommons calendar."""

    library: BiblioCommonsLibrary
    source_tier = 2
    default_max_requests_per_second = 1

    #: Days ahead requested (``endDate = today + horizon_days``).
    horizon_days = 14
    #: Rows per request. 50 is the server's real maximum (see module docstring).
    page_size = 50
    #: Hard cap on requests per run. San José's 14-day window was 961 rows
    #: (20 pages) and Oakland's 257 (6 pages) on 2026-11-12.
    max_pages = 30
    #: Hard cap on events emitted per run, per library.
    max_events = 200
    #: Recurring series (weekly storytimes, drop-in help) would flood the feed.
    include_recurring = False
    #: Types that are services or governance rather than events. An event is
    #: left out only when *every* one of its types matches.
    service_type_pattern: re.Pattern[str] | None = re.compile(
        r"social services|health services|support services|support groups"
        r"|library commission|volunteer|computer help|technology support"
        r"|homework help",
        re.I,
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        #: Why rows were left out on the last run, by rule.
        self.last_filter_counts: dict[str, int] = {}
        self.requests_made = 0

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        today = kwargs.get("today") or datetime.now(LOCAL_TZ).date()
        payload = kwargs.get("payload")
        if isinstance(payload, dict):
            rows = self._rows(payload)
        else:
            rows = await self._crawl_pages(today)
        return self._select_candidates(rows, today)

    async def _crawl_pages(self, today: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        self.requests_made = 0
        expected: int | None = None
        page = 1
        while True:
            if page > self.max_pages:
                self.last_fetch_error = (
                    f"Page cap reached after {self.max_pages} pages; crawl incomplete"
                )
                break
            self.requests_made += 1
            try:
                payload = await self._fetch_page(today, page)
            except httpx.HTTPError as exc:
                if page == 1:
                    raise
                # Keep the pages already read, but report the crawl as partial.
                self.last_fetch_error = describe_fetch_error(exc)
                break
            except ValueError:
                if page == 1:
                    raise
                self.last_fetch_error = f"Page {page} was not valid JSON; crawl incomplete"
                break

            page_rows = self._rows(payload)
            rows.extend(page_rows)
            pagination = self._pagination(payload)
            if pagination is None:
                self.last_fetch_error = "Pagination metadata missing; crawl coverage unknown"
                break
            expected, total_pages = pagination
            if page >= total_pages or not page_rows:
                # The server echoes ``limit`` without honouring it above 50, so
                # ``pages`` alone can understate the crawl. Count the rows.
                if expected is not None and len(rows) < expected:
                    self.last_fetch_error = (
                        f"Read {len(rows)} of {expected} rows; crawl incomplete"
                    )
                break
            page += 1
        return rows

    async def _fetch_page(self, today: date, page: int) -> dict[str, Any]:
        response = await self._get_with_retry(
            f"{GATEWAY_URL}/{self.library.library_id}/events/search",
            params={
                "startDate": today.isoformat(),
                "endDate": (today + timedelta(days=self.horizon_days)).isoformat(),
                "limit": self.page_size,
                "page": page,
            },
            headers=JSON_HEADERS,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected object JSON from {self.source_name}")
        return payload

    @staticmethod
    def _pagination(payload: dict[str, Any]) -> tuple[int | None, int] | None:
        events = payload.get("events")
        pagination = events.get("pagination") if isinstance(events, dict) else None
        if not isinstance(pagination, dict):
            return None
        pages = pagination.get("pages")
        count = pagination.get("count")
        if not isinstance(pages, int) or isinstance(pages, bool):
            return None
        return (count if isinstance(count, int) and not isinstance(count, bool) else None), pages

    def _rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Resolve one page's event ids against its entities."""
        events = payload.get("events")
        entities = payload.get("entities")
        if not isinstance(events, dict) or not isinstance(entities, dict):
            return []
        ids = events.get("results")
        if not isinstance(ids, list):
            ids = events.get("items")
        by_id = entities.get("events")
        if not isinstance(ids, list) or not isinstance(by_id, dict):
            return []

        rows: list[dict[str, Any]] = []
        for event_id in ids:
            event = by_id.get(event_id)
            definition = event.get("definition") if isinstance(event, dict) else None
            if not isinstance(definition, dict):
                continue
            branch_id = definition.get("branchLocationId")
            place_id = definition.get("nonBranchLocationId")
            image = self._entity(entities, "images", definition.get("featuredImageId"))
            rows.append(
                {
                    "event": event,
                    "branch": self._entity(entities, "locations", branch_id),
                    "place": self._entity(entities, "places", place_id),
                    "types": self._names(entities, "eventTypes", definition.get("typeIds")),
                    "audiences": self._names(
                        entities, "eventAudiences", definition.get("audienceIds")
                    ),
                    "image_url": image.get("url") if image else None,
                }
            )
        return rows

    @staticmethod
    def _entity(entities: dict[str, Any], kind: str, key: Any) -> dict[str, Any] | None:
        table = entities.get(kind)
        if not isinstance(table, dict) or not isinstance(key, str):
            return None
        value = table.get(key)
        return value if isinstance(value, dict) else None

    def _names(self, entities: dict[str, Any], kind: str, ids: Any) -> list[str]:
        names: list[str] = []
        for key in ids if isinstance(ids, list) else []:
            entity = self._entity(entities, kind, key)
            name = clean_str(entity.get("name")) if entity else None
            if name and name not in names:
                names.append(name)
        return names

    def _select_candidates(
        self, rows: list[dict[str, Any]], today: date
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        candidates: dict[str, dict[str, Any]] = {}
        capped = False
        for row in rows:
            reason = self.exclusion_reason(row, today=today)
            if reason is not None:
                counts[reason] = counts.get(reason, 0) + 1
                continue
            key = str(row["event"].get("id"))
            if key in candidates:
                continue
            if len(candidates) >= self.max_events:
                capped = True
                continue
            candidates[key] = row

        self.last_filter_counts = counts
        if capped:
            self.last_fetch_error = "; ".join(
                reason
                for reason in (
                    self.last_fetch_error,
                    f"Event cap reached at {self.max_events}; crawl incomplete",
                )
                if reason
            )
        if not candidates and rows:
            self.last_empty_reason = (
                f"No one-off in-person events among {len(rows)} calendar rows "
                f"(excluded: {summarize_counts(counts) or 'none'})"
            )
        return list(candidates.values())

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def exclusion_reason(self, row: dict[str, Any], *, today: date) -> str | None:
        """Why this calendar row is not ingested - or None."""
        event = row.get("event")
        definition = event.get("definition") if isinstance(event, dict) else None
        if not isinstance(definition, dict) or not event.get("id"):
            return "malformed"
        if definition.get("isCancelled"):
            return "cancelled"
        if event.get("isRecurring") and not self.include_recurring:
            return "recurring"
        if self._is_virtual(row):
            return "virtual"
        start_day = parse_iso_date(definition.get("start"))
        if start_day is None:
            return "undated"
        if not within_horizon(start_day, today=today, horizon_days=self.horizon_days):
            return "outside_horizon"
        types = row.get("types") or []
        pattern = self.service_type_pattern
        if pattern is not None and types and all(pattern.search(name) for name in types):
            return "service_not_event"
        return None

    @staticmethod
    def _is_virtual(row: dict[str, Any]) -> bool:
        """Online programmes: flagged ``isVirtual`` (and given no location at
        all), or filed under the gateway's ``BC_VIRTUAL`` pseudo-branch."""
        definition = row["event"]["definition"]
        if definition.get("isVirtual") or definition.get("branchLocationId") == "BC_VIRTUAL":
            return True
        branch = row.get("branch")
        if not isinstance(branch, dict):
            return False
        if branch.get("id") == "BC_VIRTUAL":
            return True
        name = branch.get("name")
        return (
            isinstance(name, str)
            and bool(_VIRTUAL_NAME_RE.search(name))
            and not branch.get("address")
        )

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        event = raw_item.get("event")
        definition = event.get("definition") if isinstance(event, dict) else None
        if not isinstance(definition, dict):
            return None
        event_id = clean_str(event.get("id"))
        title = clean_str(definition.get("title"))
        times = self._times(definition)
        if not event_id or not title or times is None:
            return None
        start_time, end_time, all_day = times

        categories, vibe_tags = self._categories(
            raw_item.get("types") or [], raw_item.get("audiences") or []
        )
        image_url = clean_str(raw_item.get("image_url"))
        now = self.utc_now()
        library = self.library
        return CanonicalEvent(
            source=SourceMetadata(
                source_id=library.source_id,
                # Each occurrence has its own id (a series shares ``seriesId``).
                source_record_id=event_id,
                source_url=f"{library.site_url}/v2/events/{event_id}",
                ingested_at=now,
                last_seen_at=now,
                capture_mode="api",
                crawl_job_id=f"{library.source_id}-{int(now.timestamp())}",
            ),
            title=title,
            description=short_description(definition.get("description")),
            category_tags=categories,
            vibe_tags=vibe_tags,
            start_time=start_time,
            end_time=end_time,
            all_day=all_day,
            # A date with no clock time: midnight is a placeholder.
            start_time_is_estimated=all_day,
            location=self._location(raw_item),
            # Public-library programmes are free to attend.
            offers=OffersModel(
                is_free=True, price_min=0.0, price_max=0.0, currency="USD", price_text="Free"
            ),
            organizer=OrganizerModel(name=library.name),
            image_url=image_url if image_url and image_url.startswith("http") else None,
        )

    @staticmethod
    def _times(
        definition: dict[str, Any],
    ) -> tuple[datetime, datetime | None, bool] | None:
        """``start``/``end`` are Pacific wall-clock strings, or bare dates."""
        start_day = parse_iso_date(definition.get("start"))
        if start_day is None:
            return None
        start = parse_local_datetime(definition.get("start"))
        end = parse_local_datetime(definition.get("end"))
        if start is None:
            day_start, day_end = all_day_bounds(start_day)
            end_day = parse_iso_date(definition.get("end"))
            if end is None and end_day is not None and end_day > start_day:
                day_end = all_day_bounds(end_day)[1]
            return day_start, end if end and end > day_start else day_end, True
        return start, end if end and end > start else None, False

    def _location(self, raw_item: dict[str, Any]) -> LocationModel:
        """Branch or off-site place, with the gateway's own coordinates."""
        library = self.library
        branch = raw_item.get("branch")
        place = raw_item.get("place")
        entity = place if isinstance(place, dict) else branch if isinstance(branch, dict) else {}
        name = clean_str(entity.get("name"))
        if name and entity is branch and library.name.lower() not in name.lower():
            # "Almaden" alone is not a venue anyone can find.
            name = f"{library.name} - {name}"

        address = entity.get("address") if isinstance(entity.get("address"), dict) else {}
        street = " ".join(
            part
            for part in (clean_str(address.get("number")), clean_str(address.get("street")))
            if part
        )
        city = clean_str(address.get("city")) or library.default_city
        state = clean_str(address.get("state")) or "CA"
        region = "CA" if state.lower() in ("ca", "california") else state
        postal_code = clean_str(address.get("zip"))

        map_location = entity.get("mapLocation")
        centre = map_location.get("centrePoint") if isinstance(map_location, dict) else None
        coords = (
            feed_coordinates(centre.get("lat"), centre.get("lng"))
            if isinstance(centre, dict)
            else None
        )
        confidence = FEED_COORDINATE_CONFIDENCE
        if coords is None:
            coords = nearby_venue_coordinates(name, near=library.centroid)
        if coords is None:
            # No coordinates anywhere: the city centre, flagged as a guess.
            coords = lookup_city_coordinates(city) or library.centroid
            confidence = CENTROID_CONFIDENCE
        return LocationModel(
            venue_name=name,
            # Postal form ("80 Echo Avenue, Oakland, CA 94611"): the city in
            # the address is what places a centroid-fallback row downstream.
            address_line1=postal_address(street or None, city, region, postal_code),
            city=city,
            region=region,
            postal_code=postal_code,
            lat=coords[0],
            lon=coords[1],
            location_confidence=confidence,
        )

    @staticmethod
    def _categories(types: list[str], audiences: list[str]) -> tuple[list[str], list[str]]:
        categories: list[str] = []
        vibe_tags: list[str] = []
        for name in types:
            for pattern, rule_categories, rule_tags in _TYPE_RULES:
                if pattern.search(name):
                    categories.extend(c for c in rule_categories if c not in categories)
                    vibe_tags.extend(t for t in rule_tags if t not in vibe_tags)
                    break
        if len(categories) > 1 and "Miscellaneous" in categories:
            categories.remove("Miscellaneous")
        if not categories:
            categories.extend(_DEFAULT_CATEGORIES)
        if any(_FAMILY_AUDIENCE_RE.search(name) for name in audiences) or any(
            re.search(r"\bstorytime\b", name, re.I) for name in types
        ):
            categories.append(_FAMILY_LABEL)
            vibe_tags.append(_FAMILY_TAG)
        return categories, vibe_tags


class OaklandLibrarySource(BiblioCommonsSource):
    """oaklandlibrary.bibliocommons.com - Oakland Public Library events."""

    source_name = "oakland_library"
    library = OAKLAND


class SanJoseLibrarySource(BiblioCommonsSource):
    """sjpl.bibliocommons.com - San José Public Library events."""

    source_name = "san_jose_library"
    library = SAN_JOSE
