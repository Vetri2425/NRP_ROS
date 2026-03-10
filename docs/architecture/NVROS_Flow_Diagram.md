# NVROS System Architecture Flow Diagram

This PDF describes the full flow of the NVROS system, including Pixhawk, ROS2, Backend, and Frontend components.

---

## Block Diagram Overview

```
[Frontend (Web/App)]
        ↑        ↓
      REST/WebSocket
        ↑        ↓
[Backend (Python APIs)]
        ↑        ↓
      ROS2 Bridge
        ↑        ↓
[ROS2 Nodes/Topics]
        ↑        ↓
      MAVROS/MAVLink
        ↑        ↓
[Pixhawk (Flight Controller)]
```

---

## Component Details

### 1. Pixhawk (Flight Controller)
- Receives mission commands
- Sends telemetry data
- Communicates via MAVLink protocol

### 2. ROS2
- Middleware for robotics communication
- Uses MAVROS to bridge Pixhawk and ROS2 topics
- Publishes/subscribes to telemetry, mission, and control topics

### 3. Backend (Python APIs)
- Subscribes to ROS2 topics
- Provides REST/WebSocket APIs for frontend
- Handles mission logic, logging, and data aggregation

### 4. Frontend (Web/App)
- User interface for mission control and monitoring
- Sends commands to backend
- Receives telemetry and mission status updates

---

## Data Flow

1. **Telemetry:** Pixhawk → MAVLink → ROS2 → Backend → Frontend
2. **Commands:** Frontend → Backend → ROS2 → MAVROS → Pixhawk
3. **Mission Control:** Frontend ↔ Backend ↔ ROS2 ↔ Pixhawk

---

## Visual Flow Chart

(See block diagram above. For a graphical version, use Figma/Draw.io with rectangles and arrows as shown.)

---

## Notes
- All communication is bi-directional where applicable.
- ROS2 acts as the central middleware.
- Backend provides APIs and business logic.
- Frontend is the user-facing layer.

---

For a graphical diagram, import the above structure into Figma or Draw.io and export as PDF.
