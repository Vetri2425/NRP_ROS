import os
import time
import threading
import subprocess
import shutil
import tempfile
from queue import Queue
from typing import Optional

# Non-blocking TTS with rate limiting and deduplication.
# Primary: edge-tts (Microsoft Edge Neural Voices via cloud)
# Fallback: Piper (local neural TTS)

_MIN_INTERVAL_SEC = float(os.environ.get("NRP_TTS_MIN_INTERVAL", "3.0"))
_ENABLE_VOICE = os.environ.get("NRP_TTS_ENABLE", "true").lower() in ("1", "true", "yes")

# edge-tts voice mapping per language (male/female variants)
_EDGE_VOICES_MALE = {
    "ta": "ta-IN-ValluvarNeural",
    "en": "en-US-RogerNeural",
    "hi": "hi-IN-MadhurNeural",
}
_EDGE_VOICES_FEMALE = {
    "ta": "ta-IN-PallaviNeural",
    "en": "en-US-MichelleNeural",
    "hi": "hi-IN-SwaraNeural",
}

# NRP_TTS_GENDER: "male" or "female" (default: male)
_VOICE_GENDER = os.environ.get("NRP_TTS_GENDER", "male").strip().lower()
_EDGE_VOICES = _EDGE_VOICES_MALE if _VOICE_GENDER == "male" else _EDGE_VOICES_FEMALE

def _get_edge_voice() -> str:
    """Get the edge-tts voice for the current language."""
    override = os.environ.get("NRP_TTS_EDGE_VOICE")
    if override:
        return override
    lang = os.environ.get("JARVIS_LANG", "en").strip().lower()
    return _EDGE_VOICES.get(lang) or _EDGE_VOICES["en"]


class _TTSWorker:
    def __init__(self):
        self.queue: Queue[str] = Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.last_spoken_text: Optional[str] = None
        self.last_spoken_at: float = 0.0
        self._stop_event = threading.Event()
        self._piper_available: Optional[bool] = None
        self._edge_available: Optional[bool] = None
        self._gst_available: Optional[bool] = None
        self.thread.start()

    def stop(self):
        self._stop_event.set()
        self.queue.put("\0")
        self.thread.join(timeout=1.0)

    def enqueue(self, text: str):
        if not text:
            return
        self.queue.put(text)

    def _should_speak(self, text: str) -> bool:
        now = time.time()
        if self.last_spoken_text == text and (now - self.last_spoken_at) < _MIN_INTERVAL_SEC:
            return False
        return True

    def _run(self):
        while not self._stop_event.is_set():
            try:
                text = self.queue.get(timeout=0.5)
            except Exception:
                continue
            if self._stop_event.is_set():
                break
            if text == "\0":
                continue
            if not _ENABLE_VOICE:
                continue
            if not self._should_speak(text):
                continue

            ok = self._speak_impl(text)
            if ok:
                self.last_spoken_text = text
                self.last_spoken_at = time.time()
                time.sleep(0.3)

    def _speak_impl(self, text: str) -> bool:
        # Retry edge-tts until success (handles boot-time network delays)
        _RETRY_INTERVAL = 2.0
        _MAX_RETRIES = 30  # 30 x 2s = 60s max wait
        for attempt in range(1, _MAX_RETRIES + 1):
            if self._stop_event.is_set():
                return False
            if self._speak_edge(text):
                return True
            print(f"[TTS] edge-tts failed (attempt {attempt}/{_MAX_RETRIES}), retrying in {_RETRY_INTERVAL}s...", flush=True)
            self._stop_event.wait(_RETRY_INTERVAL)

        print("[TTS] edge-tts failed after all retries", flush=True)
        return False

    # ── edge-tts (cloud neural) ──────────────────────────────────

    def _is_edge_available(self) -> bool:
        if self._edge_available is None:
            self._edge_available = shutil.which("edge-tts") is not None
        return self._edge_available

    def _is_gst_available(self) -> bool:
        if self._gst_available is None:
            self._gst_available = shutil.which("gst-play-1.0") is not None
        return self._gst_available

    def _speak_edge(self, text: str) -> bool:
        if not self._is_edge_available():
            return False
        if not self._is_gst_available():
            return False

        tmp_mp3 = None
        try:
            fd, tmp_mp3 = tempfile.mkstemp(suffix=".mp3", prefix="tts_")
            os.close(fd)

            voice = _get_edge_voice().strip()
            print(f"[TTS] Using voice: {voice} (gender={_VOICE_GENDER}, lang={os.environ.get('JARVIS_LANG', 'en')})", flush=True)

            # Run edge-tts in a subprocess to avoid eventlet monkey-patch conflicts
            result = subprocess.run(
                ["edge-tts", "--voice", voice, "--text", text, "--write-media", tmp_mp3],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                print(f"[TTS] edge-tts subprocess failed: {result.stderr[:200]}", flush=True)
                return False

            # Check file was actually created with content
            if not os.path.exists(tmp_mp3) or os.path.getsize(tmp_mp3) == 0:
                print("[TTS] edge-tts produced empty file", flush=True)
                return False

            # Play with GStreamer
            result = subprocess.run(
                ["gst-play-1.0", tmp_mp3],
                capture_output=True, text=True, timeout=15
            )
            return result.returncode == 0

        except Exception as e:
            print(f"[TTS] edge-tts error: {e}", flush=True)
            return False
        finally:
            if tmp_mp3 and os.path.exists(tmp_mp3):
                try:
                    os.unlink(tmp_mp3)
                except OSError:
                    pass

    # ── Piper (local neural) ─────────────────────────────────────

    def _is_piper_available(self) -> bool:
        if self._piper_available is not None:
            return self._piper_available

        for path in [
            "/home/flash/.local/bin/piper",
            "/usr/local/bin/piper",
            "/usr/bin/piper",
        ]:
            if os.path.exists(path) and os.access(path, os.X_OK):
                self._piper_available = True
                return True

        if shutil.which("piper"):
            self._piper_available = True
            return True

        self._piper_available = False
        return False

    def _piper_model_path(self) -> Optional[str]:
        for base in ["/opt/jarvis/models/piper", "/home/flash/.local/share/piper/models"]:
            path = os.path.join(base, "en.onnx")
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        return None

    def _speak_piper(self, text: str) -> bool:
        if not self._is_piper_available():
            return False

        model = self._piper_model_path()
        if not model:
            return False

        try:
            piper_bin = "/home/flash/.local/bin/piper"
            if not os.path.exists(piper_bin):
                piper_bin = shutil.which("piper") or "piper"

            alsa_device = os.environ.get("NRP_TTS_ALSA_DEVICE", "default")
            cmd = f'echo "{text}" | {piper_bin} --model {model} --output_raw | aplay -D {alsa_device} -r 22050 -c 1 -f S16_LE -t raw'

            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = "/home/flash/.local/lib"

            result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                print(f"[TTS] Piper failed: {result.stderr[:200]}", flush=True)
                return False
            return True
        except Exception as e:
            print(f"[TTS] Piper error: {e}", flush=True)
            return False


_worker = _TTSWorker()


def speak(text: str, async_: bool = True, engine: Optional[str] = None):
    """Queue or synchronously speak text. Default: non-blocking."""
    if not _ENABLE_VOICE:
        return
    if async_:
        _worker.enqueue(text)
    else:
        if _worker._should_speak(text):
            _worker._speak_impl(text)


def shutdown():
    """Stop the background worker."""
    try:
        _worker.stop()
    except Exception:
        pass
