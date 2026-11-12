"""Self-service account management: password, data export, deletion.

All of these require the user's own JWT — never a delegated agent token: an
agent that can read events must not be able to change a password or delete
the account it was lent access to.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from app.api.auth import (
    AuthResponse,
    _auth_response,
    _hash_password,
    _verify_password,
    revoke_sessions,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.ratelimit import auth_rate_limit
from app.core.security import get_current_user
from app.models.user import User
from app.services.account import delete_account, export_account

router = APIRouter(prefix="/users/me", tags=["account"])


def _require_password(user: User, password: str) -> None:
    if not user.hashed_password or not _verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That password is not correct.",
        )


class _PasswordBody(BaseModel):
    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def fits_bcrypt(cls, value: Any) -> Any:
        if isinstance(value, str) and len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes.")
        return value


class ChangePasswordRequest(_PasswordBody):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=12)


class DeleteAccountRequest(_PasswordBody):
    password: str = Field(min_length=1)


@router.post(
    "/password",
    response_model=AuthResponse,
    operation_id="changePassword",
    summary="Change your password and sign out every other session",
    dependencies=[Depends(auth_rate_limit)],
)
def change_password(
    *,
    payload: ChangePasswordRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> AuthResponse:
    _require_password(user, payload.current_password)
    user.hashed_password = _hash_password(payload.new_password)
    revoke_sessions(user)
    session.add(user)
    session.commit()
    session.refresh(user)
    # The caller's own token was just revoked with the rest; hand back a new one.
    return _auth_response(user, settings)


@router.get(
    "/export",
    operation_id="exportMyData",
    summary="Download everything stored about your account",
)
def export_my_data(
    *,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="truth-of-fun-data.json"'
    return export_account(session, user)


@router.post(
    "/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteMyAccount",
    summary="Permanently delete your account and its data",
    dependencies=[Depends(auth_rate_limit)],
)
def delete_my_account(
    *,
    payload: DeleteAccountRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """Irreversible. Requires the password again so a borrowed, unlocked
    browser session is not enough to destroy an account."""
    _require_password(user, payload.password)
    delete_account(session, user)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
