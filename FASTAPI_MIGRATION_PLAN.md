# Flask → FastAPI Migration Plan

## Context
The NRP_ROS backend (`Backend/server.py`, ~5800 lines) currently uses Flask + Flask-SocketIO + eventlet. We're migrating to **FastAPI + python-socketio AsyncServer + uvicorn (asyncio)**.

**Decisions Made:**
- **Socket.IO**: Keep python-socketio, use `AsyncServer` (no frontend changes needed)
- **Async**: Switch from eventlet to asyncio/uvicorn
- **Backend modules**: No changes needed (already decoupled via callbacks)

---

## Current Architecture (Pre-Migration)

### Server Stack
- Flask 2.2.2 + Flask-SocketIO 5.3.6 + eventlet 0.33.3
- Runs on `0.0.0.0:5001`
- Launched via: `python3 -m Backend.server`

### Key Numbers
- **56 REST endpoints** (`@app.route` / `@app.get` / `@app.post`)
- **24 SocketIO event handlers** (`@socketio.on(...)`)
- **3 background tasks** (`socketio.start_background_task(...)`)
- **~75 `socketio.emit()` calls** throughout the file
- **4 middleware handlers** (`@app.before_request` / `@app.after_request`)
- **3 HTML templates** (monitor.html, node_details.html, index.html)

### Backend Modules (No Changes Needed)
These are all decoupled via callbacks — no Flask/SocketIO imports:
- `integrated_mission_controller.py` — threading.RLock, daemon threads
- `mavros_bridge.py` — threading.Lock, roslibpy
- `telemetry_node.py` — pure ROS2 node
- `tts.py` — daemon thread + subprocess
- `led_controller.py` — threading.Lock + SPI
- `obstacle_monitor.py` — threading.Event + UART
- `gps_failsafe_monitor.py` — threading.RLock + state machine
- `manual_control_handler.py` — callback-based
- `lora_rtk_handler.py` — callback-based

---

## Migration Phases

### Phase 1 — Dependencies + Core Setup (lines 1-170)

**File: `Backend/requirements.txt`** — Replace contents with:
```
# FastAPI and ASGI Server
fastapi==0.115.0
uvicorn[standard]==0.30.0

# SocketIO (async mode for ASGI)
python-socketio==5.10.0
python-engineio==4.8.0

# Templates and static files
jinja2==3.1.2
aiofiles==23.2.1

# MAVLink Communication
pymavlink==2.4.39
googletrans==4.0.0-rc1
```

**File: `Backend/server.py`** — Lines 1-170 only:

1. **Remove these imports:**
   ```python
   import eventlet
   eventlet.monkey_patch()
   from flask import Flask, request, jsonify, Response, render_template
   from flask_socketio import SocketIO, emit
   from flask_cors import CORS
   ```

2. **Add these imports** (after `from __future__ import annotations`):
   ```python
   import asyncio
   import socketio as socketio_pkg
   from fastapi import FastAPI, Request
   from fastapi.responses import JSONResponse, HTMLResponse, Response, StreamingResponse
   from fastapi.templating import Jinja2Templates
   from fastapi.middleware.cors import CORSMiddleware
   from starlette.responses import FileResponse
   ```

3. **Replace app initialization** (lines 99-151):
   ```python
   app = FastAPI()
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["*"],
       allow_credentials=True,
       allow_methods=["*"],
       allow_headers=["*"],
   )

   templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

   sio = socketio_pkg.AsyncServer(
       async_mode='asgi',
       cors_allowed_origins='*',
       ping_timeout=60,
       ping_interval=25,
       engineio_logger=False,
       logger=False,
       always_connect=True,
       max_http_buffer_size=int(1e8),
   )

   sio_app = socketio_pkg.ASGIApp(sio, other_app=app)
   ```

4. **Add `sync_emit` helper** (critical — bridges sync→async for threaded callbacks):
   ```python
   _main_loop: asyncio.AbstractEventLoop | None = None

   def sync_emit(event, data=None, to=None, room=None, namespace=None):
       """Emit a Socket.IO event from synchronous / threaded code."""
       loop = _main_loop
       if loop is None or loop.is_closed():
           return
       coro = sio.emit(event, data, to=to, room=room, namespace=namespace)
       asyncio.run_coroutine_threadsafe(coro, loop)
   ```

5. **Global rename throughout ENTIRE file:**
   - `socketio.emit(` → `sync_emit(` (~75 occurrences)
   - `socketio.start_background_task(` → `asyncio.create_task(` (3 occurrences near line 5784)
   - Do NOT rename `@socketio.on(...)` decorators yet (Phase 4)

---

### Phase 2 — Middleware + Helpers (lines 105-985)

**Convert Flask middleware to FastAPI middleware:**

```python
# Replace @app.before_request / @app.after_request with:
@app.middleware("http")
async def log_and_track_requests(request: Request, call_next):
    # Skip Socket.IO transport noise
    if request.url.path.startswith('/socket.io'):
        return await call_next(request)

    # Log request
    if request.url.path != '/api/health':
        print(f"[INFO] {request.method} {request.url.path} from {request.client.host}")

    # Track activity
    try:
        meta = {'method': request.method, 'path': request.url.path}
        if request.method in ('POST', 'PUT', 'PATCH'):
            body = await request.body()
            # ... parse JSON keys
        event_type = 'ui_request' if request.url.path.startswith('/api/') else 'http_request'
        record_activity(f"HTTP {request.method} {request.url.path} request", level='DEBUG', event_type=event_type, meta=meta)
    except Exception:
        pass

    response = await call_next(request)

    # Log response
    if request.url.path != '/api/health':
        print(f"[INFO] Response: {response.status_code} for {request.method} {request.url.path}")

    return response
```

- CORS is handled by `CORSMiddleware` — remove all manual CORS header logic
- `app.logger.info(...)` → `print(...)` or use Python `logging`

---

### Phase 3 — REST Routes (56 endpoints)

**Conversion pattern for each route:**

```python
# Flask
@app.route('/api/arm', methods=['POST'])
def arm_vehicle():
    data = request.json
    return jsonify({'success': True})

# FastAPI
@app.post('/api/arm')
async def arm_vehicle(request: Request):
    data = await request.json()
    return {'success': True}
```

**Key changes:**
| Flask | FastAPI |
|-------|---------|
| `@app.route(..., methods=['POST'])` | `@app.post(...)` |
| `@app.route(..., methods=['GET'])` | `@app.get(...)` |
| `request.json` | `await request.json()` |
| `request.args.get('key', default)` | `request.query_params.get('key', default)` |
| `jsonify({...})` | return dict directly |
| `jsonify({...}), 400` | `JSONResponse({...}, status_code=400)` |
| `Response(text, mimetype='text/plain')` | `Response(content=text, media_type='text/plain')` |
| `render_template('x.html')` | `templates.TemplateResponse("x.html", {"request": request})` |

**Error handlers:**
```python
# Flask
@app.errorhandler(404)
def not_found(e): ...

# FastAPI
from fastapi.exceptions import HTTPException
@app.exception_handler(404)
async def not_found(request, exc):
    return JSONResponse({'error': 'Not found'}, status_code=404)
```

---

### Phase 4 — SocketIO Event Handlers (24 events)

**Conversion pattern:**

```python
# Flask-SocketIO
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    emit('connection_response', {...})

# python-socketio AsyncServer
@sio.on('connect')
async def handle_connect(sid, environ):
    await sio.emit('connection_response', {...}, to=sid)
```

**Key changes:**
| Flask-SocketIO | python-socketio AsyncServer |
|----------------|----------------------------|
| `@socketio.on('event')` | `@sio.on('event')` |
| `def handler():` | `async def handler(sid, data=None):` |
| `request.sid` | `sid` parameter |
| `emit('event', data)` | `await sio.emit('event', data, to=sid)` |
| `emit('event', data, broadcast=True)` | `await sio.emit('event', data)` |
| `socketio.on_error_default` | `@sio.on('*')` or try/except in handlers |

**All 24 handlers to convert:**
```
connect, disconnect, ping, request_rover_reconnect,
request_mission_logs, mission_upload, connect_caster, disconnect_caster,
start_lora_rtk_stream, stop_lora_rtk_stream, get_lora_rtk_status,
subscribe_mission_status, get_mission_status, send_command,
inject_mavros_telemetry, manual_control, emergency_stop, stop_manual_control,
set_gps_failsafe_mode, set_obstacle_detection, failsafe_acknowledge,
failsafe_resume_mission, failsafe_restart_mission
```

---

### Phase 5 — Background Tasks + Entry Point (lines 5780-5806)

**Background tasks:**
```python
# Flask-SocketIO (eventlet)
socketio.start_background_task(maintain_mavros_connection)
socketio.start_background_task(telemetry_loop)
socketio.start_background_task(connection_health_monitor)

# FastAPI (asyncio)
@app.on_event("startup")
async def startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    asyncio.create_task(maintain_mavros_connection())
    asyncio.create_task(telemetry_loop())
    asyncio.create_task(connection_health_monitor())
```

- Each background function becomes `async def`
- `eventlet.sleep()` / `time.sleep()` → `await asyncio.sleep()`
- Threading in backend modules continues to work — asyncio and threading coexist

**Server entry point:**
```python
# Flask
socketio.run(app, host='0.0.0.0', port=5001, debug=False)

# FastAPI
import uvicorn
uvicorn.run(sio_app, host='0.0.0.0', port=5001)
```

Note: `sio_app` (ASGI app wrapping both Socket.IO and FastAPI) is what uvicorn serves.

**`start_service.sh`** — No changes needed (launch command stays `python3 -m Backend.server`).

---

### Phase 6 — Verification + Fixes

1. `python3 -m Backend.server` starts without errors on port 5001
2. Frontend React app connects via Socket.IO (receives `rover_data` events)
3. REST API endpoints respond (`/api/mission/status`, `/api/tts/status`, etc.)
4. Background tasks run (telemetry loop, MAVROS connection)
5. Templates render (`/monitor` page)
6. TTS greeting plays on Pixhawk connection

---

## Files Modified
| File | Change |
|------|--------|
| `Backend/server.py` | Full refactor (Flask → FastAPI + AsyncServer) |
| `Backend/requirements.txt` | Swap Flask deps for FastAPI deps |

## Files NOT Modified
| File | Reason |
|------|--------|
| All Backend modules | Already decoupled via callbacks |
| `Backend/templates/*` | Jinja2 works with FastAPI's Jinja2Templates |
| `start_service.sh` | Launch command unchanged |
| `nrp-service.service` | No changes needed |
| Frontend code | Socket.IO client unchanged |

---

## Project Structure (Post-Cleanup)

```
NRP_ROS/
├── Backend/
│   ├── server.py                         # Main server (Flask → FastAPI)
│   ├── integrated_mission_controller.py
│   ├── mavros_bridge.py
│   ├── mavlink_core.py
│   ├── telemetry_node.py
│   ├── tts.py
│   ├── led_controller.py
│   ├── lora_receiver_usb.py
│   ├── lora_rtk_handler.py
│   ├── manual_control_handler.py
│   ├── gps_failsafe_monitor.py
│   ├── obstacle_monitor.py
│   ├── ultrasonic_sensor.py
│   ├── ultrasonic_watch.py
│   ├── gps_altitude_corrector.py
│   ├── requirements.txt
│   ├── README.md
│   ├── config/
│   │   └── mission_controller_config.json
│   └── templates/
│       ├── monitor.html
│       ├── node_details.html
│       └── index.html
├── docs/
│   ├── architecture/       # System flow diagrams
│   ├── endpoints/           # API reference
│   ├── tts/                 # Voice system docs
│   ├── servo/               # Servo control docs
│   ├── gps-failsafe/        # GPS failsafe docs
│   ├── rtk/                 # RTK monitoring docs
│   ├── field-test/          # Test checklists
│   └── fixes/               # Bug fix reports
├── tests/                   # 23 consolidated test files
├── utils/
│   └── network_monitor.py
├── tools/
│   ├── find_topic_by_fields.py
│   ├── install_piper_models.sh
│   └── tts_smoke_test.py
├── start_service.sh
├── nrp-service.service
├── mav.parm
├── README.md
└── QUICK_START.md
```

---

## Notes

### sync_emit Helper (Critical)
Many existing functions call `socketio.emit(...)` from synchronous/threaded context (MAVROS callbacks, mission controller callbacks, etc.). The `sync_emit()` helper bridges sync→async safely using `asyncio.run_coroutine_threadsafe()`.

### Threading + asyncio Coexistence
Backend modules (mavros_bridge, mission_controller, etc.) use `threading.Lock`/`threading.RLock` and daemon threads. These continue to work alongside asyncio — Python's threading and asyncio coexist naturally. The `sync_emit` helper is the bridge between the two worlds.

### Audio/TTS Status
- Default PulseAudio sink: `alsa_output.usb-Jieli_Technology_UACDemoV1.0_4150344C3631390E-00.analog-stereo`
- TTS engine: edge-tts with `en-US-RogerNeural` voice
- Service has PulseAudio access via `PULSE_SERVER` and `XDG_RUNTIME_DIR` env vars
- Greeting triggers on first Pixhawk MAVROS connection (not server startup)
