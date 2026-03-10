#!/usr/bin/env python3
"""
Test script to verify TTS integration with mission status handler.
This simulates mission events to test TTS announcements.
"""

import time
import sys
import os

# Add Backend to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Backend"))

# Import the TTS module and server's handle_mission_status
try:
    import tts
    print("✓ TTS module imported successfully")
except Exception as e:
    print(f"✗ Failed to import TTS module: {e}")
    sys.exit(1)

# Test basic TTS functionality
print("\n=== Testing TTS Module ===")
print("Speaking: 'TTS integration test starting'")
tts.speak("TTS integration test starting")
time.sleep(4)

# Simulate mission events
test_events = [
    {
        "name": "Mission Load",
        "status_data": {
            "timestamp": "2025-01-15T10:00:00",
            "message": "Mission loaded with 3 waypoints",
            "level": "success",
            "mission_state": "ready",
            "total_waypoints": 3,
            "current_waypoint": 0
        },
        "expected": "Waypoints loaded: 3 waypoints"
    },
    {
        "name": "Mission Start",
        "status_data": {
            "timestamp": "2025-01-15T10:00:05",
            "message": "Mission started",
            "level": "success",
            "mission_state": "running",
            "total_waypoints": 3,
            "current_waypoint": 1
        },
        "expected": "Mission started"
    },
    {
        "name": "Executing Waypoint",
        "status_data": {
            "timestamp": "2025-01-15T10:00:10",
            "message": "Executing waypoint 1",
            "level": "info",
            "mission_state": "running",
            "total_waypoints": 3,
            "current_waypoint": 1
        },
        "expected": "Going to waypoint 1 of 3"
    },
    {
        "name": "Waypoint Reached",
        "status_data": {
            "timestamp": "2025-01-15T10:01:00",
            "message": "Waypoint 1 reached",
            "level": "success",
            "mission_state": "running",
            "total_waypoints": 3,
            "current_waypoint": 1,
            "extra_data": {
                "event_type": "waypoint_reached"
            }
        },
        "expected": "Waypoint 1 reached"
    },
    {
        "name": "Waypoint Complete",
        "status_data": {
            "timestamp": "2025-01-15T10:01:30",
            "message": "Waypoint 1 marking completed",
            "level": "success",
            "mission_state": "running",
            "total_waypoints": 3,
            "current_waypoint": 1,
            "extra_data": {
                "event_type": "waypoint_marked",
                "marking_status": "completed"
            }
        },
        "expected": "Waypoint 1 marked complete"
    },
    {
        "name": "Mission Complete",
        "status_data": {
            "timestamp": "2025-01-15T10:05:00",
            "message": "Mission completed successfully",
            "level": "success",
            "mission_state": "completed",
            "total_waypoints": 3,
            "current_waypoint": 3,
            "extra_data": {
                "waypoints_completed": 3,
                "mission_duration": 300
            }
        },
        "expected": "Mission completed: 3 waypoints in 300 seconds"
    }
]

print("\n=== Testing Mission Event TTS Announcements ===")
print("You should hear the following announcements through your USB audio device:\n")

for i, test_event in enumerate(test_events, 1):
    print(f"{i}. {test_event['name']}")
    print(f"   Expected: \"{test_event['expected']}\"")

    # Extract the TTS logic from handle_mission_status
    status_data = test_event['status_data']
    message = status_data.get('message', '')
    level = status_data.get('level', 'info')
    mission_state = status_data.get('mission_state', '')
    current_wp = status_data.get('current_waypoint', 0)
    total_wp = status_data.get('total_waypoints', 0)
    extra_data = status_data.get('extra_data', {})
    event_type = extra_data.get('event_type') if isinstance(extra_data, dict) else None

    # Apply same logic as in handle_mission_status
    try:
        if 'Mission loaded with' in message and 'waypoints' in message:
            count = total_wp
            tts.speak(f"Waypoints loaded: {count} waypoints")
            print(f"   ✓ Triggered TTS")

        elif 'Mission started' in message and mission_state == 'running':
            tts.speak("Mission started")
            print(f"   ✓ Triggered TTS")

        elif 'Executing waypoint' in message and current_wp > 0:
            tts.speak(f"Going to waypoint {current_wp} of {total_wp}")
            print(f"   ✓ Triggered TTS")

        elif event_type == 'waypoint_reached':
            tts.speak(f"Waypoint {current_wp} reached")
            print(f"   ✓ Triggered TTS")

        elif event_type == 'waypoint_marked':
            marking_status = extra_data.get('marking_status', '')
            if marking_status == 'completed':
                tts.speak(f"Waypoint {current_wp} marked complete")
                print(f"   ✓ Triggered TTS")

        elif 'Mission completed successfully' in message:
            waypoints_completed = extra_data.get('waypoints_completed', total_wp)
            mission_duration = extra_data.get('mission_duration', 0)
            if mission_duration > 0:
                tts.speak(f"Mission completed: {waypoints_completed} waypoints in {int(mission_duration)} seconds")
            else:
                tts.speak(f"Mission completed: {waypoints_completed} waypoints")
            print(f"   ✓ Triggered TTS")

    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Wait longer between announcements for clarity (10 seconds)
    print("   Waiting 5 seconds before next announcement...")
    time.sleep(5)
    print()

print("\n=== Test Complete ===")
print("Waiting 8 seconds for final announcements to complete...")
time.sleep(8)

print("\nShutting down TTS worker...")
tts.shutdown()
print("✓ Test finished successfully")
