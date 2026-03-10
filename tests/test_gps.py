#!/usr/bin/env python3
"""Test GPS data from MAVROS and MAVLink"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
import sys

class GPSTest(Node):
    def __init__(self):
        super().__init__('gps_test')
        
        # MAVROS uses BEST_EFFORT QoS
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            durability=DurabilityPolicy.VOLATILE
        )
        
        self.count = 0
        self.subscription = self.create_subscription(
            NavSatFix,
            '/mavros/global_position/global',
            self.gps_callback,
            qos
        )
        
        self.get_logger().info('GPS Test Node Started - Listening for GPS data...')
        
    def gps_callback(self, msg):
        self.count += 1
        self.get_logger().info(f'\n=== GPS Message #{self.count} ===')
        self.get_logger().info(f'Latitude:  {msg.latitude:.8f}')
        self.get_logger().info(f'Longitude: {msg.longitude:.8f}')
        self.get_logger().info(f'Altitude:  {msg.altitude:.2f} m')
        self.get_logger().info(f'GPS Status: {msg.status.status}')
        self.get_logger().info(f'GPS Service: {msg.status.service}')

def main():
    rclpy.init()
    node = GPSTest()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
