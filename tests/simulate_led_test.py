#!/usr/bin/env python3
"""
Simulate mission controller states to test LED integration.

Cycles through all mission states with realistic timing to verify
LED behavior without needing Pixhawk/MAVROS.

Run with: python3 Backend/simulate_led_test.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Backend"))
from led_controller import LEDController


def simulate():
    led = LEDController()
    if not led.spi:
        print("ERROR: SPI not available. Run with appropriate permissions.")
        sys.exit(1)

    try:
        print("=== LED Mission State Simulation ===\n")

        # 1. IDLE (Blue)
        print("[1/7] IDLE -> Blue (3s)")
        led.update_state("idle")
        time.sleep(3)

        # 2. READY - mission loaded (Blue)
        print("[2/7] READY (mission loaded) -> Blue (3s)")
        led.update_state("ready")
        time.sleep(3)

        # 3. RUNNING - mission started (White)
        print("[3/7] RUNNING (mission started) -> White (5s)")
        led.update_state("running")
        time.sleep(5)

        # 4. PAUSED (Yellow)
        print("[4/7] PAUSED -> Yellow (3s)")
        led.update_state("paused")
        time.sleep(3)

        # 5. RUNNING - resumed (White)
        print("[5/7] RUNNING (resumed) -> White (3s)")
        led.update_state("running")
        time.sleep(3)

        # 6. ERROR (Red Blink)
        print("[6/7] ERROR -> Red Blink (5s)")
        led.update_state("error")
        time.sleep(5)

        # 7. COMPLETED (Green)
        print("[7/7] COMPLETED -> Green (5s)")
        led.update_state("completed")
        time.sleep(5)

        print("\n=== Simulation Complete ===")

    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        led.shutdown()


if __name__ == "__main__":
    simulate()
