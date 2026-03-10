# ASGI Integration Audit

## Rating: GOOD (7/10)

The FastAPI + Socket.IO ASGI wiring is correctly structured. Minor issues around deprecated API and single-worker deployment.

---

## What's GOOD

### 1. Correct ASGI Wrapping Order (Excellent)

Socket.IO wraps FastAPI — not the other way around. This is the officially documented pattern.

```python
# Backend/server.py:116-128
sio = socketio_pkg.AsyncServer(
    async_mode='asgi',          # Correct: native ASGI mode
    cors_allowed_origins='*',
    ping_timeout=60,
    ping_interval=25,
)
sio_app = socketio_pkg.ASGIApp(sio, other_asgi_app=app)  # SIO wraps FastAPI
```

**Why this is correct:** Socket.IO intercepts `/socket.io/` requests first, everything else falls through to FastAPI. If reversed, Socket.IO transport would break.

### 2. AsyncServer Mode (Excellent)

```python
# async_mode='asgi' at line 117
```

Using `asgi` mode means Socket.IO shares the same asyncio event loop as FastAPI. No separate thread or process for WebSocket handling. This is the most efficient integration.

### 3. Event Loop Reference Capture (Good)

```python
# Backend/server.py:131-139
_main_loop: asyncio.AbstractEventLoop | None = None

def sync_emit(event, data=None, to=None, room=None, namespace=None):
    loop = _main_loop
    if loop is None or loop.is_closed():
        return
    coro = sio.emit(event, data, to=to, room=room, namespace=namespace)
    asyncio.run_coroutine_threadsafe(coro, loop)
```

**Why this works:** Background threads (ROS2, RTK, mission controller) need to emit Socket.IO events. `asyncio.run_coroutine_threadsafe()` is the correct bridge from sync threads to the async loop.

### 4. Middleware Skips Socket.IO Path (Good)

```python
# Backend/server.py:147
if request.url.path.startswith('/socket.io'):
    return await call_next(request)
```

Socket.IO transport requests bypass the logging middleware — prevents noise and overhead on high-frequency polling.

---

## What's BAD

### 1. Deprecated Startup Event (Minor)

```python
# Backend/server.py:6588-6592
@app.on_event("startup")    # DEPRECATED in FastAPI 0.103+
async def startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()
```

**Risk:** Will show deprecation warnings. Future FastAPI versions may remove this.

### 2. Single Worker, No Graceful Shutdown Hook

```python
# Backend/server.py:6609-6612
if __name__ in ('__main__', 'Backend.server'):
    import uvicorn
    uvicorn.run(sio_app, host='0.0.0.0', port=5001, log_level='info')
```

**Risk:** No `--workers`, no `--timeout-graceful-shutdown`. If uvicorn hangs during shutdown, daemon threads are killed mid-operation.

### 3. No Shutdown Event Handler

There is `_shutdown_ros_runtime()` registered via `atexit`, but no `@app.on_event("shutdown")` or lifespan shutdown. The atexit handler may not fire if `os._exit(1)` is called (line 1751).

---

## Improvements Needed

| Area | Current | Target | Priority |
|------|---------|--------|----------|
| Startup/Shutdown | `@app.on_event` | `lifespan` context manager | Medium |
| Worker config | No config | Explicit single-worker + graceful timeout | Low |
| Shutdown hook | `atexit` only | Lifespan shutdown + atexit fallback | Medium |

---

## Exact Fix

### Fix 1: Replace deprecated `on_event` with `lifespan`

**Current code (line 6588-6606):**
```python
@app.on_event("startup")
async def startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    load_system_settings()
    asyncio.create_task(maintain_mavros_connection())
    asyncio.create_task(telemetry_loop())
    asyncio.create_task(connection_health_monitor())
```

**Fixed code — replace the above with:**
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    """Startup and shutdown lifecycle for the FastAPI application."""
    global _main_loop
    _main_loop = asyncio.get_event_loop()

    # --- STARTUP ---
    load_system_settings()

    mavros_task = asyncio.create_task(maintain_mavros_connection())
    telemetry_task = asyncio.create_task(telemetry_loop())
    health_task = asyncio.create_task(connection_health_monitor())
    log_message("All background tasks started successfully", "SUCCESS")

    yield  # App runs here

    # --- SHUTDOWN (runs on SIGTERM / Ctrl+C) ---
    log_message("Lifespan shutdown initiated", "INFO")
    mavros_task.cancel()
    telemetry_task.cancel()
    health_task.cancel()

    # Wait for tasks to finish cancellation
    for task in [mavros_task, telemetry_task, health_task]:
        try:
            await asyncio.wait_for(task, timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    _shutdown_ros_runtime()
    log_message("Lifespan shutdown complete", "INFO")
```

**Also update the FastAPI app creation (line 99):**
```python
# Before:
app = FastAPI()

# After:
app = FastAPI(lifespan=lifespan)
```

**And remove the old startup decorator block (lines 6588-6606).**

### Fix 2: Add graceful shutdown timeout to uvicorn

**Current code (line 6612):**
```python
uvicorn.run(sio_app, host='0.0.0.0', port=5001, log_level='info')
```

**Fixed code:**
```python
uvicorn.run(
    sio_app,
    host='0.0.0.0',
    port=5001,
    log_level='info',
    timeout_graceful_shutdown=10,  # 10s for cleanup before force-kill
)
```

---

## Summary

The ASGI integration is architecturally sound. The Socket.IO + FastAPI wrapping is correct, the async mode is right, and the cross-thread emit bridge works. The main fix is migrating from deprecated `on_event` to `lifespan` — this also gives you a proper shutdown hook that `os._exit` currently bypasses.
