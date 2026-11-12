"""Bay Area geography: which city and region an event is in.

"Where" used to mean a keyword match — ``location_preset=oakland`` found only
events whose venue name or address happened to contain the word "Oakland", so
a show at the Fox Theater (whose listing says "1807 Telegraph Ave") was not
in Oakland, and nothing at all could be asked about Berkeley, the Peninsula
or Marin. This module assigns every event a ``city`` and one of five
``region`` values from its coordinates, so the whole nine-county Bay Area is
filterable the way people actually talk about it.

Assignment is nearest-anchor: each anchor is a (lat, lon) inside a city, and
an event belongs to the city of the closest anchor. Large cities carry
several anchors (a single San Francisco centroid would hand Ocean Beach to
Daly City and the Marina to Sausalito). It is deliberately coarse — the
answer to "is this in the East Bay?", not a parcel lookup — and it is cheap,
offline and deterministic.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any

SF = "sf"
EAST_BAY = "east_bay"
SOUTH_BAY = "south_bay"
PENINSULA = "peninsula"
NORTH_BAY = "north_bay"
BEYOND = "beyond"

#: Display order and labels for the regions clients may filter by.
REGION_LABELS: dict[str, str] = {
    SF: "San Francisco",
    EAST_BAY: "East Bay",
    PENINSULA: "Peninsula",
    SOUTH_BAY: "South Bay",
    NORTH_BAY: "North Bay",
}
#: Every stored value. ``beyond`` marks places sources list alongside Bay Area
#: events (Santa Cruz, Sacramento, Tahoe) so they can be told apart, but it is
#: not offered as a filter.
REGIONS: frozenset[str] = frozenset({*REGION_LABELS, BEYOND})

#: Farther than this from every anchor and we do not guess.
MAX_ANCHOR_DISTANCE_KM = 30.0
#: Below this ``location_confidence`` the coordinates are a source's centroid
#: fallback, so a city named in the address is better evidence than they are.
TRUSTED_COORDINATE_CONFIDENCE = 0.5


@dataclass(frozen=True)
class Place:
    city: str | None
    region: str | None


UNKNOWN = Place(city=None, region=None)

# city -> (region, [(lat, lon), ...]). The first anchor is the civic centre;
# extra anchors cover districts far from it.
_CITIES: dict[str, tuple[str, list[tuple[float, float]]]] = {
    # --- San Francisco -----------------------------------------------------
    "San Francisco": (SF, [
        (37.7793, -122.4193),  # Civic Center
        (37.7946, -122.3999),  # Financial District / Embarcadero
        (37.7786, -122.3893),  # SoMa / Oracle Park
        (37.7680, -122.3877),  # Mission Bay / Chase Center
        (37.7599, -122.4148),  # Mission
        (37.7609, -122.4350),  # Castro
        (37.8005, -122.4100),  # North Beach
        (37.8037, -122.4368),  # Marina / Fort Mason
        (37.7989, -122.4662),  # Presidio
        (37.7800, -122.4830),  # Richmond district
        (37.7694, -122.4862),  # Golden Gate Park
        (37.7530, -122.4860),  # Sunset
        (37.7594, -122.5080),  # Ocean Beach
        (37.7373, -122.4713),  # Stern Grove / Parkside
        (37.7230, -122.4520),  # Ingleside / Excelsior
        (37.7300, -122.3900),  # Bayview
        (37.7410, -122.4180),  # Bernal Heights
        (37.7590, -122.3900),  # Dogpatch / Potrero
        (37.8235, -122.3706),  # Treasure Island
    ]),
    # --- East Bay (Alameda and Contra Costa counties) ------------------------
    "Oakland": (EAST_BAY, [
        (37.8044, -122.2712),  # Downtown / Uptown
        (37.7955, -122.2773),  # Jack London Square
        (37.8360, -122.2620),  # Temescal
        (37.7760, -122.2250),  # Fruitvale
        (37.7516, -122.2005),  # Coliseum / East Oakland
        (37.8270, -122.2100),  # Montclair
        (37.8110, -122.2470),  # Lake Merritt / Grand Lake
    ]),
    "Berkeley": (EAST_BAY, [(37.8715, -122.2730), (37.8690, -122.2590), (37.8650, -122.2980)]),
    "Emeryville": (EAST_BAY, [(37.8313, -122.2852)]),
    "Alameda": (EAST_BAY, [(37.7652, -122.2416)]),
    "Albany": (EAST_BAY, [(37.8869, -122.2978)]),
    "El Cerrito": (EAST_BAY, [(37.9161, -122.3108)]),
    "Richmond": (EAST_BAY, [(37.9358, -122.3477)]),
    "San Leandro": (EAST_BAY, [(37.7249, -122.1561)]),
    "Castro Valley": (EAST_BAY, [(37.6941, -122.0864)]),
    "Hayward": (EAST_BAY, [(37.6688, -122.0808)]),
    "Union City": (EAST_BAY, [(37.5934, -122.0438)]),
    "Fremont": (EAST_BAY, [(37.5485, -121.9886)]),
    "Newark": (EAST_BAY, [(37.5297, -122.0402)]),
    "Dublin": (EAST_BAY, [(37.7022, -121.9358)]),
    "Pleasanton": (EAST_BAY, [(37.6624, -121.8747)]),
    "Livermore": (EAST_BAY, [(37.6819, -121.7680)]),
    "San Ramon": (EAST_BAY, [(37.7799, -121.9780)]),
    "Danville": (EAST_BAY, [(37.8216, -121.9999)]),
    "Walnut Creek": (EAST_BAY, [(37.9101, -122.0652)]),
    "Lafayette": (EAST_BAY, [(37.8858, -122.1180)]),
    "Orinda": (EAST_BAY, [(37.8771, -122.1797)]),
    "Pleasant Hill": (EAST_BAY, [(37.9480, -122.0608)]),
    "Concord": (EAST_BAY, [(37.9780, -122.0311)]),
    "Martinez": (EAST_BAY, [(38.0194, -122.1341)]),
    "Pittsburg": (EAST_BAY, [(38.0280, -121.8847)]),
    "Antioch": (EAST_BAY, [(38.0049, -121.8058)]),
    "Brentwood": (EAST_BAY, [(37.9319, -121.6958)]),
    # --- Peninsula (San Mateo County plus Palo Alto / Stanford) -----------------
    "Daly City": (PENINSULA, [(37.6879, -122.4702)]),
    "South San Francisco": (PENINSULA, [(37.6547, -122.4077)]),
    "Pacifica": (PENINSULA, [(37.6138, -122.4869)]),
    "San Bruno": (PENINSULA, [(37.6305, -122.4111)]),
    "Millbrae": (PENINSULA, [(37.5985, -122.3872)]),
    "Burlingame": (PENINSULA, [(37.5841, -122.3660)]),
    "San Mateo": (PENINSULA, [(37.5630, -122.3255)]),
    "Foster City": (PENINSULA, [(37.5585, -122.2711)]),
    "Belmont": (PENINSULA, [(37.5202, -122.2758)]),
    "San Carlos": (PENINSULA, [(37.5072, -122.2605)]),
    "Redwood City": (PENINSULA, [(37.4852, -122.2364)]),
    "Menlo Park": (PENINSULA, [(37.4530, -122.1817)]),
    "East Palo Alto": (PENINSULA, [(37.4688, -122.1411)]),
    "Palo Alto": (PENINSULA, [(37.4419, -122.1430)]),
    "Stanford": (PENINSULA, [(37.4275, -122.1697)]),
    "Half Moon Bay": (PENINSULA, [(37.4636, -122.4286)]),
    # --- South Bay (Santa Clara County) ------------------------------------------
    "Mountain View": (SOUTH_BAY, [(37.3861, -122.0839), (37.4269, -122.0808)]),
    "Los Altos": (SOUTH_BAY, [(37.3852, -122.1141)]),
    "Sunnyvale": (SOUTH_BAY, [(37.3688, -122.0363)]),
    "Cupertino": (SOUTH_BAY, [(37.3230, -122.0322)]),
    "Santa Clara": (SOUTH_BAY, [(37.3541, -121.9552), (37.4030, -121.9700)]),
    "San Jose": (SOUTH_BAY, [
        (37.3382, -121.8863),  # Downtown
        (37.3327, -121.9010),  # SAP Center / Diridon
        (37.3040, -121.8990),  # Willow Glen
        (37.4000, -121.9200),  # North San Jose
        (37.3500, -121.8200),  # East San Jose
        (37.2500, -121.8600),  # South San Jose / Almaden
        (37.3200, -121.9480),  # Santana Row / West San Jose
    ]),
    "Campbell": (SOUTH_BAY, [(37.2872, -121.9500)]),
    "Saratoga": (SOUTH_BAY, [(37.2638, -122.0230)]),
    "Los Gatos": (SOUTH_BAY, [(37.2358, -121.9624)]),
    "Milpitas": (SOUTH_BAY, [(37.4323, -121.8996)]),
    "Morgan Hill": (SOUTH_BAY, [(37.1305, -121.6544)]),
    "Gilroy": (SOUTH_BAY, [(37.0058, -121.5683)]),
    # --- North Bay (Marin, Sonoma, Napa, Solano) ---------------------------------
    "Sausalito": (NORTH_BAY, [(37.8591, -122.4853)]),
    "Mill Valley": (NORTH_BAY, [(37.9060, -122.5450)]),
    "Tiburon": (NORTH_BAY, [(37.8735, -122.4566)]),
    "Larkspur": (NORTH_BAY, [(37.9341, -122.5353)]),
    "San Rafael": (NORTH_BAY, [(37.9735, -122.5311)]),
    "Fairfax": (NORTH_BAY, [(37.9871, -122.5889)]),
    "Novato": (NORTH_BAY, [(38.1074, -122.5697)]),
    "Stinson Beach": (NORTH_BAY, [(37.9005, -122.6444)]),
    "Point Reyes Station": (NORTH_BAY, [(38.0691, -122.8069)]),
    "Petaluma": (NORTH_BAY, [(38.2324, -122.6367)]),
    "Rohnert Park": (NORTH_BAY, [(38.3396, -122.7011)]),
    "Santa Rosa": (NORTH_BAY, [(38.4404, -122.7141)]),
    "Sebastopol": (NORTH_BAY, [(38.4021, -122.8239)]),
    "Healdsburg": (NORTH_BAY, [(38.6105, -122.8692)]),
    "Sonoma": (NORTH_BAY, [(38.2919, -122.4580)]),
    "Napa": (NORTH_BAY, [(38.2975, -122.2869)]),
    "Yountville": (NORTH_BAY, [(38.4016, -122.3608)]),
    "St. Helena": (NORTH_BAY, [(38.5052, -122.4703)]),
    "Calistoga": (NORTH_BAY, [(38.5788, -122.5797)]),
    "Vallejo": (NORTH_BAY, [(38.1041, -122.2566)]),
    "Benicia": (NORTH_BAY, [(38.0494, -122.1586)]),
    "Fairfield": (NORTH_BAY, [(38.2494, -122.0400)]),
    "Vacaville": (NORTH_BAY, [(38.3566, -121.9877)]),
    # --- Listed by Bay Area sources but outside the nine counties ----------------
    "Santa Cruz": (BEYOND, [(36.9741, -122.0308)]),
    "Monterey": (BEYOND, [(36.6002, -121.8947)]),
    "Sacramento": (BEYOND, [(38.5816, -121.4944)]),
    "Davis": (BEYOND, [(38.5449, -121.7405)]),
    "Stockton": (BEYOND, [(37.9577, -121.2908)]),
    "Modesto": (BEYOND, [(37.6391, -120.9969)]),
    "Tracy": (BEYOND, [(37.7397, -121.4252)]),
}

_ANCHORS: list[tuple[float, float, str, str]] = [
    (lat, lon, city, region)
    for city, (region, points) in _CITIES.items()
    for lat, lon in points
]

#: Cities offered per region, for filter UIs.
CITIES_BY_REGION: dict[str, list[str]] = {
    region: sorted(city for city, (city_region, _) in _CITIES.items() if city_region == region)
    for region in REGION_LABELS
}

_CITY_BY_KEY: dict[str, str] = {city.lower(): city for city in _CITIES}
_CITY_BY_KEY.update({"saint helena": "St. Helena", "st helena": "St. Helena", "so. san francisco": "South San Francisco"})

# "Richmond" and "Sunset" are also San Francisco districts, and plenty of
# venues are named for a city they are not in ("Sonoma Wine Bar, Oakland").
# Only a city in postal position — "..., Oakland, CA" / "Oakland, CA 94612" —
# counts as address evidence.
_POSTAL_CITY = re.compile(
    r"(?:^|,)\s*([A-Za-z.' ]{3,40}?)\s*,\s*(?:CA|California)\b", re.IGNORECASE
)

#: Spoken names people use for the regions, for natural-language planning.
_REGION_ALIASES: dict[str, str] = {
    "sf": SF, "san francisco": SF, "the city": SF,
    "east bay": EAST_BAY, "eastbay": EAST_BAY,
    "south bay": SOUTH_BAY, "silicon valley": SOUTH_BAY,
    "peninsula": PENINSULA, "the peninsula": PENINSULA,
    "north bay": NORTH_BAY, "marin": NORTH_BAY, "marin county": NORTH_BAY,
    "wine country": NORTH_BAY, "napa valley": NORTH_BAY,
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    h = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(min(1.0, h)))


def canonical_city(name: str | None) -> str | None:
    """The table's spelling of *name* ("oakland" -> "Oakland"), or None."""
    if not name:
        return None
    return _CITY_BY_KEY.get(re.sub(r"\s+", " ", name).strip().lower())


def region_for_city(city: str | None) -> str | None:
    canonical = canonical_city(city)
    return _CITIES[canonical][0] if canonical else None


def canonical_region(name: str | None) -> str | None:
    """Resolve a region id or spoken alias ("East Bay", "marin") to its id."""
    if not name:
        return None
    key = re.sub(r"[\s_-]+", " ", name).strip().lower()
    if key.replace(" ", "_") in REGION_LABELS:
        return key.replace(" ", "_")
    return _REGION_ALIASES.get(key)


def locate_point(lat: float, lon: float) -> Place:
    """City and region of the anchor nearest to a coordinate."""
    best: tuple[float, str, str] | None = None
    for a_lat, a_lon, city, region in _ANCHORS:
        distance = _haversine_km(lat, lon, a_lat, a_lon)
        if best is None or distance < best[0]:
            best = (distance, city, region)
    if best is None or best[0] > MAX_ANCHOR_DISTANCE_KM:
        return UNKNOWN
    return Place(city=best[1], region=best[2])


def city_in_address(*texts: str | None) -> str | None:
    """A known city written in postal position in any of *texts*."""
    for text in texts:
        if not text:
            continue
        for match in _POSTAL_CITY.finditer(text):
            # "1807 Telegraph Ave Oakland" arrives without the comma some
            # sources omit; the city is then the tail of the captured run.
            words = match.group(1).strip().split()
            for size in range(min(3, len(words)), 0, -1):
                city = canonical_city(" ".join(words[-size:]))
                if city:
                    return city
    return None


def locate_event(
    *,
    lat: float | None,
    lon: float | None,
    location_confidence: float | None = None,
    venue_name: str | None = None,
    raw_address: str | None = None,
) -> Place:
    """Best available city/region for an event.

    Trusted coordinates decide. When the coordinates are only a source's
    centroid fallback (low confidence), a city written in the address wins:
    an Oakland event whose venue could not be geocoded sits on the *San
    Francisco* default point in several connectors, and its address is the
    only thing that still knows where it is.
    """
    trusted = location_confidence is None or location_confidence >= TRUSTED_COORDINATE_CONFIDENCE
    if not trusted:
        named = city_in_address(raw_address, venue_name)
        if named:
            return Place(city=named, region=_CITIES[named][0])
    if lat is None or lon is None:
        return UNKNOWN
    return locate_point(lat, lon)


_WKT_POINT = re.compile(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.IGNORECASE)


def parse_point(location: Any) -> tuple[float, float] | None:
    """(lat, lon) from a WKT string or a PostGIS EWKB element, else None."""
    if location is None:
        return None
    if isinstance(location, str):
        match = _WKT_POINT.search(location)
        if match:
            return float(match.group(2)), float(match.group(1))
    try:
        raw = bytes(location.data) if hasattr(location, "data") else bytes.fromhex(
            getattr(location, "desc", None) or str(location)
        )
        endian = "<" if raw[0] == 1 else ">"
        (kind,) = struct.unpack(f"{endian}I", raw[1:5])
        offset = 9 if kind & 0x20000000 else 5  # EWKB carries an SRID word
        lon, lat = struct.unpack(f"{endian}dd", raw[offset:offset + 16])
        return float(lat), float(lon)
    except Exception:
        return None


def place_for_event(event: Any) -> Place:
    """Stored (city, region) for an Event row or an event payload dict.

    Never returns a NULL region: an event that cannot be placed is ``beyond``,
    so "not yet assigned" (NULL) and "not in the Bay Area" stay distinct.
    """
    get = event.get if isinstance(event, dict) else lambda key: getattr(event, key, None)
    point = parse_point(get("location"))
    place = locate_event(
        lat=point[0] if point else None,
        lon=point[1] if point else None,
        location_confidence=get("location_confidence"),
        venue_name=get("venue_name"),
        raw_address=get("raw_address"),
    )
    return place if place.region else Place(city=None, region=BEYOND)


def assign_missing_places(session: Any, *, batch_size: int = 1000, max_rows: int = 200_000) -> int:
    """Assign city/region to rows that have none yet. Returns rows updated.

    Runs at worker start and after every cycle, so rows created before this
    column existed (or written by a path that bypassed the pipeline) converge
    without a one-off backfill script. Idempotent and bounded.
    """
    from sqlalchemy import text

    updated = 0
    while updated < max_rows:
        rows = session.execute(
            text(
                "SELECT id, ST_Y(location) AS lat, ST_X(location) AS lon, "
                "location_confidence, venue_name, raw_address "
                "FROM events WHERE region IS NULL ORDER BY id LIMIT :limit"
            ),
            {"limit": batch_size},
        ).mappings().all()
        if not rows:
            break
        params = []
        for row in rows:
            place = locate_event(
                lat=row["lat"], lon=row["lon"],
                location_confidence=row["location_confidence"],
                venue_name=row["venue_name"], raw_address=row["raw_address"],
            )
            params.append({"id": row["id"], "city": place.city, "region": place.region or BEYOND})
        session.execute(
            text("UPDATE events SET city = :city, region = :region WHERE id = :id"), params
        )
        session.commit()
        updated += len(rows)
    return updated
