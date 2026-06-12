from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel


class SourceHealthRecord(SQLModel, table=True):
    """Per-source ingestion health snapshot, written by the worker after each run.

    The worker and the API server are separate processes; this table is how
    GET /health/sources sees the worker's canary state.
    """

    __tablename__ = "source_health"

    source_name: str = Field(sa_column=Column(String(length=128), primary_key=True))
    status: str = Field(sa_column=Column(String(length=32), nullable=False))
    last_event_count: int = Field(sa_column=Column(Integer, nullable=False, default=0))
    consecutive_zeros: int = Field(sa_column=Column(Integer, nullable=False, default=0))
    last_run_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
