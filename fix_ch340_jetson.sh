#!/bin/bash

##############################################################################
# CH340 Driver Fix for Jetson (Ubuntu-based)
# This script loads the WCH CH340 driver that comes with Jetson kernels
# and creates udev rules for automatic device access
##############################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}CH340 Driver Fix for Jetson${NC}"
echo -e "${BLUE}=====================================${NC}"

# Step 1: Check if device is detected
echo -e "\n${YELLOW}[1/4] Checking if CH340 device is detected...${NC}"
if lsusb | grep -q "1a86:7523\|CH340"; then
    echo -e "${GREEN}✓ CH340 device found in lsusb${NC}"
else
    echo -e "${RED}✗ CH340 device not detected. Please connect the LoRa module.${NC}"
    exit 1
fi

# Step 2: Load WCH driver
echo -e "\n${YELLOW}[2/4] Loading WCH CH340 driver...${NC}"
WCH_DRIVER="/lib/modules/$(uname -r)/updates/drivers/tty/serial/wch_35x/wch.ko"

if [ ! -f "$WCH_DRIVER" ]; then
    echo -e "${RED}✗ WCH driver not found at: $WCH_DRIVER${NC}"
    echo "Available serial drivers:"
    find /lib/modules/$(uname -r)/drivers/tty/serial -name "*.ko" 2>/dev/null || echo "None found"
    exit 1
fi

if lsmod | grep -q "^wch "; then
    echo -e "${GREEN}✓ WCH driver already loaded${NC}"
else
    sudo insmod "$WCH_DRIVER"
    echo -e "${GREEN}✓ WCH driver loaded${NC}"
fi

# Step 3: Create udev rules
echo -e "\n${YELLOW}[3/4] Setting up udev rules...${NC}"
sudo tee /etc/udev/rules.d/99-ch340.rules > /dev/null << 'UDEV_EOF'
# CH340/CH341 USB Serial Adapter (Reyax LoRa modules, etc)
# Vendor: 1a86, Product: 7523

# Grant read/write permissions for all users
SUBSYSTEMS=="usb", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE:="0666"

# Create /dev/ttyUSB* or /dev/ttyACM* with proper permissions
KERNEL=="ttyUSB*", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE="0666", GROUP="dialout"
KERNEL=="ttyACM*", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE="0666", GROUP="dialout"

# Create convenient symlink
SUBSYSTEMS=="usb", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="lora_device"
UDEV_EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
echo -e "${GREEN}✓ udev rules created and activated${NC}"

# Step 4: Add user to dialout group
echo -e "\n${YELLOW}[4/4] Setting user permissions...${NC}"
CURRENT_USER=$(whoami)
if groups "$CURRENT_USER" | grep -q dialout; then
    echo -e "${GREEN}✓ User '$CURRENT_USER' already in dialout group${NC}"
else
    sudo usermod -a -G dialout "$CURRENT_USER"
    echo -e "${YELLOW}! Added user '$CURRENT_USER' to dialout group${NC}"
    echo -e "${YELLOW}! You may need to log out and back in for group changes${NC}"
    echo -e "${YELLOW}! Or run: newgrp dialout${NC}"
fi

# Step 5: Instructions for user
echo -e "\n${GREEN}=====================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${GREEN}=====================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Unplug and replug your LoRa module"
echo "2. Check if device appears:"
echo "   ls -la /dev/ttyUSB* /dev/ttyACM* /dev/lora_device"
echo ""
echo "3. Test with the Python script:"
echo "   python3 test_lora_communication.py --mode basic"
echo ""
echo -e "${YELLOW}Troubleshooting:${NC}"
echo "• If device still doesn't appear, check kernel messages:"
echo "  sudo dmesg | grep -i 'ch340\|usb.*serial'"
echo ""
echo "• Check if driver is loaded:"
echo "  lsmod | grep wch"
echo ""
echo "• Check USB device:"
echo "  lsusb | grep 1a86"
echo ""
