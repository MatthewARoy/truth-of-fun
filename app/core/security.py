from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

import jwt
from fastapi import Depends, HTTPException, status
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


def _build_dev_principal() -> InternalPrincipal:
    return InternalPrincipal(
        client_id="local-dev-client",
        subject="local-dev-subject",
        scopes={"internal:secrets:read", "internal:secrets:write"},
        raw_claims={"mode": "aaim_disabled"},
    )


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
        algorithms=settings.aaim_jwt_algorithms,
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
    signing_key = _get_jwk_client(settings.aaim_oidc_jwks_url).get_signing_key_from_jwt(token)
    options = {"verify_aud": settings.aaim_oidc_audience is not None}
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=settings.aaim_jwt_algorithms,
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
            detail=f"Token verification failed: {exc}",
        ) from exc


def get_internal_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> InternalPrincipal:
    if not settings.aaim_enabled:
        return _build_dev_principal()

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
