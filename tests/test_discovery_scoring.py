from app.services.recommender import RecommenderService


def _score(**kwargs):
    return RecommenderService._vibe_score(**kwargs)


def test_score_event_uses_explicit_preference_and_profile_weights() -> None:
    score, matched = _score(
        event_tags=["#Jazz", "#DateNight"],
        preferred_vibes={"#jazz"},
        profile_scores={"#jazz": 2.0, "#datenight": 1.0},
    )

    # An explicit like (100) plus profile weight (3.0 * 10) saturates the cap.
    assert score == 100.0
    assert "#Jazz" in matched
    assert "#DateNight" in matched


def test_score_event_returns_zero_for_unmatched_event() -> None:
    score, matched = _score(
        event_tags=["#Techno"],
        preferred_vibes={"#jazz"},
        profile_scores={"#datenight": 3.0},
    )

    assert score == 0
    assert matched == []


def test_score_event_matches_across_spelling_variants() -> None:
    """Stored tags arrive bare, hyphenated or CamelCase; all must match."""
    for stored in ("HighEnergy", "#high-energy", "high_energy", "#highenergy"):
        score, matched = _score(
            event_tags=[stored],
            preferred_vibes=set(),
            profile_scores={"#highenergy": 4.0},
        )

        assert score > 0, f"{stored!r} failed to match #highenergy"
        assert matched == [stored]
