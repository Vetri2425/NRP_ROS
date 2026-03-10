# 🔗 TTS Backend Endpoints - Quick Reference Guide

## ✅ Status: All Endpoints Working

---

## 📍 Quick Test Commands

### Check TTS Status
```bash
curl http://localhost:5001/api/tts/status
```

### Enable TTS
```bash
curl -X POST http://localhost:5001/api/tts/control \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

### Disable TTS
```bash
curl -X POST http://localhost:5001/api/tts/control \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### Test TTS Voice
```bash
curl -X POST http://localhost:5001/api/tts/test \
  -H "Content-Type: application/json" \
  -d '{"message": "Test voice output"}'
```

### Run Complete Endpoint Test
```bash
python3 test_endpoints_complete.py
```

---

## 📊 Endpoint Reference Table

| Endpoint | Method | Purpose | Status |
|----------|--------|---------|--------|
| `/api/tts/status` | GET | Get TTS configuration | ✅ Working |
| `/api/tts/control` | POST | Enable/disable TTS | ✅ Working |
| `/api/tts/test` | POST | Test voice output | ✅ Working |

---

## 📋 Response Examples

### GET /api/tts/status
```json
{
  "success": true,
  "enabled": false,
  "engine": "espeak",
  "language": "en",
  "bluetooth_warmup_enabled": true
}
```

### POST /api/tts/control (Request)
```json
{
  "enabled": true
}
```

### POST /api/tts/control (Response)
```json
{
  "success": true,
  "enabled": true,
  "message": "TTS voice output enabled"
}
```

### POST /api/tts/test (Request)
```json
{
  "message": "Backend test successful"
}
```

### POST /api/tts/test (Response)
```json
{
  "success": true,
  "message": "TTS test message queued"
}
```

---

## 🔧 Configuration

| Variable | Current Value | Purpose |
|----------|---------------|---------|
| `BACKEND_HOST` | localhost | Server hostname |
| `BACKEND_PORT` | 5001 | Server port |
| `BACKEND_URL` | http://localhost:5001 | Full backend URL |
| `NRP_TTS_ENABLE` | true/false | TTS enable flag |
| `JARVIS_LANG` | en | Language (en/hi/ta) |
| `NRP_TTS_BT_WARMUP` | true | Bluetooth warmup |

---

## 💻 Frontend Integration

### React Example
```typescript
const getTTSStatus = async () => {
  const response = await fetch('http://localhost:5001/api/tts/status');
  return await response.json();
};

const toggleTTS = async (enabled: boolean) => {
  const response = await fetch('http://localhost:5001/api/tts/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled })
  });
  return await response.json();
};

const testTTS = async (message: string) => {
  const response = await fetch('http://localhost:5001/api/tts/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });
  return await response.json();
};
```

---

## 🛟 Troubleshooting

### Backend Not Running?
```bash
ps aux | grep server.py
# If not running, start it:
python Backend/server.py
```

### Connection Refused?
- Check backend is running
- Verify port 5001 is open
- Check firewall settings

### 500 Error?
- Check backend logs
- Verify environment variables
- Restart backend service

---

## ✨ Verification Results (Latest)

```
Date: 2025-12-16
Time: 12:45:19 UTC
Total Tests: 4
Passed: 4/4 (100%)
Status: ✅ ALL WORKING
```

Test tool: `test_endpoints_complete.py`

---

**Ready for production integration!** 🚀
