"""RideSafe Backend - Main Application Entrypoint.

Smart two-wheeler accident detection and emergency alert system.
Integrates ESP32 telemetry ingestion, persistent SQLite storage, deduplication,
and Twilio WhatsApp Sandbox emergency notification dispatch.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from app.config import Settings, get_settings
from app.models import (
    AlertResponse,
    ComponentStatus,
    EventPayload,
    EventType,
    HealthResponse,
    SecurityStatus,
    ServiceStatusResponse,
    StorageStatus,
    TestMessageResponse,
    TwilioStatus,
)
from app.storage import DatabaseError, event_store, get_event_store
from app.twilio_service import twilio_service

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager ensuring database schema initialization on startup."""
    store = get_event_store()
    store.init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "Backend service for RideSafe - smart two-wheeler accident detection "
        "and emergency alert system with Twilio WhatsApp dispatch."
    ),
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan,
)


def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    current_settings: Settings = Depends(get_settings),
) -> Optional[str]:
    """Validate X-API-Key header against configured RIDESAFE_API_KEY.

    If RIDESAFE_API_KEY is configured in the environment, all requests to protected
    endpoints must present a matching X-API-Key header.
    """
    if current_settings.is_api_key_configured:
        if not x_api_key or x_api_key != current_settings.ridesafe_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Missing or invalid X-API-Key header.",
            )
    return x_api_key


@app.exception_handler(DatabaseError)
def database_error_handler(request: Request, exc: DatabaseError) -> JSONResponse:
    """Handle persistent database errors gracefully without returning false success."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Persistent storage failure while processing the event."},
    )


@app.get(
    "/",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["Root"],
    summary="Root service health",
    description="Returns the service name, operational health status, and description.",
)
def root_status() -> HealthResponse:
    """Return root service name and health status."""
    return HealthResponse(
        service=settings.app_name,
        status="healthy",
        version="1.0.0",
        message="RideSafe Smart Accident Detection and Emergency Alert Backend is running.",
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["Monitoring"],
    summary="Health check",
    description="Returns a simple JSON response indicating that the service is running.",
)
def health_check() -> HealthResponse:
    """Return basic health status of the application."""
    return HealthResponse(
        status="healthy",
        service="ridesafe-backend",
        version="1.0.0",
        message="Service is healthy.",
    )


@app.get(
    f"{settings.api_prefix}/status",
    response_model=ServiceStatusResponse,
    status_code=status.HTTP_200_OK,
    tags=["Monitoring"],
    summary="RideSafe service status",
    description=(
        "Reports backend operational status, persistent SQLite state, and Twilio WhatsApp "
        "configuration status. Sensitive credentials are never exposed."
    ),
)
def system_status(
    current_settings: Settings = Depends(get_settings),
) -> ServiceStatusResponse:
    """Report detailed backend status, component availability, and configuration."""
    store = get_event_store()
    whatsapp_status = "operational" if current_settings.is_twilio_configured else "not_configured"

    return ServiceStatusResponse(
        status="online",
        service=current_settings.app_name,
        version="1.0.0",
        environment=current_settings.app_env,
        components=ComponentStatus(
            api="operational",
            esp32_receiver="operational",
            whatsapp_alert_service=whatsapp_status,
            storage=StorageStatus(
                type="sqlite",
                initialized=store.is_initialized(),
                database_path=store.db_path,
            ),
        ),
        twilio=TwilioStatus(
            configured=current_settings.is_twilio_configured,
            account_sid_present=current_settings.has_valid_account_sid,
            auth_token_present=current_settings.has_valid_auth_token,
            whatsapp_from_present=bool(current_settings.twilio_whatsapp_from),
            emergency_contact_present=current_settings.has_valid_emergency_contact,
            content_sid_configured=current_settings.has_valid_content_sid,
            recipient_masked=current_settings.get_masked_emergency_contact(),
        ),
        security=SecurityStatus(
            api_key_required=current_settings.is_api_key_configured,
        ),
    )


@app.post(
    f"{settings.api_prefix}/alert",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Events"],
    summary="Ingest emergency accident or manual SOS event",
    description=(
        "Receives confirmed emergency telemetry from an ESP32 device. "
        "Validates coordinates and event schema, deduplicates based on "
        "(device_id, event_id), persists to SQLite, and dispatches a WhatsApp alert via Twilio."
    ),
)
def ingest_alert_event(
    payload: EventPayload,
    _: Optional[str] = Depends(verify_api_key),
) -> AlertResponse:
    """Ingest, validate, store, and dispatch WhatsApp alert for ACCIDENT or MANUAL_SOS."""
    if payload.event == EventType.TEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Test events must be sent to the test endpoint (/api/ridesafe/test).",
        )

    received_at = datetime.now(timezone.utc)

    # Persist event to SQLite; returns False on (device_id, event_id) duplicate
    is_new = event_store.add_event(
        payload=payload,
        received_at=received_at,
        is_test=False,
        is_emergency=True,
    )

    if not is_new:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Duplicate event: event_id '{payload.event_id}' has already been "
                f"processed for device_id '{payload.device_id}'."
            ),
        )

    # Dispatch WhatsApp alert via Twilio Sandbox
    notification = twilio_service.send_emergency_alert(payload)

    return AlertResponse(
        status="received",
        event_id=payload.event_id,
        device_id=payload.device_id,
        event=payload.event,
        is_test=False,
        is_emergency=True,
        received_at=received_at,
        storage="sqlite",
        notification=notification,
        message=(
            "Emergency alert event received and persisted for processing. "
            f"WhatsApp notification status: {notification.status}."
        ),
    )


@app.post(
    f"{settings.api_prefix}/test",
    response_model=TestMessageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Events"],
    summary="Ingest test event and send test WhatsApp message",
    description=(
        "Receives a test event for backend validation and dispatches a clearly labelled "
        "test WhatsApp message via Twilio. Guarantees that real emergency alerts are suppressed."
    ),
)
def ingest_test_event(
    payload: Optional[EventPayload] = None,
    _: Optional[str] = Depends(verify_api_key),
) -> TestMessageResponse:
    """Ingest, store, and dispatch a non-emergency test WhatsApp message."""
    received_at = datetime.now(timezone.utc)

    if payload is None:
        # Default test payload if none provided in request body
        payload = EventPayload(
            device_id="RIDESAFE_TEST_DEVICE",
            event_id=f"test-{int(received_at.timestamp())}",
            event=EventType.TEST,
            gps_valid=False,
            timestamp=received_at,
        )

    is_new = event_store.add_event(
        payload=payload,
        received_at=received_at,
        is_test=True,
        is_emergency=False,
    )

    if not is_new:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Duplicate test event: event_id '{payload.event_id}' has already been "
                f"processed for device_id '{payload.device_id}'."
            ),
        )

    # Dispatch clearly labelled test message via Twilio
    notification = twilio_service.send_test_message(
        device_id=payload.device_id,
        event_id=payload.event_id,
    )

    return TestMessageResponse(
        status="test_acknowledged",
        event_id=payload.event_id,
        device_id=payload.device_id,
        event=payload.event,
        is_test=True,
        is_emergency=False,
        received_at=received_at,
        storage="sqlite",
        notification=notification,
        message="Test event received and acknowledged. Emergency notifications are suppressed.",
    )
