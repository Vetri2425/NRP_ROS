# RTK API Endpoints - Frontend Integration Guide

## Overview
Complete REST API documentation for RTK corrections management (NTRIP and LoRa sources).

**Base URL**: `http://YOUR_ROVER_IP:5000`

---

## 📡 NTRIP RTK Endpoints

### 1. Start NTRIP Stream
**Endpoint**: `POST /api/rtk/ntrip_start`

**Description**: Initiates RTK corrections from an NTRIP caster server.

**Request Headers**:
```
Content-Type: application/json
```

**Request Body** (Option 1 - NTRIP URL):
```json
{
  "ntrip_url": "rtcm://username:password@caster.host.com:2101/MOUNTPOINT"
}
```

**Request Body** (Option 2 - Individual Parameters):
```json
{
  "host": "caster.host.com",
  "port": 2101,
  "mountpoint": "MOUNTPOINT",
  "user": "username",
  "password": "password"
}
```

**Success Response** (200):
```json
{
  "success": true,
  "message": "NTRIP RTK stream started from caster.host.com:2101/MOUNTPOINT",
  "source": "NTRIP",
  "caster": {
    "host": "caster.host.com",
    "port": 2101,
    "mountpoint": "MOUNTPOINT",
    "user": "username",
    "password": "password"
  }
}
```

**Error Response** (409 - Conflict):
```json
{
  "success": false,
  "message": "LoRa RTK stream is active. Please stop it first.",
  "source": "NTRIP"
}
```

**Error Response** (400 - Bad Request):
```json
{
  "success": false,
  "message": "Missing required parameters: host and mountpoint",
  "source": "NTRIP"
}
```

**Frontend Example** (React/TypeScript):
```typescript
const startNTRIPStream = async () => {
  try {
    const response = await fetch('http://192.168.1.100:5000/api/rtk/ntrip_start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: 'caster.example.com',
        port: 2101,
        mountpoint: 'RTCM3',
        user: 'myuser',
        password: 'mypass'
      })
    });

    const data = await response.json();
    if (data.success) {
      console.log('NTRIP started:', data.message);
    } else {
      console.error('Failed:', data.message);
    }
  } catch (error) {
    console.error('Request failed:', error);
  }
};
```

---

### 2. Stop NTRIP Stream
**Endpoint**: `POST /api/rtk/ntrip_stop`

**Description**: Stops the NTRIP RTK corrections stream.

**Request**: No body required

**Success Response** (200):
```json
{
  "success": true,
  "message": "NTRIP RTK stream stopped successfully",
  "source": "NTRIP"
}
```

**Already Stopped Response** (200):
```json
{
  "success": true,
  "message": "NTRIP RTK stream was not running",
  "source": "NTRIP"
}
```

**Frontend Example**:
```typescript
const stopNTRIPStream = async () => {
  const response = await fetch('http://192.168.1.100:5000/api/rtk/ntrip_stop', {
    method: 'POST'
  });
  const data = await response.json();
  console.log(data.message);
};
```

---

## 📻 LoRa RTK Endpoints

### 3. Start LoRa Stream
**Endpoint**: `POST /api/rtk/lora_start`

**Description**: Starts receiving RTK corrections via LoRa USB receiver.

**Request**: No body required

**Success Response** (200):
```json
{
  "success": true,
  "message": "LoRa RTK stream started successfully",
  "source": "LoRa",
  "status": {
    "is_connected": true,
    "is_running": true,
    "status_message": "Streaming",
    "messages_received": 0,
    "bytes_received": 0,
    "error_count": 0,
    "connection_time": "2025-12-18T13:00:00.000000",
    "uptime_seconds": 0
  }
}
```

**Error Response** (409 - Conflict):
```json
{
  "success": false,
  "message": "NTRIP RTK stream is active. Please stop it first.",
  "source": "LoRa"
}
```

**Error Response** (500 - Hardware Error):
```json
{
  "success": false,
  "message": "Failed to connect to LoRa receiver",
  "source": "LoRa"
}
```

**Frontend Example**:
```typescript
const startLoRaStream = async () => {
  try {
    const response = await fetch('http://192.168.1.100:5000/api/rtk/lora_start', {
      method: 'POST'
    });

    const data = await response.json();
    if (data.success) {
      console.log('LoRa started:', data.status);
    } else {
      alert(`Failed: ${data.message}`);
    }
  } catch (error) {
    console.error('Request failed:', error);
  }
};
```

---

### 4. Stop LoRa Stream
**Endpoint**: `POST /api/rtk/lora_stop`

**Description**: Stops the LoRa RTK corrections stream.

**Request**: No body required

**Success Response** (200):
```json
{
  "success": true,
  "message": "LoRa RTK stream stopped successfully",
  "source": "LoRa"
}
```

**Error Response** (500 - Internal Error):
```json
{
  "success": false,
  "message": "Failed to stop LoRa stream: USB device error",
  "source": "LoRa"
}
```

**Frontend Example**:
```typescript
const stopLoRaStream = async () => {
  const response = await fetch('http://192.168.1.100:5000/api/rtk/lora_stop', {
    method: 'POST'
  });
  const data = await response.json();
  console.log(data.message);
};
```

---

## 🔄 Unified Control Endpoints

### 5. Stop All RTK Streams
**Endpoint**: `POST /api/rtk/stop`

**Description**: Stops both NTRIP and LoRa streams simultaneously.

**Request**: No body required

**Success Response** (200):
```json
{
  "success": true,
  "message": "RTK stream(s) stopped: NTRIP, LoRa"
}
```

**Frontend Example**:
```typescript
const stopAllRTKStreams = async () => {
  const response = await fetch('http://192.168.1.100:5000/api/rtk/stop', {
    method: 'POST'
  });
  const data = await response.json();
  console.log(data.message);
};
```

---

### 6. Get RTK Status
**Endpoint**: `GET /api/rtk/status`

**Description**: Retrieves current status of both NTRIP and LoRa RTK streams.

**Request**: No parameters required

**Success Response** (200):
```json
{
  "success": true,
  "ntrip": {
    "running": true,
    "caster": {
      "host": "caster.example.com",
      "port": 2101,
      "mountpoint": "RTCM3",
      "user": "myuser",
      "password": "mypass"
    },
    "total_bytes": 245678
  },
  "lora": {
    "running": false,
    "status": null
  }
}
```

**Response When LoRa is Active**:
```json
{
  "success": true,
  "ntrip": {
    "running": false,
    "caster": null,
    "total_bytes": 0
  },
  "lora": {
    "running": true,
    "status": {
      "is_connected": true,
      "is_running": true,
      "status_message": "Streaming",
      "messages_received": 152,
      "bytes_received": 45632,
      "error_count": 0,
      "connection_time": "2025-12-18T13:00:00.000000",
      "uptime_seconds": 120.5
    }
  }
}
```

**Frontend Example**:
```typescript
const getRTKStatus = async () => {
  const response = await fetch('http://192.168.1.100:5000/api/rtk/status');
  const data = await response.json();

  if (data.ntrip.running) {
    console.log('NTRIP active:', data.ntrip.caster);
  }

  if (data.lora.running) {
    console.log('LoRa active:', data.lora.status);
  }
};
```

---

## 🎯 Complete React Component Example

```typescript
import React, { useState, useEffect } from 'react';

const RTKControl: React.FC = () => {
  const [status, setStatus] = useState<any>(null);
  const BASE_URL = 'http://192.168.1.100:5000';

  // Poll status every 2 seconds
  useEffect(() => {
    const interval = setInterval(async () => {
      const response = await fetch(`${BASE_URL}/api/rtk/status`);
      const data = await response.json();
      setStatus(data);
    }, 2000);

    return () => clearInterval(interval);
  }, []);

  const startNTRIP = async () => {
    const response = await fetch(`${BASE_URL}/api/rtk/ntrip_start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: 'caster.example.com',
        port: 2101,
        mountpoint: 'RTCM3',
        user: 'user',
        password: 'pass'
      })
    });
    const data = await response.json();
    alert(data.message);
  };

  const stopNTRIP = async () => {
    const response = await fetch(`${BASE_URL}/api/rtk/ntrip_stop`, {
      method: 'POST'
    });
    const data = await response.json();
    alert(data.message);
  };

  const startLoRa = async () => {
    const response = await fetch(`${BASE_URL}/api/rtk/lora_start`, {
      method: 'POST'
    });
    const data = await response.json();
    alert(data.message);
  };

  const stopLoRa = async () => {
    const response = await fetch(`${BASE_URL}/api/rtk/lora_stop`, {
      method: 'POST'
    });
    const data = await response.json();
    alert(data.message);
  };

  const stopAll = async () => {
    const response = await fetch(`${BASE_URL}/api/rtk/stop`, {
      method: 'POST'
    });
    const data = await response.json();
    alert(data.message);
  };

  return (
    <div className="rtk-control">
      <h2>RTK Control Panel</h2>

      {/* NTRIP Section */}
      <div className="section">
        <h3>NTRIP RTK</h3>
        <p>Status: {status?.ntrip.running ? '🟢 Running' : '🔴 Stopped'}</p>
        {status?.ntrip.running && (
          <p>Caster: {status.ntrip.caster?.host}:{status.ntrip.caster?.port}/{status.ntrip.caster?.mountpoint}</p>
        )}
        <button onClick={startNTRIP} disabled={status?.ntrip.running}>
          Start NTRIP
        </button>
        <button onClick={stopNTRIP} disabled={!status?.ntrip.running}>
          Stop NTRIP
        </button>
      </div>

      {/* LoRa Section */}
      <div className="section">
        <h3>LoRa RTK</h3>
        <p>Status: {status?.lora.running ? '🟢 Running' : '🔴 Stopped'}</p>
        {status?.lora.running && status?.lora.status && (
          <>
            <p>Messages: {status.lora.status.messages_received}</p>
            <p>Bytes: {status.lora.status.bytes_received}</p>
            <p>Errors: {status.lora.status.error_count}</p>
            <p>Uptime: {Math.floor(status.lora.status.uptime_seconds)}s</p>
          </>
        )}
        <button onClick={startLoRa} disabled={status?.lora.running}>
          Start LoRa
        </button>
        <button onClick={stopLoRa} disabled={!status?.lora.running}>
          Stop LoRa
        </button>
      </div>

      {/* Emergency Stop */}
      <div className="section">
        <button onClick={stopAll} className="emergency">
          🛑 Stop All RTK Streams
        </button>
      </div>
    </div>
  );
};

export default RTKControl;
```

---

## ⚙️ API Behavior Rules

### Mutual Exclusivity
- **NTRIP and LoRa cannot run simultaneously**
- Starting one stream while the other is active returns HTTP 409 (Conflict)
- Use `/api/rtk/stop` to stop all streams before switching

### State Management
- `rtk_running` flag controls NTRIP stream
- `lora_rtk_source_active` flag controls LoRa stream
- Both flags are independent but mutually exclusive

### Error Handling
- **400**: Invalid parameters
- **409**: Conflict (stream already running)
- **500**: Hardware/internal server error

### GPS Fix Persistence
- Stopping RTK stream doesn't immediately clear GPS fix
- GPS retains RTK fix for 30-60 seconds using cached corrections
- `rtk_fix_type` will gradually degrade: 6→5→4→3→2

---

## 🧪 Testing Commands (cURL)

```bash
# Start NTRIP
curl -X POST http://192.168.1.100:5000/api/rtk/ntrip_start \
  -H "Content-Type: application/json" \
  -d '{"host":"caster.example.com","port":2101,"mountpoint":"RTCM3","user":"user","password":"pass"}'

# Stop NTRIP
curl -X POST http://192.168.1.100:5000/api/rtk/ntrip_stop

# Start LoRa
curl -X POST http://192.168.1.100:5000/api/rtk/lora_start

# Stop LoRa
curl -X POST http://192.168.1.100:5000/api/rtk/lora_stop

# Stop All
curl -X POST http://192.168.1.100:5000/api/rtk/stop

# Get Status
curl http://192.168.1.100:5000/api/rtk/status
```

---

## 📊 Status Polling Recommendation

Poll `/api/rtk/status` every **2-5 seconds** to keep UI synchronized with RTK state.

```typescript
// Polling example with React hooks
useEffect(() => {
  const pollInterval = setInterval(async () => {
    const response = await fetch(`${BASE_URL}/api/rtk/status`);
    const data = await response.json();
    setRTKStatus(data);
  }, 3000); // Poll every 3 seconds

  return () => clearInterval(pollInterval);
}, []);
```

---

## 🔐 CORS Configuration

If frontend is on different domain, ensure CORS is enabled in backend:

```python
# Backend server.py already has CORS enabled via flask-cors
# No additional configuration needed for same-network requests
```

---

## 📝 Notes

1. **Network Requirements**: Frontend must be on same network as rover
2. **USB Device**: LoRa requires CH340 USB device at `1a86:7523`
3. **Permissions**: No authentication required (local network only)
4. **Logging**: All endpoints log to systemd journal: `journalctl -u nrp-service -f`

---

**Last Updated**: 2025-12-18
**API Version**: 1.0
**Backend**: Flask + Socket.IO + PyUSB
