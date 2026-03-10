# NRP_ROS Production Improvements — Status & Scorecard

**Last verified:** 2026-03-09 against actual codebase
**Status:** Partially implemented — 3 of 6 tasks complete

---

## Overall Scores

| Category | Score | Notes |
|----------|-------|-------|
| **Graceful Shutdown** | 9/10 | Lifespan implemented, shutdown handler wired, signal handlers still unused |
| **Error Handling** | 5/10 | 42 silent except:pass in server.py + 25 in backend modules = **67 total** |
| **Logging (server.py)** | 9/10 | `logging` module fully integrated, `log_message()` uses logger, only 7 residual print() (TTS announcements) |
| **Logging (backend modules)** | 2/10 | 184 print() calls across modules, only beacon.py + lora_rtk_handler.py use logging |
| **Health Monitoring** | 3/10 | `/api/ping` exists, no `/api/health/detailed` |
| **Input Validation** | 1/10 | 0 Pydantic models, all endpoints accept raw dicts |
| **Thread Safety** | 7/10 | 14 locks across codebase, async/sync properly handled |

---

## Task Status

### Task 1: Graceful Shutdown + Lifespan Migration — DONE
**Was:** No shutdown handler, deprecated `@app.on_event("startup")`
**Now:**
- FastAPI lifespan context manager at lines 114-163 with `@asynccontextmanager`
- `app = FastAPI(lifespan=lifespan)` at line 167
- Shutdown calls `_shutdown_ros_runtime()` at line 161
- `@app.on_event("startup")` fully removed
- **Remaining gap:** `signal` and `atexit` imported (lines 50-51) but never registered — uvicorn handles SIGTERM/SIGINT so this is acceptable for now

---

### Task 2: Fix Silent Exception Handlers — NOT DONE
**Current count:** 67 silent `except: pass` blocks total
- **server.py:** 42 blocks
- **Backend modules:** 25 blocks (beacon: 5, mavros_bridge: 4, telemetry_node: 4, lora_receiver_usb: 4, led_controller: 2, tts: 2, others: 1 each)

**Priority fixes still needed:**
- Mission-critical paths in server.py (mission start/stop, arm/disarm handlers)
- Socket.IO event handlers
- Any bare `except:` (should be `except Exception as e:`)

---

### Task 3: Replace print() with Structured Logging — PARTIAL (server.py done, modules not)

**server.py — DONE:**
- `logging.basicConfig()` at lines 25-29
- `logger = logging.getLogger('nrp_ros')` at line 30
- `log_message()` function uses `logger.debug/info/warning/error/critical` (lines 323-333)
- Only 7 residual `print()` calls remaining (all TTS voice announcements — acceptable)

**Backend modules — NOT DONE (184 print() calls):**

| File | print() | logging | Status |
|------|---------|---------|--------|
| ultrasonic_sensor.py | 75 | 0 | Diagnostic script, low priority |
| lora_receiver_usb.py | 56 | 0 | Needs logging |
| mavros_bridge.py | 30 | 0 | Needs logging |
| tts.py | 8 | 0 | Needs logging |
| obstacle_monitor.py | 6 | 0 | Needs logging |
| ultrasonic_watch.py | 4 | 0 | Low priority |
| integrated_mission_controller.py | 2 | 0 | Needs logging |
| led_controller.py | 1 | 0 | Minor |
| manual_control_handler.py | 1 | 0 | Minor |
| gps_failsafe_monitor.py | 1 | 0 | Minor |
| beacon.py | 0 | 1 (logger) | Done |
| lora_rtk_handler.py | 0 | 1 (logger) | Done |

---

### Task 4: Add Health Check Endpoint — NOT DONE
**Current state:** No `/api/health/detailed` endpoint exists.
- `/api/ping` exists (line 3981) — basic connectivity only
- `/monitor` exists — HTML dashboard page

**Available data for health checks (already in codebase):**
- `mavros_bridge.is_connected`, `mavros_bridge._rclpy_ready`
- `mission_controller.get_status()`
- `_beacon.is_alive()`
- `threading.active_count()`
- RTK stream status, GPS failsafe state

---

### Task 5: Add Pydantic Validation — NOT DONE
**Current state:** 0 Pydantic models. All endpoints accept raw dicts without validation.

**Priority endpoints for validation:**
- Mission upload (waypoints with lat/lng/alt/command)
- Arm/disarm, Set mode
- RTK configuration
- Manual control (RC override values)

---

### Task 6: Migrate to FastAPI Lifespan — DONE (merged with Task 1)
Completed as part of Task 1.

---

## Remaining Work Priority

```
1. Task 4 (Health endpoint)      -> Quick win, small effort, high value for monitoring
2. Task 2 (Silent exceptions)    -> Fix critical paths only, leave defensive ones
3. Task 3 (Module logging)       -> mavros_bridge.py and lora_receiver_usb.py first
4. Task 5 (Pydantic validation)  -> Mission upload + arm/disarm endpoints first
```

---

## Deployment Context

**Hardware:** Jetson Orin Nano
**OS:** Linux 5.15.148-tegra (JetPack)
**ROS2:** Active (rclpy + roslibpy dual path)
**Startup:** systemd (nrp-service) -> uvicorn + Socket.IO
**Network:** WiFi (local network)
**Fleet:** Single rover (prototype)
