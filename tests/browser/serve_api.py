"""Seed a disposable local database and serve the real API for browser tests."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select

# Refuse to migrate or seed an ordinary application database by mistake.
database_url = os.environ["DATABASE_URL"]
parsed_url = make_url(database_url)
if (
    parsed_url.get_backend_name() != "postgresql"
    or parsed_url.host not in {"127.0.0.1", "localhost"}
    or not (parsed_url.database or "").endswith("_test")
    # PostgreSQL query options can override URL host/dbname after validation.
    # This dedicated harness has no need for connection query parameters.
    or parsed_url.query
):
    raise SystemExit("Sharing browser tests require a local disposable PostgreSQL database ending in _test, without URL query parameters.")

subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

from app.core.localtime import LOCAL_TZ
from app.models.event import Event

engine = create_engine(database_url)
with Session(engine) as session:
    fixture = session.exec(select(Event).where(Event.source_name == "sharing-browser-fixture")).first()
    starts_at = (datetime.now(LOCAL_TZ) + timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
    if fixture is None:
        fixture = Event(
            title="Sharing acceptance jazz", start_at=starts_at,
            source_name="sharing-browser-fixture", source_tier=1,
            location="POINT(-122.4194 37.7749)",
            venue_name="San Francisco Test Hall", raw_address="San Francisco, CA",
            tags=["#jazz", "#date"], categories=["Music"],
            created_at=datetime.now(timezone.utc),
        )
    fixture.start_at = starts_at
    fixture.end_at = starts_at + timedelta(hours=2)
    fixture.status = "scheduled"
    session.add(fixture)
    session.commit()
engine.dispose()

os.execv(sys.executable, [
    sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
    "--port", os.environ.get("SHARING_E2E_API_PORT", "8168"),
])
