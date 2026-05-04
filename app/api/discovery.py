from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from geoalchemy2 import Geography
from sqlalchemy import cast, func, text
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import get_current_user, get_optional_user
from app.models.event import Event
from app.models.user import User
from app.models.user_signal import UserSignal
from app.services.concierge import parse_intent_prompt, sequence_itinerary
from app.services.recommender import RecommenderService, ScoredEvent
from app.services.user_profile import UserProfileService

router = APIRouter(tags=["discovery"])
_user_profile_service = UserProfileService()
_recommender_service = RecommenderService()


class EventResponse(BaseModel):
    id: int
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime | None
    external_url: str | None
    venue_name: str | None
    tags: list[str]
    categories: list[str]
    image_url: str | None
    price: float | None
    currency: str | None
    status: str
    friends_interested: int = 0
    distance_miles: float | None = None


class RecommendationResponse(EventResponse):
    match_score: int
    matched_vibes: list[str]


class ConciergeRequest(BaseModel):
    query: str
    limit: int = 25


class ItineraryStopResponse(BaseModel):
    kind: str
    event_id: int
    title: str
    start_at: datetime
    end_at: datetime | None
    venue_name: str | None
    external_url: str | None
    travel_buffer_minutes_before: int


class ConciergeResponse(BaseModel):
    intent: str
    timeframe: str
    geography: str | None
    anchor_event_id: int | None
    itinerary: list[ItineraryStopResponse]


class InterestRequest(BaseModel):
    action: Literal["save", "like", "click", "external_ticket_click"]
    event_id: int | None = None
    vibe_tag: str | None = None


class InterestResponse(BaseModel):
    user_id: int
    saved_event_ids: list[int]
    preferred_vibes: list[str]


class OnboardingRequest(BaseModel):
    perfect_saturday: str


class OnboardingResponse(BaseModel):
    user_id: int
    extracted_vibes: list[str]
    preferred_vibes: list[str]


def _serialize_event(event: Event, *, friends_interested: int = 0) -> EventResponse:
    return EventResponse(
        id=int(event.id or 0),
        title=event.title,
        description=event.description,
        start_at=event.start_at,
        end_at=event.end_at,
        external_url=event.external_url,
        venue_name=event.venue_name,
        tags=list(event.tags or []),
        categories=list(event.categories or []),
        image_url=event.image_url,
        price=float(event.price) if event.price is not None else None,
        currency=event.currency,
        status=event.status,
        friends_interested=friends_interested,
    )


def _score_event_for_user(
    *,
    event_tags: list[str],
    preferred_vibes: set[str],
    profile_scores: dict[str, float],
) -> tuple[float, list[str]]:
    if not event_tags:
        return 0.0, []

    tag_map = {tag.lower(): tag for tag in event_tags}
    matched_keys = sorted(set(tag_map.keys()).intersection(preferred_vibes))
    weighted_score = sum(profile_scores.get(key, 0.0) for key in tag_map.keys())

    if not matched_keys and weighted_score <= 0:
        return 0.0, []

    matched = [tag_map[key] for key in matched_keys]
    profile_matched_keys = [key for key in tag_map.keys() if profile_scores.get(key, 0.0) > 0]
    for key in profile_matched_keys:
        original = tag_map[key]
        if original not in matched:
            matched.append(original)

    # Explicit likes drive relevance first, then decayed behavioral profile weight.
    score = (len(matched_keys) * 100.0) + (weighted_score * 10.0)
    return score, matched


def _apply_concierge_geography_filter(stmt: object, geography: str | None) -> object:
    if not geography:
        return stmt
    geography_like = f"%{geography}%"
    return stmt.where(
        Event.venue_name.ilike(geography_like)
        | Event.raw_address.ilike(geography_like)
        | Event.title.ilike(geography_like)
    )


def _friends_interested_counts(*, session: Session, event_ids: list[int]) -> dict[int, int]:
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


def _apply_time_preset(*, time_preset: str | None) -> tuple[datetime | None, datetime | None]:
    if not time_preset:
        return None, None
    now = datetime.now(timezone.utc)
    if time_preset == "tonight":
        end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=timezone.utc)
        return now, end_of_day
    if time_preset == "this_weekend":
        days_to_friday = (4 - now.weekday()) % 7
        friday = (now + timedelta(days=days_to_friday)).replace(hour=17, minute=0, second=0, microsecond=0)
        monday = (friday + timedelta(days=3)).replace(hour=6, minute=0, second=0, microsecond=0)
        return friday, monday
    return None, None


def _location_keyword_for_preset(location_preset: str | None) -> str | None:
    if location_preset == "sf":
        return "San Francisco"
    if location_preset == "oakland":
        return "Oakland"
    if location_preset == "san_jose":
        return "San Jose"
    return None


@router.get("/events", response_model=list[EventResponse])
def search_events(
    *,
    session: Session = Depends(get_session),
    q: str | None = Query(default=None, description="Full-text search query"),
    lat: float | None = Query(default=None, description="Latitude for geo search"),
    lng: float | None = Query(default=None, description="Longitude for geo search"),
    radius_miles: float | None = Query(default=None, gt=0, description="Search radius miles"),
    vibe_tag: str | None = Query(default=None, description="Filter by vibe tag"),
    time_preset: Literal["tonight", "this_weekend"] | None = Query(
        default=None,
        description="Friendly time filter for quick UI controls",
    ),
    location_preset: Literal["sf", "oakland", "san_jose"] | None = Query(
        default=None,
        description="Friendly location filter for quick UI controls",
    ),
    start_at: datetime | None = Query(default=None, description="Start time lower bound"),
    end_at: datetime | None = Query(default=None, description="Start time upper bound"),
    include_past: bool = Query(False, description="Include past events in results"),
    sort_by: Literal["date", "distance"] = Query(
        "date", description="Sort order: 'date' (default) or 'distance' (requires lat/lng)"
    ),
    status: str | None = Query(None, description="Filter by event status"),
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
        stmt = stmt.where(Event.start_at >= func.now())
    if status is not None:
        stmt = stmt.where(Event.status == status)

    preset_start, preset_end = _apply_time_preset(time_preset=time_preset)
    start_bound = start_at or preset_start
    end_bound = end_at or preset_end

    if start_bound is not None:
        stmt = stmt.where(Event.start_at >= start_bound)
    if end_bound is not None:
        stmt = stmt.where(Event.start_at <= end_bound)
    if vibe_tag:
        stmt = stmt.where(Event.tags.contains([vibe_tag]))

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

    # Sort order: distance (when geo available) or date (default / fallback).
    if sort_by == "distance" and has_geo:
        stmt = stmt.order_by(distance_expr.asc())
    else:
        stmt = stmt.order_by(Event.start_at.asc())

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

    counts = _friends_interested_counts(
        session=session,
        event_ids=[int(ev.id or 0) for ev, _ in events_with_distance if ev.id is not None],
    )

    response: list[EventResponse] = []
    for event, distance_meters in events_with_distance:
        event_resp = _serialize_event(
            event, friends_interested=counts.get(int(event.id or 0), 0)
        )
        if distance_meters is not None:
            event_resp.distance_miles = round(distance_meters / 1609.34, 2)
        response.append(event_resp)
    return response


@router.post("/users/me/interests", response_model=InterestResponse)
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


@router.post("/users/me/onboarding", response_model=OnboardingResponse)
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


@router.get("/recommendations", response_model=list[RecommendationResponse])
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
    if not preferred_vibes and not profile_scores:
        return []

    now_utc = datetime.now(timezone.utc)
    stmt = select(Event).where(Event.start_at >= now_utc).order_by(Event.start_at.asc())
    upcoming_events = session.exec(stmt).all()

    # Popularity counts: one aggregated query instead of loading all signals.
    pop_rows = session.exec(
        select(UserSignal.event_id, func.count())
        .where(UserSignal.event_id.isnot(None))
        .group_by(UserSignal.event_id)
    ).all()
    popularity_counts: dict[int, int] = {
        int(eid): int(cnt) for eid, cnt in pop_rows if eid is not None
    }

    scored_events: list[ScoredEvent] = _recommender_service.score_events(
        events=upcoming_events,
        user=user,
        user_vibe_scores=profile_scores,
        popularity_counts=popularity_counts,
    )

    # Filter out events with no signal at all (vibe_score <= 0 and no matched tags).
    scored_events = [se for se in scored_events if se.vibe_score > 0 or se.matched_tags]

    paged = scored_events[offset : offset + limit]

    recommendations: list[RecommendationResponse] = []
    counts = _friends_interested_counts(
        session=session,
        event_ids=[int(se.event.id or 0) for se in paged if se.event.id is not None],
    )
    for se in paged:
        base = _serialize_event(
            se.event, friends_interested=counts.get(int(se.event.id or 0), 0)
        )
        recommendations.append(
            RecommendationResponse(
                **base.model_dump(),
                match_score=int(round(se.total_score)),
                matched_vibes=se.matched_tags,
            )
        )
    return recommendations


@router.post("/concierge/itinerary", response_model=ConciergeResponse)
def build_concierge_itinerary(
    *,
    payload: ConciergeRequest,
    session: Session = Depends(get_session),
) -> ConciergeResponse:
    parsed = parse_intent_prompt(payload.query)
    limit = max(3, min(int(payload.limit), 100))

    anchor_stmt = (
        select(Event)
        .where(
            Event.start_at >= parsed.window_start,
            Event.start_at <= parsed.window_end,
            Event.source_tier <= 2,
        )
        .order_by(Event.start_at.asc())
        .limit(limit)
    )
    anchor_stmt = _apply_concierge_geography_filter(anchor_stmt, parsed.geography)
    anchor_events = session.exec(anchor_stmt).all()
    anchor = anchor_events[0] if anchor_events else None
    if anchor is None:
        return ConciergeResponse(
            intent=parsed.intent,
            timeframe=parsed.timeframe_label,
            geography=parsed.geography,
            anchor_event_id=None,
            itinerary=[],
        )

    radius_meters = 0.5 * 1609.34
    support_stmt = (
        select(Event)
        .where(
            Event.id != anchor.id,
            Event.start_at >= parsed.window_start,
            Event.start_at <= parsed.window_end,
            Event.source_tier >= 3,
            func.ST_DWithin(
                func.Geography(Event.location),
                func.Geography(anchor.location),
                radius_meters,
            ),
        )
        .order_by(Event.start_at.asc())
        .limit(limit)
    )
    support_events = session.exec(support_stmt).all()
    sequenced = sequence_itinerary(anchor=anchor, support_events=support_events)

    itinerary = [
        ItineraryStopResponse(
            kind=item.kind,
            event_id=item.event_id,
            title=item.title,
            start_at=item.start_at,
            end_at=item.end_at,
            venue_name=item.venue_name,
            external_url=item.external_url,
            travel_buffer_minutes_before=item.travel_buffer_minutes_before,
        )
        for item in sequenced
    ]
    return ConciergeResponse(
        intent=parsed.intent,
        timeframe=parsed.timeframe_label,
        geography=parsed.geography,
        anchor_event_id=int(anchor.id or 0),
        itinerary=itinerary,
    )
