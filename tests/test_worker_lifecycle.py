"""Lifecycle cleanup: events become 'past' 24h after they END, not after they start.

Requires the local Postgres (PostGIS geometry column prevents sqlite); skips
cleanly when the database is unreachable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.event import Event


def _db_session_or_skip() -> Session:
    from sqlalchemy import create_engine, text

    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres is not reachable; run `make db-up` to enable this test.")
    return Session(engine)


def test_mark_past_respects_end_at() -> None:
    from app.worker import IngestionWorker

    session = _db_session_or_skip()
    now = datetime.now(timezone.utc)
    suffix = int(now.timestamp())

    ongoing = Event(
        title=f"Multi-day festival {suffix}",
        start_at=now - timedelta(days=2),
        end_at=now + timedelta(days=1),  # still running
        source_name="ticketmaster",
        source_tier=1,
        status="scheduled",
        location="POINT(-122.4194 37.7749)",
        source_event_id=f"test-lifecycle-ongoing-{suffix}",
    )
    finished = Event(
        title=f"Finished show {suffix}",
        start_at=now - timedelta(days=3),
        end_at=now - timedelta(days=2),
        source_name="ticketmaster",
        source_tier=1,
        status="scheduled",
        location="POINT(-122.4194 37.7749)",
        source_event_id=f"test-lifecycle-finished-{suffix}",
    )
    with session as s:
        s.add(ongoing)
        s.add(finished)
        s.commit()
        ongoing_id, finished_id = ongoing.id, finished.id

        try:
            engine = s.get_bind()
            worker = IngestionWorker(session_factory=lambda: Session(engine))
            worker._mark_past_events()

            s.expire_all()
            refreshed = {
                e.id: e.status
                for e in s.exec(
                    select(Event).where(Event.id.in_([ongoing_id, finished_id]))
                ).all()
            }
            assert refreshed[finished_id] == "past"
            assert refreshed[ongoing_id] == "scheduled"
        finally:
            for event_id in (ongoing_id, finished_id):
                record = s.get(Event, event_id)
                if record is not None:
                    s.delete(record)
            s.commit()
