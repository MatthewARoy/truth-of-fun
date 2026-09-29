"""User-JWT-only token lifecycle. Raw secrets are returned once at creation."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.ratelimit import auth_rate_limit
from app.core.security import get_current_user, Actor, require_scope
from app.models.agent_token import AgentToken
from app.models.user import User
from app.services.user_profile import UserProfileService

router = APIRouter(prefix="/users/me", tags=["agent-access"])
AgentScope = Literal["events:read", "profile:read", "signals:write", "plans:read"]


class MintTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[AgentScope] = Field(min_length=1, max_length=4)
    expires_in_days: int = Field(default=30, ge=1, le=365)

    @field_validator("name")
    @classmethod
    def plain_name(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Token name must be nonempty plain text without control characters")
        return value.strip()


class TokenResponse(BaseModel):
    id: int
    name: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    request_count: int


class MintTokenResponse(TokenResponse):
    token: str


def _summary(token: AgentToken) -> dict:
    return {field: getattr(token, field) for field in TokenResponse.model_fields}


@router.post("/tokens", response_model=MintTokenResponse, status_code=201,
    operation_id="mintAgentToken", summary="Mint a scoped agent token (user JWT only)",
    dependencies=[Depends(auth_rate_limit)])
def mint_token(payload: MintTokenRequest, response: Response,
    session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    now = datetime.now(timezone.utc)
    # Serialize concurrent minting by this owner on PostgreSQL.
    session.exec(select(User).where(User.id == user.id).with_for_update()).one()
    active = session.exec(select(AgentToken.id).where(AgentToken.user_id == user.id,
        AgentToken.revoked_at.is_(None), AgentToken.expires_at > now)).all()
    if len(active) >= 50:
        raise HTTPException(409, "Revoke an active token before creating another (limit 50).")
    prefix = secrets.token_hex(6)
    raw = f"tof_pat_{prefix}_{secrets.token_urlsafe(32)}"
    token = AgentToken(user_id=int(user.id), name=payload.name, token_prefix=prefix,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=sorted(set(payload.scopes)),
        created_at=now, expires_at=now + timedelta(days=payload.expires_in_days))
    session.add(token)
    session.commit()
    session.refresh(token)
    return MintTokenResponse(**_summary(token), token=raw)


@router.get("/tokens", response_model=list[TokenResponse], operation_id="listAgentTokens",
    summary="List token metadata and usage (user JWT only)")
def list_tokens(response: Response, limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0), session: Session = Depends(get_session),
    user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    rows = session.exec(select(AgentToken).where(AgentToken.user_id == user.id)
        .order_by(AgentToken.created_at.desc(), AgentToken.id.desc()).offset(offset).limit(limit)).all()
    return [TokenResponse(**_summary(row)) for row in rows]


@router.delete("/tokens/{token_id}", status_code=204, operation_id="revokeAgentToken",
    summary="Revoke an owned agent token (user JWT only)")
def revoke_token(token_id: int, session: Session = Depends(get_session),
    user: User = Depends(get_current_user)):
    token = session.exec(select(AgentToken).where(AgentToken.id == token_id,
        AgentToken.user_id == user.id).with_for_update()).first()
    if token is None:
        raise HTTPException(404, "Token not found.")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        session.add(token)
        session.commit()
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


class ProfileResponse(BaseModel):
    user_id: int
    preferred_vibes: list[str]
    saved_event_ids: list[int]
    vibe_scores: dict[str, float]


@router.get("", response_model=ProfileResponse, operation_id="getMyProfile",
    summary="Read your profile and learned vibe weights")
def get_profile(response: Response, session: Session = Depends(get_session),
    actor: Actor = Depends(require_scope("profile:read"))):
    response.headers["Cache-Control"] = "private, no-store"
    user = actor.user
    return ProfileResponse(user_id=int(user.id), preferred_vibes=list(user.preferred_vibes),
        saved_event_ids=list(user.saved_event_ids),
        vibe_scores=UserProfileService().compute_vibe_scores_for_user(session=session, user_id=int(user.id)))
