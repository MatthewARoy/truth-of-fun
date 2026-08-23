"""
Canonical vibe-tag vocabulary.

Tags arrive from many places -- source adapters, the LLM vibe tagger, user
onboarding text -- each with its own spelling conventions. Ranking matches tags
exactly, so ``#live-music`` and ``#LiveMusic`` silently fail to match
``#livemusic`` and the vibe signal collapses to zero.

Every producer and consumer of a vibe tag goes through :func:`canonical_tag`, so
there is one spelling of each concept. Write paths additionally pass through
:func:`canonical_vibe_tags`, which drops anything outside the controlled
vocabulary -- performer names, ticket types and venue policies are not vibes and
only dilute the tag space.
"""

from __future__ import annotations

import re

# Everything that separates words collapses, so hyphenation and casing choices
# upstream cannot fork one concept into several non-matching tags.
_SEPARATORS = re.compile(r"[\s\-_./]+")
_DISALLOWED = re.compile(r"[^a-z0-9+]")


def canonical_tag(tag: str | None) -> str | None:
    """Return *tag* in canonical ``#lowercasenospaces`` form, or ``None``.

    ``None`` means the input carried no tag at all (empty, punctuation-only, or
    not a string). Callers filter those out rather than storing them.
    """
    if not isinstance(tag, str):
        return None

    cleaned = _SEPARATORS.sub("", tag.strip().lstrip("#").lower())
    cleaned = _DISALLOWED.sub("", cleaned)
    return f"#{cleaned}" if cleaned else None


# The closed set of vibes the product ranks on. Every tag weighted in
# ``_INTENT_VIBE_PROFILES`` MUST appear here -- a profile weighting a tag outside
# this set can never match a stored event. ``test_vibe_tags.py`` enforces that.
VIBE_VOCABULARY: frozenset[str] = frozenset(
    {
        # Mood / energy
        "#chill",
        "#highenergy",
        "#intimate",
        "#social",
        "#quirky",
        # Occasion
        "#date",
        "#nightout",
        "#nightlife",
        "#latenight",
        "#familyfriendly",
        "#festival",
        "#free",
        # Form
        "#livemusic",
        "#comedy",
        "#film",
        "#art",
        "#theatre",
        "#dance",
        "#workshop",
        "#market",
        "#sports",
        "#outdoors",
        "#wellness",
        "#intellectual",
        "#foodanddrink",
        # Genre
        "#jazz",
        "#classical",
        "#electronic",
        "#hiphop",
        "#rock",
        "#country",
    }
)


# Spellings that mean an existing vocabulary tag. Only unambiguous aliases and
# morphological variants belong here -- mapping a genuinely broader term (a
# circus is "live entertainment", not live music) would mislabel events.
# Counts below are live-corpus matches as of 2026-08-23.
_SYNONYMS: dict[str, str] = {
    # Comedy (159 events)
    "#standup": "#comedy",
    "#standupcomedy": "#comedy",
    "#comedyclub": "#comedy",
    # Music
    "#concert": "#livemusic",
    "#smoothjazz": "#jazz",
    # Mood -- the only existing content for date_night's "#chill"
    "#relaxed": "#chill",
    "#laidback": "#chill",
    "#mellow": "#chill",
    "#energetic": "#highenergy",
    # Occasion. The LLM naturally emits "datenight" for "#date".
    "#datenight": "#date",
    "#romantic": "#date",
    "#romance": "#date",
    "#familyfun": "#familyfriendly",
    "#freeevent": "#free",
    "#nightclub": "#nightlife",
    # Form
    "#outdoor": "#outdoors",
    "#arts": "#art",
    "#theater": "#theatre",
    "#theatershow": "#theatre",
    "#dancing": "#dance",
    "#cinema": "#film",
    "#movie": "#film",
    "#movies": "#film",
    "#foodie": "#foodanddrink",
    "#food": "#foodanddrink",
    "#drinks": "#foodanddrink",
    "#yoga": "#wellness",
    "#meditation": "#wellness",
    "#marketplace": "#market",
}


def resolve_vibe_tag(tag: str | None) -> str | None:
    """Canonicalize *tag* and fold known aliases onto their vocabulary entry.

    Kept separate from :func:`canonical_tag` because this step is semantic:
    the backfill rewrites tag *form* only and must not relabel events.
    """
    canonical = canonical_tag(tag)
    if canonical is None:
        return None
    return _SYNONYMS.get(canonical, canonical)


def canonical_vibe_tags(tags: object) -> list[str]:
    """Canonicalize *tags* and keep only recognised vibes, order preserved."""
    if not isinstance(tags, list):
        return []

    kept: list[str] = []
    for tag in tags:
        canonical = resolve_vibe_tag(tag)
        if canonical is None or canonical not in VIBE_VOCABULARY:
            continue
        if canonical not in kept:
            kept.append(canonical)
    return kept


def stored_forms_for(vibe_tag: str) -> list[str]:
    """Every canonical spelling that resolves to *vibe_tag*, prefix stripped.

    The recommender folds aliases in Python, but the query filter matches in
    SQL. Without this, ``?vibe_tag=comedy`` would miss the events stored as
    ``#standup`` that the recommender counts as comedy.
    """
    resolved = resolve_vibe_tag(vibe_tag)
    if resolved is None:
        return []

    forms = {resolved}
    forms.update(alias for alias, target in _SYNONYMS.items() if target == resolved)
    return sorted(form.lstrip("#") for form in forms)
