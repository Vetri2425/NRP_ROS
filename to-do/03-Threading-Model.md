# Threading Model Audit

## Rating: MODERATE (5/10)

The threading architecture works in practice but has race conditions, no lock ordering, and unprotected shared state that can cause subtle data corruption or deadlocks under load.

---

## Current Thread Map

```
MAIN THREAD (uvicorn / asyncio event loop)
  |
  |-- FastAPI HTTP handlers (some sync = auto-threadpool)
  |-- Socket.IO async handlers
  |-- Background tasks:
  |     maintain_mavros_connection()
  |     telemetry_loop()
  |     connection_health_monitor()
  |
DAEMON THREADS:
  |
  |-- [ROS2 Thread] rclpy MultiThreadedExecutor spin
  |     Runs: TelemetryBridge, CommandBridge nodes
  |     Calls: _merge_ros2_telemetry() -> schedule_fast_emit()
  |
  |-- [MavrosBridge rclpy Thread] rclpy spin for direct service clients
  |     Runs: arm(), set_mode(), push_waypoints() service calls
  |
  |-- [roslibpy Thread] rosbridge WebSocket internal thread
  |     Runs: telemetry callbacks -> _handle_mavros_telemetry()
  |
  |-- [RTK Thread] rtk_worker() NTRIP socket streaming
  |     Calls: sync_emit(), _inject_rtcm_to_mav()
  |
  |-- [Mission Controller Timers] threading.Timer instances
  |     hold_timer, mission_timer, position_check_timer, rtk_monitor_timer
  |     Calls: sync_emit() via status_callback
  |
  |-- [Status Logging Thread] 2Hz periodic status logging
  |
  |-- [FastAPI Threadpool] auto-created for sync def routes
```

---

## What's GOOD

### 1. All Background Threads are Daemon (Excellent)

```python
# Backend/server.py:639-641
ros_thread = threading.Thread(target=_ros_executor_spin)
ros_thread.daemon = True
ros_thread.start()
```

All threads use `daemon=True`. When the main process exits, daemon threads are killed automatically. This prevents zombie threads keeping the process alive.

### 2. sync_emit Bridge Pattern (Excellent)

```python
# Backend/server.py:133-139
def sync_emit(event, data=None, to=None, room=None, namespace=None):
    loop = _main_loop
    if loop is None or loop.is_closed():
        return
    coro = sio.emit(event, data, to=to, room=room, namespace=namespace)
    asyncio.run_coroutine_threadsafe(coro, loop)
```

**Why this is correct:** `asyncio.run_coroutine_threadsafe()` is the only safe way to schedule a coroutine from a non-async thread. All background threads (ROS2, RTK, mission controller) use this pattern to emit Socket.IO events.

### 3. Telemetry Lock Consistently Used (Good)

```python
# Backend/server.py:761
mavros_telem_lock = threading.Lock()

# Used consistently in ~25+ places:
with mavros_telem_lock:
    current_state.position = Position(lat=float(lat), lng=float(lon))
    current_state.last_update = now
```

The telemetry state is modified from multiple threads (ROS2 callback, MAVROS callback, command handlers). The lock prevents torn reads/writes.

### 4. Mission Controller Uses RLock (Good)

```python
# Backend/integrated_mission_controller.py:94
self.lock = threading.RLock()  # Reentrant lock
```

`RLock` allows the same thread to acquire the lock multiple times without deadlocking. This is important because mission controller methods call each other internally.

### 5. Singleton Lock via fcntl (Good)

```python
# Backend/server.py:44-46, 738-749
import fcntl
# File lock prevents two server instances running simultaneously
```

Prevents accidental double-start which would cause port conflicts and MAVROS resource contention.

---

## What's BAD

### 1. CRITICAL: _client_sessions has NO lock

```python
# Backend/server.py:3252
_client_sessions = {}    # <-- plain dict, NO lock

# Written from async handlers:
@sio.on('ping')
async def handle_ping(sid, data=None):
    _client_sessions[client_id] = {...}       # line 3262
    session['last_ping'] = current_time        # line 3270

# Read + Written from async background task:
async def connection_health_monitor():
    for client_id, session in list(_client_sessions.items()):    # line 2248
        ...
    _client_sessions.pop(client_id, None)                        # line 2267

# Written from disconnect handler:
@sio.on('disconnect')
async def handle_disconnect(sid):
    _client_sessions.pop(client_id, None)      # line 3248
```

**Risk:** In a single-threaded asyncio context, dict operations between `await` points are safe. But `connection_health_monitor` iterates the dict and pops items in the same loop, while `handle_disconnect` can pop concurrently between awaits. With CPython's GIL this is unlikely to crash, but the logic can skip entries or double-pop.

### 2. HIGH: Global flags modified without locks

```python
# Backend/server.py:3307 — no lock
is_vehicle_connected = False

# Backend/server.py:1782 — no lock
is_vehicle_connected = False

# Backend/server.py:2810 — no lock
rtk_running = True

# Backend/server.py:2762 — no lock
rtk_running = False
```

These booleans are read from multiple threads (telemetry_loop, health_monitor, RTK worker) and written from async handlers. While Python's GIL makes single-assignment atomic, **compound check-then-act** is not safe:

```python
# RTK worker thread:
while rtk_running:          # reads True
    data = sock.recv(4096)  # blocks
    # Meanwhile, async handler sets rtk_running = False
    # Worker doesn't see it until next iteration
```

This is a design issue more than a crash risk — the RTK worker may process one extra chunk after stop is requested.

### 3. HIGH: No Lock Ordering Protocol

The application has 7+ locks:

```
mavros_bridge_lock       (server.py:760)
mavros_telem_lock        (server.py:761)
mission_upload_lock      (server.py:855)
mission_download_lock    (server.py:856)
_emit_lock               (server.py:873)
_activity_log_lock       (server.py:885)
rtk_bytes_lock           (server.py:2689)
CommandBridge._lock      (server.py:552)
MavrosBridge._lock       (mavros_bridge.py:71)
IntegratedMissionController.lock  (integrated_mission_controller.py:94)
```

**No documented acquisition order.** If thread A acquires `mavros_telem_lock` then `_emit_lock`, and thread B acquires `_emit_lock` then `mavros_telem_lock`, a deadlock occurs.

**Current risk paths:**
```
_handle_mavros_telemetry()
  -> with mavros_telem_lock:       # acquires lock 1
      -> schedule_fast_emit()
          -> with _emit_lock:      # acquires lock 2  (order: telem -> emit)

emit_rover_data_now()
  -> sync_emit()                   # no lock held (OK)

_emit_timer_cb()
  -> with _emit_lock:              # acquires lock 2
      -> _emit_timer = None
  -> emit_rover_data_now()         # no lock held (OK)
```

Currently the order is consistent (telem -> emit), but this is by accident, not by design. Adding new code that reverses the order would cause a deadlock.

### 4. MODERATE: schedule_fast_emit calls loop.call_later from any thread

```python
# Backend/server.py:1636-1638
with _emit_lock:
    if _emit_timer is None:
        _emit_timer = _main_loop.call_later(delay, _emit_timer_cb)
```

`loop.call_later()` is **not thread-safe** per asyncio documentation. It should be `loop.call_soon_threadsafe()` wrapping a function that does `call_later`. In practice, CPython's GIL often makes this work, but it's technically a race condition.

### 5. MODERATE: Mission controller Timer callbacks run on Timer threads

```python
# Backend/integrated_mission_controller.py:1262-1263
self.mission_timer = threading.Timer(self.mission_timeout, self.waypoint_timeout)
self.mission_timer.start()
```

`waypoint_timeout()` runs on the Timer's thread. If it calls `sync_emit()` (which it does via the status callback), that's fine. But if it accesses `current_state` without `mavros_telem_lock`, it's a race condition.

---

## Exact Fixes

### Fix 1: Add lock to _client_sessions

```python
# Add at module level (near line 3252):
_client_sessions_lock = threading.Lock()
_client_sessions = {}

# In handle_ping (line 3255):
async def handle_ping(sid, data=None):
    client_id = sid
    current_time = time.time()
    with _client_sessions_lock:
        if client_id not in _client_sessions:
            _client_sessions[client_id] = {
                'connected_at': current_time,
                'last_ping': current_time,
                'ping_count': 0,
                'missed_pings': 0
            }
        session = _client_sessions[client_id]
        session['last_ping'] = current_time
        session['ping_count'] += 1
        ping_interval = current_time - session.get('last_ping_response', current_time)
    # ... rest unchanged, emit outside the lock ...

# In handle_disconnect (line 3237):
async def handle_disconnect(sid):
    with _client_sessions_lock:
        _client_sessions.pop(sid, None)

# In connection_health_monitor (line 2240):
async def connection_health_monitor():
    while True:
        try:
            current_time = time.time()
            with _client_sessions_lock:
                snapshot = dict(_client_sessions)  # snapshot under lock
            # iterate snapshot outside lock
            for client_id, session in snapshot.items():
                ...
            # cleanup
            with _client_sessions_lock:
                for client_id in list(_client_sessions.keys()):
                    if current_time - _client_sessions[client_id].get('last_ping', current_time) > 300:
                        _client_sessions.pop(client_id, None)
```

### Fix 2: Use threading.Event for rtk_running instead of bare bool

```python
# Replace (near line 2687):
# Before:
rtk_running = False

# After:
_rtk_stop_event = threading.Event()  # Set = stop requested

# In handle_connect_caster (line 2745):
# Before:
rtk_running = True
# After:
_rtk_stop_event.clear()

# Before:
rtk_running = False
# After:
_rtk_stop_event.set()

# In rtk_worker (line 2904):
# Before:
while rtk_running:
# After:
while not _rtk_stop_event.is_set():
```

**Why:** `threading.Event` is designed for cross-thread signaling and is thread-safe by design.

### Fix 3: Fix schedule_fast_emit thread safety

```python
# Before (line 1636-1638):
with _emit_lock:
    if _emit_timer is None:
        _emit_timer = _main_loop.call_later(delay, _emit_timer_cb)

# After:
def _schedule_timer(delay):
    """Must be called from the event loop thread."""
    global _emit_timer
    with _emit_lock:
        if _emit_timer is None:
            _emit_timer = _main_loop.call_later(delay, _emit_timer_cb)

# In schedule_fast_emit():
def schedule_fast_emit():
    global _emit_timer
    now = time.monotonic()
    elapsed = now - last_emit_monotonic
    if elapsed >= EMIT_MIN_INTERVAL:
        emit_rover_data_now(reason='realtime')
        return
    delay = EMIT_MIN_INTERVAL - elapsed
    loop = _main_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(_schedule_timer, delay)
```

### Fix 4: Document lock ordering

Add a comment block at the top of server.py near the lock definitions:

```python
# ============================================================================
# LOCK ORDERING PROTOCOL
# ============================================================================
# To prevent deadlocks, locks MUST be acquired in this order:
#
#   1. mavros_bridge_lock       (outermost — connection management)
#   2. mavros_telem_lock        (telemetry state updates)
#   3. _emit_lock               (emit throttling)
#   4. _activity_log_lock       (activity logging)
#   5. mission_upload_lock      (mission operations)
#   6. mission_download_lock    (mission operations)
#   7. rtk_bytes_lock           (RTK byte counter)
#   8. _client_sessions_lock    (client tracking)
#
# NEVER acquire a lower-numbered lock while holding a higher-numbered one.
# ============================================================================
```

---

## Summary

The threading model is functional but fragile. The most important fixes are:
1. Add lock to `_client_sessions` (prevents race condition)
2. Use `threading.Event` for stop signals (cleaner than bare bools)
3. Fix `call_later` thread safety (prevents rare corruption)
4. Document lock ordering (prevents future deadlocks)

None of these are causing crashes today, but under concurrent load (3 clients sending commands + telemetry flowing) they become real risks.
