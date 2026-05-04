from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def _create_access_token(*, user: User, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user.email,
        "user_id": user.id,
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    *,
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    existing = session.exec(select(User).where(User.email == payload.email)).first()
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


@router.post("/login", response_model=AuthResponse)
def login(
    *,
    payload: LoginRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if user is None or not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not _verify_password(payload.password, user.hashed_password):
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
