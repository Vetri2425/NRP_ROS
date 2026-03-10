#!/usr/bin/env python3
"""
Test script to listen for rover beacon broadcasts.
Run this to verify the beacon system is working.
"""

import socket
import json
import time

def listen_for_beacons(port=5002, timeout=10):
    """Listen for rover beacon broadcasts on the specified port."""
    print(f"Listening for rover beacons on UDP port {port}...")
    print(f"Will timeout after {timeout} seconds if no beacons received.")
    print("Press Ctrl+C to stop.\n")
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    
    try:
        # Bind to all interfaces on the beacon port
        sock.bind(('', port))
        
        beacon_count = 0
        start_time = time.time()
        
        while True:
            try:
                # Receive beacon data
                data, addr = sock.recvfrom(1024)
                beacon_count += 1
                
                # Parse JSON payload
                try:
                    beacon = json.loads(data.decode('utf-8'))
                    print(f"[{beacon_count}] Beacon from {addr[0]}:{addr[1]}")
                    print(f"    Rover ID: {beacon.get('rover_id', 'unknown')}")
                    print(f"    Rover Name: {beacon.get('rover_name', 'unknown')}")
                    print(f"    IP: {beacon.get('ip', 'unknown')}")
                    print(f"    Port: {beacon.get('port', 'unknown')}")
                    print(f"    Version: {beacon.get('version', 'unknown')}")
                    print(f"    Uptime: {beacon.get('uptime', 0)} seconds")
                    print(f"    Timestamp: {beacon.get('timestamp', 0)}")
                    print()
                    
                except json.JSONDecodeError as e:
                    print(f"[{beacon_count}] Invalid JSON from {addr}: {e}")
                    print(f"    Raw data: {data}")
                    print()
                    
            except socket.timeout:
                elapsed = time.time() - start_time
                print(f"No beacons received after {elapsed:.1f} seconds.")
                break
                
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\nStopped after {elapsed:.1f} seconds.")
        print(f"Total beacons received: {beacon_count}")
        
    except Exception as e:
        print(f"Error: {e}")
        
    finally:
        sock.close()

if __name__ == "__main__":
    listen_for_beacons()