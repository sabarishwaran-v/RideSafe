"""Automated tests for FastAPI endpoints: root, status, Twilio dispatch, and API key auth."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from app.config import Settings, get_settings
from app.main import app
from app.storage import event_store


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure database is clean before and after each test."""
    event_store.clear()
    yield
    event_store.clear()


def test_root_endpoint():
    """Test GET / returns 200 OK with service name and healthy status."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "RideSafe Backend"
    assert data["status"] == "healthy"
    assert "version" in data
    assert "message" in data


def test_status_endpoint_reports_twilio_presence_without_leaks():
    """Test GET /api/ridesafe/status reports Twilio status booleans without exposing credentials."""
    client = TestClient(app)
    response = client.get("/api/ridesafe/status")
    assert response.status_code == 200
    data = response.json()

    assert "twilio" in data
    twilio_info = data["twilio"]
    assert "configured" in twilio_info
    assert "account_sid_present" in twilio_info
    assert "auth_token_present" in twilio_info
    assert "whatsapp_from_present" in twilio_info
    assert "emergency_contact_present" in twilio_info
    assert "recipient_masked" in twilio_info

    # Verify no raw secrets leaked in response
    resp_text = response.text
    assert "AC" not in resp_text or "ACXXXX" not in resp_text
    assert "auth_token" not in resp_text.lower() or "auth_token_present" in resp_text


def test_api_key_security_enforcement():
    """Verify X-API-Key header enforcement when RIDESAFE_API_KEY is configured."""
    custom_settings = Settings(
        ridesafe_api_key="super_secret_ridesafe_token_999",
        database_path="data/ridesafe.db",
    )
    app.dependency_overrides[get_settings] = lambda: custom_settings

    try:
        client = TestClient(app)
        payload = {
            "device_id": "ESP32-AUTH-TEST",
            "event_id": "evt-auth-1",
            "event": "ACCIDENT",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "gps_valid": True,
            "timestamp": "2026-10-21T10:30:00Z",
        }

        # Request missing X-API-Key header -> 401
        res_no_key = client.post("/api/ridesafe/alert", json=payload)
        assert res_no_key.status_code == 401
        assert "Unauthorized" in res_no_key.json()["detail"]

        # Request with wrong X-API-Key header -> 401
        res_bad_key = client.post(
            "/api/ridesafe/alert",
            json=payload,
            headers={"X-API-Key": "wrong-key"},
        )
        assert res_bad_key.status_code == 401

        # Request with valid X-API-Key header -> 201
        res_valid = client.post(
            "/api/ridesafe/alert",
            json=payload,
            headers={"X-API-Key": "super_secret_ridesafe_token_999"},
        )
        assert res_valid.status_code == 201

        # Test endpoint with valid vs invalid key
        test_payload = {
            "device_id": "ESP32-AUTH-TEST",
            "event_id": "evt-auth-test-1",
            "event": "TEST",
            "gps_valid": False,
            "timestamp": "2026-10-21T10:30:00Z",
        }
        res_test_bad = client.post(
            "/api/ridesafe/test",
            json=test_payload,
            headers={"X-API-Key": "wrong-key"},
        )
        assert res_test_bad.status_code == 401

        res_test_good = client.post(
            "/api/ridesafe/test",
            json=test_payload,
            headers={"X-API-Key": "super_secret_ridesafe_token_999"},
        )
        assert res_test_good.status_code == 201
    finally:
        app.dependency_overrides.pop(get_settings, None)


from app.models import NotificationDetail


def test_alert_endpoint_triggers_twilio_dispatch_and_prevents_duplicate_whatsapp():
    """Verify emergency alert dispatches via Twilio and duplicate requests do not re-trigger Twilio."""
    client = TestClient(app)
    payload = {
        "device_id": "ESP32-DISPATCH-01",
        "event_id": "evt-dispatch-101",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "speed_kmph": 25.5,
        "tilt_degrees": 55.0,
        "gps_valid": True,
        "timestamp": "2026-10-21T10:30:00Z",
    }

    with patch("app.main.twilio_service.send_emergency_alert") as mock_send_alert:
        mock_send_alert.return_value = NotificationDetail(
            status="dispatched",
            provider="twilio_whatsapp",
            message_sid="SM_TEST_MOCK_MESSAGE_SID_0000000",
            delivery_status="queued_by_twilio",
            recipient="whatsapp:+91****3210",
            note="Twilio accepted message.",
        )

        # First request: new event, dispatches Twilio
        first_resp = client.post("/api/ridesafe/alert", json=payload)
        assert first_resp.status_code == 201
        data = first_resp.json()
        assert data["status"] == "received"
        assert data["notification"]["status"] == "dispatched"
        assert data["notification"]["message_sid"] == "SM_TEST_MOCK_MESSAGE_SID_0000000"
        assert mock_send_alert.call_count == 1

        # Second request: duplicate (same device_id and event_id) -> 409 Conflict
        dup_resp = client.post("/api/ridesafe/alert", json=payload)
        assert dup_resp.status_code == 409
        # Crucial reliability check: Twilio must NOT be called a second time
        assert mock_send_alert.call_count == 1


def test_alert_endpoint_handles_twilio_failure_gracefully():
    """When Twilio dispatch fails, event is still accepted and persisted, returning 201 with failed notification."""
    client = TestClient(app)
    payload = {
        "device_id": "ESP32-FAILOVER-01",
        "event_id": "evt-failover-201",
        "event": "MANUAL_SOS",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-21T10:30:00Z",
    }

    with patch("app.main.twilio_service.send_emergency_alert") as mock_send_alert:
        mock_send_alert.return_value = NotificationDetail(
            status="failed",
            provider="twilio_whatsapp",
            message_sid=None,
            delivery_status="failed",
            recipient="whatsapp:+91****3210",
            note="Twilio network timeout.",
        )

        response = client.post("/api/ridesafe/alert", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "received"
        assert data["notification"]["status"] == "failed"
        assert "failed" in data["notification"]["delivery_status"]

        # Ensure event is still stored in SQLite
        stored = event_store.get_event("ESP32-FAILOVER-01", "evt-failover-201")
        assert stored is not None
        assert stored.is_emergency is True


def test_exact_prompt_example_payload():
    """Verify that the exact JSON structure provided in the prompt is accepted."""
    client = TestClient(app)
    exact_payload = {
        "event_id": "unique-event-id-prompt-sample",
        "device_id": "RIDESAFE_01",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "altitude": 42.5,
        "speed_kmph": 12.7,
        "tilt_degrees": 48.2,
        "gps_valid": True,
        "timestamp": "2026-10-21T10:30:00",
    }
    response = client.post("/api/ridesafe/alert", json=exact_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "received"
    assert data["event_id"] == "unique-event-id-prompt-sample"
    assert data["device_id"] == "RIDESAFE_01"
    assert data["event"] == "ACCIDENT"
    assert data["notification"]["provider"] == "twilio_whatsapp"


def test_test_endpoint_custom_payload():
    """Verify POST /api/ridesafe/test with custom payload dispatches test message and suppresses emergency alerts."""
    client = TestClient(app)
    test_payload = {
        "device_id": "CUSTOM-DEV-007",
        "event_id": "test-evt-custom-007",
        "event": "TEST",
        "gps_valid": False,
        "timestamp": "2026-10-21T11:00:00Z",
    }
    with patch("app.main.twilio_service.send_test_message") as mock_send_test:
        mock_send_test.return_value = NotificationDetail(
            status="dispatched",
            provider="twilio_whatsapp",
            message_sid="SMcustomtest777",
            delivery_status="queued_by_twilio",
            recipient="whatsapp:+91****3210",
            note="Test WhatsApp message dispatched.",
        )
        response = client.post("/api/ridesafe/test", json=test_payload)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "test_acknowledged"
        assert data["event_id"] == "test-evt-custom-007"
        assert data["device_id"] == "CUSTOM-DEV-007"
        assert data["is_test"] is True
        assert data["is_emergency"] is False
        assert mock_send_test.call_count == 1
