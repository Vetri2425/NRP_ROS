# Jarvis Voice System - Event Type Refactor Implementation Guide

**Status**: Recommended Next Action  
**Difficulty**: Moderate  
**Time Estimate**: 2 hours  
**Scope**: Replace string-based TTS triggers with structured event types  

---

## OVERVIEW

This guide provides step-by-step instructions to implement the **single most important next action** from the Jarvis Voice System assessment: converting TTS event triggers from fragile string pattern matching to robust structured event types.

**Current Problem**:
```python
# Fragile - breaks if message text changes:
if 'Mission loaded with' in message and 'waypoints' in message:
    tts.speak(f"Waypoints loaded: {count} waypoints")
```

**Target Solution**:
```python
# Robust - independent of message text:
event_type = extra_data.get('event_type')
if event_type == 'mission_loaded':
    tts.speak(f"Waypoints loaded: {count} waypoints")
```

---

## PART A: Update Mission Controller Event Emissions

### File: `Backend/integrated_mission_controller.py`

Locate each `emit_status()` call and add structured `extra_data` with `event_type`.

#### Change 1: Mission Loaded Event

**Location**: `load_mission()` method (~line 410)

**BEFORE**:
```python
self.emit_status(
    f"Mission loaded with {len(waypoints)} waypoints",
    "success",
    extra_data={
        "waypoints_count": len(waypoints),
        "mode": self.mission_mode.value,
        "waypoints": waypoints
    }
)
```

**AFTER**:
```python
self.emit_status(
    f"Mission loaded with {len(waypoints)} waypoints",
    "success",
    extra_data={
        "event_type": "mission_loaded",  # ← ADD THIS LINE
        "waypoints_count": len(waypoints),
        "mode": self.mission_mode.value,
        "waypoints": waypoints
    }
)
```

---

#### Change 2: Mission Started Event

**Location**: `start_mission()` method (~line 465)

**BEFORE**:
```python
self.log(f'═══════════════════════════════════════════════════')
self.log(f'🚀 MISSION STARTED')
self.log(f'Starting from waypoint {self.current_waypoint_index + 1}/{len(self.waypoints)}')
self.log(f'Mission Mode: {self.mission_mode.value}')
self.log(f'═══════════════════════════════════════════════════')
self.emit_status("Mission started", "success")
```

**AFTER**:
```python
self.log(f'═══════════════════════════════════════════════════')
self.log(f'🚀 MISSION STARTED')
self.log(f'Starting from waypoint {self.current_waypoint_index + 1}/{len(self.waypoints)}')
self.log(f'Mission Mode: {self.mission_mode.value}')
self.log(f'═══════════════════════════════════════════════════')
self.emit_status(
    "Mission started",
    "success",
    extra_data={
        "event_type": "mission_started"  # ← ADD THIS
    }
)
```

---

#### Change 3: Executing Waypoint Event

**Location**: `execute_current_waypoint()` method (~line 825)

**BEFORE**:
```python
self.emit_status(
    f"Executing waypoint {self.current_waypoint_index + 1}",
    "info",
    extra_data={
        "current_waypoint": self.current_waypoint_index + 1,
        "total_waypoints": len(self.waypoints),
        "waypoint": waypoint,
        "mode": self.mission_mode.value
    }
)
```

**AFTER**:
```python
self.emit_status(
    f"Executing waypoint {self.current_waypoint_index + 1}",
    "info",
    extra_data={
        "event_type": "waypoint_executing",  # ← ADD THIS LINE
        "current_waypoint": self.current_waypoint_index + 1,
        "total_waypoints": len(self.waypoints),
        "waypoint": waypoint,
        "mode": self.mission_mode.value
    }
)
```

---

#### Change 4: Waypoint Reached Event

**Location**: `waypoint_reached()` method (~line 965)

**This one already has the structure in the codebase, just verify it exists**:

```python
self.emit_status(
    f"Waypoint {self.current_waypoint_index + 1} reached",
    "success",
    extra_data={
        "event_type": "waypoint_reached",  # ← Already exists ✓
        "waypoint_id": self.current_waypoint_index + 1,
        "current_waypoint": self.current_waypoint_index + 1,
        "timestamp": current_time,
        "position": self.current_position.copy() if self.current_position else None,
        "waypoint_target": waypoint,
        "message": f"Waypoint {self.current_waypoint_index + 1} reached successfully"
    }
)
```

**Status**: ✓ Already compliant - no change needed

---

#### Change 5: Waypoint Marked Event

**Location**: `hold_period_complete()` method (search for "waypoint_marked")

**Currently implemented as**:
```python
self.emit_status(
    f"Waypoint {self.current_waypoint_index + 1} marking completed",
    "success",
    extra_data={
        "event_type": "waypoint_marked",  # ← Already exists ✓
        "marking_status": "completed",
        "waypoint_id": self.current_waypoint_index + 1,
        "timestamp": datetime.now().isoformat() + "Z",
        "servo_enabled": self.servo_enabled
    }
)
```

**Status**: ✓ Already compliant - no change needed

---

#### Change 6: Mission Completed Event

**Location**: `complete_mission()` method (~line 1080)

**BEFORE**:
```python
self.emit_status(
    "Mission completed successfully",
    "success",
    extra_data={
        "waypoints_completed": self.current_waypoint_index,
        "mission_duration": mission_duration
    }
)
```

**AFTER**:
```python
self.emit_status(
    "Mission completed successfully",
    "success",
    extra_data={
        "event_type": "mission_completed",  # ← ADD THIS LINE
        "waypoints_completed": self.current_waypoint_index,
        "mission_duration": mission_duration
    }
)
```

---

#### Change 7: Waypoint Timeout (Failure) Event

**Location**: `waypoint_timeout()` method (search for this method)

**BEFORE**:
```python
self.emit_status(
    f"Waypoint {self.current_waypoint_index + 1} timeout - marking as failed",
    "error"
)
```

**AFTER**:
```python
self.emit_status(
    f"Waypoint {self.current_waypoint_index + 1} timeout - marking as failed",
    "error",
    extra_data={
        "event_type": "waypoint_failed",  # ← ADD THIS LINE
        "failure_reason": "timeout",
        "current_waypoint": self.current_waypoint_index + 1
    }
)
```

---

### Summary of Mission Controller Changes
- **4 new `event_type` additions** to existing emit_status() calls
- **2 already compliant** (waypoint_reached, waypoint_marked)
- **No API breaking changes** - just adding keys to extra_data dict

---

## PART B: Update Server TTS Handler

### File: `Backend/server.py`

**Location**: `handle_mission_status()` function (~line 1280-1360)

Replace the entire TTS section with structured event type dispatch.

### BEFORE: String-based pattern matching

```python
# TTS announcements for key mission events (non-blocking)
try:
    mission_state = status_data.get('mission_state', '')
    current_wp = status_data.get('current_waypoint', 0)
    total_wp = status_data.get('total_waypoints', 0)
    extra_data = status_data.get('extra_data', {})
    tts_event_type = extra_data.get('event_type') if isinstance(extra_data, dict) else None

    # Mission loaded
    if 'Mission loaded with' in message and 'waypoints' in message:
        count = total_wp
        tts.speak(f"Waypoints loaded: {count} waypoints")
        log_message(f"TTS: Waypoints loaded: {count} waypoints", "DEBUG", event_type='tts')

    # Mission started
    elif 'Mission started' in message and mission_state == 'running':
        tts.speak("Mission started")
        log_message("TTS: Mission started", "DEBUG", event_type='tts')

    # Going to waypoint
    elif 'Executing waypoint' in message and current_wp > 0:
        tts.speak(f"Going to waypoint {current_wp} of {total_wp}")
        log_message(f"TTS: Going to waypoint {current_wp} of {total_wp}", "DEBUG", event_type='tts')

    # Waypoint reached
    elif tts_event_type == 'waypoint_reached':
        tts.speak(f"Waypoint {current_wp} reached")
        log_message(f"TTS: Waypoint {current_wp} reached", "DEBUG", event_type='tts')

    # Waypoint marked complete or failed
    elif tts_event_type == 'waypoint_marked':
        marking_status = extra_data.get('marking_status', '')
        if marking_status == 'completed':
            tts.speak(f"Waypoint {current_wp} marked complete")
            log_message(f"TTS: Waypoint {current_wp} marked complete", "DEBUG", event_type='tts')
        elif marking_status == 'failed' or 'timeout' in message.lower():
            tts.speak(f"Waypoint {current_wp} failed")
            log_message(f"TTS: Waypoint {current_wp} failed", "DEBUG", event_type='tts')

    # Mission completed
    elif 'Mission completed successfully' in message:
        # Extract waypoints completed and duration if available
        waypoints_completed = extra_data.get('waypoints_completed', total_wp)
        mission_duration = extra_data.get('mission_duration', 0)
        if mission_duration > 0:
            tts.speak(f"Mission completed: {waypoints_completed} waypoints in {int(mission_duration)} seconds")
            log_message(f"TTS: Mission completed: {waypoints_completed} waypoints in {int(mission_duration)} seconds", "DEBUG", event_type='tts')
        else:
            tts.speak(f"Mission completed: {waypoints_completed} waypoints")
            log_message(f"TTS: Mission completed: {waypoints_completed} waypoints", "DEBUG", event_type='tts')

    # Errors (but not high-frequency telemetry)
    elif level == 'error' and 'Telemetry' not in message:
        # Keep error messages brief
        error_msg = message[:50]  # Truncate long errors
        tts.speak(f"Error: {error_msg}")
        log_message(f"TTS: Error: {error_msg}", "DEBUG", event_type='tts')

except Exception as e:
    # Silently fail TTS - don't break mission status handling
    print(f"[WARN] TTS announcement failed: {e}", flush=True)
```

### AFTER: Structured event type dispatch

```python
# TTS announcements for key mission events (non-blocking)
try:
    mission_state = status_data.get('mission_state', '')
    current_wp = status_data.get('current_waypoint', 0)
    total_wp = status_data.get('total_waypoints', 0)
    extra_data = status_data.get('extra_data', {})
    event_type = extra_data.get('event_type') if isinstance(extra_data, dict) else None
    
    # Dispatch based on structured event_type instead of string patterns
    if event_type == 'mission_loaded':
        waypoints_count = extra_data.get('waypoints_count', total_wp)
        tts_msg = f"Waypoints loaded: {waypoints_count} waypoints"
        tts.speak(tts_msg)
        log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
    
    elif event_type == 'mission_started':
        tts.speak("Mission started")
        log_message("TTS: Mission started", "DEBUG", event_type='tts')
    
    elif event_type == 'waypoint_executing':
        tts_msg = f"Going to waypoint {current_wp} of {total_wp}"
        tts.speak(tts_msg)
        log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
    
    elif event_type == 'waypoint_reached':
        tts_msg = f"Waypoint {current_wp} reached"
        tts.speak(tts_msg)
        log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
    
    elif event_type == 'waypoint_marked':
        marking_status = extra_data.get('marking_status', '')
        if marking_status == 'completed':
            tts_msg = f"Waypoint {current_wp} marked complete"
            tts.speak(tts_msg)
            log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
        elif marking_status == 'failed':
            tts_msg = f"Waypoint {current_wp} failed"
            tts.speak(tts_msg)
            log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
    
    elif event_type == 'waypoint_failed':
        failure_reason = extra_data.get('failure_reason', 'unknown')
        tts_msg = f"Waypoint {current_wp} failed: {failure_reason}"
        tts.speak(tts_msg)
        log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
    
    elif event_type == 'mission_completed':
        waypoints_completed = extra_data.get('waypoints_completed', total_wp)
        mission_duration = extra_data.get('mission_duration', 0)
        if mission_duration > 0:
            tts_msg = f"Mission completed: {waypoints_completed} waypoints in {int(mission_duration)} seconds"
        else:
            tts_msg = f"Mission completed: {waypoints_completed} waypoints"
        tts.speak(tts_msg)
        log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
    
    elif event_type == 'mission_error':
        # Use event_type for structured error handling
        error_msg = extra_data.get('error_message', message[:50])
        tts_msg = f"Error: {error_msg}"
        tts.speak(tts_msg)
        log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
    
    elif level == 'error' and 'Telemetry' not in message and not event_type:
        # Fallback: Unclassified errors (e.g., from non-refactored code paths)
        error_msg = message[:50]
        tts_msg = f"Error: {error_msg}"
        tts.speak(tts_msg)
        log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')

except Exception as e:
    # Silently fail TTS - don't break mission status handling
    print(f"[WARN] TTS announcement failed: {e}", flush=True)
```

---

## PART C: Update Test Script

### File: `test_tts_integration.py`

The test script already has good coverage. Just verify the expected outputs match the new implementation.

**Changes needed**: Minimal - the test events already include `extra_data` with `event_type`, so they should work as-is.

**Verify lines 65-80**: That test_events already define event_type correctly:
```python
"extra_data": {
    "event_type": "waypoint_reached"  # ← Should already be there
}
```

If any events are missing event_type in their test data, add them following the same pattern.

---

## PART D: Validation & Testing

### Step 1: Manual Code Review

- [ ] All mission controller `emit_status()` calls checked for `event_type` in `extra_data`
- [ ] All TTS triggers in `handle_mission_status()` use event type dispatch
- [ ] No remaining string pattern matching for TTS (except error fallback)
- [ ] Comment headers explain why fallback error handler exists

### Step 2: Unit Test

Run the existing test to verify nothing broke:
```bash
cd /home/flash/NRP_ROS
python3 test_tts_integration.py
```

Expected output:
```
✓ TTS module imported successfully

=== Testing TTS Module ===
Speaking: 'TTS integration test starting'

=== Testing Mission Event TTS Announcements ===
You should hear the following announcements through your Bluetooth speaker:

1. Mission Load
   Expected: "Waypoints loaded: 3 waypoints"
   ✓ Triggered TTS
   Waiting 5 seconds before next announcement...

[... remaining events ...]

=== Test Complete ===
✓ Test finished successfully
```

### Step 3: Field Trial Validation

Run a mini mission with 2-3 waypoints:
1. Load mission → Listen for "Waypoints loaded: X waypoints"
2. Start mission → Listen for "Mission started"
3. Rover executes → Listen for "Going to waypoint 1 of 3"
4. Rover reaches WP → Listen for "Waypoint 1 reached"
5. Servo executes → Listen for "Waypoint 1 marked complete"
6. All WPs done → Listen for "Mission completed: X waypoints in Ys"

---

## PART E: Rollback Plan

If something breaks during implementation:

1. **Revert mission controller changes**:
   ```bash
   git checkout Backend/integrated_mission_controller.py
   ```

2. **Revert server changes**:
   ```bash
   git checkout Backend/server.py
   ```

3. **Restart service**:
   ```bash
   sudo systemctl restart nrp-service
   ```

The old string-based TTS triggers will still work.

---

## PART F: Documentation Updates (Optional)

After implementation, consider updating:

1. **Code comments** in `handle_mission_status()` to explain the event type dispatch
2. **README.md** with a section on mission events and their TTS outputs
3. **JARVIS_VOICE_SYSTEM_ASSESSMENT.md** to mark this action as completed

---

## CHECKLIST

- [ ] Backed up current code (git branch or local copy)
- [ ] Updated `integrated_mission_controller.py` emit_status() calls
- [ ] Updated `server.py` handle_mission_status() TTS handler
- [ ] Verified test script still passes
- [ ] Manual field test with Bluetooth speaker
- [ ] All 6 mission events tested for correct announcements
- [ ] Code reviewed by team member
- [ ] Merged to main branch
- [ ] Documented in git commit message

---

## SUCCESS CRITERIA ✓

After implementation, you should be able to:

1. ✅ Refactor mission controller messages without breaking TTS
2. ✅ Add new mission events by simply adding a new `event_type` case
3. ✅ Trace TTS triggers by searching for `event_type == '...'` (not fragile string patterns)
4. ✅ Unit test TTS mapping by mocking status_data with structured event_types
5. ✅ Have confidence that TTS won't fail due to unrelated message text changes

---

**Estimated Effort**: 2 hours total  
**Complexity**: Moderate (no algorithmic changes, just refactoring)  
**Risk**: Very Low (graceful error handling + rollback available)  
**Impact**: High (increases robustness and maintainability significantly)

