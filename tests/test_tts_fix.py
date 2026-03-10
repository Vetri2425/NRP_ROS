#!/usr/bin/env python3
"""Test TTS fix by simulating mission_loaded event"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Backend'))

import tts

# Simulate what the mission controller sends
status_data = {
    'timestamp': '2025-12-17T16:00:00',
    'message': 'Mission loaded with 3 waypoints',
    'level': 'success',
    'mission_state': 'ready',
    'mission_mode': 'auto',
    'current_waypoint': 0,
    'total_waypoints': 3,
    'current_position': None,
    'pixhawk_state': None,
    # These come from extra_data but get merged into top level
    'event_type': 'mission_loaded',
    'waypoints_count': 3,
    'mode': 'auto',
}

# Simulate what server.py does NOW (after fix)
print("Testing FIXED server.py logic:")
print(f"status_data['event_type'] = {status_data.get('event_type')}")

event_type = status_data.get('event_type')
total_wp = status_data.get('total_waypoints', 0)

if event_type == 'mission_loaded':
    waypoints_count = status_data.get('waypoints_count', total_wp)
    tts_msg = f"Mission loaded: {waypoints_count} points"
    print(f"\nTTS message: {tts_msg}")
    print("Calling tts.speak()...")
    tts.speak(tts_msg, async_=False)
    print("✓ TTS call completed!")
else:
    print(f"ERROR: event_type '{event_type}' did not match 'mission_loaded'")
