"""Idle motion patch — scale + occasional burst fidgets (not constant sway)."""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np

logger = logging.getLogger(__name__)

MIN_SCALE = 0.0
MAX_SCALE = 1.5
DEFAULT_SCALE = 0.55
MIN_CADENCE = 6.0
MAX_CADENCE = 90.0
DEFAULT_CADENCE = 22.0
MIN_BURST = 0.5
MAX_BURST = 8.0
DEFAULT_BURST = 2.2

_PATCH_DIR = Path(__file__).resolve().parent
if (_PATCH_DIR.parent / "dashboard").is_dir():
    _RUN = _PATCH_DIR.parent / ".run"
else:
    _RUN = Path(os.environ.get("REACHY_RUN_DIR", Path.home() / ".run"))
_SCALE_FILE = Path(os.environ.get("REACHY_IDLE_MOTION_FILE", _RUN / "idle_motion_scale.json"))

_settings: dict[str, float] = {
    "scale": DEFAULT_SCALE,
    "cadence_s": DEFAULT_CADENCE,
    "burst_s": DEFAULT_BURST,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _load_persisted() -> None:
    global _settings
    try:
        if _SCALE_FILE.is_file():
            data = json.loads(_SCALE_FILE.read_text())
            if isinstance(data, dict):
                _settings["scale"] = _clamp(
                    data.get("scale", DEFAULT_SCALE), MIN_SCALE, MAX_SCALE
                )
                _settings["cadence_s"] = _clamp(
                    data.get("cadence_s", DEFAULT_CADENCE), MIN_CADENCE, MAX_CADENCE
                )
                _settings["burst_s"] = _clamp(
                    data.get("burst_s", DEFAULT_BURST), MIN_BURST, MAX_BURST
                )
                return
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    env_scale = os.environ.get("REACHY_IDLE_MOTION_SCALE")
    if env_scale:
        try:
            _settings["scale"] = _clamp(float(env_scale), MIN_SCALE, MAX_SCALE)
        except ValueError:
            pass


def _save() -> None:
    _SCALE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: round(v, 3) for k, v in _settings.items()}
    _SCALE_FILE.write_text(json.dumps(payload, indent=2) + "\n")


_load_persisted()


def get_idle_motion_settings() -> dict[str, float]:
    return dict(_settings)


def get_idle_motion_scale() -> float:
    return _settings["scale"]


def set_idle_motion_settings(
    *,
    scale: float | None = None,
    cadence_s: float | None = None,
    burst_s: float | None = None,
) -> dict[str, float]:
    if scale is not None:
        _settings["scale"] = _clamp(scale, MIN_SCALE, MAX_SCALE)
    if cadence_s is not None:
        _settings["cadence_s"] = _clamp(cadence_s, MIN_CADENCE, MAX_CADENCE)
    if burst_s is not None:
        burst = _clamp(burst_s, MIN_BURST, MAX_BURST)
        _settings["burst_s"] = min(burst, _settings["cadence_s"] * 0.6)
    _save()
    return get_idle_motion_settings()


def mount_idle_motion_routes(app: Any) -> None:
    try:
        from fastapi import Query
        from fastapi.responses import JSONResponse
    except ImportError:
        return

    @app.get("/idle-motion")
    def _idle_motion_get() -> dict[str, float]:
        s = get_idle_motion_settings()
        return {
            "scale": s["scale"],
            "cadence_s": s["cadence_s"],
            "burst_s": s["burst_s"],
            "min_scale": MIN_SCALE,
            "max_scale": MAX_SCALE,
            "min_cadence_s": MIN_CADENCE,
            "max_cadence_s": MAX_CADENCE,
            "min_burst_s": MIN_BURST,
            "max_burst_s": MAX_BURST,
        }

    @app.post("/idle-motion/apply")
    def _idle_motion_apply(
        scale: float | None = Query(None),
        cadence_s: float | None = Query(None),
        burst_s: float | None = Query(None),
    ) -> dict[str, Any]:
        if scale is None and cadence_s is None and burst_s is None:
            return JSONResponse({"ok": False, "error": "missing_params"}, status_code=400)
        applied = set_idle_motion_settings(scale=scale, cadence_s=cadence_s, burst_s=burst_s)
        return {"ok": True, **applied}


def apply_patches() -> None:
    import gradio as gr

    from reachy_mini_conversation_app import headless_personality_ui, moves
    from reachy_mini.utils import create_head_pose

    if getattr(moves.BreathingMove.evaluate, "_peachy_idle_patched", False):
        return

    _orig_evaluate = moves.BreathingMove.evaluate
    _neutral_head = create_head_pose(0, 0, 0, 0, 0, 0, degrees=True)
    _neutral_ant = np.array([-0.1745, 0.1745])

    def _scaled_evaluate(self: moves.BreathingMove, t: float):
        settings = get_idle_motion_settings()
        scale = settings["scale"]
        cadence = settings["cadence_s"]
        burst = min(settings["burst_s"], cadence * 0.6)

        if not hasattr(self, "_peachy_base_z"):
            self._peachy_base_z = self.breathing_z_amplitude
            self._peachy_base_ant = self.antenna_sway_amplitude

        if t < self.interpolation_duration:
            return _orig_evaluate(self, t)

        if scale <= 0.01:
            return _neutral_head.copy(), _neutral_ant.astype(np.float64), 0.0

        idle_t = t - self.interpolation_duration
        phase = idle_t % cadence
        if phase > burst:
            return _neutral_head.copy(), _neutral_ant.astype(np.float64), 0.0

        self.breathing_z_amplitude = self._peachy_base_z * scale
        self.antenna_sway_amplitude = self._peachy_base_ant * scale
        burst_t = phase
        z_offset = self.breathing_z_amplitude * math.sin(
            2 * math.pi * self.breathing_frequency * burst_t
        )
        head_pose = create_head_pose(x=0, y=0, z=z_offset, roll=0, pitch=0, yaw=0, degrees=True, mm=False)
        antenna_sway = self.antenna_sway_amplitude * math.sin(
            2 * math.pi * self.antenna_frequency * burst_t
        )
        antennas = np.array([antenna_sway, -antenna_sway], dtype=np.float64)
        return head_pose, antennas, 0.0

    _scaled_evaluate._peachy_idle_patched = True  # type: ignore[attr-defined]
    moves.BreathingMove.evaluate = _scaled_evaluate  # type: ignore[method-assign]

    _orig_mount = headless_personality_ui.mount_personality_routes

    def _mount_with_idle(app: Any, *args: Any, **kwargs: Any) -> None:
        _orig_mount(app, *args, **kwargs)
        mount_idle_motion_routes(app)

    headless_personality_ui.mount_personality_routes = _mount_with_idle  # type: ignore[assignment]

    _orig_gradio_mount: Callable[..., Any] = gr.mount_gradio_app

    def _gradio_mount_with_idle(fastapi_app: Any, blocks: Any, path: str = "/") -> Any:
        result = _orig_gradio_mount(fastapi_app, blocks, path=path)
        mount_idle_motion_routes(fastapi_app)
        return result

    gr.mount_gradio_app = _gradio_mount_with_idle  # type: ignore[assignment]

    s = get_idle_motion_settings()
    logger.info(
        "Peachy idle-motion patch active (scale=%.2f cadence=%.0fs burst=%.1fs)",
        s["scale"],
        s["cadence_s"],
        s["burst_s"],
    )
