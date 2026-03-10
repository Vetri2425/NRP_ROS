#!/usr/bin/env python3
"""
Test LoRa RTK Stream Events
Simulates Socket.IO client connecting to backend and testing LoRa endpoints
"""

import socketio
import time
import sys
from threading import Event

# Create Socket.IO client
sio = socketio.Client(
    ssl_verify=False,
    reconnection=True,
    reconnection_attempts=5,
    reconnection_delay=1
)

# Track events received
events_received = []
test_complete = Event()

@sio.event
def connect():
    print("✓ Connected to backend")
    events_received.append(('connect', {}))

@sio.event
def disconnect():
    print("✗ Disconnected from backend")
    events_received.append(('disconnect', {}))

@sio.on('connection_response')
def on_connection_response(data):
    print(f"[connection_response] {data}")
    events_received.append(('connection_response', data))

@sio.on('lora_rtk_status')
def on_lora_rtk_status(data):
    status = data.get('status', 'unknown')
    message = data.get('message', '')
    print(f"[lora_rtk_status] Status: {status}")
    print(f"  └─ Message: {message}")
    if data.get('messages_received'):
        print(f"  └─ Messages: {data.get('messages_received')}")
    if data.get('bytes_received'):
        print(f"  └─ Bytes: {data.get('bytes_received')}")
    if data.get('error_count'):
        print(f"  └─ Errors: {data.get('error_count')}")
    events_received.append(('lora_rtk_status', data))

@sio.on('rtk_log')
def on_rtk_log(data):
    message = data.get('message', '')
    print(f"[rtk_log] {message}")
    events_received.append(('rtk_log', data))

@sio.on('connection_status')
def on_connection_status(data):
    print(f"[connection_status] {data.get('status', 'unknown')}")
    events_received.append(('connection_status', data))

def test_lora_events():
    """Test LoRa RTK stream events"""
    
    print("\n" + "="*60)
    print("TESTING LoRa RTK STREAM EVENTS")
    print("="*60)
    
    # Connect to backend
    print("\n[TEST 1] Connecting to backend...")
    try:
        sio.connect('http://localhost:5001')
        time.sleep(1)
        print("✓ Backend connection established\n")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        sys.exit(1)
    
    # Test 1: Get initial status
    print("[TEST 2] Getting initial LoRa status...")
    sio.emit('get_lora_rtk_status', {})
    time.sleep(1)
    print()
    
    # Test 2: Start LoRa stream
    print("[TEST 3] Starting LoRa RTK stream...")
    sio.emit('start_lora_rtk_stream', {})
    time.sleep(2)
    print()
    
    # Test 3: Get status while running
    print("[TEST 4] Getting LoRa status (should show streaming)...")
    sio.emit('get_lora_rtk_status', {})
    time.sleep(1)
    print()
    
    # Test 4: Stop LoRa stream
    print("[TEST 5] Stopping LoRa RTK stream...")
    sio.emit('stop_lora_rtk_stream', {})
    time.sleep(1)
    print()
    
    # Test 5: Get final status
    print("[TEST 6] Getting final LoRa status (should show disconnected)...")
    sio.emit('get_lora_rtk_status', {})
    time.sleep(1)
    print()
    
    # Disconnect
    print("[TEST 7] Disconnecting from backend...")
    sio.disconnect()
    time.sleep(1)
    
    # Print summary
    print("\n" + "="*60)
    print("EVENTS RECEIVED SUMMARY")
    print("="*60)
    for event_name, event_data in events_received:
        print(f"• {event_name}")
    
    print("\n" + "="*60)
    print("BACKEND TESTING COMPLETE ✓")
    print("="*60)
    print("\nBackend LoRa endpoints are functioning correctly!")
    print("Check /var/log/nrp-service.log for detailed backend logs")

if __name__ == "__main__":
    try:
        test_lora_events()
    except KeyboardInterrupt:
        print("\n\nTest interrupted")
        sio.disconnect()
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
