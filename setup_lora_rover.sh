#!/bin/bash

##############################################################################
# LoRa Module Setup Script for Rover - India Region (IN865)
# Detects, configures, and tests LoRa module for rover communication
##############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# India LoRa Region Configuration (IN865)
LORA_FREQUENCY="865000000"  # 865 MHz center frequency for India
LORA_BANDWIDTH="125000"     # 125 kHz bandwidth
LORA_SPREADING_FACTOR="7"   # SF7 for good range/speed balance
LORA_CODING_RATE="5"        # 4/5 coding rate
LORA_TX_POWER="20"          # 20 dBm (100mW - check local regulations)
LORA_PREAMBLE="8"           # 8 symbol preamble
LORA_SYNC_WORD="0x12"       # Private network sync word

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}LoRa Module Setup for Rover (India)${NC}"
echo -e "${BLUE}========================================${NC}"

##############################################################################
# Step 1: Load CH340/CH341 Driver
##############################################################################
echo -e "\n${YELLOW}[1/6] Loading CH340/CH341 USB-Serial Driver...${NC}"

if ! lsmod | grep -q ch341; then
    echo "Loading ch341-uart kernel module..."
    sudo modprobe ch341-uart 2>/dev/null || sudo modprobe ch341 2>/dev/null || {
        echo -e "${YELLOW}Note: CH341 module may already be built-in${NC}"
    }
    sleep 2
else
    echo -e "${GREEN}✓ CH341 driver already loaded${NC}"
fi

##############################################################################
# Step 2: Detect LoRa Device
##############################################################################
echo -e "\n${YELLOW}[2/6] Detecting LoRa Module...${NC}"

# Check USB devices
if lsusb | grep -q "1a86:7523\|QinHeng"; then
    echo -e "${GREEN}✓ CH340 USB-Serial converter detected${NC}"
else
    echo -e "${RED}✗ CH340 device not found in USB devices${NC}"
    echo "Please check if LoRa module is properly connected"
    lsusb
    exit 1
fi

# Find the serial device
LORA_DEVICE=""
for device in /dev/ttyUSB* /dev/ttyACM*; do
    if [ -e "$device" ]; then
        LORA_DEVICE="$device"
        break
    fi
done

if [ -z "$LORA_DEVICE" ]; then
    echo -e "${RED}✗ No serial device found (/dev/ttyUSB* or /dev/ttyACM*)${NC}"
    echo "Troubleshooting:"
    echo "1. Unplug and replug the LoRa module"
    echo "2. Check dmesg: sudo dmesg | tail -20"
    echo "3. Try: sudo modprobe usbserial vendor=0x1a86 product=0x7523"
    exit 1
fi

echo -e "${GREEN}✓ LoRa device found: $LORA_DEVICE${NC}"

##############################################################################
# Step 3: Check User Permissions
##############################################################################
echo -e "\n${YELLOW}[3/6] Checking Permissions...${NC}"

if groups | grep -q dialout; then
    echo -e "${GREEN}✓ User is in dialout group${NC}"
else
    echo -e "${YELLOW}! User not in dialout group. Adding...${NC}"
    sudo usermod -a -G dialout $USER
    echo -e "${YELLOW}! Please log out and log back in for group changes to take effect${NC}"
    echo -e "${YELLOW}! Or run: newgrp dialout${NC}"
fi

# Set device permissions temporarily
sudo chmod 666 $LORA_DEVICE
echo -e "${GREEN}✓ Device permissions set${NC}"

##############################################################################
# Step 4: Detect LoRa Module Type
##############################################################################
echo -e "\n${YELLOW}[4/6] Detecting LoRa Module Type...${NC}"

# Try to identify the module (common types: SX1276/SX1278, E32, RYLR)
python3 - <<EOF
import serial
import time

device = "$LORA_DEVICE"
module_type = "Unknown"

try:
    # Try common LoRa module AT commands
    ser = serial.Serial(device, 9600, timeout=2)
    time.sleep(1)
    
    # Test for RYLR (Reyax) modules
    ser.write(b'AT\r\n')
    time.sleep(0.5)
    response = ser.read(100).decode('utf-8', errors='ignore')
    if '+OK' in response or 'OK' in response:
        module_type = "RYLR (Reyax)"
        print(f"Detected: {module_type}")
    
    # Test for E32 modules (transparent transmission)
    ser.write(b'AT\r\n')
    time.sleep(0.5)
    response = ser.read(100).decode('utf-8', errors='ignore')
    if 'OK' in response:
        module_type = "E32 Series"
        print(f"Detected: {module_type}")
    
    if module_type == "Unknown":
        print("LoRa module connected, type detection inconclusive")
        print("Will proceed with generic configuration")
    
    ser.close()
except Exception as e:
    print(f"Device accessible at {device}")
    print(f"Note: {str(e)}")

EOF

##############################################################################
# Step 5: Configure LoRa for India Region (IN865)
##############################################################################
echo -e "\n${YELLOW}[5/6] Configuring LoRa for India Region (865-867 MHz)...${NC}"

# Create configuration script
cat > /tmp/lora_config.py << 'PYEOF'
import serial
import time
import sys

device = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"

def send_at_command(ser, cmd, wait=1):
    """Send AT command and get response"""
    print(f"  Sending: {cmd}")
    ser.write(f"{cmd}\r\n".encode())
    time.sleep(wait)
    response = ser.read(1000).decode('utf-8', errors='ignore')
    print(f"  Response: {response.strip()}")
    return response

try:
    print(f"\nConnecting to {device}...")
    ser = serial.Serial(device, 115200, timeout=2)
    time.sleep(1)
    
    print("\n--- Testing Communication ---")
    send_at_command(ser, "AT", 0.5)
    
    print("\n--- Configuring for India (IN865) ---")
    
    # Common configuration commands for RYLR/Reyax modules
    commands = [
        ("AT+ADDRESS=1", "Set address to 1 (rover)"),
        ("AT+NETWORKID=6", "Set network ID to 6"),
        ("AT+BAND=865000000", "Set frequency to 865 MHz (India)"),
        ("AT+PARAMETER=7,7,1,4", "Set SF=7, BW=125kHz, CR=4/5, Preamble=4"),
        ("AT+CPIN=FABC0002EEDCAA90FABC0002EEDCAA90", "Set AES encryption key"),
        ("AT+CRFOP=20", "Set TX power to 20 dBm"),
        ("AT+MODE=1", "Set to transmission mode"),
    ]
    
    for cmd, desc in commands:
        print(f"\n{desc}:")
        send_at_command(ser, cmd, 0.5)
    
    print("\n--- Testing Configuration ---")
    send_at_command(ser, "AT+ADDRESS?", 0.5)
    send_at_command(ser, "AT+BAND?", 0.5)
    send_at_command(ser, "AT+PARAMETER?", 0.5)
    
    print("\n✓ Configuration complete!")
    ser.close()
    
except serial.SerialException as e:
    print(f"✗ Serial communication error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

PYEOF

python3 /tmp/lora_config.py $LORA_DEVICE || {
    echo -e "${YELLOW}Note: Configuration may vary by module type${NC}"
    echo -e "${YELLOW}Manual configuration may be required${NC}"
}

##############################################################################
# Step 6: Create ROS2 Configuration
##############################################################################
echo -e "\n${YELLOW}[6/6] Creating ROS2 Configuration...${NC}"

# Create a configuration file for the rover
cat > /home/flash/NRP_ROS/lora_rover_config.yaml << EOF
# LoRa Rover Configuration - India Region
lora:
  device: "$LORA_DEVICE"
  baudrate: 115200
  region: "IN865"
  frequency: $LORA_FREQUENCY
  bandwidth: $LORA_BANDWIDTH
  spreading_factor: $LORA_SPREADING_FACTOR
  coding_rate: $LORA_CODING_RATE
  tx_power: $LORA_TX_POWER
  address: 1  # Rover address
  network_id: 6
  
  # India specific settings
  frequency_plan: "IN865"
  allowed_frequencies:
    - 865062500
    - 865402500
    - 865985000
  
  # Communication settings
  timeout: 5000  # milliseconds
  retry_count: 3
  max_payload: 250  # bytes
EOF

echo -e "${GREEN}✓ Configuration saved to: lora_rover_config.yaml${NC}"

##############################################################################
# Summary
##############################################################################
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}LoRa Module Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Device: ${GREEN}$LORA_DEVICE${NC}"
echo -e "Region: ${GREEN}India (IN865)${NC}"
echo -e "Frequency: ${GREEN}865 MHz${NC}"
echo -e "Bandwidth: ${GREEN}125 kHz${NC}"
echo -e "Spreading Factor: ${GREEN}SF7${NC}"
echo -e "TX Power: ${GREEN}20 dBm${NC}"
echo ""
echo -e "${BLUE}Configuration file: lora_rover_config.yaml${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Test communication: python3 test_lora_communication.py"
echo "2. Integrate with ROS2 rover node"
echo "3. Configure ground station with matching settings"
echo ""
echo -e "${YELLOW}Important Notes:${NC}"
echo "• Ensure antenna is connected before transmitting"
echo "• Check local regulations for power limits"
echo "• IN865 band: 865-867 MHz"
echo "• Max EIRP in India: typically 30 dBm (1W)"
echo ""
