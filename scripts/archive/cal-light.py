#!/usr/bin/env python3
"""Voice-guided light calibration sweep for reachy_room_watch.

You're tethered at the laptop; Reachy is across the room near the controls, so
this talks you through the sweep over **Reachy's speaker** (macOS `say` → WAV →
daemon upload → play_sound). Fully automated timed phases — no typing once it
starts. It logs the SAME LightSensor reachy_room_watch uses (raw / fast EMA /
slow ambient / Δ) and at the end prints recommended thresholds.

  python scripts/cal-light.py                 # default sweep
  python scripts/cal-light.py --lead 15 --hold 14
  python scripts/cal-light.py --local-audio    # speak from laptop instead

Env: REACHY_HOST (192.168.99.2), REACHY_PORT (8000), REACHY_CAM_INDEX (0)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hostfind import resolve_host
HOST = resolve_host()
PORT = int(os.environ.get("REACHY_PORT", "8000"))

# Reuse the exact detector watch-room.py uses.
_spec = importlib.util.spec_from_file_location("rrw", _SCRIPTS / "watch-room.py")
rrw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rrw)


def _post_json(path: str, body: dict, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(f"http://{HOST}:{PORT}{path}", method="POST",
                                 data=json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        t = r.read().decode()
        return json.loads(t) if t else {}


class Voice:
    """TTS through Reachy's speaker (default) or the laptop (--local-audio)."""

    def __init__(self, local: bool) -> None:
        self.local = local
        self._cache: dict[str, str] = {}  # text -> uploaded filename
        self._tmp = Path("/tmp/reachy_cal")
        self._tmp.mkdir(exist_ok=True)

    def _wav(self, text: str, idx: int) -> Path:
        aiff = self._tmp / f"p{idx}.aiff"
        wav = self._tmp / f"p{idx}.wav"
        subprocess.run(["say", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", str(aiff), str(wav), "-d", "LEI16",
                        "-f", "WAVE"], check=True)
        return wav

    def prepare(self, lines: list[str]) -> None:
        """Pre-generate + upload every prompt so playback has no mid-sweep lag."""
        for i, text in enumerate(lines):
            if text in self._cache:
                continue
            wav = self._wav(text, i)
            if self.local:
                self._cache[text] = str(wav)
                continue
            out = subprocess.run(
                ["curl", "-s", "-m", "20", "-X", "POST",
                 f"http://{HOST}:{PORT}/api/media/sounds/upload",
                 "-F", f"file=@{wav};type=audio/wav"],
                capture_output=True, text=True)
            # Daemon replies {"status":"ok","path":"…/p0.wav"}; play_sound
            # wants the basename. Fall back to the local name (it's preserved).
            try:
                resp = json.loads(out.stdout)
                name = Path(resp.get("path", "")).name or wav.name
            except (json.JSONDecodeError, AttributeError):
                name = wav.name
            self._cache[text] = name

    def say(self, text: str, block: bool = True) -> None:
        print(f"  🔊 {text}")
        if self.local:
            subprocess.run(["afplay", self._cache.get(text, "")],
                           check=False) if block else \
                subprocess.Popen(["afplay", self._cache.get(text, "")])
            return
        try:
            _post_json("/api/media/play_sound", {"file": self._cache[text]})
        except Exception as e:
            print(f"  (speaker play failed: {e} — falling back to laptop)")
            self.local = True


def _phase(sensor, voice: Voice, label: str, instruction: str,
           hold: float, samples: list) -> dict:
    voice.say(instruction)
    print(f"--- {label} ({hold:.0f}s) ---")
    end = time.time() + hold
    vals_raw, vals_ema, vals_d = [], [], []
    while time.time() < end:
        sensor.lit()  # advances raw/ema/slow
        vals_raw.append(sensor.raw)
        vals_ema.append(sensor.ema)
        vals_d.append(sensor.ema - sensor.reference)
        remaining = end - time.time()
        if 2.4 < remaining < 2.6:
            voice.say("next", block=False)
        line = (f"  raw={sensor.raw:6.1f} ema={sensor.ema:6.1f} "
                f"ref={sensor.reference:6.1f} Δ={sensor.ema - sensor.reference:+6.1f}")
        print(line, end="\r")
        time.sleep(0.4)
    print()
    st = {
        "label": label,
        "raw_min": min(vals_raw), "raw_max": max(vals_raw),
        "raw_mean": statistics.fmean(vals_raw),
        "ema_min": min(vals_ema), "ema_max": max(vals_ema),
        "d_min": min(vals_d), "d_max": max(vals_d),
    }
    samples.append(st)
    print(f"    raw {st['raw_min']:.1f}–{st['raw_max']:.1f} "
          f"(μ{st['raw_mean']:.1f})  Δ {st['d_min']:+.1f}…{st['d_max']:+.1f}")
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description="Voice-guided light calibration sweep")
    ap.add_argument("--lead", type=float, default=12.0,
                    help="seconds to walk to the controls before the sweep (12)")
    ap.add_argument("--hold", type=float, default=12.0,
                    help="seconds to hold each phase (12)")
    ap.add_argument("--local-audio", action="store_true",
                    help="speak from the laptop instead of Reachy's speaker")
    args = ap.parse_args()

    # label, spoken instruction, hold-seconds (None = use --hold)
    SEQ = [
        ("AMBIENT",     "Starting light calibration. Do not touch anything yet.", None),
        ("WALK",        f"Walk to the controls now. You have about {int(args.lead)} "
                        "seconds. The lights may switch on as you move; that is fine.",
                        args.lead),
        ("LIGHTS_ON",   "Turn the room lights fully on.", None),
        ("LIGHTS_OFF",  "Turn the room lights fully off.", None),
        ("DIM_UP",      "Slowly dim the lights up, from off to full brightness.", None),
        ("DIM_DOWN",    "Slowly dim the lights back down to off.", None),
        ("SHADES_OPEN", "Leave the lights off. Open the window shades more.", None),
        ("SHADES_CLOSE","Close the window shades.", None),
        ("DONE",        "Calibration complete. Returning the room to you.", 0.0),
    ]

    voice = Voice(local=args.local_audio)
    print("Generating + uploading voice prompts…")
    voice.prepare([s[1] for s in SEQ] + ["next"])

    sensor = rrw.LightSensor(int(os.environ.get("REACHY_CAM_INDEX", "0")))
    sensor.adaptive = True
    sensor.calibrate_dark(2.0)
    print(f"Seeded reference ≈ {sensor.reference:.1f}\n")

    samples: list = []
    for label, instruction, hold in SEQ:
        h = args.hold if hold is None else hold
        if label == "DONE":
            voice.say(instruction)
            break
        _phase(sensor, voice, label, instruction, h, samples)
    sensor.close()

    by = {s["label"]: s for s in samples}
    print("\n================ SUMMARY ================")
    for s in samples:
        print(f"  {s['label']:<12} raw {s['raw_min']:6.1f}–{s['raw_max']:6.1f}  "
              f"Δ {s['d_min']:+6.1f}…{s['d_max']:+6.1f}")

    rec = []
    if "LIGHTS_ON" in by:
        jump = by["LIGHTS_ON"]["d_max"]
        on = max(8.0, round(jump * 0.55))
        off = max(4.0, round(jump * 0.28))
        rec += [f"REACHY_LIGHT_ON_DELTA={on:.0f}",
                f"REACHY_LIGHT_OFF_DELTA={off:.0f}"]
        print(f"\n  Lights-on Δ jump ≈ {jump:+.1f}")
    # If daylight phases (shades/dim) show big Δ drift, slow the tracker.
    drift = max((abs(by[k]["d_max"]) for k in ("SHADES_OPEN", "DIM_UP")
                 if k in by), default=0.0)
    if "LIGHTS_ON" in by and drift > by["LIGHTS_ON"]["d_max"] * 0.5:
        rec.append("REACHY_LIGHT_SLOW_EMA=0.004  # daylight swings large → slow tracker")
    print("\n  Recommended (export these or prefix the watcher):")
    for r in rec:
        print(f"    {r}")
    print("  Test:  " + " ".join(rec[:2]) +
          " python scripts/watch-room.py --dry-run")
    print("=========================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
