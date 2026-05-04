from fastapi.testclient import TestClient

from app.main import app


def test_health_check_confirms_database_connection() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
