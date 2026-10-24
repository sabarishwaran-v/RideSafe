"""Automated tests for PostgreSQL storage selection, operations, and database-only verification."""

from datetime import datetime, timezone
import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation

from app.config import Settings, get_settings
from app.main import app
from app.models import EventPayload, EventType
from app.storage import (
    DatabaseError,
    PostgreSQLEventStore,
    SQLiteEventStore,
    get_event_store,
    reset_event_store,
    verify_storage_persistence,
)


def create_sample_payload(
    device_id: str = "ESP32-PG-001",
    event_id: str = "evt-pg-100",
    event: EventType = EventType.ACCIDENT,
) -> EventPayload:
    """Helper to generate a valid test payload."""
    return EventPayload(
        device_id=device_id,
        event_id=event_id,
        event=event,
        latitude=13.0827,
        longitude=80.2707,
        altitude=45.0,
        speed_kmph=32.5,
        tilt_degrees=55.0,
        gps_valid=True,
        timestamp=datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc),
    )


def test_storage_selection_postgres_when_database_url_present(monkeypatch):
    """When DATABASE_URL is configured, get_event_store() selects PostgreSQLEventStore."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_ridesafe")
    get_settings.cache_clear()
    reset_event_store()

    with patch.object(PostgreSQLEventStore, "init_db"):
        with patch("psycopg_pool.ConnectionPool"):
            store = get_event_store()
            assert isinstance(store, PostgreSQLEventStore)
            assert store.db_type == "postgresql"

    reset_event_store()
    get_settings.cache_clear()


def test_storage_selection_sqlite_when_database_url_empty(monkeypatch):
    """When DATABASE_URL is empty, get_event_store() falls back to SQLiteEventStore."""
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    reset_event_store()

    store = get_event_store()
    assert isinstance(store, SQLiteEventStore)
    assert store.db_type == "sqlite"

    reset_event_store()
    get_settings.cache_clear()


def test_postgres_store_add_and_get_event_mocked():
    """Verify PostgreSQLEventStore.add_event and get_event with mocked connection pool."""
    payload = create_sample_payload()
    received_at = datetime(2026, 10, 24, 9, 0, 1, tzinfo=timezone.utc)

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.connection.return_value.__enter__.return_value = mock_conn

    # Setup mocked row returned from SELECT
    mock_conn.execute.return_value.fetchone.return_value = {
        "device_id": payload.device_id,
        "event_id": payload.event_id,
        "event_type": payload.event.value,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "altitude": payload.altitude,
        "speed_kmph": payload.speed_kmph,
        "tilt_degrees": payload.tilt_degrees,
        "gps_valid": True,
        "device_timestamp": payload.timestamp.isoformat(),
        "received_at": received_at.isoformat(),
        "is_test": False,
        "is_emergency": True,
    }

    with patch.object(PostgreSQLEventStore, "init_db"):
        with patch("psycopg_pool.ConnectionPool", return_value=mock_pool):
            store = PostgreSQLEventStore("postgresql://user:pass@localhost:5432/ridesafe")
            store._pool = mock_pool

            # Test add_event
            success = store.add_event(payload, received_at, is_test=False, is_emergency=True)
            assert success is True
            assert mock_conn.execute.call_count == 1

            # Test get_event
            retrieved = store.get_event(payload.device_id, payload.event_id)
            assert retrieved is not None
            assert retrieved.payload.device_id == payload.device_id
            assert retrieved.payload.event_id == payload.event_id
            assert retrieved.is_emergency is True


def test_postgres_store_duplicate_unique_violation():
    """Verify duplicate event submission catches UniqueViolation and returns False without failing."""
    payload = create_sample_payload()
    received_at = datetime.now(timezone.utc)

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = UniqueViolation("duplicate key value violates unique constraint")
    mock_pool.connection.return_value.__enter__.return_value = mock_conn

    with patch.object(PostgreSQLEventStore, "init_db"):
        with patch("psycopg_pool.ConnectionPool", return_value=mock_pool):
            store = PostgreSQLEventStore("postgresql://user:pass@localhost:5432/ridesafe")
            store._pool = mock_pool

            is_new = store.add_event(payload, received_at, is_test=False, is_emergency=True)
            assert is_new is False


def test_postgres_store_database_error_on_unhandled_exception():
    """Verify unexpected database exceptions raise DatabaseError."""
    payload = create_sample_payload()
    received_at = datetime.now(timezone.utc)

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = RuntimeError("connection terminated abruptly")
    mock_pool.connection.return_value.__enter__.return_value = mock_conn

    with patch.object(PostgreSQLEventStore, "init_db"):
        with patch("psycopg_pool.ConnectionPool", return_value=mock_pool):
            store = PostgreSQLEventStore("postgresql://user:pass@localhost:5432/ridesafe")
            store._pool = mock_pool

            with pytest.raises(DatabaseError, match="PostgreSQL write failure"):
                store.add_event(payload, received_at, is_test=False, is_emergency=True)


def test_postgres_init_db_failure_raises_database_error():
    """Verify PostgreSQLEventStore raises DatabaseError when schema initialization fails."""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("network timeout during connect")
    mock_pool.connection.return_value.__enter__.return_value = mock_conn

    with patch("psycopg_pool.ConnectionPool", return_value=mock_pool):
        with pytest.raises(DatabaseError, match="PostgreSQL.*failed"):
            PostgreSQLEventStore("postgresql://bad-host:5432/ridesafe")


def test_postgres_delete_event():
    """Verify delete_event executes parameterised DELETE and returns True when rows affected."""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 1
    mock_conn.execute.return_value = mock_cur
    mock_pool.connection.return_value.__enter__.return_value = mock_conn

    with patch.object(PostgreSQLEventStore, "init_db"):
        with patch("psycopg_pool.ConnectionPool", return_value=mock_pool):
            store = PostgreSQLEventStore("postgresql://user:pass@localhost:5432/ridesafe")
            store._pool = mock_pool

            deleted = store.delete_event("DEV_TEST", "evt_del_01")
            assert deleted is True
            call_sql, call_params = mock_conn.execute.call_args[0]
            assert "DELETE FROM events WHERE device_id = %s AND event_id = %s" in call_sql
            assert call_params == ("DEV_TEST", "evt_del_01")


def test_sqlite_delete_event(tmp_path):
    """Verify delete_event on SQLiteStore correctly deletes specific records."""
    db_file = str(tmp_path / "del_test.db")
    store = SQLiteEventStore(db_file)
    payload = create_sample_payload(device_id="DEV-DEL", event_id="evt-del-1")
    store.add_event(payload, datetime.now(timezone.utc), is_test=True, is_emergency=False)

    assert store.has_event("DEV-DEL", "evt-del-1") is True
    deleted = store.delete_event("DEV-DEL", "evt-del-1")
    assert deleted is True
    assert store.has_event("DEV-DEL", "evt-del-1") is False

    # Deleting non-existent record returns False
    assert store.delete_event("DEV-DEL", "evt-del-1") is False


def test_verify_storage_persistence_does_not_invoke_twilio(monkeypatch):
    """Verify that verify_storage_persistence performs write/read/delete without invoking Twilio."""
    with patch("app.twilio_service.twilio_service.send_emergency_alert") as mock_emergency, \
         patch("app.twilio_service.twilio_service.send_test_message") as mock_test:

        result = verify_storage_persistence()

        assert result["status"] == "operational"
        assert result["verified"] is True
        assert "verified successfully" in result["message"]

        # Crucial invariant: Twilio must NEVER be called
        assert mock_emergency.call_count == 0
        assert mock_test.call_count == 0


def test_diagnostics_endpoint_authenticated_success():
    """Verify POST /api/ridesafe/diagnostics/database succeeds and does not invoke Twilio."""
    client = TestClient(app)

    with patch("app.twilio_service.twilio_service.send_emergency_alert") as mock_emergency, \
         patch("app.twilio_service.twilio_service.send_test_message") as mock_test:

        resp = client.post("/api/ridesafe/diagnostics/database")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "operational"
        assert data["verified"] is True
        assert data["storage_type"] in {"sqlite", "postgresql"}
        assert "timestamp" in data

        assert mock_emergency.call_count == 0
        assert mock_test.call_count == 0


def test_diagnostics_endpoint_requires_api_key_when_configured(monkeypatch):
    """Verify diagnostics endpoint enforces API key authentication."""
    monkeypatch.setenv("RIDESAFE_API_KEY", "super_secret_test_key_123")
    get_settings.cache_clear()

    client = TestClient(app)

    # 1. Missing header -> 401
    resp_unauth = client.post("/api/ridesafe/diagnostics/database")
    assert resp_unauth.status_code == 401

    # 2. Invalid header -> 401
    resp_invalid = client.post(
        "/api/ridesafe/diagnostics/database",
        headers={"X-API-Key": "wrong_key"},
    )
    assert resp_invalid.status_code == 401

    # 3. Valid header -> 200
    resp_valid = client.post(
        "/api/ridesafe/diagnostics/database",
        headers={"X-API-Key": "super_secret_test_key_123"},
    )
    assert resp_valid.status_code == 200
    assert resp_valid.json()["verified"] is True


def test_diagnostics_endpoint_failure_path_returns_503(monkeypatch):
    """Verify diagnostics endpoint returns HTTP 503 without leaking SQL or connection details."""
    client = TestClient(app)

    with patch("app.storage.get_event_store") as mock_get_store:
        broken_store = MagicMock()
        broken_store.db_type = "postgresql"
        broken_store.add_event.side_effect = DatabaseError("Connection to postgresql://secret:password@db failed")
        mock_get_store.return_value = broken_store

        resp = client.post("/api/ridesafe/diagnostics/database")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "error"
        assert data["verified"] is False
        assert "password" not in resp.text
        assert "postgresql://" not in resp.text


def test_verify_storage_persistence_finally_cleanup_on_read_failure():
    """Verify verify_storage_persistence() cleans up the inserted test record in finally block even if read verification fails."""
    mock_store = MagicMock()
    mock_store.db_type = "postgresql"
    mock_store.add_event.return_value = True
    # Simulate read failure / record not found
    mock_store.get_event.return_value = None

    result = verify_storage_persistence(store=mock_store)

    assert result["verified"] is False
    assert result["status"] == "error"
    # Even though get_event failed to find the record, delete_event must be called in finally block
    assert mock_store.delete_event.call_count == 1
    call_device, call_evt = mock_store.delete_event.call_args[0]
    assert call_device == "RIDESAFE_DIAGNOSTIC"
    assert call_evt.startswith("diag-")


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Requires live PostgreSQL via TEST_DATABASE_URL")
def test_postgres_live_roundtrip(monkeypatch):
    """Live verification against real PostgreSQL when TEST_DATABASE_URL is provided."""
    live_url = os.environ["TEST_DATABASE_URL"]
    store = PostgreSQLEventStore(live_url)

    # Write
    payload = create_sample_payload(device_id="LIVE-PG-TEST", event_id="live-001")
    now = datetime.now(timezone.utc)
    inserted = store.add_event(payload, now, is_test=True, is_emergency=False)
    assert inserted is True

    # Duplicate
    duplicate = store.add_event(payload, now, is_test=True, is_emergency=False)
    assert duplicate is False

    # Read
    stored = store.get_event("LIVE-PG-TEST", "live-001")
    assert stored is not None
    assert stored.payload.device_id == "LIVE-PG-TEST"

    # Delete
    deleted = store.delete_event("LIVE-PG-TEST", "live-001")
    assert deleted is True

    # Verify deleted
    assert store.has_event("LIVE-PG-TEST", "live-001") is False
    store.close()
