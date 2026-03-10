#!/usr/bin/env python3
"""
Servo Channel Test Script - Direct ROS2 Version

This script tests a servo channel using direct ROS2 service calls:
1. Setting PWM to first value (default 600 microseconds)
2. Waiting specified delay (default 5 seconds)  
3. Setting PWM to second value (default 1000 microseconds)

Uses direct ROS2 service calls to MAVROS.
Parameters can be configured via environment variables or defaults.
"""

import rclpy
from rclpy.node import Node
from mavros_msgs.srv import CommandLong
import time
import sys
import os

# Get test parameters from environment variables or use defaults
SERVO_CHANNEL = int(os.getenv('SERVO_CHANNEL', '10'))
FIRST_PWM = int(os.getenv('FIRST_PWM', '600'))
SECOND_PWM = int(os.getenv('SECOND_PWM', '1000'))
DELAY_SECONDS = int(os.getenv('DELAY_SECONDS', '5'))
TIMEOUT_SECONDS = float(os.getenv('TIMEOUT_SECONDS', '5.0'))


class ServoTester(Node):
    """ROS2 Node for testing servo channels."""
    
    def __init__(self):
        super().__init__('servo_tester')
        
        # Create service client for MAVROS command service
        self.command_client = self.create_client(
            CommandLong, 
            '/mavros/cmd/command'
        )
        
        # Wait for service to be available
        self.get_logger().info('Waiting for MAVROS command service...')
        while not self.command_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('MAVROS command service not available, waiting...')
    
    def set_servo(self, servo_number: int, pwm_value: int) -> bool:
        """
        Set servo to specific PWM value using MAV_CMD_DO_SET_SERVO.
        
        Args:
            servo_number: Servo channel number (1-16)
            pwm_value: PWM value in microseconds
            
        Returns:
            bool: True if command was successful
        """
        # Create service request
        request = CommandLong.Request()
        request.broadcast = False
        request.command = 183  # MAV_CMD_DO_SET_SERVO
        request.confirmation = 0
        request.param1 = float(servo_number)  # Servo number
        request.param2 = float(pwm_value)     # PWM value
        request.param3 = 0.0
        request.param4 = 0.0
        request.param5 = 0.0
        request.param6 = 0.0
        request.param7 = 0.0
        
        # Call service
        try:
            future = self.command_client.call_async(request)
            rclpy.spin_until_future_complete(self, future, timeout_sec=TIMEOUT_SECONDS)
            
            if future.result() is not None:
                response = future.result()
                success = response.success and response.result == 0
                
                if success:
                    self.get_logger().info(
                        f'✓ Servo {servo_number} set to {pwm_value} μs PWM'
                    )
                else:
                    self.get_logger().error(
                        f'✗ Servo command failed - Success: {response.success}, Result: {response.result}'
                    )
                
                return success
            else:
                self.get_logger().error('✗ Service call failed - no response')
                return False
                
        except Exception as e:
            self.get_logger().error(f'✗ Service call exception: {e}')
            return False
    
    def run_test(self) -> bool:
        """
        Run the complete servo test sequence.
        
        Returns:
            bool: True if all tests passed
        """
        self.get_logger().info(f'=== Servo Channel {SERVO_CHANNEL} Test ===')
        self.get_logger().info(f'Parameters: PWM1={FIRST_PWM}μs → Wait {DELAY_SECONDS}s → PWM2={SECOND_PWM}μs')
        self.get_logger().info(f'Testing servo channel {SERVO_CHANNEL}')
        
        try:
            # Step 1: Set PWM to first value
            self.get_logger().info(f'Step 1: Setting servo to {FIRST_PWM} μs PWM...')
            if not self.set_servo(SERVO_CHANNEL, FIRST_PWM):
                return False
            
            # Step 2: Wait specified delay
            self.get_logger().info(f'Step 2: Waiting {DELAY_SECONDS} seconds...')
            for i in range(DELAY_SECONDS, 0, -1):
                self.get_logger().info(f'  {i} seconds remaining...')
                time.sleep(1)
            self.get_logger().info('  Wait complete!')
            
            # Step 3: Set PWM to second value
            self.get_logger().info(f'Step 3: Setting servo to {SECOND_PWM} μs PWM...')
            if not self.set_servo(SERVO_CHANNEL, SECOND_PWM):
                return False
            
            self.get_logger().info('=== Test Complete ===')
            self.get_logger().info(f'✓ Servo channel {SERVO_CHANNEL} test completed successfully!')
            return True
            
        except KeyboardInterrupt:
            self.get_logger().warn('⚠ Test interrupted by user')
            return False
        except Exception as e:
            self.get_logger().error(f'✗ Unexpected error: {e}')
            return False


def main():
    """Main function."""
    print("Servo Channel Test - ROS2 Version")
    print("=====================================")
    print(f"Test Parameters: Channel={SERVO_CHANNEL}, PWM1={FIRST_PWM}, PWM2={SECOND_PWM}, Delay={DELAY_SECONDS}s")
    print("")
    
    # Initialize ROS2
    rclpy.init()
    
    try:
        # Create and run servo tester
        tester = ServoTester()
        success = tester.run_test()
        
        if success:
            print("\n🎉 Test completed successfully!")
            return 0
        else:
            print("\n❌ Test failed!")
            return 1
            
    except KeyboardInterrupt:
        print("\n⚠ Test interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        return 1
    finally:
        # Cleanup ROS2
        try:
            rclpy.shutdown()
        except:
            pass


if __name__ == '__main__':
    sys.exit(main())