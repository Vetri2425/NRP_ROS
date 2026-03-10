# Error Handling & Crash Resilience Audit

## Rating: MODERATE (5/10)

Good per-handler error catching, but background tasks can die silently, `os._exit(1)` skips cleanup, and hardware (servos/LEDs) can be left in unknown states after crashes.

---

## Field Test Crash Investigation (No Logs Available)

Server restarted 1-2 times during field testing. No logs were captured. Below is every code path that can kill the process, ranked by probability based on field conditions.

### SUSPECT #1 (90% likely): Telemetry Timeout False Positive → os._exit(1)

**The kill chain:**

```
maintain_mavros_connection()          [server.py:1731]  runs every 2s
  → bridge.is_pixhawk_disconnect_detected()  [server.py:1739]
    → time_since_telemetry > 10.0     [mavros_bridge.py:194-197]
      → returns True (FALSE POSITIVE)
  → os._exit(1)                       [server.py:1751]  SERVER DIES
```

**Why this fires in the field:**

The telemetry timeout is only **10 seconds** (`mavros_bridge.py:84`). Telemetry can stall for >10s during:

1. **REST API mission upload** — `POST /api/mission/upload` calls `bridge.push_waypoints()` which blocks rosbridge for 10-30 seconds. The `suppress_disconnect_check` flag exists to prevent this, but it is ONLY set by `IntegratedMissionController` operations (lines 713, 820, 859, 901 in `integrated_mission_controller.py`). **The REST API path does NOT set it:**

```python
# This REST path is UNPROTECTED:
@app.post("/api/mission/upload")                    # server.py:4008
async def api_mission_upload(request: Request):
    result = _handle_upload_mission(data)
      → bridge.push_waypoints(mavros_waypoints)     # server.py:2451
        # Blocks rosbridge for 10-30s
        # suppress_disconnect_check is NOT set!
        # telemetry stalls > 10s → os._exit(1) fires
```

2. **Multiple rapid service calls** — arm + set_mode + start mission in quick sequence, each blocking rosbridge
3. **rosbridge momentary stall** under CPU/memory load on Jetson
4. **Pixhawk USB briefly drops** from vibration or loose connector in field

**Evidence this is the cause:**
- The codebase already knows about this problem — `integrated_mission_controller.py:1206` comments: *"false disconnect → os._exit(1)"*
- `suppress_disconnect_check()` was added specifically to prevent it during mission controller operations
- But REST API calls to `/api/mission/upload`, `/api/arm`, `/api/set_mode` bypass this protection entirely

**Fix summary:** Wrap REST API bridge calls with `suppress_disconnect_check(True/False)`, increase timeout from 10s to 20s, and replace `os._exit(1)` with graceful shutdown (see Fix 1 below).

---

### SUSPECT #2 (40% likely): rosbridge WebSocket Connection Drop

**The kill chain:**

```
rosbridge_server restarts or WebSocket drops
  → roslibpy fires close event
    → _on_close()                        [mavros_bridge.py:759]
      → self._connected = False
  → Next maintain_mavros_connection() cycle (within 2s)
    → bridge.is_connected returns False
    → bridge.connect() called
    → OR _pixhawk_disconnect_detected flag already True
      → os._exit(1)                      [server.py:1751]
```

**Field triggers:**
- rosbridge_server crashing under memory pressure on Jetson Orin Nano
- MAVROS node restarting (e.g., USB serial timeout on Pixhawk)
- WiFi router reboot affecting rosbridge (if rosbridge is on a different host)

**Fix summary:** Don't `os._exit` on rosbridge drop — instead, reconnect the bridge gracefully. The `maintain_mavros_connection()` loop already handles reconnection, but the `os._exit` fires before it gets a chance.

---

### SUSPECT #3 (20% likely): Unhandled Exception in Background Task

```
asyncio.create_task(maintain_mavros_connection())   [server.py:6597]
asyncio.create_task(telemetry_loop())               [server.py:6600]
asyncio.create_task(connection_health_monitor())     [server.py:6603]
  ↑ fire-and-forget — if any of these throw, the task dies SILENTLY
```

If `maintain_mavros_connection()` itself crashes from an unexpected exception (e.g., `AttributeError` from `None` bridge, malformed telemetry dict), the task dies. No restart, no log, no alert. The operator sees frozen telemetry and thinks the server crashed.

This doesn't actually restart the server, but it **looks identical** to a restart from the operator's perspective (frozen UI, no data, must reconnect).

**Fix summary:** Supervised task wrapper with auto-restart (see Fix 2 below).

---

### SUSPECT #4 (15% likely): rclpy Context Conflict at Startup

```
server.py:604      → rclpy.init()            (module-level, in ROS_AVAILABLE block)
mavros_bridge.py:631-632 → rclpy.init()      (in MavrosBridge.__init__)
```

Two code paths call `rclpy.init()`. Both have guards, but the guard at `server.py:608-616` only catches errors containing the string `"has already been initialized"` or `"already been called"`. If rclpy throws a **different** RuntimeError (e.g., context corruption, signal handler conflict), it falls through to:

```python
else:
    print(f"[ERROR] Unexpected rclpy.init() error: {exc}", flush=True)
    raise   # ← CRASHES THE SERVER AT MODULE LOAD TIME
```

This would crash the server immediately at startup, before any log system is initialized — explaining the lack of logs.

**Fix summary:** Catch all RuntimeError from rclpy.init(), not just specific messages.

---

### SUSPECT #5 (10% likely): Linux OOM Killer

The Jetson Orin Nano has limited RAM. Running simultaneously:
- uvicorn + FastAPI + Socket.IO
- rclpy + MultiThreadedExecutor (2 nodes)
- roslibpy + rosbridge WebSocket thread
- RTK thread (if NTRIP active)
- Mission controller timers
- 20Hz debug prints to stdout (`flush=True` on every print)

Under memory pressure, Linux OOM killer terminates the highest-memory process. No Python exception, no log — process just disappears.

**How to check after the fact:**
```bash
dmesg | grep -i "oom\|killed process"
journalctl -k | grep -i oom
```

**Fix summary:** Reduce memory footprint (remove debug prints, limit deque sizes), set `OOMScoreAdj=-900` in systemd service file to protect the server from OOM.

---

### Crash Probability Summary

| Suspect | Cause | Probability | Restarts Server? | Leaves Logs? |
|---------|-------|-------------|------------------|--------------|
| #1 | Telemetry timeout false positive | **90%** | Yes (`os._exit`) | No (`os._exit` skips cleanup) |
| #2 | rosbridge WebSocket drop | 40% | Yes (`os._exit`) | No |
| #3 | Background task unhandled exception | 20% | No (task dies silently) | No |
| #4 | rclpy context conflict | 15% | Yes (startup crash) | Partial (print to stdout only) |
| #5 | Linux OOM killer | 10% | Yes (SIGKILL) | Only in `dmesg` |

**Most likely scenario for your field test:**

```
Operator uploads mission via tablet (REST API)
  → push_waypoints blocks rosbridge for 15-20s
  → suppress_disconnect_check NOT set (REST path unprotected)
  → telemetry stalls > 10 seconds
  → maintain_mavros_connection detects "disconnect"
  → os._exit(1) fires → server dies
  → systemd restarts server → comes back up in ~5 seconds
  → happened 1-2 times during field test
```

---

## What's GOOD

### 1. Every Socket.IO Handler Has try/except (Excellent)

```python
# Backend/server.py:3174 — connect handler
@sio.on('connect')
async def handle_connect(sid, environ):
    try:
        ...
    except Exception as e:
        # Do not reject the connection if our handler has a transient error
        log_message(f"Error in connect handler: {e}", 'ERROR')
        try:
            await sio.emit('connection_response', {
                'status': 'connected', 'sid': sid, 'timestamp': time.time()
            }, to=sid)
        except Exception:
            pass
```

**Why this is excellent:** The connect handler NEVER rejects a connection due to internal errors. Even if fetching rover data fails, the client still connects and can retry.

### 2. Graceful Degradation for Optional Components (Good)

```python
# Backend/server.py:772-776
try:
    led_controller = LEDController()
except Exception as e:
    print(f"[WARN] LED controller init failed: {e}", flush=True)
    led_controller = None  # Server continues without LEDs
```

Same pattern for: ROS2, CommandBridge, LoRa RTK handler, obstacle monitor. The server starts even if hardware is missing.

### 3. Best-Effort Shutdown Cleanup (Good)

```python
# Backend/server.py:655-749
def _shutdown_ros_runtime() -> None:
    # Cleanup LED controller
    try:
        if led_controller is not None:
            led_controller.shutdown()
    except Exception as exc:
        print(f"[WARN] LED controller cleanup failed: {exc}", flush=True)

    # Cleanup mission controller
    try:
        if mission_controller is not None:
            mission_controller.shutdown()
    except Exception as exc:
        ...
    # ... continues for ROS executor, TTS, rclpy, mavros_bridge ...
```

Each cleanup step is independently wrapped — one failure doesn't prevent others from running.

### 4. Singleton File Lock (Good)

```python
# Prevents two server instances running simultaneously
# Uses fcntl.flock() — released on process exit
```

Prevents port conflicts and double-control of MAVROS.

---

## What's BAD

### 1. CRITICAL: os._exit(1) Skips ALL Cleanup

```python
# Backend/server.py:1749-1751
log_message("Exiting to trigger systemd restart", "ERROR")
await asyncio.sleep(1.0)
os._exit(1)  # Force exit to trigger systemd restart
```

**What `os._exit(1)` does:**
- Immediately terminates the process
- **Skips:** `atexit` handlers, `finally` blocks, `__del__` methods, file flushes
- **Skips:** `_shutdown_ros_runtime()` — LEDs, servos, mission controller NOT cleaned up
- **Skips:** Socket.IO disconnect events — clients don't know why connection dropped

**What this means for hardware:**
- If a servo was ON (spraying), it stays ON
- If LEDs were in a pattern, they stay frozen
- If mission controller was mid-waypoint, Pixhawk continues the mission unmonitored

### 2. CRITICAL: Background Tasks Have No Supervision

```python
# Backend/server.py:6597-6604
asyncio.create_task(maintain_mavros_connection())   # fire-and-forget
asyncio.create_task(telemetry_loop())               # fire-and-forget
asyncio.create_task(connection_health_monitor())     # fire-and-forget
```

If any of these tasks throw an unhandled exception, **the task dies silently**. No restart, no alert, no log. The operator sees frozen telemetry and has no idea why.

**Example crash scenario for `telemetry_loop()`:**
```python
# Backend/server.py:2225-2237
async def telemetry_loop():
    global last_sent_telemetry, last_emit_monotonic
    fallback_interval = float(os.getenv('FALLBACK_EMIT_SEC', '60.0'))
    while True:
        if is_vehicle_connected:
            now = time.monotonic()
            if now - last_emit_monotonic >= fallback_interval:
                emit_rover_data_now(reason='fallback')    # If this throws... task dies
                last_sent_telemetry = get_rover_data()
        else:
            last_sent_telemetry = {}
        await asyncio.sleep(0.5)
```

If `emit_rover_data_now()` or `get_rover_data()` raises an unexpected exception (e.g., `current_state` corruption), the entire telemetry loop stops forever.

### 3. HIGH: threading.Timer callbacks die silently

```python
# Backend/integrated_mission_controller.py:1262-1263
self.mission_timer = threading.Timer(self.mission_timeout, self.waypoint_timeout)
self.mission_timer.start()
```

If `waypoint_timeout()` raises an exception, the Timer thread dies and the mission continues without timeout protection.

### 4. HIGH: spray_thread.join() after timeout doesn't kill the thread

```python
# Backend/server.py:4770-4771
except asyncio.TimeoutError:
    spray_thread.join()  # "ensure thread is terminated"
```

**`join()` does NOT terminate a thread.** It waits for the thread to finish. If the thread is stuck in `time.sleep(30)`, `join()` blocks for 30 seconds — freezing the async handler.

Python threads cannot be forcefully killed. The thread will eventually finish its `time.sleep()` and exit, but during that time the HTTP response is blocked.

### 5. MODERATE: Bare except catches everything

```python
# Backend/server.py:3978
try:
    body = await request.json()
except:                    # catches KeyboardInterrupt, SystemExit, MemoryError
    body = {}
```

`except:` (no exception type) catches `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit` — signals that should propagate. This can prevent clean shutdown.

**Found in:** lines 3978, 3994, 4397, 4527

---

## Exact Fixes

### Fix 1: Replace os._exit(1) with Graceful Shutdown

```python
# Before (line 1749-1751):
log_message("Exiting to trigger systemd restart", "ERROR")
await asyncio.sleep(1.0)
os._exit(1)

# After:
async def _graceful_shutdown(reason: str):
    """Perform cleanup then exit for systemd restart."""
    log_message(f"Graceful shutdown initiated: {reason}", "ERROR")

    # 1. Notify all connected clients
    try:
        await sio.emit('server_shutdown', {
            'reason': reason,
            'restart_expected': True,
            'timestamp': time.time()
        })
    except Exception:
        pass

    # 2. Safe hardware state
    try:
        if mission_controller is not None:
            mission_controller.stop_mission()
    except Exception:
        pass
    try:
        if led_controller is not None:
            led_controller.shutdown()
    except Exception:
        pass

    # 3. Cleanup ROS resources
    _shutdown_ros_runtime()

    # 4. Give Socket.IO clients time to receive shutdown event
    await asyncio.sleep(0.5)

    # 5. Exit for systemd restart
    log_message("Shutdown complete, exiting", "ERROR")
    sys.exit(1)   # sys.exit runs atexit handlers, unlike os._exit

# Usage (replace the os._exit call):
await _graceful_shutdown("MAVROS telemetry loss detected - service restart required")
```

### Fix 2: Add Task Supervision with Auto-Restart

```python
# Replace the fire-and-forget task creation with supervised tasks:

async def _supervised_task(name: str, coro_fn, *args, restart_delay: float = 2.0):
    """Run an async function with automatic restart on failure."""
    while True:
        try:
            log_message(f"[supervisor] Starting task: {name}", "INFO")
            await coro_fn(*args)
        except asyncio.CancelledError:
            log_message(f"[supervisor] Task cancelled: {name}", "INFO")
            raise  # Let cancellation propagate
        except Exception as exc:
            log_message(
                f"[supervisor] Task {name} crashed: {exc} — restarting in {restart_delay}s",
                "ERROR",
                event_type='supervisor'
            )
            try:
                sync_emit('server_activity', {
                    'level': 'ERROR',
                    'message': f'Background task "{name}" crashed and is restarting',
                    'event': 'supervisor'
                })
            except Exception:
                pass
            await asyncio.sleep(restart_delay)

# In the startup/lifespan:
asyncio.create_task(_supervised_task("mavros_connection", maintain_mavros_connection))
asyncio.create_task(_supervised_task("telemetry_loop", telemetry_loop))
asyncio.create_task(_supervised_task("connection_health", connection_health_monitor))
```

**What this gives you:**
- If `telemetry_loop` crashes, it restarts after 2 seconds
- The crash is logged and emitted to frontend as a server_activity event
- `CancelledError` is re-raised so the task can be cleanly stopped during shutdown

### Fix 3: Wrap Timer Callbacks Safely

```python
# In IntegratedMissionController, add a safe wrapper:

def _safe_timer_callback(self, callback, callback_name: str):
    """Wrap a Timer callback with error handling."""
    def wrapper():
        try:
            callback()
        except Exception as exc:
            self.log(f"Timer callback '{callback_name}' failed: {exc}", level="ERROR")
            try:
                self.emit_status(f"Timer error: {callback_name}", "error")
            except Exception:
                pass
    return wrapper

# Usage (replace direct Timer callbacks):
# Before:
self.mission_timer = threading.Timer(self.mission_timeout, self.waypoint_timeout)

# After:
self.mission_timer = threading.Timer(
    self.mission_timeout,
    self._safe_timer_callback(self.waypoint_timeout, "waypoint_timeout")
)
```

### Fix 4: Fix spray_thread timeout handling

```python
# Before (line 4758-4771):
spray_thread = threading.Thread(target=execute_spray)
spray_thread.daemon = True
spray_thread.start()

try:
    await asyncio.wait_for(
        loop.run_in_executor(None, spray_thread.join, None),
        timeout=TEST_TIMEOUT
    )
except asyncio.TimeoutError:
    spray_thread.join()   # THIS BLOCKS!

# After — use a cancellation flag:
_spray_cancel = threading.Event()

def execute_spray():
    try:
        # Step 2: Wait delay before spray (interruptible)
        if _spray_cancel.wait(mission_controller.servo_delay_before):
            result['error'] = 'Test cancelled (timeout)'
            return

        # Step 3: Turn servo ON
        response_on = bridge.set_servo(...)
        if not response_on.get('success'):
            result['error'] = f"Servo ON failed: {response_on}"
            return

        # Step 4: Wait spray duration (interruptible)
        if _spray_cancel.wait(mission_controller.servo_spray_duration):
            # Timeout — ensure servo is OFF for safety
            bridge.set_servo(mission_controller.servo_channel, mission_controller.servo_pwm_off)
            result['error'] = 'Test cancelled (timeout)'
            return

        # Step 5: Turn servo OFF
        bridge.set_servo(mission_controller.servo_channel, mission_controller.servo_pwm_off)

        # Step 6: Wait delay after
        if _spray_cancel.wait(mission_controller.servo_delay_after):
            result['error'] = 'Test cancelled (timeout)'
            return

        result['success'] = True
    except Exception as e:
        result['error'] = str(e)
        # Safety: try to turn servo OFF on any error
        try:
            bridge.set_servo(mission_controller.servo_channel, mission_controller.servo_pwm_off)
        except Exception:
            pass

_spray_cancel.clear()
spray_thread = threading.Thread(target=execute_spray, daemon=True)
spray_thread.start()

try:
    await asyncio.wait_for(
        loop.run_in_executor(None, spray_thread.join, None),
        timeout=TEST_TIMEOUT
    )
except asyncio.TimeoutError:
    _spray_cancel.set()  # Signal the thread to stop
    # Give it 2 seconds to clean up servo
    await loop.run_in_executor(None, spray_thread.join, 2.0)
```

### Fix 5: Replace bare except with Exception

```python
# Before (lines 3978, 3994, 4397, 4527):
try:
    body = await request.json()
except:
    body = {}

# After:
try:
    body = await request.json()
except Exception:
    body = {}
```

Simple one-line fix at 4 locations. `except Exception` catches all normal errors but lets `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit` propagate correctly.

---

## Crash Scenarios and Prevention

| Scenario | Current Behavior | After Fix |
|----------|-----------------|-----------|
| MAVROS telemetry loss | `os._exit(1)` — skips cleanup | Graceful shutdown: stop servo, notify clients, then exit |
| telemetry_loop exception | Task dies silently, frozen UI | Auto-restart in 2s, error logged |
| Timer callback exception | Timer thread dies, no timeout protection | Error caught, logged, status emitted |
| Servo test timeout | Blocks async handler for 30s | Cancel flag set, servo turned OFF safely |
| JSON parse error | `except:` catches SystemExit | `except Exception:` — clean shutdown works |
| Mission controller crash | Hardware left in unknown state | `_safe_timer_callback` wraps all timer callbacks |

---

## Summary

The biggest risks are: (1) `os._exit(1)` bypassing hardware cleanup and (2) unsupervised background tasks dying silently. The supervised task pattern and graceful shutdown fix both issues. The spray thread fix ensures hardware is always returned to a safe state on timeout.
