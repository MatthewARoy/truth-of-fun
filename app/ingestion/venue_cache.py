"""
Static venue geocoding cache for known Bay Area event venues.
Used to assign accurate coordinates instead of defaulting to SF city center.
"""

# Format: "venue_name_lowercase": (latitude, longitude)
import re
import unicodedata
from math import asin, cos, radians, sin, sqrt

_PUNCTUATION_FOLD = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)

VENUE_COORDINATES: dict[str, tuple[float, float]] = {
    # Major SF Venues
    "chase center": (37.7680, -122.3877),
    "bill graham civic auditorium": (37.7784, -122.4178),
    "the fillmore": (37.7840, -122.4332),
    "the warfield": (37.7826, -122.4100),
    "great american music hall": (37.7852, -122.4193),
    "the independent": (37.7755, -122.4378),
    "august hall": (37.7862, -122.4070),
    "bimbo's 365 club": (37.8025, -122.4138),
    "the chapel": (37.7608, -122.4214),
    "bottom of the hill": (37.7648, -122.3960),
    "dna lounge": (37.7710, -122.4130),
    "f8": (37.7714, -122.4104),
    "the knockout": (37.7454, -122.4214),
    "public works": (37.7641, -122.4187),
    "1015 folsom": (37.7781, -122.4052),
    "audio": (37.7710, -122.4123),
    "mezzanine": (37.7811, -122.4035),
    "slim's": (37.7706, -122.4043),
    "the regency ballroom": (37.7877, -122.4223),
    "palace of fine arts": (37.8028, -122.4484),
    "moscone center": (37.7836, -122.4005),
    "davies symphony hall": (37.7783, -122.4200),
    "war memorial opera house": (37.7792, -122.4208),
    "sf jazz center": (37.7762, -122.4214),
    "sfjazz center": (37.7762, -122.4214),
    "sfjazz": (37.7762, -122.4214),
    "the orpheum": (37.7793, -122.4174),
    "curran theatre": (37.7863, -122.4114),
    "golden gate theatre": (37.7827, -122.4112),
    "the masonic": (37.7910, -122.4122),
    "stern grove": (37.7373, -122.4713),
    "outside lands": (37.7694, -122.4862),
    "golden gate park": (37.7694, -122.4862),
    "dolores park": (37.7596, -122.4269),
    "exploratorium": (37.8017, -122.3975),
    "de young museum": (37.7714, -122.4686),
    "sfmoma": (37.7858, -122.4008),
    "yerba buena gardens": (37.7849, -122.4025),
    "the armory": (37.7702, -122.4190),
    "fort mason center": (37.8063, -122.4315),
    "pier 70": (37.7585, -122.3879),
    "the castro theatre": (37.7621, -122.4350),
    "castro theatre": (37.7621, -122.4350),
    "rickshaw stop": (37.7754, -122.4199),
    "the social sf": (37.7861, -122.4101),
    "temple nightclub": (37.7862, -122.4018),
    "cobb's comedy club": (37.8082, -122.4138),
    "punch line comedy club": (37.7941, -122.3986),
    "the saloon": (37.7976, -122.4057),

    # Oakland
    "fox theater": (37.8048, -122.2712),
    "fox theater oakland": (37.8048, -122.2712),
    "the new parish": (37.8084, -122.2665),
    "oakland arena": (37.7504, -122.2028),
    "the paramount theatre": (37.8092, -122.2685),
    "oakland museum": (37.7986, -122.2631),
    "starline social club": (37.8086, -122.2625),
    "the terminal": (37.8070, -122.2626),
    "crybaby": (37.8097, -122.2671),
    "complex oakland": (37.8013, -122.2752),
    "lake merritt amphitheater": (37.8037, -122.2568),

    # Berkeley / East Bay
    "uc theatre": (37.8681, -122.2597),
    "the freight and salvage": (37.8707, -122.2680),
    "greek theatre": (37.8739, -122.2541),
    "cornerstone berkeley": (37.8573, -122.2580),
    "ashkenaz": (37.8809, -122.2975),

    # South Bay
    "shoreline amphitheatre": (37.4269, -122.0808),
    "sap center": (37.3327, -121.9010),
    "san jose civic": (37.3340, -121.8906),
    "the catalyst": (36.9741, -122.0272),
    "stanford university": (37.4275, -122.1697),

    # Marin / North Bay
    "sweetwater music hall": (37.8931, -122.5176),
    "outdoor art club": (37.8949, -122.5219),

    # Minnesota Street Project galleries
    "minnesota street project": (37.7568, -122.3897),
    "minnesota street": (37.7568, -122.3897),
    "1275 minnesota st": (37.7568, -122.3897),
    "1275 minnesota street": (37.7568, -122.3897),
    # Central-corridor and recurring-feed venues (Mission, Castro, Divisadero,
    # Golden Gate Park, SoMa). Coordinates are street-address level; they only
    # need to be good enough for radius search, not survey-grade.
    "cafe du nord": (37.7669, -122.4295),
    "swedish american hall": (37.7669, -122.4295),
    "the roxie": (37.7649, -122.4220),
    "roxie theater": (37.7649, -122.4220),
    "biscuits and blues": (37.7873, -122.4098),
    "madrone art bar": (37.7757, -122.4376),
    "club waziema": (37.7761, -122.4376),
    "the midway": (37.7480, -122.3877),
    "halcyon": (37.7712, -122.4131),
    "the endup": (37.7776, -122.4053),
    "the hibernia": (37.7810, -122.4130),
    "rickshaw stop": (37.7767, -122.4200),
    "zeitgeist": (37.7699, -122.4223),
    "el rio": (37.7476, -122.4194),
    "thee parkside": (37.7654, -122.3980),
    "bissap baobab": (37.7601, -122.4188),
    "the function": (37.7754, -122.4176),
    "endgames improv": (37.7503, -122.4183),
    "japanese tea garden": (37.7702, -122.4703),
    "spreckels temple of music": (37.7702, -122.4682),
    "robin williams meadow": (37.7700, -122.4680),
    "skatin' place": (37.7714, -122.4640),
    "dolores park": (37.7596, -122.4269),
    "crissy field": (37.8038, -122.4644),
    "union square park": (37.7880, -122.4075),
    "house of air": (37.8026, -122.4573),
    "mersea": (37.8225, -122.3706),
    "mesa maguey": (37.8262, -122.2620),
}


# City centroids, used only when a venue can't be resolved but its city is
# known. Coarse by design: the point is to land in the right city rather than
# to pretend to venue-level precision. Callers must pair these with a low
# location_confidence.
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "san francisco": (37.7749, -122.4194),
    "oakland": (37.8044, -122.2712),
    "berkeley": (37.8715, -122.2730),
    "san jose": (37.3382, -121.8863),
    "santa cruz": (36.9741, -122.0308),
    "sacramento": (38.5816, -121.4944),
    "palo alto": (37.4419, -122.1430),
    "san mateo": (37.5630, -122.3255),
    "redwood city": (37.4852, -122.2364),
    "richmond": (37.9358, -122.3477),
    "emeryville": (37.8313, -122.2852),
    "alameda": (37.7652, -122.2416),
    "napa": (38.2975, -122.2869),
    "sonoma": (38.2919, -122.4580),
    "santa rosa": (38.4404, -122.7141),
    "novato": (38.1074, -122.5697),
    "san rafael": (37.9735, -122.5311),
    "vallejo": (38.1041, -122.2566),
    "concord": (37.9780, -122.0311),
    "walnut creek": (37.9101, -122.0652),
    "fremont": (37.5485, -121.9886),
    "union city": (37.5934, -122.0438),
    "hayward": (37.6688, -122.0808),
    "daly city": (37.6879, -122.4702),
    "half moon bay": (37.4636, -122.4286),
    "mountain view": (37.3861, -122.0839),
    "sunnyvale": (37.3688, -122.0363),
    "santa clara": (37.3541, -121.9552),
    "reno": (39.5296, -119.8138),
    "fresno": (36.7378, -119.7871),
    "stockton": (37.9577, -121.2908),
}


def _normalize_venue(value: str) -> str:
    """Fold the punctuation variants scrapers emit into one comparable form.

    Sites render apostrophes as U+2019 ("Cobb’s") while this table stores
    ASCII ("Cobb's"), so without folding the lookup misses entirely.
    """
    text = unicodedata.normalize("NFKC", value).translate(_PUNCTUATION_FOLD)
    return re.sub(r"\s+", " ", text).strip().lower()


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def _named_city(normalized: str) -> str | None:
    """The most specific city named inside a venue string, if any."""
    best: str | None = None
    for city in CITY_COORDINATES:
        if city in normalized and (best is None or len(city) > len(best)):
            best = city
    return best


def _city_is_consistent(coords: tuple[float, float], city: str | None) -> bool:
    """Reject a match whose coordinates sit nearer some other city's centroid.

    "Punch Line Comedy Club - Sacramento" shares a name prefix with the SF
    club; without this guard it resolves to San Francisco and a Sacramento
    show is planted in the middle of the city at full confidence.
    """
    if city is None:
        return True
    nearest = min(
        CITY_COORDINATES,
        key=lambda name: _haversine_km(coords, CITY_COORDINATES[name]),
    )
    return nearest == city


def lookup_city_coordinates(city: str | None) -> tuple[float, float] | None:
    """Look up a city centroid. Returns (lat, lon) or None when unknown."""
    if not city:
        return None
    return CITY_COORDINATES.get(_normalize_venue(city))


def lookup_venue_coordinates(venue_name: str | None) -> tuple[float, float] | None:
    """Look up coordinates for a known venue. Returns (lat, lon) or None.

    Prefers the longest matching key so a specific venue wins over a short
    one that happens to be a substring, and refuses any match that would
    place the event in the wrong city. Returning None is the safe failure:
    callers fall back to a centroid with a low ``location_confidence``,
    which the discovery radius filter then excludes.
    """
    if not venue_name:
        return None
    normalized = _normalize_venue(venue_name)
    if not normalized:
        return None

    candidates: list[tuple[int, tuple[float, float]]] = []
    exact = VENUE_COORDINATES.get(normalized)
    if exact is not None:
        candidates.append((len(normalized), exact))
    else:
        for key, coords in VENUE_COORDINATES.items():
            if key in normalized:
                candidates.append((len(key), coords))
        if not candidates:
            for key, coords in VENUE_COORDINATES.items():
                if normalized in key:
                    candidates.append((len(normalized), coords))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    coords = candidates[0][1]
    if not _city_is_consistent(coords, _named_city(normalized)):
        return None
    return coords
