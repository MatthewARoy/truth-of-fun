"""Tests for the pure piece of scripts/repair_centroid_confidence.py.

Only repaired_confidence is tested here — it's pure. The DB update lives in
main(), following the precedent in tests/test_export_digest.py.
"""

from __future__ import annotations

from app.api.discovery import DEFAULT_MIN_LOCATION_CONFIDENCE
from app.ingestion.venue_cache import CITY_COORDINATES
from scripts.repair_centroid_confidence import (
    UNRESOLVED_CONFIDENCE,
    repaired_confidence,
)

SF_LAT, SF_LON = CITY_COORDINATES["san francisco"]
CAFE_DU_NORD = (37.7669, -122.4295)


def test_city_centroid_with_searchable_confidence_is_demoted() -> None:
    """Rows written before the fallback bug was fixed carry 0.5 (and, via the
    old merge, sometimes 0.9) on the exact SF centroid."""
    assert repaired_confidence(SF_LAT, SF_LON, 0.5) == UNRESOLVED_CONFIDENCE
    assert repaired_confidence(SF_LAT, SF_LON, 0.9) == UNRESOLVED_CONFIDENCE


def test_other_city_centroids_are_treated_the_same() -> None:
    oakland_lat, oakland_lon = CITY_COORDINATES["oakland"]
    assert repaired_confidence(oakland_lat, oakland_lon, 0.9) == UNRESOLVED_CONFIDENCE


def test_a_real_venue_coordinate_is_left_alone() -> None:
    assert repaired_confidence(*CAFE_DU_NORD, 0.9) is None


def test_a_centroid_already_below_the_threshold_is_left_alone() -> None:
    """Already honest — rewriting it would churn rows for nothing."""
    assert repaired_confidence(SF_LAT, SF_LON, 0.4) is None
    assert DEFAULT_MIN_LOCATION_CONFIDENCE == 0.5
