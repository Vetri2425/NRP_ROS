# Backend Beacon Implementation Prompt

## Context

This is a **rover control system** running on Jetson Orin Nano devices. There are 3+ rovers, each running a FastAPI + python-socketio backend on port 5001. A single Android tablet (React Native / Expo) connects to control them.

**The problem:** The tablet cannot find rovers when IPs change (new router, DHCP renewal, reboot). Currently the tablet guesses from hardcoded IP lists which is slow and unreliable.

**The solution:** Each rover broadcasts a UDP beacon every 2 seconds. The tablet listens passively and builds a live rover list. No scanning, no IP guessing.

---

## Task

Create a single file `Backend/beacon.py` and integrate it into `Backend/server.py`.

---

## Architecture

```
Rover (Jetson)                          Tablet
   |                                      |
   | UDP broadcast 255.255.255.255:5002   |
   |------------------------------------->|
   | every 2 seconds                      |
   |                                      |
   | JSON payload:                        |  Listens on UDP :5002
   | {                                    |  Parses beacon JSON
   |   "rover_id": "rover-001",          |  Builds rover list
   |   "rover_name": "Alpha",            |  Shows in UI
   |   "ip": "192.168.1.102",            |
   |   "port": 5001,                     |
   |   "version": "1.0",                 |
   |   "uptime": 3600                    |
   | }                                   |
```

---

## Exact Requirements for `Backend/beacon.py`

### 1. Class: `RoverBeacon`

```python
class RoverBeacon:
    def __init__(self, rover_id: str, rover_name: str, port: int = 5001, beacon_port: int = 5002, interval: float = 2.0):
```

**Constructor parameters:**
- `rover_id` -- unique identifier per Jetson (e.g., "rover-001"). Read from env var `ROVER_ID` with fallback to hostname.
- `rover_name` -- human-readable name (e.g., "Alpha"). Read from env var `ROVER_NAME` with fallback to `rover_id`.
- `port` -- the FastAPI server port (always 5001)
- `beacon_port` -- UDP broadcast port (always 5002)
- `interval` -- seconds between beacons (default 2.0)

### 2. Method: `start()`

- Creates a **daemon thread** that runs the broadcast loop
- Thread must be daemon so it dies when main process exits
- Sets `self._running = True`
- Logs: `"Beacon started: {rover_name} ({rover_id}) broadcasting on UDP {beacon_port}"`

### 3. Method: `stop()`

- Sets `self._running = False`
- Closes the UDP socket if open
- Logs: `"Beacon stopped"`

### 4. Broadcast loop (private method `_broadcast_loop`)

- Create a UDP socket: `socket.socket(socket.AF_INET, socket.SOCK_DGRAM)`
- Set socket option: `socket.SO_BROADCAST` to True
- In a while loop (while `self._running`):
  - Build JSON payload (see below)
  - Send to `('255.255.255.255', self.beacon_port)`
  - Sleep for `self.interval` seconds
  - Wrap each send in try/except -- log errors but never crash the loop
- On loop exit, close socket

### 5. Beacon JSON payload

```json
{
  "type": "rover_beacon",
  "rover_id": "rover-001",
  "rover_name": "Alpha",
  "ip": "<current_local_ip>",
  "port": 5001,
  "version": "1.0",
  "uptime": 3600,
  "timestamp": 1709920000.123
}
```

- `type` -- always `"rover_beacon"` (so receiver can filter)
- `ip` -- current local IP address (must update if IP changes)
- `uptime` -- integer seconds since beacon started
- `timestamp` -- `time.time()` float

### 6. Getting local IP -- CRITICAL

**DO NOT** use the `connect to 8.8.8.8` trick. The rover may be on an isolated network with no internet.

Use this approach:
```python
import socket

def _get_local_ip(self) -> str:
    """Get local IP without requiring internet access."""
    try:
        # Create a UDP socket and connect to a broadcast address
        # This doesn't send any data, just determines the outgoing interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(('10.254.254.254', 1))  # Doesn't need to be reachable
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass

    # Fallback: parse hostname resolution
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if not ip.startswith('127.'):
            return ip
    except Exception:
        pass

    # Last resort: scan interfaces
    try:
        import subprocess
        result = subprocess.run(
            ['hostname', '-I'], capture_output=True, text=True, timeout=2
        )
        ips = result.stdout.strip().split()
        for ip in ips:
            if not ip.startswith('127.') and ':' not in ip:
                return ip
    except Exception:
        pass

    return '127.0.0.1'
```

**Re-fetch IP on every beacon send**, not just at startup. This way if DHCP changes the IP, the next beacon automatically has the correct IP.

### 7. Logging

Use Python `logging` module:
```python
import logging
logger = logging.getLogger("beacon")
```

Log levels:
- `info` -- start, stop, IP change detected
- `debug` -- each beacon sent (only when debug logging enabled)
- `error` -- socket errors

---

## Integration with `Backend/server.py`

### What to modify

The file is 6612 lines. Only modify two small sections:

**1. Add import near the top (around line 40, after existing imports):**
```python
from beacon import RoverBeacon
```

Use the same try/except pattern as other imports in server.py:
```python
try:
    from .beacon import RoverBeacon
except Exception:
    from beacon import RoverBeacon
```

**2. In the `startup()` function (line 6588-6606), add beacon start:**

```python
@app.on_event("startup")
async def startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()

    load_system_settings()

    asyncio.create_task(maintain_mavros_connection())
    log_message("MAVROS connection maintenance task started")

    asyncio.create_task(telemetry_loop())
    log_message("Telemetry task started")

    asyncio.create_task(connection_health_monitor())
    log_message("Connection health monitor started")

    # Start rover discovery beacon
    global _beacon
    _beacon = RoverBeacon(
        rover_id=os.environ.get('ROVER_ID', socket.gethostname()),
        rover_name=os.environ.get('ROVER_NAME', 'Rover'),
        port=5001,
    )
    _beacon.start()
    log_message("Rover discovery beacon started", "SUCCESS")

    log_message("All background tasks started successfully", "SUCCESS")
```

Add a global `_beacon = None` near the top of the file (around line 131 where `_main_loop` is defined).

**3. Add an `/api/ping` endpoint** so the tablet can verify connectivity after discovering via beacon:

```python
@app.get("/api/ping")
async def api_ping():
    return JSONResponse({
        "status": "ok",
        "rover_id": os.environ.get('ROVER_ID', socket.gethostname()),
        "rover_name": os.environ.get('ROVER_NAME', 'Rover'),
        "timestamp": time.time()
    })
```

---

## File Structure After Implementation

```
Backend/
  beacon.py          <-- NEW (single file, ~100 lines)
  server.py          <-- MODIFIED (3 small additions: import, startup beacon, /api/ping)
  mavros_bridge.py   <-- unchanged
  ... (all other files unchanged)
```

---

## What NOT to Do

- Do NOT use `zeroconf` library or mDNS -- we're using simple UDP broadcast
- Do NOT use asyncio for the beacon -- use a plain daemon thread (the server's event loop is for FastAPI/Socket.IO)
- Do NOT create config files -- use environment variables (`ROVER_ID`, `ROVER_NAME`) with hostname fallback
- Do NOT modify any file other than `beacon.py` (new) and `server.py` (3 small additions)
- Do NOT add type: ignore comments unless necessary
- Do NOT add docstrings beyond what's specified
- Do NOT use emojis in log messages (the existing server.py uses them but beacon.py should not)

---

## Testing

After implementation, test with:

```bash
# Terminal 1: Start server
cd /home/flash/NRP_ROS/Backend
ROVER_ID=rover-001 ROVER_NAME=Alpha python -m Backend.server

# Terminal 2: Listen for beacons (on any machine on same network)
python3 -c "
import socket, json
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 5002))
while True:
    data, addr = s.recvfrom(1024)
    print(f'From {addr}: {json.loads(data)}')
"
```

Expected output every 2 seconds:
```
From ('192.168.1.102', <ephemeral>): {'type': 'rover_beacon', 'rover_id': 'rover-001', 'rover_name': 'Alpha', 'ip': '192.168.1.102', 'port': 5001, 'version': '1.0', 'uptime': 2, 'timestamp': 1709920002.123}
```

Also test `/api/ping`:
```bash
curl http://192.168.1.102:5001/api/ping
# {"status":"ok","rover_id":"rover-001","rover_name":"Rover","timestamp":1709920005.456}
```
