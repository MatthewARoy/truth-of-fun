from sqlmodel import Session, select

from app.models.user import User
from tests.test_interest_persistence import _build_client, _register


def test_structured_preferences_preserve_every_choice_and_can_be_cleared():
    with _build_client() as (client, engine):
        headers = _register(client)
        choices = ["#LiveMusic", "#Comedy", "#Nightlife", "#FoodAndDrink", "#Art"]
        response = client.put("/users/me/preferences", headers=headers, json={"preferred_vibes": choices})
        assert response.status_code == 200, response.text
        expected = ["#livemusic", "#comedy", "#nightlife", "#foodanddrink", "#art"]
        assert response.json()["preferred_vibes"] == expected
        with Session(engine) as session:
            assert session.exec(select(User)).one().preferred_vibes == expected
        cleared = client.put("/users/me/preferences", headers=headers, json={"preferred_vibes": []})
        assert cleared.status_code == 200
        assert cleared.json()["preferred_vibes"] == []


def test_preferences_reject_unknown_tags_and_require_auth():
    with _build_client() as (client, engine):
        assert client.put("/users/me/preferences", json={"preferred_vibes": []}).status_code == 401
        headers = _register(client)
        response = client.put("/users/me/preferences", headers=headers, json={"preferred_vibes": ["invented"]})
        assert response.status_code == 422
