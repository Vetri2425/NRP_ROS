# High Priority — 2026-03-10

## 1. Fix Silent except:pass Blocks in Critical Paths
**Risk:** HIGH — missions silently fail, arms don't engage, nobody knows
**Scope:** 200+ silent blocks across codebase (42 in server.py, 25 in backend modules)

### Focus Areas (critical paths only):
- [ ] Mission start/stop/pause/resume handlers
- [ ] Arm/disarm handlers
- [ ] Mode change handlers
- [ ] Socket.IO event handlers (mission_upload, goto, etc.)
- [ ] Any bare `except:` -> change to `except Exception as e:`

### Pattern:
```python
# BEFORE:
try:
    some_operation()
except Exception:
    pass

# AFTER:
try:
    some_operation()
except Exception as e:
    log_message(f"[operation_name] failed: {e}", "ERROR")
```

### Leave alone (defensive/cleanup — acceptable):
- Telemetry parsing (best-effort data)
- _shutdown_ros_runtime() cleanup blocks
- JSON serialization fallbacks

---

## 2. Register Signal Handlers for Graceful Shutdown
**Risk:** MEDIUM-HIGH — hard kills leave LEDs on, ROS nodes dangling, timers active
**Scope:** Small change in server.py

### What to do:
- [ ] Register SIGTERM/SIGINT handlers that call `_shutdown_ros_runtime()`
- [ ] Add `atexit.register(_shutdown_ros_runtime)` as fallback
- [ ] Both `signal` and `atexit` already imported (lines 50-51) but never used
- [ ] Ensure handlers are idempotent (safe to call twice)

### Cleanup targets on shutdown:
- LED strip (left in last color state)
- ROS nodes (rclpy not shut down)
- Mission controller timers (hold_timer, mission_timer, position_check_timer, rtk_monitor_timer)
- Rosbridge websocket connection
- Beacon thread
