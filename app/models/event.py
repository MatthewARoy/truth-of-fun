from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, Numeric, String, event, func, inspect
from sqlmodel import Field, SQLModel


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(sa_column=Column(String(length=500), index=True, nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    start_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), index=True, nullable=False)
    )
    # True when the calendar date is real but the clock time is a connector
    # placeholder. Dedupe widens its time window for these, and the API tells
    # clients not to render a precise time.
    start_time_is_estimated: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
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
    performers: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, server_default="[]"))
    genres: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, server_default="[]"))
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
    organizer_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), nullable=True),
    )
    attendee_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    location_confidence: float = Field(
        default=1.0,
        sa_column=Column(Float, nullable=False, server_default="1.0"),
    )
    # Derived from the coordinates (or the address, when the coordinates are a
    # low-confidence centroid) by app/services/regions.py. ``region`` is NULL
    # only until the row has been assigned; "beyond" means outside the Bay Area.
    city: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=100), index=True, nullable=True),
    )
    region: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=20), index=True, nullable=True),
    )
    is_free: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
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


_PLACE_INPUTS = ("location", "location_confidence", "venue_name", "raw_address")


def _assign_place(target: Event) -> None:
    from app.services.regions import place_for_event

    place = place_for_event(target)
    target.city, target.region = place.city, place.region


@event.listens_for(Event, "before_insert")
def _place_new_event(_mapper, _connection, target: Event) -> None:  # type: ignore[no-untyped-def]
    """Every row written through the ORM gets its city/region — the pipeline,
    the demo seed and test fixtures alike — so a region filter never silently
    skips an event just because of which code path created it."""
    _assign_place(target)


@event.listens_for(Event, "before_update")
def _replace_moved_event(_mapper, _connection, target: Event) -> None:  # type: ignore[no-untyped-def]
    state = inspect(target)
    if target.region is None or any(
        state.attrs[name].history.has_changes() for name in _PLACE_INPUTS
    ):
        _assign_place(target)
