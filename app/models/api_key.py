from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, func
from sqlmodel import Field, SQLModel


class ApiKeyInventory(SQLModel, table=True):
    __tablename__ = "api_key_inventory"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(sa_column=Column(String(length=64), nullable=False, index=True))
    key_id: str = Field(sa_column=Column(String(length=128), nullable=False, unique=True, index=True))
    status: str = Field(default="active", sa_column=Column(String(length=32), nullable=False))
    label: str | None = Field(default=None, sa_column=Column(String(length=255), nullable=True))
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


class ApiKeyUsageSnapshot(SQLModel, table=True):
    __tablename__ = "api_key_usage_snapshots"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(sa_column=Column(String(length=64), nullable=False, index=True))
    key_id: str = Field(sa_column=Column(String(length=128), nullable=False, index=True))
    usage_count: int = Field(sa_column=Column(Integer, nullable=False, default=0))
    quota_limit: int = Field(sa_column=Column(Integer, nullable=False, default=0))
    status: str = Field(default="active", sa_column=Column(String(length=32), nullable=False))
    last_status: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    last_error: str | None = Field(default=None, sa_column=Column(String(length=1024), nullable=True))
    captured_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    )
