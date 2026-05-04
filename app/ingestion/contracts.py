from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


SourceId = Literal[
    "ticketmaster",
    "eventbrite",
    "meetup",
    "funcheap_sf",
    "19hz",
    "luma",
    "dothebay",
    "sfstation",
    "minnesotastreet",
    "reddit",
    "eddies_list",
]

CaptureMode = Literal["api", "scrape", "email_ingest", "llm_extract"]
RetentionPolicy = Literal["full", "metadata_only"]


class SourceMetadata(BaseModel):
    source_id: SourceId
    source_record_id: str | None = None
    source_url: HttpUrl
    ingested_at: datetime
    last_seen_at: datetime
    capture_mode: CaptureMode
    crawl_job_id: str


class LocationModel(BaseModel):
    venue_name: str | None = None
    address_line1: str | None = None
    city: str = "San Francisco"
    region: str = "CA"
    postal_code: str | None = None
    country: str = "US"
    lat: float | None = None
    lon: float | None = None
    location_is_private: bool = False
    location_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class OffersModel(BaseModel):
    is_free: bool = False
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = Field(default="USD", min_length=3, max_length=3)
    price_text: str | None = None


class OrganizerModel(BaseModel):
    name: str | None = None
    organizer_url: HttpUrl | None = None


class SocialSignalsModel(BaseModel):
    popularity_score: float = 0.0
    vote_count: int = 0
    attendee_count: int = 0
    comment_count: int = 0


class ComplianceModel(BaseModel):
    retention_policy: RetentionPolicy = "full"
    tos_risk: Literal["low", "medium", "high"] = "low"
    copyright_risk: Literal["low", "medium", "high"] = "low"
    notes: str | None = None


class QualityModel(BaseModel):
    record_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    llm_extracted: bool = False
    needs_review: bool = False
    validation_errors: list[str] = Field(default_factory=list)


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: UUID | None = None
    source: SourceMetadata
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    category_tags: list[str] = Field(default_factory=list)
    vibe_tags: list[str] = Field(default_factory=list)
    status: Literal["scheduled", "cancelled", "postponed", "unknown"] = "scheduled"
    timezone: str = "America/Los_Angeles"
    start_time: datetime
    end_time: datetime | None = None
    all_day: bool = False
    location: LocationModel
    offers: OffersModel = Field(default_factory=OffersModel)
    organizer: OrganizerModel = Field(default_factory=OrganizerModel)
    social_signals: SocialSignalsModel = Field(default_factory=SocialSignalsModel)
    image_url: HttpUrl | None = None
    compliance: ComplianceModel = Field(default_factory=ComplianceModel)
    quality: QualityModel = Field(default_factory=QualityModel)

    def to_legacy_event_payload(self, *, source_tier: int) -> dict[str, object]:
        location = None
        if self.location.lat is not None and self.location.lon is not None:
            location = f"POINT({self.location.lon} {self.location.lat})"

        return {
            "title": self.title,
            "description": self.description,
            "start_at": self.start_time,
            "end_at": self.end_time,
            "source_name": self.source.source_id,
            "source_tier": source_tier,
            "source_event_id": self.source.source_record_id,
            "external_url": str(self.source.source_url),
            "venue_name": self.location.venue_name,
            "raw_address": self.location.address_line1,
            "location": location,
            "categories": self.category_tags,
            "tags": self.vibe_tags,
            "price": self.offers.price_min,
            "currency": self.offers.currency,
            "image_url": str(self.image_url) if self.image_url else None,
            "status": self.status if self.status != "unknown" else "scheduled",
        }


class SourceAccountProfile(BaseModel):
    account_id: UUID
    source_id: SourceId
    account_type: Literal["api_key", "oauth", "session_cookie", "imap", "manual"]
    label: str
    status: Literal["active", "paused", "revoked", "expired"] = "active"
    secrets_ref: str
    requests_per_second: int | None = None
    requests_per_day: int | None = None
    points_per_window: int | None = None
    window_seconds: int = 60
    session_strategy: Literal[
        "none", "refresh_token", "cookie_rotation", "browser_login"
    ] = "none"
    last_validated_at: datetime | None = None
    owner: str = "platform-ingestion"
    notes: str | None = None
