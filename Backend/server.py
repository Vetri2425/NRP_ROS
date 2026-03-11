from __future__ import annotations

import asyncio
import socketio as socketio_pkg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response as FastAPIResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import threading
import time
import math
import json
import base64
import socket
import sys
import tempfile
import os
from datetime import datetime
from collections import deque
from contextlib import contextmanager, asynccontextmanager
from itertools import count
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('nrp_ros')



# Mission Controller Process Management - REMOVED
# The mission controller node has been removed due to causing rover rotation issues
# with problematic Pixhawk parameter interactions

class RosNodeManager:
    def __init__(self):
        pass  # Mission controller removed

ros_manager = RosNodeManager()
from pymavlink.dialects.v20 import common as mavlink
from dataclasses import dataclass, asdict, field
from typing import Optional, List, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from lora_rtk_handler import LoRaRTKHandler
import os
import atexit
import signal

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Windows lacks fcntl
    fcntl = None  # type: ignore

try:
    # When running as a package (e.g., python -m Backend.server)
    from .mavros_bridge import MavrosBridge  # type: ignore
except Exception:
    # When running as a script from the Backend directory
    from mavros_bridge import MavrosBridge  # type: ignore

try:
    # LoRa RTK Handler for receiving corrections via LoRa
    from .lora_rtk_handler import create_lora_rtk_handler, get_lora_rtk_handler, LoRaRTKHandler  # type: ignore
except Exception:
    try:
        from lora_rtk_handler import create_lora_rtk_handler, get_lora_rtk_handler, LoRaRTKHandler  # type: ignore
    except Exception:
        LoRaRTKHandler = None
        create_lora_rtk_handler = None
        get_lora_rtk_handler = None

try:
    # Import integrated mission controller
    from .integrated_mission_controller import IntegratedMissionController, MissionState, MissionMode  # type: ignore
except Exception:
    from integrated_mission_controller import IntegratedMissionController, MissionState, MissionMode  # type: ignore

try:
    # Import manual control handler
    from .manual_control_handler import ManualControlHandler  # type: ignore
except Exception:
    from manual_control_handler import ManualControlHandler  # type: ignore

try:
    # Import TTS module for mission announcements
    from . import tts  # type: ignore
except Exception:
    import tts  # type: ignore

try:
    from .led_controller import LEDController  # type: ignore
except Exception:
    from led_controller import LEDController  # type: ignore

try:
    from .beacon import RoverBeacon  # type: ignore
except Exception:
    from beacon import RoverBeacon  # type: ignore


# Import network monitor for WiFi/LoRa status
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.network_monitor import NetworkMonitor



# --- FastAPI Lifespan (replaces deprecated @app.on_event) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown handling."""
    global _main_loop, _beacon

    # === STARTUP ===
    _main_loop = asyncio.get_event_loop()

    # Load system settings from config file
    load_system_settings()

    asyncio.create_task(_supervised_task(maintain_mavros_connection, "maintain_mavros_connection"))
    log_message("MAVROS connection maintenance task started")

    asyncio.create_task(_supervised_task(telemetry_loop, "telemetry_loop"))
    log_message("Telemetry task started")

    asyncio.create_task(_supervised_task(connection_health_monitor, "connection_health_monitor"))
    log_message("Connection health monitor started")

    # Start rover discovery beacon
    _beacon = RoverBeacon(
        rover_id=os.environ.get('ROVER_ID', socket.gethostname()),
        rover_name=os.environ.get('ROVER_NAME', 'Rover'),
        port=5001,
    )
    _beacon.start()
    log_message("Rover discovery beacon started", "SUCCESS")

    log_message("All background tasks started successfully", "SUCCESS")

    yield  # Application is running

    # === SHUTDOWN ===
    log_message("Shutting down application...", "WARNING")

    # Stop beacon if running
    if _beacon is not None:
        try:
            _beacon.stop()
            if isinstance(_beacon, threading.Thread):
                _beacon.join(timeout=5.0)
            log_message("Rover discovery beacon stopped", "SUCCESS")
        except Exception as exc:
            logger.warning(f"Beacon shutdown failed: {exc}")

    # Call ROS runtime shutdown
    _shutdown_ros_runtime()

    log_message("Shutdown complete", "SUCCESS")


# --- FastAPI & SocketIO Setup ---
app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jinja2 templates (same directory as FastAPI uses)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# Socket.IO documentation routes (AsyncAPI + interactive tester)
from .socket_docs_router import make_docs_router as _make_docs_router
app.include_router(_make_docs_router(templates))

# Socket.IO AsyncServer (ASGI mode, native FastAPI integration)
sio = socketio_pkg.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    ping_timeout=60,
    ping_interval=25,
    engineio_logger=False,
    logger=False,
    always_connect=True,
    max_http_buffer_size=int(1e8),
)

# ASGI app: Socket.IO wraps FastAPI
sio_app = socketio_pkg.ASGIApp(sio, other_asgi_app=app)

# --- sync_emit helper for threaded callbacks ---
_main_loop: asyncio.AbstractEventLoop | None = None
_beacon: Optional[RoverBeacon] = None

def sync_emit(event, data=None, to=None, room=None, namespace=None):
    """Emit a Socket.IO event from synchronous / threaded code."""
    loop = _main_loop
    if loop is None or loop.is_closed():
        return
    coro = sio.emit(event, data, to=to, room=room, namespace=namespace)
    asyncio.run_coroutine_threadsafe(coro, loop)

# --- FastAPI Middleware ---

@app.middleware("http")
async def request_lifecycle(request: Request, call_next):
    """Unified request/response logging and activity tracking."""
    # Skip Socket.IO transport
    if request.url.path.startswith('/socket.io'):
        return await call_next(request)

    # Log request
    if request.url.path != '/api/health':
        logger.info(f"{request.method} {request.url.path} from {request.client.host if request.client else 'unknown'}")

    # Track HTTP request activity
    try:
        meta: dict = {
            'method': request.method,
            'path': str(request.url.path),
        }
        if request.method in ('POST', 'PUT', 'PATCH'):
            try:
                body = await request.body()
                if body:
                    import json as _json
                    body_dict = _json.loads(body)
                    if isinstance(body_dict, dict):
                        meta['json_keys'] = sorted(list(body_dict.keys()))[:15]
                        if 'waypoints' in body_dict and isinstance(body_dict['waypoints'], list):
                            meta['waypoint_count'] = len(body_dict['waypoints'])
            except Exception:
                pass
        event_type = 'ui_request' if request.url.path.startswith('/api/') else 'http_request'
        record_activity(
            f"HTTP {request.method} {request.url.path} request",
            level='DEBUG',
            event_type=event_type,
            meta=meta
        )
    except Exception as e:
        log_message(f"[request_lifecycle] Failed to record request activity: {e}", "ERROR")

    response = await call_next(request)

    # Log response
    if request.url.path != '/api/health':
        logger.info(f"Response: {response.status_code} for {request.method} {request.url.path}")

    # Track response activity
    try:
        level = 'INFO' if response.status_code < 400 else 'ERROR'
        record_activity(
            f"HTTP {request.method} {request.url.path} responded",
            level=level,
            event_type='server_response',
            meta={
                'status': response.status_code,
            }
        )
    except Exception as e:
        log_message(f"[request_lifecycle] Failed to record response activity: {e}", "ERROR")

    return response

# --- Mission Controller WebSocket Handlers - REMOVED ---
# Mission controller node and related handlers have been removed
# Use direct MAVROS integration for mission control instead

ROS_DISTRO = os.environ.get('ROS_DISTRO', 'humble')
_ros_lib_dir = f"/opt/ros/{ROS_DISTRO}/lib"
if os.path.isdir(_ros_lib_dir):
    _existing_ld = os.environ.get('LD_LIBRARY_PATH', '')
    if _ros_lib_dir not in _existing_ld.split(':'):
        _patched_ld = ':'.join(filter(None, [_ros_lib_dir, _existing_ld]))
        os.environ['LD_LIBRARY_PATH'] = _patched_ld

ROS_AVAILABLE = False
ROS_IMPORT_ERROR: Exception | None = None
telemetry_bridge = None
command_bridge: Optional["CommandBridge"] = None
# Executor may be created only when ROS is available.
_ros_executor: Optional["MultiThreadedExecutor"] = None # type: ignore
ros_thread: Optional[threading.Thread] = None
_singleton_lock_handle: Optional[TextIO] = None

try:
    import rclpy  # type: ignore
    from rclpy.node import Node  # type: ignore
    from rclpy.executors import MultiThreadedExecutor  # type: ignore
    from std_msgs.msg import String  # type: ignore

    try:
        from mavros_msgs.srv import CommandBool, SetMode  # type: ignore
    except ImportError:
        CommandBool = None  # type: ignore
        SetMode = None  # type: ignore

    ROS_AVAILABLE = True
except Exception as exc:
    rclpy = None  # type: ignore
    Node = None  # type: ignore
    MultiThreadedExecutor = None  # type: ignore
    String = None  # type: ignore
    CommandBool = None  # type: ignore
    SetMode = None  # type: ignore
    ROS_IMPORT_ERROR = exc
    logger.warning(f"ROS2 support disabled: {exc}")


def log_message(message, level='INFO', event_type: str = 'general', meta=None):
    """Logs a message using the configured logger and emits to frontend."""
    try:
        record_activity(message, level=level, event_type=event_type, meta=meta)
        
        level_map = {
            "DEBUG": logger.debug,
            "INFO": logger.info,
            "SUCCESS": logger.info,
            "WARN": logger.warning,
            "WARNING": logger.warning,
            "ERROR": logger.error,
            "CRITICAL": logger.critical,
        }
        log_func = level_map.get(level.upper(), logger.info)
        log_func(message)

        try:
            # Format for frontend with a timestamp
            ts = time.strftime('%Y-%m-%d %H:%M:%S')
            text = f"[{ts}] [{level}] {message}"
            sync_emit('server_log', {'message': text, 'level': level})
        except Exception:
            pass  # sync_emit can fail if loop is not running
            
    except Exception as e:
        # Failsafe: if logging itself fails, print to stderr
        print(f"!!! LOGGING FAILED: {e} !!!", file=sys.stderr, flush=True)
        print(f"Original message: [{level}] {message}", file=sys.stderr, flush=True)


def emit_rtk_debug(event: str, sender_id: Optional[str] = None, extra: Optional[dict] = None) -> None:
    """Emit a compact RTK debug event to the frontend and log it locally.

    Args:
        event: Short event name, e.g. 'start_lora_request_received'
        sender_id: Socket.IO sender id to target the debug message (optional)
        extra: Additional key/value pairs to include
    """
    payload = {
        'event': event,
        'timestamp': datetime.now().isoformat()
    }
    if extra:
        payload.update(extra)
    try:
        sync_emit('rtk_debug', payload, to=sender_id)
    except Exception:
        pass
    try:
        log_message(f"RTK DEBUG: {event} -> {json.dumps(payload)}", level='DEBUG')
    except Exception:
        # Ensure debug emitter never raises
        pass
    


if not ROS_AVAILABLE and ROS_IMPORT_ERROR is not None:
    log_message(
        f"ROS2 features disabled: {ROS_IMPORT_ERROR}",
        level='WARNING',
        event_type='startup',
        meta={'ros_distro': ROS_DISTRO}
    )

if ROS_AVAILABLE:

    def derive_signal_strength(last_heartbeat: float | None, rc_connected: bool) -> str:
        """Return a human readable link quality label for the UI."""
        if last_heartbeat is None:
            return 'No Link'
        age = time.time() - last_heartbeat
        if age <= 2:
            return 'Excellent' if rc_connected else 'Good'
        if age <= 5:
            return 'Fair'
        if age <= 10:
            return 'Weak'
        return 'Lost'

    def _merge_ros2_telemetry(payload: dict) -> None:
        """Merge telemetry published via the ROS2 bridge into the shared rover state."""
        if not payload or not isinstance(payload, dict):
            return
        global is_vehicle_connected, schedule_fast_emit, emit_rover_data_now
        changed = False
        now = time.time()
        try:
            state = payload.get('state')
            global_data = payload.get('global')
            position = payload.get('position')  # Legacy support
            rtk = payload.get('rtk')

            with mavros_telem_lock:
                if isinstance(state, dict):
                    armed_flag = bool(state.get('armed'))
                    status = 'armed' if armed_flag else 'disarmed'
                    if status != current_state.status:
                        current_state.status = status
                        changed = True
                    connected = state.get('connected')
                    if isinstance(connected, bool) and connected != is_vehicle_connected:
                        is_vehicle_connected = connected
                        changed = True
                    mode = state.get('mode')
                    if isinstance(mode, str) and mode:
                        normalized_mode = mode.upper()
                        if normalized_mode != current_state.mode:
                            current_state.mode = normalized_mode
                            changed = True
                    heartbeat_ms = state.get('heartbeat_ts')
                    if isinstance(heartbeat_ms, (int, float)) and heartbeat_ms > 0:
                        current_state.last_heartbeat = float(heartbeat_ms) / 1000.0
                    system_status = state.get('system_status')
                    if isinstance(system_status, str) and system_status:
                        current_state.signal_strength = derive_signal_strength(
                            current_state.last_heartbeat,
                            current_state.rc_connected
                        )
                    current_state.last_update = now

                # Process global position data (NEW FORMAT)
                if isinstance(global_data, dict):
                    lat = global_data.get('latitude')
                    lon = global_data.get('longitude')
                    alt = global_data.get('altitude')
                    vel = global_data.get('vel')
                    satellites = global_data.get('satellites_visible')
                    hrms = global_data.get('hrms')
                    vrms = global_data.get('vrms')
                    
                    # Only update position if values are non-zero.
                    # telemetry_node.py publishes (0.0, 0.0) when its position
                    # callback hasn't fired (QoS mismatch), which overwrites
                    # the correct data already set by MavrosBridge.
                    if (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                            and (float(lat) != 0.0 or float(lon) != 0.0)):
                        current_state.position = Position(lat=float(lat), lng=float(lon))
                        changed = True
                        current_state.last_update = now

                    # Update satellites count (skip zero — may be stale default)
                    if isinstance(satellites, (int, float)) and int(satellites) > 0:
                        if int(satellites) != current_state.satellites_visible:
                            current_state.satellites_visible = int(satellites)
                            changed = True

                    # Update HRMS and VRMS from covariance data (skip zero — stale default)
                    if isinstance(hrms, (int, float)) and float(hrms) > 0:
                        hrms_str = f"{float(hrms):.3f}"
                        if hrms_str != current_state.hrms:
                            current_state.hrms = hrms_str
                            changed = True
                    if isinstance(vrms, (int, float)) and float(vrms) > 0:
                        vrms_str = f"{float(vrms):.3f}"
                        if vrms_str != current_state.vrms:
                            current_state.vrms = vrms_str
                            changed = True

                    # Map velocity from ROS2 'global.vel' into shared groundspeed field
                    try:
                        if isinstance(vel, (int, float)):
                            new_gs = float(vel)
                            if current_state.groundspeed != new_gs:
                                current_state.groundspeed = new_gs
                                changed = True
                    except Exception as e:
                        log_message(f"[_merge_ros2_telemetry] Failed to update groundspeed: {e}", "ERROR")

                # Legacy position format support
                elif isinstance(position, dict):
                    lat = position.get('latitude')
                    lon = position.get('longitude')
                    if (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                            and (float(lat) != 0.0 or float(lon) != 0.0)):
                        current_state.position = Position(lat=float(lat), lng=float(lon))
                        changed = True
                        current_state.last_update = now

                # Process RTK status data (NEW)
                # Skip stale zero values from telemetry_node (QoS mismatch → never receives position)
                if isinstance(rtk, dict):
                    fix_type = rtk.get('fix_type')
                    baseline_age = rtk.get('baseline_age')
                    base_linked = rtk.get('base_linked')

                    if isinstance(fix_type, (int, float)) and int(fix_type) > 0:
                        fix_type_int = int(fix_type)
                        # Map fix type to status string (MAVROS 0-6 range)
                        rtk_status_map = {
                            1: 'No Fix',
                            2: '2D Fix',
                            3: '3D Fix',
                            4: 'DGPS',
                            5: 'RTK Float',
                            6: 'RTK Fixed'
                        }
                        rtk_status_str = rtk_status_map.get(fix_type_int, 'Unknown')
                        if rtk_status_str != current_state.rtk_status:
                            current_state.rtk_status = rtk_status_str
                            changed = True
                        if fix_type_int != current_state.rtk_fix_type:
                            current_state.rtk_fix_type = fix_type_int
                            changed = True

                    if isinstance(baseline_age, (int, float)) and float(baseline_age) > 0:
                        if baseline_age != current_state.rtk_baseline_age:
                            current_state.rtk_baseline_age = float(baseline_age)
                            changed = True

                    if isinstance(base_linked, bool) and base_linked:
                        if base_linked != current_state.rtk_base_linked:
                            current_state.rtk_base_linked = base_linked
                            changed = True

                # Process battery telemetry if provided via ROS2 bridge (/nrp/telemetry)
                battery = payload.get('battery')
                if isinstance(battery, dict):
                    try:
                        pct = battery.get('percentage')
                        volt = battery.get('voltage')
                        curr = battery.get('current')
                        # Accept either fraction (0.0-1.0) or percent (0-100)
                        if isinstance(pct, (int, float)):
                            if pct > 1:
                                pct_val = float(pct)  # Already percent
                            else:
                                pct_val = float(pct) * 100.0  # Convert fraction to percent
                            if current_state.battery != pct_val:
                                current_state.battery = pct_val
                                changed = True
                        if volt is not None:
                            try:
                                current_state.voltage = float(volt)
                                changed = True
                            except Exception as e:
                                log_message(f"[_merge_ros2_telemetry] Failed to update voltage: {e}", "ERROR")
                        if curr is not None:
                            try:
                                current_state.current = float(curr)
                                changed = True
                            except Exception as e:
                                log_message(f"[_merge_ros2_telemetry] Failed to update current: {e}", "ERROR")
                        if changed:
                            current_state.last_update = now
                    except Exception as e:
                        log_message(f"[_merge_ros2_telemetry] Failed to process battery data: {e}", "ERROR")

                # Process temperature telemetry if provided via ROS2 bridge (/nrp/telemetry)
                temperature = payload.get('temperature')
                if isinstance(temperature, (int, float)):
                    try:
                        if current_state.temperature != temperature:
                            current_state.temperature = float(temperature)
                            changed = True
                            current_state.last_update = now
                            # Debug: log temperature values received from ROS2 telemetry
                            log_message(f"ROS2 telemetry temperature: {temperature}", 'DEBUG', event_type='ros_topic')
                    except Exception as e:
                        log_message(f"[_merge_ros2_telemetry] Failed to update temperature: {e}", "ERROR")
        except Exception as exc:
            log_message(f"Failed to merge ROS2 telemetry: {exc}", "WARNING", event_type='ros_topic')
            return

        if changed:
            try:
                schedule_fast_emit()
            except NameError as e:
                log_message(f"schedule_fast_emit not available: {e}", "WARNING")
                # Fallback: emit directly
                emit_rover_data_now(reason='ros2_telemetry')

    class TelemetryBridge(Node):  # type: ignore[misc]
        def __init__(self):
            super().__init__('telemetry_bridge')
            self.subscription = self.create_subscription(
                String,
                '/nrp/telemetry',
                self.telemetry_callback,
                10
            )

        def telemetry_callback(self, msg):
            global _last_telemetry_activity_log
            try:
                telemetry_data = json.loads(msg.data)
                _merge_ros2_telemetry(telemetry_data)
                    
                now = time.time()
                if now - _last_telemetry_activity_log >= TELEMETRY_ACTIVITY_INTERVAL:
                    record_activity(
                        "Forwarded telemetry update to frontend",
                        level='DEBUG',
                        event_type='ros_topic',
                        meta={
                            'topic': '/nrp/telemetry',
                            'field_count': len(telemetry_data) if isinstance(telemetry_data, dict) else None,
                            'fields': sorted(list(telemetry_data.keys()))[:10] if isinstance(telemetry_data, dict) else None,
                        }
                    )
                    _last_telemetry_activity_log = now
            except Exception as e:
                log_message(f"Error processing telemetry: {e}", "ERROR", event_type='ros_topic')

    class CommandBridge(Node):  # type: ignore[misc]
        def __init__(self):
            if CommandBool is None or SetMode is None:
                raise RuntimeError("mavros_msgs.srv not available; CommandBridge disabled")
            super().__init__('command_bridge')
            self._lock = threading.Lock()
            self._set_mode_client = self.create_client(SetMode, '/mavros/set_mode')
            self._arm_client = self.create_client(CommandBool, '/mavros/cmd/arming')

        def _call_service(self, client, request, timeout: float) -> object:
            if client is None:
                raise RuntimeError("ROS2 client is not initialized")

            service_name = getattr(client, 'srv_name', 'unknown service')

            with self._lock:
                if not client.wait_for_service(timeout_sec=timeout):
                    raise TimeoutError(f"Service {service_name} not available")

                future = client.call_async(request)

            deadline = time.time() + max(timeout, 0.1)
            while time.time() < deadline:
                if future.done():
                    result = future.result()
                    if result is not None:
                        return result
                    exc = future.exception()
                    if exc:
                        raise exc
                    raise RuntimeError("Service call returned no result")
                time.sleep(0.01)

            raise TimeoutError(f"Service {service_name} timed out")

        def set_mode(self, *, mode: str, base_mode: int = 0, timeout: float = 5.0) -> dict:
            request = SetMode.Request()
            request.base_mode = int(base_mode)
            request.custom_mode = str(mode)
            response = self._call_service(self._set_mode_client, request, timeout)
            return {
                'success': bool(getattr(response, 'success', False)),
                'mode_sent': bool(getattr(response, 'mode_sent', False)),
            }

        def arm(self, *, value: bool, timeout: float = 5.0) -> dict:
            request = CommandBool.Request()
            request.value = bool(value)
            response = self._call_service(self._arm_client, request, timeout)
            return {
                'success': bool(getattr(response, 'success', False)),
                'result': bool(getattr(response, 'result', False)),
            }

    # Initialize ROS2 bridge (guard against multiple init calls)
    try:
        # Force initialization with try/except for duplicate init
        rclpy.init()
        logger.info("ROS2 context initialized successfully")
    except RuntimeError as exc:
        # Any RuntimeError from rclpy.init() is non-fatal — context may already
        # exist, or there may be a signal-handler conflict.  Log and continue.
        logger.warning(f"rclpy.init() RuntimeError (continuing): {exc}")
    telemetry_bridge = TelemetryBridge()
    try:
        command_bridge = CommandBridge()
    except Exception as exc:
        logger.warning(f"Failed to initialize CommandBridge: {exc}")
        command_bridge = None

    _ros_executor = MultiThreadedExecutor()
    _ros_executor.add_node(telemetry_bridge)
    if command_bridge is not None:
        _ros_executor.add_node(command_bridge)

    def _ros_executor_spin() -> None:
        """Run the ROS executor until shutdown, ignoring Ctrl-C noise."""
        try:
            _ros_executor.spin()  # type: ignore[union-attr]
        except KeyboardInterrupt:
            # Suppress noisy stack traces when the process is interrupted.
            pass
        except Exception as exc:
            logger.error(f"[ROS] executor thread error: {exc}")

    ros_thread = threading.Thread(target=_ros_executor_spin)
    ros_thread.daemon = True
    ros_thread.start()
else:

    class CommandBridge:  # type: ignore[no-redef]
        """ROS2 disabled placeholder to keep type-checkers satisfied."""

        def __init__(self):
            raise RuntimeError("ROS2 stack not available")


_ros_shutdown_lock = threading.Lock()
_ros_shutdown_done = False


def _shutdown_ros_runtime() -> None:
    """Best-effort cleanup for ROS resources when the process exits."""
    global _ros_shutdown_done, mission_controller
    with _ros_shutdown_lock:
        if _ros_shutdown_done:
            return
        _ros_shutdown_done = True
    
    logger.info("_shutdown_ros_runtime() called - cleaning up ROS resources")
    import traceback
    traceback.print_stack()  # Show who called shutdown

    # Cleanup LED controller
    try:
        if led_controller is not None:
            logger.info("Shutting down LED controller")
            led_controller.shutdown()
    except Exception as exc:
        logger.warning(f"LED controller cleanup failed: {exc}")

    # Cleanup mission controller first
    try:
        if mission_controller is not None:
            logger.info("Shutting down integrated mission controller")
            mission_controller.shutdown()
            mission_controller = None
    except Exception as exc:
        logger.warning(f"Mission controller cleanup failed: {exc}")

    # Shutdown TTS worker thread
    try:
        logger.info("Shutting down TTS worker")
        tts.shutdown()
    except Exception as exc:
        logger.warning(f"TTS shutdown failed: {exc}")

    try:
        if _ros_executor is not None:
            _ros_executor.shutdown()
    except Exception:
        pass

    try:
        if ros_thread is not None and ros_thread.is_alive() and threading.current_thread() is not ros_thread:
            ros_thread.join(timeout=2.0)
    except Exception:
        pass

    try:
        if _ros_executor is not None and telemetry_bridge is not None:
            _ros_executor.remove_node(telemetry_bridge)
    except Exception:
        pass
    try:
        if telemetry_bridge is not None:
            telemetry_bridge.destroy_node()
    except Exception:
        pass

    if command_bridge is not None:
        try:
            if _ros_executor is not None:
                _ros_executor.remove_node(command_bridge)
        except Exception:
            pass
        try:
            command_bridge.destroy_node()
        except Exception:
            pass

    try:
        if mavros_bridge is not None:
            mavros_bridge.close()
    except Exception:
        pass

    try:
        if ROS_AVAILABLE and rclpy is not None:
            logger.info("Calling rclpy.shutdown()")
            rclpy.shutdown()
    except Exception as exc:
        logger.warning(f"rclpy.shutdown() failed: {exc}")

    if fcntl is not None:
        global _singleton_lock_handle
        if _singleton_lock_handle is not None:
            try:
                fcntl.flock(_singleton_lock_handle, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                _singleton_lock_handle.close()
            except Exception:
                pass
            _singleton_lock_handle = None


os.environ["MAVROS_BRIDGE_HOST"] = "127.0.0.1"    # Local MAVROS instance
os.environ["MAVROS_BRIDGE_PORT"] = "9090"         # rosbridge_server WebSocket port
os.environ["MAVROS_FCU_URL"] = "/dev/ttyUSB0:115200"  # Rover connection parameters


# --- MAVROS Connection ---
mavros_bridge: Optional[MavrosBridge] = None
is_vehicle_connected = False
current_mission = []  # Store current mission waypoints
mavros_bridge_lock = threading.Lock()
mavros_telem_lock = threading.Lock()
mavros_connection_last_attempt = 0.0
_mavros_last_connect_log = 0.0  # Throttle reconnection log messages
_MAVROS_LOG_INTERVAL = 30.0     # Only log reconnection attempts every 30s
# Battery low warning tracking (edge-triggered thresholds)
_battery_warned_20 = False  # warned at 20%
_battery_warned_10 = False  # warned at 10%

# --- Integrated Mission Controller ---
mission_controller: Optional[IntegratedMissionController] = None
latest_mission_status: dict = {}

# --- LED Controller ---
try:
    led_controller = LEDController()
except Exception as e:
    logger.warning(f"LED controller init failed: {e}")
    led_controller = None

# Track LED controller enabled state
led_enabled = True

# System settings loaded from config
system_settings = {}

# PHASE 2 FIX: Status history cache for frontend reconnection
# Store last 10 mission status messages
mission_status_history: deque = deque(maxlen=10)

# --- Manual Control Handler ---
manual_control_handler: Optional[ManualControlHandler] = None

 

@dataclass
class Position:
    lat: float
    lng: float


@dataclass
class CurrentState:
    # Will be set when GPS available
    position: Optional[Position] = None
    heading: float = 0.0
    
    battery: int = -1
    voltage: float = 0.0  # Battery voltage (V)
    current: float = 0.0  # Battery current (A)
    status: str = 'disarmed'
    mode: str = 'UNKNOWN'
    rtk_status: str = 'No GPS'
    signal_strength: str = 'No Link'
    current_waypoint_id: Optional[int] = None
    rc_connected: bool = False
    last_heartbeat: Optional[float] = None
    # UI expected fields
    hrms: str = '0.000'
    vrms: str = '0.000'
    imu_status: str = 'UNALIGNED'
    imu: Optional[dict] = None
    satellites_visible: int = 0
    activeWaypointIndex: Optional[int] = None
    completedWaypointIds: List[int] = field(default_factory=list)
    distanceToNext: float = 0.0
    # Servo output telemetry (PWM values from /mavros/rc/out)
    servo_output: Optional[dict] = None
    # Ground speed (m/s) as derived from MAVROS velocity or ROS2 telemetry
    groundspeed: float = 0.0
    # IMU temperature (°C)
    temperature: float = 0.0
    # RTK detailed status (for frontend RTKPanel)
    rtk_fix_type: int = 0
    rtk_baseline_age: float = 0.0
    rtk_base_linked: bool = False
    # Raw RTK baseline payload (from /mavros/gps_rtk/rtk_baseline)
    rtk_baseline: Optional[dict] = None
    # Timestamp (seconds since epoch) when last baseline was received
    rtk_baseline_ts: Optional[float] = None
    # Timestamp pushed to frontend (seconds since epoch)
    last_update: Optional[float] = None
    # GPS Failsafe state fields
    gps_failsafe_mode: str = "disable"  # "disable", "strict", or "relax"
    gps_failsafe_triggered: bool = False  # Whether failsafe has been triggered
    gps_failsafe_accuracy_error_mm: float = 0.0  # Accuracy error in mm
    gps_failsafe_servo_suppressed: bool = False  # Whether servo commands are suppressed

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# Initialize current vehicle state
current_state = CurrentState()

# Initialize network monitor for WiFi and LoRa status telemetry
# Cache duration of 3 seconds to avoid overhead in high-frequency telemetry loop
network_monitor = NetworkMonitor(interface="wlan0", cache_duration=3.0)

mission_upload_lock = threading.Lock()
mission_download_lock = threading.Lock()

# Real-time streaming throttle configuration
def _compute_emit_interval() -> float:
    try:
        min_ms_env = os.getenv('TELEMETRY_MIN_MS')
        if min_ms_env is not None:
            min_ms = max(1.0, float(min_ms_env))
            return max(0.001, min_ms / 1000.0)
        hz = float(os.getenv('TELEMETRY_HZ', '20'))
        return max(0.001, 1.0 / max(1.0, hz))
    except Exception:
        return 0.05  # ~20Hz


EMIT_MIN_INTERVAL = _compute_emit_interval()
last_emit_monotonic = 0.0
_emit_lock = threading.Lock()
_emit_timer: Optional[object] = None

MISSION_LOG_HISTORY_MAX = 1000
mission_log_history: deque[dict] = deque(maxlen=MISSION_LOG_HISTORY_MAX)
mission_log_state = {
    'last_active_seq': None,
    'last_reached_seq': None,
}

ACTIVITY_LOG_MAX = int(os.getenv('ACTIVITY_LOG_MAX', '2000'))
activity_log: deque[dict] = deque(maxlen=ACTIVITY_LOG_MAX)
_activity_log_lock = threading.Lock()
_activity_seq = count(1)
TELEMETRY_ACTIVITY_INTERVAL = float(os.getenv('TELEMETRY_ACTIVITY_INTERVAL', '5.0'))
_last_telemetry_activity_log: float = 0.0

# RTK TTS cooldown — prevents oscillation between fix_type 5↔6 from spamming voice
_rtk_announced_state: str = "none"   # "acquired", "float", "gps_only", "none"
_rtk_announce_time: float = 0.0
_RTK_ANNOUNCE_COOLDOWN_SEC: float = 12.0

# HTTP response tracking log
_response_log: list[dict] = []

def _make_json_safe(obj, depth: int = 2):
    """Return a JSON-serialisable version of obj, truncating deeply nested data."""
    try:
        if depth < 0:
            return str(obj)
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            limited = {}
            for idx, (key, value) in enumerate(obj.items()):
                if idx >= 15:
                    limited["..."] = f"+{len(obj) - idx} more"
                    break
                limited[str(key)] = _make_json_safe(value, depth - 1)
            return limited
        if isinstance(obj, (list, tuple, set)):
            seq = list(obj)
            limited = [_make_json_safe(value, depth - 1) for value in seq[:15]]
            if len(seq) > 15:
                limited.append(f"... (+{len(seq) - 15} more)")
            return limited
        return json.loads(json.dumps(obj))
    except Exception:
        return str(obj)

def record_activity(message: str, *, level: str = 'INFO', event_type: str = 'general', meta: dict | list | str | int | float | None = None):
    """Store and broadcast backend activity events."""
    timestamp = time.time()
    entry = {
        'id': next(_activity_seq),
        'timestamp': timestamp,
        'isoTime': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(timestamp)),
        'level': str(level),
        'event': str(event_type),
        'message': str(message),
        'meta': _make_json_safe(meta),
    }
    try:
        with _activity_log_lock:
            activity_log.append(entry)
    except Exception as e:
        log_message(f"[record_activity] Failed to append to activity log: {e}", "ERROR")
    try:
        sync_emit('server_activity', entry)
    except Exception:
        pass
    return entry

COMMAND_ID_TO_NAME = {
    mavlink.MAV_CMD_COMPONENT_ARM_DISARM: 'ARM_DISARM',
    mavlink.MAV_CMD_DO_SET_MODE: 'SET_MODE',
}

COMMAND_NAME_TO_ID = {
    'WAYPOINT': mavlink.MAV_CMD_NAV_WAYPOINT,
    'NAV_WAYPOINT': mavlink.MAV_CMD_NAV_WAYPOINT,
    'TAKEOFF': mavlink.MAV_CMD_NAV_TAKEOFF,
    'NAV_TAKEOFF': mavlink.MAV_CMD_NAV_TAKEOFF,
    'LAND': mavlink.MAV_CMD_NAV_LAND,
    'NAV_LAND': mavlink.MAV_CMD_NAV_LAND,
    'SPLINE_WAYPOINT': mavlink.MAV_CMD_NAV_SPLINE_WAYPOINT,
    'DO_SET_SERVO': mavlink.MAV_CMD_DO_SET_SERVO,
    'DO_CHANGE_SPEED': mavlink.MAV_CMD_DO_CHANGE_SPEED,
    'DO_SET_HOME': mavlink.MAV_CMD_DO_SET_HOME,
    # 🔵 ADDED: wait N seconds before continuing (used for spray duration)
    'CONDITION_DELAY': mavlink.MAV_CMD_CONDITION_DELAY,
}

# Mode mappings
COPTER_MODES = {
    0: 'STABILIZE', 1: 'ACRO', 2: 'ALT_HOLD', 3: 'AUTO', 4: 'GUIDED',
    5: 'LOITER', 6: 'RTL', 7: 'CIRCLE', 9: 'LAND', 11: 'DRIFT',
    13: 'SPORT', 14: 'FLIP', 15: 'AUTOTUNE', 16: 'POSHOLD', 17: 'BRAKE',
    18: 'THROW', 19: 'AVOID_ADSB', 20: 'GUIDED_NOGPS', 21: 'SMART_RTL',
    22: 'FLOWHOLD', 23: 'FOLLOW', 24: 'ZIGZAG', 25: 'SYSTEMID', 26: 'AUTOROTATE'
}

ROVER_MODES = {
    0: 'MANUAL', 1: 'ACRO', 3: 'STEERING', 4: 'HOLD', 10: 'AUTO',
    11: 'RTL', 12: 'SMART_RTL', 15: 'GUIDED', 16: 'INITIALISING'
}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def _current_position() -> tuple[float | None, float | None]:
    try:
        if current_state and current_state.position:
            return current_state.position.lat, current_state.position.lng
    except Exception as e:
        log_message(f"[_current_position] Failed to get position: {e}", "ERROR")
    return None, None


def _record_mission_event(
    message: str,
    *,
    status: str | None = None,
    waypoint_id: int | None = None,
    servo_action: str | None = None
) -> None:
    lat, lng = _current_position()
    entry = {
        'timestamp': time.time(),
        'message': message,
        'status': status,
        'waypointId': waypoint_id,
        'servoAction': servo_action,
        'lat': lat,
        'lng': lng,
    }
    mission_log_history.append(entry)
    try:
        sync_emit('mission_event', entry)
    except Exception:
        pass


def safe_float(value, default=0.0) -> float:
    """Best-effort float conversion with fallback."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)




# ============================================================
# SERVO CONTROL MISSION BUILDER (3 modes)
# ============================================================

def _is_nav_waypoint(cmd_name_or_id) -> bool:
    cid = resolve_mav_command(cmd_name_or_id)
    return command_requires_nav_coordinates(cid)

def _mk_do_set_servo(channel: int, pwm: float) -> dict:
    # DO_SET_SERVO uses param1=servo no, param2=PWM. No coordinates required.
    return {
        'command': 'DO_SET_SERVO',
        'param1': float(channel),
        'param2': float(pwm),
        'param3': 0.0,
        'param4': 0.0,
        'lat': 0.0, 'lng': 0.0, 'alt': 0.0,
        'frame': mavlink.MAV_FRAME_MISSION
    }

def _mk_condition_delay(seconds: float) -> dict:
    # Wait N seconds before proceeding
    return {
        'command': 'CONDITION_DELAY',
        'param1': float(seconds),
        'param2': 0.0, 'param3': 0.0, 'param4': 0.0,
        'lat': 0.0, 'lng': 0.0, 'alt': 0.0,
        'frame': mavlink.MAV_FRAME_MISSION
    }

def _mk_nav_wp(lat: float, lng: float, alt: float, frame: int = mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT) -> dict:
    return {
        'command': 'WAYPOINT',
        'lat': float(lat), 'lng': float(lng), 'alt': float(alt),
        'frame': int(frame),
        'param1': 0.0, 'param2': 0.0, 'param3': 0.0, 'param4': 0.0
    }

def apply_servo_modes(waypoints: list[dict], servo_config: dict) -> list[dict]:
    """
    Expand mission with DO_SET_SERVO items based on the popup config.
    Modes:
      1) MARK_AT_WAYPOINT: ON -> delay(s) -> OFF after each WP in [fromWp..toWp]
      2) CONTINUOUS_LINE: ON after startPoint, OFF after endPoint
      3) INTERVAL_SPRAY: insert mini-waypoints every intervalCm, toggling ON/OFF
    """
    if not servo_config:
        return waypoints

    mode = str(servo_config.get('mode', '')).upper()
    servo = int(safe_float(servo_config.get('servoNumber', 10), 10))
    pwm_on = float(safe_float(servo_config.get('pwmOn', 650), 650))
    pwm_off = float(safe_float(servo_config.get('pwmOff', 1000), 1000))

    # Helper: iterate original nav WPs with a 1-based index
    def _iter_nav_indexed():
        for idx, wp in enumerate(waypoints, start=1):
            yield (idx, wp)

    # -------------------------
    # Mode 1: MARK_AT_WAYPOINT
    # -------------------------
    if mode == 'MARK_AT_WAYPOINT':
        from_wp = int(safe_float(servo_config.get('fromWp', 1), 1))
        to_wp = int(safe_float(servo_config.get('toWp', len(waypoints)), len(waypoints)))
        dur_s = float(safe_float(servo_config.get('sprayDuration', 0.5), 0.5))

        new_list: list[dict] = []
        for idx, wp in _iter_nav_indexed():
            new_list.append(wp)
            if from_wp <= idx <= to_wp and _is_nav_waypoint(wp.get('command')):
                # ON right after reaching this WP, hold for dur_s, then OFF
                new_list.append(_mk_do_set_servo(servo, pwm_on))
                if dur_s > 0:
                    new_list.append(_mk_condition_delay(dur_s))
                new_list.append(_mk_do_set_servo(servo, pwm_off))
        return new_list

    # -------------------------
    # Mode 2: CONTINUOUS_LINE
    # -------------------------
    if mode == 'CONTINUOUS_LINE':
        start_pt = int(safe_float(servo_config.get('startPoint', 1), 1))
        end_pt = int(safe_float(servo_config.get('endPoint', len(waypoints)), len(waypoints)))
        if end_pt < start_pt:
            end_pt = start_pt

        new_list: list[dict] = []
        for idx, wp in _iter_nav_indexed():
            new_list.append(wp)
            if idx == start_pt and _is_nav_waypoint(wp.get('command')):
                # turn ON immediately after we "arrive" at start WP
                new_list.append(_mk_do_set_servo(servo, pwm_on))
            if idx == end_pt and _is_nav_waypoint(wp.get('command')):
                # turn OFF after end WP
                new_list.append(_mk_do_set_servo(servo, pwm_off))
        return new_list

    # -------------------------
    # Mode 3: INTERVAL_SPRAY
    # -------------------------
    if mode == 'INTERVAL_SPRAY':
        interval_cm = float(safe_float(servo_config.get('intervalCm', 30.0), 30.0))
        step_m = max(0.01, interval_cm / 100.0)  # meters

        # Prepare a new mission with sub-steps between each consecutive NAV WP
        import math
        def haversine_m(lat1, lon1, lat2, lon2):
            # rough distance in meters (good enough for path splitting)
            R = 6371000.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
            return 2 * R * math.asin(min(1, math.sqrt(a)))

        def lerp(a, b, t): return a + (b - a) * t

        # filter only the NAV waypoints (we preserve order and any pre-existing DO_* too)
        # but we build intervals only between NAV->NAV legs
        new_list: list[dict] = []
        toggle_on = True  # alternate ON/OFF per sub-step

        # build a list of indices of NAV waypoints in original list
        nav_indices = [i for i, w in enumerate(waypoints) if _is_nav_waypoint(w.get('command'))]

        for i, wp in enumerate(waypoints):
            new_list.append(wp)

            # if this is a NAV wp and the next NAV wp exists, insert sub-steps after this one
            if i in nav_indices:
                cur_idx_in_nav = nav_indices.index(i)
                if cur_idx_in_nav < len(nav_indices) - 1:
                    a = waypoints[nav_indices[cur_idx_in_nav]]
                    b = waypoints[nav_indices[cur_idx_in_nav + 1]]
                    lat1, lon1, alt1 = float(a.get('lat', 0)), float(a.get('lng', 0)), float(a.get('alt', 0))
                    lat2, lon2, alt2 = float(b.get('lat', 0)), float(b.get('lng', 0)), float(b.get('alt', 0))
                    dist = haversine_m(lat1, lon1, lat2, lon2)
                    steps = int(max(0, math.floor(dist / step_m)))

                    # Insert at each sub-distance: a small NAV WP + a DO_SET_SERVO toggle
                    for s in range(1, steps + 1):
                        t = s / (steps + 1)
                        lat = lerp(lat1, lat2, t)
                        lon = lerp(lon1, lon2, t)
                        alt = lerp(alt1, alt2, t)

                        # go to subpoint
                        new_list.append(_mk_nav_wp(lat, lon, alt))
                        # toggle servo value at this subpoint
                        new_list.append(_mk_do_set_servo(servo, pwm_on if toggle_on else pwm_off))
                        toggle_on = not toggle_on

        return new_list

    # Fallback: unchanged
    return waypoints

def resolve_mav_command(command_value) -> int:
    """Return MAV_CMD integer for mission item."""
    if isinstance(command_value, (int, float)):
        return int(command_value)
    if isinstance(command_value, str):
        normalized = command_value.strip().upper()
        resolved = COMMAND_NAME_TO_ID.get(normalized)
        if resolved is not None:
            return resolved
        log_message(f"Unknown mission command '{command_value}', defaulting to NAV_WAYPOINT", "WARNING")
    return mavlink.MAV_CMD_NAV_WAYPOINT


def command_requires_nav_coordinates(command_id: int) -> bool:
    """True when mission item expects lat/lon/alt."""
    return command_id in {
        mavlink.MAV_CMD_NAV_WAYPOINT,
        mavlink.MAV_CMD_NAV_SPLINE_WAYPOINT,
        mavlink.MAV_CMD_NAV_TAKEOFF,
        mavlink.MAV_CMD_NAV_LAND,
        mavlink.MAV_CMD_NAV_LOITER_TIME,
        mavlink.MAV_CMD_NAV_LOITER_TURNS,
        mavlink.MAV_CMD_NAV_LOITER_UNLIM,
    }


def get_mode_name(mode_num, vehicle_type='ROVER'):
    """Convert mode number to mode name based on vehicle type."""
    if vehicle_type == 'ROVER':
        return ROVER_MODES.get(mode_num, f'UNKNOWN({mode_num})')
    else:
        return COPTER_MODES.get(mode_num, f'UNKNOWN({mode_num})')


def get_mode_number(mode_name, vehicle_type='ROVER'):
    """Convert mode name to mode number based on vehicle type."""
    mode_map = ROVER_MODES if vehicle_type == 'ROVER' else COPTER_MODES
    for num, name in mode_map.items():
        if name == mode_name.upper():
            return num
    return None


def _map_navsat_status(status_code: Optional[int]) -> str:
    """Map sensor_msgs/NavSatStatus codes to human readable text."""
    mapping = {
        None: 'Unknown',
        -1: 'No Fix',
        0: 'GPS Fix',
        1: 'DGPS',
        2: 'RTK Fixed',
        3: 'RTK Float',
    }
    return mapping.get(status_code, f"Status {status_code}")


def _convert_mavros_waypoints_to_ui(waypoints: List[dict]) -> List[dict]:
    """Convert MAVROS waypoint dictionaries into the UI mission format."""
    converted: List[dict] = []
    for idx, wp in enumerate(waypoints or []):
        try:
            cmd = int(wp.get("command", mavlink.MAV_CMD_NAV_WAYPOINT))
        except Exception:
            cmd = mavlink.MAV_CMD_NAV_WAYPOINT
        converted.append({
            "id": idx + 1,
            "command": 'WAYPOINT' if cmd == mavlink.MAV_CMD_NAV_WAYPOINT else COMMAND_ID_TO_NAME.get(cmd, f'COMMAND_{cmd}'),
            "lat": safe_float(wp.get("x_lat", 0.0)),
            "lng": safe_float(wp.get("y_long", 0.0)),
            "alt": safe_float(wp.get("z_alt", 0.0)),
            "frame": int(safe_float(wp.get("frame", mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT),
                                   mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)),
            "param1": safe_float(wp.get("param1", 0.0)),
            "param2": safe_float(wp.get("param2", 0.0)),
            "param3": safe_float(wp.get("param3", 0.0)),
            "param4": safe_float(wp.get("param4", 0.0)),
            "autocontinue": int(safe_float(wp.get("autocontinue", 1), 1)),
        })
    return converted


def _build_mavros_waypoints(waypoints: List[dict]) -> List[dict]:
    """Translate UI waypoint dictionaries into MAVROS Waypoint structures."""
    mavros_waypoints: List[dict] = []
    for idx, wp in enumerate(waypoints):
        command_id = resolve_mav_command(wp.get("command"))
        frame = int(safe_float(wp.get("frame", mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT),
                               mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT))
        autocontinue = bool(safe_float(wp.get("autocontinue", 1), 1))
        param1 = safe_float(wp.get("param1", 0.0))
        param2 = safe_float(wp.get("param2", 0.0))
        param3 = safe_float(wp.get("param3", 0.0))
        param4 = safe_float(wp.get("param4", 0.0))

        # Unified coordinate extraction - always prioritize lat/lng field names for consistency
        # This ensures coordinates are never swapped regardless of command type
        lat = safe_float(wp.get("lat", wp.get("x_lat", 0.0)))
        lon = safe_float(wp.get("lng", wp.get("y_long", 0.0)))
        alt = safe_float(wp.get("alt", wp.get("z_alt", 0.0)))

        mavros_waypoints.append({
            "frame": frame,
            "command": command_id,
            "is_current": idx == 0,
            "autocontinue": autocontinue,
            "param1": param1,
            "param2": param2,
            "param3": param3,
            "param4": param4,
            "x_lat": lat,
            "y_long": lon,
            "z_alt": alt
        })
    return mavros_waypoints


def derive_signal_strength(last_heartbeat: float | None, rc_connected: bool) -> str:
    """Return a human readable link quality label for the UI."""
    if last_heartbeat is None:
        return 'No Link'
    age = time.time() - last_heartbeat
    if age <= 2:
        return 'Excellent' if rc_connected else 'Good'
    if age <= 5:
        return 'Fair'
    if age <= 10:
        return 'Weak'
    return 'Lost'


def _get_vehicle_bridge(*, require_vehicle: bool = True, timeout: float = 5.0) -> MavrosBridge:
    """
    Return a MAVROS bridge, optionally ensuring the rover reports as connected.

    When attempting to arm/disarm the vehicle we may not yet have seen a telemetry
    heartbeat, but the command can still succeed; allowing callers to bypass the
    vehicle connectivity assertion prevents false negatives.
    """
    bridge = _init_mavros_bridge()
    if not bridge.is_connected:
        bridge.connect(timeout=timeout)
    if require_vehicle and not is_vehicle_connected:
        raise RuntimeError("Vehicle not connected")
    return bridge


def handle_mission_status(status_data: dict):
    """Handle mission status updates from integrated controller and emit to frontend"""
    global latest_mission_status, mission_status_history
    try:
        # Store latest status
        latest_mission_status = status_data

        # Add server timestamp
        status_data['server_timestamp'] = time.time()

        # Sync GPS failsafe status into current_state for rover_data emissions
        if 'gps_failsafe_mode' in status_data:
            current_state.gps_failsafe_mode = status_data['gps_failsafe_mode']
        if 'gps_failsafe_triggered' in status_data:
            current_state.gps_failsafe_triggered = bool(status_data.get('gps_failsafe_triggered'))
        if 'gps_failsafe_servo_suppressed' in status_data:
            current_state.gps_failsafe_servo_suppressed = bool(status_data.get('gps_failsafe_servo_suppressed'))
        if 'gps_failsafe_accuracy_error_mm' in status_data:
            current_state.gps_failsafe_accuracy_error_mm = float(status_data.get('gps_failsafe_accuracy_error_mm', 0.0))
        
        # Sync distance to next waypoint from mission controller
        if 'distance_to_next_m' in status_data:
            current_state.distanceToNext = float(status_data.get('distance_to_next_m', 0.0))

        # PHASE 2 FIX: Cache status in history for frontend reconnection
        mission_status_history.append(status_data.copy())

        # Log important updates
        level = status_data.get('level', 'info')
        message = status_data.get('message', '')

        if level == 'error':
            log_message(f"Mission: {message}", "ERROR", event_type='mission')
        elif level == 'warning':
            log_message(f"Mission: {message}", "WARNING", event_type='mission')
        elif level == 'success':
            log_message(f"Mission: {message}", "INFO", event_type='mission')

        # PHASE 2 FIX: Add emission verification logging
        # Log critical mission events to track if they reach frontend
        event_type = status_data.get('event_type')
        if event_type in ['waypoint_reached', 'waypoint_marked']:
            log_message(f"📡 EMITTING {event_type}: WP{status_data.get('current_waypoint')} - {message}", "INFO", event_type='mission')

        # TTS announcements for key mission events (non-blocking)
        # REFACTOR: Event-type driven dispatch (replaces fragile string pattern matching)
        try:
            mission_state = status_data.get('mission_state', '')
            current_wp = status_data.get('current_waypoint', 0)
            total_wp = status_data.get('total_waypoints', 0)
            # FIX: event_type is at top level of status_data (merged from extra_data by emit_status)
            event_type = status_data.get('event_type')
            _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()

            # Dispatch TTS based on structured event_type (primary method)
            if event_type == 'mission_loaded':
                waypoints_count = status_data.get('waypoints_count', total_wp)
                tts_msgs = {
                    "en": f"Mission loaded, {waypoints_count} points",
                    "ta": f"பணி ஏற்றப்பட்டது, {waypoints_count} இலக்குகள்",
                    "hi": f"मिशन लोड हो गया, {waypoints_count} points",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'mission_started':
                tts_msgs = {
                    "en": "Mission started, let's go",
                    "ta": "பணி தொடங்கியது, போகலாம்",
                    "hi": "मिशन शुरू हो गया, चलते हैं",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'waypoint_executing':
                tts_msgs = {
                    "en": f"Heading to target {current_wp} of {total_wp}",
                    "ta": f"இலக்கு{current_wp} க்கு செல்கிறோம், மொத்தம் {total_wp}",
                    "hi": f"लक्ष्य {current_wp} की तरफ जा रहे हैं, कुल {total_wp}",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'waypoint_reached':
                tts_msgs = {
                    "en": f"Target {current_wp} reached",
                    "ta": f"இலக்கு{current_wp} அடையப்பட்டது",
                    "hi": f"लक्ष्य {current_wp} पहुँच गए",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'waypoint_marked':
                marking_status = status_data.get('marking_status', '')
                if marking_status == 'completed':
                    tts_msgs = {
                        "en": f"Target {current_wp} done",
                        "ta": f"இலக்கு{current_wp} முடிந்தது",
                        "hi": f"लक्ष्य {current_wp} पूरा हो गया",
                    }
                    tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                    tts.speak(tts_msg)
                    log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'waypoint_failed':
                failure_reason = status_data.get('failure_reason', 'unknown')
                tts_msgs = {
                    "en": f"Target {current_wp} failed, {failure_reason}",
                    "ta": f"இலக்கு{current_wp} தோல்வி, {failure_reason}",
                    "hi": f"लक्ष्य {current_wp} फेल हो गया, {failure_reason}",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'mission_completed':
                waypoints_completed = status_data.get('waypoints_completed', total_wp)
                mission_duration = status_data.get('mission_duration', 0)
                dur = int(mission_duration)
                if mission_duration > 0:
                    tts_msgs = {
                        "en": f"Mission completed. {waypoints_completed} targets in {dur} seconds",
                        "ta": f"பணி முடிந்தது. {waypoints_completed} இலக்குகள், {dur} விநாடிகள்",
                        "hi": f"मिशन पूरा हुआ. {waypoints_completed} लक्ष्य, {dur} सेकंड में",
                    }
                else:
                    tts_msgs = {
                        "en": f"Mission completed. {waypoints_completed} targets",
                        "ta": f"பணி முடிந்தது. {waypoints_completed} இலக்குகள்",
                        "hi": f"मिशन पूरा हुआ. {waypoints_completed} लक्ष्य",
                    }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'mission_error':
                error_msg = status_data.get('error_message', message)[:50]
                tts_msgs = {
                    "en": f"Error, {error_msg}",
                    "ta": f"பிழை ஏற்பட்டது, {error_msg}",
                    "hi": f"Error आ गया, {error_msg}",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'obstacle_warning':
                dist_cm = status_data.get('obstacle_distance_mm', 0) / 10
                tts_msgs = {
                    "en": f"Object detected, {dist_cm:.0f} centimeters away",
                    "ta": f"பொருள் கண்டறியப்பட்டது, {dist_cm:.0f} சென்டிமீட்டர் தூரத்தில்",
                    "hi": f"Object detect हुआ है, {dist_cm:.0f} centimeters दूर",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            elif event_type == 'obstacle_danger':
                tts_msgs = {
                    "en": "Mission paused, object too close",
                    "ta": "பணி நிறுத்தப்பட்டது, பொருள் மிக அருகில் உள்ளது",
                    "hi": "मिशन रुक गया, object बहुत करीब है",
                }
                tts_msg = tts_msgs.get(_lang, tts_msgs["en"])
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

            # Fallback: Unclassified errors (events without event_type)
            elif level == 'error' and 'Telemetry' not in message and not event_type:
                error_msg = message[:50]
                tts_msg = f"Error: {error_msg}"
                tts.speak(tts_msg)
                log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

        except Exception as e:
            # Silently fail TTS - don't break mission status handling
            logger.warning(f"TTS announcement failed: {e}")

        # Update LED only when enabled
        if led_controller and led_enabled:
            led_controller.update_state(
                status_data.get('mission_state', ''),
                status_data.get('event_type')
            )

        # Emit to frontend via WebSocket
        sync_emit('mission_status', status_data, namespace='/')

        # PHASE 2 FIX: Log emission success for critical events
        if event_type in ['waypoint_reached', 'waypoint_marked']:
            log_message(f"✓ Emission sent to frontend: {event_type}", "DEBUG", event_type='mission')

    except Exception as e:
        log_message(f"Mission status handler error: {e}", "ERROR", event_type='mission')


def initialize_mission_controller():
    """Initialize the integrated mission controller after MAVROS bridge connects"""
    global mission_controller
    try:
        bridge = _init_mavros_bridge()
        mission_controller = IntegratedMissionController(
            mavros_bridge=bridge,
            status_callback=handle_mission_status,
            logger=None
        )
        # Apply loaded GPS failsafe mode from config
        mission_controller.set_failsafe_mode(current_state.gps_failsafe_mode)
        log_message(f"Integrated mission controller initialized with GPS failsafe: {current_state.gps_failsafe_mode}", "SUCCESS", event_type='mission')

        # Apply loaded obstacle detection state from config
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            obstacle_enabled = config.get('system_settings', {}).get('obstacle_detection_enabled', False)
            mission_controller.set_obstacle_detection(obstacle_enabled)
            log_message(f"Applied obstacle detection from config: {obstacle_enabled}", "INFO", event_type='mission')
        except Exception as e:
            log_message(f"Failed to load obstacle detection config: {e}", "WARNING", event_type='mission')
        
        # Load LED enabled state from config
        global led_enabled
        led_enabled = system_settings.get("led_enabled", True)
        log_message(f"Loaded LED enabled state: {led_enabled}", "INFO", event_type="led")
        
        # Apply startup LED state
        if led_controller and not led_enabled:
            led_controller._send_off()
        
        return True
    except Exception as e:
        log_message(f"Failed to initialize mission controller: {e}", "ERROR", event_type='mission')
        return False


def initialize_manual_control_handler():
    """Initialize the manual control handler after MAVROS bridge connects"""
    global manual_control_handler
    try:
        bridge = _init_mavros_bridge()
        manual_control_handler = ManualControlHandler(
            mavros_bridge=bridge,
            logger=log_message
        )
        log_message("Manual control handler initialized successfully", "SUCCESS", event_type='manual_control')
        return True
    except Exception as e:
        log_message(f"Failed to initialize manual control handler: {e}", "WARNING", event_type='manual_control')
        return False


def _require_vehicle_bridge() -> MavrosBridge:
    """Backward-compatible helper enforcing a connected vehicle."""
    return _get_vehicle_bridge(require_vehicle=True)


@contextmanager
def _suppress_disconnect_during_bridge_call():
    """Suppress telemetry-timeout disconnect detection while a blocking bridge call runs.

    Without this, long-running ROS service calls (push_waypoints, arm, set_mode)
    can stall telemetry for >20s, causing a false disconnect detection in
    maintain_mavros_connection().  The IntegratedMissionController already uses
    bridge.suppress_disconnect_check() — this brings the same protection to
    REST API handlers.
    """
    bridge = mavros_bridge
    if bridge is None:
        yield
        return
    bridge.suppress_disconnect_check(True)
    try:
        yield
    finally:
        bridge.suppress_disconnect_check(False)


# ============================================================================
# TELEMETRY EMISSION
# ============================================================================

def emit_rover_data_now(reason: str | None = None) -> None:
    """Emit current_state to all clients with throttling bookkeeping."""
    global last_emit_monotonic
    data = get_rover_data()
    
    # DEBUG: Log position data being sent to frontend
    if data.get('position'):
        pos = data['position']
        logger.debug(f"Sending rover_data ({reason}): position={pos}")
    else:
        logger.debug(f"Sending rover_data ({reason}): NO POSITION DATA")
    
    try:
        sync_emit('rover_data', data)
        if reason:
            log_message(f"rover_data emitted ({reason}) @ {time.strftime('%H:%M:%S')}", 'DEBUG')
    finally:
        last_emit_monotonic = time.monotonic()


def _emit_timer_cb():
    global _emit_timer
    with _emit_lock:
        _emit_timer = None
    emit_rover_data_now(reason='throttled')


def schedule_fast_emit():
    """Emit at most EMIT_MIN_INTERVAL; schedule deferred emit if needed.

    IMPORTANT: This function is called from the roslibpy WebSocket callback
    thread (via _handle_mavros_telemetry).  emit_rover_data_now() runs
    get_rover_data() which invokes subprocess calls (network_monitor).
    We must NEVER call it inline — always marshal to the asyncio event loop
    or a daemon thread so the roslibpy thread returns immediately.
    """
    global _emit_timer
    loop = _main_loop
    now = time.monotonic()
    elapsed = now - last_emit_monotonic
    if elapsed >= EMIT_MIN_INTERVAL:
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(emit_rover_data_now, 'realtime')
        else:
            threading.Thread(target=emit_rover_data_now, args=('realtime',), daemon=True).start()
        return
    delay = EMIT_MIN_INTERVAL - elapsed
    with _emit_lock:
        if _emit_timer is None:
            # Set sentinel immediately to prevent duplicate scheduling
            _emit_timer = True
            try:
                loop.call_soon_threadsafe(loop.call_later, delay, _emit_timer_cb)
            except Exception:
                _emit_timer = None
                threading.Thread(target=emit_rover_data_now, args=('realtime',), daemon=True).start()


def get_rover_data():
    """Return complete rover data structure with all required fields."""
    try:
        with mavros_telem_lock:
            current_state.signal_strength = derive_signal_strength(
                current_state.last_heartbeat, current_state.rc_connected
            )
    except Exception as e:
        log_message(f"[get_rover_data] Failed to derive signal strength: {e}", "ERROR")

    data = current_state.to_dict()
    
    # Add network telemetry (WiFi signal strength and LoRa status)
    try:
        network_data = network_monitor.get_network_data()
        data['network'] = network_data
    except Exception as e:
        # Provide safe defaults on network monitoring failure
        logger.warning(f"Network monitoring error: {e}")
        data['network'] = {
            'connection_type': 'none',
            'wifi_signal_strength': 0,
            'wifi_rssi': -100,
            'interface': 'unknown',
            'wifi_connected': False,
            'lora_connected': False
        }

    # Add manual control status
    if manual_control_handler:
        data['manual_control'] = manual_control_handler.get_status()
    else:
        data['manual_control'] = {'active': False}

    # Compute baseline age dynamically from last baseline timestamp if available
    try:
        with mavros_telem_lock:
            if getattr(current_state, 'rtk_baseline_ts', None) is not None:
                age = time.time() - float(current_state.rtk_baseline_ts)
                current_state.rtk_baseline_age = float(age)
                data['rtk_baseline_age'] = float(age)
    except Exception as e:
        log_message(f"[get_rover_data] Failed to compute baseline age: {e}", "ERROR")

    # Add mission controller status to telemetry
    # FIX: Frontend MissionControlCard needs telemetry.mission.status to be lowercase "running", "paused", etc.
    global mission_controller
    if mission_controller:
        try:
            mission_status = mission_controller.get_status()
            # mission_state is a MissionState enum value like 'running', 'idle', 'paused'
            state = mission_status.get('mission_state', 'idle')
            current_wp = mission_status.get('current_waypoint', 0)
            total_wp = mission_status.get('total_waypoints', 0)

            data['mission'] = {
                'status': str(state).lower(),  # Ensure lowercase for frontend
                'current_wp': current_wp,
                'total_wp': total_wp,
                'progress_pct': (current_wp / max(1, total_wp)) * 100.0 if total_wp > 0 else 0.0
            }
        except Exception as e:
            logger.warning(f"Failed to get mission status for telemetry: {e}")
            data['mission'] = {'status': 'idle', 'current_wp': 0, 'total_wp': 0, 'progress_pct': 0.0}
    else:
        data['mission'] = {'status': 'idle', 'current_wp': 0, 'total_wp': 0, 'progress_pct': 0.0}

    # Debug: Log RTK fix type being sent
    logger.debug(f"get_rover_data() sending rtk_fix_type={current_state.rtk_fix_type}, rtk_base_linked={current_state.rtk_base_linked}, rtk_baseline_age={current_state.rtk_baseline_age}")
    
    return data


# ============================================================================
# MAVLINK CONNECTION & MESSAGE PROCESSING
# ============================================================================

def _init_mavros_bridge() -> MavrosBridge:
    """Ensure a single MavrosBridge instance and attach telemetry subscriptions."""
    global mavros_bridge
    with mavros_bridge_lock:
        if mavros_bridge is None:
            log_message("Creating MAVROS bridge instance")
            mavros_bridge = MavrosBridge()
            mavros_bridge.subscribe_telemetry(_handle_mavros_telemetry)
    return mavros_bridge


async def maintain_mavros_connection():
    """Establish and monitor the MAVROS bridge connection."""
    global is_vehicle_connected, mavros_connection_last_attempt, mission_controller, manual_control_handler
    global _mavros_last_connect_log
    while True:
        try:
            bridge = _init_mavros_bridge()
            if bridge.is_connected:
                # Check if Pixhawk disconnection or MAVROS crash was detected
                if bridge.is_pixhawk_disconnect_detected():
                    telem_age = time.time() - bridge._last_telemetry_time
                    suppressed = bridge._suppress_disconnect_check
                    log_message(
                        f"MAVROS telemetry loss detected — telemetry_age={telem_age:.1f}s, "
                        f"suppress={suppressed}, connected={bridge._connected}. "
                        f"Closing bridge and attempting graceful reconnection.",
                        "ERROR",
                    )
                    bridge.clear_disconnect_flag()
                    bridge.close()
                    is_vehicle_connected = False
                    # Safely shutdown mission controller before clearing reference
                    _mc = mission_controller
                    mission_controller = None  # Reset so it re-initialises after reconnect
                    if _mc is not None:
                        try:
                            _mc.shutdown()
                        except Exception:
                            pass
                    sync_emit('connection_status', {
                        'status': 'WAITING_FOR_ROVER',
                        'message': 'MAVROS telemetry lost - reconnecting...'
                    })
                    # Give rosbridge a moment to stabilise before reconnecting
                    await asyncio.sleep(3.0)
                    continue  # Skip to reconnection attempt

                # Initialize mission controller if not already done and bridge is connected
                if mission_controller is None:
                    initialize_mission_controller()
                # Initialize manual control handler if not already done
                if manual_control_handler is None:
                    initialize_manual_control_handler()
                await asyncio.sleep(2.0)
                continue

            now = time.time()
            if now - mavros_connection_last_attempt < 1.0:
                await asyncio.sleep(1.0)
                continue

            mavros_connection_last_attempt = now
            _now_log = time.time()
            _should_log = (_now_log - _mavros_last_connect_log) >= _MAVROS_LOG_INTERVAL
            if _should_log:
                log_message(f"Attempting MAVROS connection to {bridge.host}:{bridge.port}")
            bridge.connect(timeout=float(os.getenv("MAVROS_CONNECT_TIMEOUT", "10")))
            if _should_log:
                _mavros_last_connect_log = _now_log
                log_message("MAVROS bridge connected to rosbridge", "SUCCESS")

            # Initialize mission controller after successful connection
            if mission_controller is None:
                initialize_mission_controller()

            # Initialize manual control handler after successful connection
            if manual_control_handler is None:
                initialize_manual_control_handler()

        except Exception as exc:
            if is_vehicle_connected:
                is_vehicle_connected = False
                log_message("Vehicle connection lost via MAVROS", "ERROR")
                sync_emit('connection_status', {
                    'status': 'WAITING_FOR_ROVER',
                    'message': str(exc)
                })
            log_message(f"MAVROS connection error: {exc}", "ERROR")
            await asyncio.sleep(2.0)
        await asyncio.sleep(2.0)


def _handle_mavros_telemetry(message: dict) -> None:
    """Translate MAVROS telemetry payloads into the shared rover state."""
    global is_vehicle_connected, current_mission
    msg_type = str(message.get("type", "")).lower()

    try:
        if msg_type == "state":
            connected = bool(message.get("connected", False))
            armed = bool(message.get("armed", False))
            mode = str(message.get("mode", "UNKNOWN")).upper()
            previous = is_vehicle_connected
            is_vehicle_connected = connected

            with mavros_telem_lock:
                prev_armed = current_state.status
                current_state.status = "armed" if armed else "disarmed"
                current_state.mode = mode
                current_state.last_heartbeat = time.time() if connected else None
                current_state.signal_strength = derive_signal_strength(
                    current_state.last_heartbeat,
                    current_state.rc_connected
                )
                current_state.last_update = time.time()

            if connected and not previous:
                log_message("Vehicle connected through MAVROS", "SUCCESS")
                sync_emit('connection_status', {'status': 'CONNECTED_TO_ROVER'})
                # Voice: Rover initialised greeting with time-of-day
                try:
                    _hour = datetime.now().hour
                    if _hour < 12:
                        _greeting = {"en": "Good morning", "ta": "காலை வணக்கம்", "hi": "सुप्रभात"}
                    elif _hour < 17:
                        _greeting = {"en": "Good afternoon", "ta": "மதிய வணக்கம்", "hi": "नमस्कार"}
                    else:
                        _greeting = {"en": "Good evening", "ta": "மாலை வணக்கம்", "hi": "शुभ संध्या"}
                    _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
                    _greet = _greeting.get(_lang, _greeting["en"])
                    _init_msgs = {
                        "en": f"Way to Mark initialised. {_greet}!",
                        "ta": f"வே டு மார்க் தொடங்கப்பட்டது. {_greet}!",
                        "hi": f"वे टू मार्क शुरू हो गया. {_greet}!",
                    }
                    tts.speak(_init_msgs.get(_lang, _init_msgs["en"]))
                    logger.debug(f"TTS: {_init_msgs.get(_lang, _init_msgs['en'])}")
                except Exception:
                    pass
            elif not connected and previous:
                log_message("Vehicle disconnected from MAVROS", "WARNING")
                sync_emit('connection_status', {'status': 'WAITING_FOR_ROVER'})
                # Voice: Only announce connection lost during active mission
                try:
                    if mission_controller and mission_controller.mission_state.value in ("running", "paused"):
                        _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
                        _dc_msgs = {"en": "Warning! Vehicle connection lost.", "ta": "எச்சரிக்கை! வாகன இணைப்பு துண்டிக்கப்பட்டது.", "hi": "चेतावनी! वाहन कनेक्शन टूट गया."}
                        tts.speak(_dc_msgs.get(_lang, _dc_msgs["en"]))
                        logger.debug(f"TTS: {_dc_msgs.get(_lang, _dc_msgs['en'])}")
                except Exception:
                    pass

            schedule_fast_emit()

        elif msg_type == "navsat":
            lat = message.get("latitude")
            lon = message.get("longitude")
            alt = message.get("altitude", 0.0)

            # DEBUG: Log navsat message reception
            logger.debug(f"Received navsat: lat={lat}, lon={lon}, alt={alt}")

            if lat is not None and lon is not None:
                with mavros_telem_lock:
                    current_state.position = Position(lat=float(lat), lng=float(lon))
                    current_state.last_update = time.time()
                    # Note: distanceToNext should be populated from mission controller, not altitude
                    logger.debug(f"Updated current_state.position: lat={current_state.position.lat:.7f}, lng={current_state.position.lng:.7f}")
                schedule_fast_emit()

        elif msg_type == "gps_fix":
            # Handle GPS fix quality information from MAVROS bridge (gps1/raw)
            # This provides fix_type and satellites_visible (accurate values)
            with mavros_telem_lock:
                # Update RTK status and fix type
                rtk_status = message.get("rtk_status")
                fix_type = message.get("fix_type")
                satellites_visible = message.get("satellites_visible")

                if rtk_status is not None and current_state.rtk_status != rtk_status:
                    current_state.rtk_status = rtk_status
                    current_state.last_update = time.time()

                if isinstance(fix_type, int) and current_state.rtk_fix_type != fix_type:
                    prev_fix = current_state.rtk_fix_type
                    current_state.rtk_fix_type = fix_type
                    current_state.last_update = time.time()
                    # Voice: RTK status change with cooldown to prevent oscillation spam.
                    # GPS fix_type can oscillate rapidly (5↔6↔5↔6) triggering alternating
                    # "acquired"/"lost" messages every second. We map fix_type to a coarse
                    # state category and only announce when the category changes AND the
                    # cooldown has elapsed.
                    try:
                        global _rtk_announced_state, _rtk_announce_time
                        _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
                        _now = time.time()

                        # Map fix_type to a coarse announcement category
                        if fix_type == 6:
                            _new_rtk_state = "acquired"
                        elif fix_type == 5:
                            _new_rtk_state = "float"
                        else:
                            _new_rtk_state = "gps_only"

                        _cooldown_ok = (_now - _rtk_announce_time) >= _RTK_ANNOUNCE_COOLDOWN_SEC
                        _state_changed = _new_rtk_state != _rtk_announced_state

                        if _state_changed and _cooldown_ok:
                            if _new_rtk_state == "acquired":
                                _rtk_msgs = {
                                    "en": "RTK fix! acquired. Centimeter accuracy active.",
                                    "ta": "ஆர்.டி.கே! சரி. சென்டிமீட்டர் துல்லியம் செயலில்.",
                                    "hi": "RTK फिक्स! मिल गया. सेंटीमीटर सटीकता सक्रिय.",
                                }
                            elif _new_rtk_state == "float" and _rtk_announced_state == "acquired":
                                _rtk_msgs = {
                                    "en": "RTK fix! lost. Float mode active.",
                                    "ta": "ஆர்.டி.கே! இழந்தது. ஃப்ளோட் பயன்முறை.",
                                    "hi": "RTK फिक्स! खो गया. फ्लोट मोड सक्रिय.",
                                }
                            elif _new_rtk_state == "gps_only" and _rtk_announced_state in ("acquired", "float"):
                                _rtk_msgs = {
                                    "en": "RTK! signal lost. GPS only mode.",
                                    "ta": "ஆர்.டி.கே! சிக்னல் இழப்பு. ஜி.பி.எஸ் மட்டும்.",
                                    "hi": "RTK! सिग्नल खो गया. केवल GPS मोड.",
                                }
                            else:
                                _rtk_msgs = None

                            if _rtk_msgs:
                                tts.speak(_rtk_msgs.get(_lang, _rtk_msgs["en"]))
                                logger.debug(f"TTS: {_rtk_msgs.get(_lang, _rtk_msgs['en'])}")
                                _rtk_announced_state = _new_rtk_state
                                _rtk_announce_time = _now
                    except Exception:
                        pass

                if isinstance(satellites_visible, int) and current_state.satellites_visible != satellites_visible:
                    current_state.satellites_visible = satellites_visible
                    current_state.last_update = time.time()

            schedule_fast_emit()

        elif msg_type == "gps_accuracy":
            with mavros_telem_lock:
                hrms = message.get("hrms")
                vrms = message.get("vrms")

                if isinstance(hrms, (int, float)):
                    hrms_str = f"{float(hrms):.3f}"
                    if current_state.hrms != hrms_str:
                        current_state.hrms = hrms_str
                        current_state.last_update = time.time()

                if isinstance(vrms, (int, float)):
                    vrms_str = f"{float(vrms):.3f}"
                    if current_state.vrms != vrms_str:
                        current_state.vrms = vrms_str
                        current_state.last_update = time.time()

            schedule_fast_emit()

        elif msg_type == "estimator_status":
            # Bridge publishes a normalized 'imu_aligned' boolean when available
            imu_aligned = message.get('imu_aligned')
            if isinstance(imu_aligned, bool):
                with mavros_telem_lock:
                    new_status = 'ALIGNED' if imu_aligned else 'UNALIGNED'
                    if current_state.imu_status != new_status:
                        current_state.imu_status = new_status
                        current_state.last_update = time.time()
                schedule_fast_emit()

        elif msg_type == 'imu':
            # Store last IMU sample (orientation / angular velocity / linear acc)
            imu_payload = message.get('imu')
            if isinstance(imu_payload, dict):
                with mavros_telem_lock:
                    current_state.imu = imu_payload
                    current_state.last_update = time.time()
                schedule_fast_emit()

        elif msg_type == "heading":
            heading = message.get("heading")
            if heading is not None:
                with mavros_telem_lock:
                    current_state.heading = float(heading)
                    current_state.last_update = time.time()
            schedule_fast_emit()

        elif msg_type == "velocity":
            # Velocity messages published by MAVROS bridge may include a 'groundspeed' key.
            gs = message.get('groundspeed')
            if gs is not None:
                try:
                    with mavros_telem_lock:
                        current_state.groundspeed = float(gs)
                        current_state.last_update = time.time()
                except Exception as e:
                    log_message(f"[velocity] Failed to update groundspeed: {e}", "ERROR")
                schedule_fast_emit()

        elif msg_type == "rtk_baseline":
            # Baseline vectors from RTK base (broadcast by MAVROS bridge)
            baseline = message.get('rtk_baseline') or message
            logger.debug(f"rtk_baseline handler: message keys={list(message.keys())}, baseline type={type(baseline)}")
            try:
                with mavros_telem_lock:
                    current_state.rtk_baseline = dict(baseline) if isinstance(baseline, dict) else None
                    current_state.rtk_baseline_ts = time.time()
                    # Reset/initialize baseline_age to zero on receipt
                    current_state.rtk_baseline_age = 0.0
                    logger.debug(f"Stored rtk_baseline: {current_state.rtk_baseline is not None}, ts={current_state.rtk_baseline_ts}")

                    # Heuristic for base_linked: explicit field, or use iar_num_hypotheses==1 or small accuracy
                    base_linked = None
                    if isinstance(baseline, dict):
                        if 'base_linked' in baseline and isinstance(baseline.get('base_linked'), bool):
                            base_linked = bool(baseline.get('base_linked'))
                        else:
                            iar = baseline.get('iar_num_hypotheses')
                            acc = baseline.get('accuracy')
                            try:
                                if iar is not None and int(iar) == 1:
                                    base_linked = True
                                elif acc is not None:
                                    # accuracy in meters: consider very small accuracy as linked
                                    if float(acc) <= 0.05:
                                        base_linked = True
                                    else:
                                        base_linked = False
                            except Exception:
                                base_linked = None

                    if isinstance(base_linked, bool):
                        current_state.rtk_base_linked = base_linked
                        try:
                            log_message(f"[RTK] rtk_baseline received, setting rtk_base_linked={base_linked}", 'DEBUG')
                        except Exception:
                            pass
                    else:
                        # Fallback: infer from rtk_fix_type if available
                        try:
                            current_state.rtk_base_linked = (current_state.rtk_fix_type >= 5)
                            try:
                                log_message(f"[RTK] rtk_baseline received, inferred rtk_base_linked from fix_type: {current_state.rtk_base_linked}", 'DEBUG')
                            except Exception:
                                pass
                        except Exception:
                            pass

                    current_state.last_update = time.time()
            except Exception:
                pass
            schedule_fast_emit()

        elif msg_type == "battery":
            # Accept either 'percentage' (fraction 0.0-1.0 or 0-100) or 'battery' (already percent)
            perc_value = message.get("percentage")
            if perc_value is None:
                perc_value = message.get("battery")
            volt_value = message.get("voltage")
            curr_value = message.get("current")

            #log_message(f"Battery telem received: perc={perc_value}, volt={volt_value}, curr={curr_value}, keys={list(message.keys())}", 'DEBUG', event_type='ros_topic')

            updated = False
            if perc_value is not None:
                with mavros_telem_lock:
                    try:
                        pctf = float(perc_value)
                        # Check for NaN or invalid values
                        import math
                        if not math.isnan(pctf) and not math.isinf(pctf):
                            pct_val = max(0, int(round(pctf * 100))) if pctf <= 1.0 else max(0, int(round(pctf)))
                            if current_state.battery != pct_val:
                                current_state.battery = pct_val
                                updated = True
                    except Exception:
                        pass

            # Optionally store voltage/current for future UI use
            with mavros_telem_lock:
                try:
                    if volt_value is not None:
                        v = float(volt_value)
                        if not math.isnan(v) and not math.isinf(v):
                            current_state.voltage = v
                            updated = True
                except Exception:
                    pass
                try:
                    if curr_value is not None:
                        c = float(curr_value)
                        if not math.isnan(c) and not math.isinf(c):
                            current_state.current = c
                            updated = True
                except Exception:
                    pass
                if updated:
                    current_state.last_update = time.time()

            # Voice: Battery low warning (edge-triggered at 20% and 10%)
            if updated and current_state.battery >= 0:
                try:
                    global _battery_warned_20, _battery_warned_10
                    _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
                    batt = current_state.battery
                    if batt <= 10 and not _battery_warned_10:
                        _battery_warned_10 = True
                        _batt_msgs = {
                            "en": f"Warning! Battery critical, {batt} percent remaining.",
                            "ta": f"எச்சரிக்கை! பேட்டரி மிகக் குறைவு, {batt} சதவீதம் மீதம்.",
                            "hi": f"चेतावनी! बैटरी गंभीर, {batt} प्रतिशत बाकी.",
                        }
                        tts.speak(_batt_msgs.get(_lang, _batt_msgs["en"]))
                        print(f"[TTS] {_batt_msgs.get(_lang, _batt_msgs['en'])}", flush=True)
                    elif batt <= 20 and not _battery_warned_20:
                        _battery_warned_20 = True
                        _batt_msgs = {
                            "en": f"Battery low, {batt} percent remaining.",
                            "ta": f"பேட்டரி குறைவு, {batt} சதவீதம் மீதம்.",
                            "hi": f"बैटरी कम है, {batt} प्रतिशत बाकी.",
                        }
                        tts.speak(_batt_msgs.get(_lang, _batt_msgs["en"]))
                        print(f"[TTS] {_batt_msgs.get(_lang, _batt_msgs['en'])}", flush=True)
                    elif batt > 25:
                        # Reset warnings when battery recovers (e.g., new battery)
                        _battery_warned_20 = False
                        _battery_warned_10 = False
                except Exception:
                    pass

            schedule_fast_emit()

        elif msg_type == "mission_list":
            waypoints = message.get("waypoints", [])
            current_seq = message.get("current_seq")
            converted = _convert_mavros_waypoints_to_ui(waypoints)
            with mavros_telem_lock:
                current_mission = converted
                current_state.activeWaypointIndex = int(current_seq) if current_seq is not None else current_state.activeWaypointIndex
                current_state.current_waypoint_id = current_state.activeWaypointIndex
                current_state.last_update = time.time()
            schedule_fast_emit()

        elif msg_type == "mission_reached":
            seq = message.get("wp_seq")
            if seq is not None:
                waypoint_id = int(seq) + 1
                with mavros_telem_lock:
                    if waypoint_id not in current_state.completedWaypointIds:
                        current_state.completedWaypointIds.append(waypoint_id)
                    current_state.current_waypoint_id = int(seq)
                    current_state.activeWaypointIndex = int(seq)
                    current_state.last_update = time.time()
                _record_mission_event(
                    f"Waypoint {waypoint_id} reached",
                    status='REACHED',
                    waypoint_id=waypoint_id
                )
                schedule_fast_emit()

        elif msg_type == "servo_output":
            servo_state = message.get("servo_output")
            if servo_state and isinstance(servo_state, dict):
                with mavros_telem_lock:
                    current_state.servo_output = servo_state
                    current_state.last_update = time.time()
                schedule_fast_emit()

        # Fallback: process battery fields even if message type isn't explicitly 'battery'
        try:
            perc_value = message.get("percentage")
            if perc_value is None:
                perc_value = message.get("battery")
            volt_value = message.get("voltage")
            curr_value = message.get("current")
            updated = False
            if perc_value is not None:
                with mavros_telem_lock:
                    try:
                        pctf = float(perc_value)
                        import math
                        if not math.isnan(pctf) and not math.isinf(pctf):
                            pct_val = max(0, int(round(pctf * 100))) if pctf <= 1.0 else max(0, int(round(pctf)))
                            if current_state.battery != pct_val:
                                current_state.battery = pct_val
                                updated = True
                    except Exception:
                        pass
                
            with mavros_telem_lock:
                try:
                    if volt_value is not None:
                        v = float(volt_value)
                        if not math.isnan(v) and not math.isinf(v):
                            current_state.voltage = v
                            updated = True
                except Exception:
                    pass
                try:
                    if curr_value is not None:
                        c = float(curr_value)
                        if not math.isnan(c) and not math.isinf(c):
                            current_state.current = c
                            updated = True
                except Exception:
                    pass
                if updated:
                    current_state.last_update = time.time()
                    schedule_fast_emit()
        except Exception:
            pass

    except Exception as exc:
        log_message(f"MAVROS telemetry handler error: {exc}", "ERROR")



last_sent_telemetry = {}


async def telemetry_loop():
    """Continuously sends telemetry data to the frontend."""
    global last_sent_telemetry, last_emit_monotonic
    fallback_interval = float(os.getenv('FALLBACK_EMIT_SEC', '60.0'))
    while True:
        if is_vehicle_connected:
            now = time.monotonic()
            if now - last_emit_monotonic >= fallback_interval:
                emit_rover_data_now(reason='fallback')
                last_sent_telemetry = get_rover_data()
        else:
            last_sent_telemetry = {}
        await asyncio.sleep(0.5)


async def connection_health_monitor():
    """Monitor client connections and emit health status periodically."""
    while True:
        try:
            current_time = time.time()
            
            # Check for stale client connections
            stale_clients = []
            for client_id, session in list(_client_sessions.items()):
                time_since_ping = current_time - session.get('last_ping', current_time)
                
                # Mark clients as stale if no ping for 30 seconds
                if time_since_ping > 30:
                    stale_clients.append(client_id)
                    session['missed_pings'] = session.get('missed_pings', 0) + 1
                    
                    # Emit warning to specific client
                    sync_emit('connection_warning', {
                        'message': 'Connection may be unstable',
                        'time_since_ping': time_since_ping,
                        'timestamp': current_time
                    }, room=client_id)
            
            # Clean up very stale sessions (no activity for 5 minutes)
            for client_id in list(_client_sessions.keys()):
                session = _client_sessions[client_id]
                if current_time - session.get('last_ping', current_time) > 300:
                    _client_sessions.pop(client_id, None)
                    log_message(f'Cleaned up stale session: {client_id}', 'INFO')
            
            # Emit overall health status
            active_clients = len(_client_sessions) - len(stale_clients)
            sync_emit('server_health', {
                'timestamp': current_time,
                'active_clients': active_clients,
                'total_clients': len(_client_sessions),
                'vehicle_connected': is_vehicle_connected,
                'ros_available': ROS_AVAILABLE,
                'uptime': current_time
            })
            
        except Exception as exc:
            log_message(f"Connection health monitor error: {exc}", "ERROR")
        
        await asyncio.sleep(10)  # Check every 10 seconds


# ============================================================================
# COMMAND HANDLERS
# ============================================================================

def _handle_arm_disarm(data):
    """Handle arm/disarm command."""
    arm = bool(data.get('arm', False))
    global is_vehicle_connected
    log_message(f"{'Arming' if arm else 'Disarming'} vehicle...")

    response_payload: dict[str, object] = {}
    errors: list[str] = []
    ros2_sent = False
    mavros_sent = False

    if command_bridge is not None:
        try:
            response = command_bridge.arm(value=arm)
            ros2_sent = bool(response.get('success', False))
            if not ros2_sent and response.get('result') is not None:
                ros2_sent = bool(response['result'])
            log_message(f"ROS2 arm service {'accepted' if ros2_sent else 'rejected'} ({response})")
            response_payload['ros2'] = response
        except Exception as exc:
            log_message(f"ROS2 arm service failed: {exc}", "WARNING")
            errors.append(f"ROS2: {exc}")

    if not ros2_sent:
        try:
            bridge = _get_vehicle_bridge(require_vehicle=False)
            mavros_response = bridge.arm(value=arm)
            response_payload['mavros'] = mavros_response
            log_message(f"MAVROS arm service acknowledged ({mavros_response})", 'INFO', event_type='ui_request')
            mavros_sent = True
            if not is_vehicle_connected:
                # Assume vehicle is reachable if the command succeeded.
                is_vehicle_connected = True
        except Exception as exc:
            errors.append(f"MAVROS: {exc}")
            log_message(f"MAVROS arm/disarm failed: {exc}", "ERROR", event_type='ui_request')

    if not ros2_sent and not mavros_sent:
        error_text = "; ".join(errors) if errors else "unknown error"
        raise RuntimeError(f"Arm/disarm command failed ({error_text})")

    with mavros_telem_lock:
        current_state.status = 'armed' if arm else 'disarmed'
        current_state.last_update = time.time()
        current_state.last_heartbeat = time.time()
    emit_rover_data_now(reason='arm_disarm')

    record_activity(
        f"Vehicle {'armed' if arm else 'disarmed'}",
        event_type='server_response',
        meta={
            'via_ros2': ros2_sent,
            'via_mavros': mavros_sent,
            'response': _make_json_safe(response_payload),
            'errors': errors,
        }
    )

    return {
        'status': 'success',
        'via_ros2': ros2_sent,
        'via_mavros': mavros_sent,
        'message': f"Vehicle {'armed' if arm else 'disarmed'}"
    }


def _handle_set_mode(data):
    """Handle mode change command."""
    new_mode = data.get('mode', 'MANUAL')
    mode_num = get_mode_number(new_mode)
    if mode_num is None:
        raise Exception(f"Unknown mode: {new_mode}")
    log_message(f"Setting vehicle mode to: {new_mode} (mode #{mode_num})")

    target_mode = str(new_mode).upper()
    ros2_sent = False
    if command_bridge is not None:
        try:
            response = command_bridge.set_mode(mode=target_mode)
            ros2_sent = bool(response.get('success', False) and response.get('mode_sent', False))
            log_message(f"ROS2 set_mode response: {response}")
        except Exception as exc:
            log_message(f"ROS2 set_mode failed: {exc}", "WARNING")

    if not ros2_sent:
        bridge = _require_vehicle_bridge()
        bridge.set_mode(mode=target_mode, custom_mode=target_mode)

    with mavros_telem_lock:
        current_state.mode = target_mode
        current_state.last_update = time.time()
    emit_rover_data_now(reason='set_mode')
    return {
        'status': 'success',
        'via_ros2': ros2_sent,
        'message': f"Mode change requested: {new_mode}"
    }


def _handle_goto(data):
    """Handle goto command."""
    bridge = _require_vehicle_bridge()
    lat = data['lat']
    lon = data['lon']
    alt = data.get('alt', 0)
    log_message(f"Sending vehicle to: {lat}, {lon}, alt: {alt}m")
    bridge.send_global_position_target(
        latitude=float(lat),
        longitude=float(lon),
        altitude=float(alt),
        coordinate_frame=mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        type_mask=0b0000111111111000
    )
    return {
        'status': 'success',
        'message': f"GOTO command sent to {lat}, {lon}"
    }


def _handle_upload_mission(data):
    """
    Upload a mission to the rover via MAVROS.
    
    This is the centralized mission upload handler used by both:
    - REST API /api/mission/upload
    - Socket.IO mission_upload (deprecated)
    
    Args:
        data: Dict with 'waypoints' (required) and optional 'servoConfig'
        
    Returns:
        Dict with status and message
    """
    global current_mission
    bridge = _require_vehicle_bridge()
    
    waypoints = data.get("waypoints")
    if not isinstance(waypoints, list) or not waypoints:
        raise ValueError("Mission upload requires waypoints")
    
    # Validate coordinates before upload to catch any lat/lng swap issues
    for wp in waypoints:
        lat_val = wp.get('lat', 0)
        lng_val = wp.get('lng', 0)
        if abs(lat_val) > 90:
            raise ValueError(f"Invalid latitude {lat_val} in waypoint {wp.get('id', '?')} - must be between -90 and +90")
        if abs(lng_val) > 180:
            raise ValueError(f"Invalid longitude {lng_val} in waypoint {wp.get('id', '?')} - must be between -180 and +180")
    
    # Apply servo configuration if provided
    servo_config = data.get("servoConfig")
    if servo_config:
        log_message(f"[mission_upload] Applying servo mode: {servo_config.get('mode')}", "INFO")
        waypoints = apply_servo_modes(waypoints, servo_config)
    
    mission_count = len(waypoints)
    log_message(f"[mission_upload] Uploading {mission_count} waypoint(s) via MAVROS", "INFO")
    
    # Convert to MAVROS format and push to vehicle
    mavros_waypoints = _build_mavros_waypoints(waypoints)
    response = bridge.push_waypoints(mavros_waypoints)
    
    if not response.get("success", False):
        raise RuntimeError(f"MAVROS mission push failed: {response}")
    
    # Update mission state
    current_mission = list(waypoints)
    with mavros_telem_lock:
        current_state.completedWaypointIds = []
        current_state.activeWaypointIndex = None
        current_state.current_waypoint_id = None
        mission_log_state['last_active_seq'] = None
        mission_log_state['last_reached_seq'] = None
    
    # Send load_mission command to mission controller node
    try:
        load_mission_data = {
            'command': 'load_mission',
            'waypoints': waypoints,
            'config': servo_config or {}
        }
        if hasattr(bridge, 'publish_mission_command'):
            bridge.publish_mission_command(load_mission_data)
            log_message(f"Sent load_mission command to mission controller ({mission_count} waypoints)", "INFO")
        else:
            log_message("Warning: MAVROS bridge not available for load_mission command", "WARNING")
    except Exception as e:
        log_message(f"Failed to send load_mission to mission controller: {e}", "ERROR")
    
    # Record activity
    _record_mission_event(
        f"Mission uploaded ({mission_count} items)",
        status='MISSION_UPLOADED'
    )
    
    log_message(f"Mission uploaded successfully via MAVROS ({mission_count} waypoints)", "SUCCESS")
    
    return {
        "status": "success",
        "message": f"Mission uploaded ({mission_count} waypoints)"
    }


def _handle_get_mission(data):
    """
    Handle mission download from vehicle.
    
    Returns waypoints from vehicle if available, otherwise returns cached mission.
    Provides clear error messages for different failure scenarios.
    """
    global current_mission
    bridge = _require_vehicle_bridge()
    
    try:
        log_message("[MISSION] Downloading mission from vehicle...", "INFO")
        mission_waypoints = download_mission_from_vehicle()
        
        if not mission_waypoints or len(mission_waypoints) == 0:
            log_message("[MISSION] Downloaded empty mission from vehicle", "INFO")
            return {
                'status': 'success',
                'message': 'Rover mission is empty (0 waypoints)',
                'waypoints': []
            }
        
        # Validate coordinates to catch any lat/lng swap issues
        for wp in mission_waypoints:
            lat_val = wp.get('lat', 0)
            lng_val = wp.get('lng', 0)
            if abs(lat_val) > 90:
                log_message(f"WARNING: Invalid latitude {lat_val} in waypoint {wp.get('id')} - possible lat/lng swap!", "ERROR")
            if abs(lng_val) > 180:
                log_message(f"WARNING: Invalid longitude {lng_val} in waypoint {wp.get('id')} - possible lat/lng swap!", "ERROR")
        
        log_message(f"[MISSION] Successfully downloaded {len(mission_waypoints)} waypoints", "SUCCESS")
        return {
            'status': 'success',
            'message': f'Downloaded {len(mission_waypoints)} waypoints from rover',
            'waypoints': mission_waypoints
        }
        
    except TimeoutError as e:
        log_message(f"[MISSION] Download timeout: {e}", "ERROR")
        if current_mission and len(current_mission) > 0:
            return {
                'status': 'success',
                'message': f'Download timed out. Using cached mission ({len(current_mission)} waypoints)',
                'waypoints': current_mission,
                'warning': 'timeout'
            }
        raise TimeoutError("Mission download timed out. Please check MAVROS connection and try again.")
        
    except ConnectionError as e:
        log_message(f"[MISSION] Connection error during download: {e}", "ERROR")
        raise ConnectionError("Unable to connect to rover. Please check MAVROS bridge is running.")
        
    except Exception as e:
        log_message(f"[MISSION] Download failed: {e}", "ERROR")
        
        # Try to provide cached mission as fallback
        if current_mission and len(current_mission) > 0:
            return {
                'status': 'success',
                'message': f'Download failed. Using cached mission ({len(current_mission)} waypoints)',
                'waypoints': current_mission,
                'warning': 'fallback'
            }
        
        # No cached mission available
        error_msg = str(e)
        if "not available" in error_msg.lower():
            raise RuntimeError("MAVROS service not available. Please check rosbridge connection.")
        elif "timeout" in error_msg.lower():
            raise TimeoutError("Mission download timed out. Vehicle may not be responding.")
        else:
            raise RuntimeError(f"Mission download failed: {error_msg}")


def _handle_clear_mission(_data=None):
    """Clear all mission waypoints from the vehicle."""
    global current_mission
    bridge = _require_vehicle_bridge()
    log_message("Clearing mission from vehicle...")
    try:
        response = bridge.clear_waypoints()
        if not response.get('success', False):
            error_msg = response.get('error', 'Unknown error')
            log_message(f"MAVROS mission clear failed: {error_msg}", "ERROR")
            raise RuntimeError(f"MAVROS mission clear failed: {error_msg}")
    except Exception as e:
        log_message(f"Failed to clear waypoints: {e}", "ERROR")
        raise RuntimeError(f"Failed to clear mission: {str(e)}")
    
    with mavros_telem_lock:
        current_mission = []
        current_state.completedWaypointIds = []
        current_state.activeWaypointIndex = None
        current_state.current_waypoint_id = None
        current_state.last_update = time.time()
    _record_mission_event('Mission cleared from vehicle', status='MISSION_CLEARED')
    emit_rover_data_now(reason='mission_clear')
    log_message("Mission cleared successfully via MAVROS", "SUCCESS")
    return {'status': 'success', 'message': 'Mission cleared'}


COMMAND_HANDLERS = {
    'ARM_DISARM': _handle_arm_disarm,
    'SET_MODE': _handle_set_mode,
    'GOTO': _handle_goto,
    'UPLOAD_MISSION': _handle_upload_mission,
    'GET_MISSION': _handle_get_mission,
    'CLEAR_MISSION': _handle_clear_mission,
}


@sio.on('request_mission_logs')
async def handle_request_mission_logs(sid):
    try:
        snapshot = list(mission_log_history)
        await sio.emit('mission_logs_snapshot', snapshot, to=sid)
    except Exception as exc:
        log_message(f"Failed to serve mission logs snapshot: {exc}", 'ERROR')


# ============================================================================
# MISSION UPLOAD/DOWNLOAD
# ============================================================================
# NOTE: Socket.IO mission_upload handler is DEPRECATED.
# All mission uploads should use REST API /api/mission/upload
# which properly integrates with MAVROS through _handle_upload_mission().
#
# This Socket.IO handler is kept only for backward compatibility but
# now redirects to the same MAVROS implementation.

@sio.on("mission_upload")
async def on_mission_upload(sid, data):
    """
    DEPRECATED: Mission upload via Socket.IO.
    Use REST API /api/mission/upload instead.
    
    This handler redirects to _handle_upload_mission() for MAVROS integration.
    """
    global current_mission
    
    log_message("[mission_upload] Socket.IO upload called (DEPRECATED - use REST API)", "WARNING")

    try:
        # Use the centralized handler that REST API uses
        result = _handle_upload_mission(data)
        
        # Emit progress events for backward compatibility
        await sio.emit('mission_upload_progress', {'progress': 100})
        
        # Emit completion event with success response
        await sio.emit("mission_uploaded", {
            "ok": True,
            "count": len(data.get("waypoints", [])),
            "message": result.get("message", "Mission uploaded via MAVROS")
        }, to=sid)
        
    except Exception as e:
        log_message(f"[mission_upload] Error: {e}", "ERROR")
        await sio.emit("mission_uploaded", {"ok": False, "error": str(e)}, to=sid)


def download_mission_from_vehicle():
    """Download mission from vehicle."""
    global current_mission
    bridge = _require_vehicle_bridge()
    acquired = mission_download_lock.acquire(blocking=True, timeout=30.0)
    if not acquired:
        raise Exception("Mission download timeout - another download still in progress, please retry")

    try:
        sync_emit('mission_download_progress', {'progress': 5})
        response = bridge.pull_waypoints()
        waypoint_list = response.get("waypoints", [])
        converted = _convert_mavros_waypoints_to_ui(waypoint_list)
        current_mission = converted.copy()
        sync_emit('mission_download_progress', {'progress': 100})
        log_message(f"[mission_download] Completed via MAVROS: {len(converted)} waypoints", "SUCCESS")
        return converted
    except Exception as e:
        log_message(f"Error downloading mission: {e}", "ERROR")
        raise
    finally:
        try:
            mission_download_lock.release()
        except Exception:
            pass


# ============================================================================
# RTK INJECTION SYSTEM (Enhanced with Debug Headers)
# ============================================================================

rtk_thread: Optional[threading.Thread] = None
rtk_running = False
rtk_bytes_total = 0
rtk_bytes_lock = threading.Lock()
rtk_current_caster = None

# LoRa RTK injection handler
lora_rtk_handler: Optional["LoRaRTKHandler"] = None # pyright: ignore[reportInvalidTypeForm] # type: ignore
lora_rtk_source_active = False


# Replace the existing _ntrip_request() function with:
def _ntrip_request(host: str, mount: str, user: str, pwd: str) -> bytes:
    """Builds an exact NTRIP 2.0 HTTP/1.0 request identical to manual telnet test."""
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    req = (
        f"GET /{mount} HTTP/1.0\r\n"
        f"User-Agent: NTRIP_RoverPlan/1.0\r\n"
        f"Ntrip-Version: Ntrip/2.0\r\n"
        f"Authorization: Basic {auth}\r\n"
        f"\r\n"
    )
    return req.encode("ascii", errors="ignore")


def _inject_rtcm_to_mav(rtcm_bytes: bytes) -> bool:
    """Send RTCM correction data to rover's GPS module."""
    try:
        bridge = _require_vehicle_bridge()
    except Exception as exc:
        log_message(f"[RTK] ⚠️ Cannot send - {exc}", "WARNING")
        return False

    MAX_CHUNK = 180
    try:
        total_sent = 0
        for i in range(0, len(rtcm_bytes), MAX_CHUNK):
            chunk = rtcm_bytes[i:i + MAX_CHUNK]
            if chunk:
                bridge.send_rtcm(bytes(chunk))
                total_sent += len(chunk)

        if total_sent > 0:
            with rtk_bytes_lock:
                global rtk_bytes_total
                rtk_bytes_total += total_sent
                current_total = rtk_bytes_total
            # Tell frontend how many bytes forwarded
            sync_emit('rtk_forwarded', {
                'added': total_sent,
                'total': current_total,
            })
        return True
    except Exception as e:
        log_message(f"[RTK] ❌ Failed to send data: {e}", "ERROR")
        sync_emit('rtk_log', {'message': f'❌ Send error: {e}'})
        return False


@sio.on('connect_caster')
async def handle_connect_caster(sid, caster_details):
    """Start RTK corrections stream from caster network."""
    global rtk_thread, rtk_running, rtk_current_caster

    sender_id = sid

    # Emit debug event for connect request
    emit_rtk_debug('connect_caster_request_received', sender_id, {
        'rtk_running': bool(globals().get('rtk_running', False)),
        'lora_rtk_source_active': bool(globals().get('lora_rtk_source_active', False))
    })

    # --- IMPROVEMENT: Automatically stop the existing stream ---
    if rtk_running:
        log_message("[RTK] 🔄 Restart requested. Stopping existing stream first...", "INFO")
        await sio.emit('rtk_log', {'message': '🔄 Restarting stream...'})
        rtk_running = False
        # Give the old thread a moment to see the flag and exit
        await asyncio.sleep(0.2)
    # --- END IMPROVEMENT ---

    try:
        host = str(caster_details.get('host', '')).strip()
        port = int(caster_details.get('port', 2101))
        mount = str(caster_details.get('mountpoint', '')).strip()
        user = str(caster_details.get('user') or caster_details.get('username', '')).strip()
        pwd = str(caster_details.get('password', '')).strip()

        if not host or not mount:
            raise ValueError("Missing host or mountpoint")
        # Enforce credentials presence to prevent unauthenticated streams
        if not user or not pwd:
            raise ValueError("Missing username or password")

    except Exception as e:
        msg = f'❌ Invalid settings: {str(e)}'
        await sio.emit('rtk_log', {'message': msg})
        await sio.emit('caster_status', {
            'status': 'error',
            'message': msg
        }, to=sender_id)
        return

    # Ensure the bridge and vehicle are connected before starting RTK
    try:
        _require_vehicle_bridge()
    except Exception as exc:
        msg = f'❌ {exc}'
        log_message(f"[RTK] Rejecting stream start: {msg}", "WARNING")
        await sio.emit('rtk_log', {'message': msg})
        await sio.emit('caster_status', {
            'status': 'error',
            'message': msg
        }, to=sender_id)
        return

    rtk_current_caster = caster_details
    log_message(f"[RTK] 🚀 Starting stream from {host}:{port}/{mount}", "INFO")
    await sio.emit('rtk_log', {'message': f'🔄 Connecting to {host}:{port}...'})
    await sio.emit('caster_status', {
        'status': 'connecting',
        'message': f'Connecting to {mount}...'
    })

    rtk_running = True

    def rtk_worker():
        """Background thread for continuous RTK data streaming."""
        global rtk_running, rtk_bytes_total
        sock = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)

            log_message(f"[RTK] Attempting connection to {host}:{port}...")
            sync_emit('rtk_log', {'message': f'📡 Connecting to {host}:{port}...'})
            sock.connect((host, port))
            log_message(f"[RTK] Connection to {host}:{port} successful!", "SUCCESS")
            sync_emit('rtk_log', {'message': f'📡 Connected to {host}:{port}'})

            request_data = _ntrip_request(host, mount, user, pwd)
            sock.sendall(request_data)
            sync_emit('rtk_log', {
                'message': f'📤 Sent NTRIP request for mountpoint {mount}'
            })

            # --- Wait for optional HTTP header or direct binary stream ---
            buffer = b''
            header_timeout = time.time() + 12.0
            header_found = False

            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    raise RuntimeError('Caster closed connection during handshake')
                buffer += chunk

                if b'\r\n\r\n' in buffer:
                    headers, leftover_data = buffer.split(b'\r\n\r\n', 1)
                    header_text = headers.decode('ascii', errors='ignore')
                    first_line = header_text.split('\n')[0]
                    # Emit the full caster response header for visibility
                    sync_emit('rtk_log', {'message': f'🧾 Caster Response:\n{header_text}'})
                    upper_hdr = header_text.upper()
                    # Explicitly detect auth failures and sourcetable responses
                    if ('SOURCETABLE' in upper_hdr or
                        '401' in upper_hdr or 'UNAUTHORIZED' in upper_hdr or
                        '403' in upper_hdr or 'FORBIDDEN' in upper_hdr or
                        'NTRIP-ERROR' in upper_hdr):
                        raise RuntimeError('❌ Unauthorized or bad username/password!')
                    # Accept either ICY 200 or standard 200 OK
                    if b'ICY 200' not in headers and b'200 OK' not in headers:
                        raise RuntimeError(f'❌ Unexpected response:\n{header_text}')
                    sync_emit('rtk_log', {'message': '✅ Connection established! Streaming RTCM data...'})
                    leftover = leftover_data
                    header_found = True
                    break

                # direct binary
                if any(b < 32 and b not in (b'\r'[0], b'\n'[0], b'\t'[0]) for b in chunk):
                    sync_emit('rtk_log', {'message': '✅ No header — direct RTCM stream detected'})
                    leftover = buffer
                    break

                if time.time() > header_timeout:
                    raise TimeoutError('Caster took too long to respond')

            if header_found:
                sync_emit('caster_status', {
                    'status': 'Connected',
                    'message': 'ICY 200 OK – RTCM stream active'
                })
            else:
                sync_emit('caster_status', {
                    'status': 'Connected',
                    'message': 'RTCM stream active (no header)'
                })

            with rtk_bytes_lock:
                rtk_bytes_total = 0

            # Inject leftover RTCM if present
            if 'leftover' in locals() and leftover:
                if _inject_rtcm_to_mav(leftover):
                    sync_emit('rtk_log', {
                        'message': f'📥 Sent initial {len(leftover)} bytes'
                    })
                    # Debug: print RTCM header bytes to browser console
                    if leftover.startswith(b'\xd3'):
                        msg_len = int.from_bytes(leftover[1:3], "big") & 0x03FF
                        sync_emit('rtk_log', {
                            'message': f'🔍 RTCM Detected: Header 0xD3, length {msg_len} bytes'
                        })

            sock.settimeout(3.0)
            last_data_time = time.time()

            while rtk_running:
                try:
                    data = sock.recv(4096)

                    if not data:
                        if time.time() - last_data_time > 10:
                            raise RuntimeError('No data received for 10 seconds')
                        time.sleep(0.1)
                        continue

                    last_data_time = time.time()

                    # Debug: parse RTCM header
                    if data.startswith(b'\xd3') and len(data) >= 3:
                        msg_len = int.from_bytes(data[1:3], "big") & 0x03FF
                        sync_emit('rtk_log', {
                            'message': f'🔍 RTCM Packet: 0xD3 len={msg_len}'
                        })

                    if _inject_rtcm_to_mav(data):
                        sync_emit('rtcm_data', data)

                except socket.timeout:
                    continue

                except Exception as stream_error:
                    log_message(f"[RTK] Stream error: {stream_error}", "ERROR")
                    sync_emit('rtk_log', {
                        'message': f'⚠️ Stream error: {stream_error}'
                    })
                    break

        except Exception as e:
            error_msg = str(e)
            log_message(f"[RTK] ❌ Connection failed: {error_msg}", "ERROR")
            sync_emit('rtk_log', {'message': f'❌ Error: {error_msg}'})
            sync_emit('caster_status', {
                'status': 'error',
                'message': error_msg
            })

        finally:
            rtk_running = False
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

            sync_emit('rtk_log', {'message': '🛑 RTK stream stopped'})
            sync_emit('caster_status', {
                'status': 'Disconnected',
                'message': 'Stream ended'
            })
            log_message("[RTK] Stream thread ended", "INFO")

    rtk_thread = threading.Thread(target=rtk_worker, daemon=True, name="RTK-Worker")
    rtk_thread.start()

    await sio.emit('rtk_log', {'message': '🎬 RTK thread started'})


@sio.on('disconnect_caster')
async def handle_disconnect_caster(sid):
    """Stop the RTK stream."""
    global rtk_running

    sender_id = sid

    emit_rtk_debug('disconnect_caster_request_received', sender_id, {
        'rtk_running': bool(globals().get('rtk_running', False))
    })

    if rtk_running:
        log_message("[RTK] 🛑 Stop requested by user", "INFO")
        rtk_running = False
        await sio.emit('rtk_log', {'message': '🛑 Stopping RTK stream...'})
        await sio.emit('caster_status', {
            'status': 'Disconnected',
            'message': 'Stop requested'
        }, to=sender_id)
    else:
        await sio.emit('rtk_log', {'message': 'ℹ️ Stream was not running'})
        await sio.emit('caster_status', {
            'status': 'Disconnected',
            'message': 'Already stopped'
        }, to=sender_id)


# ============================================================================
# LoRa RTK INJECTION ENDPOINTS
# ============================================================================

@sio.on('start_lora_rtk_stream')
async def handle_start_lora_rtk_stream(sid, data=None):
    """Start receiving RTK corrections via LoRa USB receiver."""
    global lora_rtk_handler, lora_rtk_source_active, rtk_running

    sender_id = sid

    # Emit debug event for LoRa start request
    emit_rtk_debug('start_lora_request_received', sender_id, {
        'rtk_running': bool(globals().get('rtk_running', False)),
        'lora_rtk_source_active': bool(globals().get('lora_rtk_source_active', False)),
        'handler_exists': bool(globals().get('lora_rtk_handler'))
    })

    # Don't allow both NTRIP and LoRa streams simultaneously
    if rtk_running and lora_rtk_source_active is False:
        msg = "⚠️ NTRIP stream already active. Please disconnect NTRIP first."
        log_message(f"[LoRa RTK] {msg}", "WARNING")
        await sio.emit('rtk_log', {'message': msg})
        await sio.emit('lora_rtk_status', {
            'status': 'error',
            'message': msg
        }, to=sender_id)
        return

    try:
        # Ensure vehicle bridge is connected
        _require_vehicle_bridge()
    except Exception as exc:
        msg = f'❌ {exc}'
        log_message(f"[LoRa RTK] Rejecting stream start: {msg}", "WARNING")
        await sio.emit('rtk_log', {'message': msg})
        await sio.emit('lora_rtk_status', {
            'status': 'error',
            'message': msg
        }, to=sender_id)
        return

    try:
        # Initialize handler if not exists
        if lora_rtk_handler is None and create_lora_rtk_handler:
            log_message("[LoRa RTK] Initializing LoRa RTK handler...", "INFO")
            lora_rtk_handler = create_lora_rtk_handler(_inject_rtcm_to_mav)
            
            # Set status callback
            def lora_status_callback(status_type: str, data: dict):
                """Emit LoRa status updates to frontend"""
                sync_emit('lora_rtk_status', {
                    'status': status_type,
                    **data
                })
            
            lora_rtk_handler.set_status_callback(lora_status_callback)

        if not lora_rtk_handler:
            raise Exception("LoRa RTK handler not available")

        # Connect to receiver
        if not lora_rtk_handler.is_connected:
            log_message("[LoRa RTK] Connecting to receiver...", "INFO")
            await sio.emit('rtk_log', {'message': '🔌 Connecting to LoRa receiver...'})
            await sio.emit('lora_rtk_status', {
                'status': 'connecting',
                'message': 'Connecting to LoRa receiver...'
            }, to=sender_id)

            if not lora_rtk_handler.connect():
                raise Exception("Failed to connect to LoRa receiver")

        # Start receiving stream
        log_message("[LoRa RTK] Starting RTK stream...", "INFO")
        await sio.emit('rtk_log', {'message': '📡 Starting LoRa RTK stream...'})
        await sio.emit('lora_rtk_status', {
            'status': 'connecting',
            'message': 'Starting stream...'
        }, to=sender_id)

        if not lora_rtk_handler.start_stream():
            raise Exception("Failed to start LoRa stream")

        lora_rtk_source_active = True
        log_message("[LoRa RTK] 🚀 LoRa RTK stream started successfully", "INFO")
        await sio.emit('rtk_log', {'message': '✅ LoRa RTK stream active'})
        await sio.emit('lora_rtk_status', {
            'status': 'streaming',
            'message': 'Receiving RTCM corrections via LoRa',
            'started_at': datetime.now().isoformat()
        }, to=sender_id)

    except Exception as e:
        msg = f"❌ LoRa RTK stream error: {str(e)}"
        log_message(f"[LoRa RTK] {msg}", "ERROR")
        await sio.emit('rtk_log', {'message': msg})
        await sio.emit('lora_rtk_status', {
            'status': 'error',
            'message': str(e)
        }, to=sender_id)
        lora_rtk_source_active = False


@sio.on('stop_lora_rtk_stream')
async def handle_stop_lora_rtk_stream(sid, data=None):
    """Stop receiving RTK corrections via LoRa."""
    global lora_rtk_handler, lora_rtk_source_active

    sender_id = sid

    # Emit debug event for LoRa stop request
    emit_rtk_debug('stop_lora_request_received', sender_id, {
        'lora_rtk_source_active': bool(globals().get('lora_rtk_source_active', False)),
        'handler_exists': bool(globals().get('lora_rtk_handler'))
    })

    if not lora_rtk_handler or not lora_rtk_source_active:
        await sio.emit('rtk_log', {'message': 'ℹ️ LoRa stream not running'})
        await sio.emit('lora_rtk_status', {
            'status': 'disconnected',
            'message': 'Stream was not running'
        }, to=sender_id)
        return

    try:
        log_message("[LoRa RTK] 🛑 Stop requested by user", "INFO")
        lora_rtk_handler.stop_stream()
        lora_rtk_source_active = False

        await sio.emit('rtk_log', {'message': '🛑 LoRa RTK stream stopped'})
        await sio.emit('lora_rtk_status', {
            'status': 'disconnected',
            'message': 'Stream stopped by user'
        }, to=sender_id)

    except Exception as e:
        msg = f"❌ Error stopping LoRa stream: {str(e)}"
        log_message(f"[LoRa RTK] {msg}", "ERROR")
        await sio.emit('rtk_log', {'message': msg})


@sio.on('get_lora_rtk_status')
async def handle_get_lora_rtk_status(sid, data=None):
    """Get current LoRa RTK handler status."""
    global lora_rtk_handler, lora_rtk_source_active

    sender_id = sid

    if not lora_rtk_handler:
        await sio.emit('lora_rtk_status', {
            'status': 'unavailable',
            'message': 'LoRa RTK handler not available',
            'is_connected': False,
            'is_running': False
        }, to=sender_id)
        return

    try:
        status = lora_rtk_handler.get_status()
        status['source_active'] = lora_rtk_source_active
        
        await sio.emit('lora_rtk_status', {
            'status': 'status_update',
            **status
        }, to=sender_id)

    except Exception as e:
        log_message(f"[LoRa RTK] Error getting status: {e}", "ERROR")
        await sio.emit('lora_rtk_status', {
            'status': 'error',
            'message': f'Failed to get status: {str(e)}'
        }, to=sender_id)



# ============================================================================
# SOCKET.IO EVENT HANDLERS
# ============================================================================

@sio.on('connect')
async def handle_connect(sid, environ):
    """Handles a new client connection."""
    try:
        client_id = sid
        client_addr = environ.get('REMOTE_ADDR', 'unknown')
        log_message(f'✅ Client connected: {client_id} from {client_addr}', 'INFO')
        
        # Send connection confirmation with session ID
        await sio.emit('connection_response', {
            'status': 'connected',
            'sid': client_id,
            'timestamp': time.time()
        }, to=sid)
        
        # Send system settings to new client
        await sio.emit('failsafe_mode_changed', {
            'mode': current_state.gps_failsafe_mode,
            'timestamp': time.time()
        }, to=sid)
        log_message(f"📤 Sent GPS failsafe mode to new client: {current_state.gps_failsafe_mode}", "INFO")

        if is_vehicle_connected:
            log_message("Emitting 'CONNECTED_TO_ROVER' to NEW client...")
            await sio.emit('connection_status', {'status': 'CONNECTED_TO_ROVER'}, to=sid)
            rover_data = get_rover_data()
            if rover_data:
                log_message("Sending current rover data to new client")
                await sio.emit('rover_data', rover_data, to=sid)
        else:
            log_message("Emitting 'WAITING_FOR_ROVER' to NEW client...")
            await sio.emit('connection_status', {'status': 'WAITING_FOR_ROVER'}, to=sid)
    except Exception as e:
        # Do not reject the connection if our handler has a transient error
        log_message(f"Error in connect handler: {e}", 'ERROR')
        try:
            await sio.emit('connection_response', {
                'status': 'connected',
                'sid': sid,
                'timestamp': time.time()
            }, to=sid)
        except Exception as e:
            log_message(f"[handle_connect] Failed to send connection response: {e}", "ERROR")

    # Also inform new clients of current RTK caster status for seamless UX
    try:
        if rtk_running:
            caster = rtk_current_caster or {}
            host = str(caster.get('host', ''))
            port = str(caster.get('port', ''))
            mount = str(caster.get('mountpoint', ''))
            await sio.emit('caster_status', {
                'status': 'Connected',
                'message': f'Active stream: {host}:{port}/{mount}'
            }, to=sid)
        else:
            await sio.emit('caster_status', {
                'status': 'Disconnected',
                'message': 'No active RTK stream'
            }, to=sid)
    except Exception as e:
        log_message(f"Failed to emit caster status to new client: {e}", 'WARNING')


@sio.on('disconnect')
async def handle_disconnect(sid):
    client_id = sid
    log_message(f'❌ Client disconnected: {client_id}', 'INFO')

    # Stop manual control if active
    if manual_control_handler and manual_control_handler.is_active:
        log_message("Client disconnected during manual control - stopping", "WARNING")
        manual_control_handler.stop_session(reason="client_disconnect")

    # Clear client-specific state if needed
    _client_sessions.pop(client_id, None)


# Track client sessions for connection quality monitoring
_client_sessions = {}

@sio.on('ping')
async def handle_ping(sid, data=None):
    """Handle ping from client for connection testing with latency tracking."""
    client_id = sid
    current_time = time.time()
    
    # Initialize client session if not exists
    if client_id not in _client_sessions:
        _client_sessions[client_id] = {
            'connected_at': current_time,
            'last_ping': current_time,
            'ping_count': 0,
            'missed_pings': 0
        }
    
    session = _client_sessions[client_id]
    session['last_ping'] = current_time
    session['ping_count'] += 1
    
    # Calculate connection quality metrics
    ping_interval = current_time - session.get('last_ping_response', current_time)
    
    # Respond with comprehensive connection info
    response_data = {
        'timestamp': current_time,
        'server_time': current_time,
        'session_id': client_id,
        'ping_count': session['ping_count'],
        'connection_quality': 'good' if ping_interval < 2.0 else 'degraded' if ping_interval < 5.0 else 'poor'
    }
    
    # Include client-sent timestamp if available for RTT calculation
    if data and isinstance(data, dict) and 'client_timestamp' in data:
        response_data['client_timestamp'] = data['client_timestamp']
    
    await sio.emit('pong', response_data, to=sid)
    session['last_ping_response'] = current_time


@sio.on('request_rover_reconnect')
async def handle_rover_reconnect(sid):
    """Force the backend to drop and re-establish the vehicle link."""
    global is_vehicle_connected

    log_message('Frontend requested rover reconnect', 'INFO')
    await sio.emit('rover_reconnect_ack', {'status': 'success', 'message': 'Reconnect initiated'}, to=sid)

    try:
        bridge = _init_mavros_bridge()
        bridge.close()
    except Exception as exc:
        log_message(f'Error closing MAVROS bridge: {exc}', 'WARNING')

    is_vehicle_connected = False
    current_state.last_heartbeat = None
    current_state.signal_strength = 'No Link'
    log_message('Flagged vehicle connection as lost; will retry', 'INFO')
    await sio.emit('connection_status', {
        'status': 'WAITING_FOR_ROVER',
        'message': 'Reconnect requested by operator'
    })


@sio.on('subscribe_mission_status')
async def handle_subscribe_mission_status(sid):
    """Handle frontend subscription to mission status updates"""
    try:
        global latest_mission_status, mission_status_history

        # PHASE 2 FIX: Send status history on subscription for frontend sync
        if mission_status_history:
            await sio.emit('mission_status_history', {
                'success': True,
                'history': list(mission_status_history)
            }, to=sid)
            log_message(f"Sent {len(mission_status_history)} cached status messages to client", event_type='mission')

        # Send current status immediately if available
        if latest_mission_status:
            await sio.emit('mission_status', latest_mission_status, to=sid)

        # Send confirmation
        await sio.emit('mission_status_subscribed', {
            'success': True,
            'message': 'Subscribed to mission status updates'
        }, to=sid)

        log_message("Client subscribed to mission status", event_type='mission')

    except Exception as e:
        log_message(f"Mission status subscription error: {e}", "ERROR", event_type='mission')
        await sio.emit('mission_status_subscribed', {
            'success': False,
            'error': str(e)
        }, to=sid)


@sio.on('get_mission_status')
async def handle_get_mission_status(sid):
    """Handle real-time mission status request via WebSocket"""
    try:
        global mission_controller, latest_mission_status
        if mission_controller:
            status = mission_controller.get_status()
            await sio.emit('mission_status_response', {
                'success': True,
                'status': status,
                'latest_update': latest_mission_status
            }, to=sid)
        else:
            await sio.emit('mission_status_response', {
                'success': False,
                'error': 'Mission controller not available'
            }, to=sid)
            
    except Exception as e:
        log_message(f"Mission status request error: {e}", "ERROR", event_type='mission')
        await sio.emit('mission_status_response', {
            'success': False,
            'error': str(e)
        }, to=sid)


@sio.on('send_command')
async def handle_command(sid, data, ack_callback=None):
    """Handle incoming commands from the frontend with acknowledgment support."""
    try:
        _require_vehicle_bridge()
    except Exception as exc:
        log_message("Command rejected - vehicle not connected", "ERROR", event_type='ui_request')
        payload = {'status': 'error', 'message': str(exc), 'acked': True}
        
        # Send acknowledgment if callback provided
        if ack_callback:
            ack_callback(payload)
        else:
            await sio.emit('command_response', payload, to=sid)
        
        record_activity(
            "Socket command rejected - vehicle not connected",
            level='ERROR',
            event_type='server_response',
            meta={'reason': str(exc)}
        )
        return

    command_type = data.get('command')
    log_message(f"Received command: {command_type}", event_type='ui_request')
    record_activity(
       
        event_type='ui_request',
        meta={
            'command': command_type,
            'payload_keys': sorted(list(data.keys()))[:10] if isinstance(data, dict) else None
        }
    )

    handler = COMMAND_HANDLERS.get(command_type)
# ---------------------------------------------------------------------------
    if not handler:
        log_message(f"Unknown command: {command_type}", "ERROR", event_type='ui_request')
        payload = {
            'status': 'error',
            'message': f'Unknown command: {command_type}',
            'acked': True
        }
        
        if ack_callback:
            ack_callback(payload)
        else:
            await sio.emit('command_response', payload, to=sid)
        
        record_activity(
            f"Unknown command received: {command_type}",
            level='ERROR',
            event_type='server_response',
            meta={'command': command_type}
        )
        return

    try:
        # Run blocking command handlers in a thread pool to avoid freezing
        # the asyncio event loop (bridge calls like arm/set_mode/push_waypoints
        # can block for seconds via roslibpy service calls).
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, handler, data)
        response_payload = None

        if isinstance(result, dict):
            response_payload = {**result, 'acked': True}
            record_activity(
                f"Socket command '{command_type}' processed",
                event_type='server_response',
                meta={'command': command_type, 'response': _make_json_safe(result)}
            )
        elif isinstance(result, str):
            response_payload = {'status': 'success', 'message': result, 'acked': True}
            record_activity(
                f"Socket command '{command_type}' processed",
                event_type='server_response',
                meta={'command': command_type, 'message': result}
            )
        else:
            response_payload = {'status': 'success', 'message': f"{command_type} dispatched", 'acked': True}
            record_activity(
                f"Socket command '{command_type}' processed",
                event_type='server_response',
                meta={'command': command_type, 'message': response_payload['message']}
            )
        
        # Send acknowledgment
        if ack_callback:
            ack_callback(response_payload)
        else:
            await sio.emit('command_response', response_payload, to=sid)
            
    except Exception as e:
        log_message(f"Command error ({command_type}): {e}", "ERROR", event_type='server_response')
        payload = {
            'status': 'error',
            'message': str(e),
            'command': command_type,
            'acked': True
        }
        
        if ack_callback:
            ack_callback(payload)
        else:
            await sio.emit('command_response', payload, to=sid)
        
        record_activity(
            f"Socket command '{command_type}' failed",
            level='ERROR',
            event_type='server_response',
            meta=_make_json_safe(payload)
        )

# ---------------------------------------------------------------------------
# Testing / dev helpers
# ---------------------------------------------------------------------------
@sio.on('inject_mavros_telemetry')
async def handle_inject_mavros_telemetry(sid, data):
    """Inject a MAVROS-like telemetry payload into the server for testing.

    Use with care: this is intended for local testing only (development).
    Emits a short ack and triggers the usual telemetry merge/emit path.
    """
    try:
        # Accept either full envelope or a partial payload
        _handle_mavros_telemetry(data)
        await sio.emit('inject_ack', {'status': 'ok'}, to=sid)
    except Exception as exc:
        log_message(f"inject_mavros_telemetry failed: {exc}", 'ERROR')
        try:
            await sio.emit('inject_ack', {'status': 'error', 'error': str(exc)}, to=sid)
        except Exception:
            pass


# ============================================================================
# MANUAL CONTROL SOCKET.IO HANDLERS
# ============================================================================

@sio.on('manual_control')
async def handle_manual_control(sid, data, ack_callback=None):
    """
    Handle real-time manual control from dual joystick interface.

    Delegates to ManualControlHandler for all processing.
    """
    try:
        # Check if handler available
        if manual_control_handler is None:
            error = {'status': 'error', 'message': 'Manual control not available', 'acked': True}
            if ack_callback:
                ack_callback(error)
            else:
                await sio.emit('manual_control_error', error, to=sid)
            return

        # Require MAVROS connection
        _require_vehicle_bridge()

        # Delegate to handler (run in executor — start_session() can block on
        # bridge.set_mode/arm calls; subsequent commands are fast but we keep
        # them off the event loop for safety).
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, manual_control_handler.handle_command, data)

        # Handle response
        if result['status'] == 'success':
            # Acknowledge (throttled - every 10th command)
            if ack_callback and (int(time.time() * 20) % 10 == 0):
                ack_callback(result)

            # Log (throttled to 1/sec)
            if int(time.time()) % 1 == 0:
                record_activity(
                    f"Manual control: PWM L={result.get('left_pwm')} R={result.get('right_pwm')}",
                    event_type='manual_control'
                )

        elif result['status'] == 'error':
            error = {**result, 'acked': True}
            if ack_callback:
                ack_callback(error)
            else:
                await sio.emit('manual_control_error', error, to=sid)

        elif result['status'] == 'dropped':
            # Silently dropped due to rate limit
            pass

    except Exception as e:
        log_message(f"Manual control error: {e}", "ERROR", event_type='manual_control')
        error = {'status': 'error', 'message': str(e), 'acked': True}
        if ack_callback:
            ack_callback(error)
        else:
            await sio.emit('manual_control_error', error, to=sid)


@sio.on('emergency_stop')
async def handle_emergency_stop(sid, data=None, ack_callback=None):
    """Emergency stop - immediately halt motors and switch to HOLD."""
    try:
        log_message("EMERGENCY STOP activated", "WARNING", event_type='manual_control')

        if manual_control_handler:
            manual_control_handler.emergency_stop()

        # Notify frontend
        await sio.emit('manual_control_stopped', {
            'reason': 'emergency_stop',
            'timestamp': time.time()
        })

        response = {'status': 'success', 'message': 'Emergency stop activated', 'acked': True}
        if ack_callback:
            ack_callback(response)
        else:
            await sio.emit('command_response', response, to=sid)

        record_activity("Emergency stop activated", level='WARNING', event_type='manual_control')

    except Exception as e:
        log_message(f"Emergency stop error: {e}", "ERROR")
        if ack_callback:
            ack_callback({'status': 'error', 'message': str(e), 'acked': True})


@sio.on('stop_manual_control')
async def handle_stop_manual_control(sid, data=None, ack_callback=None):
    """Gracefully stop manual control session."""
    try:
        if manual_control_handler:
            manual_control_handler.stop_session(reason="user_request")

        response = {'status': 'success', 'message': 'Manual control stopped', 'acked': True}
        if ack_callback:
            ack_callback(response)
        else:
            await sio.emit('command_response', response, to=sid)

    except Exception as e:
        log_message(f"Stop error: {e}", "ERROR")
        if ack_callback:
            ack_callback({'status': 'error', 'message': str(e), 'acked': True})


# ============================================================================
# GPS FAILSAFE EVENT HANDLERS
# ============================================================================

@sio.on('set_gps_failsafe_mode')
async def handle_set_gps_failsafe_mode(sid, data):
    """Set GPS failsafe mode: 'disable', 'strict', or 'relax'."""
    try:
        mode = data.get('mode', 'disable')
        
        log_message(f"🎛 FAILSAFE MODE REQUEST: {mode}", "INFO", event_type='gps_failsafe')
        
        if mode not in ['disable', 'strict', 'relax']:
            log_message(f"❌ Invalid failsafe mode: {mode}", "ERROR", event_type='gps_failsafe')
            await sio.emit('failsafe_error', {'message': f'Invalid mode: {mode}'}, to=sid)
            return
        
        # Update current state
        current_state.gps_failsafe_mode = mode
        log_message(f"✅ Updated current_state.gps_failsafe_mode to: {mode}", "INFO", event_type='gps_failsafe')

        # Save to config file for persistence across restarts
        save_system_setting('gps_failsafe_mode', mode)

        # Update mission controller if running
        if mission_controller:
            result = mission_controller.set_failsafe_mode(mode)
            log_message(f"✅ Mission controller mode set: {result}", "INFO", event_type='gps_failsafe')
        else:
            log_message(f"⚠ Mission controller not available (not yet initialized)", "WARNING", event_type='gps_failsafe')

        log_message(f"GPS failsafe mode set to: {mode}", "INFO", event_type='gps_failsafe')
        record_activity(f"GPS failsafe mode changed to {mode}", level='INFO', event_type='gps_failsafe')
        
        # Emit confirmation to frontend
        await sio.emit('failsafe_mode_changed', {
            'mode': mode,
            'timestamp': time.time(),
            'message': f'Failsafe mode set to {mode.upper()}'
        })
        
    except Exception as e:
        log_message(f"Set failsafe mode error: {e}", "ERROR", event_type='gps_failsafe')
        await sio.emit('failsafe_error', {'message': str(e)}, to=sid)

@sio.on('request_gps_failsafe_mode')
async def handle_request_gps_failsafe_mode(sid, data=None):
    """Send current GPS failsafe mode to requesting client."""
    try:
        log_message(f"📡 Client {sid} requested current GPS failsafe mode", "INFO", event_type='gps_failsafe')
        await sio.emit('failsafe_mode_changed', {
            'mode': current_state.gps_failsafe_mode,
            'timestamp': time.time(),
            'message': f'Current failsafe mode: {current_state.gps_failsafe_mode.upper()}'
        }, to=sid)
        log_message(f"✅ Sent GPS failsafe mode to client {sid}: {current_state.gps_failsafe_mode}", "INFO", event_type='gps_failsafe')
    except Exception as e:
        log_message(f"Request failsafe mode error: {e}", "ERROR", event_type='gps_failsafe')


@sio.on('set_obstacle_detection')
async def handle_set_obstacle_detection(sid, data):
    """Enable or disable ultrasonic obstacle detection pause logic."""
    try:
        enabled = bool(data.get('enabled', False))

        log_message(f"Obstacle detection {'ENABLED' if enabled else 'DISABLED'}", "INFO", event_type='obstacle')

        # Save to config file for persistence across restarts
        save_system_setting('obstacle_detection_enabled', enabled)

        if mission_controller:
            result = mission_controller.set_obstacle_detection(enabled)
            log_message(f"Obstacle detection set: {result}", "INFO", event_type='obstacle')
        else:
            log_message("Mission controller not available", "WARNING", event_type='obstacle')

        await sio.emit('obstacle_detection_changed', {
            'enabled': enabled,
            'timestamp': time.time(),
        })

        # Voice: Confirm obstacle detection toggle
        try:
            _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
            if enabled:
                _obs_msgs = {
                    "en": "Obstacle detection enabled.",
                    "ta": "தடை கண்டறிதல் இயக்கப்பட்டது.",
                    "hi": "बाधा पहचान सक्रिय.",
                }
            else:
                _obs_msgs = {
                    "en": "Obstacle detection disabled.",
                    "ta": "தடை கண்டறிதல் நிறுத்தப்பட்டது.",
                    "hi": "बाधा पहचान निष्क्रिय.",
                }
            tts.speak(_obs_msgs.get(_lang, _obs_msgs["en"]))
            print(f"[TTS] {_obs_msgs.get(_lang, _obs_msgs['en'])}", flush=True)
        except Exception:
            pass

    except Exception as e:
        log_message(f"Set obstacle detection error: {e}", "ERROR", event_type='obstacle')
        await sio.emit('obstacle_error', {'message': str(e)}, to=sid)


@sio.on("set_led_controller")
async def handle_set_led_controller(sid, data):
    """Enable or disable LED controller."""
    global led_enabled

    try:
        enabled = data.get("enabled")

        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")

        log_message(
            f"LED controller {'ENABLED' if enabled else 'DISABLED'}",
            "INFO",
            event_type="led"
        )

        # Persist config
        save_system_setting("led_enabled", enabled)

        led_enabled = enabled

        if led_controller:
            if enabled:
                current_state_val = getattr(
                    mission_controller,
                    "mission_state",
                    None
                )
                if current_state_val:
                    led_controller.update_state(str(current_state_val.value))
                else:
                    led_controller.update_state("idle")
            else:
                led_controller._send_off()

        await sio.emit(
            "led_controller_changed",
            {
                "enabled": enabled,
                "timestamp": time.time(),
            }
        )

    except Exception as e:
        log_message(
            f"LED controller set error: {e}",
            "ERROR",
            event_type="led"
        )

        await sio.emit(
            "led_error",
            {
                "message": str(e),
                "timestamp": time.time(),
            },
            to=sid
        )


@sio.on('failsafe_acknowledge')
async def handle_failsafe_acknowledge(sid, data=None):
    """Acknowledge GPS failsafe trigger (strict mode only)."""
    try:
        if mission_controller:
            mission_controller.acknowledge_failsafe()
        
        log_message("User acknowledged GPS failsafe trigger", "INFO", event_type='gps_failsafe')
        record_activity("User acknowledged GPS failsafe", level='INFO', event_type='gps_failsafe')
        
        await sio.emit('failsafe_acknowledged', {
            'timestamp': time.time(),
            'message': 'Failsafe acknowledged - starting stable window timer'
        })
        
    except Exception as e:
        log_message(f"Failsafe acknowledge error: {e}", "ERROR")
        await sio.emit('failsafe_error', {'message': str(e)}, to=sid)


@sio.on('failsafe_resume_mission')
async def handle_failsafe_resume_mission(sid, data=None):
    """Resume mission after GPS failsafe (strict mode - after stable window)."""
    try:
        if not mission_controller:
            await sio.emit('failsafe_error', {'message': 'Mission controller not available'}, to=sid)
            return
        
        # Mission controller will handle resuming from current waypoint
        mission_controller.acknowledge_failsafe()
        
        log_message("User resumed mission after GPS failsafe", "INFO", event_type='gps_failsafe')
        record_activity("Mission resumed after GPS failsafe", level='INFO', event_type='gps_failsafe')
        
        await sio.emit('failsafe_resumed', {
            'timestamp': time.time(),
            'message': 'Mission resumed from current waypoint'
        })
        
    except Exception as e:
        log_message(f"Failsafe resume error: {e}", "ERROR")
        await sio.emit('failsafe_error', {'message': str(e)}, to=sid)


@sio.on('failsafe_restart_mission')
async def handle_failsafe_restart_mission(sid, data=None):
    """Restart mission from beginning (strict mode option)."""
    try:
        if not mission_controller:
            await sio.emit('failsafe_error', {'message': 'Mission controller not available'}, to=sid)
            return
        
        # Stop current mission and restart from waypoint 1
        # Use run_in_executor to avoid blocking the async event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, mission_controller.stop_mission)
        await loop.run_in_executor(None, mission_controller.start_mission)
        
        log_message("User restarted mission after GPS failsafe", "INFO", event_type='gps_failsafe')
        record_activity("Mission restarted after GPS failsafe", level='INFO', event_type='gps_failsafe')
        
        await sio.emit('failsafe_restarted', {
            'timestamp': time.time(),
            'message': 'Mission restarted from waypoint 1'
        })
        
    except Exception as e:
        log_message(f"Failsafe restart error: {e}", "ERROR")
        await sio.emit('failsafe_error', {'message': str(e)}, to=sid)


# ============================================================================
# ROOT & HEALTH ENDPOINTS
# ============================================================================

@app.get('/')
async def root():
    """Root endpoint - returns server status and available endpoints."""
    return {
        'status': 'online',
        'message': 'NRP Rover Backend Server',
        'version': '1.0',
        'ros_available': ROS_AVAILABLE,
        'endpoints': {
            'health': '/api/health',
            'rover_data': '/api/rover-data'
        }
    }

@app.get("/api/ping")
async def api_ping():
    """Ping endpoint for rover connectivity verification after beacon discovery."""
    return JSONResponse({
        "status": "ok",
        "rover_id": os.environ.get('ROVER_ID', socket.gethostname()),
        "rover_name": os.environ.get('ROVER_NAME', 'Rover'),
        "timestamp": time.time()
    })

@app.get("/monitor")
def monitor_dashboard(request: Request):
    """Serve the activity monitor page from a template file.

    The large HTML previously embedded in `MONITOR_PAGE_HTML` has been moved to
    `Backend/templates/monitor.html` and is rendered here via FastAPI's
    template response.
    """
    return templates.TemplateResponse("monitor.html", {"request": request})


@app.get("/node/{node_name}")
def node_details(node_name: str, request: Request):
    """Serve the node details page."""
    return templates.TemplateResponse("node_details.html", {"request": request, "node_name": node_name})


# ============================================================================
# ERROR HANDLERS
# ============================================================================

def _http_success(message: str | None = None, status: int = 200, **extra):
    payload = {'success': True}
    if message:
        payload['message'] = message
    payload.update(extra)
    return JSONResponse(payload, status_code=status)


def _http_error(message: str, status: int = 400, **extra):
    payload = {'success': False, 'message': message}
    payload.update(extra)
    return JSONResponse(payload, status_code=status)


@app.get("/api/activity")
def api_activity_feed(request: Request):
    """Return recent backend activity entries with optional filtering."""
    try:
        limit = int(request.query_params.get('limit', 500))
    except Exception:
        limit = 500
    limit = max(1, min(limit, ACTIVITY_LOG_MAX))
    event_filter = request.query_params.get('event')

    with _activity_log_lock:
        entries = list(activity_log)

    if event_filter:
        entries = [entry for entry in entries if entry.get('event') == event_filter]

    if len(entries) > limit:
        entries = entries[-limit:]

    return {
        'entries': entries,
        'returned': len(entries),
        'total': len(activity_log),
    }


@app.get("/api/activity/types")
def api_activity_types():
    """Expose the set of known activity event types."""
    with _activity_log_lock:
        events = sorted({entry.get('event', 'general') for entry in activity_log})
    return {'events': events, 'count': len(events)}


@app.get("/api/activity/download")
def api_activity_download():
    """Provide a text download of the current activity log."""
    with _activity_log_lock:
        entries = list(activity_log)

    lines: list[str] = []
    for entry in entries:
        iso = entry.get('isoTime') or time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(entry.get('timestamp', time.time())))
        level = entry.get('level', 'INFO')
        event = entry.get('event', 'general')
        message = entry.get('message', '')
        meta = entry.get('meta')
        meta_str = ''
        if meta not in (None, '', {}):
            try:
                meta_str = json.dumps(meta, ensure_ascii=True)
            except Exception:
                meta_str = str(meta)
        line = f"[{iso}] [{level}] ({event}) {message}"
        if meta_str:
            line = f"{line} | meta={meta_str}"
        lines.append(line)

    payload = "\n".join(lines)
    headers = {
        'Content-Disposition': 'attachment; filename=\"nrp-activity.log\"'
    }
    return FastAPIResponse(content=payload, media_type='text/plain', headers=headers)


@app.post("/api/arm")
async def api_arm_vehicle(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    arm_value = bool(body.get('value', body.get('arm', True)))
    try:
        with _suppress_disconnect_during_bridge_call():
            result = _handle_arm_disarm({'arm': arm_value})
        message = result.get('message') if isinstance(result, dict) else None
        return _http_success(message or "Arm command dispatched")
    except Exception as exc:
        log_message(f"/api/arm error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/set_mode")
async def api_set_mode(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = str(body.get('mode') or '').strip()
    if not mode:
        return _http_error("Missing mode", 400)
    try:
        with _suppress_disconnect_during_bridge_call():
            result = _handle_set_mode({'mode': mode})
        message = result.get('message') if isinstance(result, dict) else None
        return _http_success(message or f"Mode change requested: {mode}")
    except Exception as exc:
        log_message(f"/api/set_mode error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/upload")
async def api_mission_upload(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    waypoints = body.get('waypoints')
    if not isinstance(waypoints, list) or not waypoints:
        return _http_error("No waypoints provided", 400)
    payload = {
        'waypoints': waypoints,
        'servoConfig': body.get('servoConfig'),
    }
    try:
        with _suppress_disconnect_during_bridge_call():
            result = _handle_upload_mission(payload)
        message = result.get('message') if isinstance(result, dict) else None
        count = len(waypoints)
        return _http_success(message or f"Mission upload queued ({count} waypoints)", count=count)
    except Exception as exc:
        log_message(f"/api/mission/upload error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.get("/api/mission/download")
def api_mission_download():
    try:
        with _suppress_disconnect_during_bridge_call():
            result = _handle_get_mission({})
        waypoints = result.get('waypoints', []) if isinstance(result, dict) else []
        message = result.get('message') if isinstance(result, dict) else None
        return _http_success(message or f"Mission retrieved ({len(waypoints)} waypoints)", waypoints=waypoints)
    except Exception as exc:
        log_message(f"/api/mission/download error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/clear")
def api_mission_clear():
    try:
        with _suppress_disconnect_during_bridge_call():
            result = _handle_clear_mission({})
        message = result.get('message') if isinstance(result, dict) else None
        return _http_success(message or "Mission cleared")
    except Exception as exc:
        log_message(f"/api/mission/clear error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/set_current")
async def api_mission_set_current(request: Request):
    """
    Set the current mission waypoint (skip to specific waypoint).

    Expected JSON body:
    {
        "wp_seq": 5  // 0-based waypoint sequence number
    }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    wp_seq = body.get('wp_seq')
    
    if wp_seq is None:
        return _http_error("Missing wp_seq parameter", 400)
    
    try:
        wp_seq_int = int(wp_seq)
        if wp_seq_int < 0:
            return _http_error("wp_seq must be >= 0", 400)
        
        bridge = _require_vehicle_bridge()
        response = bridge.set_current_waypoint(wp_seq_int)
        
        log_message(f"[MISSION] Set current waypoint to {wp_seq_int}", "INFO")
        
        return _http_success(
            f"Current waypoint set to {wp_seq_int}",
            wp_seq=wp_seq_int
        )
    except Exception as exc:
        log_message(f"/api/mission/set_current error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/resume_deprecated")
def api_mission_resume():
    """
    Resume mission execution by switching to AUTO mode (DEPRECATED - use controller).
    """
    try:
        with _suppress_disconnect_during_bridge_call():
            bridge = _require_vehicle_bridge()
            # Switch to AUTO mode to resume mission (DEPRECATED - use controller)
            response = bridge.set_mode(mode="AUTO")

        log_message("[MISSION] Mission resumed (switched to AUTO mode)", "INFO")
        _record_mission_event("Mission resumed", status='MISSION_RESUMED')

        return _http_success("Mission resumed (AUTO mode)")
    except Exception as exc:
        log_message(f"/api/mission/resume error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.get("/api/mission/config")
def api_mission_config():
    """
    Return full mission controller configuration (mission_controller section) from
    the mission_controller_config.json file.
    """
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
        if not os.path.exists(config_file):
            return _http_error("Configuration file not found", 404)
        with open(config_file, 'r') as f:
            config = json.load(f)
        mc = config.get('mission_controller', {})
        return _http_success(mc)
    except Exception as exc:
        log_message(f"/api/mission/config error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/config")
async def api_mission_config_update(request: Request):
    """
    Update mission controller servo configuration and timing parameters.

    RESPONSIBILITY: Servo & Timer Configuration ONLY
    - Updates servo channel, PWM values, spray timing, GPS timeout, mode
    - Applies to currently loaded mission (if any)
    - Does NOT handle waypoint loading

    Expected JSON body:
    {
        "servo_channel": 10,
        "servo_pwm_start": 1500,
        "servo_pwm_stop": 1100,
        "spray_duration": 5.0,
        "delay_before_spray": 1.0,
        "delay_after_spray": 1.0,
        "gps_timeout": 30.0,
        "auto_mode": true
    }
    """
    global current_mission
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        
        # Validate required servo/timer parameters
        required_params = ['servo_channel', 'servo_pwm_start', 'servo_pwm_stop', 
                          'spray_duration', 'delay_before_spray', 'delay_after_spray', 
                          'gps_timeout', 'auto_mode']
        
        for param in required_params:
            if param not in body:
                return _http_error(f"Missing required parameter: {param}", 400)
        
        # Reject waypoint data if included (wrong endpoint)
        if 'waypoints' in body:
            return _http_error("Waypoints should not be included in /api/mission/config. Use /api/mission/load instead.", 400)
        
        # Load existing config
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
        
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
        else:
            config = {
                "mission_controller": {
                    "sprayer_parameters": {},
                    "mission_parameters": {
                        "waypoint_reach_threshold": 2.0,
                        "max_retry_attempts": 3,
                        "retry_delay": 5.0,
                        "status_update_interval": 1.0
                    },
                    "safety_parameters": {
                        "max_speed": 5.0,
                        "emergency_stop_enabled": True,
                        "low_battery_threshold": 20.0,
                        "connection_timeout": 10.0
                    }
                },
                "metadata": {
                    "version": "1.0",
                    "last_updated": "2025-11-10",
                    "description": "Mission controller configuration for NRP ROS spraying system"
                }
            }
        
        # Update ONLY sprayer parameters (servo & timing)
        config['mission_controller']['sprayer_parameters'] = body
        config['metadata']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Save config to file
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        log_message("Servo config saved to file", "INFO")
        
        # Send load_mission command to mission controller with updated config
        try:
            bridge = _require_vehicle_bridge()
            
            # Send command only if there are waypoints loaded
            if current_mission and len(current_mission) > 0:
                load_mission_data = {
                    'command': 'load_mission',
                    'waypoints': current_mission,
                    'config': body
                }
                
                if hasattr(bridge, 'publish_mission_command'):
                    bridge.publish_mission_command(load_mission_data)
                    log_message(f"Sent load_mission command with updated servo config to mission controller", "INFO")
                else:
                    log_message("Warning: publish_mission_command not available, config saved but not applied", "WARNING")
            else:
                log_message("No mission waypoints loaded, config saved but not sent to mission controller", "INFO")
                
        except Exception as e:
            # Config was saved successfully, log warning but don't fail the request
            log_message(f"Warning: Config saved but failed to send command to mission controller: {e}", "WARNING")
        
        return _http_success("Servo config updated (applies to current mission)")
        
    except Exception as exc:
        log_message(f"/api/mission/config POST error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/load")
async def api_mission_load(request: Request):
    """
    Load waypoints to the mission controller.

    RESPONSIBILITY: Waypoint Loading ONLY
    - Accepts waypoint list with lat/lng coordinates
    - Updates current_mission global variable
    - Sends load_mission command with waypoints to mission controller
    - Does NOT handle servo configuration (use /api/mission/config for that)
    - Can optionally apply servo modes based on waypoint attributes

    Expected JSON body:
    {
      "waypoints": [
        {"lat": 13.071922, "lng": 80.2619957},
        {"lat": 13.072000, "lng": 80.2620000}
      ]
    }

    Note: servoConfig field (if included) is for backward compatibility only.
          New implementations should use /api/mission/config endpoint.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    waypoints = body.get('waypoints')
    if not isinstance(waypoints, list) or not waypoints:
        return _http_error("No waypoints provided", 400)

    # Validate required fields for waypoints
    for wp in waypoints:
        if not all(k in wp for k in ['lat', 'lng']):
            return _http_error(f"Waypoint missing required fields (lat, lng): {wp}", 400)

    try:
        bridge = _require_vehicle_bridge()

        # Optional: Apply servo modes based on waypoint data (backward compatibility)
        servo_config = body.get('servoConfig')
        if servo_config:
            log_message(f"[mission_load] Applying servo mode: {servo_config.get('mode')}", "INFO")
            waypoints = apply_servo_modes(waypoints, servo_config)

        mission_count = len(waypoints)
        
        # Prepare load_mission command with waypoints
        # Config will be applied separately via /api/mission/config
        load_mission_data = {
            'command': 'load_mission',
            'waypoints': waypoints,
            'config': servo_config or {}
        }

        # Use integrated mission controller
        global mission_controller, current_mission
        
        if not mission_controller:
            return _http_error("Mission controller not initialized", 503)
        
        result = mission_controller.process_command(load_mission_data)
        
        if result.get('success', False):
            # Update local mission state for consistency
            current_mission = list(waypoints)
            _record_mission_event(f"Mission loaded to controller ({mission_count} waypoints)", status='MISSION_LOADED')
            log_message(f"Mission loaded to controller ({mission_count} waypoints)", "INFO")
            return _http_success(f"Mission loaded to controller ({mission_count} waypoints)")
        else:
            error_msg = result.get('error', 'Unknown error')
            return _http_error(error_msg, 400)
            
    except Exception as exc:
        log_message(f"/api/mission/load error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


def _publish_controller_cmd_or_error(cmd: dict):
    """Helper to process mission command via integrated controller or return an error tuple."""
    global mission_controller
    
    try:
        if not mission_controller:
            return None, _http_error("Mission controller not initialized", 503)
        
        # Process command through integrated controller
        result = mission_controller.process_command(cmd)
        
        if result.get('success', False):
            log_message(f"Mission command '{cmd.get('command')}' executed successfully", "INFO", event_type='mission')
            return True, None
        else:
            error_msg = result.get('error', 'Unknown error')
            log_message(f"Mission command '{cmd.get('command')}' failed: {error_msg}", "WARNING", event_type='mission')
            return None, _http_error(error_msg, 400)
        
    except Exception as exc:
        error_msg = f"Mission command error: {str(exc)}"
        log_message(error_msg, "ERROR", event_type='mission')
        return None, _http_error(error_msg, 500)


@app.post("/api/mission/start")
def api_mission_start():
    try:
        ok, err = _publish_controller_cmd_or_error({'command': 'start'})
        if err:
            return err
        _record_mission_event('Mission controller started', status='MISSION_STARTED')
        return _http_success('Mission controller started')
    except Exception as exc:
        log_message(f"/api/mission/start error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.get("/api/mission/start")
def api_mission_start_get():
    """Inform clients that POST must be used to start missions."""
    return _http_error("Method not allowed: use POST /api/mission/start to start missions", 405)


@app.post("/api/mission/stop")
def api_mission_stop():
    try:
        ok, err = _publish_controller_cmd_or_error({'command': 'stop'})
        if err:
            return err
        _record_mission_event('Mission controller stopped', status='MISSION_STOPPED')
        return _http_success('Mission controller stopped')
    except Exception as exc:
        log_message(f"/api/mission/stop error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/servo_config")
async def api_mission_servo_config(request: Request):
    """
    Update servo configuration dynamically without reloading mission.

    Expected JSON body:
    {
        "servo_channel": 9,  // optional
        "servo_pwm_on": 600,  // optional
        "servo_pwm_off": 1000,  // optional
        "servo_delay_before": 0.0,  // optional - delay BEFORE turning servo ON
        "servo_spray_duration": 0.5,  // optional - time between ON and OFF
        "servo_delay_after": 2.0,  // optional - delay AFTER turning servo OFF
        "servo_enabled": true  // optional
    }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    if not body:
        return _http_error("No configuration provided", 400)
    
    try:
        global mission_controller
        if not mission_controller:
            return _http_error("Mission controller not initialized", 500)
        
        result = mission_controller.update_servo_config(body)
        
        if result.get('success'):
            log_message(f"Servo config updated: {result.get('updated_params', [])}", "INFO")
            
            # Persist changes to config file for persistence across restarts
            try:
                config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
                
                # Load existing config
                if os.path.exists(config_file):
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                else:
                    config = {
                        "mission_controller": {
                            "sprayer_parameters": {},
                            "mission_parameters": {},
                            "safety_parameters": {}
                        },
                        "system_settings": {},
                        "metadata": {
                            "version": "1.0",
                            "last_updated": "",
                            "description": "Mission controller configuration"
                        }
                    }
                
                # Update servo parameters in config
                if 'sprayer_parameters' not in config.get('mission_controller', {}):
                    config['mission_controller']['sprayer_parameters'] = {}
                
                config['mission_controller']['sprayer_parameters'].update(body)
                config['metadata']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Save config to file
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=2)
                
                log_message("Servo config persisted to mission_controller_config.json", "INFO")
            except Exception as e:
                log_message(f"Warning: Failed to persist servo config to file: {e}", "WARNING")
                # Don't fail the request - in-memory config is still updated
            
            return _http_success(
                result.get('message', 'Servo configuration updated'),
                updated_params=result.get('updated_params', [])
            )
        else:
            return _http_error(result.get('error', 'Unknown error'), 400)
            
    except Exception as exc:
        log_message(f"/api/mission/servo_config error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.get("/api/mission/servo_config")
def api_mission_servo_config_get():
    """
    Get current servo configuration.
    """
    try:
        global mission_controller
        if not mission_controller:
            return _http_error("Mission controller not initialized", 500)
        
        config = {
            'servo_channel': mission_controller.servo_channel,
            'servo_pwm_on': mission_controller.servo_pwm_on,
            'servo_pwm_off': mission_controller.servo_pwm_off,
            'servo_delay_before': mission_controller.servo_delay_before,
            'servo_spray_duration': mission_controller.servo_spray_duration,
            'servo_delay_after': mission_controller.servo_delay_after,
            'servo_enabled': mission_controller.servo_enabled
        }
        
        return _http_success(config)
            
    except Exception as exc:
        log_message(f"/api/mission/servo_config GET error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/servo_config/test")
async def api_mission_servo_config_test(request: Request):
    """
    Test servo configuration temporarily without saving to config file.
    Executes one spray cycle and returns pass/fail result.
    
    Request Body:
    {
        "servo_channel": 9,           // Servo channel (1-16)
        "servo_pwm_on": 1900,         // PWM when ON (0-4000)
        "servo_pwm_off": 1100,        // PWM when OFF (0-4000)
        "servo_delay_before": 0.7,    // Delay before spray (0-30s)
        "servo_spray_duration": 6.0,  // Spray duration (0-30s)
        "servo_delay_after": 3.1      // Delay after spray (0-30s)
    }
    
    Response (success):
    {
        "success": true,
        "message": "Test PASSED - Servo cycle completed successfully",
        "status": "pass"
    }
    
    Response (failure):
    {
        "success": false,
        "message": "Test FAILED - [specific error]",
        "status": "fail",
        "error": "Detailed error message"
    }
    """
    try:
        # Parse request body
        try:
            body = await request.json()
        except Exception:
            body = {}
        
        if not body:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Test FAILED - No configuration provided",
                    "status": "fail",
                    "error": "Request body is required"
                }
            )
        
        global mission_controller, mavros_bridge
        
        # Check if mission controller is initialized
        if not mission_controller:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "message": "Test FAILED - Mission controller not initialized",
                    "status": "fail",
                    "error": "Mission controller not initialized"
                }
            )
        
        # Check if rover is connected
        bridge = None
        if mavros_bridge and hasattr(mavros_bridge, 'is_connected'):
            bridge = mavros_bridge
        else:
            # Try to get bridge from mission controller
            if hasattr(mission_controller, 'bridge'):
                bridge = mission_controller.bridge
        
        if not bridge or not bridge.is_connected:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Test FAILED - Rover not connected",
                    "status": "fail",
                    "error": "Rover not connected"
                }
            )
        
        # Check if mission is active (RUNNING, LOADING, or PAUSED)
        if mission_controller.mission_state in [MissionState.RUNNING, MissionState.LOADING, MissionState.PAUSED]:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Test FAILED - Cannot test during active mission",
                    "status": "fail",
                    "error": "Cannot test during active mission"
                }
            )
        
        # Validate servo channel (1-16)
        servo_channel = body.get('servo_channel')
        if servo_channel is None:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Test FAILED - servo_channel is required",
                    "status": "fail",
                    "error": "servo_channel is required"
                }
            )
        
        try:
            servo_channel = int(servo_channel)
        except (ValueError, TypeError):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Test FAILED - Invalid servo channel",
                    "status": "fail",
                    "error": "Invalid servo channel - must be an integer"
                }
            )
        
        if servo_channel < 1 or servo_channel > 16:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Test FAILED - Invalid servo channel",
                    "status": "fail",
                    "error": "Invalid servo channel - must be between 1 and 16"
                }
            )
        
        # Validate PWM values (1000-2000)
        servo_pwm_on = body.get('servo_pwm_on')
        servo_pwm_off = body.get('servo_pwm_off')
        
        for pwm_val, pwm_name in [(servo_pwm_on, 'servo_pwm_on'), (servo_pwm_off, 'servo_pwm_off')]:
            if pwm_val is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": f"Test FAILED - {pwm_name} is required",
                        "status": "fail",
                        "error": f"{pwm_name} is required"
                    }
                )
            
            try:
                pwm_val = float(pwm_val)
            except (ValueError, TypeError):
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": f"Test FAILED - Invalid {pwm_name}",
                        "status": "fail",
                        "error": f"Invalid {pwm_name} - must be a number"
                    }
                )
            
            if pwm_val < 0 or pwm_val > 4000:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": f"Test FAILED - Invalid {pwm_name}",
                        "status": "fail",
                        "error": f"Invalid {pwm_name} - must be between 0 and 4000"
                    }
                )
        
        # Validate delays (0-30 seconds)
        servo_delay_before = body.get('servo_delay_before', 0)
        servo_spray_duration = body.get('servo_spray_duration', 0.5)
        servo_delay_after = body.get('servo_delay_after', 0)
        
        for delay_val, delay_name in [
            (servo_delay_before, 'servo_delay_before'),
            (servo_spray_duration, 'servo_spray_duration'),
            (servo_delay_after, 'servo_delay_after')
        ]:
            try:
                delay_val = float(delay_val)
            except (ValueError, TypeError):
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": f"Test FAILED - Invalid {delay_name}",
                        "status": "fail",
                        "error": f"Invalid {delay_name} - must be a number"
                    }
                )
            
            if delay_val < 0 or delay_val > 30:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": f"Test FAILED - Invalid {delay_name}",
                        "status": "fail",
                        "error": f"Invalid {delay_name} - must be between 0 and 30 seconds"
                    }
                )
        
        # Store current config
        original_config = {
            'servo_channel': mission_controller.servo_channel,
            'servo_pwm_on': mission_controller.servo_pwm_on,
            'servo_pwm_off': mission_controller.servo_pwm_off,
            'servo_delay_before': mission_controller.servo_delay_before,
            'servo_spray_duration': mission_controller.servo_spray_duration,
            'servo_delay_after': mission_controller.servo_delay_after,
            'servo_enabled': mission_controller.servo_enabled
        }
        
        # Apply test config (temporarily, don't persist)
        mission_controller.servo_channel = servo_channel
        mission_controller.servo_pwm_on = int(servo_pwm_on)
        mission_controller.servo_pwm_off = int(servo_pwm_off)
        mission_controller.servo_delay_before = float(servo_delay_before)
        mission_controller.servo_spray_duration = float(servo_spray_duration)
        mission_controller.servo_delay_after = float(servo_delay_after)
        
        log_message(f"[Servo Test] Applying test config: channel={servo_channel}, pwm_on={servo_pwm_on}, pwm_off={servo_pwm_off}", "INFO")
        log_message(f"[Servo Test] Timing: before={servo_delay_before}s, spray={servo_spray_duration}s, after={servo_delay_after}s", "INFO")
        
        # Execute spray cycle with timeout
        TEST_TIMEOUT = 60  # seconds
        
        try:
            # Use threading with timeout to implement the timeout
            import threading
            
            result = {'success': False, 'error': None}
            
            def execute_spray():
                try:
                    # Execute the spray cycle using the same logic as execute_servo_sequence
                    # Step 1: Wait before delay
                    if mission_controller.servo_delay_before > 0:
                        time.sleep(mission_controller.servo_delay_before)
                    
                    # Step 2: Turn servo ON
                    response_on = bridge.set_servo(mission_controller.servo_channel, mission_controller.servo_pwm_on)
                    if not response_on.get('success'):
                        result['error'] = f"Servo ON command failed: {response_on}"
                        return
                    
                    # Step 3: Wait spray duration
                    time.sleep(mission_controller.servo_spray_duration)
                    
                    # Step 4: Turn servo OFF
                    response_off = bridge.set_servo(mission_controller.servo_channel, mission_controller.servo_pwm_off)
                    if not response_off.get('success'):
                        result['error'] = f"Servo OFF command failed: {response_off}"
                        return
                    
                    # Step 5: Wait delay after spray
                    time.sleep(mission_controller.servo_delay_after)
                    
                    result['success'] = True
                except Exception as e:
                    result['error'] = str(e)
            
            # Run in thread with timeout
            spray_thread = threading.Thread(target=execute_spray)
            spray_thread.daemon = True
            spray_thread.start()
            
            # Use asyncio.wait_for with run_in_executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, spray_thread.join, None),
                    timeout=TEST_TIMEOUT
                )
            except asyncio.TimeoutError:
                # Thread is still running after timeout - ensure it's terminated
                spray_thread.join()  # ensure thread is terminated
                log_message("[Servo Test] Test timeout after 60s", "ERROR")
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": "Test FAILED - Test timeout after 60s",
                        "status": "fail",
                        "error": "Test timeout after 60s"
                    }
                )
            
            if not result['success']:
                error_msg = result['error'] or "Unknown error during spray cycle"
                log_message(f"[Servo Test] Test failed: {error_msg}", "ERROR")
                
                # Restore original config
                mission_controller.servo_channel = original_config['servo_channel']
                mission_controller.servo_pwm_on = original_config['servo_pwm_on']
                mission_controller.servo_pwm_off = original_config['servo_pwm_off']
                mission_controller.servo_delay_before = original_config['servo_delay_before']
                mission_controller.servo_spray_duration = original_config['servo_spray_duration']
                mission_controller.servo_delay_after = original_config['servo_delay_after']
                
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": f"Test FAILED - {error_msg}",
                        "status": "fail",
                        "error": error_msg
                    }
                )
            
            # Test passed - restore original config
            mission_controller.servo_channel = original_config['servo_channel']
            mission_controller.servo_pwm_on = original_config['servo_pwm_on']
            mission_controller.servo_pwm_off = original_config['servo_pwm_off']
            mission_controller.servo_delay_before = original_config['servo_delay_before']
            mission_controller.servo_spray_duration = original_config['servo_spray_duration']
            mission_controller.servo_delay_after = original_config['servo_delay_after']
            
            log_message("[Servo Test] Test PASSED - Servo cycle completed successfully", "INFO")
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Test PASSED - Servo cycle completed successfully",
                    "status": "pass"
                }
            )
            
        except Exception as e:
            # Restore original config on any error
            mission_controller.servo_channel = original_config['servo_channel']
            mission_controller.servo_pwm_on = original_config['servo_pwm_on']
            mission_controller.servo_pwm_off = original_config['servo_pwm_off']
            mission_controller.servo_delay_before = original_config['servo_delay_before']
            mission_controller.servo_spray_duration = original_config['servo_spray_duration']
            mission_controller.servo_delay_after = original_config['servo_delay_after']
            
            log_message(f"/api/mission/servo_config/test error: {e}", "ERROR")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "message": f"Test FAILED - {str(e)}",
                    "status": "fail",
                    "error": str(e)
                }
            )
    
    except Exception as exc:
        log_message(f"/api/mission/servo_config/test unexpected error: {exc}", "ERROR")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Test FAILED - {str(exc)}",
                "status": "fail",
                "error": str(exc)
            }
        )


@app.post("/api/mission/pause")
def api_mission_pause_frontend():
    try:
        ok, err = _publish_controller_cmd_or_error({'command': 'pause'})
        if err:
            return err
        _record_mission_event('Mission paused (controller)', status='MISSION_PAUSED')
        # Voice: Mission paused
        try:
            _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
            _p_msgs = {"en": "Mission paused.", "ta": "பணி நிறுத்தப்பட்டது.", "hi": "मिशन रुक गया."}
            tts.speak(_p_msgs.get(_lang, _p_msgs["en"]))
            print(f"[TTS] {_p_msgs.get(_lang, _p_msgs['en'])}", flush=True)
        except Exception:
            pass
        return _http_success('Mission paused')
    except Exception as exc:
        log_message(f"/api/mission/pause error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/resume")
def api_mission_resume_frontend():
    try:
        ok, err = _publish_controller_cmd_or_error({'command': 'resume'})
        if err:
            return err
        _record_mission_event('Mission resumed (controller)', status='MISSION_RESUMED')
        # Voice: Mission resumed
        try:
            _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
            _r_msgs = {"en": "Mission resumed.", "ta": "பணி மீண்டும் தொடங்கப்பட்டது.", "hi": "मिशन फिर से शुरू."}
            tts.speak(_r_msgs.get(_lang, _r_msgs["en"]))
            print(f"[TTS] {_r_msgs.get(_lang, _r_msgs['en'])}", flush=True)
        except Exception:
            pass
        return _http_success('Mission resumed')
    except Exception as exc:
        log_message(f"/api/mission/resume error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/restart")
def api_mission_restart():
    """
    Restart the mission controller. Prefer explicit 'restart' command; if not
    supported, perform stop then start.
    """
    try:
        # Try restart first
        ok, err = _publish_controller_cmd_or_error({'command': 'restart'})
        if err is None and ok:
            _record_mission_event('Mission controller restarted', status='MISSION_RESTARTED')
            return _http_success('Mission controller restarted')

        # Fallback: stop then start
        _publish_controller_cmd_or_error({'command': 'stop'})
        time.sleep(0.1)
        _publish_controller_cmd_or_error({'command': 'start'})
        _record_mission_event('Mission controller restarted (stop/start)', status='MISSION_RESTARTED')
        return _http_success('Mission controller restarted (stop/start)')
    except Exception as exc:
        log_message(f"/api/mission/restart error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/next")
def api_mission_next():
    """Advance mission controller to the next waypoint/step."""
    try:
        ok, err = _publish_controller_cmd_or_error({'command': 'next'})
        if err:
            return err
        _record_mission_event('Mission controller advanced to next', status='MISSION_NEXT')
        return _http_success('Advanced to next mission step')
    except Exception as exc:
        log_message(f"/api/mission/next error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/mission/skip")
def api_mission_skip():
    """Skip current waypoint and advance to the next waypoint/step."""
    try:
        ok, err = _publish_controller_cmd_or_error({'command': 'skip'})
        if err:
            return err
        _record_mission_event('Mission controller skipped waypoint', status='MISSION_SKIP')
        return _http_success('Skipped to next mission step')
    except Exception as exc:
        log_message(f"/api/mission/skip error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.get("/api/mission/status")
def api_mission_status():
    """Get current mission controller status"""
    try:
        global mission_controller, latest_mission_status
        if mission_controller:
            status = mission_controller.get_status()
            return {
                'success': True,
                'status': status,
                'latest_update': latest_mission_status
            }
        else:
            return JSONResponse({
                'success': False,
                'error': 'Mission controller not available'
            }, status_code=503)

    except Exception as exc:
        log_message(f"Failed to get mission status: {exc}", "ERROR", event_type='mission')
        return JSONResponse({
            'success': False,
            'error': str(exc)
        }, status_code=500)


@app.get("/api/led/status")
async def get_led_status():
    """Get LED controller status."""
    try:
        return {
            "success": True,
            "enabled": led_enabled,
            "state": (
                led_controller._current_state
                if led_controller else "unavailable"
            ),
            "hardware_available": (
                led_controller is not None
                and getattr(led_controller, "spi", None) is not None
            ),
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }


@app.get("/api/mission/mode")
def api_mission_mode_get():
    """Get current mission mode (auto/manual)"""
    try:
        global mission_controller
        if mission_controller:
            status = mission_controller.get_status()
            return {
                'success': True,
                'mode': status.get('mission_mode', 'unknown')
            }
        else:
            return JSONResponse({
                'success': False,
                'error': 'Mission controller not available'
            }, status_code=503)

    except Exception as exc:
        log_message(f"Failed to get mission mode: {exc}", "ERROR", event_type='mission')
        return JSONResponse({
            'success': False,
            'error': str(exc)
        }, status_code=500)


@app.post("/api/mission/mode")
async def api_mission_mode_set(request: Request):
    """Set mission mode (auto/manual)"""
    try:
        global mission_controller
        try:
            data = await request.json()
        except Exception:
            data = {}
        mode = data.get('mode', 'auto').lower()
        
        if mode not in ['auto', 'manual', 'continuous', 'dash']:
            log_message(f"Invalid mission mode requested: {mode}", "WARNING", event_type='mission')
            return JSONResponse({
                'success': False,
                'error': 'Mode must be "auto", "manual", "continuous", or "dash"'
            }, status_code=400)

        if not mission_controller:
            log_message("Mission controller not available for mode change", "ERROR", event_type='mission')
            return JSONResponse({
                'success': False,
                'error': 'Mission controller not available'
            }, status_code=503)

        result = mission_controller.set_mode(mode)

        # Log the result of mode change
        if result.get('success', False):
            log_message(f"Mission mode changed to: {mode.upper()}", "SUCCESS", event_type='mission')
        else:
            log_message(f"Failed to change mission mode to {mode}: {result.get('error')}", "ERROR", event_type='mission')

        return result

    except Exception as exc:
        log_message(f"Failed to set mission mode: {exc}", "ERROR", event_type='mission')
        return JSONResponse({
            'success': False,
            'error': str(exc)
        }, status_code=500)


@app.post("/api/mission/stop_controller")
def api_mission_stop_controller():
    """
    Stop mission execution on the Jetson mission controller node.
    
    This sends a 'stop' command to the ROS mission controller
    to halt autonomous waypoint execution and spraying operations.
    
    The mission controller will return to idle state.
    """
    try:
        bridge = _require_vehicle_bridge()
        
        # Send stop command to mission controller node
        stop_command = {'command': 'stop'}
        
        if hasattr(bridge, 'publish_mission_command'):
            bridge.publish_mission_command(stop_command)
            log_message("Sent stop command to mission controller", "INFO")
            # Voice: Mission stopped
            try:
                _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
                _s_msgs = {"en": "Mission stopped.", "ta": "பணி நிறுத்தப்பட்டது.", "hi": "मिशन रोक दिया गया."}
                tts.speak(_s_msgs.get(_lang, _s_msgs["en"]))
                print(f"[TTS] {_s_msgs.get(_lang, _s_msgs['en'])}", flush=True)
            except Exception:
                pass
            return _http_success("Mission controller stopped")
        else:
            return _http_error("MAVROS bridge not available for mission controller commands", 500)
            
    except Exception as exc:
        log_message(f"/api/mission/stop_controller error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.get("/api/config/sprayer")
def api_get_sprayer_config():
    """
    Get current sprayer configuration parameters for the mission controller.
    
    Returns the current sprayer parameters from the config file.
    """
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
        
        if not os.path.exists(config_file):
            return _http_error("Configuration file not found", 404)
        
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        sprayer_params = config.get('mission_controller', {}).get('sprayer_parameters', {})
        return _http_success(sprayer_params)
        
    except Exception as exc:
        log_message(f"/api/config/sprayer GET error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/config/sprayer")
async def api_save_sprayer_config(request: Request):
    """
    Save sprayer configuration parameters for the mission controller.

    Expected JSON body:
    {
        "servo_channel": 10,
        "servo_pwm_start": 1500,
        "servo_pwm_stop": 1100,
        "spray_duration": 5.0,
        "delay_before_spray": 1.0,
        "delay_after_spray": 1.0,
        "gps_timeout": 30.0,
        "auto_mode": true
    }
    """
    global current_mission
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        
        # Validate required parameters
        required_params = ['servo_channel', 'servo_pwm_start', 'servo_pwm_stop', 
                          'spray_duration', 'delay_before_spray', 'delay_after_spray', 
                          'gps_timeout', 'auto_mode']
        
        for param in required_params:
            if param not in body:
                return _http_error(f"Missing required parameter: {param}", 400)
        
        # Load existing config
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
        
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
        else:
            # Create default config structure if file doesn't exist
            config = {
                "mission_controller": {
                    "sprayer_parameters": {},
                    "mission_parameters": {
                        "waypoint_reach_threshold": 2.0,
                        "max_retry_attempts": 3,
                        "retry_delay": 5.0,
                        "status_update_interval": 1.0
                    },
                    "safety_parameters": {
                        "max_speed": 5.0,
                        "emergency_stop_enabled": True,
                        "low_battery_threshold": 20.0,
                        "connection_timeout": 10.0
                    }
                },
                "metadata": {
                    "version": "1.0",
                    "last_updated": "2025-11-10",
                    "description": "Mission controller configuration for NRP ROS spraying system"
                }
            }
        
        # Update sprayer parameters
        config['mission_controller']['sprayer_parameters'] = body
        config['metadata']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Save config
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        log_message("Sprayer configuration saved", "INFO")
        
        # Send load_mission command to mission controller with updated servo config
        try:
            bridge = _require_vehicle_bridge()
            
            # Send command only if there are waypoints loaded
            if current_mission and len(current_mission) > 0:
                load_mission_data = {
                    'command': 'load_mission',
                    'waypoints': current_mission,
                    'config': body
                }
                
                if hasattr(bridge, 'publish_mission_command'):
                    bridge.publish_mission_command(load_mission_data)
                    log_message(f"Sent load_mission command to mission controller with updated servo config", "INFO")
                else:
                    log_message("Warning: publish_mission_command not available, config saved but not applied", "WARNING")
            else:
                log_message("No mission waypoints loaded, config saved but not applied to mission controller", "INFO")
                
        except Exception as e:
            # Config was saved successfully, log warning but don't fail the request
            log_message(f"Warning: Config saved but failed to send command to mission controller: {e}", "WARNING")
        
        return _http_success("Sprayer configuration saved and applied to mission controller")
        
    except Exception as exc:
        log_message(f"/api/config/sprayer POST error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/rtk/inject")
async def api_rtk_inject(request: Request):
    """
    Inject RTK corrections from an NTRIP caster.

    Expected JSON body:
    {
        "ntrip_url": "rtcm://user:pass@host:port/mountpoint"
        OR
        "host": "...", "port": 2101, "mountpoint": "...", "user": "...", "password": "..."
    }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    ntrip_url = str(body.get('ntrip_url') or body.get('url') or '').strip()
    
    # Parse NTRIP URL if provided (format: rtcm://user:pass@host:port/mountpoint)
    if ntrip_url:
        try:
            from urllib.parse import urlparse
            
            # Handle both rtcm:// and http:// schemes
            if ntrip_url.startswith('rtcm://'):
                url = urlparse(ntrip_url.replace('rtcm://', 'http://'))
            else:
                url = urlparse(ntrip_url)
            
            caster_details = {
                'host': url.hostname or '',
                'port': url.port or 2101,
                'mountpoint': url.path.lstrip('/') or '',
                'user': url.username or '',
                'password': url.password or ''
            }
        except Exception as e:
            log_message(f"[RTK] Failed to parse NTRIP URL: {e}", "ERROR")
            return _http_error(f"Invalid NTRIP URL format: {e}", 400)
    else:
        # Use individual parameters
        caster_details = {
            'host': str(body.get('host', '')).strip(),
            'port': int(body.get('port', 2101)),
            'mountpoint': str(body.get('mountpoint', '')).strip(),
            'user': str(body.get('user') or body.get('username', '')).strip(),
            'password': str(body.get('password', '')).strip()
        }
    
    # Validate required fields
    if not caster_details.get('host') or not caster_details.get('mountpoint'):
        return _http_error("Missing host or mountpoint", 400)
    if not caster_details.get('user') or not caster_details.get('password'):
        return _http_error("Missing user or password", 400)
    
    # Call the async SocketIO handler directly with a dummy sid for REST context
    try:
        await handle_connect_caster("rest_api", caster_details)

        log_message(f"[RTK] REST API triggered RTK injection to {caster_details['host']}", "INFO")
        return {
            'success': True,
            'message': f"RTK stream started from {caster_details['host']}:{caster_details['port']}/{caster_details['mountpoint']}"
        }
    except Exception as exc:
        log_message(f"/api/rtk/inject error: {exc}", "ERROR")
        return _http_error(str(exc), 500)


@app.post("/api/rtk/stop")
def api_rtk_stop():
    """Stop the RTK corrections stream (both NTRIP and LoRa)."""
    global rtk_running, lora_rtk_handler, lora_rtk_source_active

    stopped_sources = []

    # Stop NTRIP RTK stream if running
    if rtk_running:
        log_message("[RTK] 🛑 REST API stop requested for NTRIP stream", "INFO")
        rtk_running = False
        stopped_sources.append("NTRIP")

    # Stop LoRa RTK stream if running
    if lora_rtk_source_active and lora_rtk_handler:
        log_message("[RTK] 🛑 REST API stop requested for LoRa stream", "INFO")
        try:
            lora_rtk_handler.stop_stream()
            lora_rtk_source_active = False
            stopped_sources.append("LoRa")
        except Exception as e:
            log_message(f"[RTK] Error stopping LoRa stream: {e}", "ERROR")
            return JSONResponse({
                'success': False,
                'message': f'Failed to stop LoRa stream: {str(e)}'
            }, status_code=500)

    if stopped_sources:
        return {
            'success': True,
            'message': f'RTK stream(s) stopped: {", ".join(stopped_sources)}'
        }
    else:
        return {
            'success': True,
            'message': 'RTK stream was not running'
        }


@app.post("/api/rtk/ntrip_stop")
def api_ntrip_stop():
    """Stop NTRIP RTK corrections stream only."""
    global rtk_running

    if rtk_running:
        log_message("[RTK] 🛑 REST API stop requested for NTRIP stream", "INFO")
        rtk_running = False
        return {
            'success': True,
            'message': 'NTRIP RTK stream stopped successfully',
            'source': 'NTRIP'
        }
    else:
        return {
            'success': True,
            'message': 'NTRIP RTK stream was not running',
            'source': 'NTRIP'
        }


@app.post("/api/rtk/lora_stop")
def api_lora_stop():
    """Stop LoRa RTK corrections stream only."""
    global lora_rtk_handler, lora_rtk_source_active

    if lora_rtk_source_active and lora_rtk_handler:
        log_message("[RTK] 🛑 REST API stop requested for LoRa stream", "INFO")
        try:
            lora_rtk_handler.stop_stream()
            lora_rtk_source_active = False
            return {
                'success': True,
                'message': 'LoRa RTK stream stopped successfully',
                'source': 'LoRa'
            }
        except Exception as e:
            log_message(f"[RTK] Error stopping LoRa stream: {e}", "ERROR")
            return JSONResponse({
                'success': False,
                'message': f'Failed to stop LoRa stream: {str(e)}',
                'source': 'LoRa'
            }, status_code=500)
    else:
        return {
            'success': True,
            'message': 'LoRa RTK stream was not running',
            'source': 'LoRa'
        }


@app.post("/api/rtk/ntrip_start")
async def api_ntrip_start(request: Request):
    """Start NTRIP RTK corrections stream via REST API."""
    global rtk_running, lora_rtk_source_active

    # Check if LoRa is already running
    if lora_rtk_source_active:
        return JSONResponse({
            'success': False,
            'message': 'LoRa RTK stream is active. Please stop it first.',
            'source': 'NTRIP'
        }, status_code=409)

    try:
        try:
            data = await request.json()
        except Exception:
            data = {}

        # Parse NTRIP URL or individual parameters
        if 'ntrip_url' in data:
            ntrip_url = data['ntrip_url']
            # Parse rtcm://user:pass@host:port/mountpoint
            if not ntrip_url.startswith('rtcm://'):
                return JSONResponse({
                    'success': False,
                    'message': 'Invalid NTRIP URL format. Expected: rtcm://user:pass@host:port/mountpoint'
                }, status_code=400)

            # Remove rtcm:// prefix
            url_parts = ntrip_url[7:]  # Remove 'rtcm://'

            # Split user:pass@host:port/mountpoint
            if '@' not in url_parts:
                return JSONResponse({
                    'success': False,
                    'message': 'Invalid NTRIP URL format. Missing credentials.'
                }, status_code=400)

            auth_part, location_part = url_parts.split('@', 1)
            user, password = auth_part.split(':', 1)

            if '/' not in location_part:
                return JSONResponse({
                    'success': False,
                    'message': 'Invalid NTRIP URL format. Missing mountpoint.'
                }, status_code=400)

            host_port, mountpoint = location_part.split('/', 1)

            if ':' in host_port:
                host, port = host_port.rsplit(':', 1)
                port = int(port)
            else:
                host = host_port
                port = 2101
        else:
            # Individual parameters
            host = data.get('host')
            port = int(data.get('port', 2101))
            mountpoint = data.get('mountpoint')
            user = data.get('user') or data.get('username', '')
            password = data.get('password', '')

        if not host or not mountpoint:
            return JSONResponse({
                'success': False,
                'message': 'Missing required parameters: host and mountpoint'
            }, status_code=400)

        # Prepare caster details
        caster_details = {
            'host': host,
            'port': port,
            'mountpoint': mountpoint,
            'user': user,
            'password': password
        }

        # Call the async SocketIO handler directly with a dummy sid for REST context
        await handle_connect_caster("rest_api", caster_details)

        log_message(f"[RTK] REST API started NTRIP stream to {host}:{port}/{mountpoint}", "INFO")
        return {
            'success': True,
            'message': f'NTRIP RTK stream started from {host}:{port}/{mountpoint}',
            'source': 'NTRIP',
            'caster': caster_details
        }
    except Exception as exc:
        log_message(f"/api/rtk/ntrip_start error: {exc}", "ERROR")
        return JSONResponse({
            'success': False,
            'message': str(exc),
            'source': 'NTRIP'
        }, status_code=500)


@app.post("/api/rtk/lora_start")
async def api_lora_start(request: Request):
    """Start LoRa RTK corrections stream via REST API."""
    global lora_rtk_handler, lora_rtk_source_active, rtk_running

    # Check if NTRIP is already running
    if rtk_running and not lora_rtk_source_active:
        return JSONResponse({
            'success': False,
            'message': 'NTRIP RTK stream is active. Please stop it first.',
            'source': 'LoRa'
        }, status_code=409)

    # Check if LoRa is already running
    if lora_rtk_source_active:
        return JSONResponse({
            'success': False,
            'message': 'LoRa RTK stream is already running',
            'source': 'LoRa'
        }, status_code=409)

    try:
        # Initialize handler if needed
        if lora_rtk_handler is None and create_lora_rtk_handler:
            log_message("[LoRa RTK] Initializing LoRa RTK handler...", "INFO")
            lora_rtk_handler = create_lora_rtk_handler(_inject_rtcm_to_mav)

        if not lora_rtk_handler:
            return JSONResponse({
                'success': False,
                'message': 'LoRa RTK handler not available',
                'source': 'LoRa'
            }, status_code=500)

        # Connect to receiver if not connected
        if not lora_rtk_handler.is_connected:
            log_message("[LoRa RTK] Connecting to LoRa receiver...", "INFO")
            if not lora_rtk_handler.connect():
                return JSONResponse({
                    'success': False,
                    'message': 'Failed to connect to LoRa receiver',
                    'source': 'LoRa'
                }, status_code=500)

        # Start streaming
        if not lora_rtk_handler.start_stream():
            return JSONResponse({
                'success': False,
                'message': 'Failed to start LoRa stream',
                'source': 'LoRa'
            }, status_code=500)

        lora_rtk_source_active = True
        log_message("[LoRa RTK] 🚀 LoRa RTK stream started successfully via REST API", "INFO")

        return {
            'success': True,
            'message': 'LoRa RTK stream started successfully',
            'source': 'LoRa',
            'status': lora_rtk_handler.get_status()
        }

    except Exception as e:
        log_message(f"[LoRa RTK] Error starting stream: {e}", "ERROR")
        return JSONResponse({
            'success': False,
            'message': str(e),
            'source': 'LoRa'
        }, status_code=500)


@app.get("/api/rtk/status")
def api_rtk_status():
    """Get the current RTK stream status (both NTRIP and LoRa)."""
    global rtk_running, rtk_current_caster, rtk_bytes_total, lora_rtk_handler, lora_rtk_source_active

    with rtk_bytes_lock:
        total_bytes = rtk_bytes_total

    # Get LoRa status
    lora_status = None
    if lora_rtk_handler:
        try:
            lora_status = lora_rtk_handler.get_status()
        except Exception as e:
            log_message(f"[RTK] Error getting LoRa status: {e}", "ERROR")

    return {
        'success': True,
        'ntrip': {
            'running': rtk_running,
            'caster': rtk_current_caster if rtk_running else None,
            'total_bytes': total_bytes
        },
        'lora': {
            'running': lora_rtk_source_active,
            'status': lora_status
        }
    }


@app.post("/api/rtk/force_clear")
def api_rtk_force_clear():
    """
    Force-clear GPS RTK fix by sending GPS reset command.
    WARNING: This will temporarily lose GPS fix. Use only if needed.
    The GPS will naturally degrade fix after 30-60 seconds anyway.
    """
    try:
        bridge = _require_vehicle_bridge()

        # Send GPS reset command via MAVLink
        # This clears the GPS cache and forces fix_type to reset
        from pymavlink import mavutil

        # GPS_INPUT message with zero values to clear state
        # Or send COMMAND_LONG with MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN
        bridge.mav.command_long_send(
            bridge.target_system,
            bridge.target_component,
            mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
            0,  # confirmation
            0,  # param1: 0=no action on autopilot
            0,  # param2: 0=no action on onboard computer
            0,  # param3: 0=no action on camera
            0,  # param4: 0=no action on mount
            1,  # param5: 1=reboot GPS
            0,  # param6
            0   # param7
        )

        log_message("[RTK] GPS reset command sent to clear RTK fix", "INFO")

        return {
            'success': True,
            'message': 'GPS reset command sent. Fix type will clear immediately.',
            'warning': 'GPS will reacquire satellites and take 30-60s to recover fix'
        }

    except Exception as e:
        log_message(f"[RTK] Error sending GPS reset: {e}", "ERROR")
        return JSONResponse({
            'success': False,
            'message': f'Failed to reset GPS: {str(e)}'
        }, status_code=500)


@app.post("/api/servo/control")
async def api_servo_control(request: Request):
    """
    Control a servo directly via MAVROS.

    Expected JSON body:
    {
        "servo_id": 10,  // Servo channel number (1-16)
        "angle": 90      // Angle in degrees (0-180) OR
        "pwm": 1500      // Direct PWM value (1000-2000)
    }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    servo_id = body.get('servo_id')
    
    if servo_id is None:
        return _http_error("Missing servo_id", 400)
    
    # Accept either angle (0-180) or direct PWM (1000-2000)
    angle = body.get('angle')
    pwm = body.get('pwm')
    
    if angle is None and pwm is None:
        return _http_error("Missing angle or pwm parameter", 400)
    
    # Convert angle to PWM if needed
    if pwm is None:
        # Map angle (0-180) to PWM (1000-2000)
        # Standard servo: 0° = 1000µs, 90° = 1500µs, 180° = 2000µs
        angle_val = float(angle)
        if angle_val < 0 or angle_val > 180:
            return _http_error("Angle must be between 0 and 180", 400)
        pwm_value = int(1000 + (angle_val / 180.0) * 1000)
    else:
        pwm_value = int(pwm)
        if pwm_value < 1000 or pwm_value > 2000:
            return _http_error("PWM must be between 1000 and 2000", 400)
    
    try:
        with _suppress_disconnect_during_bridge_call():
            bridge = _require_vehicle_bridge()
            result = bridge.set_servo(int(servo_id), pwm_value)

        if result.get('success'):
            log_message(f"[SERVO] Set servo {servo_id} to PWM {pwm_value}", "INFO")
            return {
                'success': True,
                'message': f'Servo {servo_id} set to PWM {pwm_value}',
                'servo_id': servo_id,
                'pwm': pwm_value,
                'angle': angle if angle is not None else None
            }
        else:
            return _http_error(f"Servo command failed: result={result.get('result')}", 500)
    except Exception as exc:
        log_message(f"/api/servo/control error: {exc}", "ERROR")
        return _http_error(str(exc), 500)

# ============================================================================
# TTS Voice Control API Endpoints
# ============================================================================

@app.get("/api/tts/status")
async def api_tts_status():
    """
    Get current TTS voice output status.

    Returns:
        {
            "success": true,
            "enabled": true|false,
            "engine": "piper|espeak|pyttsx3",
            "language": "en|hi|ta",
            "bluetooth_warmup_enabled": true|false
        }
    """
    try:
        # Get current TTS configuration from environment
        enabled = os.environ.get("NRP_TTS_ENABLE", "true").lower() in ("1", "true", "yes")
        language = os.environ.get("JARVIS_LANG", "en").strip().lower()
        bt_warmup = os.environ.get("NRP_TTS_BT_WARMUP", "true").lower() in ("1", "true", "yes")

        # Try to determine active engine (Piper preferred if available)
        try:
            import shutil
            engine = "piper" if shutil.which("piper") else "espeak"
        except Exception:
            engine = "espeak"

        return {
            "success": True,
            "enabled": enabled,
            "engine": engine,
            "language": language,
            "bluetooth_warmup_enabled": bt_warmup
        }
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/tts/control")
async def api_tts_control(request: Request):
    """
    Enable or disable TTS voice output.

    Request body:
        {
            "enabled": true|false
        }

    Returns:
        {
            "success": true,
            "enabled": true|false,
            "message": "TTS voice output enabled|disabled"
        }
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        enabled = body.get("enabled")

        if enabled is None:
            return JSONResponse({
                "success": False,
                "error": "Missing 'enabled' field in request body"
            }, status_code=400)

        if not isinstance(enabled, bool):
            return JSONResponse({
                "success": False,
                "error": "'enabled' must be a boolean (true or false)"
            }, status_code=400)

        # Update environment variable
        os.environ["NRP_TTS_ENABLE"] = "true" if enabled else "false"

        # Reload TTS module to apply changes
        try:
            import importlib
            importlib.reload(tts)
        except Exception as reload_error:
            # If reload fails, at least the env var is set for next restart
            log_message(f"TTS module reload warning: {reload_error}", "WARNING")

        action = "enabled" if enabled else "disabled"
        log_message(f"TTS voice output {action} via API", "INFO")

        return {
            "success": True,
            "enabled": enabled,
            "message": f"TTS voice output {action}"
        }

    except Exception as e:
        log_message(f"TTS control API error: {e}", "ERROR")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@app.post("/api/tts/test")
async def api_tts_test(request: Request):
    """
    Test TTS voice output with a custom message.

    Request body:
        {
            "message": "Test message to speak"
        }

    Returns:
        {
            "success": true,
            "message": "TTS test message queued"
        }
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        message = body.get("message", "TTS voice test")

        if not isinstance(message, str) or not message.strip():
            return JSONResponse({
                "success": False,
                "error": "Invalid message"
            }, status_code=400)

        # Queue TTS message
        tts.speak(message.strip())

        log_message(f"TTS test message queued: {message[:50]}", "INFO")

        return {
            "success": True,
            "message": "TTS test message queued"
        }

    except Exception as e:
        log_message(f"TTS test API error: {e}", "ERROR")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)

# ============================================================================
# ROS 2 Node Management Endpoints
# ============================================================================


# ---------------------------------------------------------------------------
# TTS Language Selection Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/tts/languages")
async def api_tts_languages():
    """
    Return supported TTS languages.
    Response: { "success": true, "languages": [{"code":"en","name":"English"}, ...] }
    """
    try:
        langs = [
            {"code": "en", "name": "English"},
            {"code": "ta", "name": "Tamil"},
            {"code": "hi", "name": "Hindi"},
        ]
        return {"success": True, "languages": langs}
    except Exception as e:
        log_message(f"/api/tts/languages error: {e}", "ERROR")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/tts/language")
async def api_tts_set_language(request: Request):
    """
    Set the TTS language. Request body: { "language": "en|ta|hi" }
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        lang = body.get("language")

        if not isinstance(lang, str) or not lang.strip():
            return JSONResponse({"success": False, "error": "Missing or invalid 'language' field"}, status_code=400)

        lang = lang.strip().lower()
        supported = {"en": "English", "ta": "Tamil", "hi": "Hindi"}

        if lang not in supported:
            return JSONResponse({"success": False, "error": f"Unsupported language: {lang}"}, status_code=400)

        # Persist to environment for runtime use
        os.environ["JARVIS_LANG"] = lang

        # Attempt to reload TTS module so running worker picks up language where possible
        try:
            import importlib
            importlib.reload(tts)
        except Exception as reload_error:
            log_message(f"TTS module reload warning (language change): {reload_error}", "WARNING")

        log_message(f"TTS language set to {supported[lang]} via API", "INFO")

        # Voice: Confirm language change in the NEW language
        try:
            _lang_msgs = {
                "en": "Language set to English.",
                "ta": "மொழி தமிழுக்கு மாற்றப்பட்டது.",
                "hi": "भाषा हिंदी में बदल गई.",
            }
            tts.speak(_lang_msgs.get(lang, _lang_msgs["en"]))
            print(f"[TTS] {_lang_msgs.get(lang, _lang_msgs['en'])}", flush=True)
        except Exception:
            pass

        return {"success": True, "language": lang, "message": f"Language set to {supported[lang]}"}

    except Exception as e:
        log_message(f"TTS set language API error: {e}", "ERROR")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/api/tts/gender")
async def api_tts_get_gender():
    """
    Get current TTS voice gender.

    Returns:
        {
            "success": true,
            "gender": "male" | "female"
        }
    """
    try:
        gender = os.environ.get("NRP_TTS_GENDER", "male").strip().lower()
        if gender not in ("male", "female"):
            gender = "male"
        return {"success": True, "gender": gender}
    except Exception as e:
        log_message(f"TTS get gender API error: {e}", "ERROR")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/tts/gender")
async def api_tts_set_gender(request: Request):
    """
    Set TTS voice gender.

    Request body:
        {
            "gender": "male" | "female"
        }

    Returns:
        {
            "success": true,
            "gender": "male" | "female",
            "message": "Voice gender set to Male"
        }
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}

        gender = body.get("gender")

        if not isinstance(gender, str) or not gender.strip():
            return JSONResponse({"success": False, "error": "Missing or invalid 'gender' field"}, status_code=400)

        gender = gender.strip().lower()

        if gender not in ("male", "female"):
            return JSONResponse({"success": False, "error": f"Unsupported gender: {gender}. Use 'male' or 'female'"}, status_code=400)

        # Persist to environment for runtime use
        os.environ["NRP_TTS_GENDER"] = gender

        # Reload TTS module so the worker picks up the new voice map
        try:
            import importlib
            importlib.reload(tts)
        except Exception as reload_error:
            log_message(f"TTS module reload warning (gender change): {reload_error}", "WARNING")

        log_message(f"TTS gender set to {gender} via API", "INFO")

        # Voice: Confirm gender change
        try:
            _lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
            _gender_msgs = {
                "male": {
                    "en": "Voice changed to male.",
                    "ta": "குரல் ஆண் குரலுக்கு மாற்றப்பட்டது.",
                    "hi": "आवाज पुरुष में बदल गई.",
                },
                "female": {
                    "en": "Voice changed to female.",
                    "ta": "குரல் பெண் குரலுக்கு மாற்றப்பட்டது.",
                    "hi": "आवाज महिला में बदल गई.",
                },
            }
            msg = _gender_msgs[gender].get(_lang, _gender_msgs[gender]["en"])
            tts.speak(msg)
        except Exception:
            pass

        label = "Male" if gender == "male" else "Female"
        return {"success": True, "gender": gender, "message": f"Voice gender set to {label}"}

    except Exception as e:
        log_message(f"TTS set gender API error: {e}", "ERROR")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/api/nodes")
async def api_nodes():
    """Return list of active ROS 2 nodes."""
    if not ROS_AVAILABLE:
        return _http_error("ROS 2 not available", 503)
    try:
        proc = await asyncio.create_subprocess_exec(
            'ros2', 'node', 'list',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return _http_error("ros2 node list timed out", 504)
        if proc.returncode == 0:
            nodes = stdout.decode().strip().split('\n')
            nodes = [node.strip() for node in nodes if node.strip()]
            return {'nodes': nodes, 'count': len(nodes)}
        else:
            return _http_error(f"Failed to list nodes: {stderr.decode()}", 500)
    except Exception as exc:
        log_message(f"/api/nodes error: {exc}", "ERROR")
        return _http_error(str(exc), 500)

@app.get("/api/node/{node_name}")
async def api_node_info(node_name: str):
    """Return detailed information about a specific ROS 2 node."""
    if not ROS_AVAILABLE:
        return _http_error("ROS 2 not available", 503)
    try:
        proc = await asyncio.create_subprocess_exec(
            'ros2', 'node', 'info', node_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return _http_error("ros2 node info timed out", 504)
        if proc.returncode == 0:
            # Parse the output
            lines = stdout.decode().strip().split('\n')
            info = {
                'node_name': node_name,
                'subscribers': [],
                'publishers': [],
                'service_servers': [],
                'service_clients': [],
                'action_servers': [],
                'action_clients': []
            }

            current_section = None
            for line in lines[1:]:  # Skip the node name line
                line = line.strip()
                if not line:
                    continue

                if line.startswith('Subscribers:'):
                    current_section = 'subscribers'
                elif line.startswith('Publishers:'):
                    current_section = 'publishers'
                elif line.startswith('Service Servers:'):
                    current_section = 'service_servers'
                elif line.startswith('Service Clients:'):
                    current_section = 'service_clients'
                elif line.startswith('Action Servers:'):
                    current_section = 'action_servers'
                elif line.startswith('Action Clients:'):
                    current_section = 'action_clients'
                elif current_section and line.startswith('/'):
                    # Extract topic/service name and type
                    if ':' in line:
                        parts = line.split(':', 1)
                        name = parts[0].strip()
                        type_info = parts[1].strip()
                        info[current_section].append({'name': name, 'type': type_info})
                    else:
                        info[current_section].append({'name': line, 'type': 'unknown'})

            return info
        else:
            return _http_error(f"Failed to get node info: {stderr.decode()}", 404)
    except Exception as exc:
        log_message(f"/api/node/{node_name} error: {exc}", "ERROR")
        return _http_error(str(exc), 500)

@sio.on('*')
async def catch_all_event(sid, event, data):
    """Catch-all Socket.IO event handler - will be refined in Phase 4."""
    pass


@app.exception_handler(404)
async def not_found_error(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            'error': 'Not found',
            'message': f'The requested URL {request.url.path} was not found',
            'available_endpoints': '/api/*'
        }
    )


@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            'error': str(exc),
            'type': type(exc).__name__
        }
    )


# ============================================================================
# MAIN EXECUTION
# ============================================================================

# ============================================================================
# SERVO CONTROL API (integrated for concurrent backend)
# ============================================================================
# Simple process manager to launch/stop servo scripts living under Backend/servo_manager
import subprocess as _subprocess

SERVO_BASE = os.path.join(os.path.dirname(__file__), "servo_manager")
CONFIG_PATH = os.path.join(SERVO_BASE, "config.json")
LOG_DIR = os.path.join(SERVO_BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_running: dict[str, dict] = {}

def _is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        return os.system(f"ps -p {int(pid)} > /dev/null 2>&1") == 0
    except Exception:
        return False

def _cleanup_running() -> None:
    for m in list(_running.keys()):
        pid = _running[m].get("pid")
        if not _is_pid_alive(pid):
            try:
                del _running[m]
            except Exception:
                pass

def _kill_mode(mode: str, timeout_sec: float = 3.0) -> None:
    info = _running.get(mode)
    if not info:
        return
    pid = info.get("pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            if not _is_pid_alive(pid):
                break
            time.sleep(0.1)
        if _is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    try:
        del _running[mode]
    except Exception:
        pass

def _find_running_mode(except_mode: str | None = None) -> str | None:
    _cleanup_running()
    for m, info in _running.items():
        if except_mode and m == except_mode:
            if _is_pid_alive(info.get("pid")):
                return m
            continue
        if _is_pid_alive(info.get("pid")):
            return m
    return None


@app.get("/servo/run")
async def servo_run(request: Request):
    mode = request.query_params.get("mode")
    if not mode:
        return JSONResponse({"error": "missing mode"}, status_code=400)

    scripts = {
        "continuous": "continuous_line.py",
        "interval": "interval_spray.py",
        "wpmark": "wpmark.py",
    }
    if mode not in scripts:
        return JSONResponse({"error": "invalid mode"}, status_code=400)

    # Enforce only one script running at a time
    replace = str(request.query_params.get("replace", "0")).lower() in ("1", "true", "yes")
    current = _find_running_mode()
    if current and current != mode and not replace:
        return JSONResponse({
            "error": "another mode is running",
            "current_mode": current,
            "requested_mode": mode,
            "action": "pass replace=1 to switch"
        }, status_code=409)
    if current and current != mode and replace:
        _kill_mode(current)

    # If same mode already running, return its info
    info = _running.get(mode)
    if info and _is_pid_alive(info.get("pid")):
        return {
            "status": f"{mode} already running",
            "pid": info.get("pid"),
            "log": info.get("log"),
            "start": info.get("start")
        }

    log_path = os.path.join(LOG_DIR, f"{mode}_{int(time.time())}.log")
    log_file = open(log_path, "a")

    p = _subprocess.Popen(
        ["python3", os.path.join(SERVO_BASE, scripts[mode])],
        stdout=log_file, stderr=_subprocess.STDOUT,
        cwd=SERVO_BASE
    )
    _running[mode] = {"pid": p.pid, "log": log_path, "start": time.time()}
    return {"status": f"{mode} started", "pid": p.pid, "log": log_path}


@app.get("/servo/stop")
async def servo_stop(request: Request):
    mode = request.query_params.get("mode")
    if not mode or mode not in _running:
        return JSONResponse({"error": "not running"}, status_code=400)
    try:
        _kill_mode(mode)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"status": f"{mode} stopped"}


@app.post("/servo/emergency_stop")
async def servo_emergency_stop():
    """
    Emergency stop all running servo scripts immediately.

    Returns:
    {
        "status": "emergency stop initiated",
        "stopped_modes": ["mode1", "mode2", ...]
    }
    """
    stopped_modes = []
    for mode in list(_running.keys()):
        try:
            _kill_mode(mode)
            stopped_modes.append(mode)
        except Exception as e:
            # Log error but continue stopping other modes
            logger.error(f"Error stopping {mode}: {e}")

    return {
        "status": "emergency stop initiated",
        "stopped_modes": stopped_modes
    }


@app.get("/servo/status")
async def servo_status():
    """
    Return servo status including running servo scripts and current servo output telemetry.

    Returns:
    {
        "success": true,
        "active": bool,           // Any servo script is running
        "running_modes": {...},   // Active servo scripts (wpmark, continuous, etc.)
        "servo_output": {...}     // Current PWM values from MAVROS telemetry
    }
    """
    _cleanup_running()
    for m, info in list(_running.items()):
        alive = _is_pid_alive(info.get("pid"))
        info["running"] = bool(alive)

    # Get current servo telemetry from MAVROS
    servo_telemetry = {}
    if current_state.servo_output:
        servo_telemetry = current_state.servo_output

    return {
        "success": True,
        "active": len(_running) > 0,
        "running_modes": _running,
        "servo_output": servo_telemetry,
        "timestamp": time.time()
    }


@app.get("/servo/edit")
async def servo_edit(request: Request):
    data = dict(request.query_params)
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    for k, v in data.items():
        keys = k.split(".")
        ref = cfg
        for part in keys[:-1]:
            ref = ref.setdefault(part, {})
        try:
            val = float(v) if "." in v else int(v)
        except Exception:
            val = v
        ref[keys[-1]] = val
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    return {"status": "updated", "config": cfg}


@app.post("/servo/edit")
async def servo_edit_post(request: Request):
    """Accept JSON body to update servo config (more robust than querystring)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}

    def _coerce(s):
        try:
            if isinstance(s, (int, float)):
                return s
            if isinstance(s, str):
                if s.strip() == "":
                    return s
                if "." in s:
                    return float(s)
                return int(s)
        except Exception:
            return s
        return s

    for k, v in body.items():
        keys = str(k).split(".")
        ref = cfg
        for part in keys[:-1]:
            ref = ref.setdefault(part, {})
        ref[keys[-1]] = _coerce(v)

    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    return {"status": "updated", "config": cfg}


@app.get("/servo/log")
async def servo_log(request: Request):
    path = request.query_params.get("path")
    if not path:
        return JSONResponse({"error": "invalid log path"}, status_code=400)
    try:
        # Prevent directory traversal: require logs under LOG_DIR
        abs_path = os.path.abspath(path)
        if not abs_path.startswith(os.path.abspath(LOG_DIR)):
            return JSONResponse({"error": "forbidden path"}, status_code=403)
        if not os.path.isfile(abs_path):
            return JSONResponse({"error": "invalid log path"}, status_code=400)
        with open(abs_path, "r") as f:
            lines = f.readlines()[-200:]
        return {"log": "".join(lines)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- Mission Controller WebSocket Event Handlers - REMOVED ---
# Mission controller node has been deleted
# Use direct MAVROS services for mission operations


def load_system_settings():
    """Load system settings from config file on startup."""
    global current_state, system_settings
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)

            system_settings = config.get('system_settings', {})

            # Load GPS failsafe mode
            gps_mode = system_settings.get('gps_failsafe_mode', 'disable')
            if gps_mode in ['disable', 'strict', 'relax']:
                current_state.gps_failsafe_mode = gps_mode
                log_message(f"✅ Loaded GPS failsafe mode from config: {gps_mode}", "INFO", event_type='config')

            # Load obstacle detection state (applied in initialize_mission_controller)
            obstacle_enabled = system_settings.get('obstacle_detection_enabled', False)
            log_message(f"✅ Loaded obstacle detection from config: {obstacle_enabled}", "INFO", event_type='config')

            return True
        else:
            log_message("⚠️  Config file not found, using defaults", "WARNING", event_type='config')
            system_settings = {}
            return False
    except Exception as e:
        log_message(f"❌ Failed to load system settings: {e}", "ERROR", event_type='config')
        system_settings = {}
        return False

# Dash configuration endpoints
@app.get("/api/config/dash")
async def api_get_dash_config():
    """Get current dash configuration"""
    try:
        global mission_controller
        if not mission_controller:
            return JSONResponse({
                'success': False,
                'error': 'Mission controller not available'
            }, status_code=503)

        return JSONResponse({
            'success': True,
            'data': {
                'servo_on_distance': mission_controller.dash_servo_on_distance,
                'servo_off_distance': mission_controller.dash_servo_off_distance
            }
        })
    except Exception as e:
        log_message(f"Failed to get dash config: {e}", "ERROR", event_type='config')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@app.post("/api/config/dash")
async def api_set_dash_config(request: Request):
    """Set dash configuration"""
    try:
        global mission_controller
        if not mission_controller:
            return JSONResponse({
                'success': False,
                'error': 'Mission controller not available'
            }, status_code=503)

        data = await request.json()
        servo_on_distance = data.get('servo_on_distance')
        servo_off_distance = data.get('servo_off_distance')

        # Validate inputs
        if servo_on_distance is not None:
            try:
                servo_on_distance = float(servo_on_distance)
                if servo_on_distance <= 0:
                    return JSONResponse({
                        'success': False,
                        'error': 'servo_on_distance must be greater than 0'
                    }, status_code=400)
            except (TypeError, ValueError):
                return JSONResponse({
                    'success': False,
                    'error': 'servo_on_distance must be a valid number'
                }, status_code=400)

        if servo_off_distance is not None:
            try:
                servo_off_distance = float(servo_off_distance)
                if servo_off_distance <= 0:
                    return JSONResponse({
                        'success': False,
                        'error': 'servo_off_distance must be greater than 0'
                    }, status_code=400)
            except (TypeError, ValueError):
                return JSONResponse({
                    'success': False,
                    'error': 'servo_off_distance must be a valid number'
                }, status_code=400)

        # Update mission controller
        if servo_on_distance is not None:
            mission_controller.dash_servo_on_distance = servo_on_distance
        if servo_off_distance is not None:
            mission_controller.dash_servo_off_distance = servo_off_distance

        # Persist to config file
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            # Update dash config
            if 'mission_controller' not in config:
                config['mission_controller'] = {}
            if 'dash_config' not in config['mission_controller']:
                config['mission_controller']['dash_config'] = {}
            
            if servo_on_distance is not None:
                config['mission_controller']['dash_config']['servo_on_distance'] = servo_on_distance
            if servo_off_distance is not None:
                config['mission_controller']['dash_config']['servo_off_distance'] = servo_off_distance
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)

        log_message(f"Dash config updated: ON={servo_on_distance}m, OFF={servo_off_distance}m", "SUCCESS", event_type='config')

        return JSONResponse({
            'success': True,
            'message': 'Dash configuration updated',
            'data': {
                'servo_on_distance': mission_controller.dash_servo_on_distance,
                'servo_off_distance': mission_controller.dash_servo_off_distance
            }
        })
    except Exception as e:
        log_message(f"Failed to set dash config: {e}", "ERROR", event_type='config')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

def save_system_setting(setting_name: str, setting_value):
    """Save a system setting to config file."""
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'config', 'mission_controller_config.json')

        # Load existing config
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
        else:
            config = {
                "mission_controller": {},
                "system_settings": {},
                "metadata": {}
            }

        # Ensure system_settings section exists
        if 'system_settings' not in config:
            config['system_settings'] = {}

        # Update setting
        config['system_settings'][setting_name] = setting_value

        # Update metadata
        config['metadata'] = {
            "version": "1.0",
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # Save to file
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)

        log_message(f"✅ Saved {setting_name} = {setting_value} to config", "INFO", event_type='config')
        return True
    except Exception as e:
        log_message(f"❌ Failed to save system setting {setting_name}: {e}", "ERROR", event_type='config')
        return False

async def _supervised_task(coro_fn, name: str, restart_delay: float = 3.0):
    """Run *coro_fn()* in a loop, restarting on unhandled exceptions.

    Prevents silent task death (Suspect #3 in crash investigation).
    """
    while True:
        try:
            await coro_fn()
        except asyncio.CancelledError:
            log_message(f"[SUPERVISOR] {name} cancelled — stopping", "WARNING")
            return
        except Exception as exc:
            log_message(
                f"[SUPERVISOR] {name} crashed: {exc!r} — restarting in {restart_delay}s",
                "ERROR",
            )
            await asyncio.sleep(restart_delay)


if __name__ in ('__main__', 'Backend.server'):
    import uvicorn
    log_message("Starting FastAPI server on http://0.0.0.0:5001", "SUCCESS")
    uvicorn.run(sio_app, host='0.0.0.0', port=5001, log_level='info')
