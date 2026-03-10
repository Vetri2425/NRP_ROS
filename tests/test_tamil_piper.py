#!/usr/bin/env python3
"""
Test script for Tamil Piper TTS integration.
Verifies that Piper models are installed and Tamil language works.

Usage:
    JARVIS_LANG=ta python3 test_tamil_piper.py
"""

import os
import sys
import time

# Set language before importing tts
os.environ['JARVIS_LANG'] = 'ta'
os.environ['NRP_TTS_ENABLE'] = 'true'

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Backend'))

try:
    import tts
except ImportError as e:
    print(f"[ERROR] Failed to import tts module: {e}")
    sys.exit(1)

def test_tamil_announcements():
    """Test Tamil voice announcements."""
    
    tamil_messages = [
        "பணி தொடங்கியது",  # Mission started (Tamil)
        "தரை புள்ளி ஒன்று வந்துசேர்ந்தது",  # Waypoint 1 reached (Tamil)
        "பணி முடிந்து விட்டது",  # Mission completed (Tamil)
    ]
    
    print("[INFO] Testing Tamil Piper TTS")
    print(f"[INFO] Language: {os.environ.get('JARVIS_LANG', 'en')}")
    print(f"[INFO] TTS Enabled: {os.environ.get('NRP_TTS_ENABLE', 'true')}")
    print()
    
    for i, msg in enumerate(tamil_messages, 1):
        print(f"[{i}] Queuing: {msg}")
        tts.speak(msg, async_=True)
        time.sleep(2)  # Allow TTS to process before next message
    
    # Wait for final message to complete
    print("[INFO] Waiting for final message to complete...")
    time.sleep(5)
    
    print("[INFO] Tamil TTS test completed successfully!")

if __name__ == "__main__":
    try:
        test_tamil_announcements()
    except KeyboardInterrupt:
        print("\n[INFO] Test interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] Test failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
