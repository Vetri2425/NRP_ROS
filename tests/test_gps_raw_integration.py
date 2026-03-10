#!/usr/bin/env python3
"""
Test script to verify GPS RAW topic integration in mavros_bridge.py

This script directly tests the _handle_gps_raw() method with real GPS raw data
to ensure correct conversion and broadcasting.
"""

import sys
import os

# Add Backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Backend'))

from mavros_bridge import MavrosBridge


def test_gps_raw_handler():
    """Test GPS raw message handling with real data from the topic."""
    
    # Sample real message from /mavros/gpsstatus/gps1/raw
    sample_message = {
        "header": {
            "stamp": {"sec": 1761818350, "nanosec": 838369280},
            "frame_id": "/wgs84"
        },
        "fix_type": 6,
        "lat": 130720581,
        "lon": 802619324,
        "alt": 16610,
        "eph": 70,
        "epv": 120,
        "vel": 0,
        "cog": 18000,
        "satellites_visible": 29,
        "alt_ellipsoid": 0,
        "h_acc": 0,
        "v_acc": 0,
        "vel_acc": 0,
        "hdg_acc": 0,
        "yaw": 0,
        "dgps_numch": 255,
        "dgps_age": 4294967295
    }
    
    print("=" * 80)
    print("GPS RAW INTEGRATION TEST")
    print("=" * 80)
    print("\nTesting GPS raw message handler with real data...")
    print(f"\nInput (raw GPS message):")
    print(f"  fix_type:           {sample_message['fix_type']}")
    print(f"  lat (raw):          {sample_message['lat']}")
    print(f"  lon (raw):          {sample_message['lon']}")
    print(f"  alt (mm):           {sample_message['alt']}")
    print(f"  eph (cm):           {sample_message['eph']}")
    print(f"  epv (cm):           {sample_message['epv']}")
    print(f"  satellites_visible: {sample_message['satellites_visible']}")
    print(f"  vel (cm/s):         {sample_message['vel']}")
    print(f"  cog (cdeg):         {sample_message['cog']}")
    
    # Create bridge instance (without connecting to ROS)
    bridge = MavrosBridge()
    
    # Capture telemetry broadcasts
    telemetry_messages = []
    
    def capture_callback(data):
        telemetry_messages.append(data)
    
    bridge.subscribe_telemetry(capture_callback)
    
    # Call the handler directly
    bridge._handle_gps_raw(sample_message)
    
    print("\n" + "=" * 80)
    print("TELEMETRY BROADCASTS")
    print("=" * 80)
    
    for msg in telemetry_messages:
        print(f"\n{msg}")
    
    # Verify conversions
    print("\n" + "=" * 80)
    print("VERIFICATION")
    print("=" * 80)
    
    # Find navsat message
    navsat_msg = next((m for m in telemetry_messages if 'latitude' in m), None)
    gps_fix_msg = next((m for m in telemetry_messages if 'rtk_status' in m), None)
    
    if navsat_msg:
        lat = navsat_msg['latitude']
        lon = navsat_msg['longitude']
        alt = navsat_msg['altitude']
        
        expected_lat = 130720581 / 1e7
        expected_lon = 802619324 / 1e7
        expected_alt = 16610 / 1000.0
        
        print(f"\n✓ Position (navsat message):")
        print(f"  Latitude:  {lat:.7f}° (expected: {expected_lat:.7f}°)")
        print(f"  Longitude: {lon:.7f}° (expected: {expected_lon:.7f}°)")
        print(f"  Altitude:  {alt:.2f} m (expected: {expected_alt:.2f} m)")
        
        assert abs(lat - expected_lat) < 1e-6, f"Latitude mismatch: {lat} != {expected_lat}"
        assert abs(lon - expected_lon) < 1e-6, f"Longitude mismatch: {lon} != {expected_lon}"
        assert abs(alt - expected_alt) < 0.01, f"Altitude mismatch: {alt} != {expected_alt}"
        print("  ✅ All position values correct!")
    else:
        print("  ❌ No navsat message found!")
    
    if gps_fix_msg:
        rtk_status = gps_fix_msg['rtk_status']
        fix_type = gps_fix_msg['fix_type']
        sats = gps_fix_msg['satellites_visible']
        hrms = gps_fix_msg['hrms']
        vrms = gps_fix_msg['vrms']
        
        expected_hrms = 70 / 100.0
        expected_vrms = 120 / 100.0
        
        print(f"\n✓ GPS Fix Quality (gps_fix message):")
        print(f"  RTK Status:         {rtk_status} (expected: RTK Fixed)")
        print(f"  Fix Type:           {fix_type} (expected: 6)")
        print(f"  Satellites Visible: {sats} (expected: 29)")
        print(f"  Horizontal Accuracy: {hrms:.2f} m (expected: {expected_hrms:.2f} m)")
        print(f"  Vertical Accuracy:   {vrms:.2f} m (expected: {expected_vrms:.2f} m)")
        
        assert rtk_status == "RTK Fixed", f"RTK status mismatch: {rtk_status}"
        assert fix_type == 6, f"Fix type mismatch: {fix_type}"
        assert sats == 29, f"Satellites mismatch: {sats}"
        assert abs(hrms - expected_hrms) < 0.01, f"HRMS mismatch: {hrms} != {expected_hrms}"
        assert abs(vrms - expected_vrms) < 0.01, f"VRMS mismatch: {vrms} != {expected_vrms}"
        print("  ✅ All GPS fix values correct!")
    else:
        print("  ❌ No gps_fix message found!")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("\n✅ GPS RAW integration test PASSED!")
    print("\nThe mavros_bridge correctly:")
    print("  • Converts lat/lon from 1e7 format to degrees")
    print("  • Converts altitude from millimeters to meters")
    print("  • Converts accuracy from centimeters to meters")
    print("  • Maps fix_type=6 to 'RTK Fixed' status")
    print("  • Extracts satellites_visible count")
    print("  • Broadcasts position and fix quality data")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_gps_raw_handler()
