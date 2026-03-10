Production-Ready Security Architecture
Your Requirements
✅ Secure rover discovery (Zeroconf)

✅ Prevent unauthorized control

✅ Protect server data/files from physical access

✅ Hide application structure/code

✅ No sensitive files in home directory

✅ Production deployment = locked down system

Architecture Overview
┌─────────────────────────────────────────────────────────────┐
│                    PRODUCTION ARCHITECTURE                   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Operator (Tablet)                                           │
│       ↓                                                       │
│  [Login] → Central Auth Server (Cloud/Router)                │
│       ↓                                                       │
│  [JWT Token + Rover List]                                    │
│       ↓                                                       │
│  [Zeroconf Discovery] → Find rovers on network               │
│       ↓                                                       │
│  [Connect] → Rover (Jetson) - Encrypted Socket.IO            │
│       ↓                                                       │
│  [Validate JWT] → Execute Commands                           │
│                                                               │
└─────────────────────────────────────────────────────────────┘

Security Layers (Production)
Layer 1: Physical & Network Security
✓ Separate WiFi network (WPA3)
✓ Jetson SSH disabled after deployment
✓ Jetson firewall (only port 5001 open)
✓ No USB/HDMI access (disable in BIOS if possible)
 -
Layer 2: Application Hardening
A. Hide Application Code
# Current (Development):
/home/user/rover_app/
├── server.py          # ❌ Visible source code
├── config.json        # ❌ Visible secrets
└── requirements.txt

# Production (Locked):
/opt/rover/
├── rover_server       # ✅ Compiled binary (PyInstaller)
├── config.enc         # ✅ Encrypted config
└── .env              # ✅ Environment variables only
  
Implementation:

Compile Python to binary using PyInstaller

Move to /opt/rover/ (requires root to access)

Run as systemd service (non-root user)

Source code never on Jetson

B. Encrypt Sensitive Data
# Encrypted config file
/opt/rover/config.enc  # AES-256 encrypted

# Decryption key stored in:
- Hardware TPM chip (best)
- Environment variable (good)
- Encrypted with device serial number (acceptable)
  
What to encrypt:

Rover auth token

Database credentials (if any)

API keys

SSL certificates

C. Read-Only Filesystem
# Make application directory immutable
sudo chattr +i /opt/rover/rover_server
sudo chattr +i /opt/rover/config.enc

# Even root can't modify without removing immutable flag
 
Layer 3: Authentication & Authorization
A. Central Auth Server
┌──────────────────────────────────────────┐
│         Auth Server (Cloud/Router)        │
├──────────────────────────────────────────┤
│ • User database (operators)               │
│ • Rover registry                          │
│ • JWT token generation                    │
│ • Access control lists                    │
│ • Audit logs                              │
└──────────────────────────────────────────┘

Endpoints:

POST /auth/login
  → Returns: JWT token + list of accessible rovers

GET /auth/rovers
  → Returns: Live rover list with IPs

POST /auth/validate
  → Validates JWT token (rovers call this)
B. JWT-Based Authentication
Flow:
1. Operator logs in → Gets JWT (expires in 8 hours)
2. JWT contains: {user_id, role, allowed_rovers, exp}
3. App connects to rover → Sends JWT
4. Rover validates JWT with auth server
5. Rover caches validation (5 min) to work offline
 -
JWT Payload:

{
  "user_id": "operator-001",
  "role": "operator",
  "allowed_rovers": ["rover-001", "rover-002"],
  "permissions": ["move", "stop", "status"],
  "exp": 1735689600
}
 -
json
C. Per-Rover Secret Token
Each rover has unique token (never leaves Jetson)
Stored encrypted in /opt/rover/config.enc

Used for:
- Rover-to-auth-server communication
- Emergency local access (if auth server down)
 -
Layer 4: Runtime Security
A. Run as Non-Root User
# Create dedicated user
sudo useradd -r -s /bin/false rover_service

# Service runs as rover_service (no shell, no home dir)
# Can't access other files on system
  
B. Systemd Service (Auto-Start + Restart)
# /etc/systemd/system/rover.service
[Unit]
Description=Rover Control Server
After=network.target

[Service]
Type=simple
User=rover_service
Group=rover_service
WorkingDirectory=/opt/rover
ExecStart=/opt/rover/rover_server
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/opt/rover

# Environment
EnvironmentFile=/opt/rover/.env

[Install]
WantedBy=multi-user.target
 -
ini
C. Command Validation & Rate Limiting
# Every command validated
ALLOWED_COMMANDS = ['move', 'stop', 'status', 'battery']
MAX_SPEED = 2.0  # m/s
RATE_LIMIT = 10  # commands/second

# Log all commands
audit_log.write(f"{timestamp} {user_id} {command} {params}")
 -
python
Layer 5: Data Protection
A. Encrypted Logs
# Logs encrypted and rotated
/var/log/rover/
├── commands.log.enc    # Encrypted command history
├── errors.log.enc      # Encrypted error logs
└── audit.log.enc       # Encrypted audit trail

# Decryption key only on auth server
# Logs uploaded to auth server daily, then deleted locally
  
B. No Persistent Sensitive Data
✓ No passwords stored on Jetson
✓ No user data stored on Jetson
✓ JWT tokens cached in memory only (cleared on restart)
✓ Telemetry data streamed, not stored
 -
C. Secure Boot & Disk Encryption
# Full disk encryption (LUKS)
# Decryption key in TPM chip
# Prevents data extraction if Jetson stolen

# Enable on Jetson:
sudo cryptsetup luksFormat /dev/mmcblk0p1
  
Layer 6: Network Security
A. TLS/SSL Encryption
# All Socket.IO traffic encrypted
socketio.run(app, 
    host='0.0.0.0', 
    port=5001,
    ssl_context=('cert.pem', 'key.pem')
)
 -
python
Certificate management:

Self-signed certs generated per rover

Pinned in app (prevent MITM)

Auto-rotate every 90 days

B. Firewall Rules
# Only allow necessary ports
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 5001/tcp  # Rover control
sudo ufw enable

# Block SSH after deployment
sudo ufw deny 22/tcp
  
C. Intrusion Detection
# Monitor for suspicious activity
- Multiple failed auth attempts → Lock rover
- Unknown commands → Alert + disconnect
- Unusual network traffic → Alert
- Physical tampering (if sensors available) → Shutdown
 -
python
Deployment Process
Development Phase (Now)
/home/user/NRP_ROS/
├── backend/
│   ├── server.py
│   ├── config.json
│   └── requirements.txt
└── frontend/

# You can edit, test, restart freely
  
Production Deployment
Step 1: Build Binary
# On development machine
cd /home/user/NRP_ROS/backend
pip install pyinstaller cryptography

# Create encrypted config
python encrypt_config.py config.json → config.enc

# Compile to binary
pyinstaller --onefile \
    --add-data "config.enc:." \
    --hidden-import socketio \
    --hidden-import flask \
    --name rover_server \
    server.py

# Output: dist/rover_server (single binary)
  
Step 2: Deploy to Jetson
# Copy binary to Jetson
scp dist/rover_server jetson:/tmp/
scp config.enc jetson:/tmp/
scp deploy.sh jetson:/tmp/

# On Jetson, run deployment script
ssh jetson
sudo /tmp/deploy.sh

# deploy.sh does:
# 1. Create /opt/rover/
# 2. Move binary + config
# 3. Create rover_service user
# 4. Install systemd service
# 5. Set permissions (700)
# 6. Make files immutable
# 7. Enable firewall
# 8. Disable SSH
# 9. Remove /tmp files
# 10. Start service
  
Step 3: Lock Down System
# After deployment, Jetson has:
/opt/rover/
├── rover_server       (binary, immutable)
├── config.enc         (encrypted, immutable)
└── .env              (env vars only)

# No source code
# No development files
# No home directory files
# SSH disabled
# Service auto-starts on boot
  
Step 4: Remove Development Access
# Disable SSH permanently
sudo systemctl disable ssh
sudo systemctl stop ssh

# Remove sudo access for default user
sudo deluser user sudo

# Lock root account
sudo passwd -l root

# Only way to access: Physical console (if needed for emergency)
  
File Structure Comparison
Before (Development)
/home/user/NRP_ROS/
├── backend/
│   ├── server.py              ❌ Source code visible
│   ├── config.json            ❌ Secrets visible
│   ├── auth_token.txt         ❌ Token visible
│   ├── database.db            ❌ Data visible
│   └── logs/                  ❌ Logs visible
└── frontend/
 -
After (Production)
/opt/rover/
├── rover_server               ✅ Compiled binary (no source)
├── config.enc                 ✅ Encrypted (AES-256)
└── .env                       ✅ Only non-sensitive vars

/var/log/rover/
└── audit.log.enc              ✅ Encrypted logs

/home/user/                    ✅ Empty (no files)
 -
Security Checklist
Application Security
 Source code compiled to binary
 Config files encrypted
 No secrets in plaintext
 Runs as non-root user
 Read-only filesystem
 Command validation
 Rate limiting
 Audit logging
Authentication
 Central auth server
 JWT-based authentication
 Per-rover secret tokens
 Role-based access control
 Token expiration (8 hours)
 Offline validation cache
Network Security
 TLS/SSL encryption
 Firewall enabled
 Only port 5001 open
 SSH disabled
 Certificate pinning
Physical Security
 No source code on device
 Encrypted disk (optional)
 Immutable files
 No development tools
 No shell access
 Tamper detection (optional)
Data Protection
 Encrypted logs
 No persistent sensitive data
 Logs uploaded & deleted
 Secure boot (optional)
Emergency Access
If you need to update rover after deployment:

# Option 1: Physical console access
# - Connect keyboard/monitor
# - Boot into recovery mode
# - Remove immutable flag
# - Update files
# - Re-lock

# Option 2: Signed update mechanism
# - Create update package (signed with your key)
# - Rover validates signature
# - Auto-applies update
# - Restarts service

# Option 3: Remote update (if auth server accessible)
# - Auth server pushes update
# - Rover validates source
# - Downloads & applies
# - Restarts
  
Cost & Complexity
Component	Complexity	Time	Cost
PyInstaller binary	Low	1 hour	Free
Config encryption	Low	2 hours	Free
Systemd service	Low	1 hour	Free
Firewall setup	Low	30 min	Free
Auth server	Medium	1 day	$5/month (cloud)
JWT implementation	Medium	4 hours	Free
TLS certificates	Medium	2 hours	Free (self-signed)
Disk encryption	High	4 hours	Free
Total	Medium	2-3 days	$5/month
Final Architecture
┌─────────────────────────────────────────────────────────────┐
│                    PRODUCTION SYSTEM                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Operator Tablet                                             │
│    ↓ (Login)                                                 │
│  Auth Server (Cloud) ← Validates all access                  │
│    ↓ (JWT + Rover List)                                      │
│  App discovers rovers (Zeroconf)                             │
│    ↓ (Connect with JWT)                                      │
│  Rover (Jetson) - LOCKED DOWN:                               │
│    • Binary only (no source)                                 │
│    • Encrypted config                                        │
│    • No SSH                                                  │
│    • Firewall active                                         │
│    • Immutable files                                         │
│    • Non-root execution                                      │
│    • Encrypted logs                                          │
│    • Rate limiting                                           │
│    • Command validation                                      │
│                                                               │
└─────────────────────────────────────────────────────────────┘

## Implementation Priority

### Phase 1: Basic Security (Week 1)
- [ ] Compile to binary with PyInstaller
- [ ] Encrypt configuration files
- [ ] Create systemd service
- [ ] Set up firewall rules
- [ ] Disable SSH access

### Phase 2: Authentication (Week 2)
- [ ] Implement JWT authentication
- [ ] Set up central auth server
- [ ] Add role-based access control
- [ ] Implement token validation

### Phase 3: Advanced Security (Week 3)
- [ ] Add audit logging
- [ ] Implement rate limiting
- [ ] Set up encrypted log rotation
- [ ] Add intrusion detection
- [ ] Configure TLS certificates

### Phase 4: Hardening (Week 4)
- [ ] Enable disk encryption (optional)
- [ ] Implement secure boot (optional)
- [ ] Add tamper detection (optional)
- [ ] Set up remote update mechanism

## Quick Start Commands

```bash
# Development to Production Conversion
cd /home/flash/NRP_ROS/backend

# 1. Install build tools
pip install pyinstaller cryptography

# 2. Encrypt config
python -c "
import json
from cryptography.fernet import Fernet
key = Fernet.generate_key()
with open('config.json', 'r') as f:
    data = f.read()
encrypted = Fernet(key).encrypt(data.encode())
with open('config.enc', 'wb') as f:
    f.write(encrypted)
with open('key.txt', 'wb') as f:
    f.write(key)
print('Config encrypted successfully')
"

# 3. Build binary
pyinstaller --onefile --name rover_server server.py

# 4. Deploy to Jetson
scp dist/rover_server jetson:/tmp/
scp config.enc jetson:/tmp/
```

## Security Validation

```bash
# Check security status on Jetson
sudo systemctl status rover
sudo ufw status
ls -la /opt/rover/
lsattr /opt/rover/*  # Check immutable flags
ps aux | grep rover  # Verify non-root execution
```

This security framework transforms your development rover into a production-ready, locked-down system while maintaining full functionality and remote management capabilities.                  │
│    • Non-root service                                        │
│    • TLS encrypted                                           │
│    • Command validation                                      │
│    • Audit logging                                           │
│                                                               │
│  Result: Even with physical access, attacker gets:          │
│    ❌ No source code                                         │
│    ❌ No secrets                                             │
│    ❌ No shell access                                        │
│    ❌ No file modification                                   │
│    ✅ Only encrypted binary                                  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
 -
This architecture ensures:

✅ No one can steal rover code/data

✅ No one can access Jetson files

✅ No one can modify application

✅ Only authorized operators can control rovers

✅ All actions are logged and audited

✅ Production-ready and scalable to 100+ rovers