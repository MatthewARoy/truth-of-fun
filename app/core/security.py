from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.user import User

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
