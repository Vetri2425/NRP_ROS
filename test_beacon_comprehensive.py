#!/usr/bin/env python3
"""
Comprehensive test for the rover beacon implementation.
Tests both the beacon broadcasting and the /api/ping endpoint.
"""

import socket
import json
import time
import requests
import sys
import os

def test_beacon_reception(timeout=5):
    """Test receiving beacon broadcasts."""
    print("🔍 Testing beacon reception...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    
    try:
        sock.bind(('', 5002))
        print(f"   Listening on UDP port 5002 for {timeout} seconds...")
        
        data, addr = sock.recvfrom(1024)
        beacon = json.loads(data.decode('utf-8'))
        
        print(f"✅ Beacon received from {addr[0]}:{addr[1]}")
        print(f"   Rover ID: {beacon.get('rover_id')}")
        print(f"   Rover Name: {beacon.get('rover_name')}")
        print(f"   IP: {beacon.get('ip')}")
        print(f"   Port: {beacon.get('port')}")
        print(f"   Type: {beacon.get('type')}")
        print(f"   Version: {beacon.get('version')}")
        print(f"   Uptime: {beacon.get('uptime')} seconds")
        
        return True, beacon
        
    except socket.timeout:
        print("❌ No beacon received within timeout")
        return False, None
    except Exception as e:
        print(f"❌ Error receiving beacon: {e}")
        return False, None
    finally:
        sock.close()

def test_ping_endpoint(ip="localhost", port=5001):
    """Test the /api/ping endpoint."""
    print(f"🔍 Testing /api/ping endpoint at {ip}:{port}...")
    
    try:
        url = f"http://{ip}:{port}/api/ping"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Ping endpoint responded successfully")
            print(f"   Status: {data.get('status')}")
            print(f"   Rover ID: {data.get('rover_id')}")
            print(f"   Rover Name: {data.get('rover_name')}")
            print(f"   Timestamp: {data.get('timestamp')}")
            return True, data
        else:
            print(f"❌ Ping endpoint returned status {response.status_code}")
            print(f"   Response: {response.text}")
            return False, None
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to {ip}:{port}")
        return False, None
    except Exception as e:
        print(f"❌ Error testing ping endpoint: {e}")
        return False, None

def main():
    """Run comprehensive beacon tests."""
    print("🚀 Starting comprehensive rover beacon tests...\n")
    
    # Test 1: Beacon reception
    beacon_success, beacon_data = test_beacon_reception()
    print()
    
    # Test 2: Ping endpoint
    ping_success, ping_data = test_ping_endpoint()
    print()
    
    # Test 3: Cross-validation (if both work, check consistency)
    if beacon_success and ping_success:
        print("🔍 Cross-validating beacon and ping data...")
        
        beacon_rover_id = beacon_data.get('rover_id')
        ping_rover_id = ping_data.get('rover_id')
        
        beacon_ip = beacon_data.get('ip')
        beacon_port = beacon_data.get('port')
        
        if beacon_rover_id == ping_rover_id:
            print(f"✅ Rover ID matches: {beacon_rover_id}")
        else:
            print(f"❌ Rover ID mismatch: beacon='{beacon_rover_id}', ping='{ping_rover_id}'")
        
        # Test ping endpoint using beacon IP
        if beacon_ip and beacon_port:
            print(f"🔍 Testing ping endpoint using beacon IP {beacon_ip}:{beacon_port}...")
            ping_success_2, ping_data_2 = test_ping_endpoint(beacon_ip, beacon_port)
            if ping_success_2:
                print("✅ Ping endpoint accessible via beacon IP")
            else:
                print("❌ Ping endpoint not accessible via beacon IP")
        
        print()
    
    # Summary
    print("📊 Test Summary:")
    print(f"   Beacon reception: {'✅ PASS' if beacon_success else '❌ FAIL'}")
    print(f"   Ping endpoint: {'✅ PASS' if ping_success else '❌ FAIL'}")
    
    if beacon_success and ping_success:
        print("\n🎉 All tests PASSED! Rover beacon system is working correctly.")
        print("\nThe tablet should be able to:")
        print("1. Discover rovers via UDP beacon broadcasts on port 5002")
        print("2. Verify connectivity via /api/ping endpoint")
        return 0
    else:
        print("\n❌ Some tests FAILED. Check the server logs and configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())