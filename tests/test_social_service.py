from app.services.social import (
    generate_share_token,
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
