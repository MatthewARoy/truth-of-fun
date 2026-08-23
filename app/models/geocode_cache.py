from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, String
from sqlmodel import Field, SQLModel


class GeocodeCacheEntry(SQLModel, table=True):
    """One provider answer per distinct query string, successes and failures.

    The ingestion worker re-reads every feed every six hours and the public
    geocoder allows one request per second, so without this table each cycle
    would re-derive the same few hundred answers. Failures are cached too:
    most of the unresolved tail is one-off spaces and private addresses that
    will never resolve, and retrying them is what would actually exhaust the
    rate-limit budget.
    """

    __tablename__ = "geocode_cache"

    # The normalized query, folded by the same rules as the static venue
    # table so "Bimbo&#039;s" and "Bimbo's" share one entry.
    query_key: str = Field(sa_column=Column(String(length=512), primary_key=True))
    provider: str = Field(sa_column=Column(String(length=32), nullable=False))
    # Null on a cached failure; ``resolved`` is the discriminator rather than
    # a null check, so a future provider returning (0, 0) can't read as a hit.
    lat: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    lon: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    confidence: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    precision: str | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    resolved: bool = Field(sa_column=Column(Boolean, nullable=False, default=False))
    looked_up_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
