#!/usr/bin/env python3
"""
Servo Channel Test Script

This script tests a servo channel by:
1. Setting PWM to first value (default 600 microseconds)
2. Waiting specified delay (default 5 seconds)
3. Setting PWM to second value (default 1000 microseconds)

Uses ROS2 service calls through MAVROS bridge.
Parameters can be configured via environment variables or defaults.
"""

import time
import sys
import os

# Get test parameters from environment variables or use defaults
SERVO_CHANNEL = int(os.getenv('SERVO_CHANNEL', '10'))
FIRST_PWM = int(os.getenv('FIRST_PWM', '600'))
SECOND_PWM = int(os.getenv('SECOND_PWM', '1000'))
DELAY_SECONDS = int(os.getenv('DELAY_SECONDS', '5'))
TIMEOUT_SECONDS = float(os.getenv('TIMEOUT_SECONDS', '5.0'))

# Add the Backend directory to Python path to import mavros_bridge
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Backend'))

try:
    from mavros_bridge import MavrosBridge, ServiceError
except ImportError as e:
    print(f"Error importing MavrosBridge: {e}")
    print("Make sure you're running this from the NRP_ROS directory")
    sys.exit(1)


def test_servo_channel():
    """
    Test servo channel with specified PWM values and timing.
    """
    print(f"=== Servo Channel {SERVO_CHANNEL} Test ===")
    print(f"Parameters: PWM1={FIRST_PWM}μs → Wait {DELAY_SECONDS}s → PWM2={SECOND_PWM}μs")
    print("Initializing MAVROS bridge connection...")
    
    # Initialize MAVROS bridge
    try:
        bridge = MavrosBridge()
        bridge.connect()
        print("✓ MAVROS bridge connected successfully")
    except Exception as e:
        print(f"✗ Failed to connect to MAVROS bridge: {e}")
        print("Make sure MAVROS is running and rosbridge_server is available")
        return False
    
    try:
        # Test sequence
        print(f"\n--- Test Sequence for Servo Channel {SERVO_CHANNEL} ---")
        
        # Step 1: Set PWM to first value
        print(f"Step 1: Setting servo {SERVO_CHANNEL} to {FIRST_PWM} μs PWM...")
        try:
            response = bridge.set_servo(SERVO_CHANNEL, FIRST_PWM, TIMEOUT_SECONDS)
            if response.get('success', False):
                print(f"✓ Servo command sent successfully ({FIRST_PWM} μs)")
                print(f"  Response: {response}")
            else:
                print(f"✗ Servo command failed: {response}")
                return False
        except ServiceError as e:
            print(f"✗ Service error: {e}")
            return False
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            return False
        
        # Step 2: Wait specified delay
        print(f"\nStep 2: Waiting {DELAY_SECONDS} seconds...")
        for i in range(DELAY_SECONDS, 0, -1):
            print(f"  {i} seconds remaining...", end='\r')
            time.sleep(1)
        print("  Wait complete!             ")
        
        # Step 3: Set PWM to second value
        print(f"\nStep 3: Setting servo {SERVO_CHANNEL} to {SECOND_PWM} μs PWM...")
        try:
            response = bridge.set_servo(SERVO_CHANNEL, SECOND_PWM, TIMEOUT_SECONDS)
            if response.get('success', False):
                print(f"✓ Servo command sent successfully ({SECOND_PWM} μs)")
                print(f"  Response: {response}")
            else:
                print(f"✗ Servo command failed: {response}")
                return False
        except ServiceError as e:
            print(f"✗ Service error: {e}")
            return False
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            return False
        
        print("\n=== Test Complete ===")
        print(f"✓ Servo channel {SERVO_CHANNEL} test completed successfully!")
        return True
        
    except KeyboardInterrupt:
        print("\n\n⚠ Test interrupted by user")
        return False
    
    finally:
        # Clean up connection
        try:
            bridge.disconnect()
            print("✓ MAVROS bridge disconnected")
        except:
            pass


def print_usage():
    """Print usage information."""
    print("Servo Channel Test Script")
    print("Usage: python3 test_servo_10.py")
    print("")
    print("This script will:")
    print(f"1. Connect to MAVROS via rosbridge")
    print(f"2. Set servo channel {SERVO_CHANNEL} to {FIRST_PWM} μs PWM")
    print(f"3. Wait {DELAY_SECONDS} seconds")
    print(f"4. Set servo channel {SERVO_CHANNEL} to {SECOND_PWM} μs PWM")
    print("")
    print("Configuration (via environment variables):")
    print(f"- SERVO_CHANNEL={SERVO_CHANNEL}")
    print(f"- FIRST_PWM={FIRST_PWM}")
    print(f"- SECOND_PWM={SECOND_PWM}")
    print(f"- DELAY_SECONDS={DELAY_SECONDS}")
    print(f"- TIMEOUT_SECONDS={TIMEOUT_SECONDS}")
    print("")
    print("Prerequisites:")
    print("- MAVROS must be running")
    print("- rosbridge_server must be running (port 9090)")
    print("- ArduPilot/PX4 autopilot must be connected")
    print("")
    print("Safety Notes:")
    print(f"- Ensure servo channel {SERVO_CHANNEL} is properly configured")
    print(f"- Check that no critical systems are connected to channel {SERVO_CHANNEL}")
    print(f"- PWM values: {FIRST_PWM}μs and {SECOND_PWM}μs should be within safe servo range")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help', 'help']:
        print_usage()
        sys.exit(0)
    
    print(f"Starting servo channel {SERVO_CHANNEL} test...")
    print("Press Ctrl+C to interrupt at any time")
    print("")
    
    success = test_servo_channel()
    
    if success:
        print("\n🎉 Test completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Test failed!")
        sys.exit(1)