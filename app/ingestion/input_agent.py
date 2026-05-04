from __future__ import annotations

from abc import abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.ingestion.base import BaseSource
from app.ingestion.contracts import CanonicalEvent


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
        candidates = await self.discover_candidates(**kwargs)
        canonical_events: list[CanonicalEvent] = []

        for candidate in candidates:
            try:
                raw_item = await self.extract_candidate(candidate)
                if raw_item is None:
                    continue
                event = self.normalize_raw(raw_item)
                if event is not None:
                    canonical_events.append(event)
            except ValidationError:
                continue
            except Exception:
                continue

        return [
            event.to_legacy_event_payload(source_tier=self.source_tier)
            for event in canonical_events
        ]

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)
