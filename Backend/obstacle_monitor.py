#!/usr/bin/env python3
"""
A2111BU Ultrasonic Obstacle Monitor
Reads distance from DYP A21 series sensor via UART and triggers callbacks
when objects enter warning or danger zones.

Port: /dev/ttyTHS1 | Baud: 115200
Protocol: 4-byte frames [0xFF, HighByte, LowByte, Checksum]
"""

import serial
import threading
import time
from typing import Optional, Callable


class ObstacleMonitor:
    """Threaded ultrasonic sensor reader with zone-based obstacle detection."""

    # Zone thresholds (mm) — continuous, no gaps
    DANGER_MAX = 2000   # 0-1.0m = danger (pause mission)
    WARNING_MAX = 4000  # 1.0-2.0m = warning (alert only)
    # > 2.0m = clear

    # Debounce: consecutive readings required before triggering
    DEBOUNCE_COUNT = 3

    # Logging interval (seconds) for periodic distance reports
    LOG_INTERVAL = 1.0

    def __init__(self, port: str = '/dev/ttyTHS1', baud: int = 115200,
                 callback: Optional[Callable] = None, logger=None):
        self.port = port
        self.baud = baud
        self.callback = callback
        self.logger = logger

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_distance_mm: int = 0
        self._current_zone: str = "clear"
        self._zone_counter: int = 0
        self._confirmed_zone: str = "clear"
        self._last_log_time: float = 0.0
        self._reading_count: int = 0

    @property
    def last_distance_mm(self) -> int:
        return self._last_distance_mm

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Start the sensor reader thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._confirmed_zone = "clear"
        self._zone_counter = 0
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        self._log("Obstacle monitor started")

    def stop(self):
        """Stop the sensor reader thread."""
        if not self.is_running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._confirmed_zone = "clear"
        self._zone_counter = 0
        self._log("Obstacle monitor stopped")

    def _log(self, msg: str):
        if self.logger:
            self.logger(f"[OBSTACLE] {msg}")
        else:
            print(f"[OBSTACLE] {msg}", flush=True)

    def _classify_zone(self, distance_mm: int) -> str:
        """Classify distance into a zone (continuous, no gaps)."""
        if distance_mm <= self.DANGER_MAX:
            return "danger"
        if distance_mm <= self.WARNING_MAX:
            return "warning"
        return "clear"

    def _reader_loop(self):
        """Main sensor reading loop."""
        try:
            ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5
            )
        except Exception as e:
            self._log(f"Failed to open {self.port}: {e}")
            return

        self._log(f"Sensor connected on {self.port} @ {self.baud}")
        buf = bytearray()

        try:
            while not self._stop_event.is_set():
                chunk = ser.read(64)
                if not chunk:
                    continue

                buf.extend(chunk)

                while len(buf) >= 4:
                    if buf[0] == 0xFF:
                        high = buf[1]
                        low = buf[2]
                        checksum = buf[3]
                        expected = (0xFF + high + low) & 0xFF

                        if checksum == expected:
                            dist_mm = (high << 8) | low
                            buf = buf[4:]
                            self._process_reading(dist_mm)
                        else:
                            buf = buf[1:]
                    else:
                        buf = buf[1:]

        except Exception as e:
            if not self._stop_event.is_set():
                self._log(f"Reader error: {e}")
        finally:
            ser.close()

    def _process_reading(self, distance_mm: int):
        """Process a single distance reading with debounce."""
        # Ignore invalid readings
        if distance_mm >= 0xFFFD or distance_mm == 0:
            return

        self._last_distance_mm = distance_mm
        self._reading_count += 1
        zone = self._classify_zone(distance_mm)

        # Periodic distance logging
        now = time.time()
        if now - self._last_log_time >= self.LOG_INTERVAL:
            self._last_log_time = now
            self._log(f"Sensor: {distance_mm}mm ({distance_mm/10:.1f}cm) zone={zone} [readings={self._reading_count}]")

        # Debounce: count consecutive same-zone readings
        if zone == self._current_zone:
            self._zone_counter += 1
        else:
            self._current_zone = zone
            self._zone_counter = 1

        # Only trigger callback after DEBOUNCE_COUNT consecutive readings in same zone
        if self._zone_counter == self.DEBOUNCE_COUNT and zone != self._confirmed_zone:
            self._confirmed_zone = zone
            if zone != "clear" and self.callback:
                self._log(f"Zone change: {zone} at {distance_mm}mm ({distance_mm/10:.1f}cm)")
                try:
                    self.callback(distance_mm, zone)
                except Exception as e:
                    self._log(f"Callback error: {e}")


# Standalone test
if __name__ == "__main__":
    def on_obstacle(distance_mm, zone):
        if zone == "warning":
            print(f"  WARNING: Object at {distance_mm}mm ({distance_mm/10:.1f}cm)")
        elif zone == "danger":
            print(f"  DANGER: Object at {distance_mm}mm ({distance_mm/10:.1f}cm) - pausing mission!")

    monitor = ObstacleMonitor(callback=on_obstacle)
    monitor.start()

    print("Obstacle Monitor running. Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(0.5)
            d = monitor.last_distance_mm
            if d > 0:
                print(f"\r  Distance: {d}mm ({d/10:.1f}cm)    ", end="", flush=True)
    except KeyboardInterrupt:
        print("\nStopping...")
        monitor.stop()
