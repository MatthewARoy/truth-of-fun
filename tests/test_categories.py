from app.services.categories import (
    FITNESS,
    OUTDOORS,
    WELLNESS,
    canonical_category,
    infer_categories,
    query_targets_fitness,
)


def test_infer_adds_fitness_for_gym_promo() -> None:
    categories = infer_categories(
        title="New Year gym promo — first month free",
        description="Sign up this week and get a free workout with a personal training session.",
    )
    assert FITNESS in categories


def test_infer_is_additive_and_preserves_source_categories() -> None:
    categories = infer_categories(
        title="Sunset Yoga at the studio",
        description="All-levels vinyasa flow.",
        existing=["Wellness"],
    )
    # Source category kept, Fitness appended (yoga is an active offering).
    assert categories[0] == "Wellness"
    assert FITNESS in categories


def test_infer_does_not_duplicate_existing_category() -> None:
    categories = infer_categories(
        title="Bouldering night",
        description="Intro climbing session.",
        existing=["Fitness"],
    )
    assert categories.count(FITNESS) == 1


def test_infer_leaves_spectator_sports_alone() -> None:
    # A basketball game is spectator Sports, not participatory Fitness.
    categories = infer_categories(
        title="Warriors vs. Lakers",
        description="Pacific Division rivalry game. Doors open 90 min before tip-off.",
        existing=["Sports"],
    )
    assert categories == ["Sports"]


def test_infer_climbing_and_run_club() -> None:
    assert FITNESS in infer_categories(title="Dogpatch Boulders intro to climbing")
    assert FITNESS in infer_categories(title="Saturday morning run club — free 5k")


def test_infer_outdoors_and_wellness_keywords() -> None:
    assert OUTDOORS in infer_categories(title="Sunrise hiking meetup at the trailhead")
    assert WELLNESS in infer_categories(
        title="Evening sound bath", description="A restorative sound bath and meditation."
    )


def test_canonical_category_resolves_synonyms() -> None:
    assert canonical_category("gym") == FITNESS
    assert canonical_category("Workout") == FITNESS
    assert canonical_category("yoga") == FITNESS
    assert canonical_category("Fitness") == FITNESS
    assert canonical_category("music") == "Music"


def test_canonical_category_unknown_returns_none() -> None:
    assert canonical_category("underwater basket weaving") is None
    assert canonical_category("") is None
    assert canonical_category(None) is None


def test_query_targets_fitness() -> None:
    assert query_targets_fitness("gym/workout promos near noe downtown in sf") is True
    assert query_targets_fitness("find me a yoga class this weekend") is True
    assert query_targets_fitness("date night in the mission") is False
