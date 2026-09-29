import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.core.ratelimit import SlidingWindowLimiter
from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate-limit windows are process-global; start each test with clean ones."""
    SlidingWindowLimiter.reset_all()
    yield
    SlidingWindowLimiter.reset_all()


def _require_disposable_database(database_url: str) -> None:
    parsed = make_url(database_url)
    if (parsed.get_backend_name() != "postgresql"
        or parsed.host not in {"localhost", "127.0.0.1"}
        or not (parsed.database or "").endswith("_test")
        or parsed.query):
        raise pytest.UsageError(
            "isolated_events_session requires a loopback PostgreSQL database "
            "ending in _test without URL query overrides"
        )


@pytest.fixture
def isolated_events_session():
    """A session whose ``events`` table holds only the rows the test seeds.

    Endpoints like ``/concierge/itinerary`` rank over the *whole* table, so a
    test that seeds a handful of rows and asserts on the global winner really
    asserts about whatever was ingested last. This fixture opens a transaction,
    empties ``events`` inside it, hands back a ``Session`` bound to that same
    connection, and rolls the transaction back afterwards — changes are never committed. The fixture refuses ordinary application
    databases; DATABASE_URL must name a disposable loopback _test database.

    Two things to know:

    - ``TRUNCATE`` (not ``DELETE``: ``user_signals`` and ``folder_items``
      reference ``events`` with ``NO ACTION``) takes an ACCESS EXCLUSIVE lock,
      so **stop the dev API and the ingestion worker first**. ``lock_timeout``
      makes that conflict fail fast instead of hanging the suite.
    - Seed through the yielded session. Rows written on a second connection
      (``engine.begin()``) commit for real and are invisible in here.
    """
    database_url = get_settings().database_url
    _require_disposable_database(database_url)
    engine = create_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("TRUNCATE events CASCADE"))
        app.dependency_overrides[get_session] = lambda: session
        yield session
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
