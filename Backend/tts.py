import os
import time
import threading
import subprocess
import shutil
import tempfile
from queue import Queue
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

# Non-blocking TTS with rate limiting and deduplication.
# Primary: Piper local HTTP server (pre-loaded model, ~1.8s latency)
# Fallback: edge-tts (Microsoft Edge Neural Voices via cloud)

_MIN_INTERVAL_SEC = float(os.environ.get("NRP_TTS_MIN_INTERVAL", "3.0"))
_ENABLE_VOICE = os.environ.get("NRP_TTS_ENABLE", "true").lower() in ("1", "true", "yes")
_PIPER_SERVER_URL = os.environ.get("NRP_PIPER_URL", "http://127.0.0.1:5111")

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

    def flush(self):
        """Clear all pending items from the queue."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break

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

            # Support delay commands in queue (e.g. "__delay:2.0")
            if text.startswith("__delay:"):
                try:
                    delay = float(text.split(":")[1])
                    time.sleep(delay)
                except ValueError:
                    pass
                continue

            ok = self._speak_impl(text)
            if ok:
                self.last_spoken_text = text
                self.last_spoken_at = time.time()
                time.sleep(0.3)

    def _speak_impl(self, text: str) -> bool:
        # Try cached audio first (instant playback)
        with _cache_lock:
            cached_wav = _audio_cache.get(text)
        if cached_wav and os.path.exists(cached_wav):
            print(f"[TTS] Playing cached: {text}", flush=True)
            result = subprocess.run(
                ["gst-play-1.0", cached_wav],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0

        # Try Piper local server (fastest live generation)
        if self._speak_piper_server(text):
            return True

        # Fallback: edge-tts with retries
        _RETRY_INTERVAL = 2.0
        _MAX_RETRIES = 10
        for attempt in range(1, _MAX_RETRIES + 1):
            if self._stop_event.is_set():
                return False
            if self._speak_edge(text):
                return True
            print(f"[TTS] edge-tts failed (attempt {attempt}/{_MAX_RETRIES}), retrying in {_RETRY_INTERVAL}s...", flush=True)
            self._stop_event.wait(_RETRY_INTERVAL)

        print("[TTS] all TTS engines failed", flush=True)
        return False

    # ── Piper HTTP server (local, pre-loaded model) ─────────────

    def _speak_piper_server(self, text: str) -> bool:
        import json
        tmp_wav = None
        try:
            payload = json.dumps({"text": text}).encode("utf-8")
            req = Request(
                _PIPER_SERVER_URL + "/",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=10)
            wav_data = resp.read()
            if not wav_data or len(wav_data) < 100:
                return False

            fd, tmp_wav = tempfile.mkstemp(suffix=".wav", prefix="tts_piper_")
            os.close(fd)
            with open(tmp_wav, "wb") as f:
                f.write(wav_data)

            result = subprocess.run(
                ["gst-play-1.0", tmp_wav],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                print(f"[TTS] Piper server OK ({len(wav_data)} bytes)", flush=True)
                return True
            return False
        except (URLError, OSError, subprocess.TimeoutExpired) as e:
            print(f"[TTS] Piper server unavailable: {e}", flush=True)
            return False
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                try:
                    os.unlink(tmp_wav)
                except OSError:
                    pass

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

# ── Audio cache for pre-generated mission phrases ─────────────
# Pre-cache static phrases that are always needed
_STATIC_PHRASES = [
    # Mission events
    "Mission loaded",
    "Mission started, let's go",
    "Mission paused, object too close",
    "Mission completed",
    "Mission paused.",
    "Mission resumed.",
    "Mission stopped.",
    # Vehicle connection
    "Warning! Vehicle connection lost.",
    # RTK
    "RTK fix! acquired.",
    "RTK fix! lost.",
    "RTK! signal lost.",
    # Battery
    "Battery low, 20 percent remaining.",
    "Battery low, 15 percent remaining.",
    "Warning! Battery critical, 10 percent remaining.",
    "Warning! Battery critical, 5 percent remaining.",
    # Obstacle detection
    "Obstacle detection enabled.",
    "Obstacle detection disabled.",
    # Skip
    "Waypoint skipped.",
    "Waypoint skipped. Heading to next target.",
    # Mission modes
    "Auto mode",
    "Manual mode",
    "Continuous mode",
    "Dash mode",
    # Vehicle init
    "Way to Mark initialised!",
    "Good morning!",
    "Good afternoon!",
    "Good evening!",
    # Language
    "Language set to English.",
    "Language set to Hindi.",
    "Language set to Tamil.",
]

_STATIC_PHRASES_HI = [
    # Mission events
    "मिशन लोड हो गया",
    "मिशन शुरू हो गया, चलते हैं",
    "मिशन रुक गया, object बहुत करीब है",
    "मिशन पूरा हुआ",
    "मिशन रुक गया.",
    "मिशन फिर से शुरू.",
    "मिशन बंद.",
    # Vehicle connection
    "चेतावनी! वाहन कनेक्शन टूट गया.",
    # RTK
    "आर टी के फिक्स मिल गया.",
    "आर टी के फिक्स खो गया.",
    "आर टी के सिग्नल खो गया.",
    # Battery
    "बैटरी कम, 20 प्रतिशत बाकी.",
    "बैटरी कम, 15 प्रतिशत बाकी.",
    "चेतावनी! बैटरी गंभीर, 10 प्रतिशत बाकी.",
    "चेतावनी! बैटरी गंभीर, 5 प्रतिशत बाकी.",
    # Obstacle detection
    "बाधा पहचान चालू.",
    "बाधा पहचान बंद.",
    # Skip
    "वेपॉइंट स्किप हो गया.",
    # Mission modes
    "ऑटो मोड",
    "मैनुअल मोड",
    "कंटीन्यूअस मोड",
    "डैश मोड",
    # Vehicle init
    "वे टू मार्क शुरू हो गया!",
    "सुप्रभात!",
    "नमस्कार!",
    "शुभ संध्या!",
    # Language
    "भाषा अंग्रेजी में सेट.",
    "भाषा हिंदी में सेट.",
    "भाषा तमिल में सेट.",
]
_CACHE_DIR = "/home/flash/NRP_ROS/Backend/tts_audio"
_audio_cache: dict[str, str] = {}  # text -> wav file path
_cache_lock = threading.Lock()
mission_just_resumed = False  # Flag for resume->waypoint ordering
mission_just_skipped = False  # Flag for skip->waypoint ordering


_PIPER_MODELS = {
    "en": "/home/flash/.local/share/piper/models/en_US-ryan-medium.onnx",
    "hi": "/home/flash/.local/share/piper/models/hi_IN-rohan-medium.onnx",
}


def _generate_to_cache(text: str, lang: str = "en") -> Optional[str]:
    """Generate audio via Piper server (en) or CLI (hi) and save to cache. Returns wav path."""
    import json, hashlib
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        key = hashlib.md5(text.encode()).hexdigest()[:12]
        wav_path = os.path.join(_CACHE_DIR, f"{key}.wav")

        if lang == "en":
            # Use Piper HTTP server for English (already warm)
            payload = json.dumps({"text": text}).encode("utf-8")
            req = Request(
                _PIPER_SERVER_URL + "/",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=15)
            wav_data = resp.read()
            if not wav_data or len(wav_data) < 100:
                return None
            with open(wav_path, "wb") as f:
                f.write(wav_data)
        else:
            # Use Piper CLI for other languages
            model = _PIPER_MODELS.get(lang)
            if not model or not os.path.exists(model):
                print(f"[TTS] No Piper model for lang={lang}", flush=True)
                return None
            result = subprocess.run(
                ["piper", "--model", model, "--output-file", wav_path],
                input=text, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 or not os.path.exists(wav_path):
                return None

        return wav_path
    except Exception as e:
        print(f"[TTS] Cache generate failed ({lang}): {e}", flush=True)
        return None


def precache_mission(total_waypoints: int):
    """Pre-generate all mission waypoint audio in background thread."""
    import hashlib

    def _do_cache():
        os.makedirs(_CACHE_DIR, exist_ok=True)

        # English per-waypoint phrases
        en_phrases = []
        for wp in range(1, total_waypoints + 1):
            en_phrases.append(f"Heading to target {wp}")
            en_phrases.append(f"Target {wp} reached")
            en_phrases.append(f"Target {wp} done")

        # Hindi per-waypoint phrases
        hi_phrases = []
        for wp in range(1, total_waypoints + 1):
            hi_phrases.append(f"लक्ष्य {wp} की तरफ जा रहे हैं")
            hi_phrases.append(f"लक्ष्य {wp} पहुँच गए")
            hi_phrases.append(f"लक्ष्य {wp} पूरा हो गया")

        all_phrases = [(p, "en") for p in en_phrases] + [(p, "hi") for p in hi_phrases]

        loaded = 0
        to_generate = []
        for phrase, lang in all_phrases:
            with _cache_lock:
                if phrase in _audio_cache:
                    loaded += 1
                    continue
            key = hashlib.md5(phrase.encode()).hexdigest()[:12]
            wav_path = os.path.join(_CACHE_DIR, f"{key}.wav")
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
                with _cache_lock:
                    _audio_cache[phrase] = wav_path
                loaded += 1
            else:
                to_generate.append((phrase, lang))

        print(f"[TTS] Mission: {loaded} loaded, {len(to_generate)} to generate", flush=True)
        generated = 0
        for phrase, lang in to_generate:
            wav_path = _generate_to_cache(phrase, lang=lang)
            if wav_path:
                with _cache_lock:
                    _audio_cache[phrase] = wav_path
                generated += 1
        if generated:
            print(f"[TTS] Mission: generated {generated} new phrases", flush=True)

    t = threading.Thread(target=_do_cache, daemon=True)
    t.start()


def flush():
    """Clear all pending TTS items from the queue."""
    _worker.flush()


def speak(text: str, async_: bool = True, engine: Optional[str] = None):
    """Queue or synchronously speak text. Default: non-blocking."""
    if not _ENABLE_VOICE:
        return

    # All audio goes through the queue so phrases play sequentially
    if async_:
        _worker.enqueue(text)
    else:
        if _worker._should_speak(text):
            _worker._speak_impl(text)


def _load_or_generate_cache():
    """Load existing audio from disk, generate missing ones via Piper server."""
    import hashlib

    def _do():
        os.makedirs(_CACHE_DIR, exist_ok=True)
        loaded = 0
        to_generate = []

        # Load existing files from disk
        for phrase in _STATIC_PHRASES:
            key = hashlib.md5(phrase.encode()).hexdigest()[:12]
            wav_path = os.path.join(_CACHE_DIR, f"{key}.wav")
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
                with _cache_lock:
                    _audio_cache[phrase] = wav_path
                loaded += 1
            else:
                to_generate.append(phrase)

        # Also load Hindi phrases from disk
        hi_to_generate = []
        for phrase in _STATIC_PHRASES_HI:
            key = hashlib.md5(phrase.encode()).hexdigest()[:12]
            wav_path = os.path.join(_CACHE_DIR, f"{key}.wav")
            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
                with _cache_lock:
                    _audio_cache[phrase] = wav_path
                loaded += 1
            else:
                hi_to_generate.append(phrase)

        print(f"[TTS] Loaded {loaded} phrases from disk, {len(to_generate)} EN + {len(hi_to_generate)} HI to generate", flush=True)

        if not to_generate and not hi_to_generate:
            return

        # Wait for Piper server to be ready before generating
        import time
        time.sleep(3)
        generated = 0
        for phrase in to_generate:
            wav_path = _generate_to_cache(phrase, lang="en")
            if wav_path:
                with _cache_lock:
                    _audio_cache[phrase] = wav_path
                generated += 1
        if generated:
            print(f"[TTS] Generated {generated} EN phrases", flush=True)

        hi_generated = 0
        for phrase in hi_to_generate:
            wav_path = _generate_to_cache(phrase, lang="hi")
            if wav_path:
                with _cache_lock:
                    _audio_cache[phrase] = wav_path
                hi_generated += 1
        if hi_generated:
            print(f"[TTS] Generated {hi_generated} HI phrases", flush=True)

    threading.Thread(target=_do, daemon=True).start()

_load_or_generate_cache()


def shutdown():
    """Stop the background worker."""
    try:
        _worker.stop()
    except Exception:
        pass
