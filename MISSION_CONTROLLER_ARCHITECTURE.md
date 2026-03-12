# NRP ROS Mission Controller - Complete Architecture & Communication Flow

## Executive Summary

The integrated mission controller is a sophisticated system that manages autonomous rover missions with GPS failsafe, obstacle detection, and servo control. It communicates with the frontend via WebSocket (Socket.IO) and with the rover via MAVROS bridge (ROS2/rosbridge).

---

## 1. OVERALL MISSION EXECUTION FLOW

### 1.1 Mission Lifecycle States
```
IDLE → LOADING → READY → RUNNING → COMPLETED/STOPPED/ERROR
                           ↓
                        PAUSED (can resume)
```

### 1.2 Key Execution Steps

#### Step 1: Mission Load
- **Trigger**: Frontend sends `POST /api/mission/load` or Socket.IO `mission_upload`
- **Process**:
  1. Validate waypoints (lat/lng coordinates)
  2. Apply servo modes if configured (MARK_AT_WAYPOINT, CONTINUOUS_LINE, INTERVAL_SPRAY)
  3. Convert to MAVROS format
  4. Push to Pixhawk via `bridge.push_waypoints()`
  5. Update `current_mission` global variable
  6. Emit `mission_status` with `event_type: 'mission_loaded'`

#### Step 2: Mission Start
- **Trigger**: Frontend sends `POST /api/mission/start` or Socket.IO `send_command` with `command: 'start'`
- **Process**:
  1. Verify vehicle armed (call `bridge.arm(value=True)`)
  2. Set mission state to `RUNNING`
  3. Initialize failsafe monitor (if STRICT mode)
  4. Start RTK monitoring loop (if STRICT mode)
  5. Start obstacle detection (if enabled)
  6. Execute first waypoint or all waypoints (based on mode)
  7. Emit `mission_status` with `event_type: 'mission_started'`

#### Step 3: Waypoint Execution (Point-by-Point Mode)
- **Trigger**: Mission running, waiting for waypoint reach
- **Process**:
  1. Upload single waypoint to Pixhawk (HOME + mission WP)
  2. Set current waypoint to 1
  3. Arm vehicle
  4. Set mode to AUTO
  5. Wait for `/mavros/mission/reached` topic (primary) or distance fallback
  6. On waypoint reached:
     - Set mode to HOLD
     - Check GPS accuracy (failsafe)
     - Execute servo sequence (ON → spray → OFF)
     - Proceed to next waypoint or complete mission

#### Step 4: Waypoint Execution (Multi-Waypoint Mode - Continuous/Dash)
- **Trigger**: Mission mode is CONTINUOUS or DASH
- **Process**:
  1. Upload ALL waypoints at once to Pixhawk
  2. Set current waypoint to 1
  3. Arm vehicle
  4. Set mode to AUTO
  5. Rover navigates autonomously through all waypoints
  6. On each waypoint reached:
     - Continuous: Turn servo ON at first WP, OFF at last WP
     - Dash: Toggle servo ON/OFF based on time or distance intervals
  7. On mission complete: Set mode to HOLD, emit completion event

---

## 2. WEBSOCKET FRONTEND-BACKEND COMMUNICATION

### 2.1 Connection Lifecycle

#### Client Connect
```
Client → Server: WebSocket connect
Server → Client: 'connection_response' {status: 'connected', sid: <session_id>}
Server → Client: 'failsafe_mode_changed' {mode: <current_mode>}
Server → Client: 'connection_status' {status: 'CONNECTED_TO_ROVER' | 'WAITING_FOR_ROVER'}
Server → Client: 'rover_data' {position, battery, mode, armed, ...}
```

#### Client Disconnect
```
Client → Server: WebSocket disconnect
Server: Clean up manual control session (if active)
Server: Remove from _client_sessions
```

### 2.2 Mission Status Events

#### Mission Loaded
```json
{
  "event_type": "mission_loaded",
  "mission_state": "ready",
  "message": "Mission loaded with N waypoints",
  "waypoints_count": N,
  "level": "success"
}
```

#### Mission Started
```json
{
  "event_type": "mission_started",
  "mission_state": "running",
  "message": "Mission started",
  "level": "success"
}
```

#### Waypoint Executing
```json
{
  "event_type": "waypoint_executing",
  "mission_state": "running",
  "current_waypoint": N,
  "total_waypoints": M,
  "waypoint": {lat, lng, alt},
  "mode": "auto|manual|continuous|dash",
  "level": "info"
}
```

#### Waypoint Reached
```json
{
  "event_type": "waypoint_reached",
  "mission_state": "running",
  "current_waypoint": N,
  "waypoint_id": N,
  "timestamp": "ISO8601",
  "position": {lat, lng, alt},
  "accuracy_error_mm": X.X,
  "level": "success"
}
```

#### Waypoint Marked (Servo Executed)
```json
{
  "event_type": "waypoint_marked",
  "mission_state": "running",
  "current_waypoint": N,
  "waypoint_id": N,
  "timestamp": "ISO8601",
  "marking_status": "completed",
  "spray_duration": X.X,
  "accuracy_error_mm": X.X,
  "level": "success"
}
```

#### Mission Completed
```json
{
  "event_type": "mission_completed",
  "mission_state": "completed",
  "message": "Mission completed successfully",
  "mission_duration": X.X,
  "waypoints_completed": N,
  "completion_time": "ISO8601",
  "level": "success"
}
```

#### Mission Error
```json
{
  "event_type": "mission_error",
  "mission_state": "error",
  "message": "Error description",
  "error_source": "load_mission|start|waypoint_execution",
  "error_message": "Detailed error",
  "level": "error"
}
```

### 2.3 Telemetry Streaming (rover_data)

**Frequency**: ~20 Hz (configurable via `TELEMETRY_HZ` env var)

**Payload Structure**:
```json
{
  "position": {lat, lng},
  "heading": X.X,
  "battery": X,
  "voltage": X.X,
  "current": X.X,
  "status": "armed|disarmed",
  "mode": "AUTO|HOLD|MANUAL|...",
  "rtk_status": "RTK Fixed|RTK Float|3D Fix|...",
  "signal_strength": "Excellent|Good|Fair|Weak|Lost",
  "satellites_visible": N,
  "hrms": "X.XXX",
  "vrms": "X.XXX",
  "imu_status": "ALIGNED|UNALIGNED",
  "groundspeed": X.X,
  "temperature": X.X,
  "rtk_fix_type": N,
  "rtk_baseline_age": X.X,
  "rtk_base_linked": true|false,
  "rtk_baseline": {baseline_a_mm, baseline_b_mm, baseline_c_mm, ...},
  "servo_output": {channels: [...], servo1_pwm: X, ...},
  "mission": {
    "status": "idle|running|paused|completed",
    "current_wp": N,
    "total_wp": M,
    "progress_pct": X.X
  },
  "network": {
    "connection_type": "wifi|lora|none",
    "wifi_signal_strength": X,
    "wifi_rssi": X,
    "wifi_connected": true|false,
    "lora_connected": true|false
  },
  "manual_control": {active: true|false},
  "gps_failsafe_mode": "disable|strict|relax",
  "gps_failsafe_triggered": true|false,
  "gps_failsafe_servo_suppressed": true|false,
  "gps_failsafe_accuracy_error_mm": X.X
}
```

### 2.4 Command Handlers (Socket.IO)

#### send_command
```json
Request: {
  "command": "ARM_DISARM|SET_MODE|GOTO|UPLOAD_MISSION|GET_MISSION|CLEAR_MISSION",
  "arm": true|false,  // for ARM_DISARM
  "mode": "AUTO|HOLD|MANUAL",  // for SET_MODE
  "lat": X.X, "lng": X.X, "alt": X.X,  // for GOTO
  "waypoints": [...],  // for UPLOAD_MISSION
  "servoConfig": {...}  // optional for UPLOAD_MISSION
}

Response: {
  "status": "success|error",
  "message": "...",
  "acked": true
}
```

#### Mission Commands
```
subscribe_mission_status → mission_status_subscribed + mission_status_history
get_mission_status → mission_status_response
```

#### Manual Control
```
manual_control {left_pwm, right_pwm, ...} → manual_control_error (if error)
emergency_stop → manual_control_stopped
stop_manual_control → command_response
```

#### GPS Failsafe
```
set_gps_failsafe_mode {mode: "disable|strict|relax"} → failsafe_mode_changed
request_gps_failsafe_mode → failsafe_mode_changed
failsafe_acknowledge → failsafe_acknowledged
failsafe_resume_mission → failsafe_resumed
failsafe_restart_mission → failsafe_restarted
```

#### Obstacle Detection
```
set_obstacle_detection {enabled: true|false} → obstacle_detection_changed
```

#### RTK Injection
```
connect_caster {host, port, mountpoint, user, password} → rtk_log, caster_status
disconnect_caster → rtk_log, caster_status
start_lora_rtk_stream → rtk_log, lora_rtk_status
stop_lora_rtk_stream → rtk_log, lora_rtk_status
get_lora_rtk_status → lora_rtk_status
```

---

## 3. SERVICE CALLS & SUBSCRIPTIONS

### 3.1 MAVROS Service Calls (via rclpy)

#### Arming
```
Service: /mavros/cmd/arming
Type: mavros_msgs/srv/CommandBool
Request: {value: true|false}
Response: {success: bool, result: bool}
```

#### Set Mode
```
Service: /mavros/set_mode
Type: mavros_msgs/srv/SetMode
Request: {base_mode: int, custom_mode: str}
Response: {mode_sent: bool, success: bool}
```

#### Command Long
```
Service: /mavros/cmd/command
Type: mavros_msgs/srv/CommandLong
Request: {broadcast, command, confirmation, param1-7}
Response: {success: bool, result: int}
```

#### Waypoint Push
```
Service: /mavros/mission/push
Type: mavros_msgs/srv/WaypointPush
Request: {start_index: int, waypoints: [Waypoint]}
Response: {success: bool, wp_transfered: int}
```

#### Waypoint Clear
```
Service: /mavros/mission/clear
Type: mavros_msgs/srv/WaypointClear
Request: {}
Response: {success: bool}
```

#### Waypoint Set Current
```
Service: /mavros/mission/set_current
Type: mavros_msgs/srv/WaypointSetCurrent
Request: {wp_seq: int}
Response: {success: bool}
```

#### Waypoint Pull
```
Service: /mavros/mission/pull
Type: mavros_msgs/srv/WaypointPull
Request: {}
Response: {success: bool, wp_received: int}
```

### 3.2 MAVROS Topic Subscriptions (via roslibpy)

#### State
```
Topic: /mavros/state
Type: mavros_msgs/State
Fields: connected, armed, mode, system_status
Handler: _handle_state()
```

#### Position (NavSat)
```
Topic: /mavros/global_position/global_corrected
Type: sensor_msgs/NavSatFix
Fields: latitude, longitude, altitude, position_covariance
Handler: _handle_navsat()
```

#### GPS Raw
```
Topic: /mavros/gpsstatus/gps1/raw
Type: mavros_msgs/GPSRAW
Fields: fix_type, satellites_visible
Handler: _handle_gps_raw()
```

#### RTK Baseline
```
Topic: /mavros/gps_rtk/rtk_baseline
Type: mavros_msgs/RTKBaseline
Fields: baseline_a_mm, baseline_b_mm, baseline_c_mm, accuracy, iar_num_hypotheses
Handler: _handle_rtk_baseline()
```

#### Heading
```
Topic: /mavros/global_position/compass_hdg
Type: std_msgs/Float64
Handler: _handle_heading()
```

#### Battery
```
Topic: /mavros/battery
Type: sensor_msgs/BatteryState
Fields: percentage, voltage, current
Handler: _handle_battery()
```

#### Velocity
```
Topic: /mavros/global_position/raw/gps_vel
Type: geometry_msgs/TwistStamped
Handler: _handle_velocity()
```

#### Servo Output
```
Topic: /mavros/rc/out
Type: mavros_msgs/RCOut
Fields: channels (PWM values)
Handler: _handle_servo_output()
```

#### Mission Waypoints
```
Topic: /mavros/mission/waypoints
Type: mavros_msgs/WaypointList
Handler: _handle_waypoint_list()
```

#### Waypoint Reached (Primary)
```
Topic: /mavros/mission/reached
Type: mavros_msgs/WaypointReached
Fields: wp_seq
Handler: _handle_waypoint_reached_rclpy() (rclpy) or _handle_waypoint_reached() (roslibpy)
```

#### Estimator Status
```
Topic: /mavros/estimator_status
Type: mavros_msgs/EstimatorStatus
Handler: _handle_estimator_status()
```

#### IMU Data
```
Topic: /mavros/imu/data
Type: sensor_msgs/Imu
Handler: _handle_imu_data()
```

### 3.3 MAVROS Topic Publications

#### RTCM Corrections (rclpy - PRIMARY)
```
Topic: /mavros/gps_rtk/send_rtcm
Type: mavros_msgs/RTCM
Publisher: bridge._rtcm_pub_rclpy
Method: bridge.send_rtcm(payload: bytes)
```

#### RC Override (roslibpy)
```
Topic: /mavros/rc/override
Type: mavros_msgs/OverrideRCIn
Publisher: bridge._rc_override_topic
Method: bridge.send_rc_override(channels: Dict[int, int])
```

#### Global Position Target (roslibpy)
```
Topic: /mavros/setpoint_raw/global
Type: mavros_msgs/GlobalPositionTarget
Publisher: bridge._setpoint_topic
Method: bridge.send_global_position_target(...)
```

---

## 4. SERVER READINESS & INITIALIZATION

### 4.1 Startup Sequence

```
1. FastAPI lifespan startup
   ├─ Load system settings from config file
   ├─ Start maintain_mavros_connection() task
   ├─ Start telemetry_loop() task
   ├─ Start connection_health_monitor() task
   └─ Start rover discovery beacon

2. maintain_mavros_connection() loop
   ├─ Initialize MAVROS bridge (_init_mavros_bridge)
   ├─ Connect to rosbridge WebSocket
   ├─ Subscribe to telemetry topics
   ├─ Initialize mission controller (initialize_mission_controller)
   ├─ Initialize manual control handler (initialize_manual_control_handler)
   └─ Monitor for disconnections

3. Mission Controller Initialization
   ├─ Create IntegratedMissionController instance
   ├─ Set GPS failsafe mode from config
   ├─ Set obstacle detection from config
   ├─ Load LED enabled state from config
   └─ Register status callback (handle_mission_status)

4. Manual Control Handler Initialization
   ├─ Create ManualControlHandler instance
   └─ Register with MAVROS bridge
```

### 4.2 Essential State for Frontend

#### Connection Status
```json
{
  "status": "CONNECTED_TO_ROVER | WAITING_FOR_ROVER",
  "message": "...",
  "timestamp": <unix_timestamp>
}
```

#### Server Health
```json
{
  "timestamp": <unix_timestamp>,
  "active_clients": N,
  "total_clients": N,
  "vehicle_connected": true|false,
  "ros_available": true|false,
  "uptime": <seconds>
}
```

#### Mission Status (Cached)
```
mission_status_history: deque[dict] (max 10 entries)
latest_mission_status: dict
```

#### Current Rover State
```
current_state: CurrentState {
  position, heading, battery, voltage, current,
  status, mode, rtk_status, signal_strength,
  satellites_visible, hrms, vrms, imu_status,
  groundspeed, temperature, rtk_fix_type,
  rtk_baseline_age, rtk_base_linked, rtk_baseline,
  servo_output, mission, network, manual_control,
  gps_failsafe_mode, gps_failsafe_triggered,
  gps_failsafe_servo_suppressed, gps_failsafe_accuracy_error_mm
}
```

#### Activity Log
```
activity_log: deque[dict] (max 2000 entries)
Each entry: {
  id, timestamp, isoTime, level, event, message, meta
}
```

### 4.3 Configuration Files

#### mission_controller_config.json
```json
{
  "mission_controller": {
    "sprayer_parameters": {
      "servo_channel": 9,
      "servo_pwm_on": 1900,
      "servo_pwm_off": 1100,
      "servo_delay_before": 0.0,
      "servo_spray_duration": 0.2,
      "servo_delay_after": 0.0,
      "servo_enabled": true
    },
    "mission_parameters": {
      "waypoint_reach_threshold": 0.25,
      "mission_timeout": 3000.0,
      "accuracy_threshold_mm": 60.0,
      "fallback_zone_timeout_seconds": 30.0
    },
    "safety_parameters": {
      "gps_failsafe_mode": "disable|strict|relax",
      "obstacle_detection_enabled": false
    }
  },
  "system_settings": {
    "led_enabled": true,
    "gps_failsafe_mode": "disable"
  },
  "metadata": {
    "version": "1.0",
    "last_updated": "2025-01-01T00:00:00",
    "description": "Mission controller configuration"
  }
}
```

---

## 5. CRITICAL COMMUNICATION PATTERNS

### 5.1 Blocking Operations Handling

**Problem**: Service calls (arm, set_mode, push_waypoints) can block for 10+ seconds, stalling telemetry.

**Solution**: Use `_suppress_disconnect_during_bridge_call()` context manager
```python
with _suppress_disconnect_during_bridge_call():
    bridge.push_waypoints(waypoints)  # Blocks, but disconnect check suppressed
```

### 5.2 Telemetry Throttling

**Problem**: Telemetry updates at 50+ Hz, but frontend only needs ~20 Hz.

**Solution**: Throttle with `schedule_fast_emit()` and `EMIT_MIN_INTERVAL`
```python
EMIT_MIN_INTERVAL = 0.05  # 20 Hz
schedule_fast_emit()  # Emits only if interval elapsed
```

### 5.3 Callback Thread Safety

**Problem**: MAVROS telemetry callbacks run on roslibpy WebSocket thread, blocking stalls all telemetry.

**Solution**: Offload to daemon threads
```python
threading.Thread(
    target=self._broadcast_telem,
    args=(...),
    daemon=True
).start()
```

### 5.4 Mission Status History for Reconnection

**Problem**: Frontend reconnects and misses mission events.

**Solution**: Cache last 10 mission status messages
```python
mission_status_history: deque = deque(maxlen=10)
# On client connect: emit mission_status_history
```

---

## 6. ESSENTIAL STATE FOR FRONTEND READINESS

### 6.1 Minimum Required State

1. **Connection Status**: Vehicle connected or waiting
2. **Current Position**: Latitude, longitude, altitude
3. **Vehicle State**: Armed/disarmed, mode, battery
4. **Mission State**: Idle/running/paused/completed
5. **RTK Status**: Fix type, base linked, baseline age
6. **Failsafe Mode**: Current GPS failsafe mode

### 6.2 Initialization Checklist

- [ ] MAVROS bridge connected to rosbridge
- [ ] Telemetry subscriptions active
- [ ] Mission controller initialized
- [ ] Manual control handler initialized
- [ ] LED controller initialized
- [ ] Configuration loaded from file
- [ ] Activity log initialized
- [ ] Client session tracking active
- [ ] Health monitor running
- [ ] Rover discovery beacon running

### 6.3 Frontend Readiness Signals

```
Server Ready: All background tasks started + MAVROS connected
Vehicle Ready: Vehicle connected + armed + in AUTO mode
Mission Ready: Mission loaded + vehicle armed + in AUTO mode
```

---

## 7. ERROR HANDLING & RECOVERY

### 7.1 Disconnection Detection

```
Trigger: No telemetry for 20 seconds
Action: 
  1. Flag disconnect
  2. Close bridge
  3. Shutdown mission controller
  4. Emit WAITING_FOR_ROVER
  5. Attempt reconnection
```

### 7.2 Mission Failure Recovery

```
Trigger: Waypoint timeout (3000s default)
Action:
  1. Set mode to HOLD
  2. Emit waypoint_failed event
  3. Set mission state to ERROR
  4. Allow manual restart
```

### 7.3 GPS Failsafe Modes

- **disable**: No GPS failsafe checks
- **relax**: Suppress servo if accuracy > 60mm
- **strict**: Pause mission if RTK fix lost, require user acknowledgment

---

## 8. PERFORMANCE METRICS

- **Telemetry Update Rate**: ~20 Hz (configurable)
- **Mission Status Events**: Real-time (< 100ms latency)
- **Service Call Timeout**: 3-10 seconds (rclpy) + 10 seconds (CLI fallback)
- **Waypoint Upload**: ~1-5 seconds for 10 waypoints
- **RTK Injection**: Continuous streaming, 180-byte chunks
- **Activity Log**: 2000 entries max, ~1KB per entry

---

## 9. DEBUGGING & MONITORING

### 9.1 Activity Log Endpoints

```
GET /api/activity - Recent activity entries
GET /api/activity/types - Known event types
GET /api/activity/download - Download as text file
```

### 9.2 Monitor Dashboard

```
GET /monitor - Activity monitor page
GET /node/{node_name} - Node details page
```

### 9.3 Health Check

```
GET /api/ping - Server ping with rover ID
GET /api/health - Server health status
```

---

## 10. SUMMARY TABLE

| Component | Type | Protocol | Frequency | Timeout |
|-----------|------|----------|-----------|---------|
| Telemetry | Subscription | roslibpy | 50+ Hz | N/A |
| Telemetry Emit | Publication | Socket.IO | 20 Hz | N/A |
| Arm/Disarm | Service | rclpy | On-demand | 3s + 10s |
| Set Mode | Service | rclpy | On-demand | 3s + 10s |
| Waypoint Push | Service | rclpy | On-demand | 3s + 15s |
| Waypoint Reached | Subscription | rclpy | Event-driven | N/A |
| RTCM Send | Publication | rclpy | Continuous | N/A |
| Mission Status | Event | Socket.IO | Event-driven | N/A |
| Rover Data | Event | Socket.IO | 20 Hz | N/A |
| Activity Log | Event | Socket.IO | On-demand | N/A |

