"""Automated tests for Phase 2 event ingestion endpoints.

Covers:
1. Valid ACCIDENT event.
2. Valid MANUAL_SOS event.
3. Missing required fields.
4. Invalid latitude/longitude.
5. GPS unavailable with null coordinates.
6. GPS marked valid but coordinates missing.
7. Duplicate event_id from the same device.
8. Same event_id from different devices.
9. Test endpoint does not initiate a real emergency alert.
10. Existing health and status endpoints still work.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage import event_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_event_store():
    """Ensure in-memory store is empty before and after each test."""
    event_store.clear()
    yield
    event_store.clear()


def test_1_valid_accident_event():
    """1. Test valid ACCIDENT event returns 201 Created and expected payload."""
    payload = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-accident-1001",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "altitude": 15.5,
        "speed_kmph": 48.2,
        "tilt_degrees": 75.0,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    response = client.post("/api/ridesafe/alert", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "received"
    assert data["event_id"] == "evt-accident-1001"
    assert data["device_id"] == "ESP32-BIKE-001"
    assert data["event"] == "ACCIDENT"
    assert data["is_test"] is False
    assert data["is_emergency"] is True
    assert data["storage"] == "sqlite"
    assert "received_at" in data


def test_2_valid_manual_sos_event():
    """2. Test valid MANUAL_SOS event returns 201 Created."""
    payload = {
        "device_id": "ESP32-BIKE-002",
        "event_id": "evt-sos-2001",
        "event": "MANUAL_SOS",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "altitude": 920.0,
        "speed_kmph": 0.0,
        "tilt_degrees": 5.0,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:56:00+05:30",
    }
    response = client.post("/api/ridesafe/alert", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "received"
    assert data["event_id"] == "evt-sos-2001"
    assert data["event"] == "MANUAL_SOS"
    assert data["is_test"] is False
    assert data["is_emergency"] is True


@pytest.mark.parametrize(
    "missing_field",
    ["device_id", "event_id", "event", "gps_valid", "timestamp"],
)
def test_3_missing_required_fields(missing_field):
    """3. Test that omitting required fields returns 422 Unprocessable Entity."""
    base_payload = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-3001",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    del base_payload[missing_field]

    response = client.post("/api/ridesafe/alert", json=base_payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "lat,lon",
    [
        (91.0, 80.0),     # latitude > 90
        (-91.0, 80.0),    # latitude < -90
        (13.0, 181.0),    # longitude > 180
        (13.0, -181.0),   # longitude < -180
    ],
)
def test_4_invalid_latitude_longitude(lat, lon):
    """4. Test that out-of-range latitude/longitude coordinates return 422."""
    payload = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-coords-4001",
        "event": "ACCIDENT",
        "latitude": lat,
        "longitude": lon,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    response = client.post("/api/ridesafe/alert", json=payload)
    assert response.status_code == 422


def test_5_gps_unavailable_with_null_coordinates():
    """5. Test that GPS unavailable (gps_valid=False) with null coords is accepted (201)."""
    payload = {
        "device_id": "ESP32-BIKE-003",
        "event_id": "evt-nogps-5001",
        "event": "MANUAL_SOS",
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "speed_kmph": None,
        "tilt_degrees": 10.0,
        "gps_valid": False,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    response = client.post("/api/ridesafe/alert", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "received"
    assert data["event_id"] == "evt-nogps-5001"


def test_6_gps_marked_valid_but_coordinates_missing():
    """6. Test that gps_valid=True with null/missing coordinates is rejected (422)."""
    payload_null_lat = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-missing-lat-6001",
        "event": "ACCIDENT",
        "latitude": None,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    response = client.post("/api/ridesafe/alert", json=payload_null_lat)
    assert response.status_code == 422

    payload_null_both = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-missing-both-6002",
        "event": "ACCIDENT",
        "latitude": None,
        "longitude": None,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    response_both = client.post("/api/ridesafe/alert", json=payload_null_both)
    assert response_both.status_code == 422


def test_7_duplicate_event_id_from_same_device():
    """7. Test duplicate event_id from the same device returns 409 Conflict."""
    payload = {
        "device_id": "ESP32-BIKE-SAME",
        "event_id": "evt-duplicate-7001",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    # First submission: Accepted
    first_resp = client.post("/api/ridesafe/alert", json=payload)
    assert first_resp.status_code == 201

    # Second submission with same device_id and event_id: Rejected as duplicate
    dup_resp = client.post("/api/ridesafe/alert", json=payload)
    assert dup_resp.status_code == 409
    assert "Duplicate event" in dup_resp.json()["detail"]


def test_8_same_event_id_from_different_devices():
    """8. Test that the same event_id from DIFFERENT devices is allowed (both 201)."""
    payload_device_a = {
        "device_id": "DEVICE-ALPHA",
        "event_id": "evt-shared-8001",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    payload_device_b = {
        "device_id": "DEVICE-BETA",
        "event_id": "evt-shared-8001",
        "event": "ACCIDENT",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }

    resp_a = client.post("/api/ridesafe/alert", json=payload_device_a)
    assert resp_a.status_code == 201

    resp_b = client.post("/api/ridesafe/alert", json=payload_device_b)
    assert resp_b.status_code == 201


def test_9_test_endpoint_does_not_initiate_real_emergency_alert():
    """9. Test POST /api/ridesafe/test marks event as non-emergency test."""
    payload = {
        "device_id": "ESP32-BENCH-TEST",
        "event_id": "evt-test-9001",
        "event": "TEST",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    response = client.post("/api/ridesafe/test", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "test_acknowledged"
    assert data["is_test"] is True
    assert data["is_emergency"] is False
    assert "suppressed" in data["message"].lower()

    # Verify event stored in memory reflects is_emergency=False
    stored = event_store.get_event("ESP32-BENCH-TEST", "evt-test-9001")
    assert stored is not None
    assert stored.is_test is True
    assert stored.is_emergency is False


def test_10_existing_health_and_status_endpoints_work():
    """10. Test that existing GET /health and GET /api/ridesafe/status still work."""
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "healthy"

    status_resp = client.get("/api/ridesafe/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "online"
    assert status_data["components"]["api"] == "operational"
    assert status_data["components"]["esp32_receiver"] == "operational"
    assert status_data["components"]["whatsapp_alert_service"] == "not_configured"


def test_timestamp_naive_accepted():
    """Ensure naive timestamp without explicit timezone offset is accepted (normalized to UTC)."""
    payload = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-naive-ts-1",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00",
    }
    response = client.post("/api/ridesafe/alert", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "received"


def test_invalid_timestamp_fails_validation():
    """Ensure non-ISO datetime string is rejected with 422."""
    payload = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-invalid-ts-1",
        "event": "ACCIDENT",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "invalid-timestamp-string",
    }
    response = client.post("/api/ridesafe/alert", json=payload)
    assert response.status_code == 422


def test_test_event_rejected_on_live_alert_endpoint():
    """Ensure TEST event type sent to /alert is rejected with 400 Bad Request."""
    payload = {
        "device_id": "ESP32-BIKE-001",
        "event_id": "evt-test-on-alert",
        "event": "TEST",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "gps_valid": True,
        "timestamp": "2026-10-19T17:55:00Z",
    }
    response = client.post("/api/ridesafe/alert", json=payload)
    assert response.status_code == 400
    assert "Test events must be sent to the test endpoint" in response.json()["detail"]
