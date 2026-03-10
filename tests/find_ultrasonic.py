#!/usr/bin/env python3
"""
A21 Series Ultrasonic Sensor Finder
Scans all available UART ports at multiple baud rates to detect the DYP A2111BU sensor.
Expected UART data format: 0xFF, HighByte, LowByte, Checksum
Distance (mm) = (HighByte << 8) + LowByte
Checksum = (0xFF + HighByte + LowByte) & 0xFF
"""

import serial
import serial.tools.list_ports
import glob
import time
import sys

BAUD_RATES = [115200, 9600, 57600, 38400, 19200, 14400, 76800, 4800]
UART_DEVICES = []

# Find all possible UART devices
for pattern in ['/dev/ttyTHS*', '/dev/ttyUSB*', '/dev/ttyAMA*', '/dev/ttyS*', '/dev/serial*']:
    UART_DEVICES.extend(sorted(glob.glob(pattern)))

# Also add from pyserial's port list
for port in serial.tools.list_ports.comports():
    if port.device not in UART_DEVICES:
        UART_DEVICES.append(port.device)

if not UART_DEVICES:
    print("No UART devices found!")
    sys.exit(1)

print("=" * 60)
print("DYP A21 Ultrasonic Sensor Finder")
print("=" * 60)
print(f"\nFound {len(UART_DEVICES)} UART device(s):")
for dev in UART_DEVICES:
    print(f"  - {dev}")
print()


def parse_a21_frame(buf):
    """Parse A21 UART frame: [0xFF] [HighByte] [LowByte] [Checksum]"""
    results = []
    for i in range(len(buf) - 3):
        if buf[i] == 0xFF:
            high = buf[i + 1]
            low = buf[i + 2]
            checksum = buf[i + 3]
            expected = (0xFF + high + low) & 0xFF
            if checksum == expected:
                distance_mm = (high << 8) | low
                results.append(distance_mm)
    return results


def send_trigger(ser):
    """Send trigger command for UART controlled mode (0x55)"""
    try:
        ser.write(b'\x55')
    except Exception:
        pass


def try_port(device, baud):
    """Try reading from a port at a given baud rate."""
    try:
        ser = serial.Serial(
            port=device,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5
        )
    except (serial.SerialException, PermissionError, OSError) as e:
        return None, str(e)

    try:
        ser.reset_input_buffer()

        # Send trigger command in case it's controlled mode
        send_trigger(ser)
        time.sleep(0.05)
        send_trigger(ser)

        # Read data for up to 2 seconds
        buf = bytearray()
        start = time.time()
        while time.time() - start < 2.0:
            chunk = ser.read(64)
            if chunk:
                buf.extend(chunk)
                # Check if we have enough data to parse
                if len(buf) >= 4:
                    distances = parse_a21_frame(buf)
                    if distances:
                        ser.close()
                        return distances, buf
            else:
                # No data, send another trigger
                send_trigger(ser)
                time.sleep(0.1)

        ser.close()

        if buf:
            return None, f"Got {len(buf)} bytes but no valid frames: {buf[:20].hex()}"
        else:
            return None, "No data received"

    except Exception as e:
        ser.close()
        return None, str(e)


# Scan all ports and baud rates
found = False
for device in UART_DEVICES:
    print(f"Scanning {device}...")
    for baud in BAUD_RATES:
        sys.stdout.write(f"  Baud {baud:>6}... ")
        sys.stdout.flush()

        result, info = try_port(device, baud)

        if result is not None:
            distances = result
            raw = info
            print(f"FOUND SENSOR!")
            print(f"  {'=' * 50}")
            print(f"  PORT: {device}")
            print(f"  BAUD: {baud}")
            print(f"  Raw hex: {raw[:20].hex()}")
            print(f"  Distances: {distances} mm")
            for d in distances:
                print(f"    -> {d} mm ({d / 10:.1f} cm)")
            if any(d == 0xFFFE for d in distances):
                print(f"    NOTE: 0xFFFE = interference detected")
            if any(d == 0 for d in distances):
                print(f"    NOTE: 0 = no echo / out of range")
            print(f"  {'=' * 50}")
            found = True
            break
        else:
            error_msg = info
            if "No data" in error_msg:
                print("no data")
            elif "Permission" in error_msg or "busy" in error_msg:
                print(f"SKIP ({error_msg})")
                break  # Skip remaining bauds for this port
            else:
                print(f"raw data but no valid frames")
                if "bytes" in error_msg:
                    print(f"    {error_msg}")

    if found:
        break
    print()

if not found:
    print("\nSensor NOT found on any port/baud combination.")
    print("\nTroubleshooting:")
    print("  1. Check wiring: Sensor TX -> Jetson Pin 10 (RX)")
    print("                   Sensor RX -> Jetson Pin 8 (TX)")
    print("                   Sensor VCC -> Pin 2 or 4 (5V)")
    print("                   Sensor GND -> Pin 6 or 9 (GND)")
    print("  2. Check sensor power: red+blue LED should flash on power-up")
    print("  3. Try swapping TX/RX wires")
    print("  4. Ensure user is in dialout group: sudo usermod -aG dialout $USER")
    print("  5. Check permissions: ls -la /dev/ttyTHS*")
