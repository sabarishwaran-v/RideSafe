"""Automated tests for RideSafe FastAPI application endpoints."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_endpoint():
    """Verify GET /health returns 200 OK and expected payload."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "ridesafe-backend"


def test_ridesafe_status_endpoint():
    """Verify GET /api/ridesafe/status returns 200 OK and reports Phase 3 storage status."""
    response = client.get("/api/ridesafe/status")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "online"
    assert data["service"] == "RideSafe Backend"
    assert "version" in data
    assert "environment" in data
    assert "phase" in data

    components = data["components"]
    assert components["api"] == "operational"
    assert components["esp32_receiver"] == "operational"
    assert components["whatsapp_alert_service"] == "not_configured"

    # Verify Phase 3 persistent storage reporting
    storage = components["storage"]
    assert storage["type"] == "sqlite"
    assert storage["initialized"] is True
    assert "database_path" in storage


def test_non_existent_endpoint():
    """Verify standard 404 response for undefined routes."""
    response = client.get("/non-existent-route")
    assert response.status_code == 404
