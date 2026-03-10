#!/usr/bin/env python3
"""
test_emit_data.py — Verify all rover_data fields emitted to the frontend.

Connects to the live server via Socket.IO, captures 5 rover_data messages,
then validates every field for presence, type, and expected range.
"""

import socketio
import json
import sys
import time
import threading
from typing import Any

# ─── Config ──────────────────────────────────────────────────────────────────
SERVER_URL   = "http://localhost:5001"
SAMPLE_COUNT = 5          # number of rover_data messages to collect
TIMEOUT_SEC  = 60         # give up after this many seconds

# ─── Color helpers ───────────────────────────────────────────────────────────
G = "\033[92m"   # green
R = "\033[91m"   # red
Y = "\033[93m"   # yellow
B = "\033[94m"   # blue
C = "\033[96m"   # cyan
W = "\033[97m"   # white
X = "\033[0m"    # reset
BOLD = "\033[1m"

def ok(msg):  print(f"  {G}✓{X}  {msg}")
def fail(msg):print(f"  {R}✗{X}  {msg}")
def warn(msg):print(f"  {Y}⚠{X}  {msg}")
def hdr(msg): print(f"\n{BOLD}{C}{'─'*66}{X}\n{BOLD}{C}  {msg}{X}\n{C}{'─'*66}{X}")

# ─── Field schema ─────────────────────────────────────────────────────────────
# Each entry: (field_path, expected_type_or_types, nullable, range_or_choices)
# field_path uses dot notation for nested fields, e.g. "position.lat"
FIELD_SCHEMA = [
    # ── Core position ──────────────────────────────────────────────────
    ("position",                  (dict, type(None)), True,  None),
    ("position.lat",              float,              False, (-90.0,   90.0)),
    ("position.lng",              float,              False, (-180.0, 180.0)),
    ("heading",                   (int, float),       False, (0.0, 360.0)),

    # ── Battery ───────────────────────────────────────────────────────
    ("battery",                   (int, float),       False, (-1, 100)),
    ("voltage",                   (int, float),       False, (0.0, 60.0)),
    ("current",                   (int, float),       False, (0.0, 200.0)),

    # ── Vehicle state ─────────────────────────────────────────────────
    ("status",                    str,                False, None),
    ("mode",                      str,                False, None),
    ("rc_connected",              bool,               False, None),
    ("last_heartbeat",            (float, int, type(None)), True, None),
    ("signal_strength",           str,                False, None),

    # ── GPS / RTK ─────────────────────────────────────────────────────
    ("rtk_status",                str,                False, None),
    ("rtk_fix_type",              int,                False, (0, 6)),
    ("rtk_baseline_age",          (int, float),       False, (0.0, None)),
    ("rtk_base_linked",           bool,               False, None),
    ("rtk_baseline",              (dict, type(None)), True,  None),
    ("rtk_baseline_ts",           (float, int, type(None)), True, None),
    ("satellites_visible",        int,                False, (0, 100)),
    ("hrms",                      str,                False, None),
    ("vrms",                      str,                False, None),
    ("groundspeed",               (int, float),       False, (0.0, 50.0)),

    # ── IMU ───────────────────────────────────────────────────────────
    ("imu_status",                str,                False, None),
    ("imu",                       (dict, type(None)), True,  None),
    ("temperature",               (int, float),       False, (-50.0, 100.0)),

    # ── Mission / Waypoints ───────────────────────────────────────────
    ("current_waypoint_id",       (int, type(None)),  True,  None),
    ("activeWaypointIndex",       (int, type(None)),  True,  None),
    ("completedWaypointIds",      list,               False, None),
    ("distanceToNext",            (int, float),       False, None),

    # ── Servo ─────────────────────────────────────────────────────────
    ("servo_output",              (dict, type(None)), True,  None),

    # ── GPS Failsafe ──────────────────────────────────────────────────
    ("gps_failsafe_mode",         str,                False, {"disable","strict","relax"}),
    ("gps_failsafe_triggered",    bool,               False, None),
    ("gps_failsafe_accuracy_error_mm", (int,float),   False, (0.0, None)),
    ("gps_failsafe_servo_suppressed", bool,           False, None),

    # ── Timestamps ────────────────────────────────────────────────────
    ("last_update",               (float, int, type(None)), True, None),

    # ── Network (injected in get_rover_data) ──────────────────────────
    ("network",                          dict,         False, None),
    ("network.connection_type",          str,          False, None),
    ("network.wifi_signal_strength",     (int,float),  False, (-1, 100)),
    ("network.wifi_rssi",                (int,float),  False, (-200, 0)),
    ("network.interface",                str,          False, None),
    ("network.wifi_connected",           bool,         False, None),
    ("network.lora_connected",           bool,         False, None),

    # ── Manual control (injected in get_rover_data) ───────────────────
    ("manual_control",                   dict,         False, None),
    ("manual_control.active",            bool,         False, None),
]


def _get_nested(data: dict, path: str) -> tuple[bool, Any]:
    """Walk dot-separated path.  Returns (found, value)."""
    parts = path.split(".")
    cur = data
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def validate_sample(sample: dict, index: int) -> tuple[int, int]:
    """Return (passed, failed) counts for one rover_data message."""
    passed = failed = 0
    for path, expected_type, nullable, constraint in FIELD_SCHEMA:
        found, value = _get_nested(sample, path)

        # 1. presence
        if not found:
            fail(f"[#{index}] MISSING  {path}")
            failed += 1
            continue

        # 2. nullable check
        if value is None:
            if nullable:
                ok(f"[#{index}] {path} = null  (nullable ✓)")
                passed += 1
                continue
            else:
                fail(f"[#{index}] {path} = null  (expected {expected_type.__name__ if hasattr(expected_type,'__name__') else expected_type})")
                failed += 1
                continue

        # 3. type check
        if not isinstance(value, expected_type):
            exp_name = (expected_type.__name__
                        if hasattr(expected_type, '__name__')
                        else str(expected_type))
            fail(f"[#{index}] TYPE     {path} = {value!r}  got {type(value).__name__}, want {exp_name}")
            failed += 1
            continue

        # 4. constraint check (range tuple or set of allowed values)
        if constraint is not None:
            if isinstance(constraint, set):
                if value not in constraint:
                    fail(f"[#{index}] VALUE    {path} = {value!r}  not in {constraint}")
                    failed += 1
                    continue
            elif isinstance(constraint, tuple):
                lo, hi = constraint
                try:
                    v_num = float(value)
                    if lo is not None and v_num < lo:
                        warn(f"[#{index}] RANGE    {path} = {value}  below min {lo}")
                    elif hi is not None and v_num > hi:
                        warn(f"[#{index}] RANGE    {path} = {value}  above max {hi}")
                    else:
                        ok(f"[#{index}] {path} = {value!r}")
                        passed += 1
                        continue
                except (TypeError, ValueError):
                    pass
            passed += 1
            continue

        ok(f"[#{index}] {path} = {value!r}")
        passed += 1

    return passed, failed


# ─── Socket.IO client ─────────────────────────────────────────────────────────
samples: list[dict] = []
done    = threading.Event()
_lock   = threading.Lock()

sio = socketio.Client(logger=False, reconnection=False)

@sio.on("connect")
def on_connect():
    print(f"{G}[connected]{X}  {SERVER_URL}")

@sio.on("connect_error")
def on_error(data):
    print(f"{R}[connect_error]{X}  {data}")
    done.set()

@sio.on("rover_data")
def on_rover_data(data):
    with _lock:
        if len(samples) >= SAMPLE_COUNT:
            return
        samples.append(data)
        n = len(samples)
        print(f"{B}[rover_data #{n}]{X}  received ({len(data)} top-level keys)")
        if n >= SAMPLE_COUNT:
            done.set()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"\n{BOLD}{W}NRP rover_data Field Verification{X}")
    print(f"Server : {SERVER_URL}")
    print(f"Samples: {SAMPLE_COUNT}   Timeout: {TIMEOUT_SEC}s\n")

    try:
        sio.connect(SERVER_URL)
    except Exception as exc:
        print(f"{R}Cannot connect: {exc}{X}")
        return 1

    if not done.wait(TIMEOUT_SEC):
        print(f"{Y}Timeout: only {len(samples)}/{SAMPLE_COUNT} messages received.{X}")

    try:
        sio.disconnect()
    except Exception:
        pass

    if not samples:
        print(f"{R}No rover_data received — is the server running?{X}")
        return 1

    # ── Pretty-print the first raw payload ───────────────────────────────────
    hdr("Raw rover_data #1 (full payload)")
    print(json.dumps(samples[0], indent=2, default=str))

    # ── Validate each sample ─────────────────────────────────────────────────
    total_pass = total_fail = 0
    for i, sample in enumerate(samples, 1):
        hdr(f"Validating sample #{i}")
        p, f = validate_sample(sample, i)
        total_pass += p
        total_fail += f

    # ── Summary ──────────────────────────────────────────────────────────────
    hdr("SUMMARY")
    total = total_pass + total_fail
    rate  = (total_pass / total) * 100 if total else 0
    print(f"  Samples checked : {len(samples)}/{SAMPLE_COUNT}")
    print(f"  Fields checked  : {total}")
    print(f"  {G}Passed{X}          : {total_pass}")
    print(f"  {R}Failed{X}          : {total_fail}")
    print(f"  Success rate    : {rate:.1f}%\n")

    if total_fail == 0:
        print(f"{G}{BOLD}  ✅  All rover_data fields are present and correctly typed.{X}\n")
        return 0
    else:
        print(f"{R}{BOLD}  ❌  {total_fail} field check(s) failed — see above.{X}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
