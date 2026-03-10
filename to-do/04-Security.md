# Security Audit

## Rating: VERY POOR (2/10)

No authentication, wide-open CORS, test endpoints in production, no rate limiting. Anyone on the same WiFi network can fully control the rover — arm, disarm, upload missions, inject fake telemetry.

**Context:** Firebase for user management (online/office), Jetson-local JWT for rover control (offline/field). Hybrid approach — works with or without internet.

---

## Authentication Architecture: Firebase + Jetson Hybrid

```
=============================================================
  ONLINE MODE (Office / Home — has internet)
=============================================================

  Admin Tablet                      Firebase Auth
  +-----------+                    +------------------+
  | 1. Login  |------------------->| Verify email/pwd |
  | 2. Manage |                    | User database    |
  |    users  |                    | Role management  |
  +-----------+                    +--------+---------+
                                            |
                                   Returns Firebase ID token
                                            |
                                            v
                                   +------------------+
                                   | Frontend caches: |
                                   | - User list      |
                                   | - Roles          |
                                   | - Permissions    |
                                   | to localStorage  |
                                   +------------------+

  Admin creates users:
    - operator@nrp.local  (role: operator)
    - admin@nrp.local     (role: admin)
    - field1@nrp.local    (role: operator)

  Frontend syncs authorized user list to device storage
  before going to the field.

=============================================================
  OFFLINE MODE (Field — no internet)
=============================================================

  Operator Tablet                   Jetson (rover-nrp.local)
  +-----------+                    +------------------------+
  | 1. Open   |--- mDNS discover ->| rover-nrp.local:5001  |
  |    app    |                    |                        |
  | 2. Login  |--- POST /api/auth ->| Validate against     |
  |    page   |    /login          | local auth.json        |
  |           |<-- JWT token ------| (synced from Firebase) |
  | 3. Control|--- Bearer token -->| Verify JWT locally     |
  |    rover  |--- Socket.IO+token>| No Firebase call!      |
  +-----------+                    +------------------------+

  Jetson validates everything locally.
  Zero internet required for rover operation.

=============================================================
  SYNC FLOW (When internet available)
=============================================================

  Frontend App (online)             Firebase Firestore
  +-----------+                    +------------------+
  | Detect    |--- Fetch users --->| /authorized_users|
  | internet  |<-- User list ------| collection       |
  | available |                    +------------------+
  |           |
  |           |--- Push to Jetson ->  POST /api/auth/sync
  |           |    (user list)        Jetson saves to auth.json
  +-----------+

  This happens automatically when internet is detected.
  Jetson always has a recent copy of the user list.
```

---

## What's GOOD (Current Codebase)

### 1. Input Validation on Waypoints (Good)

```python
# Backend/server.py:2432-2438
for wp in waypoints:
    lat_val = wp.get('lat', 0)
    lng_val = wp.get('lng', 0)
    if abs(lat_val) > 90:
        raise ValueError(f"Invalid latitude {lat_val}")
    if abs(lng_val) > 180:
        raise ValueError(f"Invalid longitude {lng_val}")
```

Prevents obviously invalid coordinates from reaching the Pixhawk.

### 2. NTRIP Credentials Required (Good)

```python
# Backend/server.py:2777-2778
if not user or not pwd:
    raise ValueError("Missing username or password")
```

Prevents unauthenticated NTRIP streams.

### 3. Singleton Lock Prevents Double-Start (Good)

```python
# Uses fcntl file lock to prevent two server instances
```

Prevents resource conflicts if accidentally started twice.

---

## What's BAD

### 1. CRITICAL: No Authentication At All

```python
# Backend/server.py:99
app = FastAPI()    # No auth middleware, no API key, nothing

# ANY client on the network can:
# - POST /api/arm              -> ARM the rover
# - POST /api/set_mode         -> Change to any mode
# - POST /api/mission/upload   -> Upload arbitrary waypoints
# - POST /api/mission/start    -> Start mission execution
# - Socket.IO 'emergency_stop' -> Stop the rover
# - Socket.IO 'manual_control' -> Drive the rover manually
```

**Impact:** A malicious device on the same WiFi can take full control of a physical vehicle.

### 2. CRITICAL: CORS Wide Open with Credentials

```python
# Backend/server.py:100-106
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # ANY website can make requests
    allow_credentials=True,        # Including cookies/auth headers
    allow_methods=["*"],
    allow_headers=["*"],
)

# Backend/server.py:118
sio = socketio_pkg.AsyncServer(
    cors_allowed_origins='*',      # ANY website can open WebSocket
)
```

**Impact:** If a tablet has a browser open to a malicious website, that website's JavaScript can make API calls to the rover backend. `allow_origins=["*"]` + `allow_credentials=True` is specifically warned against in the CORS specification.

### 3. CRITICAL: Test Endpoint Left in Production

```python
# Backend/server.py:3490-3506
@sio.on('inject_mavros_telemetry')
async def handle_inject_mavros_telemetry(sid, data):
    """Inject a MAVROS-like telemetry payload into the server for testing."""
    _handle_mavros_telemetry(data)
    await sio.emit('inject_ack', {'status': 'ok'}, to=sid)
```

**Impact:** Any client can inject fake GPS positions, fake battery levels, fake RTK status.

### 4. HIGH: No Rate Limiting

```python
@sio.on('send_command')
async def handle_command(sid, data, ack_callback=None):
    # ... processes every command immediately, no limit
```

**Impact:** A client can flood the server with arm/disarm commands.

### 5. HIGH: No HTTPS/WSS

```python
# Backend/server.py:6612
uvicorn.run(sio_app, host='0.0.0.0', port=5001, log_level='info')
# No ssl_keyfile, no ssl_certfile
```

**Impact:** All traffic is plaintext. Anyone on WiFi can sniff packets.

### 6. MODERATE: Error Messages Leak Internal Details

```python
return _http_error(str(exc), 500)
# Exposes: "ROS2 client is not initialized", file paths, etc.
```

### 7. MODERATE: 100MB Socket.IO Buffer

```python
max_http_buffer_size=int(1e8),   # 100MB — memory DoS risk
```

### 8. LOW: Bare except on JSON parsing

```python
try:
    body = await request.json()
except:                           # catches SystemExit, KeyboardInterrupt too
    body = {}
```

---

## Exact Fixes

### Fix 1: Firebase + Jetson Hybrid Auth System

#### Part A: Create `Backend/auth.py` (Jetson-local auth engine)

```python
"""
Firebase + Jetson Hybrid Authentication for NRP Rover.

ONLINE:  Firebase handles user registration, password reset, profile management.
OFFLINE: Jetson validates users locally using a synced user list from Firebase.

The Jetson NEVER calls Firebase directly. The frontend app acts as the bridge:
  1. Frontend fetches authorized users from Firebase Firestore
  2. Frontend pushes the user list to Jetson via POST /api/auth/sync
  3. Jetson saves to auth.json and validates all logins locally

Two roles:
  - 'operator': View telemetry, control rover, run missions
  - 'admin':    All operator permissions + config changes, servo test, user sync
"""
import os
import time
import json
import hashlib
import hmac
import base64
import secrets
import threading
from typing import Optional, Dict, List
from functools import wraps
from fastapi import Request, HTTPException

# --- Configuration ---
AUTH_DIR = os.path.join(os.path.dirname(__file__), 'config')
AUTH_CONFIG_FILE = os.path.join(AUTH_DIR, 'auth.json')
JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '8'))
TOKEN_HEADER = 'Authorization'  # "Bearer <token>"
MAX_LOGIN_ATTEMPTS = 5           # Lock account after 5 failed attempts
LOGIN_LOCKOUT_SECONDS = 300      # 5 minute lockout

# --- JWT Secret (auto-generated on first run, persisted) ---
_secret_file = os.path.join(AUTH_DIR, '.jwt_secret')


def _load_or_create_secret() -> str:
    """Load JWT secret from file, or generate and save a new one."""
    os.makedirs(AUTH_DIR, exist_ok=True)
    if os.path.exists(_secret_file):
        with open(_secret_file, 'r') as f:
            secret = f.read().strip()
        if secret:
            return secret
    secret = secrets.token_hex(32)
    with open(_secret_file, 'w') as f:
        f.write(secret)
    try:
        os.chmod(_secret_file, 0o600)
    except OSError:
        pass
    return secret


JWT_SECRET = os.getenv('JWT_SECRET', '') or _load_or_create_secret()

# --- Login attempt tracking (in-memory, resets on restart) ---
_login_attempts: Dict[str, List[float]] = {}
_auth_lock = threading.Lock()

# --- Audit log (last 100 auth events) ---
_auth_audit: List[Dict] = []
_AUTH_AUDIT_MAX = 100


def _audit(event: str, username: str = '', success: bool = True, detail: str = ''):
    """Record an authentication event for auditing."""
    entry = {
        'timestamp': time.time(),
        'iso_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'event': event,
        'username': username,
        'success': success,
        'detail': detail
    }
    with _auth_lock:
        _auth_audit.append(entry)
        if len(_auth_audit) > _AUTH_AUDIT_MAX:
            _auth_audit.pop(0)


def get_auth_audit() -> List[Dict]:
    """Return recent auth events for admin dashboard."""
    with _auth_lock:
        return list(_auth_audit)


# ============================================================================
# PASSWORD HASHING
# ============================================================================

def _hash_password(password: str) -> str:
    """Hash password with per-user salt using SHA-256.

    For LAN-only use, SHA-256 with a static salt is sufficient.
    Passwords never leave the local network.
    """
    salt = "nrp_rover_v1"
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


# ============================================================================
# USER DATABASE (auth.json)
# ============================================================================

def _default_users() -> Dict:
    """Create default user database for first boot."""
    return {
        "version": 1,
        "synced_from_firebase": False,
        "last_sync": None,
        "users": {
            "operator": {
                "password_hash": _hash_password("operator123"),
                "role": "operator",
                "permissions": ["view", "control", "mission"],
                "display_name": "Default Operator",
                "enabled": True,
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%S')
            },
            "admin": {
                "password_hash": _hash_password("admin456"),
                "role": "admin",
                "permissions": [
                    "view", "control", "mission",
                    "config", "servo", "update", "user_sync", "auth_audit"
                ],
                "display_name": "Default Admin",
                "enabled": True,
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%S')
            }
        }
    }


def _load_users() -> Dict:
    """Load user database from auth.json."""
    if not os.path.exists(AUTH_CONFIG_FILE):
        users = _default_users()
        _save_users(users)
        _audit('db_created', detail='Default users created (change passwords!)')
        return users
    try:
        with open(AUTH_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        _audit('db_load_error', detail=str(exc), success=False)
        # Fallback to defaults if file is corrupted
        return _default_users()


def _save_users(data: Dict) -> bool:
    """Save user database to auth.json."""
    try:
        os.makedirs(AUTH_DIR, exist_ok=True)
        with open(AUTH_CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        try:
            os.chmod(AUTH_CONFIG_FILE, 0o600)
        except OSError:
            pass
        return True
    except Exception as exc:
        _audit('db_save_error', detail=str(exc), success=False)
        return False


# ============================================================================
# JWT TOKEN CREATION & VERIFICATION (no external library)
# ============================================================================

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + '=' * padding)


def create_token(username: str, role: str, permissions: List[str]) -> str:
    """Create a JWT token signed with HS256."""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_data = {
        "sub": username,
        "role": role,
        "permissions": permissions,
        "iat": int(time.time()),
        "exp": int(time.time()) + (JWT_EXPIRY_HOURS * 3600)
    }
    payload = _b64url_encode(json.dumps(payload_data).encode())
    signature_input = f"{header}.{payload}".encode()
    signature = _b64url_encode(
        hmac.new(JWT_SECRET.encode(), signature_input, hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> Optional[Dict]:
    """Verify and decode a JWT token. Returns payload dict or None."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts

        # Verify signature
        expected_sig = _b64url_encode(
            hmac.new(
                JWT_SECRET.encode(),
                f"{header_b64}.{payload_b64}".encode(),
                hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature_b64, expected_sig):
            return None

        # Decode payload
        payload = json.loads(_b64url_decode(payload_b64))

        # Check expiry
        if payload.get('exp', 0) < time.time():
            return None

        return payload
    except Exception:
        return None


# ============================================================================
# LOGIN & AUTHENTICATION
# ============================================================================

def _is_locked_out(username: str) -> bool:
    """Check if account is locked due to too many failed attempts."""
    now = time.time()
    with _auth_lock:
        attempts = _login_attempts.get(username, [])
        # Remove attempts older than lockout window
        recent = [t for t in attempts if now - t < LOGIN_LOCKOUT_SECONDS]
        _login_attempts[username] = recent
        return len(recent) >= MAX_LOGIN_ATTEMPTS


def _record_failed_attempt(username: str):
    """Record a failed login attempt."""
    with _auth_lock:
        if username not in _login_attempts:
            _login_attempts[username] = []
        _login_attempts[username].append(time.time())


def _clear_attempts(username: str):
    """Clear failed attempts after successful login."""
    with _auth_lock:
        _login_attempts.pop(username, None)


def authenticate(username: str, password: str) -> Optional[Dict]:
    """Authenticate user and return token + user info, or None if invalid.

    Returns:
        {
            'token': 'eyJ...',
            'username': 'operator',
            'role': 'operator',
            'display_name': 'Field Operator 1',
            'permissions': ['view', 'control', 'mission']
        }
        or None on failure.
    """
    # Check lockout
    if _is_locked_out(username):
        _audit('login_locked', username, success=False,
               detail=f'Account locked ({MAX_LOGIN_ATTEMPTS} failed attempts)')
        return None

    db = _load_users()
    user = db.get('users', {}).get(username)

    if not user:
        _record_failed_attempt(username)
        _audit('login_failed', username, success=False, detail='Unknown user')
        return None

    if not user.get('enabled', True):
        _audit('login_disabled', username, success=False, detail='Account disabled')
        return None

    if user['password_hash'] != _hash_password(password):
        _record_failed_attempt(username)
        _audit('login_failed', username, success=False, detail='Wrong password')
        return None

    # Success
    _clear_attempts(username)
    token = create_token(username, user['role'], user['permissions'])
    _audit('login_success', username, success=True)

    return {
        'token': token,
        'username': username,
        'role': user['role'],
        'display_name': user.get('display_name', username),
        'permissions': user['permissions']
    }


# ============================================================================
# FIREBASE SYNC — Frontend pushes authorized users to Jetson
# ============================================================================

def sync_users_from_firebase(user_list: List[Dict], admin_username: str) -> Dict:
    """Sync authorized users from Firebase (called via POST /api/auth/sync).

    The frontend fetches users from Firebase Firestore and pushes them here.
    This endpoint requires admin role.

    Args:
        user_list: List of user dicts from Firebase:
            [
                {
                    "username": "operator1",
                    "password": "field_password_123",
                    "role": "operator",
                    "permissions": ["view", "control", "mission"],
                    "display_name": "Field Operator 1",
                    "enabled": true
                },
                ...
            ]
        admin_username: The admin performing the sync (for audit)

    Returns:
        {'success': True/False, 'message': '...', 'synced_count': N}
    """
    if not isinstance(user_list, list):
        return {'success': False, 'message': 'user_list must be an array'}

    db = _load_users()
    synced = 0
    errors = []

    for entry in user_list:
        try:
            uname = str(entry.get('username', '')).strip().lower()
            password = str(entry.get('password', ''))
            role = str(entry.get('role', 'operator'))
            display_name = str(entry.get('display_name', uname))
            permissions = entry.get('permissions', [])
            enabled = bool(entry.get('enabled', True))

            if not uname or not password:
                errors.append(f"Skipped entry: missing username or password")
                continue

            if role not in ('operator', 'admin'):
                role = 'operator'

            # Default permissions by role
            if not permissions:
                if role == 'admin':
                    permissions = [
                        "view", "control", "mission",
                        "config", "servo", "update", "user_sync", "auth_audit"
                    ]
                else:
                    permissions = ["view", "control", "mission"]

            db['users'][uname] = {
                'password_hash': _hash_password(password),
                'role': role,
                'permissions': permissions,
                'display_name': display_name,
                'enabled': enabled,
                'synced_from_firebase': True,
                'synced_at': time.strftime('%Y-%m-%dT%H:%M:%S')
            }
            synced += 1

        except Exception as exc:
            errors.append(f"Error processing user: {exc}")

    db['synced_from_firebase'] = True
    db['last_sync'] = time.strftime('%Y-%m-%dT%H:%M:%S')

    if _save_users(db):
        _audit('firebase_sync', admin_username, success=True,
               detail=f'Synced {synced} users')
        result = {
            'success': True,
            'message': f'Synced {synced} users from Firebase',
            'synced_count': synced,
            'total_users': len(db['users'])
        }
        if errors:
            result['warnings'] = errors
        return result
    else:
        return {'success': False, 'message': 'Failed to save user database'}


# ============================================================================
# LOCAL USER MANAGEMENT (admin-only, for field use without Firebase)
# ============================================================================

def register_local_user(
    username: str, password: str, role: str,
    display_name: str = '', admin_username: str = ''
) -> Dict:
    """Register a new user locally on the Jetson (admin-only).

    Use this when in the field without internet — admin can create
    a temporary operator account directly on the Jetson.
    """
    username = username.strip().lower()
    if not username or not password:
        return {'success': False, 'message': 'Username and password required'}
    if len(password) < 6:
        return {'success': False, 'message': 'Password must be at least 6 characters'}
    if role not in ('operator', 'admin'):
        return {'success': False, 'message': 'Role must be operator or admin'}

    db = _load_users()
    if username in db.get('users', {}):
        return {'success': False, 'message': f'User "{username}" already exists'}

    if role == 'admin':
        permissions = [
            "view", "control", "mission",
            "config", "servo", "update", "user_sync", "auth_audit"
        ]
    else:
        permissions = ["view", "control", "mission"]

    db['users'][username] = {
        'password_hash': _hash_password(password),
        'role': role,
        'permissions': permissions,
        'display_name': display_name or username,
        'enabled': True,
        'synced_from_firebase': False,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'created_by': admin_username
    }

    if _save_users(db):
        _audit('user_created', admin_username, success=True,
               detail=f'Created local user: {username} ({role})')
        return {
            'success': True,
            'message': f'User "{username}" created as {role}'
        }
    return {'success': False, 'message': 'Failed to save user database'}


def change_password(username: str, new_password: str, admin_username: str = '') -> Dict:
    """Change a user's password (admin can change any, user can change own)."""
    if len(new_password) < 6:
        return {'success': False, 'message': 'Password must be at least 6 characters'}

    db = _load_users()
    if username not in db.get('users', {}):
        return {'success': False, 'message': f'User "{username}" not found'}

    db['users'][username]['password_hash'] = _hash_password(new_password)

    if _save_users(db):
        _audit('password_changed', admin_username or username, success=True,
               detail=f'Password changed for: {username}')
        return {'success': True, 'message': f'Password changed for "{username}"'}
    return {'success': False, 'message': 'Failed to save'}


def list_users(include_hash: bool = False) -> List[Dict]:
    """List all users (for admin dashboard)."""
    db = _load_users()
    users = []
    for uname, data in db.get('users', {}).items():
        entry = {
            'username': uname,
            'role': data.get('role', 'operator'),
            'display_name': data.get('display_name', uname),
            'permissions': data.get('permissions', []),
            'enabled': data.get('enabled', True),
            'synced_from_firebase': data.get('synced_from_firebase', False),
        }
        if not include_hash:
            pass  # Don't include password hash
        users.append(entry)
    return users


# ============================================================================
# REQUEST HELPERS (for use in server.py)
# ============================================================================

def get_current_user(request: Request) -> Optional[Dict]:
    """Extract and verify user from request Authorization header."""
    auth_header = request.headers.get(TOKEN_HEADER, '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        return verify_token(token)
    return None


def require_auth(permission: str = None):
    """Decorator for FastAPI routes requiring authentication.

    Usage:
        @app.post("/api/arm")
        @require_auth("control")
        async def api_arm(request: Request):
            user = request.state.user  # Authenticated user payload
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            user = get_current_user(request)
            if not user:
                raise HTTPException(status_code=401, detail="Authentication required")
            if permission and permission not in user.get('permissions', []):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission '{permission}' required"
                )
            request.state.user = user
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator


def verify_socketio_token(token: str) -> Optional[Dict]:
    """Verify token sent during Socket.IO connection handshake."""
    return verify_token(token)
```

#### Part B: Add Auth Endpoints to server.py

```python
# Add these imports near the top of server.py:
from auth import (
    authenticate, get_current_user, verify_socketio_token,
    require_auth, sync_users_from_firebase, register_local_user,
    change_password, list_users, get_auth_audit
)

# ============================================================================
# AUTH ENDPOINTS (add near the REST routes section)
# ============================================================================

@app.post("/api/auth/login")
async def api_login(request: Request):
    """Login and receive JWT token. Works fully offline."""
    try:
        body = await request.json()
    except Exception:
        return _http_error("Invalid request body", 400)

    username = str(body.get('username', '')).strip()
    password = str(body.get('password', '')).strip()

    if not username or not password:
        return _http_error("Username and password required", 400)

    result = authenticate(username, password)
    if not result:
        log_message(f"Failed login: {username}", "WARNING", event_type='auth')
        return _http_error("Invalid credentials", 401)

    log_message(f"User logged in: {username} ({result['role']})", "INFO", event_type='auth')
    return JSONResponse({
        'success': True,
        'token': result['token'],
        'username': result['username'],
        'role': result['role'],
        'display_name': result['display_name'],
        'permissions': result['permissions']
    })


@app.post("/api/auth/sync")
async def api_auth_sync(request: Request):
    """Sync authorized users from Firebase (admin-only).

    Called by the frontend when internet is available.
    The frontend fetches users from Firebase Firestore,
    then pushes them here so Jetson has a local copy.
    """
    user = get_current_user(request)
    if not user:
        return _http_error("Authentication required", 401)
    if 'user_sync' not in user.get('permissions', []):
        return _http_error("Admin permission required", 403)

    try:
        body = await request.json()
    except Exception:
        return _http_error("Invalid request body", 400)

    user_list = body.get('users', [])
    if not isinstance(user_list, list) or not user_list:
        return _http_error("No users provided", 400)

    result = sync_users_from_firebase(user_list, user.get('sub', 'admin'))

    if result['success']:
        log_message(
            f"Firebase sync: {result['synced_count']} users synced by {user['sub']}",
            "INFO", event_type='auth'
        )
        return JSONResponse(result)
    else:
        return _http_error(result['message'], 400)


@app.post("/api/auth/register")
async def api_auth_register(request: Request):
    """Register a new local user (admin-only, for field use)."""
    user = get_current_user(request)
    if not user:
        return _http_error("Authentication required", 401)
    if user.get('role') != 'admin':
        return _http_error("Admin role required", 403)

    try:
        body = await request.json()
    except Exception:
        return _http_error("Invalid request body", 400)

    result = register_local_user(
        username=str(body.get('username', '')),
        password=str(body.get('password', '')),
        role=str(body.get('role', 'operator')),
        display_name=str(body.get('display_name', '')),
        admin_username=user.get('sub', '')
    )

    if result['success']:
        log_message(
            f"User registered: {body.get('username')} by {user['sub']}",
            "INFO", event_type='auth'
        )
        return JSONResponse(result)
    return _http_error(result['message'], 400)


@app.post("/api/auth/change-password")
async def api_auth_change_password(request: Request):
    """Change password (admin can change any, user can change own)."""
    user = get_current_user(request)
    if not user:
        return _http_error("Authentication required", 401)

    try:
        body = await request.json()
    except Exception:
        return _http_error("Invalid request body", 400)

    target_user = str(body.get('username', user.get('sub', ''))).strip()
    new_password = str(body.get('new_password', ''))

    # Non-admins can only change their own password
    if target_user != user.get('sub') and user.get('role') != 'admin':
        return _http_error("Cannot change other users' passwords", 403)

    result = change_password(target_user, new_password, user.get('sub', ''))

    if result['success']:
        return JSONResponse(result)
    return _http_error(result['message'], 400)


@app.get("/api/auth/users")
async def api_auth_users(request: Request):
    """List all users (admin-only)."""
    user = get_current_user(request)
    if not user:
        return _http_error("Authentication required", 401)
    if user.get('role') != 'admin':
        return _http_error("Admin role required", 403)

    return JSONResponse({'success': True, 'users': list_users()})


@app.get("/api/auth/audit")
async def api_auth_audit(request: Request):
    """Get auth audit log (admin-only)."""
    user = get_current_user(request)
    if not user:
        return _http_error("Authentication required", 401)
    if 'auth_audit' not in user.get('permissions', []):
        return _http_error("Permission required", 403)

    return JSONResponse({'success': True, 'events': get_auth_audit()})


@app.get("/api/auth/me")
async def api_auth_me(request: Request):
    """Get current user info from token (validates token is still valid)."""
    user = get_current_user(request)
    if not user:
        return _http_error("Authentication required", 401)
    return JSONResponse({
        'success': True,
        'username': user.get('sub'),
        'role': user.get('role'),
        'permissions': user.get('permissions', [])
    })
```

#### Part C: Socket.IO Auth Middleware

```python
# Modify handle_connect (line 3173) in server.py:
@sio.on('connect')
async def handle_connect(sid, environ):
    """Authenticated connection handler."""

    # --- Extract token from query string or headers ---
    token = None
    query_string = environ.get('QUERY_STRING', '')
    for param in query_string.split('&'):
        if param.startswith('token='):
            token = param[6:]
            break

    if not token:
        auth_header = environ.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]

    if not token:
        log_message(f"Socket.IO rejected: no token from {sid}", "WARNING", event_type='auth')
        return False  # Reject connection

    user = verify_socketio_token(token)
    if not user:
        log_message(f"Socket.IO rejected: invalid token from {sid}", "WARNING", event_type='auth')
        return False  # Reject connection

    # --- Authenticated! Store user in session ---
    username = user.get('sub', 'unknown')
    role = user.get('role', 'unknown')
    await sio.save_session(sid, {'user': user})

    log_message(f"Client connected: {username} ({role}) sid={sid}", 'INFO', event_type='auth')

    # ... rest of existing connect handler (send status, rover data, etc.) ...
```

#### Part D: Frontend Socket.IO Connection (example)

```javascript
// Frontend: connect with token after login
const socket = io(`http://rover-nrp.local:5001`, {
    query: { token: localStorage.getItem('jwt_token') },
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionAttempts: Infinity,
});

// Frontend: REST API calls with token
async function armRover() {
    const response = await fetch('/api/arm', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${localStorage.getItem('jwt_token')}`
        },
        body: JSON.stringify({ arm: true })
    });
}
```

#### Part E: Firebase Firestore Structure (frontend syncs from here)

```
Firebase Firestore:
  /rover_users/
    /operator1:
      username: "operator1"
      password: "field_pass_123"     (plain — only synced to Jetson, hashed on arrival)
      role: "operator"
      display_name: "Murugan"
      enabled: true
    /admin1:
      username: "admin1"
      password: "admin_secure_456"
      role: "admin"
      display_name: "Supervisor"
      enabled: true
```

**Important:** Passwords in Firestore are stored in a **restricted collection** with Firebase Security Rules that only allow admin reads:

```javascript
// Firebase Security Rules
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /rover_users/{userId} {
      allow read: if request.auth != null
                  && get(/databases/$(database)/documents/rover_admins/$(request.auth.uid)).data.role == 'admin';
      allow write: if request.auth != null
                   && get(/databases/$(database)/documents/rover_admins/$(request.auth.uid)).data.role == 'admin';
    }
  }
}
```

---

### Fix 2: Restrict CORS to Your Frontend

```python
# Before (line 100-106):
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# After:
ALLOWED_ORIGINS = [
    "http://rover-nrp.local:3000",     # Frontend via mDNS
    "http://rover-nrp.local:5001",     # Direct backend access
    "http://192.168.1.100:3000",       # Fallback static IP
    "http://localhost:3000",           # Development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Socket.IO:
sio = socketio_pkg.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=ALLOWED_ORIGINS,
    ...
)
```

### Fix 3: Remove or Gate the Test Endpoint

```python
# Only allow in development mode + admin role:
@sio.on('inject_mavros_telemetry')
async def handle_inject_mavros_telemetry(sid, data):
    if os.getenv('NRP_ENV', 'production') != 'development':
        await sio.emit('inject_ack', {
            'status': 'error', 'error': 'Disabled in production'
        }, to=sid)
        return

    session = await sio.get_session(sid)
    user = session.get('user', {})
    if user.get('role') != 'admin':
        await sio.emit('inject_ack', {
            'status': 'error', 'error': 'Admin only'
        }, to=sid)
        return

    _handle_mavros_telemetry(data)
    await sio.emit('inject_ack', {'status': 'ok'}, to=sid)
```

### Fix 4: Add Basic Rate Limiting

```python
from collections import defaultdict

_rate_limit_buckets: Dict[str, list] = defaultdict(list)
_RATE_LIMIT_WINDOW = 1.0   # 1 second window
_RATE_LIMIT_MAX = 10        # max 10 commands per second

def _check_rate_limit(sid: str) -> bool:
    """Return True if allowed, False if rate-limited."""
    now = time.time()
    bucket = _rate_limit_buckets[sid]
    bucket[:] = [t for t in bucket if now - t < _RATE_LIMIT_WINDOW]
    if len(bucket) >= _RATE_LIMIT_MAX:
        return False
    bucket.append(now)
    return True

# Use in handle_command:
@sio.on('send_command')
async def handle_command(sid, data, ack_callback=None):
    if not _check_rate_limit(sid):
        payload = {'status': 'error', 'message': 'Rate limit exceeded', 'acked': True}
        if ack_callback:
            ack_callback(payload)
        return
    # ... rest of handler ...
```

### Fix 5: Reduce Socket.IO Buffer Size

```python
# Before:
max_http_buffer_size=int(1e8),   # 100MB

# After:
max_http_buffer_size=5 * 1024 * 1024,  # 5MB
```

### Fix 6: Sanitize Error Messages

```python
def _safe_error_message(exc: Exception) -> str:
    """Return user-safe error message without internal details."""
    msg = str(exc)
    if '/home/' in msg or 'Traceback' in msg:
        return "Internal server error"
    if any(k in msg.lower() for k in ['timeout', 'not connected', 'not available', 'invalid']):
        return msg
    return "Operation failed"

# Usage throughout:
return _http_error(_safe_error_message(exc), 500)
```

### Fix 7: HTTPS via nginx (Self-Signed, LAN-Only)

```nginx
# /etc/nginx/sites-available/nrp-rover
server {
    listen 443 ssl;
    server_name rover-nrp.local;

    ssl_certificate /opt/rover/certs/rover.crt;
    ssl_certificate_key /opt/rover/certs/rover.key;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /socket.io/ {
        proxy_pass http://127.0.0.1:5001/socket.io/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
# Generate self-signed cert (valid 10 years):
mkdir -p /opt/rover/certs
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /opt/rover/certs/rover.key \
  -out /opt/rover/certs/rover.crt \
  -subj "/CN=rover-nrp.local"
```

---

## Complete Auth Flow Summary

```
SCENARIO 1: First deployment (office, has internet)
  1. Admin logs into Firebase web console
  2. Creates users: operator1, admin1, field_operator2
  3. Opens NRP frontend app on tablet
  4. App fetches user list from Firebase Firestore
  5. App calls POST /api/auth/sync on Jetson with user list
  6. Jetson saves users to auth.json (passwords hashed locally)
  7. Done — Jetson now has all users offline

SCENARIO 2: Field operation (no internet)
  1. Operator opens app on tablet
  2. App discovers rover via mDNS (rover-nrp.local)
  3. Login page shown — operator enters username/password
  4. App calls POST /api/auth/login on Jetson
  5. Jetson checks auth.json locally, returns JWT
  6. App stores JWT, connects Socket.IO with token
  7. Operator controls rover — zero internet needed

SCENARIO 3: Emergency field user creation (no internet)
  1. Admin logs into app with admin credentials
  2. Goes to Settings > User Management
  3. Calls POST /api/auth/register (admin-only)
  4. New operator account created directly on Jetson
  5. New operator can now log in immediately

SCENARIO 4: Back online — sync updates
  1. App detects internet is available
  2. Fetches latest user list from Firebase
  3. Calls POST /api/auth/sync to update Jetson
  4. Any users added/disabled in Firebase are now reflected locally
```

---

## Priority Order

1. **auth.py + login endpoint** — stops unauthorized control (do first)
2. **Socket.IO auth** — stops unauthorized WebSocket connections
3. **Restrict CORS** — stops browser-based attacks
4. **Remove test endpoint** — stops telemetry injection
5. **Rate limiting** — stops flooding
6. **Firebase sync endpoint** — enables centralized user management
7. **HTTPS via nginx** — stops packet sniffing (deployment time)
8. **Sanitize errors** — stops info leakage
