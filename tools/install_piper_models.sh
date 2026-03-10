#!/usr/bin/env bash
set -euo pipefail

# Installs Piper voice models for English, Hindi, and Tamil into /opt/jarvis/models/piper
# and names them en.onnx/en.onnx.json, hi.onnx/hi.onnx.json, and ta.onnx/ta.onnx.json
# as expected by Backend/tts.py.

EN_ONNX_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
EN_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
HI_ONNX_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/rohan/medium/hi_IN-rohan-medium.onnx"
HI_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/rohan/medium/hi_IN-rohan-medium.onnx.json"
TA_ONNX_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/ta/ta_IN/surya/medium/ta_IN-surya-medium.onnx"
TA_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/ta/ta_IN/surya/medium/ta_IN-surya-medium.onnx.json"

TARGET_DIR="/opt/jarvis/models/piper"

echo "Creating target directory: $TARGET_DIR (sudo may be required)"
sudo mkdir -p "$TARGET_DIR"
sudo chown "$USER":"$USER" "$TARGET_DIR" || true

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT

echo "Downloading English (en) Piper model..."
curl -L --fail -o "$tmpdir/en.onnx" "$EN_ONNX_URL"
curl -L --fail -o "$tmpdir/en.onnx.json" "$EN_JSON_URL"

echo "Downloading Hindi (hi) Piper model..."
curl -L --fail -o "$tmpdir/hi.onnx" "$HI_ONNX_URL"
curl -L --fail -o "$tmpdir/hi.onnx.json" "$HI_JSON_URL"

echo "Downloading Tamil (ta) Piper model..."
# Note: Tamil model may not be available upstream yet
if curl -L --fail -o "$tmpdir/ta.onnx" "$TA_ONNX_URL" 2>/dev/null && \
   curl -L --fail -o "$tmpdir/ta.onnx.json" "$TA_JSON_URL" 2>/dev/null; then
    echo "Tamil model downloaded successfully"
    ta_available=true
else
    echo "WARNING: Tamil Piper model not currently available upstream (404 Not Found)"
    echo "Tamil will use eSpeak fallback. Check back later for ta_IN-surya model availability."
    ta_available=false
fi

echo "Installing models to $TARGET_DIR ..."
sudo install -m 0644 "$tmpdir/en.onnx" "$TARGET_DIR/en.onnx"
sudo install -m 0644 "$tmpdir/en.onnx.json" "$TARGET_DIR/en.onnx.json"
sudo install -m 0644 "$tmpdir/hi.onnx" "$TARGET_DIR/hi.onnx"
sudo install -m 0644 "$tmpdir/hi.onnx.json" "$TARGET_DIR/hi.onnx.json"

if [ "$ta_available" = true ]; then
    sudo install -m 0644 "$tmpdir/ta.onnx" "$TARGET_DIR/ta.onnx"
    sudo install -m 0644 "$tmpdir/ta.onnx.json" "$TARGET_DIR/ta.onnx.json"
fi

echo ""
echo "Done. Models installed:"
ls -l "$TARGET_DIR" | sed 's/^/  /'
echo ""
echo "Notes:"
echo "- Set JARVIS_LANG to 'en' or 'hi' to use Piper with those languages."
if [ "$ta_available" = true ]; then
    echo "- Tamil (ta) Piper model is also available."
else
    echo "- Tamil (ta) Piper model is not available upstream yet; ta will use eSpeak fallback."
fi
echo "- Ensure 'piper' and 'paplay' are installed and that your PulseAudio default sink is your Bluetooth device."
