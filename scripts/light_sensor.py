"""Peachy head-camera brightness — never uses the laptop webcam.

Reads JPEG frames from the robot (/tmp/peachy_live.jpg when preview is on,
otherwise a fast cam-snap). Used by watch-room.py, light_probe.py, dashboard.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

def _load_tune() -> dict:
    try:
        data = json.loads((_REPO / ".run" / "light_tune.json").read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return {}


def _tuned(key: str, env: str, default: str) -> float:
    tune = _load_tune()
    if key in tune:
        return float(tune[key])
    return float(os.environ.get(env, default))


ON_DELTA = _tuned("on_delta", "REACHY_LIGHT_ON_DELTA", "25")
OFF_DELTA = _tuned("off_delta", "REACHY_LIGHT_OFF_DELTA", "12")
EMA_ALPHA = float(os.environ.get("REACHY_LIGHT_EMA", "0.35"))
SLOW_ALPHA = float(os.environ.get("REACHY_LIGHT_SLOW_EMA", "0.01"))
_LIGHT_QUALITY = int(os.environ.get("REACHY_LIGHT_QUALITY", "28"))
_LIGHT_SCALE = float(os.environ.get("REACHY_LIGHT_SCALE", "0.32"))
_LIGHT_WARMUP = float(os.environ.get("REACHY_LIGHT_WARMUP", "0.08"))
_MIN_JPEG = int(os.environ.get("REACHY_LIGHT_MIN_JPEG", "180"))

_PREVIEW_RMT = "/tmp/peachy_live.jpg"
_SNAP_RMT = "/tmp/peachy_light_probe.jpg"


def _ssh_base() -> list[str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=10"]
    port = os.environ.get("REACHY_SSH_PORT", "").strip()
    if port:
        cmd += ["-p", port]
    return cmd


def _scp_base() -> list[str]:
    cmd = ["scp", "-o", "ConnectTimeout=10"]
    port = os.environ.get("REACHY_SSH_PORT", "").strip()
    if port:
        cmd += ["-P", port]
    return cmd


def _ssh_target() -> str:
    t = os.environ.get("REACHY_SSH", "").strip()
    if t:
        return t
    host = os.environ.get("REACHY_HOST", "reachy-mini.local")
    return f"pollen@{host}"


def _on_robot() -> bool:
    return os.environ.get("REACHY_ON_ROBOT", "").lower() in ("1", "true", "yes")


def _jpeg_mean_luma(path: Path) -> float:
    sys.path.insert(0, str(_REPO / "scripts"))
    from light_lab import roi_mean_luma

    return roi_mean_luma(path)


def _light_snap_args(out: str, *, remote: bool = False) -> list[str]:
    q = max(12, min(60, _LIGHT_QUALITY))
    w = max(0.05, min(0.25, _LIGHT_WARMUP))
    args = ["--out", out, "--no-wake", "--fast", "--quality", str(q), "--warmup", f"{w:.2f}"]
    if not remote:
        sc = max(0.12, min(0.5, _LIGHT_SCALE))
        args += ["--scale", f"{sc:.2f}"]
    return args


def _local_preview_path() -> Path | None:
    p = Path(_PREVIEW_RMT)
    if p.is_file() and p.stat().st_size > _MIN_JPEG:
        return p
    return None


def _jpeg_ok(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > _MIN_JPEG


def _fetch_robot_jpeg(dest: Path) -> bool:
    """Copy a robot camera JPEG to *dest*. Returns True on success."""
    if _on_robot():
        src = _local_preview_path()
        if src:
            shutil.copy2(src, dest)
            return True
        snap = subprocess.run(
            ["/venvs/apps_venv/bin/python3", str(_REPO / "scripts" / "cam-snap.py"),
             *_light_snap_args(str(dest), remote=False)],
            capture_output=True, timeout=20, cwd=_REPO)
        return snap.returncode == 0 and _jpeg_ok(dest)

    ssh_t = _ssh_target()
    try:
        p = subprocess.run(
            [*_scp_base(), f"{ssh_t}:{_PREVIEW_RMT}", str(dest)],
            capture_output=True, timeout=8)
        if p.returncode == 0 and _jpeg_ok(dest):
            return True
    except subprocess.TimeoutExpired:
        pass

    snap_args = " ".join(_light_snap_args(_SNAP_RMT, remote=True))
    py = "/venvs/apps_venv/bin/python3"
    for script in (f"{py} ~/peachy/scripts/cam-snap.py {snap_args}",
                   f"{py} scripts/cam-snap.py {snap_args}"):
        try:
            p1 = subprocess.run([*_ssh_base(), ssh_t, script],
                                capture_output=True, timeout=22)
            if p1.returncode != 0:
                continue
            p2 = subprocess.run(
                [*_scp_base(), f"{ssh_t}:{_SNAP_RMT}", str(dest)],
                capture_output=True, timeout=8)
            if p2.returncode == 0 and _jpeg_ok(dest):
                return True
        except subprocess.TimeoutExpired:
            continue
    return False


_REANCHOR_FILE = _REPO / ".run" / "light_reanchor.json"
_CONFIRM_LOG = _REPO / ".run" / "light_confirmations.jsonl"


def schedule_reanchor(*, ref: float, ema: float | None = None, lit: bool | None = None) -> None:
    """Ask watch-room / dashboard sensor to snap adaptive ref on next read."""
    _REANCHOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    _REANCHOR_FILE.write_text(json.dumps({
        "t": time.time(),
        "ref": round(ref, 2),
        "ema": round(ema, 2) if ema is not None else None,
        "lit": lit,
    }) + "\n")


def apply_reanchor(sensor: "LightSensor") -> bool:
    """Apply a pending teacher re-anchor (consumes the file)."""
    try:
        data = json.loads(_REANCHOR_FILE.read_text())
        if time.time() - float(data.get("t", 0)) > 120:
            _REANCHOR_FILE.unlink(missing_ok=True)
            return False
        sensor.slow = float(data["ref"])
        if data.get("ema") is not None:
            sensor.ema = float(data["ema"])
        if "lit" in data and data["lit"] is not None:
            sensor._lit = bool(data["lit"])
        _REANCHOR_FILE.unlink(missing_ok=True)
        return True
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        return False


class LightSensor:
    """Head-camera mean-luma with hysteresis (lit vs dark)."""

    def __init__(self) -> None:
        self._tmp = Path(tempfile.gettempdir()) / "peachy_light_probe.jpg"
        self.dark_level: float | None = None
        self._lit = False
        self.raw: float = 0.0
        self.ema: float | None = None
        self.slow: float | None = None
        self.adaptive = True
        self.motion: float = 0.0
        self._prev_luma: float | None = None
        self.last_source: str = ""

    def _lock_exposure(self) -> None:
        """No-op — robot camera auto-exposure; kept for watch-room API compat."""

    def read(self) -> float | None:
        if not _fetch_robot_jpeg(self._tmp):
            return None
        self.last_source = "preview" if _on_robot() else "robot"
        try:
            self.raw = _jpeg_mean_luma(self._tmp)
        except OSError:
            return None
        if self._prev_luma is not None:
            self.motion = abs(self.raw - self._prev_luma)
        self._prev_luma = self.raw
        a = EMA_ALPHA
        self.ema = self.raw if self.ema is None else (1 - a) * self.ema + a * self.raw
        if self.slow is None:
            self.slow = self.raw
        elif not self._lit or self.raw < self.slow:
            self.slow += SLOW_ALPHA * (self.raw - self.slow)
        # Ref can stay high after lights-off; drag it down when clearly dark.
        on_d = _tuned("on_delta", "REACHY_LIGHT_ON_DELTA", "25")
        if (
            self.slow is not None
            and self.ema is not None
            and not self._lit
            and self.ema < self.slow - on_d * 0.35
        ):
            self.slow = 0.82 * self.slow + 0.18 * self.ema
        return self.ema

    def calibrate_dark(self, seconds: float = 2.0) -> float:
        vals: list[float] = []
        end = time.time() + seconds
        while time.time() < end:
            v = self.read()
            if v is not None:
                vals.append(v)
            time.sleep(max(0.15, seconds / 8))
        self.dark_level = (sum(vals) / len(vals)) if vals else 0.0
        self.ema = self.dark_level
        self.slow = self.dark_level
        return self.dark_level

    def lit(self, *, fresh: bool = True) -> bool:
        v = self.read() if fresh or self.ema is None else self.ema
        if v is None:
            return self._lit
        on_d = _tuned("on_delta", "REACHY_LIGHT_ON_DELTA", "25")
        off_d = _tuned("off_delta", "REACHY_LIGHT_OFF_DELTA", "12")
        ref = self.slow if self.adaptive else self.dark_level
        if ref is None:
            return self._lit
        if not self._lit and v >= ref + on_d:
            self._lit = True
        elif self._lit and v <= ref + off_d:
            self._lit = False
        return self._lit

    @property
    def reference(self) -> float:
        r = self.slow if self.adaptive else self.dark_level
        return r if r is not None else 0.0

    def snapshot(self) -> dict:
        sys.path.insert(0, str(_REPO / "scripts"))
        from light_lab import preferred_roi

        on_d = _tuned("on_delta", "REACHY_LIGHT_ON_DELTA", "25")
        off_d = _tuned("off_delta", "REACHY_LIGHT_OFF_DELTA", "12")
        return {
            "raw": round(self.raw, 1),
            "ema": round(self.ema or 0, 1),
            "ref": round(self.reference, 1),
            "delta": round((self.ema or 0) - self.reference, 1),
            "lit": self._lit,
            "motion": round(self.motion, 1),
            "on_delta": on_d,
            "off_delta": off_d,
            "source": "peachy_camera",
            "roi": preferred_roi(),
        }

    def close(self) -> None:
        try:
            self._tmp.unlink(missing_ok=True)
        except OSError:
            pass
