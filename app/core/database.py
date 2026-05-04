from collections.abc import Generator

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def check_database_connection() -> bool:
    with Session(engine) as session:
        session.exec(text("SELECT 1"))
    return True


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
