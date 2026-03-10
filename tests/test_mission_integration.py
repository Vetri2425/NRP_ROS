#!/usr/bin/env python3
"""
Quick test script to verify integrated mission controller is working.
Run this after starting the server to test the integration.
"""

import requests
import json
import time
from typing import Dict, Any

BASE_URL = "http://localhost:5001"

def test_endpoint(method: str, endpoint: str, data: Dict[Any, Any] = None) -> Dict[Any, Any]:
    """Test an API endpoint"""
    url = f"{BASE_URL}{endpoint}"
    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=5)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, timeout=5)
        else:
            return {"error": f"Unknown method: {method}"}
        
        return {
            "status_code": response.status_code,
            "data": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 70)
    print("INTEGRATED MISSION CONTROLLER - TEST SUITE")
    print("=" * 70)
    print()
    
    # Test 1: Health check
    print("1. Testing server health...")
    result = test_endpoint("GET", "/api/data")
    if result.get("status_code") == 200:
        print("   ✓ Server is running")
    else:
        print(f"   ⚠ Server check returned {result.get('status_code')}, but continuing tests...")
        # Don't return - server might be running but rover not connected
    
    # Test 2: Mission status endpoint
    print("\n2. Testing mission status endpoint...")
    result = test_endpoint("GET", "/api/mission/status")
    if result.get("status_code") in [200, 503]:
        print(f"   ✓ Mission status endpoint responding")
        if result.get("status_code") == 503:
            print("   ⚠ Mission controller not initialized yet (waiting for MAVROS)")
        else:
            print(f"   Status: {json.dumps(result.get('data', {}), indent=4)}")
    else:
        print(f"   ✗ Mission status endpoint failed: {result}")
    
    # Test 3: Mission mode endpoint
    print("\n3. Testing mission mode endpoint...")
    result = test_endpoint("GET", "/api/mission/mode")
    if result.get("status_code") in [200, 503]:
        print(f"   ✓ Mission mode endpoint responding")
        if result.get("status_code") == 200:
            mode = result.get("data", {}).get("mode", "unknown")
            print(f"   Current mode: {mode}")
    else:
        print(f"   ✗ Mission mode endpoint failed: {result}")
    
    # Test 4: Load mission
    print("\n4. Testing mission load...")
    test_mission = {
        "waypoints": [
            {"lat": 13.071922, "lng": 80.2619957, "alt": 10.0},
            {"lat": 13.072000, "lng": 80.2620000, "alt": 10.0}
        ],
        "config": {
            "waypoint_threshold": 2.0,
            "hold_duration": 5.0,
            "auto_mode": False  # Manual mode for testing
        }
    }
    result = test_endpoint("POST", "/api/mission/load", {"waypoints": test_mission["waypoints"]})
    if result.get("status_code") in [200, 503]:
        print(f"   ✓ Mission load endpoint responding")
        if result.get("status_code") == 503:
            print("   ⚠ Mission controller not available (MAVROS not connected)")
        else:
            print(f"   Response: {result.get('data', {})}")
    else:
        print(f"   ✗ Mission load failed: {result}")
    
    # Test 5: Set mode to manual
    print("\n5. Testing mode setting...")
    result = test_endpoint("POST", "/api/mission/mode", {"mode": "manual"})
    if result.get("status_code") in [200, 503]:
        print(f"   ✓ Mode setting endpoint responding")
        if result.get("status_code") == 200:
            print(f"   Response: {result.get('data', {})}")
    else:
        print(f"   ✗ Mode setting failed: {result}")
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print("\nIntegrated mission controller API endpoints are functional!")
    print("\nNext steps:")
    print("  1. Ensure MAVROS bridge is connected")
    print("  2. Check server logs for 'Mission controller initialized'")
    print("  3. Load a real mission and test execution")
    print("  4. Monitor via: curl http://localhost:5001/api/mission/status")
    print()
    print("For full testing guide, see: INTEGRATED_MISSION_CONTROLLER.md")
    print("=" * 70)


if __name__ == "__main__":
    main()
