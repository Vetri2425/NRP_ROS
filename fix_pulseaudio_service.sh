#!/bin/bash
# Fix PulseAudio access for nrp-service systemd unit

echo "Adding PulseAudio environment variables to nrp-service.service..."

# Backup the current file
sudo cp /etc/systemd/system/nrp-service.service /etc/systemd/system/nrp-service.service.backup2

# Add PulseAudio environment variables after JARVIS_LANG
sudo sed -i '/^Environment=JARVIS_LANG=en$/a \
\
# PulseAudio Access\
Environment=XDG_RUNTIME_DIR=/run/user/1000\
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native' /etc/systemd/system/nrp-service.service

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Restarting nrp-service..."
sudo systemctl restart nrp-service

echo "Done! PulseAudio access configured for systemd service."
echo ""
echo "Verify with: systemctl show nrp-service | grep XDG"
echo "Test by loading a mission - you should hear TTS through Piper + Bluetooth"
