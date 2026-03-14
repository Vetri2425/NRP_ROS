#!/bin/bash

set -euo pipefail

PROJECT_ROOT="/home/flash/NRP_ROS"
ROS_SETUP="/opt/ros/humble/setup.bash"

declare -a CHILD_PIDS=()
NPM_PID=""
BACKEND_PID=""

log() {
    echo "[start_service] $*"
}

cleanup() {
    log "Cleaning up child processes..."
    for pid in "${CHILD_PIDS[@]:-}"; do
        if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    if [[ -n "${NPM_PID:-}" ]] && kill -0 "$NPM_PID" 2>/dev/null; then
        kill "$NPM_PID" 2>/dev/null || true
        wait "$NPM_PID" 2>/dev/null || true
    fi
}

handle_exit() {
    local code=$1
    trap - EXIT INT TERM
    cleanup
    exit "$code"
}

terminate_existing() {
    local patterns=(
        "rosbridge_websocket_launch.xml"
        "mavros apm.launch"
    )
    for pattern in "${patterns[@]}"; do
        pkill -f "$pattern" 2>/dev/null || true
    done
}

free_ports() {
    local ports=(9090 5761 5001)
    for port in "${ports[@]}"; do
        if lsof -i ":$port" >/dev/null 2>&1; then
            log "Port $port busy, terminating listeners"
            lsof -ti ":$port" | xargs -r kill -9 || true
        fi
    done
}

check_ros_node() {
    local node_name="$1"
    local nodes
    if ! nodes=$(ros2 node list 2>/dev/null); then
        return 1
    fi
    if grep -q "$node_name" <<< "$nodes"; then
        return 0
    fi
    return 1
}

wait_for_port() {
    local host="${1:-127.0.0.1}"
    local port="${2:-5001}"
    local attempts="${3:-30}"

    for ((i = 1; i <= attempts; i++)); do
        if python3 - <<PY >/dev/null 2>&1
import socket
with socket.create_connection(("${host}", ${port}), timeout=1.0):
    pass
PY
        then
            log "Port ${host}:${port} is ready"
            return 0
        fi
        log "Waiting for ${host}:${port}... ($i/${attempts})"
        sleep 1
    done

    log "Timeout waiting for ${host}:${port}"
    return 1
}

start_ros_process() {
    local name="$1"
    local cmd="$2"
    local node_pattern="$3"

    log "Starting $name..."
    eval "$cmd" &
    local pid=$!

    for i in {1..30}; do
        if [[ -z "$node_pattern" ]] || check_ros_node "$node_pattern"; then
            log "$name is ready"
            CHILD_PIDS+=("$pid")
            return 0
        fi

        if ! kill -0 "$pid" 2>/dev/null; then
            log "$name exited unexpectedly"
            return 1
        fi

        log "Waiting for $name... ($i/30)"
        sleep 1
    done

    log "$name did not report ready in time"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
    return 1
}

start_backend() {
    log "Starting backend server..."
    python3 -m Backend.server &
    BACKEND_PID=$!
    CHILD_PIDS+=("$BACKEND_PID")

    if ! wait_for_port "127.0.0.1" 5001 30; then
        log "Backend server failed to start correctly"
        return 1
    fi

    log "Backend server is ready"
    return 0
}

trap 'handle_exit $?' EXIT
trap 'handle_exit 130' INT
trap 'handle_exit 143' TERM

if [[ -f "$ROS_SETUP" ]]; then
    : "${AMENT_TRACE_SETUP_FILES:=}"
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    set -u
else
    log "Unable to locate ROS 2 setup script at $ROS_SETUP"
    exit 1
fi

ros2 daemon stop >/dev/null 2>&1 || true

terminate_existing
free_ports
sleep 1

start_ros_process "rosbridge_server" \
    "ros2 launch rosbridge_server rosbridge_websocket_launch.xml" \
    "/rosbridge_websocket" || exit 1

start_ros_process "MAVROS" \
    "ros2 launch mavros apm.launch fcu_url:=/dev/ttyACM0:115200 gcs_url:=tcp-l://:5760" \
    "/mavros" || exit 1

start_ros_process "GPS Altitude Corrector" \
    "python3 Backend/gps_altitude_corrector.py" \
    "/gps_altitude_corrector"


start_ros_process "Telemetry Node" \
    "python3 -m Backend.telemetry_node" \
    ""

# Mission Controller - DISABLED (causes rover rotation issue)
# start_ros_process "Mission Controller" \
#     "python3 -m Backend.mission_controller_node" \
#     "/mission_controller"

export LED_STRIP=strip
export JARVIS_LANG=en
export NRP_TTS_GENDER=male

# Set USB audio as default PulseAudio sink (persists for this session)
log "Configuring audio output..."
sleep 2  # Wait for PulseAudio to detect USB audio device
USB_SINK="alsa_output.usb-Jieli_Technology_UACDemoV1.0_4150344C3631390E-00.analog-stereo"
if pactl list sinks short 2>/dev/null | grep -q "$USB_SINK"; then
    pactl set-default-sink "$USB_SINK"
    log "Audio output set to USB speaker: $USB_SINK"
else
    log "WARNING: USB audio sink not found, TTS may not be audible"
fi

start_backend || exit 1

log "Active ROS nodes:"
ros2 node list || true

log "All services running. Waiting on backend (PID $BACKEND_PID)..."
wait "$BACKEND_PID"

