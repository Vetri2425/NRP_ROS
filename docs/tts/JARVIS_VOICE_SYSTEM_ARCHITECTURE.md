# Jarvis Voice System - Architecture & Data Flow

**Visual Reference for Understanding the System**

---

## SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS ROVER STACK                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  HARDWARE LAYER:                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   Pixhawk    │  │   Jetson     │  │  Bluetooth Speaker   │   │
│  │  (ArduRover) │  │  (ROS2 + Py) │  │   (HFP Audio)        │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│                                                 ▲                │
│  SOFTWARE LAYER:                                │                │
│  ┌──────────────────────────────────────────────┼────────────┐  │
│  │             JETSON COMPUTE                   │            │  │
│  │                                              │            │  │
│  │  ┌─────────────────────────────────────┐   │            │  │
│  │  │      Flask Backend Server           │   │            │  │
│  │  │  (Backend/server.py)                │   │            │  │
│  │  │                                     │   │            │  │
│  │  │  ┌──────────────────────────────┐  │   │            │  │
│  │  │  │ MissionController            │  │   │            │  │
│  │  │  │ (integrated_mission_         │  │   │            │  │
│  │  │  │  controller.py)              │  │   │            │  │
│  │  │  │                              │  │   │            │  │
│  │  │  │ • Load mission               │  │   │            │  │
│  │  │  │ • Execute waypoints          │  │   │            │  │
│  │  │  │ • Detect waypoint reached    │  │   │            │  │
│  │  │  │ • Execute servo              │  │   │            │  │
│  │  │  │ • Emit status (callbacks)    │  │   │            │  │
│  │  │  └─────────────┬────────────────┘  │   │            │  │
│  │  │                │ emit_status()     │   │            │  │
│  │  │                ▼                   │   │            │  │
│  │  │  ┌──────────────────────────────┐  │   │            │  │
│  │  │  │ handle_mission_status()      │  │   │            │  │
│  │  │  │                              │  │   │            │  │
│  │  │  │ • Extract event type         │  │   │            │  │
│  │  │  │ • Trigger TTS                │  │   │            │  │
│  │  │  │ • Log to journalctl          │  │   │            │  │
│  │  │  │ • Emit to frontend           │  │   │            │  │
│  │  │  └─────────────┬────────────────┘  │   │            │  │
│  │  │                │ tts.speak()       │   │            │  │
│  │  │                ▼                   │   │            │  │
│  │  │  ┌──────────────────────────────┐  │   │            │  │
│  │  │  │ TTS Module (tts.py)          │  │   │            │  │
│  │  │  │                              │  │   │            │  │
│  │  │  │  _worker: _TTSWorker         │  │   │            │  │
│  │  │  │  ├─ Thread (daemon)          │  │   │            │  │
│  │  │  │  ├─ Queue (text messages)    │  │   │            │  │
│  │  │  │  └─ Deduplication logic      │  │   │            │  │
│  │  │  │                              │  │   │            │  │
│  │  │  │  speak(text, async_=True)   │  │   │            │  │
│  │  │  │  ├─ Enqueue text             │  │   │            │  │
│  │  │  │  └─ Return immediately       │  │   │            │  │
│  │  │  └─────────────┬────────────────┘  │   │            │  │
│  │  │                │ Queue.put()       │   │            │  │
│  │  │                ▼                   │   │            │  │
│  │  │  ┌──────────────────────────────┐  │   │            │  │
│  │  │  │ Worker Thread _run()         │  │   │            │  │
│  │  │  │ (background/async)           │  │   │            │  │
│  │  │  │                              │  │   │            │  │
│  │  │  │ 1. Dequeue text              │  │   │            │  │
│  │  │  │ 2. Check should_speak()      │  │   │            │  │
│  │  │  │ 3. Warm up audio             │  │   │            │  │
│  │  │  │ 4. _speak_impl(text)         │  │   │            │  │
│  │  │  │ 5. Record last_spoken_*      │  │   │            │  │
│  │  │  │ 6. Sleep 0.5s                │  │   │            │  │
│  │  │  └─────────────┬────────────────┘  │   │            │  │
│  │  │                │                   │   │            │  │
│  │  │                ├─► _speak_espeak() │   │            │  │
│  │  │                │   └─► subprocess   │   │            │  │
│  │  │                │       espeak       │───┤            │  │
│  │  │                │                   │   │            │  │
│  │  │                └─► _speak_pyttsx3()│   │            │  │
│  │  │                    (fallback)      │   │            │  │
│  │  │                                    │   │            │  │
│  │  └────────────────────────────────────┘   │            │  │
│  │                                           │            │  │
│  └───────────────────────────────────────────┼────────────┘  │
│                                              │               │
│  COMMUNICATION LAYERS:                       │               │
│  • MAVROS ◄──────────► Pixhawk              │               │
│  • Flask-SocketIO ◄──► React Native GCS     │               │
│  • subprocess ◄───────► espeak binary       │               │
│  • Bluetooth ◄─────────────────────────────►┘               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## DATA FLOW: Mission Event → Voice Announcement

```
MISSION STATE CHANGE (Example: Waypoint Reached)
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ IntegratedMissionController.handle_pixhawk_waypoint_ │
│ reached(wp_seq=1)                                    │
│                                                      │
│ • Validate waypoint sequence                         │
│ • Set HOLD mode                                      │
│ • Call waypoint_reached()                            │
└─────────────────────┬────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────┐
│ self.emit_status(                                    │
│     "Waypoint 1 reached",                            │
│     "success",                                       │
│     extra_data={                                     │
│         "event_type": "waypoint_reached",  ◄─ KEY   │
│         "current_waypoint": 1,                       │
│         "total_waypoints": 3,                        │
│         ...                                          │
│     }                                                │
│ )                                                    │
└─────────────────────┬────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────┐
│ Flask callback: handle_mission_status(status_data)   │
│                                                      │
│ Extract:                                             │
│  • event_type = "waypoint_reached"                  │
│  • current_wp = 1                                   │
│  • total_wp = 3                                     │
│  • level = "success"                                │
└─────────────────────┬────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────┐
│ TTS TRIGGER (Structured Event Type Dispatch)         │
│                                                      │
│ if event_type == 'waypoint_reached':                │
│     tts.speak(f"Waypoint {current_wp} reached")    │
│                                                      │
│ ✓ Robust: No string pattern matching                │
│ ✓ Decoupled: Message text doesn't matter           │
│ ✓ Testable: Unit test with mocked status_data      │
└─────────────────────┬────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────┐
│ tts.speak("Waypoint 1 reached", async_=True)        │
│                                                      │
│ • Check if enabled (NRP_TTS_ENABLE env var)        │
│ • Enqueue message                                   │
│ • Return immediately (non-blocking)                │
└─────────────────────┬────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        │                           │
        ▼                           ▼
   [Main Thread]            [Worker Thread (background)]
   Returns to mission         │
   controller                 │
   (continues executing)      │
                              ▼
                    ┌──────────────────────┐
                    │ _run() loop          │
                    │                      │
                    │ Queue.get(timeout=0.5
                    │ → "Waypoint 1 reached"
                    │                      │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ _should_speak()      │
                    │                      │
                    │ • Check dedup        │
                    │ • Check min interval │
                    │ → True (OK to speak) │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ _warmup_audio()      │
                    │                      │
                    │ espeak -s 130 -a 50  │
                    │ " " (silent probe)   │
                    │                      │
                    │ [~300ms]             │
                    │ audio device ready   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ _speak_espeak()      │
                    │                      │
                    │ subprocess.run([     │
                    │   "espeak",          │
                    │   "-s", "120",       │
                    │   "-a", "200",       │
                    │   "-g", "15",        │
                    │   "-p", "50",        │
                    │   text               │
                    │ ])                   │
                    │                      │
                    │ [~2-3 seconds]       │
                    │ Bluetooth HFP        │
                    │ Speaker plays sound  │
                    │ [~500ms-1s latency]  │
                    │                      │
                    │ "Waypoint 1 reached" │
                    │ (heard by operator)  │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Update state:        │
                    │                      │
                    │ last_spoken_text =   │
                    │ "Waypoint 1 reached" │
                    │ last_spoken_at = now │
                    │                      │
                    │ Sleep(0.5s) for      │
                    │ audio clarity        │
                    │                      │
                    │ Loop back to        │
                    │ Queue.get()          │
                    └──────────────────────┘
```

---

## EVENT TYPE → TTS OUTPUT MAPPING

| Event Type | Trigger | TTS Output | Status |
|---|---|---|---|
| `mission_loaded` | `load_mission()` completes | "Waypoints loaded: N waypoints" | ✅ Implemented |
| `mission_started` | `start_mission()` called | "Mission started" | ✅ Implemented |
| `waypoint_executing` | `execute_current_waypoint()` | "Going to waypoint X of Y" | ✅ Implemented |
| `waypoint_reached` | Pixhawk topic or distance fallback | "Waypoint X reached" | ✅ Implemented |
| `waypoint_marked` | `hold_period_complete()` → servo executed | "Waypoint X marked complete" | ✅ Implemented |
| `waypoint_failed` | `waypoint_timeout()` triggered | "Waypoint X failed: timeout" | ✅ Implemented |
| `mission_completed` | All waypoints done | "Mission completed: X waypoints in Ys" | ✅ Implemented |
| `mission_error` | Exception in mission controller | "Error: [message]" | ✅ Implemented |

---

## AUDIO TUNING PARAMETERS

```
espeak Command Parameters:
┌────────────────────────────────────────────────────────────┐
│ espeak                                                     │
│   -s 120        ← Speed (words/min)                       │
│                   130 = warmup probe (faster, quieter)    │
│                   120 = announcement (slower, clearer)    │
│   -a 200        ← Amplitude (0-200) = MAXIMUM             │
│   -g 15         ← Gap between words (15ms)                │
│   -p 50         ← Pitch (normal = 50)                     │
│   text          ← Message to speak                        │
└────────────────────────────────────────────────────────────┘

Optimized for:
  • Low-bandwidth Bluetooth HFP (8kHz, mono)
  • Noisy rover environment (loud wheels, motors)
  • Field operators (need clear, slow speech)
  • First-word clipping (warm-up probe avoids)
```

---

## MISSION TIMELINE: Voice Annotation

```
T=0s   ──────────────────────────────────────────────────────────────
       [OPERATOR] Loads mission with 3 waypoints
         ▼
       emit_status("Mission loaded with 3 waypoints", 
                   extra_data={"event_type": "mission_loaded"})
         ▼
       TTS SPEAKS: "Waypoints loaded: 3 waypoints"
       
T=5s   ──────────────────────────────────────────────────────────────
       [OPERATOR] Starts mission
         ▼
       emit_status("Mission started",
                   extra_data={"event_type": "mission_started"})
         ▼
       TTS SPEAKS: "Mission started"
       
T=10s  ──────────────────────────────────────────────────────────────
       [CONTROLLER] Uploads WP1, sets AUTO mode
         ▼
       emit_status("Executing waypoint 1",
                   extra_data={"event_type": "waypoint_executing"})
         ▼
       TTS SPEAKS: "Going to waypoint 1 of 3"
       
T=15s  ──────────────────────────────────────────────────────────────
       [ROVER] Moving toward WP1
       
T=45s  ──────────────────────────────────────────────────────────────
       [PIXHAWK] Detects waypoint reached (topic or fallback)
         ▼
       emit_status("Waypoint 1 reached",
                   extra_data={"event_type": "waypoint_reached"})
         ▼
       TTS SPEAKS: "Waypoint 1 reached"
       
T=48s  ──────────────────────────────────────────────────────────────
       [CONTROLLER] Hold period (2s), then servo sequence
       
T=52s  ──────────────────────────────────────────────────────────────
       [CONTROLLER] Servo ON → SPRAY → OFF complete
         ▼
       emit_status("Waypoint 1 marking completed",
                   extra_data={"event_type": "waypoint_marked"})
         ▼
       TTS SPEAKS: "Waypoint 1 marked complete"
       
T=55s  ──────────────────────────────────────────────────────────────
       [CONTROLLER] Proceed to WP2 (repeat cycle)
       
T=135s ──────────────────────────────────────────────────────────────
       [CONTROLLER] All waypoints complete
         ▼
       emit_status("Mission completed successfully",
                   extra_data={"event_type": "mission_completed",
                              "waypoints_completed": 3,
                              "mission_duration": 130})
         ▼
       TTS SPEAKS: "Mission completed: 3 waypoints in 130 seconds"
       
T=140s ──────────────────────────────────────────────────────────────
       [MISSION COMPLETE]
       Operator can review logs, verify waypoints in GCS, plan next mission
```

---

## FAILURE SCENARIOS & HANDLING

```
┌──────────────────────────────────────┐
│ SCENARIO 1: espeak binary missing     │
├──────────────────────────────────────┤
│ Trigger: subprocess.run() raises OSError
│ Handler: Catch exception, call _speak_pyttsx3()
│ Result: Fallback to pyttsx3 (slower but works)
│ Mission: ✓ Continues (TTS non-critical)
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ SCENARIO 2: Both TTS engines fail     │
├──────────────────────────────────────┤
│ Trigger: Both espeak & pyttsx3 raise exceptions
│ Handler: Return False, continue to next queued message
│ Result: Silent failure, message skipped
│ Mission: ✓ Continues (TTS non-critical)
│ Logging: ✓ [WARN] TTS announcement failed: {error}
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ SCENARIO 3: Bluetooth speaker offline│
├──────────────────────────────────────┤
│ Trigger: espeak succeeds but no audio hardware
│ Handler: None (no device check implemented)
│ Result: Silent failure, rover executes silently
│ Mission: ✓ Continues (TTS non-critical)
│ Logging: ✗ No warning (RISK)
│ Fix: Need audio device health monitoring
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ SCENARIO 4: Message text changed     │
├──────────────────────────────────────┤
│ OLD trigger: if 'Mission loaded with' in message
│ Change: Message becomes 'Loaded mission with'
│ Result: TTS trigger fails silently
│ Mission: ✓ Continues (TTS non-critical)
│ Logging: ✗ No warning (CURRENT RISK)
│ Fix: Use structured event_type dispatch (RECOMMENDED)
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ SCENARIO 5: Same message sent twice  │
├──────────────────────────────────────┤
│ Trigger: Same text enqueued twice within 3s
│ Handler: _should_speak() dedup logic
│ Result: Second message skipped, no repeat
│ Mission: ✓ Correct behavior (avoid stutter)
└──────────────────────────────────────┘
```

---

## TESTING STRATEGY

```
UNIT TEST LEVEL
┌─────────────────────────────────────────┐
│ test_tts_integration.py                 │
│                                         │
│ Simulates 6 mission events:             │
│ ✓ Mission Load                          │
│ ✓ Mission Start                         │
│ ✓ Executing Waypoint                    │
│ ✓ Waypoint Reached                      │
│ ✓ Waypoint Complete                     │
│ ✓ Mission Complete                      │
│                                         │
│ Verifies:                               │
│ ✓ TTS module imports                   │
│ ✓ All events trigger speak()            │
│ ✓ Correct text output                  │
│ ✓ No exceptions raised                 │
│ ✗ Actual audio playback (manual test)  │
└─────────────────────────────────────────┘

INTEGRATION TEST LEVEL
┌─────────────────────────────────────────┐
│ Small field mission (2-3 waypoints)     │
│                                         │
│ Verifies:                               │
│ ✓ Event propagation through stack      │
│ ✓ Bluetooth speaker is configured      │
│ ✓ Audio latency acceptable             │
│ ✓ All 6 announcements heard            │
│ ✓ Timing synchronized with visual UI   │
└─────────────────────────────────────────┘

EDGE CASE TEST LEVEL (NOT YET IMPLEMENTED)
┌─────────────────────────────────────────┐
│ Fast waypoint succession                │
│ Bluetooth disconnect during mission     │
│ ESPeak subprocess timeout               │
│ Special characters in error messages    │
│ Duplicate event firing                  │
└─────────────────────────────────────────┘
```

---

## CURRENT IMPLEMENTATION STATUS

### ✅ COMPLETE (DO NOT CHANGE)
- Queue-based worker thread architecture
- Audio warm-up mechanism
- Deduplication logic
- Dual-engine fallback (espeak → pyttsx3)
- All 6 mission event triggers
- Graceful error handling
- Configuration via environment variables

### 🔄 IN PROGRESS (REFACTORING RECOMMENDED)
- String-based TTS trigger patterns → Structured event types

### ⚠️ NOT IMPLEMENTED (FOR FUTURE)
- Audio device health monitoring
- Bluetooth connection verification
- Audio latency measurement
- Multi-language support
- AI/Neural TTS
- Voice input (speech recognition)
- Error classification system

---

## ARCHITECTURE QUALITY ASSESSMENT

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Decoupling** | 7/10 | TTS is loosely coupled from mission; string triggers are tightly coupled |
| **Reusability** | 8/10 | TTS module can be used for other announcements |
| **Testability** | 6/10 | Can test TTS module in isolation; event mapping needs structured data |
| **Maintainability** | 6/10 | Code is readable; string patterns are fragile |
| **Scalability** | 8/10 | Can easily add new event types |
| **Reliability** | 7/10 | Graceful failures; no single point of failure |
| **Performance** | 9/10 | Async/non-blocking; won't stall mission |

---

**Document Version**: 1.0  
**Last Updated**: 15 December 2025  
**Status**: Complete Assessment
