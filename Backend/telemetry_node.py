#!/usr/bin/env python3
"""
ROS2 Telemetry Node - Redundant position/state data collection

Data sources and consistency notes:
- Position: /mavros/global_position/global_corrected (corrected altitude +92.2m)
  * HRMS/VRMS calculated from position_covariance matrix diagonal elements
  * Satellite count: NOT from NavSatFix.status.service (that's a GNSS bitmask)
- RTK Status: From NavSatFix.status.status (fix_type 0-6: GPS modes 0-4, RTK modes 5-6)
- State: /mavros/state (armed, connected, mode, system_status)
- Battery: /mavros/battery (percentage, voltage, current)
- Temperature: /mavros/imu/temperature_imu
- Velocity: /mavros/global_position/raw/gps_vel (calculated magnitude)

This mirrors MAVROS bridge implementation for consistency.
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import BatteryState, Temperature
from mavros_msgs.msg import State
from sensor_msgs.msg import NavSatFix
from geometry_msgs.msg import TwistStamped
import json
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

MAV_STATE_LABELS = {
    0: 'UNINIT',
    1: 'BOOT',
    2: 'CALIBRATING',
    3: 'STANDBY',
    4: 'ACTIVE',
    5: 'CRITICAL',
    6: 'EMERGENCY',
    7: 'POWEROFF',
    8: 'TERMINATION',
}

def _map_mav_state(value: int) -> str:
    return MAV_STATE_LABELS.get(int(value), f'UNKNOWN({int(value)})')

def _map_gps_fix_type(fix_type: int) -> int:
    """Map GPS fix type to standard values
    0: No GPS
    1: No Fix
    2: 2D Fix
    3: 3D Fix
    4: DGPS
    5: RTK Float
    6: RTK Fixed
    """
    if fix_type < 0:
        return 0
    elif fix_type > 6:
        return 6
    return fix_type

class TelemetryNode(Node):
    def __init__(self):
        super().__init__('telemetry_node')

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )

        self.state_sub = self.create_subscription(
            State,
            '/mavros/state',
            self.state_callback,
            qos_profile
        )

        self.position_sub = self.create_subscription(
            NavSatFix,
            '/mavros/global_position/global_corrected',
            self.position_callback,
            qos_profile
        )

        self.velocity_sub = self.create_subscription(
            TwistStamped,
            '/mavros/global_position/raw/gps_vel',
            self.velocity_callback,
            qos_profile
        )

        # Subscribe to battery state published by MAVROS
        try:
            battery_qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=1
            )
            self.battery_sub = self.create_subscription(
                BatteryState,
                '/mavros/battery',
                self.battery_callback,
                battery_qos
            )
        except Exception:
            # If BatteryState type isn't available or QoS fails, skip battery subscription
            self.get_logger().warning('BatteryState subscription unavailable; battery telemetry will be absent')

        # Subscribe to IMU temperature published by MAVROS
        try:
            temp_qos = QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=1
            )
            self.temperature_sub = self.create_subscription(
                Temperature,
                '/mavros/imu/temperature_imu',
                self.temperature_callback,
                temp_qos
            )
        except Exception:
            # If Temperature type isn't available or QoS fails, skip temperature subscription
            self.get_logger().warning('Temperature subscription unavailable; temperature telemetry will be absent')

        self.telemetry_pub = self.create_publisher(
            String,
            '/nrp/telemetry',
            qos_profile
        )

        self.telemetry_data = {
            'state': {
                'mode': '',
                'armed': False,
                'system_status': 'STANDBY',
                'connected': False,
                'heartbeat_ts': 0
            },
            'global': {
                'latitude': 0.0,
                'longitude': 0.0,
                'altitude': 0.0,
                'vel': 0.0,
                'satellites_visible': 0,
                'hrms': 0.0,
                'vrms': 0.0
            },
            'rtk': {
                'fix_type': 0,
                'baseline_age': 0,
                'base_linked': False
            }
            ,
            'battery': {
                'percentage': None,
                'voltage': 0.0,
                'current': 0.0
            },
            'temperature': 0.0
        }

        self.timer = self.create_timer(0.1, self.publish_telemetry)
        self.get_logger().info('Telemetry node initialized with GPS/RTK support')

    def state_callback(self, msg):
        self.telemetry_data['state']['mode'] = (msg.mode or '').upper()
        self.telemetry_data['state']['armed'] = msg.armed
        self.telemetry_data['state']['connected'] = msg.connected
        self.telemetry_data['state']['system_status'] = _map_mav_state(msg.system_status)
        self.telemetry_data['state']['heartbeat_ts'] = self.get_clock().now().nanoseconds // 1000000

    def position_callback(self, msg):
        import math
        self.telemetry_data['global']['latitude'] = msg.latitude
        self.telemetry_data['global']['longitude'] = msg.longitude
        self.telemetry_data['global']['altitude'] = msg.altitude
        
        # Calculate accuracy from position covariance using universal formula
        # HRMS = sqrt(covariance[0] + covariance[4]) and VRMS = sqrt(covariance[8])
        if hasattr(msg, 'position_covariance') and len(msg.position_covariance) >= 9:
            try:
                hrms = math.sqrt(abs(float(msg.position_covariance[0])) + abs(float(msg.position_covariance[4])))
                vrms = math.sqrt(abs(float(msg.position_covariance[8])))
                self.telemetry_data['global']['hrms'] = hrms
                self.telemetry_data['global']['vrms'] = vrms
            except Exception:
                self.telemetry_data['global']['hrms'] = 0.0
                self.telemetry_data['global']['vrms'] = 0.0
        
        if hasattr(msg, 'status'):
            # NOTE: msg.status.service is GNSS service bitmask (0x01=GPS, 0x02=SBAS, etc), NOT satellite count
            # Satellite count comes from separate GPSRAW topic via MAVROS bridge
            # Use fix type for RTK status mapping (0-6 range matches MAVROS bridge)
            fix_type = int(msg.status.status) if hasattr(msg.status, 'status') else 0
            
            # Map RTK status consistently (0-6 range for consistency with MAVROS bridge)
            rtk_status_map = {
                0: "No GPS",
                1: "No Fix",
                2: "2D Fix",
                3: "3D Fix",
                4: "3D DGPS",
                5: "RTK Float",
                6: "RTK Fixed"
            }
            self.telemetry_data['rtk']['fix_type'] = fix_type
            # RTK modes are 5-6 (Float/Fixed), not 3+ as previously mapped
            self.telemetry_data['rtk']['base_linked'] = fix_type >= 5

    def velocity_callback(self, msg):
        import math
        vx = msg.twist.linear.x
        vy = msg.twist.linear.y
        self.telemetry_data['global']['vel'] = math.sqrt(vx*vx + vy*vy)

    def battery_callback(self, msg):
        try:
            import math
            # BatteryState.percentage is typically 0.0-1.0 (fraction)
            pct = msg.percentage if hasattr(msg, 'percentage') else None
            # Debug log to confirm callback is invoked and contents
            try:
                self.get_logger().info(f"Battery callback received: pct={pct}, volt={getattr(msg,'voltage',None)}, cur={getattr(msg,'current',None)}")
            except Exception:
                pass
            # Only set percentage if it's a valid number (not NaN or Inf)
            if pct is not None and not math.isnan(pct) and not math.isinf(pct):
                self.telemetry_data['battery']['percentage'] = float(pct)
            self.telemetry_data['battery']['voltage'] = float(msg.voltage) if hasattr(msg, 'voltage') and not math.isnan(msg.voltage) else 0.0
            self.telemetry_data['battery']['current'] = float(msg.current) if hasattr(msg, 'current') and not math.isnan(msg.current) else 0.0
        except Exception:
            pass

    def temperature_callback(self, msg):
        try:
            import math
            temp = msg.temperature if hasattr(msg, 'temperature') else 0.0
            if not math.isnan(temp) and not math.isinf(temp):
                self.telemetry_data['temperature'] = float(temp)
                self.get_logger().info(f"Temperature callback received: temp={temp}")
        except Exception:
            pass

    def publish_telemetry(self):
        msg = String()
        msg.data = json.dumps(self.telemetry_data)
        self.telemetry_pub.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    telemetry_node = TelemetryNode()

    try:
        rclpy.spin(telemetry_node)
    except KeyboardInterrupt:
        pass
    finally:
        telemetry_node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
