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


def test_profile_streams_joined_tags_without_per_signal_event_queries():
    from sqlalchemy import event, text
    from sqlmodel import Session, SQLModel, create_engine
    from app.models.user import User
    from app.models.user_signal import UserSignal

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[User.__table__, UserSignal.__table__])
    # Geometry is irrelevant to this read path; only the projected columns exist.
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE events (id INTEGER PRIMARY KEY, tags TEXT)"))
        connection.execute(text("INSERT INTO events VALUES (1, '[\"#Jazz\"]')"))
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for _ in range(100):
            session.add(UserSignal(user_id=1, event_id=1, signal_type="click", weight=1, created_at=now))
        session.add(UserSignal(user_id=1, vibe_tag="#Chill", signal_type="like", weight=4, created_at=now))
        session.add(UserSignal(user_id=2, event_id=1, signal_type="save", weight=5, created_at=now))
        session.commit()
    queries = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    with Session(engine) as session:
        scores = UserProfileService().compute_vibe_scores_for_user(session=session, user_id=1, now=now)
    assert scores == {"#jazz": 100.0, "#chill": 4.0}
    assert len(queries) == 1
    engine.dispose()
