# Frontend HTTP Ping Discovery - Fallback Prompt

## When to use this prompt

Use this ONLY if `react-native-udp` failed to install, build, or work at runtime in TASK 1/2 of the UDP beacon prompt. This replaces TASK 2 only -- Tasks 1 (skip), 3, 4, 5 remain the same.

---

## What changed

Instead of listening for UDP beacons on port 5002, the `beaconListener.ts` service scans the subnet by hitting `GET /api/ping` on every IP in parallel batches using `axios` (already installed, zero new dependencies).

The **interface stays identical** (`DiscoveredRover`, `BeaconCallback`, `start()`, `stop()`, `waitForFirst()`, `getDiscoveredRovers()`, `isListening()`). Tasks 3, 4, 5 do not need any changes.

---

## Replacement for TASK 2: Create `src/services/beaconListener.ts` (HTTP version)

### Differences from UDP version

| Aspect | UDP version | HTTP version |
|--------|-------------|-------------|
| Dependency | `react-native-udp` | `axios` (already installed) |
| How it works | Passive listener on port 5002 | Active scan of .1-.254 via `/api/ping` |
| Speed | Rover appears in <2 seconds | Full scan in 3-5 seconds |
| Network load | Near zero | 254 HTTP requests per scan cycle |
| Scan interval | N/A (passive) | Every 10 seconds |
| `DiscoveredRover` fields | Has `version`, `uptime` from beacon | No `version`/`uptime` (ping doesn't return them) |

### Types (slightly different -- no version/uptime)

```typescript
export interface DiscoveredRover {
  roverId: string;       // from ping response "rover_id"
  roverName: string;     // from ping response "rover_name"
  ip: string;            // the IP that responded
  port: number;          // 5001
  version: string;       // always "unknown" (ping doesn't return this)
  uptime: number;        // always 0 (ping doesn't return this)
  lastSeen: number;      // Date.now() when last ping succeeded
  url: string;           // "http://{ip}:5001"
}

export type BeaconCallback = (rovers: DiscoveredRover[]) => void;
```

### Class: `BeaconListener` (same interface, different internals)

**Import:**
```typescript
import axios from 'axios';
```

**Constants:**
```typescript
const ROVER_PORT = 5001;
const PING_TIMEOUT = 2000;     // 2 seconds per IP
const BATCH_SIZE = 25;         // 25 concurrent pings
const SCAN_INTERVAL = 10000;   // scan every 10 seconds
const STALE_TIMEOUT = 25000;   // remove if missed 2 consecutive scans
const SUBNET = '192.168.1';    // default subnet
```

**Private properties:**
```typescript
private static instance: BeaconListener;
private rovers: Map<string, DiscoveredRover> = new Map();
private scanTimer: ReturnType<typeof setInterval> | null = null;
private onChange: BeaconCallback | null = null;
private _listening: boolean = false;
private _scanning: boolean = false;  // prevent overlapping scans
```

**Methods -- same signatures as UDP version:**

1. **`static getInstance(): BeaconListener`**

2. **`start(onChange: BeaconCallback): void`**
   ```
   - If already listening, call stop() first
   - Save onChange
   - Set _listening = true
   - Run scanSubnet() immediately
   - Start interval: scanSubnet() every SCAN_INTERVAL
   - Log: console.log('[BeaconListener] Started HTTP subnet discovery')
   ```

3. **`stop(): void`**
   - Clear interval, set _listening = false, onChange = null
   - Do NOT clear rovers map
   - Safe to call multiple times

4. **`getDiscoveredRovers(): DiscoveredRover[]`**
   - Same as UDP version

5. **`isListening(): boolean`**
   - Same as UDP version

6. **`waitForFirst(timeoutMs: number): Promise<DiscoveredRover | null>`**
   - Same logic as UDP version
   - Start listening, resolve on first rover found or timeout

7. **`private async scanSubnet(): Promise<void>`**
   ```
   - If _scanning is true, return (prevent overlap)
   - Set _scanning = true
   - Build IP list: 192.168.1.1 through 192.168.1.254
   - Process in batches of BATCH_SIZE:
       const batch = ips.slice(i, i + BATCH_SIZE);
       await Promise.allSettled(batch.map(ip => this.pingRover(ip)));
   - After all batches: remove stale rovers (lastSeen > STALE_TIMEOUT)
   - If rovers changed, call onChange
   - Set _scanning = false
   ```

8. **`private async pingRover(ip: string): Promise<void>`**
   ```
   - try:
       const response = await axios.get(`http://${ip}:${ROVER_PORT}/api/ping`, {
         timeout: PING_TIMEOUT,
         validateStatus: (status) => status < 500,
       });
       if (response.data?.status === 'ok' && response.data?.rover_id) {
         Upsert into this.rovers:
         {
           roverId: response.data.rover_id,
           roverName: response.data.rover_name || response.data.rover_id,
           ip: ip,
           port: ROVER_PORT,
           version: 'unknown',
           uptime: 0,
           lastSeen: Date.now(),
           url: `http://${ip}:${ROVER_PORT}`,
         }
         Call this.onChange with current array
       }
   - catch: silently ignore (expected for 250+ IPs that aren't rovers)
   ```

### Export (identical to UDP version)

```typescript
const beaconListener = BeaconListener.getInstance();
export default beaconListener;
export { BeaconListener };
```

### Files changed
- `src/services/beaconListener.ts` -- NEW (HTTP version, ~120 lines)
- No changes to `package.json` or `app.json` (no new dependencies)

### After creating this file
Continue with TASK 3, 4, 5 from the UDP prompt -- they work identically because the `beaconListener` interface is the same.
