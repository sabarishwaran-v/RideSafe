"""Twilio WhatsApp Sandbox Service for RideSafe emergency notifications.

Supports both standard WhatsApp body messages and Twilio Content API templates
(ContentSid HX...) required by Meta/Twilio WhatsApp policy for business-initiated
outbound messages.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client
from app.config import Settings, get_settings
from app.models import EventPayload, NotificationDetail

logger = logging.getLogger(__name__)


class TwilioWhatsAppService:
    """Handles dispatching emergency notifications and test messages via Twilio WhatsApp Sandbox."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        """Retrieve active settings."""
        return self._settings or get_settings()

    def is_configured(self) -> bool:
        """Check if all required Twilio environment variables are configured."""
        return self.settings.is_twilio_configured

    def _normalize_whatsapp_number(self, number: str) -> str:
        """Ensure phone number has 'whatsapp:' prefix required by Twilio API."""
        trimmed = number.strip()
        if not trimmed.startswith("whatsapp:"):
            return f"whatsapp:{trimmed}"
        return trimmed

    def get_masked_recipient(self) -> Optional[str]:
        """Return masked recipient phone number for safe reporting without exposing credentials."""
        return self.settings.get_masked_emergency_contact()

    def format_emergency_message(self, payload: EventPayload) -> str:
        """Format WhatsApp emergency notification body with vehicle telemetry and GPS data."""
        event_name = "ACCIDENT" if payload.event.value == "ACCIDENT" else "MANUAL SOS"
        ts_str = payload.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "🚨 *RIDESAFE EMERGENCY ALERT* 🚨",
            "",
            f"*Event:* {event_name}",
            f"*Device ID:* {payload.device_id}",
            f"*Time:* {ts_str}",
            "",
            "📊 *Telemetry:*",
        ]

        if payload.speed_kmph is not None:
            lines.append(f"• Speed: {payload.speed_kmph:.1f} km/h")
        if payload.tilt_degrees is not None:
            lines.append(f"• Tilt Angle: {payload.tilt_degrees:.1f}°")
        if payload.altitude is not None:
            lines.append(f"• Altitude: {payload.altitude:.1f} m")

        lines.append("")
        lines.append("📍 *Location:*")

        if payload.gps_valid and payload.latitude is not None and payload.longitude is not None:
            lines.append(f"Latitude: {payload.latitude:.6f}")
            lines.append(f"Longitude: {payload.longitude:.6f}")
            lines.append(f"🔗 *Google Maps:* https://maps.google.com/?q={payload.latitude},{payload.longitude}")
        else:
            lines.append("⚠️ *GPS Fix Unavailable / No Location Acquired*")

        lines.append("")
        lines.append("⚠️ *NOTICE:* This is an automated emergency alert from RideSafe. Immediate verification required.")

        return "\n".join(lines)

    def format_test_message(self, device_id: str, event_id: str) -> str:
        """Format clearly labelled test WhatsApp message."""
        lines = [
            "🧪 *[TEST] RIDESAFE SYSTEM TEST* 🧪",
            "",
            "This is a *TEST* message from the RideSafe backend.",
            "No accident has occurred. Emergency services are NOT required.",
            "",
            f"*Device ID:* {device_id}",
            f"*Event ID:* {event_id}",
            "*Status:* Operational",
            "",
            "ℹ️ *Note:* Twilio Sandbox recipients must join sandbox before receiving messages.",
        ]
        return "\n".join(lines)

    def get_alert_content_variables(self, payload: EventPayload) -> Dict[str, str]:
        """Construct variable dictionary for Content Template (ContentSid) dispatch."""
        event_name = "ACCIDENT" if payload.event.value == "ACCIDENT" else "MANUAL SOS"
        ts_str = payload.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        telemetry_items = []
        if payload.speed_kmph is not None:
            telemetry_items.append(f"Speed: {payload.speed_kmph:.1f} km/h")
        if payload.tilt_degrees is not None:
            telemetry_items.append(f"Tilt: {payload.tilt_degrees:.1f}°")
        if payload.altitude is not None:
            telemetry_items.append(f"Alt: {payload.altitude:.1f} m")
        telemetry_str = ", ".join(telemetry_items) if telemetry_items else "N/A"

        if payload.gps_valid and payload.latitude is not None and payload.longitude is not None:
            location_str = f"https://maps.google.com/?q={payload.latitude},{payload.longitude}"
        else:
            location_str = "GPS Fix Unavailable"

        context = {
            "event": event_name,
            "device_id": payload.device_id,
            "event_id": payload.event_id,
            "timestamp": ts_str,
            "telemetry": telemetry_str,
            "location": location_str,
            "speed": f"{payload.speed_kmph:.1f} km/h" if payload.speed_kmph is not None else "N/A",
            "tilt": f"{payload.tilt_degrees:.1f}°" if payload.tilt_degrees is not None else "N/A",
            "latitude": str(payload.latitude) if payload.latitude is not None else "N/A",
            "longitude": str(payload.longitude) if payload.longitude is not None else "N/A",
            "message": self.format_emergency_message(payload),
        }

        # Check for user-defined variable mapping in TWILIO_CONTENT_VARIABLES
        if self.settings.twilio_content_variables:
            try:
                mapping = json.loads(self.settings.twilio_content_variables)
                if isinstance(mapping, dict):
                    return {
                        str(k): str(v).format(**context)
                        for k, v in mapping.items()
                    }
            except Exception as exc:
                logger.warning("Failed to parse TWILIO_CONTENT_VARIABLES; using defaults: %s", exc)

        # Standard positional mappings matching Twilio Content Template standard placeholders {{1}}..{{5}}
        return {
            "1": context["event"],
            "2": context["device_id"],
            "3": context["timestamp"],
            "4": context["telemetry"],
            "5": context["location"],
        }

    def get_test_content_variables(self, device_id: str, event_id: str) -> Dict[str, str]:
        """Construct variable dictionary for Twilio Sandbox Appointment Reminders template.

        Twilio Sandbox Appointment Reminders Template layout:
        'Your appointment is coming up on {{1}} at {{2}}'
        - {{1}}: Date and test designation (e.g. '2026-10-21 (RideSafe Test)')
        - {{2}}: Time, reporting device, and event reference (e.g. '12:58:20 UTC [Dev: TEST_BENCH_01, Evt: test-001]')
        """
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S UTC")

        context = {
            "date": date_str,
            "time": time_str,
            "device_id": device_id,
            "event_id": event_id,
            "timestamp": f"{date_str} {time_str}",
            "status": "Operational",
            "message": self.format_test_message(device_id, event_id),
        }

        if self.settings.twilio_content_variables:
            try:
                mapping = json.loads(self.settings.twilio_content_variables)
                if isinstance(mapping, dict):
                    return {
                        str(k): str(v).format(**context)
                        for k, v in mapping.items()
                    }
            except Exception as exc:
                logger.warning("Failed to parse TWILIO_CONTENT_VARIABLES for test; using defaults: %s", exc)

        # Standard 2-variable mapping aligned with Twilio Sandbox Appointment Reminders:
        # "Your appointment is coming up on {{1}} at {{2}}"
        return {
            "1": f"{date_str} (RideSafe Test)",
            "2": f"{time_str} [Dev: {device_id}, Evt: {event_id}]",
        }

    def _get_client(self) -> Client:
        """Instantiate Twilio client."""
        return Client(
            self.settings.twilio_account_sid,
            self.settings.twilio_auth_token,
        )

    def _handle_twilio_error(self, exc: TwilioRestException, masked_to: Optional[str]) -> NotificationDetail:
        """Format helpful error responses, with explicit remediation for error 21654."""
        logger.error("Twilio API error (%s): %s", exc.code, exc.msg)
        if exc.code == 21654 or "ContentSid Required" in str(exc.msg):
            note = (
                "Twilio API error 21654: ContentSid Required. Meta/Twilio WhatsApp policy requires "
                "a pre-approved Content Template for this message. Please configure TWILIO_CONTENT_SID "
                "in your .env file with the template SID (starting with 'HX') from Twilio Console "
                "(Messaging > Try it out > Send a WhatsApp message or Content Template Builder)."
            )
        else:
            note = f"Twilio API error ({exc.code}): {exc.msg}"

        return NotificationDetail(
            status="failed",
            provider="twilio_whatsapp",
            message_sid=None,
            delivery_status="failed",
            recipient=masked_to,
            note=note,
        )

    def send_emergency_alert(self, payload: EventPayload) -> NotificationDetail:
        """Send formatted WhatsApp emergency alert to the configured emergency contact."""
        if not self.is_configured():
            logger.info("Twilio is not configured; skipping WhatsApp dispatch for %s", payload.event_id)
            return NotificationDetail(
                status="skipped",
                provider="twilio_whatsapp",
                message_sid=None,
                delivery_status="not_configured",
                recipient=None,
                note="Twilio credentials not configured in environment. WhatsApp alert was skipped.",
            )

        from_number = self._normalize_whatsapp_number(self.settings.twilio_whatsapp_from)
        to_number = self._normalize_whatsapp_number(self.settings.emergency_whatsapp_to or "")
        masked_to = self.get_masked_recipient()

        try:
            client = self._get_client()

            # Prefer Twilio Content API if ContentSid is configured
            if self.settings.has_valid_content_sid:
                content_sid = (self.settings.twilio_content_sid or "").strip()
                variables = self.get_alert_content_variables(payload)
                message = client.messages.create(
                    from_=from_number,
                    to=to_number,
                    content_sid=content_sid,
                    content_variables=json.dumps(variables),
                )
            else:
                body = self.format_emergency_message(payload)
                message = client.messages.create(
                    from_=from_number,
                    to=to_number,
                    body=body,
                )

            logger.info(
                "Dispatched Twilio emergency alert for %s (SID: %s, status: %s)",
                payload.event_id,
                message.sid,
                message.status,
            )
            return NotificationDetail(
                status="dispatched",
                provider="twilio_whatsapp",
                message_sid=message.sid,
                delivery_status=message.status or "queued_by_twilio",
                recipient=masked_to,
                note=(
                    "Twilio accepted message for dispatch. Delivery to recipient is subject "
                    "to WhatsApp Sandbox participation (recipient must join sandbox)."
                ),
            )
        except TwilioRestException as exc:
            return self._handle_twilio_error(exc, masked_to)
        except Exception as exc:
            logger.error("Unexpected error dispatching Twilio alert: %s", type(exc).__name__)
            return NotificationDetail(
                status="failed",
                provider="twilio_whatsapp",
                message_sid=None,
                delivery_status="failed",
                recipient=masked_to,
                note=f"Dispatch failed: {type(exc).__name__}",
            )

    def send_test_message(self, device_id: str, event_id: str) -> NotificationDetail:
        """Send formatted test message via Twilio WhatsApp Sandbox."""
        if not self.is_configured():
            logger.info("Twilio is not configured; skipping test WhatsApp message for %s", event_id)
            return NotificationDetail(
                status="skipped",
                provider="twilio_whatsapp",
                message_sid=None,
                delivery_status="not_configured",
                recipient=None,
                note="Twilio credentials not configured in environment. Test message was skipped.",
            )

        from_number = self._normalize_whatsapp_number(self.settings.twilio_whatsapp_from)
        to_number = self._normalize_whatsapp_number(self.settings.emergency_whatsapp_to or "")
        masked_to = self.get_masked_recipient()

        try:
            client = self._get_client()

            # Prefer Content API if test or default ContentSid is configured
            effective_sid = self.settings.effective_test_content_sid
            if effective_sid:
                variables = self.get_test_content_variables(device_id, event_id)
                message = client.messages.create(
                    from_=from_number,
                    to=to_number,
                    content_sid=effective_sid,
                    content_variables=json.dumps(variables),
                )
            else:
                body = self.format_test_message(device_id, event_id)
                message = client.messages.create(
                    from_=from_number,
                    to=to_number,
                    body=body,
                )

            logger.info(
                "Dispatched Twilio test message for %s (SID: %s, status: %s)",
                event_id,
                message.sid,
                message.status,
            )
            return NotificationDetail(
                status="dispatched",
                provider="twilio_whatsapp",
                message_sid=message.sid,
                delivery_status=message.status or "queued_by_twilio",
                recipient=masked_to,
                note=(
                    "Twilio accepted test message for dispatch. Delivery to recipient is subject "
                    "to WhatsApp Sandbox participation."
                ),
            )
        except TwilioRestException as exc:
            return self._handle_twilio_error(exc, masked_to)
        except Exception as exc:
            logger.error("Unexpected error dispatching Twilio test message: %s", type(exc).__name__)
            return NotificationDetail(
                status="failed",
                provider="twilio_whatsapp",
                message_sid=None,
                delivery_status="failed",
                recipient=masked_to,
                note=f"Dispatch failed: {type(exc).__name__}",
            )


twilio_service = TwilioWhatsAppService()
