"""The backfill's UPDATE must actually land on the events table.

Every other part of the geocoding path is exercised by unit tests or was
verified live. This statement is the one that touches PostGIS, and a cast
mismatch here fails only at runtime, on the operator, mid-backfill —
``events.location`` is a ``geometry`` column, not ``geography``.

Runs inside a transaction that is always rolled back, so the shared
development database is left untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.core.config import get_settings
from app.models.event import Event
from app.services.geocoding import GeocodeResult
from scripts.backfill_geocode import GeocodeCandidate, PlannedChange, apply_changes


def _database_reachable() -> bool:
    engine = create_engine(get_settings().database_url, connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


pytestmark = pytest.mark.skipif(
    not _database_reachable(),
    reason="needs real Postgres + PostGIS to exercise the geometry write",
)

TARGET = GeocodeResult(
    lat=37.8446, lon=-122.2560, confidence=0.85, precision="poi", provider="probe"
)


def test_the_backfill_writes_the_point_and_confidence_it_planned() -> None:
    engine = create_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            session.begin()
            try:
                row = Event(
                    title="Backfill probe", start_at=datetime.now(timezone.utc),
                    source_name="test-backfill-write", source_tier=3,
                    location="POINT(-122.4194 37.7749)", location_confidence=0.4,
                )
                session.add(row)
                session.flush()

                apply_changes(
                    session,
                    [
                        PlannedChange(
                            candidate=GeocodeCandidate(
                                event_id=row.id,
                                title="probe",
                                venue_name=None,
                                raw_address=None,
                                location_confidence=0.4,
                            ),
                            result=TARGET,
                        )
                    ],
                )
                session.flush()

                written = session.execute(
                    text(
                        "SELECT ST_Y(location::geometry) AS lat,"
                        " ST_X(location::geometry) AS lon,"
                        " ST_SRID(location::geometry) AS srid,"
                        " location_confidence"
                        " FROM events WHERE id = :event_id"
                    ),
                    {"event_id": row.id},
                ).one()

                assert round(written.lat, 5) == TARGET.lat
                assert round(written.lon, 5) == TARGET.lon
                assert written.srid == 4326
                assert float(written.location_confidence) == TARGET.confidence
            finally:
                session.rollback()
    finally:
        engine.dispose()
