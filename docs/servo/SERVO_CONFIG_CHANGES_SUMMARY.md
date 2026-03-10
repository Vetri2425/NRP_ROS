# Servo Configuration - Frontend Integration Summary

## What Changed

The servo parameters (delay time, servo number, PWM values) are now **fully configurable from the frontend** instead of being hardcoded constants.

## Changes Made

### 1. **Backend: IntegratedMissionController** (`Backend/integrated_mission_controller.py`)

#### Added Method: `update_servo_config()`
- Dynamically updates servo parameters at runtime
- Supports all servo-related parameters:
  - `servo_channel` - Servo channel number (default: 9)
  - `servo_pwm_on` - PWM for ON state (default: 600)
  - `servo_pwm_off` - PWM for OFF state (default: 1000)
  - `servo_spray_duration` - Time between ON/OFF (default: 0.5s)
  - `servo_delay_after` - Delay after OFF (default: 2.0s)
  - `servo_enabled` - Enable/disable servo (default: true)

#### Modified Method: `load_mission()`
- Now accepts servo configuration in the `config` parameter
- Automatically applies servo parameters when loading a mission
- Logs servo configuration when mission is loaded

### 2. **Backend: API Endpoints** (`Backend/server.py`)

#### New Endpoint: `POST /api/mission/servo_config`
- Update servo configuration independently
- Accepts partial updates (only parameters you want to change)
- Takes effect immediately for future waypoints

#### New Endpoint: `GET /api/mission/servo_config`
- Retrieve current servo configuration
- Returns all 6 servo parameters

#### Modified Endpoint: `POST /api/mission/load_controller`
- Now accepts servo parameters in the request body
- Can configure servo settings when loading mission
- Parameters are optional (uses defaults if not provided)

## How to Use from Frontend

### Option 1: Update Configuration Standalone
```javascript
// Update only the parameters you want to change
await fetch('http://192.168.1.10:5000/api/mission/servo_config', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    servo_channel: 10,
    servo_pwm_on: 1500,
    servo_spray_duration: 1.0
  })
});
```

### Option 2: Configure When Loading Mission
```javascript
// Load mission with servo config in one call
await fetch('http://192.168.1.10:5000/api/mission/load_controller', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    waypoints: [
      { lat: 13.071922, lng: 80.2619957, alt: 10.0 },
      { lat: 13.071932, lng: 80.2619967, alt: 10.0 }
    ],
    servo_channel: 10,
    servo_pwm_on: 1500,
    servo_pwm_off: 1100,
    servo_spray_duration: 1.0,
    servo_delay_after: 3.0
  })
});
```

### Option 3: Get Current Configuration
```javascript
const response = await fetch('http://192.168.1.10:5000/api/mission/servo_config');
const result = await response.json();
console.log('Current config:', result.data);
// Output: { servo_channel: 9, servo_pwm_on: 600, ... }
```

## Frontend UI Recommendations

### Recommended UI Controls:

1. **Servo Channel** 
   - Number input (1-16)
   - Default: 9

2. **PWM ON Value**
   - Number input (500-2500 µs)
   - Default: 600

3. **PWM OFF Value**
   - Number input (500-2500 µs)
   - Default: 1000

4. **Spray Duration**
   - Number input with 0.1s step (0.1-10s)
   - Default: 0.5s

5. **Delay After Spray**
   - Number input with 0.1s step (0-10s)
   - Default: 2.0s

6. **Enable Servo**
   - Checkbox
   - Default: checked

### Example UI Component Structure:
```
┌─────────────────────────────────┐
│   Servo Configuration           │
├─────────────────────────────────┤
│ Servo Channel:    [9]           │
│ PWM ON (µs):      [600]         │
│ PWM OFF (µs):     [1000]        │
│ Spray Duration:   [0.5] seconds │
│ Delay After:      [2.0] seconds │
│ Enable Servo:     [✓]           │
│                                 │
│ [Update Configuration]          │
└─────────────────────────────────┘
```

## Testing

Run the test script to verify the API:
```bash
python3 test_servo_config_api.py
```

This will test:
- ✅ Getting current configuration
- ✅ Updating all parameters
- ✅ Partial updates
- ✅ Loading mission with config
- ✅ Enabling/disabling servo

## Files Created/Modified

### Modified Files:
1. `Backend/integrated_mission_controller.py`
   - Added `update_servo_config()` method
   - Modified `load_mission()` to accept servo config
   - Enhanced logging to show servo parameters

2. `Backend/server.py`
   - Added `POST /api/mission/servo_config`
   - Added `GET /api/mission/servo_config`
   - Modified `POST /api/mission/load_controller`

### New Files:
1. `SERVO_CONFIG_API_GUIDE.md` - Complete API documentation with examples
2. `test_servo_config_api.py` - Test script for all endpoints

## Benefits

✅ **No more hardcoded values** - All parameters configurable from frontend
✅ **Real-time updates** - Change configuration during mission execution
✅ **Flexible control** - Update all or only specific parameters
✅ **Better testing** - Easy to test different servo configurations
✅ **User-friendly** - Operators can adjust spray timing without code changes

## Migration Notes

**For existing frontend code:**
- Old mission loading still works (uses default servo values)
- No breaking changes - all new features are additive
- Servo parameters are optional in all requests

**For new implementations:**
- Use `POST /api/mission/servo_config` for configuration panels
- Include servo parameters in `POST /api/mission/load_controller` for one-step setup
- Use `GET /api/mission/servo_config` to populate UI with current values
