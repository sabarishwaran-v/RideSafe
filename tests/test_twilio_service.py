"""Automated tests for Twilio WhatsApp notification service."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from twilio.base.exceptions import TwilioRestException
from app.config import Settings
from app.models import EventPayload, EventType
from app.twilio_service import TwilioWhatsAppService


@pytest.fixture
def mock_settings():
    """Return mock settings with Twilio configured using freeform body."""
    return Settings(
        twilio_account_sid="AC_TEST_MOCK_ACCOUNT_SID_00000000",
        twilio_auth_token="dummy_auth_token_for_testing",
        twilio_whatsapp_from="whatsapp:+14155238886",
        emergency_whatsapp_to="whatsapp:+919876543210",
        ridesafe_api_key="test_api_key_secret",
        twilio_content_sid=None,
    )


@pytest.fixture
def mock_content_settings():
    """Return mock settings with Twilio Content API (HX...) configured."""
    return Settings(
        twilio_account_sid="AC_TEST_MOCK_ACCOUNT_SID_00000000",
        twilio_auth_token="dummy_auth_token_for_testing",
        twilio_whatsapp_from="whatsapp:+14155238886",
        emergency_whatsapp_to="whatsapp:+919876543210",
        ridesafe_api_key="test_api_key_secret",
        twilio_content_sid="HX_TEST_MOCK_CONTENT_SID_00000000",
    )


@pytest.fixture
def unconfigured_settings():
    """Return mock settings with no Twilio credentials."""
    return Settings(
        twilio_account_sid=None,
        twilio_auth_token=None,
        twilio_whatsapp_from="whatsapp:+14155238886",
        emergency_whatsapp_to=None,
    )


def test_twilio_message_formatting_with_valid_gps(mock_settings):
    """Verify emergency message body includes telemetry and Google Maps link when GPS is valid."""
    service = TwilioWhatsAppService(settings=mock_settings)
    payload = EventPayload(
        device_id="RIDESAFE_TEST_01",
        event_id="evt-fmt-001",
        event=EventType.ACCIDENT,
        latitude=13.0827,
        longitude=80.2707,
        altitude=42.5,
        speed_kmph=12.7,
        tilt_degrees=48.2,
        gps_valid=True,
        timestamp=datetime(2026, 10, 21, 10, 30, 0, tzinfo=timezone.utc),
    )
    message = service.format_emergency_message(payload)

    assert "RIDESAFE EMERGENCY ALERT" in message
    assert "ACCIDENT" in message
    assert "RIDESAFE_TEST_01" in message
    assert "Speed: 12.7 km/h" in message
    assert "Tilt Angle: 48.2°" in message
    assert "Altitude: 42.5 m" in message
    assert "Latitude: 13.082700" in message
    assert "Longitude: 80.270700" in message
    assert "https://maps.google.com/?q=13.0827,80.2707" in message
    assert "automated emergency alert" in message.lower()


def test_twilio_message_formatting_without_gps(mock_settings):
    """Verify emergency message body labels missing GPS and does NOT include a maps link."""
    service = TwilioWhatsAppService(settings=mock_settings)
    payload = EventPayload(
        device_id="RIDESAFE_TEST_02",
        event_id="evt-fmt-002",
        event=EventType.MANUAL_SOS,
        latitude=None,
        longitude=None,
        altitude=None,
        speed_kmph=0.0,
        tilt_degrees=15.0,
        gps_valid=False,
        timestamp=datetime(2026, 10, 21, 10, 35, 0, tzinfo=timezone.utc),
    )
    message = service.format_emergency_message(payload)

    assert "MANUAL SOS" in message
    assert "GPS Fix Unavailable" in message
    assert "https://maps.google.com" not in message
    assert "automated emergency alert" in message.lower()


def test_twilio_test_message_formatting(mock_settings):
    """Verify test message format is clearly labelled and suppresses emergency alerts."""
    service = TwilioWhatsAppService(settings=mock_settings)
    msg = service.format_test_message(device_id="TEST_BENCH_01", event_id="test-evt-99")

    assert "[TEST]" in msg
    assert "No accident has occurred" in msg
    assert "TEST_BENCH_01" in msg
    assert "test-evt-99" in msg
    assert "Twilio Sandbox" in msg


def test_send_alert_when_twilio_unconfigured(unconfigured_settings):
    """When Twilio is not configured, send_emergency_alert returns status='skipped' without error."""
    service = TwilioWhatsAppService(settings=unconfigured_settings)
    payload = EventPayload(
        device_id="DEV_01",
        event_id="evt-skip-01",
        event=EventType.ACCIDENT,
        latitude=13.0,
        longitude=80.0,
        gps_valid=True,
        timestamp=datetime.now(timezone.utc),
    )
    result = service.send_emergency_alert(payload)

    assert result.status == "skipped"
    assert result.delivery_status == "not_configured"
    assert result.message_sid is None
    assert "not configured" in result.note.lower()


def test_send_alert_success_body_fallback(mock_settings):
    """When ContentSid is not configured, send using standard body."""
    service = TwilioWhatsAppService(settings=mock_settings)
    payload = EventPayload(
        device_id="DEV_01",
        event_id="evt-success-01",
        event=EventType.ACCIDENT,
        latitude=13.0,
        longitude=80.0,
        gps_valid=True,
        timestamp=datetime.now(timezone.utc),
    )

    mock_msg = MagicMock()
    mock_msg.sid = "SM999888777666555444333222111000"
    mock_msg.status = "queued"

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_get_client.return_value = mock_client

        result = service.send_emergency_alert(payload)

        assert result.status == "dispatched"
        assert result.message_sid == "SM999888777666555444333222111000"
        assert result.delivery_status == "queued"
        assert result.recipient == "whatsapp:+91****3210"

        # Verify body was used when content_sid is not configured
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "body" in call_kwargs
        assert "content_sid" not in call_kwargs


def test_send_alert_success_with_content_sid(mock_content_settings):
    """When ContentSid is configured, send using Content API (content_sid & content_variables)."""
    service = TwilioWhatsAppService(settings=mock_content_settings)
    payload = EventPayload(
        device_id="DEV_01",
        event_id="evt-content-success-01",
        event=EventType.ACCIDENT,
        latitude=13.0827,
        longitude=80.2707,
        speed_kmph=15.0,
        tilt_degrees=50.0,
        gps_valid=True,
        timestamp=datetime(2026, 10, 21, 10, 30, 0, tzinfo=timezone.utc),
    )

    mock_msg = MagicMock()
    mock_msg.sid = "SM_TEST_MOCK_MESSAGE_SID_0000000"
    mock_msg.status = "queued"

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_get_client.return_value = mock_client

        result = service.send_emergency_alert(payload)

        assert result.status == "dispatched"
        assert result.message_sid == "SM_TEST_MOCK_MESSAGE_SID_0000000"

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "body" not in call_kwargs
        assert call_kwargs["content_sid"] == "HX_TEST_MOCK_CONTENT_SID_00000000"
        assert "content_variables" in call_kwargs

        vars_dict = json.loads(call_kwargs["content_variables"])
        assert vars_dict["1"] == "ACCIDENT"
        assert vars_dict["2"] == "DEV_01"
        assert "Speed: 15.0 km/h" in vars_dict["4"]
        assert "https://maps.google.com" in vars_dict["5"]


def test_send_test_message_with_content_sid(mock_content_settings):
    """When ContentSid is configured, test message uses Content API with Appointment Reminders mapping."""
    service = TwilioWhatsAppService(settings=mock_content_settings)
    mock_msg = MagicMock()
    mock_msg.sid = "SMtestcontent123"
    mock_msg.status = "queued"

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_get_client.return_value = mock_client

        result = service.send_test_message("TEST_BENCH_01", "test-001")

        assert result.status == "dispatched"
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "body" not in call_kwargs
        assert call_kwargs["content_sid"] == "HX_TEST_MOCK_CONTENT_SID_00000000"
        vars_dict = json.loads(call_kwargs["content_variables"])
        assert "1" in vars_dict
        assert "2" in vars_dict
        assert "(RideSafe Test)" in vars_dict["1"]
        assert "TEST_BENCH_01" in vars_dict["2"]
        assert "test-001" in vars_dict["2"]


def test_appointment_reminders_template_variable_mapping(mock_content_settings):
    """Verify variables match Twilio Sandbox Appointment Reminders: 'Your appointment is coming up on {{1}} at {{2}}'."""
    service = TwilioWhatsAppService(settings=mock_content_settings)
    vars_dict = service.get_test_content_variables("ESP32_BENCH_TEST", "evt-chk-009")

    # Positional keys must be exact sequential strings "1" and "2"
    assert list(vars_dict.keys()) == ["1", "2"]

    # Variable 1 corresponds to {{1}} (Date after "on ")
    assert "(RideSafe Test)" in vars_dict["1"]

    # Variable 2 corresponds to {{2}} (Time after "at ") and conveys the device & event details
    assert "UTC" in vars_dict["2"]
    assert "Dev: ESP32_BENCH_TEST" in vars_dict["2"]
    assert "Evt: evt-chk-009" in vars_dict["2"]


def test_regression_error_21654_contentsid_required(mock_settings):
    """Regression test for Twilio API Error 21654 ('Unable to create record: ContentSid Required').

    Verifies that when Twilio requires a Content Template, the service catches the error,
    returns status='failed', and provides an actionable remediation note instructing the
    developer to set TWILIO_CONTENT_SID.
    """
    service = TwilioWhatsAppService(settings=mock_settings)
    payload = EventPayload(
        device_id="DEV_01",
        event_id="evt-err-21654",
        event=EventType.ACCIDENT,
        latitude=13.0,
        longitude=80.0,
        gps_valid=True,
        timestamp=datetime.now(timezone.utc),
    )

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri="/2010-04-01/Accounts/AC123/Messages.json",
            msg="Unable to create record: ContentSid Required",
            code=21654,
        )
        mock_get_client.return_value = mock_client

        result = service.send_emergency_alert(payload)

        assert result.status == "failed"
        assert result.delivery_status == "failed"
        assert result.message_sid is None
        assert "21654" in result.note
        assert "ContentSid Required" in result.note
        assert "TWILIO_CONTENT_SID" in result.note


def test_custom_content_variables_interpolation():
    """Verify custom TWILIO_CONTENT_VARIABLES template mapping is properly interpolated."""
    custom_settings = Settings(
        twilio_account_sid="AC_TEST_MOCK_ACCOUNT_SID_00000000",
        twilio_auth_token="dummy_token",
        twilio_whatsapp_from="whatsapp:+14155238886",
        emergency_whatsapp_to="whatsapp:+919876543210",
        twilio_content_sid="HX123",
        twilio_content_variables='{"first": "{event}", "second": "{device_id} at {location}"}',
    )
    service = TwilioWhatsAppService(settings=custom_settings)
    payload = EventPayload(
        device_id="ESP32-007",
        event_id="evt-custom-var-1",
        event=EventType.MANUAL_SOS,
        latitude=12.9716,
        longitude=77.5946,
        gps_valid=True,
        timestamp=datetime(2026, 10, 21, 10, 30, 0, tzinfo=timezone.utc),
    )
    vars_dict = service.get_alert_content_variables(payload)

    assert vars_dict["first"] == "MANUAL SOS"
    assert "ESP32-007" in vars_dict["second"]
    assert "https://maps.google.com" in vars_dict["second"]


def test_masked_recipient_phone_number(mock_settings):
    """Verify phone number is masked properly and does not reveal full recipient number."""
    service = TwilioWhatsAppService(settings=mock_settings)
    masked = service.get_masked_recipient()
    assert masked == "whatsapp:+91****3210"
    assert "987654" not in masked
