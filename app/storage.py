"""SQLite persistent event store and deduplication manager for Phase 3.

Provides thread-safe persistence using Python's standard sqlite3 module.
Ensures (device_id, event_id) deduplication at the database constraint level.
Database failures are caught and surfaced without false success responses.
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.config import get_settings
from app.schemas import EventPayload, EventType


class DatabaseError(Exception):
    """Raised when an unrecoverable database operation failure occurs."""


class StoredEvent(BaseModel):
    """Representation of an event retrieved from persistent storage."""

    payload: EventPayload
    received_at: datetime
    is_test: bool
    is_emergency: bool


class SQLiteEventStore:
    """Thread-safe SQLite persistent store with composite unique constraint deduplication."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._ensure_dir()
        self.init_db()

    def _ensure_dir(self) -> None:
        """Create database directory if it does not already exist."""
        if self.db_path and self.db_path != ":memory:":
            dirname = os.path.dirname(os.path.abspath(self.db_path))
            if dirname:
                os.makedirs(dirname, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Create a new SQLite connection configured for concurrent access."""
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if self.db_path != ":memory:":
            # WAL mode allows concurrent readers and high-throughput writes
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
            except sqlite3.Error:
                pass
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self) -> None:
        """Create database tables and indexes safely if they do not exist."""
        schema_sql = """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            speed_kmph REAL,
            tilt_degrees REAL,
            gps_valid INTEGER NOT NULL,
            device_timestamp TEXT NOT NULL,
            received_at TEXT NOT NULL,
            is_test INTEGER NOT NULL,
            is_emergency INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            UNIQUE (device_id, event_id)
        );

        CREATE INDEX IF NOT EXISTS idx_events_device_event ON events (device_id, event_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (device_timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_is_emergency ON events (is_emergency);
        """
        try:
            with self._connect() as conn:
                conn.executescript(schema_sql)
                conn.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database initialization failed: {exc}") from exc

    def is_initialized(self) -> bool:
        """Check whether the events table has been created."""
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name='events';"
        try:
            with self._connect() as conn:
                cursor = conn.execute(query)
                return cursor.fetchone() is not None
        except sqlite3.Error:
            return False

    def add_event(
        self,
        payload: EventPayload,
        received_at: datetime,
        is_test: bool,
        is_emergency: bool,
    ) -> bool:
        """Persist an event to SQLite.

        Returns:
            True if the event was newly accepted and inserted.
            False if (device_id, event_id) violates the unique constraint (duplicate).

        Raises:
            DatabaseError: If an unexpected database failure occurs.
        """
        insert_sql = """
        INSERT INTO events (
            device_id, event_id, event_type, latitude, longitude, altitude,
            speed_kmph, tilt_degrees, gps_valid, device_timestamp, received_at,
            is_test, is_emergency
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            payload.device_id,
            payload.event_id,
            payload.event.value,
            payload.latitude,
            payload.longitude,
            payload.altitude,
            payload.speed_kmph,
            payload.tilt_degrees,
            1 if payload.gps_valid else 0,
            payload.timestamp.isoformat(),
            received_at.isoformat(),
            1 if is_test else 0,
            1 if is_emergency else 0,
        )

        try:
            with self._connect() as conn:
                conn.execute(insert_sql, params)
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Duplicate event_id for the same device_id caught by UNIQUE constraint
            return False
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database write failure: {exc}") from exc

    def get_event(self, device_id: str, event_id: str) -> Optional[StoredEvent]:
        """Fetch a stored event by device_id and event_id."""
        query = """
        SELECT device_id, event_id, event_type, latitude, longitude, altitude,
               speed_kmph, tilt_degrees, gps_valid, device_timestamp, received_at,
               is_test, is_emergency
        FROM events
        WHERE device_id = ? AND event_id = ?;
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (device_id, event_id))
                row = cursor.fetchone()
                if not row:
                    return None
                return StoredEvent(
                    payload=EventPayload(
                        device_id=row["device_id"],
                        event_id=row["event_id"],
                        event=EventType(row["event_type"]),
                        latitude=row["latitude"],
                        longitude=row["longitude"],
                        altitude=row["altitude"],
                        speed_kmph=row["speed_kmph"],
                        tilt_degrees=row["tilt_degrees"],
                        gps_valid=bool(row["gps_valid"]),
                        timestamp=datetime.fromisoformat(row["device_timestamp"]),
                    ),
                    received_at=datetime.fromisoformat(row["received_at"]),
                    is_test=bool(row["is_test"]),
                    is_emergency=bool(row["is_emergency"]),
                )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database query failure: {exc}") from exc

    def has_event(self, device_id: str, event_id: str) -> bool:
        """Check whether an event exists in persistent storage."""
        query = "SELECT 1 FROM events WHERE device_id = ? AND event_id = ? LIMIT 1;"
        try:
            with self._connect() as conn:
                cursor = conn.execute(query, (device_id, event_id))
                return cursor.fetchone() is not None
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database query failure: {exc}") from exc

    def count(self) -> int:
        """Return total number of stored events."""
        try:
            with self._connect() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM events;")
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database count failure: {exc}") from exc

    def clear(self) -> None:
        """Delete all events (for test isolation)."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM events;")
                conn.commit()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database clear failure: {exc}") from exc


class PostgreSQLEventStore:
    """PostgreSQL-backed event store with the same interface as SQLiteEventStore."""

    db_type = "postgresql"
    db_path = "managed PostgreSQL"

    def __init__(self, database_url: str) -> None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            self._dict_row = dict_row
            self._pool = ConnectionPool(
                conninfo=database_url,
                min_size=1,
                max_size=5,
                kwargs={"row_factory": dict_row},
                open=True,
            )
            self.init_db()
        except Exception as exc:
            if isinstance(exc, DatabaseError):
                raise
            raise DatabaseError("PostgreSQL initialization failed; verify DATABASE_URL and database availability.") from exc

    def init_db(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS events (
            id BIGSERIAL PRIMARY KEY,
            device_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            altitude DOUBLE PRECISION,
            speed_kmph DOUBLE PRECISION,
            tilt_degrees DOUBLE PRECISION,
            gps_valid BOOLEAN NOT NULL,
            device_timestamp TEXT NOT NULL,
            received_at TEXT NOT NULL,
            is_test BOOLEAN NOT NULL,
            is_emergency BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (device_id, event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (device_timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_is_emergency ON events (is_emergency);
        """
        try:
            with self._pool.connection() as conn:
                for statement in schema.split(";"):
                    if statement.strip():
                        conn.execute(statement)
        except Exception as exc:
            raise DatabaseError("PostgreSQL schema initialization failed.") from exc

    def is_initialized(self) -> bool:
        try:
            with self._pool.connection() as conn:
                row = conn.execute("SELECT to_regclass('public.events') AS table_name").fetchone()
                return bool(row and row["table_name"])
        except Exception:
            return False

    def add_event(self, payload: EventPayload, received_at: datetime, is_test: bool, is_emergency: bool) -> bool:
        from psycopg.errors import UniqueViolation
        sql = """INSERT INTO events (device_id,event_id,event_type,latitude,longitude,altitude,
            speed_kmph,tilt_degrees,gps_valid,device_timestamp,received_at,is_test,is_emergency)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        params = (payload.device_id, payload.event_id, payload.event.value, payload.latitude,
            payload.longitude, payload.altitude, payload.speed_kmph, payload.tilt_degrees,
            payload.gps_valid, payload.timestamp.isoformat(), received_at.isoformat(), is_test, is_emergency)
        try:
            with self._pool.connection() as conn:
                conn.execute(sql, params)
            return True
        except UniqueViolation:
            return False
        except Exception as exc:
            raise DatabaseError("PostgreSQL write failure.") from exc

    def get_event(self, device_id: str, event_id: str) -> Optional[StoredEvent]:
        sql = """SELECT device_id,event_id,event_type,latitude,longitude,altitude,speed_kmph,
            tilt_degrees,gps_valid,device_timestamp,received_at,is_test,is_emergency
            FROM events WHERE device_id=%s AND event_id=%s"""
        try:
            with self._pool.connection() as conn:
                row = conn.execute(sql, (device_id, event_id)).fetchone()
            if not row:
                return None
            return StoredEvent(payload=EventPayload(device_id=row["device_id"], event_id=row["event_id"],
                event=EventType(row["event_type"]), latitude=row["latitude"], longitude=row["longitude"],
                altitude=row["altitude"], speed_kmph=row["speed_kmph"], tilt_degrees=row["tilt_degrees"],
                gps_valid=bool(row["gps_valid"]), timestamp=datetime.fromisoformat(row["device_timestamp"])),
                received_at=datetime.fromisoformat(row["received_at"]), is_test=bool(row["is_test"]),
                is_emergency=bool(row["is_emergency"]))
        except Exception as exc:
            if isinstance(exc, DatabaseError):
                raise
            raise DatabaseError("PostgreSQL query failure.") from exc

    def has_event(self, device_id: str, event_id: str) -> bool:
        try:
            with self._pool.connection() as conn:
                row = conn.execute("SELECT 1 AS found FROM events WHERE device_id=%s AND event_id=%s LIMIT 1", (device_id, event_id)).fetchone()
                return row is not None
        except Exception as exc:
            raise DatabaseError("PostgreSQL query failure.") from exc

    def count(self) -> int:
        try:
            with self._pool.connection() as conn:
                row = conn.execute("SELECT COUNT(*) AS total FROM events").fetchone()
                return int(row["total"])
        except Exception as exc:
            raise DatabaseError("PostgreSQL count failure.") from exc

    def clear(self) -> None:
        try:
            with self._pool.connection() as conn:
                conn.execute("DELETE FROM events")
        except Exception as exc:
            raise DatabaseError("PostgreSQL clear failure.") from exc

    def close(self) -> None:
        self._pool.close()


_global_store = None


def get_event_store(db_path: Optional[str] = None):
    """Return the configured store; PostgreSQL is selected when DATABASE_URL is set."""
    global _global_store
    if db_path is not None:
        return SQLiteEventStore(db_path)
    if _global_store is None:
        settings = get_settings()
        database_url = settings.effective_database_url
        _global_store = PostgreSQLEventStore(database_url) if database_url else SQLiteEventStore(settings.database_path)
    return _global_store


def set_event_store(store) -> None:
    """Set the active SQLiteEventStore instance."""
    global _global_store
    _global_store = store


def reset_event_store() -> None:
    """Reset the global store instance (primarily for test teardown)."""
    global _global_store
    if _global_store is not None and isinstance(_global_store, PostgreSQLEventStore):
        _global_store.close()
    _global_store = None


class _EventStoreProxy:
    """Dynamic proxy delegating to the current active event store."""

    def __getattr__(self, name: str):
        return getattr(get_event_store(), name)


# Transparent proxy export for backward compatibility
event_store = _EventStoreProxy()
