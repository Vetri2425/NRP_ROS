# Frontend UDP Beacon Discovery - Implementation Prompt

## Execute as 5 sequential tasks. Complete one task fully before starting the next.

---

## Project Context (read once, applies to all tasks)

**App:** DYX-GCS-Mobile - React Native rover ground control station
**Framework:** Expo SDK 54 (`expo: ~54.0.30`), React Native 0.81.5, React 19.1.0
**Build:** `npx expo prebuild` then `cd android && ./gradlew assembleRelease`
**Platform:** Android tablet only (landscape orientation)
**Package:** `com.dyxgcs.mobile`

**What the app does:** Controls rovers (Jetson Orin Nano) via Socket.IO on port 5001. One tablet connects to one rover at a time. There are 3+ rovers.

**What the backend does now:** Each rover broadcasts a UDP beacon every 2 seconds on port 5002:
```json
{
  "type": "rover_beacon",
  "rover_id": "rover-001",
  "rover_name": "Alpha",
  "ip": "192.168.1.39",
  "port": 5001,
  "version": "1.0",
  "uptime": 24,
  "timestamp": 1773041325.123
}
```
Each rover also serves `GET /api/ping`:
```json
{"status": "ok", "rover_id": "rover-001", "rover_name": "Alpha", "timestamp": 1773041349.208}
```

**Current problem:** App hardcodes `192.168.1.242:5001` in `App.tsx` line 121. When rover IP changes (new router, DHCP, reboot), tablet can't connect. Discovery files exist but are dead code (never imported by App.tsx).

**Theme:** Dark UI - `#0A1628` status bar, `#1a1a1a` background, `#2a2a2a` cards, `#4CAF50` green accent, `#2196F3` blue, white text. Uses `Ionicons` from `@expo/vector-icons`.

### Key files to READ before any task

| File | Path | What it does |
|------|------|-------------|
| package.json | `package.json` | Dependencies - axios, socket.io-client, expo SDK 54 |
| app.json | `app.json` | Expo config - package name, orientation, plugins |
| config.ts | `src/config.ts` | `getBackendURL()`, `setBackendURL()`, `SOCKET_CONFIG` |
| App.tsx | `App.tsx` | `initBackend()` hardcodes IP, manual IP modal |
| backendStorage.ts | `src/utils/backendStorage.ts` | `saveBackendURL()`, `getSavedBackendURL()` via AsyncStorage |
| jetsonDiscovery.ts | `src/utils/jetsonDiscovery.ts` | `JetsonDevice` interface, scan functions |
| autoConnect.ts | `src/utils/autoConnect.ts` | Dead code - 23 hardcoded IPs |
| RoverDiscoveryScreen.tsx | `src/screens/RoverDiscoveryScreen.tsx` | Dead code - scan UI, manual entry modal |
| useRoverTelemetry.ts | `src/hooks/useRoverTelemetry.ts` | Socket.IO via `getHttpBase()` -> `getBackendURL()` |

### Files to NEVER modify

- `src/config.ts` -- `getBackendURL`/`setBackendURL`/`SOCKET_CONFIG` work fine
- `src/hooks/useRoverTelemetry.ts` -- uses `getBackendURL()`, no changes needed
- `src/context/RoverContext.ts` -- uses useRoverTelemetry
- `src/utils/jetsonDiscovery.ts` -- keep as legacy fallback, reuse `JetsonDevice` interface
- `src/utils/priorityBackends.ts` -- dead code, leave it

### The `JetsonDevice` interface (from `jetsonDiscovery.ts`, reuse as-is)

```typescript
export interface JetsonDevice {
  id: string;
  name: string;
  ip: string;
  port: number;
  url: string;
  responseTime: number;
}
```

All downstream code (storage, config, Socket.IO) expects this interface. Any new discovery type must bridge to it.

---

## TASK 1: Install `react-native-udp` and configure Expo

### Goal
Install `react-native-udp` package and configure it to work with Expo prebuild.

### Steps

1. **Install the package:**
   ```bash
   cd Source/DYX_GCS_V
   npm install react-native-udp
   ```

2. **Add config plugin to `app.json`:**
   `react-native-udp` needs network permissions. Add to `app.json` under `expo`:
   ```json
   {
     "expo": {
       ...existing config...,
       "plugins": [
         ["react-native-udp"]
       ],
       "android": {
         ...existing config...,
         "permissions": ["android.permission.INTERNET", "android.permission.ACCESS_WIFI_STATE"]
       }
     }
   }
   ```
   Note: If `react-native-udp` does NOT have an Expo config plugin, skip the plugins array and just add the Android permissions. The native module will be linked automatically during `npx expo prebuild`.

3. **Verify prebuild works:**
   ```bash
   npx expo prebuild --clean
   ```
   Check that `android/` is generated without errors.

4. **Test build:**
   ```bash
   cd android && ./gradlew assembleDebug
   ```

### What to verify
- `react-native-udp` appears in `package.json` dependencies
- `npx expo prebuild` completes without errors
- Android build compiles successfully
- If `react-native-udp` fails with Expo 54 / RN 0.81.5, try `react-native-udp@4.1.7` or check for a fork that supports newer RN

### Files changed
- `package.json` -- new dependency
- `app.json` -- permissions added
- `package-lock.json` -- auto-updated

---

## TASK 2: Create `src/services/beaconListener.ts`

### Goal
Create the UDP beacon listener service that passively receives rover broadcast beacons.

### File to create: `src/services/beaconListener.ts`

### Types to define

```typescript
export interface DiscoveredRover {
  roverId: string;       // "rover-001" from beacon rover_id
  roverName: string;     // "Alpha" from beacon rover_name
  ip: string;            // "192.168.1.39" from beacon ip
  port: number;          // 5001 from beacon port
  version: string;       // "1.0" from beacon version
  uptime: number;        // seconds from beacon uptime
  lastSeen: number;      // Date.now() when beacon was received
  url: string;           // "http://192.168.1.39:5001" (constructed)
}

export type BeaconCallback = (rovers: DiscoveredRover[]) => void;
```

### Class: `BeaconListener` (singleton)

**Import:**
```typescript
import dgram from 'react-native-udp';
```

**Constants:**
```typescript
const BEACON_PORT = 5002;
const STALE_TIMEOUT = 10000;   // 10 seconds - remove rover if no beacon
const CLEANUP_INTERVAL = 5000; // check for stale rovers every 5 seconds
```

**Private properties:**
```typescript
private static instance: BeaconListener;
private rovers: Map<string, DiscoveredRover> = new Map();
private socket: any = null;           // dgram socket
private cleanupTimer: ReturnType<typeof setInterval> | null = null;
private onChange: BeaconCallback | null = null;
private _listening: boolean = false;
```

**Methods:**

1. **`static getInstance(): BeaconListener`**
   - Standard singleton

2. **`start(onChange: BeaconCallback): void`**
   ```
   - If already listening, call stop() first
   - Save onChange callback
   - Set _listening = true
   - Create UDP socket: dgram.createSocket({ type: 'udp4', reuseAddr: true })
   - Bind to port 5002
   - On 'message' event: call this.handleBeacon(msg, rinfo)
   - On 'error' event: log error, set _listening = false
   - Start cleanup interval timer
   - Log: console.log('[BeaconListener] Listening on UDP port 5002')
   ```

3. **`stop(): void`**
   ```
   - Safe to call multiple times
   - If socket exists: socket.close(), set socket = null
   - Clear cleanup interval
   - Set _listening = false, onChange = null
   - Do NOT clear rovers map (preserve last-known list)
   ```

4. **`getDiscoveredRovers(): DiscoveredRover[]`**
   - Return `Array.from(this.rovers.values())` sorted by `roverName`

5. **`isListening(): boolean`**
   - Return `_listening`

6. **`waitForFirst(timeoutMs: number): Promise<DiscoveredRover | null>`**
   ```
   - Returns a Promise
   - Internally: start listening with a callback
   - When first rover appears in callback, resolve with it, then stop
   - If timeoutMs elapses, resolve with null, then stop
   - Use setTimeout for the timeout, clear it on success
   ```

7. **`private handleBeacon(msg: Buffer, rinfo: { address: string, port: number }): void`**
   ```
   - Parse msg.toString() as JSON
   - Verify parsed.type === 'rover_beacon'
   - Verify parsed.rover_id exists (string, non-empty)
   - Verify parsed.ip exists (string, non-empty)
   - Verify parsed.port exists (number)
   - Construct DiscoveredRover:
     {
       roverId: parsed.rover_id,
       roverName: parsed.rover_name || parsed.rover_id,
       ip: parsed.ip,
       port: parsed.port,
       version: parsed.version || '1.0',
       uptime: parsed.uptime || 0,
       lastSeen: Date.now(),
       url: `http://${parsed.ip}:${parsed.port}`,
     }
   - Upsert into this.rovers Map keyed by rover_id
   - Call this.onChange with current rover array
   - Wrap everything in try/catch - never crash on bad data
   ```

8. **`private cleanupStale(): void`**
   ```
   - Iterate this.rovers
   - Remove entries where Date.now() - lastSeen > STALE_TIMEOUT
   - If any removed, call this.onChange with current rover array
   ```

### Export

```typescript
const beaconListener = BeaconListener.getInstance();
export default beaconListener;
export { BeaconListener };
```

### `react-native-udp` API reference

```typescript
import dgram from 'react-native-udp';

// Create socket
const socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });

// Bind to port
socket.bind(5002, () => {
  console.log('Bound to port 5002');
});

// Receive messages
socket.on('message', (msg: Buffer, rinfo: { address: string, port: number }) => {
  const data = msg.toString();
  console.log(`Received from ${rinfo.address}:${rinfo.port}: ${data}`);
});

// Error handling
socket.on('error', (err: Error) => {
  console.error('Socket error:', err);
});

// Close
socket.close();
```

### Files changed
- `src/services/beaconListener.ts` -- NEW

---

## TASK 3: Update `src/screens/RoverDiscoveryScreen.tsx`

### Goal
Replace the IP-scanning discovery screen with a live beacon-based rover list.

### Read first: current `src/screens/RoverDiscoveryScreen.tsx` (the full file)

### What to keep unchanged
- `RoverDiscoveryScreenProps` interface and `onRoverSelected` callback
- Manual URL entry modal (the entire `<Modal>` block and `handleConnectManualUrl`)
- Skip/Offline mode (`handleSkip` function and button)
- Overall dark theme styling
- `Ionicons` usage

### What to change

**1. Add imports:**
```typescript
import beaconListener, { DiscoveredRover } from '../services/beaconListener';
```

**2. Replace state:**
```typescript
// REMOVE: scanning, devices, progress, scanType
// ADD:
const [discoveredRovers, setDiscoveredRovers] = useState<DiscoveredRover[]>([]);
const [listening, setListening] = useState(true);
const [now, setNow] = useState(Date.now()); // for status dot refresh
```

**3. On mount -- start beacon listener:**
```typescript
useEffect(() => {
  beaconListener.start((rovers) => {
    setDiscoveredRovers(rovers);
  });
  setListening(true);

  // Refresh "now" every 2 seconds for status dot colors
  const dotTimer = setInterval(() => setNow(Date.now()), 2000);

  return () => {
    beaconListener.stop();
    clearInterval(dotTimer);
  };
}, []);
```

**4. Remove:** `startQuickScan`, `startFullScan` functions

**5. Add rover selection handler:**
```typescript
const handleSelectBeaconRover = async (rover: DiscoveredRover) => {
  const device: JetsonDevice = {
    id: rover.roverId,
    name: rover.roverName,
    ip: rover.ip,
    port: rover.port,
    url: rover.url,
    responseTime: 0,
  };
  await saveBackendURL(device.url, device.ip, device.port);
  onRoverSelected(device);
};
```

**6. Replace the scanning progress UI with:**
```
When discoveredRovers.length === 0:
  - Show pulsing ActivityIndicator
  - Text: "Listening for rovers..."
  - Subtitle: "Make sure rover is powered on and on the same WiFi"
```

**7. Replace device list with beacon rover list:**
Each card shows:
- Status dot: green (#4CAF50) if `now - rover.lastSeen < 5000`, yellow (#FF9800) if >= 5000
- Rover name (rover.roverName) -- bold, white, 18px
- Rover ID (rover.roverId) -- gray, 12px
- IP:port (rover.ip:rover.port) -- green (#4CAF50), 14px
- Uptime: format `rover.uptime` as "Xh Ym" or "Xm Ys"
- Tap -> calls `handleSelectBeaconRover(rover)`

**8. Replace scan buttons with:**
- "Refresh" button (green) -- calls `beaconListener.stop()` then `beaconListener.start(callback)`
- "Network Scan" button (blue) -- runs existing `quickScanForJetsonDevices()` as fallback, shows those results in a separate section below beacon results

**9. Keep:** Manual URL button and modal, Skip button -- no changes

### Files changed
- `src/screens/RoverDiscoveryScreen.tsx` -- MODIFIED

---

## TASK 4: Update `App.tsx` -- wire discovery and remove hardcoded IPs

### Goal
Replace hardcoded IP connection with beacon auto-discovery and show RoverDiscoveryScreen when needed.

### Read first: current `App.tsx` (the full file)

### What to remove
- Line 21: `const FALLBACK_IPS = [...]` -- delete entirely
- Lines 28-72: `testBackendConnection()` function -- delete entirely
- Lines 78-94: `probeWithAttempts()` function -- delete entirely

### What to add

**1. New imports (near top of file):**
```typescript
import beaconListener from './src/services/beaconListener';
import RoverDiscoveryScreen from './src/screens/RoverDiscoveryScreen';
import { JetsonDevice } from './src/utils/jetsonDiscovery';
```

**2. New state in `AppContent`:**
```typescript
const [showDiscovery, setShowDiscovery] = useState(false);
```

**3. Rewrite `initBackend()`:**
```typescript
const initBackend = async () => {
  setRetrying(true);
  setConnectionStatus('Initializing...');
  setBackendUnreachable(false);
  setShowDiscovery(false);

  // Step 1: Load saved URL from AsyncStorage
  await initializeBackendURL();
  const savedUrl = getBackendURL();

  // Step 2: If saved URL exists, verify with /api/ping (3s timeout)
  if (savedUrl && !savedUrl.includes('localhost')) {
    setConnectionStatus('Verifying last known rover...');
    try {
      const response = await axios.get(`${savedUrl}/api/ping`, {
        timeout: 3000,
        validateStatus: () => true,
      });
      if (response.status === 200 && response.data?.status === 'ok') {
        console.log('[initBackend] Saved rover reachable:', savedUrl);
        setConnectionStatus(`Connected to ${response.data.rover_name || 'Rover'}`);
        setBackendConfigured(true);
        setRetrying(false);
        return;
      }
    } catch {
      console.log('[initBackend] Saved rover unreachable, trying beacon...');
    }
  }

  // Step 3: Wait for beacon (5 seconds)
  setConnectionStatus('Searching for rovers...');
  const firstRover = await beaconListener.waitForFirst(5000);

  if (firstRover) {
    const url = firstRover.url;
    console.log('[initBackend] Found rover via beacon:', firstRover.roverName, url);
    setBackendURL(url);
    await saveBackendURL(url, firstRover.ip, firstRover.port);
    setConnectionStatus(`Found ${firstRover.roverName}`);
    setBackendConfigured(true);
    setRetrying(false);
    return;
  }

  // Step 4: No rover found -- show discovery screen
  console.log('[initBackend] No rover found, showing discovery');
  setConnectionStatus('');
  setShowDiscovery(true);
  setRetrying(false);
};
```

**4. Add rover selected handler:**
```typescript
const handleRoverSelected = (device: JetsonDevice) => {
  console.log('[App] Rover selected:', device.name, device.url);
  setBackendURL(device.url);
  setBackendConfigured(true);
  setShowDiscovery(false);
  setBackendUnreachable(false);
};
```

**5. Update render -- add discovery screen gate:**
In the render body of `AppContent`, BEFORE the existing `backendUnreachable` check and the main `NavigationContainer`, add:

```typescript
// Show discovery screen if no rover found
if (showDiscovery) {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <StatusBar barStyle="light-content" backgroundColor="#0A1628" hidden={true} />
      <RoverDiscoveryScreen onRoverSelected={handleRoverSelected} />
    </GestureHandlerRootView>
  );
}
```

**6. Keep:** The manual IP entry UI that shows on `backendUnreachable` -- but it should now be less likely to trigger since discovery handles most cases. Keep `handleManualIPEntry`, `handleTestManualIP`, `handleCancel`, and the manual IP form JSX.

### Files changed
- `App.tsx` -- MODIFIED

---

## TASK 5: Update `autoConnect.ts` and `backendStorage.ts` -- cleanup

### Goal
Remove hardcoded IPs from autoConnect, remove stale IP migration from backendStorage.

### Part A: Rewrite `src/utils/autoConnect.ts`

**Read the current file first.**

Replace the entire file content with:

```typescript
/**
 * Auto-Connect Utility
 * Attempts beacon discovery on app launch, falls back to legacy scan.
 */

import { JetsonDevice } from './jetsonDiscovery';
import beaconListener from '../services/beaconListener';

/**
 * Attempt auto-connect using beacon discovery.
 * Returns first discovered rover within timeout, or null.
 */
export async function attemptAutoConnect(
  onProgress?: (message: string) => void
): Promise<JetsonDevice | null> {
  // Listen for rover beacons (fast path)
  if (onProgress) onProgress('Listening for rovers...');

  const firstRover = await beaconListener.waitForFirst(5000);

  if (firstRover) {
    if (onProgress) onProgress(`Found ${firstRover.roverName}`);
    return {
      id: firstRover.roverId,
      name: firstRover.roverName,
      ip: firstRover.ip,
      port: firstRover.port,
      url: firstRover.url,
      responseTime: 0,
    };
  }

  if (onProgress) onProgress('No rovers found');
  return null;
}
```

This removes: `DEFAULT_IP`, `CONNECTION_TIMEOUT`, `PRIORITY_ORDER` (23 hardcoded IPs), `testConnection()`.

### Part B: Clean up `src/utils/backendStorage.ts`

**Read the current file first.**

**Remove lines 13-16:**
```typescript
// DELETE these two constants:
const STALE_IPS: string[] = ['192.168.1.39'];
const CURRENT_DEFAULT_IP = '192.168.1.242';
```

**In `getSavedBackendURL()`, remove the stale IP migration block (lines 43-55).** The function should become:
```typescript
export async function getSavedBackendURL(): Promise<string | null> {
  try {
    const url = await AsyncStorage.getItem(BACKEND_URL_KEY);
    return url;
  } catch (error) {
    console.error('Failed to get backend URL:', error);
    return null;
  }
}
```

Everything else in the file stays unchanged.

### Files changed
- `src/utils/autoConnect.ts` -- REWRITTEN
- `src/utils/backendStorage.ts` -- MODIFIED (removed 2 constants + migration block)

---

## Complete file summary across all 5 tasks

| File | Task | Action |
|------|------|--------|
| `package.json` | 1 | Add `react-native-udp` dependency |
| `app.json` | 1 | Add Android permissions |
| `src/services/beaconListener.ts` | 2 | **NEW** - UDP beacon listener (~130 lines) |
| `src/screens/RoverDiscoveryScreen.tsx` | 3 | **MODIFY** - live rover list from beacons |
| `App.tsx` | 4 | **MODIFY** - beacon auto-connect, show discovery, remove hardcoded IPs |
| `src/utils/autoConnect.ts` | 5 | **REWRITE** - beacon-first, remove 23 IPs |
| `src/utils/backendStorage.ts` | 5 | **MODIFY** - remove stale IP migration |

### Files NEVER changed (across all tasks)

| File | Why |
|------|-----|
| `src/config.ts` | `getBackendURL`/`setBackendURL` work once correct URL is set |
| `src/hooks/useRoverTelemetry.ts` | Uses `getBackendURL()` - no changes needed |
| `src/utils/jetsonDiscovery.ts` | `JetsonDevice` interface reused, scan kept as fallback |
| `src/utils/priorityBackends.ts` | Dead code, not breaking |
| `src/context/RoverContext.ts` | Uses useRoverTelemetry |
