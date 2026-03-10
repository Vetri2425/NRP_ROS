import os
import sys
import time

# Simple smoke test for Backend/tts
# Usage:
#   cd /home/flash/NRP_ROS
#   JARVIS_LANG=en python3 tools/tts_smoke_test.py
#   JARVIS_LANG=hi python3 tools/tts_smoke_test.py
#   JARVIS_LANG=ta python3 tools/tts_smoke_test.py  (falls back to eSpeak)

os.environ.setdefault("NRP_TTS_ENABLE", "true")
os.environ.setdefault("NRP_TTS_MIN_INTERVAL", "0.5")

# Add parent directory to path so we can import Backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Backend import tts  # noqa: E402


def main():
    lang = os.environ.get("JARVIS_LANG", "en")
    print(f"[SMOKE] JARVIS_LANG={lang}")
    tts.speak("TTS smoke test: announcement one.")
    tts.speak("TTS smoke test complete.")
    # Allow background worker time to play both announcements fully
    time.sleep(6)
    tts.shutdown()
    print("[SMOKE] Test finished")


if __name__ == "__main__":
    main()
