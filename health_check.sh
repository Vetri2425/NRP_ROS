#!/bin/bash
# NRP_ROS System Health Check Script
# Complete diagnostic tool for Navigation Rover Platform

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   🏥 NRP_ROS System Health Check          ║${NC}"
echo -e "${BLUE}║   Navigation Rover Platform Diagnostics   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# Function to print status
print_status() {
    local service=$1
    local status=$2
    if [ "$status" = "OK" ]; then
        echo -e "  ${GREEN}✅${NC} $service: ${GREEN}HEALTHY${NC}"
    elif [ "$status" = "WARN" ]; then
        echo -e "  ${YELLOW}⚠️${NC}  $service: ${YELLOW}WARNING${NC}"
    else
        echo -e "  ${RED}❌${NC} $service: ${RED}DOWN${NC}"
    fi
}

# 1. SYSTEM SERVICE STATUS
echo -e "${BLUE}═══ 🎛️  System Service ═══${NC}"
if systemctl is-active --quiet rosbridge.service; then
    print_status "rosbridge.service" "OK"
    UPTIME=$(systemctl show rosbridge.service --property=ActiveEnterTimestamp --value)
    echo -e "     └─ Started: $UPTIME"
else
    print_status "rosbridge.service" "FAIL"
fi
echo ""

# 2. FRONTEND STATUS
echo -e "${BLUE}═══ 🎨 Frontend (Vite) ═══${NC}"
if curl -s --connect-timeout 2 http://localhost:5173 > /dev/null 2>&1; then
    print_status "Frontend Server (Port 5173)" "OK"
    VITE_PID=$(lsof -ti:5173 2>/dev/null || echo "N/A")
    echo -e "     └─ PID: $VITE_PID"
else
    print_status "Frontend Server (Port 5173)" "FAIL"
fi
echo ""

# 3. BACKEND STATUS
echo -e "${BLUE}═══ 🐍 Backend (Flask + Socket.IO) ═══${NC}"
if curl -s --connect-timeout 2 http://localhost:5001/api/health > /dev/null 2>&1; then
    print_status "Backend Server (Port 5001)" "OK"
    FLASK_PID=$(lsof -ti:5001 2>/dev/null || echo "N/A")
    echo -e "     └─ PID: $FLASK_PID"
    
    # Check specific backend processes
    if pgrep -f "server.py" > /dev/null; then
        print_status "Flask Server Process" "OK"
    else
        print_status "Flask Server Process" "FAIL"
    fi
    
    if pgrep -f "telemetry_node.py" > /dev/null; then
        print_status "Telemetry Node" "OK"
    else
        print_status "Telemetry Node" "WARN"
    fi
else
    print_status "Backend Server (Port 5001)" "FAIL"
fi
echo ""

# 4. ROS 2 SYSTEM
echo -e "${BLUE}═══ 🤖 ROS 2 Humble ═══${NC}"
if source /opt/ros/humble/setup.bash 2>/dev/null; then
    NODE_COUNT=$(ros2 node list 2>/dev/null | wc -l)
    if [ "$NODE_COUNT" -gt 0 ]; then
        print_status "ROS 2 Nodes" "OK"
        echo -e "     └─ Active Nodes: $NODE_COUNT"
        
        # List key nodes
        if ros2 node list 2>/dev/null | grep -q "rosbridge"; then
            print_status "rosbridge_websocket" "OK"
        else
            print_status "rosbridge_websocket" "FAIL"
        fi
        
        if ros2 node list 2>/dev/null | grep -q "mavros"; then
            print_status "mavros" "OK"
        else
            print_status "mavros" "FAIL"
        fi
    else
        print_status "ROS 2 Nodes" "FAIL"
    fi
else
    print_status "ROS 2 Environment" "FAIL"
fi
echo ""

# 5. MAVROS CONNECTION
echo -e "${BLUE}═══ 🔌 MAVROS Bridge ═══${NC}"
if lsof -i:9090 > /dev/null 2>&1; then
    print_status "rosbridge WebSocket (Port 9090)" "OK"
    
    # Check MAVROS state
    if source /opt/ros/humble/setup.bash 2>/dev/null; then
        MAVROS_STATE=$(timeout 2 ros2 topic echo /mavros/state --once 2>/dev/null | grep "connected:" | awk '{print $2}' || echo "unknown")
        if [ "$MAVROS_STATE" = "True" ]; then
            print_status "MAVROS FCU Connection" "OK"
        elif [ "$MAVROS_STATE" = "False" ]; then
            print_status "MAVROS FCU Connection" "WARN"
            echo -e "     ${YELLOW}└─ Flight controller not connected${NC}"
        else
            print_status "MAVROS FCU Connection" "WARN"
        fi
    fi
else
    print_status "rosbridge WebSocket (Port 9090)" "FAIL"
fi
echo ""

# 6. NETWORK PORTS
echo -e "${BLUE}═══ 🌐 Network Ports ═══${NC}"
check_port() {
    local port=$1
    local name=$2
    if lsof -i:$port > /dev/null 2>&1; then
        print_status "$name (Port $port)" "OK"
    else
        print_status "$name (Port $port)" "FAIL"
    fi
}

check_port 5173 "Frontend"
check_port 5001 "Backend"
check_port 9090 "rosbridge"
echo ""

# 7. SYSTEM RESOURCES
echo -e "${BLUE}═══ 💻 System Resources ═══${NC}"
MEMORY_USAGE=$(free | grep Mem | awk '{printf "%.1f%%", $3/$2 * 100}')
CPU_LOAD=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}')
DISK_USAGE=$(df -h /home/flash/NRP_ROS | tail -1 | awk '{print $5}')

echo -e "  📊 Memory Usage: $MEMORY_USAGE"
echo -e "  📊 CPU Load (1min): $CPU_LOAD"
echo -e "  📊 Disk Usage: $DISK_USAGE"
echo ""

# 8. CRITICAL PROCESSES
echo -e "${BLUE}═══ 🔍 Process Check ═══${NC}"
PROCESS_COUNT=0

if pgrep -f "vite" > /dev/null; then
    ((PROCESS_COUNT++))
    print_status "Vite Dev Server" "OK"
else
    print_status "Vite Dev Server" "FAIL"
fi

if pgrep -f "server.py" > /dev/null; then
    ((PROCESS_COUNT++))
    print_status "Flask Backend" "OK"
else
    print_status "Flask Backend" "FAIL"
fi

if pgrep -f "rosbridge" > /dev/null; then
    ((PROCESS_COUNT++))
    print_status "rosbridge_server" "OK"
else
    print_status "rosbridge_server" "FAIL"
fi

if pgrep -f "mavros" > /dev/null; then
    ((PROCESS_COUNT++))
    print_status "MAVROS Node" "OK"
else
    print_status "MAVROS Node" "FAIL"
fi

echo -e "     └─ Total Critical Processes: $PROCESS_COUNT/4"
echo ""

# 9. RECENT ERRORS (from logs)
echo -e "${BLUE}═══ 📋 Recent Errors (Last 10 min) ═══${NC}"
ERROR_COUNT=$(sudo journalctl -u rosbridge.service --since "10 min ago" -p err 2>/dev/null | grep -c "error" || echo 0)
if [ "$ERROR_COUNT" -eq 0 ]; then
    print_status "Service Errors" "OK"
    echo -e "     └─ No errors in last 10 minutes"
else
    print_status "Service Errors" "WARN"
    echo -e "     ${YELLOW}└─ $ERROR_COUNT errors found (check logs)${NC}"
fi
echo ""

# 10. SUMMARY
echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              📊 SUMMARY                    ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"

TOTAL_CHECKS=10
PASSED_CHECKS=0

systemctl is-active --quiet rosbridge.service && ((PASSED_CHECKS++))
curl -s --connect-timeout 2 http://localhost:5173 > /dev/null 2>&1 && ((PASSED_CHECKS++))
curl -s --connect-timeout 2 http://localhost:5001/api/health > /dev/null 2>&1 && ((PASSED_CHECKS++))
lsof -i:9090 > /dev/null 2>&1 && ((PASSED_CHECKS++))
pgrep -f "vite" > /dev/null && ((PASSED_CHECKS++))
pgrep -f "server.py" > /dev/null && ((PASSED_CHECKS++))
pgrep -f "rosbridge" > /dev/null && ((PASSED_CHECKS++))
pgrep -f "mavros" > /dev/null && ((PASSED_CHECKS++))

HEALTH_PERCENT=$((PASSED_CHECKS * 100 / 8))

if [ "$HEALTH_PERCENT" -ge 90 ]; then
    echo -e "  ${GREEN}✅ System Health: EXCELLENT (${HEALTH_PERCENT}%)${NC}"
elif [ "$HEALTH_PERCENT" -ge 70 ]; then
    echo -e "  ${YELLOW}⚠️  System Health: GOOD (${HEALTH_PERCENT}%)${NC}"
elif [ "$HEALTH_PERCENT" -ge 50 ]; then
    echo -e "  ${YELLOW}⚠️  System Health: DEGRADED (${HEALTH_PERCENT}%)${NC}"
else
    echo -e "  ${RED}❌ System Health: CRITICAL (${HEALTH_PERCENT}%)${NC}"
fi

echo -e "  Checks Passed: ${PASSED_CHECKS}/8"
echo ""

# Recommendations
if [ "$HEALTH_PERCENT" -lt 100 ]; then
    echo -e "${YELLOW}💡 Recommendations:${NC}"
    
    systemctl is-active --quiet rosbridge.service || \
        echo -e "  • Start service: ${BLUE}sudo systemctl start rosbridge.service${NC}"
    
    curl -s --connect-timeout 2 http://localhost:5001/api/health > /dev/null 2>&1 || \
        echo -e "  • Check backend logs: ${BLUE}sudo journalctl -u rosbridge.service -n 50${NC}"
    
    pgrep -f "mavros" > /dev/null || \
        echo -e "  • MAVROS not running: ${BLUE}Check FCU connection${NC}"
    
    echo ""
fi

echo -e "${BLUE}════════════════════════════════════════════${NC}"
echo -e "Run ${BLUE}sudo journalctl -u rosbridge.service -f${NC} to view live logs"
echo -e "${BLUE}════════════════════════════════════════════${NC}"
