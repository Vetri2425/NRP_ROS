# Pre-Field Test Checklist

## 🔴 CRITICAL ISSUE FOUND

### Problem: Single Waypoint Without HOME

**Issue:** The refactored code uploads a **single waypoint** without HOME, but ArduPilot **requires** at least a HOME position to accept AUTO mode.

**What happens:**
- Upload 1 waypoint (seq=0)
- ArduPilot expects HOME at seq=0
- Set AUTO mode → **WILL FAIL** "No mission loaded"

**Location:** `upload_single_waypoint()` at line 761

### ✅ Solution Required

ArduPilot needs either:

**Option A: Upload HOME + Waypoint (Recommended)**
```python
# Always upload: HOME (seq=0) + Mission waypoint (seq=1)
waypoints = [home_waypoint, mission_waypoint]
```

**Option B: Set HOME separately (Complex)**
```python
# Use MAVLink CMD_DO_SET_HOME before waypoint upload
# Then upload single mission waypoint
```

### The Issue With Current Code

Line 761: `response = self.bridge.push_waypoints([waypoint])`

This uploads **only 1 waypoint**, but:
- ArduPilot needs seq=0 (HOME) + seq=1 (mission) minimum
- Single waypoint will be rejected by AUTO mode
- Mission will fail at step 4 (Set AUTO mode)

## 🧪 Required Tests Before Field

### 1. Bench Test (Indoor - MANDATORY)

**Test the refactored code without ArduPilot:**

```bash
# After restarting service
./test_mission_flow.sh
```

**Check for:**
- ✅ Mission loads successfully
- ✅ Mission starts successfully
- ⚠️ **Waypoint upload - will likely fail AUTO mode**
- ⚠️ Check logs for "No mission" or AUTO mode rejection

### 2. Pixhawk Connection Test

**With Pixhawk connected but rover stationary:**

```bash
# Load single waypoint
curl -X POST http://localhost:5001/api/mission/load \
  -d '{"waypoints":[{"lat":13.072100,"lng":80.262000,"alt":10}]}'

# Start mission
curl -X POST http://localhost:5001/api/mission/start

# Monitor
journalctl -u nrp-service -f | grep -E "(MISSION_CONTROLLER|AUTO mode|armed)"
```

**Expected Issues:**
1. Waypoint uploads successfully
2. ARM succeeds
3. **AUTO mode likely fails** - "No mission loaded" or "Invalid mission"

### 3. Required Fix Before Field Test

You need to decide on the approach:

**OPTION 1: Keep HOME + Waypoint (Safer)**

Revert to uploading HOME + waypoint but simplify verification:

```python
def upload_single_waypoint(self, waypoint):
    # Create HOME + waypoint
    home = create_home_waypoint()
    mission = create_mission_waypoint(waypoint, seq=1)

    # Upload both
    self.bridge.push_waypoints([home, mission])

    # Set current to seq=1 (mission waypoint)
    self.bridge.set_current_waypoint(1)

    return True
```

**OPTION 2: Fix Single Waypoint Approach**

Need to ensure HOME is set in Pixhawk's memory before mission:

```python
def set_home_position(self):
    # Actually SET HOME via MAVLink command
    # CMD_DO_SET_HOME or similar
    # Then single waypoint uploads will work
```

## 📋 Test Sequence (After Fix)

### Phase 1: Service Restart Test
- [ ] Restart service
- [ ] Check mission controller initializes
- [ ] No errors in logs

### Phase 2: Mission Load Test
- [ ] Load 1 waypoint mission
- [ ] Check state changes to READY
- [ ] Waypoints stored correctly

### Phase 3: Mission Start Test
- [ ] Start mission
- [ ] HOME set (first time only)
- [ ] Waypoint uploads
- [ ] ARM succeeds
- [ ] **AUTO mode activates successfully** ← CRITICAL
- [ ] Check rover doesn't show "No mission"

### Phase 4: Waypoint Navigation Test (Stationary)
- [ ] Rover accepts AUTO mode
- [ ] Mission shows active
- [ ] Distance calculations work
- [ ] Can manually set HOLD mode

### Phase 5: Multi-Waypoint Test
- [ ] Load 2-3 waypoints
- [ ] Start mission
- [ ] HOME set once (not repeated)
- [ ] Each waypoint uploads individually
- [ ] AUTO mode works for each waypoint
- [ ] Transitions between waypoints smooth

### Phase 6: Field Test (Outdoors)
- [ ] GPS lock acquired
- [ ] RTK fix if available
- [ ] Load actual mission
- [ ] Start and verify AUTO mode
- [ ] **Rover actually moves** ← ULTIMATE TEST
- [ ] Distance monitoring works
- [ ] Waypoint reached detection
- [ ] HOLD mode at waypoint
- [ ] Next waypoint proceeds
- [ ] Mission completes

## ⚠️ Recommended Action

**Before field test, you need to:**

1. **Test current refactored code** (will likely fail at AUTO mode)
2. **Fix the HOME waypoint issue** (choose Option 1 or 2 above)
3. **Re-test with fix** (verify AUTO mode works)
4. **Then proceed to field test**

## 🎯 Quick Decision

**If you want quick field test:**
- Use **Option 1** (HOME + waypoint, simpler verification)
- This is proven to work (your old code did this)
- Just remove the complex retry verification
- Keep the ARM check

**If you want pure single waypoint:**
- Need to implement proper HOME setting command
- More testing required
- Higher risk

## Current Status

| Component | Status | Field Ready? |
|-----------|--------|--------------|
| Logic Flow | ✅ Good | Yes |
| ARM Check | ✅ Good | Yes |
| HOME Setting | ⚠️ Needs Fix | **NO** |
| Waypoint Upload | ⚠️ Issue Found | **NO** |
| AUTO Mode | ⚠️ Will Fail | **NO** |
| Distance Check | ✅ Good | Yes |
| State Machine | ✅ Good | Yes |

**Overall Field Readiness: 60%** - Needs HOME waypoint fix

---

**Recommendation:** Test on bench first, identify AUTO mode failure, then implement fix before field test.
