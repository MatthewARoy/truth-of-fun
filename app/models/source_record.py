"""Stable source identities for events merged across providers."""

from sqlalchemy import JSON, Column, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel


class EventSourceRecord(SQLModel, table=True):
    __tablename__ = "event_source_records"

    source_name: str = Field(sa_column=Column(String(100), primary_key=True))
    source_event_id: str = Field(sa_column=Column(String(255), primary_key=True))
    event_id: int = Field(sa_column=Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True))
    content_hash: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    hash_version: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default="1"))
    catalog_facts: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}"))
