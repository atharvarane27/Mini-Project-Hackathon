from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_success() -> None:
    """Verify /api/v1/health returns HTTP 200 with standard envelope."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    payload = response.json()
    assert "data" in payload
    assert "meta" in payload
    assert "request_id" in payload

    data = payload["data"]
    assert data["status"] == "ok"
    assert data["app"] == "AuditForge"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data
    assert data["db_backend"] == "supabase"


def test_request_id_middleware_generates_id() -> None:
    """Verify X-Request-ID is generated and returned in headers when omitted."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_request_id_middleware_preserves_id() -> None:
    """Verify custom X-Request-ID is preserved and echoed."""
    custom_id = "test-custom-request-id-12345"
    response = client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id
    assert response.json()["request_id"] == custom_id
