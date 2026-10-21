"""Automated tests for configuration management."""

import os
from unittest import mock
from app.config import Settings, get_settings


def test_default_settings():
    """Verify default configuration values when no env vars are set."""
    with mock.patch.dict(os.environ, {}, clear=True):
        settings = Settings()
        assert settings.app_name == "RideSafe Backend"
        assert settings.app_env == "development"
        assert settings.debug is False
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
        assert settings.api_prefix == "/api/ridesafe"
        assert settings.database_path == "data/ridesafe.db"
        assert settings.esp32_api_key is None
        assert settings.whatsapp_api_token is None


def test_environment_variable_override():
    """Verify settings can be overridden by environment variables."""
    with mock.patch.dict(
        os.environ,
        {
            "APP_NAME": "RideSafe Test App",
            "APP_ENV": "test",
            "DEBUG": "True",
            "PORT": "9000",
            "DATABASE_PATH": "custom/db/test.sqlite",
        },
    ):
        custom_settings = Settings()
        assert custom_settings.app_name == "RideSafe Test App"
        assert custom_settings.app_env == "test"
        assert custom_settings.debug is True
        assert custom_settings.port == 9000
        assert custom_settings.database_path == "custom/db/test.sqlite"


def test_get_settings_cached():
    """Verify get_settings returns a cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
