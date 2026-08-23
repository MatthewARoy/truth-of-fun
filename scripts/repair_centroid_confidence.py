"""One-time repair: demote city-centroid guesses that claim to be locations.

Before the fallback-confidence fix, dothebay/sfstation/luma scored a
named-but-unresolved venue at exactly 0.5 while placing it on the San
Francisco centroid, and _merge_event_payloads could raise that to the other
payload's confidence while keeping the centroid. Both are fixed at write
time now, but rows already stored keep their bad score: the ingestion path
only ever raises confidence, so nothing demotes them.

Any event sitting exactly on a city centroid is a fallback guess by
construction — CITY_COORDINATES is documented as coarse and to be paired
with a low confidence. Demote those to UNRESOLVED_CONFIDENCE so radius
search stops treating them as real places.

Usage:
    python -m scripts.repair_centroid_confidence            # report only
    python -m scripts.repair_centroid_confidence --apply    # write changes
"""

from __future__ import annotations

import argparse

from sqlalchemy import text
from sqlmodel import Session

from app.api.discovery import DEFAULT_MIN_LOCATION_CONFIDENCE
from app.core.database import engine
from app.ingestion.venue_cache import CITY_COORDINATES
from app.models.event import Event

UNRESOLVED_CONFIDENCE = 0.4

# Coordinates are stored at the precision the cache defines them with, so an
# exact-ish comparison is right; the tolerance only absorbs float round-trips.
_TOLERANCE = 1e-6


def _is_city_centroid(lat: float, lon: float) -> bool:
    return any(
        abs(lat - city_lat) < _TOLERANCE and abs(lon - city_lon) < _TOLERANCE
        for city_lat, city_lon in CITY_COORDINATES.values()
    )


def repaired_confidence(
    lat: float, lon: float, confidence: float
) -> float | None:
    """Corrected confidence for a row, or None when it needs no change."""
    if not _is_city_centroid(lat, lon):
        return None
    if confidence < DEFAULT_MIN_LOCATION_CONFIDENCE:
        return None
    return UNRESOLVED_CONFIDENCE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the demotions (default is a dry-run report)",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT id, title, venue_name, location_confidence,"
                " ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon"
                " FROM events"
            )
        ).all()

        changed = []
        for row in rows:
            new_confidence = repaired_confidence(
                float(row.lat), float(row.lon), float(row.location_confidence)
            )
            if new_confidence is not None:
                changed.append((row.id, row.title, row.venue_name, new_confidence))

        print(f"{len(changed)} event(s) sit on a city centroid above the threshold")
        for event_id, title, venue, new_confidence in changed[:20]:
            print(f"  #{event_id} {title[:48]!r} @ {venue!r} -> {new_confidence}")
        if len(changed) > 20:
            print(f"  ... and {len(changed) - 20} more")

        if not args.apply:
            print("\ndry run — pass --apply to write these changes")
            return

        for event_id, _, _, new_confidence in changed:
            event = session.get(Event, event_id)
            if event is not None:
                event.location_confidence = new_confidence
        session.commit()
        print(f"\nupdated {len(changed)} event(s)")


if __name__ == "__main__":
    main()
