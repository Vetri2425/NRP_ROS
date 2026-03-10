#!/usr/bin/env python3
"""
A2111BU Ultrasonic Sensor - Continuous Distance Monitor
Port: /dev/ttyTHS1 | Baud: 115200
Press Ctrl+C to stop
"""

import serial
import time
import sys

PORT = '/dev/ttyTHS1'
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=0.5)
ser.reset_input_buffer()

print("A2111BU Ultrasonic Sensor Monitor")
print(f"Port: {PORT} | Baud: {BAUD}")
print("Press Ctrl+C to stop\n")

buf = bytearray()
try:
    while True:
        chunk = ser.read(64)
        if chunk:
            buf.extend(chunk)
            while len(buf) >= 4:
                if buf[0] == 0xFF:
                    high = buf[1]
                    low = buf[2]
                    checksum = buf[3]
                    expected = (0xFF + high + low) & 0xFF
                    if checksum == expected:
                        dist_mm = (high << 8) | low
                        if dist_mm == 0xFFFE:
                            status = "⚠ Interference"
                        elif dist_mm >= 0xFFFD:
                            status = "✗ No echo / out of range"
                        elif dist_mm == 0:
                            status = "✗ Too close (blind zone)"
                        elif dist_mm <= 50:
                            status = f"▓▓▓▓▓ VERY CLOSE  {dist_mm:>5} mm ({dist_mm/10:.1f} cm)"
                        elif dist_mm <= 200:
                            status = f"▓▓▓▓  CLOSE       {dist_mm:>5} mm ({dist_mm/10:.1f} cm)"
                        elif dist_mm <= 500:
                            status = f"▓▓▓   NEAR        {dist_mm:>5} mm ({dist_mm/10:.1f} cm)"
                        elif dist_mm <= 1500:
                            status = f"▓▓    MEDIUM      {dist_mm:>5} mm ({dist_mm/10:.1f} cm)"
                        else:
                            status = f"▓     FAR         {dist_mm:>5} mm ({dist_mm/10:.1f} cm)"
                        sys.stdout.write(f"\r  {status}    ")
                        sys.stdout.flush()
                        buf = buf[4:]
                    else:
                        buf = buf[1:]
                else:
                    buf = buf[1:]
except KeyboardInterrupt:
    print("\n\nStopped.")
finally:
    ser.close()
