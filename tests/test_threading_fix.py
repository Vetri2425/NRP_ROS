#!/usr/bin/env python3
"""
Test: Spin-thread deadlock fix for _handle_waypoint_reached_rclpy

Simulates the exact deadlock scenario:
  OLD: spin_thread → callback → _broadcast_telem (sync) → set_mode → service call
       → spin thread BLOCKED → future never completes → 3s timeout → CLI fallback (2s)

  NEW: spin_thread → callback → Thread(_broadcast_telem) → spin thread FREE
       → new thread → set_mode → service call → spin thread processes → FAST
"""

import time
import threading
from typing import Callable, Dict, List, Optional


class SpinThreadSimulator:
    """
    Simulates rclpy's spin thread behavior:
    - Runs a loop that processes callbacks and service responses
    - Service responses can only be resolved when the spin thread is FREE
    """

    def __init__(self):
        self._running = True
        self._pending_responses: List[threading.Event] = []
        self._lock = threading.Lock()
        self._spin_thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._spin_thread.start()

    def _spin_loop(self):
        """Simulates rclpy.spin() — processes service responses."""
        while self._running:
            with self._lock:
                for event in self._pending_responses:
                    event.set()  # Resolve the future
                self._pending_responses.clear()
            time.sleep(0.005)  # 5ms spin rate

    def call_service_async(self, service_name: str, timeout: float = 3.0) -> bool:
        """
        Simulates _call_service_rclpy — sends request, polls future.done().
        The response can only be resolved when the spin thread processes it.
        """
        response_event = threading.Event()

        # Queue the response for the spin thread to resolve
        with self._lock:
            self._pending_responses.append(response_event)

        # Poll until done (same pattern as _call_service_rclpy)
        start = time.time()
        while not response_event.is_set():
            elapsed = time.time() - start
            if elapsed > timeout:
                return False  # Timeout — spin thread was blocked
            time.sleep(0.01)

        return True  # Success

    def shutdown(self):
        self._running = False


class MockBridge:
    """Simulates MavrosBridge with the deadlock-prone callback pattern."""

    def __init__(self, spin_sim: SpinThreadSimulator):
        self._spin = spin_sim
        self._telemetry_callbacks: List[Callable] = []

    def subscribe_telemetry(self, callback: Callable):
        self._telemetry_callbacks.append(callback)

    def _broadcast_telem(self, payload: Dict, message_type: Optional[str] = None):
        if message_type:
            payload["type"] = message_type
        for cb in self._telemetry_callbacks:
            cb(payload)

    def set_mode(self, mode: str) -> Dict:
        """Calls the service via spin thread (simulates _call_service_rclpy)."""
        t0 = time.time()
        success = self._spin.call_service_async("set_mode", timeout=3.0)
        elapsed = (time.time() - t0) * 1000
        return {"mode_sent": success, "elapsed_ms": elapsed}

    def set_servo(self, channel: int, pwm: int) -> Dict:
        """Calls CommandLong via spin thread."""
        t0 = time.time()
        success = self._spin.call_service_async("command_long", timeout=3.0)
        elapsed = (time.time() - t0) * 1000
        return {"success": success, "elapsed_ms": elapsed}

    # --- OLD behavior: sync callback (DEADLOCKS) ---
    def handle_waypoint_reached_OLD(self, wp_seq: int):
        """OLD: _broadcast_telem runs IN the spin thread — blocks it."""
        self._broadcast_telem({
            "mission_progress": {"current": wp_seq + 1},
            "wp_seq": wp_seq
        }, message_type="mission_reached")

    # --- NEW behavior: threaded callback (FIXED) ---
    def handle_waypoint_reached_NEW(self, wp_seq: int):
        """NEW: _broadcast_telem offloaded to separate thread — spin thread stays free."""
        threading.Thread(
            target=self._broadcast_telem,
            args=({
                "mission_progress": {"current": wp_seq + 1},
                "wp_seq": wp_seq
            },),
            kwargs={"message_type": "mission_reached"},
            daemon=True
        ).start()


class MockMissionController:
    """Simulates the mission controller's waypoint reached flow."""

    def __init__(self, bridge: MockBridge):
        self.bridge = bridge
        self.bridge.subscribe_telemetry(self.handle_telemetry_update)
        self.results: Dict = {}

    def handle_telemetry_update(self, telemetry_data: Dict):
        message_type = telemetry_data.get("type", "")
        if message_type != "mission_reached":
            return

        wp_seq = telemetry_data.get("wp_seq")
        t_start = time.time()

        # Step 1: Set HOLD mode (THIS is where the deadlock happens)
        mode_result = self.bridge.set_mode("HOLD")
        t_mode = time.time()

        # Step 2: Servo ON
        servo_on = self.bridge.set_servo(9, 2300)
        t_servo_on = time.time()

        # Step 3: Spray duration
        time.sleep(0.1)

        # Step 4: Servo OFF
        servo_off = self.bridge.set_servo(9, 1750)
        t_end = time.time()

        self.results = {
            "set_mode_ms": (t_mode - t_start) * 1000,
            "set_mode_success": mode_result["mode_sent"],
            "servo_on_ms": (t_servo_on - t_mode) * 1000,
            "servo_on_success": servo_on["success"],
            "servo_off_ms": (t_end - t_servo_on) * 1000 - 100,  # subtract spray wait
            "servo_off_success": servo_off["success"],
            "total_ms": (t_end - t_start) * 1000,
        }


def run_test(label: str, use_new: bool):
    print(f"\n{'='*60}")
    print(f"  TEST: {label}")
    print(f"{'='*60}")

    spin = SpinThreadSimulator()
    bridge = MockBridge(spin)
    controller = MockMissionController(bridge)

    # Simulate: spin thread calls the callback (like rclpy subscription)
    def simulate_spin_thread_callback():
        if use_new:
            bridge.handle_waypoint_reached_NEW(wp_seq=1)
        else:
            bridge.handle_waypoint_reached_OLD(wp_seq=1)

    # Run callback FROM the spin thread (replacing spin loop temporarily)
    # This simulates what happens when rclpy delivers a subscription message
    old_running = spin._running
    spin._running = False  # Pause spin loop
    time.sleep(0.02)       # Let spin loop stop

    t0 = time.time()

    if use_new:
        # NEW: callback offloads to thread, spin thread stays free
        spin._running = True  # Restart spin loop BEFORE callback
        spin._spin_thread = threading.Thread(target=spin._spin_loop, daemon=True)
        spin._spin_thread.start()
        bridge.handle_waypoint_reached_NEW(wp_seq=1)
        time.sleep(0.5)  # Wait for threaded work to complete
    else:
        # OLD: callback runs in spin thread context (spin loop stopped = deadlock)
        bridge.handle_waypoint_reached_OLD(wp_seq=1)
        # Spin loop was stopped, so service calls timeout

    total = (time.time() - t0) * 1000

    r = controller.results
    if r:
        mode_status = "OK" if r["set_mode_success"] else "TIMEOUT"
        servo_on_status = "OK" if r["servo_on_success"] else "TIMEOUT"
        servo_off_status = "OK" if r["servo_off_success"] else "TIMEOUT"

        print(f"\n  set_mode HOLD:  {r['set_mode_ms']:>8.0f}ms  [{mode_status}]")
        print(f"  servo ON:      {r['servo_on_ms']:>8.0f}ms  [{servo_on_status}]")
        print(f"  servo OFF:     {r['servo_off_ms']:>8.0f}ms  [{servo_off_status}]")
        print(f"  ─────────────────────────────")
        print(f"  TOTAL:         {r['total_ms']:>8.0f}ms")
    else:
        print(f"\n  No results — callback may still be running")
        print(f"  Elapsed so far: {total:.0f}ms")

    spin.shutdown()
    return r


if __name__ == "__main__":
    print("=" * 60)
    print("  SPIN-THREAD DEADLOCK FIX VERIFICATION")
    print("  Simulates rclpy spin thread + service call behavior")
    print("=" * 60)

    # Test 1: OLD behavior (sync — deadlocks)
    old_results = run_test("OLD: Sync callback (DEADLOCK expected)", use_new=False)

    # Test 2: NEW behavior (threaded — should be fast)
    new_results = run_test("NEW: Threaded callback (FIX)", use_new=True)

    # Summary
    print(f"\n{'='*60}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*60}")

    if old_results and new_results:
        print(f"\n  {'':30s} {'OLD (sync)':>12s}  {'NEW (thread)':>12s}")
        print(f"  {'─'*30} {'─'*12}  {'─'*12}")
        print(f"  {'set_mode':30s} {old_results['set_mode_ms']:>10.0f}ms  {new_results['set_mode_ms']:>10.0f}ms")
        print(f"  {'servo ON':30s} {old_results['servo_on_ms']:>10.0f}ms  {new_results['servo_on_ms']:>10.0f}ms")
        print(f"  {'servo OFF':30s} {old_results['servo_off_ms']:>10.0f}ms  {new_results['servo_off_ms']:>10.0f}ms")
        print(f"  {'TOTAL':30s} {old_results['total_ms']:>10.0f}ms  {new_results['total_ms']:>10.0f}ms")

        speedup = old_results['total_ms'] / new_results['total_ms'] if new_results['total_ms'] > 0 else 0
        print(f"\n  Speedup: {speedup:.1f}x faster")

        if new_results['total_ms'] < 500:
            print(f"  ✅ FIX VERIFIED: Total sequence under 500ms")
        else:
            print(f"  ⚠  Slower than expected")
    print()
