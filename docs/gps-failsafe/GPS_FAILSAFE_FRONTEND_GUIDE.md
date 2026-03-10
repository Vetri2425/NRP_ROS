# GPS Failsafe Backend - Quick Reference for Frontend Team

## What's Ready on Backend ✅

The GPS failsafe system is fully implemented and tested on the backend. Three operational modes are ready:

| Mode | Behavior | Use Case |
|------|----------|----------|
| **disable** | No failsafe checks | Testing, stationary work |
| **strict** | Mission pauses + await user ack | Precision spraying missions |
| **relax** | Servo suppression only | Regular agricultural missions |

## Socket.IO Events Reference

### Send from Frontend → Backend

```javascript
// 1. Set failsafe mode (call BEFORE starting mission)
socket.emit('set_gps_failsafe_mode', { mode: 'strict' })
socket.emit('set_gps_failsafe_mode', { mode: 'relax' })
socket.emit('set_gps_failsafe_mode', { mode: 'disable' })

// 2. User acknowledges failsafe trigger (strict mode popup only)
socket.emit('failsafe_acknowledge')

// 3. Resume mission after stable window (strict mode)
socket.emit('failsafe_resume_mission')

// 4. Restart mission from waypoint 1 (strict mode alternative)
socket.emit('failsafe_restart_mission')
```

### Receive from Backend → Frontend

```javascript
// Emitted when failsafe state changes (listen continuously)
socket.on('rover_data', (data) => {
  const {
    gps_failsafe_mode,              // "disable", "strict", or "relax"
    gps_failsafe_triggered,         // boolean
    gps_failsafe_accuracy_error_mm, // float (millimeters)
    gps_failsafe_servo_suppressed   // boolean
  } = data
})

// Emitted when servo is suppressed in relax mode
socket.on('servo_suppressed', (event) => {
  console.log(`Accuracy: ${event.accuracy_error_mm}mm (threshold: ${event.threshold_mm}mm)`)
})

// Confirmation events
socket.on('failsafe_mode_changed', (data) => {
  console.log(`Failsafe mode: ${data.mode}`)
})

socket.on('failsafe_acknowledged', (data) => {
  console.log('User acknowledged. Starting 5-second stable window...')
})

socket.on('failsafe_resumed', (data) => {
  console.log('Mission resumed from current waypoint')
})

socket.on('failsafe_restarted', (data) => {
  console.log('Mission restarted from waypoint 1')
})

socket.on('failsafe_error', (data) => {
  console.error(`Error: ${data.message}`)
})
```

## Implementation Checklist for Frontend

### Pre-Mission Setup
- [ ] Add mode selector dropdown (options: disable, strict, relax)
- [ ] Emit `set_gps_failsafe_mode` when user selects mode
- [ ] Display current failsafe mode in mission details panel

### During Mission - Continuous Display
- [ ] Listen to `rover_data` events (~20Hz)
- [ ] Display current failsafe mode (text or icon)
- [ ] Display accuracy error in real-time (e.g., "Accuracy: 45mm")
- [ ] Show servo suppression indicator when `gps_failsafe_servo_suppressed = true`

### Strict Mode - Failsafe Popup
- [ ] Listen for `servo_suppressed` events
- [ ] Show modal popup with:
  - Title: "GPS Failsafe Triggered"
  - Message: "Accuracy error: {X}mm (threshold: 60mm)"
  - Button: "[Acknowledge]"
- [ ] On button click: Emit `failsafe_acknowledge`
- [ ] After 5 seconds: Show options:
  - "[Resume Mission]" → emit `failsafe_resume_mission`
  - "[Restart Mission]" → emit `failsafe_restart_mission`
  - "[Stop Mission]" → emit `stop_mission` (existing)

### Relax Mode - Silent Suppression
- [ ] Listen for `servo_suppressed` events (for logging)
- [ ] Show brief notification (e.g., "Spray suppressed: accuracy violation")
- [ ] Auto-dismiss after 3 seconds (mission continues)
- [ ] Resume spraying automatically after 5 seconds if conditions recover

## Data Fields in rover_data

```json
{
  "gps_failsafe_mode": "strict",           // Current mode
  "gps_failsafe_triggered": false,         // Has failsafe been triggered
  "gps_failsafe_accuracy_error_mm": 42.5,  // Distance error from target
  "gps_failsafe_servo_suppressed": false,  // Is servo blocked
  
  // ... existing fields ...
  "position": { "lat": 40.0, "lng": -74.0 },
  "rtk_fix_type": 6,    // 6 = RTK Fixed (ideal)
  "satellites_visible": 12
}
```

## Thresholds to Know

| Metric | Value | Meaning |
|--------|-------|---------|
| **Accuracy Threshold** | 60mm | Max acceptable distance error from target |
| **RTK Fix Type Target** | 6 | RTK Fixed (0-6 scale; 6 is best) |
| **Stable Window** | 5 sec | Duration to confirm conditions are stable before resuming |

## Test Scenarios

### Test 1: Disable Mode (Default)
1. Set mode to `disable`
2. Load mission and start
3. Expected: Mission runs normally, no failsafe checks

### Test 2: Strict Mode - Accurate Position
1. Set mode to `strict`
2. Rover reaches waypoint with accuracy < 60mm
3. Expected: Servo executes normally, mission continues

### Test 3: Strict Mode - Inaccurate Position
1. Set mode to `strict`
2. Rover reaches waypoint with accuracy > 60mm
3. Expected: Popup appears → User clicks acknowledge → 5s timer → Resume/Restart options

### Test 4: Relax Mode - Accuracy Violation
1. Set mode to `relax`
2. Rover reaches waypoint with accuracy > 60mm
3. Expected: Notification appears briefly → Spray skipped → Mission continues → Recovery after 5s

### Test 5: RTK Fix Type Loss
1. Any mode with RTK Fix Type ≠ 6
2. Expected: Servo behavior matches mode (pause for strict, suppress for relax)

## Backend Files Modified

| File | Changes | Status |
|------|---------|--------|
| `Backend/gps_failsafe_monitor.py` | New file (320 lines) | ✅ Complete |
| `Backend/integrated_mission_controller.py` | Servo suppression logic (~70 lines) | ✅ Complete |
| `Backend/server.py` | Socket.IO handlers + state fields (~120 lines) | ✅ Complete |

## Verification Command

Run this to verify backend is ready:
```bash
cd /home/flash/NRP_ROS && python3 verify_gps_failsafe.py
```

Expected output: `✅ ALL TESTS PASSED`

## Integration Workflow

1. **Frontend loads mission page**
   - Display failsafe mode selector: [disable ▼]

2. **User selects mode**
   - Emit: `set_gps_failsafe_mode({ mode: 'strict' })`
   - Receive: `failsafe_mode_changed` confirmation

3. **User starts mission**
   - Backend calls `mission_controller.set_failsafe_mode(mode)`
   - Mission begins with failsafe enabled

4. **Rover reaches waypoint**
   - Backend calculates accuracy error
   - Compares to 60mm threshold
   - Decision: proceed normally, pause (strict), or suppress servo (relax)

5. **Frontend receives updates**
   - Continuous `rover_data` with accuracy_error_mm
   - Optional `servo_suppressed` event on violation

6. **Strict mode: Failsafe triggered**
   - Backend emits `servo_suppressed` event
   - Frontend shows popup with ack button
   - User clicks ack → Backend starts 5s stable window
   - After 5s → Frontend shows resume/restart options

## Troubleshooting

**Q: Mode selector not working?**
- A: Ensure `mission_controller` is initialized (wait for MAVROS connection)
- Check server logs for: "Integrated mission controller initialized"

**Q: Failsafe popup not appearing?**
- A: Verify you're listening to `servo_suppressed` event
- Check accuracy in rover_data is > 60mm

**Q: Relay mode not suppressing servo?**
- A: Verify `gps_failsafe_servo_suppressed` is true in rover_data
- Check RTK fix type is 6 (not degraded)

**Q: Mission pausing unexpectedly in relax mode?**
- A: Relax mode should NOT pause, only suppress servo
- If pausing, check you're sending correct mode value

## Performance Notes

- Accuracy calculations happen only at waypoint arrival (not continuous)
- Failsafe state machine runs in background thread (non-blocking)
- Rover_data emissions continue at ~20Hz (unaffected by failsafe)
- No measurable CPU impact from failsafe monitoring

## Next Phase

Frontend implementation should include:
- Mode selector UI component
- Failsafe trigger popup modal
- Servo suppression visual indicator
- Accuracy error display in telemetry panel
- Socket.IO event emitters and listeners

---

**Status:** Backend implementation ✅ COMPLETE
**Frontend Status:** Ready for development
**Testing:** All unit and integration tests passing
