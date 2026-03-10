# Servo Configuration API - Frontend Integration Guide

## Overview
The servo parameters (channel, PWM values, timing) are now fully configurable from the frontend. You can set them when loading a mission or update them dynamically at any time.

## API Endpoints

### 1. Update Servo Config (Standalone)
**Endpoint:** `POST /api/mission/servo_config`

Update servo configuration without reloading the mission.

**Request Body:**
```json
{
  "servo_channel": 9,           // Servo channel (default: 9)
  "servo_pwm_on": 600,          // PWM value for ON/START state (default: 600)
  "servo_pwm_off": 1000,        // PWM value for OFF/STOP state (default: 1000)
  "servo_delay_before": 0.0,    // Delay BEFORE turning servo ON in seconds (default: 0.0)
  "servo_spray_duration": 0.5,  // Time between ON and OFF in seconds (default: 0.5)
  "servo_delay_after": 2.0,     // Delay AFTER turning servo OFF in seconds (default: 2.0)
  "servo_enabled": true         // Enable/disable servo control (default: true)
}
```

**Response:**
```json
{
  "success": true,
  "message": "Servo configuration updated",
  "data": {
    "updated_params": [
      "servo_channel=9",
      "servo_pwm_on=600",
      "servo_pwm_off=1000"
    ]
  }
}
```

**Example (JavaScript/TypeScript):**
```typescript
async function updateServoConfig(config: ServoConfig) {
  const response = await fetch('http://192.168.1.10:5000/api/mission/servo_config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  });
  
  const result = await response.json();
  console.log('Servo config updated:', result.data.updated_params);
}

// Usage
updateServoConfig({
  servo_channel: 10,
  servo_pwm_on: 1500,
  servo_pwm_off: 1100,
  servo_delay_before: 1.0,     // Wait 1s before starting
  servo_spray_duration: 1.0,   // Spray for 1s
  servo_delay_after: 3.0       // Wait 3s after stopping
});
```

### 2. Get Current Servo Config
**Endpoint:** `GET /api/mission/servo_config`

Retrieve the current servo configuration.

**Response:**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "servo_channel": 9,
    "servo_pwm_on": 600,
    "servo_pwm_off": 1000,
    "servo_delay_before": 0.0,
    "servo_spray_duration": 0.5,
    "servo_delay_after": 2.0,
    "servo_enabled": true
  }
}
```

**Example:**
```typescript
async function getServoConfig() {
  const response = await fetch('http://192.168.1.10:5000/api/mission/servo_config');
  const result = await response.json();
  return result.data;
}

// Usage
const config = await getServoConfig();
console.log('Current servo channel:', config.servo_channel);
```

### 3. Load Mission with Servo Config
**Endpoint:** `POST /api/mission/load_controller`

Load waypoints AND configure servo parameters in a single request.

**Request Body:**
```json
{
  "waypoints": [
    { "lat": 13.071922, "lng": 80.2619957, "alt": 10.0 },
    { "lat": 13.071932, "lng": 80.2619967, "alt": 10.0 }
  ],
  "servo_channel": 9,
  "servo_pwm_on": 600,
  "servo_pwm_off": 1000,
  "servo_delay_before": 0.0,
  "servo_spray_duration": 0.5,
  "servo_delay_after": 2.0,
  "servo_enabled": true
}
```

**Example:**
```typescript
async function loadMissionWithServoConfig(waypoints: Waypoint[], servoConfig: ServoConfig) {
  const response = await fetch('http://192.168.1.10:5000/api/mission/load_controller', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      waypoints,
      ...servoConfig  // Spread servo config into the request
    })
  });
  
  return await response.json();
}

// Usage
const waypoints = [
  { lat: 13.071922, lng: 80.2619957, alt: 10.0 },
  { lat: 13.071932, lng: 80.2619967, alt: 10.0 }
];

const servoConfig = {
  servo_channel: 10,
  servo_pwm_on: 1500,
  servo_pwm_off: 1100,
  servo_delay_before: 1.0,
  servo_spray_duration: 1.0,
  servo_delay_after: 3.0,
  servo_enabled: true
};

await loadMissionWithServoConfig(waypoints, servoConfig);
```

## Frontend UI Integration

### React Component Example

```typescript
import React, { useState, useEffect } from 'react';

interface ServoConfig {
  servo_channel: number;
  servo_pwm_on: number;
  servo_pwm_off: number;
  servo_delay_before: number;
  servo_spray_duration: number;
  servo_delay_after: number;
  servo_enabled: boolean;
}

const ServoConfigPanel: React.FC = () => {
  const [config, setConfig] = useState<ServoConfig>({
    servo_channel: 9,
    servo_pwm_on: 600,
    servo_pwm_off: 1000,
    servo_delay_before: 0.0,
    servo_spray_duration: 0.5,
    servo_delay_after: 2.0,
    servo_enabled: true
  });

  // Load current config on mount
  useEffect(() => {
    fetch('http://192.168.1.10:5000/api/mission/servo_config')
      .then(res => res.json())
      .then(result => setConfig(result.data))
      .catch(err => console.error('Failed to load servo config:', err));
  }, []);

  const handleUpdate = async () => {
    try {
      const response = await fetch('http://192.168.1.10:5000/api/mission/servo_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      
      const result = await response.json();
      alert(`Servo config updated: ${result.data.updated_params.join(', ')}`);
    } catch (err) {
      alert('Failed to update servo config');
    }
  };

  return (
    <div className="servo-config-panel">
      <h3>Servo Configuration</h3>
      
      <label>
        Servo Channel:
        <input 
          type="number" 
          value={config.servo_channel}
          onChange={e => setConfig({...config, servo_channel: parseInt(e.target.value)})}
        />
      </label>

      <label>
        PWM ON (µs):
        <input 
          type="number" 
          value={config.servo_pwm_on}
          onChange={e => setConfig({...config, servo_pwm_on: parseInt(e.target.value)})}
        />
      </label>

      <label>
        PWM OFF (µs):
        <input 
          type="number" 
          value={config.servo_pwm_off}
          onChange={e => setConfig({...config, servo_pwm_off: parseInt(e.target.value)})}
        />
      </label>

      <label>
        Delay Before Spray (s):
        <input 
          type="number" 
          step="0.1"
          value={config.servo_delay_before}
          onChange={e => setConfig({...config, servo_delay_before: parseFloat(e.target.value)})}
        />
      </label>

      <label>
        Spray Duration (s):
        <input 
          type="number" 
          step="0.1"
          value={config.servo_spray_duration}
          onChange={e => setConfig({...config, servo_spray_duration: parseFloat(e.target.value)})}
        />
      </label>

      <label>
        Delay After Spray (s):
        <input 
          type="number" 
          step="0.1"
          value={config.servo_delay_after}
          onChange={e => setConfig({...config, servo_delay_after: parseFloat(e.target.value)})}
        />
      </label>

      <label>
        Enable Servo:
        <input 
          type="checkbox" 
          checked={config.servo_enabled}
          onChange={e => setConfig({...config, servo_enabled: e.target.checked})}
        />
      </label>

      <button onClick={handleUpdate}>Update Configuration</button>
    </div>
  );
};

export default ServoConfigPanel;
```

## Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `servo_channel` | int | 9 | Servo channel number (1-16) |
| `servo_pwm_on` | int | 600 | PWM value in microseconds for ON/START state |
| `servo_pwm_off` | int | 1000 | PWM value in microseconds for OFF/STOP state |
| `servo_delay_before` | float | 0.0 | Delay in seconds **BEFORE** turning servo ON |
| `servo_spray_duration` | float | 0.5 | Time in seconds **BETWEEN** ON and OFF commands (spray active time) |
| `servo_delay_after` | float | 2.0 | Delay in seconds **AFTER** turning servo OFF before continuing to next waypoint |
| `servo_enabled` | bool | true | Enable/disable servo control at waypoints |

## Usage Scenarios

### Scenario 1: Pre-configure before mission load
```typescript
// 1. Set servo configuration
await updateServoConfig({
  servo_channel: 10,
  servo_pwm_on: 1500,
  servo_pwm_off: 1100
});

// 2. Load mission (will use the configured values)
await loadMission(waypoints);
```

### Scenario 2: Configure while loading mission
```typescript
// Load mission with servo config in one call
await loadMissionWithServoConfig(waypoints, {
  servo_channel: 10,
  servo_pwm_on: 1500,
  servo_pwm_off: 1100,
  servo_delay_before: 1.0,   // Wait before starting
  servo_spray_duration: 1.0, // Spray time
  servo_delay_after: 3.0     // Wait after stopping
});
```

### Scenario 3: Update during mission execution
```typescript
// Mission is running, but you want to adjust timing
await updateServoConfig({
  servo_delay_before: 0.5,    // Decrease pre-spray delay
  servo_spray_duration: 2.0,  // Increase spray time
  servo_delay_after: 1.0      // Decrease post-spray delay
});
```

### Scenario 4: Disable servo temporarily
```typescript
// Disable servo without stopping mission
await updateServoConfig({
  servo_enabled: false
});

// Later, re-enable it
await updateServoConfig({
  servo_enabled: true
});
```

## Complete Mission Flow

Understanding the exact sequence helps you configure timing properly:

```
1. Push WP          → Upload waypoints to controller
2. Arm              → Arm the vehicle  
3. Set AUTO         → Switch to AUTO mode
4. Go to WP         → Vehicle navigates to waypoint
5. Hold             → Vehicle stops at waypoint (hold_duration)
   ↓
6. Before Delay     → Wait servo_delay_before seconds ⏱
   ↓
7. Servo ON         → Set PWM to servo_pwm_on (START) 🟢
   ↓
8. Spray Duration   → Wait servo_spray_duration seconds ⏱
   ↓
9. Servo OFF        → Set PWM to servo_pwm_off (STOP) 🔴
   ↓
10. After Delay     → Wait servo_delay_after seconds ⏱
    ↓
11. Next Action:
    • AUTO mode  → Automatically proceed to next waypoint
    • MANUAL mode → Wait for manual command
```

### Timing Example

If you configure:
```json
{
  "servo_delay_before": 1.0,
  "servo_spray_duration": 2.0,
  "servo_delay_after": 3.0
}
```

At each waypoint:
- **Total time at waypoint** = hold_duration + 1.0s (before) + 2.0s (spray) + 3.0s (after)
- **Spray active time** = 2.0 seconds only
- If `hold_duration = 5s`, total waypoint time = **11 seconds**

### UI Component Structure

```
┌─────────────────────────────────────┐
│   Servo Configuration Panel         │
├─────────────────────────────────────┤
│ Servo Channel:        [9      ]     │
│ PWM START (µs):       [600    ]     │
│ PWM STOP (µs):        [1000   ]     │
│                                     │
│ ⏱ Timing Configuration              │
│ Before Delay (s):     [0.0    ]     │
│ Spray Duration (s):   [0.5    ]     │
│ After Delay (s):      [2.0    ]     │
│                                     │
│ Enable Servo:         [✓]           │
│                                     │
│ [Update Configuration]              │
└─────────────────────────────────────┘
```

## Testing with curl Commands

### 1. Get Current Servo Configuration
```bash
curl -X GET http://localhost:5000/api/mission/servo_config | python3 -m json.tool
```

**Expected Response:**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "servo_channel": 9,
    "servo_pwm_on": 600,
    "servo_pwm_off": 1000,
    "servo_delay_before": 0.0,
    "servo_spray_duration": 0.5,
    "servo_delay_after": 2.0,
    "servo_enabled": true
  }
}
```

### 2. Update Servo Configuration
```bash
curl -X POST http://localhost:5000/api/mission/servo_config \
  -H "Content-Type: application/json" \
  -d '{
    "servo_channel": 10,
    "servo_pwm_on": 1500,
    "servo_pwm_off": 1100,
    "servo_delay_before": 1.0,
    "servo_spray_duration": 2.0,
    "servo_delay_after": 3.0
  }' | python3 -m json.tool
```

### 3. Update Only Specific Parameters
```bash
# Update only timing parameters
curl -X POST http://localhost:5000/api/mission/servo_config \
  -H "Content-Type: application/json" \
  -d '{
    "servo_delay_before": 0.5,
    "servo_spray_duration": 1.5,
    "servo_delay_after": 2.5
  }' | python3 -m json.tool
```

### 4. Load Mission with Servo Config
```bash
curl -X POST http://localhost:5000/api/mission/load_controller \
  -H "Content-Type: application/json" \
  -d '{
    "waypoints": [
      {"lat": 13.071922, "lng": 80.2619957, "alt": 10.0},
      {"lat": 13.071932, "lng": 80.2619967, "alt": 10.0}
    ],
    "servo_channel": 10,
    "servo_pwm_on": 1500,
    "servo_pwm_off": 1100,
    "servo_delay_before": 1.0,
    "servo_spray_duration": 2.0,
    "servo_delay_after": 3.0,
    "servo_enabled": true
  }' | python3 -m json.tool
```

### 5. Disable/Enable Servo
```bash
# Disable servo
curl -X POST http://localhost:5000/api/mission/servo_config \
  -H "Content-Type: application/json" \
  -d '{"servo_enabled": false}' | python3 -m json.tool

# Enable servo
curl -X POST http://localhost:5000/api/mission/servo_config \
  -H "Content-Type: application/json" \
  -d '{"servo_enabled": true}' | python3 -m json.tool
```

### Quick Test Script
Save this as `test_servo_config.sh`:
```bash
#!/bin/bash

echo "=== Current Servo Configuration ==="
curl -s http://localhost:5000/api/mission/servo_config | python3 -m json.tool

echo -e "\n=== Updating Configuration ==="
curl -s -X POST http://localhost:5000/api/mission/servo_config \
  -H "Content-Type: application/json" \
  -d '{
    "servo_channel": 10,
    "servo_pwm_on": 1500,
    "servo_pwm_off": 1100,
    "servo_delay_before": 1.0,
    "servo_spray_duration": 2.0,
    "servo_delay_after": 3.0
  }' | python3 -m json.tool

echo -e "\n=== Verify Updated Configuration ==="
curl -s http://localhost:5000/api/mission/servo_config | python3 -m json.tool
```

Make executable and run:
```bash
chmod +x test_servo_config.sh
./test_servo_config.sh
```

## Verification Checklist

### ✅ Backend Verification
1. **Check mission controller initialization:**
   ```bash
   # Check if mission controller has default values
   grep -A 10 "Servo configuration" Backend/integrated_mission_controller.py
   ```

2. **Check API endpoints are registered:**
   ```bash
   # Search for servo_config endpoints in server.py
   grep -n "servo_config" Backend/server.py
   ```

3. **Verify all 7 parameters are configurable:**
   - servo_channel ✓
   - servo_pwm_on ✓
   - servo_pwm_off ✓
   - servo_delay_before ✓
   - servo_spray_duration ✓
   - servo_delay_after ✓
   - servo_enabled ✓

### ✅ Frontend Integration Checklist
1. **Create servo config state:**
   ```typescript
   const [servoConfig, setServoConfig] = useState({
     servo_channel: 9,
     servo_pwm_on: 600,
     servo_pwm_off: 1000,
     servo_delay_before: 0.0,
     servo_spray_duration: 0.5,
     servo_delay_after: 2.0,
     servo_enabled: true
   });
   ```

2. **Fetch config on component mount:**
   ```typescript
   useEffect(() => {
     fetch('/api/mission/servo_config')
       .then(res => res.json())
       .then(data => setServoConfig(data.data));
   }, []);
   ```

3. **Update config on user input:**
   ```typescript
   const updateConfig = async () => {
     await fetch('/api/mission/servo_config', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify(servoConfig)
     });
   };
   ```

4. **Include in mission load:**
   ```typescript
   const loadMission = async (waypoints) => {
     await fetch('/api/mission/load_controller', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({
         waypoints,
         ...servoConfig  // Spread all servo parameters
       })
     });
   };
   ```

## Troubleshooting

### Server Not Running
```bash
# Check if server is running
curl http://localhost:5000/api/health

# If not running, start it
cd Backend
python3 server.py
```

### Wrong Port
```bash
# Check which port the server is using
ps aux | grep server.py

# Common ports: 5000 (default), 5001, 8000
curl http://localhost:5001/api/mission/servo_config
```

### Mission Controller Not Initialized
```bash
# Check server logs for initialization
journalctl -u nrp-service.service -f | grep "Mission controller initialized"
```

### Configuration Not Persisting
- Configuration is stored in memory, not saved to disk
- Restarting the server will reset to default values
- To persist, you need to send config after each server restart

## Notes

- All parameters are optional when updating configuration
- Changes take effect immediately for future waypoints
- Current waypoint execution is not affected by config changes
- Configuration persists for the entire mission controller session (until server restart)
- Default values are loaded from `integrated_mission_controller.py` initialization
- **Before delay** is useful for stabilization before spraying
- **After delay** is useful for allowing spray to settle before moving
- Use `GET` to verify configuration was applied correctly
- Use `POST` with partial JSON to update only specific parameters
