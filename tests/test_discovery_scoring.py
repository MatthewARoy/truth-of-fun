from app.api.discovery import _score_event_for_user


def test_score_event_uses_explicit_preference_and_profile_weights() -> None:
    score, matched = _score_event_for_user(
        event_tags=["#Jazz", "#DateNight"],
        preferred_vibes={"#jazz"},
        profile_scores={"#jazz": 2.0, "#datenight": 1.0},
    )

    assert score > 100
    assert "#Jazz" in matched
    assert "#DateNight" in matched


def test_score_event_returns_zero_for_unmatched_event() -> None:
    score, matched = _score_event_for_user(
        event_tags=["#Techno"],
        preferred_vibes={"#jazz"},
        profile_scores={"#datenight": 3.0},
    )

    assert score == 0
    assert matched == []
