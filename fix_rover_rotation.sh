#!/bin/bash
# Emergency fix for rover rotation issue

echo "=== Applying Emergency Fixes to Pixhawk Parameters ==="
echo ""

source /opt/ros/humble/setup.bash

echo "1. Disarming rover..."
ros2 service call /mavros/cmd/arming mavros_msgs/srv/CommandBool "{value: false}"
sleep 1

echo ""
echo "2. Setting to MANUAL mode..."
ros2 service call /mavros/set_mode mavros_msgs/srv/SetMode "{custom_mode: 'MANUAL'}"
sleep 1

echo ""
echo "=== CRITICAL PARAMETERS TO FIX ==="
echo ""
echo "Connect to Pixhawk with QGroundControl or Mission Planner and change:"
echo ""
echo "# Increase waypoint acceptance radius"
echo "WP_RADIUS = 2.0    (currently 0.1 - TOO SMALL!)"
echo ""
echo "# Reduce cruise speed or disable"
echo "CRUISE_SPEED = 0.0  (currently 0.79)"
echo "WP_SPEED = 0.0      (currently 0.2)"
echo ""
echo "# Disable EKF for testing (optional)"
echo "AHRS_EKF_TYPE = 0   (currently using EKF3)"
echo ""
echo "# Enable RC failsafe"
echo "FS_THR_ENABLE = 1   (currently 0 - DISABLED!)"
echo ""
echo "=== ALTERNATIVE QUICK FIX ==="
echo ""
echo "If you can't change parameters right now:"
echo "1. Stay DISARMED when not actively driving"
echo "2. Only ARM when you're actively controlling via RC"
echo "3. Immediately DISARM when done"
echo ""
echo "Commands:"
echo "  ARM:    ros2 service call /mavros/cmd/arming mavros_msgs/srv/CommandBool '{value: true}'"
echo "  DISARM: ros2 service call /mavros/cmd/arming mavros_msgs/srv/CommandBool '{value: false}'"
echo ""
echo "=== Current Status ==="
ros2 topic echo /mavros/state --once | grep -E "(armed|mode)"
