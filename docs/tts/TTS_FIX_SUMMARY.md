# TTS "Mission Loaded" Announcement Fix

## Problem Summary

When loading a mission in the Mission Controller, the TTS announcement "Mission loaded: X points" was not being spoken through the Bluetooth speaker.

## Root Causes Identified

### 1. **Event Type Lookup Bug in server.py** (PRIMARY ISSUE - FIXED ✓)

**Location:** [Backend/server.py:1318](Backend/server.py#L1318)

**The Bug:**
```python
# WRONG - Looking for event_type in wrong location
extra_data = status_data.get('extra_data', {})
event_type = extra_data.get('event_type') if isinstance(extra_data, dict) else None
```

**Why it Failed:**
1. In `integrated_mission_controller.py` line 361-370, when `emit_status()` is called:
   ```python
   self.emit_status(
       "Mission loaded with 3 waypoints",
       "success",
       extra_data={
           "event_type": "mission_loaded",
           "waypoints_count": 3
       }
   )
   ```

2. The `emit_status` method uses `status_data.update(extra_data)` which **merges** `extra_data` directly into `status_data`

3. So the final `status_data` looks like:
   ```python
   {
       'message': 'Mission loaded with 3 waypoints',
       'level': 'success',
       'event_type': 'mission_loaded',      # ← At TOP LEVEL
       'waypoints_count': 3,                # ← At TOP LEVEL
       # No 'extra_data' key exists!
   }
   ```

4. The server tried to access `status_data['extra_data']['event_type']` but `status_data['extra_data']` doesn't exist!

5. Result: `event_type` was always `None`, so TTS was never triggered

**The Fix:**
```python
# CORRECT - Look at top level of status_data
event_type = status_data.get('event_type')
```

**Files Modified:**
- [Backend/server.py](Backend/server.py) - Lines 1307, 1318, 1342, 1349, 1367

### 2. **Missing TTS Environment Variables in systemd Service** (SECONDARY ISSUE)

**Problem:** The `nrp-service.service` systemd unit file doesn't include TTS configuration environment variables.

**Result:**
- Piper TTS fails (no model path configured)
- eSpeak fallback works but doesn't route to Bluetooth speaker
- No audio output despite TTS being triggered

**Required Environment Variables:**
```bash
NRP_TTS_ENABLE=true
NRP_TTS_ENGINE=espeak
NRP_TTS_SINK=bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink
NRP_TTS_BT_WARMUP=true
NRP_TTS_BT_WARMUP_DURATION=1.8
NRP_TTS_PRE_SPEECH_DELAY=0.3
NRP_TTS_BT_WARMUP_IDLE=5.0
NRP_TTS_MIN_INTERVAL=3.0
JARVIS_LANG=en
```

**Solution:** Run the provided script to add these to the service file.

## How to Apply the Complete Fix

### Step 1: Verify Code Fix (Already Applied ✓)

The code fix in `Backend/server.py` has been applied. The TTS is now being triggered correctly (confirmed by logs showing "TTS: Mission loaded: 3 points").

### Step 2: Add TTS Environment Variables to Service

Run this command:
```bash
cd /home/flash/NRP_ROS
./add_tts_env_to_service.sh
```

This will:
1. Backup the current service file
2. Add TTS environment variables
3. Reload systemd
4. Restart the service

### Step 3: Test

1. Load a mission with 3 waypoints
2. You should hear: "Mission loaded: 3 points"

Monitor logs:
```bash
journalctl -u nrp-service -f | grep -i "tts\|piper\|espeak"
```

Expected output after fix:
```
[DEBUG] TTS: Mission loaded: 3 points
[DEBUG] TTS: Bluetooth warmup completed
[DEBUG] TTS: Piper success
```

OR (if Piper not configured):
```
[DEBUG] TTS: Mission loaded: 3 points
[DEBUG] TTS: Bluetooth warmup completed
[DEBUG] TTS: eSpeak fallback success
```

## Verification

### Before Fix:
```bash
# Event type was None
event_type = extra_data.get('event_type')  # → None
if event_type == 'mission_loaded':         # → False (never executed)
    tts.speak("Mission loaded...")         # → Never called
```

### After Fix:
```bash
# Event type is correctly found
event_type = status_data.get('event_type')  # → 'mission_loaded'
if event_type == 'mission_loaded':          # → True ✓
    tts.speak("Mission loaded: 3 points")   # → Called! ✓
```

## TTS Architecture

### TTS Module ([Backend/tts.py](Backend/tts.py))

**Features:**
- Non-blocking queue-based worker thread
- Rate limiting (3 second minimum between announcements)
- Deduplication (same message within interval)
- Bluetooth warmup to prevent first-word clipping
- Multi-engine support with fallback chain:
  1. **Piper TTS** (high-quality neural voice) → Primary
  2. **eSpeak** (low-latency, always available) → Fallback
  3. **pyttsx3** (Python TTS library) → Last resort

**Bluetooth Audio Handling:**
- Pre-warms Bluetooth path with silent tone (~1.8 seconds)
- Adds leading silence to speech to prevent clipping
- Routes audio through PulseAudio to Bluetooth sink
- Auto-detects or uses configured sink

### Server Integration ([Backend/server.py](Backend/server.py))

**Event-Driven TTS Dispatch:**
```python
def handle_mission_status(status_data: dict):
    event_type = status_data.get('event_type')

    if event_type == 'mission_loaded':
        tts.speak(f"Mission loaded: {waypoints_count} points")
    elif event_type == 'mission_started':
        tts.speak("Mission started")
    elif event_type == 'waypoint_reached':
        tts.speak(f"Waypoint {current_wp} reached")
    # ... more events
```

**Supported Events:**
- `mission_loaded` - Mission loaded announcement
- `mission_started` - Mission start confirmation
- `waypoint_executing` - "Going to waypoint X of Y"
- `waypoint_reached` - Waypoint arrival confirmation
- `waypoint_marked` - Waypoint marking completed
- `mission_completed` - Mission completion summary
- `mission_error` - Error announcements

## Related Files

- [Backend/tts.py](Backend/tts.py) - TTS worker implementation
- [Backend/server.py](Backend/server.py) - Mission status handler with TTS dispatch
- [Backend/integrated_mission_controller.py](Backend/integrated_mission_controller.py) - Mission controller that emits events
- [add_tts_env_to_service.sh](add_tts_env_to_service.sh) - Script to add env vars to service
- `/etc/systemd/system/nrp-service.service` - Systemd service file

## Testing

### Manual Test (Standalone):
```bash
cd /home/flash/NRP_ROS
python3 test_tts_simple.py
```

### Test with Fix Simulation:
```bash
python3 test_tts_fix.py
```

### Full Integration Test:
1. Start service: `sudo systemctl start nrp-service`
2. Open frontend
3. Load a mission with waypoints
4. Listen for "Mission loaded: X points"

## Troubleshooting

### No sound but TTS logs show success:

Check PulseAudio sink:
```bash
pactl list sinks short
pactl get-default-sink
```

Set correct sink:
```bash
export NRP_TTS_SINK=bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink
```

### Piper fails:

Check model exists:
```bash
ls -la /opt/jarvis/models/piper/en.onnx
```

Check piper binary:
```bash
which piper
/home/flash/.local/bin/piper --version
```

### eSpeak works but no Bluetooth audio:

Verify Bluetooth connection:
```bash
bluetoothctl info B2:55:E1:6A:7C:4A
```

Test audio routing:
```bash
echo "test" | espeak --stdout | paplay --device bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink
```

## Summary

The TTS system is working correctly at the code level. The primary bug (event_type lookup) has been fixed. The remaining step is to add TTS environment variables to the systemd service so audio routes correctly to the Bluetooth speaker when running as a service.
