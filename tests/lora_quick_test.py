#!/usr/bin/env python3
"""
Quick LoRa connection test - bypass serial drivers
Tries multiple connection methods
"""

import os
import time
import subprocess

def find_ch340():
    """Find CH340 device details"""
    result = subprocess.run(
        "lsusb -d 1a86:7523",
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout.strip()

def check_serial_devices():
    """Check what serial devices exist"""
    result = subprocess.run(
        "ls -la /dev/tty*USB* /dev/ttyACM* /dev/ttyS* 2>/dev/null",
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout if result.stdout else "No standard serial devices found"

def check_usb_direct():
    """Check if we can access device directly via /dev/bus/usb"""
    result = subprocess.run(
        "ls -la /dev/bus/usb/001/0*| grep -i 35 | tail -1",
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout.strip() if result.stdout else "USB device not found in /dev/bus/usb"

def try_screen():
    """Check if we can use screen to communicate"""
    # Try to find any available serial device
    for dev in ["/dev/ttyTHS1", "/dev/ttyTHS1", "/dev/ttyS0"]:
        if os.path.exists(dev):
            print(f"\n{dev} exists!")
            try:
                result = subprocess.run(
                    f"sudo timeout 2 screen -S test -d -m -X at # {dev} 115200",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                return dev
            except:
                pass
    return None

print("=" * 60)
print("CH340 LoRa Device Detection & Connection Test")
print("=" * 60)

print("\n1. USB Detection:")
device_info = find_ch340()
if device_info:
    print(f"   ✓ {device_info}")
else:
    print("   ✗ Device not found in lsusb")

print("\n2. Serial Devices:")
serial_devs = check_serial_devices()
print(f"   {serial_devs}")

print("\n3. Direct USB Access:")
usb_direct = check_usb_direct()
print(f"   {usb_direct}")

print("\n4. Kernel Modules:")
result = subprocess.run(
    "lsmod | grep -E 'wch|ftdi|usbserial'",
    shell=True,
    capture_output=True,
    text=True
)
if result.stdout:
    for line in result.stdout.strip().split('\n'):
        print(f"   {line}")
else:
    print("   No relevant drivers loaded")

print("\n5. Recent Kernel Messages:")
result = subprocess.run(
    "sudo dmesg | tail -5 | grep -E 'usb|tty|ch340' || echo '   No recent USB messages'",
    shell=True,
    capture_output=True,
    text=True
)
print(f"   {result.stdout.strip()}")

print("\n" + "=" * 60)
print("Troubleshooting:")
print("=" * 60)
print("""
If NO /dev/ttyUSB* is shown above:

Option 1: Use screen directly on USB device
  sudo screen /dev/bus/usb/001/035 115200

Option 2: Reinstall CH340 driver module
  cd /tmp
  git clone https://github.com/morrissimo/CH340
  cd CH340/ch340_mod
  make clean
  make
  sudo make install
  sudo modprobe ch340

Option 3: Use PyUSB to communicate directly with CH340
  pip3 install pyusb
  Then modify test_lora_communication.py to use USB mode

Option 4: Check if device is working but unresponsive
  echo "AT" | sudo timeout 1 screen -S lora /dev/ttyTHS1 115200
""")

print("\nNext steps:")
print("1. Physically REPLUG the LoRa module")
print("2. Run this script again: python3 lora_quick_test.py")
print("3. If /dev/ttyUSB* appears, run: python3 test_lora_communication.py --mode basic")
