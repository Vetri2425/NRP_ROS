"""
Standalone Manual Control Handler for Virtual Joystick

This module provides real-time RC override control for tank-style
differential drive rovers using virtual joystick input.

Features:
- RC_CHANNELS_OVERRIDE control method
- MANUAL mode operation
- Watchdog safety timer
- Emergency stop
- Independent state management
"""

import threading
import time
from typing import Optional, Dict, Any, Tuple
from datetime import datetime


class ManualControlHandler:
    """
    Handles manual control operations for virtual joystick input.

    Completely independent of mission controller - manages its own
    state, mode switching, and safety features.
    """

    def __init__(self, mavros_bridge, logger=None):
        """
        Initialize manual control handler.

        Args:
            mavros_bridge: MavrosBridge instance for MAVROS communication
            logger: Optional logger function
        """
        self.bridge = mavros_bridge
        self.logger = logger

        # State management
        self.is_active = False
        self.lock = threading.Lock()
        self.last_command_time = 0.0
        self.watchdog_timer: Optional[threading.Timer] = None

        # Configuration
        self.config = {
            'left_motor_channel': 73,
            'right_motor_channel': 74,
            'pwm_center': 1500,
            'pwm_min': 1000,
            'pwm_max': 2000,
            'rate_limit_hz': 20,
            'throttle_deadband': 0.05,
            'watchdog_timeout': 5.0,
        }

        self.log("Manual control handler initialized")

    def log(self, message: str, level: str = "INFO"):
        """Log message."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        log_msg = f"[MANUAL_CONTROL] [{timestamp}] {message}"
        print(log_msg, flush=True)

        if self.logger:
            try:
                self.logger(message, level, event_type='manual_control')
            except Exception:
                pass

    def validate_payload(self, data: dict) -> Tuple[bool, Optional[str]]:
        """
        Validate manual control payload.

        Returns: (is_valid, error_message)
        """
        if not isinstance(data, dict):
            return False, "Payload must be dict"

        has_throttle = 'left_throttle' in data and 'right_throttle' in data
        has_pwm = 'left_pwm' in data and 'right_pwm' in data

        if not (has_throttle or has_pwm):
            return False, "Must provide throttle or PWM values"

        if has_throttle:
            try:
                left = float(data['left_throttle'])
                right = float(data['right_throttle'])
                if not (-1.0 <= left <= 1.0):
                    return False, f"left_throttle {left} out of range"
                if not (-1.0 <= right <= 1.0):
                    return False, f"right_throttle {right} out of range"
            except (ValueError, TypeError) as e:
                return False, f"Invalid throttle: {e}"

        if has_pwm:
            try:
                left = int(data['left_pwm'])
                right = int(data['right_pwm'])
                if not (1000 <= left <= 2000):
                    return False, f"left_pwm {left} out of range"
                if not (1000 <= right <= 2000):
                    return False, f"right_pwm {right} out of range"
            except (ValueError, TypeError) as e:
                return False, f"Invalid PWM: {e}"

        return True, None

    def throttle_to_pwm(self, throttle: float) -> int:
        """Convert normalized throttle (-1 to 1) to PWM (1000-2000)."""
        # Apply deadband
        if abs(throttle) < self.config['throttle_deadband']:
            throttle = 0.0

        # Clamp
        throttle = max(-1.0, min(1.0, throttle))

        # Convert
        pwm_center = self.config['pwm_center']
        pwm_range = (self.config['pwm_max'] - self.config['pwm_min']) / 2
        pwm = int(pwm_center + (throttle * pwm_range))

        # Bounds
        return max(self.config['pwm_min'], min(self.config['pwm_max'], pwm))

    def handle_command(self, data: dict) -> Dict[str, Any]:
        """
        Process manual control command.

        Returns: Response dict with status
        """
        try:
            # Validate
            is_valid, error = self.validate_payload(data)
            if not is_valid:
                return {'status': 'error', 'message': error}

            # Rate limiting
            current_time = time.time()
            with self.lock:
                if current_time - self.last_command_time < (1.0 / self.config['rate_limit_hz']):
                    return {'status': 'dropped', 'message': 'Rate limit'}

                # Start session if needed
                if not self.is_active:
                    if not self.start_session():
                        return {'status': 'error', 'message': 'Failed to start session'}

                self.last_command_time = current_time

                # Reset watchdog
                self._reset_watchdog()

            # Extract values
            left_throttle = float(data.get('left_throttle', 0.0))
            right_throttle = float(data.get('right_throttle', 0.0))

            # Convert to PWM
            left_pwm = data.get('left_pwm') or self.throttle_to_pwm(left_throttle)
            right_pwm = data.get('right_pwm') or self.throttle_to_pwm(right_throttle)

            # Send commands
            self._send_motor_commands(left_pwm, right_pwm)

            return {
                'status': 'success',
                'timestamp': current_time,
                'left_pwm': left_pwm,
                'right_pwm': right_pwm
            }

        except Exception as e:
            self.log(f"Command error: {e}", "ERROR")
            return {'status': 'error', 'message': str(e)}

    def start_session(self) -> bool:
        """Start manual control session."""
        try:
            self.log("Starting manual control session")

            # Switch to MANUAL mode (non-critical - continue if it fails)
            try:
                self.bridge.set_mode(mode="MANUAL")
                self.log("Switched to MANUAL mode")
            except Exception as e:
                # Mode switch timeout is OK - rover might already be in MANUAL mode
                # or we can still send RC override commands in current mode
                self.log(f"Mode switch skipped (continuing): {e}", "WARNING")

            # Arm if needed (non-critical - continue if it fails)
            try:
                self.bridge.arm(value=True)
                self.log("Vehicle armed")
            except Exception as e:
                # Arm failure is OK - might already be armed
                self.log(f"Arm skipped (continuing): {e}", "WARNING")

            # Session is active even if mode switch/arm failed
            # RC override commands can still work
            self.is_active = True
            self.log("Manual control session started (ready to send RC override)")
            return True

        except Exception as e:
            self.log(f"Failed to start session: {e}", "ERROR")
            self.is_active = False
            return False

    def stop_session(self, reason: str = "user_request") -> None:
        """Stop manual control session."""
        try:
            self.log(f"Stopping session: {reason}")

            with self.lock:
                self.is_active = False

                # Cancel watchdog
                if self.watchdog_timer:
                    self.watchdog_timer.cancel()
                    self.watchdog_timer = None

            # Stop motors
            try:
                self._send_motor_commands(1500, 1500)
            except Exception as e:
                self.log(f"Failed to stop motors: {e}", "WARNING")

            # Clear RC override
            try:
                self.bridge.clear_rc_override()
            except Exception as e:
                self.log(f"Failed to clear override: {e}", "WARNING")

            # Switch to HOLD mode
            try:
                self.bridge.set_mode(mode="HOLD")
                self.log("Switched to HOLD mode")
            except Exception as e:
                self.log(f"Failed to set HOLD: {e}", "WARNING")

            self.log(f"Session stopped: {reason}")

        except Exception as e:
            self.log(f"Stop error: {e}", "ERROR")

    def emergency_stop(self) -> None:
        """Emergency stop - immediate halt."""
        self.log("EMERGENCY STOP", "WARNING")
        self.stop_session(reason="emergency_stop")

    def _send_motor_commands(self, left_pwm: int, right_pwm: int) -> None:
        """Send motor commands via RC override."""
        try:
            self.bridge.send_rc_override({
                self.config['left_motor_channel']: left_pwm,
                self.config['right_motor_channel']: right_pwm
            })
        except Exception as e:
            self.log(f"RC override failed: {e}", "ERROR")
            raise

    def _reset_watchdog(self) -> None:
        """Reset watchdog timer."""
        if self.watchdog_timer:
            self.watchdog_timer.cancel()

        self.watchdog_timer = threading.Timer(
            self.config['watchdog_timeout'],
            self._watchdog_timeout
        )
        self.watchdog_timer.start()

    def _watchdog_timeout(self) -> None:
        """Watchdog timeout callback."""
        self.log(f"Watchdog timeout ({self.config['watchdog_timeout']}s)", "WARNING")
        self.stop_session(reason="watchdog_timeout")

    def get_status(self) -> Dict[str, Any]:
        """Get current manual control status."""
        with self.lock:
            return {
                'active': self.is_active,
                'last_command_age': (
                    time.time() - self.last_command_time
                    if self.last_command_time > 0 else None
                ),
                'watchdog_timeout': self.config['watchdog_timeout']
            }
