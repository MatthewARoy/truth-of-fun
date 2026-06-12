from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from Levenshtein import ratio as levenshtein_ratio
from sqlmodel import Session, select

from app.models.event import Event
from app.services.vibe_tagger import ClaudeVibeTagger, VibeTagger


class DataPipelineService:
    """Process raw ingested events with dedupe, LLM tagging, and conditional upserts."""

    DEDUPE_WINDOW_HOURS = 2
    DEDUPE_TITLE_SIMILARITY_THRESHOLD = 85.0

    def __init__(self, *, vibe_tagger: VibeTagger | None = None) -> None:
        self._vibe_tagger = vibe_tagger or ClaudeVibeTagger()

    async def process_raw_events(
        self,
        *,
        session: Session,
        raw_events: list[dict[str, Any]],
    ) -> dict[str, int]:
        deduped_events = self.deduplicate_events(raw_events)

        inserted = 0
        updated = 0
        skipped = 0

        for event_payload in deduped_events:
            llm_tags = await self._vibe_tagger.generate_vibe_tags(event_payload.get("description"))
            event_payload["tags"] = self._merge_lists(event_payload.get("tags", []), llm_tags)

            existing = self._find_existing_event(session=session, incoming_event=event_payload)
            if existing is None:
                session.add(Event(**event_payload))
                inserted += 1
                continue

            if self.has_significant_new_information(existing_event=existing, incoming_event=event_payload):
                merged_for_update = self._merge_event_payloads(
                    primary=self._event_to_payload(existing),
                    secondary=event_payload,
                )
                self._apply_payload(existing=existing, payload=merged_for_update)
                updated += 1
            else:
                skipped += 1

        session.commit()
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "deduped_count": len(deduped_events),
        }

    def deduplicate_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        for raw_event in events:
            normalized = self._normalize_event_payload(raw_event)
            if normalized is None:
                continue

            duplicate_index = next(
                (i for i, existing in enumerate(deduped) if self._is_duplicate(existing, normalized)),
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
        start_at = incoming_event["start_at"]
        window = timedelta(hours=self.DEDUPE_WINDOW_HOURS)
        stmt = select(Event).where(
            Event.start_at >= (start_at - window),
            Event.start_at <= (start_at + window),
        )
        candidates = session.exec(stmt).all()
        if not candidates:
            return None

        scored = [
            (candidate, self._title_similarity(candidate.title, incoming_event["title"]))
            for candidate in candidates
        ]
        viable = [item for item in scored if item[1] > self.DEDUPE_TITLE_SIMILARITY_THRESHOLD]
        if not viable:
            return None
        return max(viable, key=lambda item: item[1])[0]

    def has_significant_new_information(
        self,
        *,
        existing_event: Event,
        incoming_event: dict[str, Any],
    ) -> bool:
        existing_payload = self._event_to_payload(existing_event)

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
            if self._is_missing(existing_payload.get(key)) and not self._is_missing(incoming_event.get(key)):
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
        if isinstance(existing_description, str) and isinstance(incoming_description, str):
            similarity = self._text_similarity(existing_description, incoming_description)
            if len(incoming_description.strip()) > len(existing_description.strip()) + 30 and similarity < 95:
                return True

        if existing_payload.get("start_at") and incoming_event.get("start_at"):
            delta = abs((incoming_event["start_at"] - existing_payload["start_at"]).total_seconds())
            if delta > 30 * 60:
                return True

        return False

    def _is_duplicate(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        start_at_left = left["start_at"]
        start_at_right = right["start_at"]
        start_delta_hours = abs((start_at_left - start_at_right).total_seconds()) / 3600
        if start_delta_hours > self.DEDUPE_WINDOW_HOURS:
            return False
        title_similarity = self._title_similarity(left["title"], right["title"])
        return title_similarity > self.DEDUPE_TITLE_SIMILARITY_THRESHOLD

    def _title_similarity(self, left_title: str, right_title: str) -> float:
        return self._text_similarity(left_title, right_title)

    def _text_similarity(self, left_text: str, right_text: str) -> float:
        left = (left_text or "").strip().lower()
        right = (right_text or "").strip().lower()
        if not left or not right:
            return 0.0
        return levenshtein_ratio(left, right) * 100

    STATUS_SEVERITY = {"scheduled": 0, "postponed": 1, "cancelled": 2, "past": 3}

    def _merge_event_payloads(
        self, *, primary: dict[str, Any], secondary: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(primary)

        # Trust hierarchy: a more authoritative (lower-tier) source owns the
        # times. Between equal tiers, keep the earliest start and latest end.
        primary_tier = int(primary.get("source_tier", 99))
        secondary_tier = int(secondary.get("source_tier", 99))
        if primary_tier < secondary_tier:
            merged["start_at"] = primary["start_at"]
            merged["end_at"] = primary.get("end_at") or secondary.get("end_at")
        elif secondary_tier < primary_tier:
            merged["start_at"] = secondary["start_at"]
            merged["end_at"] = secondary.get("end_at") or primary.get("end_at")
        else:
            merged["start_at"] = min(primary["start_at"], secondary["start_at"])
            merged["end_at"] = self._pick_latest_datetime(
                primary.get("end_at"), secondary.get("end_at")
            )

        for field in (
            "title",
            "description",
            "external_url",
            "venue_name",
            "raw_address",
            "image_url",
            "location",
            "source_event_id",
            "currency",
        ):
            merged[field] = self._prefer_richer_value(primary.get(field), secondary.get(field))

        # Status only escalates: scheduled < postponed < cancelled < past.
        merged["status"] = max(
            primary.get("status", "scheduled"),
            secondary.get("status", "scheduled"),
            key=lambda value: self.STATUS_SEVERITY.get(value, 0),
        )

        merged["source_name"] = self._prefer_richer_value(
            primary.get("source_name"), secondary.get("source_name")
        )
        merged["source_tier"] = min(
            int(primary.get("source_tier", 99)),
            int(secondary.get("source_tier", 99)),
        )
        merged["categories"] = self._merge_lists(primary.get("categories", []), secondary.get("categories", []))
        merged["tags"] = self._merge_lists(primary.get("tags", []), secondary.get("tags", []))
        merged["price"] = self._prefer_price(primary.get("price"), secondary.get("price"))
        merged["organizer_name"] = self._prefer_richer_value(
            primary.get("organizer_name"), secondary.get("organizer_name")
        )
        merged["attendee_count"] = max(
            int(primary.get("attendee_count") or 0),
            int(secondary.get("attendee_count") or 0),
        )
        merged["location_confidence"] = max(
            float(primary.get("location_confidence") or 1.0),
            float(secondary.get("location_confidence") or 1.0),
        )
        merged["is_free"] = bool(primary.get("is_free")) or bool(secondary.get("is_free"))

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
            "title": title.strip(),
            "description": self._normalize_str(event.get("description")),
            "start_at": start_at,
            "end_at": self._coerce_datetime(event.get("end_at")),
            "source_name": source_name.strip(),
            "source_tier": source_tier,
            "source_event_id": self._normalize_str(event.get("source_event_id")),
            "external_url": self._normalize_str(event.get("external_url")),
            "venue_name": self._normalize_str(event.get("venue_name")),
            "raw_address": self._normalize_str(event.get("raw_address")),
            "location": location.strip(),
            "categories": self._normalize_list(event.get("categories")),
            "tags": self._normalize_list(event.get("tags")),
            "price": self._coerce_decimal(event.get("price")),
            "currency": self._normalize_currency(event.get("currency")),
            "image_url": self._normalize_str(event.get("image_url")),
            "status": status.strip().lower(),
            "organizer_name": self._normalize_str(event.get("organizer_name")),
            "attendee_count": self._coerce_int(event.get("attendee_count")),
            "location_confidence": self._coerce_confidence(event.get("location_confidence")),
            "is_free": bool(event.get("is_free", False)),
        }

    def _event_to_payload(self, event: Event) -> dict[str, Any]:
        return {
            "title": event.title,
            "description": event.description,
            "start_at": event.start_at,
            "end_at": event.end_at,
            "source_name": event.source_name,
            "source_tier": event.source_tier,
            "source_event_id": event.source_event_id,
            "external_url": event.external_url,
            "venue_name": event.venue_name,
            "raw_address": event.raw_address,
            "location": event.location,
            "categories": list(event.categories),
            "tags": list(event.tags),
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
        existing.location_confidence = payload.get("location_confidence") or 1.0
        existing.is_free = bool(payload.get("is_free", False))
        # Status severity: scheduled < postponed < cancelled < past
        incoming_status = payload.get("status", "scheduled")
        current_severity = self.STATUS_SEVERITY.get(existing.status, 0)
        incoming_severity = self.STATUS_SEVERITY.get(incoming_status, 0)
        if incoming_severity > current_severity:
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

    def _prefer_price(self, left: Decimal | None, right: Decimal | None) -> Decimal | None:
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
