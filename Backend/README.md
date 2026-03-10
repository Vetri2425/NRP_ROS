# MAVLink SocketIO Backend (Python)

This Flask-SocketIO service mirrors the contract expected by the React planner UI while talking directly to a MAVLink-enabled rover. It maintains a live connection using `pymavlink`, relays telemetry to the frontend, handles command requests, and pushes mission uploads/downloads to the vehicle.

## Prerequisites

- Python 3.10+
- Access to the rover over MAVLink (adjust `CONNECTION_STRING` / `BAUD_RATE` as required)

## Setup

```bash
cd backend-python
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```bash
python server.py
```

The service listens on port `5000`. Point the frontend env (`VITE_JETSON_BACKEND_URL`) to `http://localhost:5000` so `useRoverConnection` talks to this backend.

## Behaviour Overview

- Emits `connection_status` and `rover_data` Socket.IO events identical to the expectations in `src/hooks/useRoverConnection.ts`.
- Streams telemetry as new MAVLink packets arrive (with periodic full refreshes every 5 s).
- Handles planner commands (`ARM_DISARM`, `SET_MODE`, `GOTO`, `UPLOAD_MISSION`, `GET_MISSION`) by issuing the corresponding MAVLink commands and responding on `command_response`.
- Tracks mission uploads progress, forwarding `mission_upload_progress` updates to the UI.

Adjust the mission command mapping or connection settings at the top of `server.py` to suit your hardware.
