"""Frozen source-category mapping used by migration 007. Add v2 rather than edit."""
from __future__ import annotations

CANONICAL = ("Music", "Nightlife", "Comedy", "Arts & Theatre", "Film", "Festival", "Food", "Sports", "Fitness", "Wellness", "Outdoors", "Social", "Business", "Miscellaneous")
_GROUPS = {
    "Music": "rock|alternative|alternative rock|pop|jazz|r&b|rnb|hip-hop|hip hop|hip-hop/rap|rap|country|folk|reggae|reggaeton|metal|classical|blues|electronic|dance/electronic|house|progressive house|tech house|deep house|techno|trance|disco|afrobeats|drum and bass|dubstep|ambient|dj|latin|world|soul|funk|indie|punk|concert|concerts|live music",
    "Arts & Theatre": "arts|art|theatre|theater|musical|ballet|dance|performance art|gallery|exhibition|exhibitions|reception|opening reception|circus|circus & specialty acts",
    "Sports": "baseball|basketball|football|hockey|soccer|tennis|golf|wrestling|boxing",
    "Film": "movie|movies|cinema|screening",
    "Social": "community|meetup",
    "Business": "tech|startup|networking|conference",
    "Festival": "fair|street fair|festival|fairs & festivals",
}
ALIASES = {word: category for category, words in _GROUPS.items() for word in words.split("|")}
ALIASES.update({value.lower(): value for value in CANONICAL})
_MUSIC_GENRES = set(_GROUPS["Music"].split("|")) - {"concert", "concerts", "live music"}
_LEGACY_GENRES = _MUSIC_GENRES | {"baseball", "basketball", "football", "hockey", "soccer", "tennis", "golf", "wrestling", "boxing", "musical", "ballet", "dance", "circus", "circus & specialty acts", "fairs & festivals", "family"}


def categories_v1(values) -> list[str]:
    """Only known buckets; age, cost, Undefined and unknown labels are absent."""
    return list(dict.fromkeys(ALIASES[v.strip().lower()] for v in (values or [])
        if isinstance(v, str) and v.strip().lower() in ALIASES))


def legacy_genres_v1(values) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in (values or [])
        if isinstance(v, str) and v.strip().lower() in _LEGACY_GENRES))
