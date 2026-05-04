from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, String, func
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(
        sa_column=Column(String(length=255), unique=True, index=True, nullable=False)
    )
    hashed_password: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), nullable=True),
    )
    is_active: bool = Field(default=True, nullable=False)
    full_name: Optional[str] = Field(default=None, max_length=255)
    role: str = Field(default="user", max_length=64, nullable=False)
    saved_event_ids: list[int] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    preferred_vibes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )
    )
