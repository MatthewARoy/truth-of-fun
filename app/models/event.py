from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import JSON, Column, DateTime, Integer, Numeric, String, func
from sqlmodel import Field, SQLModel


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(String(length=500), index=True, nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    start_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), index=True, nullable=False)
    )
    end_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    source_name: str = Field(sa_column=Column(String(length=100), nullable=False))
    source_tier: int = Field(sa_column=Column(Integer, nullable=False))
    source_event_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), index=True, nullable=True),
    )
    external_url: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=2048), nullable=True),
    )
    venue_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), nullable=True),
    )
    raw_address: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    location: Any = Field(
        sa_column=Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    )
    categories: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    price: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(10, 2), nullable=True),
    )
    currency: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=3), nullable=True),
    )
    image_url: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=2048), nullable=True),
    )
    status: str = Field(
        default="scheduled",
        sa_column=Column(String(length=50), nullable=False, server_default="scheduled"),
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
