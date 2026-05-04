from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Protocol

from sqlmodel import Session, select

from app.models.event import Event
from app.models.user_signal import UserSignal


class OnboardingTagExtractor(Protocol):
    async def extract_vibe_tags(self, text: str) -> list[str]:
        """Extract user vibe tags from onboarding free text."""


class HeuristicOnboardingTagExtractor:
    """Fallback extractor that converts text phrases into simple vibe tags."""

    async def extract_vibe_tags(self, text: str) -> list[str]:
        words = re.findall(r"[A-Za-z][A-Za-z0-9']+", text or "")
        if not words:
            return []

        candidates: list[str] = []
        for idx, word in enumerate(words):
            lower = word.lower()
            if len(lower) < 4:
                continue
            if lower in {"with", "from", "that", "this", "there", "about", "would"}:
                continue

            normalized = "#" + re.sub(r"[^A-Za-z0-9]", "", word.title())
            if len(normalized) <= 2:
                continue
            if normalized not in candidates:
                candidates.append(normalized)

            if idx + 1 < len(words):
                pair = f"{word} {words[idx + 1]}"
                pair_tag = "#" + re.sub(r"[^A-Za-z0-9]", "", pair.title().replace(" ", ""))
                if pair_tag not in candidates and len(pair_tag) > 3:
                    candidates.append(pair_tag)

            if len(candidates) >= 5:
                break

        return candidates[:5]


class UserProfileService:
    SIGNAL_WEIGHTS: dict[str, float] = {
        "click": 1.0,
        "save": 5.0,
        "external_ticket_click": 10.0,
        "onboarding": 6.0,
        "like": 4.0,
    }
    HALF_LIFE_DAYS = 30.0

    def __init__(self, *, onboarding_extractor: OnboardingTagExtractor | None = None) -> None:
        self._onboarding_extractor = onboarding_extractor or HeuristicOnboardingTagExtractor()

    def signal_weight(self, signal_type: str) -> float:
        return self.SIGNAL_WEIGHTS.get(signal_type, 0.0)

    def decay_multiplier(self, *, created_at: datetime, now: datetime | None = None) -> float:
        if now is None:
            now = datetime.now(timezone.utc)
        created_utc = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        age_days = max((now - created_utc).total_seconds(), 0.0) / 86400.0
        return math.pow(0.5, age_days / self.HALF_LIFE_DAYS)

    async def extract_onboarding_tags(self, text: str) -> list[str]:
        tags = await self._onboarding_extractor.extract_vibe_tags(text)
        return self._normalize_tags(tags)

    def compute_vibe_scores_for_user(
        self,
        *,
        session: Session,
        user_id: int,
        now: datetime | None = None,
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        signals = session.exec(select(UserSignal).where(UserSignal.user_id == user_id)).all()
        for signal in signals:
            contribution = float(signal.weight) * self.decay_multiplier(
                created_at=signal.created_at,
                now=now,
            )
            if contribution <= 0:
                continue

            tags: list[str] = []
            if signal.vibe_tag:
                tags = [signal.vibe_tag]
            elif signal.event_id:
                event = session.get(Event, signal.event_id)
                if event is not None:
                    tags = list(event.tags or [])

            for tag in self._normalize_tags(tags):
                key = tag.lower()
                scores[key] = scores.get(key, 0.0) + contribution
        return scores

    def record_signal(
        self,
        *,
        session: Session,
        user_id: int,
        signal_type: str,
        event_id: int | None = None,
        vibe_tag: str | None = None,
    ) -> UserSignal | None:
        weight = self.signal_weight(signal_type)
        if weight <= 0:
            return None
        normalized_tag = self._normalize_tags([vibe_tag] if vibe_tag else [])
        signal = UserSignal(
            user_id=user_id,
            event_id=event_id,
            signal_type=signal_type,
            vibe_tag=normalized_tag[0] if normalized_tag else None,
            weight=weight,
        )
        session.add(signal)
        return signal

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        normalized: list[str] = []
        for tag in tags:
            if not isinstance(tag, str):
                continue
            cleaned = tag.strip()
            if not cleaned:
                continue
            if not cleaned.startswith("#"):
                cleaned = f"#{cleaned}"
            cleaned = "#" + re.sub(r"\s+", "", cleaned[1:])
            if len(cleaned) <= 1:
                continue
            if cleaned not in normalized:
                normalized.append(cleaned)
        return normalized
