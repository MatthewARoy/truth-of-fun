from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.ingestion.base import BaseSource
from app.ingestion.contracts import CanonicalEvent

logger = logging.getLogger(__name__)


class InputAgentSource(BaseSource):
    """
    Reusable source pipeline for scrape/API/email agents.

    Subclasses implement candidate discovery + extraction while this base class
    centralizes canonical validation and conversion into the current event payload shape.
    """

    @abstractmethod
    async def discover_candidates(self, **kwargs: Any) -> list[Any]:
        """Return source-specific candidate units (URLs, IDs, text blocks)."""

    @abstractmethod
    async def extract_candidate(self, candidate: Any) -> dict[str, Any] | None:
        """Extract raw source attributes from a candidate."""

    @abstractmethod
    def normalize_raw(self, raw_item: dict[str, Any]) -> CanonicalEvent | None:
        """Map source raw item into canonical event model."""

    async def fetch_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.last_fetch_error = None
        self.last_empty_reason = None
        candidates = await self.discover_candidates(**kwargs)
        failure_types: dict[str, int] = {}
        canonical_events: list[CanonicalEvent] = []

        for candidate in candidates:
            try:
                raw_item = await self.extract_candidate(candidate)
                if raw_item is None:
                    continue
                event = self.normalize_raw(raw_item)
                if event is not None:
                    canonical_events.append(event)
            except Exception as exc:
                # Retain valid candidates, but never present a partial scrape as
                # a clean small/empty feed. Error types are safe to publish;
                # exception messages and candidate URLs can contain credentials.
                name = type(exc).__name__
                failure_types[name] = failure_types.get(name, 0) + 1

        if failure_types:
            failed = sum(failure_types.values())
            details = ", ".join(f"{name}={count}" for name, count in sorted(failure_types.items()))
            extraction_error = f"{failed} of {len(candidates)} candidates failed ({details})"
            self.last_fetch_error = "; ".join(
                reason for reason in (self.last_fetch_error, extraction_error) if reason
            )[:1000]
            logger.warning("Source %s partial extraction: %s", self.source_name, self.last_fetch_error)

        if not canonical_events:
            self.last_empty_reason = self.last_fetch_error or (
                f"No usable events from {len(candidates)} discovered candidates (extraction/validation rejected them)"
                if candidates else "Empty discovery result: no candidates returned"
            )
            logger.warning("Source %s yielded zero events: %s", self.source_name, self.last_empty_reason)

        return [
            event.to_legacy_event_payload(source_tier=self.source_tier)
            for event in canonical_events
        ]

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)
