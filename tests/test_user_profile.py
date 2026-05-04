from datetime import datetime, timedelta, timezone

import pytest

from app.services.user_profile import UserProfileService

pytestmark = pytest.mark.anyio


def test_signal_weights_match_prd() -> None:
    service = UserProfileService()
    assert service.signal_weight("click") == 1.0
    assert service.signal_weight("save") == 5.0
    assert service.signal_weight("external_ticket_click") == 10.0


def test_decay_half_life_30_days() -> None:
    service = UserProfileService()
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    decay_30 = service.decay_multiplier(created_at=thirty_days_ago, now=now)
    decay_60 = service.decay_multiplier(created_at=sixty_days_ago, now=now)

    assert 0.49 <= decay_30 <= 0.51
    assert 0.24 <= decay_60 <= 0.26


async def test_onboarding_tag_extraction_normalizes_tags() -> None:
    service = UserProfileService()
    tags = await service.extract_onboarding_tags(
        "I want coffee in the Mission and late night jazz in Oakland."
    )
    assert tags
    assert all(tag.startswith("#") for tag in tags)
    assert all(" " not in tag for tag in tags)
