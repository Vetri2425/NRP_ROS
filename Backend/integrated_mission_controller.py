#!/usr/bin/env python3
"""
Integrated Mission Controller - Runs within FastAPI Application

This replaces the separate ROS2 node approach with a threaded mission controller
that runs directly in your FastAPI server.py process.
"""

import threading
import time
import json
import os
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
import math

# Import GPS failsafe monitor
try:
    from gps_failsafe_monitor import GPSFailsafeMonitor, calculate_accuracy_error_mm
except ImportError:
    try:
        from .gps_failsafe_monitor import GPSFailsafeMonitor, calculate_accuracy_error_mm
    except ImportError:
        GPSFailsafeMonitor = None
        calculate_accuracy_error_mm = None

# Import obstacle monitor
try:
    from obstacle_monitor import ObstacleMonitor
except ImportError:
    try:
        from .obstacle_monitor import ObstacleMonitor
    except ImportError:
        ObstacleMonitor = None


class MissionState(Enum):
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"


class MissionMode(Enum):
    MANUAL = "manual"
    AUTO = "auto"
    CONTINUOUS = "continuous"
    DASH = "dash"


class IntegratedMissionController:
    """
    Mission Controller that runs as part of the FastAPI application.
    Handles waypoint-by-waypoint execution with status callbacks.
    """
    
    def __init__(self, mavros_bridge, status_callback: Optional[Callable] = None, logger=None):
        self.bridge = mavros_bridge
        self.status_callback = status_callback
        self.logger = logger
        
        # Mission state
        self.mission_state = MissionState.IDLE
        self.mission_mode = MissionMode.AUTO
        self.waypoints: List[Dict[str, Any]] = []
        self.current_waypoint_index = 0
        self.mission_start_time: Optional[float] = None
        self.current_position: Optional[Dict[str, float]] = None
        self.pixhawk_state: Optional[Dict[str, Any]] = None
        
        # Configuration
        self.waypoint_reached_threshold = 0.250  # meters
        self.hold_duration = 0  # seconds
        self.mission_timeout = 3000.0  # 5 minutes per waypoint
        
        # GPS Failsafe thresholds (configurable)
        self.accuracy_threshold_mm = 60.0  # Suppress spray if GPS error exceeds this
        self.fallback_zone_timeout_seconds = 30.0  # Wait time before using distance fallback

        # Servo configuration (loaded from config file, can be overridden)
        self.servo_enabled = True  # Enable servo control after hold
        self.servo_channel = 9
        self.servo_pwm_on = 2300
        self.servo_pwm_off = 1750
        self.servo_delay_before = 0.0  # Delay BEFORE turning servo ON
        self.servo_spray_duration = 0.2  # Time between ON and OFF
        self.servo_delay_after = 0.0  # Delay after OFF before continuing
        
        # Threading
        self.lock = threading.RLock()  # Use RLock to allow reentrant locking
        self.hold_timer: Optional[threading.Timer] = None
        self.mission_timer: Optional[threading.Timer] = None
        self.position_check_timer: Optional[threading.Timer] = None
        self.running = True
        
        # Mission execution state
        self.waiting_for_waypoint_reach = False
        self.waypoint_upload_time: Optional[float] = None
        self.home_set = False  # Track if HOME position has been set

        # Continuous/Dash shared state
        self.multi_waypoint_mode = False
        self.first_mission_wp_reached = False
        self.continuous_servo_active = False
        self.last_telemetry_position = None
        self.last_wp_seq_reached = 0
        self.reached_waypoints: List[int] = []  # Track reached waypoint IDs (1-based) for resume

        # Dash mode specific
        self.dash_servo_on = False
        self.dash_last_toggle_position = None
        self.dash_cumulative_distance = 0.0
        self.dash_distance_since_toggle = 0.0
        self.dash_servo_on_distance = 5.0   # default 5m
        self.dash_servo_off_distance = 3.0  # default 3m
        
        # Dash time-based mode
        self.dash_last_toggle_time = None
        self.dash_servo_on_time = 2.0   # default 2s
        self.dash_servo_off_time = 1.0  # default 1s

        # REFACTOR: Use Pixhawk waypoint reached topic instead of distance calculation
        self.use_pixhawk_waypoint_reached = True  # Primary: use /mavros/mission/reached topic
        self.fallback_to_distance_check = True  # Fallback: use distance if topic fails
        self.last_telemetry_emission_time: float = 0  # Phase 2: Throttle telemetry emissions
        self.last_distance_check_time: float = 0  # For fallback distance monitoring

        # GPS Failsafe monitoring
        self.failsafe_mode = "disable"  # "strict", "relax", "disable"
        self.servo_suppressed = False  # Tracks if servo suppression active (relax mode)
        self.failsafe_position_at_arrival: Optional[Dict[str, float]] = None  # Position when waypoint reached
        self.rtk_fix_type = 0  # Current RTK fix type (0=invalid, 6=RTK Fixed)
        self.rtk_monitoring_active = False  # Track if RTK monitoring loop is running
        self.rtk_monitor_timer: Optional[threading.Timer] = None  # Timer for periodic RTK check
        self.last_known_good_rtk_fix_type = 6  # Track last good fix type (for detecting loss)
        
        if GPSFailsafeMonitor is not None:
            self.failsafe_monitor = GPSFailsafeMonitor(
                status_callback=self._emit_failsafe_status,
                logger=self.log
            )
            self.log("GPS Failsafe Monitor initialized")
        else:
            self.failsafe_monitor = None
            self.log("GPS Failsafe Monitor not available (import failed)")

        # Obstacle detection monitor with configurable zones
        self.obstacle_detection_enabled = False  # Disabled by default, frontend enables it
        self.obstacle_warning_min_mm = 1200  # 1.2m - configurable warning zone minimum
        self.obstacle_warning_max_mm = 2000  # 2.0m - configurable warning zone maximum
        self.obstacle_danger_min_mm = 800    # 0.8m - configurable danger zone minimum
        self.obstacle_danger_max_mm = 1000   # 1.0m - configurable danger zone maximum
        
        if ObstacleMonitor is not None:
            try:
                self.obstacle_monitor = ObstacleMonitor(
                    callback=self._handle_obstacle,
                    logger=self.log
                )
                # Update zone thresholds after initialization (if the monitor supports it)
                # For now, zone thresholds are class constants, so they're set at class level
                self.log("Obstacle monitor initialized (A2111BU on /dev/ttyTHS1) - disabled by default")
            except Exception as e:
                self.log(f"Warning: Failed to initialize obstacle monitor: {e}", "warning")
                self.obstacle_monitor = None
        else:
            self.obstacle_monitor = None
            self.log("Obstacle monitor not available (import failed)")

        # Load persisted mission mode before the first status emission.
        self._load_persisted_mission_mode()

        # Start telemetry subscription
        self.start_telemetry_subscription()

        self.log("Mission controller initialized")
        self.emit_status("Mission controller initialized", "info")
        self.emit_status(
            f"Loaded mission mode: {self.mission_mode.value}",
            "info",
            extra_data={"event_type": "mission_mode_loaded"}
        )

    def _config_file_path(self) -> str:
        """Return absolute path to mission controller config."""
        return os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')

    def _load_persisted_mission_mode(self):
        """Load persisted mission mode from config system_settings."""
        mode_map = {mode.value: mode for mode in MissionMode}
        config_file = self._config_file_path()

        try:
            if not os.path.exists(config_file):
                self.log("Mission mode config not found, using default AUTO", "info")
                return

            with open(config_file, 'r') as f:
                config = json.load(f)

            system_settings = config.get('system_settings', {})
            configured_mode = str(system_settings.get('mission_mode', self.mission_mode.value)).strip().lower()
            loaded_mode = mode_map.get(configured_mode)

            if loaded_mode is None:
                self.log(
                    f"Invalid persisted mission_mode='{configured_mode}', using default {self.mission_mode.value}",
                    "warning"
                )
                return

            self.mission_mode = loaded_mode
            self.log(f"Loaded persisted mission mode: {self.mission_mode.value}", "info")
        except Exception as e:
            self.log(f"Failed to load persisted mission mode: {e}", "warning")

    def _persist_mission_mode(self, mode: MissionMode) -> bool:
        """Persist mission mode into config system_settings for restart safety."""
        config_file = self._config_file_path()
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
            else:
                config = {
                    "mission_controller": {},
                    "system_settings": {},
                    "metadata": {}
                }

            if 'system_settings' not in config:
                config['system_settings'] = {}

            config['system_settings']['mission_mode'] = mode.value
            config['metadata'] = {
                "version": "1.0",
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
            }

            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)

            return True
        except Exception as e:
            self.log(f"Failed to persist mission mode '{mode.value}': {e}", "warning")
            return False
    
    def log(self, message: str, level: str = "info"):
        """Log message with optional logger"""
        import sys
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        log_msg = f"[MISSION_CONTROLLER] [{timestamp}] {message}"
        
        # Always print to stdout for journalctl (unbuffered)
        print(log_msg, flush=True)
        
        # Also log through application logger if available
        if self.logger:
            try:
                log_func = getattr(self.logger, level, self.logger.info)
                log_func(log_msg)
            except Exception as e:
                print(f"[MISSION_CONTROLLER] Logger error: {e}", flush=True)
    
    def emit_status(self, message: str, level: str, extra_data: Optional[Dict[str, Any]] = None):
        """Emit status update via callback"""
        status_data = {
            'timestamp': datetime.now().isoformat(),
            'message': message,
            'level': level,
            'mission_state': self.mission_state.value,
            'mission_mode': self.mission_mode.value,
            'current_waypoint': self.current_waypoint_index + 1 if self.waypoints else 0,
            'total_waypoints': len(self.waypoints),
            'current_position': self.current_position,
            'pixhawk_state': self.pixhawk_state,
            'reached_waypoints': list(self.reached_waypoints)
        }
        
        # Calculate distance to next waypoint for CurrentState.distanceToNext
        if (self.waypoints and self.current_waypoint_index < len(self.waypoints) and
            self.current_position and 'lat' in self.current_position and 'lng' in self.current_position):
            try:
                waypoint = self.waypoints[self.current_waypoint_index]
                current_lat = self.current_position.get('lat', 0.0)
                current_lng = self.current_position.get('lng', 0.0)
                target_lat = waypoint.get('lat', 0.0)
                target_lng = waypoint.get('lng', 0.0)
                
                if current_lat != 0.0 and current_lng != 0.0 and target_lat != 0.0 and target_lng != 0.0:
                    distance_to_next = self.calculate_distance(current_lat, current_lng, target_lat, target_lng)
                    status_data['distance_to_next_m'] = distance_to_next
            except Exception as e:
                self.log(f"Error calculating distance to next waypoint: {e}", "warning")
        
        if extra_data:
            status_data.update(extra_data)
        
        if self.status_callback:
            try:
                self.status_callback(status_data)
            except Exception as e:
                self.log(f"Status callback error: {e}", "error")
    
    def start_telemetry_subscription(self):
        """Subscribe to telemetry updates from MAVROS bridge"""
        try:
            self.bridge.subscribe_telemetry(self.handle_telemetry_update)
            self.log("Subscribed to telemetry updates")
        except Exception as e:
            self.log(f"Failed to subscribe to telemetry: {e}", "error")
    
    def handle_telemetry_update(self, telemetry_data: Dict[str, Any]):
        """Handle telemetry updates from MAVROS bridge"""
        try:
            # Support multiple telemetry formats coming from MavrosBridge or
            # an existing normalized server-level telemetry payload.

            # Case A: telemetry_data uses flat keys from MavrosBridge
            # (e.g. 'latitude', 'longitude', 'altitude', 'mode', 'armed')
            if 'latitude' in telemetry_data or 'longitude' in telemetry_data:
                lat = telemetry_data.get('latitude') or telemetry_data.get('lat')
                lng = telemetry_data.get('longitude') or telemetry_data.get('lng')
                alt = telemetry_data.get('altitude') or telemetry_data.get('alt')
                try:
                    self.current_position = {
                        'lat': float(lat) if lat is not None else 0.0,
                        'lng': float(lng) if lng is not None else 0.0,
                        'alt': float(alt) if alt is not None else 0.0
                    }
                except Exception:
                    # ignore bad numeric values
                    pass

            # Case B: telemetry nested under 'global' (older formats)
            elif 'global' in telemetry_data:
                global_data = telemetry_data['global']
                self.current_position = {
                    'lat': global_data.get('latitude', 0.0),
                    'lng': global_data.get('longitude', 0.0),
                    'alt': global_data.get('altitude', 0.0)
                }

            # Update Pixhawk state from flat fields if present
            if any(k in telemetry_data for k in ('mode', 'armed', 'connected')):
                self.pixhawk_state = {
                    'mode': telemetry_data.get('mode', ''),
                    'armed': bool(telemetry_data.get('armed', False)),
                    'connected': bool(telemetry_data.get('connected', False)),
                    'system_status': telemetry_data.get('system_status', '')
                }

            # Or from nested 'state' field
            if 'state' in telemetry_data:
                state_data = telemetry_data['state']
                self.pixhawk_state = {
                    'mode': state_data.get('mode', ''),
                    'armed': state_data.get('armed', False),
                    'connected': state_data.get('connected', False),
                    'system_status': state_data.get('system_status', '')
                }
            
            # Track RTK fix type for failsafe movement control (strict mode)
            if 'rtk_fix_type' in telemetry_data:
                self.rtk_fix_type = int(telemetry_data.get('rtk_fix_type', 0))
            elif 'fix_type' in telemetry_data:
                self.rtk_fix_type = int(telemetry_data.get('fix_type', 0))

            # REFACTOR: Check for Pixhawk waypoint reached message (primary method)
            # DEBUG: Log mission_progress and type fields for waypoint detection
            if "wp_seq" in telemetry_data or "mission_progress" in telemetry_data:
                import json
                wp_seq = telemetry_data.get("wp_seq", "none")
                msg_type = telemetry_data.get("type", "none")
                mission_prog = telemetry_data.get("mission_progress", {})
                #self.log(f"DEBUG_MISSION: wp_seq={wp_seq} type={msg_type} mission_progress={mission_prog}", "debug")

            if 'mission_progress' in telemetry_data:
                mission_progress = telemetry_data.get('mission_progress', {})
                message_type = telemetry_data.get('type', '')

                # Check if this is a waypoint reached message from Pixhawk
                if (message_type == 'mission_reached' and
                    self.use_pixhawk_waypoint_reached and
                    self.mission_state == MissionState.RUNNING and
                    self.waiting_for_waypoint_reach):

                    # Extract waypoint sequence from mission progress
                    wp_seq = telemetry_data.get('wp_seq')  # wp_seq is top-level
                    if wp_seq is not None:
                        self.log(f'📡 RECEIVED /mavros/mission/reached: wp_seq={wp_seq}', 'info')
                        # IMPORTANT: Offload to daemon thread so the roslibpy/rclpy
                        # callback thread (which delivers ALL telemetry) is never
                        # blocked by set_pixhawk_mode() or other slow operations.
                        threading.Thread(
                            target=self.handle_pixhawk_waypoint_reached,
                            args=(wp_seq,),
                            daemon=True
                        ).start()

            # Fallback: Check distance if enabled and topic hasn't triggered
            if (self.fallback_to_distance_check and
                self.mission_state == MissionState.RUNNING and
                self.waiting_for_waypoint_reach and
                self.current_position):

                # Only check distance every 0.5 seconds (not every telemetry update)
                current_time = time.time()
                if current_time - self.last_distance_check_time >= 1.0:
                    self.last_distance_check_time = current_time
                    # IMPORTANT: Offload to daemon thread — distance fallback may
                    # call waypoint_reached() → set_pixhawk_mode() which blocks.
                    # Running on the roslibpy callback thread would freeze all telemetry.
                    threading.Thread(
                        target=self.check_waypoint_reached_distance_fallback,
                        daemon=True
                    ).start()

            # Dash mode time-based tracking (after position update)
            if (self.mission_mode == MissionMode.DASH and
                self.mission_state == MissionState.RUNNING and
                self.first_mission_wp_reached):
                
                self._update_dash_time()
            
            # # Dash mode distance tracking (COMMENTED - using time-based instead)
            # if (self.mission_mode == MissionMode.DASH and
            #     self.mission_state == MissionState.RUNNING and
            #     self.first_mission_wp_reached and
            #     self.current_position):
            #     
            #     self._update_dash_distance()

            # Emit a generic telemetry update for the frontend (position, battery, mode, etc.)
            # Skip when actively navigating to a waypoint — the periodic status logger already
            # emits structured mission_progress events at 5Hz in that state.
            current_time = time.time()
            if self.current_position or self.pixhawk_state:
                navigating = (
                    self.mission_state == MissionState.RUNNING
                    and self.waiting_for_waypoint_reach
                    and getattr(self, '_status_logging_active', False)
                )
                if not navigating:
                    time_since_last_emission = current_time - self.last_telemetry_emission_time
                    if time_since_last_emission >= 0.2:
                        self.emit_status("Telemetry update", "info")
                        self.last_telemetry_emission_time = current_time

        except Exception as e:
            self.log(f"Telemetry handling error: {e}", "error")
    
    def process_command(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process mission command and return response"""
        try:
            command = command_data.get('command', '')
            self.log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.log(f"📥 COMMAND RECEIVED: {command.upper()}")
            self.log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            
            if command == 'load_mission':
                return self.load_mission(command_data)
            elif command == 'start':
                return self.start_mission()
            elif command == 'stop':
                return self.stop_mission()
            elif command == 'pause':
                return self.pause_mission()
            elif command == 'resume':
                return self.resume_mission()
            elif command == 'restart':
                return self.restart_mission()
            elif command == 'next':
                return self.next_waypoint()
            elif command == 'skip':
                return self.skip_waypoint()
            elif command == 'set_mode':
                mode = command_data.get('mode', 'auto')
                return self.set_mode(mode)
            else:
                return {'success': False, 'error': f'Unknown command: {command}'}
                
        except Exception as e:
            error_msg = f"Command processing error: {str(e)}"
            self.log(error_msg, "error")
            return {'success': False, 'error': error_msg}
    
    def update_servo_config(self, servo_config: Dict[str, Any]) -> Dict[str, Any]:
        """Update servo configuration dynamically"""
        try:
            # Validate ALL values before applying any (atomic: reject all or accept all)
            validated = {}

            if 'servo_channel' in servo_config:
                ch = int(servo_config['servo_channel'])
                if not (1 <= ch <= 16):
                    return {'success': False, 'error': f'servo_channel {ch} out of range (1-16)'}
                validated['servo_channel'] = ch

            if 'servo_pwm_on' in servo_config:
                pwm = int(servo_config['servo_pwm_on'])
                if not (800 <= pwm <= 2500):
                    return {'success': False, 'error': f'servo_pwm_on {pwm} out of range (800-2500 µs)'}
                validated['servo_pwm_on'] = pwm

            if 'servo_pwm_off' in servo_config:
                pwm = int(servo_config['servo_pwm_off'])
                if not (800 <= pwm <= 2500):
                    return {'success': False, 'error': f'servo_pwm_off {pwm} out of range (800-2500 µs)'}
                validated['servo_pwm_off'] = pwm

            if 'servo_delay_before' in servo_config:
                val = float(servo_config['servo_delay_before'])
                if not (0.0 <= val <= 60.0):
                    return {'success': False, 'error': f'servo_delay_before {val} out of range (0-60 s)'}
                validated['servo_delay_before'] = val

            if 'servo_spray_duration' in servo_config:
                val = float(servo_config['servo_spray_duration'])
                if not (0.0 <= val <= 60.0):
                    return {'success': False, 'error': f'servo_spray_duration {val} out of range (0-60 s)'}
                validated['servo_spray_duration'] = val

            if 'servo_delay_after' in servo_config:
                val = float(servo_config['servo_delay_after'])
                if not (0.0 <= val <= 60.0):
                    return {'success': False, 'error': f'servo_delay_after {val} out of range (0-60 s)'}
                validated['servo_delay_after'] = val

            if 'servo_enabled' in servo_config:
                validated['servo_enabled'] = bool(servo_config['servo_enabled'])

            # Apply all validated values
            updated_params = []
            for key, value in validated.items():
                setattr(self, key, value)
                updated_params.append(f"{key}={value}")

            self.log(f"✓ Servo config updated: {', '.join(updated_params)}")

            return {
                'success': True,
                'message': 'Servo configuration updated',
                'updated_params': updated_params
            }
        except (TypeError, ValueError) as e:
            error_msg = f"Invalid servo config value: {str(e)}"
            self.log(error_msg, "error")
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Failed to update servo config: {str(e)}"
            self.log(error_msg, "error")
            return {'success': False, 'error': error_msg}
    
    def update_mission_parameters(self, mission_params: Dict[str, Any]) -> Dict[str, Any]:
        """Update mission execution parameters dynamically"""
        try:
            # Validate ALL values before applying any (atomic: reject all or accept all)
            validated = {}

            if 'mission_timeout' in mission_params:
                val = float(mission_params['mission_timeout'])
                if val <= 0:
                    return {'success': False, 'error': f'mission_timeout must be > 0 (got {val})'}
                validated['mission_timeout'] = val

            if 'accuracy_threshold_mm' in mission_params:
                val = float(mission_params['accuracy_threshold_mm'])
                if val <= 0:
                    return {'success': False, 'error': f'accuracy_threshold_mm must be > 0 (got {val})'}
                validated['accuracy_threshold_mm'] = val

            if 'fallback_zone_timeout_seconds' in mission_params:
                val = float(mission_params['fallback_zone_timeout_seconds'])
                if val <= 0:
                    return {'success': False, 'error': f'fallback_zone_timeout_seconds must be > 0 (got {val})'}
                validated['fallback_zone_timeout_seconds'] = val

            # Apply all validated values
            updated_params = []
            for key, value in validated.items():
                setattr(self, key, value)
                updated_params.append(f"{key}={value}")

            self.log(f"✓ Mission parameters updated: {', '.join(updated_params)}")

            return {
                'success': True,
                'message': 'Mission parameters updated',
                'updated_params': updated_params
            }
        except (TypeError, ValueError) as e:
            error_msg = f"Invalid mission parameter value: {str(e)}"
            self.log(error_msg, "error")
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Failed to update mission parameters: {str(e)}"
            self.log(error_msg, "error")
            return {'success': False, 'error': error_msg}
    
    def update_obstacle_zones(self, obstacle_config: Dict[str, Any]) -> Dict[str, Any]:
        """Update obstacle detection zones dynamically"""
        try:
            # Parse incoming values, fall back to current values for unchanged fields
            warning_min = float(obstacle_config.get('warning_min_mm', self.obstacle_warning_min_mm))
            warning_max = float(obstacle_config.get('warning_max_mm', self.obstacle_warning_max_mm))
            danger_min  = float(obstacle_config.get('danger_min_mm',  self.obstacle_danger_min_mm))
            danger_max  = float(obstacle_config.get('danger_max_mm',  self.obstacle_danger_max_mm))

            # Validate individual zones are internally consistent
            if danger_min >= danger_max:
                return {'success': False, 'error': f'danger_min ({danger_min}mm) must be less than danger_max ({danger_max}mm)'}
            if warning_min >= warning_max:
                return {'success': False, 'error': f'warning_min ({warning_min}mm) must be less than warning_max ({warning_max}mm)'}
            # Danger zone must be closer (smaller distance) than warning zone
            if danger_max > warning_min:
                return {'success': False, 'error': f'danger_max ({danger_max}mm) must be <= warning_min ({warning_min}mm): danger zone must be closer than warning zone'}

            # Apply all validated values
            self.obstacle_warning_min_mm = warning_min
            self.obstacle_warning_max_mm = warning_max
            self.obstacle_danger_min_mm  = danger_min
            self.obstacle_danger_max_mm  = danger_max

            updated_params = [
                f"danger={danger_min}-{danger_max}mm",
                f"warning={warning_min}-{warning_max}mm"
            ]

            # Note: Zone configuration is stored but ObstacleMonitor has fixed class-level constants
            # To support dynamic zones, ObstacleMonitor would need to be refactored
            self.log(f"✓ Obstacle zones updated (local config): {', '.join(updated_params)}")

            return {
                'success': True,
                'message': 'Obstacle detection zones updated',
                'updated_params': updated_params
            }
        except (TypeError, ValueError) as e:
            error_msg = f"Invalid obstacle zone value: {str(e)}"
            self.log(error_msg, "error")
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Failed to update obstacle zones: {str(e)}"
            self.log(error_msg, "error")
            return {'success': False, 'error': error_msg}
    
    def load_mission(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Load waypoints and mission configuration"""
        with self.lock:
            try:
                waypoints = command_data.get('waypoints', [])
                config = command_data.get('config', {})
                
                self.log(f"📦 Received {len(waypoints)} waypoint(s) in load_mission command")
                
                if not waypoints:
                    self.log(f"❌ Error: No waypoints provided", "error")
                    return {'success': False, 'error': 'No waypoints provided'}
                
                # Validate waypoints
                self.log(f"✓ Validating waypoints...")
                for i, wp in enumerate(waypoints):
                    if 'lat' not in wp or 'lng' not in wp:
                        self.log(f"❌ Waypoint {i} validation failed: missing lat/lng", "error")
                        return {'success': False, 'error': f'Waypoint {i} missing lat/lng'}
                    try:
                        lat_val = float(wp['lat'])
                        lng_val = float(wp['lng'])
                    except (TypeError, ValueError):
                        self.log(f"❌ Waypoint {i}: lat/lng not numeric", "error")
                        return {'success': False, 'error': f'Waypoint {i}: lat/lng must be numeric values'}
                    if not (-90.0 <= lat_val <= 90.0):
                        self.log(f"❌ Waypoint {i}: latitude {lat_val} out of range [-90, 90]", "error")
                        return {'success': False, 'error': f'Waypoint {i}: latitude {lat_val} out of range (-90 to 90)'}
                    if not (-180.0 <= lng_val <= 180.0):
                        self.log(f"❌ Waypoint {i}: longitude {lng_val} out of range [-180, 180]", "error")
                        return {'success': False, 'error': f'Waypoint {i}: longitude {lng_val} out of range (-180 to 180)'}
                self.log(f"✓ All waypoints validated successfully")
                
                # Validate and process per-waypoint marking flag
                for i, wp in enumerate(waypoints):
                    if 'mark' in wp:
                        # Ensure mark is boolean
                        if not isinstance(wp['mark'], bool):
                            self.log(f"⚠ Waypoint {i+1}: invalid mark value '{wp['mark']}', converting to boolean")
                            waypoints[i]['mark'] = bool(wp['mark'])
                        self.log(f'  WP{i+1}: mark={waypoints[i]["mark"]}')
                
                self.waypoints = waypoints
                self.current_waypoint_index = 0
                self.reached_waypoints = []
                self.log(f"📝 Setting mission state: IDLE → READY")
                self.mission_state = MissionState.READY
                
                # Update configuration
                if 'waypoint_threshold' in config:
                    self.waypoint_reached_threshold = float(config['waypoint_threshold'])
                if 'hold_duration' in config:
                    self.hold_duration = float(config['hold_duration'])
                if 'auto_mode' in config:
                    self.mission_mode = MissionMode.AUTO if config['auto_mode'] else MissionMode.MANUAL
                
                # Update servo configuration if provided
                if any(key.startswith('servo_') for key in config.keys()):
                    servo_config = {k: v for k, v in config.items() if k.startswith('servo_')}
                    self.update_servo_config(servo_config)
                
                # Load dash configuration if provided
                if 'dash_servo_on_time' in config:
                    self.dash_servo_on_time = float(config['dash_servo_on_time'])
                    self.log(f"Dash servo ON time set to {self.dash_servo_on_time}s")
                    
                if 'dash_servo_off_time' in config:
                    self.dash_servo_off_time = float(config['dash_servo_off_time'])
                    self.log(f"Dash servo OFF time set to {self.dash_servo_off_time}s")
                
                # Distance-based config (kept for future use)
                if 'dash_servo_on_distance' in config:
                    self.dash_servo_on_distance = float(config['dash_servo_on_distance'])
                    self.log(f"Dash servo ON distance set to {self.dash_servo_on_distance}m (not active)")
                    
                if 'dash_servo_off_distance' in config:
                    self.dash_servo_off_distance = float(config['dash_servo_off_distance'])
                    self.log(f"Dash servo OFF distance set to {self.dash_servo_off_distance}m (not active)")
                
                # Log dash config when in dash mode
                if self.mission_mode == MissionMode.DASH:
                    self.log(f'Dash Config: ON time={self.dash_servo_on_time}s, OFF time={self.dash_servo_off_time}s')
                    self.log(f"✓ Applied servo configuration from load_mission")
                
                # Log mission load details
                self.log(f'═══════════════════════════════════════════════════')
                self.log(f'MISSION LOADED: {len(waypoints)} waypoints')
                self.log(f'Mission Mode: {self.mission_mode.value}')
                self.log(f'Waypoint Threshold: {self.waypoint_reached_threshold}m')
                self.log(f'Hold Duration: {self.hold_duration}s')
                self.log(f'Servo Config: channel={self.servo_channel}, pwm_on={self.servo_pwm_on}, pwm_off={self.servo_pwm_off}')
                self.log(f'Servo Timing: before={self.servo_delay_before}s, spray={self.servo_spray_duration}s, after={self.servo_delay_after}s, enabled={self.servo_enabled}')
                for i, wp in enumerate(waypoints, 1):
                    mark_status = wp.get('mark', self.servo_enabled)
                    mark_str = 'MARK' if mark_status else 'SKIP'
                    self.log(f'  WP{i}: lat={wp["lat"]:.9f}, lng={wp["lng"]:.9f}, alt={wp.get("alt", 10.0)}m [{mark_str}]')
                self.log(f'═══════════════════════════════════════════════════')
                self.emit_status(
                    f"Mission loaded with {len(waypoints)} waypoints",
                    "success",
                    extra_data={
                        "event_type": "mission_loaded",
                        "waypoints_count": len(waypoints),
                        "mode": self.mission_mode.value,
                        "waypoints": waypoints
                    }
                )
                
                return {
                    'success': True,
                    'message': f'Mission loaded with {len(waypoints)} waypoints',
                    'waypoints_count': len(waypoints)
                }
                
            except Exception as e:
                self.mission_state = MissionState.ERROR
                error_msg = f"Failed to load mission: {str(e)}"
                self.log(error_msg, "error")
                self.emit_status(
                    error_msg,
                    "error",
                    extra_data={
                        "event_type": "mission_error",
                        "error_source": "load_mission",
                        "error_message": error_msg
                    }
                )
                return {'success': False, 'error': error_msg}
    
    def start_mission(self) -> Dict[str, Any]:
        """Start mission execution"""
        with self.lock:
            self.log(f"🎬 START command received")
            self.log(f"Current state: {self.mission_state.value}")
            self.log(f"Waypoints loaded: {len(self.waypoints)}")

            # PHASE 3 FIX: Allow starting from COMPLETED state (in case auto-transition fails)
            # Allow starting from READY, PAUSED, IDLE, STOPPED, or COMPLETED (if waypoints are loaded)
            if self.mission_state not in [MissionState.READY, MissionState.PAUSED, MissionState.IDLE, MissionState.STOPPED, MissionState.COMPLETED]:
                self.log(f"❌ Cannot start - invalid state: {self.mission_state.value}", "error")
                return {'success': False, 'error': f'Cannot start mission - invalid state: {self.mission_state.value}'}

            if not self.waypoints:
                self.log(f"❌ Cannot start - no waypoints loaded", "error")
                return {'success': False, 'error': 'No waypoints loaded'}

        # ARM CHECK outside the lock (blocking bridge call)
        self.log("⚡ Verifying vehicle armed state before mission start...")
        self.emit_status(
            "Verifying vehicle armed state...",
            "info",
            extra_data={"event_type": "mission_arming"}
        )
        self.bridge.suppress_disconnect_check(True)
        try:
            arm_ok = self.ensure_pixhawk_armed()
        finally:
            self.bridge.suppress_disconnect_check(False)
        if not arm_ok:
            msg = 'Arm failed. Mission cannot start until the vehicle is armed.'
            self.log(f"❌ {msg}", "error")
            self.emit_status(msg, "error", extra_data={"event_type": "mission_arm_error"})
            return {'success': False, 'error': msg}
        self.log("✅ Vehicle armed — proceeding with mission start")

        with self.lock:
            # Re-check state after releasing/re-acquiring lock
            if self.mission_state not in [MissionState.READY, MissionState.PAUSED, MissionState.IDLE, MissionState.STOPPED, MissionState.COMPLETED]:
                return {'success': False, 'error': f'State changed during arm check: {self.mission_state.value}'}

            # Remember if we're resuming from pause
            was_paused = self.mission_state == MissionState.PAUSED

            self.mission_state = MissionState.RUNNING
            self.mission_start_time = time.time()
            
            # Only reset waypoint index if not resuming from pause
            if not was_paused:
                self.current_waypoint_index = 0
                self.reached_waypoints = []
            
            # Initialize failsafe monitor
            if self.failsafe_monitor:
                self.failsafe_monitor.start_mission()
            
            # Start RTK monitoring if in STRICT mode
            if self.failsafe_mode == "strict":
                self._start_rtk_monitoring()

            # Start obstacle detection (if enabled by frontend)
            if self.obstacle_monitor and self.obstacle_detection_enabled:
                self.obstacle_monitor.start()
                self.log(f'Obstacle Detection: ENABLED (danger ≤{self.obstacle_danger_max_mm}mm, warning ≤{self.obstacle_warning_max_mm}mm)')
            else:
                self.log(f'Obstacle Detection: DISABLED (monitor={self.obstacle_monitor is not None}, enabled={self.obstacle_detection_enabled})')

            self.log(f'═══════════════════════════════════════════════════')
            self.log(f'🚀 MISSION STARTED')
            self.log(f'Starting from waypoint {self.current_waypoint_index + 1}/{len(self.waypoints)}')
            self.log(f'Mission Mode: {self.mission_mode.value}')
            self.log(f'GPS Failsafe Mode: {self.failsafe_mode}')
            self.log(f'═══════════════════════════════════════════════════')
            self.emit_status(
                "Mission started",
                "success",
                extra_data={
                    "event_type": "mission_started"
                }
            )
            
            # Execute first/current waypoint or all waypoints based on mode
            if self.mission_mode in [MissionMode.CONTINUOUS, MissionMode.DASH]:
                # Multi-waypoint mode: upload all waypoints at once
                self.execute_all_waypoints()
            else:
                # Traditional point-by-point mode
                self.execute_current_waypoint()
            
            return {
                'success': True,
                'message': 'Mission started',
                'current_waypoint': self.current_waypoint_index + 1
            }
    
    def stop_mission(self) -> Dict[str, Any]:
        """Stop mission execution"""
        need_servo_off = False
        with self.lock:
            if self.mission_state not in [MissionState.RUNNING, MissionState.PAUSED]:
                return {'success': False, 'error': 'No mission running'}

            # Stop RTK monitoring
            self._stop_rtk_monitoring()

            # Stop obstacle detection
            if self.obstacle_monitor:
                self.obstacle_monitor.stop()

            # Set state to STOPPED to show red solid LED
            self.mission_state = MissionState.STOPPED
            self.cancel_timers()
            self.waiting_for_waypoint_reach = False
            self.home_set = False  # Reset HOME flag so it gets set again on restart

            # Check if servo needs to be turned off
            if self.continuous_servo_active or self.dash_servo_on:
                need_servo_off = True
                self.continuous_servo_active = False
                self.dash_servo_on = False

            # Reset multi-waypoint mode state
            self.multi_waypoint_mode = False
            self.first_mission_wp_reached = False
            self.last_telemetry_position = None
            self.last_wp_seq_reached = 0

            # Reset dash mode specific state
            self.dash_last_toggle_position = None
            self.dash_cumulative_distance = 0.0
            self.dash_distance_since_toggle = 0.0
            self.dash_last_toggle_time = None

        # Blocking bridge calls OUTSIDE the lock
        if need_servo_off:
            self.log("🔴 Forcing servo OFF due to mission stop")
            try:
                self.bridge.set_servo(self.servo_channel, self.servo_pwm_off)
            except Exception as e:
                self.log(f"Warning: servo OFF on stop failed: {e}", "warning")

        self.bridge.suppress_disconnect_check(True)
        try:
            self.set_pixhawk_mode("HOLD")
        finally:
            self.bridge.suppress_disconnect_check(False)

        self.log('Mission stopped')
        self.emit_status("Mission stopped", "info", extra_data={"event_type": "mission_stopped"})

        return {'success': True, 'message': 'Mission stopped'}
    
    def pause_mission(self) -> Dict[str, Any]:
        """Pause mission execution"""
        need_servo_off = False
        with self.lock:
            if self.mission_state != MissionState.RUNNING:
                return {'success': False, 'error': 'No mission running'}

            # Stop RTK monitoring
            self._stop_rtk_monitoring()

            # Stop obstacle detection
            if self.obstacle_monitor:
                self.obstacle_monitor.stop()

            self.mission_state = MissionState.PAUSED
            self.cancel_timers()
            self.waiting_for_waypoint_reach = False

            # Check if servo needs to be turned off
            if self.continuous_servo_active or self.dash_servo_on:
                need_servo_off = True
                self.continuous_servo_active = False
                self.dash_servo_on = False

        # Blocking bridge calls OUTSIDE the lock
        if need_servo_off:
            self.log("🔴 Forcing servo OFF due to mission pause")
            try:
                self.bridge.set_servo(self.servo_channel, self.servo_pwm_off)
            except Exception as e:
                self.log(f"Warning: servo OFF on pause failed: {e}", "warning")

        self.bridge.suppress_disconnect_check(True)
        try:
            self.set_pixhawk_mode("HOLD")
        finally:
            self.bridge.suppress_disconnect_check(False)

        self.log('Mission paused')
        self.emit_status("Mission paused", "info", extra_data={"event_type": "mission_paused"})

        return {'success': True, 'message': 'Mission paused'}
    
    def resume_mission(self) -> Dict[str, Any]:
        """Resume paused mission"""
        with self.lock:
            if self.mission_state != MissionState.PAUSED:
                return {'success': False, 'error': 'No paused mission'}
            
            self.mission_state = MissionState.RUNNING

            # Resume RTK monitoring if in STRICT mode
            if self.failsafe_mode == "strict":
                self._start_rtk_monitoring()

            # Resume obstacle detection
            if self.obstacle_monitor:
                self.obstacle_monitor.start()

            self.log('Mission resumed')
            self.emit_status("Mission resumed", "success", extra_data={"event_type": "mission_resumed"})

            # Re-emit waypoint_reached events for all previously reached waypoints
            # so frontend can reconstruct correct status after pause/resume
            for wp_id in self.reached_waypoints:
                self.emit_status(
                    f"Waypoint {wp_id} reached",
                    "info",
                    extra_data={
                        "event_type": "waypoint_reached",
                        "waypoint_id": wp_id,
                        "wp_seq": wp_id,
                        "is_replay": True,
                        "mode": self.mission_mode.value
                    }
                )

            if self.multi_waypoint_mode:
                # Continuous/dash: waypoints already on Pixhawk, just restore AUTO mode
                self.log("🔄 Continuous mode resume: restoring AUTO mode (no re-upload)")
                self.waiting_for_waypoint_reach = True
                self.start_periodic_status_logging()
                # Dash: reset toggle timer so servo doesn't instantly fire due to pause duration
                if self.mission_mode == MissionMode.DASH and self.dash_last_toggle_time is not None:
                    self.dash_last_toggle_time = time.time()
                self.set_pixhawk_mode("AUTO")
            else:
                # Point-by-point: re-upload current waypoint
                self.execute_current_waypoint()

            return {'success': True, 'message': 'Mission resumed'}
    
    def restart_mission(self) -> Dict[str, Any]:
        """Restart mission from beginning"""
        with self.lock:
            if not self.waypoints:
                return {'success': False, 'error': 'No waypoints loaded'}

        # ARM CHECK outside the lock (blocking bridge call)
        self.bridge.suppress_disconnect_check(True)
        try:
            arm_ok = self.ensure_pixhawk_armed()
        finally:
            self.bridge.suppress_disconnect_check(False)
        if not arm_ok:
            msg = 'Arm failed. Mission cannot restart until the vehicle is armed.'
            self.log(f"❌ {msg}", "error")
            self.emit_status(msg, "error", extra_data={"event_type": "mission_arm_error"})
            return {'success': False, 'error': msg}

        with self.lock:
            if not self.waypoints:
                return {'success': False, 'error': 'No waypoints loaded'}

            self.current_waypoint_index = 0
            self.reached_waypoints = []
            self.cancel_timers()
            self.waiting_for_waypoint_reach = False

            self.mission_state = MissionState.RUNNING
            self.mission_start_time = time.time()

            self.log('Mission restarted')
            self.emit_status("Mission restarted", "success", extra_data={"event_type": "mission_restarted"})

            if self.mission_mode in [MissionMode.CONTINUOUS, MissionMode.DASH]:
                self.execute_all_waypoints()
            else:
                self.execute_current_waypoint()

            return {'success': True, 'message': 'Mission restarted'}
    
    def set_failsafe_mode(self, mode: str) -> Dict[str, Any]:
        """Set GPS failsafe mode (strict/relax/disable)"""
        if mode not in ['strict', 'relax', 'disable']:
            return {'success': False, 'error': f'Invalid mode: {mode}'}
        
        with self.lock:
            self.failsafe_mode = mode
            if self.failsafe_monitor:
                self.failsafe_monitor.set_mode(mode)
            self.log(f"Failsafe mode set to: {mode}", "info")
            return {'success': True, 'message': f'Failsafe mode: {mode.upper()}'}
    
    def acknowledge_failsafe(self) -> Dict[str, Any]:
        """User acknowledges failsafe in strict mode"""
        with self.lock:
            if not self.failsafe_monitor:
                return {'success': False, 'error': 'Failsafe monitor not available'}
            return self.failsafe_monitor.acknowledge_failsafe()
    
    def _emit_failsafe_status(self, status_data: Dict[str, Any]):
        """Internal callback from failsafe monitor to emit status"""
        self.emit_status(
            status_data.get('message', 'Failsafe status update'),
            'warning' if status_data.get('triggered') else 'info',
            extra_data={
                'event_type': 'failsafe_status',
                'failsafe_status': status_data
            }
        )
    
    def check_rtk_fix_for_movement(self) -> bool:
        """
        Check if RTK fix is good enough for movement (strict mode only).
        
        Returns:
            True if movement allowed
            False if movement blocked (strict mode + bad RTK fix)
        """
        # Relax and disable modes always allow movement
        if self.failsafe_mode != "strict":
            return True
        
        # Strict mode: RTK fix must be 6 (RTK Fixed)
        if self.rtk_fix_type != 6:
            self.log(f"❌ STRICT MODE - RTK FIX BLOCKED: fix_type={self.rtk_fix_type} (need 6)", "warning")
            self.emit_status(
                f"RTK Fix Loss - Movement Paused: fix_type={self.rtk_fix_type} (need 6 for RTK Fixed)",
                "warning",
                extra_data={
                    'event_type': 'rtk_fix_loss',
                    'rtk_fix_type': self.rtk_fix_type,
                    'required_fix_type': 6,
                    'failsafe_mode': 'strict'
                }
            )
            return False
        
        return True
    
    def _start_rtk_monitoring(self):
        """
        Start continuous RTK monitoring during mission running.
        Periodically checks RTK fix type in STRICT mode.
        If fix_type != 6: Pause mission immediately.
        """
        if self.rtk_monitoring_active:
            return  # Already running
        
        self.rtk_monitoring_active = True
        self.log("📡 Starting continuous RTK monitoring (strict mode)", "info")
        self._monitor_rtk_continuous()
    
    def _stop_rtk_monitoring(self):
        """Stop continuous RTK monitoring."""
        self.rtk_monitoring_active = False
        if self.rtk_monitor_timer:
            self.rtk_monitor_timer.cancel()
            self.rtk_monitor_timer = None
        self.log("🛑 Stopped RTK monitoring", "debug")
    
    def _monitor_rtk_continuous(self):
        """
        Continuous RTK monitoring loop - runs every 0.5 seconds during mission.
        Checks if RTK fix has degraded in STRICT mode and pauses mission if so.
        """
        if not self.rtk_monitoring_active or self.mission_state != MissionState.RUNNING:
            return

        need_hold = False
        try:
            with self.lock:
                # Only check if in STRICT mode
                if self.failsafe_mode == "strict" and self.mission_state == MissionState.RUNNING:
                    # Check if RTK fix has degraded
                    if self.rtk_fix_type != 6:
                        # RTK fix loss detected in STRICT mode - PAUSE mission immediately
                        if self.last_known_good_rtk_fix_type == 6:
                            # This is a new loss (transition from 6 to non-6)
                            self.log(f"❌ RTK FIX LOSS DETECTED (continuous): fix_type={self.rtk_fix_type} (need 6)", "warning")
                            self.emit_status(
                                f"🚨 RTK Fix Loss - Mission Paused: fix_type={self.rtk_fix_type} (need 6)",
                                "warning",
                                extra_data={
                                    'event_type': 'rtk_loss_continuous',
                                    'rtk_fix_type': self.rtk_fix_type,
                                    'required_fix_type': 6,
                                    'failsafe_mode': 'strict',
                                    'action': 'mission_paused'
                                }
                            )
                            self.mission_state = MissionState.PAUSED
                            need_hold = True
                            self.log(f"⏸ Mission PAUSED - Awaiting RTK recovery", "warning")

                        self.last_known_good_rtk_fix_type = self.rtk_fix_type
                    else:
                        # RTK fix is good
                        if self.last_known_good_rtk_fix_type != 6:
                            # RTK has recovered (transition from non-6 to 6)
                            self.log(f"✅ RTK FIX RECOVERED: fix_type=6", "info")
                            self.emit_status(
                                "✅ RTK Fix Recovered - Ready to resume mission",
                                "success",
                                extra_data={
                                    'event_type': 'rtk_recovered',
                                    'rtk_fix_type': 6,
                                    'action': 'ready_for_resume'
                                }
                            )
                        self.last_known_good_rtk_fix_type = 6

            # Blocking bridge call OUTSIDE the lock to avoid stalling other threads
            if need_hold:
                self.bridge.suppress_disconnect_check(True)
                try:
                    self.set_pixhawk_mode("HOLD")
                finally:
                    self.bridge.suppress_disconnect_check(False)

        except Exception as e:
            self.log(f"❌ RTK monitoring error: {e}", "error")
        
        # Schedule next check in 0.5 seconds.
        # Use local variable to build/start the timer before assigning to self.rtk_monitor_timer.
        # This prevents AttributeError if _stop_rtk_monitoring() sets self.rtk_monitor_timer=None
        # between the object creation and the .daemon/.start() calls (race outside the lock).
        if self.rtk_monitoring_active and self.mission_state == MissionState.RUNNING:
            _t = threading.Timer(0.5, self._monitor_rtk_continuous)
            _t.daemon = True
            _t.start()
            self.rtk_monitor_timer = _t
    
    def set_obstacle_detection(self, enabled: bool) -> Dict[str, Any]:
        """Enable or disable obstacle detection pause logic."""
        self.obstacle_detection_enabled = enabled
        if enabled:
            self.log("Obstacle detection ENABLED")
            # Start monitor if mission is already running
            if self.obstacle_monitor and self.mission_state == MissionState.RUNNING:
                self.obstacle_monitor.start()
        else:
            self.log("Obstacle detection DISABLED")
            # Stop monitor if running
            if self.obstacle_monitor:
                self.obstacle_monitor.stop()
        return {'success': True, 'enabled': enabled}

    def _handle_obstacle(self, distance_mm: int, zone: str):
        """Handle obstacle detection callback from ultrasonic sensor."""
        if self.mission_state != MissionState.RUNNING:
            self.log(f"[OBSTACLE_CB] Ignored (state={self.mission_state.value}): {distance_mm}mm zone={zone}")
            return

        dist_cm = distance_mm / 10.0

        if zone == "warning":
            self.log(f"━━━ OBSTACLE WARNING ━━━")
            self.log(f"⚠ Object detected at {distance_mm}mm ({dist_cm:.0f}cm) — WARNING ZONE")
            self.log(f"  WP{self.current_waypoint_index + 1}/{len(self.waypoints)} | Mode: {self.mission_mode.value}")
            self.emit_status(
                f"Obstacle detected at {dist_cm:.0f}cm",
                "warning",
                extra_data={
                    "event_type": "obstacle_warning",
                    "obstacle_distance_mm": distance_mm,
                }
            )

        elif zone == "danger":
            self.log(f"━━━ OBSTACLE DANGER ━━━")
            self.log(f"🛑 Object at {distance_mm}mm ({dist_cm:.0f}cm) — DANGER ZONE — PAUSING MISSION")
            self.log(f"  WP{self.current_waypoint_index + 1}/{len(self.waypoints)} | Mode: {self.mission_mode.value}")
            self.emit_status(
                f"Obstacle too close ({dist_cm:.0f}cm) - Mission paused",
                "warning",
                extra_data={
                    "event_type": "obstacle_danger",
                    "obstacle_distance_mm": distance_mm,
                }
            )
            # Pause on a separate thread — callback runs on obstacle monitor thread,
            # and pause_mission() calls obstacle_monitor.stop() which would join this thread
            threading.Thread(target=self.pause_mission, daemon=True).start()

    def next_waypoint(self) -> Dict[str, Any]:
        """Proceed to next waypoint (manual mode)"""
        with self.lock:
            if self.mission_state != MissionState.RUNNING:
                return {'success': False, 'error': 'Mission not running'}
            
            if self.mission_mode == MissionMode.AUTO:
                return {'success': False, 'error': 'Mission in auto mode - cannot manually proceed'}
            
            self.proceed_to_next_waypoint()
            return {'success': True, 'message': 'Proceeding to next waypoint'}
    
    def skip_waypoint(self) -> Dict[str, Any]:
        """Skip current waypoint and proceed to next (works in both manual and auto mode)"""
        with self.lock:
            if self.mission_state != MissionState.RUNNING:
                return {'success': False, 'error': 'Mission not running'}

            current_wp = self.current_waypoint_index
            self.log(f"Skipping waypoint {current_wp}", "info")
            self.emit_status(f"Skipping waypoint {current_wp}", "warning")

        # Set HOLD before clear/push so ArduPilot accepts mission commands
        self.bridge.suppress_disconnect_check(True)
        try:
            self.set_pixhawk_mode("HOLD")
        finally:
            self.bridge.suppress_disconnect_check(False)

        self.proceed_to_next_waypoint()
        return {'success': True, 'message': f'Skipped waypoint {current_wp}'}
    
    def set_mode(self, mode: str) -> Dict[str, Any]:
        """Set mission mode (auto/manual/continuous/dash)"""
        with self.lock:
            try:
                # Block mode change while mission is RUNNING
                if self.mission_state == MissionState.RUNNING:
                    return {'success': False, 'error': 'Cannot change mode while mission is running - stop mission first'}
                
                old_mode = self.mission_mode
                
                # Use mode map for cleaner conversion
                mode_map = {
                    'auto': MissionMode.AUTO,
                    'manual': MissionMode.MANUAL,
                    'continuous': MissionMode.CONTINUOUS,
                    'dash': MissionMode.DASH
                }
                
                if mode.lower() not in mode_map:
                    return {'success': False, 'error': f'Invalid mode: {mode}. Valid modes: auto, manual, continuous, dash'}
                
                new_mode = mode_map[mode.lower()]
                self.mission_mode = new_mode
                persisted = self._persist_mission_mode(new_mode)
                
                # Log with SUCCESS level so it shows clearly in journalctl
                self.log(f'MISSION MODE CHANGED: {old_mode.value} → {new_mode.value}', 'success')
                self.emit_status(
                    f"Mission mode set to {new_mode.value}",
                    "success",
                    extra_data={
                        "event_type": "mission_mode_changed",
                        "persisted": persisted
                    }
                )
                if not persisted:
                    self.log("Mission mode changed in memory but failed to persist to config", "warning")
                
                return {
                    'success': True,
                    'message': f'Mode set to {new_mode.value}',
                    'mode': new_mode.value,
                    'persisted': persisted
                }
                
            except Exception as e:
                error_msg = f"Failed to set mode: {str(e)}"
                self.log(error_msg, "error")
                return {'success': False, 'error': error_msg}
    
    def execute_current_waypoint(self):
        """Execute the current waypoint - send one waypoint at a time"""
        if self.current_waypoint_index >= len(self.waypoints):
            self.complete_mission()
            return

        waypoint = self.waypoints[self.current_waypoint_index]

        try:
            self.log(f'───────────────────────────────────────────────────')
            self.log(f'📍 EXECUTING WAYPOINT {self.current_waypoint_index + 1}/{len(self.waypoints)}')
            self.log(f'Target: lat={waypoint["lat"]:.6f}, lng={waypoint["lng"]:.6f}, alt={waypoint.get("alt", 10.0)}m')

            # Suppress disconnect detection during blocking bridge operations.
            # Waypoint upload involves multiple sequential service calls through
            # rosbridge that can stall telemetry for 10+ seconds, triggering a
            # false disconnect → os._exit(1).
            self.bridge.suppress_disconnect_check(True)

            try:
                # Step 1: Set HOME position (only first time)
                if not self.home_set:
                    self.log(f'🏠 Setting HOME position (first time only)...')
                    if self.set_home_position():
                        self.home_set = True
                        self.log(f'✅ HOME position set successfully')
                    else:
                        self.log(f'⚠ Warning: Could not set HOME position', "warning")

                # Step 2: Upload waypoint (includes HOME position for ArduPilot compatibility)
                self.log(f'📤 Uploading waypoint {self.current_waypoint_index + 1}...')
                mavros_waypoint = self.create_single_waypoint(waypoint, seq=0)

                if self.upload_single_waypoint(mavros_waypoint):
                    self.log(f'✅ Waypoint ready for navigation')

                    # Step 3: ARM if not already armed (check before AUTO mode)
                    if not self.ensure_pixhawk_armed():
                        self.log("⚠ Warning: Could not arm Pixhawk, attempting AUTO mode anyway", "warning")
                    else:
                        self.log(f'✅ PIXHAWK ARMED')

                    # Step 4: Set AUTO mode
                    self.log(f'🔄 Setting AUTO mode...')
                    self.set_pixhawk_mode("AUTO")
                    self.log(f'✅ AUTO mode activated - rover should move to waypoint')
                else:
                    raise Exception("Failed to upload waypoint to Pixhawk")
            finally:
                # Always re-enable disconnect detection after blocking ops finish
                self.bridge.suppress_disconnect_check(False)

            # Step 5: Start monitoring for waypoint reached
            # Reset dedup guard — in point-by-point mode Pixhawk always sends seq=1 for each waypoint
            self.last_wp_seq_reached = 0
            self.waiting_for_waypoint_reach = True
            self.waypoint_upload_time = time.time()
            self.start_periodic_status_logging()

            self.emit_status(
                f"Executing waypoint {self.current_waypoint_index + 1}",
                "info",
                extra_data={
                    "event_type": "waypoint_executing",
                    "current_waypoint": self.current_waypoint_index + 1,
                    "total_waypoints": len(self.waypoints),
                    "waypoint": waypoint,
                    "mode": self.mission_mode.value
                }
            )

            # Set timeout for waypoint execution
            self.mission_timer = threading.Timer(self.mission_timeout, self.waypoint_timeout)
            self.mission_timer.start()

        except Exception as e:
            # Ensure disconnect check is re-enabled even on unexpected errors
            self.bridge.suppress_disconnect_check(False)
            error_msg = f"Failed to execute waypoint {self.current_waypoint_index + 1}: {str(e)}"
            self.log(error_msg, "error")
            self.mission_state = MissionState.ERROR
            self.emit_status(error_msg, "error", extra_data={"event_type": "waypoint_error"})
            raise

    def execute_all_waypoints(self):
        """Upload ALL waypoints to Pixhawk at once and set AUTO mode.
        Used for continuous and dash modes where the rover navigates autonomously."""
        if not self.waypoints:
            self.log("No waypoints to execute", "error")
            return

        if not self.current_position:
            error_msg = "No current position available for HOME waypoint"
            self.log(f"❌ {error_msg}", "error")
            self.mission_state = MissionState.ERROR
            self.emit_status(error_msg, "error", extra_data={"event_type": "mission_error"})
            return

        # Initialize multi-waypoint mode state
        self.multi_waypoint_mode = True
        self.first_mission_wp_reached = False
        self.continuous_servo_active = False
        self.last_wp_seq_reached = 0
        self.last_telemetry_position = None

        # Initialize dash mode specific state
        if self.mission_mode == MissionMode.DASH:
            self.dash_servo_on = False
            self.dash_last_toggle_position = None
            self.dash_cumulative_distance = 0.0
            self.dash_distance_since_toggle = 0.0
            self.dash_last_toggle_time = None

        self.log(f'═══════════════════════════════════════════════════')
        self.log(f'🎯 MULTI-WAYPOINT UPLOAD ({self.mission_mode.value} mode)')
        self.log(f'Uploading {len(self.waypoints)} waypoints to Pixhawk at once')
        self.log(f'═══════════════════════════════════════════════════')

        # Suppress disconnect detection during blocking bridge operations
        self.bridge.suppress_disconnect_check(True)

        try:
            # Build waypoint list: HOME (seq=0) + mission waypoints (seq=1..N)
            mavros_waypoints = []

            # HOME waypoint (seq=0) - uses current position
            home_waypoint = {
                'frame': 0,  # MAV_FRAME_GLOBAL (absolute altitude for HOME)
                'command': 16,  # MAV_CMD_NAV_WAYPOINT
                'is_current': True,
                'autocontinue': True,
                'param1': 0.0, 'param2': 0.0, 'param3': 0.0, 'param4': 0.0,
                'x_lat': float(self.current_position['lat']),
                'y_long': float(self.current_position['lng']),
                'z_alt': float(self.current_position.get('alt', 0.0))
            }
            mavros_waypoints.append(home_waypoint)

            # Mission waypoints (seq=1..N)
            for i, wp in enumerate(self.waypoints):
                mission_wp = {
                    'frame': 3,  # MAV_FRAME_GLOBAL_RELATIVE_ALT
                    'command': 16,  # MAV_CMD_NAV_WAYPOINT
                    'is_current': False,
                    'autocontinue': True,
                    'param1': 0.0,
                    'param2': float(self.waypoint_reached_threshold),
                    'param3': 0.0,
                    'param4': 0.0,
                    'x_lat': float(wp['lat']),
                    'y_long': float(wp['lng']),
                    'z_alt': float(wp.get('alt', 10.0))
                }
                mavros_waypoints.append(mission_wp)

            self.log(f"Built {len(mavros_waypoints)} waypoints (1 HOME + {len(self.waypoints)} mission)")

            # Step 1: Set HOME position (only first time)
            if not self.home_set:
                if self.set_home_position():
                    self.home_set = True

            # Step 2: Clear existing waypoints
            self.log(f"🗑️ Clearing existing waypoints...")
            try:
                clear_resp = self.bridge.clear_waypoints()
                if not clear_resp.get('success', False):
                    self.log("⚠ roslibpy clear failed, trying CLI...")
                    clear_resp = self.bridge.clear_waypoints_cli()
                if clear_resp.get('success', False):
                    self.log("✓ Cleared existing waypoints")
                else:
                    self.log(f"⚠ Clear waypoints returned: {clear_resp}", "warning")
            except Exception as clear_error:
                try:
                    self.log(f"⚠ roslibpy failed, trying CLI: {clear_error}")
                    self.bridge.clear_waypoints_cli()
                except Exception:
                    self.log("⚠ Failed to clear waypoints (non-fatal)", "warning")

            # Step 3: Upload all waypoints
            self.log(f"📤 Uploading {len(mavros_waypoints)} waypoints to Pixhawk...")
            try:
                response = self.bridge.push_waypoints(mavros_waypoints)
                if not response.get('success', False):
                    self.log("⚠ roslibpy push failed, trying CLI...")
                    response = self.bridge.push_waypoints_cli(mavros_waypoints)
            except Exception as push_error:
                self.log(f"⚠ roslibpy push failed, trying CLI: {push_error}")
                try:
                    response = self.bridge.push_waypoints_cli(mavros_waypoints)
                except Exception as cli_error:
                    self.log(f"❌ CLI push also failed: {cli_error}", "error")
                    self.mission_state = MissionState.ERROR
                    self.emit_status("Failed to upload waypoints", "error",
                                     extra_data={"event_type": "mission_error"})
                    return

            if not response.get('success', False):
                self.log(f"❌ Failed to upload waypoints: {response}", "error")
                self.mission_state = MissionState.ERROR
                self.emit_status("Failed to upload waypoints", "error",
                                 extra_data={"event_type": "mission_error"})
                return

            self.log(f"✅ Upload successful")

            # Step 4: Verify upload
            # self._verify_multi_waypoint_upload(len(mavros_waypoints))

            # Step 5: Set current waypoint to 1 (first mission waypoint, skip HOME)
            self.log("🎯 Setting current waypoint to 1 (first mission target)")
            try:
                set_resp = self.bridge.set_current_waypoint(1)
                if not set_resp.get('success', False):
                    self.log("⚠ roslibpy set_current failed, trying CLI...")
                    self.bridge.set_current_waypoint_cli(1)
            except Exception as e:
                try:
                    self.bridge.set_current_waypoint_cli(1)
                except Exception:
                    self.log(f"⚠ Failed to set current waypoint: {e}", "warning")

            # Step 6: Arm if not already armed
            if not self.ensure_pixhawk_armed():
                self.log("⚠ Could not arm Pixhawk, attempting AUTO mode anyway", "warning")

            # Step 7: Set AUTO mode
            self.log("🔄 Setting AUTO mode...")
            self.set_pixhawk_mode("AUTO")
            self.log(f"✅ AUTO mode set - rover will navigate all {len(self.waypoints)} waypoints")

        finally:
            # Always re-enable disconnect detection
            self.bridge.suppress_disconnect_check(False)

        # Step 8: Start monitoring
        self.waiting_for_waypoint_reach = True
        self.waypoint_upload_time = time.time()
        self.start_periodic_status_logging()

        self.emit_status(
            f"All {len(self.waypoints)} waypoints uploaded ({self.mission_mode.value} mode)",
            "success",
            extra_data={
                "event_type": "multi_waypoint_executing",
                "total_waypoints": len(self.waypoints),
                "mode": self.mission_mode.value
            }
        )

        # Set a generous overall mission timeout
        total_timeout = self.mission_timeout * len(self.waypoints)
        self.mission_timer = threading.Timer(total_timeout, self.waypoint_timeout)
        self.mission_timer.start()

    def _verify_multi_waypoint_upload(self, expected_count: int) -> bool:
        """Verify multi-waypoint upload to Pixhawk. Logs warnings but does not block."""
        max_retries = 3
        for retry in range(max_retries):
            delay = 1.0 + (retry * 0.5)  # 1.0s, 1.5s, 2.0s
            self.log(f"⏱ Verifying upload (attempt {retry + 1}/{max_retries}, waiting {delay}s)...")
            time.sleep(delay)
            try:
                verify_response = self.bridge.pull_waypoints()
                stored = verify_response.get('waypoints', [])
                self.log(f"📊 Verification: {len(stored)}/{expected_count} waypoints on Pixhawk")
                if len(stored) == expected_count:
                    self.log(f"✅ Multi-waypoint upload verified: {expected_count} waypoints")
                    return True
            except Exception as e:
                self.log(f"Verification attempt {retry + 1} error: {e}", "warning")
        self.log(f"⚠ Verification incomplete after {max_retries} attempts, proceeding anyway", "warning")
        return True  # Don't block mission - proceed anyway

    def handle_pixhawk_waypoint_reached(self, wp_seq: int):
        """
        Handle waypoint reached message from Pixhawk via /mavros/mission/reached topic.
        This is the PRIMARY method for waypoint detection (more robust than distance calculation).

        Args:
            wp_seq: Waypoint sequence number from Pixhawk (1-based indexing for mission waypoints)
        """
        try:
            # Dedup guard: both rclpy and roslibpy may fire for same wp_seq.
            # Use lock to make the check-and-set atomic (prevents race condition
            # where both threads pass the check before either sets the value).
            with self.lock:
                if wp_seq == self.last_wp_seq_reached:
                    return
                self.last_wp_seq_reached = wp_seq

            # Mode dispatch: multi-waypoint vs point-by-point
            if self.multi_waypoint_mode:
                self._handle_multi_wp_reached(wp_seq)
                return

            # Traditional point-by-point mode (existing logic)
            # FIX: In point-by-point mode, we upload only 1 mission waypoint at a time to Pixhawk.
            # Since there's only 1 waypoint in the mission, Pixhawk ALWAYS sends wp_seq=1
            # (seq=0 is HOME, seq=1 is the single mission waypoint).
            # Therefore, we accept wp_seq=1 unconditionally in point-by-point mode.
            
            self.log(f'🎯 Pixhawk reports waypoint reached: seq={wp_seq} (point-by-point mode)')

            # In point-by-point mode, wp_seq=1 is always correct (only 1 waypoint uploaded)
            # No sequence validation needed - just accept wp_seq=1
            if wp_seq != 1:
                self.log(
                    f'⚠️ WARNING: Received wp_seq={wp_seq} but expected wp_seq=1 in point-by-point mode. '
                    f'Current waypoint index={self.current_waypoint_index}',
                    'warning'
                )
                return

            # Mark waypoint as reached and proceed with servo operations
            self.waypoint_reached()

        except Exception as e:
            self.log(f"Error handling waypoint reached: {e}", "error")

    def _handle_multi_wp_reached(self, wp_seq: int):
        """Handle waypoint reached in multi-waypoint modes (continuous/dash)"""
        try:
            # Determine if this is first or last waypoint
            total_wps = len(self.waypoints)
            is_first = (wp_seq == 1)  # First mission waypoint
            is_last = (wp_seq == total_wps)  # Last mission waypoint
            
            self.log(f'🎯 Multi-WP reached: seq={wp_seq}, first={is_first}, last={is_last}')

            # Set index to just-reached WP before emitting so current_waypoint is correct
            self.current_waypoint_index = wp_seq - 1  # 0-based, just-reached

            # Track this waypoint as reached for resume re-emission
            if wp_seq not in self.reached_waypoints:
                self.reached_waypoints.append(wp_seq)

            # Emit waypoint reached event — include waypoint_id so frontend can mark it
            self.emit_status(
                f"Waypoint {wp_seq} reached",
                "info",
                extra_data={
                    "event_type": "waypoint_reached",
                    "waypoint_id": wp_seq,   # frontend looks for waypoint_id
                    "wp_seq": wp_seq,
                    "is_first": is_first,
                    "is_last": is_last,
                    "mode": self.mission_mode.value
                }
            )

            # Advance index to next target so distance monitor tracks the right WP.
            # If last, clear waiting flag so distance monitor stops.
            if is_last:
                self.waiting_for_waypoint_reach = False
                # current_waypoint_index stays at last WP (already set above)
            else:
                self.current_waypoint_index = wp_seq  # Next WP index (0-based)

            # Dispatch to mode-specific handlers
            if self.mission_mode == MissionMode.CONTINUOUS:
                self._handle_continuous_wp_reached(wp_seq, is_first, is_last)
            elif self.mission_mode == MissionMode.DASH:
                self._handle_dash_wp_reached(wp_seq, is_first, is_last)

            # Check if this was the last waypoint
            if is_last:
                self.complete_mission()
                
        except Exception as e:
            self.log(f"Error handling multi-waypoint reached: {e}", "error")

    def _handle_continuous_wp_reached(self, wp_seq: int, is_first: bool, is_last: bool):
        """Handle waypoint reached in continuous mode"""
        try:
            if is_first:
                # First waypoint: turn servo ON
                self.log(f"🟢 CONTINUOUS MODE: Servo ON at first waypoint (#{wp_seq})")
                self.bridge.suppress_disconnect_check(True)
                try:
                    self.bridge.set_servo(self.servo_channel, self.servo_pwm_on)
                finally:
                    self.bridge.suppress_disconnect_check(False)
                self.continuous_servo_active = True
                self.first_mission_wp_reached = True

                self.emit_status(
                    "Servo ON - continuous spraying started",
                    "success",
                    extra_data={
                        "event_type": "servo_on",
                        "mode": "continuous",
                        "waypoint_id": wp_seq
                    }
                )

            elif is_last:
                # Last waypoint: turn servo OFF
                self.log(f"🔴 CONTINUOUS MODE: Servo OFF at last waypoint (#{wp_seq})")
                self.bridge.suppress_disconnect_check(True)
                try:
                    self.bridge.set_servo(self.servo_channel, self.servo_pwm_off)
                finally:
                    self.bridge.suppress_disconnect_check(False)
                self.continuous_servo_active = False
                
                self.emit_status(
                    "Servo OFF - continuous spraying completed",
                    "success",
                    extra_data={
                        "event_type": "servo_off",
                        "mode": "continuous",
                        "waypoint_id": wp_seq
                    }
                )
            else:
                # Intermediate waypoint: log only, rover keeps moving
                self.log(f"➡️ CONTINUOUS MODE: Passed waypoint #{wp_seq} (servo stays ON)")
                
        except Exception as e:
            self.log(f"Error in continuous waypoint handling: {e}", "error")

    def _handle_dash_wp_reached(self, wp_seq: int, is_first: bool, is_last: bool):
        """Handle waypoint reached in dash mode"""
        try:
            if is_first:
                # First waypoint: turn servo ON and initialize distance tracking
                self.log(f"🟢 DASH MODE: Servo ON at first waypoint (#{wp_seq})")
                self.bridge.suppress_disconnect_check(True)
                try:
                    self.bridge.set_servo(self.servo_channel, self.servo_pwm_on)
                finally:
                    self.bridge.suppress_disconnect_check(False)
                self.dash_servo_on = True
                self.first_mission_wp_reached = True

                # Initialize time-based tracking
                self.dash_last_toggle_time = time.time()
                
                # # Initialize distance tracking (COMMENTED - using time-based instead)
                # if self.current_position:
                #     self.dash_last_toggle_position = self.current_position.copy()
                #     self.last_telemetry_position = self.current_position.copy()

                self.emit_status(
                    "Dash mode started - servo ON",
                    "success",
                    extra_data={
                        "event_type": "dash_started",
                        "mode": "dash"
                    }
                )

            elif is_last:
                # Last waypoint: force servo OFF
                self.log(f"🔴 DASH MODE: Servo OFF at last waypoint (#{wp_seq})")
                self.bridge.suppress_disconnect_check(True)
                try:
                    self.bridge.set_servo(self.servo_channel, self.servo_pwm_off)
                finally:
                    self.bridge.suppress_disconnect_check(False)
                self.dash_servo_on = False

                self.emit_status(
                    "Dash mode completed",
                    "success",
                    extra_data={
                        "event_type": "dash_completed",
                        "cumulative_distance": self.dash_cumulative_distance
                    }
                )
            else:
                # Intermediate waypoint: no action (distance tracking handles servo toggling)
                self.log(f"➡️ DASH MODE: Passed waypoint #{wp_seq} (distance-based control active)")

        except Exception as e:
            self.log(f"Error in dash waypoint handling: {e}", "error")

    def _update_dash_distance(self):
        """Update dash mode distance tracking and toggle servo if thresholds reached.
        Called on each telemetry update while dash mode is active."""
        try:
            if not self.last_telemetry_position or not self.current_position:
                return

            current_lat = self.current_position.get('lat', 0.0)
            current_lng = self.current_position.get('lng', 0.0)

            if current_lat == 0.0 or current_lng == 0.0:
                return

            # Initialize last position on first call
            if self.last_telemetry_position is None:
                self.last_telemetry_position = self.current_position.copy()
                return

            # Calculate incremental distance from last telemetry tick (Karney)
            last_lat = self.last_telemetry_position.get('lat', 0.0)
            last_lng = self.last_telemetry_position.get('lng', 0.0)
            incremental = self.calculate_distance(last_lat, last_lng, current_lat, current_lng)

            # Update last position for next iteration
            self.last_telemetry_position = self.current_position.copy()

            # Skip bad readings or stationary
            if incremental == float('inf') or incremental < 0.01:
                return

            # Update cumulative distance
            self.dash_cumulative_distance += incremental

            # Calculate distance from last toggle using absolute position (prevents drift)
            if self.dash_last_toggle_position:
                toggle_lat = self.dash_last_toggle_position.get('lat', 0.0)
                toggle_lng = self.dash_last_toggle_position.get('lng', 0.0)
                self.dash_distance_since_toggle = self.calculate_distance(
                    toggle_lat, toggle_lng, current_lat, current_lng
                )
            else:
                self.dash_distance_since_toggle += incremental

            # Determine threshold based on current servo state
            # If servo ON → threshold = servo_on_distance (how far to stay ON)
            # If servo OFF → threshold = servo_off_distance (how far to stay OFF)
            threshold = self.dash_servo_on_distance if self.dash_servo_on else self.dash_servo_off_distance

            # Toggle servo when threshold reached
            if self.dash_distance_since_toggle >= threshold:
                self.dash_servo_on = not self.dash_servo_on
                new_pwm = self.servo_pwm_on if self.dash_servo_on else self.servo_pwm_off
                state_str = "ON" if self.dash_servo_on else "OFF"

                self.log(f"🔄 DASH: Servo {state_str} at {self.dash_distance_since_toggle:.2f}m "
                         f"(threshold={threshold}m, cumulative={self.dash_cumulative_distance:.1f}m)")

                self.bridge.suppress_disconnect_check(True)
                try:
                    self.bridge.set_servo(self.servo_channel, new_pwm)
                finally:
                    self.bridge.suppress_disconnect_check(False)

                # Reset toggle tracking
                self.dash_last_toggle_position = self.current_position.copy()
                self.dash_distance_since_toggle = 0.0

                self.emit_status(
                    f"Dash: Servo {state_str}",
                    "info",
                    extra_data={
                        "event_type": "dash_toggle",
                        "servo_state": state_str.lower(),
                        "cumulative_distance": round(self.dash_cumulative_distance, 1),
                        "distance_since_toggle": 0.0,
                        "threshold": threshold
                    }
                )

        except Exception as e:
            self.log(f"Error updating dash distance: {e}", "error")
    
    def _update_dash_time(self):
        """Update dash mode time-based tracking and toggle servo if thresholds reached.
        Called on each telemetry update while dash mode is active."""
        try:
            current_time = time.time()
            
            # Initialize on first call
            if self.dash_last_toggle_time is None:
                self.dash_last_toggle_time = current_time
                return
            
            # Calculate time since last toggle
            time_since_toggle = current_time - self.dash_last_toggle_time
            
            # Determine threshold based on current servo state
            threshold = self.dash_servo_on_time if self.dash_servo_on else self.dash_servo_off_time
            
            # Toggle servo when threshold reached
            if time_since_toggle >= threshold:
                self.dash_servo_on = not self.dash_servo_on
                new_pwm = self.servo_pwm_on if self.dash_servo_on else self.servo_pwm_off
                state_str = "ON" if self.dash_servo_on else "OFF"

                # Reset toggle tracking immediately (before async call)
                # to prevent re-triggering on the next telemetry update.
                self.dash_last_toggle_time = current_time

                self.log(f"🔄 DASH: Servo {state_str} at {time_since_toggle:.2f}s "
                         f"(threshold={threshold}s)")

                # IMPORTANT: Offload to daemon thread — set_servo() calls
                # _call_service_rclpy (3s) + CLI fallback (10s) which would
                # block the roslibpy callback thread and freeze all telemetry.
                def _dash_servo_toggle(bridge, channel, pwm, s_str, tst, thresh):
                    bridge.suppress_disconnect_check(True)
                    try:
                        bridge.set_servo(channel, pwm)
                    finally:
                        bridge.suppress_disconnect_check(False)
                    self.emit_status(
                        f"Dash: Servo {s_str}",
                        "info",
                        extra_data={
                            "event_type": "dash_toggle",
                            "servo_state": s_str.lower(),
                            "time_since_toggle": round(tst, 2),
                            "threshold": thresh
                        }
                    )
                threading.Thread(
                    target=_dash_servo_toggle,
                    args=(self.bridge, self.servo_channel, new_pwm,
                          state_str, time_since_toggle, threshold),
                    daemon=True
                ).start()
        
        except Exception as e:
            self.log(f"Error updating dash time: {e}", "error")

    def check_waypoint_reached_distance_fallback(self):
        """
        FALLBACK: Simple distance-based waypoint detection (backup method).
        This is only used if Pixhawk topic messages are not received.
        Simpler than original - just monitors distance for logging and emergency backup.
        """
        if (not self.waiting_for_waypoint_reach or
            not self.current_position or
            self.current_waypoint_index >= len(self.waypoints)):
            return

        waypoint = self.waypoints[self.current_waypoint_index]
        distance = self.calculate_distance(
            self.current_position['lat'], self.current_position['lng'],
            waypoint['lat'], waypoint['lng']
        )

        # If distance calculation failed, just log it (not critical since topic is primary)
        if distance == float('inf'):
            return

        # Simple logging every 5 seconds for monitoring
        if not hasattr(self, '_last_distance_log_time'):
            self._last_distance_log_time = 0

        current_time = time.time()
        if current_time - self._last_distance_log_time > 5:
            self.log(f'📊 Distance monitor: WP{self.current_waypoint_index + 1} is {distance:.2f}m away (waiting for Pixhawk topic)')
            self._last_distance_log_time = current_time

        # Emergency fallback: If within threshold for 10+ seconds and no topic message
        if distance <= self.waypoint_reached_threshold:
            if not hasattr(self, '_fallback_threshold_entry_time'):
                self._fallback_threshold_entry_time = current_time
                self.log(f'⚠️ FALLBACK: Entered threshold zone ({distance:.2f}m) - waiting {self.fallback_zone_timeout_seconds}s for Pixhawk topic before fallback trigger')
            else:
                time_in_zone = current_time - self._fallback_threshold_entry_time
                if time_in_zone >= self.fallback_zone_timeout_seconds:
                    # Topic didn't fire for configured timeout - use fallback
                    self.log(f'🚨 FALLBACK TRIGGERED: No Pixhawk topic after {self.fallback_zone_timeout_seconds}s in zone - using distance detection', 'warning')
                    self.log(f'✓ Waypoint {self.current_waypoint_index + 1} reached via FALLBACK distance check ({distance:.2f}m)')
                    del self._fallback_threshold_entry_time
                    if self.multi_waypoint_mode:
                        self._handle_multi_wp_reached(self.current_waypoint_index + 1)
                    else:
                        self.waypoint_reached()
        else:
            # Outside threshold - reset fallback timer
            if hasattr(self, '_fallback_threshold_entry_time'):
                del self._fallback_threshold_entry_time
    
    def waypoint_reached(self):
        """Handle waypoint reached (called by either Pixhawk topic or distance fallback)"""
        # Phase 1: State updates under lock
        with self.lock:
            if not self.waiting_for_waypoint_reach or self.mission_state != MissionState.RUNNING:
                return

            self.waiting_for_waypoint_reach = False
            self.stop_periodic_status_logging()

            # Cancel mission timeout
            if self.mission_timer:
                self.mission_timer.cancel()
                self.mission_timer = None

            # Capture current position at waypoint arrival for accuracy calculation
            self.failsafe_position_at_arrival = self.current_position.copy() if self.current_position else None

        # Phase 2: Blocking bridge call OUTSIDE the lock
        self.log(f'🛑 Setting HOLD mode')
        self.bridge.suppress_disconnect_check(True)
        try:
            self.set_pixhawk_mode("HOLD")
        finally:
            self.bridge.suppress_disconnect_check(False)

        # Phase 3: Post-HOLD processing under lock
        with self.lock:
            # Re-check state — another thread may have stopped the mission while we were outside the lock
            if self.mission_state != MissionState.RUNNING:
                return

            # Record waypoint completion
            current_time = datetime.now().isoformat() + "Z"
            waypoint = self.waypoints[self.current_waypoint_index]

            self.log(f'✅ WAYPOINT {self.current_waypoint_index + 1} REACHED')
            self.log(f'Position: lat={self.current_position["lat"]:.6f}, lng={self.current_position["lng"]:.6f}' if self.current_position else 'Position: unknown')

            # Track this waypoint as reached for resume re-emission
            wp_id = self.current_waypoint_index + 1
            if wp_id not in self.reached_waypoints:
                self.reached_waypoints.append(wp_id)

            # GPS Failsafe check (only if mission is running and failsafe enabled)
            failsafe_triggered = False
            failsafe_reason = None

            if self.mission_state == MissionState.RUNNING and self.failsafe_mode != "disable" and self.failsafe_monitor:
                # We'll check failsafe conditions, but store result for later use in hold_period_complete
                # For now, just log the conditions - the monitor state is managed by servo sequence
                self.log(f"GPS Failsafe check will run after servo decision", "debug")

            # Calculate accuracy error at waypoint arrival
            accuracy_error_mm = None
            if calculate_accuracy_error_mm is not None and waypoint and self.current_position:
                accuracy_error_mm = calculate_accuracy_error_mm(
                    waypoint['lat'], waypoint['lng'],
                    self.current_position['lat'], self.current_position['lng']
                )
                self.log(f"GPS Accuracy at arrival: {accuracy_error_mm:.1f}mm error from target", "info")
            self.last_accuracy_error_mm = accuracy_error_mm  # Store for waypoint_marked event

            # Emit waypoint_reached event for frontend table
            self.emit_status(
                f"Waypoint {self.current_waypoint_index + 1} reached",
                "success",
                extra_data={
                    "event_type": "waypoint_reached",
                    "waypoint_id": self.current_waypoint_index + 1,
                    "current_waypoint": self.current_waypoint_index + 1,
                    "timestamp": current_time,
                    "position": self.current_position.copy() if self.current_position else None,
                    "waypoint_target": waypoint,
                    "accuracy_error_mm": accuracy_error_mm,
                    "message": f"Waypoint {self.current_waypoint_index + 1} reached successfully"
                }
            )

            # Start hold period
            self.log(f'⏱ Starting {self.hold_duration}s hold period at waypoint {self.current_waypoint_index + 1}')
            self.hold_timer = threading.Timer(self.hold_duration, self.hold_period_complete)
            self.hold_timer.start()

    def execute_servo_sequence(self, override_enabled=False):
        """
        Execute servo ON/OFF sequence after hold period.
        
        Args:
            override_enabled: If True, ignores global servo_enabled check for per-waypoint marking
        
        Sequence: Before delay → Servo ON → Spray duration → Servo OFF → After delay
        
        Checks GPS failsafe before spraying:
        - If accuracy error > 60mm: suppress spray (relax) or was already paused (strict)
        """
        try:
            if not self.servo_enabled and not override_enabled:
                self.log('⚠ Servo control disabled - skipping servo sequence')
                return

            # GPS Failsafe: Check accuracy error before spraying
            waypoint = self.waypoints[self.current_waypoint_index] if self.current_waypoint_index < len(self.waypoints) else None
            
            if (self.failsafe_mode != "disable" and self.failsafe_monitor and 
                waypoint and self.failsafe_position_at_arrival):
                
                if calculate_accuracy_error_mm is not None:
                    # Calculate accuracy error in mm
                    accuracy_error_mm = calculate_accuracy_error_mm(
                        waypoint['lat'], waypoint['lng'],
                        self.failsafe_position_at_arrival['lat'], self.failsafe_position_at_arrival['lng']
                    )
                    
                    self.log(f"GPS Accuracy at waypoint: {accuracy_error_mm:.1f}mm error from target", "info")
                    
                    # Suppress servo if accuracy exceeds threshold
                    if accuracy_error_mm > self.accuracy_threshold_mm:
                        self.log(f"❌ Spray suppressed: accuracy error {accuracy_error_mm:.1f}mm > {self.accuracy_threshold_mm}mm threshold", "warning")
                        # Emit both events for backward compatibility
                        failsafe_time = datetime.now().isoformat() + "Z"

                        # Keep existing servo_suppressed event for backward compatibility
                        self.emit_status(
                            f"Spray suppressed: accuracy {accuracy_error_mm:.1f}mm > {self.accuracy_threshold_mm}mm",
                            "warning",
                            extra_data={
                                'event_type': 'servo_suppressed',
                                'reason': 'accuracy_error',
                                'accuracy_error_mm': accuracy_error_mm,
                                'threshold_mm': self.accuracy_threshold_mm
                            }
                        )

                        # Add new waypoint_skipped event for frontend state management
                        self.emit_status(
                            f"Waypoint {self.current_waypoint_index + 1} skipped: GPS accuracy {accuracy_error_mm:.1f}mm > {self.accuracy_threshold_mm}mm",
                            "warning",
                            extra_data={
                                "event_type": "waypoint_skipped",
                                "waypoint_id": self.current_waypoint_index + 1,
                                "current_waypoint": self.current_waypoint_index + 1,
                                "timestamp": failsafe_time,
                                "marking_status": "skipped_gps_failsafe",
                                "accuracy_error_mm": accuracy_error_mm,
                                "threshold_mm": self.accuracy_threshold_mm,
                                "message": f"GPS accuracy insufficient for waypoint {self.current_waypoint_index + 1}"
                            }
                        )
                        return  # Skip servo sequence

            self.log(f'═══════════════════════════════════════════════════')
            self.log(f'🎯 STARTING SERVO SEQUENCE')
            self.log(f'Servo Channel: {self.servo_channel}')
            self.log(f'═══════════════════════════════════════════════════')

            # Suppress disconnect detection during servo commands (blocking bridge calls)
            self.bridge.suppress_disconnect_check(True)
            try:
                # Step 1: Wait before delay (delay BEFORE turning servo ON)
                if self.servo_delay_before > 0:
                    self.log(f'⏱ Waiting {self.servo_delay_before}s (pre-spray delay)...')
                    time.sleep(self.servo_delay_before)

                # Step 2: Turn servo ON
                self.log(f'📡 Setting servo {self.servo_channel} to {self.servo_pwm_on}µs (ON)')
                response_on = self.bridge.set_servo(self.servo_channel, self.servo_pwm_on)

                if response_on.get('success'):
                    self.log(f'✅ Servo ON: {self.servo_pwm_on}µs')
                else:
                    self.log(f'⚠ Servo ON command sent (response: {response_on})', 'warning')

                # Step 3: Wait spray duration (time between ON and OFF)
                self.log(f'⏱ Waiting {self.servo_spray_duration}s (spray duration)...')
                time.sleep(self.servo_spray_duration)

                # Step 4: Turn servo OFF
                self.log(f'📡 Setting servo {self.servo_channel} to {self.servo_pwm_off}µs (OFF)')
                response_off = self.bridge.set_servo(self.servo_channel, self.servo_pwm_off)

                if response_off.get('success'):
                    self.log(f'✅ Servo OFF: {self.servo_pwm_off}µs')
                else:
                    self.log(f'⚠ Servo OFF command sent (response: {response_off})', 'warning')

                # Step 5: Wait delay after spray (before continuing to next waypoint)
                self.log(f'⏱ Waiting {self.servo_delay_after}s (post-spray delay)...')
                time.sleep(self.servo_delay_after)
            finally:
                self.bridge.suppress_disconnect_check(False)

            self.log(f'✅ SERVO SEQUENCE COMPLETE')
            self.log(f'═══════════════════════════════════════════════════')
            
            # Emit waypoint_marked event after successful servo sequence
            mark_time = datetime.now().isoformat() + "Z"
            self.emit_status(
                f"Waypoint marked: {self.current_waypoint_index + 1}",
                "success",
                extra_data={
                    "event_type": "waypoint_marked",
                    "waypoint_id": self.current_waypoint_index + 1,
                    "current_waypoint": self.current_waypoint_index + 1,
                    "timestamp": mark_time,
                    "marking_status": "completed",
                    "spray_duration": self.servo_spray_duration,
                    "accuracy_error_mm": getattr(self, 'last_accuracy_error_mm', None),
                    "message": f"Waypoint {self.current_waypoint_index + 1} marked successfully"
                }
            )
            self.log(f'✓ Waypoint {self.current_waypoint_index + 1} marked event emitted')

        except Exception as e:
            # Don't fail mission if servo fails - just log and continue
            self.log(f'❌ Servo sequence error: {e}', 'error')
            self.log(f'⚠ Continuing mission despite servo failure', 'warning')

    def hold_period_complete(self):
        """Called when hold period is complete"""
        with self.lock:
            if self.mission_state != MissionState.RUNNING:
                return

            # Get current waypoint marking preference (INSIDE LOCK)
            waypoint = self.waypoints[self.current_waypoint_index]
            should_mark = waypoint.get('mark', self.servo_enabled)
            
            self.log(f'✓ Hold period complete for waypoint {self.current_waypoint_index + 1}')
            self.log(f'   Marking decision: {should_mark} (per-waypoint or fallback to global)')

            # Emit waypoint_hold_complete event (BEFORE servo decision)
            reach_time = datetime.now().isoformat() + "Z"
            self.emit_status(
                f"Waypoint {self.current_waypoint_index + 1} hold complete - marking: {'YES' if should_mark else 'NO'}",
                "info",
                extra_data={
                    "event_type": "waypoint_hold_complete",
                    "waypoint_id": self.current_waypoint_index + 1,
                    "current_waypoint": self.current_waypoint_index + 1,
                    "timestamp": reach_time,
                    "should_mark": should_mark,
                    "message": f"Waypoint {self.current_waypoint_index + 1} hold complete"
                }
            )

        # Execute servo sequence OUTSIDE the lock ONLY if should_mark is True
        if should_mark:
            self.execute_servo_sequence(override_enabled=True)
        else:
            self.log(f'⏭ Skipping servo - waypoint {self.current_waypoint_index + 1} not marked')
            # Emit waypoint_skipped event
            skip_time = datetime.now().isoformat() + "Z"
            self.emit_status(
                f"Waypoint {self.current_waypoint_index + 1} skipped (no marking)",
                "info",
                extra_data={
                    "event_type": "waypoint_skipped",
                    "waypoint_id": self.current_waypoint_index + 1,
                    "current_waypoint": self.current_waypoint_index + 1,
                    "timestamp": skip_time,
                    "marking_status": "skipped_user_preference",
                    "accuracy_error_mm": getattr(self, 'last_accuracy_error_mm', None),
                    "message": f"Waypoint {self.current_waypoint_index + 1} - no marking requested"
                }
            )

        # Re-acquire lock for final waypoint progression logic
        with self.lock:
            if self.mission_state != MissionState.RUNNING:
                return

            # Check mission mode
            if self.mission_mode == MissionMode.AUTO:
                self.proceed_to_next_waypoint()
            else:
                # Manual mode — if this was the last waypoint, complete immediately
                if self.current_waypoint_index >= len(self.waypoints) - 1:
                    self.waiting_for_waypoint_reach = False
                    self.complete_mission()
                else:
                    # More waypoints remain — wait for NEXT command
                    self.emit_status(
                        f"Waypoint {self.current_waypoint_index + 1} completed - waiting for manual next",
                        "info",
                        extra_data={
                            "event_type": "waypoint_completed_manual",
                            "waiting_for_manual": True,
                            "current_waypoint": self.current_waypoint_index + 1,
                            "next_waypoint": self.current_waypoint_index + 2,
                        }
                    )
    
    def proceed_to_next_waypoint(self):
        """
        Proceed to the next waypoint.
        
        Note: RTK fix is monitored continuously in STRICT mode by _monitor_rtk_continuous().
        Accuracy is checked here at waypoint arrival (before servo command).
        """
        # REFACTOR: No longer need delay or debounce reset - Pixhawk handles waypoint transitions
        self.waiting_for_waypoint_reach = False

        # Proceed to next waypoint (RTK is monitored continuously in strict mode)
        self.current_waypoint_index += 1

        if self.current_waypoint_index >= len(self.waypoints):
            self.complete_mission()
        else:
            self.log(f'➡ Proceeding to next waypoint ({self.current_waypoint_index + 1}/{len(self.waypoints)})')
            self.execute_current_waypoint()
    
    def complete_mission(self):
        """Complete the mission with proper state cleanup"""
        # PHASE 3 FIX: Prepare data BEFORE acquiring lock to minimize lock time
        mission_duration = time.time() - (self.mission_start_time or time.time()) if self.mission_start_time else 0
        waypoints_completed = len(self.waypoints)
        completion_time = datetime.now().isoformat()

        with self.lock:
            # Stop RTK monitoring
            self._stop_rtk_monitoring()

            # Stop obstacle detection
            if self.obstacle_monitor:
                self.obstacle_monitor.stop()

            self.mission_state = MissionState.COMPLETED
            self.cancel_timers()
            self.waiting_for_waypoint_reach = False

            # PHASE 3 FIX: Stop periodic status logging thread
            self.stop_periodic_status_logging()

            # PHASE 3 FIX: Complete state cleanup for restart capability
            self.current_waypoint_index = 0
            self.reached_waypoints = []
            self.mission_start_time = None
            self.home_set = False
            self.waypoint_upload_time = None

            # Reset multi-waypoint mode state
            self.multi_waypoint_mode = False
            self.first_mission_wp_reached = False
            self.continuous_servo_active = False
            self.last_telemetry_position = None
            self.last_wp_seq_reached = 0

            # Reset dash mode specific state
            self.dash_servo_on = False
            self.dash_last_toggle_position = None
            self.dash_cumulative_distance = 0.0
            self.dash_distance_since_toggle = 0.0
            self.dash_last_toggle_time = None

            # REFACTOR: Clean up fallback tracking (no longer using Phase 1 variables)
            if hasattr(self, '_fallback_threshold_entry_time'):
                del self._fallback_threshold_entry_time
            if hasattr(self, '_last_distance_log_time'):
                del self._last_distance_log_time

            self.log(f'═══════════════════════════════════════════════════')
            self.log(f'🎉 MISSION COMPLETED SUCCESSFULLY')
            self.log(f'Duration: {mission_duration:.1f} seconds ({mission_duration/60:.1f} minutes)')
            self.log(f'Waypoints completed: {waypoints_completed}')
            self.log(f'═══════════════════════════════════════════════════')

        # PHASE 3 FIX: Emit status OUTSIDE of lock to prevent deadlock
        try:
            self.emit_status(
                "Mission completed successfully",
                "success",
                extra_data={
                    "event_type": "mission_completed",
                    "mission_duration": mission_duration,
                    "waypoints_completed": waypoints_completed,
                    "completion_time": completion_time
                }
            )
        except Exception as e:
            self.log(f"Error emitting completion status: {e}", "error")

        # PHASE 3 FIX: Set HOLD mode OUTSIDE of lock to prevent deadlock
        self.bridge.suppress_disconnect_check(True)
        try:
            self.log(f'🛑 Setting final HOLD mode')
            self.set_pixhawk_mode("HOLD")
        except Exception as e:
            self.log(f"Failed to set HOLD mode on completion: {e}", "warning")
        finally:
            self.bridge.suppress_disconnect_check(False)

        # PHASE 3 FIX: Auto-transition to READY state for restart capability
        with self.lock:
            self.log(f'📝 Transitioning state: COMPLETED → READY (mission can be restarted)')
            self.mission_state = MissionState.READY
    
    def waypoint_timeout(self):
        """Handle waypoint execution timeout"""
        need_hold = False
        wp_index = 0
        error_msg = ""
        with self.lock:
            if self.mission_state == MissionState.RUNNING and self.waiting_for_waypoint_reach:
                wp_index = self.current_waypoint_index
                error_msg = f"Waypoint {wp_index + 1} execution timeout"
                self.log(error_msg, "error")
                self.mission_state = MissionState.ERROR
                self.waiting_for_waypoint_reach = False
                need_hold = True

        # Blocking bridge call OUTSIDE the lock
        if need_hold:
            self.bridge.suppress_disconnect_check(True)
            try:
                self.set_pixhawk_mode("HOLD")
            finally:
                self.bridge.suppress_disconnect_check(False)

            # Emit a failed marking event for the waypoint
            fail_time = datetime.now().isoformat() + "Z"
            self.emit_status(
                error_msg,
                "error",
                extra_data={
                    "event_type": "waypoint_failed",
                    "waypoint_id": wp_index + 1,
                    "current_waypoint": wp_index + 1,
                    "timestamp": fail_time,
                    "failure_reason": "timeout",
                    "message": error_msg
                }
            )
    
    def set_home_position(self) -> bool:
        """Set HOME position using current rover position (called only once at mission start)"""
        try:
            if not self.current_position:
                self.log("⚠ No current position available", "warning")
                self.log("✓ HOME will be auto-set by ArduPilot on ARM")
                return True

            home_lat = self.current_position['lat']
            home_lng = self.current_position['lng']
            home_alt = self.current_position.get('alt', 0.0)

            self.log(f"🏠 HOME will be: lat={home_lat:.6f}, lng={home_lng:.6f}, alt={home_alt:.1f}m")
            self.log(f"✓ ArduPilot will auto-set HOME on ARM at current position")

            # ArduPilot automatically sets HOME position when vehicle is armed
            # No explicit command needed - this is the standard behavior
            return True

        except Exception as e:
            self.log(f"⚠ Error checking HOME position: {e}", "warning")
            # Don't fail - ArduPilot will auto-set HOME on arm
            return True

    def create_single_waypoint(self, waypoint: Dict[str, Any], seq: int = 0) -> Dict[str, Any]:
        """Create a single MAVROS waypoint"""
        return {
            'frame': 3,  # MAV_FRAME_GLOBAL_RELATIVE_ALT (relative to HOME)
            'command': 16,  # MAV_CMD_NAV_WAYPOINT
            'is_current': True,  # This waypoint is the current target
            'autocontinue': True,
            'param1': 0,  # Hold time
            'param2': float(self.waypoint_reached_threshold),  # Accept radius
            'param3': 0,  # Pass through radius
            'param4': 0,  # Yaw (0 = maintain current heading)
            'x_lat': float(waypoint['lat']),
            'y_long': float(waypoint['lng']),
            'z_alt': float(waypoint.get('alt', 10.0))
        }
    
    def upload_single_waypoint(self, waypoint: Dict[str, Any]) -> bool:
        """Upload waypoint with HOME position - ArduPilot requires HOME + mission waypoint"""
        try:
            # CRITICAL: ArduPilot requires HOME waypoint (seq=0) + mission waypoint (seq=1)
            # Cannot upload single waypoint alone - AUTO mode will reject it

            if not self.current_position:
                self.log("❌ No current position available for HOME", "error")
                return False

            # Create HOME waypoint (seq=0) - REQUIRED by ArduPilot
            home_waypoint = {
                'frame': 0,  # MAV_FRAME_GLOBAL (absolute altitude)
                'command': 16,  # MAV_CMD_NAV_WAYPOINT
                'is_current': True,  # HOME is initially current
                'autocontinue': True,
                'param1': 0,  # Hold time
                'param2': 0,  # Accept radius
                'param3': 0,  # Pass through radius
                'param4': 0,  # Yaw
                'x_lat': float(self.current_position['lat']),
                'y_long': float(self.current_position['lng']),
                'z_alt': float(self.current_position.get('alt', 0.0))
            }

            # Create mission waypoint (seq=1) - This is the actual target
            mission_waypoint = {
                'frame': 3,  # MAV_FRAME_GLOBAL_RELATIVE_ALT (relative to HOME)
                'command': 16,  # MAV_CMD_NAV_WAYPOINT
                'is_current': False,  # Will become current after upload
                'autocontinue': True,
                'param1': 0,  # Hold time
                'param2': float(self.waypoint_reached_threshold),  # Accept radius
                'param3': 0,  # Pass through radius
                'param4': 0,  # Yaw
                'x_lat': float(waypoint['x_lat']),
                'y_long': float(waypoint['y_long']),
                'z_alt': float(waypoint['z_alt'])
            }

            # Clear existing waypoints
            self.log(f"🗑️ Clearing existing waypoints...")
            try:
                # Try roslibpy first, fall back to CLI if it fails
                clear_response = self.bridge.clear_waypoints()
                if not clear_response.get('success', False):
                    # Fall back to CLI method
                    self.log(f"⚠ roslibpy clear failed, trying CLI...")
                    clear_response = self.bridge.clear_waypoints_cli()
                if clear_response.get('success', False):
                    self.log(f"✓ Cleared existing waypoints")
                else:
                    self.log(f"⚠ Clear waypoints returned: {clear_response}", "warning")
            except Exception as clear_error:
                # Try CLI as fallback
                try:
                    self.log(f"⚠ roslibpy failed, trying CLI: {clear_error}")
                    clear_response = self.bridge.clear_waypoints_cli()
                    if clear_response.get('success', False):
                        self.log(f"✓ Cleared existing waypoints (CLI)")
                    else:
                        self.log(f"⚠ CLI also failed: {clear_response}", "warning")
                except Exception as cli_error:
                    self.log(f"⚠ Failed to clear waypoints (non-fatal): {cli_error}", "warning")

            # Upload HOME + mission waypoint (2 waypoints total)
            self.log(f"📤 Uploading HOME + waypoint to Pixhawk...")
            # Try roslibpy first, fall back to CLI if it fails or times out
            try:
                response = self.bridge.push_waypoints([home_waypoint, mission_waypoint])
                if not response.get('success', False):
                    self.log(f"⚠ roslibpy push returned failure, trying CLI...")
                    response = self.bridge.push_waypoints_cli([home_waypoint, mission_waypoint])
            except Exception as push_error:
                # roslibpy timed out or failed - try CLI as fallback
                self.log(f"⚠ roslibpy push failed (timeout?), trying CLI: {push_error}")
                try:
                    response = self.bridge.push_waypoints_cli([home_waypoint, mission_waypoint])
                except Exception as cli_error:
                    self.log(f"❌ CLI push also failed: {cli_error}", "error")
                    return False

            if response.get('success', False):
                self.log(f"✅ HOME + waypoint uploaded successfully")

                # Set current waypoint to 1 (mission waypoint, since 0 is HOME)
                self.log(f"🎯 Setting current waypoint to 1 (mission target)")
                try:
                    response = self.bridge.set_current_waypoint(1)
                    if not response.get('success', False):
                        # Fall back to CLI
                        self.log(f"⚠ roslibpy set_current failed, trying CLI...")
                        response = self.bridge.set_current_waypoint_cli(1)
                except Exception as e:
                    # Try CLI as fallback
                    self.log(f"⚠ roslibpy failed, trying CLI: {e}")
                    try:
                        response = self.bridge.set_current_waypoint_cli(1)
                    except Exception as cli_error:
                        self.log(f"⚠ CLI also failed: {cli_error}", "warning")

                # Simple verification delay
                time.sleep(0.5)

                return True
            else:
                self.log(f"❌ Failed to upload waypoints: {response}", "error")
                return False

        except Exception as e:
            self.log(f"❌ Waypoint upload error: {e}", "error")
            return False

    def upload_mission_to_pixhawk(self, waypoints: List[Dict[str, Any]]) -> bool:
        """Upload mission to Pixhawk via MAVROS bridge"""
        try:
            # Set loading state
            self.mission_state = MissionState.LOADING
            
            # Clear existing mission first
            self.log(f"Clearing existing waypoints...")
            try:
                clear_response = self.bridge.clear_waypoints()
                if not clear_response.get('success', False):
                    # Fall back to CLI method
                    self.log("⚠ roslibpy clear failed, trying CLI...")
                    clear_response = self.bridge.clear_waypoints_cli()
                if clear_response.get('success', False):
                    self.log(f"✓ Cleared existing waypoints")
                else:
                    self.log("⚠ Failed to clear existing waypoints", "warning")
            except Exception as clear_error:
                # Try CLI as fallback
                try:
                    self.log(f"⚠ roslibpy failed, trying CLI: {clear_error}")
                    clear_response = self.bridge.clear_waypoints_cli()
                    if clear_response.get('success', False):
                        self.log(f"✓ Cleared existing waypoints (CLI)")
                except Exception as cli_error:
                    self.log(f"⚠ Failed to clear waypoints (non-fatal): {cli_error}", "warning")

            # Upload new waypoints (HOME + mission waypoint = 2 total)
            expected_count = len(waypoints)
            self.log(f"Uploading {expected_count} waypoint(s) to Pixhawk...")
            self.log(f"  • Waypoint 0: HOME position")
            self.log(f"  • Waypoint 1: Mission target")

            # Try roslibpy first, fall back to CLI if it fails
            response = self.bridge.push_waypoints(waypoints)
            if not response.get('success', False):
                self.log(f"⚠ roslibpy push failed, trying CLI...")
                response = self.bridge.push_waypoints_cli(waypoints)

            if response.get('success', False):
                self.log(f"✅ Successfully uploaded {expected_count} waypoint(s)")

                # CRITICAL: Verify mission was properly stored on Pixhawk
                self.log(f"🔍 Verifying mission on Pixhawk...")

                # Retry verification up to 3 times with increasing delays
                max_retries = 3
                for retry in range(max_retries):
                    delay = 1.0 + (retry * 0.5)  # 1.0s, 1.5s, 2.0s
                    self.log(f"⏱ Waiting {delay}s for Pixhawk to commit mission (attempt {retry + 1}/{max_retries})...")
                    time.sleep(delay)

                    try:
                        verify_response = self.bridge.pull_waypoints()
                        stored_waypoints = verify_response.get('waypoints', [])

                        self.log(f"📊 Verification attempt {retry + 1}: Found {len(stored_waypoints)} waypoints on Pixhawk")

                        if len(stored_waypoints) != expected_count:
                            if retry < max_retries - 1:
                                self.log(f"⚠ Verification attempt {retry + 1} incomplete - retrying...", "warning")
                                continue
                            else:
                                self.log(f"❌ Mission verification FAILED after {max_retries} attempts:", "error")
                                self.log(f"   Expected: {expected_count} waypoints (HOME + mission)", "error")
                                self.log(f"   Actual: {len(stored_waypoints)} waypoints", "error")
                                self.log(f"   Mission not properly stored - AUTO mode will fail", "error")
                                return False

                        # Verify sequence numbers and commands
                        home_found = False
                        mission_found = False
                        for wp in stored_waypoints:
                            seq = wp.get('seq', -1)
                            cmd = wp.get('command', -1)
                            if seq == 0:
                                home_found = True
                                self.log(f"✓ HOME waypoint found (seq=0, cmd={cmd})")
                            elif seq == 1:
                                mission_found = True
                                self.log(f"✓ Mission waypoint found (seq=1, cmd={cmd})")

                        if not home_found or not mission_found:
                            if retry < max_retries - 1:
                                self.log(f"⚠ Mission structure incomplete on attempt {retry + 1} - retrying...", "warning")
                                continue
                            else:
                                self.log(f"❌ Mission structure invalid after {max_retries} attempts:", "error")
                                self.log(f"   HOME found: {home_found}, Mission found: {mission_found}", "error")
                                return False

                        self.log(f"✅ Mission verified on attempt {retry + 1}: Complete HOME + mission waypoint structure")
                        self.log(f"✅ Mission is VALID and ready for AUTO mode")

                        # Debug: Show detailed mission structure using already-fetched waypoints
                        self.debug_mission_structure_with_data(stored_waypoints)

                        return True

                    except Exception as verify_error:
                        if retry < max_retries - 1:
                            self.log(f"⚠ Verification attempt {retry + 1} error: {verify_error} - retrying...", "warning")
                            continue
                        else:
                            self.log(f"⚠ Mission verification failed after {max_retries} attempts: {verify_error}", "warning")
                            self.log(f"⚠ Proceeding without verification - AUTO mode may fail", "warning")
                            return True  # Continue anyway on final attempt, but warn

                # Should not reach here
                return False

            else:
                self.log(f"❌ Failed to upload waypoints: {response}", "error")
                return False

        except Exception as e:
            self.log(f"Mission upload error: {e}", "error")
            return False
    
    def ensure_pixhawk_armed(self) -> bool:
        """Ensure Pixhawk is armed before setting AUTO mode. Returns True if armed, False if failed."""
        import time
        try:
            # Check current armed state from telemetry
            if self.pixhawk_state and self.pixhawk_state.get('armed', False):
                self.log("✓ Pixhawk already armed")
                return True
            
            # Try to arm the vehicle
            self.log("⚡ Attempting to arm Pixhawk...")
            arm_response = self.bridge.set_armed(True)
            
            # Trust the bridge response first - if it indicates success, accept it
            if arm_response.get('success', False) or arm_response.get('armed', False):
                self.log("✅ PIXHAWK ARMED SUCCESSFULLY (via bridge response)")
                return True
            
            # If bridge didn't signal success, wait briefly for telemetry to update
            # Don't trust bridge response - verify actual armed state
            # Wait up to 3 seconds for arm to complete
            max_wait = 3.0
            check_interval = 0.2
            elapsed = 0.0
            
            while elapsed < max_wait:
                time.sleep(check_interval)
                elapsed += check_interval
                
                # Check if actually armed via telemetry
                if self.pixhawk_state and self.pixhawk_state.get('armed', False):
                    self.log(f"✅ PIXHAWK ARMED SUCCESSFULLY (verified after {elapsed:.1f}s via telemetry)")
                    return True
            
            # Timeout - arm failed
            self.log(f"✗ Failed to arm Pixhawk - pre-arm checks not satisfied (bridge response: {arm_response})", "error")
            return False
                
        except Exception as e:
            self.log(f"Error during arm attempt: {e}", "error")
            return False

    def set_pixhawk_mode(self, mode: str):
        """Set Pixhawk flight mode"""
        try:
            current_mode = self.pixhawk_state.get('mode', 'UNKNOWN') if self.pixhawk_state else 'UNKNOWN'
            self.log(f"🔄 MODE CHANGE: {current_mode} → {mode}")
            response = self.bridge.set_mode(mode=mode)
            if response.get('mode_sent', False):
                self.log(f"✅ PIXHAWK MODE CHANGED TO: {mode}")
            else:
                self.log(f"❌ Failed to set mode to {mode}", "warning")
        except Exception as e:
            self.log(f"❌ Mode setting error: {e}", "error")
    
    def set_current_waypoint(self, wp_seq: int):
        """Set the current waypoint in the mission"""
        try:
            response = self.bridge.set_current_waypoint(wp_seq)
            if not response.get('success', False):
                # Fall back to CLI
                self.log(f"⚠ roslibpy set_current failed, trying CLI...")
                response = self.bridge.set_current_waypoint_cli(wp_seq)
            if response.get('success', False):
                self.log(f"✅ Current waypoint set to {wp_seq}")
            else:
                self.log(f"⚠ Failed to set current waypoint: {response}", "warning")
        except Exception as e:
            # Try CLI as fallback
            self.log(f"⚠ roslibpy failed, trying CLI: {e}")
            try:
                response = self.bridge.set_current_waypoint_cli(wp_seq)
                if response.get('success', False):
                    self.log(f"✅ Current waypoint set to {wp_seq} (CLI)")
                else:
                    self.log(f"⚠ CLI also failed: {response}", "warning")
            except Exception as cli_error:
                self.log(f"❌ Error setting current waypoint: {cli_error}", "error")
    
    def calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance between two GPS coordinates in meters using Karney geodesic formulas.
        Uses Karney's method for consistency with GPS failsafe monitor.
        Karney's geodesic formulas are more accurate than Haversine for all distances.
        """
        if calculate_accuracy_error_mm is not None:
            try:
                # Use Karney geodesic method via gps_failsafe_monitor for consistency
                distance_mm = calculate_accuracy_error_mm(lat2, lng2, lat1, lng1)
                return distance_mm / 1000.0  # Convert mm to meters
            except Exception:
                pass
        
        # Fallback to Haversine if Karney unavailable
        try:
            R = 6371000  # Earth radius in meters
            lat1_rad = math.radians(lat1)
            lat2_rad = math.radians(lat2)
            delta_lat = math.radians(lat2 - lat1)
            delta_lng = math.radians(lng2 - lng1)
            
            a = (math.sin(delta_lat/2) * math.sin(delta_lat/2) +
                 math.cos(lat1_rad) * math.cos(lat2_rad) *
                 math.sin(delta_lng/2) * math.sin(delta_lng/2))
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            
            return R * c
            
        except Exception:
            return float('inf')  # Return large distance on error
    
    def cancel_timers(self):
        """Cancel all active timers including RTK monitor.

        Note: Only cancels timers (non-blocking). Does NOT join here because
        timer callbacks (hold_period_complete, waypoint_timeout) acquire self.lock,
        and callers of cancel_timers() already hold self.lock — joining would deadlock.
        """
        for timer in [self.hold_timer, self.mission_timer,
                      self.position_check_timer, self.rtk_monitor_timer]:
            if timer is not None:
                timer.cancel()
        self.hold_timer = None
        self.mission_timer = None
        self.position_check_timer = None
        self.rtk_monitor_timer = None
    
    def get_status(self) -> Dict[str, Any]:
        """Get current mission status"""
        with self.lock:
            return {
                'mission_state': self.mission_state.value,
                'mission_mode': self.mission_mode.value,
                'current_waypoint': self.current_waypoint_index + 1 if self.waypoints else 0,
                'total_waypoints': len(self.waypoints),
                'current_position': self.current_position,
                'pixhawk_state': self.pixhawk_state,
                'waiting_for_waypoint_reach': self.waiting_for_waypoint_reach,
                'waypoints': self.waypoints,
                # Mission execution parameters
                'mission_timeout': self.mission_timeout,
                'accuracy_threshold_mm': self.accuracy_threshold_mm,
                'fallback_zone_timeout_seconds': self.fallback_zone_timeout_seconds,
                # GPS Failsafe status fields
                'gps_failsafe_mode': self.failsafe_mode,
                'gps_failsafe_triggered': self.failsafe_monitor.state if self.failsafe_monitor else None,
                'gps_failsafe_servo_suppressed': self.servo_suppressed,
                # Obstacle detection status
                'obstacle_detection_enabled': self.obstacle_detection_enabled,
                'obstacle_distance_mm': self.obstacle_monitor.last_distance_mm if self.obstacle_monitor else None,
                'obstacle_warning_zones': {
                    'min_mm': self.obstacle_warning_min_mm,
                    'max_mm': self.obstacle_warning_max_mm
                },
                'obstacle_danger_zones': {
                    'min_mm': self.obstacle_danger_min_mm,
                    'max_mm': self.obstacle_danger_max_mm
                },
                # Multi-waypoint mode status
                'multi_waypoint_mode': self.multi_waypoint_mode,
                'continuous_servo_active': self.continuous_servo_active,
                'dash_state': {
                    'active': self.mission_mode == MissionMode.DASH,
                    'servo_on': self.dash_servo_on,
                    'cumulative_distance': round(self.dash_cumulative_distance, 1),
                    'distance_since_toggle': round(self.dash_distance_since_toggle, 1),
                    'servo_on_distance': self.dash_servo_on_distance,
                    'servo_off_distance': self.dash_servo_off_distance
                } if self.mission_mode == MissionMode.DASH else None
            }
    
    def start_periodic_status_logging(self):
        """Start periodic status logging at 20Hz (every 0.05 seconds)"""
        if hasattr(self, '_status_logging_active') and self._status_logging_active:
            return
        
        self._status_logging_active = True
        
        def log_status_periodically():
            while self._status_logging_active and self.mission_state == MissionState.RUNNING:
                progress_data = None
                with self.lock:
                    if self.waiting_for_waypoint_reach and self.current_position:
                        waypoint = self.waypoints[self.current_waypoint_index]
                        distance = self.calculate_distance(
                            self.current_position['lat'], self.current_position['lng'],
                            waypoint['lat'], waypoint['lng']
                        )
                        mode = self.pixhawk_state.get('mode', 'UNKNOWN') if self.pixhawk_state else 'UNKNOWN'
                        armed = self.pixhawk_state.get('armed', False) if self.pixhawk_state else False

                        self.log(
                            f"📍 Status: WP{self.current_waypoint_index + 1}/{len(self.waypoints)} | "
                            f"Distance: {distance:.2f}m | "
                            f"Mode: {mode} | "
                            f"Armed: {'YES' if armed else 'NO'} | "
                            f"Pos: ({self.current_position['lat']:.6f}, {self.current_position['lng']:.6f})"
                        )

                        progress_data = {
                            "event_type": "mission_progress",
                            "waypoint_id": self.current_waypoint_index + 1,
                            "current_waypoint": self.current_waypoint_index + 1,
                            "distance_to_next_m": distance,
                            "mode": mode,
                            "armed": armed,
                        }

                # Emit outside the lock so the callback never deadlocks
                if progress_data is not None:
                    self.emit_status("Navigation progress", "info", extra_data=progress_data)

                time.sleep(0.05)  # 20Hz = 0.05 seconds
            # Thread exiting (paused or stopped) — clear flag so resume can restart
            self._status_logging_active = False

        # Start logging thread
        self._status_logging_thread = threading.Thread(target=log_status_periodically, daemon=True)
        self._status_logging_thread.start()
        self.log(f"📊 Started periodic status logging at 20Hz")
    
    def stop_periodic_status_logging(self):
        """Stop periodic status logging"""
        if hasattr(self, '_status_logging_active'):
            self._status_logging_active = False
            self.log(f"⏹ Stopped periodic status logging")
    
    def debug_mission_structure(self):
        """Debug helper to verify mission structure on Pixhawk (pulls waypoints)"""
        try:
            verify_response = self.bridge.pull_waypoints()
            waypoints = verify_response.get('waypoints', [])
            self.debug_mission_structure_with_data(waypoints)
        except Exception as e:
            self.log(f"❌ Debug mission structure failed: {e}", "error")

    def debug_mission_structure_with_data(self, waypoints: List[Dict[str, Any]]):
        """Debug helper to display mission structure using already-fetched waypoints"""
        try:
            self.log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.log(f"📋 MISSION STRUCTURE DEBUG")
            self.log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            self.log(f"Total waypoints on Pixhawk: {len(waypoints)}")
            self.log(f"UI mission waypoints: {len(self.waypoints)}")
            self.log(f"Current UI waypoint index: {self.current_waypoint_index}")
            self.log(f"")

            for wp in waypoints:
                seq = wp.get('seq', 'unknown')
                cmd = wp.get('command', 'unknown')
                frame = wp.get('frame', 'unknown')
                lat = wp.get('x_lat', 0)
                lng = wp.get('y_long', 0)
                alt = wp.get('z_alt', 0)
                current = wp.get('is_current', False)

                wp_type = "HOME" if seq == 0 else f"MISSION-{seq}"
                current_marker = "← CURRENT" if current else ""

                self.log(
                    f"  Pixhawk WP{seq}: {wp_type:12} | "
                    f"CMD:{cmd:3} | FRAME:{frame} | "
                    f"({lat:.6f}, {lng:.6f}, {alt:.1f}m) | "
                    f"{current_marker}"
                )

                # Show which UI waypoint this corresponds to
                if seq > 0 and seq - 1 < len(self.waypoints):
                    ui_wp = self.waypoints[seq - 1]
                    self.log(
                        f"            → UI WP{seq}: "
                        f"({ui_wp['lat']:.6f}, {ui_wp['lng']:.6f}, {ui_wp.get('alt', 10.0):.1f}m)"
                    )

            self.log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        except Exception as e:
            self.log(f"❌ Debug mission structure display failed: {e}", "error")

    def shutdown(self):
        """Shutdown mission controller"""
        # Capture timer refs and state before cancelling
        need_hold = False
        with self.lock:
            timers_to_join = [self.hold_timer, self.mission_timer,
                              self.position_check_timer, self.rtk_monitor_timer]
            self.running = False
            self.stop_periodic_status_logging()
            self.cancel_timers()
            self.waiting_for_waypoint_reach = False

            # Stop obstacle detection
            if self.obstacle_monitor:
                self.obstacle_monitor.stop()

            if self.mission_state == MissionState.RUNNING:
                need_hold = True

            self.log("Mission controller shutdown")

        # Blocking bridge call OUTSIDE the lock
        if need_hold:
            try:
                self.set_pixhawk_mode("HOLD")
            except Exception:
                pass

        # Join timers OUTSIDE the lock to avoid deadlock with timer callbacks
        for timer in timers_to_join:
            if timer is not None:
                try:
                    timer.join(timeout=1.0)
                except Exception:
                    pass
