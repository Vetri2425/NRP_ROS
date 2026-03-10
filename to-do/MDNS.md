✗ Problem: With 5 robots, you manually change IP in client code for each robot

Solution: Service Discovery + Rover Selection UI
Implementation Methods (Ranked by Security & Reliability)
Method 1: mDNS/Zeroconf Discovery (Recommended)
Best for: Local network, zero configuration, secure

How it works:

Each rover broadcasts its presence with a unique name: rover-1.local, rover-2.local

Client automatically discovers all rovers on network

No manual IP entry needed

Works even if DHCP changes IPs

Backend (Python):

Install: zeroconf library

Each rover publishes service: _rover._tcp.local. with unique ID

Broadcast: Rover ID, IP, port, status

Frontend:

Use bonjour-service or WebSocket-based discovery endpoint

Backend provides /api/discover endpoint that returns all found rovers

UI shows list: "Rover-1 (192.168.1.100)", "Rover-2 (192.168.1.101)"

Security:

mDNS only works on local network (not internet-exposed)

Add authentication token per rover

Optional: TLS/SSL for Socket.IO connections

Method 2: Central Registry Server
Best for: Multiple networks, cloud monitoring

How it works:

Each rover registers itself to a central server (on router or cloud)

Client queries registry to get list of available rovers

Registry maintains heartbeat to know which rovers are online

Backend:

Each rover sends heartbeat every 5-10 seconds to registry

Registry endpoint: /register (rover posts ID, IP, status)

Registry endpoint: /rovers (client gets list)

Frontend:

Fetch from registry: GET http://<registry-ip>/rovers

Display online rovers with last-seen timestamp

Connect to selected rover's IP:port

Security:

API key authentication for registry

Rate limiting on registration

HTTPS for registry communication

Method 3: UDP Broadcast Discovery
Best for: Simple, fast, no dependencies

How it works:

Client broadcasts "WHO_IS_ROVER?" on UDP port (e.g., 5002)

All rovers respond with their ID, IP, port

Client builds list from responses

Backend:

UDP listener on port 5002

Responds to discovery packets with JSON: {id: "rover-1", ip: "192.168.1.100", port: 5001}

Frontend:

Send UDP broadcast from backend proxy (browsers can't do UDP)

Or: Backend provides /api/scan that does UDP scan and returns results

Display discovered rovers

Security:

⚠️ UDP is unencrypted (add signature/HMAC to responses)

Limit to local subnet only

Add challenge-response authentication

Method 4: QR Code + Manual Selection
Best for: Field operations, offline

How it works:

Each rover displays QR code on screen/label with its connection info

Operator scans QR to get rover-id and connection details

App stores multiple rover profiles

Implementation:

QR contains: {"id": "rover-1", "ip": "192.168.1.100", "port": 5001, "token": "xxx"}

Frontend has "Scan Rover" button

Stores in localStorage for quick switching

Security:

QR includes unique auth token

Token rotates periodically

Physical access required to scan

Recommended Architecture
Best approach: mDNS + Authentication

Discovery Flow:
1. User opens app → Shows "Scanning for rovers..."
2. Backend scans network using mDNS (2-3 seconds)
3. Displays: 
   - Rover-1 (192.168.1.100) [Online] [Battery: 85%]
   - Rover-2 (192.168.1.101) [Online] [Battery: 72%]
   - Rover-3 (192.168.1.102) [Offline]
4. User clicks "Connect to Rover-1"
5. App connects to Socket.IO at discovered IP
6. Authenticates with rover-specific token
7. Stores last-connected rover for quick reconnect

Copy

Insert at cursor
Security Layers:

Network: mDNS only on local network

Authentication: Each rover has unique token (stored in rover config)

Transport: Socket.IO with CORS restricted to local subnet

Session: JWT token after initial auth

Optional: TLS certificates for production

Rover ID Management:

Store in rover: /etc/rover-config.json → {"rover_id": "rover-1", "auth_token": "..."}

Set once during rover setup

Backend reads on startup

Implementation Complexity
Method	Setup Time	Reliability	Security	Network Changes
mDNS	Medium	⭐⭐⭐⭐⭐	⭐⭐⭐⭐	Handles automatically
Registry	High	⭐⭐⭐⭐	⭐⭐⭐⭐⭐	Handles automatically
UDP Broadcast	Low	⭐⭐⭐	⭐⭐⭐	Handles automatically
QR Code	Low	⭐⭐⭐⭐	⭐⭐⭐⭐	Manual update needed
My recommendation: Start with mDNS (Method 1) - it's the industry standard for local device discovery (used by Chromecast, AirPlay, IoT devices) and requires minimal infrastructure.