from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    """Health endpoint returns the expected ok payload."""

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
