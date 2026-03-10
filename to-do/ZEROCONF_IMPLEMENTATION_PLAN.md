# Zeroconf Implementation Plan for Secure Rover Discovery

## Table of Contents
1. [What is Zeroconf?](#what-is-zeroconf)
2. [How Zeroconf Works](#how-zeroconf-works)
3. [Pros and Cons](#pros-and-cons)
4. [IP Address Changes Handling](#ip-address-changes-handling)
5. [Security Considerations](#security-considerations)
6. [Implementation Architecture](#implementation-architecture)
7. [Rover-Side Implementation (Jetson)](#rover-side-implementation-jetson)
8. [Client-Side Implementation (Tablet/App)](#client-side-implementation-tabletapp)
9. [Integration with Authentication](#integration-with-authentication)
10. [Testing & Deployment](#testing--deployment)

---

## What is Zeroconf?

Zeroconf (Zero Configuration Networking) is a set of technologies that enables automatic discovery of devices and services on a local network without manual configuration. It uses:

- **mDNS (Multicast DNS)**: Resolves hostnames to IP addresses using multicast
- **DNS-SD (DNS Service Discovery)**: Discovers services available on the network

### Service Announcement Format
```
Service Type: _rovercontrol._tcp
Service Name: rover-001._rovercontrol._tcp.local
Port: 5001
 TXT Records: version=1.0, uuid=abc123, auth_required=true
```

---

## How Zeroconf Works

### Discovery Process Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ZEROCONF DISCOVERY FLOW                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ROVER (Jetson)                      CLIENT (Tablet)                   │
│       │                                    │                             │
│       │  1. Start mDNS service             │                             │
│       │  Advertise:                        │                             │
│       │  rover-001._rovercontrol._tcp.local│                             │
│       │  Port: 5001                        │                             │
│       │       │                            │                             │
│       │       │  Multicast (224.0.0.251)   │                             │
│       │◄─────►│  Port 5353                  │                             │
│       │       │                            │                             │
│       │       │                     2. Browse for services             │
│       │       │                     _rovercontrol._tcp.local           │
│       │       │                            │                             │
│       │  3. Service Found                  │                             │
│       │◄───────────────────────────────────┤                             │
│       │  Returns: hostname, IP, port       │                             │
│       │       │                            │                             │
│       │       │                     4. Connect to IP:5001                │
│       │◄───────────────────────────────────┤                             │
│       │  Socket.IO + JWT Auth              │                             │
│       │       │                            │                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step Operation

1. **Rover boots up**
   - Python service starts on port 5001
   - Registers mDNS service: `rover-001._rovercontrol._tcp.local`
   - Advertises TXT records (version, UUID, capabilities)

2. **Client starts discovery**
   - Queries for `_rovercontrol._tcp.local` services
   - Receives list of available rovers with IPs

3. **Client connects**
   - Establishes Socket.IO connection to discovered IP
   - Performs JWT authentication

4. **IP change handling**
   - Rover re-announces service with new IP
   - Client receives update automatically

---

## Pros and Cons

### ✅ Advantages of Zeroconf

| Advantage | Description |
|-----------|-------------|
| **Zero Configuration** | No need to manually set IPs or hostnames |
| **Automatic Discovery** | Rovers appear automatically when online |
| **IP Change Resilience** | Automatically adapts to new IPs |
| **Low Latency** | Discovery happens in seconds |
| **No Central Server** | Works without infrastructure |
| **Cross-Platform** | Works on Linux, Android, iOS, Windows |
| **Offline Capable** | Works on local network without internet |
| **Standard Protocol** | Well-established, widely supported |

### ❌ Disadvantages of Zeroconf

| Disadvantage | Description | Mitigation |
|--------------|-------------|------------|
| **Limited to Local Network** | Only works on same subnet | Use VPN for remote access |
| **Multicast Traffic** | Can generate network traffic | Use with small networks (<50 devices) |
| **No Built-in Security** | Discovery is unauthenticated | Combine with JWT + TLS |
| **Name Conflicts** | Two devices same name possible | Use unique UUIDs in names |
| **Discovery Delay** | May take 1-5 seconds | Cache results, show "discovering" |
| **Router Issues** | Some routers block mDNS | Configure router or use unicast fallback |

---

## IP Address Changes Handling

This is a critical advantage of Zeroconf over static IPs or manual configuration.

### What Happens When Rover IP Changes

```
┌─────────────────────────────────────────────────────────────────────────┐
│              IP CHANGE HANDLING SCENARIOS                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  SCENARIO 1: DHCP Lease Renewal (Most Common)                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Rover: 192.168.1.100 → Router assigns new IP: 192.168.1.105   │    │
│  │                                                                  │    │
│  │ 1. Network stack gets new IP                                    │    │
│  │ 2. Rover re-announces mDNS service with new IP                  │    │
│  │ 3. Client receives "service updated" callback                  │    │
│  │ 4. Client automatically reconnects to new IP                   │    │
│  │ 5. User sees "reconnected" notification                         │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  SCENARIO 2: Rover Reboot                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Rover restarts, gets potentially different IP                  │    │
│  │                                                                  │    │
│  │ 1. Rover boots → gets IP from DHCP                              │    │
│  │ 2. Rover starts mDNS service                                    │    │
│  │ 3. Client browser picks up new service                          │    │
│  │ 4. Shows rover as "online" in list                              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  SCENARIO 3: Network Switch/Change                                      │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Rover moves to different WiFi network                          │    │
│  │                                                                  │    │
│  │ 1. Rover connects to new network                                │    │
│  │ 2. Rover announces on new network                               │    │
│  │ 3. Client on new network discovers rover                        │    │
│  │ 4. Client on old network removes rover (timeout)               │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Implementation for IP Change Handling

```python
# On Rover: Re-announce on any network change
import socket
import threading
from zeroconf import Zeroconf, ServiceInfo, ServiceListener

class RoverZeroconfService:
    def __init__(self, rover_name: str, port: int, uuid: str):
        self.rover_name = rover_name
        self.port = port
        self.uuid = uuid
        self.zeroconf = None
        self.service_name = f"{rover_name}._rovercontrol._tcp.local."
        
    def start(self):
        """Start Zeroconf service advertisement"""
        self.zeroconf = Zeroconf()
        
        # Get current IP
        ip = self._get_local_ip()
        
        # Create service info
        service_info = ServiceInfo(
            "_rovercontrol._tcp.local.",
            self.service_name,
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={
                b"version": b"1.0",
                b"uuid": self.uuid.encode(),
                b"auth_required": b"true",
                b"features": b"telemetry,camera,mission"
            },
            server=f"{self.rover_name}.local."
        )
        
        self.zeroconf.register_service(service_info)
        print(f"📡 Zeroconf: Advertising {self.service_name} on {ip}:{self.port}")
        
    def _get_local_ip(self) -> str:
        """Get local IP address"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
        
    def handle_network_change(self):
        """Called when network configuration changes"""
        print("🔄 Network changed, re-advertising...")
        
        # Unregister old service
        if self.zeroconf:
            self.zeroconf.unregister_service(self.service_info)
            
        # Re-register with new IP
        self.start()
        
    def stop(self):
        """Stop Zeroconf service"""
        if self.zeroconf:
            self.zeroconf.unregister_all_services()
            self.zeroconf.close()
```

---

## Security Considerations

### Security Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SECURITY LAYERS                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Layer 1: Network Isolation                                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ • Separate WiFi network (VLAN)                                  │    │
│  │ • WPA2/WPA3 encryption                                          │    │
│  │ • Firewall blocks external access                               │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  Layer 2: Service Discovery Authentication                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ • TXT records can include auth tokens                           │    │
│  │ • Client verifies service via TLS certificate                  │    │
│  │ • Rover validates client before accepting connection           │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  Layer 3: Connection Security                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ • TLS/SSL encryption on Socket.IO                               │    │
│  │ • JWT token authentication                                      │    │
│  │ • Certificate pinning in client app                            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  Layer 4: Command Authorization                                        │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ • JWT contains allowed_rovers list                              │    │
│  │ • Per-command permission checking                               │    │
│  │ • Rate limiting to prevent attacks                             │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Secure Service Announcement

```python
# Rover: Include security token in TXT records
# Only clients with this token can attempt connection
properties = {
    b"version": b"1.0",
    b"uuid": rover_uuid.encode(),
    b"auth_required": b"true",
    b"features": b"telemetry,camera,mission",
    b"token_hash": hash_rover_token()  # Hash for verification
}
```

---

## Implementation Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ROVER DISCOVERY SYSTEM                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ROVER (Jetson Nano/Xavier)                                            │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Python Service: rover_server                                   │    │
│  │  ├── Flask + Socket.IO server (port 5001)                      │    │
│  │  ├── Zeroconf service advertiser                                │    │
│  │  ├── JWT validator                                               │    │
│  │  └── Network change monitor                                     │    │
│  │                                                                  │    │
│  │  Dependencies:                                                   │    │
│  │  pip install zeroconf flask-socketio python-socketio           │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  mDNS Service: rover-001._rovercontrol._tcp.local              │    │
│  │  Port: 5001 (Socket.IO)                                         │    │
│  │  TXT: {version, uuid, auth_required, features}                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  CLIENT (Tablet/Phone/Web)                                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Discovery Library: zeroconf (Python) / mdns (Flutter)         │    │
│  │  ├── Service browser                                            │    │
│  │  ├── Service resolver                                           │    │
│  │  └── Connection manager                                          │    │
│  │                                                                  │    │
│  │  Flow:                                                           │    │
│  │  1. Browse _rovercontrol._tcp.local                             │    │
│  │  2. Get rover list with IPs                                      │    │
│  │  3. User selects rover                                           │    │
│  │  4. Connect via Socket.IO + JWT                                 │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  AUTH SERVER (Optional - Cloud/Router)                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  JWT validation endpoint                                        │    │
│  │  /auth/validate (rover calls this)                              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Rover-Side Implementation (Jetson)

### Step 1: Install Dependencies

```bash
# On Jetson
pip install zeroconf
```

### Step 2: Create Zeroconf Service Module

Create file: `Backend/zeroconf_service.py`

```python
"""
Zeroconf Service Advertisement for Rover
Publishes _rovercontrol._tcp.local for automatic discovery
"""

import socket
import threading
import logging
import network
from typing import Optional
from zeroconf import Zeroconf, ServiceInfo, ServiceListener

logger = logging.getLogger(__name__)


class Rover ZeroconfService:
    """Advertises rover service via mDNS/DNS-SD"""
    
    SERVICE_TYPE = "_rovercontrol._tcp.local."
    
    def __init__(
        self,
        rover_name: str,
        port: int,
        uuid: str,
        version: str = "1.0",
        features: list = None
    ):
        self.rover_name = rover_name
        self.port = port
        self.uuid = uuid
        self.version = version
        self.features = features or ["telemetry", "camera", "mission"]
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None
        self._running = False
        
    @property
    def service_name(self) -> str:
        return f"{self.rover_name}.{self.SERVICE_TYPE}"
    
    def get_local_ip(self) -> str:
        """Get the local IP address of the rover"""
        try:
            # Connect to external address to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            logger.error(f"Failed to get local IP: {e}")
            return "127.0.0.1"
    
    def start(self):
        """Start advertising the rover service"""
        if self._running:
            logger.warning("Zeroconf service already running")
            return
            
        try:
            self.zeroconf = Zeroconf()
            self._running = True
            
            # Get current IP
            ip = self.get_local_ip()
            logger.info(f"Starting Zeroconf service: {self.rover_name} at {ip}:{self.port}")
            
            # Create TXT record properties
            properties = {
                "version": self.version,
                "uuid": self.uuid,
                "auth_required": "true",
                "features": ",".join(self.features),
                "port": str(self.port)
            }
            
            # Convert to bytes for TXT records
            txt_properties = {k.encode(): v.encode() for k, v in properties.items()}
            
            # Create service info
            self.service_info = ServiceInfo(
                self.SERVICE_TYPE,
                self.service_name,
                addresses=[socket.inet_aton(ip)],
                port=self.port,
                properties=txt_properties,
                server=f"{self.rover_name}.local."
            )
            
            # Register service
            self.zeroconf.register_service(self.service_info)
            logger.info(f"✅ Zeroconf: Advertising {self.service_name}")
            
            # Start network change monitor
            self._start_network_monitor()
            
        except Exception as e:
            logger.error(f"Failed to start Zeroconf service: {e}")
            self._running = False
    
    def stop(self):
        """Stop advertising the rover service"""
        if not self._running:
            return
            
        try:
            if self.zeroconf and self.service_info:
                self.zeroconf.unregister_service(self.service_info)
                logger.info("Zeroconf service unregistered")
            
            if self.zeroconf:
                self.zeroconf.close()
                self.zeroconf = None
                
            self._running = False
            logger.info("Zeroconf service stopped")
            
        except Exception as e:
            logger.error(f"Error stopping Zeroconf service: {e}")
    
    def update_service(self):
        """Update service info (e.g., after IP change)"""
        if not self._running:
            return
            
        try:
            # Unregister old service
            if self.service_info:
                self.zeroconf.unregister_service(self.service_info)
            
            # Get new IP and re-register
            ip = self.get_local_ip()
            
            properties = {
                "version": self.version,
                "uuid": self.uuid,
                "auth_required": "true",
                "features": ",".join(self.features),
                "port": str(self.port)
            }
            txt_properties = {k.encode(): v.encode() for k, v in properties.items()}
            
            self.service_info = ServiceInfo(
                self.SERVICE_TYPE,
                self.service_name,
                addresses=[socket.inet_aton(ip)],
                port=self.port,
                properties=txt_properties,
                server=f"{self.rover_name}.local."
            )
            
            self.zeroconf.register_service(self.service_info)
            logger.info(f"🔄 Zeroconf service updated: {ip}:{self.port}")
            
        except Exception as e:
            logger.error(f"Failed to update Zeroconf service: {e}")
    
    def _start_network_monitor(self):
        """Monitor for network changes and update service"""
        def monitor():
            last_ip = self.get_local_ip()
            while self._running:
                try:
                    current_ip = self.get_local_ip()
                    if current_ip != last_ip:
                        logger.info(f"Network change detected: {last_ip} -> {current_ip}")
                        self.update_service()
                        last_ip = current_ip
                except Exception as e:
                    logger.error(f"Network monitor error: {e}")
                threading.Event().wait(5)  # Check every 5 seconds
        
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
    
    def get_discovery_info(self) -> dict:
        """Get current discovery info"""
        return {
            "name": self.rover_name,
            "host": f"{self.rover_name}.local",
            "ip": self.get_local_ip(),
            "port": self.port,
            "uuid": self.uuid,
            "version": self.version,
            "features": self.features
        }


class RoverServiceListener(ServiceListener):
    """Listener for discovering other rovers (for multi-rover control)"""
    
    def __init__(self, on_rover_found=None, on_rover_lost=None):
        self.on_rover_found = on_rover_found
        self.on_rover_lost = on_rover_lost
        self.rovers = {}
    
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        logger.info(f"Service added: {name}")
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        logger.info(f"Service removed: {name}")
        if name in self.rovers:
            rover = self.rovers.pop(name)
            if self.on_rover_lost:
                self.on_rover_lost(rover)
    
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        logger.info(f"Service updated: {name}")
```

### Step 3: Integrate with Server

Modify `Backend/server.py` to include Zeroconf:

```python
# Add to imports
from zeroconf_service import Rover ZeroconfService

# Add to your Flask-SocketIO server class
class RoverServer:
    def __init__(self, config):
        # ... existing init code ...
        
        # Initialize Zeroconf service
        self.zeroconf_service = Rover ZeroconfService(
            rover_name=config.get('rover_name', 'rover-001'),
            port=config.get('socket_port', 5001),
            uuid=config.get('rover_uuid', 'default-uuid'),
            version=config.get('version', '1.0'),
            features=config.get('features', ['telemetry', 'camera', 'mission'])
        )
    
    def start(self):
        """Start the rover server"""
        # ... existing startup code ...
        
        # Start Zeroconf service
        self.zeroconf_service.start()
        logger.info("🚀 Rover server started with Zeroconf discovery")
    
    def stop(self):
        """Stop the rover server"""
        # ... existing shutdown code ...
        
        # Stop Zeroconf service
        self.zeroconf_service.stop()
```

---

## Client-Side Implementation (Tablet/App)

### Python Client (Web Interface)

```python
# For web interface using JavaScript/browser
# Use bonjour.js or similar JavaScript library

# Example: Using zeroconf in Python client
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

class RoverDiscoveryClient:
    """Discovers rovers on the local network"""
    
    SERVICE_TYPE = "_rovercontrol._tcp.local."
    
    def __init__(self):
        self.zeroconf = None
        self.browser = None
        self.rovers = {}  # {name: {ip, port, uuid, version, features}}
        self.listener = RoverDiscoveryListener(self.rovers)
    
    def start_discovery(self):
        """Start browsing for rovers"""
        self.zeroconf = Zeroconf()
        self.browser = ServiceBrowser(
            self.zeroconf,
            self.SERVICE_TYPE,
            self.listener
        )
        print("🔍 Searching for rovers...")
    
    def stop_discovery(self):
        """Stop browsing"""
        if self.zeroconf:
            self.zeroconf.close()
    
    def get_rovers(self) -> list:
        """Get list of discovered rovers"""
        return [
            {
                "name": name,
                "ip": info.get("addresses", [""])[0] if info.get("addresses") else None,
                "port": info.get("port"),
                "uuid": info.get("properties", {}).get("uuid"),
                "version": info.get("properties", {}).get("version"),
                "features": info.get("properties", {}).get("features", "").split(","),
                "address": f"{info.get('addresses', [''])[0]}:{info.get('port')}" if info.get("addresses") else None
            }
            for name, info in self.rovers.items()
        ]


class RoverDiscoveryListener(ServiceListener):
    """Listener for rover discovery"""
    
    def __init__(self, rovers: dict):
        self.rovers = rovers
    
    def add_service(self, zc: Zeroconf, type_: str, name: str):
        info = zc.get_service_info(type_, name)
        if info:
            properties = {k.decode(): v.decode() for k, v in info.properties.items()}
            self.rovers[name] = {
                "name": name.replace(f".{type_}", ""),
                "addresses": [socket.inet_ntoa(addr) for addr in info.addresses],
                "port": info.port,
                "properties": properties
            }
            print(f"✅ Rover found: {name}")
            print(f"   IP: {self.rovers[name]['addresses']}")
            print(f"   Port: {info.port}")
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str):
        if name in self.rovers:
            del self.rovers[name]
            print(f"❌ Rover lost: {name}")
    
    def update_service(self, zc: Zeroconf, type_: str, name: str):
        # Re-add to update info
        self.add_service(zc, type_, name)
```

### JavaScript Client (Web Browser)

For web browsers, use `bonjour.js` or similar:

```javascript
// In web application
const bonjour = require('bonjour')({ mdns: true });

// Browse for rovers
const browser = bonjour.find({ type: 'rovercontrol', protocol: 'tcp' });

browser.on('up', service => {
    console.log('Rover found:', service.name);
    console.log('IP:', service.addresses[0]);
    console.log('Port:', service.port);
    console.log('Properties:', service.txt);
    
    // Add to rover list
    rovers.push({
        name: service.name,
        ip: service.addresses[0],
        port: service.port,
        uuid: service.txt.uuid,
        features: service.txt.features.split(',')
    });
});

browser.on('down', service => {
    // Remove from rover list
    const index = rovers.findIndex(r => r.name === service.name);
    if (index > -1) {
        rovers.splice(index, 1);
    }
});
```

### Flutter Client (Mobile App)

```dart
// Flutter using mdns package
import 'package:mdns/mdns.dart';

class RoverDiscoveryService {
  late ServiceBrowser _browser;
  final List<Rover> _rovers = [];
  
  Future<void> startDiscovery() async {
    _browser = ServiceBrowser('_rovercontrol._tcp.local');
    
    _browser.onServiceAdded.listen((Service service) {
      print('Rover found: ${service.name}');
      _resolveService(service);
    });
    
    _browser.onServiceRemoved.listen((Service service) {
      _rovers.removeWhere((r) => r.name == service.name);
    });
  }
  
  void _resolveService(Service service) async {
    final ip = await service.ip;
    final port = service.port;
    
    _rovers.add(Rover(
      name: service.name,
      ip: ip,
      port: port,
      uuid: service.txt['uuid'],
      features: service.txt['features']?.split(',') ?? [],
    ));
  }
}
```

---

## Integration with Authentication

### Complete Discovery + Auth Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│              COMPLETE DISCOVERY & AUTH FLOW                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. OPERATOR LOGS IN                                                    │
│     ┌──────────────────┐                                                │
│     │  Auth Server     │                                                │
│     │  (Cloud/Router)  │                                                │
│     └────────┬─────────┘                                                │
│              │ Returns:                                                 │
│              │ JWT token + rover list                                   │
│              ↓                                                          │
│     ┌──────────────────┐                                                │
│     │  Operator App    │                                                │
│     └────────┬─────────┘                                                │
│              │ Start Zeroconf discovery                                 │
│              ↓                                                          │
│  2. DISCOVER ROVERS                                                      │
│     ┌──────────────────┐                                                │
│     │  mDNS Query      │                                                │
│     │  _rovercontrol   │                                                │
│     └────────┬─────────┘                                                │
│              │ Returns:                                                  │
│              │ [rover-001, rover-002, ...]                              │
│              ↓                                                          │
│     ┌──────────────────┐                                                │
│     │  Filter by JWT   │  Only show rovers user has access to          │
│     │  allowed_rovers   │                                                │
│     └────────┬─────────┘                                                │
│              │                                                          │
│  3. SELECT ROVER                                                        │
│              ↓                                                          │
│  4. CONNECT                                                             │
│     ┌──────────────────┐                                                │
│     │  Socket.IO       │  Connect to discovered IP                     │
│     │  + TLS           │                                                │
│     └────────┬─────────┘                                                │
│              │ Send JWT                                                 │
│              ↓                                                          │
│  5. VALIDATE                                                            │
│     ┌──────────────────┐                                                │
│     │  Rover validates │  Validate JWT with auth server                │
│     │  JWT + Token     │  Or use cached validation                     │
│     └────────┬─────────┘                                                │
│              │ Success: Allow commands                                   │
│              ↓                                                          │
│  6. CONTROL                                                             │
│     ┌──────────────────┐                                                │
│     │  Socket.IO cmds  │  move, stop, mission, etc.                     │
│     └──────────────────┘                                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### JWT Integration

```python
# In server.py - JWT validation
from flask_socketio import emit, disconnect
from functools import wraps
import jwt

# Configuration
JWT_SECRET = "your-secret-key"
AUTH_SERVER_URL = "http://auth-server:8080"

def require_auth(f):
    """Decorator to require JWT authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not token:
            emit('error', {'message': 'No token provided'})
            disconnect()
            return
            
        try:
            # Verify JWT
            # Option 1: Verify locally (if you have the secret)
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            
            # Option 2: Verify with auth server (more secure)
            # payload = verify_with_auth_server(token)
            
            # Check if user has access to this rover
            allowed = payload.get('allowed_rovers', [])
            if config['rover_uuid'] not in allowed and 'admin' not in payload.get('role', []):
                emit('error', {'message': 'Access denied to this rover'})
                disconnect()
                return
                
            # Store user info in session
            g.user_id = payload['user_id']
            g.user_role = payload['role']
            
        except jwt.ExpiredSignatureError:
            emit('error', {'message': 'Token expired'})
            disconnect()
        except jwt.InvalidTokenError:
            emit('error', {'message': 'Invalid token'})
            disconnect()
            
        return f(*args, **kwargs)
    return decorated

# Apply to Socket.IO events
@socketio.on('move')
@require_auth
def handle_move(data):
    # Process move command
    pass
```

---

## Testing & Deployment

### Testing Checklist

```bash
# 1. Test Zeroconf service on rover
cd /home/flash/NRP_ROS/Backend

# Start server (should auto-advertise)
python server.py

# Check if service is advertised
# On same network, run:
avahi-resolve -n rover-001.local --address
# Should return: rover-001.local    192.168.x.x

# Browse for services
avahi-browse -r _rovercontrol._tcp.local

# 2. Test discovery from client
python -c "
from zeroconf_service import RoverDiscoveryClient
client = RoverDiscoveryClient()
client.start_discovery()
import time
time.sleep(5)
print('Found rovers:', client.get_rovers())
client.stop_discovery()
"

# 3. Test IP change handling
# - Change router DHCP settings
# - Reconnect rover to different network
# - Check if discovery still works

# 4. Test authentication flow
# - Start server
# - Connect with invalid JWT → should fail
# - Connect with valid JWT → should succeed
```

### Production Deployment

```bash
# On Jetson - Install dependencies
pip install zeroconf

# Start server (Zeroconf will auto-start)
sudo systemctl restart nrp-service

# Verify Zeroconf is running
avahi-browse -r _rovercontrol._tcp.local

# Check logs
journalctl -u nrp-service -f
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Rover not discovered | mDNS blocked by firewall | Open port 5353 (UDP) |
| Discovery slow | Network congestion | Reduce discovery frequency |
| Name conflict | Duplicate rover names | Use unique UUIDs in names |
| IP not updating | Network monitor failed | Restart service |
| Cross-network discovery | mDNS doesn't route | Use service discovery server |

### Debug Commands

```bash
# Check if avahi-daemon is running
systemctl status avahi-daemon

# Manually resolve a service
avahi-resolve -n "rover-001._rovercontrol._tcp.local" --service

# View all services on network
avahi-browse -a

# Check network interfaces
ip addr show

# Monitor mDNS traffic
sudo tcpdump -i eth0 port 5353
```

---

## Summary

Zeroconf provides an excellent solution for rover discovery:

✅ **Automatic**: No manual IP configuration needed  
✅ **Resilient**: Handles IP changes automatically  
✅ **Standard**: Works across all platforms  
✅ **Fast**: Discovery in 1-5 seconds  
✅ **Secure**: Combined with JWT + TLS  

**Best for**: Local network operations where rovers may change IPs (DHCP) or move between networks.

**Considerations**: 
- Requires all devices on same local network
- May need router configuration for best results
- Always combine with TLS + JWT for security

---

*Document Version: 1.0*  
*Last Updated: 2026-03-09*  
*Part of: NRP_ROS Security Architecture*
