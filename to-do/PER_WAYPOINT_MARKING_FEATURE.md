# Per-Waypoint Marking Feature Implementation Guide

## Overview
Add ability to mark/spray at individual waypoints (optional per waypoint) instead of global ON/OFF.

## Files to Modify
- `Backend/integrated_mission_controller.py`

---

## Step 1: Update `load_mission()` - Accept `mark` field
**Location:** `Backend/integrated_mission_controller.py:521-614`

### What to Add
After line 552 (after `self.log(f"✓ All waypoints validated successfully")`), add:

```python
# Validate and process per-waypoint marking flag
for i, wp in enumerate(waypoints):
    if 'mark' in wp:
        # Ensure mark is boolean
        try:
            waypoints[i]['mark'] = bool(wp['mark'])
        except (TypeError, ValueError):
            waypoints[i]['mark'] = True  # Default to True if invalid
        self.log(f'  WP{i+1}: mark={waypoints[i]["mark"]}')
```

### Why
- Accepts `mark: true/false` in waypoint data
- Provides default backward compatibility
- Logs marking status for each waypoint

---

## Step 2: Update `hold_period_complete()` - Check per-waypoint marking
**Location:** `Backend/integrated_mission_controller.py:1404-1451`

### What to Change (3 modifications)

#### Modification 1: Emit status BEFORE servo decision
Move lines 1412-1427 (emit_status block) to AFTER the servo decision. Replace with:

```python
# Get current waypoint marking preference
waypoint = self.waypoints[self.current_waypoint_index]
should_mark = waypoint.get('mark', self.servo_enabled)

self.log(f'✓ Hold period complete for waypoint {self.current_waypoint_index + 1}')
self.log(f'   Marking decision: {should_mark} (per-waypoint or fallback to global)')

# Emit waypoint_reached event (before servo)
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
```

#### Modification 2: Execute servo conditionally
Replace line 1431 (`self.execute_servo_sequence()`) with:

```python
# Execute servo sequence only if marked
if should_mark:
    self.execute_servo_sequence()
else:
    self.log(f'⏭ Skipping servo - waypoint {self.current_waypoint_index + 1} not marked')
    # Mark as completed (no spray) immediately
    mark_time = datetime.now().isoformat() + "Z"
    self.emit_status(
        f"Waypoint {self.current_waypoint_index + 1} skipped (no marking)",
        "info",
        extra_data={
            "event_type": "waypoint_skipped",
            "waypoint_id": self.current_waypoint_index + 1,
            "current_waypoint": self.current_waypoint_index + 1,
            "timestamp": mark_time,
            "marking_status": "skipped",
            "accuracy_error_mm": getattr(self, 'last_accuracy_error_mm', None),
            "message": f"Waypoint {self.current_waypoint_index + 1} - no marking requested"
        }
    )
```

#### Modification 3: Move waypoint_marked event to servo completion
In `execute_servo_sequence()`, at the end (around line 1397), add:

```python
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
```

---

## Step 3: Update waypoint logging in `load_mission()`
**Location:** `Backend/integrated_mission_controller.py:581-582`

Replace:
```python
for i, wp in enumerate(waypoints, 1):
    self.log(f'  WP{i}: lat={wp["lat"]:.9f}, lng={wp["lng"]:.9f}, alt={wp.get("alt", 10.0)}m')
```

With:
```python
for i, wp in enumerate(waypoints, 1):
    mark_status = wp.get('mark', self.servo_enabled)
    mark_str = 'MARK' if mark_status else 'SKIP'
    self.log(f'  WP{i}: lat={wp["lat"]:.9f}, lng={wp["lng"]:.9f}, alt={wp.get("alt", 10.0)}m [{mark_str}]')
```

---

## Testing

### Test Case 1: Mixed marking
```json
{
  "waypoints": [
    {"lat": 34.0522, "lng": -118.2437, "alt": 10.0, "mark": true},
    {"lat": 34.0532, "lng": -118.2447, "alt": 10.0, "mark": false},
    {"lat": 34.0542, "lng": -118.2457, "alt": 10.0}  // Uses global servo_enabled
  ]
}
```

### Test Case 2: Global fallback (no `mark` field)
```json
{
  "waypoints": [
    {"lat": 34.0522, "lng": -118.2437, "alt": 10.0},
    {"lat": 34.0532, "lng": -118.2447, "alt": 10.0}
  ],
  "config": {
    "servo_enabled": false  // All waypoints skip marking
  }
}
```

---

## Frontend Changes Required

### Waypoint Data Structure
Add `mark` checkbox to waypoint editor:
```typescript
interface Waypoint {
  lat: number;
  lng: number;
  alt: number;
  mark?: boolean;  // Optional - defaults to global servo_enabled
}
```

### UI Update
- Add checkbox: "Mark at this waypoint" (checked by default)
- Show icon indicating mark/skip status in waypoint list
- Display "MARK" or "SKIP" badge on waypoint markers

---

## Backward Compatibility
- Existing missions without `mark` field work as before
- Uses global `servo_enabled` as default
- No breaking changes to current API

---

## Event Types (for frontend)
| Event | Description |
|-------|-------------|
| `waypoint_hold_complete` | Hold period ended, shows if marking will occur |
| `waypoint_marked` | Servo sequence completed successfully |
| `waypoint_skipped` | Waypoint completed without marking |

---

## Edge Cases Handled
1. **Invalid `mark` value**: Defaults to `true`
2. **Missing `mark` field**: Falls back to `self.servo_enabled`
3. **Global servo disabled**: Per-waypoint `mark:true` still works (takes priority)
4. **Empty waypoints**: Validation catches before processing

---

## Summary Flow
```
load_mission()
  ↓ Validate 'mark' field in waypoints
  ↓ Log mark status: WP1 [MARK], WP2 [SKIP]
execute_current_waypoint()
  ↓ Navigate to waypoint
waypoint_reached()
  ↓ Set HOLD mode
  ↓ Start hold timer
hold_period_complete()
  ↓ Check: should_mark = waypoint.get('mark', self.servo_enabled)
  ├─→ if should_mark: execute_servo_sequence()
  │                ├→ Servo ON, wait, OFF
  │                └→ emit waypoint_marked event
  └─→ else: emit waypoint_skipped event
proceed_to_next_waypoint()
```

---

## Notes
- No changes to `execute_servo_sequence()` - keep GPS failsafe checking intact
- Per-waypoint `mark` has priority over global `servo_enabled`
- Frontend should show marking status in mission preview table

---

## My Honest Reasoning - Critical Review of Complete Fix Guide

### WHERE I AGREE (Correct fixes)

- **FIX 1: Move should_mark check before servo call** - AGREE
  - Reason: Correctly implements priority (per-waypoint mark overrides global servo_enabled)

- **FIX 2: Add waypoint_marked event at servo completion** - AGREE
  - Reason: Properly separates hold_complete from marked event

- **FIX 3: Add GPS event when accuracy fails** - AGREE with modification
  - Reason: Frontend needs to know why marking failed
  - Modification needed: Keep both servo_suppressed and waypoint_skipped events for backward compatibility

- **FIX 4: Validate mark field in load_mission** - AGREE
  - Reason: Prevents invalid data types

- **FIX 5: Remove servo_enabled early return** - CRITICAL DISAGREE

---

### CRITICAL ISSUE: FIX 5 IS WRONG

**What FIX 5 says:**
Remove this check: `if not self.servo_enabled: return`

**Why this is INCORRECT:**

Your requirement: User can decide per-waypoint mark/skip
- Waypoint with `mark: true/false` field
- Per-waypoint decision should override global setting

FIX 1 logic:
```python
should_mark = waypoint.get('mark', self.servo_enabled)
```

This gives correct priority:
- If waypoint has `mark: false` → `should_mark = false`
- If waypoint has `mark: true` → `should_mark = true`
- If waypoint has NO `mark` field → `should_mark = self.servo_enabled`

But FIX 5 breaks global servo control:
- User wants global servo disable (servo_enabled = false)
- Does not add mark field to waypoints (uses default)
- Global `servo_enabled = false` is IGNORED
- Servo executes anyway when it shouldn't

**THE CORRECT FIX:**

Keep the global servo check BUT add override parameter:

```python
def execute_servo_sequence(self, override_enabled=False):
    """Execute servo ON/OFF sequence after hold period.
    
    Args:
        override_enabled: If True, ignores global servo_enabled check
    """
    try:
        if not self.servo_enabled and not override_enabled:
            self.log('⚠ Servo control disabled - skipping servo sequence')
            return
        
        # GPS failsafe check remains:
        if accuracy_error_mm > self.accuracy_threshold_mm:
            # ... emit waypoint_skipped (FIX 3)
            return
```

Then FIX 1 calls it with override:
```python
if should_mark:
    self.execute_servo_sequence(override_enabled=True)
```

---

### MINOR CONCERN: FIX 3 EVENT DESIGN

Current FIX 3 changes `servo_suppressed` to `waypoint_skipped`

Issue: Existing frontend systems might depend on `servo_suppressed` event

Better solution: Emit BOTH events for backward compatibility

---

### FINAL VERDICT

- FIX 1: Correct (with FIX 5 modification)
- FIX 2: Correct
- FIX 3: Correct with modification (use dual events)
- FIX 4: Correct
- FIX 5: WRONG - breaks global servo control

**DO NOT APPLY FIX 5 as written. Use override parameter approach instead.**
