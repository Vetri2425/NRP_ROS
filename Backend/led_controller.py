#!/usr/bin/env python3
"""
WS2812 LED Controller for Mission State Feedback.

Swappable between two hardware configs (set LED_STRIP env var):
  - "crowtail" (default): 8 LEDs  (2x Crowtail 4-LED modules, for testing)
  - "strip":              30 LEDs (500mm 60/m WS2812 strip, for deployment)

LED State Mapping:
  idle      -> Solid Blue
  loading   -> Blue comet chase (serial light sweep @ 0.009s)
  ready     -> Solid Yellow  (mission loaded, ready to arm)
  running   -> Yellow strobe (mission running)
  paused    -> Solid Orange
  completed -> Solid Green
  error     -> Red blink (@ 0.3s)
  stopped   -> Solid Red (mission stopped by /api/mission/stop)

Hardware:
  - LED DIN  -> Jetson Pin 19 (SPI0_MOSI) -> /dev/spidev0.0
  - LED GND  -> Jetson Pin 39 (GND)
  - LED VCC  -> External 5V supply (common GND with Jetson)
  - SPI: 6.4 MHz, 8-bit encoding per WS2812 bit
    WS_0 = 0b11100000  (3 high + 5 low  -> T0H ~468ns, T0L ~781ns)
    WS_1 = 0b11111100  (6 high + 2 low  -> T1H ~937ns, T1L ~312ns)
"""

import os
import threading
import time

try:
    import spidev
    SPI_AVAILABLE = True
except ImportError:
    SPI_AVAILABLE = False

# Swappable LED count: set LED_STRIP=strip for 30-LED deployment strip
LED_PROFILES = {
    'crowtail': 8,   # 2x Crowtail 4-LED modules (testing)
    'strip':    30,  # 500mm 60 LEDs/m WS2812 strip (deployment)
}
_led_profile = os.environ.get('LED_STRIP', 'crowtail').lower()
NUM_LEDS = LED_PROFILES.get(_led_profile, 8)

SPI_SPEED_HZ = 6_400_000

# WS2812 bit encoding at 6.4 MHz (8 SPI bits per WS2812 bit)
WS_0 = 0b11100000  # T0H ~468 ns, T0L ~781 ns  (spec: 350/800 ns)
WS_1 = 0b11111100  # T1H ~937 ns, T1L ~312 ns  (spec: 700/600 ns)

# ── Animation definitions ──────────────────────────────────────────────────────
# anim_type: 'solid' | 'chase' | 'blink' | 'strobe'
ANIMATION_MAP = {
    'idle':      ('solid',  (0,   0,   255)),  # Blue solid
    'loading':   ('chase',  (0,   0,   255)),  # Blue chase (comet effect)
    'ready':     ('solid', (255, 200,   0)),  # Yellow solid (ready to arm)
    'running':   ('strobe', (255, 200,   0)),  # Yellow strobe (mission running)
    'paused':    ('solid',  (255, 128,   0)),  # Orange solid
    'completed': ('solid',  (0,   255,   0)),  # Green solid
    'error':     ('blink',  (255,   0,   0)),  # Red blink
    'stopped':   ('solid',  (255,   0,   0)),  # Red solid (mission stopped)
}

BLINK_INTERVAL = 0.3   # seconds per half-cycle (on or off)
CHASE_INTERVAL = 0.009   # seconds per chase step
STROBE_INTERVAL = 0.009  # seconds per LED in strobe effect (fast one-by-one)


# ── SPI encoding ──────────────────────────────────────────────────────────────

def _color_to_spi_bytes(r, g, b):
    """Encode one RGB pixel into 24 SPI bytes (GRB order, 8 SPI bits per WS2812 bit)."""
    out = []
    for byte_val in (g, r, b):   # WS2812 wire order: Green, Red, Blue
        for bit in range(7, -1, -1):
            out.append(WS_1 if (byte_val & (1 << bit)) else WS_0)
    return out


def _scale(color, factor):
    """Scale an RGB tuple by factor (0.0–1.0), clamped to uint8."""
    return tuple(max(0, min(255, int(c * factor))) for c in color)


# ── Controller ────────────────────────────────────────────────────────────────

class LEDController:
    """Thread-safe WS2812 LED controller for mission state feedback."""

    def __init__(self, num_leds=None, logger=None):
        self.logger = logger
        self.num_leds = num_leds if num_leds is not None else NUM_LEDS
        self.spi = None
        self._current_state = 'idle'
        self._lock = threading.Lock()
        self._running = True

        if not SPI_AVAILABLE:
            self._log("spidev not installed - LED controller disabled", "warning")
            return

        try:
            self.spi = spidev.SpiDev()
            self.spi.open(0, 0)
            self.spi.max_speed_hz = SPI_SPEED_HZ
            self.spi.mode = 0
            self._log(
                f"LED controller initialized "
                f"({self.num_leds} LEDs, profile='{_led_profile}', /dev/spidev0.0)"
            )
        except Exception as e:
            self._log(f"Failed to open SPI - LED controller disabled: {e}", "warning")
            self.spi = None
            return

        # Start idle (blue solid) immediately
        self._send_solid((0, 0, 255))

        self._anim_thread = threading.Thread(
            target=self._animation_loop, daemon=True, name="led-anim"
        )
        self._anim_thread.start()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log(self, message, level="info"):
        msg = f"[LED] {message}"
        print(msg, flush=True)
        if self.logger:
            try:
                getattr(self.logger, level, self.logger.info)(msg)
            except Exception:
                pass

    def _send_pixels(self, pixels):
        """Write a list of (r, g, b) tuples to the strip."""
        if not self.spi:
            return
        try:
            spi_data = []
            for (r, g, b) in pixels:
                spi_data.extend(_color_to_spi_bytes(r, g, b))
            spi_data.extend([0x00] * 200)   # >50 µs reset pulse
            self.spi.xfer2(spi_data)
        except Exception as e:
            self._log(f"SPI write error: {e}", "error")

    def _send_solid(self, color):
        self._send_pixels([color] * self.num_leds)

    def _send_off(self):
        self._send_solid((0, 0, 0))

    def _send_chase_frame(self, pos, color):
        """Comet frame: bright head at pos, two-step dimming tail behind it."""
        pixels = [(0, 0, 0)] * self.num_leds
        n = self.num_leds
        pixels[pos % n] = color
        pixels[(pos - 1) % n] = _scale(color, 0.20)
        pixels[(pos - 2) % n] = _scale(color, 0.05)
        self._send_pixels(pixels)

    def _send_strobe_frame(self, pos, color):
        """Strobe frame: single LED lit at position (fast one-by-one effect)."""
        pixels = [(0, 0, 0)] * self.num_leds
        pixels[pos % self.num_leds] = color
        self._send_pixels(pixels)

    # ── Animation loop ────────────────────────────────────────────────────────

    def _animation_loop(self):
        """Background thread drives blink, chase, and strobe animations."""
        blink_on  = True
        chase_pos = 0
        strobe_pos = 0
        last_state: str = ""

        while self._running:
            with self._lock:
                state = self._current_state
                # Check for custom state
                custom_color = getattr(self, '_custom_color', None)
                custom_effect = getattr(self, '_custom_effect', None)

            # Determine animation type and color
            if state.startswith('custom_'):
                # Custom state - use stored color and effect
                if custom_color is not None and custom_effect is not None:
                    anim_type = custom_effect
                    color = custom_color
                else:
                    anim_type = 'solid'
                    color = (0, 0, 255)
            else:
                anim_type, color = ANIMATION_MAP.get(state, ('solid', (0, 0, 255)))

            # Reset animation counters whenever state changes
            if state != last_state:
                blink_on  = True
                chase_pos = 0
                strobe_pos = 0
                last_state = state
                # Fire the first frame immediately so the change is instant
                if anim_type == 'chase':
                    self._send_chase_frame(0, color)
                elif anim_type == 'strobe':
                    self._send_strobe_frame(0, color)
                elif anim_type == 'blink':
                    self._send_solid(color)
                # solid states are sent synchronously in update_state

            if anim_type == 'chase':
                chase_pos = (chase_pos + 1) % self.num_leds
                self._send_chase_frame(chase_pos, color)
                time.sleep(CHASE_INTERVAL)

            elif anim_type == 'strobe':
                strobe_pos = (strobe_pos + 1) % self.num_leds
                self._send_strobe_frame(strobe_pos, color)
                time.sleep(STROBE_INTERVAL)

            elif anim_type == 'blink':
                blink_on = not blink_on
                if blink_on:
                    self._send_solid(color)
                else:
                    self._send_off()
                time.sleep(BLINK_INTERVAL)

            else:
                # Solid — nothing to drive, let update_state handle it
                time.sleep(0.05)

    # ── Public API ────────────────────────────────────────────────────────────

    def update_state(self, mission_state: str, _event_type=None):
        """Switch LED pattern based on mission state.

        Args:
            mission_state: 'idle' | 'loading' | 'ready' | 'running' |
                           'paused' | 'completed' | 'error' | 'stopped'
            event_type: optional string (unused, reserved for future use)
        """
        if not self.spi:
            return

        with self._lock:
            if mission_state == self._current_state:
                return
            self._current_state = mission_state

        anim_type, color = ANIMATION_MAP.get(mission_state, ('solid', (0, 0, 255)))

        # For solid states send immediately so the response feels instant.
        # Animated states are driven by _animation_loop (which detects the
        # state change and fires the first frame without waiting for a sleep).
        if anim_type == 'solid':
            self._send_solid(color)

        self._log(f"State -> {mission_state} ({anim_type} {color})")

    def set_custom(self, color: tuple, effect_type: str):
        """Set custom LED color and effect.

        Args:
            color: RGB tuple (r, g, b) with values 0-255
            effect_type: 'solid' | 'blink' | 'chase' | 'strobe'
        """
        if not self.spi:
            return

        # Validate effect type
        valid_effects = ['solid', 'blink', 'chase', 'strobe']
        if effect_type not in valid_effects:
            self._log(f"Invalid effect type: {effect_type}", "error")
            return

        # Validate color
        if not isinstance(color, (tuple, list)) or len(color) != 3:
            self._log(f"Invalid color: {color}", "error")
            return

        # Clamp color values
        color = tuple(max(0, min(255, int(c))) for c in color)

        # Use a special state name for custom patterns
        custom_state = f"custom_{effect_type}_{color}"

        with self._lock:
            self._current_state = custom_state
            self._custom_color = color
            self._custom_effect = effect_type

        # For solid effect, send immediately
        if effect_type == 'solid':
            self._send_solid(color)

        self._log(f"Custom -> {effect_type} {color}")

    def shutdown(self):
        """Turn off all LEDs and release the SPI device."""
        self._running = False
        if self.spi:
            try:
                self._send_off()
                self.spi.close()
                self._log("LED controller shut down")
            except Exception:
                pass
            self.spi = None
