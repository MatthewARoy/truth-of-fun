from app.main import app


def test_ui_contract_v1_paths_exist() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    expected_paths = [
        "/events",
        "/recommendations",
        "/users/me/onboarding",
        "/users/me/interests",
        "/concierge/itinerary",
        "/folders",
        "/folders/{folder_id}",
        "/folders/{folder_id}/items",
        "/folders/{folder_id}/votes",
        "/folders/{folder_id}/invite",
        "/shared/folders/{token}",
    ]
    for path in expected_paths:
        assert path in paths
