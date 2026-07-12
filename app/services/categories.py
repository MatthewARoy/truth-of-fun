"""Canonical activity-category taxonomy and inference.

Truth of Fun started life around nightlife and entertainment — music, comedy,
film, and *spectator* sports (a Warriors game). Users increasingly want the
feed to also surface *active* offerings they can participate in: gym and
workout-class promos, climbing, yoga, run clubs, rec-league sports. Those
arrive from scrapers and calendars either untagged or tagged with wildly
inconsistent strings, so this module gives the rest of the app one place to:

* enumerate a canonical, ordered top-level category vocabulary;
* infer top-level categories from free-text titles/descriptions, so an
  untagged "New Year gym promo — first month free" still lands in ``Fitness``;
* resolve a user-supplied filter term ("gym", "workout") back to a canonical
  category for querying.

Inference is deliberately *additive*: it never rewrites or drops the
source-provided category strings (which often carry useful genre detail like
"Rock" or "Basketball") — it only appends canonical buckets that are missing.
"""

from __future__ import annotations

from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Canonical vocabulary
# ---------------------------------------------------------------------------

MUSIC = "Music"
NIGHTLIFE = "Nightlife"
COMEDY = "Comedy"
ARTS = "Arts & Theatre"
FILM = "Film"
FESTIVAL = "Festival"
FOOD = "Food"
SPORTS = "Sports"  # spectator sports (watching a game)
FITNESS = "Fitness"  # participatory / active (gym, workout classes, climbing…)
WELLNESS = "Wellness"  # restorative (meditation, spa, sound baths)
OUTDOORS = "Outdoors"
SOCIAL = "Social"
BUSINESS = "Business"
MISCELLANEOUS = "Miscellaneous"

#: Ordered vocabulary used for UI filter chips and validation.
CANONICAL_CATEGORIES: list[str] = [
    MUSIC,
    NIGHTLIFE,
    COMEDY,
    ARTS,
    FILM,
    FESTIVAL,
    FOOD,
    SPORTS,
    FITNESS,
    WELLNESS,
    OUTDOORS,
    SOCIAL,
    BUSINESS,
    MISCELLANEOUS,
]

# ---------------------------------------------------------------------------
# Keyword inference
# ---------------------------------------------------------------------------

# Ordered (keywords, canonical_category) rules. A rule fires when any of its
# keyword substrings appears in the lowercased haystack (title + description +
# existing category/tag strings). Keep phrases specific enough to avoid
# swallowing spectator events: "boxing class" (Fitness) but not "boxing"
# (a bout is Sports); "run club" but not the bare word "run".
_KEYWORD_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        (
            "gym",
            "workout",
            "work out",
            "fitness class",
            "fitness studio",
            "group fitness",
            "bootcamp",
            "boot camp",
            "crossfit",
            "hiit",
            "spin class",
            "spinning class",
            "cycling class",
            "indoor cycling",
            "pilates",
            "yoga",
            "vinyasa",
            "barre",
            "climbing",
            "bouldering",
            "rock climb",
            "run club",
            "running club",
            "5k",
            "10k",
            "half marathon",
            "marathon training",
            "martial arts",
            "jiu-jitsu",
            "jiu jitsu",
            "bjj",
            "kickboxing",
            "kickbox",
            "muay thai",
            "boxing class",
            "pickleball",
            "rec league",
            "rec sports",
            "open gym",
            "personal training",
            "strength training",
            "calisthenics",
            "rowing class",
        ),
        FITNESS,
    ),
    (
        (
            "meditation",
            "sound bath",
            "breathwork",
            "spa ",
            "sauna",
            "reiki",
            "restorative",
        ),
        WELLNESS,
    ),
    (
        (
            "hike",
            "hiking",
            "trailhead",
            "kayak",
            "paddleboard",
            "stand-up paddle",
            "surf lesson",
            "camping",
        ),
        OUTDOORS,
    ),
]

# Terms a natural-language query might use to ask for active / fitness offers.
FITNESS_QUERY_KEYWORDS: tuple[str, ...] = (
    "gym",
    "workout",
    "work out",
    "fitness",
    "exercise",
    "bootcamp",
    "boot camp",
    "crossfit",
    "hiit",
    "spin class",
    "pilates",
    "yoga",
    "barre",
    "climbing",
    "bouldering",
    "run club",
    "running club",
    "martial arts",
    "kickboxing",
    "pickleball",
    "personal training",
    "strength training",
)

# Synonyms mapping a user-supplied filter term onto a canonical category.
_SYNONYMS: dict[str, str] = {
    "gym": FITNESS,
    "gyms": FITNESS,
    "workout": FITNESS,
    "workouts": FITNESS,
    "work out": FITNESS,
    "fitness": FITNESS,
    "exercise": FITNESS,
    "climbing": FITNESS,
    "bouldering": FITNESS,
    "yoga": FITNESS,
    "pilates": FITNESS,
    "bootcamp": FITNESS,
    "crossfit": FITNESS,
    "active": FITNESS,
    "wellness": WELLNESS,
    "meditation": WELLNESS,
    "outdoors": OUTDOORS,
    "outdoor": OUTDOORS,
    "hiking": OUTDOORS,
    "music": MUSIC,
    "concert": MUSIC,
    "concerts": MUSIC,
    "nightlife": NIGHTLIFE,
    "comedy": COMEDY,
    "film": FILM,
    "movies": FILM,
    "food": FOOD,
    "sports": SPORTS,
    "social": SOCIAL,
    "business": BUSINESS,
    "networking": BUSINESS,
}


def _clean_existing(existing: Iterable[str]) -> tuple[list[str], set[str]]:
    result: list[str] = []
    seen_lower: set[str] = set()
    for item in existing:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        lower = cleaned.lower()
        if lower in seen_lower:
            continue
        result.append(cleaned)
        seen_lower.add(lower)
    return result, seen_lower


def infer_categories(
    *,
    title: str | None = None,
    description: str | None = None,
    existing: Iterable[str] = (),
) -> list[str]:
    """Return the event's categories, appending inferred canonical buckets.

    The source-provided ``existing`` categories are preserved (deduped,
    order-stable, whitespace-trimmed). Canonical categories implied by keywords
    in the title/description/existing strings are appended only when not
    already present (case-insensitively).
    """
    result, seen_lower = _clean_existing(existing)

    haystack_parts = [title or "", description or "", *result]
    haystack = " ".join(part.lower() for part in haystack_parts if part)

    for keywords, category in _KEYWORD_CATEGORY_RULES:
        if category.lower() in seen_lower:
            continue
        if any(keyword in haystack for keyword in keywords):
            result.append(category)
            seen_lower.add(category.lower())

    return result


def canonical_category(value: str | None) -> str | None:
    """Resolve a user-supplied filter term to a canonical category, or None."""
    if not value or not value.strip():
        return None
    key = value.strip().lower()
    if key in _SYNONYMS:
        return _SYNONYMS[key]
    for category in CANONICAL_CATEGORIES:
        if category.lower() == key:
            return category
    return None


def query_targets_fitness(text: str | None) -> bool:
    """True when a natural-language query is asking for active/fitness offers."""
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in FITNESS_QUERY_KEYWORDS)
