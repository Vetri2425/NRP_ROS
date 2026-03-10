# GPS Failsafe Debug Guide - Strict Mode RTK Movement Control

## What Was Fixed

**Problem:** Strict mode wasn't pausing the rover when RTK fix was lost.

**Root Cause:** 
1. Mode was being set ✅ 
2. Accuracy servo check was implemented ✅
3. **BUT: RTK movement control for strict mode was MISSING** ❌

**Solution Implemented:**
- Added RTK fix type tracking in mission controller
- Added `check_rtk_fix_for_movement()` method
- Added RTK check in `proceed_to_next_waypoint()` 
- Enhanced logging to track mode changes

---

## How It Works Now

### **STRICT Mode Flow**
```
Waypoint reached
    ↓
Hold period completes
    ↓
servo sequence executes (accuracy check here)
    ↓
Hold period done, ready for next waypoint
    ↓
proceed_to_next_waypoint() called
    ↓
CHECK RTK FIX TYPE ← NEW!
    ├─ If fix_type ≠ 6: PAUSE mission + HOLD mode + log warning
    └─ If fix_type = 6: Continue to next waypoint
```

### **RELAX Mode Flow**
```
Same as above, but...
    ↓
CHECK RTK FIX TYPE
    ├─ Always allows movement (no RTK check)
    └─ Continue to next waypoint regardless of RTK
```

---

## Logging Checklist - What to Look For

### **1. Frontend sends mode**
Look in `journalctl -u nrp-service -f` for:
```
🎛 FAILSAFE MODE REQUEST: strict
```

### **2. Mode received and set**
```
✅ Updated current_state.gps_failsafe_mode to: strict
✅ Mission controller mode set: {'success': True, 'message': 'Failsafe mode: STRICT'}
```

### **3. Mission starts**
```
[MISSION_CONTROLLER] Mission started
GPS Failsafe Monitor initialized
```

### **4. Waypoint reached**
```
✅ WAYPOINT 1 REACHED
Position: lat=40.123456, lng=-74.123456
⏱ Starting 2.0s hold period
```

### **5. Servo sequence completes**
```
🎯 STARTING SERVO SEQUENCE
📡 Setting servo 9 to 2300µs (ON)
⏱ Waiting 0.5s (spray duration)...
📡 Setting servo 9 to 1750µs (OFF)
```

### **6. NOW - THE RTK CHECK (New!)**

**If RTK is GOOD (fix_type = 6):**
```
➡ Proceeding to next waypoint (2/3)
```

**If RTK is BAD (fix_type ≠ 6) in STRICT mode:**
```
❌ STRICT MODE - RTK FIX BLOCKED: fix_type=1 (need 6)
⏸ PAUSING MISSION - Awaiting RTK recovery in STRICT mode
🛑 Setting HOLD mode
```

---

## Testing Steps

### **Test 1: Verify Mode is Accepted**
```bash
# In browser console, connect via Socket.IO:
socket.emit('set_gps_failsafe_mode', { mode: 'strict' })

# Watch for:
socket.on('failsafe_mode_changed', (data) => {
  console.log('Mode changed:', data.mode)  // Should print: 'strict'
})
```

**Check logs for:**
```
🎛 FAILSAFE MODE REQUEST: strict
✅ Updated current_state.gps_failsafe_mode to: strict
```

### **Test 2: Verify RTK Data is Flowing**

Check if RTK fix type is being sent from backend:
```bash
journalctl -u nrp-service -f | grep -i "rtk_fix_type\|fix_type"
```

Should see RTK status in rover_data (every ~20Hz):
```
[DEBUG] get_rover_data() sending rtk_fix_type=6
```

**If you DON'T see RTK data:**
- Check: `/mavros/gpsstatus/gps1/raw` is publishing
- Check: Backend is receiving it

### **Test 3: Simulate RTK Loss in Strict Mode**

1. Start mission with `strict` mode
2. Rover reaches waypoint
3. **Manually stop RTK base station** (simulate loss)
4. RTK fix_type will drop to 1 (GPS only)
5. **Expect: Rover STOPS and sets HOLD mode**

Check logs:
```
❌ STRICT MODE - RTK FIX BLOCKED: fix_type=1 (need 6)
⏸ PAUSING MISSION - Awaiting RTK recovery
🛑 Setting HOLD mode
```

### **Test 4: Relax Mode Ignores RTK Loss**

1. Start mission with `relax` mode
2. Rover reaches waypoint
3. Manually stop RTK base
4. **Expect: Rover CONTINUES to next waypoint**

Check logs:
```
➡ Proceeding to next waypoint (2/3)
```
(No RTK block message should appear)

---

## Key Log Entries to Monitor

| What | Log Message | Status |
|-----|-------------|--------|
| Mode set | `🎛 FAILSAFE MODE REQUEST: strict` | Should appear when frontend sends |
| Mode confirmed | `✅ Updated current_state.gps_failsafe_mode to: strict` | Should appear immediately |
| RTK tracked | `rtk_fix_type=6` | Should appear continuously |
| RTK loss detected (STRICT) | `❌ STRICT MODE - RTK FIX BLOCKED: fix_type=1` | Should appear when fix_type ≠ 6 |
| Mission paused (STRICT) | `⏸ PAUSING MISSION - Awaiting RTK recovery` | Should follow RTK block |
| HOLD mode set | `🛑 Setting HOLD mode` | Should follow pause |
| Waypoint continues (RELAX) | `➡ Proceeding to next waypoint` | Should appear even with low RTK |

---

## Debugging Commands

### **1. Check Current Mode in Real-time**
```bash
journalctl -u nrp-service -f | grep -E "FAILSAFE MODE|gps_failsafe_mode"
```

### **2. Check RTK Fix Type Updates**
```bash
journalctl -u nrp-service -f | grep -E "rtk_fix_type|fix_type"
```

### **3. Check Mission Pause Events**
```bash
journalctl -u nrp-service -f | grep -E "RTK FIX BLOCKED|PAUSING MISSION|HOLD mode"
```

### **4. Check All GPS Failsafe Events**
```bash
journalctl -u nrp-service -f | grep -i "failsafe\|rtk"
```

### **5. Check Socket.IO Events**
```bash
journalctl -u nrp-service -f | grep "failsafe\|set_gps"
```

---

## Troubleshooting

### **Problem: Mode set but rover still moves in strict mode with RTK loss**

**Check:**
1. Is `rtk_fix_type` being tracked?
   ```bash
   journalctl -u nrp-service -f | grep "rtk_fix_type"
   ```
   - If NOT seeing this: RTK data not reaching mission controller

2. Is `proceed_to_next_waypoint()` being called?
   ```bash
   journalctl -u nrp-service -f | grep "Proceeding to next waypoint\|RTK FIX BLOCKED"
   ```
   - If NOT seeing either: Mission not progressing

3. What is the mode really set to?
   ```bash
   journalctl -u nrp-service -f | grep "gps_failsafe_mode"
   ```
   - Confirm it shows: `FAILSAFE MODE REQUEST: strict`

### **Problem: All modes block rover movement**

**Check:**
1. Is RTK always degraded?
   ```bash
   journalctl -u nrp-service -f | grep "rtk_fix_type"
   ```
   - If always `rtk_fix_type=1`, need to check RTK base station

2. Is `failsafe_mode` set to something other than "disable"?
   ```bash
   journalctl -u nrp-service -f | grep "FAILSAFE MODE REQUEST\|gps_failsafe_mode"
   ```

### **Problem: Relax mode blocks servo but still moves (correct)**

This is working as designed:
- Movement: Allowed ✅
- Servo/spray: Blocked if accuracy > 60mm ✅

Check accuracy in logs:
```bash
journalctl -u nrp-service -f | grep "GPS Accuracy\|accuracy_error_mm"
```

---

## Data Structure - What Gets Sent

### **rover_data includes:**
```json
{
  "gps_failsafe_mode": "strict",
  "gps_failsafe_triggered": false,
  "gps_failsafe_accuracy_error_mm": 45.3,
  "gps_failsafe_servo_suppressed": false
}
```

### **When RTK Loss in Strict Mode:**
```json
{
  "event_type": "rtk_fix_loss",
  "rtk_fix_type": 1,
  "required_fix_type": 6,
  "failsafe_mode": "strict",
  "current_waypoint": 2
}
```

---

## Summary of Changes

### **Files Modified:**
1. **integrated_mission_controller.py:**
   - Added: `self.rtk_fix_type` tracking
   - Added: `check_rtk_fix_for_movement()` method
   - Modified: `proceed_to_next_waypoint()` to check RTK in strict mode
   - Modified: `handle_telemetry_update()` to capture RTK fix type

2. **server.py:**
   - Enhanced: `handle_set_gps_failsafe_mode()` with detailed logging

### **Logic Flow:**
```
Failsafe Mode Selection (Frontend)
  ↓
set_gps_failsafe_mode handler (Server)
  ↓ (with logging)
mission_controller.set_failsafe_mode()
  ↓
Stored in mission_controller.failsafe_mode
  ↓
At waypoint hold completion:
  - Servo sequence checks accuracy (all modes)
  - proceed_to_next_waypoint() checks RTK (strict mode only)
```

---

## Expected Behavior Summary

| Scenario | Strict Mode | Relax Mode | Disable Mode |
|----------|-------------|-----------|--------------|
| **RTK Fix Good** | ✅ Move ✅ Spray | ✅ Move ✅ Spray | ✅ Move ✅ Spray |
| **RTK Fix Bad** | ❌ PAUSE | ✅ Move ✅ Spray | ✅ Move ✅ Spray |
| **Accuracy Bad** | ❌ Skip spray | ❌ Skip spray | ✅ Spray |

---

**Now test it and check the logs!**
