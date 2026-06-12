"""Integration check: /health confirms a live database connection.

This is the one test in the suite that needs a real Postgres (it exercises
the actual ``SELECT 1`` against ``DATABASE_URL``). It skips automatically
when the database is unreachable — e.g. a fresh clone before ``make db-up``
— so the default ``pytest`` run stays green. Backend CI provides a Postgres
service container, so the test always runs there.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.main import app


def _database_reachable() -> bool:
    engine = create_engine(
        get_settings().database_url, connect_args={"connect_timeout": 2}
    )
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
    reason=(
        "Postgres is not reachable at DATABASE_URL — "
        "start it with `make db-up` to run this integration test"
    ),
)


def test_health_check_confirms_database_connection() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
