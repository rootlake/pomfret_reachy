"""Hide when you say “boo”; wake with three gentle knocks on the head (wireless IMU)."""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Any, Callable

from reachy_mini import ReachyMini, ReachyMiniApp

_logger = logging.getLogger("boo_hide")

# IMU knock tuning (wireless). Override via env for your tap strength / mounting noise.
_KNOCK_DELTA_MS2 = float(os.environ.get("REACHY_KNOCK_DELTA", "2.8"))
_KNOCK_DEBOUNCE_S = float(os.environ.get("REACHY_KNOCK_DEBOUNCE", "0.22"))
_KNOCK_MIN_GAP_S = float(os.environ.get("REACHY_KNOCK_MIN_GAP", "0.14"))
_KNOCK_MAX_GAP_S = float(os.environ.get("REACHY_KNOCK_MAX_GAP", "1.15"))
_KNOCK_SEQUENCE_WINDOW_S = float(os.environ.get("REACHY_KNOCK_WINDOW", "2.8"))
_SLOW_BASELINE_ALPHA = float(os.environ.get("REACHY_KNOCK_BASELINE_ALPHA", "0.018"))


class TripleKnockDetector:
    """Impulse when acceleration magnitude moves away from a slow baseline."""

    def __init__(self) -> None:
        self._slow_baseline: float | None = None
        self._last_spike_t = 0.0
        self._knock_times: list[float] = []

    def arm(self) -> None:
        self._slow_baseline = None
        self._last_spike_t = 0.0
        self._knock_times.clear()

    def sample(self, accel: tuple[float, float, float], now: float) -> bool:
        """Return True when three spaced knocks are detected."""
        ax, ay, az = accel
        mag = math.sqrt(ax * ax + ay * ay + az * az)
        if self._slow_baseline is None:
            self._slow_baseline = mag
            return False
        a = _SLOW_BASELINE_ALPHA
        self._slow_baseline = (1.0 - a) * self._slow_baseline + a * mag
        dev = abs(mag - self._slow_baseline)
        if dev < _KNOCK_DELTA_MS2:
            return False
        if now - self._last_spike_t < _KNOCK_DEBOUNCE_S:
            return False
        self._last_spike_t = now
        self._knock_times.append(now)
        self._knock_times = [
            t for t in self._knock_times if now - t <= _KNOCK_SEQUENCE_WINDOW_S
        ]
        if len(self._knock_times) < 3:
            return False
        t1, t2, t3 = self._knock_times[-3:]
        if not (_KNOCK_MIN_GAP_S <= t2 - t1 <= _KNOCK_MAX_GAP_S):
            return False
        if not (_KNOCK_MIN_GAP_S <= t3 - t2 <= _KNOCK_MAX_GAP_S):
            return False
        self._knock_times.clear()
        _logger.info("Triple knock detected → wake_up")
        return True


def _speech_listener(stop_event: threading.Event, on_boo: Callable[[], None]) -> None:
    try:
        import speech_recognition as sr
    except ImportError:
        _logger.warning(
            "speech_recognition not installed — voice trigger disabled. "
            "Install with: uv pip install speechrecognition pyaudio"
        )
        return

    try:
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        mic = sr.Microphone()
    except Exception as e:
        _logger.warning("Microphone unavailable (%s) — use /boo from the settings page.", e)
        return

    _logger.info("Listening for “boo”…")
    with mic as source:
        try:
            r.adjust_for_ambient_noise(source, duration=0.7)
        except Exception:
            pass

    while not stop_event.is_set():
        try:
            with mic as source:
                audio = r.listen(source, timeout=3, phrase_time_limit=4)
            text = r.recognize_google(audio)
        except Exception:
            continue
        if text and "boo" in text.lower():
            _logger.info("Heard: %r → hide", text)
            on_boo()


class BooHide(ReachyMiniApp):
    custom_app_url: str | None = "http://0.0.0.0:8042"
    # LAN / classroom: avoid WebRTC signalling (ws :8443) which often times out from a laptop.
    # Voice uses ``speech_recognition`` + the laptop mic, not SDK streaming.
    request_media_backend: str | None = "no_media"

    def wrapped_run(self, *args: Any, **kwargs: Any) -> None:
        """Honor ``REACHY_HOST`` so classroom IP works without ``.local`` DNS."""
        kwargs.pop("connection_mode", None)

        host = os.environ.get("REACHY_HOST", "").strip()
        saved_daemon_local: bool | None = None
        if host:
            kwargs.setdefault("host", host)
            saved_daemon_local = self.daemon_on_localhost
            self.daemon_on_localhost = False
        try:
            super().wrapped_run(*args, **kwargs)
        finally:
            if saved_daemon_local is not None:
                self.daemon_on_localhost = saved_daemon_local

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        hide_lock = threading.Lock()
        hide_requested = False
        wake_requested = False
        last_hide_t = 0.0
        cooldown_s = 5.0
        waiting_for_knocks = False
        knock_arm_ready_t = 0.0
        knock_detector = TripleKnockDetector()
        imu_warned = False

        def request_hide() -> None:
            nonlocal hide_requested
            with hide_lock:
                hide_requested = True

        def request_wake() -> None:
            nonlocal wake_requested
            with hide_lock:
                wake_requested = True

        @self.settings_app.post("/boo")
        def boo_trigger() -> dict[str, str]:
            request_hide()
            return {"status": "queued"}

        @self.settings_app.post("/wake")
        def wake_trigger() -> dict[str, str]:
            """Simulator / Lite: manual wake without IMU knocks."""
            request_wake()
            return {"status": "queued"}

        speech_t = threading.Thread(
            target=_speech_listener,
            args=(stop_event, request_hide),
            name="boo-listener",
            daemon=True,
        )
        speech_t.start()

        reachy_mini.enable_motors()

        while not stop_event.is_set():
            with hide_lock:
                want_hide = hide_requested
                if want_hide:
                    hide_requested = False
                want_wake = wake_requested
                if want_wake:
                    wake_requested = False

            now = time.time()

            if want_wake:
                try:
                    reachy_mini.wake_up()
                    waiting_for_knocks = False
                    knock_arm_ready_t = 0.0
                    knock_detector.arm()
                    _logger.info("wake_up() complete (manual).")
                except Exception:
                    _logger.exception("wake_up failed")
                continue

            if want_hide:
                if now - last_hide_t < cooldown_s:
                    _logger.info("Cooldown active — ignoring hide.")
                else:
                    try:
                        reachy_mini.goto_sleep()
                        last_hide_t = time.time()
                        waiting_for_knocks = True
                        knock_arm_ready_t = time.time() + 0.65
                        knock_detector.arm()
                        imu_warned = False
                        _logger.info(
                            "goto_sleep() complete — tap head gently 3× to wake "
                            "(wireless IMU), or POST /wake."
                        )
                    except Exception:
                        _logger.exception("goto_sleep failed")

            if waiting_for_knocks and now >= knock_arm_ready_t:
                imu = reachy_mini.imu
                if imu is None:
                    if not imu_warned:
                        _logger.warning(
                            "No IMU (Lite / sim) — use POST /wake or the Wake button."
                        )
                        imu_warned = True
                else:
                    acc = imu["accelerometer"]
                    if isinstance(acc, (list, tuple)) and len(acc) >= 3:
                        ax, ay, az = float(acc[0]), float(acc[1]), float(acc[2])
                        try:
                            if knock_detector.sample((ax, ay, az), now):
                                reachy_mini.wake_up()
                                waiting_for_knocks = False
                                knock_arm_ready_t = 0.0
                                knock_detector.arm()
                                _logger.info("wake_up() complete (triple knock).")
                        except Exception:
                            _logger.exception("knock sampling failed")

            time.sleep(0.04)


if __name__ == "__main__":
    app = BooHide()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()
