"""Contract tests for the canonical vibe-tag vocabulary.

These guard the failure that motivated the vocabulary: five of the six tags
weighted in ``date_night`` matched zero events, so the vibe signal -- 50% of the
recommender score -- resolved to ~0 for every candidate.

Live-corpus coverage is deliberately *not* asserted here. The suite has no
populated database, so such a test would silently skip -- which is how the
original breakage went unnoticed. Use ``scripts/audit_vibe_coverage.py``.
"""

from __future__ import annotations

import pytest

from app.services.concierge import _INTENT_VIBE_PROFILES, intent_vibe_profile
from app.services.data_pipeline import DataPipelineService
from app.services.recommender import RecommenderService
from app.services.tags import VIBE_VOCABULARY, canonical_tag, canonical_vibe_tags


@pytest.mark.parametrize("intent", sorted(_INTENT_VIBE_PROFILES))
def test_every_profile_tag_is_in_the_vocabulary(intent: str) -> None:
    """A profile weighting an unknown tag can never match a stored event."""
    unknown = sorted(set(intent_vibe_profile(intent)) - VIBE_VOCABULARY)
    assert not unknown, f"{intent} weights tags outside VIBE_VOCABULARY: {unknown}"


@pytest.mark.parametrize("tag", sorted(VIBE_VOCABULARY))
def test_vocabulary_tags_are_canonical(tag: str) -> None:
    """Vocabulary entries must be fixed points, or matching is asymmetric."""
    assert canonical_tag(tag) == tag


@pytest.mark.parametrize(
    "variant",
    ["#livemusic", "#live-music", "live_music", "LiveMusic", "  Live Music  ", "#LIVEMUSIC"],
)
def test_spelling_variants_collapse_to_one_key(variant: str) -> None:
    assert canonical_tag(variant) == "#livemusic"


@pytest.mark.parametrize("junk", ["", "   ", "#", "###", None, 42])
def test_untaggable_input_is_dropped(junk: object) -> None:
    assert canonical_tag(junk) is None  # type: ignore[arg-type]


def test_non_vibe_metadata_is_filtered_out() -> None:
    """Performer names and ticket types are not vibes and must not be stored."""
    kept = canonical_vibe_tags(
        [
            "HighEnergy",
            "San Francisco Giants",
            "#GeneralAdmission",
            "#drink-minimum",
            "#live-music",
            "#refund",
        ]
    )
    assert kept == ["#highenergy", "#livemusic"]


def test_stored_camelcase_tag_scores_against_intent_profile() -> None:
    """``HighEnergy`` is the corpus's single most common tag; it must score."""
    score, matched = RecommenderService._vibe_score(
        event_tags=["HighEnergy"],
        preferred_vibes=set(),
        profile_scores=intent_vibe_profile("general_night_out"),
    )

    assert score > 0
    assert matched == ["HighEnergy"]


def test_hyphenated_variant_scores_identically_to_bare_form() -> None:
    profile = intent_vibe_profile("date_night")
    scores = {
        variant: RecommenderService._vibe_score(
            event_tags=[variant], preferred_vibes=set(), profile_scores=profile
        )[0]
        for variant in ("#livemusic", "#live-music", "LiveMusic")
    }

    assert len(set(scores.values())) == 1, scores
    assert all(value > 0 for value in scores.values())


def test_pipeline_drops_non_vibe_tags_at_write() -> None:
    payload = DataPipelineService()._normalize_event_payload(
        {
            "title": "Show",
            "start_at": "2026-09-01T20:00:00+00:00",
            "source_name": "ticketmaster",
            "source_tier": 1,
            "location": "San Francisco",
            "status": "scheduled",
            "tags": ["Alex Ramon", "#ClubAccess", "#High-Energy"],
        }
    )

    assert payload is not None
    assert payload["tags"] == ["#highenergy"]
