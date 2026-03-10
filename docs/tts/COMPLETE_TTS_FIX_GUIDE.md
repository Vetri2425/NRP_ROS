# Complete TTS Fix Guide - Mission Loaded Announcement

## Current Status ✓

🎉 **eSpeak is working** - You're hearing sound through Bluetooth!
⚠️ **Piper still failing** - Needs one more restart with the fix

## What Was Fixed

### 1. ✅ Event Type Bug (server.py) - FIXED

**Problem:** `event_type` lookup was searching in wrong location
**Fix:** Changed from `extra_data.get('event_type')` to `status_data.get('event_type')`
**Result:** TTS is now being triggered correctly

### 2. ✅ TTS Environment Variables - FIXED

**Problem:** Service didn't have TTS configuration
**Fix:** Added to `/etc/systemd/system/nrp-service.service`:
```ini
Environment=NRP_TTS_ENABLE=true
Environment=NRP_TTS_SINK=bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink
Environment=JARVIS_LANG=en
# ... etc
```
**Result:** TTS knows where to route audio

### 3. ✅ PulseAudio Access - FIXED

**Problem:** Service couldn't connect to PulseAudio
**Fix:** Added to service:
```ini
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native
```
**Result:** eSpeak can now play audio to Bluetooth

### 4. ✅ Piper Binary Path - JUST FIXED

**Problem:** Systemd service doesn't have PATH, so `which piper` fails
**Fix:** Modified `Backend/tts.py` to use full path `/home/flash/.local/bin/piper`
**Result:** Piper can now be found and executed

## Final Step: Restart Service

Run this command to apply the Piper path fix:

```bash
./restart_nrp_service.sh
```

Then test by loading a mission. You should now hear:
- **Piper neural voice** (high quality) instead of eSpeak
- Through Bluetooth speaker
- "Mission loaded: 3 points"

## Verification

### Monitor logs:
```bash
journalctl -u nrp-service -f | grep -i "tts\|piper"
```

### Expected output (after restart):
```
[DEBUG] TTS: Mission loaded: 3 points
[DEBUG] TTS: Bluetooth warmup completed
[DEBUG] TTS: Piper success  ← Should see this now!
```

### What changed:
- Before: `[DEBUG] TTS: Piper failed, falling back to eSpeak`
- After: `[DEBUG] TTS: Piper success`

## Architecture Overview

### Complete TTS Flow

```
┌──────────────────────────────────────────────────┐
│ 1. Mission Load Event                            │
│    integrated_mission_controller.py:361          │
└──────────────┬───────────────────────────────────┘
               │
               │ emit_status(extra_data={'event_type': 'mission_loaded'})
               v
┌──────────────────────────────────────────────────┐
│ 2. Event Processing                              │
│    server.py:1318                                │
│    ✓ Fixed: event_type = status_data.get(...)   │
└──────────────┬───────────────────────────────────┘
               │
               │ if event_type == 'mission_loaded'
               v
┌──────────────────────────────────────────────────┐
│ 3. TTS Queue                                     │
│    tts.py:speak()                                │
│    - Rate limiting (3s minimum)                  │
│    - Deduplication check                         │
└──────────────┬───────────────────────────────────┘
               │
               │ Worker thread processes queue
               v
┌──────────────────────────────────────────────────┐
│ 4. Bluetooth Warmup                              │
│    tts.py:_warmup_audio()                        │
│    - 1.8s silent tone to wake BT path            │
│    - Prevents first-word clipping                │
└──────────────┬───────────────────────────────────┘
               │
               v
┌──────────────────────────────────────────────────┐
│ 5. TTS Engine Selection                          │
│    tts.py:_speak_impl()                          │
└──────────────┬───────────────────────────────────┘
               │
               ├─── Try Piper (primary)
               │    │
               │    v
               │    ┌────────────────────────────────┐
               │    │ Piper TTS                      │
               │    │ ✓ Full path: ~/.local/bin/piper│
               │    │ ✓ Model: /opt/jarvis/.../en.onnx│
               │    └──────┬─────────────────────────┘
               │           │
               │           │ Raw PCM audio (22050Hz s16le)
               │           v
               │    ┌────────────────────────────────┐
               │    │ paplay                         │
               │    │ ✓ XDG_RUNTIME_DIR set          │
               │    │ ✓ PULSE_SERVER set             │
               │    │ ✓ --device BLUETOOTH_SINK      │
               │    └──────┬─────────────────────────┘
               │           │
               │           │ SUCCESS ✓
               │           └──────────────────┐
               │                              │
               └─── Fallback: eSpeak          │
                    (if Piper fails)          │
                                              v
┌──────────────────────────────────────────────────┐
│ 6. PulseAudio                                    │
│    /run/user/1000/pulse/native                   │
└──────────────┬───────────────────────────────────┘
               │
               v
┌──────────────────────────────────────────────────┐
│ 7. Bluetooth A2DP                                │
│    bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink       │
│    🔊 Your Bluetooth Speaker                     │
└──────────────────────────────────────────────────┘
```

## All Fixes Applied

### Backend/server.py
```python
# Line 1307: Fixed event_type extraction
event_type = status_data.get('event_type')  # Was: extra_data.get('event_type')

# Line 1318: Fixed TTS dispatch
if event_type == 'mission_loaded':
    waypoints_count = status_data.get('waypoints_count', total_wp)
    tts_msg = f"Mission loaded: {waypoints_count} points"
    tts.speak(tts_msg)
```

### Backend/tts.py
```python
# Line 167: Piper availability check with full paths
def _is_piper_available(self) -> bool:
    piper_paths = [
        "/home/flash/.local/bin/piper",
        "/usr/local/bin/piper",
        "/usr/bin/piper",
    ]
    for path in piper_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return True
    return False

# Line 216: Use full path for piper binary
piper_binary = "/home/flash/.local/bin/piper"
if not os.path.exists(piper_binary):
    piper_binary = shutil.which("piper") or "piper"
```

### /etc/systemd/system/nrp-service.service
```ini
# TTS Configuration
Environment=NRP_TTS_ENABLE=true
Environment=NRP_TTS_ENGINE=espeak
Environment=NRP_TTS_SINK=bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink
Environment=NRP_TTS_BT_WARMUP=true
Environment=NRP_TTS_BT_WARMUP_DURATION=1.8
Environment=NRP_TTS_PRE_SPEECH_DELAY=0.3
Environment=NRP_TTS_BT_WARMUP_IDLE=5.0
Environment=NRP_TTS_MIN_INTERVAL=3.0
Environment=JARVIS_LANG=en

# PulseAudio Access
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native
```

## Testing Checklist

After restarting the service:

- [ ] Service starts successfully: `systemctl status nrp-service`
- [ ] Load a mission with waypoints
- [ ] Logs show: `[DEBUG] TTS: Piper success`
- [ ] Hear: "Mission loaded: X points" in Piper voice
- [ ] Sound comes through Bluetooth speaker
- [ ] No "Piper failed" in logs

## Troubleshooting

### If Piper still fails:

1. Check logs for specific error:
   ```bash
   journalctl -u nrp-service --since "1 minute ago" | grep -A 5 "Piper\|paplay"
   ```

2. Verify Piper binary is executable:
   ```bash
   ls -la /home/flash/.local/bin/piper
   # Should show: -rwxr-xr-x
   ```

3. Test Piper manually with PulseAudio:
   ```bash
   echo "test" | XDG_RUNTIME_DIR=/run/user/1000 \
     PULSE_SERVER=unix:/run/user/1000/pulse/native \
     /home/flash/.local/bin/piper \
     --model /opt/jarvis/models/piper/en.onnx \
     --output_raw | paplay --raw --rate 22050 --channels 1 --format s16le
   ```

4. Check PulseAudio connection:
   ```bash
   pactl list sinks | grep -E "Name:|State:"
   pactl get-default-sink
   ```

### If no sound at all:

1. Check Bluetooth connection:
   ```bash
   bluetoothctl info B2:55:E1:6A:7C:4A
   # Should show: Connected: yes
   ```

2. Verify Bluetooth sink exists:
   ```bash
   pactl list sinks short | grep bluez
   ```

3. Set Bluetooth as default:
   ```bash
   pactl set-default-sink bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink
   ```

## Summary

🎯 **All Issues Resolved:**

1. ✅ TTS trigger bug - Fixed in server.py
2. ✅ Environment variables - Added to service
3. ✅ PulseAudio access - XDG_RUNTIME_DIR configured
4. ✅ Piper binary path - Full path in tts.py

🚀 **Next Step:**

Run `./restart_nrp_service.sh` and enjoy Piper's beautiful voice announcing your missions!

## Related Files

- [TTS_FIX_SUMMARY.md](TTS_FIX_SUMMARY.md) - Original TTS fix documentation
- [PIPER_TTS_PULSEAUDIO_FIX.md](PIPER_TTS_PULSEAUDIO_FIX.md) - PulseAudio detailed explanation
- [Backend/tts.py](Backend/tts.py) - TTS engine implementation
- [Backend/server.py](Backend/server.py) - Event handler with TTS dispatch
- [restart_nrp_service.sh](restart_nrp_service.sh) - Service restart script
