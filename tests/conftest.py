"""Shared Pytest configuration and fixtures.

Guarantees that automated tests run in an isolated environment with temporary
SQLite database files and isolated settings, preventing tests from being coupled
to the developer's local .env file.
"""

import pytest
from app.config import get_settings
from app.storage import SQLiteEventStore, reset_event_store, set_event_store


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path, monkeypatch):
    """Provide an isolated environment and temporary SQLite database for each test run."""
    temp_db_path = str(tmp_path / "test_ridesafe.db")
    monkeypatch.setenv("DATABASE_PATH", temp_db_path)

    # Clear authentication and Twilio variables so tests run in a clean, predictable state
    monkeypatch.setenv("RIDESAFE_API_KEY", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    monkeypatch.setenv("EMERGENCY_WHATSAPP_TO", "")
    monkeypatch.setenv("TWILIO_CONTENT_SID", "")

    # Invalidate settings cache so Settings picks up the isolated environment
    get_settings.cache_clear()

    # Create and register isolated store
    store = SQLiteEventStore(temp_db_path)
    set_event_store(store)

    yield store

    # Teardown
    reset_event_store()
    get_settings.cache_clear()
