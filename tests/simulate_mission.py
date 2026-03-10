#!/usr/bin/env python3
"""
Mission Simulation Script - Tests waypoint-by-waypoint execution WITHOUT real hardware.

Creates a MockMavrosBridge that replaces roslibpy/MAVROS calls with in-memory simulation.
Loads a mission into IntegratedMissionController, starts it, and for each waypoint:
  1. Simulates the rover moving toward the target position (telemetry updates)
  2. Publishes a 'mission_reached' event (exactly like Pixhawk would)
  3. Measures how fast the controller reacts

Usage:
    python3 simulate_mission.py
"""

import sys
import os
import time
import threading
import math
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# Add Backend to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Backend"))


class MockMavrosBridge:
    """
    Mock MavrosBridge that simulates MAVROS responses without ROS/hardware.
    Supports telemetry callbacks so the mission controller works normally.
    """

    def __init__(self):
        self._telemetry_callbacks: List[Callable] = []
        self._lock = threading.Lock()
        self._current_mode = "HOLD"
        self._armed = False
        self._uploaded_waypoints: List[Dict] = []
        self._current_wp_seq = 0

        # Simulated rover position (starts at a default)
        self.sim_lat = 7.250000
        self.sim_lng = 80.350000
        self.sim_alt = 0.0

        # Telemetry broadcast thread
        self._running = True
        self._telem_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self._telem_thread.start()

    # ---------- Telemetry subscription (used by mission controller) ----------

    def subscribe_telemetry(self, callback: Callable):
        with self._lock:
            self._telemetry_callbacks.append(callback)

    def _broadcast(self, payload: Dict[str, Any], message_type: Optional[str] = None):
        with self._lock:
            if message_type:
                payload["type"] = message_type
            payload["lastUpdate"] = int(time.time() * 1000)
            callbacks = list(self._telemetry_callbacks)
        for cb in callbacks:
            try:
                cb(payload)
            except Exception:
                pass

    def _telemetry_loop(self):
        """Broadcast position + state telemetry at ~4 Hz."""
        while self._running:
            self._broadcast({
                "latitude": self.sim_lat,
                "longitude": self.sim_lng,
                "altitude": self.sim_alt,
                "mode": self._current_mode,
                "armed": self._armed,
                "connected": True,
            }, message_type="state")
            time.sleep(0.25)

    # ---------- Service stubs (called by mission controller) ----------

    def set_mode(self, *, mode: str, **kwargs) -> Dict[str, Any]:
        self._current_mode = mode
        print(f"  [MOCK_BRIDGE] Mode → {mode}", flush=True)
        return {"mode_sent": True}

    def set_armed(self, value: bool, **kwargs) -> Dict[str, Any]:
        self._armed = value
        print(f"  [MOCK_BRIDGE] Armed → {value}", flush=True)
        return {"success": True, "armed": value}

    def clear_waypoints(self, **kwargs) -> Dict[str, Any]:
        self._uploaded_waypoints.clear()
        return {"success": True}

    def push_waypoints(self, waypoints: List[Dict], **kwargs) -> Dict[str, Any]:
        self._uploaded_waypoints = list(waypoints)
        print(f"  [MOCK_BRIDGE] Uploaded {len(waypoints)} waypoints", flush=True)
        return {"success": True, "wp_transfered": len(waypoints)}

    def set_current_waypoint(self, wp_seq: int, **kwargs) -> Dict[str, Any]:
        self._current_wp_seq = wp_seq
        return {"success": True}

    def pull_waypoints(self, **kwargs) -> Dict[str, Any]:
        return {"waypoints": self._uploaded_waypoints, "success": True}

    def set_servo(self, channel: int, pwm: int, **kwargs) -> Dict[str, Any]:
        print(f"  [MOCK_BRIDGE] Servo ch{channel} → {pwm}µs", flush=True)
        return {"success": True}

    def send_command_long(self, **kwargs) -> Dict[str, Any]:
        return {"success": True, "result": 0}

    def suppress_disconnect_check(self, value: bool):
        pass  # No-op for mock

    def set_current_waypoint_cli(self, wp_seq: int, **kwargs) -> Dict[str, Any]:
        return {"success": True}

    # ---------- Simulation helpers ----------

    def simulate_move_to(self, target_lat: float, target_lng: float, steps: int = 5, step_delay: float = 0.15):
        """Gradually move the simulated rover toward a target position."""
        start_lat = self.sim_lat
        start_lng = self.sim_lng
        for i in range(1, steps + 1):
            frac = i / steps
            self.sim_lat = start_lat + (target_lat - start_lat) * frac
            self.sim_lng = start_lng + (target_lng - start_lng) * frac
            time.sleep(step_delay)

    def simulate_waypoint_reached(self, wp_seq: int):
        """
        Publish a mission_reached event — exactly what Pixhawk sends via
        /mavros/mission/reached topic when the rover arrives at a waypoint.
        """
        print(f"  [MOCK_BRIDGE] Publishing mission_reached: wp_seq={wp_seq}", flush=True)
        self._broadcast({
            "mission_progress": {
                "current": wp_seq + 1
            },
            "wp_seq": wp_seq,
        }, message_type="mission_reached")

    def shutdown(self):
        self._running = False


# ─────────────────────────────────────────────────────────────────────────────
# Event tracking
# ─────────────────────────────────────────────────────────────────────────────

class MissionEventTracker:
    """Captures mission controller status events for timing analysis."""

    def __init__(self):
        self.events: List[Dict] = []
        self.lock = threading.Lock()
        self.wp_reached_times: Dict[int, float] = {}   # wp_id → time controller confirmed
        self.wp_completed_times: Dict[int, float] = {}  # wp_id → time hold+servo done
        self.mission_completed = threading.Event()

    def status_callback(self, status_data: Dict[str, Any]):
        event_type = status_data.get("event_type", "")
        msg = status_data.get("message", "")
        level = status_data.get("level", "info")
        ts = time.time()

        with self.lock:
            self.events.append({"time": ts, "event_type": event_type, "message": msg, "level": level})

        # Track waypoint reached confirmations
        if event_type == "waypoint_reached":
            wp_id = status_data.get("waypoint_id", 0)
            self.wp_reached_times[wp_id] = ts
            print(f"  ✅ Controller confirmed WP{wp_id} REACHED  (t={ts:.3f})", flush=True)

        elif event_type == "waypoint_marked":
            wp_id = status_data.get("waypoint_id", 0)
            self.wp_completed_times[wp_id] = ts
            print(f"  🎯 Controller completed WP{wp_id} (hold+servo done)  (t={ts:.3f})", flush=True)

        elif event_type == "mission_completed":
            print(f"  🏁 MISSION COMPLETED", flush=True)
            self.mission_completed.set()

        elif event_type == "mission_error":
            print(f"  ❌ MISSION ERROR: {msg}", flush=True)

        elif event_type == "waypoint_failed":
            print(f"  ❌ WAYPOINT FAILED: {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main simulation
# ─────────────────────────────────────────────────────────────────────────────

def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def run_simulation():
    print("=" * 70)
    print("  MISSION SIMULATION - Waypoint Reach Timing Test")
    print("=" * 70)

    # ── 1. Create mock bridge & tracker ──
    bridge = MockMavrosBridge()
    tracker = MissionEventTracker()

    # ── 2. Create mission controller (the real one, with mock bridge) ──
    from integrated_mission_controller import IntegratedMissionController
    controller = IntegratedMissionController(
        mavros_bridge=bridge,
        status_callback=tracker.status_callback,
        logger=None
    )
    # Disable failsafe (no real GPS to check)
    controller.failsafe_mode = "disable"
    controller.failsafe_monitor = None

    # Wait for telemetry to propagate initial position to controller
    print("⏳ Waiting for initial telemetry position...")
    for _ in range(40):  # up to 2s
        if controller.current_position is not None:
            break
        time.sleep(0.05)

    if controller.current_position:
        print(f"   ✅ Controller has position: {controller.current_position}")
    else:
        print("   ❌ No position received — simulation may fail")

    # ── 3. Define test waypoints ──
    waypoints = [
        {"lat": 7.250100, "lng": 80.350100, "alt": 0.0},
        {"lat": 7.250200, "lng": 80.350200, "alt": 0.0},
        {"lat": 7.250300, "lng": 80.350300, "alt": 0.0},
        {"lat": 7.250400, "lng": 80.350400, "alt": 0.0},
        {"lat": 7.250500, "lng": 80.350500, "alt": 0.0},
    ]

    print(f"\n📋 Test mission: {len(waypoints)} waypoints")
    for i, wp in enumerate(waypoints, 1):
        dist = haversine_m(bridge.sim_lat, bridge.sim_lng, wp["lat"], wp["lng"])
        print(f"   WP{i}: ({wp['lat']:.6f}, {wp['lng']:.6f})  ~{dist:.1f}m from start")
    print()

    # ── 4. Load mission ──
    print("─" * 70)
    print("STEP 1: Loading mission...")
    result = controller.process_command({
        "command": "load_mission",
        "waypoints": waypoints,
        "config": {
            "waypoint_threshold": 0.160,
            "hold_duration": 0,          # 0s hold — test pure reaction speed
            "auto_mode": True,
            "servo_enabled": True,
            "servo_spray_duration": 0.1,  # fast spray for test
            "servo_delay_before": 0.0,
            "servo_delay_after": 0.0,
        }
    })
    print(f"   Load result: {result}")
    assert result["success"], "Failed to load mission!"

    # ── 5. Start mission ──
    print("\n" + "─" * 70)
    print("STEP 2: Starting mission...")
    result = controller.process_command({"command": "start"})
    print(f"   Start result: {result}")
    assert result["success"], "Failed to start mission!"

    # ── 6. Simulate each waypoint ──
    publish_times: Dict[int, float] = {}  # wp_index → time we published reached

    for wp_idx, wp in enumerate(waypoints):
        wp_num = wp_idx + 1
        print(f"\n{'─' * 70}")
        print(f"STEP 3.{wp_num}: Simulating travel to WP{wp_num} ({wp['lat']:.6f}, {wp['lng']:.6f})")

        # Wait for controller to be waiting for waypoint reach
        wait_start = time.time()
        while not controller.waiting_for_waypoint_reach:
            if time.time() - wait_start > 10:
                print(f"   ⚠ Timeout waiting for controller to start monitoring WP{wp_num}")
                break
            time.sleep(0.05)

        # Simulate rover movement toward waypoint
        bridge.simulate_move_to(wp["lat"], wp["lng"], steps=5, step_delay=0.1)
        print(f"   📍 Rover arrived at ({bridge.sim_lat:.6f}, {bridge.sim_lng:.6f})")

        # Publish waypoint reached (Pixhawk seq: wp_idx+1 because seq=0 is HOME)
        pixhawk_seq = wp_idx + 1
        t_publish = time.time()
        publish_times[wp_num] = t_publish
        bridge.simulate_waypoint_reached(pixhawk_seq)

        # Wait for controller to confirm waypoint reached
        wait_start = time.time()
        while wp_num not in tracker.wp_reached_times:
            if time.time() - wait_start > 15:
                print(f"   ⚠ Timeout! Controller did NOT confirm WP{wp_num} reached in 15s")
                print(f"     controller.waiting_for_waypoint_reach = {controller.waiting_for_waypoint_reach}")
                print(f"     controller.mission_state = {controller.mission_state}")
                print(f"     controller.current_waypoint_index = {controller.current_waypoint_index}")
                break
            time.sleep(0.01)

        # Wait for hold+servo complete before next waypoint
        wait_start = time.time()
        while wp_num not in tracker.wp_completed_times:
            if time.time() - wait_start > 15:
                print(f"   ⚠ Timeout waiting for WP{wp_num} hold+servo completion")
                break
            time.sleep(0.01)

    # ── 7. Wait for mission completion ──
    print(f"\n{'─' * 70}")
    print("STEP 4: Waiting for mission completion...")
    if not tracker.mission_completed.wait(timeout=15):
        print("   ⚠ Mission did not complete within timeout")

    # ── 8. Print timing results ──
    print(f"\n{'=' * 70}")
    print("  TIMING RESULTS")
    print(f"{'=' * 70}")
    print(f"{'WP':<6} {'Publish→Reached':<20} {'Reached→Complete':<20} {'Total':<15}")
    print(f"{'─'*6} {'─'*20} {'─'*20} {'─'*15}")

    total_reaction = 0
    total_complete = 0
    count = 0

    for wp_num in sorted(publish_times.keys()):
        t_pub = publish_times.get(wp_num)
        t_reached = tracker.wp_reached_times.get(wp_num)
        t_complete = tracker.wp_completed_times.get(wp_num)

        if t_pub and t_reached:
            reaction_ms = (t_reached - t_pub) * 1000
            total_reaction += reaction_ms
            count += 1
        else:
            reaction_ms = None

        if t_reached and t_complete:
            complete_ms = (t_complete - t_reached) * 1000
            total_complete += complete_ms
        else:
            complete_ms = None

        if reaction_ms is not None and complete_ms is not None:
            total_ms = reaction_ms + complete_ms
        else:
            total_ms = None

        r_str = f"{reaction_ms:.1f}ms" if reaction_ms is not None else "N/A"
        c_str = f"{complete_ms:.1f}ms" if complete_ms is not None else "N/A"
        t_str = f"{total_ms:.1f}ms" if total_ms is not None else "N/A"
        print(f"WP{wp_num:<4} {r_str:<20} {c_str:<20} {t_str:<15}")

    print(f"{'─'*6} {'─'*20} {'─'*20} {'─'*15}")
    if count > 0:
        print(f"{'AVG':<6} {total_reaction/count:.1f}ms{'':<14} {total_complete/count:.1f}ms")
    print()

    # ── 9. Summary ──
    if count == len(waypoints):
        avg_reaction = total_reaction / count
        if avg_reaction < 100:
            print("✅ EXCELLENT: Waypoint reach detection is under 100ms")
        elif avg_reaction < 500:
            print("✅ GOOD: Waypoint reach detection is under 500ms")
        elif avg_reaction < 2000:
            print("⚠ SLOW: Waypoint reach detection is 0.5-2s (check telemetry rate)")
        else:
            print("❌ VERY SLOW: Waypoint reach detection > 2s (the bug may still exist)")
    else:
        print(f"⚠ Only {count}/{len(waypoints)} waypoints were confirmed — check for errors above")

    # Cleanup
    controller.shutdown()
    bridge.shutdown()
    print("\n✅ Simulation complete.\n")


if __name__ == "__main__":
    run_simulation()
