# Integrated Mission Controller - API Endpoints & WebSocket Events

## 📊 Executive Summary

| Category | Count | Details |
|----------|-------|---------|
| **REST API Endpoints** | 57 | HTTP GET/POST/PUT/DELETE endpoints |
| **WebSocket Event Handlers (Input)** | 24 | Socket events client sends to server |
| **WebSocket Event Emitters (Output)** | 35 | Socket events server sends to client |
| **Total Communication Points** | 116 | All endpoints + handlers + emitters |

---

## 🔌 Mission Controller - Specific Endpoints

### Mission Management Endpoints

#### Load & Start Mission
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/mission/load_controller` | Load waypoints into integrated controller |
| POST | `/api/mission/start_controller` | Start loaded mission execution |
| POST | `/api/mission/load` | Load mission (legacy) |
| POST | `/api/mission/start` | Start mission (dual method) |
| GET | `/api/mission/start` | Get mission start status |

#### Mission Execution Control
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/mission/stop` | Stop current mission |
| POST | `/api/mission/pause` | Pause mission execution |
| POST | `/api/mission/resume` | Resume paused mission |
| POST | `/api/mission/restart` | Restart mission from beginning |
| POST | `/api/mission/next` | Advance to next waypoint (manual mode) |
| POST | `/api/mission/skip` | Skip current waypoint |
| POST | `/api/mission/stop_controller` | Stop integrated controller |

#### Mission Status & Query
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/mission/status` | Get current mission execution status |
| GET | `/api/mission/mode` | Get mission mode (AUTO/MANUAL) |
| POST | `/api/mission/mode` | Set mission mode |
| GET | `/api/mission/config` | Get mission configuration parameters |
| POST | `/api/mission/config` | Update mission configuration |

#### Mission Upload/Download
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/mission/upload` | Upload mission to Pixhawk |
| GET | `/api/mission/download` | Download mission from Pixhawk |
| POST | `/api/mission/clear` | Clear mission from Pixhawk |
| POST | `/api/mission/set_current` | Set current waypoint index |
| POST | `/api/mission/resume_deprecated` | Resume mission (deprecated) |

#### Servo Configuration
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/mission/servo_config` | Update servo/spray parameters |
| GET | `/api/mission/servo_config` | Get current servo configuration |

---

## 🟢 WebSocket Events Related to Mission Controller

### Mission Status Events (WebSocket Input)
Client sends these events to server:

| Event | Purpose | Parameters |
|-------|---------|------------|
| `subscribe_mission_status` | Subscribe to mission status updates | - |
| `get_mission_status` | Request current mission status | - |
| `send_command` | Send mission command (start/stop/pause) | command, data |
| `set_gps_failsafe_mode` | Set GPS failsafe mode | mode: "disable"/"relax"/"strict" |
| `set_obstacle_detection` | Enable/disable obstacle detection | enabled: bool |
| `failsafe_acknowledge` | Acknowledge failsafe condition | - |
| `failsafe_resume_mission` | Resume mission after failsafe | - |
| `failsafe_restart_mission` | Restart mission after failsafe | - |

### Mission Status Events (WebSocket Output - Server Emits)
Server broadcasts these events to connected clients:

| Event | Purpose | Data Includes |
|-------|---------|---------------|
| `mission_status` | Current mission execution state | state, waypoint, position, mode |
| `mission_event` | Mission lifecycle events | event_type, waypoint, timestamp |
| `mission_status_subscribed` | Subscription confirmed | - |
| `mission_status_response` | Response to status query | Full mission status object |
| `mission_status_history` | Mission execution history | All completed waypoints |
| `failsafe_mode_changed` | Failsafe mode changed | new_mode, reason |
| `failsafe_acknowledged` | Failsafe acknowledged | - |
| `failsafe_resumed` | Mission resumed after failsafe | - |
| `failsafe_restarted` | Mission restarted after failsafe | - |
| `failsafe_error` | Failsafe error occurred | error_message |
| `obstacle_detection_changed` | Obstacle detection toggled | enabled: bool |
| `obstacle_error` | Obstacle detection error | error_message |
| `command_response` | Response to mission command | success, message, result |

---

## 📝 New Configurable Parameters (Just Added)

These 4 parameters are now configurable via API:

### 1. Mission Timeout
- **Endpoint**: POST `/api/mission/config` or `update_mission_parameters()`
- **Parameter**: `mission_timeout`
- **Type**: float (seconds)
- **Default**: 3000.0 (5 minutes per waypoint)
- **Purpose**: Maximum time allowed to reach any waypoint before timeout

### 2. Accuracy Threshold
- **Endpoint**: POST `/api/mission/config` or `update_mission_parameters()`
- **Parameter**: `accuracy_threshold_mm`
- **Type**: float (millimeters)
- **Default**: 60.0 mm
- **Purpose**: GPS error threshold - suppress spray if exceeds this

### 3. Fallback Zone Timeout
- **Endpoint**: POST `/api/mission/config` or `update_mission_parameters()`
- **Parameter**: `fallback_zone_timeout_seconds`
- **Type**: float (seconds)
- **Default**: 30.0 seconds
- **Purpose**: Wait time in threshold zone before using GPS distance fallback

### 4. Obstacle Detection Zones
- **Endpoint**: POST `/api/mission/config` or `update_obstacle_zones()`
- **Parameters**:
  - `warning_min_mm` - Default: 1200 (1.2m)
  - `warning_max_mm` - Default: 2000 (2.0m)
  - `danger_min_mm` - Default: 800 (0.8m)
  - `danger_max_mm` - Default: 1000 (1.0m)
- **Purpose**: Define obstacle detection zones

---

## 🎯 REST API Endpoints - Complete List (57 Total)

### Core Navigation (7 endpoints)
1. POST `/api/arm` - Arm vehicle
2. POST `/api/set_mode` - Set flight mode (AUTO/HOLD/MANUAL)
3. GET `/` - Root endpoint
4. GET `/monitor` - Monitor dashboard
5. GET `/node/{node_name}` - Node details
6. POST `/mission/set_current` - Set current waypoint
7. GET `/api/mission/start` - Get mission start status

### Mission Management (14 endpoints)
1. POST `/api/mission/load_controller`
2. POST `/api/mission/start_controller`
3. POST `/api/mission/stop_controller`
4. POST `/api/mission/load`
5. POST `/api/mission/start`
6. POST `/api/mission/stop`
7. POST `/api/mission/pause`
8. POST `/api/mission/resume`
9. POST `/api/mission/restart`
10. POST `/api/mission/next`
11. POST `/api/mission/skip`
12. POST `/api/mission/upload`
13. GET `/api/mission/download`
14. POST `/api/mission/clear`

### Mission Configuration (6 endpoints)
1. GET `/api/mission/status`
2. GET `/api/mission/mode`
3. POST `/api/mission/mode`
4. GET `/api/mission/config`
5. POST `/api/mission/config`
6. POST `/api/mission/resume_deprecated`

### Servo Control (5 endpoints)
1. POST `/api/mission/servo_config`
2. GET `/api/mission/servo_config`
3. POST `/api/servo/control`
4. GET `/servo/run`
5. GET `/servo/stop`

### Activity & Logging (3 endpoints)
1. GET `/api/activity`
2. GET `/api/activity/types`
3. GET `/api/activity/download`

### RTK/GNSS (8 endpoints)
1. POST `/api/rtk/inject`
2. POST `/api/rtk/stop`
3. POST `/api/rtk/ntrip_stop`
4. POST `/api/rtk/lora_stop`
5. POST `/api/rtk/ntrip_start`
6. POST `/api/rtk/lora_start`
7. GET `/api/rtk/status`
8. POST `/api/rtk/force_clear`

### TTS/Audio (5 endpoints)
1. GET `/api/tts/status`
2. POST `/api/tts/control`
3. POST `/api/tts/test`
4. GET `/api/tts/languages`
5. POST `/api/tts/language`

### System & Diagnostics (5 endpoints)
1. POST `/servo/emergency_stop`
2. GET `/servo/status`
3. GET `/servo/edit`
4. POST `/servo/edit`
5. GET `/servo/log`

### Node Management (2 endpoints)
1. GET `/api/nodes`
2. GET `/api/node/{node_name}`

### Config/Sprayer (2 endpoints)
1. GET `/api/config/sprayer`
2. POST `/api/config/sprayer`

---

## 🔊 WebSocket Event Handlers (24 Input Events)

Server receives these events from client:

### Mission Control (8 events)
1. `subscribe_mission_status` - Subscribe to mission updates
2. `get_mission_status` - Request mission status
3. `send_command` - Send mission command
4. `set_gps_failsafe_mode` - Configure failsafe
5. `set_obstacle_detection` - Toggle obstacle detection
6. `failsafe_acknowledge` - Acknowledge failsafe condition
7. `failsafe_resume_mission` - Resume after failsafe
8. `failsafe_restart_mission` - Restart after failsafe

### Manual Control (2 events)
1. `manual_control` - Manual rover control
2. `stop_manual_control` - Stop manual control
3. `emergency_stop` - Emergency stop rover

### RTK/GNSS (4 events)
1. `connect_caster` - Connect to NTRIP caster
2. `disconnect_caster` - Disconnect from caster
3. `start_lora_rtk_stream` - Start LoRa RTK stream
4. `stop_lora_rtk_stream` - Stop LoRa RTK stream

### System (5 events)
1. `connect` - Client connection
2. `disconnect` - Client disconnection
3. `ping` - Ping (keep-alive)
4. `request_mission_logs` - Request mission logs
5. `request_rover_reconnect` - Reconnect to rover

### Data Injection (1 event)
1. `inject_mavros_telemetry` - Inject telemetry data

### Broadcast/Other (1 event)
1. `*` - Wildcard event handler

---

## 📡 WebSocket Emitters - Server Output Events (35 Unique Events)

Server broadcasts these events to all connected clients:

### Mission Status Updates (8 events)
1. `mission_status` - Current mission state
2. `mission_event` - Mission event occurred
3. `mission_status_response` - Response to status query
4. `mission_status_subscribed` - Subscription confirmed
5. `mission_status_history` - Mission history
6. `mission_upload_progress` - Mission upload progress
7. `mission_download_progress` - Mission download progress
8. `mission_logs_snapshot` - Mission logs snapshot

### Failsafe Events (5 events)
1. `failsafe_mode_changed` - Failsafe mode changed
2. `failsafe_acknowledged` - Failsafe acknowledged
3. `failsafe_resumed` - Mission resumed
4. `failsafe_restarted` - Mission restarted
5. `failsafe_error` - Failsafe error

### Obstacle Events (2 events)
1. `obstacle_detection_changed` - Detection toggled
2. `obstacle_error` - Obstacle error

### RTK/GNSS Events (5 events)
1. `caster_status` - NTRIP caster status
2. `lora_rtk_status` - LoRa RTK status
3. `rtk_debug` - RTK debug info
4. `rtk_forwarded` - RTK data forwarded
5. `rtk_log` - RTK logging

### System Events (10 events)
1. `rover_data` - Telemetry data (position, speed, mode, etc.)
2. `telemetry` - Raw telemetry
3. `connection_status` - Connection status
4. `connection_response` - Connection response
5. `connection_warning` - Connection warning
6. `rover_reconnect_ack` - Reconnection acknowledged
7. `server_activity` - Server activity
8. `server_health` - Server health status
9. `server_log` - Server logs
10. `rtcm_data` - RTCM correction data

### Utility Events (5 events)
1. `pong` - Pong response
2. `command_response` - Command response
3. `inject_ack` - Injection acknowledged
4. `manual_control_error` - Manual control error
5. `manual_control_stopped` - Manual control stopped

---

## 📊 Parameter Categories

### Total Configurable Parameters in Mission Controller: 17

#### Mission Execution (4 parameters)
1. `waypoint_reached_threshold` - Distance threshold
2. `hold_duration` - Hold time at waypoint
3. `mission_timeout` - **[NEW]** Max execution time
4. `mission_mode` - AUTO or MANUAL

#### GPS Failsafe (3 parameters)
1. `failsafe_mode` - disable/relax/strict
2. `accuracy_threshold_mm` - **[NEW]** GPS error threshold
3. `fallback_zone_timeout_seconds` - **[NEW]** Fallback wait time

#### Servo Control (7 parameters)
1. `servo_enabled` - Enable/disable servo
2. `servo_channel` - PWM channel number
3. `servo_pwm_on` - ON pulse width
4. `servo_pwm_off` - OFF pulse width
5. `servo_delay_before` - Pre-spray delay
6. `servo_spray_duration` - Spray duration
7. `servo_delay_after` - Post-spray delay

#### Obstacle Detection (4 parameters - **[NEW]**)
1. `obstacle_warning_min_mm` - Warning zone minimum
2. `obstacle_warning_max_mm` - Warning zone maximum
3. `obstacle_danger_min_mm` - Danger zone minimum
4. `obstacle_danger_max_mm` - Danger zone maximum

#### Obstacle Detection (1 parameter)
1. `obstacle_detection_enabled` - Enable/disable detection

---

## 🔄 Mission Controller Internal Methods

### Public API Methods for External Configuration
1. `update_servo_config(servo_config)` - Configure servo
2. `update_mission_parameters(mission_params)` - **[NEW]** Configure mission params
3. `update_obstacle_zones(obstacle_config)` - **[NEW]** Configure obstacle zones
4. `set_failsafe_mode(mode)` - Configure failsafe
5. `set_obstacle_detection(enabled)` - Toggle obstacle detection
6. `load_mission(command_data)` - Load waypoints
7. `start_mission()` - Start execution
8. `stop_mission()` - Stop execution
9. `pause_mission()` - Pause execution
10. `resume_mission()` - Resume execution
11. `set_mode(mode)` - Set AUTO/MANUAL mode

---

## 📈 Architecture Overview

```
┌─────────────────────────────────────────────────┐
│          Frontend Web Client                     │
│  (WebSocket + REST API calls)                    │
└────────────┬────────────────────────────────────┘
             │
     ┌───────┴────────┐
     │                │
 WebSocket (35)   REST API (57)
   Events           Endpoints
     │                │
     └───────┬────────┘
             │
    ┌────────▼────────┐
    │   FastAPI Server│
    │    (server.py)  │
    └────────┬────────┘
             │
    ┌────────▼──────────────────────────┐
    │ Integrated Mission Controller      │
    │ • 17 configurable parameters      │
    │ • 4 new parameters (just added)   │
    │ • Mission execution logic         │
    │ • GPS failsafe monitoring         │
    │ • Obstacle detection              │
    │ • Servo control                   │
    └────────┬──────────────────────────┘
             │
    ┌────────▼──────────────────────────┐
    │ MAVROS Bridge / Pixhawk           │
    │ • Waypoint upload                 │
    │ • Mode control                    │
    │ • Telemetry monitoring            │
    └───────────────────────────────────┘
```

---

## 🎓 Usage Examples

### Load Mission via REST API
```bash
POST /api/mission/load_controller
{
  "waypoints": [
    {"lat": 37.7749, "lng": -122.4194, "alt": 10.0},
    {"lat": 37.7750, "lng": -122.4195, "alt": 10.0}
  ],
  "config": {
    "waypoint_threshold": 0.5,
    "hold_duration": 5.0,
    "mission_timeout": 3600.0,
    "accuracy_threshold_mm": 100.0,
    "fallback_zone_timeout_seconds": 60.0
  }
}
```

### Update Mission Parameters via REST API
```bash
POST /api/mission/config
{
  "mission_timeout": 3600.0,
  "accuracy_threshold_mm": 100.0,
  "fallback_zone_timeout_seconds": 60.0
}
```

### Configure Obstacle Zones via REST API
```bash
POST /api/mission/config
{
  "warning_min_mm": 1500,
  "warning_max_mm": 2500,
  "danger_min_mm": 600,
  "danger_max_mm": 1200
}
```

### Mission Control via WebSocket
```javascript
// Subscribe to mission status
socket.emit('subscribe_mission_status');

// Get current status
socket.emit('get_mission_status');

// Send command
socket.emit('send_command', {
  command: 'start'
});

// Listen for updates
socket.on('mission_status', (data) => {
  console.log('Mission status:', data);
});

socket.on('mission_event', (data) => {
  console.log('Mission event:', data);
});
```

---

## 📋 Summary

The Integrated Mission Controller now exposes:
- **57 REST API endpoints** for programmatic control
- **24 WebSocket input handlers** for real-time client commands
- **35 WebSocket output events** for real-time server broadcasts
- **17 configurable parameters** (including 4 newly added)
- **Full parameter management API** for dynamic runtime configuration

Total communication points: **116** (endpoints + handlers + emitters)

