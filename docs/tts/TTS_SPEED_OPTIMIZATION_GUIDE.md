# TTS Speed Optimization Guide

## Current Delays Explained

When you load a mission, the TTS system goes through these steps:

```
Mission Load Event
    ↓
Event Processing (instant)
    ↓
TTS Queue (instant)
    ↓
[DELAY 1] Bluetooth Warmup Check
    ├─ If idle > 5 seconds:
    │   ├─ Play silent warmup tone: 1.8 seconds
    │   └─ Pre-speech delay: 0.3 seconds
    │   └─ TOTAL: ~2.1 seconds
    │
    └─ If recently used (< 5s ago):
        └─ Skip warmup: 0 seconds
    ↓
Piper TTS Generation (~0.5-1s for short phrase)
    ↓
Audio Playback (~2s for "Mission loaded: 3 points")
```

**Total delay on first announcement after idle:** ~4-5 seconds
**Total delay on repeat announcements:** ~2-3 seconds

## Why Warmup is Needed

Bluetooth A2DP speakers have a power-saving feature that puts the audio path to "sleep" after ~3-5 seconds of silence. When you send audio suddenly:

1. **Without warmup:** First 0.5-1 second of audio is clipped/cut off
   - Result: "ission loaded: 3 points" (missing "M")

2. **With warmup:** Silent tone wakes up the Bluetooth path
   - Result: "Mission loaded: 3 points" (perfect!)

## Optimization Options

### Option 1: Balanced Speed (Recommended)

**Script:** `./optimize_tts_speed.sh`

**Changes:**
- Warmup duration: **1.8s → 1.0s** (saves 0.8s)
- Pre-speech delay: **0.3s → 0.15s** (saves 0.15s)
- Min interval: **3.0s → 1.5s** (faster repeats)

**Result:**
- Announcement starts **~1 second faster**
- Still prevents clipping on most Bluetooth devices
- Good balance between speed and reliability

**Timing:**
- First announcement: ~3-4 seconds (was 4-5s)
- Repeat announcements: ~2-3 seconds (unchanged)

### Option 2: Aggressive Speed

**Script:** `./optimize_tts_aggressive.sh`

**Changes:**
- Warmup duration: **1.8s → 0.6s** (saves 1.2s)
- Pre-speech delay: **0.3s → 0.05s** (saves 0.25s)
- Warmup idle: **5.0s → 10.0s** (warmup less often)
- Min interval: **3.0s → 1.0s** (much faster repeats)

**Result:**
- Announcement starts **~1.5 seconds faster**
- ⚠️ May cause slight clipping on first word if Bluetooth is slow to wake
- Warmup happens less frequently (every 10s instead of 5s)

**Timing:**
- First announcement: ~2.5-3.5 seconds (was 4-5s)
- Repeat announcements: ~2-3 seconds (unchanged)

**Risk:** If you hear "ission loaded" instead of "Mission loaded", use Option 1 instead.

### Option 3: Disable Warmup (Not Recommended)

**Manual change:**
```bash
sudo sed -i 's/^Environment=NRP_TTS_BT_WARMUP=.*/Environment=NRP_TTS_BT_WARMUP=false/' /etc/systemd/system/nrp-service.service
sudo systemctl daemon-reload
sudo systemctl restart nrp-service
```

**Result:**
- Instant announcement (no warmup delay)
- ❌ First word WILL be clipped on most Bluetooth devices
- Only use if you don't care about clipping

## Comparison Table

| Configuration | Warmup Time | First Word Clipping? | Total Delay | Best For |
|--------------|-------------|---------------------|-------------|----------|
| **Current (Default)** | 1.8s + 0.3s | Never | 4-5s | Maximum reliability |
| **Balanced (Option 1)** | 1.0s + 0.15s | Rarely | 3-4s | **Recommended** |
| **Aggressive (Option 2)** | 0.6s + 0.05s | Occasionally | 2.5-3.5s | Need speed, tolerate rare clips |
| **No Warmup (Option 3)** | 0s | Always | 2-3s | Don't care about clipping |

## Recommendation

### Start with Balanced (Option 1):
```bash
./optimize_tts_speed.sh
```

This gives you **1 second faster announcements** with minimal risk.

### If you want more speed:
```bash
./optimize_tts_aggressive.sh
```

Test it. If you hear clipping, revert:
```bash
./optimize_tts_speed.sh  # Back to balanced
```

## Additional Speed Tricks

### 1. Shorten Messages

Instead of "Mission loaded: 3 points", you could modify the message to just "Mission loaded" (saves ~0.5s in speech time).

Edit [Backend/server.py:1323](Backend/server.py#L1323):
```python
# Current:
tts_msg = f"Mission loaded: {waypoints_count} points"

# Shorter:
tts_msg = "Mission loaded"

# Or even shorter:
tts_msg = "Loaded"
```

### 2. Use eSpeak Instead of Piper

Piper is higher quality but slightly slower. eSpeak is instant but robotic.

To force eSpeak (no Piper delay):
```bash
sudo sed -i 's/^Environment=NRP_TTS_ENGINE=.*/Environment=NRP_TTS_ENGINE=espeak_only/' /etc/systemd/system/nrp-service.service
sudo systemctl daemon-reload
sudo systemctl restart nrp-service
```

Then modify [Backend/tts.py:147-158](Backend/tts.py#L147-158) to skip Piper and go straight to eSpeak.

## Understanding the Delays

### Delay Breakdown (Current Config):

```
Event Trigger:           0.000s  ─┐
Event Processing:        0.001s   │ Instant
TTS Queue:               0.001s   │
                                 ─┘
Check Warmup Needed:     0.001s

Bluetooth Warmup:        1.800s  ─┐
Pre-speech Delay:        0.300s   │ ← Optimize these!
                                 ─┘
Piper Generation:        0.800s  ─┐
Audio Playback:          2.000s   │ Can't optimize
                                 ─┘
─────────────────────────────────
TOTAL:                   ~5.0s
```

### After Balanced Optimization:

```
Event → Queue:           0.002s  (instant)
Warmup + Delay:          1.150s  ← Reduced from 2.1s
Piper + Playback:        2.800s  (same)
─────────────────────────────────
TOTAL:                   ~4.0s
```

**Savings: 1.0 second (20% faster)**

### After Aggressive Optimization:

```
Event → Queue:           0.002s  (instant)
Warmup + Delay:          0.650s  ← Reduced from 2.1s
Piper + Playback:        2.800s  (same)
─────────────────────────────────
TOTAL:                   ~3.5s
```

**Savings: 1.5 seconds (30% faster)**

## Testing Your Optimization

After applying optimization:

1. **Test clipping:**
   - Wait 15 seconds (ensure Bluetooth is idle)
   - Load a mission
   - Listen carefully: Do you hear "Mission" clearly?
   - ✓ Clear = optimization successful
   - ✗ Clipped = revert to balanced mode

2. **Measure delay:**
   ```bash
   # Terminal 1: Monitor logs with timestamps
   journalctl -u nrp-service -f -o short-precise | grep TTS

   # Terminal 2: Load mission via frontend
   # Note the time between log entries
   ```

3. **Test repeat speed:**
   - Load mission 1
   - Wait 2 seconds
   - Load mission 2
   - Should hear both announcements with minimal gap

## Reverting to Original

If you want to go back to the original safe settings:

```bash
sudo sed -i 's/^Environment=NRP_TTS_BT_WARMUP_DURATION=.*/Environment=NRP_TTS_BT_WARMUP_DURATION=1.8/' /etc/systemd/system/nrp-service.service
sudo sed -i 's/^Environment=NRP_TTS_PRE_SPEECH_DELAY=.*/Environment=NRP_TTS_PRE_SPEECH_DELAY=0.3/' /etc/systemd/system/nrp-service.service
sudo sed -i 's/^Environment=NRP_TTS_BT_WARMUP_IDLE=.*/Environment=NRP_TTS_BT_WARMUP_IDLE=5.0/' /etc/systemd/system/nrp-service.service
sudo sed -i 's/^Environment=NRP_TTS_MIN_INTERVAL=.*/Environment=NRP_TTS_MIN_INTERVAL=3.0/' /etc/systemd/system/nrp-service.service
sudo systemctl daemon-reload
sudo systemctl restart nrp-service
```

## Summary

**Quick Start:**
```bash
# Apply recommended optimization (1 second faster)
./optimize_tts_speed.sh

# Test by loading a mission
# If satisfied, done! If you want even faster:

# Apply aggressive optimization (1.5 seconds faster)
./optimize_tts_aggressive.sh

# Test for clipping
# If clipped, revert to balanced:
./optimize_tts_speed.sh
```

**Expected Results:**
- **Before:** 4-5 second delay
- **After (Balanced):** 3-4 second delay ✓
- **After (Aggressive):** 2.5-3.5 second delay (may clip)

Choose the optimization that works best for your Bluetooth speaker!
