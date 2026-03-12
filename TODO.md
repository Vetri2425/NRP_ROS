# Mission Mode Persistence Task
## Status: Planning Phase

### Plan Overview
**Goal**: Add `mission_mode` persistence like `gps_failsafe_mode`
1. Load from `system_settings` in `server.py`
2. Override hardcoded `MissionMode.AUTO` in `__init__`
3. Save on `set_mode()` calls
4. Emit loaded mode after init

### Files to Edit
1. `Backend/server.py` - `load_system_settings()`, add `mission_mode` parsing
2. `Backend/integrated_mission_controller.py` - `__init__()` load from config, `set_mode()` save
3. `Backend/config/mission_controller_config.json` - Add default field

### Dependencies
- None (self-contained)

### Steps
1. ✅ Add `mission_mode` parsing in `server.py`
2. Add config loading in `__init__()` 
3. Update `set_mode()` to persist changes
4. Test init emits correct loaded mode

**Ready to implement - approve to proceed**
