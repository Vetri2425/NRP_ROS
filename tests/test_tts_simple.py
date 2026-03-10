#!/usr/bin/env python3
"""Simple TTS test to verify it works"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Backend'))

import tts

print("Testing TTS module...")
print(f"TTS enabled: {tts._ENABLE_VOICE}")
print(f"TTS engine: {tts._DEFAULT_ENGINE}")
print(f"Min interval: {tts._MIN_INTERVAL_SEC}")
print(f"Bluetooth warmup: {tts._BT_WARMUP_ENABLED}")
print(f"Jarvis lang: {tts._JARVIS_LANG}")

print("\nTesting speech...")
tts.speak("Mission loaded: 3 points", async_=False)
print("TTS test complete!")
