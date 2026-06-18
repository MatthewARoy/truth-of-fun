from datetime import datetime, timedelta, timezone

from app.services.social import (
    DEFAULT_INVITE_TTL_DAYS,
    compute_invite_expiry,
    generate_share_token,
    is_invite_expired,
    is_valid_share_token,
    normalize_vote_value,
    upsert_vote_value,
)


def test_share_token_generation_and_validation() -> None:
    token = generate_share_token()
    assert is_valid_share_token(token) is True
    assert is_valid_share_token("bad token with spaces") is False
    assert is_valid_share_token("short") is False


def test_vote_normalization_and_idempotent_upsert() -> None:
    assert normalize_vote_value(99) == 1
    assert normalize_vote_value(-3) == -1

    value, changed = upsert_vote_value(existing_vote_value=None, incoming_vote_value=1)
    assert value == 1
    assert changed is True

    same_value, same_changed = upsert_vote_value(existing_vote_value=1, incoming_vote_value=10)
    assert same_value == 1
    assert same_changed is False

    flipped_value, flipped_changed = upsert_vote_value(existing_vote_value=1, incoming_vote_value=-1)
    assert flipped_value == -1
    assert flipped_changed is True


def test_compute_invite_expiry_defaults_to_ttl_window() -> None:
    created = datetime(2026, 6, 13, tzinfo=timezone.utc)
    assert compute_invite_expiry(created_at=created) == created + timedelta(
        days=DEFAULT_INVITE_TTL_DAYS
    )
    assert compute_invite_expiry(created_at=created, ttl_days=3) == created + timedelta(days=3)


def test_compute_invite_expiry_is_none_for_non_positive_ttl() -> None:
    # ttl_days of 0 or None means "never expires".
    created = datetime(2026, 6, 13, tzinfo=timezone.utc)
    assert compute_invite_expiry(created_at=created, ttl_days=0) is None
    assert compute_invite_expiry(created_at=created, ttl_days=None) is None


def test_is_invite_expired() -> None:
    now = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
    assert is_invite_expired(None, now=now) is False
    assert is_invite_expired(now + timedelta(days=1), now=now) is False
    assert is_invite_expired(now - timedelta(seconds=1), now=now) is True
    # Naive timestamps (round-tripped through SQLite) are treated as UTC, not crashed on.
    naive_past = (now - timedelta(days=1)).replace(tzinfo=None)
    assert is_invite_expired(naive_past, now=now) is True
