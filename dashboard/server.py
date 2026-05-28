#!/usr/bin/env python3
"""Peachy control server — serves the phone dashboard on the LAN.

Runs on the laptop (later: on the robot as the Peachy app's web UI). Phones on
the same Wi-Fi open http://<laptop-ip>:8080/ and tap big buttons; the server
relays to the daemon by invoking the existing repo scripts (single source of
truth — no duplicated motion logic).

  ./dashboard/run.sh                 # prints the LAN URL
  python dashboard/server.py --port 8080
Env: REACHY_HOST (192.168.99.2), REACHY_PORT (8000)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

import secrets

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
import uvicorn

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
_STATIC = Path(__file__).resolve().parent / "static"
_RUN = _REPO / ".run"
_RUN.mkdir(exist_ok=True)


def _load_reachy_env() -> None:
    """Match dashboard/run.sh — subprocess scripts need REACHY_SSH from .run/reachy.env."""
    envfile = _RUN / "reachy.env"
    if not envfile.is_file():
        return
    for line in envfile.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_reachy_env()

HOST = os.environ.get("REACHY_HOST", "192.168.99.2")
PORT = int(os.environ.get("REACHY_PORT", "8000"))
_SSH_TARGET = os.environ.get("REACHY_SSH", "").strip()  # e.g. pollen@100.88.209.10 (uplink)
_SSH_PORT = os.environ.get("REACHY_SSH_PORT", "").strip()
_ON_ROBOT = os.environ.get("REACHY_ON_ROBOT", "").lower() in ("1", "true", "yes")

_CONFIRM_LOG = _RUN / "light_confirmations.jsonl"
_REANCHOR_FILE = _RUN / "light_reanchor.json"
_RW_PID = _RUN / "dashboard_roomwatch.pid"
_RW_LOG = _RUN / "dashboard_roomwatch.log"
_CONVO_PID = _RUN / "conversation_app.pid"
_CONVO_GRADIO = _RUN / "conversation_app.gradio"
_CONVO_SH = _SCRIPTS / "app-conversation.sh"
_convo_started_at: float = 0.0          # wall-clock when last start was initiated
_convo_gradio_cache: tuple[float, bool] = (0.0, False)  # (checked_at, result)
_CONVO_GRADIO_CACHE_TTL = 6.0           # max SSH-check rate (seconds)
_STATE_FILE = _RUN / "reachy_toggle_state.json"
_VOLUME_FILE = _RUN / "speaker_volume.json"
_DEFAULT_VOLUME = 100
_DEFAULT_CONVO_VOICE = "ballad"
_volume_boot_done = False
_PREVIEW_FLAG = _RUN / "cam_preview_on"
_PREVIEW_SETTINGS = _RUN / "cam_preview_settings.json"
_PREVIEW_INTERVAL_LEGACY = _RUN / "cam_preview_interval"

# Persistent light sensor — hysteresis (ema/ref/lit) must survive between HTTP polls.
_LIGHT_SENSOR = None
_LIGHT_SENSOR_LOCK = threading.Lock()
_LIGHT_HISTORY: deque[dict] = deque(maxlen=360)


def _light_payload_from_watcher(watcher: dict, on_d: float, off_d: float) -> dict:
    """Build status light dict from watch-room log line (same sensor as the state machine)."""
    ref = float(watcher.get("ref") or 0)
    ema = float(watcher.get("ema") or 0)
    delta = float(watcher.get("delta") if watcher.get("delta") is not None else ema - ref)
    lit = bool(watcher.get("lit"))
    would_lit = ema >= ref + on_d
    would_dark = ema <= ref + off_d
    entry = {
        "t": time.time(),
        "ts": watcher.get("t") or time.strftime("%H:%M:%S"),
        "raw": watcher.get("raw"),
        "ema": ema,
        "ref": ref,
        "delta": delta,
        "lit": lit,
        "would_lit": would_lit,
        "on_threshold": round(ref + on_d, 1),
        "off_threshold": round(ref + off_d, 1),
    }
    if not _LIGHT_HISTORY or _LIGHT_HISTORY[-1].get("ts") != entry["ts"]:
        _LIGHT_HISTORY.append(entry)
    return {
        "ok": True,
        "raw": watcher.get("raw"),
        "ema": ema,
        "ref": ref,
        "delta": delta,
        "lit": lit,
        "would_lit": would_lit,
        "would_dark": would_dark,
        "motion": watcher.get("motion"),
        "on_threshold": entry["on_threshold"],
        "off_threshold": entry["off_threshold"],
        "source": "roomwatch_log",
    }


def _reset_dashboard_light_sensor() -> None:
    global _LIGHT_SENSOR
    with _LIGHT_SENSOR_LOCK:
        _LIGHT_SENSOR = None


def _dashboard_light_read() -> dict:
    global _LIGHT_SENSOR
    sys.path.insert(0, str(_SCRIPTS))
    from light_lab import effective_off_delta, effective_on_delta

    with _LIGHT_SENSOR_LOCK:
        if _LIGHT_SENSOR is None:
            from light_sensor import LightSensor
            _LIGHT_SENSOR = LightSensor()
        sensor = _LIGHT_SENSOR
        sensor.read()
        sensor.lit(fresh=False)
        snap = sensor.snapshot()
    on_d = effective_on_delta()
    off_d = effective_off_delta()
    ref = float(snap.get("ref") or 0)
    ema = float(snap.get("ema") or 0)
    would_lit = ema >= ref + on_d
    would_dark = ema <= ref + off_d
    entry = {
        "t": time.time(),
        "ts": time.strftime("%H:%M:%S"),
        "raw": snap.get("raw"),
        "ema": ema,
        "ref": ref,
        "delta": snap.get("delta"),
        "lit": bool(snap.get("lit")),
        "would_lit": would_lit,
        "on_threshold": round(ref + on_d, 1),
        "off_threshold": round(ref + off_d, 1),
    }
    _LIGHT_HISTORY.append(entry)
    return {
        **snap,
        "would_lit": would_lit,
        "would_dark": would_dark,
        "on_threshold": entry["on_threshold"],
        "off_threshold": entry["off_threshold"],
    }
_PREVIEW_RMT = "/tmp/peachy_live.jpg"
_PREVIEW_DEFAULTS = {
    "interval_s": 0.85,
    "quality": 32,
    "scale": 0.35,
    "mode": "stream",  # stream | motion (motion = cam-motion-watch.py)
}

_HEAD_AXES = ("x", "y", "z", "roll", "pitch", "yaw")
_LIM_PR = math.radians(38.0)

# --- access token (REQUIRED before exposing via Tailscale Funnel) -----------
# PEACHY_TOKEN env wins; else a stable secret in .run/peachy_token (auto-made).
# Set PEACHY_TOKEN=off to disable auth (trusted LAN / tunnel only).
_TOKEN_FILE = _RUN / "peachy_token"
_TOKEN = os.environ.get("PEACHY_TOKEN", "").strip()
if not _TOKEN:
    if _TOKEN_FILE.exists():
        _TOKEN = _TOKEN_FILE.read_text().strip()
    else:
        _TOKEN = secrets.token_urlsafe(18)
        _TOKEN_FILE.write_text(_TOKEN)
_AUTH_ON = _TOKEN.lower() != "off"

app = FastAPI(title="Peachy Control")
_robot_lock = threading.Lock()       # one motion action at a time
_last: dict = {"action": None, "ok": None, "msg": "", "at": 0.0}
_LOG: deque = deque(maxlen=200)      # ring buffer for verbose analysis
_FAN_HIST: deque = deque(maxlen=120)   # ~4 min at 2s polling


def _logrec(action: str, ok, msg: str = "") -> None:
    _LOG.append({
        "t": time.strftime("%H:%M:%S"),
        "action": action,
        "ok": ok,
        "msg": (msg or "")[-400:],
    })


@app.middleware("http")
async def _gate(request: Request, call_next):
    """When auth is on (Funnel/public), require the token via ?k=, the
    X-Peachy-Token header, or the peachy_token cookie. One valid ?k= visit
    drops a cookie so the SPA's fetches are authorized thereafter."""
    if not _AUTH_ON:
        return await call_next(request)
    if request.url.path in ("/api/qr", "/api/qr.png"):
        return await call_next(request)
    q = request.query_params.get("k")
    hdr = request.headers.get("x-peachy-token")
    cookie = request.cookies.get("peachy_token")
    if q and secrets.compare_digest(q, _TOKEN):
        # clean the URL and persist via cookie
        if request.method == "GET" and request.url.path == "/":
            r = RedirectResponse("/", status_code=303)
        else:
            r = await call_next(request)
        r.set_cookie("peachy_token", _TOKEN, max_age=60 * 60 * 24 * 90,
                     httponly=True, samesite="lax")
        return r
    if (hdr and secrets.compare_digest(hdr, _TOKEN)) or \
       (cookie and secrets.compare_digest(cookie, _TOKEN)):
        return await call_next(request)
    return PlainTextResponse(
        "Peachy: access token required. Open the link with ?k=<token>.",
        status_code=401)


def _script_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("REACHY_HOST", HOST)
    env.setdefault("REACHY_PORT", str(PORT))
    if _SSH_TARGET:
        env.setdefault("REACHY_SSH", _SSH_TARGET)
    if _SSH_PORT:
        env.setdefault("REACHY_SSH_PORT", _SSH_PORT)
    return env


def _run_script(args: list[str], timeout: float = 140.0) -> tuple[bool, str]:
    try:
        p = subprocess.run([sys.executable, *args], cwd=_REPO, env=_script_env(),
                           capture_output=True, text=True, timeout=timeout)
        out = (p.stdout + p.stderr).strip()
        return p.returncode == 0, out[-600:]
    except subprocess.TimeoutExpired:
        return False, "timed out (robot slow or unreachable)"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _daemon_up() -> bool:
    try:
        urllib.request.urlopen(f"http://{HOST}:{PORT}/api/state/full", timeout=3)
        return True
    except Exception:
        return False


def _daemon_json(path: str, method: str = "GET", body: dict | None = None,
                 timeout: float = 12.0) -> dict:
    url = f"http://{HOST}:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
    req = urllib.request.Request(url, method=method, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        t = r.read().decode()
        return json.loads(t) if t else {}


def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _head_offset() -> dict[str, float]:
    sys.path.insert(0, str(_SCRIPTS))
    from head_pose import resolve_home

    resolved = resolve_home()
    if resolved:
        return resolved[0]
    off = _load_state().get("head_offset", {})
    return {k: float(off.get(k, 0.0)) for k in _HEAD_AXES}


def _clamp_head(p: dict) -> dict:
    out = {k: float(p.get(k, 0.0)) for k in _HEAD_AXES}
    out["pitch"] = max(-_LIM_PR, min(_LIM_PR, out["pitch"]))
    out["roll"] = max(-_LIM_PR, min(_LIM_PR, out["roll"]))
    return out


def _enable_motors() -> None:
    _daemon_json("/api/motors/set_mode/enabled", "POST", {})


def _head_goto(pose: dict, dur: float = 0.45) -> None:
    _enable_motors()
    body = {"head_pose": _clamp_head(pose), "duration": dur, "interpolation": "minjerk",
            "antennas": [0.0, 0.0]}
    _daemon_json("/api/move/goto", "POST", body, timeout=max(12.0, dur + 8))


def _settle_head_home(dur: float = 1.0) -> bool:
    """Goto saved head home before a snap so the camera view matches Head tune."""
    sys.path.insert(0, str(_SCRIPTS))
    from head_pose import settle_home

    def _http(_h, _p, path, method, timeout=30.0, body=None):
        return _daemon_json(path, method, body, timeout=timeout)

    if settle_home(_http, HOST, PORT, dur=dur):
        time.sleep(0.35)  # brief hold so the head stops moving before capture
        return True
    return False


def _ssh_control_path() -> str | None:
    """Match net-connect.sh ssh_ctl — one mux socket for tunnel + cam-snap."""
    if not _SSH_TARGET:
        return None
    key = f"{_SSH_TARGET}:{_SSH_PORT}" if _SSH_PORT else _SSH_TARGET
    safe = key.translate(str.maketrans("/.:@", "____"))
    return str(_RUN / "ssh-ctl" / safe)


def _ssh_mux_opts() -> list[str]:
    ctl = _ssh_control_path()
    if not ctl:
        return []
    return [
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={ctl}",
        "-o", "ControlPersist=600",
    ]


def _ssh_cmd() -> list[str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=10", *_ssh_mux_opts()]
    if _SSH_PORT:
        cmd += ["-p", _SSH_PORT]
    return cmd


def _scp_cmd() -> list[str]:
    # -p preserves source mtime so frame_ts in the dashboard reflects when the
    # robot's preview loop actually wrote the JPG (not "just now"). Without it,
    # scp stamps the local file with current time and a dead preview loop looks
    # forever-fresh — exactly the "camera is a lie" bug.
    cmd = ["scp", "-p",
           "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=10", *_ssh_mux_opts()]
    if _SSH_PORT:
        cmd += ["-P", _SSH_PORT]
    return cmd


def _ssh_target() -> str:
    return _SSH_TARGET or f"pollen@{HOST}"


def _preview_marked_on() -> bool:
    return _PREVIEW_FLAG.exists()


def _dashboard_on_robot() -> bool:
    """True when this process runs on the CM4 (systemd), not the teacher laptop."""
    if _ON_ROBOT:
        return True
    return not _SSH_TARGET and HOST in ("127.0.0.1", "localhost")


def _kill_preview_local() -> None:
    subprocess.run(
        ["pkill", "-f", "cam-preview-loop.py"],
        capture_output=True, timeout=4)
    subprocess.run(
        ["pkill", "-f", "cam-motion-watch.py"],
        capture_output=True, timeout=4)


def _snap_local(out: Path, *, fast: bool = False,
                warmup: float | None = None) -> tuple[bool, str]:
    """Run cam-snap.py in-process on the robot — no SSH loopback."""
    t0 = time.time()
    args = [str(_SCRIPTS / "cam-snap.py"), "--out", str(out)]
    if fast:
        q = _preview_settings()["quality"]
        sc = _preview_settings()["scale"]
        w = 0.6 if warmup is None else max(0.2, min(2.5, float(warmup)))
        args += ["--no-wake", "--warmup", f"{w:.2f}",
                 "--quality", str(q), "--scale", f"{sc:.2f}"]
    ok, msg = _run_script(args, timeout=25 if fast else 45)
    note = f"({time.time()-t0:.1f}s) {msg or ('ok' if ok else 'failed')}"
    return ok, note


def _preview_loop_running() -> bool:
    for pat in ("cam-preview-loop.py", "cam-motion-watch.py"):
        try:
            p = subprocess.run(["pgrep", "-f", pat], capture_output=True, timeout=3)
            if p.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
    return False


def _start_preview_loop(cfg: dict) -> tuple[bool, str]:
    """Start cam-preview-loop or cam-motion-watch on the robot."""
    iv, q, sc = cfg["interval_s"], cfg["quality"], cfg["scale"]
    script = ("cam-motion-watch.py" if cfg["mode"] == "motion"
              else "cam-preview-loop.py")
    _kill_preview_local() if _dashboard_on_robot() else _kill_preview_remote(_ssh_target())
    cmd = (
        f"PEACHY_PREVIEW_INTERVAL={iv:.3f} PEACHY_PREVIEW_QUALITY={q} "
        f"PEACHY_PREVIEW_SCALE={sc:.3f} nohup /venvs/apps_venv/bin/python "
        f"{_SCRIPTS}/{script} {_PREVIEW_RMT} "
        f"</dev/null >>/tmp/peachy_preview.log 2>&1 & sleep 0.4; "
        f"pgrep -f {script} >/dev/null && echo ok"
    )
    try:
        if _dashboard_on_robot():
            p = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=14)
        else:
            p = subprocess.run(
                [*_ssh_cmd(), _ssh_target(), cmd],
                capture_output=True, text=True, timeout=14)
        ok = p.returncode == 0 and "ok" in (p.stdout or "")
        fps = 1.0 / iv
        tag = cfg["mode"]
        msg = (f"live ~{fps:.1g}/s q{q} {int(sc*100)}% {tag}" if ok
               else (p.stdout + p.stderr).strip()[-200:])
        return ok, msg
    except subprocess.TimeoutExpired:
        return False, "preview start timed out"


def _preview_settings() -> dict:
    s = dict(_PREVIEW_DEFAULTS)
    if _PREVIEW_SETTINGS.exists():
        try:
            s.update(json.loads(_PREVIEW_SETTINGS.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    elif _PREVIEW_INTERVAL_LEGACY.exists():
        try:
            s["interval_s"] = float(_PREVIEW_INTERVAL_LEGACY.read_text().strip())
        except (OSError, ValueError):
            pass
    s["interval_s"] = max(0.25, min(4.0, float(s.get("interval_s", 0.85))))
    s["quality"] = max(20, min(90, int(s.get("quality", 45))))
    s["scale"] = max(0.2, min(1.0, float(s.get("scale", 0.5))))
    if s.get("mode") not in ("stream", "motion"):
        s["mode"] = "stream"
    return s


def _save_preview_settings(**kwargs) -> dict:
    s = _preview_settings()
    s.update(kwargs)
    s["interval_s"] = max(0.25, min(4.0, float(s["interval_s"])))
    s["quality"] = max(20, min(90, int(s["quality"])))
    s["scale"] = max(0.2, min(1.0, float(s["scale"])))
    if s.get("mode") not in ("stream", "motion"):
        s["mode"] = "stream"
    _PREVIEW_SETTINGS.write_text(json.dumps(s, indent=0))
    return s


def _preview_interval() -> float:
    return _preview_settings()["interval_s"]


def _kill_preview_remote(ssh_t: str) -> None:
    """Stop all preview loops on the robot (pkill regex OR is unreliable over ssh)."""
    subprocess.run(
        [*_ssh_cmd(), ssh_t,
         "pkill -f cam-preview-loop.py 2>/dev/null; "
         "pkill -f cam-motion-watch.py 2>/dev/null; true"],
        capture_output=True, timeout=8)


def _jpeg_dark(path: Path) -> bool:
    """True when the frame is near-uniform black (head down / lights off)."""
    try:
        from PIL import Image
        import statistics

        px = list(Image.open(path).convert("L").getdata())
        if not px:
            return False
        step = max(1, len(px) // 4000)
        sample = px[::step]
        m = statistics.mean(sample)
        s = statistics.pstdev(sample) if len(sample) > 1 else 0.0
        return m < 30 and s < 10
    except Exception:
        return False


def _annotate_frame(payload: dict, path: Path) -> dict:
    if _jpeg_dark(path):
        payload["dark"] = True
        hint = "very dark — raise head pitch or turn on lights"
        payload["msg"] = f"{payload.get('msg', '').strip(' · ')} · {hint}".strip(" · ")
    return payload


def _fetch_snap_frame(out: Path, *, snap_warmup: float | None = None,
                      force_fresh: bool = False) -> dict:
    """Copy a frame to *out* (preview file or fresh cam-snap). No _robot_lock."""
    t0 = time.time()
    stale_after = max(6.0, 3.0 * _preview_settings()["interval_s"])
    live = Path(_PREVIEW_RMT)

    if _preview_marked_on() and not force_fresh and _preview_loop_running():
        if _dashboard_on_robot():
            try:
                if live.exists():
                    age = time.time() - live.stat().st_mtime
                    if age <= stale_after:
                        shutil.copy2(live, out)
                        ms = int((time.time() - t0) * 1000)
                        return _annotate_frame(
                            _preview_pull_payload(out, pull_ms=ms, via="live"), out)
            except OSError:
                pass
        else:
            ssh_t = _ssh_target()
            try:
                p = subprocess.run([*_scp_cmd(), f"{ssh_t}:{_PREVIEW_RMT}", str(out)],
                                   capture_output=True, text=True, timeout=12)
                if p.returncode == 0 and out.exists():
                    age = time.time() - out.stat().st_mtime
                    if age <= stale_after:
                        ms = int((time.time() - t0) * 1000)
                        return _annotate_frame(
                            _preview_pull_payload(out, pull_ms=ms, via="live"), out)
            except subprocess.TimeoutExpired:
                pass
    elif _preview_marked_on() and not _preview_loop_running():
        _PREVIEW_FLAG.unlink(missing_ok=True)

    if _dashboard_on_robot():
        ok, msg = _snap_local(out, fast=True, warmup=snap_warmup)
    else:
        ok, msg = _snap_remote(out, fast=True, warmup=snap_warmup)
    if ok and out.exists():
        ms = int((time.time() - t0) * 1000)
        payload = _preview_pull_payload(out, pull_ms=ms, via="snap")
        payload["msg"] = msg
        return _annotate_frame(payload, out)
    return {"ok": False, "msg": msg or "picture failed — camera busy?"}


def _snap_remote(out_local: Path, *, fast: bool = False,
                 warmup: float | None = None) -> tuple[bool, str]:
    """SSH snap on robot → scp to dashboard static. No _robot_lock (preview path)."""
    t0 = time.time()
    ssh_t = _ssh_target()
    rmt = _PREVIEW_RMT if fast and _preview_marked_on() else "/tmp/peachy_snap.jpg"
    snap_args = f"--out {rmt}"
    if fast:
        q = _preview_settings()["quality"]
        sc = _preview_settings()["scale"]
        w = 0.6 if warmup is None else max(0.2, min(2.5, float(warmup)))
        snap_args += f" --no-wake --warmup {w:.2f} --quality {q} --scale {sc:.2f}"
    try:
        p1 = subprocess.run(
            [*_ssh_cmd(), ssh_t,
             f"/venvs/apps_venv/bin/python ~/peachy/scripts/cam-snap.py {snap_args}"],
            capture_output=True, text=True, timeout=25 if fast else 45)
        if p1.returncode != 0:
            return False, (p1.stdout + p1.stderr).strip()[-300:]
        p2 = subprocess.run([*_scp_cmd(), f"{ssh_t}:{rmt}", str(out_local)],
                            capture_output=True, text=True, timeout=15)
        ok = p2.returncode == 0
        msg = f"({time.time()-t0:.1f}s) " + ("ok" if ok else (p2.stdout + p2.stderr).strip()[-200:])
        return ok, msg
    except subprocess.TimeoutExpired:
        return False, "ssh/scp timed out"


def _release_robot_control() -> str:
    """Stop conversation / in-flight moves so wake-sleep owns the head."""
    notes: list[str] = []
    if _conversation_running():
        subprocess.run([str(_CONVO_SH), "stop"], cwd=_REPO, env=_script_env(),
                       capture_output=True, text=True, timeout=25)
        notes.append("conversation stopped")
        time.sleep(1.8)
    try:
        _daemon_json("/api/move/stop", "POST", {}, timeout=6.0)
        notes.append("move halted")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    try:
        _daemon_json("/api/motors/set_mode/enabled", "POST", {}, timeout=8.0)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    time.sleep(0.25)
    sys.path.insert(0, str(_SCRIPTS))
    from motion_ready import ensure_motion_ready

    revived = ensure_motion_ready(HOST, PORT)
    if revived:
        notes.append(revived)
    return " · ".join(notes)


def _stop_services(*, sleep: bool = False) -> tuple[bool, str]:
    """Stop conversation, room watch, preview, and in-flight moves."""
    msgs: list[str] = []
    try:
        _daemon_json("/api/move/stop", "POST", {}, timeout=6.0)
        msgs.append("move halted")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    if _preview_marked_on():
        try:
            if _dashboard_on_robot():
                _kill_preview_local()
            else:
                _kill_preview_remote(_ssh_target())
        except (subprocess.TimeoutExpired, OSError):
            pass
        _PREVIEW_FLAG.unlink(missing_ok=True)
        msgs.append("preview stopped")
    elif _SSH_TARGET:
        try:
            _kill_preview_remote(_ssh_target())
        except (subprocess.TimeoutExpired, OSError):
            pass
    if _roomwatch_running():
        _stop_roomwatch()
        msgs.append("room watch stopped")
    if _conversation_running():
        subprocess.run([str(_CONVO_SH), "stop"], cwd=_REPO, env=_script_env(),
                       capture_output=True, timeout=25)
        msgs.append("conversation stopped")
    else:
        subprocess.run([str(_CONVO_SH), "stop"], cwd=_REPO, env=_script_env(),
                       capture_output=True, timeout=25)
    if sleep:
        released = _release_robot_control()
        ok, smsg = _run_script([str(_SCRIPTS / "ctl-toggle.py"), "sleep"], 120)
        if released:
            smsg = f"{released} · {smsg}" if smsg else released
        msgs.append("asleep" if ok else (smsg or "sleep failed"))
    note = " · ".join(msgs) or "nothing running — Peachy idle"
    return True, note


def _toggle_state() -> str:
    try:
        return json.loads(_STATE_FILE.read_text()).get("state", "unknown")
    except (FileNotFoundError, json.JSONDecodeError):
        return "unknown"


def _lan_ip() -> str:
    """Best-guess LAN IP via routing table (no packets sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "localhost"
    finally:
        s.close()


def _pid_alive(pidfile: Path) -> bool:
    try:
        os.kill(int(pidfile.read_text().strip()), 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def _roomwatch_pid() -> int | None:
    try:
        pid = int(_RW_PID.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None


def _roomwatch_cmdline(pid: int) -> str:
    try:
        p = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3,
        )
        return (p.stdout or "").strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _roomwatch_log_age_s() -> float | None:
    try:
        if not _RW_LOG.is_file():
            return None
        return max(0.0, time.time() - _RW_LOG.stat().st_mtime)
    except OSError:
        return None


def _roomwatch_running() -> bool:
    pid = _roomwatch_pid()
    if pid is None:
        return False
    if "watch-room.py" not in _roomwatch_cmdline(pid):
        _RW_PID.unlink(missing_ok=True)
        return False
    return True


def _roomwatch_healthy() -> bool:
    """Watcher process alive and log line fresh (not a stale/orphan pid)."""
    pid = _roomwatch_pid()
    if pid is None:
        return False
    if "watch-room.py" not in _roomwatch_cmdline(pid):
        return False
    age = _roomwatch_log_age_s()
    if age is None:
        return False
    try:
        size = _RW_LOG.stat().st_size
    except OSError:
        size = 0
    if size < 8:
        return age < 20.0   # just started — log not flushed yet
    return age < 45.0


def _roomwatch_light_read(on_d: float, off_d: float) -> tuple[dict, str, dict, float | None]:
    """Light telemetry for dashboard — prefer watcher log, never SSH-hammer while running."""
    log = _parse_roomwatch_log()
    watcher = log.get("last") or {}
    log_age = _roomwatch_log_age_s()
    if _roomwatch_running() and watcher:
        stale = log_age is None or log_age >= 45.0
        light = _light_payload_from_watcher(watcher, on_d, off_d)
        return light, ("roomwatch_stale" if stale else "roomwatch"), log, log_age
    try:
        light = {"ok": True, **_dashboard_light_read()}
        return light, "dashboard", log, log_age
    except OSError as e:
        return {"ok": False, "msg": str(e)[-200:]}, "error", log, log_age


def _stop_roomwatch() -> None:
    pid = _roomwatch_pid()
    if pid is not None:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
    _RW_PID.unlink(missing_ok=True)


def _start_roomwatch_proc() -> subprocess.Popen:
    logf = open(_RW_LOG, "w", buffering=1)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen(
        [sys.executable, "-u", str(_SCRIPTS / "watch-room.py")],
        cwd=_REPO, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True, env=env,
    )


def _conversation_running() -> bool:
    if _pid_alive(_CONVO_PID):
        return True
    try:
        p = subprocess.run(
            [str(_CONVO_SH), "status"],
            cwd=_REPO, env=_script_env(), capture_output=True, text=True, timeout=12,
        )
        return p.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _conversation_gradio() -> bool:
    if _CONVO_GRADIO.is_file():
        return True
    if not _conversation_running() or not _SSH_TARGET:
        return False
    try:
        p = subprocess.run(
            [*_ssh_cmd(), _ssh_target(), "ss -tln 2>/dev/null | grep -q ':7860'"],
            capture_output=True, timeout=8, env=_script_env())
        return p.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _conversation_gradio_cached() -> bool:
    """Rate-limited wrapper — SSH check at most every _CONVO_GRADIO_CACHE_TTL seconds."""
    global _convo_gradio_cache
    if _CONVO_GRADIO.is_file():
        return True
    now = time.time()
    if now - _convo_gradio_cache[0] < _CONVO_GRADIO_CACHE_TTL:
        return _convo_gradio_cache[1]
    result = _conversation_gradio()
    if result:
        try:
            _CONVO_GRADIO.touch()  # persist so future calls skip SSH
        except OSError:
            pass
    _convo_gradio_cache = (now, result)
    return result


def _convo_status() -> str:
    """Return idle | starting | ready | error — reflects actual app readiness."""
    if not _conversation_running():
        return "idle"
    if _conversation_gradio_cached():
        return "ready"
    if _CONVO_LOG.exists():
        try:
            lines = _CONVO_LOG.read_text(errors="replace").splitlines()
            recent = "\n".join(lines[-12:])
            if "ERROR" in recent and (
                "timeout" in recent.lower() or "Connection" in recent
            ):
                return "error"
        except OSError:
            pass
    return "starting"


def _gradio_url() -> str | None:
    if not _conversation_running() or not _conversation_gradio_cached():
        return None
    # Uplink / SSH tunnel: Gradio is forwarded to localhost, not the VPS tailnet IP.
    if HOST in ("127.0.0.1", "localhost"):
        return "http://127.0.0.1:7860/"
    if _SSH_TARGET:
        host = _SSH_TARGET.split("@", 1)[-1]
        return f"http://{host}:7860/"
    return f"http://{_lan_ip()}:7860/"


def _convo_base_url() -> str:
    return os.environ.get("PEACHY_CONVERSATION_GRADIO_URL", "http://127.0.0.1:7860").rstrip("/")


def _convo_api_json(path: str, *, method: str = "GET", params: dict | None = None,
                    timeout: float = 10.0) -> dict | list:
    q = urllib.parse.urlencode(params or {})
    url = f"{_convo_base_url()}{path}"
    if q:
        url = f"{url}{'&' if '?' in url else '?'}{q}"
    data = b"{}" if method == "POST" else None
    req = urllib.request.Request(url, method=method, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def _apply_convo_voice(voice: str = _DEFAULT_CONVO_VOICE) -> tuple[bool, str]:
    """Set conversation voice after start — API may need a few seconds to come up."""
    last_err = ""
    for attempt in range(10):
        if attempt:
            time.sleep(1.5)
        try:
            data = _convo_api_json(
                "/voices/apply", method="POST", params={"voice": voice}, timeout=12.0,
            )
            if isinstance(data, dict) and data.get("ok") is False:
                last_err = str(data.get("error") or data.get("status") or "failed")
                continue
            status = data.get("status", voice) if isinstance(data, dict) else voice
            return True, str(status)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
                json.JSONDecodeError) as e:
            last_err = str(e)[:200]
    return False, last_err or "voice apply timed out"


_QR_PNG = _RUN / "peachy_qr.png"
_DASH_PORT_FILE = _RUN / "peachy_dashboard.port"


def _dashboard_port() -> int:
    try:
        return int(_DASH_PORT_FILE.read_text().strip())
    except (OSError, ValueError):
        return int(os.environ.get("PEACHY_PORT", "8080"))


def _refresh_qr() -> dict:
    """Regenerate .run/peachy_qr.png; return {ok, url, source, msg}."""
    try:
        p = subprocess.run(
            [sys.executable, str(_SCRIPTS / "tool-qr.py"), "--from-run", "--write-json"],
            capture_output=True, text=True, timeout=15, cwd=_REPO,
        )
        if p.returncode == 0 and p.stdout.strip():
            return json.loads(p.stdout.strip())
        msg = (p.stdout + p.stderr).strip()[-200:] or "QR generation failed"
        return {"ok": False, "msg": msg}
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"ok": False, "msg": str(e)}


@app.get("/api/qr")
def qr_info() -> JSONResponse:
    """Dashboard URL + source for the scan-to-open QR (same as terminal QR)."""
    data = _refresh_qr() if not _QR_PNG.exists() else {}
    if not data.get("url"):
        try:
            url = (_RUN / "peachy_qr_url").read_text().strip()
            if url:
                data = {"ok": True, "url": url, "source": "pinned"}
        except OSError:
            pass
    if not data.get("url"):
        data = _refresh_qr()
    data.setdefault("ok", bool(data.get("url")))
    data["auth"] = _AUTH_ON
    data["one_driver"] = True
    return JSONResponse(data)


@app.get("/api/qr.png")
def qr_png() -> FileResponse:
    if not _QR_PNG.exists():
        _refresh_qr()
    if not _QR_PNG.exists():
        raise HTTPException(404, "QR not available — run ./run.sh or tool-qr.py --pin")
    return FileResponse(_QR_PNG, media_type="image/png")


@app.get("/")
def index() -> FileResponse:
    # Browsers aggressively cache index.html when opened via ?k=token; after a
    # deploy they keep showing the old "control deck" until a hard refresh.
    return FileResponse(
        _STATIC / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/api/status")
def status() -> JSONResponse:
    return JSONResponse({
        "daemon": _daemon_up(),
        "state": _toggle_state(),                 # asleep | awake | unknown
        "roomwatch": _roomwatch_running(),
        "conversation": _conversation_running(),
        "conversation_gradio": _conversation_gradio_cached(),
        "convo_status": _convo_status(),
        "convo_started_at": _convo_started_at if _conversation_running() else None,
        "preview": _preview_marked_on(),
        "gradio_url": _gradio_url(),
        "peachy": _peachy_status_cached(),
        "busy": _robot_lock.locked(),
        "last": _last,
        "host": f"{HOST}:{PORT}",
    })


# ── Peachy audio bridge (v0.1) ────────────────────────────────────────────
# Mutes/unmutes the bridge on the CM4 by toggling ~/peachy_mute via SSH.
# The bridge polls that flag before every mic frame + every TTS chunk, so
# toggling it is instant (<100 ms perceived). Service starts MUTED on boot.
_peachy_status_cache: tuple[float, dict] = (0.0, {})
_PEACHY_STATUS_TTL = 4.0  # seconds


_PEACHY_MUTE = Path.home() / "peachy_mute"


def _peachy_bridge_cmd(cmd: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Run bridge mute/status on the CM4 — locally when dashboard is on-robot."""
    if _dashboard_on_robot():
        try:
            if cmd.strip() == "touch ~/peachy_mute":
                _PEACHY_MUTE.touch()
                return True, "muted"
            if cmd.strip() == "rm -f ~/peachy_mute":
                _PEACHY_MUTE.unlink(missing_ok=True)
                return True, "live"
            if "peachy_mute" in cmd and "systemctl" in cmd:
                muted = _PEACHY_MUTE.exists()
                p = subprocess.run(
                    ["systemctl", "is-active", "peachy-audio-bridge.service"],
                    capture_output=True, text=True, timeout=4)
                svc = (p.stdout or p.stderr or "unknown").strip()
                return True, f"{'MUTED' if muted else 'LIVE'}\n{svc}"
        except OSError as e:
            return False, str(e)
    return _peachy_ssh(cmd, timeout=timeout)


def _peachy_ssh(cmd: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Run a shell command on the CM4 via SSH. Returns (ok, output).

    Honours ``PEACHY_PROXYJUMP`` env (e.g. ``root@31.97.131.165``) so the
    dashboard can reach the CM4 even when the Mac's Tailscale is blocked
    by Fortinet. When unset, uses the standard dashboard SSH path.
    """
    if not _SSH_TARGET:
        return False, "no REACHY_SSH set"
    proxy = os.environ.get("PEACHY_PROXYJUMP", "").strip()
    base = list(_ssh_cmd())
    if proxy:
        base.extend(["-J", proxy])
    try:
        p = subprocess.run(
            [*base, _ssh_target(), cmd],
            capture_output=True, text=True, timeout=timeout, env=_script_env(),
        )
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)[-200:]


def _peachy_status_cached() -> dict:
    """Status of the audio bridge — cached so /api/status stays cheap."""
    global _peachy_status_cache
    now = time.time()
    if now - _peachy_status_cache[0] < _PEACHY_STATUS_TTL:
        return _peachy_status_cache[1]
    # Single SSH check: muted flag + service active state
    cmd = (
        "test -e ~/peachy_mute && echo MUTED || echo LIVE; "
        "systemctl is-active peachy-audio-bridge.service 2>/dev/null"
    )
    ok, out = _peachy_bridge_cmd(cmd, timeout=6.0)
    if not ok:
        result = {"reachable": False, "muted": None, "service": None, "error": out[-200:]}
    else:
        lines = out.splitlines()
        muted = lines[0] == "MUTED" if lines else None
        service = lines[1] if len(lines) > 1 else "unknown"
        result = {"reachable": True, "muted": muted, "service": service}
    _peachy_status_cache = (now, result)
    return result


@app.get("/api/peachy/status")
def peachy_status() -> JSONResponse:
    return JSONResponse(_peachy_status_cached())


@app.post("/api/peachy/mute")
def peachy_mute() -> JSONResponse:
    global _peachy_status_cache
    ok, msg = _peachy_bridge_cmd("touch ~/peachy_mute", timeout=5.0)
    _peachy_status_cache = (0.0, {})  # invalidate
    _logrec("peachy:mute", ok, msg)
    return JSONResponse({"ok": ok, "msg": msg or "muted"})


@app.post("/api/peachy/unmute")
def peachy_unmute() -> JSONResponse:
    global _peachy_status_cache
    ok, msg = _peachy_bridge_cmd("rm -f ~/peachy_mute", timeout=5.0)
    _peachy_status_cache = (0.0, {})
    _logrec("peachy:unmute", ok, msg)
    return JSONResponse({"ok": ok, "msg": msg or "live"})


@app.post("/api/peachy/restart")
def peachy_restart() -> JSONResponse:
    """Hard restart the bridge service. Always returns to MUTED state (safety)."""
    global _peachy_status_cache
    ok, msg = _peachy_ssh(
        "sudo systemctl restart peachy-audio-bridge.service", timeout=15.0
    )
    _peachy_status_cache = (0.0, {})
    _logrec("peachy:restart", ok, msg)
    return JSONResponse({"ok": ok, "msg": msg or "restarted (muted)"})


# ── Peachy mode switcher (v0.4) ───────────────────────────────────────────
# Three mutually exclusive modes:
#   - "open":          no assistant; mic free for student code
#   - "conversation":  the existing Pollen conversation app
#   - "glados":        peachy-audio-bridge live + peachy-glados on VPS
# The dashboard offers one-tap switching; the underlying mechanism is
# systemd start/stop + the bridge mute flag.

def _peachy_mode() -> str:
    """Best-effort current mode based on cached service state."""
    if _conversation_running():
        return "conversation"
    p = _peachy_status_cached()
    if p.get("reachable") and p.get("service") == "active" and p.get("muted") is False:
        return "glados"
    return "open"


@app.get("/api/peachy/mode")
def peachy_mode_get() -> JSONResponse:
    return JSONResponse({"mode": _peachy_mode()})


@app.post("/api/peachy/mode/{mode}")
def peachy_mode_set(mode: str) -> JSONResponse:
    """Switch to a mode. Returns ok=False if mode name is unknown."""
    global _peachy_status_cache
    mode = mode.strip().lower()
    if mode not in {"open", "conversation", "glados"}:
        return JSONResponse({"ok": False, "msg": f"unknown mode: {mode}"})

    steps: list[tuple[str, bool, str]] = []

    def step(desc: str, ok: bool, msg: str) -> None:
        steps.append((desc, ok, (msg or "")[-200:]))

    if mode == "open":
        # Mute bridge + stop conversation. Don't stop the bridge service
        # itself (it stays running so flipping back to glados is instant);
        # mute alone is enough to free the mic.
        ok, m = _peachy_bridge_cmd("touch ~/peachy_mute", timeout=5.0)
        step("mute bridge", ok, m)
        if _conversation_running():
            try:
                p = subprocess.run([str(_CONVO_SH), "stop"], cwd=_REPO,
                                   env=_script_env(), capture_output=True,
                                   text=True, timeout=15)
                step("stop conversation", p.returncode == 0, p.stderr or p.stdout)
            except Exception as e:  # noqa: BLE001
                step("stop conversation", False, str(e))

    elif mode == "conversation":
        # Mute bridge so it releases ALSA, then start conversation app
        ok, m = _peachy_bridge_cmd("touch ~/peachy_mute", timeout=5.0)
        step("mute bridge", ok, m)
        try:
            p = subprocess.run([str(_CONVO_SH), "start", "--gradio"],
                               cwd=_REPO, env=_script_env(),
                               capture_output=True, text=True, timeout=20)
            step("start conversation", p.returncode == 0, p.stderr or p.stdout)
            global _convo_started_at
            _convo_started_at = time.time()
        except Exception as e:  # noqa: BLE001
            step("start conversation", False, str(e))

    elif mode == "glados":
        # Stop conversation app, un-mute bridge. peachy-glados is on the
        # VPS — we attempt to bring it up too if it's installed.
        if _conversation_running():
            try:
                p = subprocess.run([str(_CONVO_SH), "stop"], cwd=_REPO,
                                   env=_script_env(), capture_output=True,
                                   text=True, timeout=15)
                step("stop conversation", p.returncode == 0, p.stderr or p.stdout)
            except Exception as e:  # noqa: BLE001
                step("stop conversation", False, str(e))
        # Try to bring up peachy-glados on the VPS (idempotent — no-op if
        # already running). This requires VPS_HOST env or hard-coded IP.
        vps = os.environ.get("PEACHY_VPS", "root@31.97.131.165")
        if _dashboard_on_robot():
            step("start glados (VPS)", True, "already running on VPS (remote start skipped)")
        else:
            try:
                cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                       "-o", "ConnectTimeout=8", vps,
                       "systemctl is-enabled peachy-glados.service 2>/dev/null && "
                       "systemctl start peachy-glados.service || echo 'glados not enabled'"]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                step("start glados (VPS)", p.returncode == 0, p.stdout or p.stderr)
            except Exception as e:  # noqa: BLE001
                step("start glados (VPS)", False, str(e))
        # Un-mute bridge last so audio doesn't flow before GlaDOS is ready
        ok, m = _peachy_bridge_cmd("rm -f ~/peachy_mute", timeout=5.0)
        step("unmute bridge", ok, m)

    _peachy_status_cache = (0.0, {})
    overall_ok = all(s[1] for s in steps)
    _logrec(f"peachy:mode:{mode}", overall_ok, "; ".join(s[0] for s in steps))
    return JSONResponse({
        "ok": overall_ok,
        "mode": mode,
        "msg": f"→ {mode}",
        "steps": [{"step": d, "ok": o, "msg": m} for d, o, m in steps],
    })


@app.get("/api/log", response_model=None)
def log_view(n: int = 80, fmt: str = ""):
    """Verbose action history (newest last). Ring buffer of 200 entries.

    ?n=50 limits rows returned. ?fmt=text returns plain lines for copy/paste."""
    n = max(1, min(n, 200))
    rows = list(_LOG)[-n:]
    if fmt.lower() in ("text", "txt", "plain"):
        lines = [
            f"{r['t']}  {r['action']:<16}  {'OK' if r['ok'] else 'FAIL'}  {r['msg']}"
            for r in rows
        ]
        return PlainTextResponse("\n".join(lines) if lines else "(no activity yet)\n")
    return JSONResponse(rows)


def _action(name: str, args: list[str]) -> JSONResponse:
    if not _robot_lock.acquire(blocking=False):
        _logrec(name, False, "busy — concurrent action rejected")
        raise HTTPException(409, "Peachy is busy with another action — wait a sec")
    try:
        t0 = time.time()
        ok, msg = _run_script(args)
        _last.update(action=name, ok=ok, msg=msg, at=time.time())
        _logrec(name, ok, f"({time.time()-t0:.1f}s) {msg}")
        return JSONResponse({"ok": ok, "msg": msg})
    finally:
        _robot_lock.release()


@app.post("/api/do/{cmd}")
def do(cmd: str) -> JSONResponse:
    if cmd not in ("wake", "sleep", "toggle"):
        raise HTTPException(404, "unknown command")
    if not _robot_lock.acquire(blocking=False):
        _logrec(cmd, False, "busy — concurrent action rejected")
        raise HTTPException(409, "Peachy is busy with another action — wait a sec")
    try:
        released = _release_robot_control()
        t0 = time.time()
        ok, msg = _run_script([str(_SCRIPTS / "ctl-toggle.py"), cmd])
        if released:
            msg = f"{released} · {msg}" if msg else released
        _last.update(action=cmd, ok=ok, msg=msg, at=time.time())
        _logrec(cmd, ok, f"({time.time()-t0:.1f}s) {msg}")
        return JSONResponse({"ok": ok, "msg": msg})
    finally:
        _robot_lock.release()


@app.get("/api/head")
def head_status() -> JSONResponse:
    """Saved head_offset + live daemon pose (for wake-pose tuning UI)."""
    off = _head_offset()
    live: dict = {}
    try:
        live = _daemon_json("/api/state/full").get("head_pose", {})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    ang = ("roll", "pitch", "yaw")
    return JSONResponse({
        "offset": off,
        "offset_deg": {k: round(math.degrees(off[k]), 2) for k in ang},
        "live": live,
        "live_deg": {k: round(math.degrees(float(live.get(k, 0))), 2) for k in ang},
        "saved_at": _load_state().get("head_offset_saved"),
    })


@app.post("/api/head/move")
async def head_move(request: Request) -> JSONResponse:
    """Move to a head_offset pose (degrees for roll/pitch/yaw). Body: pitch, roll, yaw
    (optional x,y,z metres). Persists in session until save."""
    if not _robot_lock.acquire(blocking=False):
        raise HTTPException(409, "Peachy is busy — wait a sec")
    try:
        body = await request.json()
        pose = _head_offset()
        for k in ("x", "y", "z"):
            if k in body:
                pose[k] = float(body[k])
        for k in ("roll", "pitch", "yaw"):
            if k in body:
                pose[k] = math.radians(float(body[k]))
            elif f"{k}_deg" in body:
                pose[k] = math.radians(float(body[f"{k}_deg"]))
        t0 = time.time()
        try:
            _head_goto(pose)
            msg = (f"roll={math.degrees(pose['roll']):+.1f}° "
                   f"pitch={math.degrees(pose['pitch']):+.1f}° "
                   f"yaw={math.degrees(pose['yaw']):+.1f}°")
            _logrec("head:move", True, f"({time.time()-t0:.1f}s) {msg}")
            return JSONResponse({"ok": True, "msg": msg, "pose": pose,
                                 "pose_deg": {k: round(math.degrees(pose[k]), 2)
                                               for k in ("roll", "pitch", "yaw")}})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                OSError) as e:
            m = str(e)[-200:]
            _logrec("head:move", False, m)
            return JSONResponse({"ok": False, "msg": m})
    finally:
        _robot_lock.release()


@app.post("/api/head/save")
async def head_save(request: Request) -> JSONResponse:
    if not _robot_lock.acquire(blocking=False):
        raise HTTPException(409, "Peachy is busy — wait a sec")
    try:
        body = await request.json()
        sys.path.insert(0, str(_SCRIPTS))
        from head_pose import write_home

        if body.get("from_live"):
            live = _daemon_json("/api/state/full")
            hp = dict(live.get("head_pose") or {})
            ant = list(live.get("antennas_position") or [0.0, 0.0])
        else:
            pose = _head_offset()
            for k in ("x", "y", "z"):
                if k in body:
                    pose[k] = float(body[k])
            for k in ("roll", "pitch", "yaw"):
                if k in body:
                    pose[k] = math.radians(float(body[k]))
                elif f"{k}_deg" in body:
                    pose[k] = math.radians(float(body[f"{k}_deg"]))
            hp = _clamp_head(pose)
            ant = [0.0, 0.0]
        write_home(hp, ant)
        msg = "head home saved → .run/reachy_toggle_state.json"
        _logrec("head:save", True, msg)
        return JSONResponse({"ok": True, "msg": msg})
    finally:
        _robot_lock.release()


@app.post("/api/head/capture")
def head_capture() -> JSONResponse:
    """Save the robot's current live pose as head home (after manual positioning)."""
    if not _robot_lock.acquire(blocking=False):
        raise HTTPException(409, "Peachy is busy — wait a sec")
    try:
        sys.path.insert(0, str(_SCRIPTS))
        from head_pose import write_home

        live = _daemon_json("/api/state/full")
        hp = dict(live.get("head_pose") or {})
        ant = list(live.get("antennas_position") or [0.0, 0.0])
        write_home(hp, ant)
        msg = "captured live pose as head home"
        _logrec("head:capture", True, msg)
        return JSONResponse({"ok": True, "msg": msg,
                             "pose_deg": {k: round(math.degrees(float(hp.get(k, 0))), 2)
                                          for k in ("roll", "pitch", "yaw")}})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError) as e:
        m = str(e)[-200:]
        _logrec("head:capture", False, m)
        return JSONResponse({"ok": False, "msg": m})
    finally:
        _robot_lock.release()


@app.post("/api/head/zero")
def head_zero() -> JSONResponse:
    if not _robot_lock.acquire(blocking=False):
        raise HTTPException(409, "Peachy is busy — wait a sec")
    try:
        pose = {k: 0.0 for k in _HEAD_AXES}
        _head_goto(pose)
        _logrec("head:zero", True, "moved to 0° (saved home unchanged — use Save home to update)")
        return JSONResponse({"ok": True, "msg": "moved to neutral (saved home unchanged)"})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError) as e:
        _logrec("head:zero", False, str(e)[-200:])
        return JSONResponse({"ok": False, "msg": str(e)})
    finally:
        _robot_lock.release()


@app.post("/api/express/{name}")
def express(name: str) -> JSONResponse:
    return _action(f"express:{name}",
                   [str(_SCRIPTS / "ctl-express.py"), "express", name])


# Bundled daemon WAVs + uploaded names from /api/media/sounds (custom later).
_SOUND_BOARD: dict[str, str] = {
    "wake": "wake_up.wav",
    "sleep": "go_sleep.wav",
    "boop": "impatient1.wav",
}
_TURRET_PACK = "portalturret"
_TURRET_DIR = _REPO / "sounds" / _TURRET_PACK
_TURRET_MANIFEST = _TURRET_DIR / "manifest.json"
_TURRET_CUES = os.environ.get("PEACHY_TURRET_CUES", "1").lower() not in (
    "0", "false", "off")


def _load_turret_manifest() -> dict:
    if not _TURRET_MANIFEST.is_file():
        return {"sounds": {}, "cues": {}}
    return json.loads(_TURRET_MANIFEST.read_text())


def _robot_sound_files() -> set[str]:
    sys.path.insert(0, str(_SCRIPTS))
    from sound_sync import list_robot_sounds

    return list_robot_sounds(HOST, PORT)


def _ensure_wav_on_robot(filename: str) -> None:
    if filename in _robot_sound_files():
        return
    local = _TURRET_DIR / filename
    if not local.is_file():
        raise FileNotFoundError(f"missing {local}")
    sys.path.insert(0, str(_SCRIPTS))
    from sound_sync import upload_wav

    upload_wav(HOST, PORT, local)


def _play_wav_file(filename: str) -> None:
    _ensure_wav_on_robot(filename)
    _daemon_json("/api/media/play_sound", "POST", {"file": filename}, timeout=12)


def _play_turret_id(sound_id: str) -> tuple[bool, str]:
    manifest = _load_turret_manifest()
    meta = manifest.get("sounds", {}).get(sound_id)
    if not meta:
        return False, f"unknown turret sound {sound_id!r}"
    fname = meta["file"]
    _play_wav_file(fname)
    return True, fname


def _play_turret_cue(cue: str) -> None:
    manifest = _load_turret_manifest()
    sid = manifest.get("cues", {}).get(cue)
    if not sid:
        return
    ok, msg = _play_turret_id(sid)
    _logrec(f"turret:{cue}", ok, msg)


def _turret_cue_async(cue: str) -> None:
    threading.Thread(target=_play_turret_cue, args=(cue,), daemon=True).start()


@app.get("/api/sounds/turret")
def turret_catalog() -> JSONResponse:
    manifest = _load_turret_manifest()
    on_robot = _robot_sound_files()
    sounds = []
    for sid, meta in manifest.get("sounds", {}).items():
        fname = meta["file"]
        sounds.append({
            "id": sid,
            "file": fname,
            "label": meta.get("label", sid.replace("_", " ")),
            "on_robot": fname in on_robot,
        })
    return JSONResponse({
        "pack": _TURRET_PACK,
        "cues": manifest.get("cues", {}),
        "sounds": sounds,
    })


@app.post("/api/sounds/turret/sync")
def turret_sync() -> JSONResponse:
    sys.path.insert(0, str(_SCRIPTS))
    from sound_sync import sync_pack

    try:
        result = sync_pack(HOST, PORT, _TURRET_PACK)
        msg = f"uploaded {len(result['uploaded'])}, skipped {len(result['skipped'])}"
        _logrec("turret:sync", True, msg)
        return JSONResponse({"ok": True, "msg": msg, **result})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, FileNotFoundError, ValueError) as e:
        msg = str(e)[-200:]
        _logrec("turret:sync", False, msg)
        return JSONResponse({"ok": False, "msg": msg})


@app.get("/api/light")
def light_status() -> JSONResponse:
    """Peachy head-camera brightness (never the laptop webcam)."""
    try:
        data = {"ok": True, **_dashboard_light_read()}
        data["roomwatch"] = _roomwatch_running()
        data["preview"] = _preview_marked_on()
        if not data["preview"]:
            data["hint"] = "Start Live preview for faster light reads"
        return JSONResponse(data)
    except OSError as e:
        return JSONResponse({"ok": False, "msg": str(e)[-200:]})


_LIGHT_LAB_IMAGES = {
    "baseline": _RUN / "light_lab_baseline.jpg",
    "sample": _RUN / "light_lab_sample.jpg",
    "live": _RUN / "light_lab_live.jpg",
    "baseline_annot": _RUN / "light_lab_baseline_annot.jpg",
    "sample_annot": _RUN / "light_lab_sample_annot.jpg",
    "live_annot": _RUN / "light_lab_live_annot.jpg",
}


@app.get("/api/light/lab")
def light_lab_status() -> JSONResponse:
    """Full light lab readout — ROIs, compare, tune, sensor."""
    sys.path.insert(0, str(_SCRIPTS))
    from light_lab import lab_status

    try:
        return JSONResponse(lab_status())
    except OSError as e:
        return JSONResponse({"ok": False, "msg": str(e)[-200:]})


@app.post("/api/light/lab/capture/{label}")
def light_lab_capture(label: str, note: str = Query("")) -> JSONResponse:
    """Capture frame without waking (baseline/sample/live compare photos)."""
    if label not in ("baseline", "sample", "live"):
        raise HTTPException(404, "label must be baseline, sample, or live")
    sys.path.insert(0, str(_SCRIPTS))
    from light_lab import analyze_path, annotate, capture_frame, save_capture

    try:
        if label == "live":
            dest = _RUN / "light_lab_live.jpg"
            if not capture_frame(dest):
                return JSONResponse({"ok": False, "msg": "camera read failed"})
            annotate(dest, _RUN / "light_lab_live_annot.jpg")
            data = analyze_path(dest)
            return JSONResponse({"ok": True, "label": "live", **data})
        data = save_capture(label, note or ("lights off" if label == "baseline" else "lights on"))
        _logrec(f"light:capture:{label}", data.get("ok", False), note[:80])
        return JSONResponse(data)
    except OSError as e:
        return JSONResponse({"ok": False, "msg": str(e)[-200:]})


@app.get("/api/light/lab/compare")
def light_lab_compare() -> JSONResponse:
    sys.path.insert(0, str(_SCRIPTS))
    from light_lab import compare_captures

    return JSONResponse(compare_captures())


@app.post("/api/light/lab/tune")
async def light_lab_tune(request: Request) -> JSONResponse:
    """Persist on/off deltas and preferred ROI to .run/light_tune.json."""
    sys.path.insert(0, str(_SCRIPTS))
    from light_lab import save_tune

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    kwargs: dict = {}
    if "on_delta" in body:
        kwargs["on_delta"] = max(3.0, min(80.0, float(body["on_delta"])))
    if "off_delta" in body:
        kwargs["off_delta"] = max(2.0, min(60.0, float(body["off_delta"])))
    if "preferred_roi" in body:
        from light_lab import ROIS

        roi = str(body["preferred_roi"])
        if roi in ROIS:
            kwargs["preferred_roi"] = roi
    if not kwargs:
        return JSONResponse({"ok": False, "msg": "nothing to save"})
    data = save_tune(**kwargs)
    _logrec("light:tune", True, json.dumps(kwargs)[:120])
    return JSONResponse({"ok": True, "tune": data})


@app.get("/api/light/lab/image/{name}")
def light_lab_image(name: str) -> FileResponse:
    path = _LIGHT_LAB_IMAGES.get(name)
    if not path or not path.is_file():
        raise HTTPException(404, "image not found — capture first")
    return FileResponse(path, media_type="image/jpeg")


def _saved_volume() -> int:
    try:
        return max(0, min(100, int(json.loads(_VOLUME_FILE.read_text()).get("volume", _DEFAULT_VOLUME))))
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return _DEFAULT_VOLUME


def _persist_volume(vol: int) -> None:
    _VOLUME_FILE.write_text(json.dumps({"volume": vol}, indent=2) + "\n")


def _apply_speaker_volume(vol: int) -> dict:
    """Set daemon speaker volume and persist. Returns daemon response dict."""
    vol = max(0, min(100, int(vol)))
    snap = _daemon_json("/api/volume/set", "POST", {"volume": vol}, timeout=12.0)
    _persist_volume(vol)
    return snap if isinstance(snap, dict) else {"volume": vol}


def _ensure_volume_boot() -> None:
    """Once per dashboard process: apply saved speaker level (default max)."""
    global _volume_boot_done
    if _volume_boot_done or not _daemon_up():
        return
    _volume_boot_done = True
    vol = _saved_volume()
    try:
        cur = int(_daemon_json("/api/volume/current", timeout=6.0).get("volume", -1))
        if cur != vol:
            _daemon_json("/api/volume/set", "POST", {"volume": vol}, timeout=10.0)
            _logrec("volume:boot", True, f"{vol}%")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        _volume_boot_done = False
        _logrec("volume:boot", False, str(e)[-200:])


@app.get("/api/sounds")
def sounds_catalog() -> JSONResponse:
    custom: list[str] = []
    try:
        data = _daemon_json("/api/media/sounds", timeout=4)
        custom = [f for f in data.get("files", []) if f.endswith(".wav")]
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass
    return JSONResponse({
        "built_in": [{"id": k, "file": v, "label": k.replace("_", " ")}
                     for k, v in _SOUND_BOARD.items()],
        "custom": custom,
    })


@app.post("/api/sound/stop")
def stop_sound() -> JSONResponse:
    try:
        _daemon_json("/api/media/stop_sound", "POST", {}, timeout=8)
        _logrec("sound:stop", True, "")
        return JSONResponse({"ok": True, "msg": "stopped"})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError) as e:
        msg = str(e)[-200:]
        _logrec("sound:stop", False, msg)
        return JSONResponse({"ok": False, "msg": msg})


@app.get("/api/volume")
def volume_get() -> JSONResponse:
    """Current robot speaker volume (0–100). Applies saved level on first read."""
    _ensure_volume_boot()
    try:
        snap = _daemon_json("/api/volume/current", timeout=6.0)
        return JSONResponse({"ok": True, **snap, "saved": _saved_volume()})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return JSONResponse({"ok": False, "msg": str(e)[-200:]})


@app.post("/api/volume")
async def volume_set(request: Request) -> JSONResponse:
    """Set speaker volume 0–100 (daemon plays a short test blip on set)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    vol = max(0, min(100, int(body.get("volume", _DEFAULT_VOLUME))))
    try:
        snap = _apply_speaker_volume(vol)
        _logrec("volume:set", True, f"{vol}%")
        return JSONResponse({"ok": True, **snap})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        msg = str(e)[-200:]
        _logrec("volume:set", False, msg)
        return JSONResponse({"ok": False, "msg": msg})


@app.post("/api/volume/test")
def volume_test() -> JSONResponse:
    """Play test sound at current volume without changing level."""
    try:
        snap = _daemon_json("/api/volume/test-sound", "POST", {}, timeout=12.0)
        _logrec("volume:test", True, snap.get("message", "ok"))
        return JSONResponse({"ok": True, **snap})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        msg = str(e)[-200:]
        _logrec("volume:test", False, msg)
        return JSONResponse({"ok": False, "msg": msg})


@app.post("/api/sound/{sound_id}")
def play_sound(sound_id: str) -> JSONResponse:
    """Play a bundled, turret, or uploaded WAV on the robot speaker."""
    if sound_id.startswith("turret/"):
        tid = sound_id.split("/", 1)[1]
        try:
            ok, msg = _play_turret_id(tid)
            _logrec(f"sound:{sound_id}", ok, msg)
            return JSONResponse({"ok": ok, "msg": msg})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                OSError, FileNotFoundError) as e:
            msg = str(e)[-200:]
            _logrec(f"sound:{sound_id}", False, msg)
            return JSONResponse({"ok": False, "msg": msg})
    wav = _SOUND_BOARD.get(sound_id)
    if not wav:
        if sound_id.endswith(".wav"):
            wav = sound_id
        else:
            return JSONResponse({"ok": False, "msg": f"unknown sound {sound_id!r}"})
    try:
        _daemon_json("/api/media/play_sound", "POST", {"file": wav}, timeout=12)
        _logrec(f"sound:{sound_id}", True, wav)
        return JSONResponse({"ok": True, "msg": wav})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError) as e:
        msg = str(e)[-200:]
        _logrec(f"sound:{sound_id}", False, msg)
        return JSONResponse({"ok": False, "msg": msg})


@app.post("/api/roomwatch/confirm")
async def roomwatch_confirm(request: Request) -> JSONResponse:
    """Teacher confirms ground-truth lights — logs sample + re-anchors ref when OFF."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    lights = str(body.get("lights", "")).strip().lower()
    if lights not in ("on", "off"):
        raise HTTPException(400, "lights must be 'on' or 'off'")

    sys.path.insert(0, str(_SCRIPTS))
    from light_lab import effective_off_delta, effective_on_delta
    from light_sensor import schedule_reanchor

    on_d = effective_on_delta()
    off_d = effective_off_delta()
    snap, _src, log, _log_age = _roomwatch_light_read(on_d, off_d)
    watcher = log.get("last") or {}
    if not snap.get("ok", True):
        return JSONResponse({"ok": False, "msg": snap.get("msg", "light read failed")})

    detected = bool(snap.get("lit"))
    confirmed_on = lights == "on"
    agree = detected == confirmed_on
    ema = float(snap.get("ema") or 0)
    ref = float(snap.get("ref") or 0)

    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "confirmed": lights,
        "detected_lit": detected,
        "agree": agree,
        "ema": ema,
        "ref": ref,
        "delta": snap.get("delta"),
        "raw": snap.get("raw"),
        "watcher_state": watcher.get("state"),
        "roomwatch": _roomwatch_running(),
    }
    _CONFIRM_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _CONFIRM_LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")

    msg_parts = [f"logged lights {lights.upper()}"]
    if agree:
        msg_parts.append("matches sensor")
    else:
        msg_parts.append(f"sensor said {'ON' if detected else 'OFF'} — correction recorded")

    if lights == "off":
        schedule_reanchor(ref=ema, ema=ema, lit=False)
        _reset_dashboard_light_sensor()
        msg_parts.append("re-anchored dark baseline")
    elif lights == "on" and not agree:
        schedule_reanchor(ref=max(0.0, ema - on_d), ema=ema, lit=True)
        msg_parts.append("nudged ref for ON")

    msg = " · ".join(msg_parts)
    _logrec("roomwatch:confirm", True, msg)
    return JSONResponse({"ok": True, "msg": msg, "agree": agree, "record": rec})


@app.post("/api/roomwatch/{cmd}")
def roomwatch(cmd: str) -> JSONResponse:
    if cmd == "start":
        if _roomwatch_running():
            if _roomwatch_healthy():
                _logrec("roomwatch:start", True, "already watching")
                return JSONResponse({"ok": True, "msg": "already watching", "running": True})
            _logrec("roomwatch:start", True, "restarting stale watcher")
            _stop_roomwatch()
        _reset_dashboard_light_sensor()
        _LIGHT_HISTORY.clear()
        if not _preview_marked_on() and _SSH_TARGET:
            try:
                preview("start")  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                pass
        proc = _start_roomwatch_proc()
        _RW_PID.write_text(str(proc.pid))
        time.sleep(1.0)
        ok = _roomwatch_running()
        msg = "room watch started" if ok else "failed — check dashboard_roomwatch.log (calibration?)"
        _logrec("roomwatch:start", ok, msg)
        return JSONResponse({"ok": ok, "msg": msg, "running": ok})
    if cmd == "stop":
        _stop_roomwatch()
        _logrec("roomwatch:stop", True, "")
        return JSONResponse({"ok": True, "msg": "room watch stopped", "running": False})
    raise HTTPException(404, "unknown command")


_RW_LOG_RE = __import__("re").compile(
    r"^\[(\d{2}:\d{2}:\d{2})\] raw=([\d.+-]+) ema=([\d.+-]+) ref=([\d.+-]+) "
    r"Δ=([+-]?[\d.]+) mot=([\d.+-]+) idle=([\d.+-]+)s lit=(\w+) speech=(\w+) "
    r"state=(\w+|None)(?: pending=(\w+)\(([\d.]+)s\))?"
)
_RW_STATE_RE = __import__("re").compile(r"^\s*→ (\w+)")


def _roomwatch_timing() -> dict:
    return {
        "poll_s": float(os.environ.get("REACHY_WATCH_PERIOD", "0.6")),
        "settle_s": float(os.environ.get("REACHY_SETTLE_S", "3.0")),
        "idle_sleep_s": float(os.environ.get("REACHY_IDLE_SLEEP_S", "300")),
        "awake_hold_s": float(os.environ.get("REACHY_AWAKE_HOLD_S", "30")),
    }


def _parse_roomwatch_log() -> dict:
    out: dict = {"lines": [], "last": None, "last_transition": None}
    try:
        text = _RW_LOG.read_text(errors="replace")
    except OSError:
        return out
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out["lines"] = lines[-12:]
    for ln in reversed(lines):
        m = _RW_LOG_RE.match(ln)
        if m:
            out["last"] = {
                "t": m.group(1),
                "raw": float(m.group(2)),
                "ema": float(m.group(3)),
                "ref": float(m.group(4)),
                "delta": float(m.group(5)),
                "motion": float(m.group(6)),
                "idle_s": float(m.group(7)),
                "lit": m.group(8).lower() == "true",
                "speech": m.group(9).lower() == "true",
                "state": None if m.group(10) == "None" else m.group(10),
                "pending": m.group(11),
                "pending_s": float(m.group(12)) if m.group(12) else 0.0,
            }
            break
    for ln in reversed(lines):
        m = _RW_STATE_RE.match(ln)
        if m:
            out["last_transition"] = m.group(1)
            break
    return out


@app.get("/api/roomwatch/status")
def roomwatch_status() -> JSONResponse:
    """Live room-watch telemetry — light sense, sensitivity, watcher log."""
    sys.path.insert(0, str(_SCRIPTS))
    from light_lab import effective_off_delta, effective_on_delta, load_tune, preferred_roi

    tune = load_tune()
    on_d = effective_on_delta()
    off_d = effective_off_delta()
    timing = _roomwatch_timing()
    light, light_source, log, log_age = _roomwatch_light_read(on_d, off_d)
    t0 = time.time()
    watcher = log.get("last") or {}
    poll_ms = int((time.time() - t0) * 1000)

    ref = light.get("ref")
    ema = light.get("ema")

    return JSONResponse({
        "ok": True,
        "running": _roomwatch_running(),
        "healthy": _roomwatch_healthy(),
        "log_age_s": log_age,
        "light_source": light_source,
        "preview": _preview_marked_on(),
        "poll_ms": poll_ms,
        "lit": bool(light.get("lit")),
        "would_lit": bool(light.get("would_lit")),
        "would_dark": bool(light.get("would_dark")),
        "delta": light.get("delta"),
        "ema": ema,
        "ref": ref,
        "raw": light.get("raw"),
        "motion": light.get("motion"),
        "on_threshold": light.get("on_threshold"),
        "off_threshold": light.get("off_threshold"),
        "speech": watcher.get("speech") if watcher else False,
        "watcher_state": watcher.get("state"),
        "pending": watcher.get("pending"),
        "pending_s": watcher.get("pending_s"),
        "last_transition": log.get("last_transition"),
        "watcher_t": watcher.get("t"),
        "sensitivity": {
            "on_delta": on_d,
            "off_delta": off_d,
            "preferred_roi": preferred_roi(),
            "on_threshold": light.get("on_threshold"),
            "off_threshold": light.get("off_threshold"),
            **timing,
        },
        "tune": tune,
        "light": light,
        "history": list(_LIGHT_HISTORY),
        "log_tail": log.get("lines", []),
        "conversation": _conversation_running(),
    })


@app.post("/api/roomwatch/history/clear")
def roomwatch_history_clear() -> JSONResponse:
    _LIGHT_HISTORY.clear()
    _reset_dashboard_light_sensor()
    return JSONResponse({"ok": True, "msg": "chart history cleared — sensor re-seeded"})


def converse(cmd: str, gradio: bool = Query(False)) -> JSONResponse:
    """Start/stop the conversation app. Use ``end`` or ``/api/shutdown`` to sleep too."""
    global _convo_started_at, _convo_gradio_cache
    use_gradio = gradio or cmd == "start-gradio"
    if cmd in ("start", "start-gradio"):
        if _conversation_running():
            hint = " · open http://127.0.0.1:7860/" if _conversation_gradio_cached() else ""
            return JSONResponse({"ok": True,
                                 "msg": f"already listening — talk to Peachy{hint}"})
        if not _robot_lock.acquire(blocking=False):
            raise HTTPException(409, "Peachy is busy — wait a sec")
        try:
            _convo_started_at = time.time()
            _convo_gradio_cache = (0.0, False)
            try:
                _CONVO_GRADIO.unlink()
            except OSError:
                pass
            released = _release_robot_control()
            wok, wmsg = _run_script([str(_SCRIPTS / "ctl-toggle.py"), "wake"], 90)
            start_args = [str(_CONVO_SH), "start"]
            if use_gradio:
                start_args.append("--gradio")
            c = subprocess.run(start_args, cwd=_REPO, env=_script_env(),
                               capture_output=True, text=True, timeout=60)
            ok = wok and _conversation_running()
            if ok and use_gradio:
                msg = "Gradio UI — open http://127.0.0.1:7860/ (needs SSH tunnel)"
            elif ok:
                msg = "listening — talk to Peachy (no Gradio; use Start + UI for transcript)"
            else:
                msg = (c.stdout + c.stderr + " | " + wmsg).strip()[-300:]
            if ok:
                try:
                    _apply_speaker_volume(_DEFAULT_VOLUME)
                    _logrec("volume:convo-start", True, f"{_DEFAULT_VOLUME}%")
                    msg = f"{msg} · speaker {_DEFAULT_VOLUME}%"
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
                    _logrec("volume:convo-start", False, str(e)[-200:])
                vok, vmsg = _apply_convo_voice(_DEFAULT_CONVO_VOICE)
                _logrec("voice:convo-start", vok, vmsg[:200])
                if vok:
                    msg = f"{msg} · voice Ballad"
            if released and ok:
                msg = f"{released} · {msg}"
            action = "converse:start-gradio" if use_gradio else "converse:start"
            _last.update(action=action, ok=ok, msg=msg, at=time.time())
            _logrec(action, ok, msg)
            return JSONResponse({"ok": ok, "msg": msg, "gradio_url": _gradio_url()})
        finally:
            _robot_lock.release()
    if cmd == "stop":
        subprocess.run([str(_CONVO_SH), "stop"], cwd=_REPO, env=_script_env(),
                       capture_output=True, text=True, timeout=25)
        _convo_started_at = 0.0
        _convo_gradio_cache = (0.0, False)
        try:
            _CONVO_GRADIO.unlink()
        except OSError:
            pass
        ok = not _conversation_running()
        msg = "conversation stopped" if ok else "stop sent — check log"
        _last.update(action="converse:stop", ok=ok, msg=msg, at=time.time())
        _logrec("converse:stop", ok, msg)
        return JSONResponse({"ok": ok, "msg": msg})
    if cmd == "end":
        subprocess.run([str(_CONVO_SH), "stop"], cwd=_REPO, env=_script_env(),
                       capture_output=True, text=True, timeout=25)
        _convo_started_at = 0.0
        _convo_gradio_cache = (0.0, False)
        try:
            _CONVO_GRADIO.unlink()
        except OSError:
            pass
        if not _robot_lock.acquire(blocking=False):
            raise HTTPException(409, "Peachy is busy — wait a sec")
        try:
            released = _release_robot_control()
            ok, msg = _run_script([str(_SCRIPTS / "ctl-toggle.py"), "sleep"], 120)
            if released:
                msg = f"{released} · {msg}" if msg else released
            msg = f"conversation stopped · {msg}" if msg else "conversation stopped · asleep"
            _last.update(action="converse:end", ok=ok, msg=msg, at=time.time())
            _logrec("converse:end", ok, msg)
            return JSONResponse({"ok": ok, "msg": msg})
        finally:
            _robot_lock.release()
    raise HTTPException(404, "unknown command")


_CONVO_LOG = _RUN / "conversation_app.log"
_CONVO_LOG_RE_PREFIX = __import__("re").compile(
    r"^\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2}),\d+ \w+ [^\|]+\| ?")
_CONVO_TRANSCRIPT_RE = __import__("re").compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .* \| role=(user|assistant) content=(.+)$")


def _fetch_convo_log_lines(n: int) -> list[str]:
    n = max(1, min(n, 400))
    try:
        p = subprocess.run(
            [str(_CONVO_SH), "log", str(n)], cwd=_REPO, env=_script_env(),
            capture_output=True, text=True, timeout=25)
        raw = (p.stdout or "").strip().splitlines()
        if not raw and p.stderr:
            raw = p.stderr.strip().splitlines()
        return raw
    except (subprocess.TimeoutExpired, OSError):
        return []


def _is_transcript_speech(role: str, content: str) -> bool:
    """Keep user lines; on assistant side drop tool-call noise and raw JSON results."""
    text = content.strip()
    if not text:
        return False
    if role == "user":
        return True
    if text.startswith("🛠️") or text.startswith("[error]"):
        return False
    if "Used tool " in text and "Tool ID:" in text:
        return False
    if text.startswith("{") and text.endswith("}"):
        try:
            json.loads(text)
            return False
        except json.JSONDecodeError:
            pass
    return True


def _parse_transcript(raw: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for ln in raw:
        m = _CONVO_TRANSCRIPT_RE.match(ln.strip())
        if not m:
            continue
        t_full, role, content = m.group(1), m.group(2), m.group(3).strip()
        if not _is_transcript_speech(role, content):
            continue
        out.append({"t": t_full.split(" ", 1)[-1][:8], "role": role, "content": content})
    return out


@app.get("/api/converse/log")
def converse_log(n: int = 40) -> JSONResponse:
    """Last N lines of the conversation app log (robot log when using uplink SSH)."""
    raw = _fetch_convo_log_lines(n)
    if not raw:
        return JSONResponse({"ok": True, "lines": [], "source": "robot" if _SSH_TARGET else "local"})
    lines = []
    for ln in raw:
        m = _CONVO_LOG_RE_PREFIX.match(ln)
        if m:
            level = "err" if " ERROR " in ln else ("warn" if " WARNING " in ln else "")
            lines.append({"t": m.group(1), "msg": ln[m.end():], "level": level})
        else:
            lines.append({"t": "", "msg": ln, "level": ""})
    remote = (_RUN / "conversation_app.mode").read_text().strip() == "remote" if \
        (_RUN / "conversation_app.mode").is_file() else bool(_SSH_TARGET)
    return JSONResponse({"ok": True, "lines": lines, "source": "robot" if remote else "local"})


@app.get("/api/converse/transcript")
def converse_transcript(n: int = 120) -> JSONResponse:
    """Side-by-side chat view — user vs Peachy lines from conversation log."""
    if not _conversation_running():
        return JSONResponse({"ok": True, "running": False, "messages": []})
    raw = _fetch_convo_log_lines(n)
    msgs = _parse_transcript(raw)
    remote = (_RUN / "conversation_app.mode").read_text().strip() == "remote" if \
        (_RUN / "conversation_app.mode").is_file() else bool(_SSH_TARGET)
    return JSONResponse({
        "ok": True,
        "running": True,
        "messages": msgs,
        "source": "robot" if remote else "local",
    })


@app.get("/api/converse/idle-motion")
def converse_idle_motion_get() -> JSONResponse:
    """Proxy idle fidget settings from conversation app (:7860, Peachy patch)."""
    if not _conversation_running():
        return JSONResponse({"ok": False, "error": "conversation_not_running"})
    try:
        data = _convo_api_json("/idle-motion")
        return JSONResponse({"ok": True, **data})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


@app.post("/api/converse/idle-motion")
def converse_idle_motion_apply(
    scale: float | None = Query(None),
    cadence_s: float | None = Query(None),
    burst_s: float | None = Query(None),
) -> JSONResponse:
    if not _conversation_running():
        return JSONResponse({"ok": False, "error": "conversation_not_running"})
    params: dict[str, float] = {}
    if scale is not None:
        params["scale"] = scale
    if cadence_s is not None:
        params["cadence_s"] = cadence_s
    if burst_s is not None:
        params["burst_s"] = burst_s
    if not params:
        return JSONResponse({"ok": False, "error": "missing_params"})
    try:
        data = _convo_api_json("/idle-motion/apply", method="POST", params=params)
        if isinstance(data, dict) and data.get("ok") is False:
            return JSONResponse(data)
        return JSONResponse({"ok": True, **data} if isinstance(data, dict) else {"ok": True})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


@app.get("/api/converse/voices")
def converse_voices() -> JSONResponse:
    """Available voices from conversation app (:7860)."""
    from voice_catalog import OPENAI_VOICES, catalog_for_ids

    fallback = [v["id"] for v in OPENAI_VOICES]
    if not _conversation_running():
        return JSONResponse({
            "ok": False,
            "error": "conversation_not_running",
            "voices": fallback,
            "cards": catalog_for_ids(fallback),
        })
    try:
        data = _convo_api_json("/voices")
        voices = [str(v) for v in data] if isinstance(data, list) else []
        return JSONResponse({
            "ok": True,
            "voices": voices,
            "cards": catalog_for_ids(voices),
        })
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as e:
        return JSONResponse({
            "ok": False,
            "error": str(e)[:200],
            "voices": fallback,
            "cards": catalog_for_ids(fallback),
        })


@app.get("/api/converse/voices/current")
def converse_voice_current() -> JSONResponse:
    if not _conversation_running():
        return JSONResponse({"ok": False, "error": "conversation_not_running"})
    try:
        data = _convo_api_json("/voices/current")
        if isinstance(data, dict):
            return JSONResponse({"ok": True, **data})
        return JSONResponse({"ok": False, "error": "invalid_response"})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


@app.post("/api/converse/voices/apply")
def converse_voice_apply(voice: str = Query(...)) -> JSONResponse:
    if not _conversation_running():
        return JSONResponse({"ok": False, "error": "conversation_not_running"})
    try:
        data = _convo_api_json("/voices/apply", method="POST", params={"voice": voice})
        if isinstance(data, dict) and data.get("ok") is False:
            return JSONResponse(data)
        return JSONResponse({"ok": True, **data} if isinstance(data, dict) else {"ok": True})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


@app.get("/api/converse/personalities")
def converse_personalities() -> JSONResponse:
    """Personality modes from conversation app (:7860)."""
    from personality_catalog import DEFAULT_OPTION, catalog_for_ids

    if not _conversation_running():
        preview_ids = [DEFAULT_OPTION, "hype_bot", "victorian_butler", "mad_scientist_assistant",
                       "noir_detective", "nature_documentarian", "captain_circuit", "chess_coach"]
        preview = catalog_for_ids(preview_ids)
        return JSONResponse({
            "ok": False,
            "error": "conversation_not_running",
            "choices": [p["id"] for p in preview],
            "cards": preview,
            "current": DEFAULT_OPTION,
        })
    try:
        data = _convo_api_json("/personalities")
        if not isinstance(data, dict):
            return JSONResponse({"ok": False, "error": "invalid_response"})
        choices = [str(c) for c in data.get("choices", [])]
        return JSONResponse({
            "ok": True,
            "choices": choices,
            "cards": catalog_for_ids(choices),
            "current": data.get("current"),
            "startup": data.get("startup"),
            "locked": data.get("locked"),
        })
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


@app.post("/api/converse/personalities/apply")
def converse_personality_apply(
    name: str = Query(...),
    persist: bool = Query(False),
) -> JSONResponse:
    if not _conversation_running():
        return JSONResponse({"ok": False, "error": "conversation_not_running"})
    try:
        data = _convo_api_json(
            "/personalities/apply",
            method="POST",
            params={"name": name, "persist": "true" if persist else "false"},
            timeout=15.0,
        )
        if isinstance(data, dict) and data.get("ok") is False:
            return JSONResponse(data)
        return JSONResponse({"ok": True, **data} if isinstance(data, dict) else {"ok": True})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]})


def _preview_pull_payload(out: Path, *, pull_ms: int, via: str) -> dict:
    st = out.stat()
    age = time.time() - st.st_mtime
    cfg = _preview_settings()
    return {
        "ok": True,
        "msg": f"frame {age:.1f}s old · {st.st_size // 1024}KB",
        "via": via,
        "frame_age_s": round(age, 2),
        "frame_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        "pulled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pull_ms": pull_ms,
        "bytes_kb": round(st.st_size / 1024, 1),
        "interval_s": cfg["interval_s"],
        "fps": round(1.0 / cfg["interval_s"], 2),
        "quality": cfg["quality"],
        "scale": cfg["scale"],
        "mode": cfg["mode"],
    }


@app.post("/api/preview/{cmd}")
def preview(
    cmd: str,
    interval_s: float | None = None,
    quality: int | None = None,
    scale: float | None = None,
    mode: str | None = None,
) -> JSONResponse:
    """Live camera on the robot. start|stop|pull.

    start query params: interval_s, quality (20–90), scale (0.25–1), mode (stream|motion).
    """
    ssh_t = _ssh_target()
    if cmd == "start":
        cfg = _save_preview_settings(
            interval_s=interval_s if interval_s is not None else _preview_interval(),
            quality=quality if quality is not None else _preview_settings()["quality"],
            scale=scale if scale is not None else _preview_settings()["scale"],
            mode=mode if mode is not None else _preview_settings()["mode"],
        )
        ok, msg = _start_preview_loop(cfg)
        if ok:
            _PREVIEW_FLAG.write_text("1")
        fps = 1.0 / cfg["interval_s"]
        _logrec("preview:start", ok, msg)
        return JSONResponse({"ok": ok, "msg": msg, **cfg, "fps": round(fps, 2)})
    if cmd == "stop":
        if _dashboard_on_robot():
            _kill_preview_local()
        else:
            _kill_preview_remote(ssh_t)
        _PREVIEW_FLAG.unlink(missing_ok=True)
        _logrec("preview:stop", True, "")
        return JSONResponse({"ok": True, "msg": "preview stopped"})
    if cmd == "pull":
        out = _STATIC / "snap.jpg"
        payload = _fetch_snap_frame(out)
        return JSONResponse(payload)
    raise HTTPException(404, "unknown preview command")


@app.post("/api/snap/live")
def snap_live() -> JSONResponse:
    """One still frame, no wake. Prefers live preview file; no robot lock."""
    if not _daemon_up():
        return JSONResponse({"ok": False, "msg": "Peachy is offline"})
    asleep = _toggle_state() == "asleep"
    if asleep and not _preview_marked_on():
        return JSONResponse({"ok": False, "msg": "Peachy is sleeping"})
    out = _STATIC / "snap.jpg"
    payload = _fetch_snap_frame(out)
    ok = payload.get("ok") is not False
    _logrec("snap:live", ok, payload.get("msg", ""))
    _last.update(action="snap:live", ok=ok, msg=payload.get("msg", ""), at=time.time())
    return JSONResponse(payload)


@app.post("/api/snap")
def snap() -> JSONResponse:
    """Wake if asleep, settle to head home, then grab a still."""
    if not _daemon_up():
        return JSONResponse({"ok": False, "msg": "Peachy is offline"})
    out = _STATIC / "snap.jpg"
    if _ON_ROBOT or _dashboard_on_robot():
        if _toggle_state() == "asleep":
            w = _run_script([str(_SCRIPTS / "ctl-toggle.py"), "wake"], timeout=120)
            if not w[0]:
                return JSONResponse({"ok": False, "msg": w[1]})
        _settle_head_home()
        if _TURRET_CUES:
            _turret_cue_async("snap")
        return _action("snap", [str(_SCRIPTS / "cam-snap.py"), "--out", str(out),
                                "--no-wake", "--warmup", "1.0"])
    if _toggle_state() == "asleep":
        if _robot_lock.acquire(blocking=False):
            try:
                ok, msg = _run_script([str(_SCRIPTS / "ctl-toggle.py"), "wake"], timeout=120)
            finally:
                _robot_lock.release()
            if not ok:
                return JSONResponse({"ok": False, "msg": msg})
        else:
            return JSONResponse({"ok": False, "msg": "Peachy is busy — wait for wake to finish"})
    _settle_head_home()
    if _TURRET_CUES:
        _turret_cue_async("snap")
    payload = _fetch_snap_frame(out, snap_warmup=1.0, force_fresh=True)
    ok = payload.get("ok") is not False
    _logrec("snap", ok, payload.get("msg", ""))
    _last.update(action="snap", ok=ok, msg=payload.get("msg", ""), at=time.time())
    return JSONResponse(payload)


@app.post("/api/abort")
def abort_action() -> JSONResponse:
    """Emergency halt — stop moves and background apps; robot stays put."""
    ok, m = _stop_services(sleep=False)
    _logrec("ABORT", ok, m)
    _last.update(action="abort", ok=ok, msg=m, at=time.time())
    return JSONResponse({"ok": ok, "msg": m})


@app.post("/api/shutdown")
def shutdown_action() -> JSONResponse:
    """Stop everything Peachy-ish (conversation, watch, preview) and sleep."""
    if not _robot_lock.acquire(blocking=False):
        raise HTTPException(409, "Peachy is busy — wait a sec")
    try:
        t0 = time.time()
        ok, m = _stop_services(sleep=True)
        _logrec("shutdown", ok, f"({time.time()-t0:.1f}s) {m}")
        _last.update(action="shutdown", ok=ok, msg=m, at=time.time())
        return JSONResponse({"ok": ok, "msg": m})
    finally:
        _robot_lock.release()


def _fan_snapshot() -> dict:
    sys.path.insert(0, str(_SCRIPTS))
    from fan_read import read_sysfs, read_via_ssh

    if _ON_ROBOT or _dashboard_on_robot():
        snap = read_sysfs()
    else:
        snap = read_via_ssh(_ssh_cmd(), _ssh_target())
    if snap.get("ok", True):
        snap["ts"] = time.time()
        snap["t"] = time.strftime("%H:%M:%S")
        _FAN_HIST.append({
            "t": snap["t"],
            "ts": snap["ts"],
            "temp_c": snap.get("temp_c"),
            "pwm": snap.get("pwm"),
            "fan_state": snap.get("fan_state"),
            "fan_pct": snap.get("fan_pct"),
        })
    return snap


def _fan_tool(cmd: str, arg: str = "") -> tuple[bool, str]:
    args = ["bash", str(_SCRIPTS / "tool-fan.sh"), cmd]
    if arg:
        args.append(arg)
    env = os.environ.copy()
    env["REACHY_SSH"] = _ssh_target()   # always set — fallback is pollen@{HOST}
    if _SSH_PORT:
        env["REACHY_SSH_PORT"] = _SSH_PORT
    try:
        p = subprocess.run(args, cwd=_REPO, env=env, capture_output=True, text=True, timeout=45)
        out = (p.stdout + p.stderr).strip()
        return p.returncode == 0, out[-400:]
    except subprocess.TimeoutExpired:
        return False, "fan command timed out"


@app.get("/fan")
def fan_page() -> FileResponse:
    return FileResponse(_STATIC / "fan.html")


@app.get("/favicon.ico")
def favicon() -> PlainTextResponse:
    return PlainTextResponse("", status_code=204)


@app.get("/watch")
def watch_page() -> FileResponse:
    return FileResponse(_STATIC / "watch.html")


@app.get("/lights")
def lights_page() -> FileResponse:
    return FileResponse(_STATIC / "lights.html")


@app.get("/chat")
def chat_redirect() -> RedirectResponse:
    return RedirectResponse("/conversation", status_code=302)


@app.get("/conversation")
def conversation_page() -> FileResponse:
    return FileResponse(_STATIC / "conversation.html")


@app.get("/desk")
def desk_redirect() -> RedirectResponse:
    return RedirectResponse("/conversation", status_code=302)


@app.get("/api/fan")
def fan_status() -> JSONResponse:
    try:
        snap = _fan_snapshot()
    except (TimeoutError, subprocess.TimeoutExpired, OSError) as e:
        return JSONResponse({"ok": False, "msg": f"robot unreachable: {e}"[-200:]})
    hist = list(_FAN_HIST)
    spikes = 0
    if len(hist) >= 3:
        pwms = [h.get("pwm") for h in hist if h.get("pwm") is not None]
        if len(pwms) >= 3:
            deltas = [abs(pwms[i] - pwms[i - 1]) for i in range(1, len(pwms))]
            spikes = sum(1 for d in deltas if d >= 20)
    snap["history"] = hist
    snap["pwm_spikes"] = spikes
    snap["recommend_restore"] = bool(snap.get("trip_lowered"))
    snap["recommend_calm"] = bool(
        snap.get("cusp_risk")
        or (
            snap.get("quiet_at_default")
            and snap.get("temp_c", 0) >= snap.get("trip_1_c", 45) - 1.5
            and spikes >= 2
        )
    )
    snap["recommend_anti_pulse"] = bool(
        snap.get("quiet_at_default") is False
        and not snap.get("trip_lowered")
        and not snap.get("calm_at_trip")
        and snap.get("trip_1_c", 0) >= 44.5
        and spikes >= 3
    )
    return JSONResponse(snap)


@app.post("/api/fan/calm")
def fan_calm() -> JSONResponse:
    """Raise trip_1 to 46°C — fan stays off at idle (~44–45°C), stops cusp pulsing."""
    ok, msg = _fan_tool("calm")
    _logrec("fan:calm", ok, msg)
    return JSONResponse({"ok": ok, "msg": msg, "trip_c": 46})


@app.post("/api/fan/steady")
def fan_steady(trip: int | None = None) -> JSONResponse:
    """Lower trip to 44°C — fan stays on at idle (steady hum, louder than calm)."""
    t = max(43, min(44, trip if trip is not None else 44))
    ok, msg = _fan_tool("persist", str(t))
    _logrec("fan:anti-pulse", ok, f"trip_1={t}°C {msg}")
    return JSONResponse({"ok": ok, "msg": msg, "trip_c": t})


@app.post("/api/fan/restore")
def fan_restore() -> JSONResponse:
    ok, msg = _fan_tool("restore")
    _logrec("fan:restore", ok, msg)
    return JSONResponse({"ok": ok, "msg": msg})


_BODY_YAW_LIM = math.radians(160.0)


@app.get("/api/body")
def body_status() -> JSONResponse:
    """Current body yaw — commanded and measured."""
    try:
        state = _daemon_json("/api/state/full", timeout=4)
        present = float(_daemon_json("/api/state/present_body_yaw", "GET", timeout=4))
        commanded = float(state.get("body_yaw", 0.0) or 0.0)
        return JSONResponse({
            "ok": True,
            "yaw_rad": commanded,
            "yaw_deg": round(math.degrees(commanded), 1),
            "present_rad": present,
            "present_deg": round(math.degrees(present), 1),
        })
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return JSONResponse({"ok": False, "msg": str(e)[-200:]})


@app.post("/api/body/yaw")
async def body_yaw_move(request: Request) -> JSONResponse:
    """Move body to target yaw. Body: {yaw_deg: float, duration: float (default 0.8)}."""
    if not _robot_lock.acquire(blocking=False):
        raise HTTPException(409, "Peachy is busy — wait a sec")
    try:
        body = await request.json()
        yaw_deg = max(-160.0, min(160.0, float(body.get("yaw_deg", 0.0))))
        yaw_rad = math.radians(yaw_deg)
        dur = max(0.4, min(4.0, float(body.get("duration", 0.8))))
        t0 = time.time()
        try:
            _enable_motors()
            _daemon_json("/api/move/goto", "POST", {
                "body_yaw": yaw_rad,
                "duration": dur,
                "interpolation": "minjerk",
            }, timeout=max(12.0, dur + 8))
            msg = f"body yaw → {yaw_deg:+.1f}°"
            _logrec("body:yaw", True, f"({time.time()-t0:.1f}s) {msg}")
            return JSONResponse({"ok": True, "msg": msg, "yaw_deg": yaw_deg})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            m = str(e)[-200:]
            _logrec("body:yaw", False, m)
            return JSONResponse({"ok": False, "msg": m})
    finally:
        _robot_lock.release()


@app.post("/api/body/diag")
def body_diag() -> JSONResponse:
    """Run diag-yaw.py (±17° servo test, ~15 s) and return the full output."""
    return _action("body:diag", [str(_SCRIPTS / "diag-yaw.py"), "--amp", "0.30"])


app.mount("/static", StaticFiles(directory=_STATIC), name="static")

if os.environ.get("PEACHY_GRADIO_PANEL", "0").lower() not in ("0", "false", "off"):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from gradio_panel import mount_peachy_desk

        mount_peachy_desk(app)
    except Exception as exc:  # noqa: BLE001 — desk panel is optional
        print(f"Peachy desk panel (/desk) not mounted: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Peachy control server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PEACHY_PORT", "8080")))
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()
    uvicorn.run(app, host=args.bind, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
