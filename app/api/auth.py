from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, update
from sqlmodel import Session, select

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.ratelimit import auth_rate_limit
from app.core.security import get_current_user
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services.email import send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes.")
        return value


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# Keep unknown-user and wrong-password login paths close in cost so the API
# does not become a high-signal account-enumeration timing oracle.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"not-a-real-user-password", bcrypt.gensalt()).decode(
    "utf-8"
)


def _create_access_token(*, user: User, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user.email,
        "user_id": user.id,
        # Checked against users.token_version on every request; see
        # revoke_sessions().
        "ver": int(user.token_version or 0),
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def _user_by_email(session: Session, email: str) -> User | None:
    """Case-insensitive lookup: "Bob@x.com" and "bob@x.com" are one mailbox,
    and must not become two accounts (or a failed login)."""
    return session.exec(
        select(User).where(func.lower(User.email) == email.strip().lower()).order_by(User.id)
    ).first()


def revoke_sessions(user: User) -> None:
    """Invalidate every JWT issued to *user* so far (caller commits)."""
    user.token_version = int(user.token_version or 0) + 1


def _auth_response(user: User, settings: Settings) -> AuthResponse:
    return AuthResponse(
        access_token=_create_access_token(user=user, settings=settings),
        user_id=int(user.id or 0),
        email=user.email,
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="register",
    summary="Create an account and return a JWT",
    dependencies=[Depends(auth_rate_limit)],
)
def register(
    *,
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    existing = _user_by_email(session, payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    user = User(
        email=payload.email,
        hashed_password=_hash_password(payload.password),
        full_name=payload.full_name,
        role="user",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    token = _create_access_token(user=user, settings=settings)
    return AuthResponse(
        access_token=token,
        user_id=int(user.id or 0),
        email=user.email,
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    operation_id="login",
    summary="Exchange credentials for a JWT",
    dependencies=[Depends(auth_rate_limit)],
)
def login(
    *,
    payload: LoginRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    user = _user_by_email(session, payload.email)
    password_hash = (
        user.hashed_password
        if user is not None and user.hashed_password
        else _DUMMY_PASSWORD_HASH
    )
    password_valid = _verify_password(payload.password, password_hash)
    if user is None or not user.hashed_password or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    token = _create_access_token(user=user, settings=settings)
    return AuthResponse(
        access_token=token,
        user_id=int(user.id or 0),
        email=user.email,
    )


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12)

    @field_validator("new_password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes.")
        return value


class MessageResponse(BaseModel):
    detail: str


_RESET_ACCEPTED = (
    "If an account exists for that address, a password reset link is on its way."
)
# A person legitimately needs one or two links; more than this within the
# validity window is someone using the endpoint to flood a mailbox.
_MAX_ACTIVE_RESET_TOKENS = 3


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestPasswordReset",
    summary="Email a single-use password reset link",
    dependencies=[Depends(auth_rate_limit)],
)
def request_password_reset(
    *,
    payload: PasswordResetRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    """Always answers 202 with the same body, whether or not the address has
    an account, so the endpoint cannot be used to discover who is registered."""
    user = _user_by_email(session, payload.email)
    if user is None or not user.is_active or user.id is None:
        return MessageResponse(detail=_RESET_ACCEPTED)

    now = datetime.now(timezone.utc)
    active = session.exec(
        select(func.count())
        .select_from(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    ).one()
    if int(active) >= _MAX_ACTIVE_RESET_TOKENS:
        return MessageResponse(detail=_RESET_ACCEPTED)

    token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            user_id=int(user.id),
            token_hash=_hash_reset_token(token),
            expires_at=now + timedelta(minutes=settings.password_reset_expire_minutes),
        )
    )
    session.commit()

    link = f"{settings.public_web_url.rstrip('/')}/reset-password?token={token}"
    sent = send_email(
        to=user.email,
        subject="Reset your Truth of Fun password",
        body=(
            "Someone asked to reset the password for this Truth of Fun account.\n\n"
            f"Choose a new password here (valid for {settings.password_reset_expire_minutes} minutes):\n"
            f"{link}\n\n"
            "If this wasn't you, ignore this email — your password has not changed.\n"
        ),
        settings=settings,
    )
    if not sent and settings.app_env == "development":
        # Local development has no mail server; print the link so the flow is
        # usable. Never outside development: the link is a credential.
        logger.info("Password reset link (development only): %s", link)
    return MessageResponse(detail=_RESET_ACCEPTED)


@router.post(
    "/password-reset/confirm",
    response_model=AuthResponse,
    operation_id="confirmPasswordReset",
    summary="Set a new password with an emailed reset token",
    dependencies=[Depends(auth_rate_limit)],
)
def confirm_password_reset(
    *,
    payload: PasswordResetConfirm,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    now = datetime.now(timezone.utc)
    # Claim the token atomically: two concurrent confirmations with the same
    # link cannot both succeed.
    user_id = session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == _hash_reset_token(payload.token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(PasswordResetToken.user_id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    user = session.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        # Nothing is committed on this path, so a claimed-but-unusable token
        # is released when the request's session closes.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Request a new one.",
        )

    user.hashed_password = _hash_password(payload.new_password)
    # Whoever knew the old password — or held a stolen token — is signed out.
    revoke_sessions(user)
    # Any other outstanding links die with the one that was used.
    session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return _auth_response(user, settings)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logoutEverywhere",
    summary="Revoke every token issued to this account so far",
)
def logout_everywhere(
    *,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    revoke_sessions(user)
    session.add(user)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
