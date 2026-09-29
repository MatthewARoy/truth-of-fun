from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from Levenshtein import ratio as levenshtein_ratio
from rapidfuzz import fuzz
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.localtime import LOCAL_TZ
from app.models.event import Event
from app.models.source_record import EventSourceRecord
from app.models.vibe_tag_cache import VibeTagCache
from app.services.categories import infer_categories
from app.services.geocoding import (
    MIN_SEARCHABLE_LOCATION_CONFIDENCE,
    VenueGeocoder,
    worth_writing,
)
from app.services.tags import canonical_vibe_tags
from app.services.vibe_tagger import ClaudeVibeTagger, VibeTagger

logger = logging.getLogger(__name__)

# Column widths from app/models/event.py. Sources are third-party and their
# field lengths are not ours to control — 19hz, for instance, uses the event
# URL as its identifier, and those carry Instagram tracking parameters well
# past 255 characters. Because the whole cycle commits in one transaction, a
# single over-long value used to abort ingestion for *every* source, discarding
# a run's worth of events from all eleven. Clamping at the normalization
# boundary keeps one bad record from costing the entire cycle.
_MAX_TITLE = 500
_MAX_SOURCE_NAME = 100
_MAX_SOURCE_EVENT_ID = 255
_MAX_URL = 2048
_MAX_VENUE_NAME = 255
_MAX_ORGANIZER_NAME = 255
_MAX_STATUS = 50


class DataPipelineService:
    """Process raw ingested events with dedupe, LLM tagging, and conditional upserts."""

    DEDUPE_WINDOW_HOURS = 2
    DEDUPE_TITLE_SIMILARITY_THRESHOLD = 85.0
    # Live event titles are frequently lineup listings whose artist order
    # rotates between sources and whose support acts differ. Whole-string edit
    # distance reads those as different events (the same Brick & Mortar show
    # scored 62.9), so compare token sets instead: order-insensitive and
    # tolerant of one side carrying extra names.
    #
    # Only ever applied once the venue matches. Token-set similarity is not
    # identity on its own — it returns 100 whenever one title's tokens are a
    # subset of the other — so it needs corroboration. With the venue agreed,
    # 60 separates the same bill from a different one: distinct parties at one
    # venue score around 24.
    DEDUPE_SAME_VENUE_TOKEN_THRESHOLD = 60.0

    def __init__(
        self,
        *,
        vibe_tagger: VibeTagger | None = None,
        geocoder: VenueGeocoder | None = None,
        max_tagging_calls_per_run: int = 200,
    ) -> None:
        self._vibe_tagger = vibe_tagger or ClaudeVibeTagger()
        # No geocoder is the default: the pipeline then behaves exactly as it
        # did before geocoding existed. The worker supplies one when the
        # deployment has a provider configured.
        self._geocoder = geocoder
        self._max_tagging_calls_per_run = max(0, max_tagging_calls_per_run)
        self._tagging_calls = 0

    async def process_raw_events(
        self,
        *,
        session: Session,
        raw_events: list[dict[str, Any]],
    ) -> dict[str, int]:
        normalized = [self._normalize_event_payload(raw) for raw in raw_events]
        rejected = sum(payload is None for payload in normalized)
        observations = [p for p in normalized if p is not None]
        for payload in observations:
            # Hash source input before provider enrichment or LLM tags, which
            # are derived facts and must not make a replay look like a revision.
            payload["_source_hash"] = hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode()
            ).hexdigest()
        observations = await self.enrich_locations(
            session=session,
            events=observations,
        )
        self._tagging_calls = 0

        inserted_ids: set[int] = set()
        updated_ids: set[int] = set()
        seen_ids: set[int] = set()

        # Preserve each source observation until its revision has been checked.
        # Early in-batch merging loses which provider changed which facts.
        for event_payload in observations:
            existing = self._find_existing_event(
                session=session, incoming_event=event_payload
            )
            llm_tags = await self._cached_vibe_tags(
                session, event_payload.get("description")
            )
            event_payload["tags"] = canonical_vibe_tags(
                self._merge_lists(event_payload.get("tags", []), llm_tags)
            )

            if existing is None:
                existing = Event(**{
                    key: value for key, value in event_payload.items()
                    if key in Event.model_fields
                })
                session.add(existing)
                session.flush()
                self._remember_source_records(session, existing, event_payload)
                inserted_ids.add(existing.id)
                seen_ids.add(existing.id)
                continue

            if self.has_significant_new_information(
                existing_event=existing, incoming_event=event_payload
            ):
                merged_for_update = self._merge_event_payloads(
                    primary=self._event_to_payload(existing),
                    secondary=event_payload,
                )
                self._apply_payload(existing=existing, payload=merged_for_update)
                updated_ids.add(existing.id)
            seen_ids.add(existing.id)
            self._remember_source_records(session, existing, event_payload)

        session.commit()
        return {
            "inserted": len(inserted_ids),
            "updated": len(updated_ids - inserted_ids),
            "skipped": len(seen_ids - inserted_ids - updated_ids),
            "deduped_count": len(seen_ids),
            "rejected": rejected,
            "tagging_calls": self._tagging_calls,
        }

    async def _cached_vibe_tags(
        self, session: Session, description: str | None
    ) -> list[str]:
        if not description or not description.strip():
            return []
        text = description.strip()[:ClaudeVibeTagger.MAX_DESCRIPTION_CHARS]
        identity = getattr(
            self._vibe_tagger, "cache_identity", type(self._vibe_tagger).__qualname__
        )
        key = hashlib.sha256(f"{identity}\0{text}".encode()).hexdigest()
        cached = session.get(VibeTagCache, key)
        if cached is not None:
            return list(cached.tags)
        if self._tagging_calls >= self._max_tagging_calls_per_run:
            return []
        self._tagging_calls += 1
        tags = canonical_vibe_tags(await self._vibe_tagger.generate_vibe_tags(text))
        # Provider failures and disabled credentials must be retried next run,
        # rather than fossilized as a successful empty classification.
        if getattr(self._vibe_tagger, "last_call_succeeded", True):
            # Another worker may have classified the same description while
            # this one awaited the provider. A cache collision must not roll
            # back the authoritative event/source writes in the outer transaction.
            try:
                with session.begin_nested():
                    session.add(VibeTagCache(cache_key=key, tags=tags))
                    session.flush()
            except IntegrityError:
                winner = session.get(VibeTagCache, key)
                if winner is None:
                    raise
                return list(winner.tags)
        return tags

    @staticmethod
    def _stable_source_identity(payload: dict[str, Any]) -> bool:
        """Only connector IDs known to identify an event survive date changes.

        Curator slugs, newsletter links, 19hz profile/calendar URLs and Luma's
        title fallback can identify many separate nights. Those sources keep
        using temporal matching until their connectors emit stronger IDs.
        """
        source, key = payload.get("source_name"), payload.get("source_event_id")
        if not isinstance(key, str) or not key:
            return False
        is_url = key.startswith(("http://", "https://"))
        if source in {"ticketmaster", "meetup"}:
            return True
        if source == "eventbrite":
            return not is_url or "/e/" in key
        if source == "luma":
            return not is_url and not key.startswith("luma-")
        if source == "reddit":
            return not is_url or "/comments/" in key
        return False

    @classmethod
    def _source_records(cls, payload: dict[str, Any]) -> list[tuple[str, str]]:
        records = list(payload.get("_source_records") or [])
        if cls._stable_source_identity(payload):
            pair = (payload["source_name"], payload["source_event_id"])
            if pair not in records:
                records.append(pair)
        return records

    def _remember_source_records(
        self, session: Session, event: Event, payload: dict[str, Any]
    ) -> None:
        for name, source_id in self._source_records(payload):
            record = session.get(EventSourceRecord, (name, source_id))
            if record is None:
                session.add(EventSourceRecord(
                    source_name=name, source_event_id=source_id, event_id=event.id,
                    content_hash=payload.get("_source_hash"),
                ))
            elif record.event_id != event.id:
                raise ValueError("Source identity already belongs to a different event")
            else:
                record.content_hash = payload.get("_source_hash")

    async def enrich_locations(
        self,
        *,
        session: Session | None,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Give every centroid-bound payload one more shot at a real address.

        A payload already at or above the radius-search threshold is left
        alone: its venue came from the hand-verified table, which outranks
        anything a provider returns, and confirming it would spend a
        rate-limited lookup for nothing.

        Enrichment happens before the upsert, so ``has_significant_new
        _information`` sees the improved confidence and rewrites rows that
        were stored on a centroid in an earlier cycle.
        """
        if self._geocoder is None:
            return events

        # The lookup ceiling bounds a single cycle. A worker process lives
        # for weeks, so without this it would spend the budget once and stop
        # geocoding for good.
        self._geocoder.reset_run_budget()

        for payload in events:
            confidence = float(payload.get("location_confidence") or 0.0)
            if confidence >= MIN_SEARCHABLE_LOCATION_CONFIDENCE:
                continue

            try:
                result = await self._geocoder.resolve(
                    session=session,
                    venue_name=payload.get("venue_name"),
                    raw_address=payload.get("raw_address"),
                    city=payload.get("city"),
                )
            except Exception:
                # Geocoding is an enhancement, never a precondition. A broken
                # provider leaves the payload on its centroid and the cycle
                # completes.
                logger.warning(
                    "geocoding failed for %r; keeping fallback location",
                    payload.get("venue_name") or payload.get("raw_address"),
                    exc_info=True,
                )
                continue

            if not worth_writing(result, confidence):
                continue

            payload["location"] = f"POINT({result.lon} {result.lat})"
            payload["location_confidence"] = result.confidence

        return events

    def deduplicate_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        for raw_event in events:
            normalized = self._normalize_event_payload(raw_event)
            if normalized is None:
                continue

            duplicate_index = next(
                (
                    i
                    for i, existing in enumerate(deduped)
                    if self._is_duplicate(existing, normalized)
                ),
                None,
            )
            if duplicate_index is None:
                deduped.append(normalized)
            else:
                deduped[duplicate_index] = self._merge_event_payloads(
                    primary=deduped[duplicate_index],
                    secondary=normalized,
                )
        return deduped

    def _find_existing_event(
        self,
        *,
        session: Session,
        incoming_event: dict[str, Any],
    ) -> Event | None:
        # A source record remains the same event even when its date or venue
        # changes. Only unidentified cross-source candidates use fuzzy time matching.
        identities = self._source_records(incoming_event)
        owners: dict[int, Event] = {}
        for name, source_id in identities:
            record = session.get(EventSourceRecord, (name, source_id))
            if record is not None:
                content_hash = incoming_event.get("_source_hash")
                if content_hash and record.content_hash:
                    incoming_event["_source_unchanged"] = content_hash == record.content_hash
                    incoming_event["_source_known_revision"] = content_hash != record.content_hash
                event = session.get(Event, record.event_id)
                if event is not None:
                    owners[event.id] = event
            else:
                legacy = session.exec(select(Event).where(
                    Event.source_name == name, Event.source_event_id == source_id
                )).all()
                if legacy:
                    # Old ingestion inserted a new row when the same listing
                    # moved dates. Preserve every row/reference, but route new
                    # observations to the oldest row, as migration 003 does.
                    event = min(legacy, key=lambda row: row.id)
                    if len(legacy) > 1:
                        logger.warning(
                            "Legacy duplicate source identity for %s: routing rows %s to %s",
                            name, sorted(row.id for row in legacy), event.id,
                        )
                    owners[event.id] = event
        if len(owners) > 1:
            raise ValueError("Ambiguous source identities require reconciliation")
        if owners:
            return next(iter(owners.values()))
        start_at = incoming_event["start_at"]
        window = timedelta(hours=self.DEDUPE_WINDOW_HOURS)
        day_start, day_end = self._local_day_bounds(start_at)
        if incoming_event.get("start_time_is_estimated"):
            # Our own clock time is a placeholder, so scan the whole local day.
            time_filter = (Event.start_at >= day_start, Event.start_at < day_end)
        else:
            # We have a real time, but a stored row may not: an Eventbrite
            # placeholder at 19:00 sits outside a real 13:00 start's +/-2h
            # window, so widen to the local day for flagged rows only.
            time_filter = (
                or_(
                    (Event.start_at >= (start_at - window))
                    & (Event.start_at <= (start_at + window)),
                    Event.start_time_is_estimated.is_(True)
                    & (Event.start_at >= day_start)
                    & (Event.start_at < day_end),
                ),
            )
        stmt = select(Event).where(*time_filter)
        candidates = session.exec(stmt).all()
        if not candidates:
            return None

        # Same rule as in-batch dedupe: matching on title alone here would let
        # a duplicate that survived one cycle be re-inserted on the next.
        viable = [
            (
                candidate,
                max(
                    self._title_similarity(candidate.title, incoming_event["title"]),
                    self._token_set_similarity(
                        candidate.title, incoming_event["title"]
                    ),
                ),
            )
            for candidate in candidates
            if self._is_duplicate(self._candidate_payload(candidate), incoming_event)
        ]
        if not viable:
            return None
        return max(viable, key=lambda item: item[1])[0]

    def _candidate_payload(self, candidate: Event) -> dict[str, Any]:
        """The subset of a stored event the duplicate check reads."""
        return {
            "title": candidate.title,
            "start_at": self._coerce_datetime(candidate.start_at),
            "start_time_is_estimated": candidate.start_time_is_estimated,
            "venue_name": candidate.venue_name,
            "external_url": candidate.external_url,
            "source_name": candidate.source_name,
            "source_event_id": candidate.source_event_id,
        }

    def has_significant_new_information(
        self,
        *,
        existing_event: Event,
        incoming_event: dict[str, Any],
    ) -> bool:
        existing_payload = self._event_to_payload(existing_event)

        if incoming_event.get("_source_unchanged"):
            # Source facts cannot revert newer facts, but derived enrichment
            # can still improve on a prior failed geocode/tagging attempt.
            return (
                (self._location_context_matches(existing_payload, incoming_event)
                 and float(incoming_event.get("location_confidence") or 0)
                 > float(existing_payload.get("location_confidence") or 0) + 0.05)
                or bool(set(incoming_event.get("tags") or []) - set(existing_payload.get("tags") or []))
                or bool(set(incoming_event.get("categories") or []) - set(existing_payload.get("categories") or []))
            )

        if self._same_source_identity(existing_payload, incoming_event) or incoming_event.get("_source_known_revision"):
            merged = self._merge_event_payloads(
                primary=existing_payload, secondary=incoming_event
            )
            if any(
                merged.get(key) != existing_payload.get(key)
                for key in self.REVISION_FIELDS
            ) or merged.get("_coordinate_revision"):
                return True
        elif self.STATUS_SEVERITY.get(
            incoming_event.get("status"), 0
        ) > self.STATUS_SEVERITY.get(existing_payload.get("status"), 0):
            return True

        for key in (
            "description",
            "external_url",
            "venue_name",
            "raw_address",
            "image_url",
            "end_at",
            "price",
            "currency",
        ):
            if self._is_missing(existing_payload.get(key)) and not self._is_missing(
                incoming_event.get(key)
            ):
                return True

        # A venue that has since become resolvable is new information: without
        # this, a row stored on a centroid guess keeps that guess forever and
        # stays invisible to radius search. The margin stops float noise from
        # rewriting rows every cycle.
        existing_confidence = existing_payload.get("location_confidence")
        incoming_confidence = incoming_event.get("location_confidence")
        if (
            isinstance(existing_confidence, (int, float))
            and isinstance(incoming_confidence, (int, float))
            and float(incoming_confidence) > float(existing_confidence) + 0.05
        ):
            return True

        existing_categories = set(existing_payload.get("categories") or [])
        incoming_categories = set(incoming_event.get("categories") or [])
        if incoming_categories - existing_categories:
            return True

        existing_tags = set(existing_payload.get("tags") or [])
        incoming_tags = set(incoming_event.get("tags") or [])
        if incoming_tags - existing_tags:
            return True

        existing_description = existing_payload.get("description")
        incoming_description = incoming_event.get("description")
        if isinstance(existing_description, str) and isinstance(
            incoming_description, str
        ):
            similarity = self._text_similarity(
                existing_description, incoming_description
            )
            if (
                len(incoming_description.strip())
                > len(existing_description.strip()) + 30
                and similarity < 95
            ):
                return True

        # Losing the placeholder flag matters even when the clock value is
        # unchanged: the field goes from a guess to a fact.
        if existing_payload.get("start_time_is_estimated") and not incoming_event.get(
            "start_time_is_estimated"
        ):
            return True

        # Only meaningful between two published times. A placeholder hour sits
        # a fabricated distance from everything, so comparing it would report a
        # significant move on every cycle forever -- the merge rule keeps the
        # real time, so the delta never closes.
        both_times_are_real = not (
            existing_payload.get("start_time_is_estimated")
            or incoming_event.get("start_time_is_estimated")
            or incoming_event.get("_source_unchanged")
        )
        if (
            both_times_are_real
            and existing_payload.get("start_at")
            and incoming_event.get("start_at")
        ):
            delta = abs(
                (
                    incoming_event["start_at"] - existing_payload["start_at"]
                ).total_seconds()
            )
            if delta > 30 * 60:
                return True

        return False

    def _is_duplicate(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        if self._same_source_identity(left, right):
            return True
        # Everything below needs the events to be close in time. A URL match
        # is deliberately inside this guard: connectors fall back to a venue
        # calendar or profile page when a row has no event-specific link, so
        # the same URL routinely covers a whole season of different nights.
        if not self._starts_are_compatible(left, right):
            return False

        # Matching generic titles are not evidence against two explicitly
        # different venues ("Community Yoga" runs all across the region).
        if (
            self._normalize_venue(left.get("venue_name"))
            and self._normalize_venue(right.get("venue_name"))
            and not self._same_venue(left.get("venue_name"), right.get("venue_name"))
        ):
            return False

        if self._same_external_url(left.get("external_url"), right.get("external_url")):
            return True

        if (
            self._title_similarity(left["title"], right["title"])
            > self.DEDUPE_TITLE_SIMILARITY_THRESHOLD
        ):
            return True

        # Token-set similarity alone is not identity: it scores 100 whenever
        # one title's tokens are a subset of the other ("Comedy Night" vs
        # "Free Sunday Comedy Night in Downtown SF"). Only trust it when the
        # venue corroborates.
        if self._same_venue(left.get("venue_name"), right.get("venue_name")):
            token_similarity = self._token_set_similarity(left["title"], right["title"])
            return token_similarity >= self.DEDUPE_SAME_VENUE_TOKEN_THRESHOLD

        return False

    def _starts_are_compatible(
        self, left: dict[str, Any], right: dict[str, Any]
    ) -> bool:
        """Are these two start times close enough to be the same event?

        Normally: within DEDUPE_WINDOW_HOURS. But when either side's clock time
        is a connector placeholder, the hours carry no information and the gap
        between them is noise -- Eventbrite's 19:00 default sat six hours from
        funcheap's real 13:00 for the same zoo tea party, so the window barred
        a match it should have made. Only the calendar date is real on that
        side, so that is all we require. The title/venue/URL corroboration
        below is unchanged and remains the guard against over-merging.
        """
        if left.get("start_time_is_estimated") or right.get("start_time_is_estimated"):
            return self._same_local_day(left["start_at"], right["start_at"])
        start_delta_hours = (
            abs((left["start_at"] - right["start_at"]).total_seconds()) / 3600
        )
        return start_delta_hours <= self.DEDUPE_WINDOW_HOURS

    @staticmethod
    def _same_local_day(left: datetime, right: datetime) -> bool:
        """Compare calendar dates in SF local time.

        Not UTC: a 19:00 SF placeholder is 02:00 UTC the *next* day, so a UTC
        date comparison would fail exactly the case this exists for.
        """
        return left.astimezone(LOCAL_TZ).date() == right.astimezone(LOCAL_TZ).date()

    @staticmethod
    def _local_day_bounds(moment: datetime) -> tuple[datetime, datetime]:
        """UTC bounds of the SF-local calendar day containing ``moment``."""
        local_start = moment.astimezone(LOCAL_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        local_end = local_start + timedelta(days=1)
        return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)

    @staticmethod
    def _same_external_url(left: Any, right: Any) -> bool:
        if not isinstance(left, str) or not isinstance(right, str):
            return False
        left_url, right_url = left.strip().rstrip("/"), right.strip().rstrip("/")
        return bool(left_url) and left_url == right_url

    @staticmethod
    def _normalize_venue(venue_name: Any) -> str:
        """Reduce a venue string to a comparable core.

        Sources append their own decoration — 19hz tacks the city and genre
        list onto the name ("The Stud (San Francisco) house, disco") — so
        compare only the part before the first parenthesis.
        """
        if not isinstance(venue_name, str):
            return ""
        return venue_name.split("(")[0].strip().casefold()

    def _same_venue(self, left: Any, right: Any) -> bool:
        left_venue, right_venue = (
            self._normalize_venue(left),
            self._normalize_venue(right),
        )
        if not left_venue or not right_venue:
            return False
        return left_venue == right_venue

    def _title_similarity(self, left_title: str, right_title: str) -> float:
        return self._text_similarity(left_title, right_title)

    @staticmethod
    def _token_set_similarity(left_title: str, right_title: str) -> float:
        return float(fuzz.token_set_ratio(left_title, right_title))

    def _text_similarity(self, left_text: str, right_text: str) -> float:
        left = (left_text or "").strip().lower()
        right = (right_text or "").strip().lower()
        if not left or not right:
            return 0.0
        return levenshtein_ratio(left, right) * 100

    STATUS_SEVERITY = {"scheduled": 0, "postponed": 1, "cancelled": 2, "past": 3}
    REVISION_FIELDS = (
        "title", "description", "start_at", "end_at", "price", "currency",
        "status", "is_free", "attendee_count", "venue_name", "raw_address",
        "external_url", "image_url", "organizer_name",
    )

    @classmethod
    def _same_source_identity(cls, left: dict[str, Any], right: dict[str, Any]) -> bool:
        return cls._stable_source_identity(left) and (
            left.get("source_name"), left.get("source_event_id")
        ) == (right.get("source_name"), right.get("source_event_id"))

    def _location_context_matches(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        """Coordinates from a prior venue cannot enrich the current venue."""
        for key in ("venue_name", "raw_address", "city"):
            first, second = left.get(key), right.get(key)
            if self._is_missing(first) or self._is_missing(second):
                continue
            if key == "venue_name":
                if not self._same_venue(first, second):
                    return False
            elif str(first).strip().casefold() != str(second).strip().casefold():
                return False
        return True

    def _merge_event_payloads(
        self, *, primary: dict[str, Any], secondary: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(primary)
        same_source = self._same_source_identity(primary, secondary)
        merged["_source_records"] = list(dict.fromkeys(
            self._source_records(primary) + self._source_records(secondary)
        ))

        # A published time beats a placeholder outright, whatever the tiers say:
        # the trust hierarchy ranks sources, not guesses, and Eventbrite (tier 1)
        # defaults its hour while funcheap (tier 2) reads the real one off the
        # page. Otherwise the usual rule holds -- a more authoritative
        # (lower-tier) source owns the times, and between equal tiers we keep
        # the earliest start and latest end.
        primary_estimated = bool(primary.get("start_time_is_estimated"))
        secondary_estimated = bool(secondary.get("start_time_is_estimated"))
        primary_tier = int(primary.get("source_tier", 99))
        secondary_tier = int(secondary.get("source_tier", 99))
        # Equal-tier aliases may refresh a scheduled listing, but cannot
        # take ownership of an unavailable listing and later undo its owner's
        # cancellation/postponement. Only the owner or a better tier can do so.
        alias_can_revise = bool(secondary.get("_source_known_revision")) and (
            secondary_tier < primary_tier or primary.get("status", "scheduled") == "scheduled"
        )
        authoritative_revision = (
            same_source or alias_can_revise
        ) and secondary_tier <= primary_tier and not secondary.get("_source_unchanged")
        location_context_matches = self._location_context_matches(primary, secondary)
        if primary_estimated != secondary_estimated:
            time_winner, time_loser = (
                (secondary, primary) if primary_estimated else (primary, secondary)
            )
            merged["start_at"] = time_winner["start_at"]
            merged["end_at"] = time_winner.get("end_at") or time_loser.get("end_at")
            merged["start_time_is_estimated"] = False
        elif primary_tier < secondary_tier:
            merged["start_at"] = primary["start_at"]
            merged["end_at"] = primary.get("end_at") or secondary.get("end_at")
            merged["start_time_is_estimated"] = primary_estimated
        elif secondary_tier < primary_tier:
            merged["start_at"] = secondary["start_at"]
            merged["end_at"] = secondary.get("end_at") or primary.get("end_at")
            merged["start_time_is_estimated"] = secondary_estimated
        else:
            merged["start_at"] = min(primary["start_at"], secondary["start_at"])
            merged["end_at"] = self._pick_latest_datetime(
                primary.get("end_at"), secondary.get("end_at")
            )
            # Both sides agree on whether the hour is real (they are equal here).
            merged["start_time_is_estimated"] = primary_estimated

        for field in (
            "title",
            "description",
            "venue_name",
            "raw_address",
            "image_url",
            "currency",
        ):
            merged[field] = self._prefer_richer_value(
                primary.get(field), secondary.get(field)
            )

        # Status only escalates: scheduled < postponed < cancelled < past.
        merged["status"] = max(
            primary.get("status", "scheduled"),
            secondary.get("status", "scheduled"),
            key=lambda value: self.STATUS_SEVERITY.get(value, 0),
        )

        source_winner = secondary if secondary_tier < primary_tier or authoritative_revision else primary
        for key in ("source_name", "source_event_id", "external_url"):
            merged[key] = source_winner.get(key)
        merged["source_tier"] = min(
            int(primary.get("source_tier", 99)),
            int(secondary.get("source_tier", 99)),
        )
        merged["categories"] = self._merge_lists(
            primary.get("categories", []), secondary.get("categories", [])
        )
        merged["tags"] = self._merge_lists(
            primary.get("tags", []), secondary.get("tags", [])
        )
        merged["price"] = self._prefer_price(
            primary.get("price"), secondary.get("price")
        )
        merged["organizer_name"] = self._prefer_richer_value(
            primary.get("organizer_name"), secondary.get("organizer_name")
        )
        merged["attendee_count"] = max(
            int(primary.get("attendee_count") or 0),
            int(secondary.get("attendee_count") or 0),
        )
        # location and location_confidence travel together: keeping one
        # payload's coordinate while taking the other's confidence would stamp
        # a high score onto a city-centroid guess and let it pass radius search.
        primary_confidence = self._coerce_confidence(primary.get("location_confidence"))
        secondary_confidence = self._coerce_confidence(secondary.get("location_confidence"))
        merged["location_confidence"] = max(primary_confidence, secondary_confidence)
        location_winner = secondary if secondary_confidence > primary_confidence else primary
        merged["location"] = location_winner["location"]
        merged["city"] = location_winner.get("city")
        merged["is_free"] = bool(primary.get("is_free")) or bool(
            secondary.get("is_free")
        )

        if authoritative_revision:
            # The newest observation replaces the previous observation of the
            # same authoritative listing. Missing data is not an erasure.
            for key in self.REVISION_FIELDS:
                if key in ("start_at", "end_at"):
                    continue
                if not self._is_missing(secondary.get(key)):
                    merged[key] = secondary[key]
            # An omitted hour on the same day cannot disprove a published
            # hour. A revised calendar date does replace the old schedule,
            # even if its new clock time is explicitly only an estimate.
            accepts_schedule = not (
                secondary_estimated and not primary_estimated
                and self._same_local_day(primary["start_at"], secondary["start_at"])
            )
            if accepts_schedule:
                schedule_changed = (
                    primary["start_at"] != secondary["start_at"]
                    or primary_estimated != secondary_estimated
                )
                merged["start_at"] = secondary["start_at"]
                merged["start_time_is_estimated"] = secondary_estimated
                if schedule_changed or secondary.get("end_at") is not None:
                    merged["end_at"] = secondary.get("end_at")
            if merged.get("end_at") is not None and merged["end_at"] < merged["start_at"]:
                merged["end_at"] = None
            venue_changed = any(
                not self._is_missing(secondary.get(key))
                and secondary.get(key) != primary.get(key)
                for key in ("venue_name", "raw_address")
            )
            if venue_changed or secondary_confidence >= primary_confidence:
                # A reliable coordinate at the previous venue says nothing
                # about the new venue. Keep the new uncertainty with its point.
                merged["location"] = secondary["location"]
                merged["location_confidence"] = secondary_confidence
                merged["city"] = secondary.get("city")
                merged["_coordinate_revision"] = secondary["location"] != primary["location"]
            if primary.get("status") == "past" and merged["start_at"] == primary["start_at"]:
                merged["status"] = "past"
            else:
                merged["_allow_status_reset"] = True

        if not authoritative_revision and not location_context_matches:
            for key in ("venue_name", "raw_address", "city", "location", "location_confidence"):
                merged[key] = primary.get(key)

        if secondary.get("_source_unchanged") and secondary_tier >= primary_tier:
            # An unchanged alias is old evidence, even if it was fetched last.
            # It cannot revert a newer revision from an equally trusted source.
            for key in (*self.REVISION_FIELDS, "source_name", "source_event_id", "source_tier", "start_time_is_estimated"):
                merged[key] = primary.get(key)
            merged.pop("_allow_status_reset", None)

        return merged

    def _normalize_event_payload(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(event, dict):
            return None
        title = event.get("title")
        start_at = self._coerce_datetime(event.get("start_at"))
        location = event.get("location")
        source_name = event.get("source_name")
        source_tier = event.get("source_tier")
        status = event.get("status", "scheduled")
        if not isinstance(title, str) or not title.strip():
            return None
        if start_at is None:
            return None
        if not isinstance(location, str) or not location.strip():
            return None
        if not isinstance(source_name, str) or not source_name.strip():
            return None
        if not isinstance(source_tier, int):
            return None
        if not isinstance(status, str) or not status.strip():
            return None

        return {
            "title": self._clamp(title.strip(), _MAX_TITLE),
            "description": self._normalize_str(event.get("description")),
            "start_at": start_at,
            "start_time_is_estimated": bool(event.get("start_time_is_estimated", False)),
            "end_at": self._coerce_datetime(event.get("end_at")),
            "source_name": self._clamp(source_name.strip(), _MAX_SOURCE_NAME),
            "source_tier": source_tier,
            "source_event_id": self._normalize_source_event_id(
                event.get("source_event_id")
            ),
            "external_url": self._clamp(
                self._normalize_str(event.get("external_url")), _MAX_URL
            ),
            "venue_name": self._clamp(
                self._normalize_str(event.get("venue_name")), _MAX_VENUE_NAME
            ),
            "raw_address": self._normalize_str(event.get("raw_address")),
            "city": self._normalize_str(event.get("city")),
            "location": location.strip(),
            "categories": infer_categories(
                title=title.strip(),
                description=self._normalize_str(event.get("description")),
                existing=self._normalize_list(event.get("categories")),
            ),
            "tags": canonical_vibe_tags(self._normalize_list(event.get("tags"))),
            "price": self._coerce_decimal(event.get("price")),
            "currency": self._normalize_currency(event.get("currency")),
            "image_url": self._clamp(self._normalize_str(event.get("image_url")), _MAX_URL),
            "status": self._clamp(status.strip().lower(), _MAX_STATUS),
            "organizer_name": self._clamp(
                self._normalize_str(event.get("organizer_name")), _MAX_ORGANIZER_NAME
            ),
            "attendee_count": self._coerce_int(event.get("attendee_count")),
            "location_confidence": self._coerce_confidence(
                event.get("location_confidence")
            ),
            "is_free": bool(event.get("is_free", False)),
        }

    def _event_to_payload(self, event: Event) -> dict[str, Any]:
        return {
            "title": event.title,
            "description": event.description,
            "start_at": self._coerce_datetime(event.start_at),
            "start_time_is_estimated": event.start_time_is_estimated,
            "end_at": self._coerce_datetime(event.end_at),
            "source_name": event.source_name,
            "source_tier": event.source_tier,
            "source_event_id": event.source_event_id,
            "external_url": event.external_url,
            "venue_name": event.venue_name,
            "raw_address": event.raw_address,
            "location": event.location,
            "categories": list(event.categories),
            "tags": canonical_vibe_tags(list(event.tags)),
            "price": event.price,
            "currency": event.currency,
            "image_url": event.image_url,
            "status": event.status,
            "organizer_name": event.organizer_name,
            "attendee_count": event.attendee_count,
            "location_confidence": event.location_confidence,
            "is_free": event.is_free,
        }

    def _apply_payload(self, *, existing: Event, payload: dict[str, Any]) -> None:
        existing.title = payload["title"]
        existing.description = payload.get("description")
        existing.start_at = payload["start_at"]
        existing.start_time_is_estimated = bool(
            payload.get("start_time_is_estimated", False)
        )
        existing.end_at = payload.get("end_at")
        existing.source_name = payload["source_name"]
        existing.source_tier = payload["source_tier"]
        existing.source_event_id = payload.get("source_event_id")
        existing.external_url = payload.get("external_url")
        existing.venue_name = payload.get("venue_name")
        existing.raw_address = payload.get("raw_address")
        existing.location = payload["location"]
        existing.categories = payload.get("categories", [])
        existing.tags = payload.get("tags", [])
        existing.price = payload.get("price")
        existing.currency = payload.get("currency")
        existing.image_url = payload.get("image_url")
        existing.organizer_name = payload.get("organizer_name")
        existing.attendee_count = payload.get("attendee_count") or 0
        existing.location_confidence = self._coerce_confidence(payload.get("location_confidence"))
        existing.is_free = bool(payload.get("is_free", False))
        # Status severity: scheduled < postponed < cancelled < past
        incoming_status = payload.get("status", "scheduled")
        current_severity = self.STATUS_SEVERITY.get(existing.status, 0)
        incoming_severity = self.STATUS_SEVERITY.get(incoming_status, 0)
        if payload.get("_allow_status_reset") or incoming_severity > current_severity:
            existing.status = incoming_status

    def _coerce_datetime(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                return None
        return None

    def _coerce_int(self, value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _coerce_confidence(self, value: Any) -> float:
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return 1.0

    def _coerce_decimal(self, value: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def _normalize_str(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    def _clamp(self, value: str | None, max_length: int) -> str | None:
        """Truncate a display string to its column width.

        Losing the tail of an over-long title or venue name is a cosmetic
        problem; letting it abort the transaction costs the whole cycle.
        """
        if value is None or len(value) <= max_length:
            return value
        logger.warning(
            "Truncating a %d-character value to %d for storage: %r",
            len(value),
            max_length,
            value[:80],
        )
        return value[:max_length]

    def _normalize_source_event_id(self, value: Any) -> str | None:
        """Clamp the source identifier without breaking its identity.

        Unlike display text, this field is used to recognise the same event on
        a later run, so a plain truncation is unsafe: two long URLs sharing a
        prefix would collapse into one id and the events would be treated as
        duplicates. Keep a readable prefix and append a digest of the full
        value, which stays stable across runs and unique per source id.
        """
        normalized = self._normalize_str(value)
        if normalized is None or len(normalized) <= _MAX_SOURCE_EVENT_ID:
            return normalized

        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
        prefix = normalized[: _MAX_SOURCE_EVENT_ID - len(digest) - 1]
        logger.warning(
            "source_event_id exceeded %d characters; storing prefix+digest for %r",
            _MAX_SOURCE_EVENT_ID,
            normalized[:80],
        )
        return f"{prefix}:{digest}"

    def _normalize_currency(self, value: Any) -> str | None:
        normalized = self._normalize_str(value)
        if normalized is None:
            return None
        return normalized.upper()[:3]

    def _normalize_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    def _merge_lists(self, left: list[str], right: list[str]) -> list[str]:
        merged: list[str] = []
        for item in [*left, *right]:
            if item and item not in merged:
                merged.append(item)
        return merged

    def _prefer_richer_value(self, left: Any, right: Any) -> Any:
        if self._is_missing(left) and not self._is_missing(right):
            return right
        if self._is_missing(right):
            return left
        if isinstance(left, str) and isinstance(right, str):
            return right if len(right.strip()) > len(left.strip()) else left
        return left

    def _pick_latest_datetime(
        self, left: datetime | None, right: datetime | None
    ) -> datetime | None:
        if left is None:
            return right
        if right is None:
            return left
        return max(left, right)

    def _prefer_price(
        self, left: Decimal | None, right: Decimal | None
    ) -> Decimal | None:
        if left is None:
            return right
        if right is None:
            return left
        return min(left, right)

    def _is_missing(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, list):
            return len(value) == 0
        return False
