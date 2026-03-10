# Low Priority — 2026-03-10

## 5. Add Pydantic Validation to Critical Endpoints
**Risk:** LOW — no input validation, but frontend is the only client currently
**Effort:** Medium

### Models to create:
- [ ] WaypointModel (lat, lng, alt, command with range validation)
- [ ] MissionUploadModel (waypoints list, mission_type, hold_duration)
- [ ] SetModeRequest (mode with allowed values: GUIDED, AUTO, MANUAL, HOLD, RTL, LOITER, STABILIZE, ACRO)
- [ ] ArmRequest (arm: bool)
- [ ] RTKConfigModel (host, port, mountpoint, username, password)
- [ ] ManualControlModel (RC override channel values with range limits)

### Endpoints to apply validation:
- [ ] POST /api/mission/upload
- [ ] POST /api/arm
- [ ] POST /api/set_mode
- [ ] POST /api/rtk/ntrip_start
- [ ] POST /api/rtk/lora_start
- [ ] Socket.IO: mission_upload event

### Notes:
- Pydantic is already a FastAPI dependency — no install needed
- Add `model_config = {"extra": "ignore"}` for backward compatibility
- Only validate at system boundaries, not internal calls
