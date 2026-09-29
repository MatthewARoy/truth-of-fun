from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from geoalchemy2 import Geography
from sqlalchemy import and_, case, cast, delete, func, literal, or_, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Session, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.database import get_session
from app.core.localtime import LOCAL_TZ, tonight_end, weekend_window
from app.core.ratelimit import llm_rate_limit, share_rate_limit
from app.core.security import get_current_user, get_optional_user
from app.models.event import Event
from app.models.itinerary import SavedItinerary
from app.models.user import User
from app.models.user_signal import UserSignal
from app.services.categories import canonical_category
from app.services.concierge import (
    anchor_hour_range,
    intent_vibe_profile,
    parse_intent_async,
    sequence_itinerary,
)
from app.services.itinerary import (
    StopLocation,
    build_stop_links,
    itinerary_title,
    render_itinerary_text,
)
from app.services.recommender import RecommenderService, ScoredEvent
from app.services.social import generate_share_token, is_valid_share_token
from app.services.tags import VIBE_VOCABULARY, resolve_vibe_tag, stored_forms_for
from app.services.user_profile import UserProfileService

router = APIRouter(tags=["discovery"])
_user_profile_service = UserProfileService()
_recommender_service = RecommenderService()


class EventResponse(BaseModel):
    id: int
    title: str
    description: str | None
    start_at: datetime
    # The date is real; the clock time is a connector placeholder. Clients must
    # not render a precise time when this is true.
    start_time_is_estimated: bool = False
    end_at: datetime | None
    external_url: str | None
    venue_name: str | None
    tags: list[str]
    categories: list[str]
    image_url: str | None
    price: float | None
    currency: str | None
    status: str
    people_interested: int = 0
    distance_miles: float | None = None
    lat: float | None = None
    lng: float | None = None
    organizer_name: str | None = None
    attendee_count: int = 0
    location_confidence: float = 1.0
    is_free: bool = False


class RecommendationResponse(EventResponse):
    match_score: int
    matched_vibes: list[str]


class EventDetailResponse(EventResponse):
    """Single-event detail, with the provenance fields agents need to cite it.

    ``first_seen_at`` is deliberately *not* called ``created_at``: it is when
    this platform first ingested the event, which is not when the event was
    announced. Naming it honestly stops downstream clients from presenting it
    as an announcement date.
    """

    first_seen_at: datetime
    updated_at: datetime
    source_name: str
    source_tier: int
    raw_address: str | None = None


class ConciergeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    # Accepted for compatibility, deliberately unused: an itinerary is at most
    # three stops by construction, so this never sized the response. It used to
    # cap the candidate pools instead, which silently decided the anchor and the
    # post-anchor stop by start time before ranking and sequencing ran.
    limit: int = Field(default=25, ge=3, le=100)


class StopLinksResponse(BaseModel):
    """Tap targets for one stop. Any of these is null when the stop has no
    resolvable location (no coordinates, address, or venue name)."""

    tickets_url: str | None = None
    map_url: str | None = None
    directions_url: str | None = None
    food_url: str | None = None
    drinks_url: str | None = None
    parking_url: str | None = None


class ItineraryStopResponse(BaseModel):
    kind: str
    event_id: int
    title: str
    start_at: datetime
    # Defaulted so snapshots frozen before the flag existed still rehydrate.
    start_time_is_estimated: bool = False
    end_at: datetime | None
    venue_name: str | None
    external_url: str | None
    travel_buffer_minutes_before: int
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    links: StopLinksResponse = StopLinksResponse()


class ConciergeResponse(BaseModel):
    intent: str
    timeframe: str
    geography: str | None
    category_focus: str | None = None
    anchor_event_id: int | None
    itinerary: list[ItineraryStopResponse]
    title: str = ""
    text: str = ""


class ShareItineraryStopRequest(BaseModel):
    """A stop the client is asking to freeze.

    Only the identity and ordering of a stop come from the client; every
    display fact is re-read from the database when the snapshot is written, so
    a shared page can never be made to show text the caller supplied.
    """

    kind: str = Field(max_length=50)
    event_id: int
    travel_buffer_minutes_before: int = Field(default=0, ge=0, le=24 * 60)


class ShareItineraryRequest(BaseModel):
    # Accepted only for older clients. A raw planning prompt is never persisted
    # by this endpoint or included in the public response.
    query: str = Field(default="", max_length=2000)
    expires_in_days: int = Field(default=14, ge=1, le=30)
    intent: str = Field(default="general_night_out", max_length=100)
    timeframe: str = Field(default="upcoming_week", max_length=100)
    geography: str | None = Field(default=None, max_length=255)
    anchor_event_id: int | None = None
    stops: list[ShareItineraryStopRequest] = Field(min_length=1, max_length=20)


class PortableItineraryResponse(BaseModel):
    share_token: str
    share_url: str
    title: str
    intent: str
    timeframe: str
    geography: str | None
    anchor_event_id: int | None
    created_at: datetime
    expires_at: datetime
    itinerary: list[ItineraryStopResponse]
    text: str


class OwnedItineraryResponse(BaseModel):
    share_token: str
    share_url: str
    title: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    status: Literal["active", "expired", "revoked"]


class _NoStoreShareRoute(APIRoute):
    """Revocable links and owner inventories must not outlive access in caches."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except StarletteHTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "private, no-store"}
                raise
            except RequestValidationError as exc:
                response = await request_validation_exception_handler(request, exc)
            response.headers["Cache-Control"] = "private, no-store"
            return response

        return handler


_sharing_router = APIRouter(route_class=_NoStoreShareRoute)


class InterestRequest(BaseModel):
    action: Literal["save", "like", "click", "external_ticket_click"]
    event_id: int | None = None
    vibe_tag: str | None = Field(default=None, max_length=100)


class InterestResponse(BaseModel):
    user_id: int
    saved_event_ids: list[int]
    preferred_vibes: list[str]


class PreferencesRequest(BaseModel):
    preferred_vibes: list[str] = Field(max_length=50)

    @field_validator("preferred_vibes")
    @classmethod
    def known_vibes(cls, values: list[str]) -> list[str]:
        tags: list[str] = []
        for value in values:
            tag = resolve_vibe_tag(value)
            if tag not in VIBE_VOCABULARY:
                raise ValueError(f"Unknown vibe: {value[:100]}")
            if tag not in tags:
                tags.append(tag)
        return tags


class OnboardingRequest(BaseModel):
    perfect_saturday: str = Field(min_length=1, max_length=2000)


class OnboardingResponse(BaseModel):
    user_id: int
    extracted_vibes: list[str]
    preferred_vibes: list[str]


def _extract_lat_lng(event: Event) -> tuple[float | None, float | None]:
    """Extract (lat, lng) from a PostGIS POINT.

    Parses EWKB hex directly so we don't require Shapely as a hard dep.
    EWKB layout for a 2D POINT with SRID: 1 byte endian + 4 bytes type
    (with SRID flag set) + 4 bytes SRID + 8 bytes X + 8 bytes Y.
    """
    import struct

    location = getattr(event, "location", None)
    if location is None:
        return None, None
    try:
        raw = bytes(location.data) if hasattr(location, "data") else None
        if raw is None:
            hex_str = getattr(location, "desc", None) or str(location)
            raw = bytes.fromhex(hex_str)
        if len(raw) < 25:
            return None, None
        endian = "<" if raw[0] == 1 else ">"
        # Skip 1 byte endian + 4 bytes type + 4 bytes SRID = 9 bytes
        x, y = struct.unpack(f"{endian}dd", raw[9:25])
        return float(y), float(x)
    except Exception:
        return None, None


def _serialize_event(event: Event, *, people_interested: int = 0) -> EventResponse:
    lat, lng = _extract_lat_lng(event)
    return EventResponse(
        id=int(event.id or 0),
        title=event.title,
        description=event.description,
        start_at=event.start_at,
        start_time_is_estimated=bool(event.start_time_is_estimated),
        end_at=event.end_at,
        external_url=event.external_url,
        venue_name=event.venue_name,
        tags=list(event.tags or []),
        categories=list(event.categories or []),
        image_url=event.image_url,
        price=float(event.price) if event.price is not None else None,
        currency=event.currency,
        status=event.status,
        people_interested=people_interested,
        lat=lat,
        lng=lng,
        organizer_name=event.organizer_name,
        attendee_count=event.attendee_count or 0,
        location_confidence=event.location_confidence
        if event.location_confidence is not None
        else 1.0,
        is_free=bool(event.is_free),
    )


def _event_location(event: Event | None) -> StopLocation:
    """Map-addressable location for an event, or an empty one if it's gone."""
    if event is None:
        return StopLocation()
    lat, lng = _extract_lat_lng(event)
    return StopLocation(
        venue_name=event.venue_name,
        address=event.raw_address,
        lat=lat,
        lng=lng,
        location_confidence=(
            event.location_confidence if event.location_confidence is not None else 1.0
        ),
    )


def _portable_stops(
    raw_stops: list[tuple[ItineraryStopResponse, StopLocation]],
) -> list[ItineraryStopResponse]:
    """Attach maps links to each stop, routing each one from the previous stop.

    A stop we can't locate is left linkless and does not become the origin for
    the next leg — otherwise one venue-less entry would break directions for
    the rest of the night.
    """
    enriched: list[ItineraryStopResponse] = []
    previous: StopLocation | None = None
    for stop, location in raw_stops:
        links = build_stop_links(
            location=location,
            previous_location=previous,
            tickets_url=stop.external_url,
        )
        enriched.append(
            stop.model_copy(
                update={
                    "address": location.address,
                    "lat": location.lat,
                    "lng": location.lng,
                    "links": StopLinksResponse(**asdict(links)),
                }
            )
        )
        if location.is_locatable:
            previous = location
    return enriched


def _canonical_tag_filter(vibe_tag: str):
    """Match *vibe_tag* against stored tags regardless of their spelling.

    ``Event.tags.contains([...])`` is exact, case-sensitive JSONB containment,
    so filtering by ``#highenergy`` missed every event stored as ``HighEnergy``.
    Canonicalize both sides in SQL so the filter is correct against today's
    mixed-form rows as well as canonicalized ones.

    The cast is load-bearing: ``events.tags`` is a plain ``JSON`` column and
    Postgres has no ``jsonb_array_elements_text(json)`` overload, so without it
    every tag-filtered query dies with "function ... does not exist".
    """
    forms = stored_forms_for(vibe_tag)
    if not forms:
        return text("FALSE")

    element = func.jsonb_array_elements_text(cast(Event.tags, JSONB)).column_valued("tag")
    normalized = func.regexp_replace(
        func.lower(func.ltrim(element, "#")), "[^a-z0-9+]", "", "g"
    )
    return select(element).where(normalized.in_(forms)).exists()


# Below this, a coordinate is treated as a city-centroid guess rather than a
# place worth searching on. Ingestion sources must score an unresolved venue
# under this value or its centroid fallback is returned as a real location.
DEFAULT_MIN_LOCATION_CONFIDENCE = 0.5


def overlaps_window(window_start: datetime, window_end: datetime):
    """SQL predicate: the event overlaps [window_start, window_end].

    Filtering on ``start_at`` alone hides anything already under way, so a
    festival running 10:15-16:00 vanishes from an afternoon query made at
    15:00. An event with no published ``end_at`` is treated as a point in
    time at ``start_at``.
    """
    return and_(
        func.coalesce(Event.end_at, Event.start_at) >= window_start,
        Event.start_at <= window_end,
    )


def _apply_concierge_geography_filter(stmt: object, geography: str | None) -> object:
    if not geography:
        return stmt
    geography_like = f"%{geography}%"
    return stmt.where(
        Event.venue_name.ilike(geography_like)
        | Event.raw_address.ilike(geography_like)
        | Event.title.ilike(geography_like)
    )


def _category_filter(category: str):
    """Exact containment against ``events.categories``.

    ``categories`` is a plain JSON column, and SQLAlchemy renders ``.contains()``
    on JSON as a SQL ``LIKE`` — which Postgres rejects outright with
    "operator does not exist: json ~~ text", 500ing every category-filtered
    query. It passes on SQLite, which is what the hermetic test suite runs on,
    so only Postgres sees it. Cast to JSONB so containment uses the ``@>``
    operator it was meant to.
    """
    return cast(Event.categories, JSONB).contains([category])


def _apply_concierge_category_filter(stmt: object, category: str | None) -> object:
    if not category:
        return stmt
    return stmt.where(_category_filter(category))


def _people_interested_counts(*, session: Session, event_ids: list[int]) -> dict[int, int]:
    if not event_ids:
        return {}
    rows = session.exec(
        select(UserSignal.event_id, func.count(func.distinct(UserSignal.user_id)))
        .where(
            UserSignal.event_id.in_(event_ids),
            UserSignal.signal_type.in_(["save", "click", "external_ticket_click"]),
        )
        .group_by(UserSignal.event_id)
    ).all()
    return {int(event_id): int(count) for event_id, count in rows if event_id is not None}


def _apply_time_preset(
    *, time_preset: str | None, now: datetime | None = None
) -> tuple[datetime | None, datetime | None]:
    """Resolve a preset to a UTC window computed in SF local time."""
    if not time_preset:
        return None, None
    now = now or datetime.now(timezone.utc)
    if time_preset == "tonight":
        return now, tonight_end(now)
    if time_preset == "this_weekend":
        return weekend_window(now)
    return None, None


def _location_keyword_for_preset(location_preset: str | None) -> str | None:
    if location_preset == "sf":
        return "San Francisco"
    if location_preset == "oakland":
        return "Oakland"
    if location_preset == "san_jose":
        return "San Jose"
    return None


@router.get(
    "/events",
    response_model=list[EventResponse],
    operation_id="searchEvents",
    summary="Search and filter events",
)
def search_events(
    *,
    response: Response,
    session: Session = Depends(get_session),
    q: str | None = Query(default=None, max_length=200, description="Full-text search query"),
    lat: float | None = Query(default=None, ge=-90, le=90, description="Latitude for geo search"),
    lng: float | None = Query(default=None, ge=-180, le=180, description="Longitude for geo search"),
    radius_miles: float | None = Query(default=None, gt=0, le=500, description="Search radius miles"),
    min_location_confidence: float = Query(
        default=DEFAULT_MIN_LOCATION_CONFIDENCE,
        ge=0,
        le=1,
        description=(
            "Minimum location_confidence for radius search. Defaults to 0.5 so "
            "city-centroid fallbacks are excluded; pass 0 to include them."
        ),
    ),
    vibe_tag: str | None = Query(default=None, max_length=100, description="Filter by vibe tag"),
    category: str | None = Query(
        default=None,
        max_length=100,
        description="Filter by activity category (e.g. 'Fitness', 'Music', or a "
        "synonym like 'gym'/'workout')",
    ),
    time_preset: Literal["tonight", "this_weekend"] | None = Query(
        default=None,
        description="Friendly time filter for quick UI controls",
    ),
    location_preset: Literal["sf", "oakland", "san_jose"] | None = Query(
        default=None,
        description="Friendly location filter for quick UI controls",
    ),
    start_at: datetime | None = Query(default=None, description="Window lower bound; includes ongoing events"),
    end_at: datetime | None = Query(default=None, description="Start time upper bound"),
    include_past: bool = Query(False, description="Include past events in results"),
    sort_by: Literal["date", "distance"] = Query(
        "date", description="Sort order: 'date' (default) or 'distance' (requires lat/lng)"
    ),
    status: str | None = Query(None, max_length=50, description="Filter by event status"),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[EventResponse]:
    if any(value is not None for value in (lat, lng, radius_miles)) and any(
        value is None for value in (lat, lng, radius_miles)
    ):
        raise HTTPException(
            status_code=400,
            detail="lat, lng, and radius_miles must all be provided together.",
        )

    has_geo = lat is not None and lng is not None

    # Build the select — include distance column when geo params are present.
    if has_geo:
        user_point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        distance_expr = func.ST_Distance(
            cast(Event.location, Geography),
            cast(user_point, Geography),
        ).label("distance_meters")
        stmt = select(Event, distance_expr)
    else:
        stmt = select(Event)

    if q:
        stmt = stmt.where(
            text("search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q)
        )

    if not include_past:
        # An event in progress is not a past event: filter on when it ends,
        # falling back to the start when no end time was published.
        stmt = stmt.where(func.coalesce(Event.end_at, Event.start_at) >= func.now())
    if status is not None:
        stmt = stmt.where(Event.status == status)
    elif not include_past:
        stmt = stmt.where(Event.status == "scheduled")

    preset_start, preset_end = _apply_time_preset(time_preset=time_preset)
    start_bound = start_at or preset_start
    end_bound = end_at or preset_end

    if start_bound is not None:
        stmt = stmt.where(func.coalesce(Event.end_at, Event.start_at) >= start_bound)
    if end_bound is not None:
        stmt = stmt.where(Event.start_at <= end_bound)
    if vibe_tag:
        stmt = stmt.where(_canonical_tag_filter(vibe_tag))
    if category:
        # Resolve synonyms ("gym"/"workout" -> "Fitness"); fall back to the raw
        # term so callers can still filter by finer-grained labels (e.g. a genre).
        resolved_category = canonical_category(category) or category.strip()
        stmt = stmt.where(_category_filter(resolved_category))

    location_keyword = _location_keyword_for_preset(location_preset)
    if location_keyword:
        geography_like = f"%{location_keyword}%"
        stmt = stmt.where(
            Event.venue_name.ilike(geography_like)
            | Event.raw_address.ilike(geography_like)
            | Event.title.ilike(geography_like)
        )

    if has_geo and radius_miles is not None:
        radius_meters = radius_miles * 1609.34
        stmt = stmt.where(
            func.ST_DWithin(
                func.Geography(Event.location),
                func.Geography(user_point),
                radius_meters,
            )
        )
        # Sources fall back to a city centroid when a venue can't be resolved,
        # which otherwise puts out-of-town events inside every SF radius
        # search. Exclude those guesses unless the caller opts back in.
        stmt = stmt.where(Event.location_confidence >= min_location_confidence)

    # Sort order: distance (when geo available) or date (default / fallback).
    if sort_by == "distance" and has_geo:
        stmt = stmt.order_by(distance_expr.asc(), Event.start_at.asc(), Event.id.asc())
    else:
        stmt = stmt.order_by(Event.start_at.asc(), Event.id.asc())

    # Total matching rows before pagination, so a client (notably an agent
    # driving this through the MCP server) knows whether to keep paging without
    # having to fetch a page to find out.
    total_count = session.exec(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).one()
    response.headers["X-Total-Count"] = str(
        total_count[0] if isinstance(total_count, tuple) else total_count
    )

    stmt = stmt.offset(offset).limit(limit)
    results = session.exec(stmt).all()

    # Unpack results — shape differs depending on whether distance column is present.
    events_with_distance: list[tuple[Event, float | None]] = []
    if has_geo:
        for row in results:
            event, distance_meters = row
            events_with_distance.append((event, distance_meters))
    else:
        for row in results:
            events_with_distance.append((row, None))

    counts = _people_interested_counts(
        session=session,
        event_ids=[int(ev.id or 0) for ev, _ in events_with_distance if ev.id is not None],
    )

    serialized: list[EventResponse] = []
    for event, distance_meters in events_with_distance:
        event_resp = _serialize_event(
            event, people_interested=counts.get(int(event.id or 0), 0)
        )
        if distance_meters is not None:
            event_resp.distance_miles = round(distance_meters / 1609.34, 2)
        serialized.append(event_resp)
    return serialized


@router.get(
    "/events/{event_id}",
    response_model=EventDetailResponse,
    operation_id="getEvent",
    summary="Get one event with provenance detail",
)
def get_event(
    *,
    event_id: int,
    session: Session = Depends(get_session),
) -> EventDetailResponse:
    """Return a single event, including which source it came from and when.

    Agents relaying an event to a person need to cite it (``external_url``,
    ``source_name``) and qualify its freshness (``first_seen_at``), which the
    list endpoint does not carry.
    """
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")

    counts = _people_interested_counts(session=session, event_ids=[event_id])
    base = _serialize_event(event, people_interested=counts.get(event_id, 0))
    return EventDetailResponse(
        **base.model_dump(),
        first_seen_at=event.created_at,
        updated_at=event.updated_at,
        source_name=event.source_name,
        source_tier=event.source_tier,
        raw_address=event.raw_address,
    )


@router.put(
    "/users/me/preferences",
    response_model=InterestResponse,
    operation_id="setPreferences",
    summary="Replace the current user's explicit vibe preferences",
)
def set_preferences(
    *,
    payload: PreferencesRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> InterestResponse:
    user.preferred_vibes = list(payload.preferred_vibes)
    # Replacing explicit choices must also remove their old derived weights.
    # Event engagement remains a separate behavioral signal.
    session.execute(delete(UserSignal).where(
        UserSignal.user_id == user.id,
        UserSignal.signal_type.in_(["like", "onboarding"]),
        UserSignal.event_id.is_(None),
    ))
    session.add(user)
    session.commit()
    session.refresh(user)
    return InterestResponse(user_id=int(user.id), saved_event_ids=list(user.saved_event_ids),
                            preferred_vibes=list(user.preferred_vibes))


@router.post(
    "/users/me/interests",
    response_model=InterestResponse,
    operation_id="updateInterests",
    summary="Record a save/like/click signal for the current user",
)
def update_me_interests(
    *,
    payload: InterestRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> InterestResponse:

    if payload.action == "save":
        if payload.event_id is None:
            raise HTTPException(status_code=400, detail="event_id is required for action=save.")
        event = session.get(Event, payload.event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found.")
        if payload.event_id not in user.saved_event_ids:
            user.saved_event_ids.append(payload.event_id)
        _user_profile_service.record_signal(
            session=session,
            user_id=int(user.id or 0),
            signal_type="save",
            event_id=payload.event_id,
        )

    if payload.action == "like":
        if payload.vibe_tag is None or not payload.vibe_tag.strip():
            raise HTTPException(status_code=400, detail="vibe_tag is required for action=like.")
        tag = payload.vibe_tag.strip()
        if not tag.startswith("#"):
            tag = f"#{tag}"
        if tag not in user.preferred_vibes:
            user.preferred_vibes.append(tag)
        _user_profile_service.record_signal(
            session=session,
            user_id=int(user.id or 0),
            signal_type="like",
            vibe_tag=tag,
        )

    if payload.action in {"click", "external_ticket_click"}:
        if payload.event_id is None:
            raise HTTPException(
                status_code=400,
                detail="event_id is required for click and external_ticket_click actions.",
            )
        event = session.get(Event, payload.event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found.")
        _user_profile_service.record_signal(
            session=session,
            user_id=int(user.id or 0),
            signal_type=payload.action,
            event_id=payload.event_id,
        )

    session.add(user)
    session.commit()
    session.refresh(user)

    return InterestResponse(
        user_id=int(user.id or 0),
        saved_event_ids=list(user.saved_event_ids or []),
        preferred_vibes=list(user.preferred_vibes or []),
    )


@router.post(
    "/users/me/onboarding",
    response_model=OnboardingResponse,
    operation_id="submitOnboarding",
    summary="Extract vibe tags from a free-text onboarding answer",
    dependencies=[Depends(llm_rate_limit)],
)
async def set_onboarding_profile(
    *,
    payload: OnboardingRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OnboardingResponse:
    prompt = payload.perfect_saturday.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="perfect_saturday must not be empty.")
    extracted_tags = await _user_profile_service.extract_onboarding_tags(prompt)
    for tag in extracted_tags:
        if tag not in user.preferred_vibes:
            user.preferred_vibes.append(tag)
        _user_profile_service.record_signal(
            session=session,
            user_id=int(user.id or 0),
            signal_type="onboarding",
            vibe_tag=tag,
        )

    session.add(user)
    session.commit()
    session.refresh(user)

    return OnboardingResponse(
        user_id=int(user.id or 0),
        extracted_vibes=extracted_tags,
        preferred_vibes=list(user.preferred_vibes or []),
    )


@router.get(
    "/recommendations",
    response_model=list[RecommendationResponse],
    operation_id="getRecommendations",
    summary="Personalized event recommendations for the current user",
)
def get_recommendations(
    *,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[RecommendationResponse]:
    preferred_vibes = set(v.lower() for v in (user.preferred_vibes or []) if isinstance(v, str))
    profile_scores = _user_profile_service.compute_vibe_scores_for_user(
        session=session,
        user_id=int(user.id or 0),
        now=datetime.now(timezone.utc),
    )
    now_utc = datetime.now(timezone.utc)
    eligible = and_(
        func.coalesce(Event.end_at, Event.start_at) >= now_utc,
        Event.status == "scheduled",
    )
    # Rank lightweight scoring inputs in Postgres, including diversity, before
    # hydrating only the requested page of event descriptions/geometries.
    popularity = (
        select(UserSignal.event_id, func.count(func.distinct(UserSignal.user_id)))
        .join(Event, Event.id == UserSignal.event_id)
        .where(
            eligible,
            UserSignal.signal_type.in_(["save", "click", "external_ticket_click"]),
        )
        .group_by(UserSignal.event_id)
    ).subquery()
    popularity_count = func.coalesce(popularity.c[1], 0)
    raw_weights: dict[str, float] = {}
    for tag in {resolve_vibe_tag(v) for v in preferred_vibes} - {None}:
        raw_weights[tag] = 100.0
    for tag, value in profile_scores.items():
        key = resolve_vibe_tag(tag)
        if key:
            raw_weights[key] = raw_weights.get(key, 0.0) + value * 10.0
    raw_vibe = sum(
        (case((_canonical_tag_filter(tag), weight), else_=0.0) for tag, weight in raw_weights.items()),
        literal(0.0),
    )
    vibe = 100.0 * raw_vibe / (raw_vibe + 100.0)
    freshness = case(
        (Event.created_at >= now_utc - timedelta(hours=24), 100.0),
        (Event.created_at >= now_utc - timedelta(hours=48), 75.0),
        (Event.created_at >= now_utc - timedelta(days=7), 50.0),
        else_=25.0,
    )
    score = (
        vibe * _recommender_service.VIBE_WEIGHT
        + func.least(popularity_count * 10.0, 100.0) * _recommender_service.POPULARITY_WEIGHT
        + freshness * _recommender_service.FRESHNESS_WEIGHT
        + 100.0 * _recommender_service.DIVERSITY_WEIGHT
    )
    candidates = (
        select(
            Event.id, Event.start_at, Event.categories[0].as_string().label("category"),
            popularity_count.label("popularity"), raw_vibe.label("vibe"), score.label("score"),
        )
        .outerjoin(popularity, popularity.c.event_id == Event.id)
        .where(eligible)
    ).cte("recommendation_candidates")
    ranked = select(
        candidates,
        func.lag(candidates.c.category).over(
            order_by=(candidates.c.score.desc(), candidates.c.start_at, candidates.c.id)
        ).label("previous_category"),
    )
    if raw_weights:
        any_match = select(candidates.c.id).where(candidates.c.vibe > 0).exists()
        ranked = ranked.where(or_(candidates.c.vibe > 0, ~any_match))
    ranked = ranked.subquery()
    final_score = ranked.c.score - case(
        (and_(ranked.c.category.is_not(None), ranked.c.category == ranked.c.previous_category),
         _recommender_service.DIVERSITY_PENALTY),
        else_=0.0,
    )
    candidates_page = session.exec(
        select(Event, ranked.c.popularity, final_score)
        .join(ranked, ranked.c.id == Event.id)
        .order_by(final_score.desc(), Event.start_at.asc(), Event.id.asc())
        .offset(offset).limit(limit)
    ).all()
    upcoming_events = [event for event, _, _ in candidates_page]
    popularity_counts = {int(event.id): int(count) for event, count, _ in candidates_page}
    final_scores = {int(event.id): float(value) for event, _, value in candidates_page}

    scored_events: list[ScoredEvent] = _recommender_service.score_events(
        events=upcoming_events,
        user=user,
        user_vibe_scores=profile_scores,
        popularity_counts=popularity_counts,
        apply_diversity=False,
    )
    # SQL already ranked the full eligible corpus; never reapply a diversity
    # penalty to a page (its previous neighbor may live on the preceding page).
    for scored in scored_events:
        scored.total_score = final_scores[int(scored.event.id)]
    paged = sorted(scored_events, key=lambda item: (-item.total_score, item.event.start_at, item.event.id))

    recommendations: list[RecommendationResponse] = []
    counts = _people_interested_counts(
        session=session,
        event_ids=[int(se.event.id or 0) for se in paged if se.event.id is not None],
    )
    for se in paged:
        base = _serialize_event(
            se.event, people_interested=counts.get(int(se.event.id or 0), 0)
        )
        recommendations.append(
            RecommendationResponse(
                **base.model_dump(),
                match_score=int(round(se.total_score)),
                matched_vibes=se.matched_tags,
            )
        )
    return recommendations


@router.post(
    "/concierge/itinerary",
    response_model=ConciergeResponse,
    operation_id="buildItinerary",
    summary="Turn a natural-language request into a sequenced itinerary",
    dependencies=[Depends(llm_rate_limit)],
)
async def build_concierge_itinerary(
    *,
    payload: ConciergeRequest,
    session: Session = Depends(get_session),
    user: User | None = Depends(get_optional_user),
) -> ConciergeResponse:
    parsed = await parse_intent_async(payload.query)

    def _anchor_query(*, restrict_to_intent_hours: bool):
        stmt = select(Event).where(
            overlaps_window(parsed.window_start, parsed.window_end),
            Event.source_tier <= 2,
            Event.status == "scheduled",
        )
        hours = anchor_hour_range(parsed.intent) if restrict_to_intent_hours else None
        if hours is not None:
            # Compare in SF local time: the stored timestamps are UTC, so a
            # naive hour filter would drift by the offset.
            local_hour = func.extract(
                "hour", func.timezone(str(LOCAL_TZ), Event.start_at)
            )
            # An estimated 19:00 lands inside every evening intent's range, so
            # placeholders would out-compete events that really do start then.
            # The unrestricted fallback query below still considers them.
            stmt = stmt.where(
                Event.start_time_is_estimated.is_(False),
                local_hour >= hours[0],
                local_hour <= hours[1],
            )
        # No SQL limit: only one of these rows becomes the anchor, and the
        # choice is made by vibe ranking below. Cutting the set down to the
        # earliest `payload.limit` rows first (that field sizes the itinerary
        # payload, not the candidate pool) hid every later event from that
        # ranking.
        stmt = stmt.order_by(Event.start_at.asc())
        stmt = _apply_concierge_geography_filter(stmt, parsed.geography)
        return _apply_concierge_category_filter(stmt, parsed.category_focus)

    # Prefer an anchor that fits the intent's time of day; fall back to the
    # whole window rather than returning nothing when the day is thin.
    anchor_events = session.exec(_anchor_query(restrict_to_intent_hours=True)).all()
    if not anchor_events:
        anchor_events = session.exec(_anchor_query(restrict_to_intent_hours=False)).all()
    if anchor_events:
        vibe_scores = intent_vibe_profile(parsed.intent)
        if user is not None and user.id is not None:
            user_scores = _user_profile_service.compute_vibe_scores_for_user(
                session=session,
                user_id=int(user.id),
                now=datetime.now(timezone.utc),
            )
            for tag, score in user_scores.items():
                vibe_scores[tag] = vibe_scores.get(tag, 0.0) + score

        popularity_counts = _people_interested_counts(
            session=session,
            event_ids=[
                int(event.id) for event in anchor_events if event.id is not None
            ],
        )
        ranked_anchors = _recommender_service.score_events(
            events=list(anchor_events),
            user=user,
            user_vibe_scores=vibe_scores,
            popularity_counts=popularity_counts,
        )
        anchor = ranked_anchors[0].event if ranked_anchors else None
    else:
        anchor = None
    if anchor is None:
        return ConciergeResponse(
            intent=parsed.intent,
            timeframe=parsed.timeframe_label,
            geography=parsed.geography,
            category_focus=parsed.category_focus,
            anchor_event_id=None,
            itinerary=[],
        )

    anchor_lat, anchor_lng = _extract_lat_lng(anchor)
    if (anchor_lat is None or anchor_lng is None
            or anchor.location_confidence < DEFAULT_MIN_LOCATION_CONFIDENCE):
        support_events = []
    else:
        anchor_point = func.ST_SetSRID(
            func.ST_MakePoint(anchor_lng, anchor_lat), 4326
        )

        def _support_query(*, radius_miles: float):
            return (
                select(Event)
                .where(
                    Event.id != anchor.id,
                    overlaps_window(parsed.window_start, parsed.window_end),
                    Event.source_tier >= 3,
                    Event.status == "scheduled",
                    Event.start_time_is_estimated.is_(False),
                    Event.location_confidence >= DEFAULT_MIN_LOCATION_CONFIDENCE,
                    func.ST_DWithin(
                        cast(Event.location, Geography),
                        cast(anchor_point, Geography),
                        radius_miles * 1609.34,
                    ),
                )
                # No SQL limit, for the same reason as the anchor query above:
                # `sequence_itinerary` brackets the anchor, taking the last
                # support event before it and the first one after. Keeping only
                # the earliest rows threw away every post-anchor candidate as
                # soon as the pre-anchor ones filled the quota, so a night out
                # silently ended at the main event. The set is already bounded
                # by the intent window and the ST_DWithin radius.
                .order_by(Event.start_at.asc())
            )

        support_events = session.exec(_support_query(radius_miles=0.5)).all()
        if not support_events:
            support_events = session.exec(_support_query(radius_miles=1.0)).all()
    sequenced = sequence_itinerary(anchor=anchor, support_events=support_events)

    # The anchor and its support events are already loaded, so locations come
    # from memory rather than a second round of queries.
    events_by_id = {
        int(event.id): event
        for event in [anchor, *support_events]
        if event.id is not None
    }
    itinerary = _portable_stops(
        [
            (
                ItineraryStopResponse(
                    kind=item.kind,
                    event_id=item.event_id,
                    title=item.title,
                    start_at=item.start_at,
                    start_time_is_estimated=item.start_time_is_estimated,
                    end_at=item.end_at,
                    venue_name=item.venue_name,
                    external_url=item.external_url,
                    travel_buffer_minutes_before=item.travel_buffer_minutes_before,
                ),
                _event_location(events_by_id.get(item.event_id)),
            )
            for item in sequenced
        ]
    )
    title = itinerary_title(
        intent=parsed.intent,
        geography=parsed.geography,
        starts_at=itinerary[0].start_at if itinerary else None,
    )
    return ConciergeResponse(
        intent=parsed.intent,
        timeframe=parsed.timeframe_label,
        geography=parsed.geography,
        category_focus=parsed.category_focus,
        anchor_event_id=int(anchor.id or 0),
        itinerary=itinerary,
        title=title,
        text=render_itinerary_text(title=title, stops=itinerary),
    )


def _share_url_for(token: str) -> str:
    return f"/itinerary/{token}"


def _utc_datetime(value: datetime) -> datetime:
    # SQLite fixtures return naive timestamps; PostgreSQL stores timestamptz.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _itinerary_share_status(saved: SavedItinerary, now: datetime) -> Literal["active", "expired", "revoked"]:
    if saved.revoked_at is not None:
        return "revoked"
    return "expired" if _utc_datetime(saved.expires_at) <= now else "active"


def _portable_response(itinerary: SavedItinerary) -> PortableItineraryResponse:
    """Rehydrate a stored snapshot, recomputing links from the stored facts.

    Links are derived rather than stored so that improvements to how we build
    map URLs reach itineraries that were shared before the change.
    """
    stops = _portable_stops(
        [
            (
                ItineraryStopResponse(
                    kind=str(stop.get("kind") or "stop"),
                    event_id=int(stop.get("event_id") or 0),
                    title=str(stop.get("title") or "Untitled"),
                    start_at=datetime.fromisoformat(stop["start_at"]),
                    start_time_is_estimated=bool(
                        stop.get("start_time_is_estimated", False)
                    ),
                    end_at=(
                        datetime.fromisoformat(stop["end_at"])
                        if stop.get("end_at")
                        else None
                    ),
                    venue_name=stop.get("venue_name"),
                    external_url=stop.get("external_url"),
                    travel_buffer_minutes_before=int(
                        stop.get("travel_buffer_minutes_before") or 0
                    ),
                ),
                StopLocation(
                    venue_name=stop.get("venue_name"),
                    address=stop.get("address"),
                    lat=stop.get("lat"),
                    lng=stop.get("lng"),
                    location_confidence=float(
                        stop["location_confidence"]
                        if stop.get("location_confidence") is not None else 1.0
                    ),
                ),
            )
            for stop in (itinerary.stops or [])
        ]
    )
    share_url = _share_url_for(itinerary.share_token)
    return PortableItineraryResponse(
        share_token=itinerary.share_token,
        share_url=share_url,
        title=itinerary.title,
        intent=itinerary.intent,
        timeframe=itinerary.timeframe,
        geography=itinerary.geography,
        anchor_event_id=itinerary.anchor_event_id,
        created_at=_utc_datetime(itinerary.created_at),
        expires_at=_utc_datetime(itinerary.expires_at),
        itinerary=stops,
        text=render_itinerary_text(
            title=itinerary.title, stops=stops, share_url=share_url
        ),
    )


@_sharing_router.post(
    "/concierge/itinerary/share",
    response_model=PortableItineraryResponse,
    dependencies=[Depends(share_rate_limit)],
)
def share_concierge_itinerary(
    *,
    payload: ShareItineraryRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PortableItineraryResponse:
    """Freeze an owned itinerary and return a public link with a bounded lifetime.

    Takes the stops the caller is looking at rather than re-running the
    concierge: re-planning here would quietly hand back a different night than
    the one on screen. Titles, venues, and coordinates are re-read from the
    database so the public page only ever renders our own data.
    """
    requested_ids = [stop.event_id for stop in payload.stops]
    events_by_id = {
        int(event.id): event
        for event in session.exec(select(Event).where(Event.id.in_(requested_ids))).all()
        if event.id is not None
    }
    missing = [event_id for event_id in requested_ids if event_id not in events_by_id]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Unknown event ids: {sorted(set(missing))}"
        )

    snapshot: list[dict] = []
    for stop in payload.stops:
        event = events_by_id[stop.event_id]
        lat, lng = _extract_lat_lng(event)
        snapshot.append(
            {
                "kind": stop.kind,
                "event_id": int(event.id or 0),
                "title": event.title,
                "start_at": event.start_at.isoformat(),
                "start_time_is_estimated": bool(event.start_time_is_estimated),
                "end_at": event.end_at.isoformat() if event.end_at else None,
                "venue_name": event.venue_name,
                "address": event.raw_address,
                "lat": lat,
                "lng": lng,
                "location_confidence": (
                    event.location_confidence
                    if event.location_confidence is not None
                    else 1.0
                ),
                "external_url": event.external_url,
                "travel_buffer_minutes_before": max(
                    0, int(stop.travel_buffer_minutes_before)
                ),
            }
        )

    first_start = min(
        events_by_id[stop.event_id].start_at for stop in payload.stops
    )
    now = datetime.now(timezone.utc)
    saved = SavedItinerary(
        share_token=generate_share_token(),
        user_id=int(user.id),
        title=itinerary_title(
            intent=payload.intent,
            geography=payload.geography,
            starts_at=first_start,
        ),
        query="",
        intent=payload.intent,
        timeframe=payload.timeframe,
        geography=payload.geography,
        anchor_event_id=payload.anchor_event_id,
        stops=snapshot,
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days),
    )
    session.add(saved)
    session.commit()
    session.refresh(saved)
    return _portable_response(saved)


@_sharing_router.get("/shared/itineraries/{token}", response_model=PortableItineraryResponse)
def get_shared_itinerary(
    *,
    token: str,
    session: Session = Depends(get_session),
) -> PortableItineraryResponse:
    """Public read of a shared itinerary — no auth, so the link just works."""
    if not is_valid_share_token(token):
        raise HTTPException(status_code=404, detail="Itinerary not found")
    saved = session.exec(
        select(SavedItinerary).where(SavedItinerary.share_token == token)
    ).first()
    if saved is None or _itinerary_share_status(saved, datetime.now(timezone.utc)) != "active":
        raise HTTPException(status_code=404, detail="Itinerary not found")
    return _portable_response(saved)


@_sharing_router.get("/users/me/itineraries", response_model=list[OwnedItineraryResponse])
def list_owned_itineraries(
    *,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OwnedItineraryResponse]:
    saved = session.exec(
        select(SavedItinerary).where(SavedItinerary.user_id == user.id)
        .order_by(SavedItinerary.created_at.desc(), SavedItinerary.id.desc())
        .offset(offset).limit(limit)
    ).all()
    now = datetime.now(timezone.utc)
    return [OwnedItineraryResponse(
        share_token=item.share_token,
        share_url=_share_url_for(item.share_token),
        title=item.title,
        created_at=_utc_datetime(item.created_at),
        expires_at=_utc_datetime(item.expires_at),
        revoked_at=_utc_datetime(item.revoked_at) if item.revoked_at is not None else None,
        status=_itinerary_share_status(item, now),
    ) for item in saved]


@_sharing_router.delete("/users/me/itineraries/{token}", status_code=204)
def revoke_owned_itinerary(
    *,
    token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    if not is_valid_share_token(token):
        raise HTTPException(status_code=404, detail="Itinerary not found")
    saved = session.exec(select(SavedItinerary).where(
        SavedItinerary.share_token == token, SavedItinerary.user_id == user.id
    )).first()
    if saved is None:
        raise HTTPException(status_code=404, detail="Itinerary not found")
    # Repeated/concurrent revocation leaves the original timestamp intact.
    session.execute(update(SavedItinerary).where(
        SavedItinerary.id == saved.id,
        SavedItinerary.user_id == user.id,
        SavedItinerary.revoked_at.is_(None),
    ).values(revoked_at=datetime.now(timezone.utc)))
    session.commit()
    return Response(status_code=204)


router.include_router(_sharing_router)
