"""
Recommendation scoring service.

Combines multiple signals to rank events for a user:
- Vibe match: how well event tags match user preferences (existing logic)
- Popularity: how many users have saved/clicked this event
- Freshness: recently added events get a boost
- Diversity: penalize showing too many events of the same category in a row
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.models.event import Event
from app.models.user import User


@dataclass
class ScoredEvent:
    event: Event
    total_score: float
    vibe_score: float
    popularity_score: float
    freshness_score: float
    matched_tags: list[str] = field(default_factory=list)


class RecommenderService:
    # Weights for each scoring component (must sum to 1.0).
    VIBE_WEIGHT = 0.50
    POPULARITY_WEIGHT = 0.25
    FRESHNESS_WEIGHT = 0.15
    DIVERSITY_WEIGHT = 0.10

    # Diversity penalty applied when consecutive events share a primary category.
    DIVERSITY_PENALTY = 10.0

    def score_events(
        self,
        *,
        events: list[Event],
        user: User,
        user_vibe_scores: dict[str, float],
        popularity_counts: dict[int, int],
    ) -> list[ScoredEvent]:
        """Score and rank a list of events for the given user.

        Returns a list of ``ScoredEvent`` sorted by total score descending,
        with diversity penalties applied during the final ranking pass.
        """
        preferred_vibes = set(
            v.lower() for v in (user.preferred_vibes or []) if isinstance(v, str)
        )
        now = datetime.now(timezone.utc)

        # Phase 1: compute per-event raw scores (no diversity yet).
        raw_scored: list[ScoredEvent] = []
        for event in events:
            vibe, matched = self._vibe_score(
                event_tags=[t for t in (event.tags or []) if isinstance(t, str)],
                preferred_vibes=preferred_vibes,
                profile_scores=user_vibe_scores,
            )
            pop = self._popularity_score(popularity_counts.get(int(event.id or 0), 0))
            fresh = self._freshness_score(event.created_at, now=now)

            # Pre-diversity total (diversity component starts at full marks).
            total = (
                vibe * self.VIBE_WEIGHT
                + pop * self.POPULARITY_WEIGHT
                + fresh * self.FRESHNESS_WEIGHT
                + 100.0 * self.DIVERSITY_WEIGHT
            )

            raw_scored.append(
                ScoredEvent(
                    event=event,
                    total_score=total,
                    vibe_score=vibe,
                    popularity_score=pop,
                    freshness_score=fresh,
                    matched_tags=matched,
                )
            )

        # Phase 2: sort by raw total then apply diversity penalty in-order.
        raw_scored.sort(key=lambda s: (-s.total_score, s.event.start_at))
        self._apply_diversity_penalty(raw_scored)

        # Re-sort after penalties.
        raw_scored.sort(key=lambda s: (-s.total_score, s.event.start_at))
        return raw_scored

    # ------------------------------------------------------------------
    # Component scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _vibe_score(
        *,
        event_tags: list[str],
        preferred_vibes: set[str],
        profile_scores: dict[str, float],
    ) -> tuple[float, list[str]]:
        """Compute vibe match score (0-100) and list of matched tags.

        Mirrors the logic from ``_score_event_for_user`` in discovery.py.
        """
        if not event_tags:
            return 0.0, []

        tag_map = {tag.lower(): tag for tag in event_tags}
        matched_keys = sorted(set(tag_map.keys()).intersection(preferred_vibes))
        weighted_score = sum(profile_scores.get(key, 0.0) for key in tag_map.keys())

        if not matched_keys and weighted_score <= 0:
            return 0.0, []

        matched = [tag_map[key] for key in matched_keys]
        for key in tag_map:
            if profile_scores.get(key, 0.0) > 0:
                original = tag_map[key]
                if original not in matched:
                    matched.append(original)

        # Raw score: explicit likes drive relevance, then decayed behavioural weight.
        raw = (len(matched_keys) * 100.0) + (weighted_score * 10.0)
        # Normalise into the 0-100 range.
        return min(raw, 100.0), matched

    @staticmethod
    def _popularity_score(interaction_count: int) -> float:
        """Popularity component (0-100). Caps at 10 interactions."""
        return min(interaction_count * 10.0, 100.0)

    @staticmethod
    def _freshness_score(created_at: datetime, *, now: datetime) -> float:
        """Freshness component (0-100) based on event creation time."""
        created_utc = (
            created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        )
        age = now - created_utc
        if age <= timedelta(hours=24):
            return 100.0
        if age <= timedelta(hours=48):
            return 75.0
        if age <= timedelta(days=7):
            return 50.0
        return 25.0

    def _apply_diversity_penalty(self, scored: list[ScoredEvent]) -> None:
        """Mutate *scored* in-place: penalise consecutive same-category events."""
        prev_category: str | None = None
        for item in scored:
            categories = item.event.categories or []
            primary = categories[0] if categories else None
            if primary is not None and primary == prev_category:
                item.total_score -= self.DIVERSITY_PENALTY
            prev_category = primary
