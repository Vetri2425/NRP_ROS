# Auto-Reconnect Crash Loop Fix

## Problem Identified
The initial auto-reconnect implementation was causing a **restart loop** due to false positive disconnection detection during service startup.

### Root Cause
1. During service startup, Pixhawk reports `connected=false` briefly before establishing connection
2. Initial code started with `_last_pixhawk_connected = True`
3. When first State message arrived with `connected=false`, it triggered disconnection detection
4. Service restarted immediately, creating an infinite loop
5. Service restarted 6 times before stabilizing

## Solution Applied

### Changes to Prevent False Positives

1. **Added Startup Grace Period** (30 seconds)
   - No reconnection triggers during first 30 seconds after startup
   - Allows Pixhawk to establish connection without false positives

2. **Increased Telemetry Timeout** (5s → 10s)
   - Reduced false positives from transient telemetry delays
   - Still fast enough for actual crash detection

3. **Fixed Initial Connection State**
   - Changed `_last_pixhawk_connected` from `True` to `False` on startup
   - Only triggers disconnection if we were **actually connected** before

4. **Added Grace Period Check in Detection Logic**
   - Both explicit disconnection and timeout detection skip startup period
   - Prevents premature restart triggers

### Code Changes in `mavros_bridge.py`

**Lines 65-70: Added startup tracking**
```python
self._last_pixhawk_connected = False  # Start as False to avoid false positives during startup
self._pixhawk_disconnect_detected = False
self._last_telemetry_time = time.time()
self._telemetry_timeout = 10.0  # seconds without telemetry before reconnection (increased to avoid false positives)
self._startup_time = time.time()
self._startup_grace_period = 30.0  # Don't trigger reconnection for first 30 seconds
```

**Lines 137-140: Added grace period check**
```python
# Don't trigger during startup grace period
time_since_startup = time.time() - self._startup_time
if time_since_startup < self._startup_grace_period:
    return False
```

**Lines 528-535: Improved disconnection detection**
```python
# Only trigger disconnection if:
# 1. We were previously connected (avoid startup false positives)
# 2. Now disconnected
# 3. Past startup grace period
time_since_startup = time.time() - self._startup_time
if self._last_pixhawk_connected and not connected and time_since_startup >= self._startup_grace_period:
    self._pixhawk_disconnect_detected = True
    print("[MAVROS_BRIDGE] Pixhawk disconnection detected - flagging for reconnection", flush=True)
```

**Lines 157-160: Reset startup timer on reconnection**
```python
self._pixhawk_disconnect_detected = False
self._last_pixhawk_connected = False  # Reset to False to avoid false positives on next restart
self._last_telemetry_time = time.time()
self._startup_time = time.time()  # Reset startup timer on reconnection
```

## Updated Configuration

- **Telemetry Timeout**: 10 seconds (increased from 5s)
- **Startup Grace Period**: 30 seconds (new)
- **Check Interval**: 2 seconds (unchanged)
- **systemd Restart Delay**: 10 seconds (unchanged)
- **Total Recovery Time**: ~40-45 seconds (includes grace period)

## Behavior After Fix

### Normal Startup
1. Service starts, Pixhawk connects
2. Grace period active for 30 seconds
3. No false positive triggers
4. Service runs normally

### Actual Pixhawk Reboot (After 30s of operation)
1. Pixhawk disconnects
2. Disconnection detected immediately
3. Service restarts automatically
4. 30-second grace period prevents immediate re-trigger
5. System recovers cleanly

### MAVROS Node Crash
1. Telemetry stops flowing
2. After 10 seconds of silence, timeout triggers
3. Service restarts automatically
4. Clean recovery with grace period

## Testing Results

**Before Fix:**
- 6 restarts in rapid succession
- Service couldn't stabilize
- Continuous restart loop

**After Fix:**
- Clean startup
- No false positive triggers
- Service runs stably
- Actual disconnections still trigger restart correctly

## Adjusted Timeouts Rationale

### Why 10-second timeout instead of 5?
- Prevents false positives from transient delays
- Still fast enough to detect real crashes
- Better balance between responsiveness and stability

### Why 30-second grace period?
- Allows MAVROS and Pixhawk to fully establish connection
- Typical startup takes 15-20 seconds
- 30s provides comfortable margin

### Trade-offs
- **Slower initial crash detection**: If Pixhawk crashes within first 30 seconds, restart delayed
- **More stable system**: No false positives, clean startups
- **Worth it**: Startup crashes are rare; false positives were causing continuous problems

## Monitoring Restart Count

```bash
# Check current restart count
systemctl show nrp-service | grep NRestarts

# Reset restart counter (after fixing crash loop)
systemctl reset-failed nrp-service

# Monitor for new restarts
watch -n 2 'systemctl show nrp-service | grep NRestarts'
```

## Files Modified
- `Backend/mavros_bridge.py` - Added startup grace period and improved detection logic
