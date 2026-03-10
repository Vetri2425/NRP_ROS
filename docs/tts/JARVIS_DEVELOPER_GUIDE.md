# JARVIS Event-Type Quick Reference for Developers

**Purpose**: Guide for adding new mission events or modifying TTS announcements

---

## 🎯 How to Add a New Mission Event with TTS

### Step 1: Choose an Event Type
Use one of the 8 valid types, or propose a new one following the pattern `mission_*` or `waypoint_*`:

```
mission_loaded       → Mission file loaded and validated
mission_started      → Mission execution began
mission_completed    → All waypoints completed successfully
mission_error        → Mission-level error (bad file, GPS lost, etc)
waypoint_executing   → Started navigating to a waypoint
waypoint_reached     → Arrived at waypoint (within threshold)
waypoint_marked      → Waypoint marking action completed
waypoint_failed      → Waypoint navigation failed (timeout, obstacle, etc)
```

### Step 2: Add emit_status() Call with Event Type

In `Backend/integrated_mission_controller.py`:

```python
self.emit_status(
    "Human-readable message for logs",
    "success",  # or 'error', 'warning'
    extra_data={
        "event_type": "mission_loaded",  # ← REQUIRED
        "waypoints_count": 5,             # ← Event-specific data
        "mode": self.mission_mode.value,
    }
)
```

### Step 3: Add TTS Handler in server.py

In `Backend/server.py`, add a case in `handle_mission_status()`:

```python
elif event_type == 'mission_loaded':
    waypoints_count = extra_data.get('waypoints_count', total_wp)
    tts_msg = f"Waypoints loaded: {waypoints_count} waypoints"
    tts.speak(tts_msg)
    log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
```

---

## 🔧 How to Modify a TTS Announcement

**Wrong Way** (Don't do this):
```python
# ❌ This changes the mission controller, might break other code
self.emit_status(
    f"UPDATED: {count} waypoints ready"  # Message text change
)
```

**Right Way** (Do this):
```python
# ✅ Change the mission controller message (won't break TTS)
self.emit_status(
    f"Mission loaded: {count} waypoints ready",  # New message text
    "success",
    extra_data={"event_type": "mission_loaded", "waypoints_count": count}
)

# Then update TTS announcement in server.py (only place to change voice output)
elif event_type == 'mission_loaded':
    waypoints_count = extra_data.get('waypoints_count', total_wp)
    tts_msg = f"Ready to execute {waypoints_count} waypoints"  # ← New voice text
    tts.speak(tts_msg)
```

---

## 📋 Complete Example: Adding "Waypoint Skipped" Event

### 1. Add emit_status() in integrated_mission_controller.py

```python
def skip_waypoint(self) -> None:
    """Skip current waypoint and move to next"""
    self.current_waypoint_index += 1
    self.emit_status(
        f"Skipped waypoint {self.current_waypoint_index}",
        "info",
        extra_data={
            "event_type": "waypoint_skipped",  # New event type
            "skipped_waypoint": self.current_waypoint_index,
            "reason": "operator_request"
        }
    )
```

### 2. Add TTS case in server.py handle_mission_status()

```python
elif event_type == 'waypoint_skipped':
    skipped_wp = extra_data.get('skipped_waypoint', current_wp)
    reason = extra_data.get('reason', 'unknown')
    tts_msg = f"Skipped waypoint {skipped_wp}"
    tts.speak(tts_msg)
    log_message(f"TTS: {tts_msg}", "DEBUG", event_type='tts')
```

### 3. Add to Event Type List

Update documentation and comments to include `waypoint_skipped` in the list of valid event types.

---

## ✅ Testing Your New Event

### Unit Test Example

```python
def test_waypoint_skipped_event():
    """Verify waypoint_skipped event triggers TTS"""
    
    # Mock the TTS module
    with patch('server.tts.speak') as mock_speak:
        # Simulate the event
        status_data = {
            'message': 'Skipped waypoint 2',
            'level': 'info',
            'current_waypoint': 2,
            'total_waypoints': 5,
            'extra_data': {
                'event_type': 'waypoint_skipped',
                'skipped_waypoint': 2,
                'reason': 'operator_request'
            }
        }
        
        # Call the handler
        handle_mission_status(status_data)
        
        # Verify TTS was called
        mock_speak.assert_called_once_with("Skipped waypoint 2")
```

### Integration Test Example

```python
def test_full_mission_with_skip():
    """Test real mission flow including waypoint skip"""
    
    # Create mission with 3 waypoints
    mission = [...3 waypoints...]
    
    # Start mission
    mission_controller.load_mission(mission)
    mission_controller.start_mission()
    
    # Navigate to waypoint 1, then skip it
    # ...navigation logic...
    mission_controller.skip_waypoint()
    
    # Should announce "Skipped waypoint 1"
    # Verify in test output that TTS was triggered
```

---

## 🚫 Common Mistakes to Avoid

### ❌ Mistake #1: Using String Patterns for TTS
```python
# DON'T DO THIS:
if 'loaded' in message:
    tts.speak("Mission loaded")  # Fragile! String change breaks TTS
```

### ❌ Mistake #2: Embedding TTS in Mission Controller
```python
# DON'T DO THIS:
def load_mission(self):
    tts.speak("Mission loaded")  # Mixes concerns, hard to test
    self.emit_status("Mission loaded")
```

### ❌ Mistake #3: Forgetting extra_data
```python
# DON'T DO THIS:
self.emit_status("Mission loaded", "success")  # Missing event_type!

# DO THIS:
self.emit_status(
    "Mission loaded", "success",
    extra_data={"event_type": "mission_loaded"}
)
```

### ❌ Mistake #4: TTS Handler Without event_type Check
```python
# DON'T DO THIS (too broad):
elif message.startswith("Waypoint"):
    tts.speak(message)  # Triggers for ALL waypoint messages

# DO THIS (precise):
elif event_type == 'waypoint_executing':
    tts.speak(f"Going to waypoint {current_wp}")
```

---

## 📚 Key Files

| File | Purpose | What to Edit |
|------|---------|-------------|
| `Backend/integrated_mission_controller.py` | Mission state machine | Add `emit_status()` calls with event_type |
| `Backend/server.py` | TTS dispatch logic | Add event_type cases in `handle_mission_status()` |
| `test_tts_integration.py` | Integration tests | Add test cases for new events |
| `Backend/tts.py` | TTS engine | Usually no changes needed |

---

## 🔄 Event Type Naming Convention

Follow this pattern when creating new event types:

```
{subject}_{action}

subject = mission | waypoint | servo | gps | battery | etc
action   = loaded | started | reached | failed | completed | error | etc

Examples:
mission_loaded     ✅ Good
mission_error      ✅ Good
waypoint_reached   ✅ Good
waypoint_skipped   ✅ Good
servo_failed       ✅ Good
gps_lost           ✅ Good
bad_waypoint       ❌ Bad (unclear subject)
wp_ok              ❌ Bad (abbreviation, unclear action)
EVENT_1            ❌ Bad (not descriptive)
```

---

## 🎙️ TTS Announcement Guidelines

### Keep Announcements Concise
- ✅ "Waypoint 3 reached"
- ❌ "The rover has successfully navigated to and arrived at waypoint number three on the mission"

### Include Actionable Numbers
- ✅ "Waypoint 2 of 5"
- ❌ "Processing waypoint"

### Be Consistent
- ✅ Use same voice format: "Going to waypoint 1"
- ❌ Mix formats: "Going to waypoint 1" vs "Processing waypoint 2"

### Test with Bluetooth Speaker
- Bluetooth audio often has lower quality
- Slow speech rate (120 wpm) in tts.py is intentional
- Keep announcements under 10 words for clarity

---

## 🔍 Debugging Tips

### Check if Event Type is Being Sent
```bash
# View mission status in logs
grep "extra_data.*event_type" /tmp/nrp_ros.log

# Check TTS dispatch was triggered
grep "TTS:" /tmp/nrp_ros.log
```

### Manually Test TTS Handler
```python
# In Python REPL or test script
from Backend.server import handle_mission_status
from Backend import tts

# Simulate event
status_data = {
    'message': 'Test message',
    'level': 'info',
    'current_waypoint': 1,
    'total_waypoints': 3,
    'extra_data': {
        'event_type': 'waypoint_executing'
    }
}

# Call handler (should trigger TTS)
handle_mission_status(status_data)
```

### Verify Event Type Propagates
```bash
# Check WebSocket messages going to frontend
# Look in browser console network tab for Socket.IO messages
# Event type should be in 'extra_data' field
```

---

## 📞 Questions?

- **"How do I add TTS for a new robot action?"** → Follow the 3-step example above
- **"Can message text change without breaking TTS?"** → Yes! That's the whole point of this refactor
- **"What if I need to add a new event type?"** → Create new type, update documentation, add TTS handler case
- **"Can I disable TTS for an event?"** → Yes, just don't include the `tts.speak()` call

---

**Last Updated**: 2024  
**Refactor Version**: 1.0 (Event-Type Dispatch)  
**Status**: Production Ready ✅

