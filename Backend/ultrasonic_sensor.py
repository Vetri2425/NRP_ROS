#!/usr/bin/env python3
"""
A0221AM (53Q0619) - A02 Series Ultrasonic Sensor
Jetson Orin Nano Super

Multi-mode detection script:
  1. Try UART serial reading (if sensor is UART Auto mode)
  2. Try GPIO PWM pulse reading (if sensor is PWM mode)
  3. Try passive GPIO monitoring (detect any signal activity)

Wiring:
  Sensor Pin 1 (VCC) -> Jetson Pin 2 (5V)
  Sensor Pin 2 (GND) -> Jetson Pin 6 (GND)
  Sensor Pin 3 (RX)  -> Yellow or White wire
  Sensor Pin 4 (TX)  -> Yellow or White wire

Jetson GPIO:
  Pin 29 (PQ.05 / gpiochip0 line 105) - Yellow wire
  Pin 31 (PQ.06 / gpiochip0 line 106) - White wire
"""

import time
import signal
import sys
import os


# ─── Test 1: UART Serial ───────────────────────────────────────────

def find_serial_ports():
    """Find available serial ports on the Jetson."""
    ports = []
    # Common Jetson UART ports
    candidates = [
        "/dev/ttyTHS0", "/dev/ttyTHS2", "/dev/ttyTHS2",
        "/dev/ttyTHS1", "/dev/ttyUSB1",
        "/dev/ttyAMA0", "/dev/ttyAMA1",
        "/dev/ttyS0", "/dev/ttyS1", "/dev/ttyS2",
    ]
    for p in candidates:
        if os.path.exists(p):
            ports.append(p)
    return ports


def try_uart_read(port, timeout=5):
    """Try reading A02 UART frames from a serial port.

    A02 UART format: [0xFF, Data_H, Data_L, SUM]
    SUM = (0xFF + Data_H + Data_L) & 0xFF
    Distance (mm) = Data_H * 256 + Data_L
    """
    try:
        import serial
    except ImportError:
        print("  pyserial not installed. Install with: pip3 install pyserial")
        return None

    try:
        ser = serial.Serial(port, baudrate=9600, timeout=1,
                            bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE,
                            parity=serial.PARITY_NONE)
    except Exception as e:
        print(f"  Cannot open {port}: {e}")
        return None

    print(f"  Listening on {port} at 9600 baud for {timeout}s...")
    results = []
    start = time.monotonic()
    buf = bytearray()

    try:
        while time.monotonic() - start < timeout:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            buf.extend(data)

            # Look for 0xFF header and try to parse frames
            while len(buf) >= 4:
                # Find 0xFF start byte
                idx = buf.find(0xFF)
                if idx < 0:
                    buf.clear()
                    break
                if idx > 0:
                    buf = buf[idx:]
                if len(buf) < 4:
                    break

                header = buf[0]
                data_h = buf[1]
                data_l = buf[2]
                checksum = buf[3]

                expected_sum = (header + data_h + data_l) & 0xFF

                if checksum == expected_sum:
                    distance_mm = data_h * 256 + data_l
                    distance_cm = distance_mm / 10.0
                    results.append({
                        "distance_mm": distance_mm,
                        "distance_cm": distance_cm,
                        "raw": f"FF {data_h:02X} {data_l:02X} {checksum:02X}"
                    })
                    buf = buf[4:]
                else:
                    # Bad checksum, skip this byte
                    buf = buf[1:]

            if len(results) >= 10:
                break

    finally:
        ser.close()

    return results


def test_uart():
    """Test all available UART ports for A02 sensor data."""
    print("\n" + "=" * 55)
    print("  TEST 1: UART Serial Detection")
    print("=" * 55)

    ports = find_serial_ports()
    if not ports:
        print("  No serial ports found!")
        return None, None

    print(f"  Found ports: {', '.join(ports)}")

    for port in ports:
        print(f"\n  --- Trying {port} ---")
        results = try_uart_read(port, timeout=3)

        if results and len(results) > 0:
            print(f"  SUCCESS! Got {len(results)} readings from {port}")
            for i, r in enumerate(results[:5]):
                print(f"    #{i+1}  Distance: {r['distance_cm']:.1f} cm "
                      f"({r['distance_mm']} mm)  raw=[{r['raw']}]")
            return port, results
        else:
            print(f"  No A02 UART data on {port}")

    return None, None


# ─── Test 2: GPIO Activity Monitor ─────────────────────────────────

def test_gpio_activity():
    """Monitor both GPIO pins for any signal activity without triggering."""
    print("\n" + "=" * 55)
    print("  TEST 2: GPIO Pin Activity Monitor")
    print("=" * 55)

    try:
        import gpiod
    except ImportError:
        print("  gpiod not installed!")
        return None

    GPIO_CHIP = "gpiochip0"
    pins = {
        105: "Pin 29 (Yellow)",
        106: "Pin 31 (White)",
    }

    chip = gpiod.Chip(GPIO_CHIP)

    for line_num, label in pins.items():
        print(f"\n  --- Monitoring {label} (line {line_num}) for 3s ---")

        line = chip.get_line(line_num)
        line.request(consumer="a02_monitor", type=gpiod.LINE_REQ_DIR_IN)

        transitions = 0
        last_val = line.get_value()
        samples = 0
        high_count = 0
        low_count = 0
        start = time.monotonic()

        while time.monotonic() - start < 3.0:
            val = line.get_value()
            samples += 1
            if val == 1:
                high_count += 1
            else:
                low_count += 1
            if val != last_val:
                transitions += 1
                last_val = val

        line.release()

        print(f"  Samples: {samples}, HIGH: {high_count}, LOW: {low_count}")
        print(f"  Transitions: {transitions}")

        if transitions > 10:
            print(f"  ** ACTIVE SIGNAL detected on {label}! **")
            print(f"  This pin likely has UART TX data or PWM output")

    chip.close()


# ─── Test 3: Raw byte sniffer on GPIO (bit-bang UART) ───────────────

def test_gpio_uart_sniff():
    """Try to bit-bang read UART data from GPIO pins at 9600 baud."""
    print("\n" + "=" * 55)
    print("  TEST 3: GPIO UART Bit-Bang Sniffer")
    print("=" * 55)
    print("  (Attempting to read 9600 baud UART directly from GPIO)")
    print("  Note: This is unreliable - hardware UART is preferred")

    try:
        import gpiod
    except ImportError:
        print("  gpiod not installed!")
        return

    GPIO_CHIP = "gpiochip0"
    pins = [
        (105, "Pin 29 (Yellow)"),
        (106, "Pin 31 (White)"),
    ]

    chip = gpiod.Chip(GPIO_CHIP)

    for line_num, label in pins:
        print(f"\n  --- Sniffing {label} ---")

        line = chip.get_line(line_num)
        line.request(consumer="a02_sniff", type=gpiod.LINE_REQ_DIR_IN)

        # Sample at high rate for 2 seconds, look for patterns
        samples = []
        start = time.monotonic()
        while time.monotonic() - start < 2.0:
            samples.append((time.monotonic() - start, line.get_value()))

        line.release()

        # Analyze
        transitions = 0
        for i in range(1, len(samples)):
            if samples[i][1] != samples[i-1][1]:
                transitions += 1

        total = len(samples)
        highs = sum(1 for _, v in samples if v == 1)
        lows = total - highs
        rate = total / 2.0

        print(f"  Sample rate: {rate:.0f} Hz, Total: {total}")
        print(f"  HIGH: {highs} ({100*highs/total:.1f}%), "
              f"LOW: {lows} ({100*lows/total:.1f}%)")
        print(f"  Transitions: {transitions}")

        if transitions > 50:
            print(f"  ** HIGH ACTIVITY - likely UART TX data! **")
            print(f"  This pin should be connected to a hardware UART RX")
        elif transitions > 5:
            print(f"  ** Some activity - could be PWM or noisy signal **")
        else:
            print(f"  Static/idle signal - no data detected")

    chip.close()


# ─── Continuous UART reader ─────────────────────────────────────────

def run_uart_continuous(port):
    """Continuously read from UART port."""
    try:
        import serial
    except ImportError:
        print("pyserial not installed!")
        return

    running = True

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    ser = serial.Serial(port, baudrate=9600, timeout=1,
                        bytesize=serial.EIGHTBITS,
                        stopbits=serial.STOPBITS_ONE,
                        parity=serial.PARITY_NONE)

    print(f"\n--- CONTINUOUS UART MODE on {port} ---")
    print("Ctrl+C to stop\n")

    buf = bytearray()

    try:
        while running:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            buf.extend(data)

            while len(buf) >= 4:
                idx = buf.find(0xFF)
                if idx < 0:
                    buf.clear()
                    break
                if idx > 0:
                    buf = buf[idx:]
                if len(buf) < 4:
                    break

                header = buf[0]
                data_h = buf[1]
                data_l = buf[2]
                checksum = buf[3]

                expected_sum = (header + data_h + data_l) & 0xFF

                if checksum == expected_sum:
                    distance_mm = data_h * 256 + data_l
                    distance_cm = distance_mm / 10.0

                    if 30 <= distance_mm <= 4500:
                        print(f"Distance: {distance_cm:.1f} cm  |  "
                              f"{distance_mm/1000:.3f} m  "
                              f"[{data_h:02X} {data_l:02X}]")
                    elif distance_mm == 0:
                        print(f"No object detected (0mm)")
                    else:
                        print(f"Out of range: {distance_cm:.1f} cm ({distance_mm}mm)")
                    buf = buf[4:]
                else:
                    buf = buf[1:]
    finally:
        ser.close()
        print("\nSensor closed.")


# ─── Main ───────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  A0221AM (53Q0619) - A02 Ultrasonic Sensor Detector")
    print("  Trying ALL communication modes...")
    print("=" * 55)

    # Test 1: UART Serial
    uart_port, uart_results = test_uart()

    if uart_port:
        print("\n" + "=" * 55)
        print(f"  SENSOR FOUND on {uart_port} (UART mode)")
        print("=" * 55)
        resp = input("Start continuous reading? (y/n): ").strip().lower()
        if resp == 'y':
            run_uart_continuous(uart_port)
        return

    # Test 2: GPIO activity
    test_gpio_activity()

    # Test 3: GPIO UART sniff
    test_gpio_uart_sniff()

    # Summary
    print("\n" + "=" * 55)
    print("  DIAGNOSIS SUMMARY")
    print("=" * 55)
    print()
    print("  The sensor was NOT detected via UART or GPIO.")
    print()
    print("  Possible issues:")
    print("  1. WIRING: Verify VCC/GND connections")
    print("     - VCC (red) -> Jetson Pin 2 (5V)")
    print("     - GND (black) -> Jetson Pin 6 (GND)")
    print()
    print("  2. SENSOR MODEL: Your A0221AM may be UART mode,")
    print("     not PWM. Connect sensor TX to a Jetson UART RX:")
    print("     - Pin 10 (RXD) = /dev/ttyTHS0 or /dev/ttyTHS2")
    print("     - Check: ls /dev/ttyTHS*")
    print()
    print("  3. GPIO pins 29/31 are NOT hardware UART pins.")
    print("     If sensor uses UART output, connect to:")
    print("     - Sensor TX -> Jetson Pin 10 (UART RX)")
    print("     - Sensor RX -> Jetson Pin 8 (UART TX)")
    print()
    print("  4. VOLTAGE: Sensor TX may be 5V logic.")
    print("     Jetson GPIO is 3.3V. Use voltage divider if needed.")
    print()
    print("  5. Try: sudo cat /dev/ttyTHS2 | xxd | head")
    print("     to check if any serial data appears on UART ports.")


if __name__ == "__main__":
    main()
