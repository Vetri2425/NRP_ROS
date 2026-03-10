## Piper TTS Models (en/hi) Setup

This project prefers Piper TTS for higher-quality speech. The backend will use Piper if available, and fall back to eSpeak otherwise. Place models at `/opt/jarvis/models/piper` with these filenames:

- en: en.onnx and en.onnx.json
- hi: hi.onnx and hi.onnx.json
- ta: ta.onnx and ta.onnx.json (not yet available upstream; will fall back to eSpeak)

### Install models automatically

1) Make the installer executable and run it (sudo required to write under `/opt`):

```
chmod +x tools/install_piper_models.sh
./tools/install_piper_models.sh
```

This downloads:
- English: en_US-lessac-medium
- Hindi: hi_IN-rohan-medium
- Tamil: ta_IN-surya-medium (attempted; may not be available yet)

And installs them as `en.onnx`, `en.onnx.json`, `hi.onnx`, `hi.onnx.json`, and optionally `ta.onnx`, `ta.onnx.json` if available.

### Requirements

- `piper` CLI installed and on PATH
- PulseAudio with `paplay` available
- A Bluetooth sink set as default, or export `NRP_TTS_SINK` to the sink name

Check default sink:

```
pactl get-default-sink
```

### Select language

Set one of:

```
export JARVIS_LANG=en   # English (Piper)
export JARVIS_LANG=hi   # Hindi (Piper)
export JARVIS_LANG=ta   # Tamil (falls back to eSpeak)
```

### Quick smoke test

You can run a quick test without starting the whole service:

```
python3 tools/tts_smoke_test.py
```

You should hear two short announcements. If Piper is missing or no model is found for the selected language, the backend will fall back to eSpeak automatically.
