# Socket.IO Transport Audit

## Rating: GOOD (7/10)

The Socket.IO configuration is well-tuned for a rover control system over WiFi. Good reconnection support, proper ping/pong, and session tracking. Minor issues with fire-and-forget emits, debug noise, and missing rooms/namespaces.

---

## What's GOOD

### 1. Generous Ping/Pong Timeouts (Excellent)

```python
# Backend/server.py:116-125
sio = socketio_pkg.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    ping_timeout=60,        # Client has 60s to respond to ping
    ping_interval=25,       # Server pings every 25s
    always_connect=True,
    max_http_buffer_size=int(1e8),
)
```

**Why this is excellent for a rover:**
- WiFi in outdoor/remote areas is unreliable
- `ping_timeout=60` means a client survives up to 60 seconds of network interruption without being disconnected
- `ping_interval=25` keeps the connection alive through NAT/firewalls on the router
- Default Socket.IO values (20s timeout, 25s interval) would cause frequent disconnects in the field

### 2. always_connect=True (Excellent)

```python
always_connect=True,   # line 123
```

Client connections are always accepted, even if the connect handler raises an error. This prevents transient server errors from blocking operators from connecting.

### 3. Connection Health Monitor (Good)

```python
# Backend/server.py:2240-2284
async def connection_health_monitor():
    while True:
        # Track stale clients (no ping for 30s)
        for client_id, session in list(_client_sessions.items()):
            time_since_ping = current_time - session.get('last_ping', current_time)
            if time_since_ping > 30:
                stale_clients.append(client_id)
                sync_emit('connection_warning', {
                    'message': 'Connection may be unstable',
                    'time_since_ping': time_since_ping
                }, room=client_id)

        # Cleanup sessions inactive for 5+ minutes
        for client_id in list(_client_sessions.keys()):
            if current_time - session.get('last_ping', current_time) > 300:
                _client_sessions.pop(client_id, None)

        # Emit overall health status
        sync_emit('server_health', {
            'active_clients': active_clients,
            'vehicle_connected': is_vehicle_connected,
            'ros_available': ROS_AVAILABLE,
        })
        await asyncio.sleep(10)
```

**Why this is good:** Proactively warns unstable clients and cleans up stale sessions. The health status broadcast gives the frontend a "server heartbeat" to confirm the WebSocket is alive.

### 4. Status History Cache for Reconnection (Good)

```python
# Backend/server.py:783
mission_status_history: deque = deque(maxlen=10)

# On client subscribe (line 3317-3329):
@sio.on('subscribe_mission_status')
async def handle_subscribe_mission_status(sid):
    if mission_status_history:
        await sio.emit('mission_status_history', {
            'success': True,
            'history': list(mission_status_history)
        }, to=sid)
```

**Why this is good:** When a client reconnects after a WiFi drop, it immediately gets the last 10 mission status updates instead of waiting for the next one. This prevents "stale UI" after reconnection.

### 5. Ping/Pong with Latency Tracking (Good)

```python
# Backend/server.py:3254-3290
@sio.on('ping')
async def handle_ping(sid, data=None):
    response_data = {
        'timestamp': current_time,
        'session_id': client_id,
        'ping_count': session['ping_count'],
        'connection_quality': 'good' if ping_interval < 2.0 else 'degraded' if ping_interval < 5.0 else 'poor'
    }
    if data and isinstance(data, dict) and 'client_timestamp' in data:
        response_data['client_timestamp'] = data['client_timestamp']  # RTT calc
    await sio.emit('pong', response_data, to=sid)
```

Enables the frontend to display connection quality and round-trip time.

### 6. Ack Callback Support on Commands (Good)

```python
# Backend/server.py:3378
@sio.on('send_command')
async def handle_command(sid, data, ack_callback=None):
    ...
    if ack_callback:
        ack_callback(response_payload)    # Socket.IO acknowledgment
    else:
        await sio.emit('command_response', payload, to=sid)
```

Socket.IO acknowledgments guarantee the client knows the server received and processed the command. Fallback to emit for clients that don't use acks.

### 7. Full State Sent on Connect (Good)

```python
# Backend/server.py:3195-3204
if is_vehicle_connected:
    await sio.emit('connection_status', {'status': 'CONNECTED_TO_ROVER'}, to=sid)
    rover_data = get_rover_data()
    if rover_data:
        await sio.emit('rover_data', rover_data, to=sid)
else:
    await sio.emit('connection_status', {'status': 'WAITING_FOR_ROVER'}, to=sid)
```

New clients immediately know the vehicle state — no need to wait for the next telemetry cycle.

---

## What's BAD

### 1. MODERATE: sync_emit is Fire-and-Forget

```python
# Backend/server.py:133-139
def sync_emit(event, data=None, to=None, room=None, namespace=None):
    loop = _main_loop
    if loop is None or loop.is_closed():
        return                               # Silent drop
    coro = sio.emit(event, data, to=to, room=room, namespace=namespace)
    asyncio.run_coroutine_threadsafe(coro, loop)   # No error handling on future
```

**Risk:** If the emit fails (disconnected client, serialization error), the error is silently lost. The `Future` returned by `run_coroutine_threadsafe` is never checked.

### 2. MODERATE: Debug Prints at 20Hz Telemetry Rate

```python
# Backend/server.py:1607
print(f"[EMIT] Sending rover_data ({reason}): position={pos}", flush=True)

# Backend/server.py:1711
print(f"[DEBUG] get_rover_data() sending rtk_fix_type=...", flush=True)
```

At 20Hz telemetry rate, these print 40+ lines per second to stdout. On the Jetson:
- Fills up systemd journal quickly
- `flush=True` forces a syscall on every print — I/O bottleneck
- Can slow down the event loop if stdout is piped to a file

### 3. LOW: No Socket.IO Rooms/Namespaces

All events are broadcast to all connected clients:

```python
sync_emit('rover_data', data)           # Goes to ALL clients
sync_emit('server_activity', entry)      # Goes to ALL clients
sync_emit('rtk_log', {'message': msg})   # Goes to ALL clients
```

With 3 clients (1 operator + 2 admin), the operator receives admin-only events (server_activity, RTK debug) and admins receive operator events (manual_control_error) needlessly.

### 4. LOW: Disconnect During Manual Control is Abrupt

```python
# Backend/server.py:3243-3245
@sio.on('disconnect')
async def handle_disconnect(sid):
    if manual_control_handler and manual_control_handler.is_active:
        manual_control_handler.stop_session(reason="client_disconnect")
```

This is actually handled well — manual control stops on disconnect. But there's no **reconnection grace period**. If WiFi drops for 2 seconds and the client reconnects, manual control is already stopped and must be restarted manually.

---

## Exact Fixes

### Fix 1: Add Error Logging to sync_emit

```python
# Before (line 133-139):
def sync_emit(event, data=None, to=None, room=None, namespace=None):
    loop = _main_loop
    if loop is None or loop.is_closed():
        return
    coro = sio.emit(event, data, to=to, room=room, namespace=namespace)
    asyncio.run_coroutine_threadsafe(coro, loop)

# After:
def sync_emit(event, data=None, to=None, room=None, namespace=None):
    """Emit a Socket.IO event from synchronous / threaded code."""
    loop = _main_loop
    if loop is None or loop.is_closed():
        return
    coro = sio.emit(event, data, to=to, room=room, namespace=namespace)
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    def _on_emit_done(fut):
        try:
            fut.result()  # Raises if the emit failed
        except Exception as exc:
            # Log but don't crash — emit failures are non-fatal
            print(f"[WARN] sync_emit({event}) failed: {exc}", flush=True)

    future.add_done_callback(_on_emit_done)
```

**What this gives you:** Emit errors are logged instead of silently swallowed. Helps debug "client not receiving events" issues.

### Fix 2: Remove or Throttle Debug Prints

```python
# Before (line 1604-1609):
if data.get('position'):
    pos = data['position']
    print(f"[EMIT] Sending rover_data ({reason}): position={pos}", flush=True)
else:
    print(f"[EMIT] Sending rover_data ({reason}): NO POSITION DATA", flush=True)

# After — only print once per 10 seconds:
_last_emit_debug_time: float = 0.0

def emit_rover_data_now(reason: str | None = None) -> None:
    global last_emit_monotonic, _last_emit_debug_time
    data = get_rover_data()

    # Throttled debug logging (once per 10 seconds instead of 20Hz)
    now = time.monotonic()
    if now - _last_emit_debug_time >= 10.0:
        if data.get('position'):
            print(f"[EMIT] rover_data ({reason}): pos={data['position']}", flush=True)
        else:
            print(f"[EMIT] rover_data ({reason}): NO POSITION", flush=True)
        _last_emit_debug_time = now

    try:
        sync_emit('rover_data', data)
    finally:
        last_emit_monotonic = time.monotonic()
```

**Same for line 1711:**
```python
# Remove or wrap in a similar throttle:
# Before:
print(f"[DEBUG] get_rover_data() sending rtk_fix_type=...", flush=True)

# After: Remove this line entirely, or guard with:
if os.getenv('NRP_DEBUG_TELEMETRY'):
    print(f"[DEBUG] get_rover_data() rtk_fix_type={current_state.rtk_fix_type}", flush=True)
```

### Fix 3: Use Socket.IO Rooms for Role-Based Events (Optional)

```python
# In handle_connect, after authentication:
@sio.on('connect')
async def handle_connect(sid, environ):
    ...
    user = verify_socketio_token(token)
    role = user.get('role', 'operator')

    # Join role-based room
    sio.enter_room(sid, f'role_{role}')
    # Everyone joins the 'all' room for telemetry
    sio.enter_room(sid, 'telemetry')

# Then emit selectively:
# Telemetry to everyone:
sync_emit('rover_data', data, room='telemetry')

# Admin-only events:
sync_emit('server_activity', entry, room='role_admin')

# RTK debug to admins only:
sync_emit('rtk_debug', payload, room='role_admin')
```

This reduces unnecessary traffic to operator tablets and keeps the operator UI clean.

### Fix 4: Add Manual Control Reconnection Grace Period (Optional)

```python
# In handle_disconnect:
@sio.on('disconnect')
async def handle_disconnect(sid):
    client_id = sid
    log_message(f'Client disconnected: {client_id}', 'INFO')

    # Grace period for manual control — don't stop immediately
    if manual_control_handler and manual_control_handler.is_active:
        log_message("Client disconnected during manual control — 5s grace period", "WARNING")

        async def _grace_period_check():
            await asyncio.sleep(5.0)
            # Check if any client reconnected and resumed manual control
            if manual_control_handler and manual_control_handler.is_active:
                # Check if the same or new client took over
                if not manual_control_handler.has_active_client():
                    log_message("Grace period expired — stopping manual control", "WARNING")
                    manual_control_handler.stop_session(reason="client_disconnect_timeout")

        asyncio.create_task(_grace_period_check())
    else:
        pass  # No manual control active, nothing to do

    _client_sessions.pop(client_id, None)
```

---

## Transport Configuration Reference

| Setting | Current Value | Recommended | Why |
|---------|-------------|-------------|-----|
| `ping_timeout` | 60s | 60s (keep) | Good for outdoor WiFi |
| `ping_interval` | 25s | 25s (keep) | Good NAT keepalive |
| `always_connect` | True | True (keep) | Never reject operators |
| `max_http_buffer_size` | 100MB | 5MB | Prevent memory DoS |
| `engineio_logger` | False | False (keep) | No debug noise |
| `logger` | False | False (keep) | No debug noise |

---

## Summary

The Socket.IO transport layer is well-configured for a rover control system. The ping/pong timeouts handle WiFi instability, status history supports reconnection, and ack callbacks ensure command delivery. The main improvements are: error logging on sync_emit (debugging), removing 20Hz debug prints (performance), and optionally adding rooms for role-based event routing (cleanliness).
