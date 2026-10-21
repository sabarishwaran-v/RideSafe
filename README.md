# RideSafe Backend

**Smart Accident Detection and Emergency Alert System for Two-Wheelers**

RideSafe is a secure, high-reliability FastAPI backend designed to receive real-time accident detection telemetry and manual SOS triggers from an ESP32 microcontroller and dispatch instant emergency WhatsApp notifications using the Twilio WhatsApp Sandbox API.

---

## System Architecture

```text
+--------------------------------------------------------------+
|                    Two-Wheeler (ESP32)                      |
|                                                              |
|  [MPU6050 Gyro/Accel]   [NEO-6M GPS]   [Manual SOS Button]  |
|          |                     |                 |           |
|          +---------------------+-----------------+           |
|                                |                             |
|                    Local Fallback Alert                      |
|                 (Buzzer + Warning Flashers)                  |
|                                |                             |
|                     WiFi HTTPS POST Telemetry                |
+--------------------------------+-----------------------------+
                                 |
                                 v
+--------------------------------------------------------------+
|                       RideSafe Backend                       |
|                                                              |
|   1. API Key Authentication (X-API-Key Header)               |
|   2. Telemetry & GPS Validation (Pydantic v2)                |
|   3. Event Deduplication & SQLite Persistence (sqlite3)      |
|   4. WhatsApp Alert Formatting (Google Maps Link / GPS label)|
+--------------------------------+-----------------------------+
                                 |
                                 v
+--------------------------------------------------------------+
|               Twilio WhatsApp Sandbox Service                |
|                                                              |
|           Dispatches Alert to Configured Contact             |
|                  "whatsapp:+91XXXXXXXXXX"                    |
+--------------------------------------------------------------+
```

---

## Technology Stack

- **Language & Runtime**: Python 3.11+
- **Web Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **ASGI Server**: [Uvicorn](https://www.uvicorn.org/)
- **Data Validation**: [Pydantic v2](https://docs.pydantic.dev/)
- **WhatsApp Gateway**: [Twilio Python SDK](https://www.twilio.com/docs/libraries/python) (`twilio>=9.0.0`)
- **Persistence & Deduplication**: SQLite via standard library `sqlite3` (WAL mode enabled)
- **Configuration Management**: [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) & `python-dotenv`
- **Automated Testing**: [pytest](https://docs.pytest.org/) and HTTPX

---

## Project Structure

```text
RideSafe Software/
├── .env.example              # Environment variable configuration template (no secrets)
├── .gitignore                # Git exclusions (virtualenvs, .env, *.db, test caches)
├── README.md                 # Complete documentation and API specification
├── requirements.txt          # Production and test dependencies
├── app/
│   ├── __init__.py           # Application package marker
│   ├── config.py             # Central settings module (Pydantic Settings)
│   ├── main.py               # FastAPI application, route handlers, and security
│   ├── models.py             # Telemetry payloads, event types, and response models
│   ├── schemas.py            # Backward-compatible re-exports from models
│   ├── storage.py            # SQLite event store and deduplication manager
│   └── twilio_service.py     # Twilio WhatsApp formatting, masking, and dispatch
├── data/                     # Database directory (auto-created on startup, gitignored)
│   └── ridesafe.db           # Persistent SQLite database
└── tests/
    ├── __init__.py           # Test package marker
    ├── conftest.py           # Pytest test isolation fixtures
    ├── test_api_endpoints.py # Tests for root, status, Twilio dispatch, and API key
    ├── test_config.py        # Settings and environment variable tests
    ├── test_events.py        # Telemetry ingestion, GPS rules, and validation tests
    ├── test_main.py          # Legacy endpoint compatibility tests
    ├── test_storage_sqlite.py# SQLite persistence and concurrency tests
    └── test_twilio_service.py# WhatsApp message formatting and Twilio mock tests
```

---

## Setup & Installation

### Prerequisites
- Python 3.11 or higher installed on your system.
- Git (optional, for version control).

### 1. macOS & Linux Setup

```bash
# Navigate to the project root
cd "RideSafe Software"

# Create a virtual environment
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Windows Setup

**Command Prompt (cmd.exe):**
```cmd
cd "RideSafe Software"
python -m venv .venv
.venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
```

**PowerShell:**
```powershell
cd "RideSafe Software"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Configuration (`.env`)

1. Copy the provided `.env.example` file to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` and fill in your values:

```env
# Application Settings
APP_NAME="RideSafe Backend"
APP_ENV=development
DEBUG=false
HOST=0.0.0.0
PORT=8000
API_PREFIX=/api/ridesafe

# SQLite Database Path
DATABASE_PATH=data/ridesafe.db

# API Key Authentication
# Shared secret required in 'X-API-Key' header on /api/ridesafe/alert and /api/ridesafe/test
RIDESAFE_API_KEY=your_secret_api_key_here

# Twilio WhatsApp Sandbox Credentials (from https://console.twilio.com/)
TWILIO_ACCOUNT_SID=ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here

# Twilio WhatsApp Sender Number (default Sandbox number)
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# Emergency Recipient WhatsApp Number (E.164 format with country code)
EMERGENCY_WHATSAPP_TO=whatsapp:+919876543210
```

> [!CAUTION]
> **Credential Security**: Never commit `.env` or real API credentials to Git. The `.gitignore` file automatically excludes `.env` and SQLite database files.

---

## Running the Server Locally

Start the Uvicorn development server with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- **Server Root**: `http://127.0.0.1:8000/`
- **Interactive Swagger UI**: `http://127.0.0.1:8000/docs`
- **Alternative ReDoc UI**: `http://127.0.0.1:8000/redoc`

---

## API Endpoints

### 1. `GET /` — Root Health Check
Returns basic service availability and health status.

**Response (HTTP 200 OK):**
```json
{
  "service": "RideSafe Backend",
  "status": "healthy",
  "version": "1.0.0",
  "message": "RideSafe Smart Accident Detection and Emergency Alert Backend is running."
}
```

---

### 2. `GET /api/ridesafe/status` — System Status
Reports the operational status of backend components, persistent storage, and Twilio integration. Credentials are never exposed.

**Response (HTTP 200 OK):**
```json
{
  "status": "online",
  "service": "RideSafe Backend",
  "version": "1.0.0",
  "environment": "development",
  "phase": "Phase 4 - Twilio WhatsApp Integration",
  "components": {
    "api": "operational",
    "esp32_receiver": "operational",
    "whatsapp_alert_service": "operational",
    "storage": {
      "type": "sqlite",
      "initialized": true,
      "database_path": "data/ridesafe.db"
    }
  },
  "twilio": {
    "configured": true,
    "account_sid_present": true,
    "auth_token_present": true,
    "whatsapp_from_present": true,
    "emergency_contact_present": true,
    "recipient_masked": "whatsapp:+91****3210"
  },
  "security": {
    "api_key_required": true
  }
}
```

---

### 3. `POST /api/ridesafe/test` — Test WhatsApp Notification
Dispatches a clearly labelled non-emergency test WhatsApp message via Twilio. Requires `X-API-Key` if configured. Real emergency services are never alerted.

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: your_secret_api_key_here`

**Request Body (Optional):**
```json
{
  "event_id": "test-evt-001",
  "device_id": "ESP32-BENCH-01",
  "event": "TEST",
  "gps_valid": false,
  "timestamp": "2026-10-21T10:30:00"
}
```

**Response (HTTP 201 Created):**
```json
{
  "status": "test_acknowledged",
  "event_id": "test-evt-001",
  "device_id": "ESP32-BENCH-01",
  "event": "TEST",
  "is_test": true,
  "is_emergency": false,
  "received_at": "2026-10-21T10:30:01.123456Z",
  "storage": "sqlite",
  "notification": {
    "status": "dispatched",
    "provider": "twilio_whatsapp",
    "message_sid": "SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    "delivery_status": "queued_by_twilio",
    "recipient": "whatsapp:+91****3210",
    "note": "Twilio accepted test message for dispatch. Delivery to recipient is subject to WhatsApp Sandbox participation."
  },
  "message": "Test event received and acknowledged. Emergency notifications are suppressed."
}
```

---

### 4. `POST /api/ridesafe/alert` — Ingest Emergency Telemetry
Receives confirmed accident or manual SOS telemetry from the ESP32. Validates schema and GPS rules, deduplicates by `(device_id, event_id)`, logs to SQLite, and dispatches a WhatsApp emergency alert.

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: your_secret_api_key_here`

**Request Body (Accident with GPS fix):**
```json
{
  "event_id": "unique-event-id",
  "device_id": "RIDESAFE_01",
  "event": "ACCIDENT",
  "latitude": 13.0827,
  "longitude": 80.2707,
  "altitude": 42.5,
  "speed_kmph": 12.7,
  "tilt_degrees": 48.2,
  "gps_valid": true,
  "timestamp": "2026-10-21T10:30:00"
}
```

**Allowed Event Types:** `ACCIDENT` and `MANUAL_SOS`. (`TEST` events sent here return HTTP 400 Bad Request).

**GPS Ingestion Rules:**
- If `gps_valid: true`, both `latitude` (-90 to 90) and `longitude` (-180 to 180) are strictly required.
- If `gps_valid: false`, `latitude` and `longitude` can be `null`. Missing GPS fix will be explicitly labelled in the WhatsApp alert.
- Coordinates are never fabricated or guessed.

**Response (HTTP 201 Created):**
```json
{
  "status": "received",
  "event_id": "unique-event-id",
  "device_id": "RIDESAFE_01",
  "event": "ACCIDENT",
  "is_test": false,
  "is_emergency": true,
  "received_at": "2026-10-21T10:30:01.000000Z",
  "storage": "sqlite",
  "notification": {
    "status": "dispatched",
    "provider": "twilio_whatsapp",
    "message_sid": "SMXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    "delivery_status": "queued_by_twilio",
    "recipient": "whatsapp:+91****3210",
    "note": "Twilio accepted message for dispatch. Delivery to recipient is subject to WhatsApp Sandbox participation."
  },
  "message": "Emergency alert event received and persisted for processing. WhatsApp notification status: dispatched."
}
```

---

## WhatsApp Alert Content Specification

### 1. Alert Message with Valid GPS Fix
```text
🚨 *RIDESAFE EMERGENCY ALERT* 🚨

*Event:* ACCIDENT
*Device ID:* RIDESAFE_01
*Time:* 2026-10-21 10:30:00 UTC

📊 *Telemetry:*
• Speed: 12.7 km/h
• Tilt Angle: 48.2°
• Altitude: 42.5 m

📍 *Location:*
Latitude: 13.082700
Longitude: 80.270700
🔗 *Google Maps:* https://maps.google.com/?q=13.0827,80.2707

⚠️ *NOTICE:* This is an automated emergency alert from RideSafe. Immediate verification required.
```

### 2. Alert Message when GPS is Unavailable (`gps_valid: false`)
```text
🚨 *RIDESAFE EMERGENCY ALERT* 🚨

*Event:* MANUAL SOS
*Device ID:* RIDESAFE_01
*Time:* 2026-10-21 10:30:00 UTC

📊 *Telemetry:*
• Speed: 0.0 km/h
• Tilt Angle: 12.0°

📍 *Location:*
⚠️ *GPS Fix Unavailable / No Location Acquired*

⚠️ *NOTICE:* This is an automated emergency alert from RideSafe. Immediate verification required.
```

---

## Twilio WhatsApp Sandbox Setup & Production Guidelines

### Sandbox Setup for Development & Testing
1. Log into your [Twilio Console](https://console.twilio.com/).
2. Navigate to **Messaging** > **Try it out** > **Send a WhatsApp message**.
3. Locate your Sandbox phone number (e.g. `+1 415 523 8886` or your assigned regional sandbox number) and the unique join keyword (e.g. `join bright-lemur`).
4. **Mandatory Step**: The emergency recipient phone number specified in `EMERGENCY_WHATSAPP_TO` **must send the join keyword via WhatsApp** to your sandbox phone number. Until the recipient joins, Twilio will reject dispatch with code `63015`.
5. Copy your **Account SID** and **Auth Token** into `.env`.

---

## Twilio Content Templates (Resolving Error 21654: "ContentSid Required")

### Why Twilio Error 21654 Occurs
Meta and Twilio WhatsApp policies require business-initiated outbound messages outside of an active 24-hour customer service window to use **pre-approved Content Templates**. When attempting to send a raw `body` text to a recipient where template messaging is enforced, Twilio returns:
```text
Twilio API error 21654: "Unable to create record: ContentSid Required"
```

### How to Configure `TWILIO_CONTENT_SID`

#### Option 1: Use the Built-in Sandbox Template (Fastest)
1. In Twilio Console, go to **Messaging** > **Try it out** > **Send a WhatsApp message**.
2. Switch to the **Code Samples** tab (select Python or cURL).
3. Twilio displays the pre-configured Sandbox template ID in the code sample:
   ```python
   content_sid="HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # (copy the exact SID starting with HX from your console)
   ```
4. Copy that `HX...` value and add it to your local `.env`:
   ```env
   TWILIO_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   *(The backend automatically formats the default positional variables `{"1": ..., "2": ...}` for you!)*

#### Option 2: Create a Custom RideSafe Template
1. In Twilio Console, navigate to **Messaging** > **Content Template Builder**.
2. Click **Create new**, choose **WhatsApp**, and enter your template body with numbered placeholders, for example:
   ```text
   🚨 *RIDESAFE EMERGENCY ALERT*
   Event: {{1}}
   Device: {{2}}
   Time: {{3}}
   Telemetry: {{4}}
   Location: {{5}}
   ```
3. Submit the template. Once created, copy its **Content SID** (starts with `HX`).
4. Paste it into your local `.env`:
   ```env
   TWILIO_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
5. *(Optional)* If your template has custom variable names, configure `TWILIO_CONTENT_VARIABLES` in `.env`:
   ```env
   TWILIO_CONTENT_VARIABLES='{"1": "{event}", "2": "{device_id}", "3": "{timestamp}", "4": "{telemetry}", "5": "{location}"}'
   ```
   Available placeholder tokens: `{event}`, `{device_id}`, `{event_id}`, `{timestamp}`, `{telemetry}`, `{location}`, `{speed}`, `{tilt}`, `{latitude}`, `{longitude}`, `{message}`.

> [!WARNING]
> **Sandbox Limitations**:
> - Twilio Sandbox is strictly for development and prototyping.
> - Messages can only be sent to phone numbers that have explicitly opted into your sandbox session.
> - Sandbox sessions expire after 72 hours of inactivity and must be re-joined.
> - **Production Deployment**: Requires an approved **Meta WhatsApp Business Account (WABA)**, a registered Sender Number, and Meta-approved message templates for outbound emergency broadcasts outside the 24-hour customer service window.
> - **Never trigger real emergency notifications during testing without explicit recipient permission.**

---

## Reliability & Delivery Semantics

### 1. Delivery State Differentiation
The API explicitly differentiates between three stages:
1. **Backend Event Acceptance**: The backend verified the JSON schema, enforced GPS validity rules, and persisted the event to SQLite (`status="received"`).
2. **Twilio Message Queuing**: Twilio validated your account credentials, verified the payload syntax, and accepted the message for queued transmission (`notification.delivery_status="queued_by_twilio"`).
3. **Confirmed Recipient Delivery**: Final delivery to the recipient's phone. Because WhatsApp delivery is asynchronous, Twilio API acceptance does not guarantee immediate physical receipt (e.g. phone off, sandbox expired).

### 2. Local Deduplication Policy
- Deduplication is enforced at the database level using a composite constraint:
  `UNIQUE (device_id, event_id)`
- When an identical `(device_id, event_id)` is submitted a second time:
  - SQLite triggers a unique constraint violation.
  - The API responds with **HTTP 409 Conflict**.
  - **No duplicate WhatsApp message is sent.**
- **Deduplication Limitations**:
  - Deduplication relies on `event_id`. If an ESP32 firmware bug generates a new `event_id` for the same physical impact, the backend will treat it as a new event.
  - In single-node deployments, deduplication is local to the SQLite database file (`data/ridesafe.db`). Distributed multi-region setups would require centralized Redis or PostgreSQL caching.

### 3. ESP32 Hardware Independence
- The physical ESP32 device must handle accident detection (MPU6050 thresholds), local buzzer alarms, and LED flashing **locally on the microcontroller**.
- Microcontroller safety mechanisms must never block or wait synchronously on backend HTTP responses or WhatsApp network availability.
- The backend will never trigger automatic blind retries that could result in multiple duplicate emergency alerts.

---

## Security & Production Hardening

- **API Key Header**: All telemetry endpoints (`/api/ridesafe/alert` and `/api/ridesafe/test`) enforce header-based authentication via `X-API-Key`.
- **HTTPS Requirement**: In real deployments, you **must terminate TLS/HTTPS** using a reverse proxy (such as Nginx, Traefik, or Caddy) or an API Gateway. Never transmit raw telemetry or API keys over unencrypted HTTP over the public internet.
- **Credential Protection**: Credentials (`TWILIO_AUTH_TOKEN`, `RIDESAFE_API_KEY`) are read strictly from the environment and are never echoed in logs or responses.

---

## Example `curl` Commands

### 1. Check Root Health
```bash
curl -X GET "http://127.0.0.1:8000/"
```

### 2. Inspect System Status
```bash
curl -X GET "http://127.0.0.1:8000/api/ridesafe/status"
```

### 3. Send Test WhatsApp Alert
```bash
curl -X POST "http://127.0.0.1:8000/api/ridesafe/test" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_api_key_here" \
  -d '{
    "device_id": "ESP32-BENCH-01",
    "event_id": "test-manual-001",
    "event": "TEST",
    "gps_valid": false,
    "timestamp": "2026-10-21T10:30:00"
  }'
```

### 4. Send Confirmed Emergency Alert (Accident with GPS)
```bash
curl -X POST "http://127.0.0.1:8000/api/ridesafe/alert" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_api_key_here" \
  -d '{
    "event_id": "evt-live-accident-01",
    "device_id": "RIDESAFE_01",
    "event": "ACCIDENT",
    "latitude": 13.0827,
    "longitude": 80.2707,
    "altitude": 42.5,
    "speed_kmph": 12.7,
    "tilt_degrees": 48.2,
    "gps_valid": true,
    "timestamp": "2026-10-21T10:30:00"
  }'
```

### 5. Send Emergency Alert with GPS Unavailable
```bash
curl -X POST "http://127.0.0.1:8000/api/ridesafe/alert" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_api_key_here" \
  -d '{
    "event_id": "evt-sos-tunnel-02",
    "device_id": "RIDESAFE_01",
    "event": "MANUAL_SOS",
    "latitude": null,
    "longitude": null,
    "altitude": null,
    "speed_kmph": 0.0,
    "tilt_degrees": 12.5,
    "gps_valid": false,
    "timestamp": "2026-10-21T10:35:00"
  }'
```

---

## Automated Tests

Run the comprehensive automated test suite with:

```bash
pytest -v
```

The test suite covers:
- Root (`GET /`) and Status (`GET /api/ridesafe/status`) endpoints.
- API Key verification (`401 Unauthorized` on missing/invalid keys).
- GPS rules (coordinate ranges, requirement when `gps_valid=True`, null coordinates when `gps_valid=False`).
- Naive and timezone-aware ISO datetime parsing.
- SQLite persistent storage and deduplication (`409 Conflict`).
- Twilio WhatsApp message formatting (Google Maps links, GPS warning labels, disclaimers).
- Twilio dispatch handling (mocked success, unconfigured fallback, and `TwilioRestException` error handling).
