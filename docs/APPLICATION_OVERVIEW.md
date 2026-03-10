# NRP_ROS — Application Overview

> Jetson Orin Nano-based autonomous rover control system with real-time telemetry, mission execution, RTK GPS, obstacle avoidance, and cloud TTS — all coordinated through a FastAPI + Socket.IO backend bridging a web frontend to ROS2/MAVROS.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [FastAPI Server](#2-fastapi-server-fully-functional)
3. [MAVROS Complete Implementation](#3-mavros-complete-implementation)
4. [Mission Controller](#4-integrated-mission-controller)
5. [Manual Control (Virtual Joystick)](#5-manual-control-virtual-joystick)
6. [RTK GPS & LoRa Corrections](#6-rtk-gps--lora-corrections)
7. [GPS Failsafe Monitor](#7-gps-failsafe-monitor)
8. [Obstacle Detection (Ultrasonic)](#8-obstacle-detection-ultrasonic)
9. [LED Feedback System (WS2812)](#9-led-feedback-system-ws2812)
10. [Text-to-Speech (TTS)](#10-text-to-speech-tts)
11. [Telemetry Aggregation](#11-telemetry-aggregation)
12. [Network Monitoring](#12-network-monitoring)
13. [Socket.IO API Documentation](#13-socketio-api-documentation)
14. [Hardware Summary](#14-hardware-summary)
15. [Startup & Service Management](#15-startup--service-management)
16. [REST API Endpoints](#16-rest-api-endpoints)
17. [Socket.IO Events](#17-socketio-events)

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      WEB FRONTEND                           │
│             (React/TypeScript, Socket.IO client)            │
└────────────────────────┬────────────────────────────────────┘
                         │ WebSocket + REST
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI + Socket.IO SERVER                  │
│                                                             │
│  Mission Controller ─ Manual Control ─ RTK/LoRa Handler     │
│  GPS Failsafe ─ Obstacle Monitor ─ LED Controller ─ TTS     │
│  Network Monitor ─ Activity Logger ─ Socket Docs            │
└────────────────────────┬────────────────────────────────────┘
                         │ rosbridge WebSocket (:9090)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   ROS2 Humble Middleware                     │
│  rosbridge_server ─ MAVROS (APM) ─ Telemetry Node          │
│  GPS Altitude Corrector                                     │
└────────────────────────┬────────────────────────────────────┘
                         │ Serial / USB / SPI
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    HARDWARE LAYER                            │
│  Pixhawk FCU ─ Servos ─ LoRa USB ─ Ultrasonic Sensor       │
│  WS2812 LEDs ─ Battery ─ IMU ─ GPS                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. FastAPI Server (Fully Functional)

**File:** `Backend/server.py`

| Feature | Details |
|---------|---------|
| Framework | FastAPI (migrated from Flask) with ASGI |
| Real-time | python-socketio AsyncServer |
| REST endpoints | 57 routes, fully async/await |
| CORS | Enabled for all origins |
| Port | 5001 (uvicorn) |
| Static files | Jinja2 templates for monitoring dashboards |

- Full async request handling across all 57 REST routes
- Socket.IO integration (24 named events + catch-all)
- Activity logging with circular buffer (last 1000 entries)
- Automatic ROS2 bridge initialization (TelemetryBridge + CommandBridge)
- Graceful shutdown with cleanup handlers
- Health check and node status endpoints
- CORS middleware for cross-origin frontend access

---

## 3. MAVROS Complete Implementation

**File:** `Backend/mavros_bridge.py`

### Subscribed ROS Topics

| Topic | Purpose |
|-------|---------|
| `/mavros/state` | Armed status, flight mode, connection state |
| `/mavros/global_position/global` | GPS lat/lon/altitude |
| `/mavros/global_position/raw/gps_vel` | GPS velocity |
| `/mavros/battery` | Voltage, current, percentage |
| `/mavros/imu/temperature_imu` | IMU temperature |
| `/mavros/mission/reached` | Waypoint reached notifications |
| `/mavros/global_position/raw/satellites` | Satellite count |
| `/nrp/telemetry` | Aggregated telemetry (custom topic) |

### MAVROS Services Used

| Service | Purpose |
|---------|---------|
| `/mavros/cmd/arming` | Arm/disarm the vehicle |
| `/mavros/set_mode` | Change flight mode (MANUAL, AUTO, GUIDED, HOLD, RTL) |
| `/mavros/mission/push` | Upload waypoints to Pixhawk |
| `/mavros/mission/pull` | Download waypoints from Pixhawk |
| `/mavros/mission/clear` | Clear all waypoints |
| `/mavros/cmd/command` | Send MAVLink commands (servo control, RC override) |

### Key Capabilities

- Telemetry streaming at 10 Hz (state, GPS, battery, IMU)
- Waypoint management (upload, download, clear, set current)
- Mode control (MANUAL, AUTO, GUIDED, HOLD, RTL)
- Arm/disarm the vehicle
- Servo control — direct PWM on channels 9–14
- RC override — channel override for manual control
- Mission reached detection per waypoint
- Pixhawk auto-reconnect with disconnect grace period
- GPS altitude correction node (+92.2m offset fix)

### Connection Details

- rosbridge WebSocket: `127.0.0.1:9090`
- Pixhawk FCU: `/dev/ttyUSB0` at 115200 baud
- MAVROS mode: APM (ArduPilot)

---

## 4. Integrated Mission Controller

**File:** `Backend/integrated_mission_controller.py`

### Mission States

```
IDLE → LOADING → READY → RUNNING → COMPLETED
                           ↕
                         PAUSED
```

### Features

| Feature | Details |
|---------|---------|
| Waypoint execution | Sequential, waypoint-by-waypoint |
| Waypoint detection | Pixhawk `mission_reached` topic (primary) + distance fallback (0.25m) |
| Servo/sprayer | Channel 9, PWM on=2300 / off=1750, configurable timing |
| GPS failsafe | Strict / relax / disable modes |
| Obstacle detection | Integrated ultrasonic zone alerts |
| Pause/resume | Full mission pause with position hold |
| Status callbacks | Real-time updates via Socket.IO |
| Configuration | JSON config file + runtime API |

### Commands

`load_mission`, `start`, `stop`, `pause`, `resume`, `restart`, `next`, `skip`, `set_mode`

---

## 5. Manual Control (Virtual Joystick)

**File:** `Backend/manual_control_handler.py`

| Feature | Details |
|---------|---------|
| Method | RC_CHANNELS_OVERRIDE via MAVROS |
| Drive type | Tank-style differential drive |
| Channels | Left motor (73), Right motor (74) |
| PWM range | 1000–2000 (center: 1500) |
| Throttle input | Normalized −1.0 to +1.0 |
| Rate limiting | 20 Hz |
| Safety | 5-second watchdog auto-stop |

---

## 6. RTK GPS & LoRa Corrections

**Files:** `Backend/lora_rtk_handler.py`, `Backend/lora_receiver_usb.py`

| Feature | Details |
|---------|---------|
| LoRa receiver | CH340 USB (VID: 0x1a86, PID: 0x7523) |
| Protocol | RTCM correction data injection |
| Interface | PyUSB bulk IN/OUT endpoints |
| AT commands | Configure address, frequency, network ID |
| NTRIP client | Alternative RTK source via internet caster |
| RTK injection | Corrections injected into MAVROS GPS stream |
| Status tracking | Messages received, bytes, error count |

### RTK Fix Types

| Value | Meaning |
|-------|---------|
| 0 | No GPS |
| 1 | GPS Fix |
| 2 | DGPS |
| 3 | RTK Float |
| 4 | RTK Fixed |

---

## 7. GPS Failsafe Monitor

**File:** `Backend/gps_failsafe_monitor.py`

### States

```
IDLE → MONITORING → TRIGGERED → AWAITING_ACK → STABLE_WINDOW → READY_RESUME
                                                                      │
                                                                SUPPRESSED
```

### Modes

| Mode | Behavior |
|------|----------|
| `disable` | No failsafe checks |
| `strict` | Pause mission + HOLD mode, await user acknowledgement |
| `relax` | Suppress servo only, continue movement |

### Thresholds

- Fix type requirement: 6 (RTK Fixed)
- Accuracy threshold: 60 mm
- Stable recovery window: 5 seconds continuous

---

## 8. Obstacle Detection (Ultrasonic)

**Files:** `Backend/obstacle_monitor.py`, `Backend/ultrasonic_sensor.py`

| Feature | Details |
|---------|---------|
| Sensor | A2111BU (DYP A21 series) |
| Interface | Serial `/dev/ttyTHS1` at 115200 baud |
| Protocol | 4-byte frames `[0xFF, High, Low, Checksum]` |
| Range | 0–4000+ mm |
| Debounce | 3 consecutive readings required |

### Detection Zones

| Zone | Range | Action |
|------|-------|--------|
| Danger | 0.8m – 1.0m | Pause mission |
| Warning | 1.2m – 2.0m | Alert, reduce speed |
| Clear | > 2.0m | Normal operation |

---

## 9. LED Feedback System (WS2812)

**File:** `Backend/led_controller.py`

| Feature | Details |
|---------|---------|
| LED type | WS2812 addressable RGB |
| Interface | SPI (`/dev/spidev0.0`) at 6.4 MHz |
| Encoding | 8-bit per WS2812 bit (GRB color order) |
| Pin | Jetson Pin 19 (SPI0_MOSI) → LED DIN |
| Profiles | "crowtail" (8 LEDs), "strip" (30 LEDs) |

### State Colors

| State | Color |
|-------|-------|
| Idle / Loading / Ready | Blue (0, 0, 255) |
| Running | White (255, 255, 255) |
| Paused | Yellow (255, 255, 0) |
| Completed | Green (0, 255, 0) |
| Error | Red blink (255, 0, 0) |

---

## 10. Text-to-Speech (TTS)

**File:** `Backend/tts.py`

| Feature | Details |
|---------|---------|
| Primary engine | Edge-tts (Microsoft Neural Voices, cloud) |
| Fallback engine | Piper (local neural TTS) |
| Playback | GStreamer (`gst-play-1.0`) |
| Languages | English (en), Tamil (ta), Hindi (hi) |
| Voice selection | Male / female per language |
| Rate limiting | Min interval between repeated phrases (default: 3s) |
| Threading | Async worker for non-blocking speech |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `NRP_TTS_ENABLE` | Enable/disable TTS |
| `NRP_TTS_GENDER` | "male" or "female" |
| `JARVIS_LANG` | Language code (en / ta / hi) |
| `NRP_TTS_MIN_INTERVAL` | Min seconds between repeated phrases |

---

## 11. Telemetry Aggregation

**File:** `Backend/telemetry_node.py`

| Feature | Details |
|---------|---------|
| Publish topic | `/nrp/telemetry` |
| Publish rate | 10 Hz |
| Data included | State, GPS, velocity, battery, IMU temp, satellites, RTK status |
| Covariance | HRMS/VRMS calculated from position covariance |

**GPS Altitude Corrector** (`Backend/gps_altitude_corrector.py`) — fixes MAVROS altitude bug (+92.2m offset).

- Subscribes: `/mavros/global_position/global`
- Publishes: `/mavros/global_position/global_corrected`

---

## 12. Network Monitoring

**File:** `utils/network_monitor.py`

| Feature | Details |
|---------|---------|
| WiFi RSSI | Signal strength scale 0–4 |
| Interface | Auto-detection via `iwconfig` |
| Caching | 3-second refresh interval |
| Output | Signal strength, RSSI dBm, interface name, connection status |

---

## 13. Socket.IO API Documentation

**File:** `Backend/socket_docs_router.py`

| Route | Purpose |
|-------|---------|
| `/asyncapi` | AsyncAPI interactive UI |
| `/api/docs/asyncapi.yaml` | OpenAPI spec file |
| `/socket-docs` | Interactive Socket.IO event tester |

---

## 14. Hardware Summary

| Component | Interface | Details |
|-----------|-----------|---------|
| Jetson Orin Nano Super | — | Main compute platform |
| Pixhawk FCU | `/dev/ttyUSB0` @ 115200 | ArduPilot firmware |
| Servo outputs | Channels 9–14 | Sprayer PWM control |
| GPS | via MAVROS | RTK-capable |
| LoRa receiver | USB (CH340) | RTCM correction relay |
| Ultrasonic sensor | `/dev/ttyTHS1` @ 115200 | A2111BU obstacle detection |
| WS2812 LEDs | `/dev/spidev0.0` @ 6.4 MHz | Mission state feedback |
| Battery | via MAVROS | Voltage / current / percentage |
| IMU | via MAVROS | Temperature monitoring |
| Audio | USB speaker (PulseAudio) | TTS output |

---

## 15. Startup & Service Management

**File:** `start_service.sh`

### Launch Order

1. ROS2 environment (`/opt/ros/humble/setup.bash`)
2. rosbridge_server (port 9090)
3. MAVROS APM (`/dev/ttyUSB0:115200`)
4. GPS Altitude Corrector (ROS2 node)
5. Telemetry Node (ROS2 node)
6. Backend server (FastAPI/uvicorn on port 5001)

### Features

- Port cleanup (9090, 5761, 5001) on startup
- Graceful shutdown with SIGTERM/SIGINT handling
- ROS node health monitoring
- Port readiness checking (30s timeout)
- PulseAudio USB speaker setup
- Environment: `LED_STRIP`, `JARVIS_LANG`, `NRP_TTS_GENDER`

---

## 16. REST API Endpoints

### Mission

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/mission/upload` | Upload waypoints |
| GET | `/api/mission/download` | Download current mission |
| POST | `/api/mission/clear` | Clear all waypoints |
| POST | `/api/mission/start` | Start mission execution |
| POST | `/api/mission/stop` | Stop mission |
| POST | `/api/mission/pause` | Pause mission |
| POST | `/api/mission/resume` | Resume mission |
| GET | `/api/mission/status` | Get mission status |
| GET/POST | `/api/mission/config` | Get/set mission configuration |
| POST | `/api/mission/load` | Load mission from file |
| GET/POST | `/api/mission/servo_config` | Servo parameters |
| GET | `/api/mission/mode` | Get current mode |

### RTK

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/rtk/inject` | Inject RTCM corrections |
| POST | `/api/rtk/stop` | Stop RTK injection |
| POST | `/api/rtk/ntrip_start` | Start NTRIP client |
| POST | `/api/rtk/ntrip_stop` | Stop NTRIP client |
| POST | `/api/rtk/lora_start` | Start LoRa RTK stream |
| POST | `/api/rtk/lora_stop` | Stop LoRa RTK stream |
| GET | `/api/rtk/status` | RTK status |
| POST | `/api/rtk/force_clear` | Force clear RTK state |

### Vehicle Control

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/arm` | Arm/disarm vehicle |
| POST | `/api/set_mode` | Set flight mode |
| POST | `/api/servo/control` | Direct servo PWM control |

### TTS

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/tts/status` | TTS engine status |
| POST | `/api/tts/control` | Enable/disable TTS |
| POST | `/api/tts/test` | Test TTS with phrase |
| GET | `/api/tts/languages` | Available languages |
| POST | `/api/tts/language` | Set language |

### System

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/activity` | Activity log (last 1000 entries) |
| GET | `/api/nodes` | ROS node status |
| GET/POST | `/api/config/sprayer` | Sprayer configuration |

---

## 17. Socket.IO Events

### Client → Server

| Event | Purpose |
|-------|---------|
| `send_command` | Send mission/vehicle command |
| `manual_control` | Joystick input (throttle, steering) |
| `emergency_stop` | Emergency stop |
| `stop_manual_control` | Release manual control |
| `get_mission_status` | Request mission status |
| `subscribe_mission_status` | Subscribe to mission updates |
| `request_mission_logs` | Request mission log data |
| `mission_upload` | Upload mission via WebSocket |
| `connect_caster` | Connect to NTRIP caster |
| `disconnect_caster` | Disconnect NTRIP |
| `start_lora_rtk_stream` | Start LoRa RTK |
| `stop_lora_rtk_stream` | Stop LoRa RTK |
| `get_lora_rtk_status` | Query LoRa status |
| `inject_mavros_telemetry` | Inject telemetry data |
| `set_gps_failsafe_mode` | Set failsafe mode |
| `failsafe_acknowledge` | Acknowledge failsafe trigger |
| `failsafe_resume_mission` | Resume after failsafe |
| `failsafe_restart_mission` | Restart after failsafe |
| `set_obstacle_detection` | Enable/disable obstacle detection |
| `request_rover_reconnect` | Request Pixhawk reconnect |

### Server → Client

| Event | Purpose |
|-------|---------|
| `telemetry` | Real-time telemetry data (10 Hz) |
| `mission_status` | Mission state updates |
| `mission_log` | Mission event logs |
| `rtk_status` | RTK correction status |
| `lora_rtk_status` | LoRa RTK connection status |
| `failsafe_status` | GPS failsafe state changes |
| `obstacle_status` | Obstacle detection alerts |
| `activity` | Activity log entries |
| `rover_connection_status` | Pixhawk connection state |

---

## Summary

| Category | Status | Key Metric |
|----------|--------|------------|
| FastAPI Server | Complete | 57 REST routes, 24 Socket.IO events |
| MAVROS Integration | Complete | 8 subscribed topics, 6 services |
| Mission Controller | Complete | 5 states, 9 commands, dual waypoint detection |
| Manual Control | Complete | Differential drive, 20 Hz, watchdog safety |
| RTK / LoRa | Complete | NTRIP + LoRa USB RTCM injection |
| GPS Failsafe | Complete | 3 modes, 7 states, auto-recovery |
| Obstacle Detection | Complete | 3 zones, debounced, ultrasonic |
| LED Feedback | Complete | 5 state colors, SPI WS2812 |
| TTS | Complete | 3 languages, 2 engines, async |
| Telemetry | Complete | 10 Hz aggregated JSON stream |
| Network Monitor | Complete | WiFi RSSI tracking |
| API Documentation | Complete | AsyncAPI + interactive tester |
