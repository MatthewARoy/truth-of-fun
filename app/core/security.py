from __future__ import annotations

import secrets
import hashlib
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select
from sqlalchemy import update

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.user import User
from app.models.agent_token import AgentToken
from app.core.ratelimit import SlidingWindowLimiter

_bearer = HTTPBearer(auto_error=False)


@dataclass
class InternalPrincipal:
    client_id: str
    subject: str
    scopes: set[str]
    raw_claims: dict[str, Any]


@lru_cache(maxsize=8)
def _get_jwk_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url)


def _coerce_scopes(claims: dict[str, Any]) -> set[str]:
    scopes: set[str] = set()
    scope = claims.get("scope")
    if isinstance(scope, str):
        scopes.update(item.strip() for item in scope.split(" ") if item.strip())
    scp = claims.get("scp")
    if isinstance(scp, list):
        scopes.update(item.strip() for item in scp if isinstance(item, str) and item.strip())
    return scopes


def _verify_hs256_token(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.aaim_jwt_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AAIM shared JWT secret is not configured.",
        )
    options = {"verify_aud": settings.aaim_oidc_audience is not None}
    return jwt.decode(
        token,
        settings.aaim_jwt_shared_secret,
        algorithms=["HS256"],
        audience=settings.aaim_oidc_audience,
        issuer=settings.aaim_oidc_issuer,
        options=options,
    )


def _verify_jwks_token(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.aaim_oidc_jwks_url:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AAIM JWKS URL is not configured.",
        )
    asymmetric_algorithms = [
        algorithm
        for algorithm in settings.aaim_jwt_algorithms
        if algorithm.upper() != "HS256"
    ]
    if not asymmetric_algorithms:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No asymmetric AAIM JWT algorithm is configured.",
        )
    signing_key = _get_jwk_client(settings.aaim_oidc_jwks_url).get_signing_key_from_jwt(token)
    options = {"verify_aud": settings.aaim_oidc_audience is not None}
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=asymmetric_algorithms,
        audience=settings.aaim_oidc_audience,
        issuer=settings.aaim_oidc_issuer,
        options=options,
    )


def _decode_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        if settings.aaim_jwt_shared_secret:
            return _verify_hs256_token(token, settings)
        return _verify_jwks_token(token, settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed.",
        ) from exc


def get_internal_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> InternalPrincipal:
    if not settings.aaim_enabled:
        # With AAIM disabled (the default), the internal secrets API is
        # unreachable rather than open: a dev principal here would hand raw
        # provider keys to any unauthenticated caller.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Internal secrets API is disabled (AAIM_ENABLED=false).",
        )

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    claims = _decode_token(credentials.credentials, settings)
    client_id = claims.get("client_id") or claims.get("azp") or claims.get("sub")
    subject = claims.get("sub")
    if not isinstance(client_id, str) or not client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing client identity.",
        )
    if not isinstance(subject, str) or not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject.",
        )

    return InternalPrincipal(
        client_id=client_id,
        subject=subject,
        scopes=_coerce_scopes(claims),
        raw_claims=claims,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> User:
    """Authenticate an end-user via a Bearer JWT and return the User record."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

    email: str | None = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject.",
        )

    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    return user


@dataclass(frozen=True)
class Actor:
    user: User
    kind: str
    scopes: frozenset[str]
    token_id: int | None = None

    @property
    def created_via(self) -> str:
        return f"agent:{self.token_id}" if self.kind == "agent" else "user"


_agent_limiter = SlidingWindowLimiter(name="agent", limit=120, window_seconds=60)
_PAT = re.compile(r"tof_pat_([0-9a-f]{12})_([A-Za-z0-9_-]{43})", re.ASCII)


def get_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> Actor:
    if credentials is None or not credentials.credentials:
        raise HTTPException(401, "Missing bearer token.")
    raw = credentials.credentials
    if not raw.startswith("tof_pat_"):
        return Actor(user=get_current_user(credentials, settings, session), kind="user", scopes=frozenset({"*"}))
    match = _PAT.fullmatch(raw)
    if match is None:
        raise HTTPException(401, "Invalid agent token.")
    token = session.exec(select(AgentToken).where(AgentToken.token_prefix == match[1])).first()
    if token is None or not secrets.compare_digest(token.token_hash, hashlib.sha256(raw.encode()).hexdigest()):
        raise HTTPException(401, "Invalid agent token.")
    now = datetime.now(timezone.utc)
    expires = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=timezone.utc)
    if token.revoked_at is not None or expires <= now:
        raise HTTPException(401, "Invalid agent token.")
    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(403, "Account is deactivated.")
    retry_after = _agent_limiter.hit(str(token.id))
    if retry_after is not None:
        raise HTTPException(429, "Agent rate limit exceeded.", headers={"Retry-After": str(max(1, int(retry_after + 1)))})
    # Atomic increment with a second validity check closes a revoke-vs-auth
    # race. Revocation blocks subsequent admissions; admitted work may finish.
    admitted = session.execute(update(AgentToken).where(AgentToken.id == token.id,
        AgentToken.revoked_at.is_(None), AgentToken.expires_at > now).values(
        request_count=AgentToken.request_count + 1, last_used_at=now).returning(AgentToken.id).execution_options(synchronize_session=False)).scalar_one_or_none()
    if admitted is None:
        session.rollback()
        raise HTTPException(401, "Invalid agent token.")
    actor = Actor(user=user, kind="agent", scopes=frozenset(token.scopes), token_id=token.id)
    session.commit()  # Usage admission is durable even if the route later refuses its scope.
    return actor


def require_scope(*scopes: str):
    def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.kind != "user" and not set(scopes).issubset(actor.scopes):
            raise HTTPException(403, "Missing required scope: " + ", ".join(scopes))
        return actor
    return dependency


def get_optional_read_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings), session: Session = Depends(get_session),
) -> Actor | None:
    if credentials is None:
        return None
    actor = get_actor(request, credentials, settings, session)
    if actor.kind == "agent" and "events:read" not in actor.scopes:
        raise HTTPException(403, "Missing required scope: events:read")
    return actor


def get_optional_planning_user(actor: Actor | None = Depends(get_optional_read_actor)) -> User | None:
    # events-only credentials may plan against the public corpus without
    # gaining access to personal saved/preference signals.
    return actor.user if actor and (actor.kind == "user" or "profile:read" in actor.scopes) else None


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> User | None:
    """Return the authenticated User if a valid token is present, otherwise None."""
    if credentials is None or not credentials.credentials:
        return None

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        return None

    email: str | None = payload.get("sub")
    if not email:
        return None

    user = session.exec(select(User).where(User.email == email)).first()
    if user is None or not user.is_active:
        return None
    return user


def require_internal_scope(scope: str) -> Callable[[InternalPrincipal], InternalPrincipal]:
    def _dependency(
        principal: InternalPrincipal = Depends(get_internal_principal),
    ) -> InternalPrincipal:
        if scope and scope not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {scope}",
            )
        return principal

    return _dependency


OPS_TOKEN_HEADER = "X-Ops-Token"


def require_ops_token(
    ops_token: str | None = Header(default=None, alias=OPS_TOKEN_HEADER),
    settings: Settings = Depends(get_settings),
) -> None:
    """Gate the operator-only health surface behind a shared secret.

    A separate header rather than ``Authorization`` on purpose: the API client
    already puts the *user's* JWT there, so an operator who is also signed in
    would otherwise have to choose between the two.

    Three states, and the third is the one that matters:

    - development with no token configured: open, so ``make demo`` and the
      local admin page work with no setup.
    - any environment with a token configured: the header must match it.
    - anything other than development with no token configured: refused. An
      unconfigured deployment fails closed rather than publishing which
      scrapers are broken to anyone who guesses the path.
    """
    if not settings.ops_token:
        if settings.app_env == "development":
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This endpoint is disabled because OPS_TOKEN is not configured. "
                "Set it to enable operator access."
            ),
        )
    # Compare bytes, not str: Starlette decodes header values as latin-1, so a
    # client can hand us a non-ASCII str, and compare_digest raises TypeError on
    # those — turning a garbage token into a 500 instead of a 403.
    if ops_token is None or not secrets.compare_digest(
        ops_token.encode("utf-8"), settings.ops_token.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"A valid {OPS_TOKEN_HEADER} header is required.",
        )
