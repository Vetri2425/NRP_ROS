# Mission Controller - Complete Parameter Analysis

## Summary
- **Total Parameters Used:** 32 core parameters
- **Configurable Parameters:** 13 (can be changed via API/config)
- **Hardcoded Parameters:** 19 (fixed in code, require code changes)

---

## 🟢 CONFIGURABLE PARAMETERS (13)

These can be changed dynamically via API without code modification:

### Mission Execution (3)
| Parameter | Type | Default | Configurable Via | Purpose |
|-----------|------|---------|------------------|---------|
| `waypoint_reached_threshold` | float | 0.250 m | load_mission config | Distance threshold for waypoint completion |
| `hold_duration` | float | 0 seconds | load_mission config | Time to hold at each waypoint |
| `mission_mode` | enum | AUTO | set_mode API | AUTO (automatic) or MANUAL (user-guided) |

### Servo/Spray Control (7)
| Parameter | Type | Default | Configurable Via | Purpose |
|-----------|------|---------|------------------|---------|
| `servo_enabled` | bool | True | update_servo_config API | Enable/disable servo control |
| `servo_channel` | int | 9 | update_servo_config API | PWM channel (1-16) |
| `servo_pwm_on` | int | 2300 µs | update_servo_config API | PWM pulse when servo ON |
| `servo_pwm_off` | int | 1750 µs | update_servo_config API | PWM pulse when servo OFF |
| `servo_delay_before` | float | 0.0 seconds | update_servo_config API | Delay before turning servo ON |
| `servo_spray_duration` | float | 0.2 seconds | update_servo_config API | Duration between ON and OFF |
| `servo_delay_after` | float | 0.0 seconds | update_servo_config API | Delay after servo OFF |

### GPS Failsafe (2)
| Parameter | Type | Default | Configurable Via | Purpose |
|-----------|------|---------|------------------|---------|
| `failsafe_mode` | enum | "disable" | set_failsafe_mode API | Failsafe strategy: disable/relax/strict |
| `obstacle_detection_enabled` | bool | False | set_obstacle_detection API | Enable/disable obstacle pause logic |

### Waypoint Detection (1)
| Parameter | Type | Default | Configurable Via | Purpose |
|-----------|------|---------|------------------|---------|
| `mission_timeout` | float | 3000.0 seconds | [HARDCODED] | Max time per waypoint execution (note: actually hardcoded, not configurable) |

---

## 🔴 HARDCODED PARAMETERS (19)

These are fixed in code and require code modifications to change:

### Mission State Logic
| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Initial waypoint index | 0 | `__init__` line 67 | Always start from first waypoint |
| Mission timeout | 3000.0 seconds | `__init__` line 75 | Max time to reach any waypoint (5 minutes) |

### Servo/PWM Constants
| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Servo PWM ON (default) | 2300 µs | `__init__` line 80 | Default ON position |
| Servo PWM OFF (default) | 1750 µs | `__init__` line 81 | Default OFF position |
| Spray duration (default) | 0.2 seconds | `__init__` line 83 | Default spray time |

### GPS Failsafe Thresholds
| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Accuracy error threshold | 60.0 mm | line 1117 | Suppress spray if error exceeds 60mm |
| RTK fix type (required) | 6 | line 658, 708 | RTK Fixed status (0=invalid, 6=fixed) |
| RTK fallback timeout | 30.0 seconds | line 1009 | Wait 30s in threshold zone before fallback |

### MAVROS/Pixhawk Protocol
| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Waypoint frame (HOME) | 0 | line 1389 | MAV_FRAME_GLOBAL (absolute altitude) |
| Waypoint frame (mission) | 3 | line 1364, 1404 | MAV_FRAME_GLOBAL_RELATIVE_ALT |
| Waypoint command | 16 | line 1365, 1390, 1405 | MAV_CMD_NAV_WAYPOINT |
| Hold time parameter | 0 | line 1368, 1393, 1407 | No hold at each waypoint (separate hold_duration handles it) |
| Accept radius parameter | waypoint_reached_threshold | line 1369, 1408 | Uses configurable threshold |
| Yaw angle | 0 | line 1371, 1395, 1410 | Maintain current heading (0 = auto) |

### Telemetry Processing
| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Distance check interval | 1.0 seconds | line 278 | Check fallback distance every 1 second |
| Telemetry emit throttle | 0.2 seconds | line 287 | Emit status every 0.2 seconds max |
| RTK monitoring interval | 0.5 seconds | line 751 | Check RTK fix type every 0.5 seconds |
| Status log interval | 0.2 seconds (5Hz) | line 1704 | Periodic distance logging frequency |

### Earth & Physics Constants
| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Earth radius | 6,371,000 meters | line 1596 | For GPS distance calculation (Haversine) |

### Default States
| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Pixhawk waypoint detection | True | line 99 | Use /mavros/mission/reached topic (primary) |
| Distance fallback detection | True | line 100 | Enable GPS distance fallback method |
| Initial RTK fix type | 0 | line 108 | Assume invalid until telemetry received |
| Expected RTK fix type | 6 | line 111 | Track against this reference |

---

## 📊 Parameter Categories by Function

### Navigation (4 configurable, 5 hardcoded)
- Waypoint distance threshold (CONFIGURABLE)
- Hold duration (CONFIGURABLE)
- Mission timeout (HARDCODED - 3000s)
- Waypoint frame type (HARDCODED - frame 3)
- Waypoint command (HARDCODED - cmd 16)

### Spray/Servo Control (7 configurable, 3 hardcoded)
- All servo PWM and timing (CONFIGURABLE)
- Servo enable toggle (CONFIGURABLE)
- Default values (HARDCODED)

### Safety/Failsafe (2 configurable, 6 hardcoded)
- Failsafe mode (CONFIGURABLE)
- Obstacle detection (CONFIGURABLE)
- Accuracy threshold 60mm (HARDCODED)
- RTK fix type requirement = 6 (HARDCODED)
- RTK check interval 0.5s (HARDCODED)
- Fallback 30s timeout (HARDCODED)

### Telemetry/Monitoring (0 configurable, 5 hardcoded)
- Distance check interval 1.0s (HARDCODED)
- Status emit throttle 0.2s (HARDCODED)
- Status log interval 0.2s (HARDCODED)
- Earth radius 6,371,000m (HARDCODED)

---

## 🎯 Impact Analysis

### What can be changed WITHOUT code modification:
✅ Waypoint tolerance, hold time
✅ Servo timings and PWM values
✅ Mission mode (auto/manual)
✅ Failsafe strategy
✅ Obstacle detection on/off

### What requires code modification:
❌ Mission timeout (currently 3000s/5min per waypoint)
❌ Accuracy threshold (currently 60mm)
❌ RTK fix type requirement (currently requires type 6)
❌ Check intervals (distance, telemetry, RTK)
❌ Fallback zone timer (currently 30s)
❌ Protocol constants (frame types, commands)

---

## 💡 Recommendations

### High Priority for Making Configurable:
1. **mission_timeout** - Different missions may need different timeouts
2. **accuracy_threshold_mm** - 60mm may not suit all crop types
3. **rtk_monitoring_interval** - 0.5s might be too frequent for some systems
4. **telemetry_throttle_interval** - 0.2s might flood some frontends

### Parameters to Keep Hardcoded:
- MAVROS protocol constants (frame, command types)
- Physics constants (Earth radius)
- Safety-critical values (RTK fix type requirement)

