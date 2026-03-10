# NVROS System Architecture: File Flow & Purpose

This document describes the full flow of the NVROS system from scratch, listing key files and their purposes for Backend, ROS2, Pixhawk, and Frontend integration. Use this as a reference for creating diagrams with a notebook LLM or other tools.

---

## 1. Pixhawk (Flight Controller)
- **Purpose:** Hardware for mission execution, telemetry, and control.
- **Key Protocol:** MAVLink

---

## 2. ROS2 Layer
- **verify_ros_topic_fix.py**: Verifies ROS topic fixes for Pixhawk integration.
- **mavros_bridge.py** (`Backend/`): Bridges MAVROS (MAVLink-ROS2) topics to backend services.
- **telemetry_node.py** (`Backend/`): Handles telemetry data from Pixhawk via ROS2 topics.
- **integrated_mission_controller.py** (`Backend/`): Main mission control logic, interacts with ROS2 topics.

---

## 3. Backend (Python APIs)
- **server.py** (`Backend/`): Main backend API server, exposes REST/WebSocket endpoints.
- **gps_altitude_corrector.py** (`Backend/`): Corrects GPS altitude data from ROS2.
- **inject_and_listen.py** (`Backend/`): Injects commands and listens for events from ROS2.
- **merge_cors_handlers.py** (`Backend/`): Handles CORS for API endpoints.
- **fix_servo_cors.py** (`Backend/`): Fixes CORS issues for servo control endpoints.
- **Test_Emit_Data.py** (`Backend/`): Emits test data for backend/ROS2 integration.
- **test_integrated_mission_controller_events.py** (`Backend/`): Tests mission controller event flow.
- **test_mission_integration.py** (`Backend/`): Tests full mission integration (backend + ROS2 + Pixhawk).
- **requirements.txt** (`Backend/`): Python dependencies for backend and ROS2 bridge.

---

## 4. Frontend (Web/App)
- **src/App.tsx**: Main React app entry point.
- **src/index.tsx**: App bootstrap.
- **src/components/**: UI components for mission control, telemetry, etc.
- **src/context/**: React context for state management.
- **src/hooks/**: Custom React hooks for API calls, telemetry, etc.
- **src/utils/**: Utility functions for frontend logic.
- **src/config.ts**: Configuration for API endpoints.
- **package.json**: Frontend dependencies and scripts.

---

## 5. Integration & Testing
- **test_gps_raw_integration.py**: Tests raw GPS data flow.
- **test_mode_change.py**: Tests mode change commands from frontend to Pixhawk.
- **test_servo_10_ros2.py**: Tests servo control via ROS2.
- **test_mission_flow.sh**: Shell script for mission flow testing.
- **test_mission_logging.sh**: Shell script for mission logging verification.
- **test_mission_start_stop.sh**: Shell script for mission start/stop flow.
- **test_refactored_mission.sh**: Shell script for refactored mission flow.

---

## 6. Documentation & Reports
- **README.md**: Project overview and setup instructions.
- **MISSION_CONTROLLER_REFACTOR.md**: Refactor notes for mission controller.
- **PROJECT_REPORT.html**: Project report (HTML).
- **Backend/README.md**: Backend-specific documentation.

---

## 7. Example Flow

1. **Frontend** sends mission command → **Backend** (`server.py`) → **ROS2** (`integrated_mission_controller.py`) → **Pixhawk**
2. **Pixhawk** sends telemetry → **ROS2** (`telemetry_node.py`) → **Backend** → **Frontend**
3. **Testing** via scripts and test files ensures integration and reliability.

---

Use this file as input for your notebook LLM to generate a block diagram or flow chart visually.
