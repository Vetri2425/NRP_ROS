# FastAPI Migration — Kilo Code Prompts

## Status
- [x] Phase 1 — Dependencies + Core Setup
- [x] Phase 2 — Middleware + Error Handlers
- [x] Phase 3 — REST Routes
- [x] Phase 4 — SocketIO Event Handlers
- [x] Phase 5 — Background Tasks + Entry Point
- [x] Phase 6 — Verification

---

## Phase 3 Prompt — REST Routes

```
## Task: Flask → FastAPI Migration — Phase 3: Convert ALL REST Routes

File: `Backend/server.py`
Reference: `docs/FASTAPI_MIGRATION_PLAN.md`

Phases 1-2 are done (imports, app init, middleware, error handlers converted).
Now convert ALL ~56 REST route decorators and their handler functions.

### Conversion Rules (apply to EVERY route):

1. **Decorators:**
   - `@app.route('/path', methods=['GET'])` → `@app.get('/path')`
   - `@app.route('/path', methods=['POST'])` → `@app.post('/path')`
   - `@app.route('/path', methods=['GET', 'POST'])` → split into separate `@app.get` and `@app.post` handlers, OR use `@app.api_route('/path', methods=['GET', 'POST'])`
   - `@app.get(...)` and `@app.post(...)` that already exist — keep as-is (already FastAPI syntax)

2. **Function signatures:**
   - Every handler becomes `async def`
   - Any handler that reads request body needs `request: Request` parameter
   - URL path parameters: `@app.get("/node/<node_name>")` → `@app.get("/node/{node_name}")` with `node_name: str` as function parameter

3. **Request data access:**
   - `request.json` → `await request.json()`
   - `request.get_json(silent=True)` → wrap in try/except: `try: data = await request.json()` `except: data = None`
   - `request.get_json(force=True)` → `await request.json()`
   - `request.args.get('key', 'default')` → `request.query_params.get('key', 'default')`
   - `request.args.to_dict()` → `dict(request.query_params)`
   - `request.data` → `await request.body()`
   - `request.remote_addr` → `request.client.host`
   - `request.method` → `request.method`
   - `request.path` → `str(request.url.path)`
   - `request.content_type` → `request.headers.get('content-type')`

4. **Response returns:**
   - `return jsonify({...})` → `return {...}` (FastAPI auto-serializes dicts)
   - `return jsonify({...}), 400` → `return JSONResponse({...}, status_code=400)`
   - `return jsonify({...}), 500` → `return JSONResponse({...}, status_code=500)`
   - `return jsonify({...}), 200` → `return {...}` (200 is default)
   - `Response('text', mimetype='text/plain')` → `FastAPIResponse(content='text', media_type='text/plain')`
   - `Response('text', mimetype='text/csv')` → `FastAPIResponse(content='text', media_type='text/csv')` with appropriate headers

5. **Templates:**
   - `return render_template('monitor.html')` → `return templates.TemplateResponse("monitor.html", {"request": request})`
   - `return render_template('node_details.html', node_name=node_name)` → `return templates.TemplateResponse("node_details.html", {"request": request, "node_name": node_name})`

6. **Import note:**
   - `jsonify` is no longer imported. Remove any remaining references.
   - `request` from Flask is no longer imported. Use the `request: Request` parameter from FastAPI.
   - `Response` from Flask is replaced by `FastAPIResponse` (already imported as `Response as FastAPIResponse`).
   - `render_template` is no longer imported. Use `templates.TemplateResponse()`.

### IMPORTANT:
- Convert ALL routes — there are approximately 56 of them
- Do NOT skip any route
- Do NOT touch `@sio.on(...)` or `@socketio.on(...)` handlers — that's Phase 4
- Do NOT touch background tasks — that's Phase 5
- Do NOT touch the server entry point at the bottom — that's Phase 5
- Keep all business logic inside handlers unchanged — only change the Flask→FastAPI wrappers
- The `request` object inside route handlers must come from the function parameter, NOT from a global Flask import
```

---

## Phase 4 Prompt — SocketIO Event Handlers

```
## Task: Flask → FastAPI Migration — Phase 4: Convert ALL SocketIO Event Handlers

File: `Backend/server.py`
Reference: `docs/FASTAPI_MIGRATION_PLAN.md`

Phases 1-3 are done. Now convert all ~24 `@socketio.on(...)` handlers to `@sio.on(...)` async handlers.

### Conversion Rules:

1. **Decorator:** `@socketio.on('event_name')` → `@sio.on('event_name')`

2. **Function signature:**
   - `def handler():` → `async def handler(sid):`
   - `def handler(data):` → `async def handler(sid, data):`
   - The `sid` parameter is ALWAYS the first parameter (Socket.IO session ID)

3. **Getting session ID:**
   - `request.sid` → use the `sid` parameter directly

4. **Emitting events:**
   - `emit('event', data)` → `await sio.emit('event', data, to=sid)`
   - `emit('event', data, broadcast=True)` → `await sio.emit('event', data)`
   - `emit('event', data, room=room)` → `await sio.emit('event', data, room=room)`
   - `sync_emit(...)` calls inside these handlers → `await sio.emit(...)` (since we're already in async context)
   - BUT: `sync_emit(...)` calls from NON-handler code (callbacks, threads) stay as `sync_emit(...)`

5. **Special handlers:**
   - `@socketio.on('connect')` → `@sio.on('connect')` with signature `async def connect(sid, environ):`
   - `@socketio.on('disconnect')` → `@sio.on('disconnect')` with signature `async def disconnect(sid):`
   - `@socketio.on_error_default` → remove if still present (errors handled by try/except in handlers)
   - `@sio.on('*')` catch-all → if added in Phase 2, keep it

6. **Session management:**
   - Any `session` dict usage from Flask-SocketIO → use `await sio.save_session(sid, data)` and `await sio.get_session(sid)`
   - Or manage sessions in a global dict keyed by `sid`

7. **sleep calls inside handlers:**
   - `time.sleep(x)` → `await asyncio.sleep(x)` (only inside async handlers)
   - `eventlet.sleep(x)` → `await asyncio.sleep(x)`

### All 24 handlers to convert:
```
connect, disconnect, ping, request_rover_reconnect,
request_mission_logs, mission_upload, connect_caster, disconnect_caster,
start_lora_rtk_stream, stop_lora_rtk_stream, get_lora_rtk_status,
subscribe_mission_status, get_mission_status, send_command,
inject_mavros_telemetry, manual_control, emergency_stop, stop_manual_control,
set_gps_failsafe_mode, set_obstacle_detection, failsafe_acknowledge,
failsafe_resume_mission, failsafe_restart_mission
```

### IMPORTANT:
- Convert ALL handlers — don't skip any
- `sync_emit` calls OUTSIDE of these handlers (in callbacks, threads, background tasks) must stay as `sync_emit`
- Only change `sync_emit` → `await sio.emit` INSIDE the `@sio.on` async handlers themselves
- Do NOT touch background tasks or server entry point — that's Phase 5
- Keep all business logic unchanged — only change the SocketIO wrapper layer
```

---

## Phase 5 Prompt — Background Tasks + Entry Point

```
## Task: Flask → FastAPI Migration — Phase 5: Background Tasks + Server Entry Point

File: `Backend/server.py`
Reference: `docs/FASTAPI_MIGRATION_PLAN.md`

Phases 1-4 are done. Now convert the 3 background tasks to async and update the server entry point.

### Step 1: Convert background task functions to async

Find these 3 functions and convert them:

1. `def maintain_mavros_connection():` → `async def maintain_mavros_connection():`
2. `def telemetry_loop():` → `async def telemetry_loop():`
3. `def connection_health_monitor():` → `async def connection_health_monitor():`

Inside each function:
- `time.sleep(x)` → `await asyncio.sleep(x)`
- `eventlet.sleep(x)` → `await asyncio.sleep(x)` (if any remain)
- Keep all other logic (threading, callbacks, etc.) unchanged
- These functions contain `while True:` loops — they run forever as async tasks

### Step 2: Add FastAPI startup event

Find the block near the end of the file where `asyncio.create_task(...)` calls are made (around line 5800-5810). Replace the entire startup/run block with:

```python
@app.on_event("startup")
async def startup():
    """Initialize background tasks and set the main event loop reference."""
    global _main_loop
    _main_loop = asyncio.get_event_loop()

    asyncio.create_task(maintain_mavros_connection())
    log_message("MAVROS connection maintenance task started")

    asyncio.create_task(telemetry_loop())
    log_message("Telemetry task started")

    asyncio.create_task(connection_health_monitor())
    log_message("Connection health monitor started")

    log_message("All background tasks started successfully", "SUCCESS")
```

### Step 3: Update server entry point

Replace the `socketio.run(app, ...)` call at the very end of the file with:

```python
if __name__ in ('__main__', 'Backend.server'):
    import uvicorn
    log_message("Starting FastAPI server on http://0.0.0.0:5001", "SUCCESS")
    uvicorn.run(sio_app, host='0.0.0.0', port=5001, log_level='info')
```

Key points:
- `sio_app` (NOT `app`) is passed to uvicorn — it wraps both Socket.IO and FastAPI
- `_main_loop` is set in the startup event so `sync_emit` works from threads

### Step 4: Clean up any remaining Flask/eventlet references

Search the entire file for any remaining:
- `from flask` → remove
- `eventlet` → remove
- `jsonify` → should not exist (replaced by dict returns or JSONResponse)
- `render_template` → should not exist (replaced by templates.TemplateResponse)
- `request.sid` → should not exist (replaced by sid parameter)
- `emit(` (bare, from flask_socketio) → should not exist (replaced by await sio.emit)

### IMPORTANT:
- After this phase, the server SHOULD start successfully
- Test with: `python3 -m Backend.server`
- The server should listen on port 5001
- Check for any import errors or syntax errors in the console output
```

---

## Phase 6 Prompt — Verification

```
## Task: Flask → FastAPI Migration — Phase 6: Verification & Fixes

File: `Backend/server.py`

The migration is complete. Now verify everything works.

### Step 1: Start the server
```bash
python3 -m Backend.server
```

If there are errors, fix them. Common issues:
- Missing `await` on `request.json()` calls
- `request` used without being a function parameter
- `jsonify` still referenced somewhere
- `emit` (bare) still used instead of `await sio.emit`
- `time.sleep` instead of `await asyncio.sleep` in async functions

### Step 2: Test REST API endpoints
```bash
curl -s http://127.0.0.1:5001/ | python3 -m json.tool
curl -s http://127.0.0.1:5001/api/tts/status | python3 -m json.tool
curl -s http://127.0.0.1:5001/api/mission/status | python3 -m json.tool
curl -s http://127.0.0.1:5001/api/rtk/status | python3 -m json.tool
curl -s http://127.0.0.1:5001/api/activity?limit=3 | python3 -m json.tool
```

### Step 3: Test SocketIO connection
```bash
python3 -c "
import socketio
sio = socketio.Client()

@sio.on('connect')
def on_connect():
    print('Connected to server!')

@sio.on('rover_data')
def on_rover_data(data):
    print(f'Got rover_data: {list(data.keys()) if isinstance(data, dict) else type(data)}')
    sio.disconnect()

sio.connect('http://127.0.0.1:5001')
sio.wait()
"
```

### Step 4: Fix any issues found in steps 1-3

Report what works and what doesn't.
```
