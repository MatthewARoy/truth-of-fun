"""Real Postgres regressions for bounded, relevant recommendation retrieval."""
from datetime import datetime, timedelta, timezone

import pytest

from app.api import discovery
from app.models.event import Event
from app.models.user import User
from tests.test_discovery_ongoing_events import _database_reachable

pytestmark = pytest.mark.skipif(not _database_reachable(), reason="Postgres unavailable")


def add_event(session, *, title, days=1, tags=None, status="scheduled", duration=None):
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=days)
    event = Event(
        title=title, start_at=start,
        end_at=start + duration if duration else None,
        source_name="test-recommendation-candidates", source_tier=1,
        location="POINT(-122.4194 37.7749)", tags=tags or [], status=status,
        created_at=now, updated_at=now,
    )
    session.add(event)
    return event


def test_relevant_later_events_survive_page_limit(isolated_events_session):
    session = isolated_events_session
    user = User(email="candidate-ranking@example.com", preferred_vibes=["#livemusic"])
    session.add(user)
    for index in range(10):
        add_event(session, title=f"Unrelated {index}", tags=["#art"])
    add_event(session, title="Later concert", days=20, tags=["Concert"])
    add_event(session, title="Later live music", days=21, tags=["#live-music"])
    add_event(session, title="Cancelled concert", tags=["#livemusic"], status="cancelled")
    session.flush()
    rows = discovery.get_recommendations(session=session, user=user, limit=2, offset=0)
    assert {row.title for row in rows} == {"Later concert", "Later live music"}
    assert all(row.matched_vibes for row in rows)


def test_diversity_is_applied_before_pagination(isolated_events_session):
    session = isolated_events_session
    user = User(email="diversity@example.com")
    session.add(user)
    for index in range(4):
        event = add_event(session, title=f"Jazz {index}", days=index + 1)
        event.categories = ["Music"]
    other = add_event(session, title="Older comedy", days=20)
    other.categories = ["Comedy"]
    other.created_at -= timedelta(hours=25)
    session.flush()
    first = discovery.get_recommendations(session=session, user=user, limit=2, offset=0)
    second = discovery.get_recommendations(session=session, user=user, limit=2, offset=2)
    assert [row.title for row in first] == ["Jazz 0", "Older comedy"]
    assert [row.title for row in second] == ["Jazz 1", "Jazz 2"]


@pytest.mark.parametrize("preferences", [[], ["#jazz"]])
def test_cold_or_unmatched_profiles_get_only_eligible_events(isolated_events_session, preferences):
    session = isolated_events_session
    user = User(email="cold-start@example.com", preferred_vibes=preferences)
    session.add(user)
    add_event(session, title="Tomorrow", tags=["#art"])
    add_event(session, title="Still running", days=-1, duration=timedelta(days=2))
    add_event(session, title="Finished", days=-2)
    add_event(session, title="Cancelled", status="cancelled")
    session.flush()
    rows = discovery.get_recommendations(session=session, user=user, limit=25, offset=0)
    assert {row.title for row in rows} == {"Tomorrow", "Still running"}
