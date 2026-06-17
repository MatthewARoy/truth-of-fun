from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

# Folder invites expire after this many days unless the creator overrides it.
# Closes the "invite tokens never expire" gap while keeping links usable for a
# planning window.
DEFAULT_INVITE_TTL_DAYS = 14


def generate_share_token() -> str:
    return secrets.token_urlsafe(24)


def compute_invite_expiry(
    *, created_at: datetime, ttl_days: int | None = DEFAULT_INVITE_TTL_DAYS
) -> datetime | None:
    """Expiry instant for an invite created at ``created_at``.

    A ``ttl_days`` of 0 or ``None`` yields a non-expiring invite (returns None).
    """
    if ttl_days is None or ttl_days <= 0:
        return None
    return created_at + timedelta(days=ttl_days)


def is_invite_expired(expires_at: datetime | None, *, now: datetime) -> bool:
    """Whether an invite's expiry has passed.

    Invites without an expiry never expire. Naive timestamps (e.g. round-tripped
    through SQLite, which drops tzinfo) are interpreted as UTC so comparisons
    don't raise.
    """
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return expires_at <= now


def is_valid_share_token(token: str) -> bool:
    if not isinstance(token, str):
        return False
    cleaned = token.strip()
    return len(cleaned) >= 16 and all(char.isalnum() or char in "-_" for char in cleaned)


def normalize_vote_value(vote_value: int) -> int:
    return 1 if vote_value >= 1 else -1


def upsert_vote_value(*, existing_vote_value: int | None, incoming_vote_value: int) -> tuple[int, bool]:
    normalized = normalize_vote_value(incoming_vote_value)
    if existing_vote_value is None:
        return normalized, True
    if normalize_vote_value(existing_vote_value) == normalized:
        return normalized, False
    return normalized, True
