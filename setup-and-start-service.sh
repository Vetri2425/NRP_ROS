#!/bin/bash

# NRP Service Installation and Startup Script
set -euo pipefail

SERVICE_NAME="nrp-service"
SERVICE_FILE="nrp-service.service"
SYSTEMD_DIR="/etc/systemd/system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
    echo "[nrp-service-manager] $*"
}

check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if service file exists
    if [[ ! -f "$SCRIPT_DIR/$SERVICE_FILE" ]]; then
        log "Service file $SERVICE_FILE not found in $SCRIPT_DIR"
        exit 1
    fi
    
    # Check if start_service.sh exists and is executable
    if [[ ! -f "$SCRIPT_DIR/start_service.sh" ]]; then
        log "start_service.sh not found in $SCRIPT_DIR"
        exit 1
    fi
    
    # Make start_service.sh executable
    chmod +x "$SCRIPT_DIR/start_service.sh"
    log "Ensured start_service.sh is executable"
}

install_service() {
    log "Installing $SERVICE_NAME service..."
    
    # Check if running with sudo
    if [[ $EUID -ne 0 ]]; then
        log "Need sudo privileges to install system service. Running with sudo..."
        sudo cp "$SCRIPT_DIR/$SERVICE_FILE" "$SYSTEMD_DIR/"
        sudo chmod 644 "$SYSTEMD_DIR/$SERVICE_FILE"
        sudo chown root:root "$SYSTEMD_DIR/$SERVICE_FILE"
        sudo systemctl daemon-reload
        sudo systemctl enable "$SERVICE_NAME"
    else
        cp "$SCRIPT_DIR/$SERVICE_FILE" "$SYSTEMD_DIR/"
        chmod 644 "$SYSTEMD_DIR/$SERVICE_FILE"
        chown root:root "$SYSTEMD_DIR/$SERVICE_FILE"
        systemctl daemon-reload
        systemctl enable "$SERVICE_NAME"
    fi
    
    log "Service installed and enabled successfully"
}

start_service() {
    log "Starting $SERVICE_NAME service..."
    
    if [[ $EUID -ne 0 ]]; then
        sudo systemctl start "$SERVICE_NAME"
    else
        systemctl start "$SERVICE_NAME"
    fi
    
    log "Service started successfully"
}

check_service_status() {
    log "Checking service status..."
    
    if [[ $EUID -ne 0 ]]; then
        sudo systemctl status "$SERVICE_NAME" --no-pager || true
    else
        systemctl status "$SERVICE_NAME" --no-pager || true
    fi
}

show_logs() {
    log "Recent service logs:"
    if [[ $EUID -ne 0 ]]; then
        sudo journalctl -u "$SERVICE_NAME" --no-pager -n 20 || true
    else
        journalctl -u "$SERVICE_NAME" --no-pager -n 20 || true
    fi
}

show_usage() {
    cat << EOF

NRP Service Management Commands:
  sudo systemctl start $SERVICE_NAME     # Start the service
  sudo systemctl stop $SERVICE_NAME      # Stop the service
  sudo systemctl restart $SERVICE_NAME   # Restart the service
  sudo systemctl status $SERVICE_NAME    # Check service status
  sudo systemctl enable $SERVICE_NAME    # Enable auto-start on boot
  sudo systemctl disable $SERVICE_NAME   # Disable auto-start on boot
  
  sudo journalctl -u $SERVICE_NAME -f    # Follow service logs
  sudo journalctl -u $SERVICE_NAME       # View all service logs

To uninstall the service:
  sudo systemctl stop $SERVICE_NAME
  sudo systemctl disable $SERVICE_NAME
  sudo rm /etc/systemd/system/$SERVICE_FILE
  sudo systemctl daemon-reload
EOF
}

main() {
    log "Starting NRP service setup..."
    
    check_prerequisites
    
    # Check if service is already installed
    if systemctl list-unit-files | grep -q "$SERVICE_NAME"; then
        log "Service is already installed, skipping installation"
    else
        install_service
    fi
    
    start_service
    sleep 3
    check_service_status
    
    echo
    show_logs
    echo
    show_usage
    
    log "Setup completed!"
}

main "$@"