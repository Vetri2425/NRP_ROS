#!/usr/bin/env python3
"""
Test script for Crowtail 4 LED RGB Strip (WS2812) on Jetson Orin Nano.

Wiring:
  - LED DIN  -> Jetson Header Pin 19 (SPI0_MOSI)
  - LED GND  -> Jetson Header Pin 25 (GND)
  - LED VCC  -> Jetson Header Pin 2/4 (5V)

Uses SPI (/dev/spidev0.0) with 8-bit encoding at 6.4MHz.
Run with: sudo python3 test_led.py
"""

import time
import sys
import spidev

NUM_LEDS = 30  # 500mm 60 LEDs/m WS2812 strip
SPI_BUS = 0
SPI_DEV = 0

# 8 SPI bits per WS2812 bit at 6.4 MHz
# Each SPI bit = 156ns
# WS2812 '0' = 0b11100000 -> ~468ns high, ~780ns low
# WS2812 '1' = 0b11111100 -> ~936ns high, ~312ns low
SPI_SPEED_HZ = 6400000

WS_0 = 0b11100000
WS_1 = 0b11111100


def init_spi():
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEV)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode = 0
    spi.bits_per_word = 8
    print(f"SPI actual max_speed_hz: {spi.max_speed_hz}")
    return spi


def color_to_spi_bytes(r, g, b):
    """Encode one RGB pixel into SPI bytes (8 SPI bits per WS2812 bit)."""
    spi_bytes = []
    for byte_val in [g, r, b]:  # WS2812 uses GRB order
        for bit in range(7, -1, -1):
            if byte_val & (1 << bit):
                spi_bytes.append(WS_1)
            else:
                spi_bytes.append(WS_0)
    return spi_bytes


def send_pixels(spi, pixels):
    """Send pixel data via SPI. pixels is a list of (r, g, b) tuples."""
    spi_data = []
    for r, g, b in pixels:
        spi_data.extend(color_to_spi_bytes(r, g, b))
    spi_data.extend([0x00] * 200)  # reset pulse >280us
    spi.xfer2(spi_data)


def fill(spi, color, n=NUM_LEDS):
    send_pixels(spi, [color] * n)


def clear(spi):
    fill(spi, (0, 0, 0))


def test_signal(spi):
    """Send a strong test pattern to verify SPI output."""
    print("  Sending raw SPI high signal for 1s (check with multimeter on Pin 19)...")
    for _ in range(100):
        spi.xfer2([0xFF] * 100)
        time.sleep(0.01)
    print("  Sending raw SPI low signal...")
    spi.xfer2([0x00] * 100)
    time.sleep(0.5)


def test_single_colors(spi):
    """Cycle through Red, Green, Blue, White on all LEDs."""
    colors = [
        ("Red",   (255, 0, 0)),
        ("Green", (0, 255, 0)),
        ("Blue",  (0, 0, 255)),
        ("White", (255, 255, 255)),
    ]
    for name, color in colors:
        print(f"  {name}")
        fill(spi, color)
        time.sleep(1.5)
    clear(spi)


def test_individual(spi):
    """Light each LED one at a time in white."""
    for i in range(NUM_LEDS):
        pixels = [(0, 0, 0)] * NUM_LEDS
        pixels[i] = (255, 255, 255)
        send_pixels(spi, pixels)
        print(f"  LED {i} ON")
        time.sleep(0.7)
    clear(spi)


def test_blink(spi):
    """Blink all LEDs white 5 times."""
    for i in range(5):
        fill(spi, (255, 255, 255))
        time.sleep(0.3)
        clear(spi)
        time.sleep(0.3)
        print(f"  blink {i+1}")


def test_rainbow_cycle(spi, duration=15):
    """Smooth rainbow animation across all LEDs."""
    def wheel(pos):
        if pos < 85:
            return (pos * 3, 255 - pos * 3, 0)
        elif pos < 170:
            pos -= 85
            return (255 - pos * 3, 0, pos * 3)
        else:
            pos -= 170
            return (0, pos * 3, 255 - pos * 3)

    start = time.time()
    offset = 0
    while time.time() - start < duration:
        pixels = []
        for i in range(NUM_LEDS):
            idx = (i * 256 // NUM_LEDS + offset) & 255
            pixels.append(wheel(idx))
        send_pixels(spi, pixels)
        offset = (offset + 1) % 256
        time.sleep(0.02)
    clear(spi)


if __name__ == "__main__":
    spi = init_spi()
    try:
        print("=== Crowtail 4 LED RGB Strip Test (SPI) ===")
        print(f"SPI: /dev/spidev{SPI_BUS}.{SPI_DEV}")
        print(f"LEDs: {NUM_LEDS}\n")

        print("[0] Signal test...")
        test_signal(spi)

        print("[1] Single colors...")
        test_single_colors(spi)

        print("[2] Individual LEDs...")
        test_individual(spi)

        print("[3] Blink test...")
        test_blink(spi)

        print("[4] Rainbow cycle (5s)...")
        test_rainbow_cycle(spi)

        print("\nAll tests complete!")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        clear(spi)
        spi.close()
