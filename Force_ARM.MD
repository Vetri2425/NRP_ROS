Complete Arm → Force-Arm → Mission Flow

POST /api/mission/start
        ↓
  Already armed?
    YES ──────────────────────────────────────→ mission starts ✅
    NO  → emit "mission_arming" (info)
        ↓
  ensure_pixhawk_armed()
    SUCCESS ──────────────────────────────────→ mission starts ✅
    FAIL → emit "mission_arm_force_confirm" (warning)
           set _pending_force_arm_start = True
           return HTTP 400 { requires_force_arm: true }
        ↓
  FroForce-arm the rover?"
  [YES]                          [NO / Cancel]
    ↓                              ↓
  emit force_arm_confirm        emit force_arm_confirm
  { "confirm": true }           { "confirm": false }
    ↓                              ↓
  bridge.force_arm()            clear pending flag
  (MAV_CMD 400 + magic 21196)   emit "mission_arm_cancelled"
    SUCCESS → mission starts ✅
    FAIL    → emit "mission_arm_error" ❌
              "Force-arm failed. Check vehicle safety conditions."
Events frontend must handle:
event_type	level	Action
mission_arming	info	Show spinner "Arming..."
mission_arm_force_confirm	warning	Show dialog "Auto-arm failed. Force-arm?"
mission_arm_cancelled	info	Dismiss dialog
mission_arm_error	error	Show error toast
mission_started	success	Show mission running UI
Frontend sends (to accept/reject):

socket.emit('force_arm_confirm', { confirm: true })   // user pressed YES
socket.emit('force_arm_confirm', { confirm: false })  // user pressed NO