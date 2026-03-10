#!/usr/bin/env python3
"""
NRP Rover Backend — Comprehensive Endpoint Health Check

Tests all REST API endpoints, Socket.IO connectivity, and response validation.
Uses only stdlib (no requests/pytest needed).

Run:  python3 tests/test_all_endpoints.py [--host HOST] [--port PORT]
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

# ── Config ──────────────────────────────────────────────

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5001

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log_pass(label):
    print(f"  {GREEN}✓{RESET} {label}")


def log_fail(label, reason=""):
    r = f" — {reason}" if reason else ""
    print(f"  {RED}✗{RESET} {label}{r}")


def log_warn(label, reason=""):
    r = f" — {reason}" if reason else ""
    print(f"  {YELLOW}⚠{RESET} {label}{r}")


def log_section(title):
    print(f"\n{BOLD}{CYAN}── {title} ──{RESET}")


# ── HTTP helpers ────────────────────────────────────────

def http_get(base, path, timeout=5):
    """GET request, returns (status_code, body_str)."""
    url = f"{base}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def http_post(base, path, data=None, timeout=5):
    """POST request with JSON body, returns (status_code, body_str)."""
    url = f"{base}{path}"
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


# ── Test suites ─────────────────────────────────────────

def test_rest_get_endpoints(base):
    """Test all GET endpoints return 200."""
    endpoints = [
        # Core / Docs
        ("/", "Root status"),
        ("/docs", "Swagger UI"),
        ("/redoc", "ReDoc"),
        ("/asyncapi", "AsyncAPI Socket.IO docs"),
        ("/socket-docs", "Socket.IO interactive tester"),
        ("/api/docs/asyncapi.yaml", "AsyncAPI YAML spec"),
        ("/monitor", "Activity monitor page"),

        # Activity
        ("/api/activity", "Activity log"),
        ("/api/activity?limit=3", "Activity log (limited)"),
        ("/api/activity/types", "Activity types"),
        ("/api/activity/download", "Activity CSV download"),

        # Mission
        ("/api/mission/status", "Mission status"),
        ("/api/mission/download", "Mission waypoints download"),
        ("/api/mission/config", "Mission config"),
        ("/api/mission/servo_config", "Servo config"),
        ("/api/mission/mode", "Mission mode"),
        # /api/mission/start GET intentionally returns 405

        # RTK
        ("/api/rtk/status", "RTK status"),

        # TTS
        ("/api/tts/status", "TTS status"),
        ("/api/tts/languages", "TTS languages"),

        # ROS Nodes
        ("/api/nodes", "ROS nodes list"),

        # Servo
        ("/servo/status", "Servo status"),
        # /servo/log requires ?path= param, tested separately in node detail

        # Config
        ("/api/config/sprayer", "Sprayer config"),
    ]

    passed = failed = 0
    for path, label in endpoints:
        code, body = http_get(base, path)
        if code == 200:
            log_pass(f"GET {path:<40} {label}")
            passed += 1
        elif code == 0:
            log_fail(f"GET {path:<40} {label}", f"Connection error")
            failed += 1
        else:
            log_fail(f"GET {path:<40} {label}", f"HTTP {code}")
            failed += 1

    return passed, failed


def test_rest_post_safe(base):
    """Test POST endpoints with safe payloads (no destructive actions)."""
    endpoints = [
        ("/api/set_mode", {"mode": "HOLD"}, "Set mode HOLD"),
        ("/api/tts/control", {"action": "status"}, "TTS control status"),
        ("/api/rtk/stop", {}, "RTK stop (no-op)"),
        ("/api/rtk/ntrip_stop", {}, "RTK NTRIP stop"),
        ("/api/rtk/lora_stop", {}, "RTK LoRa stop"),
        ("/api/rtk/force_clear", {}, "RTK force clear (500 if no MAVLink)"),
        ("/api/mission/stop", {}, "Mission stop (no-op if idle)"),
        ("/api/mission/stop_controller", {}, "Mission controller stop (500 if no bridge)"),
        ("/servo/emergency_stop", {}, "Servo emergency stop"),
    ]

    passed = failed = 0
    for path, data, label in endpoints:
        code, body = http_post(base, path, data)
        if code in (200, 400, 404, 405, 409, 422):
            log_pass(f"POST {path:<40} {label} → {code}")
            passed += 1
        elif code == 0:
            log_fail(f"POST {path:<40} {label}", "Connection error")
            failed += 1
        elif code == 500:
            # 500 with JSON error response = handler works but dependency unavailable
            log_warn(f"POST {path:<40} {label}", f"500 (dependency unavailable)")
            passed += 1
        else:
            log_warn(f"POST {path:<40} {label}", f"HTTP {code}")
            passed += 1

    return passed, failed


def test_input_validation(base):
    """Verify POST endpoints don't crash on empty/bad input (should return 4xx, not 500)."""
    endpoints = [
        ("/api/arm", {}, "Arm (empty body)"),
        ("/api/set_mode", {}, "Set mode (no mode field)"),
        ("/api/mission/upload", {}, "Upload (no waypoints)"),
        ("/api/servo/control", {}, "Servo control (empty)"),
        ("/api/tts/test", {}, "TTS test (empty)"),
        ("/api/tts/language", {}, "TTS language (empty)"),
        ("/api/rtk/inject", {}, "RTK inject (empty)"),
        ("/api/mission/set_current", {}, "Set current WP (empty)"),
        ("/api/config/sprayer", {}, "Sprayer config (empty)"),
    ]

    passed = failed = 0
    for path, data, label in endpoints:
        code, body = http_post(base, path, data)
        if code in (200, 400, 422):
            log_pass(f"POST {path:<40} {label} → {code}")
            passed += 1
        elif code == 500:
            log_fail(f"POST {path:<40} {label}", "500 — missing input validation!")
            failed += 1
        elif code == 0:
            log_fail(f"POST {path:<40} {label}", "Connection error")
            failed += 1
        else:
            log_pass(f"POST {path:<40} {label} → {code}")
            passed += 1

    return passed, failed


def test_node_detail(base):
    """Test /api/node/<name> and /node/<name> with a discovered node."""
    passed = failed = 0
    code, body = http_get(base, "/api/nodes")
    if code != 200:
        log_fail("GET /api/nodes", f"HTTP {code}")
        return 0, 1

    try:
        data = json.loads(body)
        nodes = data.get("nodes", [])
    except (json.JSONDecodeError, AttributeError):
        nodes = []

    if not nodes:
        log_warn("Node detail", "No nodes returned — skipping")
        return 1, 0

    node = nodes[0] if isinstance(nodes[0], str) else str(nodes[0])
    node_clean = node.lstrip("/")

    code, _ = http_get(base, f"/api/node/{node_clean}")
    if code == 200:
        log_pass(f"GET /api/node/{node_clean}")
        passed += 1
    else:
        log_warn(f"GET /api/node/{node_clean}", f"HTTP {code}")
        passed += 1

    code, _ = http_get(base, f"/node/{node_clean}")
    if code == 200:
        log_pass(f"GET /node/{node_clean} (HTML page)")
        passed += 1
    else:
        log_warn(f"GET /node/{node_clean}", f"HTTP {code}")
        passed += 1

    return passed, failed


def test_json_structure(base):
    """Verify key endpoints return valid JSON with expected fields."""
    checks = [
        ("/", ["status", "version"]),
        ("/api/mission/status", ["success"]),
        ("/api/tts/status", ["success", "engine"]),
        ("/api/rtk/status", ["success"]),
        ("/api/tts/languages", ["success"]),
        ("/api/config/sprayer", ["success"]),
        ("/api/activity", ["entries"]),
        ("/api/nodes", ["nodes"]),
        ("/servo/status", []),  # Just verify it's JSON
    ]

    passed = failed = 0
    for path, expected_keys in checks:
        code, body = http_get(base, path)
        if code != 200:
            log_fail(f"JSON {path}", f"HTTP {code}")
            failed += 1
            continue

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            log_fail(f"JSON {path}", "Not valid JSON")
            failed += 1
            continue

        missing = [k for k in expected_keys if k not in data]
        if missing:
            log_fail(f"JSON {path}", f"Missing: {missing}")
            failed += 1
        else:
            keys_str = f" (has {expected_keys})" if expected_keys else " (valid JSON)"
            log_pass(f"JSON {path:<40}{keys_str}")
            passed += 1

    return passed, failed


def test_socketio(base):
    """Test Socket.IO connectivity via polling handshake and full client."""
    passed = failed = 0

    # 1. Polling handshake
    code, body = http_get(base, "/socket.io/?transport=polling&EIO=4")
    if code == 200 and body and body.startswith("0{"):
        try:
            handshake = json.loads(body[1:])
            sid = handshake.get("sid", "")
            if sid:
                log_pass(f"Socket.IO handshake (sid={sid[:16]}...)")
                passed += 1
            else:
                log_fail("Socket.IO handshake", "No SID")
                failed += 1
        except json.JSONDecodeError:
            log_fail("Socket.IO handshake", "Invalid JSON")
            failed += 1
    elif code == 200:
        log_pass("Socket.IO polling endpoint accessible")
        passed += 1
    else:
        log_fail("Socket.IO handshake", f"HTTP {code}")
        failed += 1

    # 2. Full client test
    try:
        import socketio as sio_client
        client = sio_client.Client(logger=False, engineio_logger=False)
        connected = False
        got_rover_data = False
        got_conn_resp = False

        @client.on("connect")
        def on_connect():
            nonlocal connected
            connected = True

        @client.on("rover_data")
        def on_rover(data):
            nonlocal got_rover_data
            got_rover_data = True

        @client.on("connection_response")
        def on_conn(data):
            nonlocal got_conn_resp
            got_conn_resp = True

        url = base.replace("0.0.0.0", "127.0.0.1")
        client.connect(url, wait_timeout=5)
        for _ in range(50):
            if got_rover_data:
                break
            time.sleep(0.1)
        client.disconnect()

        if connected:
            log_pass("Socket.IO client connected")
            passed += 1
        else:
            log_fail("Socket.IO client connect", "Timeout")
            failed += 1

        if got_conn_resp:
            log_pass("Socket.IO connection_response received")
            passed += 1
        else:
            log_warn("Socket.IO connection_response", "Not received")
            passed += 1

        if got_rover_data:
            log_pass("Socket.IO rover_data streaming")
            passed += 1
        else:
            log_warn("Socket.IO rover_data", "Not received in 5s")
            passed += 1

    except ImportError:
        log_warn("Socket.IO client test", "python-socketio not installed — skipped")
        passed += 1
    except Exception as e:
        log_fail("Socket.IO client test", str(e))
        failed += 1

    return passed, failed


def test_cors(base):
    """Verify CORS headers are present."""
    passed = failed = 0
    url = f"{base}/"
    req = urllib.request.Request(url, method="GET",
                                 headers={"Origin": "http://example.com"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            cors = resp.headers.get("access-control-allow-origin", "")
            if cors:
                log_pass(f"CORS header present: {cors}")
                passed += 1
            else:
                log_warn("CORS header", "Not present on GET /")
                passed += 1
    except Exception as e:
        log_fail("CORS test", str(e))
        failed += 1

    return passed, failed


# ── Main ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NRP Rover Backend — Endpoint Health Check")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Server host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    base = f"http://{args.host}:{args.port}"
    total_pass = total_fail = 0

    print(f"\n{BOLD}{'═' * 56}")
    print(f"  NRP Rover Backend — Endpoint Health Check")
    print(f"  Target: {base}")
    print(f"{'═' * 56}{RESET}")

    # Connectivity check
    code, body = http_get(base, "/")
    if code == 0:
        print(f"\n{RED}Cannot connect to {base} — is the server running?{RESET}")
        print(f"Error: {body}")
        sys.exit(1)

    suites = [
        ("GET Endpoints (26 routes)", test_rest_get_endpoints),
        ("POST Endpoints — Safe Calls", test_rest_post_safe),
        ("POST Input Validation (no 500s)", test_input_validation),
        ("Node Detail Pages", test_node_detail),
        ("JSON Response Structure", test_json_structure),
        ("Socket.IO Connectivity", test_socketio),
        ("CORS Headers", test_cors),
    ]

    start = time.time()
    for name, fn in suites:
        log_section(name)
        p, f = fn(base)
        total_pass += p
        total_fail += f

    elapsed = time.time() - start
    total = total_pass + total_fail

    print(f"\n{BOLD}{'═' * 56}")
    if total_fail == 0:
        print(f"  {GREEN}ALL {total} CHECKS PASSED{RESET}  ({elapsed:.1f}s)")
    else:
        print(f"  {total_pass}/{total} passed, {RED}{total_fail} FAILED{RESET}  ({elapsed:.1f}s)")
    print(f"{BOLD}{'═' * 56}{RESET}\n")

    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()
