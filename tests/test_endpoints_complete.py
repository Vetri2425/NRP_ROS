#!/usr/bin/env python3
"""
NRP Backend Endpoint & SocketIO Test Suite
Tests both HTTP REST endpoints and SocketIO event-based communication
"""

import requests
import json
import time
import threading
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import socketio

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

# Backend Configuration
BACKEND_HOST = "localhost"
BACKEND_PORT = 5001
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

# Test Results Storage
test_results: Dict[str, Dict] = {}
total_tests = 0
passed_tests = 0
failed_tests = 0

def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text.center(70)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.RESET}\n")

def print_section(text: str):
    """Print a formatted section header"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}▶ {text}{Colors.RESET}")
    print(f"{Colors.CYAN}{'-'*70}{Colors.RESET}")

def print_success(text: str, details: str = ""):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {text}{Colors.RESET}")
    if details:
        print(f"  {Colors.GREEN}{details}{Colors.RESET}")

def print_error(text: str, details: str = ""):
    """Print error message"""
    print(f"{Colors.RED}✗ {text}{Colors.RESET}")
    if details:
        print(f"  {Colors.RED}{details}{Colors.RESET}")

def print_warning(text: str, details: str = ""):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.RESET}")
    if details:
        print(f"  {Colors.YELLOW}{details}{Colors.RESET}")

def print_info(text: str):
    """Print info message"""
    print(f"{Colors.BLUE}ℹ {text}{Colors.RESET}")

def test_http_endpoint(
    method: str,
    endpoint: str,
    name: str,
    data: Optional[Dict] = None,
    expected_status: int = 200,
    timeout: int = 5
) -> Tuple[bool, str, Optional[Dict]]:
    """Test a single HTTP endpoint"""
    global total_tests, passed_tests, failed_tests
    
    total_tests += 1
    url = f"{BACKEND_URL}{endpoint}"
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=timeout)
        elif method.upper() == "POST":
            response = requests.post(
                url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=timeout
            )
        else:
            return False, f"Unsupported method: {method}", None
        
        if response.status_code == expected_status:
            passed_tests += 1
            resp_data = response.json() if response.text else {}
            return True, f"Status {response.status_code}", resp_data
        else:
            failed_tests += 1
            try:
                error_data = response.json()
                error_msg = error_data.get("error", error_data.get("message", "Unknown error"))
            except:
                error_msg = response.text[:200] if response.text else "No response body"
            return False, f"Expected {expected_status}, got {response.status_code}: {error_msg}", None
    
    except requests.exceptions.ConnectionError as e:
        failed_tests += 1
        return False, f"Connection failed", None
    except requests.exceptions.Timeout as e:
        failed_tests += 1
        return False, f"Request timeout after {timeout}s", None
    except Exception as e:
        failed_tests += 1
        return False, f"Error: {str(e)}", None

def test_socketio_events():
    """Test SocketIO event-based communication"""
    print_section("SocketIO Event Communication")
    
    global total_tests, passed_tests, failed_tests
    
    try:
        sio = socketio.Client()
        event_received = threading.Event()
        response_data = {}
        
        @sio.event
        def connect():
            print_success("SocketIO connected", "Client connected successfully")
        
        @sio.on('mission_status')
        def on_mission_status(data):
            response_data['mission_status'] = data
            event_received.set()
        
        @sio.event
        def disconnect():
            print_info("SocketIO disconnected")
        
        # Connect to SocketIO server
        print_info("Connecting to SocketIO server...")
        sio.connect(BACKEND_URL, transports=['websocket'])
        time.sleep(0.5)
        
        # Test 1: Subscribe to mission status
        total_tests += 1
        print_info("Testing: subscribe_mission_status event")
        try:
            sio.emit('subscribe_mission_status')
            if event_received.wait(timeout=3):
                passed_tests += 1
                print_success("subscribe_mission_status event", "Received mission status update")
                data = response_data.get('mission_status', {})
                if isinstance(data, dict):
                    state = data.get('mission_state', 'unknown')
                    waypoints = data.get('total_waypoints', 0)
                    print_info(f"Mission State: {state}, Waypoints: {waypoints}")
            else:
                failed_tests += 1
                print_warning("subscribe_mission_status event", "No response received within timeout")
        except Exception as e:
            failed_tests += 1
            print_error("subscribe_mission_status event", str(e))
        
        # Test 2: Ping event (keep-alive)
        total_tests += 1
        print_info("Testing: ping event")
        try:
            sio.emit('ping')
            print_success("ping event", "Ping sent successfully")
            passed_tests += 1
        except Exception as e:
            failed_tests += 1
            print_error("ping event", str(e))
        
        # Disconnect
        sio.disconnect()
        
    except Exception as e:
        print_error("SocketIO connection failed", str(e))
        print_info("SocketIO may not be fully available or backend is not running")

def test_tts_endpoints():
    """Test TTS HTTP endpoints"""
    print_section("TTS Voice Control Endpoints (HTTP REST)")
    
    # Test 1: GET /api/tts/status
    success, msg, data = test_http_endpoint(
        "GET", 
        "/api/tts/status", 
        "TTS Status",
        expected_status=200
    )
    
    if success:
        print_success("GET /api/tts/status", msg)
        if data:
            enabled = data.get("enabled", "unknown")
            engine = data.get("engine", "unknown")
            language = data.get("language", "unknown")
            print_info(f"Configuration: enabled={enabled}, engine={engine}, language={language}")
    else:
        print_error("GET /api/tts/status", msg)
    
    test_results["tts_status"] = {"success": success, "message": msg, "data": data}
    
    # Test 2: POST /api/tts/control (enable)
    success, msg, data = test_http_endpoint(
        "POST",
        "/api/tts/control",
        "TTS Control - Enable",
        data={"enabled": True},
        expected_status=200
    )
    
    if success:
        print_success("POST /api/tts/control (enable)", msg)
        if data and data.get("message"):
            print_info(f"Response: {data.get('message')}")
    else:
        print_error("POST /api/tts/control (enable)", msg)
    
    test_results["tts_control_enable"] = {"success": success, "message": msg}
    
    # Test 3: POST /api/tts/control (disable)
    success, msg, data = test_http_endpoint(
        "POST",
        "/api/tts/control",
        "TTS Control - Disable",
        data={"enabled": False},
        expected_status=200
    )
    
    if success:
        print_success("POST /api/tts/control (disable)", msg)
        if data and data.get("message"):
            print_info(f"Response: {data.get('message')}")
    else:
        print_error("POST /api/tts/control (disable)", msg)
    
    test_results["tts_control_disable"] = {"success": success, "message": msg}
    
    # Test 4: POST /api/tts/test
    success, msg, data = test_http_endpoint(
        "POST",
        "/api/tts/test",
        "TTS Test",
        data={"message": "Backend endpoint test successful"},
        expected_status=200
    )
    
    if success:
        print_success("POST /api/tts/test", msg)
        if data and data.get("message"):
            print_info(f"Response: {data.get('message')}")
    else:
        print_error("POST /api/tts/test", msg)
    
    test_results["tts_test"] = {"success": success, "message": msg}

def test_mission_endpoints():
    """Test Mission endpoints"""
    print_section("Mission Control (SocketIO Events)")
    
    global total_tests, passed_tests, failed_tests
    
    try:
        sio = socketio.Client()
        
        @sio.event
        def connect():
            pass
        
        print_info("Testing mission events via SocketIO...")
        sio.connect(BACKEND_URL, transports=['websocket'])
        time.sleep(0.5)
        
        # Test: get_mission_status event
        total_tests += 1
        try:
            sio.emit('get_mission_status')
            print_success("get_mission_status event", "Event emitted successfully")
            passed_tests += 1
        except Exception as e:
            failed_tests += 1
            print_error("get_mission_status event", str(e))
        
        sio.disconnect()
        
    except Exception as e:
        print_error("Mission SocketIO test failed", str(e))

def check_backend():
    """Check if backend is running"""
    print_section("Backend Availability Check")
    
    try:
        response = requests.get(f"{BACKEND_URL}/", timeout=3)
        print_success("Backend is reachable", f"Status: {response.status_code}")
        return True
    except:
        print_error("Backend is NOT reachable", f"Cannot connect to {BACKEND_URL}")
        print_info("Make sure the backend is running with: python Backend/server.py")
        return False

def generate_report():
    """Generate comprehensive test report"""
    print_header("TEST SUMMARY REPORT")
    
    print(f"Total Tests: {total_tests}")
    print(f"{Colors.GREEN}Passed: {passed_tests}{Colors.RESET}")
    print(f"{Colors.RED}Failed: {failed_tests}{Colors.RESET}")
    
    if total_tests > 0:
        success_rate = (passed_tests / total_tests) * 100
        print(f"Success Rate: {success_rate:.1f}%")
    
    print_section("HTTP REST Endpoints Status")
    
    http_tests = ["tts_status", "tts_control_enable", "tts_control_disable", "tts_test"]
    http_pass = sum(1 for t in http_tests if t in test_results and test_results[t].get("success"))
    
    print(f"HTTP REST Endpoints: {http_pass}/{len(http_tests)}")
    for test in http_tests:
        if test in test_results:
            result = test_results[test]
            icon = Colors.GREEN + "✓" if result.get("success") else Colors.RED + "✗"
            print(f"  {icon}{Colors.RESET} {test}: {result.get('message', 'Unknown')}")
    
    print_section("Backend Architecture Summary")
    
    print_info("Communication Methods:")
    print_info("• HTTP REST: Limited endpoints (/api/tts/*)")
    print_info("• SocketIO: Primary method for mission/telemetry (real-time bidirectional)")
    
    print_section("Recommendations")
    
    if failed_tests == 0:
        print_success("All tested endpoints are working correctly!", "")
        print_info("Backend is fully operational")
    else:
        print_warning(f"Found {failed_tests} issues", "")
        print_info("1. Verify backend is running: ps aux | grep server.py")
        print_info("2. Check backend logs for errors")
        print_info("3. Ensure port 5001 is open and not blocked")

def main():
    """Main test execution"""
    print_header("NRP BACKEND ENDPOINT & SOCKETIO TEST SUITE")
    print_info(f"Testing Backend: {BACKEND_URL}")
    print_info(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not check_backend():
        print_header("BACKEND NOT AVAILABLE")
        return 1
    
    # Run HTTP endpoint tests
    test_tts_endpoints()
    
    # Run SocketIO event tests
    test_socketio_events()
    test_mission_endpoints()
    
    # Generate final report
    generate_report()
    
    return 0 if failed_tests == 0 else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
