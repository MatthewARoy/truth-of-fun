from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, func
from sqlmodel import Field, SQLModel


class UserSignal(SQLModel, table=True):
    __tablename__ = "user_signals"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    )
    event_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("events.id"), index=True, nullable=True),
    )
    signal_type: str = Field(sa_column=Column(String(length=64), nullable=False, index=True))
    vibe_tag: Optional[str] = Field(default=None, sa_column=Column(String(length=128), nullable=True))
    weight: float = Field(sa_column=Column(Float, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
