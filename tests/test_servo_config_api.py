#!/usr/bin/env python3
"""
Test script for servo configuration API endpoints
"""

import requests
import json
import time

BASE_URL = "http://localhost:5000"

def print_response(title, response):
    """Pretty print API response"""
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    print(f"Status Code: {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except:
        print(response.text)
    print()

def test_get_servo_config():
    """Test GET /api/mission/servo_config"""
    print("\n🔍 TEST 1: Get Current Servo Configuration")
    response = requests.get(f"{BASE_URL}/api/mission/servo_config")
    print_response("GET /api/mission/servo_config", response)
    return response.json().get('data', {}) if response.status_code == 200 else {}

def test_update_servo_config():
    """Test POST /api/mission/servo_config"""
    print("\n✏️ TEST 2: Update Servo Configuration")
    
    new_config = {
        "servo_channel": 10,
        "servo_pwm_on": 1500,
        "servo_pwm_off": 1100,
        "servo_spray_duration": 1.0,
        "servo_delay_after": 3.0,
        "servo_enabled": True
    }
    
    print(f"Updating with: {json.dumps(new_config, indent=2)}")
    response = requests.post(
        f"{BASE_URL}/api/mission/servo_config",
        json=new_config,
        headers={"Content-Type": "application/json"}
    )
    print_response("POST /api/mission/servo_config", response)

def test_partial_update():
    """Test partial update (only some parameters)"""
    print("\n✏️ TEST 3: Partial Update (Only spray duration)")
    
    partial_config = {
        "servo_spray_duration": 2.5
    }
    
    response = requests.post(
        f"{BASE_URL}/api/mission/servo_config",
        json=partial_config,
        headers={"Content-Type": "application/json"}
    )
    print_response("POST /api/mission/servo_config (partial)", response)

def test_load_mission_with_config():
    """Test loading mission with servo config"""
    print("\n📦 TEST 4: Load Mission with Servo Config")
    
    mission_data = {
        "waypoints": [
            {"lat": 13.071922, "lng": 80.2619957, "alt": 10.0},
            {"lat": 13.071932, "lng": 80.2619967, "alt": 10.0},
            {"lat": 13.071942, "lng": 80.2619977, "alt": 10.0}
        ],
        "servo_channel": 11,
        "servo_pwm_on": 1600,
        "servo_pwm_off": 1200,
        "servo_spray_duration": 0.8,
        "servo_delay_after": 2.5,
        "servo_enabled": True
    }
    
    print(f"Loading mission with {len(mission_data['waypoints'])} waypoints and servo config")
    response = requests.post(
        f"{BASE_URL}/api/mission/load_controller",
        json=mission_data,
        headers={"Content-Type": "application/json"}
    )
    print_response("POST /api/mission/load_controller", response)

def test_disable_servo():
    """Test disabling servo"""
    print("\n🔴 TEST 5: Disable Servo")
    
    response = requests.post(
        f"{BASE_URL}/api/mission/servo_config",
        json={"servo_enabled": False},
        headers={"Content-Type": "application/json"}
    )
    print_response("POST /api/mission/servo_config (disable)", response)

def test_enable_servo():
    """Test re-enabling servo"""
    print("\n🟢 TEST 6: Re-enable Servo")
    
    response = requests.post(
        f"{BASE_URL}/api/mission/servo_config",
        json={"servo_enabled": True},
        headers={"Content-Type": "application/json"}
    )
    print_response("POST /api/mission/servo_config (enable)", response)

def main():
    """Run all tests"""
    print("="*60)
    print("SERVO CONFIGURATION API TESTS")
    print("="*60)
    print(f"Target: {BASE_URL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Test 1: Get current config
        current_config = test_get_servo_config()
        
        # Test 2: Update all parameters
        test_update_servo_config()
        time.sleep(0.5)
        
        # Verify update
        print("\n🔍 Verifying update...")
        test_get_servo_config()
        
        # Test 3: Partial update
        test_partial_update()
        time.sleep(0.5)
        
        # Test 4: Load mission with config
        # Note: This will fail if MAVROS is not connected, but will test the API
        test_load_mission_with_config()
        
        # Test 5 & 6: Disable/Enable servo
        test_disable_servo()
        time.sleep(0.5)
        test_enable_servo()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS COMPLETED")
        print("="*60)
        
    except requests.exceptions.ConnectionError:
        print(f"\n❌ ERROR: Could not connect to {BASE_URL}")
        print("Make sure the backend server is running!")
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
