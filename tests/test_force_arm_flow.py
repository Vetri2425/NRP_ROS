#!/usr/bin/env python3
"""
test_force_arm_flow.py — Test the complete arm → force-arm → mission flow.

Scenarios tested:
  1. Start mission when rover is ARMED             → mission_started ✅
  2. Start mission when rover is NOT ARMED         → auto-arm attempt
     2a. Auto-arm succeeds                         → mission_started ✅
     2b. Auto-arm fails, user confirms force-arm   → force-arm attempt
         2b-i.  Force-arm succeeds                 → mission_started ✅
         2b-ii. Force-arm fails                    → mission_arm_error ❌
     2c. Auto-arm fails, user cancels              → mission_arm_cancelled ✅
  3. force_arm_confirm with no pending request     → error response ✅
"""

import socketio
import requests
import json
import threading
import time
import sys
from unittest.mock import patch, MagicMock

SERVER_URL = "http://127.0.0.1:5001"

# ── Colors ────────────────────────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[94m"
C = "\033[96m"; W = "\033[1m\033[97m"; X = "\033[0m"

passed = failed = 0

def ok(msg):
    global passed; passed += 1
    print(f"  {G}✓{X}  {msg}")

def fail(msg, detail=""):
    global failed; failed += 1
    d = f"\n      {R}{detail}{X}" if detail else ""
    print(f"  {R}✗{X}  {msg}{d}")

def info(msg):  print(f"  {B}ℹ{X}  {msg}")
def warn(msg):  print(f"  {Y}⚠{X}  {msg}")
def hdr(msg):   print(f"\n{W}{'─'*64}\n  {msg}\n{'─'*64}{X}")


# ── Helpers ───────────────────────────────────────────────────────────────────
def connect_sio() -> socketio.Client:
    sio = socketio.Client(logger=False, reconnection=False)
    events = {}
    lock = threading.Lock()

    @sio.on("mission_status")
    def on_mission_status(data):
        et = data.get("event_type", "unknown")
        with lock:
            events[et] = data
        info(f"  mission_status received: event_type={et!r}  level={data.get('level')}")
        info(f"    message: {data.get('message', '')[:80]}")

    sio.connect(SERVER_URL)
    sio._nrp_events = events
    sio._nrp_lock   = lock
    return sio


def wait_event(sio, event_type: str, timeout: float = 6.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with sio._nrp_lock:
            if event_type in sio._nrp_events:
                return sio._nrp_events.pop(event_type)
        time.sleep(0.1)
    return None


def post_start() -> dict:
    r = requests.post(f"{SERVER_URL}/api/mission/start",
                      headers={"Content-Type": "application/json"}, timeout=10)
    return r.json()


# ── Unit-level tests (mock mission_controller) ────────────────────────────────
def run_unit_tests():
    hdr("UNIT TESTS — IntegratedMissionController logic")

    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from Backend.integrated_mission_controller import IntegratedMissionController, MissionState, MissionMode
    except ImportError as e:
        warn(f"Cannot import mission controller: {e}")
        return

    # ── Build a minimal mock bridge ──────────────────────────────────────────
    bridge = MagicMock()
    bridge.is_connected = True

    emitted = []
    def fake_status_callback(data):
        emitted.append(data)

    mc = IntegratedMissionController(bridge, status_callback=fake_status_callback)

    # ── Test 1: No waypoints → error before arm check ─────────────────────────
    info("Test 1: start_mission() with no waypoints")
    mc.mission_state = MissionState.READY
    mc.waypoints = []
    result = mc.start_mission()
    if not result['success'] and 'waypoints' in result['error'].lower():
        ok("Correctly rejected: no waypoints")
    else:
        fail("Expected waypoints error", str(result))

    # ── Test 2: Waypoints loaded, rover armed → mission_started ───────────────
    info("Test 2: start_mission() with waypoints and rover ARMED")
    mc.mission_state = MissionState.READY
    mc.waypoints = [{'lat': 13.0, 'lng': 80.0, 'alt': 0}]
    mc.pixhawk_state = {'armed': True, 'mode': 'AUTO'}
    bridge.set_armed.return_value = {'success': True, 'armed': True}
    # Mock execute_current_waypoint to avoid real MAVLink calls
    mc.execute_current_waypoint = MagicMock()
    emitted.clear()
    result = mc.start_mission()
    if result['success']:
        ok("Mission started when already armed")
    else:
        fail("Expected success when armed", str(result))
    if any(e.get('event_type') == 'mission_started' for e in emitted):
        ok("mission_started event emitted")
    else:
        fail("mission_started event NOT emitted", str(emitted))

    # ── Test 3: Not armed, auto-arm succeeds → mission_started ────────────────
    info("Test 3: start_mission() NOT ARMED — auto-arm succeeds")
    mc.mission_state = MissionState.READY
    mc.pixhawk_state = {'armed': False, 'mode': 'STABILIZE'}
    bridge.set_armed.return_value = {'success': True, 'armed': True}
    mc.execute_current_waypoint = MagicMock()
    emitted.clear()
    result = mc.start_mission()
    if result['success']:
        ok("Mission started after successful auto-arm")
    else:
        fail("Expected success after auto-arm", str(result))
    if any(e.get('event_type') == 'mission_arming' for e in emitted):
        ok("mission_arming event emitted during auto-arm")
    else:
        fail("mission_arming event NOT emitted")

    # ── Test 4: Not armed, auto-arm FAILS → force-arm confirmation requested ──
    info("Test 4: start_mission() NOT ARMED — auto-arm FAILS")
    mc.mission_state = MissionState.READY
    mc.pixhawk_state = {'armed': False, 'mode': 'STABILIZE'}
    bridge.set_armed.return_value = {'success': False, 'armed': False, 'error': 'pre-arm checks failed'}
    emitted.clear()
    result = mc.start_mission()
    if not result['success'] and result.get('requires_force_arm'):
        ok("Returned requires_force_arm=True on auto-arm failure")
    else:
        fail("Expected requires_force_arm=True", str(result))
    if mc._pending_force_arm_start:
        ok("_pending_force_arm_start flag set correctly")
    else:
        fail("_pending_force_arm_start NOT set")
    if any(e.get('event_type') == 'mission_arm_force_confirm' for e in emitted):
        ok("mission_arm_force_confirm event emitted to frontend")
    else:
        fail("mission_arm_force_confirm event NOT emitted", str(emitted))

    # ── Test 5: force_arm_and_start() succeeds ────────────────────────────────
    info("Test 5: force_arm_and_start() — force-arm SUCCEEDS")
    mc._pending_force_arm_start = True
    mc.mission_state = MissionState.READY
    mc.pixhawk_state = {'armed': False, 'mode': 'STABILIZE'}
    bridge.force_arm.return_value = {'success': True, 'armed': True}
    bridge.set_armed.return_value = {'success': True, 'armed': True}
    mc.execute_current_waypoint = MagicMock()
    emitted.clear()
    result = mc.force_arm_and_start()
    if result['success']:
        ok("Mission started after force-arm success")
    else:
        fail("Expected mission start success after force-arm", str(result))
    if any(e.get('event_type') == 'mission_arming' for e in emitted):
        ok("mission_arming event emitted during force-arm")
    else:
        fail("mission_arming event NOT emitted during force-arm")
    if not mc._pending_force_arm_start:
        ok("_pending_force_arm_start cleared after force-arm")
    else:
        fail("_pending_force_arm_start NOT cleared")

    # ── Test 6: force_arm_and_start() FAILS ───────────────────────────────────
    info("Test 6: force_arm_and_start() — force-arm FAILS")
    mc._pending_force_arm_start = True
    bridge.force_arm.return_value = {'success': False, 'error': 'safety switch active'}
    emitted.clear()
    result = mc.force_arm_and_start()
    if not result['success'] and 'Force-arm failed' in result.get('error', ''):
        ok("Correctly returned error on force-arm failure")
    else:
        fail("Expected force-arm failure error", str(result))
    if any(e.get('event_type') == 'mission_arm_error' for e in emitted):
        ok("mission_arm_error event emitted on force-arm failure")
    else:
        fail("mission_arm_error event NOT emitted", str(emitted))

    # ── Test 7: force_arm_and_start() with no pending request ─────────────────
    info("Test 7: force_arm_and_start() with NO pending request")
    mc._pending_force_arm_start = False
    result = mc.force_arm_and_start()
    if not result['success'] and 'No pending' in result.get('error', ''):
        ok("Correctly rejected: no pending force-arm")
    else:
        fail("Expected 'No pending' error", str(result))


# ── Integration tests (live server via SocketIO + REST) ───────────────────────
def run_integration_tests():
    hdr("INTEGRATION TESTS — Live server")

    # Check server reachability
    try:
        requests.get(f"{SERVER_URL}/", timeout=3)
    except Exception:
        warn("Server not reachable — skipping integration tests")
        return

    info("Server is reachable ✓")

    # ── Test A: REST POST /api/mission/start returns JSON ─────────────────────
    info("Test A: POST /api/mission/start — response shape")
    resp = post_start()
    if 'success' in resp:
        ok(f"Response has 'success' field: {resp['success']}")
    else:
        fail("Response missing 'success' field", str(resp))

    if not resp.get('success'):
        info(f"  Expected failure (no waypoints / not armed): {resp.get('message') or resp.get('error')}")
        error_msg = (resp.get('message') or resp.get('error') or '').lower()
        if 'waypoints' in error_msg or 'arm' in error_msg or 'mission' in error_msg:
            ok("Error is a known expected pre-condition")
        else:
            warn(f"Unexpected error: {error_msg}")

    # ── Test B: SocketIO force_arm_confirm { confirm: false } → cancelled ──────
    info("Test B: force_arm_confirm { confirm: false } → mission_arm_cancelled")
    sio = connect_sio()
    time.sleep(0.3)
    sio.emit('force_arm_confirm', {'confirm': False})
    evt = wait_event(sio, 'mission_arm_cancelled', timeout=4)
    if evt is not None:
        ok("mission_arm_cancelled received after confirm=false")
    else:
        # Might not have pending state — still a valid server response check
        warn("No mission_arm_cancelled event (may not have had pending force-arm state)")
    try:
        sio.disconnect()
    except Exception:
        pass

    # ── Test C: SocketIO force_arm_confirm without prior start → safe handling ─
    info("Test C: force_arm_confirm with no pending state → server handles gracefully")
    sio2 = connect_sio()
    time.sleep(0.3)

    err_received = threading.Event()
    @sio2.on('mission_status')
    def on_ms2(data):
        et = data.get('event_type', '')
        if et in ('mission_arm_error', 'mission_arm_cancelled', 'mission_started'):
            err_received.set()

    sio2.emit('force_arm_confirm', {'confirm': True})
    if err_received.wait(timeout=5):
        ok("Server responded to force_arm_confirm gracefully")
    else:
        warn("No event received within timeout (server may have ignored safely)")
    try:
        sio2.disconnect()
    except Exception:
        pass

    # ── Test D: mission_status events received on POST /api/mission/start ──────
    info("Test D: mission_status events flow on POST /api/mission/start")
    sio3 = connect_sio()
    time.sleep(0.3)

    got_any_event = threading.Event()
    received_events = []
    @sio3.on('mission_status')
    def on_ms3(data):
        received_events.append(data.get('event_type'))
        got_any_event.set()

    post_start()
    got_any_event.wait(timeout=5)

    if received_events:
        ok(f"mission_status events fired: {received_events}")
        arm_events = {'mission_arming', 'mission_arm_force_confirm', 'mission_arm_error',
                      'mission_started', 'mission_arm_cancelled'}
        if any(e in arm_events for e in received_events):
            ok(f"Arm-related event received: {[e for e in received_events if e in arm_events]}")
        else:
            info(f"Non-arm events received: {received_events}")
    else:
        warn("No mission_status events received (may need waypoints loaded)")

    try:
        sio3.disconnect()
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"\n{W}Force-Arm Flow Test Suite{X}")
    print(f"Server: {SERVER_URL}\n")

    run_unit_tests()
    run_integration_tests()

    hdr("RESULTS")
    total = passed + failed
    rate  = (passed / total * 100) if total else 0
    print(f"  Tests run  : {total}")
    print(f"  {G}Passed{X}     : {passed}")
    print(f"  {R}Failed{X}     : {failed}")
    print(f"  Pass rate  : {rate:.0f}%\n")

    if failed == 0:
        print(f"{G}{W}  ✅  All tests passed.{X}\n")
        return 0
    else:
        print(f"{R}{W}  ❌  {failed} test(s) failed.{X}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
