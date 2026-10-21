# RideSafe – Smart Accident Detection and Emergency Alert System for Two-Wheelers

An autonomous edge-to-cloud safety system that continuously monitors two-wheeler dynamics, automatically detects collisions and vehicle rollovers, ingests manual SOS triggers, and dispatches real-time emergency WhatsApp notifications with GPS navigation links to designated emergency contacts.

---

## Table of Contents

- [1. Project Overview & Problem Statement](#1-project-overview--problem-statement)
- [2. Objectives](#2-objectives)
- [3. Key Features](#3-key-features)
- [4. System Architecture](#4-system-architecture)
- [5. Hardware Components](#5-hardware-components)
- [6. Confirmed ESP32 Pin Configuration](#6-confirmed-esp32-pin-configuration)
- [7. Accident Detection Workflow (Planned Architecture)](#7-accident-detection-workflow-planned-architecture)
- [8. Manual SOS Workflow (Planned Architecture)](#8-manual-sos-workflow-planned-architecture)
- [9. Backend Technology Stack](#9-backend-technology-stack)
- [10. Project Directory Structure](#10-project-directory-structure)
- [11. Prerequisites](#11-prerequisites)
- [12. Local Installation & Setup](#12-local-installation--setup)
- [13. Environment Variable Configuration](#13-environment-variable-configuration)
- [14. Running the Backend](#14-running-the-backend)
- [15. API Endpoints & Telemetry Specifications](#15-api-endpoints--telemetry-specifications)
- [16. Twilio WhatsApp Sandbox Setup & Testing](#16-twilio-whatsapp-sandbox-setup--testing)
- [17. Security & Safety Considerations](#17-security--safety-considerations)
- [18. Testing Instructions & Verified Results](#18-testing-instructions--verified-results)
- [19. Current Implementation Status & Next Steps](#19-current-implementation-status--next-steps)
- [20. Limitations](#20-limitations)
- [21. License & Contribution Guidance](#21-license--contribution-guidance)

---

## 1. Project Overview & Problem Statement

Two-wheeler riders represent a vulnerable segment of global road traffic. Following a severe road accident, the probability of survival hinges on medical intervention within the **"Golden Hour"**—the initial sixty minutes post-trauma. In many real-world scenarios, however:
- The rider is knocked unconscious or physically trapped, unable to reach their smartphone.
- Accidents occur on isolated roadways or during late-night hours without immediate eyewitnesses.
- Emergency contacts or services are notified only after extensive delays, aggravating traumatic outcomes.

**RideSafe** addresses this problem by deploying an embedded on-vehicle sensor node (ESP32) coupled with a cloud-connected REST API backend. The system continuously tracks inertial changes and vehicle tilt. When a critical collision or rollover threshold is detected—or when the rider manually presses an emergency panic button—the system immediately activates local alarms and transmits georeferenced telemetry to the RideSafe backend, which formats and dispatches an instant WhatsApp notification containing the exact incident location and a one-click Google Maps navigation link.

---

## 2. Objectives

1. **Autonomous Collision & Rollover Detection**: Continuously monitor linear acceleration and angular tilt to distinguish severe impacts from routine vehicle vibration.
2. **Instant Geolocation Extraction**: Extract precise latitude, longitude, speed, and altitude metrics at the time of the event via a dedicated satellite GPS module.
3. **Dual-Tier Emergency Response**:
   - **Local Tier**: Immediate on-bike audible (buzzer) and visual (LED) warnings to alert nearby pedestrians and emergency responders.
   - **Cloud Tier**: Low-latency remote WhatsApp notification dispatch to designated emergency contacts.
4. **Manual SOS Panic Mechanism**: Provide a reliable hardware switch for situations where the rider requires urgent assistance without a physical crash (e.g., sudden medical distress, vehicle breakdown, or threat to personal safety).
5. **Robust, Verifiable Backend Architecture**: Enforce strict data schema validation, persistent event logging via SQLite in WAL mode, and database-level duplicate event suppression to prevent notification spam.

---

## 3. Key Features

- **Inertial Measurement**: Uses a 6-degree-of-freedom MPU6050 accelerometer/gyroscope for impact force and roll-angle detection.
- **Satellite Geolocation**: Synchronizes with a NEO-6M GPS receiver for live coordinates, speed, and altitude tracking.
- **Hardware Panic Button**: Interrupt-driven manual SOS button with software debounce and internal pull-up.
- **Fail-Safe Local Feedback**: Dedicated active buzzer and LED flashers activate locally even if cellular or Wi-Fi network connectivity is disrupted.
- **API Key Security**: Endpoints require `X-API-Key` header authentication to protect against unauthorized ingestion.
- **Strict Coordinate Validation**: Pydantic v2 model ensures coordinate boundaries (latitude: -90° to 90°, longitude: -180° to 180°); coordinates cannot be fabricated if GPS is invalid.
- **SQLite Persistence & WAL Mode**: Durable storage with Write-Ahead Logging for high-concurrency event ingestion and restart survival.
- **Atomic Event Deduplication**: Database constraint `UNIQUE(device_id, event_id)` rejects duplicate transmissions with `HTTP 409 Conflict`.
- **Twilio WhatsApp Integration**: Dispatches formatted messages via Twilio's WhatsApp API, supporting both freeform messages and approved Twilio Content Templates (`ContentSid`) to eliminate Twilio Error 21654.
- **Safe Test Pipeline**: Dedicated `/api/ridesafe/test` route dispatches clearly marked non-emergency notifications, preventing false alarms during development and testing.

---

## 4. System Architecture

```text
+-------------------------------------------------------------------------------+
|                             TWO-WHEELER EDGE NODE                             |
|                                                                               |
|   +-------------------+     +------------------+     +--------------------+   |
|   |  MPU6050 IMU      |     |  NEO-6M GPS      |     |  Manual SOS Button |   |
|   |  (Accel / Gyro)   |     |  (NMEA Telemetry)|     |  (Active-Low GPIO) |   |
|   +---------+---------+     +--------+---------+     +---------+----------+   |
|             | I2C                    | UART                    | GPIO Interrupt
|             +------------------------+-------------------------+              |
|                                      v                                        |
|                          +-----------------------+                            |
|                          |   ESP32 Microcontroller|                           |
|                          +-----------+-----------+                            |
|                                      |                                        |
|                 +--------------------+--------------------+                   |
|                 | Local Output                            | Remote Telemetry  |
|                 v                                         v                   |
|   +----------------------------+            +----------------------------+    |
|   |  Local Alarm Subsystem     |            |  Wi-Fi / HTTPS POST Client |    |
|   |  • Active Buzzer (GPIO 33) |            |  (SSL/TLS Secure Channel)  |    |
|   |  • Warning LED  (GPIO 32)  |            +--------------+-------------+    |
|   +----------------------------+                           |                  |
+------------------------------------------------------------|------------------+
                                                             |
                                      HTTPS POST JSON Payload| (X-API-Key Header)
                                                             v
+-------------------------------------------------------------------------------+
|                               RIDESAFE BACKEND                                |
|                                                                               |
|   +-----------------------------------------------------------------------+   |
|   |  FastAPI Application Server (Uvicorn ASGI)                            |   |
|   |                                                                       |   |
|   |   1. Authentication Filter: Verifies 'X-API-Key' header               |   |
|   |   2. Pydantic v2 Validator: Type checking, GPS coordinate bounds      |   |
|   |   3. Persistence Layer: SQLite (data/ridesafe.db, WAL Mode)           |   |
|   |   4. Deduplication Engine: UNIQUE(device_id, event_id) constraint     |   |
|   |   5. WhatsApp Service: Twilio Content API & message formatting        |   |
|   +-----------------------------------+-----------------------------------+   |
|                                       |                                       |
+---------------------------------------|---------------------------------------+
                                        | Twilio REST API HTTPS Request
                                        v
+-------------------------------------------------------------------------------+
|                     TWILIO WHATSAPP GATEWAY (SANDBOX / WABA)                  |
|                                                                               |
|   • Authenticates Account SID & Auth Token                                    |
|   • Resolves Content Template (ContentSid HX...)                              |
|   • Queues outbound WhatsApp message                                          |
+---------------------------------------+---------------------------------------+
                                        | WhatsApp Delivery
                                        v
+-------------------------------------------------------------------------------+
|                       EMERGENCY RECIPIENT SMARTPHONE                          |
|                                                                               |
|   📱 Incoming WhatsApp Alert:                                                 |
|      - Event Type: ACCIDENT or MANUAL SOS                                     |
|      - Device ID & Timestamp                                                  |
|      - Impact Speed, Tilt Angle, Altitude                                     |
|      - Precise Latitude & Longitude                                           |
|      - Direct Google Maps Navigation Link                                     |
+-------------------------------------------------------------------------------+
```

---

## 5. Hardware Components

The edge hardware prototype is composed of standard, readily available embedded components:

| Component | Function / Role | Interface | Operating Voltage |
| :--- | :--- | :--- | :--- |
| **ESP32 DevKit V1** | Central microcontroller, sensor polling, threshold processing, and Wi-Fi HTTPS client | CPU / Wi-Fi | 5V (USB) / 3.3V Logic |
| **MPU6050** | 3-axis accelerometer and 3-axis gyroscope measuring dynamic impact forces and vehicle lean angle | I2C | 3.3V – 5V (VCC to 3.3V) |
| **NEO-6M GPS Module** | Satellite positioning receiver providing NMEA latitude, longitude, ground speed, and altitude | UART Serial | 3.3V – 5V (VCC to 5V/3.3V) |
| **Momentary Push Button** | Physical handlebar-mounted panic switch for manual distress triggering | Digital Input | Pulled to 3.3V internally |
| **Active Buzzer** | High-decibel local audible alarm to alert nearby commuters | Digital Output | 3.3V – 5V |
| **Warning LED (5mm)** | High-visibility optical beacon indicating alert state | Digital Output | 3.3V (with current-limiting resistor) |

---

## 6. Confirmed ESP32 Pin Configuration

The following pin assignments have been verified for the ESP32 edge implementation:

```text
               +--------------------------------------+
               |            ESP32 DEVKIT              |
               |                                      |
   MPU6050 SDA | [GPIO 25]                  [GPIO 33] | Buzzer Signal (+)
   MPU6050 SCL | [GPIO 26]                  [GPIO 32] | Warning LED (+)
        GPS TX | [GPIO 18] (ESP32 RX2)      [GPIO 13] | SOS Button (To GND)
        GPS RX | [GPIO 19] (ESP32 TX2)                |
               +--------------------------------------+
```

### Detailed Pinout Specification

| Peripheral Component | Pin Name / Function | ESP32 GPIO | Electrical Connection & Configuration |
| :--- | :--- | :--- | :--- |
| **MPU6050 IMU** | `SDA` (Serial Data) | **GPIO 25** | Hardware I2C data line |
| **MPU6050 IMU** | `SCL` (Serial Clock) | **GPIO 26** | Hardware I2C clock line |
| **NEO-6M GPS** | `TX` (Module Transmit) | **GPIO 18** | Connected to ESP32 UART RX (HardwareSerial 2) |
| **NEO-6M GPS** | `RX` (Module Receive) | **GPIO 19** | Connected to ESP32 UART TX (HardwareSerial 2) |
| **SOS Panic Button** | Signal Lead | **GPIO 13** | Connected between GPIO 13 and GND; firmware uses `pinMode(13, INPUT_PULLUP)` |
| **Active Buzzer** | Control (+) | **GPIO 33** | Digital output; driven `HIGH` to sound alarm |
| **Warning LED** | Anode (+) | **GPIO 32** | Digital output through a 220Ω / 330Ω resistor to GND; driven `HIGH` to flash |

> [!NOTE]
> All sensors and peripherals must share a common ground (`GND`) with the ESP32. Power modules according to their verified manufacturer specifications.

---

## 7. Accident Detection Workflow (Planned Architecture)

> [!NOTE]
> **Planned Firmware Architecture**: The edge detection workflow below outlines the planned microcontroller algorithm. Because physical hardware assembly and firmware integration are pending project milestones, the thresholds shown (such as an impact acceleration spike > 3.0g and sustained lean tilt > 45°) are provisional engineering targets awaiting empirical on-bike calibration.

```text
[ESP32 Boot]
      │
      ▼
[Sample MPU6050 Acceleration & Gyroscope at Periodic Intervals]
      │
      ▼
[Is Acceleration Spike > Impact Threshold (e.g. > 3.0g)?]
      ├─► NO  ──► Continue Monitoring
      └─► YES
            │
            ▼
[Evaluate Gyroscope Tilt: Is Lean Angle > 45° for Sustained Time Window?]
      ├─► NO  ──► Ignore transient shock (e.g., speed bump/pothole)
      └─► YES ──► Accident Confirmed
            │
            ▼
[Trigger Immediate Local Alarm (GPIO 33 Buzzer HIGH, GPIO 32 LED Flashing)]
            │
            ▼
[Read Current GPS Fix from NEO-6M UART (Latitude, Longitude, Altitude, Speed)]
            │
            ▼
[Construct JSON Payload with Unique event_id, device_id, and Telemetry]
            │
            ▼
[Transmit HTTPS POST to /api/ridesafe/alert with X-API-Key]
            │
            ▼
[Backend Validates, Stores in SQLite, and Dispatches WhatsApp via Twilio]
```

---

## 8. Manual SOS Workflow (Planned Architecture)

> [!NOTE]
> **Provisional Edge Design**: The hardware interrupt, software debounce timing (~50ms), and internal pull-up mechanism represent the planned embedded design for the upcoming ESP32 firmware implementation.

```text
[Rider in Distress Presses SOS Button (GPIO 13 to GND)]
      │
      ▼
[Hardware Interrupt / Polling detects Falling Edge on GPIO 13]
      │
      ▼
[Debounce Check: Is Button Held for > 50ms?]
      ├─► NO  ──► Discard Electrical Noise
      └─► YES ──► Manual Emergency Confirmed
            │
            ▼
[Activate Local Audible & Visual Acknowledgement (Buzzer & LED Pulse)]
            │
            ▼
[Query Latest Valid GPS Coordinates from NEO-6M Cache]
            │
            ▼
[Construct Payload: event="MANUAL_SOS", gps_valid=true/false]
            │
            ▼
[Transmit HTTPS POST to /api/ridesafe/alert]
            │
            ▼
[Backend Dispatches WhatsApp Notification to Emergency Contact]
```

---

## 9. Backend Technology Stack

| Layer / Role | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Runtime** | Python | `3.11+` | Asynchronous core execution environment |
| **Web Framework** | FastAPI | `>=0.115.0` | High-performance, type-hinted REST API framework |
| **ASGI Server** | Uvicorn | `>=0.30.0` | Production-grade asynchronous HTTP server |
| **Data Validation** | Pydantic v2 | `>=2.8.0` | Strict payload schema enforcement and coordinate bounds checking |
| **Settings Management** | Pydantic Settings & python-dotenv | `>=2.4.0` | Environment variable parsing and `.env` secret isolation |
| **Database** | SQLite3 (standard library) | Standard | Thread-safe persistent event storage with WAL mode enabled |
| **WhatsApp Gateway** | Twilio Python SDK | `>=9.0.0` | Official client for Twilio Messaging and Content APIs |
| **Testing** | pytest & HTTPX | `>=8.0.0` / `>=0.27.0` | Automated test suite and asynchronous API test client |

---

## 10. Project Directory Structure

```text
RideSafe/
├── .env.example              # Environment variable template with safe placeholders
├── .gitignore                # Git exclusions (.env, .venv, *.db, test caches)
├── README.md                 # Complete project documentation and specifications
├── requirements.txt          # Python production and development dependencies
├── app/
│   ├── __init__.py           # Application package marker
│   ├── config.py             # Central Pydantic Settings configuration and validation
│   ├── main.py               # FastAPI application, route handlers, and security middleware
│   ├── models.py             # Pydantic v2 telemetry payloads, event enums, and response models
│   ├── schemas.py            # Backward-compatible re-exports from models
│   ├── storage.py            # SQLite event persistence engine and deduplication manager
│   └── twilio_service.py     # Twilio WhatsApp dispatch service (Body and Content API)
├── data/                     # Local SQLite database directory (auto-created, gitignored)
│   └── ridesafe.db           # Persistent SQLite database (WAL mode)
└── tests/
    ├── __init__.py           # Test package marker
    ├── conftest.py           # Pytest fixtures and isolated testing environment
    ├── test_api_endpoints.py # Tests for health, status, API key, and Twilio dispatch
    ├── test_config.py        # Tests for configuration parsing and default values
    ├── test_events.py        # Ingestion tests, GPS coordinate rules, and validation
    ├── test_main.py          # Legacy endpoint compatibility tests
    ├── test_storage_sqlite.py# Tests for SQLite persistence, WAL mode, and deduplication
    └── test_twilio_service.py# Tests for WhatsApp message formatting and Twilio mock dispatch
```

---

## 11. Prerequisites

Before installing the backend, ensure your environment meets the following requirements:
- **Operating System**: macOS, Linux (Ubuntu/Debian), or Windows 10/11.
- **Python**: Version `3.11` or higher (`python3 --version`).
- **Git**: Installed and configured (`git --version`).
- **Twilio Account**: Required for live WhatsApp notifications ([Twilio Console](https://console.twilio.com/)).

---

## 12. Local Installation & Setup

### Step 1: Clone the Repository
```bash
git clone https://github.com/sabarishwaran-v/RideSafe.git
cd RideSafe
```

### Step 2: Set Up Python Virtual Environment

**On macOS and Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**On Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Step 3: Upgrade pip and Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 13. Environment Variable Configuration

The backend reads configuration settings from environment variables or a local `.env` file.

> [!CAUTION]
> **Secret Protection**: Never commit your real `.env` file or credentials to Git. The project `.gitignore` explicitly excludes `.env` and all SQLite database files.

1. Create your local `.env` file by copying the provided template:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` and fill in the required parameters:

| Environment Variable | Required | Description | Example / Default |
| :--- | :---: | :--- | :--- |
| `APP_NAME` | No | Display name of the backend service | `"RideSafe Backend"` |
| `APP_ENV` | No | Application environment (`development`, `production`) | `development` |
| `DEBUG` | No | Enables verbose logging | `false` |
| `HOST` | No | Host IP address to bind Uvicorn server | `0.0.0.0` |
| `PORT` | No | Listening port for HTTP traffic | `8000` |
| `API_PREFIX` | No | Base prefix for all RideSafe endpoints | `/api/ridesafe` |
| `DATABASE_PATH` | No | File path for persistent SQLite database | `data/ridesafe.db` |
| `RIDESAFE_API_KEY` | **Yes** | Shared secret key required in `X-API-Key` header | `ridesafe_secret_key_change_me` |
| `TWILIO_ACCOUNT_SID` | **Yes** | Twilio Account SID (starts with `AC...`) | `ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX` |
| `TWILIO_AUTH_TOKEN` | **Yes** | Twilio primary Auth Token | `your_auth_token_here` |
| `TWILIO_WHATSAPP_FROM` | **Yes** | Twilio WhatsApp sender number with `whatsapp:` prefix | `whatsapp:+14155238886` |
| `EMERGENCY_WHATSAPP_TO`| **Yes** | Recipient contact number (E.164) with `whatsapp:` prefix | `whatsapp:+919876543210` |
| `TWILIO_CONTENT_SID` | Optional | Pre-approved Twilio Content Template SID (starts with `HX...`) | `HXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX` |
| `TWILIO_TEST_CONTENT_SID` | Optional | Dedicated Content SID for the `/test` endpoint | Defaults to `TWILIO_CONTENT_SID` |
| `TWILIO_CONTENT_VARIABLES`| Optional | JSON mapping for custom template variables | Positional mapping `{"1": ..., "2": ...}` |

---

## 14. Running the Backend

Start the development server with live reload enabled:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-include "*.env"
```

Once running:
- **Root Service**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **System Status**: [http://127.0.0.1:8000/api/ridesafe/status](http://127.0.0.1:8000/api/ridesafe/status)
- **Interactive Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Alternative ReDoc UI**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 15. API Endpoints & Telemetry Specifications

### 1. Root Health Check — `GET /`
Verifies that the web service is operational.

**Example Request:**
```bash
curl -X GET "http://127.0.0.1:8000/"
```

**Response (`HTTP 200 OK`):**
```json
{
  "service": "RideSafe Backend",
  "status": "healthy",
  "version": "1.0.0",
  "message": "RideSafe Smart Accident Detection and Emergency Alert Backend is running."
}
```

---

### 2. Service & Twilio Status — `GET /api/ridesafe/status`
Reports operational health of backend components, persistent storage, and Twilio WhatsApp configuration. **Credentials are never exposed.**

**Example Request:**
```bash
curl -X GET "http://127.0.0.1:8000/api/ridesafe/status"
```

**Response (`HTTP 200 OK`):**
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
    "content_sid_configured": true,
    "recipient_masked": "whatsapp:+91****3210"
  },
  "security": {
    "api_key_required": true
  }
}
```

---

### 3. Safe Test Notification — `POST /api/ridesafe/test`
Receives a test event and dispatches a clearly marked test WhatsApp message. Guarantees that emergency alerts are never triggered.

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: your_secret_api_key_here`

**Example Request:**
```bash
curl -X POST "http://127.0.0.1:8000/api/ridesafe/test" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_api_key_here" \
  -d '{
    "device_id": "RIDESAFE_TEST_BENCH_01",
    "event_id": "test-manual-001",
    "event": "TEST",
    "gps_valid": false,
    "timestamp": "2026-10-21T10:30:00Z"
  }'
```

**Response (`HTTP 201 Created`):**
```json
{
  "status": "test_acknowledged",
  "event_id": "test-manual-001",
  "device_id": "RIDESAFE_TEST_BENCH_01",
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

### 4. Emergency Telemetry Ingestion — `POST /api/ridesafe/alert`
Receives confirmed `ACCIDENT` or `MANUAL_SOS` events from the ESP32. Enforces GPS rules, deduplicates by `(device_id, event_id)`, logs to SQLite, and attempts WhatsApp dispatch.

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: your_secret_api_key_here`

**GPS Validation Rules:**
- If `gps_valid: true`, both `latitude` (`-90.0` to `90.0`) and `longitude` (`-180.0` to `180.0`) are strictly required. Missing coordinates trigger `HTTP 422 Unprocessable Entity`.
- If `gps_valid: false`, coordinates may be `null`. The backend will explicitly label the notification as "GPS Unavailable" without fabricating coordinates.

**Example Request (Accident with Valid GPS):**
```bash
curl -X POST "http://127.0.0.1:8000/api/ridesafe/alert" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_api_key_here" \
  -d '{
    "device_id": "RIDESAFE_01",
    "event_id": "evt-20261021-001",
    "event": "ACCIDENT",
    "latitude": 13.0827,
    "longitude": 80.2707,
    "altitude": 42.5,
    "speed_kmph": 24.5,
    "tilt_degrees": 52.3,
    "gps_valid": true,
    "timestamp": "2026-10-21T10:30:00Z"
  }'
```

**Response (`HTTP 201 Created`):**
```json
{
  "status": "received",
  "event_id": "evt-20261021-001",
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

## 16. Twilio WhatsApp Sandbox Setup & Testing

### How Twilio WhatsApp Sandbox Operates
During development, Twilio provides a shared WhatsApp Sandbox number to transmit test messages without needing a fully verified business profile.

1. **Access Sandbox**:
   - Log into the [Twilio Console](https://console.twilio.com/).
   - Navigate to **Messaging** > **Try it out** > **Send a WhatsApp message**.
2. **Join the Sandbox (Mandatory for Recipient)**:
   - Twilio displays a sandbox sender number (e.g., `+1 415 523 8886`) and a unique join code (e.g., `join orange-fox`).
   - From the recipient's phone (matching `EMERGENCY_WHATSAPP_TO`), **send the join code via WhatsApp to the sandbox number**.
   - Twilio will reply confirming enrollment. Without this step, Twilio rejects dispatches with error code `63015`.
3. **Sandbox Inactivity Expiration**:
   - Twilio Sandbox sessions expire after **72 hours of inactivity**. You must re-send the join code if the session lapses.

---

### Twilio Content Templates (Resolving Error 21654: "ContentSid Required")

#### Why Twilio Error 21654 Occurs
Meta and Twilio enforce a strict template policy: any business-initiated outbound message sent outside of an active 24-hour customer care window must use a pre-approved **Content Template**. Sending a raw text message outside this window results in:
```text
Twilio API error 21654: "Unable to create record: ContentSid Required"
```

#### Configuring `TWILIO_CONTENT_SID`
The RideSafe backend natively supports Twilio's Content API:

1. **Option A: Pre-approved Sandbox Template (Recommended for Quick Testing)**
   - In the Twilio Console, under **Send a WhatsApp message**, view the **Code Samples** tab (Python or cURL).
   - Locate the template Content SID shown in the example (starts with `HX...`).
   - Copy this SID and set it in your `.env`:
     ```env
     TWILIO_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     ```
   - The backend automatically binds parameters:
     - Placeholder `{{1}}`: Date and Event Label (`RideSafe Test`).
     - Placeholder `{{2}}`: Time, Device ID, and Event ID.

2. **Option B: Custom Emergency Template**
   - Go to **Messaging** > **Content Template Builder**.
   - Create a template named `ridesafe_alert` with numbered placeholders (`{{1}}`, `{{2}}`, etc.).
   - Set `TWILIO_CONTENT_SID` in `.env` and specify `TWILIO_CONTENT_VARIABLES` to map custom fields.

> [!WARNING]
> **Delivery Semantics**: A status of `"dispatched"` or `"queued_by_twilio"` confirms that Twilio validated and accepted the API request. Final physical delivery to the recipient's handset depends on active sandbox enrollment, cellular signal, and handset availability.

---

## 17. Security & Safety Considerations

1. **Centralized Secret Management**:
   - API keys and Twilio credentials must reside exclusively on the server.
   - **Never hardcode Twilio Auth Tokens or API keys in the ESP32 firmware.** The ESP32 only holds the shared `RIDESAFE_API_KEY` to authenticate against the backend.
2. **Transport Layer Security (TLS/HTTPS)**:
   - For any network outside a closed local bench test, deploy the backend behind an HTTPS reverse proxy (such as Nginx, Caddy, or Cloudflare) with a valid SSL certificate.
   - Never transmit vehicle telemetry or API keys over unencrypted public HTTP.
3. **Emergency Suppression for Testing**:
   - The `/api/ridesafe/test` endpoint is strictly separated from `/api/ridesafe/alert`. Test messages are explicitly watermarked `[TEST]` and never trigger emergency classification.
4. **Data Privacy**:
   - Emergency contact numbers are masked in logs and public status responses (e.g., `whatsapp:+91****3210`).
   - Database files (`data/*.db`) and `.env` must never be published to public repositories.
5. **Safety Disclaimer**:
   - **RideSafe is an academic engineering prototype and proof-of-concept.**
   - It is not certified for commercial automotive deployment or life-critical emergency dispatch. It should never be used as the sole safety mechanism on a motor vehicle.

---

## 18. Testing Instructions & Verified Results

The backend contains a comprehensive automated test suite covering API contracts, Pydantic validation, SQLite persistence, concurrent duplicate prevention, and Twilio message dispatch.

### Running the Tests

Ensure your virtual environment is active, then execute:

```bash
pytest -v
```

### Verified Test Results

Executed on **Python 3.14.7** (macOS arm64):
```text
============================= test session starts ==============================
platform darwin -- Python 3.14.7, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/sabarishwaranv/RideSafe Software
collected 52 items

tests/test_api_endpoints.py::test_root_endpoint PASSED                   [  1%]
tests/test_api_endpoints.py::test_status_endpoint_reports_twilio_presence_without_leaks PASSED [  3%]
tests/test_api_endpoints.py::test_api_key_security_enforcement PASSED    [  5%]
tests/test_api_endpoints.py::test_alert_endpoint_triggers_twilio_dispatch_and_prevents_duplicate_whatsapp PASSED [  7%]
tests/test_api_endpoints.py::test_alert_endpoint_handles_twilio_failure_gracefully PASSED [  9%]
tests/test_api_endpoints.py::test_exact_prompt_example_payload PASSED    [ 11%]
tests/test_api_endpoints.py::test_test_endpoint_custom_payload PASSED    [ 13%]
tests/test_config.py::test_default_settings PASSED                       [ 15%]
tests/test_config.py::test_environment_variable_override PASSED          [ 17%]
tests/test_config.py::test_get_settings_cached PASSED                    [ 19%]
tests/test_events.py::test_1_valid_accident_event PASSED                 [ 21%]
tests/test_events.py::test_2_valid_manual_sos_event PASSED               [ 23%]
tests/test_events.py::test_3_missing_required_fields[device_id] PASSED   [ 25%]
tests/test_events.py::test_3_missing_required_fields[event_id] PASSED    [ 26%]
tests/test_events.py::test_3_missing_required_fields[event] PASSED       [ 28%]
tests/test_events.py::test_3_missing_required_fields[gps_valid] PASSED   [ 30%]
tests/test_events.py::test_3_missing_required_fields[timestamp] PASSED   [ 32%]
tests/test_events.py::test_4_invalid_latitude_longitude[91.0-80.0] PASSED [ 34%]
tests/test_events.py::test_4_invalid_latitude_longitude[-91.0-80.0] PASSED [ 36%]
tests/test_events.py::test_4_invalid_latitude_longitude[13.0-181.0] PASSED [ 38%]
tests/test_events.py::test_4_invalid_latitude_longitude[13.0--181.0] PASSED [ 40%]
tests/test_events.py::test_5_gps_unavailable_with_null_coordinates PASSED [ 42%]
tests/test_events.py::test_6_gps_marked_valid_but_coordinates_missing PASSED [ 44%]
tests/test_events.py::test_7_duplicate_event_id_from_same_device PASSED  [ 46%]
tests/test_events.py::test_8_same_event_id_from_different_devices PASSED [ 48%]
tests/test_events.py::test_9_test_endpoint_does_not_initiate_real_emergency_alert PASSED [ 50%]
tests/test_events.py::test_10_existing_health_and_status_endpoints_work PASSED [ 51%]
tests/test_events.py::test_timestamp_naive_accepted PASSED               [ 53%]
tests/test_events.py::test_invalid_timestamp_fails_validation PASSED     [ 55%]
tests/test_events.py::test_test_event_rejected_on_live_alert_endpoint PASSED [ 57%]
tests/test_main.py::test_health_check_endpoint PASSED                    [ 59%]
tests/test_main.py::test_ridesafe_status_endpoint PASSED                 [ 61%]
tests/test_main.py::test_non_existent_endpoint PASSED                    [ 63%]
tests/test_storage_sqlite.py::test_persistence_after_connection_reopened PASSED [ 65%]
tests/test_storage_sqlite.py::test_duplicate_detection_after_simulated_restart PASSED [ 67%]
tests/test_storage_sqlite.py::test_same_event_id_on_different_devices PASSED [ 69%]
tests/test_storage_sqlite.py::test_concurrent_duplicate_submissions PASSED [ 71%]
tests/test_storage_sqlite.py::test_gps_unavailable_events PASSED         [ 73%]
tests/test_storage_sqlite.py::test_test_events_remain_non_emergency PASSED [ 75%]
tests/test_storage_sqlite.py::test_directory_auto_creation_and_initialization PASSED [ 76%]
tests/test_storage_sqlite.py::test_database_error_handling PASSED        [ 78%]
tests/test_twilio_service.py::test_twilio_message_formatting_with_valid_gps PASSED [ 80%]
tests/test_twilio_service.py::test_twilio_message_formatting_without_gps PASSED [ 82%]
tests/test_twilio_service.py::test_twilio_test_message_formatting PASSED [ 84%]
tests/test_twilio_service.py::test_send_alert_when_twilio_unconfigured PASSED [ 86%]
tests/test_twilio_service.py::test_send_alert_success_body_fallback PASSED [ 88%]
tests/test_twilio_service.py::test_send_alert_success_with_content_sid PASSED [ 90%]
tests/test_twilio_service.py::test_send_test_message_with_content_sid PASSED [ 92%]
tests/test_twilio_service.py::test_appointment_reminders_template_variable_mapping PASSED [ 94%]
tests/test_twilio_service.py::test_regression_error_21654_contentsid_required PASSED [ 96%]
tests/test_twilio_service.py::test_custom_content_variables_interpolation PASSED [ 98%]
tests/test_twilio_service.py::test_masked_recipient_phone_number PASSED  [100%]

======================== 52 passed, 1 warning in 0.44s =========================
```

---

## 19. Current Implementation Status & Next Steps

### Completed & Verified Milestones
- [x] **FastAPI Core & Endpoints**: Fully implemented `/`, `/health`, `/api/ridesafe/status`, `/api/ridesafe/test`, and `/api/ridesafe/alert`.
- [x] **Pydantic Validation**: Coordinate range enforcement, naive/aware timestamp normalization, and GPS rules.
- [x] **Persistent Storage**: SQLite with WAL mode, schema auto-initialization, and thread-safe operations.
- [x] **Deduplication**: Composite constraint `UNIQUE(device_id, event_id)` protecting against duplicate alerts.
- [x] **Twilio WhatsApp Integration**: Complete implementation of freeform body and Twilio Content Template (`ContentSid`) support with fallback handling.
- [x] **Automated Regression Suite**: 52 passing tests covering edge cases, simulated failures, and security controls.

### Pending Project Milestones
- [ ] **ESP32 Firmware Implementation**: Complete embedded C++ / Arduino firmware incorporating FreeRTOS tasks for concurrent sensor polling and network requests.
- [ ] **Hardware Wiring & Bench Assembly**: Physical integration of MPU6050, NEO-6M, buzzer, LED, and SOS button on test bench.
- [ ] **Sensor Threshold Calibration**: Field tuning of MPU6050 accelerometer G-force and tilt thresholds under realistic motorcycle vibration profiles to minimize false positives.
- [ ] **ESP32-to-Backend End-to-End Integration**: Real-world bench testing of ESP32 dispatching HTTPS requests to the live backend.
- [ ] **On-Vehicle Road Testing**: Secure mounting and controlled dynamic testing on a physical two-wheeler.
- [ ] **Production WhatsApp Business Profile**: Migration from Twilio Sandbox to an official Meta WhatsApp Business Account (WABA) for direct public emergency messaging.

---

## 20. Limitations

1. **Network Connectivity Dependency**: The ESP32 requires an active Wi-Fi or cellular hotspot connection to reach the backend. If connectivity is lost in a remote area, cloud dispatch is delayed until connection recovery (local buzzer and LED serve as immediate local fallbacks).
2. **GPS Acquisition Time**: In dense urban canyons, covered parking garages, or tunnels, the NEO-6M GPS receiver may experience delayed satellite lock (cold start: ~30–60s). The backend gracefully ingests events with `gps_valid: false`, but coordinates will not be present.
3. **Twilio Sandbox Opt-In**: The development sandbox requires manual recipient opt-in via WhatsApp and lapses every 72 hours.
4. **Single-Node SQLite Storage**: The local SQLite database is suited for single-server deployments. Multi-instance, load-balanced architectures would require a centralized database (e.g., PostgreSQL).
5. **Vibration Sensitivity**: Motorcycles experience engine and road vibrations. Rigorous software low-pass filtering and rolling-window average algorithms must be implemented on the ESP32 to prevent pothole-induced false alarms.

---

## 21. License & Contribution Guidance

### License
This project is currently developed for academic engineering research and evaluation. An open-source license (such as the MIT License) will be formalized upon public release.

### Academic Review & Contribution
- Feedback, code contributions, and issue reports from academic reviewers, engineering peers, and open-source contributors are welcome.
- To report bugs or suggest enhancements, please open an issue or submit a pull request on the official repository:
  **[https://github.com/sabarishwaran-v/RideSafe](https://github.com/sabarishwaran-v/RideSafe)**
- When using this project as a reference in academic works, please provide appropriate attribution to the authors.
