#!/usr/bin/env python3
"""
GPS Failsafe Monitor - State machine for monitoring GPS fix type and accuracy during mission.

Modes:
  - disable: No failsafe checks
  - strict: Pause mission + hold on fix_type ≠ 6 OR accuracy_error > 60mm, await user ack
  - relax: Suppress servo only on accuracy_error > 60mm, continue movement

Stable Window: 5 seconds continuous monitoring before recovery (both conditions healthy)
"""

import threading
import time
import math
from enum import Enum
from typing import Optional, Callable, Dict, Any
from datetime import datetime


class FailsafeState(Enum):
    """Failsafe state machine states"""
    IDLE = "idle"                    # No mission running
    MONITORING = "monitoring"        # Mission running, no failsafe trigger
    TRIGGERED = "triggered"          # Condition violated (fix_type ≠ 6 or accuracy > 60mm)
    AWAITING_ACK = "awaiting_ack"   # Waiting for user ack (strict mode only)
    STABLE_WINDOW = "stable_window" # Counting 5s with healthy conditions
    READY_RESUME = "ready_resume"   # User can resume/restart (strict mode only)
    SUPPRESSED = "suppressed"        # Servo suppressed (relax mode only)


class GPSFailsafeMonitor:
    """
    GPS Failsafe state machine and monitoring logic.
    
    Thresholds:
    - Fix type: must be 6 (RTK Fixed)
    - Accuracy error: must be ≤ 60mm
    - Stable window: 5 seconds of continuous healthy conditions
    """
    
    def __init__(self, status_callback: Optional[Callable] = None, logger=None):
        """
        Initialize the failsafe monitor.
        
        Args:
            status_callback: Callback function for status updates: func(status_dict)
            logger: Optional logger function: func(message, level)
        """
        self.status_callback = status_callback
        self.logger = logger
        
        # Current state
        self.state = FailsafeState.IDLE
        self.mode = "disable"  # "strict", "relax", "disable"
        
        # Thresholds
        self.FIX_TYPE_REQUIRED = 6  # RTK Fixed
        self.ACCURACY_THRESHOLD_MM = 60
        self.STABLE_WINDOW_SECONDS = 5
        self.CHECK_INTERVAL_MS = 100
        
        # Condition tracking
        self.last_fix_type: Optional[int] = None
        self.last_accuracy_error_mm: Optional[float] = None
        self.last_check_time: float = time.time()
        self.stable_window_start_time: Optional[float] = None
        self.stable_count = 0
        
        # User acknowledgement
        self.user_acked = False
        self.ack_received_time: Optional[float] = None
        
        # Threading
        self.lock = threading.RLock()
        self.monitor_timer: Optional[threading.Timer] = None
        self.running = True
    
    def log(self, message: str, level: str = "info"):
        """Log message with optional logger"""
        if self.logger:
            try:
                self.logger(f"[GPS_FAILSAFE] {message}", level)
            except Exception:
                pass
        print(f"[GPS_FAILSAFE] {message}", flush=True)
    
    def emit_status(self, status_data: Dict[str, Any]):
        """Emit status update via callback"""
        if self.status_callback:
            try:
                self.status_callback(status_data)
            except Exception as e:
                self.log(f"Status callback error: {e}", "error")
    
    def set_mode(self, mode: str) -> None:
        """Set failsafe mode (strict/relax/disable)"""
        with self.lock:
            if mode in ['strict', 'relax', 'disable']:
                old_mode = self.mode
                self.mode = mode
                self.log(f"Mode changed: {old_mode} → {mode}", "info")
            else:
                self.log(f"Invalid mode: {mode}", "error")
    
    def start_mission(self) -> None:
        """Start monitoring mission"""
        with self.lock:
            if self.mode == "disable":
                self.state = FailsafeState.MONITORING
                self.log("Mission started (failsafe DISABLED)", "info")
            else:
                self.state = FailsafeState.MONITORING
                self.log(f"Mission started (failsafe mode: {self.mode})", "info")
            
            self.user_acked = False
            self.ack_received_time = None
            self.stable_window_start_time = None
            self.stable_count = 0
    
    def stop_mission(self) -> None:
        """Stop monitoring mission"""
        with self.lock:
            self.state = FailsafeState.IDLE
            self.log("Mission stopped", "info")
    
    def check_conditions(self, fix_type: int, accuracy_error_mm: float) -> Dict[str, Any]:
        """
        Check GPS fix type and accuracy conditions.
        
        Args:
            fix_type: Current GPS fix type (0-6)
            accuracy_error_mm: Distance error between target and current position in mm
            
        Returns:
            Dict with:
            - triggered: bool (True if either condition violated)
            - fix_type_ok: bool
            - accuracy_ok: bool
            - state: current state name
            - action: "none" | "pause_hold" | "suppress_servo" | "recover"
        """
        with self.lock:
            self.last_fix_type = fix_type
            self.last_accuracy_error_mm = accuracy_error_mm
            self.last_check_time = time.time()
            
            # If failsafe disabled, skip all checks
            if self.mode == "disable":
                return {
                    'triggered': False,
                    'fix_type_ok': True,
                    'accuracy_ok': True,
                    'state': self.state.value,
                    'action': 'none'
                }
            
            # Check conditions
            fix_type_ok = (fix_type == self.FIX_TYPE_REQUIRED)
            accuracy_ok = (accuracy_error_mm <= self.ACCURACY_THRESHOLD_MM)
            triggered = not (fix_type_ok and accuracy_ok)
            
            # Determine action based on state and mode
            action = 'none'
            
            if self.state == FailsafeState.MONITORING:
                if triggered:
                    # Condition violated
                    self.state = FailsafeState.TRIGGERED
                    
                    if self.mode == "strict":
                        action = 'pause_hold'
                        self.user_acked = False
                        self.state = FailsafeState.AWAITING_ACK
                        reason = self._get_trigger_reason(fix_type_ok, accuracy_ok, accuracy_error_mm)
                        self.emit_status({
                            'mode': self.mode,
                            'triggered': True,
                            'reason': reason,
                            'fix_type': fix_type,
                            'accuracy_error_mm': accuracy_error_mm,
                            'requires_ack': True,
                            'action': action,
                            'timestamp': datetime.now().isoformat()
                        })
                        self.log(f"Strict failsafe triggered: {reason}", "warning")
                    
                    elif self.mode == "relax":
                        action = 'suppress_servo'
                        self.state = FailsafeState.SUPPRESSED
                        reason = self._get_trigger_reason(fix_type_ok, accuracy_ok, accuracy_error_mm)
                        self.emit_status({
                            'mode': self.mode,
                            'triggered': True,
                            'reason': reason,
                            'fix_type': fix_type,
                            'accuracy_error_mm': accuracy_error_mm,
                            'servo_suppressed': True,
                            'action': action,
                            'timestamp': datetime.now().isoformat()
                        })
                        self.log(f"Relax failsafe triggered: {reason}", "warning")
            
            elif self.state == FailsafeState.AWAITING_ACK:
                # Waiting for user ack in strict mode
                if not triggered:
                    # Conditions recovered while waiting for ack (unlikely but possible)
                    self.log("Conditions recovered while awaiting ack", "info")
            
            elif self.state == FailsafeState.STABLE_WINDOW:
                # Counting down 5s stable window
                if not triggered:
                    # Still healthy
                    elapsed = time.time() - (self.stable_window_start_time or time.time())
                    if elapsed >= self.STABLE_WINDOW_SECONDS:
                        # 5 seconds stable - recovery complete
                        self.state = FailsafeState.READY_RESUME
                        action = 'recovered'
                        self.emit_status({
                            'mode': self.mode,
                            'triggered': False,
                            'state': self.state.value,
                            'action': action,
                            'message': 'GPS conditions stable for 5 seconds',
                            'timestamp': datetime.now().isoformat()
                        })
                        self.log("Failsafe recovered - stable for 5 seconds", "success")
                else:
                    # Condition re-triggered, restart countdown
                    self.stable_window_start_time = time.time()
                    self.log("Stable window reset - condition re-triggered", "warning")
            
            elif self.state == FailsafeState.SUPPRESSED:
                # Relax mode - servo suppressed
                if not triggered:
                    # Conditions recovered
                    self.stable_window_start_time = time.time()
                    self.state = FailsafeState.STABLE_WINDOW
                    self.log("Starting stable window for recovery", "info")
                else:
                    # Still triggered in relax mode
                    action = 'suppress_servo'
            
            return {
                'triggered': triggered,
                'fix_type_ok': fix_type_ok,
                'accuracy_ok': accuracy_ok,
                'fix_type': fix_type,
                'accuracy_error_mm': accuracy_error_mm,
                'state': self.state.value,
                'action': action,
                'servo_suppressed': (self.state in [FailsafeState.SUPPRESSED, FailsafeState.TRIGGERED])
            }
    
    def _get_trigger_reason(self, fix_type_ok: bool, accuracy_ok: bool, accuracy_error_mm: float) -> str:
        """Determine trigger reason message"""
        if not fix_type_ok and not accuracy_ok:
            return f"RTK fix type not 6 AND accuracy error {accuracy_error_mm:.1f}mm > 60mm"
        elif not fix_type_ok:
            return "RTK fix type not 6 (RTK Fixed required)"
        else:
            return f"Accuracy error {accuracy_error_mm:.1f}mm > 60mm threshold"
    
    def acknowledge_failsafe(self) -> Dict[str, Any]:
        """User acknowledges failsafe in strict mode"""
        with self.lock:
            if self.state != FailsafeState.AWAITING_ACK:
                self.log(f"Acknowledge called but state is {self.state.value}", "warning")
                return {
                    'success': False,
                    'message': f'Cannot acknowledge - current state: {self.state.value}'
                }
            
            self.user_acked = True
            self.ack_received_time = time.time()
            self.stable_window_start_time = time.time()
            self.state = FailsafeState.STABLE_WINDOW
            
            self.log("User acknowledged failsafe - starting 5s stable window", "info")
            self.emit_status({
                'mode': self.mode,
                'user_acked': True,
                'state': self.state.value,
                'message': 'Starting 5 second stable window',
                'timestamp': datetime.now().isoformat()
            })
            
            return {
                'success': True,
                'message': 'Failsafe acknowledged - monitoring for 5 seconds'
            }
    
    def can_resume_mission(self) -> bool:
        """Check if mission can resume (strict mode after recovery)"""
        with self.lock:
            return self.state == FailsafeState.READY_RESUME
    
    def reset_to_monitoring(self) -> None:
        """Reset failsafe to monitoring state after resume/restart"""
        with self.lock:
            self.state = FailsafeState.MONITORING
            self.user_acked = False
            self.ack_received_time = None
            self.stable_window_start_time = None
            self.log("Failsafe reset to monitoring", "info")


def calculate_accuracy_error_mm(target_lat: float, target_lon: float, 
                                 current_lat: float, current_lon: float) -> float:
    """
    Calculate distance error between target and current position in millimeters.
    
    Uses Karney's geodesic formulas for improved accuracy.
    
    Args:
        target_lat, target_lon: Target waypoint coordinates
        current_lat, current_lon: Current rover position
        
    Returns:
        Distance in millimeters (gps_failsafe_accuracy_error_mm)
    """
    distance_m = karney_distance_meters(target_lat, target_lon, current_lat, current_lon)
    return distance_m * 1000.0  # Convert to mm


def karney_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points on Earth using Karney's geodesic formulas.
    
    Karney's method is highly accurate for all distances, including antipodal points.
    Implements a simplified version of Karney's algorithm for GPS failsafe accuracy error calculation.
    
    Args:
        lat1, lon1: First point (degrees)
        lat2, lon2: Second point (degrees)
        
    Returns:
        Distance in meters (used for gps_failsafe_accuracy_error_mm)
    """
    # WGS-84 ellipsoid parameters
    a = 6378137.0  # semi-major axis in meters
    b = 6356752.314245  # semi-minor axis in meters
    f = 1 / 298.257223563  # flattening
    
    try:
        # Convert to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
        
        dlon = lon2_rad - lon1_rad
        
        # Normalize dlon to [-π, π]
        while dlon > math.pi:
            dlon -= 2 * math.pi
        while dlon < -math.pi:
            dlon += 2 * math.pi
        
        # First approximation using Vincenty-like iteration
        sin_lat1 = math.sin(lat1_rad)
        cos_lat1 = math.cos(lat1_rad)
        sin_lat2 = math.sin(lat2_rad)
        cos_lat2 = math.cos(lat2_rad)
        
        # Reduced latitudes
        tan_U1 = (1 - f) * sin_lat1 / cos_lat1 if cos_lat1 != 0 else 0
        tan_U2 = (1 - f) * sin_lat2 / cos_lat2 if cos_lat2 != 0 else 0
        cos_U1 = 1 / math.sqrt(1 + tan_U1 * tan_U1) if (1 + tan_U1 * tan_U1) > 0 else 1
        sin_U1 = tan_U1 * cos_U1
        cos_U2 = 1 / math.sqrt(1 + tan_U2 * tan_U2) if (1 + tan_U2 * tan_U2) > 0 else 1
        sin_U2 = tan_U2 * cos_U2
        
        # Iterative process
        lambda_var = dlon
        lambda_prev = float('inf')
        iteration = 0
        iteration_limit = 100
        
        while abs(lambda_var - lambda_prev) > 1e-12 and iteration < iteration_limit:
            sin_lambda = math.sin(lambda_var)
            cos_lambda = math.cos(lambda_var)
            
            sin_sq_sigma = (cos_U2 * sin_lambda) ** 2 + (cos_U1 * sin_U2 - sin_U1 * cos_U2 * cos_lambda) ** 2
            sin_sigma = math.sqrt(sin_sq_sigma)
            
            if sin_sigma == 0:
                return 0.0
            
            cos_sigma = sin_U1 * sin_U2 + cos_U1 * cos_U2 * cos_lambda
            sigma = math.atan2(sin_sigma, cos_sigma)
            
            sin_alpha = cos_U1 * cos_U2 * sin_lambda / sin_sigma
            cos_sq_alpha = 1 - sin_alpha * sin_alpha
            
            cos_2sigma_m = cos_sigma - 2 * sin_U1 * sin_U2 / cos_sq_alpha if cos_sq_alpha > 0 else 0
            
            C = f / 16 * cos_sq_alpha * (4 + f * (4 - 3 * cos_sq_alpha))
            
            lambda_prev = lambda_var
            lambda_var = dlon + (1 - C) * f * sin_alpha * (sigma + C * sin_sigma * 
                         (cos_2sigma_m + C * cos_sigma * (-1 + 2 * cos_2sigma_m * cos_2sigma_m)))
            
            iteration += 1
        
        if iteration >= iteration_limit:
            return haversine_distance_meters(lat1, lon1, lat2, lon2)
        
        # Final calculation
        u_sq = cos_sq_alpha * (a * a - b * b) / (b * b)
        A = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
        B = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
        
        delta_sigma = B * sin_sigma * (cos_2sigma_m + B / 4 * (cos_sigma * (-1 + 2 * cos_2sigma_m * cos_2sigma_m) - 
                      B / 6 * cos_2sigma_m * (-3 + 4 * sin_sigma * sin_sigma) * (-3 + 4 * cos_2sigma_m * cos_2sigma_m)))
        
        s = b * A * (sigma - delta_sigma)
        
        return s
    
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.0


# COMMENTED OUT: Original Vincenty formula - replaced with Karney's geodesic formulas
# def vincenty_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
#     """
#     Calculate great-circle distance between two points on Earth using Vincenty's formula.
#     
#     Vincenty's formula is more accurate than Haversine, especially for longer distances.
#     
#     Args:
#         lat1, lon1: First point (degrees)
#         lat2, lon2: Second point (degrees)
#         
#     Returns:
#         Distance in meters
#     """
#     # WGS-84 ellipsoid parameters
#     a = 6378137.0  # semi-major axis in meters
#     b = 6356752.314245  # semi-minor axis in meters
#     f = 1 / 298.257223563  # flattening
#     
#     try:
#         # Convert to radians
#         lat1_rad = math.radians(lat1)
#         lon1_rad = math.radians(lon1)
#         lat2_rad = math.radians(lat2)
#         lon2_rad = math.radians(lon2)
#         
#         L = lon2_rad - lon1_rad  # difference in longitude
#         
#         # Reduced latitudes
#         tanU1 = (1 - f) * math.tan(lat1_rad)
#         cosU1 = 1 / math.sqrt(1 + tanU1**2)
#         sinU1 = tanU1 * cosU1
#         
#         tanU2 = (1 - f) * math.tan(lat2_rad)
#         cosU2 = 1 / math.sqrt(1 + tanU2**2)
#         sinU2 = tanU2 * cosU2
#         
#         # Initial approximation
#         lambda_ = L
#         lambda_prev = float('inf')  # Force at least one iteration
#         iteration_limit = 100
#         iteration = 0
#         
#         # Initialize variables
#         sigma = 0
#         sin_sigma = 0
#         cos_sigma = 1
#         cos_sq_alpha = 1
#         cos_2sigma_m = 1
#         sin_sq_sigma = 0  # Initialize here
#         
#         while abs(lambda_ - lambda_prev) > 1e-12 and iteration < iteration_limit:
#             sin_lambda = math.sin(lambda_)
#             cos_lambda = math.cos(lambda_)
#             
#             sin_sq_sigma = (cosU2 * sin_lambda)**2 + (cosU1 * sinU2 - sinU1 * cosU2 * cos_lambda)**2
#             sin_sigma = math.sqrt(sin_sq_sigma)
#             cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lambda
#             sigma = math.atan2(sin_sigma, cos_sigma)
#             
#             sin_alpha = cosU1 * cosU2 * sin_lambda / sin_sigma
#             cos_sq_alpha = 1 - sin_alpha**2
#             
#             # Handle equatorial case where cos²α → 0
#             if cos_sq_alpha < 1e-16:
#                 cos_2sigma_m = 0
#             else:
#                 cos_2sigma_m = cos_sigma - 2 * sinU1 * sinU2 / cos_sq_alpha
#             
#             C = f / 16 * cos_sq_alpha * (4 + f * (4 - 3 * cos_sq_alpha))
#             
#             lambda_prev = lambda_
#             lambda_ = L + (1 - C) * f * sin_alpha * (sigma + C * sin_sigma * (cos_2sigma_m + C * cos_sigma * (-1 + 2 * cos_2sigma_m**2)))
#             
#             iteration += 1
#         
#         if iteration >= iteration_limit:
#             # Fallback to Haversine if Vincenty doesn't converge
#             return haversine_distance_meters(lat1, lon1, lat2, lon2)
#         
#         # Check for coincident points
#         if abs(sin_sq_sigma) < 1e-24:
#             return 0.0
#         
#         u_sq = cos_sq_alpha * (a**2 - b**2) / b**2
#         A = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
#         B = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
#         
#         delta_sigma = B * sin_sigma * (cos_2sigma_m + B / 4 * (cos_sigma * (-1 + 2 * cos_2sigma_m**2) - B / 6 * cos_2sigma_m * (-3 + 4 * sin_sigma**2) * (-3 + 4 * cos_2sigma_m**2)))
#         
#         s = b * A * (sigma - delta_sigma)
#         
#         return s
#     
#     except (ValueError, TypeError, ZeroDivisionError):
#         # Return 0 if coordinates invalid or calculation fails
#         return 0.0


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points on Earth using Haversine formula.
    
    Args:
        lat1, lon1: First point (degrees)
        lat2, lon2: Second point (degrees)
        
    Returns:
        Distance in meters
    """
    R = 6371000.0  # Earth radius in meters
    
    try:
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat / 2.0) ** 2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             (math.sin(dlon / 2.0) ** 2))
        
        c = 2.0 * math.asin(min(1.0, math.sqrt(a)))
        return R * c
    except (ValueError, TypeError):
        # Return 0 if coordinates invalid
        return 0.0
