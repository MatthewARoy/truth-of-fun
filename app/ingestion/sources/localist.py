"""Localist connector - university public event calendars (Stanford, SJSU).

Localist is the hosted calendar product behind ``events.stanford.edu`` and
``events.sjsu.edu``. Its public JSON API (``/api/2/events``) returns one row
per *occurrence* inside the requested window::

    {"events": [{"event": {..., "event_instances": [{"event_instance": {...}}]}}],
     "page": {"current": 1, "size": 100, "total": 5}}

A campus calendar is mostly not for the public: academic deadlines, PhD
defenses, staff trainings, student-org meetings, clinical-study recruitment,
webinars. This connector keeps only what a member of the public could
plausibly turn up to - see ``LocalistSource.exclusion_reason``.

One class, parameterised by a ``LocalistCampus``; each campus is registered
as its own source (``stanford_events``, ``sjsu_events``) so that health,
canary history and partial-crawl reporting are tracked per calendar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
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
from app.ingestion.sources._calendar_common import distance_km
from app.ingestion.sources._calendar_common import feed_coordinates
from app.ingestion.sources._calendar_common import nearby_venue_coordinates
from app.ingestion.sources._calendar_common import parse_iso_date
from app.ingestion.sources._calendar_common import parse_local_datetime
from app.ingestion.sources._calendar_common import postal_address
from app.ingestion.sources._calendar_common import short_description
from app.ingestion.sources._calendar_common import summarize_counts
from app.ingestion.sources._calendar_common import within_horizon
from app.ingestion.venue_cache import lookup_city_coordinates

# Testable without API keys - public JSON feed
TESTABLE = True

# Canonical categories (app/services/categories.py) and vibe tags
# (app/services/tags.py). Only existing vocabulary is used: the pipeline drops
# anything else. Talks, tours and workshops have no bucket of their own, so
# they are filed under Miscellaneous (where Ticketmaster files lectures) and
# carry the vibe tag that makes them findable.
_ARTS = (("Arts & Theatre",), ("art",))
_PERFORMANCE = (("Arts & Theatre",), ())
_FILM = (("Film",), ("film",))
_TALK = (("Miscellaneous",), ("intellectual",))
_TOUR = (("Miscellaneous",), ())
_WORKSHOP = (("Miscellaneous",), ("workshop",))
_SOCIAL = (("Social",), ("social",))
_FITNESS = (("Fitness",), ())
_SPORTS = (("Sports",), ("sports",))

TypeRule = tuple[tuple[str, ...], tuple[str, ...]]

#: Audience labels that mean "anyone may come". Matched case-insensitively.
PUBLIC_AUDIENCES: frozenset[str] = frozenset({"general public", "everyone"})

#: Placeholder venue text that names no place.
_HIDDEN_LOCATION_RE = re.compile(
    r"\b(sign in|log ?in|rsvp|register)\b.*\blocation\b|^location\b.*\b(rsvp|registration)\b",
    re.IGNORECASE,
)
_UNANNOUNCED_LOCATION_RE = re.compile(r"^(tba|tbd|to be (announced|determined))\.?$", re.IGNORECASE)
#: "Reno, Nev." / "San Jose, Calif." - how athletics rows name an away venue.
_CITY_STATE_RE = re.compile(r"^(?P<city>[A-Za-z][A-Za-z .'\-]+),\s*(?P<state>[A-Za-z][A-Za-z.]{1,11})$")
_CALIFORNIA = frozenset({"ca", "calif", "california"})
#: Postal codes, AP abbreviations and one-word names, lowercased without dots.
#: Only a real state after the comma makes "X, Y" a city: "Old Union, Lobby"
#: is still a room on campus.
_US_STATES = _CALIFORNIA | frozenset(
    (
        "al ak az ar co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt "
        "ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc "
        "ala ariz ark colo conn del fla ill ind kan mass mich minn miss mont neb nev "
        "okla ore tenn wash wis wyo "
        "alabama alaska arizona arkansas colorado connecticut delaware florida georgia "
        "hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland "
        "massachusetts michigan minnesota mississippi missouri montana nebraska nevada "
        "ohio oklahoma oregon pennsylvania tennessee texas utah vermont virginia "
        "washington wisconsin wyoming"
    ).split()
)
#: Recruitment for a study is an advertisement, not an event.
_RECRUITMENT_RE = re.compile(
    r"\b(clinical|research)\s+(research\s+)?(study|studies|trial)\b"
    r"|\b(participants?|volunteers?|subjects?)\s+(needed|wanted)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"\$\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)")


@dataclass(frozen=True)
class LocalistCampus:
    """Everything that differs between two Localist calendars."""

    source_id: str
    base_url: str
    organizer: str
    #: City used when the feed gives an on-campus event no address.
    default_city: str
    #: Campus centre; only ever used with CENTROID_CONFIDENCE.
    centroid: tuple[float, float]
    #: Event type (lowercased, as the campus spells it) -> (categories, vibe tags).
    #: An event needs at least one of these types to be ingested.
    type_rules: dict[str, TypeRule]
    #: Event types that exclude an event whatever else it is tagged with.
    blocked_types: frozenset[str] = frozenset()
    #: Name of the audience filter in ``event.filters`` on this calendar.
    audience_filter: str = "event_audience"
    public_audiences: frozenset[str] = field(default=PUBLIC_AUDIENCES)


STANFORD = LocalistCampus(
    source_id="stanford_events",
    base_url="https://events.stanford.edu",
    organizer="Stanford University",
    default_city="Stanford",
    centroid=(37.4275, -122.1697),
    type_rules={
        "exhibition": _ARTS,
        "performance": _PERFORMANCE,
        "film/screening": _FILM,
        "lecture/presentation/talk": _TALK,
        "tour": _TOUR,
        "workshop": _WORKSHOP,
        "social event/reception": _SOCIAL,
        "fitness/recreational sport": _FITNESS,
    },
    # Seen but deliberately not allowlisted: Class/Seminar, Conference/Symposium,
    # Religious/Spiritual, Other (where study recruitment is filed).
    blocked_types=frozenset({"academic dates", "phd defense", "meeting", "support space"}),
    audience_filter="event_audience",
)

SJSU = LocalistCampus(
    source_id="sjsu_events",
    base_url="https://events.sjsu.edu",
    organizer="San José State University",
    default_city="San Jose",
    centroid=(37.3352, -121.8811),
    type_rules={
        # One bucket for galleries, recitals and theatre: no "art" vibe tag.
        "exhibitions, performances, installations": _PERFORMANCE,
        "athletics events": _SPORTS,
        "social events and gatherings": _SOCIAL,
        "visitors and tourism": _TOUR,
        "conferences, training, workshops": _WORKSHOP,
    },
    # "Info Sessions, Fairs and Events" is admissions/program marketing: not
    # allowlisted. About half of SJSU rows carry no type at all (student-org
    # events whose location is hidden behind a sign-in) and are dropped too.
    blocked_types=frozenset(),
    audience_filter="event_target_audience",
)


class LocalistSource(InputAgentSource):
    """Public, in-person events from one Localist calendar."""

    campus: LocalistCampus
    source_tier = 2
    default_max_requests_per_second = 1

    #: Days ahead requested from the API (``days=``), starting today.
    horizon_days = 14
    #: Rows per request; 100 is the API's maximum.
    page_size = 100
    #: Hard cap on requests per run. Stanford's 14-day window was 474 rows
    #: (5 pages) and SJSU's 241 (3 pages) on 2026-11-12.
    max_pages = 8
    #: Hard cap on events emitted per run.
    max_events = 500
    #: All-day occurrences of one event within the horizon at or above which
    #: it is treated as a long-running exhibition and emitted as one row.
    ongoing_min_days = 4

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
            rows = await self._crawl_pages()
        return self._select_candidates(rows, today)

    async def _crawl_pages(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        self.requests_made = 0
        page = 1
        while True:
            if page > self.max_pages:
                self.last_fetch_error = (
                    f"Page cap reached after {self.max_pages} pages; crawl incomplete"
                )
                break
            self.requests_made += 1
            try:
                payload = await self._fetch_page(page)
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
            total_pages = self._total_pages(payload)
            if total_pages is None:
                self.last_fetch_error = "Pagination metadata missing; crawl coverage unknown"
                break
            if page >= total_pages or not page_rows:
                break
            page += 1
        return rows

    async def _fetch_page(self, page: int) -> dict[str, Any]:
        response = await self._get_with_retry(
            f"{self.campus.base_url}/api/2/events",
            params={"days": self.horizon_days, "pp": self.page_size, "page": page},
            headers=JSON_HEADERS,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected object JSON from {self.source_name}")
        return payload

    @staticmethod
    def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows = payload.get("events")
        if not isinstance(rows, list):
            return []
        events: list[dict[str, Any]] = []
        for row in rows:
            event = row.get("event") if isinstance(row, dict) else None
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def _total_pages(payload: dict[str, Any]) -> int | None:
        page = payload.get("page")
        total = page.get("total") if isinstance(page, dict) else None
        return total if isinstance(total, int) and not isinstance(total, bool) else None

    def _select_candidates(
        self, rows: list[dict[str, Any]], today: date
    ) -> list[dict[str, Any]]:
        """One candidate per public occurrence inside the horizon."""
        counts: dict[str, int] = {}
        candidates: dict[str, dict[str, Any]] = {}
        all_day_keys: dict[str, list[tuple[date, str]]] = {}
        capped = False
        for event in rows:
            reason = self.exclusion_reason(event)
            if reason is not None:
                counts[reason] = counts.get(reason, 0) + 1
                continue
            for instance in self._instances(event):
                instance_id = instance.get("id")
                start_day = parse_iso_date(instance.get("start"))
                if instance_id is None or start_day is None:
                    counts["undated"] = counts.get("undated", 0) + 1
                    continue
                if not within_horizon(start_day, today=today, horizon_days=self.horizon_days):
                    counts["outside_horizon"] = counts.get("outside_horizon", 0) + 1
                    continue
                key = str(instance_id)
                if key in candidates:
                    continue
                event_id = event.get("id")
                if instance.get("all_day") and event_id is not None:
                    all_day_keys.setdefault(str(event_id), []).append((start_day, key))
                if len(candidates) >= self.max_events:
                    capped = True
                    continue
                candidates[key] = {"event": event, "instance": instance}

        collapsed = self._collapse_ongoing_runs(candidates, all_day_keys)
        if collapsed:
            counts["ongoing_days_collapsed"] = collapsed

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
                f"No public in-person events among {len(rows)} calendar rows "
                f"(excluded: {summarize_counts(counts) or 'none'})"
            )
        return list(candidates.values())

    def _collapse_ongoing_runs(
        self,
        candidates: dict[str, dict[str, Any]],
        all_day_keys: dict[str, list[tuple[date, str]]],
    ) -> int:
        """Fold a long-running all-day event into one ongoing row.

        Localist lists a months-long exhibition as one all-day occurrence per
        day. Emitted as-is, seventeen Stanford exhibitions were 149 of the
        campus's 259 events — the feed read as the same shows repeated daily.
        An event with ``ongoing_min_days`` or more all-day occurrences in the
        horizon becomes a single row running from its first listed day to its
        last, with an event-level id that stays stable as the window moves.
        Shorter all-day runs (a festival weekend, a weekly open day) keep one
        row per day. Returns the number of per-day rows removed.
        """
        removed = 0
        for event_id, keyed_days in all_day_keys.items():
            kept = sorted((day, key) for day, key in keyed_days if key in candidates)
            if len(kept) < self.ongoing_min_days:
                continue
            first_key = kept[0][1]
            candidates[first_key]["ongoing"] = {
                "record_id": f"{event_id}:ongoing",
                "until": kept[-1][0],
            }
            for _, key in kept[1:]:
                del candidates[key]
                removed += 1
        return removed

    @staticmethod
    def _instances(event: dict[str, Any]) -> list[dict[str, Any]]:
        instances = event.get("event_instances")
        if not isinstance(instances, list):
            return []
        found: list[dict[str, Any]] = []
        for wrapper in instances:
            instance = wrapper.get("event_instance") if isinstance(wrapper, dict) else None
            if isinstance(instance, dict):
                found.append(instance)
        return found

    # ------------------------------------------------------------------
    # Public-interest filter
    # ------------------------------------------------------------------

    def exclusion_reason(self, event: dict[str, Any]) -> str | None:
        """Why this calendar row is not a public, attendable event - or None.

        In order: it must be live, not private, in person (or hybrid), carry
        an allowlisted event type and no blocked one, be open to the general
        public where the calendar says who it is for, not be study
        recruitment, and have a place that can be located.
        """
        if event.get("status") != "live":
            return "not_live"
        if event.get("private"):
            return "private"
        if event.get("experience") not in ("inperson", "hybrid"):
            return "virtual"

        types = self._filter_names(event, "event_types")
        if types & self.campus.blocked_types:
            return "blocked_type"
        if not types & set(self.campus.type_rules):
            return "type_not_allowlisted"

        # Where the calendar tags audiences, one of them must be the public.
        # No audience tag at all is not evidence the event is closed.
        audiences = self._filter_names(event, self.campus.audience_filter)
        if audiences and not audiences & self.campus.public_audiences:
            return "audience_not_public"

        title = event.get("title")
        if isinstance(title, str) and _RECRUITMENT_RE.search(title):
            return "study_recruitment"

        if self._resolve_location(event) is None:
            return "no_usable_location"
        return None

    @staticmethod
    def _filter_names(event: dict[str, Any], key: str) -> set[str]:
        filters = event.get("filters")
        values = filters.get(key) if isinstance(filters, dict) else None
        names: set[str] = set()
        if isinstance(values, list):
            for value in values:
                name = value.get("name") if isinstance(value, dict) else None
                if isinstance(name, str) and name.strip():
                    names.add(name.strip().lower())
        return names

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        return candidate if isinstance(candidate, dict) else None

    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        event = raw_item.get("event")
        instance = raw_item.get("instance")
        if not isinstance(event, dict) or not isinstance(instance, dict):
            return None

        title = clean_str(event.get("title"))
        source_url = clean_str(event.get("localist_url"))
        instance_id = instance.get("id")
        if not title or not source_url or instance_id is None:
            return None

        times = self._instance_times(instance)
        location = self._resolve_location(event)
        if times is None or location is None:
            return None
        start_time, end_time, all_day = times
        record_id = str(instance_id)
        ongoing = raw_item.get("ongoing")
        if isinstance(ongoing, dict) and isinstance(ongoing.get("until"), date):
            # One row for the whole listed run; see _collapse_ongoing_runs.
            record_id = str(ongoing["record_id"])
            end_time = max(end_time or start_time, all_day_bounds(ongoing["until"])[1])

        categories, vibe_tags = self._categories(event)
        now = self.utc_now()
        return CanonicalEvent(
            source=SourceMetadata(
                source_id=self.campus.source_id,
                # The occurrence id: stable across runs, unique per date.
                source_record_id=record_id,
                source_url=source_url,
                ingested_at=now,
                last_seen_at=now,
                capture_mode="api",
                crawl_job_id=f"{self.campus.source_id}-{int(now.timestamp())}",
            ),
            title=title,
            description=short_description(
                event.get("description_text") or event.get("description")
            ),
            category_tags=categories,
            vibe_tags=vibe_tags,
            start_time=start_time,
            end_time=end_time,
            all_day=all_day,
            # An all-day row publishes a date and no clock time: midnight is a
            # placeholder and must not be shown or matched as a start time.
            start_time_is_estimated=all_day,
            location=location,
            offers=self._offers(event),
            organizer=OrganizerModel(name=self._organizer(event)),
            image_url=self._image_url(event),
        )

    @staticmethod
    def _instance_times(
        instance: dict[str, Any],
    ) -> tuple[datetime, datetime | None, bool] | None:
        start = parse_local_datetime(instance.get("start"))
        start_day = parse_iso_date(instance.get("start"))
        if start_day is None:
            return None
        end = parse_local_datetime(instance.get("end"))
        if instance.get("all_day") or start is None:
            day_start, day_end = all_day_bounds(start_day)
            # A published closing time (an exhibition's "until 18:00") is kept;
            # otherwise the event simply lasts the day.
            return day_start, end if end and end > day_start else day_end, True
        return start, end if end and end > start else None, False

    def _resolve_location(self, event: dict[str, Any]) -> LocationModel | None:
        """Feed coordinates, else a nearby known venue, else the campus centroid.

        Returns None when the row names somewhere that cannot be placed (an
        away game "Reno, Nev.", a venue still "TBA") - stamping the campus
        centroid on those would invent a location.
        """
        campus = self.campus
        geo = event.get("geo") if isinstance(event.get("geo"), dict) else {}
        venue = clean_str(event.get("location_name")) or clean_str(event.get("location"))
        if venue and _HIDDEN_LOCATION_RE.search(venue):
            venue = None
        street = clean_str(geo.get("street"))
        published_address = clean_str(event.get("address"))
        geo_city = clean_str(geo.get("city"))
        region = clean_str(geo.get("state")) or "CA"
        postal_code = clean_str(geo.get("zip"))

        coords = feed_coordinates(geo.get("latitude"), geo.get("longitude"))
        if coords is not None:
            return LocationModel(
                venue_name=venue,
                address_line1=(
                    postal_address(street, geo_city or campus.default_city, region, postal_code)
                    if street
                    else published_address
                    or postal_address(None, geo_city or campus.default_city, region, postal_code)
                ),
                city=geo_city or campus.default_city,
                region=region,
                postal_code=postal_code,
                lat=coords[0],
                lon=coords[1],
                location_confidence=FEED_COORDINATE_CONFIDENCE,
            )

        if venue and _UNANNOUNCED_LOCATION_RE.match(venue):
            return None

        city = geo_city or campus.default_city
        centroid = campus.centroid
        place = _CITY_STATE_RE.match(venue) if venue else None
        state = place.group("state").replace(".", "").lower() if place else None
        if place and state in _US_STATES:
            # The "venue" is a city: an athletics row for a game played there.
            if state not in _CALIFORNIA:
                return None
            city = place.group("city").strip()
            if city.lower() != campus.default_city.lower():
                city_centroid = lookup_city_coordinates(city)
                if city_centroid is None:
                    return None
                centroid = city_centroid
            venue = None

        known = nearby_venue_coordinates(venue, near=campus.centroid)
        # The cache's entry for the campus itself ("Stanford University") is a
        # centroid too, and must not come back as a venue-level fix.
        if known is not None and distance_km(known, campus.centroid) > 0.2:
            lat, lon, confidence = known[0], known[1], FEED_COORDINATE_CONFIDENCE
        else:
            lat, lon, confidence = centroid[0], centroid[1], CENTROID_CONFIDENCE
        return LocationModel(
            venue_name=venue,
            # On a centroid the address is what places the event downstream:
            # the published one if there is one, else just "City, CA".
            address_line1=published_address or postal_address(street, city, "CA", postal_code),
            city=city,
            region="CA",
            postal_code=postal_code,
            lat=lat,
            lon=lon,
            location_confidence=confidence,
        )

    def _categories(self, event: dict[str, Any]) -> tuple[list[str], list[str]]:
        categories: list[str] = []
        vibe_tags: list[str] = []
        # Sorted so the output does not depend on the feed's filter order.
        for name in sorted(self._filter_names(event, "event_types")):
            rule = self.campus.type_rules.get(name)
            if rule is None:
                continue
            for category in rule[0]:
                if category not in categories:
                    categories.append(category)
            for tag in rule[1]:
                if tag not in vibe_tags:
                    vibe_tags.append(tag)
        # A specific bucket makes the catch-all redundant.
        if len(categories) > 1 and "Miscellaneous" in categories:
            categories.remove("Miscellaneous")
        return categories, vibe_tags

    @staticmethod
    def _offers(event: dict[str, Any]) -> OffersModel:
        """Price as published. ``free: false`` only means the box was not ticked."""
        cost_text = clean_str(event.get("ticket_cost"))
        amounts = [
            float(match.replace(",", "")) for match in _PRICE_RE.findall(cost_text or "")
        ]
        says_free = bool(cost_text) and "free" in cost_text.lower() and not amounts
        if event.get("free") is True or says_free:
            return OffersModel(
                is_free=True, price_min=0.0, price_max=0.0, currency="USD",
                price_text=cost_text or "Free",
            )
        if amounts:
            return OffersModel(
                is_free=False, price_min=min(amounts), price_max=max(amounts),
                currency="USD", price_text=cost_text,
            )
        # Nothing published: unknown, not free. No currency without an amount.
        return OffersModel(price_text=cost_text)

    def _organizer(self, event: dict[str, Any]) -> str:
        for key in ("departments", "groups"):
            values = event.get(key)
            if isinstance(values, list):
                for value in values:
                    name = clean_str(value.get("name")) if isinstance(value, dict) else None
                    if name:
                        return name
        return self.campus.organizer

    @staticmethod
    def _image_url(event: dict[str, Any]) -> str | None:
        url = clean_str(event.get("photo_url"))
        return url if url and url.startswith(("https://", "http://")) else None


class StanfordEventsSource(LocalistSource):
    """events.stanford.edu - Stanford University's public calendar."""

    source_name = "stanford_events"
    campus = STANFORD


class SJSUEventsSource(LocalistSource):
    """events.sjsu.edu - San José State University's public calendar."""

    source_name = "sjsu_events"
    campus = SJSU
