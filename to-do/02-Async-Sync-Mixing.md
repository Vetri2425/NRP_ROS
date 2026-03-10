# Async / Sync Mixing Audit

## Rating: VERY POOR (3/10)

This is the **#1 crash and freeze risk** in the entire application. Blocking synchronous calls inside the async event loop freeze ALL clients (WebSocket telemetry, HTTP responses, ping/pong) for 5-10 seconds per operation.

---

## How FastAPI Handles sync vs async

```
async def handler():     -->  Runs DIRECTLY on the event loop
                              If it blocks, EVERYTHING freezes

def handler():           -->  FastAPI auto-wraps in run_in_executor()
                              Runs in a threadpool, loop stays free
```

**Critical rule:** If a function is `async def`, it MUST NOT call blocking code directly. If it does, use `await loop.run_in_executor(None, blocking_fn)`.

---

## What's GOOD (Excellent patterns found)

### 1. Failsafe restart uses run_in_executor correctly

```python
# Backend/server.py:3838-3841
async def handle_failsafe_restart_mission(sid, data=None):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, mission_controller.stop_mission)
    await loop.run_in_executor(None, mission_controller.start_mission)
```

**Why this is correct:** `stop_mission()` and `start_mission()` are blocking (they acquire locks, call MAVROS services). Wrapping in `run_in_executor` offloads them to a thread, keeping the event loop free.

### 2. Servo test uses thread + wait_for

```python
# Backend/server.py:4758-4768
spray_thread = threading.Thread(target=execute_spray)
spray_thread.daemon = True
spray_thread.start()

await asyncio.wait_for(
    loop.run_in_executor(None, spray_thread.join, None),
    timeout=TEST_TIMEOUT
)
```

**Why this is correct:** Long-running servo test (up to 60s of `time.sleep`) runs in a separate thread, with async timeout supervision.

### 3. Sync REST routes auto-offloaded by FastAPI

```python
# Backend/server.py:4348 — sync def
@app.post("/api/mission/start")
def api_mission_start():          # <-- sync def = auto threadpool
    ok, err = _publish_controller_cmd_or_error(...)
    ...
```

**Why this works:** FastAPI automatically runs `def` (non-async) route handlers in a threadpool via `run_in_executor`. So these blocking calls don't freeze the loop. **However**, this only applies to FastAPI HTTP routes, NOT to Socket.IO handlers.

---

## What's BAD (Event Loop Blocking)

### 1. CRITICAL: async Socket.IO handlers calling blocking code directly

```python
# Backend/server.py:3377-3435
@sio.on('send_command')
async def handle_command(sid, data, ack_callback=None):
    _require_vehicle_bridge()          # may block (bridge.connect)
    ...
    result = handler(data)             # calls _handle_arm_disarm, _handle_set_mode, etc.
```

**The handlers called here are ALL blocking:**

```python
# _handle_arm_disarm (line 2291) calls:
command_bridge.arm(value=arm)
#   which calls _call_service() (line 556) which does:
#     client.wait_for_service(timeout_sec=timeout)  # BLOCKS up to 5s
#     while time.time() < deadline:
#         time.sleep(0.01)                           # BLOCKS in polling loop

# _handle_upload_mission (line 2410) calls:
bridge.push_waypoints(mavros_waypoints)              # BLOCKS: ROS service call

# _handle_set_mode (line 2357) calls:
command_bridge.set_mode(mode=target_mode)             # BLOCKS up to 5s

# _handle_goto (line 2390) calls:
bridge.send_global_position_target(...)               # BLOCKS: rosbridge publish
```

**Impact:** When an operator presses "ARM" on the UI:
1. `handle_command` is async, runs on the event loop
2. `_handle_arm_disarm()` blocks for up to 5 seconds
3. During those 5 seconds: ALL other clients get no telemetry, no pong responses, no HTTP responses
4. Socket.IO clients may disconnect due to missed pings

### 2. CRITICAL: async mission_upload handler blocks

```python
# Backend/server.py:2625-2653
@sio.on("mission_upload")
async def on_mission_upload(sid, data):
    result = _handle_upload_mission(data)   # BLOCKS: push_waypoints is ROS service call
```

**Impact:** Mission upload can take 10-30 seconds for large missions. The entire server freezes during this time.

### 3. MODERATE: async REST handlers calling blocking code

```python
# Backend/server.py:3974-3987
@app.post("/api/arm")
async def api_arm_vehicle(request: Request):     # <-- async def
    body = await request.json()
    result = _handle_arm_disarm({'arm': arm_value})  # BLOCKS 5s
```

**Why async def is worse than def here:** If this were `def api_arm_vehicle`, FastAPI would auto-run it in a threadpool. But since it's `async def` (needed for `await request.json()`), the blocking `_handle_arm_disarm()` runs directly on the event loop.

**Same problem in:**
- `api_set_mode` (line 3990) — async, calls blocking `_handle_set_mode`
- `api_mission_upload` (line 4008) — async, calls blocking `_handle_upload_mission`
- `api_mission_set_current` (line 4054) — async, calls blocking bridge

### 4. maintain_mavros_connection calls blocking connect

```python
# Backend/server.py:1731-1769
async def maintain_mavros_connection():
    while True:
        bridge = _init_mavros_bridge()        # acquires lock, OK
        bridge.connect(timeout=10.0)          # BLOCKS up to 10 seconds!
```

**Impact:** During initial connection or reconnection, the event loop is frozen for up to 10 seconds.

---

## Danger Map: Which handlers block the loop

| Handler | Type | Blocking Call | Duration | Risk |
|---------|------|--------------|----------|------|
| `handle_command` | SIO async | `_handle_arm_disarm()` | 5s | CRITICAL |
| `handle_command` | SIO async | `_handle_set_mode()` | 5s | CRITICAL |
| `handle_command` | SIO async | `_handle_upload_mission()` | 10-30s | CRITICAL |
| `handle_command` | SIO async | `_handle_goto()` | 2s | HIGH |
| `on_mission_upload` | SIO async | `_handle_upload_mission()` | 10-30s | CRITICAL |
| `api_arm_vehicle` | HTTP async | `_handle_arm_disarm()` | 5s | HIGH |
| `api_set_mode` | HTTP async | `_handle_set_mode()` | 5s | HIGH |
| `api_mission_upload` | HTTP async | `_handle_upload_mission()` | 10-30s | HIGH |
| `maintain_mavros_connection` | Task async | `bridge.connect()` | 10s | HIGH |
| `api_mission_start` | HTTP sync def | `_publish_controller_cmd` | <1s | LOW (auto threadpool) |
| `api_mission_stop` | HTTP sync def | `_publish_controller_cmd` | <1s | LOW (auto threadpool) |
| `api_mission_download` | HTTP sync def | `download_mission_from_vehicle` | 5-15s | LOW (auto threadpool) |

---

## Exact Fixes

### Fix 1: Wrap all blocking calls in Socket.IO handlers with run_in_executor

**Current `handle_command` (line 3377):**
```python
@sio.on('send_command')
async def handle_command(sid, data, ack_callback=None):
    try:
        _require_vehicle_bridge()
    except Exception as exc:
        ...
        return

    command_type = data.get('command')
    handler = COMMAND_HANDLERS.get(command_type)
    if not handler:
        ...
        return

    try:
        result = handler(data)           # <-- BLOCKS THE LOOP
        ...
```

**Fixed `handle_command`:**
```python
@sio.on('send_command')
async def handle_command(sid, data, ack_callback=None):
    try:
        _require_vehicle_bridge()
    except Exception as exc:
        log_message("Command rejected - vehicle not connected", "ERROR", event_type='ui_request')
        payload = {'status': 'error', 'message': str(exc), 'acked': True}
        if ack_callback:
            ack_callback(payload)
        else:
            await sio.emit('command_response', payload, to=sid)
        return

    command_type = data.get('command')
    handler = COMMAND_HANDLERS.get(command_type)
    if not handler:
        payload = {'status': 'error', 'message': f'Unknown command: {command_type}', 'acked': True}
        if ack_callback:
            ack_callback(payload)
        else:
            await sio.emit('command_response', payload, to=sid)
        return

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, handler, data)   # <-- NON-BLOCKING
        # ... rest unchanged ...
```

### Fix 2: Wrap mission_upload Socket.IO handler

**Current (line 2625):**
```python
@sio.on("mission_upload")
async def on_mission_upload(sid, data):
    try:
        result = _handle_upload_mission(data)     # BLOCKS
```

**Fixed:**
```python
@sio.on("mission_upload")
async def on_mission_upload(sid, data):
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _handle_upload_mission, data)  # NON-BLOCKING
```

### Fix 3: Fix async REST routes that call blocking code

**Pattern — for every `async def` route that calls blocking code, either:**

**Option A: Make it sync (let FastAPI auto-threadpool):**
```python
# Before (line 3974):
@app.post("/api/arm")
async def api_arm_vehicle(request: Request):
    body = await request.json()
    result = _handle_arm_disarm({'arm': arm_value})

# After — split into body parsing + sync handler:
@app.post("/api/arm")
async def api_arm_vehicle(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    arm_value = bool(body.get('value', body.get('arm', True)))

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, _handle_arm_disarm, {'arm': arm_value}
        )
        message = result.get('message') if isinstance(result, dict) else None
        return _http_success(message or "Arm command dispatched")
    except Exception as exc:
        log_message(f"/api/arm error: {exc}", "ERROR")
        return _http_error(str(exc), 500)
```

**Apply same pattern to:**
- `api_set_mode` (line 3990)
- `api_mission_upload` (line 4008)
- `api_mission_set_current` (line 4054)

### Fix 4: Fix maintain_mavros_connection blocking connect

**Current (line 1731):**
```python
async def maintain_mavros_connection():
    while True:
        ...
        bridge.connect(timeout=10.0)    # BLOCKS 10s
```

**Fixed:**
```python
async def maintain_mavros_connection():
    loop = asyncio.get_event_loop()
    while True:
        try:
            bridge = await loop.run_in_executor(None, _init_mavros_bridge)
            if bridge.is_connected:
                ...
                await asyncio.sleep(2.0)
                continue

            now = time.time()
            if now - mavros_connection_last_attempt < 1.0:
                await asyncio.sleep(1.0)
                continue

            mavros_connection_last_attempt = now
            connect_timeout = float(os.getenv("MAVROS_CONNECT_TIMEOUT", "10"))
            await loop.run_in_executor(None, bridge.connect, connect_timeout)
            log_message("MAVROS bridge connected", "SUCCESS")
            ...
```

### Fix 5: Create a shared executor for heavy operations (optional improvement)

```python
# At module level, after imports:
from concurrent.futures import ThreadPoolExecutor

# Dedicated pool for MAVROS operations (prevents threadpool exhaustion)
_mavros_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="mavros")

# Usage in handlers:
result = await loop.run_in_executor(_mavros_executor, handler, data)
```

**Why:** The default executor has limited threads. If 3 clients send commands simultaneously, they share the pool with FastAPI's auto-threadpool sync routes. A dedicated executor prevents starvation.

---

## Summary

The core issue is simple: **blocking ROS/MAVROS service calls run directly on the async event loop** in ~80% of handlers. The fix is consistently wrapping them with `run_in_executor`. Two handlers already do this correctly (`failsafe_restart_mission`, servo test) — the same pattern must be applied everywhere.

**After fixing:** The event loop stays responsive during all MAVROS operations. Telemetry continues streaming, pings are answered, and HTTP requests are served even while arming, uploading missions, or connecting.
