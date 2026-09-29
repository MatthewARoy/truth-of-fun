"""Rebuildable cache of successful versioned event classifications."""

from sqlalchemy import Column, JSON, String
from sqlmodel import Field, SQLModel


class VibeTagCache(SQLModel, table=True):
    __tablename__ = "vibe_tag_cache"

    cache_key: str = Field(sa_column=Column(String(64), primary_key=True))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
