from __future__ import annotations

import secrets


def generate_share_token() -> str:
    return secrets.token_urlsafe(24)


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
