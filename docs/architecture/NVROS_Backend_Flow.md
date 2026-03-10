# NVROS Backend Process Flow (from Scratch)

This document describes the backend process flow for NVROS, focusing on the integration between the server, MAVROS, ROS2, and Pixhawk. The frontend is a separate part and is summarized at the end.

---

## Backend Flow: Pixhawk → ROS2 → MAVROS → Backend Server

### 1. Pixhawk (Flight Controller)
- **Purpose:** Executes missions, sends telemetry, receives commands.
- **Protocol:** Communicates via MAVLink.

### 2. ROS2 Layer
- **MAVROS Node:** Bridges MAVLink messages from Pixhawk to ROS2 topics.
- **Key Files:**
  - `Backend/mavros_bridge.py`: Handles MAVROS topic subscription/publication.
  - `Backend/telemetry_node.py`: Processes telemetry data from Pixhawk.
  - `Backend/integrated_mission_controller.py`: Orchestrates mission logic, interacts with ROS2 topics.

### 3. Backend Server
- **API Layer:**
  - `Backend/server.py`: Main API server, exposes REST/WebSocket endpoints for control and telemetry.
  - `Backend/inject_and_listen.py`: Injects commands into ROS2, listens for events.
  - `Backend/gps_altitude_corrector.py`: Corrects GPS altitude data from ROS2.
  - `Backend/merge_cors_handlers.py`, `Backend/fix_servo_cors.py`: Handle CORS for API endpoints.
- **Testing & Validation:**
  - `Backend/test_integrated_mission_controller_events.py`: Tests event flow.
  - `Backend/test_mission_integration.py`: Tests full backend integration.
- **Dependencies:**
  - `Backend/requirements.txt`: Python dependencies for backend and ROS2 bridge.

---

## Example Backend Data Flow

1. **Telemetry:**
   - Pixhawk → MAVLink → MAVROS → ROS2 Topic → Backend (`telemetry_node.py`) → API (`server.py`)
2. **Mission Command:**
   - API (`server.py`) → ROS2 Topic → MAVROS → MAVLink → Pixhawk
3. **Mission Logic:**
   - Mission control logic in `integrated_mission_controller.py` interacts with ROS2 topics and backend APIs.

---

## Frontend (Summary)
- **Purpose:** User interface for mission control and monitoring.
- **Flow:**
  - Sends commands to backend API.
  - Receives telemetry and mission status from backend API.

---

Use this file to visualize the backend process flow in a diagram or notebook LLM.
