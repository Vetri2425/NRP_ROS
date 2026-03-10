#!/usr/bin/env python3
"""
ROS2 node to correct MAVROS GPS altitude bug and republish corrected data.

This node subscribes to /mavros/global_position/global, applies altitude
correction, and republishes to /mavros/global_position/global_corrected.

The corrected topic can then be used by all ROS nodes instead of the buggy one.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy


class GPSAltitudeCorrectorNode(Node):
    """
    Corrects MAVROS GPS altitude bug by applying measured offset.
    
    Subscribe: /mavros/global_position/global (buggy altitude)
    Publish:   /mavros/global_position/global_corrected (corrected altitude)
    """
    
    # Measured altitude error: MAVROS reports -76.5m, actual is +15.6m
    ALTITUDE_CORRECTION = 92.2  # meters
    
    def __init__(self):
        super().__init__('gps_altitude_corrector')
        
        # MAVROS uses BEST_EFFORT QoS
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            durability=DurabilityPolicy.VOLATILE
        )
        
        # Subscribe to buggy MAVROS topic
        self.subscription = self.create_subscription(
            NavSatFix,
            '/mavros/global_position/global',
            self.gps_callback,
            qos_profile
        )
        
        # Publish corrected data
        self.publisher = self.create_publisher(
            NavSatFix,
            '/mavros/global_position/global_corrected',
            qos_profile
        )
        
        self.get_logger().info('GPS Altitude Corrector Node Started')
        self.get_logger().info(f'Applying altitude correction: +{self.ALTITUDE_CORRECTION}m')
        self.get_logger().info('Subscribe: /mavros/global_position/global')
        self.get_logger().info('Publish:   /mavros/global_position/global_corrected')
        
        # Statistics
        self.msg_count = 0
        self.last_log_time = self.get_clock().now()
        
    def gps_callback(self, msg: NavSatFix):
        """
        Receive GPS message, correct altitude, and republish.
        """
        # Create corrected message (copy original)
        corrected_msg = NavSatFix()
        corrected_msg.header = msg.header
        corrected_msg.status = msg.status
        
        # Copy lat/lon unchanged
        corrected_msg.latitude = msg.latitude
        corrected_msg.longitude = msg.longitude
        
        # APPLY ALTITUDE CORRECTION
        original_alt = msg.altitude
        corrected_msg.altitude = original_alt + self.ALTITUDE_CORRECTION
        
        # Copy covariance
        corrected_msg.position_covariance = msg.position_covariance
        corrected_msg.position_covariance_type = msg.position_covariance_type
        
        # Publish corrected message
        self.publisher.publish(corrected_msg)
        
        # Log periodically (every 5 seconds)
        self.msg_count += 1
        now = self.get_clock().now()
        if (now - self.last_log_time).nanoseconds / 1e9 >= 5.0:
            self.get_logger().info(
                f'GPS Fix #{self.msg_count}: '
                f'Lat={corrected_msg.latitude:.7f}, '
                f'Lon={corrected_msg.longitude:.7f}, '
                f'Alt={corrected_msg.altitude:.2f}m (raw:{original_alt:.2f}m, '
                f'correction:+{self.ALTITUDE_CORRECTION}m)'
            )
            self.last_log_time = now


def main(args=None):
    """Main entry point."""
    rclpy.init(args=args)
    
    node = GPSAltitudeCorrectorNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Shutting down GPS Altitude Corrector...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
