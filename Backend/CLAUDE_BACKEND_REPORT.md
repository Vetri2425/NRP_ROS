# NVROS Backend — Explanation for Claude

This document explains the NVROS backend architecture and connection logic. It's written to help an LLM like Claude or a human reviewer understand the communication protocols, connection logic, and main code paths used by the backend.

## Summary

- The backend is a Python Flask server (`Backend/server.py`) with real-time capabilities via Flask-SocketIO (eventlet). It exposes both REST endpoints and WebSocket events for the front-end and operators.
- The backend supports two primary vehicle connectivity modes:
  - MAVROS via rosbridge (WebSocket) with `roslibpy` — used when `rosbridge_server` is running and accessible.
  - Direct MAVLink connections via PyMAVLink (`mavlink_core.py`) — used in fallback or local/out-of-band scripts (servo manager, test harness).
- Additionally, ROS 2 native integration is supported via `rclpy` when the process runs within a ROS 2 environment; in this case `TelemetryBridge` and `CommandBridge` nodes are created to integrate `rclpy` subscriptions/services with Flask.
- The backend also handles RTK (NTRIP/RTCM) streaming and injection into MAVROS.

## High-level architecture

Components:
- Flask server: `Backend/server.py` — REST API, Socket.IO endpoints, telemetry merging and state management.
- MavrosBridge: `Backend/mavros_bridge.py` — rosbridge client via `roslibpy` that subscribes to MAVROS topics and calls MAVROS services.
- PyMAVLink abstraction: `Backend/mavlink_core.py` — a `BaseMavlinkCore` interface with `PyMavlinkCore` and placeholder `DllMavlinkCore`.
- ROS 2 Telemetry Node: `Backend/telemetry_node.py` — publishes telemetry to `/nrp/telemetry` used by `TelemetryBridge`.
- Servo Manager: `Backend/servo_manager` — uses ROS or MAVLink to send servo commands.
- Frontend (React): The front-end expects `socket.io` events and REST endpoints; they are found in `src/components` (outside this doc's scope).

The main runtime is the Flask process which starts the MavrosBridge, optionally initializes `rclpy` and spawns a MultiThreadedExecutor for ROS 2 nodes if available. Telemetry subscriptions are merged into a central `current_state` object; `socketio.emit` forwards the consolidated telemetry to connected clients.

## Main Communication Protocols

1) HTTP REST (Flask)
- Endpoints present in `Backend/server.py` include `/api/health`, `/api/arm`, `/api/set-mode`, `/api/servo/control`, `/api/mission/upload`, `/api/mission/download`, `/monitor`, `/api/nodes`, etc.
- REST endpoints accept JSON payloads and return JSON responses using `_http_success` / `_http_error` helpers.

2) WebSocket (Socket.IO)
- Uses `Flask-SocketIO` (eventlet) to push telemetry (`rover_data`) and status events (`connection_status`, `caster_status`, etc.).
- Events supported (some examples):
  - `connect` / `disconnect` (client connect/disconnect events)
  - `send_command` — triggers a command (e.g., ARM, SET_MODE) routed to MAVROS
  - `request_rover_reconnect` — instructs backend to drop MAVROS connection and reconnect
  - `connect_caster` / `disconnect_caster` — RTK caster control
  - `inject_mavros_telemetry` — test-only event to inject telemetry
  - Other commands/events: `mission_upload`, `request_mission_logs`, `ping` / `pong`

3) ROS 2 (native `rclpy`) and rosbridge (WebSocket via `roslibpy`)
- When ROS 2 environment is available (`rclpy` import success), the backend will create a native ROS 2 `TelemetryBridge` Node subscribing to `/nrp/telemetry` and a `CommandBridge` Node that talks to MAVROS services (`/mavros/set_mode`, `/mavros/cmd/arming`) via ROS service clients.
- Independent of `rclpy`, the backend also uses `MavrosBridge` which uses `roslibpy` to connect to `rosbridge_websocket` (a WebSocket server on the ROS host). `MavrosBridge` subscribes to MAVROS topics and provides higher-level functions (e.g., `arm()`, `set_mode()`, `push_waypoints()`, `send_rtcm()`, `set_servo()`).

4) MAVLink (PyMAVLink) — direct low-level link
- Abstraction provided in `mavlink_core.py`.
- Some parts of the project use `pymavlink` directly (servo manager, test scripts) to connect to a local/UDP/serial MAVLink endpoint.

5) RTK (NTRIP/RTCM) — caster streaming
- The backend can connect to an NTRIP caster and stream RTCM bytes. It receives RTCM and injects it into the rover by calling `MavrosBridge.send_rtcm()` which publishes to `/mavros/gps_rtk/send_rtcm`.

## Key Connection Logic & Code Snippets

1) MavrosBridge.connect (roslibpy WebSocket)
```python
# Backend/ mavros_bridge.py
self._ros = roslibpy.Ros(host=self.host, port=self.port)
# ... set callbacks and run
self._ros.run()
# wait for self._ros.is_connected True, then subscribe
self._setup_subscriptions()
```

2) Telemetry subscription & callbacks
- `mavros_bridge` subscribes to many topics (navsat, gps_raw, battery, imu, estimator, velocity, mission topics, rc/rc_out).
- Each topic handler (`_handle_navsat`, `_handle_gps_raw`, `_handle_battery`, `_handle_servo_output`, etc.) prepares a dictionary and calls `_broadcast_telem` which forwards the payload to registered callbacks (server uses `_handle_mavros_telemetry`).

3) Server subscribes to telemetry via MavrosBridge
```python
# Backend/server.py
mavros_bridge = MavrosBridge()
mavros_bridge.subscribe_telemetry(_handle_mavros_telemetry)
```

4) Telemetry merge and emit
- `_handle_mavros_telemetry(message)` merges payloads into a shared `current_state` (dataclass), updates fields like `rtk_fix_type`, `position`, `battery`, etc. It invokes `schedule_fast_emit()` to emit to connected clients with throttling.

5) Maintains reconnection loop
```python
# Backend/server.py
def maintain_mavros_connection():
    while True:
        try:
            bridge = _init_mavros_bridge()
            if bridge.is_connected: 
                socketio.sleep(2.0)
                continue
            bridge.connect(timeout=10)
        except Exception:
            socketio.sleep(2.0)
```
This runs in a background greenlet (via `eventlet.spawn`) to keep the rosbridge connection healthy.

6) RTK injection
```python
# Backend/server.py
def _inject_rtcm_to_mav(rtcm_bytes: bytes) -> bool:
    MAX_CHUNK = 512
    bridge = _require_vehicle_bridge()
    for i in range(0, len(rtcm_bytes), MAX_CHUNK):
        chunk = rtcm_bytes[i:i + MAX_CHUNK]
        bridge.send_rtcm(bytes(chunk))
```
This is called by the RTK thread that connects to the caster. The caster handshake & NTRIP protocol is handled via a socket and streamed bytes.

7) Servo Control via REST endpoint
```python
@app.post("/api/servo/control")
def api_servo_control():
    body = request.get_json()
    servo_id = body['servo_id']
    pwm_value = int(body.get('pwm') or angle_to_pwm(body.get('angle')))
    bridge = _require_vehicle_bridge()
    result = bridge.set_servo(int(servo_id), pwm_value)
```
`set_servo()` uses `send_command_long` with `MAV_CMD_DO_SET_SERVO` via `roslibpy`/MAVROS.

8) Arm/Set mode (via cmd/ros service)
- `CommandBridge` uses `SetMode` and `CommandBool` services via ROS when `rclpy` is available. If ROS 2 is not available, the MAVROS bridge `MavrosBridge` uses rosbridge service calls.

## Data Flow (textual diagram)

[Vehicle (Pixhawk)] <--- MAVLink ---> [Autopilot MAVROS] <--- ROS topics / services ---> [rosbridge WebSocket] <--- Websocket (roslibpy) ---> [Backend (Flask)] <--- Socket.IO/Web -> [Frontend]

Alternative: [Vehicle] <--- MAVLink ---> [Backend (PyMAVLink)] <--- (local) ---> [Backend bundles telemetry] <--- Socket.IO -> Frontend

RTK path: [Caster (NTRIP)] -> (TCP/socket) -> [Backend RTK thread] -> `bridge.send_rtcm()` -> `/mavros/gps_rtk/send_rtcm`

## Shared State & Threading

- `current_state` dataclass holds the merged telemetry.
- Protected by thread locks such as `mavros_telem_lock`, `mavros_bridge_lock`, and `rtk_bytes_lock`.
- The ROS executor spawns a `ros_thread` when `rclpy` is available (MultiThreadedExecutor). `roslibpy` subscriptions run in threads via their `on_ready` and callback mechanism.
- Emission throttling is implemented with `EMIT_MIN_INTERVAL` and a combination of eventlet spawn/later to reduce frontend update rate.

## Error Handling & Resilience

- The server is resilient to ROS availability — if `rclpy` is absent, a placeholder `CommandBridge` is used and ros-specific features are disabled.
- rosbridge connection is maintained and retried by `maintain_mavros_connection()`.
- The backend performs conservative parsing and ignores malformed telemetry data to avoid crashes.
- RTK stream can be connected by a client and will attempt to stream RTCM bytes to MAVROS; RTT/byte chunking prevents oversized messages.

## Observed Patterns & Implementation Notes

- CORS: Server sets CORS to `*` for all routes. In production, this should be tightened.
- Authentication: There is no built-in authentication or authorization in the HTTP/SocketIO events; externally protected networks or a reverse proxy are expected in production.
- Event names: `rover_data` contains a consolidated telemetry structure expected by the UI hooks.
- Fault Injection: `inject_mavros_telemetry` and similar dev endpoints help tests.

## Edge Cases & Known Problems

- ROS 2 context double initialization: server has safeguards for `rclpy.init()` being called multiple times.
- Telemetry merging: multiple sources (navsat vs gps_raw) must be handled carefully to avoid inconsistent data. The code uses high-frequency GPS raw for RTK quality and slower global_corrected for position.
- Mission controller was previously a node, but removed for rover rotation interactions; mission operations now go through MAVROS directly.

## Tips for Claude (or reviewer) when proposing changes

- To add authentication, focus on `server.py` near socketio setup and `before_request` handler. Avoid changing the message formats unless also updating the frontend.
- To support a new MAVLink backend (e.g. MAVSDK or a DLL), extend `mavlink_core.py` with a new adapter and use `_get_vehicle_bridge()` to return it.
- To add additional telemetry fields, update `mavros_bridge._setup_subscriptions()` and `server._handle_mavros_telemetry` merge logic and the `current_state` dataclass.

## Quick Code Jump Links (key entry points)
- `Backend/server.py` — main entrypoint, REST endpoints, Socket.IO handlers, telemetry management.
- `Backend/mavros_bridge.py` — rosbridge client and telemetry translation.
- `Backend/mavlink_core.py` — MAVLink abstraction.
- `Backend/telemetry_node.py` — ROS2 node publishing `/nrp/telemetry`.
- `Backend/servo_manager/ros_servo.py` — servo control via ROS or MAVLink.

## Final Notes

This document should allow a planner, operator, or LLM to reason about the backend's purpose, the communication patterns in use, and where to add or modify features safely without breaking compatibility with the front-end.
