"""
Infrastructure layer translating backend requests into MAVROS ROS topics and services.

The rest of the FastAPI application should remain agnostic of whether the vehicle
is accessed through PyMAVLink or MAVROS. This module provides the minimum set of
operations required by the server today (connection state, telemetry fan-out,
mission management, RTK forwarding, and common command helpers).
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import json
import math
import re
from std_msgs.msg import String
import roslibpy

# rclpy for direct ROS2 service calls (bypasses rosbridge bottleneck)
import rclpy
from rclpy.node import Node
from mavros_msgs.srv import (
    CommandBool,
    SetMode,
    CommandLong,
    WaypointPush,
    WaypointClear,
    WaypointSetCurrent,
)
from mavros_msgs.msg import State as MavrosState, Waypoint, WaypointReached, RTCM

TelemetryCallback = Callable[[Dict[str, Any]], None]


def _ros_time() -> Dict[str, int]:
    """Return a ROS-style time dictionary based on wall-clock time."""
    now = time.time()
    secs = int(now)
    nsecs = int((now - secs) * 1_000_000_000)
    return {"secs": secs, "nsecs": nsecs}


def _run_subprocess_safe(cmd: list, timeout: float = 10) -> subprocess.CompletedProcess:
    """Run a subprocess with a timeout that kills the entire process group.

    Using subprocess.run(capture_output=True, timeout=N) is unsafe: when the
    timeout fires Python kills only the main process. Child processes (e.g.
    ros2 daemon threads) may keep stdout/stderr pipes open, causing
    communicate() to block indefinitely. This helper creates a new session so
    the whole process group can be killed atomically on timeout.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout)


class ServiceError(RuntimeError):
    """Raised when a ROS service call fails."""


class MavrosBridge:
    """
    Thin wrapper around MAVROS topics/services via rosbridge.

    All ROS interactions are executed with threading-friendly primitives so that
    the FastAPI ASGI server can keep running in parallel.
    """

    def __init__(
        self,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        self.host = host or os.getenv("MAVROS_BRIDGE_HOST", "127.0.0.1")
        self.port = int(port if port is not None else os.getenv("MAVROS_BRIDGE_PORT", "9090"))  # rosbridge_server WebSocket port
        self.fcu_url = os.getenv("MAVROS_FCU_URL", "/dev/ttyACM0:115200")

        # ...existing code...
        self._ros = roslibpy.Ros(host=self.host, port=self.port)
        self._lock = threading.Lock()
        self._connected = False
        self._subscriptions_ready = False
        self._telemetry_state: Dict[str, Any] = {}

        self._telemetry_callbacks: List[TelemetryCallback] = []
        self._waypoint_event = threading.Event()
        self._latest_waypoints: Optional[Dict[str, Any]] = None

        # Track Pixhawk disconnection for auto-reconnect
        self._last_pixhawk_connected = False  # Start as False to avoid false positives during startup
        self._pixhawk_disconnect_detected = False
        self._last_telemetry_time = time.time()
        self._telemetry_timeout = 20.0  # seconds without telemetry before reconnection (20s to avoid false positives during blocking bridge calls)
        self._startup_time = time.time()
        self._startup_grace_period = 30.0  # Don't trigger reconnection for first 30 seconds

        # Track pending service call events so _on_close can abort them immediately
        self._pending_service_calls: Dict[int, tuple] = {}  # id(event) -> (event, result_holder)

        # rclpy heartbeat fallback: updated by direct ROS2 subscription to /mavros/state.
        # Initialized to 0.0 so it immediately times out if rclpy never starts — the
        # fallback only activates once rclpy actually receives a heartbeat.
        self._last_rclpy_heartbeat: float = 0.0

        # Suppress disconnect detection during heavy mission operations (waypoint upload, etc.)
        # When True, is_pixhawk_disconnect_detected() ignores telemetry timeout to avoid
        # false positives caused by rosbridge being busy with service calls.
        self._suppress_disconnect_check = False

        self._state_topic: Optional[roslibpy.Topic] = None
        self._navsat_topic: Optional[roslibpy.Topic] = None
        self._gps_fix_topic: Optional[roslibpy.Topic] = None
        self._estimator_topic: Optional[roslibpy.Topic] = None
        self._imu_topic: Optional[roslibpy.Topic] = None
        self._rtk_baseline_topic: Optional[roslibpy.Topic] = None
        self._heading_topic: Optional[roslibpy.Topic] = None
        self._battery_topic: Optional[roslibpy.Topic] = None
        self._mission_topic: Optional[roslibpy.Topic] = None
        self._mission_reached_topic: Optional[roslibpy.Topic] = None
        self._rc_out_topic: Optional[roslibpy.Topic] = None
        self._rc_override_topic: Optional[roslibpy.Topic] = None

        self._rtcm_topic: Optional[roslibpy.Topic] = None
        self._rtcm_pub_rclpy = None  # rclpy publisher for RTCM
        self._setpoint_topic: Optional[roslibpy.Topic] = None

        # Mission controller integration - REMOVED
        # Mission controller topics and handlers have been removed
        # Use direct MAVROS services for mission operations

        # --- rclpy: direct ROS2 service clients (bypasses rosbridge bottleneck) ---
        self._rclpy_node: Optional[Node] = None
        self._rclpy_spin_thread: Optional[threading.Thread] = None
        self._rclpy_ready = False
        self._init_rclpy()

        self._ros.on_ready(self._on_ready, run_in_thread=True)
        self._ros.on("close", lambda _: self._on_close())

    # ------------------------------------------------------------------ public

    def connect(self, timeout: float = 10.0) -> None:
        """Open the rosbridge WebSocket and await the initial connection."""
        try:
            if not self._ros.is_connected:
                self._ros.run()

            start = time.time()
            while not self._ros.is_connected:
                if timeout and (time.time() - start) >= timeout:
                    raise TimeoutError(f"Failed to connect to MAVROS bridge at {self.host}:{self.port}")
                time.sleep(0.1)

            with self._lock:
                if not self._subscriptions_ready:
                    self._setup_subscriptions()
                    self._subscriptions_ready = True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to MAVROS: {str(e)}")

    def close(self) -> None:
        """Close the rosbridge connection and shutdown rclpy node."""
        self._shutdown_rclpy()
        try:
            if hasattr(self._ros, 'terminate'):
                self._ros.terminate()
            else:
                self._ros.close()
        except Exception:
            pass
        finally:
            with self._lock:
                self._connected = False

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._ros.is_connected

    def suppress_disconnect_check(self, suppress: bool = True) -> None:
        """Suppress or unsuppress telemetry-timeout disconnect detection.

        Call with True before heavy blocking operations (e.g. waypoint upload)
        and False after they complete.  Also refreshes the telemetry timestamp
        so the timeout window resets.
        """
        with self._lock:
            self._suppress_disconnect_check = suppress
            # Reset telemetry timer so the timeout window starts fresh
            self._last_telemetry_time = time.time()

    def is_pixhawk_disconnect_detected(self) -> bool:
        """Check if Pixhawk disconnection was detected and needs reconnection."""
        with self._lock:
            # Don't trigger during startup grace period
            time_since_startup = time.time() - self._startup_time
            if time_since_startup < self._startup_grace_period:
                return False

            # Don't trigger during heavy mission operations (waypoint upload, etc.)
            if self._suppress_disconnect_check:
                return False

            # Check explicit disconnection flag
            if self._pixhawk_disconnect_detected:
                return True

            # Check telemetry timeout (MAVROS node crash detection)
            time_since_telemetry = time.time() - self._last_telemetry_time
            if time_since_telemetry > self._telemetry_timeout:
                # Before declaring disconnect, check rclpy fallback.
                # If rclpy still receives /mavros/state heartbeats, rosbridge is
                # congested but the rover is alive — do NOT trigger reconnection.
                time_since_rclpy = time.time() - self._last_rclpy_heartbeat
                if time_since_rclpy < self._telemetry_timeout:
                    return False
                print(f"[MAVROS_BRIDGE] Telemetry timeout detected ({time_since_telemetry:.1f}s) - rclpy also stale ({time_since_rclpy:.1f}s) - flagging for reconnection", flush=True)
                return True

            return False

    def clear_disconnect_flag(self) -> None:
        """Clear the Pixhawk disconnection flag after reconnection attempt."""
        with self._lock:
            self._pixhawk_disconnect_detected = False
            self._last_pixhawk_connected = False  # Reset to False to avoid false positives on next restart
            self._last_telemetry_time = time.time()
            self._startup_time = time.time()  # Reset startup timer on reconnection

    def subscribe_telemetry(self, callback: TelemetryCallback) -> None:
        """Register a callback invoked with telemetry updates."""
        with self._lock:
            self._telemetry_callbacks.append(callback)

    def arm(self, *, value: bool, timeout: float = 5.0) -> Dict[str, Any]:
        # --- rclpy (fast, direct ROS2) ---
        try:
            req = CommandBool.Request()
            req.value = bool(value)
            t0 = time.time()
            resp = self._call_service_rclpy(self._cli_arming, req, timeout=3.0)
            elapsed = (time.time() - t0) * 1000
            success = bool(resp.success) or bool(resp.result)
            print(f"[MAVROS_BRIDGE] arm via rclpy: success={success} ({elapsed:.0f}ms)", flush=True)
            if not success:
                raise ServiceError(f"Vehicle rejected arm value {value}")
            return {"success": resp.success, "result": resp.result}
        except Exception as e:
            print(f"[MAVROS_BRIDGE] arm rclpy failed ({e}), trying CLI...", flush=True)

        # --- CLI fallback ---
        try:
            val_str = "true" if value else "false"
            result = _run_subprocess_safe(
                ["ros2", "service", "call", "/mavros/cmd/arming",
                 "mavros_msgs/srv/CommandBool", f"{{value: {val_str}}}"],
                timeout=10
            )
            if result.returncode == 0 and ("success=True" in result.stdout or "success = True" in result.stdout):
                print(f"[MAVROS_BRIDGE] arm via CLI: success", flush=True)
                return {"success": True, "result": 0}
            raise ServiceError(f"CLI arm failed: {result.stdout} {result.stderr}")
        except subprocess.TimeoutExpired:
            raise ServiceError("arm CLI timed out")
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(f"arm failed: {e}")

    def set_armed(self, value: bool, timeout: float = 5.0) -> Dict[str, Any]:
        """Convenience method for mission controller compatibility. Arms or disarms the vehicle."""
        try:
            response = self.arm(value=value, timeout=timeout)
            return {
                'success': True,
                'armed': value,
                'response': response
            }
        except Exception as e:
            return {
                'success': False,
                'armed': False,
                'error': str(e)
            }

    def set_mode(
        self,
        *,
        mode: str,
        base_mode: int = 0,
        custom_mode: Optional[str] = None,
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        mode_str = str(custom_mode if custom_mode is not None else mode)

        # --- rclpy (fast, direct ROS2) ---
        try:
            req = SetMode.Request()
            req.base_mode = int(base_mode)
            req.custom_mode = mode_str
            t0 = time.time()
            resp = self._call_service_rclpy(self._cli_set_mode, req, timeout=3.0)
            elapsed = (time.time() - t0) * 1000
            print(f"[MAVROS_BRIDGE] set_mode '{mode_str}' via rclpy: mode_sent={resp.mode_sent} ({elapsed:.0f}ms)", flush=True)
            if not resp.mode_sent:
                raise ServiceError(f"Vehicle rejected mode '{mode_str}'")
            return {"mode_sent": True}
        except Exception as e:
            print(f"[MAVROS_BRIDGE] set_mode rclpy failed ({e}), trying CLI...", flush=True)

        # --- CLI fallback ---
        try:
            result = _run_subprocess_safe(
                ["ros2", "service", "call", "/mavros/set_mode",
                 "mavros_msgs/srv/SetMode",
                 f"{{base_mode: {base_mode}, custom_mode: '{mode_str}'}}"],
                timeout=10
            )
            if result.returncode == 0 and ("mode_sent=True" in result.stdout or "mode_sent = True" in result.stdout):
                print(f"[MAVROS_BRIDGE] set_mode '{mode_str}' via CLI: success", flush=True)
                return {"mode_sent": True}
            raise ServiceError(f"CLI set_mode failed: {result.stdout} {result.stderr}")
        except subprocess.TimeoutExpired:
            raise ServiceError(f"set_mode CLI timed out for '{mode_str}'")
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(f"set_mode failed: {e}")

    def send_global_position_target(
        self,
        *,
        latitude: float,
        longitude: float,
        altitude: float,
        type_mask: int,
        coordinate_frame: int,
    ) -> None:
        if self._setpoint_topic is None:
            self._setpoint_topic = roslibpy.Topic(self._ros, "/mavros/setpoint_raw/global", "mavros_msgs/GlobalPositionTarget")
            self._setpoint_topic.advertise()

        message = roslibpy.Message({
            "header": {"stamp": _ros_time(), "frame_id": "map"},
            "coordinate_frame": int(coordinate_frame),
            "type_mask": int(type_mask),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "altitude": float(altitude),
            "velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
            "acceleration_or_force": {"x": 0.0, "y": 0.0, "z": 0.0},
            "yaw": 0.0,
            "yaw_rate": 0.0,
        })
        self._setpoint_topic.publish(message)

    def push_waypoints(self, waypoints: List[Dict[str, Any]], timeout: float = 30.0) -> Dict[str, Any]:
        # --- rclpy (fast, direct ROS2) ---
        try:
            req = WaypointPush.Request()
            req.start_index = 0
            ros_wps = []
            for wp_dict in waypoints:
                wp = Waypoint()
                wp.frame = int(wp_dict.get("frame", 3))
                wp.command = int(wp_dict.get("command", 16))
                wp.is_current = bool(wp_dict.get("is_current", False))
                wp.autocontinue = bool(wp_dict.get("autocontinue", True))
                wp.param1 = float(wp_dict.get("param1", 0.0))
                wp.param2 = float(wp_dict.get("param2", 0.0))
                wp.param3 = float(wp_dict.get("param3", 0.0))
                wp.param4 = float(wp_dict.get("param4", 0.0))
                wp.x_lat = float(wp_dict.get("x_lat", 0.0))
                wp.y_long = float(wp_dict.get("y_long", 0.0))
                wp.z_alt = float(wp_dict.get("z_alt", 0.0))
                ros_wps.append(wp)
            req.waypoints = ros_wps

            t0 = time.time()
            resp = self._call_service_rclpy(self._cli_wp_push, req, timeout=3.0)
            elapsed = (time.time() - t0) * 1000
            print(f"[MAVROS_BRIDGE] push_waypoints via rclpy: success={resp.success}, "
                  f"wp_transfered={resp.wp_transfered} ({elapsed:.0f}ms)", flush=True)
            if resp.success:
                return {"success": True, "wp_transfered": resp.wp_transfered}
            raise ServiceError(f"WaypointPush rejected: wp_transfered={resp.wp_transfered}")
        except Exception as e:
            print(f"[MAVROS_BRIDGE] push_waypoints rclpy failed ({e}), trying CLI...", flush=True)

        # --- CLI fallback ---
        return self.push_waypoints_cli(waypoints, timeout=15.0)

    def push_waypoints_cli(self, waypoints: List[Dict[str, Any]], timeout: float = 15.0) -> Dict[str, Any]:
        """Push waypoints using ros2 CLI subprocess (fallback)."""
        try:
            waypoints_yaml = "{start_index: 0, waypoints: ["
            for i, wp in enumerate(waypoints):
                if i > 0:
                    waypoints_yaml += ", "
                waypoints_yaml += (
                    f"{{frame: {wp.get('frame', 3)}, command: {wp.get('command', 16)}, "
                    f"is_current: {str(wp.get('is_current', False)).lower()}, "
                    f"autocontinue: {str(wp.get('autocontinue', True)).lower()}, "
                    f"param1: {wp.get('param1', 0.0)}, param2: {wp.get('param2', 0.0)}, "
                    f"param3: {wp.get('param3', 0.0)}, param4: {wp.get('param4', 0.0)}, "
                    f"x_lat: {wp.get('x_lat', 0.0)}, y_long: {wp.get('y_long', 0.0)}, "
                    f"z_alt: {wp.get('z_alt', 0.0)}}}"
                )
            waypoints_yaml += "]}"

            result = _run_subprocess_safe(
                ["ros2", "service", "call", "/mavros/mission/push",
                 "mavros_msgs/srv/WaypointPush", waypoints_yaml],
                timeout=timeout
            )
            if result.returncode == 0 and ("success=True" in result.stdout or "success = True" in result.stdout):
                match = re.search(r"wp_transfered[= ]+(\d+)", result.stdout)
                wp_count = int(match.group(1)) if match else len(waypoints)
                return {"success": True, "wp_transfered": wp_count}
            return {"success": False, "error": f"CLI push_waypoints failed: {result.stdout}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "push_waypoints CLI timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pull_waypoints(self, timeout: float = 30.0) -> Dict[str, Any]:
        with self._lock:
            self._waypoint_event.clear()
            self._latest_waypoints = None

        service = roslibpy.Service(self._ros, "/mavros/mission/pull", "mavros_msgs/WaypointPull")
        response = self._call_service(service, roslibpy.ServiceRequest({}), timeout)
        if not response.get("success", False):
            raise ServiceError(f"Waypoint pull rejected: {response}")

        if not self._waypoint_event.wait(timeout):
            raise TimeoutError("Timed out waiting for waypoint list after pull")

        with self._lock:
            if self._latest_waypoints is None:
                raise ServiceError("No waypoint list received from MAVROS")
            return self._latest_waypoints

    def clear_waypoints(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Clear all waypoints from the mission."""
        # --- rclpy (fast, direct ROS2) ---
        try:
            req = WaypointClear.Request()
            t0 = time.time()
            resp = self._call_service_rclpy(self._cli_wp_clear, req, timeout=3.0)
            elapsed = (time.time() - t0) * 1000
            print(f"[MAVROS_BRIDGE] clear_waypoints via rclpy: success={resp.success} ({elapsed:.0f}ms)", flush=True)
            return {"success": resp.success}
        except Exception as e:
            print(f"[MAVROS_BRIDGE] clear_waypoints rclpy failed ({e}), trying CLI...", flush=True)

        # --- CLI fallback ---
        return self.clear_waypoints_cli(timeout=10.0)

    def clear_waypoints_cli(self, timeout: float = 10.0) -> Dict[str, Any]:
        """Clear all waypoints using ros2 CLI subprocess (fallback)."""
        try:
            result = _run_subprocess_safe(
                ["ros2", "service", "call", "/mavros/mission/clear",
                 "mavros_msgs/srv/WaypointClear", "{}"],
                timeout=timeout
            )
            if result.returncode == 0 and ("success=True" in result.stdout or "success = True" in result.stdout):
                return {"success": True}
            return {"success": False, "error": f"CLI clear_waypoints failed: {result.stdout}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "clear_waypoints CLI timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_current_waypoint(self, wp_seq: int, timeout: float = 20.0) -> Dict[str, Any]:
        """Set the current mission waypoint."""
        # --- rclpy (fast, direct ROS2) ---
        try:
            req = WaypointSetCurrent.Request()
            req.wp_seq = int(wp_seq)
            t0 = time.time()
            resp = self._call_service_rclpy(self._cli_wp_set_current, req, timeout=3.0)
            elapsed = (time.time() - t0) * 1000
            print(f"[MAVROS_BRIDGE] set_current_waypoint({wp_seq}) via rclpy: success={resp.success} ({elapsed:.0f}ms)", flush=True)
            if resp.success:
                return {"success": True}
            raise ServiceError(f"Failed to set current waypoint to {wp_seq}")
        except Exception as e:
            print(f"[MAVROS_BRIDGE] set_current_waypoint rclpy failed ({e}), trying CLI...", flush=True)

        # --- CLI fallback ---
        return self.set_current_waypoint_cli(wp_seq, timeout=10.0)

    def set_current_waypoint_cli(self, wp_seq: int, timeout: float = 10.0) -> Dict[str, Any]:
        """Set current waypoint using ros2 CLI subprocess (fallback)."""
        try:
            result = _run_subprocess_safe(
                ["ros2", "service", "call", "/mavros/mission/set_current",
                 "mavros_msgs/srv/WaypointSetCurrent", f"{{wp_seq: {wp_seq}}}"],
                timeout=timeout
            )
            if result.returncode == 0 and ("success=True" in result.stdout or "success = True" in result.stdout):
                return {"success": True}
            return {"success": False, "error": f"CLI set_current_waypoint failed: {result.stdout}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "set_current_waypoint CLI timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_command_long(
        self,
        command: int,
        param1: float = 0.0,
        param2: float = 0.0,
        param3: float = 0.0,
        param4: float = 0.0,
        param5: float = 0.0,
        param6: float = 0.0,
        param7: float = 0.0,
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """Send a MAVLink COMMAND_LONG via MAVROS."""
        # --- rclpy (fast, direct ROS2) ---
        try:
            req = CommandLong.Request()
            req.broadcast = False
            req.command = int(command)
            req.confirmation = 0
            req.param1 = float(param1)
            req.param2 = float(param2)
            req.param3 = float(param3)
            req.param4 = float(param4)
            req.param5 = float(param5)
            req.param6 = float(param6)
            req.param7 = float(param7)
            t0 = time.time()
            resp = self._call_service_rclpy(self._cli_cmd_long, req, timeout=3.0)
            elapsed = (time.time() - t0) * 1000
            print(f"[MAVROS_BRIDGE] command_long({command}) via rclpy: success={resp.success} ({elapsed:.0f}ms)", flush=True)
            return {"success": resp.success, "result": resp.result}
        except Exception as e:
            print(f"[MAVROS_BRIDGE] command_long rclpy failed ({e}), trying CLI...", flush=True)

        # --- CLI fallback ---
        try:
            result = _run_subprocess_safe(
                ["ros2", "service", "call", "/mavros/cmd/command",
                 "mavros_msgs/srv/CommandLong",
                 f"{{broadcast: false, command: {command}, confirmation: 0, "
                 f"param1: {param1}, param2: {param2}, param3: {param3}, "
                 f"param4: {param4}, param5: {param5}, param6: {param6}, param7: {param7}}}"],
                timeout=10
            )
            if result.returncode == 0 and ("success=True" in result.stdout or "success = True" in result.stdout):
                return {"success": True, "result": 0}
            return {"success": False, "result": -1, "error": f"CLI command_long failed: {result.stdout}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "result": -1, "error": "command_long CLI timeout"}
        except Exception as e:
            return {"success": False, "result": -1, "error": str(e)}

    def set_servo(self, servo_number: int, pwm_value: int, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Set a servo to a specific PWM value using MAV_CMD_DO_SET_SERVO (183).

        Args:
            servo_number: Servo/channel number (typically 1-16)
            pwm_value: PWM value in microseconds (typically 1000-2000)
            timeout: Service call timeout

        Returns:
            Dict with 'success' (bool) and 'result' (int) fields
        """
        MAV_CMD_DO_SET_SERVO = 183
        return self.send_command_long(
            command=MAV_CMD_DO_SET_SERVO,
            param1=float(servo_number),
            param2=float(pwm_value),
            timeout=timeout
        )

    def send_rc_override(self, channels: Dict[int, int], timeout: float = 5.0) -> None:
        """
        Override RC channels with PWM values.

        Args:
            channels: Dict mapping channel number (1-18) to PWM (1000-2000)
            timeout: Not used for topic publish (kept for API consistency)

        Example:
            bridge.send_rc_override({1: 1500, 3: 1700})

        Note:
            Channel 0 = no override. Channels 1-18 correspond to RC1-RC18.
            For tank steering: typically channels 1 (throttle) and 3 (steering).
        """
        if self._rc_override_topic is None:
            self._rc_override_topic = roslibpy.Topic(
                self._ros,
                "/mavros/rc/override",
                "mavros_msgs/OverrideRCIn"
            )
            self._rc_override_topic.advertise()

        # OverrideRCIn expects array of 18 channels (0 = no override)
        rc_array = [0] * 18

        for channel, pwm in channels.items():
            if 1 <= channel <= 18:
                rc_array[channel - 1] = int(pwm)  # Convert to 0-indexed

        message = roslibpy.Message({"channels": rc_array})
        self._rc_override_topic.publish(message)

    def clear_rc_override(self) -> None:
        """
        Clear all RC overrides (release control to physical RC or autopilot).

        Sends all zeros to release override on all channels.
        """
        if self._rc_override_topic is None:
            return

        message = roslibpy.Message({"channels": [0] * 18})
        self._rc_override_topic.publish(message)

    def send_rtcm(self, payload: bytes) -> None:
        if not payload:
            return
        
        # --- rclpy (stable, direct ROS2) ---
        if self._rclpy_ready and self._rclpy_node is not None:
            if self._rtcm_pub_rclpy is None:
                self._rtcm_pub_rclpy = self._rclpy_node.create_publisher(RTCM, "/mavros/gps_rtk/send_rtcm", 10)
            msg = RTCM()
            msg.header.stamp = self._rclpy_node.get_clock().now().to_msg()
            msg.header.frame_id = "rtcm"
            msg.data = list(payload)
            self._rtcm_pub_rclpy.publish(msg)
            return
        
        # --- roslibpy fallback (legacy) ---
        # if self._rtcm_topic is None:
        #     self._rtcm_topic = roslibpy.Topic(self._ros, "/mavros/gps_rtk/send_rtcm", "mavros_msgs/RTCM")
        #     self._rtcm_topic.advertise()
        # message = roslibpy.Message({
        #     "header": {"stamp": _ros_time(), "frame_id": "rtcm"},
        #     "data": list(payload),
        # })
        # self._rtcm_topic.publish(message)

    def latest_waypoints(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._latest_waypoints

    # ---------------------------------------------------------------- internal

    # ---- rclpy initialization and service call helpers ----

    def _init_rclpy(self) -> None:
        """Initialize rclpy node and create all MAVROS service clients."""
        try:
            if not rclpy.ok():
                rclpy.init()
            self._rclpy_node = Node("nrp_mavros_bridge")

            # Create service clients
            self._cli_arming = self._rclpy_node.create_client(CommandBool, "/mavros/cmd/arming")
            self._cli_set_mode = self._rclpy_node.create_client(SetMode, "/mavros/set_mode")
            self._cli_cmd_long = self._rclpy_node.create_client(CommandLong, "/mavros/cmd/command")
            self._cli_wp_push = self._rclpy_node.create_client(WaypointPush, "/mavros/mission/push")
            self._cli_wp_clear = self._rclpy_node.create_client(WaypointClear, "/mavros/mission/clear")
            self._cli_wp_set_current = self._rclpy_node.create_client(WaypointSetCurrent, "/mavros/mission/set_current")

            # Subscribe to waypoint reached via rclpy (more reliable than rosbridge for fast events)
            self._rclpy_wp_reached_sub = self._rclpy_node.create_subscription(
                WaypointReached,
                "/mavros/mission/reached",
                self._handle_waypoint_reached_rclpy,
                10  # QoS depth
            )

            # Heartbeat fallback: subscribe to /mavros/state via rclpy (bypasses rosbridge).
            # If rosbridge is congested but MAVROS is alive, this still receives heartbeats
            # and prevents false disconnect detection.
            self._rclpy_state_sub = self._rclpy_node.create_subscription(
                MavrosState,
                "/mavros/state",
                self._handle_rclpy_heartbeat,
                10
            )

            # Spin rclpy in a background thread so futures can complete
            self._rclpy_spin_thread = threading.Thread(
                target=self._rclpy_spin_loop, daemon=True
            )
            self._rclpy_spin_thread.start()
            self._rclpy_ready = True
            print("[MAVROS_BRIDGE] rclpy node initialized - direct ROS2 service calls enabled", flush=True)
        except Exception as e:
            print(f"[MAVROS_BRIDGE] rclpy init failed, will use CLI fallback: {e}", flush=True)
            self._rclpy_ready = False

    def _handle_rclpy_heartbeat(self, msg) -> None:
        """rclpy-direct heartbeat from /mavros/state — bypasses rosbridge entirely."""
        with self._lock:
            self._last_rclpy_heartbeat = time.time()

    def _rclpy_spin_loop(self) -> None:
        """Background thread that spins the rclpy node so service futures resolve."""
        while rclpy.ok() and self._rclpy_node is not None:
            rclpy.spin_once(self._rclpy_node, timeout_sec=0.01)

    def _call_service_rclpy(self, client, request, timeout: float = 3.0) -> Any:
        """Call a ROS2 service via rclpy with timeout. Returns the response object or raises."""
        if not self._rclpy_ready or self._rclpy_node is None:
            raise RuntimeError("rclpy not initialized")

        if not client.service_is_ready():
            # Quick wait — don't block long
            if not client.wait_for_service(timeout_sec=min(timeout, 1.0)):
                raise RuntimeError(f"Service {client.srv_name} not available")

        future = client.call_async(request)

        start = time.time()
        while not future.done():
            elapsed = time.time() - start
            if elapsed > timeout:
                future.cancel()
                raise TimeoutError(f"rclpy service call timed out after {timeout}s")
            time.sleep(0.01)  # 10ms poll — spin thread handles the actual processing

        return future.result()

    def _shutdown_rclpy(self) -> None:
        """Shutdown the rclpy node cleanly."""
        try:
            if self._rclpy_node is not None:
                self._rclpy_node.destroy_node()
                self._rclpy_node = None
            self._rclpy_ready = False
        except Exception:
            pass

    # ---- roslibpy service call (kept for backward compat) ----

    def _call_service(self, service: roslibpy.Service, request: roslibpy.ServiceRequest, timeout: float) -> Dict[str, Any]:
        result_holder: Dict[str, Any] = {}
        event = threading.Event()
        event_id = id(event)

        def _success(result: Dict[str, Any]) -> None:
            # Unregister before signalling so _on_close won't double-signal
            with self._lock:
                self._pending_service_calls.pop(event_id, None)
            result_holder["result"] = result
            event.set()

        def _error(error: Any) -> None:
            with self._lock:
                self._pending_service_calls.pop(event_id, None)
            result_holder["error"] = error
            event.set()

        # Register so _on_close can abort this call if the connection drops
        with self._lock:
            self._pending_service_calls[event_id] = (event, result_holder)

        service.call(request, callback=_success, errback=_error)

        if not event.wait(timeout):
            with self._lock:
                self._pending_service_calls.pop(event_id, None)
            raise TimeoutError(f"Service call timeout for {service.name}")

        if "error" in result_holder:
            raise ServiceError(f"Service {service.name} failed: {result_holder['error']}")

        return result_holder.get("result", {})

    def _broadcast_telem(self, payload: Dict[str, Any], message_type: Optional[str] = None) -> None:
        # Update internal state with new data
        with self._lock:
            self._telemetry_state.update(payload)
            # Create complete telemetry update with all current state
            complete_update = {
                "lastUpdate": int(time.time() * 1000),  # milliseconds
                **self._telemetry_state
            }
            if message_type is not None:
                complete_update["type"] = message_type
            callbacks = list(self._telemetry_callbacks)

        for callback in callbacks:
            try:
                callback(complete_update)
            except Exception:
                # Telemetry callbacks are best-effort; ignore downstream failures.
                pass

    def _on_ready(self, *_: Any) -> None:
        with self._lock:
            self._connected = True

    def _on_close(self) -> None:
        with self._lock:
            self._connected = False
            # Grab and clear all pending service call events while holding the lock
            pending = list(self._pending_service_calls.values())
            self._pending_service_calls.clear()

        # Signal them AFTER releasing the lock to avoid any potential deadlock
        for evt, result_holder in pending:
            result_holder["error"] = "rosbridge connection closed"
            evt.set()
        if pending:
            print(f"[MAVROS_BRIDGE] _on_close: aborted {len(pending)} pending service call(s)", flush=True)

    def _setup_subscriptions(self) -> None:
        """Set up topic subscriptions for telemetry data."""
        # Vehicle state
        self._state_topic = roslibpy.Topic(self._ros, "/mavros/state", "mavros_msgs/State")
        
        # Position and navigation
        # HYBRID APPROACH:
        # 1) Position (lat/lon/alt): From /mavros/global_position/global_corrected (corrected altitude)
        # 2) Fix type & satellites: From /mavros/gpsstatus/gps1/raw (accurate fix_type, satellites)
        # 3) Accuracy (HRMS/VRMS): From covariance in global_corrected (calculated from covariance matrix)
        self._navsat_topic = roslibpy.Topic(self._ros, "/mavros/global_position/global_corrected", "sensor_msgs/NavSatFix")
        self._gps_raw_topic = roslibpy.Topic(self._ros, "/mavros/gpsstatus/gps1/raw", "mavros_msgs/GPSRAW")

        self._rtk_baseline_topic = roslibpy.Topic(self._ros, "/mavros/gps_rtk/rtk_baseline", "mavros_msgs/RTKBaseline")
        self._heading_topic = roslibpy.Topic(self._ros, "/mavros/global_position/compass_hdg", "std_msgs/Float64")
        # Estimator / IMU topics (alignment & raw IMU data)
        self._estimator_topic = roslibpy.Topic(self._ros, "/mavros/estimator_status", "mavros_msgs/EstimatorStatus")
        self._imu_topic = roslibpy.Topic(self._ros, "/mavros/imu/data", "sensor_msgs/Imu")
        self._velocity_topic = roslibpy.Topic(self._ros, "/mavros/global_position/raw/gps_vel", "geometry_msgs/TwistStamped")
        
        # System status
        self._battery_topic = roslibpy.Topic(self._ros, "/mavros/battery", "sensor_msgs/BatteryState")
        self._sys_status_topic = roslibpy.Topic(self._ros, "/mavros/sys_status", "mavros_msgs/SysStatus")
        
        # RC and signal
        self._rc_topic = roslibpy.Topic(self._ros, "/mavros/rc/in", "mavros_msgs/RCIn")
        self._signal_topic = roslibpy.Topic(self._ros, "/mavros/radio_status", "mavros_msgs/RadioStatus")
        
        # Mission tracking
        self._mission_topic = roslibpy.Topic(self._ros, "/mavros/mission/waypoints", "mavros_msgs/WaypointList")
        self._mission_reached_topic = roslibpy.Topic(self._ros, "/mavros/mission/reached", "mavros_msgs/msg/WaypointReached")
        
        # Servo output (PWM values)
        self._rc_out_topic = roslibpy.Topic(self._ros, "/mavros/rc/out", "mavros_msgs/RCOut")

        # Subscribe to all topics
        self._state_topic.subscribe(self._handle_state)
        self._navsat_topic.subscribe(self._handle_navsat)  # Position from global_corrected + HRMS/VRMS from covariance
        self._gps_raw_topic.subscribe(self._handle_gps_raw)  # Fix type & satellites (NOT eph/epv)
        self._rtk_baseline_topic.subscribe(self._handle_rtk_baseline)
        self._heading_topic.subscribe(self._handle_heading)
        # Subscribe to estimator and IMU topics to expose alignment and raw IMU to the backend
        try:
            self._estimator_topic.subscribe(self._handle_estimator_status)
        except Exception:
            # Best-effort: some systems may not publish estimator_status
            pass
        try:
            self._imu_topic.subscribe(self._handle_imu_data)
        except Exception:
            pass
        self._velocity_topic.subscribe(self._handle_velocity)
        self._battery_topic.subscribe(self._handle_battery)
        self._sys_status_topic.subscribe(self._handle_sys_status)
        self._rc_topic.subscribe(self._handle_rc)
        self._signal_topic.subscribe(self._handle_signal)
        self._mission_topic.subscribe(self._handle_waypoint_list)
        try:
            self._mission_reached_topic.subscribe(self._handle_waypoint_reached)
            print("[MAVROS] Subscribed to /mavros/mission/reached", flush=True)
        except Exception as e:
            print(f"[MAVROS_ERROR] Failed to subscribe to mission_reached: {e}", flush=True)
        self._rc_out_topic.subscribe(self._handle_servo_output)

    # ------------------------------- topic handlers

    def _handle_state(self, message: Dict[str, Any]) -> None:
        """Handle vehicle state updates (mode, armed status)."""
        connected = bool(message.get("connected", False))

        # Detect Pixhawk disconnection and trigger reconnection
        with self._lock:
            self._connected = connected and self._ros.is_connected
            self._last_telemetry_time = time.time()  # Update telemetry timestamp

            # Only trigger disconnection if:
            # 1. We were previously connected (avoid startup false positives)
            # 2. Now disconnected
            # 3. Past startup grace period
            time_since_startup = time.time() - self._startup_time
            if self._last_pixhawk_connected and not connected and time_since_startup >= self._startup_grace_period:
                self._pixhawk_disconnect_detected = True
                print("[MAVROS_BRIDGE] Pixhawk disconnection detected - flagging for reconnection", flush=True)

            self._last_pixhawk_connected = connected

        self._broadcast_telem({
            "mode": str(message.get("mode", "UNKNOWN")),
            "armed": bool(message.get("armed", False)),
            "status": "armed" if bool(message.get("armed", False)) else "disarmed",
            "connected": connected
        }, message_type="state")


    def _handle_gps_raw(self, message: Dict[str, Any]) -> None:
        """Handle raw GPS data from /mavros/gpsstatus/gps1/raw.

        THIS HANDLER PROCESSES FIX TYPE AND SATELLITES ONLY:
        - fix_type: 0-6 where 6=RTK Fixed, 5=RTK Float, 4=DGPS, etc.
        - satellites_visible: actual satellite count

        HRMS/VRMS accuracy metrics now come from position covariance in global_corrected.
        """
        # Extract fix quality
        fix_type = int(message.get("fix_type", 0))
        satellites_visible = int(message.get("satellites_visible", 0))

        # Map fix type to RTK status string
        # Based on GPS fix type definitions:
        # 0: No GPS, 1: No Fix, 2: 2D Fix, 3: 3D Fix, 4: 3D DGPS, 5: RTK Float, 6: RTK Fixed
        rtk_status_map = {
            0: "No GPS",
            1: "No Fix",
            2: "2D Fix",
            3: "3D Fix",
            4: "3D DGPS",
            5: "RTK Float",
            6: "RTK Fixed"
        }
        rtk_status = rtk_status_map.get(fix_type, "Unknown")

        # DEBUG: Log GPS quality updates (fix type and satellites only)
        print(f"[MAVROS_BRIDGE] GPS_RAW: fix={fix_type} ({rtk_status}), sats={satellites_visible}", flush=True)

        # Broadcast GPS fix quality (RTK status, fix type, satellites)
        # NOTE: HRMS/VRMS are handled in _handle_navsat() from covariance data
        self._broadcast_telem({
            "rtk_status": rtk_status,
            "fix_type": fix_type,
            "satellites_visible": satellites_visible
        }, message_type="gps_fix")

    def _handle_navsat(self, message: Dict[str, Any]) -> None:
        """Handle global position updates from /mavros/global_position/global_corrected.

        Position data source: /mavros/global_position/global_corrected
        - Provides corrected altitude (+92.2m fix applied by gps_altitude_corrector.py ROS node)
        - Provides position covariance for accuracy calculation (HRMS/VRMS)
        - Lower update rate (~1 Hz) but more accurate position
        - This is the PRIMARY source for rover position coordinates

        Note: Fix type and satellites come from /mavros/gpsstatus/gps1/raw via _handle_gps_raw()
        """
        lat = float(message.get("latitude", 0.0))
        lon = float(message.get("longitude", 0.0))
        alt = float(message.get("altitude", 0.0))  # Already corrected by ROS node (+92.2m)

        covariance = message.get("position_covariance", [])
        hrms = 0.0
        vrms = 0.0

        if isinstance(covariance, list) and len(covariance) >= 9:
            try:
                hrms = math.sqrt(abs(float(covariance[0])) + abs(float(covariance[4])))
                vrms = math.sqrt(abs(float(covariance[8])))
            except (ValueError, TypeError) as e:
                print(f"[MAVROS_BRIDGE] Warning: Failed to calculate HRMS/VRMS from covariance: {e}", flush=True)
                hrms = 0.0
                vrms = 0.0

        # Update telemetry timestamp
        with self._lock:
            self._last_telemetry_time = time.time()

        # DEBUG: Log position and accuracy updates
        print(f"[MAVROS_BRIDGE] NavSat: lat={lat:.7f}, lon={lon:.7f}, alt={alt:.2f}m, "
              f"hrms={hrms:.3f}m, vrms={vrms:.3f}m (from covariance)", flush=True)

        # Broadcast position data
        self._broadcast_telem({
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "relative_altitude": 0.0  # Not available in NavSatFix
        }, message_type="navsat")

        self._broadcast_telem({
            "hrms": hrms,
            "vrms": vrms
        }, message_type="gps_accuracy")


    def _handle_rtk_baseline(self, message: Dict[str, Any]) -> None:
        """Handle RTK baseline updates (distance from base station)."""
        # Debug log raw baseline message for diagnostics
        try:
            print(f"[MAVROS_BRIDGE] Received rtk_baseline message: {message}", flush=True)
        except Exception:
            pass
        # Extract baseline vectors (in meters from base station)
        baseline_a = message.get("baseline_a_mm", 0) / 1000.0  # Convert mm to meters
        baseline_b = message.get("baseline_b_mm", 0) / 1000.0
        baseline_c = message.get("baseline_c_mm", 0) / 1000.0
        
        # Calculate total baseline distance
        baseline_distance = (baseline_a**2 + baseline_b**2 + baseline_c**2) ** 0.5
        
        # Extract accuracy information
        accuracy = message.get("accuracy", 0)
        iar_num_hypotheses = message.get("iar_num_hypotheses", 0)
        
        # Extract time of week
        tow = message.get("tow", 0)
        rtk_receiver_id = message.get("rtk_receiver_id", 0)
        rtk_health = message.get("rtk_health", 0)
        rtk_rate = message.get("rtk_rate", 0)
        nsats = message.get("nsats", 0)
        
        self._broadcast_telem({
            "rtk_baseline": {
                "baseline_a_mm": baseline_a * 1000,  # Keep original mm values
                "baseline_b_mm": baseline_b * 1000,
                "baseline_c_mm": baseline_c * 1000,
                "baseline_distance": baseline_distance,  # Total distance in meters
                "accuracy": accuracy,
                "iar_num_hypotheses": iar_num_hypotheses,
                "tow": tow,
                "rtk_receiver_id": rtk_receiver_id,
                "rtk_health": rtk_health,
                "rtk_rate": rtk_rate,
                "nsats": nsats
            }
        }, message_type="rtk_baseline")

    def _handle_heading(self, message: Dict[str, Any]) -> None:
        """Handle compass heading updates."""
        self._broadcast_telem({
            "heading": float(message.get("data", 0.0))
        }, message_type="heading")

    def _handle_battery(self, message: Dict[str, Any]) -> None:
        """Handle battery status updates."""
        try:
            raw_pct = message.get("percentage", None)
            raw_volt = message.get("voltage", None)
            raw_curr = message.get("current", None)
            print(f"[MAVROS_BRIDGE] Battery msg: percentage={raw_pct}, voltage={raw_volt}, current={raw_curr}", flush=True)

            pct = float(raw_pct) if raw_pct is not None else -1.0
            import math
            if math.isnan(pct) or math.isinf(pct):
                # Skip invalid metrics
                return
            percentage = pct * 100.0  # Convert to percentage scale

            voltage = float(raw_volt) if raw_volt is not None else 0.0
            current = float(raw_curr) if raw_curr is not None else 0.0
            self._broadcast_telem({
                "battery": percentage,
                "voltage": voltage,
                "current": current
            }, message_type="battery")
            print(f"[MAVROS_BRIDGE] Battery broadcast: battery={percentage:.2f}%, voltage={voltage}, current={current}", flush=True)
        except Exception as e:
            # Never crash on telemetry
            print(f"[MAVROS_BRIDGE] Battery handler error: {e}", flush=True)

    def _handle_estimator_status(self, message: Dict[str, Any]) -> None:
        """Handle estimator status updates and expose IMU alignment state.

        The exact field naming can vary by autopilot/driver. Try a few common
        keys and fall back to a conservative default (unaligned).
        """
        aligned = None
        try:
            # Common field names from various stacks
            if 'aligned' in message:
                aligned = bool(message.get('aligned'))
            elif 'attitude_aligned' in message:
                aligned = bool(message.get('attitude_aligned'))
            elif isinstance(message.get('status'), dict) and 'attitude_aligned' in message.get('status'):
                aligned = bool(message.get('status', {}).get('attitude_aligned'))
            # Some messages provide numeric flags; try a simple bit-check fallback
            elif 'flags' in message:
                try:
                    flags = int(message.get('flags', 0))
                    aligned = bool(flags & 0x01)
                except Exception:
                    aligned = None
        except Exception:
            aligned = None

        if aligned is None:
            aligned = False

        # Broadcast a small payload for server to merge
        self._broadcast_telem({
            'imu_aligned': bool(aligned)
        }, message_type='estimator_status')

    def _handle_imu_data(self, message: Dict[str, Any]) -> None:
        """Expose raw IMU fields (orientation/ang vel/linear acc) to the backend.

        Avoid publishing large nested structures frequently; only include the
        main numeric groups so the frontend can display an 'IMU' value if
        desired.
        """
        try:
            orientation = message.get('orientation')
            angular_velocity = message.get('angular_velocity') or message.get('angular_velocity', {})
            linear_acceleration = message.get('linear_acceleration') or message.get('linear_acceleration', {})

            payload = {
                'imu': {
                    'orientation': orientation,
                    'angular_velocity': angular_velocity,
                    'linear_acceleration': linear_acceleration
                }
            }
            self._broadcast_telem(payload, message_type='imu')
        except Exception:
            # best-effort
            pass

    def _handle_sys_status(self, message: Dict[str, Any]) -> None:
        """Handle system status updates."""
        self._broadcast_telem({
            "cpu_load": float(message.get("load", 0.0)),
            "drop_rate": float(message.get("drop_rate_comm", 0.0))
        }, message_type="sys_status")

    def _handle_velocity(self, message: Dict[str, Any]) -> None:
        """Handle velocity updates."""
        twist = message.get("twist", {})
        linear = twist.get("linear", {})
        self._broadcast_telem({
            "groundspeed": ((linear.get("x", 0.0) ** 2 + linear.get("y", 0.0) ** 2) ** 0.5)
        }, message_type="velocity")

    def _handle_rc(self, message: Dict[str, Any]) -> None:
        """Handle RC input status."""
        channels = message.get("channels", [])
        self._broadcast_telem({
            "rc_connected": len(channels) > 0
        }, message_type="rc")

    def _handle_signal(self, message: Dict[str, Any]) -> None:
        """Handle radio signal strength."""
        rssi = message.get("rssi", 0)
        # Convert RSSI to descriptive signal strength
        if rssi > -50:
            strength = "Excellent"
        elif rssi > -60:
            strength = "Good"
        elif rssi > -70:
            strength = "Fair"
        else:
            strength = "Poor"
            
        self._broadcast_telem({
            "signal_strength": strength
        }, message_type="signal")

    def _handle_waypoint_list(self, message: Dict[str, Any]) -> None:
        """Handle mission waypoint updates."""
        with self._lock:
            self._latest_waypoints = message
            self._waypoint_event.set()

        waypoints = message.get("waypoints", [])
        current_seq = message.get("current_seq")
        payload: Dict[str, Any] = {
            "waypoints": waypoints,
            "current_seq": current_seq
        }
        if waypoints:
            payload["mission_progress"] = {
                "total": len(waypoints),
                "current": 0  # Will be updated by reached messages
            }
        self._broadcast_telem(payload, message_type="mission_list")

    def _handle_waypoint_reached(self, message: Dict[str, Any]) -> None:
        """Handle waypoint reached updates (roslibpy/rosbridge path).

        IMPORTANT: This callback runs inside the roslibpy WebSocket thread.
        We MUST offload _broadcast_telem to a separate thread, otherwise
        downstream code (e.g. set_mode service call) will block the entire
        roslibpy message loop — stopping all GPS/battery telemetry.
        """
        wp_seq = message.get("wp_seq", 0)
        print(f"[MAVROS_BRIDGE] WaypointReached: wp_seq={wp_seq}", flush=True)
        threading.Thread(
            target=self._broadcast_telem,
            args=({
                "mission_progress": {"current": wp_seq + 1},
                "wp_seq": wp_seq
            },),
            kwargs={"message_type": "mission_reached"},
            daemon=True
        ).start()

    def _handle_waypoint_reached_rclpy(self, msg) -> None:
        """Handle waypoint reached via rclpy (direct ROS2, more reliable).

        IMPORTANT: This callback runs inside the rclpy spin thread.
        We MUST offload _broadcast_telem to a separate thread, otherwise
        downstream code (e.g. set_mode service call) will deadlock the
        spin thread — it cannot process the service response while blocked
        in this callback.
        """
        wp_seq = msg.wp_seq
        print(f"[MAVROS_BRIDGE] WaypointReached (rclpy): wp_seq={wp_seq}", flush=True)
        threading.Thread(
            target=self._broadcast_telem,
            args=({
                "mission_progress": {"current": wp_seq + 1},
                "wp_seq": wp_seq
            },),
            kwargs={"message_type": "mission_reached"},
            daemon=True
        ).start()

    def _handle_servo_output(self, message: Dict[str, Any]) -> None:
        """Handle servo output (PWM) updates from /mavros/rc/out."""
        channels = message.get("channels", [])
        
        # Build servo state with PWM values for each channel
        # Channels are 0-indexed, so servo 1 is channels[0], etc.
        servo_state = {
            "channels": channels,
            "count": len(channels)
        }
        
        # Add individual servo PWM values (up to 16 servos)
        for i, pwm in enumerate(channels[:16], start=1):
            servo_state[f"servo{i}_pwm"] = int(pwm)
        
        self._broadcast_telem({
            "servo_output": servo_state
        }, message_type="servo_output")

