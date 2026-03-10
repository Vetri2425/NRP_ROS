#!/usr/bin/env python3
"""
Test TTS with 10 waypoint mission to verify Piper output quality.
Usage: JARVIS_LANG=en python3 test_tts_10waypoints.py
"""

import time
import sys
import os

# Add Backend to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Backend"))

try:
    import tts
    print("✓ TTS module imported successfully")
except Exception as e:
    print(f"✗ Failed to import TTS module: {e}")
    sys.exit(1)

print("\n=== Testing TTS with 10 Waypoint Mission ===")
print(f"JARVIS_LANG: {os.environ.get('JARVIS_LANG', 'en')}\n")

# Mission load
print("1. Mission Loaded (10 waypoints)")
tts.speak("Mission loaded: 10 points")
time.sleep(6)

# Mission start
print("2. Mission Started")
tts.speak("Mission started")
time.sleep(4)

# Waypoints 1-10
for wp in range(1, 11):
    print(f"\n3.{wp}. Executing Waypoint {wp}")
    tts.speak(f"Going to waypoint {wp} of 10")
    time.sleep(4)
    
    print(f"    Waypoint {wp} Reached")
    tts.speak(f"Waypoint {wp} reached")
    time.sleep(3)
    
    print(f"    Waypoint {wp} Marked Complete")
    tts.speak(f"Waypoint {wp} marked complete")
    time.sleep(3)

# Mission complete
print("\n4. Mission Complete")
tts.speak("Mission completed. 10 waypoints in 180 seconds.")
time.sleep(6)

print("\n=== Test Complete ===")
print("Waiting for final audio to finish...")
time.sleep(3)

tts.shutdown()
print("✓ Test finished successfully")
