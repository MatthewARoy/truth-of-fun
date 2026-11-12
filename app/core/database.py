from collections.abc import Generator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()


def _engine_options() -> dict[str, object]:
    """Pool and safety settings for the shared engine.

    FastAPI runs sync endpoints on a 40-thread pool; SQLAlchemy's default of
    5 connections (+10 overflow) means a burst of slow queries queues every
    other request for 30 seconds and then 500s it. Size the pool explicitly,
    recycle connections before load balancers silently drop them, and cap how
    long any one statement may run so a bad query fails alone instead of
    holding a connection hostage.
    """
    options: dict[str, object] = {
        "echo": False,
        "pool_pre_ping": True,
        # Bound parameters carry emails, password hashes and share tokens;
        # keep them out of error messages and therefore out of the logs.
        "hide_parameters": True,
    }
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        return options
    options.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
    )
    if settings.db_statement_timeout_ms > 0:
        options["connect_args"] = {
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}"
        }
    return options


engine = create_engine(settings.database_url, **_engine_options())


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def check_database_connection() -> bool:
    with Session(engine) as session:
        session.exec(text("SELECT 1"))
    return True


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
