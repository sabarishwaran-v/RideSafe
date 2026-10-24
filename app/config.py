"""Application configuration management using Pydantic Settings.

Reads configuration values from environment variables or a local .env file.
Secrets and sensitive credentials are never hardcoded and must be supplied
via the environment.
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings class."""

    # Core Application Settings
    app_name: str = "RideSafe Backend"
    app_env: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    api_prefix: str = "/api/ridesafe"

    # Database Configuration: DATABASE_URL selects PostgreSQL; otherwise use SQLite.
    database_url: Optional[str] = None
    database_path: str = "data/ridesafe.db"

    @property
    def effective_database_url(self) -> Optional[str]:
        """Normalize managed PostgreSQL URLs and require TLS in production."""
        if not self.database_url or not self.database_url.strip():
            return None
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        url = self.database_url.strip()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"): ]
        parts = urlsplit(url)
        if parts.scheme not in {"postgresql", "postgres"}:
            raise ValueError("DATABASE_URL must use the postgresql:// scheme")
        query = parse_qsl(parts.query, keep_blank_values=True)
        if self.app_env.lower() == "production":
            query = [(key, value) for key, value in query if key != "sslmode"]
            query.append(("sslmode", "require"))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    # Security: RideSafe Shared API Key
    ridesafe_api_key: Optional[str] = None

    # Twilio WhatsApp Sandbox Integration
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_whatsapp_from: str = "whatsapp:+14155238886"
    emergency_whatsapp_to: Optional[str] = None

    # Twilio Content API / Content Template Configuration (HX...)
    # Required when WhatsApp/Twilio enforces pre-approved templates (Error 21654)
    twilio_content_sid: Optional[str] = None
    twilio_test_content_sid: Optional[str] = None
    twilio_content_variables: Optional[str] = None

    # Legacy / backward-compatibility aliases
    esp32_api_key: Optional[str] = None
    whatsapp_api_token: Optional[str] = None
    whatsapp_phone_number_id: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    # Known template placeholders from .env.example
    _PLACEHOLDER_SIDS = {"ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "your_account_sid_here", ""}
    _PLACEHOLDER_TOKENS = {"your_twilio_auth_token_here", "your_auth_token_here", ""}
    _PLACEHOLDER_KEYS = {"ridesafe_secret_key_change_me", "your_secret_api_key_here", ""}
    _PLACEHOLDER_CONTENT_SIDS = {"HXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "your_content_sid_here", ""}

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def has_valid_account_sid(self) -> bool:
        """Check whether twilio_account_sid is configured and not a placeholder."""
        if not self.twilio_account_sid:
            return False
        return self.twilio_account_sid.strip() not in self._PLACEHOLDER_SIDS

    @property
    def has_valid_auth_token(self) -> bool:
        """Check whether twilio_auth_token is configured and not a placeholder."""
        if not self.twilio_auth_token:
            return False
        return self.twilio_auth_token.strip() not in self._PLACEHOLDER_TOKENS

    @property
    def has_valid_emergency_contact(self) -> bool:
        """Check whether emergency_whatsapp_to is configured."""
        if not self.emergency_whatsapp_to:
            return False
        return bool(self.emergency_whatsapp_to.strip())

    @property
    def has_valid_content_sid(self) -> bool:
        """Check whether a Twilio Content SID (HX...) is configured and not a placeholder."""
        if not self.twilio_content_sid:
            return False
        return self.twilio_content_sid.strip() not in self._PLACEHOLDER_CONTENT_SIDS

    @property
    def effective_test_content_sid(self) -> Optional[str]:
        """Return the effective Content SID to use for test events."""
        if self.twilio_test_content_sid and self.twilio_test_content_sid.strip() not in self._PLACEHOLDER_CONTENT_SIDS:
            return self.twilio_test_content_sid.strip()
        if self.has_valid_content_sid:
            return self.twilio_content_sid.strip()
        return None

    @property
    def is_twilio_configured(self) -> bool:
        """Check whether all necessary Twilio WhatsApp credentials are valid and non-placeholder."""
        return bool(
            self.has_valid_account_sid
            and self.has_valid_auth_token
            and self.twilio_whatsapp_from
            and self.has_valid_emergency_contact
        )

    @property
    def is_api_key_configured(self) -> bool:
        """Check whether an API key requirement is configured and non-placeholder."""
        if not self.ridesafe_api_key:
            return False
        return self.ridesafe_api_key.strip() not in self._PLACEHOLDER_KEYS

    def get_masked_emergency_contact(self) -> Optional[str]:
        """Return a masked representation of the emergency WhatsApp recipient."""
        if not self.emergency_whatsapp_to:
            return None
        target = self.emergency_whatsapp_to.strip()
        prefix = "whatsapp:" if target.startswith("whatsapp:") else ""
        raw_num = target[len("whatsapp:"):] if target.startswith("whatsapp:") else target
        if len(raw_num) <= 6:
            return f"{prefix}****"
        return f"{prefix}{raw_num[:3]}****{raw_num[-4:]}"


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
