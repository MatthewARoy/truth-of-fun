"""Explicit planning input and approximate geometry; no provider or DB calls."""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.itinerary import StopLocation

TravelMode = Literal["driving", "walking", "bicycling", "transit"]


def plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    if any(unicodedata.category(c).startswith("C") for c in value) or re.search(
        r"[<>]|(?:[a-z][a-z0-9+.-]*://)|\b(?:www\.|javascript:|data:)", value, re.I
    ):
        raise ValueError("Use single-line plain text without markup or URLs")
    return value.strip()


class PlanningPlace(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=250)
    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    lng: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @field_validator("name", "address")
    @classmethod
    def text(cls, value):
        return plain_text(value)

    @model_validator(mode="after")
    def complete(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("Supply both latitude and longitude")
        if self.lat is None and not (self.name or self.address):
            raise ValueError("Supply a place name, address or coordinates")
        return self

    def location(self) -> StopLocation:
        return StopLocation(venue_name=self.name, address=self.address, lat=self.lat, lng=self.lng)


class UserStop(BaseModel):
    kind: Literal["meeting", "walk", "activity"]
    title: str = Field(min_length=1, max_length=160)
    place: PlanningPlace
    start_at: datetime
    end_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def title_text(cls, value):
        cleaned = plain_text(value)
        if not cleaned:
            raise ValueError("Supply a title")
        return cleaned

    @field_validator("start_at", "end_at")
    @classmethod
    def timezone(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Supply a timezone offset")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.end_at is not None and self.end_at < self.start_at:
            raise ValueError("End must follow start")
        return self


class SearchArea(BaseModel):
    label: str
    lat: float
    lng: float
    radius_miles: float


_AREAS = {
    "near ocean beach": ("Near Ocean Beach", 37.7603, -122.5094, 1.5),
    "ocean beach": ("Near Ocean Beach", 37.7603, -122.5094, 1.5),
    "west side": ("West side of San Francisco", 37.765, -122.483, 2.5),
    "sunset": ("Sunset district", 37.753, -122.486, 1.8),
    "richmond": ("Richmond district, San Francisco", 37.780, -122.483, 1.6),
    "mission": ("Mission district", 37.759, -122.419, 1.0),
    "hayes valley": ("Hayes Valley", 37.776, -122.424, 0.7),
    "noe valley": ("Noe Valley", 37.751, -122.433, 0.8),
}


def resolve_search_area(query: str) -> SearchArea | None:
    text = query.lower()
    # Explicit non-SF cities prevent an ambiguous neighborhood word from
    # silently pulling a query into San Francisco.
    if re.search(r"\b(?:oakland|berkeley|san jose|richmond ca|richmond, ca)\b", text):
        return None
    matches = [(m.start(), -len(phrase), values) for phrase, values in _AREAS.items()
               if (m := re.search(r"\b" + re.escape(phrase) + r"\b", text))]
    if not matches:
        return None
    _, _, (label, lat, lng, radius) = min(matches)
    return SearchArea(label=label, lat=lat, lng=lng, radius_miles=radius)


def distance_miles(a: StopLocation, b: StopLocation) -> float | None:
    if not a.has_precise_coordinates or not b.has_precise_coordinates:
        return None
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlng = lat2 - lat1, math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng / 2)**2
    return 3958.76 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def travel_minutes(a: StopLocation | None, b: StopLocation, mode: TravelMode) -> tuple[int, bool]:
    distance = distance_miles(a, b) if a is not None else None
    if distance is None:
        return 30, False
    speed, overhead = {"walking": (2.5, 2), "bicycling": (9, 4),
                       "driving": (15, 8), "transit": (10, 12)}[mode]
    return math.ceil(distance * 1.3 / speed * 60 + overhead), True
