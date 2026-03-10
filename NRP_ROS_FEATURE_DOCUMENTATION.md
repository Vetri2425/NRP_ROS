# NRP_ROS - Autonomous Rover Control System

## Application Overview

**NRP_ROS (NRP - Navigation & Robotics Platform)** is a Jetson Orin Nano-based autonomous rover control system with real-time telemetry, mission execution, RTK GPS positioning, obstacle avoidance, and cloud Text-to-Speech feedback - all coordinated through a FastAPI + Socket.IO backend bridging a web frontend to ROS2/MAVROS.

---

## Total Files Count: 110+ Files

### Folder Structure with Files

```
NRP_ROS/
├── .env
├── .gitignore
├── FASTAPI_MIGRATION_PLAN.md
├── fix_ch340_jetson.sh
├── fix_pulseaudio_service.sh
├── fix_rover_rotation.sh
├── Force_ARM.MD
├── FRONTEND_INTEGRATION_GUIDE.md
├── health_check.sh
├── mav.parm
├── MISSION_CONTROLLER_API_DOCUMENTATION.md
├── PARAMETER_ANALYSIS.md
├── QUICK_START.md
├── README.md
├── setup_lora_rover.sh
├── setup-and-start-service.sh
├── start_service.sh
├── TELEMETRY_FIXES_SUMMARY.md
│
├── Backend/
│   ├── CLAUDE_BACKEND_REPORT.md
│   ├── gps_altitude_corrector.py         [Modified: Dec 20 2025]
│   ├── gps_failsafe_monitor.py           [Modified: Jan 31 2026]
│   ├── integrated_mission_controller.py   [Modified: Feb 24 2026]
│   ├── led_controller.py                 [Modified: Feb 20 2026]
│   ├── lora_receiver_usb.py              [Modified: Dec 20 2025]
│   ├── lora_rtk_handler.py                [Modified: Dec 20 2025]
│   ├── manual_control_handler.py          [Modified: Dec 20 2025]
│   ├── mavlink_core.py                    [Modified: Dec 20 2025]
│   ├── mavros_bridge.py                   [Modified: Feb 24 2026]
│   ├── obstacle_monitor.py                [Modified: Feb 20 2026]
│   ├── README.md
│   ├── requirements.txt
│   ├── server.py                          [Modified: Feb 25 2026]
│   ├── socket_docs_router.py              [Modified: Feb 23 2026]
│   ├── telemetry_node.py                  [Modified: Feb 24 2026]
│   ├── tts.py                            [Modified: Feb 20 2026]
│   ├── ultrasonic_sensor.py               [Modified: Feb 17 2026]
│   ├── ultrasonic_watch.py                [Modified: Feb 20 2026]
│   │
│   ├── config/
│   │   ├── mission_controller_config.json
│   │   └── mission_controller_config.json.backup
│   │
│   ├── docs/
│   │   └── asyncapi.yaml
│   │
│   ├── servo_manager/                     [Directory - Pending scripts]
│   │
│   └── templates/
│       ├── asyncapi.html
│       ├── index.html
│       ├── monitor.html
│       ├── node_details.html
│       └── socket_docs.html
│
├── docs/
│   ├── APPLICATION_OVERVIEW.md
│   ├── APPLICATION_OVERVIEW.pdf
│   ├── FASTAPI_MIGRATION_PROMPTS.md
│   ├── generate_overview_pdf.py
│   │
│   ├── architecture/
│   │   ├── MISSION_CONTROLLER_REFACTOR.md
│   │   ├── NVROS_Backend_Flow.md
│   │   ├── NVROS_Flow_Diagram.md
│   │   ├── NVROS_Full_Flow_File_Purpose.md
│   │   ├── REFACTOR_PIXHAWK_TOPIC_SUBSCRIPTION.md
│   │   ├── REFACTORING_COMPLETE_README.md
│   │   └── REFACTORING_SUMMARY.md
│   │
│   ├── endpoints/
│   │   ├── ENDPOINTS_QUICK_REFERENCE.md
│   │   ├── ENDPOINTS_VERIFICATION_REPORT.md
│   │   ├── RTK_API_ENDPOINTS_DOCUMENTATION.md
│   │   └── SERVO_CONFIG_API_GUIDE.md
│   │
│   ├── field-test/
│   │   ├── DETAILED_TEST_RESULTS.md
│   │   ├── FIELD_TEST_CHECKLIST.md
│   │   ├── FIELD_TEST_FIXES_APPLIED.md
│   │   ├── FIELD_TEST_READINESS_CHECK.md
│   │   └── PRE_FIELD_TEST_CHECKLIST.md
│   │
│   ├── fixes/
│   │   ├── AUTO_RECONNECT_CRASH_LOOP_FIX.md
│   │   ├── IMPLEMENTATION_COMPLETE_SUMMARY.md
│   │   ├── IMPLEMENTATION_COMPLETION_REPORT.md
│   │   ├── MISSION_LOGGING_COMPLETE.md
│   │   ├── PIXHAWK_AUTO_RECONNECT_FIX.md
│   │
│   ├── gps-failsafe/
│   │   ├── GPS_FAILSAFE_BACKEND_IMPLEMENTATION.md
│   │   ├── GPS_FAILSAFE_COMPLETION_REPORT.md
│   │   ├── GPS_FAILSAFE_DELIVERY_SUMMARY.md
│   │   ├── GPS_FAILSAFE_FRONTEND_GUIDE.md
│   │   ├── GPS_FAILSAFE_INDEX.md
│   │   ├── GPS_FAILSAFE_STRICT_FIX_APPLIED.md
│   │   └── GPS_FAILSAFE_STRICT_MODE_DEBUG.md
│   │
│   ├── rtk/
│   │   ├── CONTINUOUS_RTK_MONITORING_IMPLEMENTATION.md
│   │   ├── CONTINUOUS_RTK_MONITORING_QUICK_REFERENCE.md
│   │   ├── CONTINUOUS_RTK_MONITORING_VERIFICATION.md
│   │   └── RTK_FAILSAFE_ARCHITECTURE_COMPARISON.md
│   │
│   ├── servo/
│   │   ├── SERVO_CONFIG_CHANGES_SUMMARY.md
│   │   ├── SERVO_IMPLEMENTATION_SUMMARY.md
│   │   └── SERVO_QUICK_REFERENCE.md
│   │
│   └── tts/
│       ├── COMPLETE_TTS_FIX_GUIDE.md
│       ├── JARVIS_DEVELOPER_GUIDE.md
│       ├── JARVIS_REFACTOR_COMPLETION.md
│       ├── JARVIS_VOICE_SYSTEM_ARCHITECTURE.md
│       ├── JARVIS_VOICE_SYSTEM_ASSESSMENT.md
│       ├── JARVIS_VOICE_SYSTEM_REFACTOR_GUIDE.md
│       ├── JARVIS_VOICE_SYSTEM_SUMMARY.md
│       ├── PIPER_TTS_PULSEAUDIO_FIX.md
│       ├── TTS_FIX_SUMMARY.md
│       ├── TTS_PIPER_MODELS.md
│       └── TTS_SPEED_OPTIMIZATION_GUIDE.md
│
├── tests/
│   ├── find_ultrasonic.py
│   ├── lora_quick_test.py
│   ├── simulate_led_test.py
│   ├── simulate_mission.py
│   ├── test_all_endpoints.py
│   ├── test_emit_data.py
│   ├── test_endpoints_complete.py
│   ├── test_force_arm_flow.py
│   ├── test_gps_raw_integration.py
│   ├── test_gps.py
│   ├── test_led.py
│   ├── test_lora_events.py
│   ├── test_mission_controller_events.py
│   ├── test_mission_integration.py
│   ├── test_mission_tts.py
│   ├── test_mode_change.py
│   ├── test_servo_10_ros2.py
│   ├── test_servo_10.py
│   ├── test_servo_config_api.py
│   ├── test_tamil_piper.py
│   ├── test_tts_10waypoints.py
│   ├── test_tts_fix.py
│   ├── test_tts_integration.py
│   ├── test_tts_simple.py
│   ├── test_tts_voices.py
│
├── tools/
│   ├── find_topic_by_fields.py
│   ├── install_piper_models.sh
│   └── tts_smoke_test.py
│
└── utils/
    └── network_monitor.py
```

---

## System Architecture

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
│  GPS Failsafe ─ Obstacle Monitor ─ LED Controller ─ TTS   │
│  Network Monitor ─ Activity Logger ─ Socket Docs           │
└────────────────────────┬────────────────────────────────────┘
                         │ rosbridge WebSocket (:9090)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   ROS2 Humble Middleware                    │
│  rosbridge_server ─ MAVROS (APM) ─ Telemetry Node          │
│  GPS Altitude Corrector                                    │
└────────────────────────┬────────────────────────────────────┘
                         │ Serial / USB / SPI
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    HARDWARE LAYER                           │
│  Pixhawk FCU ─ Servos ─ LoRa USB ─ Ultrasonic Sensor      │
│  WS2812 LEDs ─ Battery ─ IMU ─ GPS                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Feature List & Technical Details

### 1. FastAPI Server

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **Framework** | FastAPI with ASSI | Complete | Feb 25 2026 | 57 REST routes |
| **Real-time** | python-socketio AsyncServer | Complete | Feb 25 2026 | 24 Socket.IO events |
| **REST endpoints** | 57 routes, fully async/await | Complete | Feb 25 2026 | - |
| **CORS** | Enabled for all origins | Complete | - | - |
| **Port** | 5001 (uvicorn) | Complete | - | - |
| **Static files** | Jinja2 templates for monitoring dashboards | Complete | - | - |

**Achieves**: Full async request handling across all 57 REST routes, Socket.IO integration (24 named events + catch-all), activity logging with circular buffer (last 1000 entries), automatic ROS2 bridge initialization, graceful shutdown with cleanup handlers.

---

### 2. MAVROS Integration

| Topic/Service | Purpose | Status | Last Modified |
|--------------|---------|--------|---------------|
| `/mavros/state` | Armed status, flight mode, connection state | Complete | Feb 24 2026 |
| `/mavros/global_position/global` | GPS lat/lon/altitude | Complete | Feb 24 2026 |
| `/mavros/global_position/global_corrected` | Corrected GPS altitude | Complete | Feb 24 2026 |
| `/mavros/global_position/raw/gps_vel` | GPS velocity | Complete | Feb 24 2026 |
| `/mavros/gpsstatus/gps1/raw` | Satellite count, fix type | Complete | Feb 24 2026 |
| `/mavros/battery` | Voltage, current, percentage | Complete | Feb 24 2026 |
| `/mavros/imu/temperature_imu` | IMU temperature | Complete | Feb 24 2026 |
| `/mavros/mission/reached` | Waypoint reached notifications | Complete | Feb 24 2026 |
| `/mavros/gps_rtk/rtk_baseline` | RTK baseline data | Complete | Feb 24 2026 |
| `/mavros/rc/in` | RC input channels | Complete | Feb 24 2026 |
| `/mavros/rc/out` | Servo PWM output | Complete | Feb 24 2026 |

**MAVROS Services Used:**

| Service | Purpose | Status |
|---------|---------|--------|
| `/mavros/cmd/arming` | Arm/disarm the vehicle | Complete |
| `/mavros/set_mode` | Change flight mode (MANUAL, AUTO, GUIDED, HOLD, RTL) | Complete |
| `/mavros/mission/push` | Upload waypoints to Pixhawk | Complete |
| `/mavros/mission/pull` | Download waypoints from Pixhawk | Complete |
| `/mavros/mission/clear` | Clear all waypoints | Complete |
| `/mavros/cmd/command` | Send MAVLink commands (servo control, RC override) | Complete |
| `/mavros/mission/set_current` | Jump to specific waypoint | Complete |

**Achieves**: Telemetry streaming at 10 Hz, waypoint management, mode control, arm/disarm, servo control on channels 9-14, RC override for manual control, mission reached detection per waypoint, Pixhawk auto-reconnect with disconnect grace period.

---

### 3. Mission Controller

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **Mission States** | IDLE → LOADING → READY → RUNNING → COMPLETED ↔ PAUSED | Complete | Feb 24 2026 | 5 states |
| **Waypoint execution** | Sequential, waypoint-by-waypoint | Complete | Feb 24 2026 | - |
| **Waypoint detection** | Pixhawk `mission_reached` topic (primary) + distance fallback (0.25m) | Complete | Feb 24 2026 | Dual method |
| **Servo/sprayer** | Channel 9, PWM on=2300 / off=1750, configurable timing | Complete | Feb 24 2026 | - |
| **GPS failsafe** | Strict / relax / disable modes | Complete | Jan 31 2026 | 3 modes |
| **Obstacle detection** | Integrated ultrasonic zone alerts | Complete | Feb 20 2026 | - |
| **Pause/resume** | Full mission pause with position hold | Complete | - | - |
| **Continuous RTK Monitoring** | 0.5s interval RTK fix type check in STRICT mode | Complete | Feb 24 2026 | 0.5s interval |
| **Status callbacks** | Real-time updates via Socket.IO | Complete | - | - |
| **Configuration** | JSON config file + runtime API | Complete | - | - |

**Commands**: load_mission, start, stop, pause, resume, restart, next, skip, set_mode

**Achieves**: Autonomous waypoint navigation with real-time state management, integrated failsafe protection, obstacle avoidance integration, continuous RTK monitoring during missions, and comprehensive mission logging.

---

### 4. Manual Control (Virtual Joystick)

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **Method** | RC_CHANNELS_OVERRIDE via MAVROS | Complete | Dec 20 2025 | - |
| **Drive type** | Tank-style differential drive | Complete | - | - |
| **Channels** | Left motor (73), Right motor (74) | Complete | - | - |
| **PWM range** | 1000–2000 (center: 1500) | Complete | - | - |
| **Throttle input** | Normalized −1.0 to +1.0 | Complete | - | - |
| **Rate limiting** | 20 Hz | Complete | - | - |
| **Safety** | 5-second watchdog auto-stop | Complete | - | - |

**Achieves**: Real-time manual rover control with differential drive steering, rate-limited commands for stability, and automatic safety shutdown on communication loss.

---

### 5. RTK GPS & LoRa Corrections

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **LoRa receiver** | CH340 USB (VID: 0x1a86, PID: 0x7523) | Complete | Dec 20 2025 | - |
| **Protocol** | RTCM correction data injection | Complete | - | - |
| **Interface** | PyUSB bulk IN/OUT endpoints | Complete | - | - |
| **AT commands** | Configure address, frequency, network ID | Complete | - | - |
| **NTRIP client** | Alternative RTK source via internet caster | Complete | - | - |
| **RTK injection** | Corrections injected into MAVROS GPS stream | Complete | - | - |
| **Status tracking** | Messages received, bytes, error count | Complete | - | - |

**RTK Fix Types:**

| Value | Meaning |
|-------|---------|
| 0 | No GPS |
| 1 | GPS Fix |
| 2 | DGPS |
| 3 | RTK Float |
| 4 | RTK Fixed |

**Achieves**: Centimeter-level positioning accuracy via RTCM correction data, dual-source RTK (LoRa wireless or NTRIP internet), real-time status monitoring.

---

### 6. GPS Failsafe Monitor

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **States** | IDLE → MONITORING → TRIGGERED → AWAITING_ACK → STABLE_WINDOW → READY_RESUME ↔ SUPPRESSED | Complete | Jan 31 2026 | 6 states |
| **Modes** | disable, strict, relax | Complete | Jan 31 2026 | 3 modes |
| **Fix type requirement** | 6 (RTK Fixed) | Complete | - | - |
| **Accuracy threshold** | 60 mm | Complete | - | - |
| **Stable recovery window** | 5 seconds continuous | Complete | - | - |

**Achieves**: Protection against GPS degradation during autonomous missions, configurable response levels, user acknowledgment workflow for strict mode, automatic recovery detection.

---

### 7. Obstacle Detection (Ultrasonic)

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **Sensor** | A2111BU (DYP A21 series) | Complete | Feb 20 2026 | - |
| **Interface** | Serial `/dev/ttyTHS1` at 115200 baud | Complete | Feb 20 2026 | - |
| **Protocol** | 4-byte frames `[0xFF, High, Low, Checksum]` | Complete | - | - |
| **Range** | 0–4000+ mm | Complete | - | - |
| **Debounce** | 3 consecutive readings required | Complete | - | - |

**Detection Zones:**

| Zone | Range | Action |
|------|-------|--------|
| Danger | 0.8m – 1.0m | Pause mission |
| Warning | 1.2m – 2.0m | Alert, reduce speed |
| Clear | > 2.0m | Normal operation |

**Achieves**: Real-time obstacle proximity monitoring with zone-based alerts, mission pause on danger detection, debounced readings to prevent false triggers.

---

### 8. LED Feedback System (WS2812)

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **LED type** | WS2812 addressable RGB | Complete | Feb 20 2026 | - |
| **Interface** | SPI (`/dev/spidev0.0`) at 6.4 MHz | Complete | Feb 20 2026 | - |
| **Encoding** | 8-bit per WS2812 bit (GRB color order) | Complete | - | - |
| **Pin** | Jetson Pin 19 (SPI0_MOSI) → LED DIN | Complete | - | - |
| **Profiles** | "crowtail" (8 LEDs), "strip" (30 LEDs) | Complete | - | - |

**State Colors:**

| State | Color |
|-------|-------|
| Idle / Loading / Ready | Blue (0, 0, 255) |
| Running | White (255, 255, 255) |
| Paused | Yellow (255, 255, 0) |
| Completed | Green (0, 255, 0) |
| Error | Red blink (255, 0, 0) |

**Achieves**: Visual mission state feedback for field operators, color-coded status indication, blink animation for error states.

---

### 9. Text-to-Speech (TTS)

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **Primary engine** | Edge-tts (Microsoft Neural Voices, cloud) | Complete | Feb 20 2026 | - |
| **Fallback engine** | Piper (local neural TTS) | Complete | Feb 20 2026 | - |
| **Playback** | GStreamer (`gst-play-1.0`) | Complete | - | - |
| **Languages** | English (en), Tamil (ta), Hindi (hi) | Complete | - | 3 languages |
| **Voice selection** | Male / female per language | Complete | - | - |
| **Rate limiting** | Min interval between repeated phrases (default: 3s) | Complete | - | - |
| **Threading** | Async worker for non-blocking speech | Complete | - | - |

**TTS Voice Events:**

| Event | English | Tamil | Hindi | Status |
|-------|---------|-------|-------|--------|
| waypoint_reached | "Target {n} reached" | "இலக்கு{n} அடையப்பட்டது" | "लक्ष्य {n} पहुँच गए" | Complete |
| waypoint_marked | "Target {n} done" | "இலக்கு{n} முடிந்தது" | "लक्ष्य {n} पूरा हो गया" | Complete |
| waypoint_failed | "Target {n} failed, {reason}" | - | - | Complete |
| mission_completed | "Mission completed. {n} targets in {s} seconds" | - | - | Complete |
| mission_error | "Error, {message}" | - | - | Complete |
| obstacle_warning | "Object detected, {d} centimeters away" | - | - | Complete |
| obstacle_danger | "Mission paused, object too close" | - | - | Complete |
| vehicle_armed | "Vehicle armed" / "Vehicle disarmed" | - | - | Complete |
| rtk_fix_acquired | "RTK fix acquired. Centimeter accuracy active." | - | - | Complete |
| rtk_fix_lost | "RTK fix lost. Float mode active." | - | - | Complete |
| rtk_signal_lost | "RTK signal lost. GPS only mode." | - | - | Complete |
| battery_critical | "Warning! Battery critical, {n} percent remaining." | - | - | Complete |
| battery_low | "Battery low, {n} percent remaining." | - | - | Complete |
| obstacle_enabled | "Obstacle detection enabled/disabled" | - | - | Complete |
| mission_paused | "Mission paused" | - | - | Complete |
| mission_resumed | "Mission resumed" | - | - | Complete |
| mission_stopped | "Mission stopped" | - | - | Complete |
| system_initialized | "Way to Mark initialised" | - | - | Complete |

**Achieves**: Voice announcements for mission events, waypoint completion, failsafe triggers, multi-language support, non-blocking speech synthesis.

---

### 10. Telemetry Aggregation

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **Publish topic** | `/nrp/telemetry` | Complete | Feb 24 2026 | - |
| **Publish rate** | 10 Hz | Complete | - | - |
| **Data included** | State, GPS, velocity, battery, IMU temp, satellites, RTK status | Complete | - | - |
| **Covariance** | HRMS/VRMS calculated from position covariance | Complete | - | - |

**Achieves**: Unified telemetry stream combining all sensor data, real-time position accuracy metrics, battery and temperature monitoring.

---

### 11. GPS Altitude Corrector

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **Input topic** | `/mavros/global_position/global` | Complete | Dec 20 2025 | - |
| **Output topic** | `/mavros/global_position/global_corrected` | Complete | Dec 20 2025 | - |
| **Altitude correction** | +92.2m offset fix | Complete | - | - |

**Achieves**: Fixes MAVROS altitude bug where GPS altitude was incorrectly reported (off by ~92 meters), accurate altitude for waypoint navigation.

---

### 12. Network Monitoring

| Feature | Technical Details | Status | Last Modified | Data |
|---------|------------------|--------|---------------|------|
| **WiFi RSSI** | Signal strength scale 0–4 | Complete | - | - |
| **Interface** | Auto-detection via `iwconfig` | Complete | - | - |
| **Caching** | 3-second refresh interval | Complete | - | - |
| **Output** | Signal strength, RSSI dBm, interface name, connection status | Complete | - | - |

**Achieves**: Real-time network connectivity status for remote operations, signal quality assessment.

---

### 13. Socket.IO API

**Client → Server Events:**

| Event | Purpose | Status |
|-------|---------|--------|
| `send_command` | Send mission/vehicle command | Complete |
| `manual_control` | Joystick input (throttle, steering) | Complete |
| `emergency_stop` | Emergency stop | Complete |
| `stop_manual_control` | Release manual control | Complete |
| `get_mission_status` | Request mission status | Complete |
| `subscribe_mission_status` | Subscribe to mission updates | Complete |
| `mission_upload` | Upload mission via WebSocket | Complete |
| `connect_caster` | Connect to NTRIP caster | Complete |
| `start_lora_rtk_stream` | Start LoRa RTK | Complete |
| `stop_lora_rtk_stream` | Stop LoRa RTK | Complete |
| `set_gps_failsafe_mode` | Set failsafe mode | Complete |
| `failsafe_acknowledge` | Acknowledge failsafe trigger | Complete |
| `set_obstacle_detection` | Enable/disable obstacle detection | Complete |

**Server → Client Events:**

| Event | Purpose | Status |
|-------|---------|--------|
| `telemetry` | Real-time telemetry data (10 Hz) | Complete |
| `mission_status` | Mission state updates | Complete |
| `mission_log` | Mission event logs | Complete |
| `rtk_status` | RTK correction status | Complete |
| `lora_rtk_status` | LoRa RTK connection status | Complete |
| `failsafe_status` | GPS failsafe state changes | Complete |
| `obstacle_status` | Obstacle detection alerts | Complete |
| `activity` | Activity log entries | Complete |
| `rover_connection_status` | Pixhawk connection state | Complete |

**Achieves**: Bi-directional real-time communication, event-driven updates, WebSocket-based low-latency data streaming.

---

### 14. REST API Endpoints

**Mission Endpoints:**
| Endpoint | Purpose | Status |
|----------|---------|--------|
| `POST /api/mission/upload` | Upload waypoints | Complete |
| `GET /api/mission/download` | Download current mission | Complete |
| `POST /api/mission/clear` | Clear all waypoints | Complete |
| `POST /api/mission/start` | Start mission execution | Complete |
| `POST /api/mission/stop` | Stop mission | Complete |
| `POST /api/mission/pause` | Pause mission | Complete |
| `POST /api/mission/resume` | Resume mission | Complete |
| `GET /api/mission/status` | Get mission status | Complete |
| `GET/POST /api/mission/config` | Get/set mission configuration | Complete |
| `GET/POST /api/mission/servo_config` | Servo parameters | Complete |

**RTK Endpoints:**
| Endpoint | Purpose | Status |
|----------|---------|--------|
| `POST /api/rtk/inject` | Inject RTCM corrections | Complete |
| `POST /api/rtk/stop` | Stop RTK injection | Complete |
| `POST /api/rtk/ntrip_start` | Start NTRIP client | Complete |
| `POST /api/rtk/lora_start` | Start LoRa RTK stream | Complete |
| `GET /api/rtk/status` | RTK status | Complete |

**Vehicle Control:**
| Endpoint | Purpose | Status |
|----------|---------|--------|
| `POST /api/arm` | Arm/disarm vehicle | Complete |
| `POST /api/set_mode` | Set flight mode | Complete |
| `POST /api/servo/control` | Direct servo PWM control | Complete |

**TTS:**
| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /api/tts/status` | TTS engine status | Complete |
| `POST /api/tts/control` | Enable/disable TTS | Complete |
| `POST /api/tts/test` | Test TTS with phrase | Complete |
| `GET /api/tts/languages` | Available languages | Complete |

**System:**
| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /api/activity` | Activity log (last 1000 entries) | Complete |
| `GET /api/nodes` | ROS node status | Complete |

---

### 15. Hardware Summary

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

## Pending Features (Not Yet Implemented)

### 1. Continuous Line Mode (Servo Script)

| Feature | Technical Details | Status | Expected Data |
|---------|------------------|--------|---------------|
| **Script** | `continuous_line.py` | **Pending** | File reference exists in server.py |
| **Purpose** | Continuous spray while moving along line | Not implemented | Servo keeps spraying |
| **Location** | `Backend/servo_manager/` | Directory exists but empty | - |

**Technical Details**: Script would enable continuous servo activation based on mission progress, typically used for line-spray operations where the sprayer remains active between waypoints.

---

### 2. Interval Spray Mode (Servo Script)

| Feature | Technical Details | Status | Expected Data |
|---------|------------------|--------|---------------|
| **Script** | `interval_spray.py` | **Pending** | File reference exists in server.py |
| **Purpose** | Spray at regular intervals (time or distance based) | Not implemented | Configurable intervals |
| **Location** | `Backend/servo_manager/` | Directory exists but empty | - |

**Technical Details**: Script would activate servo at configurable time intervals (e.g., every 5 seconds) or distance intervals (e.g., every 10 meters), useful for systematic coverage spraying.

---

### 3. Waypoint Mark Mode (Servo Script)

| Feature | Technical Details | Status | Expected Data |
|---------|------------------|--------|---------------|
| **Script** | `wpmark.py` | **Pending** | File reference exists in server.py |
| **Purpose** | Mark waypoints with spray | Not implemented | Trigger on waypoint arrival |
| **Location** | `Backend/servo_manager/` | Directory exists but empty | - |

**Technical Details**: Script would activate servo precisely when reaching each waypoint, used for spot-marking or point-specific treatment applications.

---

### 4. Survey Mode

| Feature | Technical Details | Status | Expected Implementation |
|---------|------------------|--------|------------------------|
| **Purpose** | Grid pattern surveying coverage | **Not implemented** | N/A |
| **Implementation** | Would generate systematic grid waypoints | Not planned | - |

**Technical Details**: Survey mode would automatically generate a grid pattern of waypoints covering a defined area, commonly used for agricultural field surveying or terrain mapping. The feature requires path planning algorithms for optimal coverage.

---

### 5. Plan Optimisation

| Feature | Technical Details | Status | Expected Implementation |
|---------|------------------|--------|------------------------|
| **Purpose** | Optimize mission waypoint order | **Not implemented** | N/A |
| **Implementation** | Traveling salesman problem solver | Not planned | - |

**Technical Details**: Plan optimization would reorder waypoints to minimize total travel distance/time, useful for large missions with many waypoints. Would require path planning algorithms and potentially consider terrain, obstacles, and battery constraints.

---

### 6. Dash Line Mode

| Feature | Technical Details | Status | Expected Implementation |
|---------|------------------|--------|------------------------|
| **Purpose** | Dashed/segmented spray pattern | **Not implemented** | N/A |
| **Implementation** | Alternating spray segments | Not planned | - |

**Technical Details**: Dash line mode would create intermittent spray patterns (spray-pause-spray), commonly used for row-based applications where coverage needs to alternate between sections.

---

## Summary Table

| Category | Status | Key Metric | Last Modified | Data |
|----------|--------|------------|---------------|------|
| FastAPI Server | Complete | 57 REST routes, 24 Socket.IO events | Feb 25 2026 | - |
| MAVROS Integration | Complete | 8+ subscribed topics, 6 services | Feb 24 2026 | - |
| Mission Controller | Complete | 5 states, 9 commands, dual waypoint detection | Feb 24 2026 | - |
| Manual Control | Complete | Differential drive, 20 Hz, watchdog safety | Dec 20 2025 | - |
| RTK GPS | Complete | LoRa + NTRIP dual source | Dec 20 2025 | - |
| GPS Failsafe | Complete | 3 modes, RTK Fixed requirement | Jan 31 2026 | - |
| Obstacle Detection | Complete | 3 zones, A2111BU sensor | Feb 20 2026 | - |
| LED Feedback | Complete | WS2812, 6 state colors | Feb 20 2026 | - |
| TTS | Complete | Edge-tts + Piper, 3 languages, 18+ events | Feb 20 2026 | 18 voice events |
| Telemetry | Complete | 10 Hz aggregated stream | Feb 24 2026 | - |
| Altitude Corrector | Complete | +92.2m offset fix | Dec 20 2025 | - |
| Network Monitor | Complete | WiFi RSSI tracking | - | - |
| Continuous Line Script | **Pending** | - | - | Reference only |
| Interval Spray Script | **Pending** | - | - | Reference only |
| Waypoint Mark Script | **Pending** | - | - | Reference only |
| Survey Mode | **Not Planned** | - | - | - |
| Plan Optimisation | **Not Planned** | - | - | - |
| Dash Line Mode | **Not Planned** | - | - | - |

---

## Key File Modification Dates

| File | Last Modified | Status |
|------|---------------|--------|
| server.py | Feb 25 2026 18:19 | Most recent |
| integrated_mission_controller.py | Feb 24 2026 18:56 | Complete |
| telemetry_node.py | Feb 24 2026 19:01 | Complete |
| mavros_bridge.py | Feb 24 2026 17:44 | Complete |
| socket_docs_router.py | Feb 23 2026 13:31 | Complete |
| ultrasonic_sensor.py | Feb 17 2026 13:20 | Complete |
| gps_failsafe_monitor.py | Jan 31 2026 17:28 | Complete |
| led_controller.py | Feb 20 2026 16:22 | Complete |
| obstacle_monitor.py | Feb 20 2026 15:10 | Complete |
| tts.py | Feb 20 2026 19:24 | Complete |
| lora_rtk_handler.py | Dec 20 2025 12:44 | Complete |
| lora_receiver_usb.py | Dec 20 2025 12:44 | Complete |
| manual_control_handler.py | Dec 20 2025 12:44 | Complete |
| gps_altitude_corrector.py | Dec 20 2025 12:44 | Complete |

---
