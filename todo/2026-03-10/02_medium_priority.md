# Medium Priority — 2026-03-10

## 3. Add /api/health/detailed Endpoint
**Risk:** MEDIUM — can't detect problems before they become failures
**Effort:** Small

### What to expose:
- [ ] Thread count and names (`threading.active_count()`, `threading.enumerate()`)
- [ ] Memory usage (RSS via `resource` module or `psutil` if available)
- [ ] MAVROS bridge connection state (`mavros_bridge.is_connected`, `_rclpy_ready`)
- [ ] Mission controller status (`mission_controller.get_status()`)
- [ ] Beacon thread alive (`_beacon.is_alive()`)
- [ ] WebSocket client count
- [ ] Server uptime (add `_start_time = time.time()` global)
- [ ] Overall status: "healthy" / "degraded" / "error"

### Endpoint:
```
GET /api/health/detailed
```

---

## 4. Replace print() with Logging in Backend Modules
**Risk:** MEDIUM — 184 print() calls invisible to journalctl log levels
**Effort:** Medium

### Files to convert (by priority):
- [ ] mavros_bridge.py (30 print calls) — core connectivity
- [ ] lora_receiver_usb.py (56 print calls) — RTK data path
- [ ] tts.py (8 print calls)
- [ ] obstacle_monitor.py (6 print calls)
- [ ] integrated_mission_controller.py (2 print calls)
- [ ] led_controller.py (1 print call)
- [ ] manual_control_handler.py (1 print call)
- [ ] gps_failsafe_monitor.py (1 print call)

### Already done (skip):
- beacon.py — uses `logging.getLogger("beacon")`
- lora_rtk_handler.py — uses `logging.getLogger(__name__)`
- server.py — `log_message()` already uses `logger`

### Pattern per module:
```python
import logging
logger = logging.getLogger(__name__)

# Replace: print(f"[MAVROS_BRIDGE] ...", flush=True)
# With:    logger.info("...")
```
