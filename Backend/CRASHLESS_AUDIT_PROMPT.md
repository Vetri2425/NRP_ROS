# NRP_ROS Phase 1 Crashless Audit — Debug Agent Prompt

Copy everything below and give it to Claude Code as a single prompt.

---

## Prompt

You are a **crash-prevention auditor** for a Jetson Orin Nano rover running ROS2 + FastAPI + Socket.IO + roslibpy. The system experienced crashes during field missions where all telemetry froze and the server became unresponsive, requiring a manual restart. The root cause was **blocking calls on the roslibpy WebSocket callback thread** — any slow operation (ROS2 service call, subprocess, lock contention) on that single thread kills ALL telemetry (GPS, battery, mode, heading) to the frontend.

Three instances of this pattern were already found and fixed by offloading to daemon threads. Your job is to find ALL remaining instances across the entire codebase.

### Architecture Context

```
Frontend (React) ←— Socket.IO ——→ server.py (FastAPI + uvicorn)
                                      │
                                      ├── integrated_mission_controller.py (2842 lines)
                                      │     └── handle_telemetry_update() ← callback from bridge
                                      │     └── waypoint_reached() → set_pixhawk_mode() [BLOCKING]
                                      │     └── _update_dash_time() → set_servo() [BLOCKING]
                                      │     └── execute_servo_sequence() → set_servo() [BLOCKING]
                                      │
                                      ├── mavros_bridge.py (1233 lines)
                                      │     └── roslibpy WebSocket thread (SINGLE THREAD for all topics)
                                      │     └── _broadcast_telem() → calls all registered callbacks SYNCHRONOUSLY
                                      │     └── rclpy spin thread (separate, for service call futures)
                                      │     └── _call_service_rclpy() → 3s timeout, then CLI fallback 10s
                                      │
                                      ├── manual_control_handler.py
                                      ├── gps_failsafe_monitor.py
                                      ├── obstacle_monitor.py
                                      ├── led_controller.py
                                      ├── tts.py
                                      ├── lora_rtk_handler.py
                                      ├── beacon.py
                                      └── ultrasonic_watch.py / ultrasonic_sensor.py
```

### The Crash Pattern (what to look for)

**RULE: The roslibpy WebSocket callback thread must NEVER be blocked.** Any function that runs synchronously inside `_broadcast_telem()` → callback chain must return in <10ms. Violations include:

1. **Blocking ROS2 service calls** — `bridge.set_mode()`, `bridge.set_servo()`, `bridge.send_command_long()`, `bridge.arm()`, `bridge.set_current_waypoint()`, `bridge.push_waypoints()`, any `_call_service_rclpy()` call (3s timeout) + CLI subprocess fallback (10s timeout)

2. **Lock contention** — Acquiring `self.lock` (RLock) when another thread holds it during a blocking service call. If Thread A holds `self.lock` for 13s inside `waypoint_reached()` → `set_pixhawk_mode()`, and Thread B (roslibpy) tries to acquire the same lock, roslibpy is blocked for 13s.

3. **Subprocess calls** — Any `subprocess.run()` or `subprocess.Popen().communicate()` without proper timeout + process group kill. Check for raw `subprocess.run(capture_output=True)` which can hang if child processes keep pipes open.

4. **Synchronous I/O** — File writes, network calls, or `time.sleep()` inside a callback path.

5. **Threading.Timer callbacks** — `threading.Timer` fires on a new thread, but if its callback acquires `self.lock` while it's held by a blocking call, it blocks. Check all `threading.Timer` targets.

6. **Dual subscription race conditions** — Both rclpy and roslibpy subscribe to `/mavros/mission/reached`. Without atomic dedup guards, both can process the same event.

### Files to Audit (in priority order)

1. **`integrated_mission_controller.py`** — The main mission logic. Audit EVERY method that can be called from `handle_telemetry_update()` callback chain. Trace all code paths from `handle_telemetry_update()` and check if any can reach a blocking bridge call.

2. **`mavros_bridge.py`** — Check every roslibpy topic handler (`_handle_*` methods). Verify none call blocking operations. Check `_broadcast_telem()` and all its callsites. Verify `_run_subprocess_safe` is used everywhere instead of raw `subprocess.run`.

3. **`server.py`** — Check all Socket.IO event handlers (`@sio.on(...)`). Check `handle_mission_status()` callback. Check any route handler that calls bridge methods. Look for `subprocess.run(capture_output=True)` calls.

4. **`manual_control_handler.py`** — Check if manual control commands (RC override, mode changes) can block the telemetry thread.

5. **`gps_failsafe_monitor.py`** — Check if failsafe triggers can call blocking bridge operations.

6. **`obstacle_monitor.py`** — Check if obstacle detection callbacks can block.

7. **`tts.py`** — Verify TTS is truly non-blocking. Check for `subprocess.run` with `capture_output=True`.

8. **`led_controller.py`** — Check if LED updates can block (SPI calls, etc).

9. **`lora_rtk_handler.py`**, **`beacon.py`**, **`ultrasonic_watch.py`** — Check for blocking patterns.

### Specific Checks to Perform

For each file, answer:

- [ ] Does this file have any `subprocess.run(capture_output=True)` without `_run_subprocess_safe`?
- [ ] Does this file acquire `self.lock` (or any shared lock) inside code that can run on the roslibpy thread?
- [ ] Does this file call any bridge method (`set_mode`, `set_servo`, `arm`, `send_command_long`, `push_waypoints`, `set_current_waypoint`) from a callback that could be on the roslibpy thread?
- [ ] Does this file have `time.sleep()` in any callback path?
- [ ] Does this file have `threading.Timer` whose callback acquires locks or calls blocking bridge methods?
- [ ] Does this file do synchronous file I/O or network calls in a callback path?

### Already Fixed (skip these — they are confirmed safe)

- `mavros_bridge.py:1184` — `_handle_waypoint_reached` uses daemon thread
- `mavros_bridge.py:1206` — `_handle_waypoint_reached_rclpy` uses daemon thread
- `mavros_bridge.py:48` — `_run_subprocess_safe` with `start_new_session=True` + `os.killpg`
- `integrated_mission_controller.py:325` — `handle_pixhawk_waypoint_reached` offloaded to daemon thread
- `integrated_mission_controller.py:344` — `check_waypoint_reached_distance_fallback` offloaded to daemon thread
- `integrated_mission_controller.py:1497` — dedup guard with `self.lock` for atomic check-and-set
- `integrated_mission_controller.py:1807` — `_update_dash_time` servo toggle offloaded to daemon thread

### Output Format

For each issue found, report:

```
ISSUE #N: [CRITICAL/HIGH/MEDIUM/LOW]
File: <filename>:<line_number>
Method: <method_name>
Called from: <trace showing how roslibpy thread reaches this code>
Problem: <what blocks and for how long>
Fix: <specific code change needed>
```

After all issues, provide a summary table:

| # | Severity | File | Method | Block Duration | Status |
|---|----------|------|--------|---------------|--------|

End with a **CRASHLESS VERDICT**: Can this server run a full multi-waypoint mission (50+ waypoints, manual + auto modes, dash + continuous + point-by-point) without the roslibpy thread ever being blocked?
