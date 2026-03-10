#!/usr/bin/env python3
"""
Manual test + simple assertions for IntegratedMissionController event emissions.

Run from Backend directory:

    python test_integrated_mission_controller_events.py

This script:
- Mocks a MAVROS bridge with minimal methods
- Instantiates IntegratedMissionController with a status callback that records events
- Loads a 2-waypoint mission
- Starts the mission (upload handled by mock bridge)
- Simulates reaching a waypoint and verifies emitted events:
  - waypoint_reached
  - waypoint_marked (completed)
- Simulates a waypoint timeout and verifies a failed waypoint_marked event

The script prints pass/fail and exits with non-zero status on failure.
"""

import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Backend"))

from integrated_mission_controller import IntegratedMissionController, MissionMode, MissionState

# --- Mock bridge -----------------------------------------------------------
class MockBridge:
    def __init__(self):
        self._telemetry_cb = None
        self.host = 'mock'
        self.port = 0

    def subscribe_telemetry(self, cb):
        self._telemetry_cb = cb

    def clear_waypoints(self):
        return {'success': True}

    def push_waypoints(self, waypoints):
        # pretend upload works
        return {'success': True}

    def set_mode(self, mode=None):
        return {'mode_sent': True}

    # Optional helper to simulate telemetry
    def emit_telemetry(self, payload):
        if self._telemetry_cb:
            self._telemetry_cb(payload)

# --- Test runner ----------------------------------------------------------

events = []

def status_callback(payload):
    # Record copies of payloads for assertions
    events.append(payload.copy())


def assert_in(obj, key):
    if key not in obj:
        raise AssertionError(f"Missing key '{key}' in event: {obj}")


def run_tests():
    mock = MockBridge()
    mc = IntegratedMissionController(mavros_bridge=mock, status_callback=status_callback, logger=None)

    # Prepare a simple one-waypoint mission
    wp = {"lat": 13.072000, "lng": 80.262000, "alt": 50}
    load_res = mc.load_mission({"waypoints": [wp], "config": {"auto_mode": False, "hold_duration": 0.1}})
    if not load_res.get('success'):
        print("Failed to load mission in test:", load_res)
        return 2

    # Start mission
    start_res = mc.start_mission()
    if not start_res.get('success'):
        print("Failed to start mission in test:", start_res)
        return 3

    # At this point the controller should have uploaded waypoint and set waiting_for_waypoint_reach
    # Simulate current position at the waypoint (within threshold)
    mc.current_position = {"lat": 13.072000, "lng": 80.262000, "alt": 50}

    # Ensure mission state is RUNNING and waiting flag set
    mc.mission_state = MissionState.RUNNING
    mc.waiting_for_waypoint_reach = True

    # Trigger distance check that should call waypoint_reached()
    mc.check_waypoint_reached()

    # Small sleep to allow any timers/callbacks to run
    time.sleep(0.05)

    # Find the last waypoint_reached event
    wr_event = None
    for e in events:
        if e.get('event_type') == 'waypoint_reached':
            wr_event = e
            break

    if wr_event is None:
        print("FAILED: waypoint_reached event not emitted. Events:\n", events)
        return 4

    # Validate fields for waypoint_reached
    try:
        assert_in(wr_event, 'event_type')
        assert_in(wr_event, 'waypoint_id')
        assert_in(wr_event, 'current_waypoint')
        assert_in(wr_event, 'timestamp')
        assert_in(wr_event, 'position')
        assert_in(wr_event, 'message')

        assert wr_event['event_type'] == 'waypoint_reached'
        assert wr_event['waypoint_id'] == 1
        assert wr_event['current_waypoint'] == 1
        assert isinstance(wr_event['position'], dict)
    except AssertionError as ex:
        print("FAILED waypoint_reached validation:", ex)
        return 5

    print("PASS: waypoint_reached event emitted and validated")

    # Now trigger hold_period_complete manually (to avoid waiting for timer)
    mc.hold_period_complete()
    time.sleep(0.02)

    wm_event = None
    for e in events:
        if e.get('event_type') == 'waypoint_marked' and e.get('marking_status') == 'completed':
            wm_event = e
            break

    if wm_event is None:
        print("FAILED: waypoint_marked (completed) event not emitted. Events:\n", events)
        return 6

    # Validate fields for waypoint_marked
    try:
        assert_in(wm_event, 'event_type')
        assert_in(wm_event, 'waypoint_id')
        assert_in(wm_event, 'current_waypoint')
        assert_in(wm_event, 'timestamp')
        assert_in(wm_event, 'marking_status')
        assert_in(wm_event, 'message')

        assert wm_event['event_type'] == 'waypoint_marked'
        assert wm_event['waypoint_id'] == 1
        assert wm_event['marking_status'] == 'completed'
    except AssertionError as ex:
        print("FAILED waypoint_marked validation:", ex)
        return 7

    print("PASS: waypoint_marked (completed) event emitted and validated")

    # Test timeout -> failed marking
    events.clear()

    # Re-arm state to mimic waiting
    mc.mission_state = MissionState.RUNNING
    mc.waiting_for_waypoint_reach = True

    mc.waypoint_timeout()
    time.sleep(0.02)

    failed_event = None
    for e in events:
        if e.get('event_type') == 'waypoint_marked' and e.get('marking_status') == 'failed':
            failed_event = e
            break

    if failed_event is None:
        print("FAILED: waypoint_marked (failed) event not emitted on timeout. Events:\n", events)
        return 8

    try:
        assert_in(failed_event, 'event_type')
        assert_in(failed_event, 'waypoint_id')
        assert_in(failed_event, 'current_waypoint')
        assert_in(failed_event, 'timestamp')
        assert_in(failed_event, 'marking_status')
        assert failed_event['marking_status'] == 'failed'
    except AssertionError as ex:
        print("FAILED waypoint_marked (failed) validation:", ex)
        return 9

    print("PASS: waypoint_marked (failed) event emitted on timeout and validated")

    print("ALL TESTS PASSED")
    return 0


if __name__ == '__main__':
    rc = run_tests()
    if rc != 0:
        print(f"TESTS FAILED (code {rc})")
        sys.exit(rc)
    else:
        sys.exit(0)
