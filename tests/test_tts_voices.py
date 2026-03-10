#!/usr/bin/env python3
"""
Test script for all TTS voice outputs used in the NRP rover system.
Plays each message synchronously so you can verify audio output.

Usage: python3 Backend/test_tts_voices.py [--lang en|ta|hi]
"""

import os
import sys
import time

# Set language before importing tts
lang = "hi"
for i, arg in enumerate(sys.argv):
    if arg == "--lang" and i + 1 < len(sys.argv):
        lang = sys.argv[i + 1].strip().lower()
os.environ["JARVIS_LANG"] = lang
# Override to test Swara voice with Hindi messages
os.environ["NRP_TTS_EDGE_VOICE"] = "hi-IN-SwaraNeural"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Backend"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import tts

# All voice messages used in the system, grouped by category
VOICE_MESSAGES = {
    "Startup / Connection": {
        "en": [
            "Way to Mark initialised. Good afternoon!",
            "Vehicle armed.",
            "Vehicle disarmed.",
            "Warning! Vehicle connection lost.",
        ],
        "ta": [
            "வே டு மார்க் தொடங்கப்பட்டது. மதிய வணக்கம்!",
            "வாகனம் ஆர்ம் செய்யப்பட்டது.",
            "வாகனம் டிஸ்ஆர்ம் செய்யப்பட்டது.",
            "எச்சரிக்கை! வாகன இணைப்பு துண்டிக்கப்பட்டது.",
        ],
        "hi": [
            "वे टू मार्क शुरू हो गया. नमस्कार!",
            "वाहन आर्म हो गया.",
            "वाहन डिसआर्म हो गया.",
            "चेतावनी! वाहन कनेक्शन टूट गया.",
        ],
    },
    "Mission Events": {
        "en": [
            "Mission loaded, 5 points",
            "Mission started, let's go",
            "Heading to target 1 of 5",
            "Target 1 reached",
            "Target 1 done",
            "Target 2 failed, timeout",
            "Mission completed. 5 targets",
            "Mission paused.",
            "Mission resumed.",
            "Mission stopped.",
        ],
        "ta": [
            "பணி ஏற்றப்பட்டது, 5 இலக்குகள்",
            "பணி தொடங்கியது, போகலாம்",
            "இலக்கு1 க்கு செல்கிறோம், மொத்தம் 5",
            "இலக்கு1 அடையப்பட்டது",
            "இலக்கு1 முடிந்தது",
            "இலக்கு2 தோல்வி, timeout",
            "பணி முடிந்தது. 5 இலக்குகள்",
            "பணி நிறுத்தப்பட்டது.",
            "பணி மீண்டும் தொடங்கப்பட்டது.",
            "பணி நிறுத்தப்பட்டது.",
        ],
        "hi": [
            "मिशन लोड हो गया, 5 points",
            "मिशन शुरू हो गया, चलते हैं",
            "लक्ष्य 1 की तरफ जा रहे हैं, कुल 5",
            "लक्ष्य 1 पहुँच गए",
            "लक्ष्य 1 पूरा हो गया",
            "लक्ष्य 2 फेल हो गया, timeout",
            "मिशन पूरा हुआ. 5 लक्ष्य",
            "मिशन रुक गया.",
            "मिशन फिर से शुरू.",
            "मिशन रोक दिया गया.",
        ],
    },
    "RTK Status": {
        "en": [
            "RTK fix acquired. Centimeter accuracy active.",
            "RTK fix lost. Float mode active.",
            "RTK signal lost. GPS only mode.",
        ],
        "ta": [
            "ஆர்.டி.கே சரி. சென்டிமீட்டர் துல்லியம் செயலில்.",
            "ஆர்.டி.கே இழந்தது. ஃப்ளோட் பயன்முறை.",
            "ஆர்.டி.கே சிக்னல் இழப்பு. ஜி.பி.எஸ் மட்டும்.",
        ],
        "hi": [
            "RTK फिक्स मिल गया. सेंटीमीटर सटीकता सक्रिय.",
            "RTK फिक्स खो गया. फ्लोट मोड सक्रिय.",
            "RTK सिग्नल खो गया. केवल GPS मोड.",
        ],
    },
    "Obstacle Detection": {
        "en": [
            "Object detected, 30 centimeters away",
            "Mission paused, object too close",
            "Obstacle detection disabled.",
        ],
        "ta": [
            "பொருள் கண்டறியப்பட்டது, 30 சென்டிமீட்டர் தூரத்தில்",
            "பணி நிறுத்தப்பட்டது, பொருள் மிக அருகில் உள்ளது",
            "தடை கண்டறிதல் நிறுத்தப்பட்டது.",
        ],
        "hi": [
            "Object detect हुआ है, 30 centimeters दूर",
            "मिशन रुक गया, object बहुत करीब है",
            "बाधा पहचान निष्क्रिय.",
        ],
    },
    "Battery Warnings": {
        "en": [
            "Battery low, 25 percent remaining.",
            "Warning! Battery critical, 10 percent remaining.",
        ],
        "ta": [
            "பேட்டரி குறைவு, 25 சதவீதம் மீதம்.",
            "எச்சரிக்கை! பேட்டரி மிகக் குறைவு, 10 சதவீதம் மீதம்.",
        ],
        "hi": [
            "बैटरी कम है, 25 प्रतिशत बाकी.",
            "चेतावनी! बैटरी गंभीर, 10 प्रतिशत बाकी.",
        ],
    },
    "Language Switch": {
        "en": ["Language set to English."],
        "ta": ["மொழி தமிழுக்கு மாற்றப்பட்டது."],
        "hi": ["भाषा हिंदी में बदल गई."],
    },
}


def main():
    print(f"=== NRP TTS Voice Test (lang={lang}) ===")
    print(f"Engine: edge-tts -> Piper fallback")
    print(f"Voice: {tts._get_edge_voice()}")
    print()

    total = 0
    passed = 0
    failed = 0

    for category, langs in VOICE_MESSAGES.items():
        messages = langs.get(lang, langs.get("en", []))
        print(f"--- {category} ({len(messages)} messages) ---")

        for i, msg in enumerate(messages, 1):
            total += 1
            print(f"  [{i}/{len(messages)}] \"{msg}\"")
            print(f"           Speaking...", end="", flush=True)

            start = time.time()
            ok = tts._worker._speak_impl(msg)
            elapsed = time.time() - start

            if ok:
                passed += 1
                print(f" OK ({elapsed:.1f}s)")
            else:
                failed += 1
                print(f" FAILED ({elapsed:.1f}s)")

            time.sleep(0.5)

        print()

    print(f"=== Results: {passed}/{total} passed, {failed} failed ===")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
