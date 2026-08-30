from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, func
from sqlmodel import Field, SQLModel


class SavedItinerary(SQLModel, table=True):
    """A concierge plan frozen at the moment it was shared.

    Stops are a JSON snapshot rather than a join back to ``events`` on purpose:
    a shared link is an artifact someone reads on their phone hours or days
    later, and it should still say what it said when it was sent — even if the
    underlying event was re-deduped into another row, repriced, or dropped from
    the feed. ``user_id`` is nullable because the planner is usable signed out.
    """

    __tablename__ = "saved_itineraries"

    id: Optional[int] = Field(default=None, primary_key=True)
    share_token: str = Field(
        sa_column=Column(String(length=64), nullable=False, unique=True, index=True)
    )
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=True, index=True),
    )
    title: str = Field(sa_column=Column(String(length=255), nullable=False))
    query: str = Field(sa_column=Column(String, nullable=False))
    intent: str = Field(sa_column=Column(String(length=100), nullable=False))
    timeframe: str = Field(sa_column=Column(String(length=100), nullable=False))
    geography: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), nullable=True),
    )
    anchor_event_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    stops: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
