"""
Static venue geocoding cache for known Bay Area event venues.
Used to assign accurate coordinates instead of defaulting to SF city center.
"""

# Format: "venue_name_lowercase": (latitude, longitude)
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
}


def lookup_venue_coordinates(venue_name: str | None) -> tuple[float, float] | None:
    """Look up coordinates for a known venue. Returns (lat, lon) or None."""
    if not venue_name:
        return None
    normalized = venue_name.strip().lower()
    # Exact match first
    if normalized in VENUE_COORDINATES:
        return VENUE_COORDINATES[normalized]
    # Substring match (e.g., "The Fillmore SF" matches "the fillmore")
    for key, coords in VENUE_COORDINATES.items():
        if key in normalized or normalized in key:
            return coords
    return None
