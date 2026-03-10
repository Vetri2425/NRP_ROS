# Mission Controller Refactor: Pixhawk Topic Subscription

## Date: 2025-11-20

## Overview
Refactored mission controller to use Pixhawk's native `/mavros/mission/reached` topic for waypoint detection instead of GPS distance calculation. This makes the system more robust and reliable by letting Pixhawk (the autopilot) determine when waypoints are reached.

---

## Why This Change?

### The Problem with Distance Calculation
The previous approach calculated GPS distance and used complex logic to determine when a waypoint was reached:
- ❌ Dependent on GPS accuracy (RTK dropouts cause issues)
- ❌ Required debounce logic (1-second in-zone requirement)
- ❌ Required position change verification (1-meter minimum movement)
- ❌ Required time-in-motion checks (2-second minimum)
- ❌ Required 1-second delay between waypoints
- ❌ ~90 lines of complex verification code
- ❌ **We were guessing when Pixhawk thought it reached the waypoint**

### The Solution: Trust Pixhawk
**Pixhawk is the autopilot** - it's navigating in AUTO mode, so it should tell us when it reaches a waypoint:
- ✅ Pixhawk publishes `MISSION_ITEM_REACHED` MAVLink message
- ✅ MAVROS subscribes to this and publishes to `/mavros/mission/reached`
- ✅ MAVROS bridge already subscribes to this topic (mavros_bridge.py:432)
- ✅ **Let Pixhawk decide when waypoint is reached - it's the source of truth!**

---

## Changes Made

### 1. Added Primary Method: Pixhawk Topic Subscription

**File**: `Backend/integrated_mission_controller.py`

#### Configuration Flags (lines 70-74)
```python
# REFACTOR: Use Pixhawk waypoint reached topic instead of distance calculation
self.use_pixhawk_waypoint_reached = True  # Primary: use /mavros/mission/reached topic
self.fallback_to_distance_check = True  # Fallback: use distance if topic fails
self.last_telemetry_emission_time: float = 0  # Phase 2: Throttle telemetry emissions
self.last_distance_check_time: float = 0  # For fallback distance monitoring
```

#### Telemetry Handler Update (lines 180-207)
```python
# Check for Pixhawk waypoint reached message (primary method)
if 'mission_progress' in telemetry_data:
    mission_progress = telemetry_data.get('mission_progress', {})
    message_type = telemetry_data.get('message_type', '')

    # Check if this is a waypoint reached message from Pixhawk
    if (message_type == 'mission_reached' and
        self.use_pixhawk_waypoint_reached and
        self.mission_state == MissionState.RUNNING and
        self.waiting_for_waypoint_reach):

        # Extract waypoint sequence from mission progress
        wp_seq = mission_progress.get('wp_seq')
        if wp_seq is not None:
            self.log(f'📡 RECEIVED /mavros/mission/reached: wp_seq={wp_seq}', 'info')
            self.handle_pixhawk_waypoint_reached(wp_seq)

# Fallback: Check distance if enabled and topic hasn't triggered
if (self.fallback_to_distance_check and
    self.mission_state == MissionState.RUNNING and
    self.waiting_for_waypoint_reach and
    self.current_position):

    # Only check distance every 0.5 seconds (not every telemetry update)
    current_time = time.time()
    if current_time - self.last_distance_check_time >= 0.5:
        self.last_distance_check_time = current_time
        self.check_waypoint_reached_distance_fallback()
```

#### New Handler Method (lines 541-583)
```python
def handle_pixhawk_waypoint_reached(self, wp_seq: int):
    """
    Handle waypoint reached message from Pixhawk via /mavros/mission/reached topic.
    This is the PRIMARY method for waypoint detection (more robust than distance calculation).

    Args:
        wp_seq: Waypoint sequence number from Pixhawk (1-based indexing for mission waypoints)
    """
    try:
        # Pixhawk uses 1-based indexing for mission waypoints (seq=0 is HOME, seq=1 is first mission waypoint)
        # Our controller uses 0-based indexing for waypoints array
        # So Pixhawk seq=1 corresponds to our waypoint index 0
        expected_seq = self.current_waypoint_index + 1

        self.log(f'🎯 Pixhawk reports waypoint reached: seq={wp_seq}, expected={expected_seq}')

        # Verify this is the waypoint we're expecting
        if wp_seq != expected_seq:
            self.log(
                f'⚠️ WARNING: Received wp_seq={wp_seq} but expected wp_seq={expected_seq}. '
                f'Current waypoint index={self.current_waypoint_index}',
                'warning'
            )
            # Don't trigger waypoint_reached for unexpected sequence
            return

        # Verify we're in the correct state
        if not self.waiting_for_waypoint_reach:
            self.log(f'⚠️ Received waypoint reached but not waiting for it (state inconsistency)', 'warning')
            return

        if self.mission_state != MissionState.RUNNING:
            self.log(f'⚠️ Received waypoint reached but mission not running (state={self.mission_state.value})', 'warning')
            return

        # All checks passed - waypoint truly reached by Pixhawk
        self.log(f'✅ PIXHAWK CONFIRMED: Waypoint {self.current_waypoint_index + 1} reached (seq={wp_seq})')

        # Trigger the waypoint reached handler (same as distance-based method)
        self.waypoint_reached()

    except Exception as e:
        self.log(f'❌ Error handling Pixhawk waypoint reached message: {e}', 'error')
```

### 2. Simplified Fallback: Distance Monitoring

Replaced complex Phase 1 distance logic with simple monitoring + emergency fallback:

**Old approach** (~90 lines):
- Debounce timer (1-second in-zone requirement)
- Position change verification (1-meter minimum movement)
- Time-in-motion check (2-second minimum)
- Complex state tracking

**New approach** (~40 lines):
- Simple distance logging every 5 seconds for monitoring
- Emergency fallback: if within threshold for 10+ seconds without topic message, use distance
- Logs clearly show when fallback is triggered

```python
def check_waypoint_reached_distance_fallback(self):
    """
    FALLBACK: Simple distance-based waypoint detection (backup method).
    This is only used if Pixhawk topic messages are not received.
    """
    # Calculate distance
    distance = self.calculate_distance(...)

    # Log every 5 seconds for monitoring
    if current_time - self._last_distance_log_time > 5:
        self.log(f'📊 Distance monitor: WP{self.current_waypoint_index + 1} is {distance:.2f}m away (waiting for Pixhawk topic)')

    # Emergency fallback: If within threshold for 10+ seconds and no topic message
    if distance <= self.waypoint_reached_threshold:
        if time_in_zone >= 10.0:
            self.log(f'🚨 FALLBACK TRIGGERED: No Pixhawk topic after 10s in zone - using distance detection', 'warning')
            self.waypoint_reached()
```

### 3. Removed Complexity

**Removed variables** (no longer needed):
- `self.previous_waypoint_position` - position tracking for verification
- `self.waypoint_reached_start_time` - debounce timer

**Removed logic**:
- 1-second debounce requirement
- 1-meter minimum movement verification
- 2-second minimum time-in-motion check
- 1-second delay between waypoints in `proceed_to_next_waypoint()`

**Simplified methods**:
- `waypoint_reached()` - removed Phase 1 tracking
- `proceed_to_next_waypoint()` - removed 1-second delay
- `complete_mission()` - updated cleanup to remove Phase 1 variables

### 4. Preserved Features

**✅ All Phase 2 & 3 fixes retained**:
- Phase 2: Throttled telemetry emissions (every 2 seconds)
- Phase 2: Status caching (last 10 messages)
- Phase 2: Frontend status verification logging
- Phase 3: Complete state cleanup in `complete_mission()`
- Phase 3: Deadlock fixes (emit/mode outside lock)
- Phase 3: Auto-transition COMPLETED → READY

**✅ All mission functionality intact**:
- Single-waypoint upload strategy (HOME + waypoint)
- HOLD mode after each waypoint
- 5-second hold duration
- Mission start/stop/pause/resume commands
- Periodic status logging
- Timeout handling

---

## How It Works Now

### Mission Flow (Pixhawk Topic Method)

1. **Upload waypoint**: Controller uploads HOME (seq=0) + WP1 (seq=1)
2. **Set AUTO mode**: Pixhawk navigates to WP1
3. **Pixhawk reaches WP1**: Pixhawk publishes `MISSION_ITEM_REACHED` with `wp_seq=1`
4. **MAVROS receives**: Publishes to `/mavros/mission/reached` topic
5. **MAVROS Bridge receives**: Broadcasts as telemetry with `message_type="mission_reached"`
6. **Mission Controller receives**: `handle_telemetry_update()` detects `mission_reached` message
7. **Validate wp_seq**: Verify `wp_seq=1` matches `current_waypoint_index=0` (0-based)
8. **Trigger waypoint_reached()**: Set HOLD mode, start 5s hold timer
9. **Hold complete**: Proceed to next waypoint
10. **Repeat** for WP2, WP3, etc.

### Fallback Flow (Distance Method)

If Pixhawk topic doesn't fire within 10 seconds of entering threshold:

1. **Distance monitor**: Logs distance every 5 seconds ("📊 Distance monitor: WP1 is 1.5m away")
2. **Enter threshold**: Distance < 2m, start 10-second fallback timer
3. **Log warning**: "⚠️ FALLBACK: Entered threshold zone (1.5m) - waiting 10s for Pixhawk topic"
4. **Wait 10 seconds**: Give Pixhawk topic time to fire
5. **Topic doesn't fire**: Trigger fallback after 10 seconds
6. **Log fallback**: "🚨 FALLBACK TRIGGERED: No Pixhawk topic after 10s - using distance detection"
7. **Trigger waypoint_reached()**: Same as topic method

---

## Benefits

### Reliability
✅ **Pixhawk is source of truth**: Autopilot determines when waypoint is reached
✅ **No GPS accuracy dependency**: Pixhawk handles internal filtering
✅ **No false positives**: Pixhawk won't publish until actually reached
✅ **Faster response**: Immediate notification vs polling every 0.5s

### Simplicity
✅ **50 lines of code removed**: Simpler, easier to maintain
✅ **No complex verification logic**: Debounce, position checks, time checks removed
✅ **Clear logs**: Easy to see when topic fires vs when fallback triggers

### Robustness
✅ **Fallback mechanism**: If topic fails, distance check kicks in after 10s
✅ **Configurable**: Can disable topic or fallback via flags
✅ **No breaking changes**: Same external API and mission flow

---

## Testing Guide

### 1. Monitor Logs for Topic Messages

**Expected logs** during mission:
```
📡 RECEIVED /mavros/mission/reached: wp_seq=1
🎯 Pixhawk reports waypoint reached: seq=1, expected=1
✅ PIXHAWK CONFIRMED: Waypoint 1 reached (seq=1)
🛑 Setting HOLD mode
✅ WAYPOINT 1 REACHED
```

### 2. Verify Fallback Mechanism

**Simulate topic failure** by setting `self.use_pixhawk_waypoint_reached = False`:
```python
# In __init__
self.use_pixhawk_waypoint_reached = False  # Disable topic, test fallback
```

**Expected logs**:
```
📊 Distance monitor: WP1 is 3.5m away (waiting for Pixhawk topic)
📊 Distance monitor: WP1 is 2.8m away (waiting for Pixhawk topic)
📊 Distance monitor: WP1 is 1.5m away (waiting for Pixhawk topic)
⚠️ FALLBACK: Entered threshold zone (1.5m) - waiting 10s for Pixhawk topic before fallback trigger
🚨 FALLBACK TRIGGERED: No Pixhawk topic after 10s in zone - using distance detection
✓ Waypoint 1 reached via FALLBACK distance check (1.5m)
```

### 3. Field Test Scenarios

**Test 1**: Normal operation (3 waypoints, varying distances)
- ✅ Topic should fire for each waypoint
- ✅ No fallback should trigger
- ✅ Logs show "PIXHAWK CONFIRMED" for each waypoint

**Test 2**: Close waypoints (2-3 meters apart)
- ✅ Should NOT have false positives (old issue with distance method)
- ✅ Pixhawk determines when reached
- ✅ No premature mode hold

**Test 3**: Mission completion and restart
- ✅ Mission completes cleanly
- ✅ Auto-transition to READY state
- ✅ Can restart without server reboot

---

## Rollback Plan

If Pixhawk topic doesn't work reliably:

### Option 1: Disable Topic, Use Fallback Only
```python
# In __init__
self.use_pixhawk_waypoint_reached = False  # Disable topic
self.fallback_to_distance_check = True  # Use distance only
```

### Option 2: Revert to Old Distance Method
```bash
cd /home/flash/NRP_ROS
git checkout HEAD~1 Backend/integrated_mission_controller.py
sudo systemctl restart nrp-backend.service
```

---

## Configuration Options

### Enable/Disable Features

**Use topic only** (recommended):
```python
self.use_pixhawk_waypoint_reached = True
self.fallback_to_distance_check = False
```

**Use distance fallback only** (if topic unreliable):
```python
self.use_pixhawk_waypoint_reached = False
self.fallback_to_distance_check = True
```

**Use both** (topic primary, distance backup - default):
```python
self.use_pixhawk_waypoint_reached = True
self.fallback_to_distance_check = True
```

### Adjust Fallback Timeout

Change the 10-second fallback timeout in `check_waypoint_reached_distance_fallback()`:
```python
if time_in_zone >= 10.0:  # Change to 5.0 for faster fallback, 20.0 for slower
```

---

## Key Logs to Monitor

### Success Path (Topic Working)
```
📡 RECEIVED /mavros/mission/reached: wp_seq=1
✅ PIXHAWK CONFIRMED: Waypoint 1 reached (seq=1)
```

### Warning Signs (Topic Issues)
```
⚠️ WARNING: Received wp_seq=2 but expected wp_seq=1  # Sequence mismatch
⚠️ Received waypoint reached but not waiting for it   # State inconsistency
```

### Fallback Triggered
```
🚨 FALLBACK TRIGGERED: No Pixhawk topic after 10s in zone
✓ Waypoint 1 reached via FALLBACK distance check
```

---

## Summary

**What Changed**:
- ✅ Primary method: `/mavros/mission/reached` topic subscription
- ✅ Fallback method: Simple distance monitoring (10s timeout)
- ✅ Removed: 50+ lines of complex verification logic
- ✅ Removed: Debounce, position checks, time checks, 1s delay

**What Stayed the Same**:
- ✅ Phase 2 & 3 fixes (throttling, caching, deadlock fixes)
- ✅ Single-waypoint upload strategy
- ✅ HOLD mode after each waypoint
- ✅ 5-second hold duration
- ✅ All mission commands (start/stop/pause/resume)

**Why This is Better**:
- ✅ **Pixhawk decides** when waypoint is reached (source of truth)
- ✅ **Simpler code** - easier to understand and maintain
- ✅ **More reliable** - no GPS accuracy dependency
- ✅ **Faster response** - immediate notification
- ✅ **Robust fallback** - distance check if topic fails

---

**Implementation Date**: 2025-11-20
**Status**: ✅ Complete and Ready for Testing
**Next Step**: Field test with 3 waypoints, monitor logs for topic messages
