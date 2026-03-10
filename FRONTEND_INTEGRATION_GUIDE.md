# Frontend Integration Guide - NRP Mission Controller

## 📋 Table of Contents
1. [Quick Start](#quick-start)
2. [API Endpoints](#api-endpoints)
3. [WebSocket Input Handlers](#websocket-input-handlers)
4. [WebSocket Output Events](#websocket-output-events)
5. [Configurable Parameters](#configurable-parameters)
6. [Complete Usage Examples](#complete-usage-examples)

---

## 🚀 Quick Start

### Environment Setup
```javascript
// Initialize connection to backend
const API_BASE = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws';

// Create WebSocket connection
const socket = io(WS_URL);

// REST API helper function
async function apiCall(method, endpoint, data = null) {
  const options = {
    method,
    headers: { 'Content-Type': 'application/json' }
  };
  if (data) options.body = JSON.stringify(data);
  
  const response = await fetch(`${API_BASE}${endpoint}`, options);
  return response.json();
}
```

---

## 🔌 API Endpoints

### Mission Management

#### 1. Load Mission
```bash
POST /api/mission/load_controller
Content-Type: application/json

{
  "waypoints": [
    {
      "lat": 37.7749,
      "lng": -122.4194,
      "alt": 10.0
    },
    {
      "lat": 37.7750,
      "lng": -122.4195,
      "alt": 15.0
    }
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

**JavaScript Example:**
```javascript
async function loadMission(waypoints) {
  const response = await apiCall('POST', '/api/mission/load_controller', {
    waypoints: waypoints,
    config: {
      waypoint_threshold: 0.5,
      hold_duration: 5.0,
      mission_timeout: 3600.0,
      accuracy_threshold_mm: 100.0,
      fallback_zone_timeout_seconds: 60.0
    }
  });
  console.log('Mission loaded:', response);
  return response;
}
```

---

#### 2. Start Mission
```bash
POST /api/mission/start_controller
Content-Type: application/json
```

**JavaScript Example:**
```javascript
async function startMission() {
  const response = await apiCall('POST', '/api/mission/start_controller');
  console.log('Mission started:', response);
  return response;
}
```

---

#### 3. Stop Mission
```bash
POST /api/mission/stop
Content-Type: application/json
```

**JavaScript Example:**
```javascript
async function stopMission() {
  const response = await apiCall('POST', '/api/mission/stop');
  console.log('Mission stopped:', response);
  return response;
}
```

---

#### 4. Pause Mission
```bash
POST /api/mission/pause
Content-Type: application/json
```

**JavaScript Example:**
```javascript
async function pauseMission() {
  const response = await apiCall('POST', '/api/mission/pause');
  console.log('Mission paused:', response);
  return response;
}
```

---

#### 5. Resume Mission
```bash
POST /api/mission/resume
Content-Type: application/json
```

**JavaScript Example:**
```javascript
async function resumeMission() {
  const response = await apiCall('POST', '/api/mission/resume');
  console.log('Mission resumed:', response);
  return response;
}
```

---

#### 6. Get Mission Status
```bash
GET /api/mission/status
```

**Response:**
```json
{
  "state": "executing",
  "current_waypoint": 2,
  "position": {
    "lat": 37.7749,
    "lng": -122.4194,
    "alt": 12.5
  },
  "mode": "AUTO",
  "progress": 50,
  "time_remaining": 1200
}
```

**JavaScript Example:**
```javascript
async function getMissionStatus() {
  const response = await apiCall('GET', '/api/mission/status');
  console.log('Mission status:', response);
  return response;
}
```

---

### Mission Configuration

#### 1. Get Mission Configuration
```bash
GET /api/mission/config
```

**Response:**
```json
{
  "mission_timeout": 3000.0,
  "accuracy_threshold_mm": 60.0,
  "fallback_zone_timeout_seconds": 30.0,
  "waypoint_reached_threshold": 0.5,
  "hold_duration": 5.0,
  "obstacle_warning_min_mm": 1200,
  "obstacle_warning_max_mm": 2000,
  "obstacle_danger_min_mm": 800,
  "obstacle_danger_max_mm": 1000
}
```

**JavaScript Example:**
```javascript
async function getConfig() {
  const config = await apiCall('GET', '/api/mission/config');
  console.log('Current configuration:', config);
  return config;
}
```

---

#### 2. Update Mission Parameters
```bash
POST /api/mission/config
Content-Type: application/json

{
  "mission_timeout": 3600.0,
  "accuracy_threshold_mm": 100.0,
  "fallback_zone_timeout_seconds": 60.0,
  "waypoint_reached_threshold": 0.5,
  "hold_duration": 5.0
}
```

**JavaScript Example:**
```javascript
async function updateMissionParameters(params) {
  const response = await apiCall('POST', '/api/mission/config', params);
  console.log('Configuration updated:', response);
  return response;
}

// Usage
updateMissionParameters({
  mission_timeout: 3600.0,
  accuracy_threshold_mm: 100.0,
  fallback_zone_timeout_seconds: 60.0
});
```

---

#### 3. Configure Obstacle Zones
```bash
POST /api/mission/config
Content-Type: application/json

{
  "warning_min_mm": 1500,
  "warning_max_mm": 2500,
  "danger_min_mm": 600,
  "danger_max_mm": 1200
}
```

**JavaScript Example:**
```javascript
async function configureObstacleZones(zones) {
  const response = await apiCall('POST', '/api/mission/config', {
    warning_min_mm: zones.warningMin,
    warning_max_mm: zones.warningMax,
    danger_min_mm: zones.dangerMin,
    danger_max_mm: zones.dangerMax
  });
  console.log('Obstacle zones configured:', response);
  return response;
}

// Usage
configureObstacleZones({
  warningMin: 1500,
  warningMax: 2500,
  dangerMin: 600,
  dangerMax: 1200
});
```

---

#### 4. Set Mission Mode
```bash
POST /api/mission/mode
Content-Type: application/json

{
  "mode": "AUTO"
}
```

**Supported Modes:**
- `AUTO` - Autonomous mode (follows waypoints)
- `MANUAL` - Manual control mode

**JavaScript Example:**
```javascript
async function setMissionMode(mode) {
  const response = await apiCall('POST', '/api/mission/mode', { mode });
  console.log('Mode set to:', mode);
  return response;
}

// Usage
setMissionMode('AUTO');  // or 'MANUAL'
```

---

### Servo/Spray Configuration

#### 1. Get Servo Configuration
```bash
GET /api/mission/servo_config
```

**Response:**
```json
{
  "servo_enabled": true,
  "servo_channel": 11,
  "servo_pwm_on": 1900,
  "servo_pwm_off": 1100,
  "servo_delay_before": 0.5,
  "servo_spray_duration": 2.0,
  "servo_delay_after": 0.5
}
```

**JavaScript Example:**
```javascript
async function getServoConfig() {
  const config = await apiCall('GET', '/api/mission/servo_config');
  console.log('Servo configuration:', config);
  return config;
}
```

---

#### 2. Update Servo Configuration
```bash
POST /api/mission/servo_config
Content-Type: application/json

{
  "servo_enabled": true,
  "servo_channel": 11,
  "servo_pwm_on": 1900,
  "servo_pwm_off": 1100,
  "servo_delay_before": 0.5,
  "servo_spray_duration": 2.0,
  "servo_delay_after": 0.5
}
```

**JavaScript Example:**
```javascript
async function updateServoConfig(servoConfig) {
  const response = await apiCall('POST', '/api/mission/servo_config', {
    servo_enabled: servoConfig.enabled,
    servo_channel: servoConfig.channel,
    servo_pwm_on: servoConfig.pwmOn,
    servo_pwm_off: servoConfig.pwmOff,
    servo_delay_before: servoConfig.delayBefore,
    servo_spray_duration: servoConfig.sprayDuration,
    servo_delay_after: servoConfig.delayAfter
  });
  console.log('Servo configuration updated:', response);
  return response;
}

// Usage
updateServoConfig({
  enabled: true,
  channel: 11,
  pwmOn: 1900,
  pwmOff: 1100,
  delayBefore: 0.5,
  sprayDuration: 2.0,
  delayAfter: 0.5
});
```

---

### RTK/GNSS Management

#### 1. Start NTRIP RTK
```bash
POST /api/rtk/ntrip_start
Content-Type: application/json

{
  "caster_host": "caster.example.com",
  "caster_port": 2101,
  "mountpoint": "mount_point",
  "username": "user",
  "password": "pass"
}
```

**JavaScript Example:**
```javascript
async function startNTRIPRTK(casterConfig) {
  const response = await apiCall('POST', '/api/rtk/ntrip_start', casterConfig);
  console.log('NTRIP RTK started:', response);
  return response;
}
```

---

#### 2. Stop NTRIP RTK
```bash
POST /api/rtk/ntrip_stop
Content-Type: application/json
```

**JavaScript Example:**
```javascript
async function stopNTRIPRTK() {
  const response = await apiCall('POST', '/api/rtk/ntrip_stop');
  console.log('NTRIP RTK stopped:', response);
  return response;
}
```

---

#### 3. Get RTK Status
```bash
GET /api/rtk/status
```

**Response:**
```json
{
  "ntrip_connected": true,
  "lora_connected": false,
  "rtk_active": true,
  "correction_age": 2.5,
  "accuracy_cm": 3.2
}
```

**JavaScript Example:**
```javascript
async function getRTKStatus() {
  const status = await apiCall('GET', '/api/rtk/status');
  console.log('RTK status:', status);
  return status;
}
```

---

### Vehicle Control

#### 1. Arm Vehicle
```bash
POST /api/arm
Content-Type: application/json
```

**JavaScript Example:**
```javascript
async function armVehicle() {
  const response = await apiCall('POST', '/api/arm');
  console.log('Vehicle armed:', response);
  return response;
}
```

---

#### 2. Set Flight Mode
```bash
POST /api/set_mode
Content-Type: application/json

{
  "mode": "AUTO"
}
```

**Supported Modes:**
- `AUTO` - Autonomous mode
- `MANUAL` - Manual control mode
- `HOLD` - Hold position
- `GUIDED` - Guided mode

**JavaScript Example:**
```javascript
async function setFlightMode(mode) {
  const response = await apiCall('POST', '/api/set_mode', { mode });
  console.log('Flight mode set to:', mode);
  return response;
}
```

---

### TTS/Audio Management

#### 1. Get TTS Status
```bash
GET /api/tts/status
```

**Response:**
```json
{
  "enabled": true,
  "current_language": "en",
  "available_languages": ["en", "ta", "hi", "te"]
}
```

**JavaScript Example:**
```javascript
async function getTTSStatus() {
  const status = await apiCall('GET', '/api/tts/status');
  console.log('TTS status:', status);
  return status;
}
```

---

#### 2. Get Available Languages
```bash
GET /api/tts/languages
```

**Response:**
```json
{
  "languages": [
    { "code": "en", "name": "English" },
    { "code": "ta", "name": "Tamil" },
    { "code": "hi", "name": "Hindi" },
    { "code": "te", "name": "Telugu" }
  ]
}
```

**JavaScript Example:**
```javascript
async function getAvailableLanguages() {
  const languages = await apiCall('GET', '/api/tts/languages');
  console.log('Available languages:', languages);
  return languages;
}
```

---

#### 3. Set TTS Language
```bash
POST /api/tts/language
Content-Type: application/json

{
  "language": "ta"
}
```

**JavaScript Example:**
```javascript
async function setTTSLanguage(language) {
  const response = await apiCall('POST', '/api/tts/language', { language });
  console.log('TTS language set to:', language);
  return response;
}
```

---

#### 4. Test TTS
```bash
POST /api/tts/test
Content-Type: application/json

{
  "message": "System ready"
}
```

**JavaScript Example:**
```javascript
async function testTTS(message) {
  const response = await apiCall('POST', '/api/tts/test', { message });
  console.log('TTS test executed:', response);
  return response;
}
```

---

## 📡 WebSocket Input Handlers

### Mission Control Events

#### 1. Subscribe to Mission Status
```javascript
socket.emit('subscribe_mission_status');
```

**Response Event:**
```javascript
socket.on('mission_status_subscribed', (data) => {
  console.log('Subscription confirmed:', data);
});
```

---

#### 2. Get Mission Status (One-time)
```javascript
socket.emit('get_mission_status');
```

**Response Event:**
```javascript
socket.on('mission_status_response', (data) => {
  console.log('Current mission status:', data);
  // {
  //   "state": "executing",
  //   "current_waypoint": 2,
  //   "position": {...},
  //   "mode": "AUTO"
  // }
});
```

---

#### 3. Send Command
```javascript
socket.emit('send_command', {
  command: 'start',  // or 'stop', 'pause', 'resume'
  data: {}
});
```

**Response Event:**
```javascript
socket.on('command_response', (data) => {
  console.log('Command executed:', data);
  // {
  //   "success": true,
  //   "message": "Mission started",
  //   "result": {}
  // }
});
```

---

#### 4. Set GPS Failsafe Mode
```javascript
socket.emit('set_gps_failsafe_mode', {
  mode: 'strict'  // or 'disable', 'relax'
});
```

**Modes:**
- `disable` - Disable failsafe
- `relax` - Relaxed failsafe (high tolerance)
- `strict` - Strict failsafe (low tolerance)

**Response Event:**
```javascript
socket.on('failsafe_mode_changed', (data) => {
  console.log('Failsafe mode changed:', data);
  // {
  //   "new_mode": "strict",
  //   "reason": "User configured"
  // }
});
```

---

#### 5. Set Obstacle Detection
```javascript
socket.emit('set_obstacle_detection', {
  enabled: true
});
```

**Response Event:**
```javascript
socket.on('obstacle_detection_changed', (data) => {
  console.log('Obstacle detection status:', data);
  // { "enabled": true }
});
```

---

#### 6. Acknowledge Failsafe Condition
```javascript
socket.emit('failsafe_acknowledge');
```

**Response Event:**
```javascript
socket.on('failsafe_acknowledged', (data) => {
  console.log('Failsafe acknowledged:', data);
});
```

---

#### 7. Resume Mission After Failsafe
```javascript
socket.emit('failsafe_resume_mission');
```

**Response Event:**
```javascript
socket.on('failsafe_resumed', (data) => {
  console.log('Mission resumed after failsafe:', data);
});
```

---

#### 8. Restart Mission After Failsafe
```javascript
socket.emit('failsafe_restart_mission');
```

**Response Event:**
```javascript
socket.on('failsafe_restarted', (data) => {
  console.log('Mission restarted after failsafe:', data);
});
```

---

### Manual Control Events

#### 1. Manual Control
```javascript
socket.emit('manual_control', {
  throttle: 100,    // -100 to 100
  yaw: 0,           // -100 to 100
  forward: 50,      // -100 to 100
  strafe: 0         // -100 to 100
});
```

**Response Event:**
```javascript
socket.on('manual_control_error', (error) => {
  console.error('Manual control error:', error);
});
```

---

#### 2. Stop Manual Control
```javascript
socket.emit('stop_manual_control');
```

**Response Event:**
```javascript
socket.on('manual_control_stopped', (data) => {
  console.log('Manual control stopped:', data);
});
```

---

#### 3. Emergency Stop
```javascript
socket.emit('emergency_stop');
```

---

### RTK/GNSS Events

#### 1. Connect to NTRIP Caster
```javascript
socket.emit('connect_caster', {
  host: 'caster.example.com',
  port: 2101,
  mountpoint: 'mount_point',
  username: 'user',
  password: 'pass'
});
```

**Response Event:**
```javascript
socket.on('caster_status', (data) => {
  console.log('Caster status:', data);
  // {
  //   "connected": true,
  //   "message": "Connected to caster"
  // }
});
```

---

#### 2. Disconnect from Caster
```javascript
socket.emit('disconnect_caster');
```

---

#### 3. Start LoRa RTK Stream
```javascript
socket.emit('start_lora_rtk_stream', {
  frequency: 915000000,
  bandwidth: 125000,
  spreading_factor: 7
});
```

---

#### 4. Stop LoRa RTK Stream
```javascript
socket.emit('stop_lora_rtk_stream');
```

---

### System Events

#### 1. Connection
```javascript
socket.on('connect', () => {
  console.log('Connected to server');
});
```

---

#### 2. Disconnection
```javascript
socket.on('disconnect', () => {
  console.log('Disconnected from server');
});
```

---

#### 3. Ping (Keep-alive)
```javascript
socket.emit('ping');
```

**Response Event:**
```javascript
socket.on('pong', () => {
  console.log('Pong received');
});
```

---

#### 4. Request Mission Logs
```javascript
socket.emit('request_mission_logs');
```

---

#### 5. Request Rover Reconnect
```javascript
socket.emit('request_rover_reconnect');
```

**Response Event:**
```javascript
socket.on('rover_reconnect_ack', (data) => {
  console.log('Rover reconnection acknowledged:', data);
});
```

---

## 📊 WebSocket Output Events

### Mission Status Events

#### 1. Mission Status Update
```javascript
socket.on('mission_status', (data) => {
  console.log('Mission status:', data);
  // {
  //   "state": "executing",         // "idle", "executing", "paused", "completed", "failed"
  //   "current_waypoint": 2,
  //   "total_waypoints": 5,
  //   "position": {
  //     "lat": 37.7749,
  //     "lng": -122.4194,
  //     "alt": 12.5
  //   },
  //   "mode": "AUTO",               // "AUTO" or "MANUAL"
  //   "progress": 40,               // 0-100
  //   "speed": 2.5,                 // m/s
  //   "time_remaining": 1200        // seconds
  // }
});
```

---

#### 2. Mission Event
```javascript
socket.on('mission_event', (data) => {
  console.log('Mission event:', data);
  // {
  //   "event_type": "waypoint_reached",  // "waypoint_reached", "waypoint_skipped", "hold_started", "hold_completed"
  //   "waypoint_index": 2,
  //   "waypoint_data": {
  //     "lat": 37.7749,
  //     "lng": -122.4194,
  //     "alt": 10.0
  //   },
  //   "timestamp": "2026-02-24T10:30:45Z"
  // }
});
```

---

#### 3. Mission Status History
```javascript
socket.on('mission_status_history', (data) => {
  console.log('Mission history:', data);
  // {
  //   "completed_waypoints": [
  //     {
  //       "index": 0,
  //       "completed_at": "2026-02-24T10:20:00Z",
  //       "duration": 600
  //     }
  //   ]
  // }
});
```

---

### Failsafe Events

#### 1. Failsafe Mode Changed
```javascript
socket.on('failsafe_mode_changed', (data) => {
  console.log('Failsafe mode changed:', data);
  // {
  //   "new_mode": "strict",
  //   "reason": "GPS accuracy degraded"
  // }
});
```

---

#### 2. Failsafe Error
```javascript
socket.on('failsafe_error', (data) => {
  console.log('Failsafe error:', data);
  // {
  //   "error_message": "GPS signal lost",
  //   "error_code": "GPS_SIGNAL_LOST"
  // }
});
```

---

### Obstacle Detection Events

#### 1. Obstacle Detection Changed
```javascript
socket.on('obstacle_detection_changed', (data) => {
  console.log('Obstacle detection toggled:', data);
  // { "enabled": true }
});
```

---

#### 2. Obstacle Error
```javascript
socket.on('obstacle_error', (data) => {
  console.log('Obstacle detection error:', data);
  // {
  //   "error_message": "Sensor malfunction",
  //   "error_code": "SENSOR_ERROR"
  // }
});
```

---

### Telemetry Events

#### 1. Rover Data (Real-time Telemetry)
```javascript
socket.on('rover_data', (data) => {
  console.log('Rover telemetry:', data);
  // {
  //   "position": {
  //     "lat": 37.7749,
  //     "lng": -122.4194,
  //     "alt": 12.5
  //   },
  //   "velocity": {
  //     "x": 1.2,
  //     "y": 0.8,
  //     "z": 0.0
  //   },
  //   "speed": 2.5,                 // m/s
  //   "heading": 45.5,              // degrees
  //   "mode": "AUTO",
  //   "battery": {
  //     "voltage": 12.5,
  //     "current": 5.2,
  //     "percentage": 85
  //   },
  //   "timestamp": "2026-02-24T10:30:45Z"
  // }
});
```

---

#### 2. Telemetry Raw
```javascript
socket.on('telemetry', (data) => {
  console.log('Raw telemetry:', data);
});
```

---

### Connection Status Events

#### 1. Connection Status
```javascript
socket.on('connection_status', (data) => {
  console.log('Connection status:', data);
  // {
  //   "status": "connected",        // "connected", "disconnected", "reconnecting"
  //   "uptime": 3600,               // seconds
  //   "clients": 5
  // }
});
```

---

#### 2. Server Health
```javascript
socket.on('server_health', (data) => {
  console.log('Server health:', data);
  // {
  //   "cpu_usage": 25.5,
  //   "memory_usage": 45.2,
  //   "disk_usage": 60.0,
  //   "uptime": 86400,
  //   "status": "healthy"
  // }
});
```

---

### RTK Events

#### 1. RTK Status
```javascript
socket.on('rtk_status', (data) => {
  console.log('RTK status:', data);
  // {
  //   "ntrip_connected": true,
  //   "lora_connected": false,
  //   "rtk_active": true,
  //   "correction_age": 2.5,
  //   "accuracy_cm": 3.2,
  //   "satellites": 24
  // }
});
```

---

#### 2. NTRIP Caster Status
```javascript
socket.on('caster_status', (data) => {
  console.log('Caster status:', data);
  // {
  //   "connected": true,
  //   "host": "caster.example.com",
  //   "port": 2101,
  //   "message": "Connected"
  // }
});
```

---

## ⚙️ Configurable Parameters

### Mission Execution Parameters

#### 1. Waypoint Reached Threshold
```bash
POST /api/mission/config
{
  "waypoint_reached_threshold": 0.5
}
```
- **Type**: float (meters)
- **Default**: 0.5 m
- **Description**: Distance from waypoint to consider it reached

**JavaScript Example:**
```javascript
async function setWaypointThreshold(threshold) {
  return await apiCall('POST', '/api/mission/config', {
    waypoint_reached_threshold: threshold
  });
}
```

---

#### 2. Hold Duration at Waypoint
```bash
POST /api/mission/config
{
  "hold_duration": 5.0
}
```
- **Type**: float (seconds)
- **Default**: 5.0 seconds
- **Description**: Time to hold at each waypoint before moving to next

**JavaScript Example:**
```javascript
async function setHoldDuration(duration) {
  return await apiCall('POST', '/api/mission/config', {
    hold_duration: duration
  });
}
```

---

#### 3. Mission Timeout
```bash
POST /api/mission/config
{
  "mission_timeout": 3600.0
}
```
- **Type**: float (seconds)
- **Default**: 3000.0 seconds (50 minutes per waypoint)
- **Description**: Maximum time allowed to reach any waypoint before timeout

**JavaScript Example:**
```javascript
async function setMissionTimeout(timeout) {
  return await apiCall('POST', '/api/mission/config', {
    mission_timeout: timeout
  });
}
```

---

### GPS Failsafe Parameters

#### 1. GPS Accuracy Threshold
```bash
POST /api/mission/config
{
  "accuracy_threshold_mm": 100.0
}
```
- **Type**: float (millimeters)
- **Default**: 60.0 mm
- **Description**: GPS error threshold - suppress spray if accuracy exceeds this

**JavaScript Example:**
```javascript
async function setAccuracyThreshold(threshold) {
  return await apiCall('POST', '/api/mission/config', {
    accuracy_threshold_mm: threshold
  });
}
```

---

#### 2. Fallback Zone Timeout
```bash
POST /api/mission/config
{
  "fallback_zone_timeout_seconds": 60.0
}
```
- **Type**: float (seconds)
- **Default**: 30.0 seconds
- **Description**: Wait time in threshold zone before using GPS distance fallback

**JavaScript Example:**
```javascript
async function setFallbackZoneTimeout(timeout) {
  return await apiCall('POST', '/api/mission/config', {
    fallback_zone_timeout_seconds: timeout
  });
}
```

---

### Servo/Spray Parameters

#### 1. Servo Enabled
```bash
POST /api/mission/servo_config
{
  "servo_enabled": true
}
```
- **Type**: boolean
- **Default**: true
- **Description**: Enable/disable servo control

---

#### 2. Servo Channel
```bash
POST /api/mission/servo_config
{
  "servo_channel": 11
}
```
- **Type**: integer
- **Default**: 11
- **Description**: Pixhawk PWM channel for servo

---

#### 3. Servo PWM On
```bash
POST /api/mission/servo_config
{
  "servo_pwm_on": 1900
}
```
- **Type**: integer (microseconds)
- **Default**: 1900
- **Description**: PWM pulse width to activate servo (ON state)

---

#### 4. Servo PWM Off
```bash
POST /api/mission/servo_config
{
  "servo_pwm_off": 1100
}
```
- **Type**: integer (microseconds)
- **Default**: 1100
- **Description**: PWM pulse width to deactivate servo (OFF state)

---

#### 5. Servo Delay Before
```bash
POST /api/mission/servo_config
{
  "servo_delay_before": 0.5
}
```
- **Type**: float (seconds)
- **Default**: 0.5 seconds
- **Description**: Delay before activating servo at waypoint

---

#### 6. Servo Spray Duration
```bash
POST /api/mission/servo_config
{
  "servo_spray_duration": 2.0
}
```
- **Type**: float (seconds)
- **Default**: 2.0 seconds
- **Description**: Duration to keep servo activated

---

#### 7. Servo Delay After
```bash
POST /api/mission/servo_config
{
  "servo_delay_after": 0.5
}
```
- **Type**: float (seconds)
- **Default**: 0.5 seconds
- **Description**: Delay after deactivating servo before moving to next waypoint

---

### Obstacle Detection Parameters

#### 1. Warning Zone Configuration
```bash
POST /api/mission/config
{
  "warning_min_mm": 1500,
  "warning_max_mm": 2500
}
```
- **Type**: integer (millimeters)
- **Default Min**: 1200 mm
- **Default Max**: 2000 mm
- **Description**: Warning zone range for obstacle detection

**JavaScript Example:**
```javascript
async function setWarningZone(minMm, maxMm) {
  return await apiCall('POST', '/api/mission/config', {
    warning_min_mm: minMm,
    warning_max_mm: maxMm
  });
}
```

---

#### 2. Danger Zone Configuration
```bash
POST /api/mission/config
{
  "danger_min_mm": 600,
  "danger_max_mm": 1200
}
```
- **Type**: integer (millimeters)
- **Default Min**: 800 mm
- **Default Max**: 1000 mm
- **Description**: Danger zone range for obstacle detection

**JavaScript Example:**
```javascript
async function setDangerZone(minMm, maxMm) {
  return await apiCall('POST', '/api/mission/config', {
    danger_min_mm: minMm,
    danger_max_mm: maxMm
  });
}
```

---

#### 3. Obstacle Detection Enable/Disable
```bash
POST /api/mission/config
{
  "obstacle_detection_enabled": true
}
```
- **Type**: boolean
- **Default**: true
- **Description**: Enable/disable obstacle detection feature

---

## 🎯 Complete Usage Examples

### Example 1: Complete Mission Workflow
```javascript
async function runCompleteMission() {
  try {
    // 1. Configure obstacle zones
    await configureObstacleZones({
      warningMin: 1500,
      warningMax: 2500,
      dangerMin: 600,
      dangerMax: 1200
    });
    console.log('✓ Obstacle zones configured');

    // 2. Update mission parameters
    await updateMissionParameters({
      mission_timeout: 3600.0,
      accuracy_threshold_mm: 100.0,
      fallback_zone_timeout_seconds: 60.0,
      waypoint_reached_threshold: 0.5,
      hold_duration: 5.0
    });
    console.log('✓ Mission parameters updated');

    // 3. Configure servo
    await updateServoConfig({
      enabled: true,
      channel: 11,
      pwmOn: 1900,
      pwmOff: 1100,
      delayBefore: 0.5,
      sprayDuration: 2.0,
      delayAfter: 0.5
    });
    console.log('✓ Servo configured');

    // 4. Load mission with waypoints
    const waypoints = [
      { lat: 37.7749, lng: -122.4194, alt: 10.0 },
      { lat: 37.7750, lng: -122.4195, alt: 10.0 },
      { lat: 37.7751, lng: -122.4196, alt: 10.0 }
    ];
    
    await loadMission(waypoints);
    console.log('✓ Mission loaded');

    // 5. Subscribe to mission status
    socket.emit('subscribe_mission_status');
    console.log('✓ Subscribed to mission status');

    // 6. Listen for mission events
    socket.on('mission_status', (data) => {
      console.log('Mission Status:', data);
    });

    socket.on('mission_event', (data) => {
      console.log('Mission Event:', data);
    });

    // 7. Set GPS failsafe
    socket.emit('set_gps_failsafe_mode', { mode: 'strict' });
    console.log('✓ Failsafe mode set');

    // 8. Enable obstacle detection
    socket.emit('set_obstacle_detection', { enabled: true });
    console.log('✓ Obstacle detection enabled');

    // 9. Arm vehicle
    await armVehicle();
    console.log('✓ Vehicle armed');

    // 10. Start mission
    await startMission();
    console.log('✓ Mission started');

  } catch (error) {
    console.error('Mission error:', error);
  }
}
```

---

### Example 2: Real-time Mission Monitoring
```javascript
function setupMissionMonitoring() {
  // Subscribe to all mission events
  socket.emit('subscribe_mission_status');

  // Listen for status updates
  socket.on('mission_status', (data) => {
    updateUI({
      state: data.state,
      currentWaypoint: data.current_waypoint,
      progress: data.progress,
      position: data.position,
      speed: data.speed,
      timeRemaining: data.time_remaining
    });
  });

  // Listen for waypoint events
  socket.on('mission_event', (data) => {
    if (data.event_type === 'waypoint_reached') {
      console.log(`Waypoint ${data.waypoint_index} reached at ${data.timestamp}`);
      addNotification(`Reached waypoint ${data.waypoint_index}`);
    } else if (data.event_type === 'waypoint_skipped') {
      console.log(`Waypoint ${data.waypoint_index} skipped`);
      addNotification(`Skipped waypoint ${data.waypoint_index}`);
    }
  });

  // Listen for rover telemetry
  socket.on('rover_data', (data) => {
    updateMap({
      position: data.position,
      heading: data.heading,
      speed: data.speed,
      battery: data.battery
    });
  });

  // Listen for failsafe events
  socket.on('failsafe_mode_changed', (data) => {
    console.warn(`Failsafe mode changed: ${data.new_mode}`);
    addAlert(`Failsafe: ${data.reason}`);
  });

  // Listen for obstacle detection
  socket.on('obstacle_error', (data) => {
    addAlert(`Obstacle Error: ${data.error_message}`);
  });
}
```

---

### Example 3: Manual Control with Monitoring
```javascript
function setupManualControl() {
  // Listen for telemetry while in manual mode
  socket.on('rover_data', (data) => {
    console.log('Current Position:', data.position);
    console.log('Speed:', data.speed, 'm/s');
    console.log('Battery:', data.battery.percentage, '%');
  });

  // Send manual control commands
  function sendManualControl(controls) {
    socket.emit('manual_control', {
      throttle: controls.throttle,    // -100 to 100
      yaw: controls.yaw,              // -100 to 100
      forward: controls.forward,      // -100 to 100
      strafe: controls.strafe         // -100 to 100
    });
  }

  // Emergency stop
  function emergencyStop() {
    socket.emit('emergency_stop');
    socket.emit('stop_manual_control');
  }

  // Handle errors
  socket.on('manual_control_error', (error) => {
    console.error('Manual control error:', error);
  });
}
```

---

### Example 4: Failsafe Handling
```javascript
function setupFailsafeHandling() {
  // Listen for failsafe conditions
  socket.on('failsafe_mode_changed', (data) => {
    console.log('Failsafe activated:', data.new_mode);
    
    // Show alert to user
    showAlert({
      type: 'warning',
      title: 'Failsafe Activated',
      message: `GPS ${data.reason}`,
      duration: 5000
    });
  });

  // Listen for failsafe errors
  socket.on('failsafe_error', (data) => {
    console.error('Failsafe error:', data.error_message);
    
    // Show critical alert
    showAlert({
      type: 'error',
      title: 'Mission Failed',
      message: data.error_message,
      duration: 0  // Don't auto-dismiss
    });
  });

  // Handle failsafe acknowledgment
  function acknowledgFailsafe() {
    socket.emit('failsafe_acknowledge');
  }

  // Handle mission resume after failsafe
  function resumeAfterFailsafe() {
    socket.emit('failsafe_resume_mission');
  }

  // Handle mission restart after failsafe
  function restartAfterFailsafe() {
    socket.emit('failsafe_restart_mission');
  }
}
```

---

### Example 5: Configuration UI Helper
```javascript
class MissionConfigManager {
  async loadCurrentConfig() {
    return await apiCall('GET', '/api/mission/config');
  }

  async updateAllConfig(newConfig) {
    return await apiCall('POST', '/api/mission/config', newConfig);
  }

  async loadServoConfig() {
    return await apiCall('GET', '/api/mission/servo_config');
  }

  async updateServoConfig(servoConfig) {
    return await apiCall('POST', '/api/mission/servo_config', servoConfig);
  }

  async configureObstacles(zones) {
    return await apiCall('POST', '/api/mission/config', {
      warning_min_mm: zones.warningMin,
      warning_max_mm: zones.warningMax,
      danger_min_mm: zones.dangerMin,
      danger_max_mm: zones.dangerMax
    });
  }

  async setGPSFailsafeMode(mode) {
    // Via WebSocket
    socket.emit('set_gps_failsafe_mode', { mode });
  }

  getParameterDefaults() {
    return {
      mission_timeout: 3000.0,
      accuracy_threshold_mm: 60.0,
      fallback_zone_timeout_seconds: 30.0,
      waypoint_reached_threshold: 0.5,
      hold_duration: 5.0,
      warning_min_mm: 1200,
      warning_max_mm: 2000,
      danger_min_mm: 800,
      danger_max_mm: 1000
    };
  }

  validateConfig(config) {
    const errors = [];
    
    if (config.mission_timeout < 60) {
      errors.push('Mission timeout must be >= 60 seconds');
    }
    
    if (config.accuracy_threshold_mm < 10) {
      errors.push('Accuracy threshold must be >= 10 mm');
    }
    
    if (config.warning_max_mm <= config.warning_min_mm) {
      errors.push('Warning max must be > warning min');
    }
    
    if (config.danger_max_mm <= config.danger_min_mm) {
      errors.push('Danger max must be > danger min');
    }
    
    return {
      valid: errors.length === 0,
      errors
    };
  }
}
```

---

## 📝 Summary

This guide provides comprehensive documentation for frontend integration with the NRP Mission Controller backend:

| Category | Count |
|----------|-------|
| REST API Endpoints | 57 |
| WebSocket Input Handlers | 24 |
| WebSocket Output Events | 35 |
| Configurable Parameters | 17 |
| **Total Communication Points** | **116** |

### Quick Reference by Use Case:
- **Mission Planning**: Use `/api/mission/load_controller` endpoint
- **Mission Execution**: Use `/api/mission/start_controller` and WebSocket `mission_status` events
- **Real-time Monitoring**: Subscribe to `mission_status`, `rover_data`, `mission_event` events
- **Failsafe Management**: Handle `failsafe_mode_changed` events and use failsafe WebSocket handlers
- **Manual Control**: Use `manual_control` WebSocket event
- **Configuration**: Use POST `/api/mission/config` and `/api/mission/servo_config`

