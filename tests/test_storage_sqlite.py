"""Automated tests for Phase 3 SQLite persistent event storage.

Covers:
1. Event persistence after database connection is reopened.
2. Duplicate detection after simulated application restart.
3. Same event_id on different devices.
4. Concurrent duplicate submissions with multi-threading.
5. GPS-unavailable events stored and retrieved properly.
6. TEST events stored as non-emergency in database.
7. Database schema initialization, automatic directory creation, and error handling.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
from app.schemas import EventPayload, EventType
from app.storage import DatabaseError, SQLiteEventStore


def create_sample_payload(
    device_id: str = "DEV-001",
    event_id: str = "EVT-100",
    event: EventType = EventType.ACCIDENT,
    latitude: float = 13.0827,
    longitude: float = 80.2707,
    gps_valid: bool = True,
) -> EventPayload:
    """Helper to generate a valid EventPayload."""
    return EventPayload(
        device_id=device_id,
        event_id=event_id,
        event=event,
        latitude=latitude if gps_valid else None,
        longitude=longitude if gps_valid else None,
        altitude=15.0 if gps_valid else None,
        speed_kmph=30.0 if gps_valid else None,
        tilt_degrees=45.0,
        gps_valid=gps_valid,
        timestamp=datetime.now(timezone.utc),
    )


def test_persistence_after_connection_reopened(tmp_path):
    """Verify stored events persist on disk and can be read by a new connection."""
    db_file = str(tmp_path / "persistent_test.db")
    store1 = SQLiteEventStore(db_file)

    payload = create_sample_payload(
        device_id="ESP32-PERSIST-1",
        event_id="evt-persist-001",
        latitude=13.0827,
        longitude=80.2707,
    )
    receipt_ts = datetime.now(timezone.utc)
    inserted = store1.add_event(
        payload=payload,
        received_at=receipt_ts,
        is_test=False,
        is_emergency=True,
    )
    assert inserted is True

    # Simulate closing store1 and opening a completely separate store2 connection
    store2 = SQLiteEventStore(db_file)
    event = store2.get_event("ESP32-PERSIST-1", "evt-persist-001")
    assert event is not None
    assert event.payload.device_id == "ESP32-PERSIST-1"
    assert event.payload.event_id == "evt-persist-001"
    assert event.payload.latitude == 13.0827
    assert event.payload.longitude == 80.2707
    assert event.is_emergency is True
    assert event.is_test is False


def test_duplicate_detection_after_simulated_restart(tmp_path):
    """Verify duplicate detection remains active across process restarts."""
    db_file = str(tmp_path / "restart_test.db")

    # Instance 1 before restart
    store1 = SQLiteEventStore(db_file)
    payload = create_sample_payload(device_id="ESP32-RESTART", event_id="evt-restart-99")
    assert store1.add_event(payload, datetime.now(timezone.utc), False, True) is True
    assert store1.count() == 1

    # Instance 2 after simulated restart
    store2 = SQLiteEventStore(db_file)
    duplicate_result = store2.add_event(payload, datetime.now(timezone.utc), False, True)
    assert duplicate_result is False
    assert store2.count() == 1


def test_same_event_id_on_different_devices(tmp_path):
    """Verify (device_id, event_id) composite uniqueness allows same event_id on different devices."""
    db_file = str(tmp_path / "multi_device_test.db")
    store = SQLiteEventStore(db_file)

    shared_event_id = "shared-event-id-xyz"
    payload_a = create_sample_payload(device_id="DEVICE-A", event_id=shared_event_id)
    payload_b = create_sample_payload(device_id="DEVICE-B", event_id=shared_event_id)

    assert store.add_event(payload_a, datetime.now(timezone.utc), False, True) is True
    assert store.add_event(payload_b, datetime.now(timezone.utc), False, True) is True
    assert store.count() == 2


def test_concurrent_duplicate_submissions(tmp_path):
    """Verify thread-safe concurrency: duplicate submissions under high concurrency never create duplicates."""
    db_file = str(tmp_path / "concurrent_test.db")
    store = SQLiteEventStore(db_file)

    payload = create_sample_payload(device_id="ESP32-CONCURRENT", event_id="evt-conc-001")
    ts = datetime.now(timezone.utc)

    num_threads = 10

    def attempt_insert(_):
        return store.add_event(payload, ts, False, True)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = list(executor.map(attempt_insert, range(num_threads)))

    # Exactly one insert must succeed (True), and the other 9 must fail as duplicates (False)
    assert results.count(True) == 1
    assert results.count(False) == num_threads - 1
    assert store.count() == 1


def test_gps_unavailable_events(tmp_path):
    """Verify events without GPS fix are persisted with NULL coordinates."""
    db_file = str(tmp_path / "no_gps_test.db")
    store = SQLiteEventStore(db_file)

    payload = create_sample_payload(
        device_id="ESP32-TUNNEL",
        event_id="evt-tunnel-001",
        event=EventType.MANUAL_SOS,
        gps_valid=False,
    )
    assert store.add_event(payload, datetime.now(timezone.utc), False, True) is True

    retrieved = store.get_event("ESP32-TUNNEL", "evt-tunnel-001")
    assert retrieved is not None
    assert retrieved.payload.gps_valid is False
    assert retrieved.payload.latitude is None
    assert retrieved.payload.longitude is None
    assert retrieved.payload.altitude is None
    assert retrieved.is_emergency is True


def test_test_events_remain_non_emergency(tmp_path):
    """Verify test events are persisted with is_test=1 and is_emergency=0."""
    db_file = str(tmp_path / "test_events_db.db")
    store = SQLiteEventStore(db_file)

    payload = create_sample_payload(
        device_id="ESP32-BENCH",
        event_id="evt-bench-01",
        event=EventType.TEST,
        gps_valid=True,
    )
    assert store.add_event(payload, datetime.now(timezone.utc), is_test=True, is_emergency=False) is True

    retrieved = store.get_event("ESP32-BENCH", "evt-bench-01")
    assert retrieved is not None
    assert retrieved.is_test is True
    assert retrieved.is_emergency is False


def test_directory_auto_creation_and_initialization(tmp_path):
    """Verify SQLiteEventStore creates nested non-existent directories automatically."""
    nested_db_path = str(tmp_path / "nested" / "sub_dir" / "events.db")
    store = SQLiteEventStore(nested_db_path)

    assert store.is_initialized() is True
    assert store.count() == 0


def test_database_error_handling(tmp_path, monkeypatch):
    """Verify unrecoverable SQLite errors raise DatabaseError without silent success."""
    db_file = str(tmp_path / "error_test.db")
    store = SQLiteEventStore(db_file)

    payload = create_sample_payload(device_id="ESP32-ERR", event_id="evt-err-01")

    # Simulate an error by breaking the connect call or closing early
    def broken_connect():
        raise DatabaseError("Simulated disk I/O error")

    monkeypatch.setattr(store, "_connect", broken_connect)

    with pytest.raises(DatabaseError):
        store.add_event(payload, datetime.now(timezone.utc), False, True)
