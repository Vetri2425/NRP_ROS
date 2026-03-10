#!/usr/bin/env python3
"""
Quick test to verify TTS is working when mission is loaded.
This test directly calls the TTS without the full server infrastructure.
"""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Backend"))

print("=" * 60)
print("TTS Mission Loading Test")
print("=" * 60)

# Import TTS module
import tts

# Test 1: Direct TTS call
print("\n[Test 1] Direct TTS call (sync mode)")
print("Speaking: 'Test one - direct TTS call'")
tts.speak("Test one - direct TTS call", async_=False)
print("✓ Completed")
time.sleep(1)

# Test 2: Async TTS call (how server uses it)
print("\n[Test 2] Async TTS call (server mode)")
print("Speaking: 'Test two - async TTS call'")
tts.speak("Test two - async TTS call", async_=True)
print("✓ Queued (waiting 3 seconds for worker to process)")
time.sleep(3)

# Test 3: Simulate mission loaded event
print("\n[Test 3] Simulating mission loaded event")
print("Speaking: 'Mission loaded: 5 waypoints'")
tts.speak("Mission loaded: 5 waypoints", async_=True)
print("✓ Queued (waiting 3 seconds)")
time.sleep(3)

# Test 4: Multiple rapid calls (like real mission events)
print("\n[Test 4] Multiple rapid mission events")
events = [
    "Waypoints loaded: 3 waypoints",
    "Mission started",
    "Going to waypoint 1 of 3",
]

for i, event in enumerate(events, 1):
    print(f"  {i}. {event}")
    tts.speak(event, async_=True)
    time.sleep(1)  # Small delay between queuing

print("\n✓ All events queued (waiting 8 seconds for completion)")
time.sleep(8)

print("\n" + "=" * 60)
print("Test Complete!")
print("=" * 60)
print("\nIf you heard all 6 announcements, TTS is working correctly!")
print("If not, there may be a hardware/speaker issue.")
