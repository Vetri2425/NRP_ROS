#!/usr/bin/env python3
"""
Quick test script to verify mode change logic.
Tests the mission start sequence step by step.
"""
import time
import json
import subprocess
import sys

def send_command(command_dict):
    """Send a command to /mission/command topic."""
    cmd_json = json.dumps(command_dict)
    # Escape for shell - need to escape quotes properly
    escaped_json = cmd_json.replace('"', '\\"')
    cmd = [
        'ros2', 'topic', 'pub', '--once',
        '/mission/command',
        'std_msgs/msg/String',
        f'{{"data": "{escaped_json}"}}'
    ]
    print(f"\n{'='*60}")
    print(f"Sending command: {command_dict}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return False
    print("Command sent successfully")
    return True

def check_status():
    """Read one message from /mission/status."""
    cmd = [
        'ros2', 'topic', 'echo', '/mission/status',
        '--once'
    ]
    print("\nWaiting for status message...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode == 0 and result.stdout:
        # Parse the data field
        for line in result.stdout.split('\n'):
            if line.strip().startswith('data:'):
                data_str = line.split('data:', 1)[1].strip().strip("'\"")
                try:
                    status = json.loads(data_str)
                    print(f"\nStatus: {status['event_type']}")
                    print(f"Message: {status['message']}")
                    return status
                except:
                    print(f"Raw: {data_str[:100]}...")
    return None

def check_vehicle_mode():
    """Check current vehicle mode from /mavros/state."""
    cmd = [
        'ros2', 'topic', 'echo', '/mavros/state',
        '--once'
    ]
    print("\nChecking vehicle mode...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        for line in result.stdout.split('\n'):
            if 'mode:' in line:
                mode = line.split('mode:', 1)[1].strip().strip("'\"")
                print(f"Vehicle mode: {mode}")
                return mode
    return None

def main():
    print("="*60)
    print("MISSION START MODE CHANGE TEST")
    print("="*60)
    
    # Step 1: Check initial vehicle state
    print("\n[1] Checking initial vehicle state...")
    initial_mode = check_vehicle_mode()
    
    # Step 2: Load a simple mission
    print("\n[2] Loading test mission...")
    mission = {
        "command": "load_mission",
        "waypoints": [
            {"lat": 11.0, "lng": 77.0},
            {"lat": 11.001, "lng": 77.001}
        ],
        "config": {
            "auto_mode": True,
            "spray_duration": 2.0
        }
    }
    if not send_command(mission):
        print("Failed to load mission")
        return 1
    
    time.sleep(1)
    
    # Step 3: Try to start mission
    print("\n[3] Starting mission (this will attempt mode change)...")
    if not send_command({"command": "start"}):
        print("Failed to send start command")
        return 1
    
    # Wait for processing
    print("\nWaiting 5 seconds for mode change processing...")
    time.sleep(5)
    
    # Step 4: Check final state
    print("\n[4] Checking final vehicle state...")
    final_mode = check_vehicle_mode()
    
    # Step 5: Check mission status
    print("\n[5] Checking mission status...")
    time.sleep(1)
    status = check_status()
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Initial mode: {initial_mode}")
    print(f"Final mode:   {final_mode}")
    if status:
        print(f"Status:       {status.get('event_type', 'unknown')}")
        print(f"Message:      {status.get('message', 'unknown')}")
    
    # Analyze
    if final_mode == 'GUIDED':
        print("\n✓ Vehicle IS in GUIDED mode")
        if status and 'failed' in status.get('event_type', ''):
            print("✗ But mission status shows FAILED")
            print("→ This confirms the bug: mode changes but code thinks it failed")
            return 1
        else:
            print("✓ Mission status is good")
            return 0
    else:
        print(f"\n✗ Vehicle is NOT in GUIDED mode (current: {final_mode})")
        print("→ Mode change actually failed")
        return 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
