# Piper TTS + PulseAudio Fix for Systemd Service

## Problem

When running the NRP service via systemd (`nrp-service`), the TTS system shows:

```
[DEBUG] TTS: Mission loaded: 3 points
[DEBUG] TTS: Bluetooth warmup completed
[DEBUG] TTS: Piper failed, falling back to eSpeak
[DEBUG] TTS: eSpeak fallback success
```

**Piper is failing** even though:
- ✓ TTS is being triggered correctly (code fix working)
- ✓ Piper binary is available (`/home/flash/.local/bin/piper`)
- ✓ Piper model exists (`/opt/jarvis/models/piper/en.onnx`)
- ✓ Environment variables are set (`NRP_TTS_SINK`, etc.)

## Root Cause

### Issue: PulseAudio Session Access

The `nrp-service` systemd unit runs without access to the **user's PulseAudio session**.

**Why Piper Fails:**

1. Piper generates raw PCM audio and pipes it to `paplay`
2. `paplay` tries to connect to PulseAudio to play the audio
3. PulseAudio runs as a **per-user session service** at `/run/user/1000/pulse/native`
4. The systemd service doesn't have the environment variables to find this socket:
   - `XDG_RUNTIME_DIR=/run/user/1000` - Location of user runtime files
   - `PULSE_SERVER=unix:/run/user/1000/pulse/native` - PulseAudio socket path

**Error Symptoms in Logs:**

```
Failed to open audio file.
Connection failure: Connection refused
pa_context_connect() failed: Connection refused
```

This means `paplay` (used by Piper) **cannot connect to PulseAudio** → Piper fails → Falls back to eSpeak.

### Why eSpeak Works (But No Sound)

eSpeak has the same PulseAudio connection issue, but it:
- Returns success even when audio routing fails
- Might output to a different audio backend (ALSA) that doesn't reach Bluetooth
- Doesn't properly fail, so logs show "success" but no sound is heard

## The Fix

Add PulseAudio session access environment variables to the systemd service.

### Step 1: Run the Fix Script

```bash
cd /home/flash/NRP_ROS
./fix_pulseaudio_service.sh
```

This adds to `/etc/systemd/system/nrp-service.service`:

```ini
# PulseAudio Access
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native
```

### Step 2: Verify

Check that the variables are set:

```bash
systemctl show nrp-service | grep XDG
systemctl show nrp-service | grep PULSE
```

Expected output:
```
Environment=XDG_RUNTIME_DIR=/run/user/1000 ...
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native ...
```

### Step 3: Test

1. Load a mission with 3 waypoints
2. Monitor logs: `journalctl -u nrp-service -f | grep TTS`

**Expected output (after fix):**
```
[DEBUG] TTS: Mission loaded: 3 points
[DEBUG] TTS: Bluetooth warmup completed
[DEBUG] TTS: Piper success
```

You should hear: **"Mission loaded: 3 points"** through your Bluetooth speaker with Piper's high-quality voice!

## Technical Details

### TTS Audio Pipeline (Piper Path)

```
┌─────────────────┐
│ Mission Loaded  │
│     Event       │
└────────┬────────┘
         │
         v
┌─────────────────┐
│  server.py:1321 │  ← Fixed: event_type lookup
│  tts.speak()    │
└────────┬────────┘
         │
         v
┌─────────────────┐
│   tts.py:184    │
│ _speak_piper()  │
└────────┬────────┘
         │
         v
┌─────────────────────────────────────────┐
│  Piper TTS Process                      │
│  piper --model en.onnx --output_raw     │
│  Generates: Raw PCM audio (s16le)       │
└────────┬────────────────────────────────┘
         │ stdin: text
         │ stdout: raw PCM
         v
┌─────────────────────────────────────────┐
│  paplay Process                         │
│  paplay --raw --device BLUETOOTH_SINK   │
│         --rate 22050 --format s16le     │
│                                         │
│  Needs: XDG_RUNTIME_DIR (find socket)   │
│         PULSE_SERVER (connect to PA)    │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────┐
│  PulseAudio     │  @ /run/user/1000/pulse/native
│  Session        │
└────────┬────────┘
         │
         v
┌─────────────────┐
│  Bluetooth A2DP │  bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink
│  Speaker        │
└─────────────────┘
```

### Why Systemd Services Need XDG_RUNTIME_DIR

**User Session vs System Service:**

- **User Session** (terminal, desktop apps):
  - Automatically has `XDG_RUNTIME_DIR=/run/user/1000`
  - PulseAudio socket is accessible
  - Audio works out-of-the-box

- **Systemd Service** (nrp-service):
  - Runs in isolated environment
  - No `XDG_RUNTIME_DIR` by default
  - Cannot find user's PulseAudio session
  - Audio fails unless explicitly configured

**Solution:** Explicitly set `XDG_RUNTIME_DIR` and `PULSE_SERVER` in the service file to bridge the gap.

## Verification Commands

### Check Current State

```bash
# Check if service has PulseAudio access
systemctl show nrp-service | grep -E "XDG|PULSE"

# Check PulseAudio socket exists
ls -la /run/user/$(id -u)/pulse/native

# Test paplay directly from service user
sudo -u flash XDG_RUNTIME_DIR=/run/user/1000 paplay --device bluez_sink.B2_55_E1_6A_7C_4A.a2dp_sink /usr/share/sounds/alsa/Front_Center.wav
```

### Monitor TTS in Real-Time

```bash
# Terminal 1: Watch TTS logs
journalctl -u nrp-service -f | grep -i "tts\|piper\|paplay"

# Terminal 2: Load a mission via frontend
# Should see: "Piper success" instead of "Piper failed"
```

## Fallback Behavior

The TTS system has a **robust fallback chain**:

1. **Piper TTS** (Neural voice, high quality)
   - If fails: Log error and try eSpeak

2. **eSpeak** (Robotic voice, always available)
   - If fails: Try pyttsx3

3. **pyttsx3** (Python TTS library)
   - Last resort fallback

**Current Behavior:**
- Without fix: Piper fails → eSpeak "succeeds" but no audio → No sound
- **With fix: Piper succeeds → Beautiful neural voice on Bluetooth ✓**

## Complete Environment Variables (Final State)

After applying both fixes, your service should have:

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

## Summary

**Problem:** Piper TTS fails in systemd service because it can't access PulseAudio session.

**Root Cause:** Missing `XDG_RUNTIME_DIR` and `PULSE_SERVER` environment variables.

**Solution:** Run `./fix_pulseaudio_service.sh` to add PulseAudio access.

**Result:** Piper will work, and you'll hear high-quality neural voice announcements through Bluetooth! 🎉
