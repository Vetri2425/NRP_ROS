# Frontend Beacon Listener Implementation Prompt

## Context

This is a **React Native (Expo SDK 54, RN 0.81.5)** Android tablet app that controls agricultural rovers. The backend runs on Jetson Orin Nano devices (FastAPI + python-socketio on port 5001).

**Build setup:** Expo managed workflow with `expo-dev-client` and EAS Build. No `android/` directory in the repo (generated at build time via `npx expo prebuild`). Package: `com.dyxgcs.mobile`. App name: `DYX-GCS-Mobile`.

**Current problem:** The app hardcodes `192.168.1.242:5001` in `App.tsx` line 121 and never discovers rovers. There are discovery files (`jetsonDiscovery.ts`, `autoConnect.ts`, `RoverDiscoveryScreen.tsx`) but they are **dead code -- never imported by App.tsx**. When the rover IP changes (new router, DHCP, reboot), the tablet cannot connect. There are 3+ rovers.

**What the backend now does:** Each rover broadcasts a UDP beacon every 2 seconds on port 5002 containing `{ type, rover_id, rover_name, ip, port, version, uptime, timestamp }`. Each rover also serves `GET /api/ping` returning `{ status, rover_id, rover_name, timestamp }`.

**The solution:** Since this is Expo managed workflow, **UDP socket binding is not available** without native modules and prebuild complications. Instead, use the **HTTP-based parallel ping approach**: scan the subnet by hitting `/api/ping` on each IP in parallel batches. This is fast (full subnet in ~5 seconds), reliable, and works purely in JavaScript with `axios` (already installed).

---

## Task Overview

This is a **3-phase task**. Implement all phases.

### Phase A: Create `beaconListener.ts` (HTTP parallel ping discovery)
### Phase B: Update `RoverDiscoveryScreen.tsx` to show live beacon-based rover list + wire it into App.tsx
### Phase C: Update `App.tsx` to use beacon-first auto-connect and show discovery screen

---

## Current File Inventory (READ these before coding)

| File | Path | Status | What it does now |
|------|------|--------|-----------------|
| config.ts | `src/config.ts` | DO NOT MODIFY | `getBackendURL()`, `setBackendURL()`, `SOCKET_CONFIG`, `API_ENDPOINTS` |
| App.tsx | `App.tsx` | MODIFY | `initBackend()` hardcodes `192.168.1.242:5001`, manual IP modal, no discovery |
| backendStorage.ts | `src/utils/backendStorage.ts` | MODIFY (small) | AsyncStorage for saved URL, has stale IP migration to remove |
| jetsonDiscovery.ts | `src/utils/jetsonDiscovery.ts` | DO NOT MODIFY | `JetsonDevice` interface (reuse it), `quickScan`, `fullScan` (keep as fallback) |
| autoConnect.ts | `src/utils/autoConnect.ts` | MODIFY | Dead code, 23 hardcoded IPs -- rewrite to beacon-first |
| priorityBackends.ts | `src/utils/priorityBackends.ts` | DO NOT MODIFY | Dead code, not breaking |
| RoverDiscoveryScreen.tsx | `src/screens/RoverDiscoveryScreen.tsx` | MODIFY | Scan UI with buttons, manual entry modal -- update to live list |
| useRoverTelemetry.ts | `src/hooks/useRoverTelemetry.ts` | DO NOT MODIFY | Socket.IO via `getHttpBase()` -> `getBackendURL()` |
| RoverContext.ts | `src/context/RoverContext.ts` | DO NOT MODIFY | Uses useRoverTelemetry |
| GlobalCrashHandler.ts | `src/services/GlobalCrashHandler.ts` | DO NOT MODIFY | Crash handler |

**IMPORTANT: `RoverDiscoveryScreen.tsx` and `autoConnect.ts` are currently NOT imported anywhere.** App.tsx must be updated to actually use them.

---

## Confirmed Beacon/Ping Formats (from running backend)

### UDP Beacon (port 5002) -- for reference only, NOT used by frontend
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

### `/api/ping` HTTP response (THIS is what the frontend uses)
```json
{
  "status": "ok",
  "rover_id": "rover-001",
  "rover_name": "Alpha",
  "timestamp": 1773041349.208
}
```

Note: `/api/ping` does NOT return `ip` or `port` -- the frontend already knows these from the HTTP request it made. And it does NOT return `uptime` or `version` -- do not try to read these fields from ping.

---

## Phase A: Beacon Listener Service (HTTP-based)

### Create `src/services/beaconListener.ts`

This service discovers rovers by pinging `/api/ping` on IPs across the subnet in parallel. Same interface regardless of discovery method, so Phase B and C don't care how discovery works internally.

#### Types

```typescript
export interface DiscoveredRover {
  roverId: string;       // from ping response "rover_id"
  roverName: string;     // from ping response "rover_name"
  ip: string;            // the IP that responded
  port: number;          // 5001 (hardcoded, all rovers use this)
  lastSeen: number;      // Date.now() when last ping succeeded
  url: string;           // "http://{ip}:5001"
}

type BeaconCallback = (rovers: DiscoveredRover[]) => void;
```

#### Class: `BeaconListener`

Singleton pattern (only one instance across the app).

**Properties:**
- `private rovers: Map<string, DiscoveredRover>` -- keyed by `rover_id`
- `private scanInterval: ReturnType<typeof setInterval> | null`
- `private onChange: BeaconCallback | null`
- `private _listening: boolean`
- `private static instance: BeaconListener`

**Methods:**

1. `static getInstance(): BeaconListener`
   - Returns singleton instance

2. `start(onChange: BeaconCallback): void`
   - If already listening, call `stop()` first
   - Save `onChange` callback
   - Set `_listening = true`
   - Run initial scan immediately: `this.scanSubnet()`
   - Start interval: scan every 5 seconds via `setInterval`
   - Log: `console.log('[BeaconListener] Started subnet discovery')`

3. `stop(): void`
   - Clear interval
   - Set `_listening = false`
   - Clear `onChange`
   - Do NOT clear rovers map (preserve last-known list)
   - Safe to call multiple times

4. `getDiscoveredRovers(): DiscoveredRover[]`
   - Return array from Map, sorted alphabetically by `roverName`

5. `isListening(): boolean`
   - Return `_listening`

6. `waitForFirst(timeoutMs: number): Promise<DiscoveredRover | null>`
   - Start listening if not already (with an internal callback that resolves the promise)
   - Return a Promise that resolves with the first discovered rover, or null on timeout
   - After resolving/timing out, stop listening
   - This is used by auto-connect in Phase C

7. `private async scanSubnet(): Promise<void>`
   - Get subnet base (default `192.168.1`)
   - Build IP list: `.1` through `.254`
   - Scan in parallel batches of 25 using `Promise.allSettled()`
   - For each IP, call `this.pingRover(ip)`
   - After scan: remove any rover from Map where `Date.now() - lastSeen > 15000` (15 seconds, 3 missed scans)
   - If Map changed, call `onChange` with current rover array

8. `private async pingRover(ip: string): Promise<void>`
   - HTTP GET `http://${ip}:5001/api/ping` with 2-second timeout using `axios`
   - On success (status < 500):
     - Parse response JSON
     - Verify `response.data.status === 'ok'`
     - Upsert into `this.rovers` Map keyed by `response.data.rover_id`:
       ```typescript
       {
         roverId: response.data.rover_id,
         roverName: response.data.rover_name,
         ip: ip,
         port: 5001,
         lastSeen: Date.now(),
         url: `http://${ip}:5001`,
       }
       ```
     - Call `this.onChange` with current rover array
   - On failure: silently ignore (most IPs won't have rovers)

#### Important implementation notes:

- Use `axios` (already in package.json) for HTTP requests
- Timeout per ping: **2 seconds** (short -- most non-existent IPs fail in <500ms)
- Batch size: **25 concurrent** (fast but won't flood the network)
- Scan interval: **5 seconds** between full scans
- Stale timeout: **15 seconds** (rover removed if 3 consecutive scans miss it)
- The full 254-IP scan with 25-concurrent and 2s timeout completes in ~20 seconds worst case, but in practice most IPs fail fast so it finishes in 3-5 seconds
- DO NOT use `react-native-udp` or any native module

#### Export:

```typescript
// Export singleton instance
const beaconListener = BeaconListener.getInstance();
export default beaconListener;
export { BeaconListener, DiscoveredRover, BeaconCallback };
```

---

## Phase B: Update Discovery Screen

### Modify `src/screens/RoverDiscoveryScreen.tsx`

**Current behavior:** Quick Scan / Full Scan buttons trigger sequential HTTP probes on hardcoded IP ranges. Uses `JetsonDevice` from `jetsonDiscovery.ts`.

**New behavior:** Live rover list updates automatically from beaconListener. Auto-starts on mount.

#### Changes:

1. **Add import:**
   ```typescript
   import beaconListener, { DiscoveredRover } from '../services/beaconListener';
   ```

2. **New state:**
   ```typescript
   const [discoveredRovers, setDiscoveredRovers] = useState<DiscoveredRover[]>([]);
   const [listening, setListening] = useState(true);
   ```

3. **On mount:** Start `beaconListener` with callback that calls `setDiscoveredRovers`
4. **On unmount:** Stop `beaconListener`

5. **Replace scan progress** with "Listening for rovers..." and a pulsing `ActivityIndicator` when `listening && discoveredRovers.length === 0`

6. **Show live rover list** from `discoveredRovers` state:
   - Each card shows: rover name, rover ID, IP:port, status dot
   - Green dot (`#4CAF50`): `Date.now() - lastSeen < 8000`
   - Yellow dot (`#FF9800`): `Date.now() - lastSeen >= 8000`
   - Update dots every 2 seconds via a `setInterval` that forces re-render

7. **Replace scan buttons:**
   - Remove "Quick Scan" and "Full Scan" buttons
   - Add "Refresh" button that calls `beaconListener.stop()` then `beaconListener.start()`
   - Add "Network Scan (Legacy)" button that runs existing `quickScanForJetsonDevices` from `jetsonDiscovery.ts` as fallback -- results feed into the same device list

8. **Keep existing features unchanged:**
   - Manual URL entry modal (keep exactly as-is)
   - Skip/Offline mode (keep exactly as-is)
   - `onRoverSelected` callback (keep exactly as-is)

9. **When user taps a discovered rover:**
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
   This bridges `DiscoveredRover` -> `JetsonDevice` so downstream code works unchanged.

10. **Keep the existing `handleSelectDevice` for legacy scan results** (when user clicks a `JetsonDevice` from the fallback scan).

#### Style: Match existing dark theme (`#1a1a1a` bg, `#2a2a2a` cards, `#4CAF50` green, `#2196F3` blue, white text). Use existing `Ionicons` for icons.

---

## Phase C: Update App.tsx and autoConnect.ts

### Modify `App.tsx`

**Current flow (broken):**
1. `initBackend()` called on mount (line 109-128)
2. Calls `initializeBackendURL()` to load saved URL from AsyncStorage
3. Ignores the result, hardcodes `primaryURL = 'http://192.168.1.242:5001'`
4. Sets it as backend URL, marks configured
5. `RoverDiscoveryScreen` is never shown (not imported)

**New flow:**

1. **Add imports:**
   ```typescript
   import beaconListener from './src/services/beaconListener';
   import RoverDiscoveryScreen from './src/screens/RoverDiscoveryScreen';
   import { JetsonDevice } from './src/utils/jetsonDiscovery';
   ```

2. **Remove:** `FALLBACK_IPS` constant (line 21)

3. **Remove:** `testBackendConnection` function (lines 28-72) -- no longer needed
4. **Remove:** `probeWithAttempts` function (lines 78-94) -- no longer needed

5. **New state:** Add `showDiscovery` state:
   ```typescript
   const [showDiscovery, setShowDiscovery] = useState(false);
   ```

6. **Rewrite `initBackend()`:**
   ```typescript
   const initBackend = async () => {
     setRetrying(true);
     setConnectionStatus('Initializing...');
     setBackendUnreachable(false);

     // Step 1: Load saved URL from AsyncStorage
     await initializeBackendURL();
     const savedUrl = getBackendURL();

     // Step 2: If we have a saved URL, verify it's still reachable via /api/ping
     if (savedUrl && !savedUrl.includes('localhost')) {
       setConnectionStatus('Verifying last known rover...');
       try {
         const response = await axios.get(`${savedUrl}/api/ping`, { timeout: 3000 });
         if (response.status === 200 && response.data?.status === 'ok') {
           // Saved rover is still reachable
           setConnectionStatus(`Connected to ${response.data.rover_name}`);
           setBackendConfigured(true);
           setRetrying(false);
           return;
         }
       } catch {
         // Saved URL not reachable, continue to discovery
       }
     }

     // Step 3: Wait for beacon discovery (5 second timeout)
     setConnectionStatus('Searching for rovers...');
     const firstRover = await beaconListener.waitForFirst(5000);

     if (firstRover) {
       // Found a rover via beacon
       const url = firstRover.url;
       setBackendURL(url);
       await saveBackendURL(url, firstRover.ip, firstRover.port);
       setConnectionStatus(`Found ${firstRover.roverName}`);
       setBackendConfigured(true);
       setRetrying(false);
       return;
     }

     // Step 4: No rover found -- show discovery screen
     setConnectionStatus('No rovers found automatically');
     setShowDiscovery(true);
     setRetrying(false);
   };
   ```

7. **Add `handleRoverSelected` callback for discovery screen:**
   ```typescript
   const handleRoverSelected = (device: JetsonDevice) => {
     setBackendURL(device.url);
     setBackendConfigured(true);
     setShowDiscovery(false);
     setBackendUnreachable(false);
   };
   ```

8. **Update the render logic.** Before the main `NavigationContainer`, add:
   ```typescript
   if (showDiscovery) {
     return (
       <GestureHandlerRootView style={{ flex: 1 }}>
         <RoverDiscoveryScreen onRoverSelected={handleRoverSelected} />
       </GestureHandlerRootView>
     );
   }
   ```

9. **Keep the existing manual IP entry modal** -- it's the emergency fallback when even discovery fails. But wire it to also close the discovery screen if shown.

10. **Remove `backendUnreachable` state** and related UI if discovery screen replaces it. Or keep it as a simpler fallback -- use judgment to keep the flow clean.

### Modify `src/utils/autoConnect.ts`

**Current:** 23 hardcoded IPs tried sequentially (dead code, not imported anywhere).

**New:** Beacon-first with scan fallback. This function is now used by the discovery screen.

```typescript
import { JetsonDevice } from './jetsonDiscovery';
import beaconListener from '../services/beaconListener';

export async function attemptAutoConnect(
  onProgress?: (message: string) => void
): Promise<JetsonDevice | null> {
  // Step 1: Wait for beacon discovery (fast path, 5 seconds)
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

  // Step 2: No beacons -- return null (caller can try legacy scan)
  if (onProgress) onProgress('No rovers found');
  return null;
}
```

Remove the `PRIORITY_ORDER` array, `DEFAULT_IP`, `CONNECTION_TIMEOUT`, `testConnection` function, and all hardcoded IPs.

### Modify `src/utils/backendStorage.ts`

Small change -- remove stale IP migration (lines 13-16 and 43-55):

**Remove these constants:**
```typescript
const STALE_IPS: string[] = ['192.168.1.39'];
const CURRENT_DEFAULT_IP = '192.168.1.242';
```

**In `getSavedBackendURL()`**, remove the stale IP migration block (lines 43-55):
```typescript
// Remove this entire block:
const staleIP = STALE_IPS.find((old) => url.includes(old));
if (staleIP) {
  const migratedUrl = url.replace(staleIP, CURRENT_DEFAULT_IP);
  // ... rest of migration ...
  return migratedUrl;
}
```

Just return `url` directly after the null check.

---

## Testing

### Test beacon listener alone:
```typescript
import beaconListener from '../services/beaconListener';

beaconListener.start((rovers) => {
  console.log('Discovered rovers:', rovers.map(r => `${r.roverName} @ ${r.ip}`));
});
// Should log within 5 seconds:
// Discovered rovers: ["Alpha @ 192.168.1.39"]
```

### Test discovery screen:
1. Start 1+ rover backend(s) with `ROVER_ID` / `ROVER_NAME` env vars
2. Open app -> should auto-connect if saved URL is valid
3. If no saved URL or saved URL is dead -> shows discovery screen
4. Discovery screen shows rover(s) within 5 seconds
5. Tap rover -> connects, navigates to main app

### Test IP change scenario:
1. Connect to rover at 192.168.1.39
2. Change rover IP (restart with different DHCP)
3. Restart app -> saved URL (192.168.1.39) fails ping verification
4. Discovery kicks in -> finds rover at new IP within 5 seconds
5. Auto-connects to new IP

---

## What NOT to Do

- Do NOT use `react-native-udp` or any native module -- use HTTP/axios only
- Do NOT remove `jetsonDiscovery.ts` or `priorityBackends.ts` -- keep as fallback
- Do NOT modify `useRoverTelemetry.ts` -- it works via `getBackendURL()` which is set upstream
- Do NOT modify `config.ts` SOCKET_CONFIG or API_ENDPOINTS
- Do NOT change the `JetsonDevice` interface in `jetsonDiscovery.ts` -- bridge to it from `DiscoveredRover`
- Do NOT create new navigation screens -- update existing `RoverDiscoveryScreen.tsx`
- Do NOT change the dark theme styling (`#1a1a1a`, `#2a2a2a`, `#4CAF50` green accent)
- Do NOT add emojis in new code
- Do NOT read `version` or `uptime` from `/api/ping` response (those fields don't exist there)

---

## Summary of Files

### Changed

| File | Action | Details |
|------|--------|---------|
| `src/services/beaconListener.ts` | **NEW** | HTTP parallel ping discovery service (~120 lines) |
| `src/screens/RoverDiscoveryScreen.tsx` | **MODIFY** | Live rover list from beaconListener, keep manual entry + offline |
| `App.tsx` | **MODIFY** | Remove hardcoded IPs, add beacon auto-connect, show discovery screen, import RoverDiscoveryScreen |
| `src/utils/autoConnect.ts` | **MODIFY** | Rewrite to beacon-first, remove 23 hardcoded IPs |
| `src/utils/backendStorage.ts` | **MODIFY** | Remove `STALE_IPS`, `CURRENT_DEFAULT_IP`, and migration logic |

### NOT Changed

| File | Why |
|------|-----|
| `src/config.ts` | `getBackendURL`/`setBackendURL` work fine once correct URL is set |
| `src/hooks/useRoverTelemetry.ts` | Uses `getBackendURL()` -- no changes needed |
| `src/utils/jetsonDiscovery.ts` | Kept as legacy fallback, `JetsonDevice` interface reused |
| `src/utils/priorityBackends.ts` | Dead code, not breaking |
| `src/context/RoverContext.ts` | Uses useRoverTelemetry, no changes needed |
| `package.json` | No new dependencies needed (axios already installed) |
