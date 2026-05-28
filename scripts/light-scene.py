#!/usr/bin/env python3
"""Interactive light-scene recorder — lights on/off + pose, optional note.

The signal that matters for wake/sleep is **overhead lights on vs off** (and
head pose). Blinds, sky, time-of-day → optional freeform note if you care.

  python scripts/light-scene.py              # toggle board
  python scripts/light-scene.py probe
  python scripts/light-scene.py capture
  python scripts/light-scene.py analyze
  python scripts/light-scene.py matrix      # 2×2 lights × pose checklist
  python scripts/light-scene.py matrix-run  # guided four-shot session
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_RUN = _REPO / ".run"
_SCENES_DIR = _RUN / "light_scenes"
_SCENES_LOG = _RUN / "light_scenes.jsonl"
_SESSION_FILE = _RUN / "light_scene_session.json"
_STATE_FILE = _RUN / "reachy_toggle_state.json"

sys.path.insert(0, str(_REPO / "scripts"))
from hostfind import resolve_host  # noqa: E402
from light_lab import (  # noqa: E402
    analyze_path,
    annotate,
    capture_frame,
    effective_off_delta,
    effective_on_delta,
    load_tune,
)

HOST = resolve_host()
PORT = int(os.environ.get("REACHY_PORT", "8000"))

# Core toggles — everything else goes in ``note`` if needed
DIMENSIONS: dict[str, list[tuple[str, str, str]]] = {
    "lights": [("f", "off", "OFF"), ("n", "on", "ON")],
    "pose": [("s", "asleep", "SLEEP"), ("e", "semi", "SEMI"), ("w", "awake", "WAKE")],
}

DEFAULT_STATE = {
    "lights": "off",
    "pose": "asleep",
    "note": "blinds mixed, partly down",  # typical room — edit with N
}

_TAG_FOR: dict[tuple[str, str], str] = {
    ("lights", "on"): "lights_on",
    ("lights", "off"): "lights_off",
}

_LETTER_TO: dict[str, tuple[str, str]] = {}
for _dim, _opts in DIMENSIONS.items():
    for _letter, _val, _ in _opts:
        _LETTER_TO[_letter] = (_dim, _val)
        _LETTER_TO[_letter.lower()] = (_dim, _val)
        if _letter != _letter.lower():
            _LETTER_TO[_letter.upper()] = (_dim, _val)


def _tags_from_state(state: dict) -> list[str]:
    tag = _TAG_FOR.get(("lights", state.get("lights", "off")))
    return [tag] if tag else []


def _state_from_legacy(data: dict) -> dict:
    state = dict(DEFAULT_STATE)
    state["note"] = data.get("note", "")
    if data.get("pose"):
        state["pose"] = data["pose"]
    if data.get("lights"):
        state["lights"] = data["lights"]
    for tag in data.get("tags", []):
        if tag == "lights_on":
            state["lights"] = "on"
        elif tag == "lights_off":
            state["lights"] = "off"
    return state


def load_state() -> dict:
    try:
        raw = json.loads(_SESSION_FILE.read_text())
        if isinstance(raw, dict):
            if "lights" in raw:
                merged = {**DEFAULT_STATE, **raw}
            else:
                merged = _state_from_legacy(raw)
            for dim in DIMENSIONS:
                if merged.get(dim) not in {v for _, v, _ in DIMENSIONS[dim]}:
                    merged[dim] = DEFAULT_STATE[dim]
            if merged.get("pose") not in {v for _, v, _ in DIMENSIONS["pose"]}:
                merged["pose"] = DEFAULT_STATE["pose"]
            return merged
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        pass
    return dict(DEFAULT_STATE)


def save_state(state: dict) -> None:
    _RUN.mkdir(parents=True, exist_ok=True)
    slim = {k: state.get(k, DEFAULT_STATE[k]) for k in DEFAULT_STATE}
    _SESSION_FILE.write_text(json.dumps(slim, indent=2) + "\n")


def primary_label(state: dict) -> str:
    return _TAG_FOR.get(("lights", state.get("lights", "off")), "lights_off")


def human_summary(state: dict) -> str:
    parts = [f"lights {state.get('lights', '?')}", f"Peachy {state.get('pose', '?')}"]
    if state.get("note"):
        parts.append(state["note"])
    return " · ".join(parts)


def _toggle_state() -> str:
    try:
        return json.loads(_STATE_FILE.read_text()).get("state", "unknown")
    except (FileNotFoundError, json.JSONDecodeError):
        return "unknown"


def _calibration() -> tuple[dict, list, dict, list]:
    cal = json.loads(_STATE_FILE.read_text())["calibration"]
    s, w = cal["sleep"], cal["wake"]
    return s["head_pose"], list(s["antennas"]), w["head_pose"], list(w["antennas"])


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _interp_pose(t: float) -> tuple[dict, list[float]]:
    s_hp, s_ant, w_hp, w_ant = _calibration()
    keys = ("x", "y", "z", "roll", "pitch", "yaw")
    hp = {k: _lerp(float(s_hp.get(k, 0)), float(w_hp.get(k, 0)), t) for k in keys}
    ant = [_lerp(float(s_ant[i]), float(w_ant[i]), t) for i in range(2)]
    return hp, ant


def _http_goto(hp: dict, ant: list[float], dur: float = 1.2) -> None:
    import urllib.request

    urllib.request.urlopen(
        urllib.request.Request(
            f"http://{HOST}:{PORT}/api/motors/set_mode/enabled",
            data=b"{}", method="POST",
            headers={"Content-Type": "application/json"},
        ),
        timeout=10,
    )
    body = json.dumps({
        "head_pose": hp, "antennas": ant,
        "duration": dur, "interpolation": "minjerk",
    }).encode()
    urllib.request.urlopen(
        urllib.request.Request(
            f"http://{HOST}:{PORT}/api/move/goto",
            data=body, method="POST",
            headers={"Content-Type": "application/json"},
        ),
        timeout=max(30, dur + 15),
    )
    time.sleep(dur + 0.3)


def _run_toggle(cmd: str) -> bool:
    p = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "ctl-toggle.py"), cmd],
        cwd=_REPO, capture_output=True, text=True, timeout=120,
    )
    if p.returncode != 0:
        print(p.stdout + p.stderr)
    return p.returncode == 0


def ensure_pose(pose: str) -> None:
    pose = pose.lower()
    if pose == "asleep":
        if _toggle_state() != "asleep":
            print("→ sleep …")
            _run_toggle("sleep")
        return
    if pose == "awake":
        if _toggle_state() != "awake":
            print("→ wake …")
            _run_toggle("wake")
        return
    if pose == "semi":
        if _toggle_state() == "asleep":
            _run_toggle("wake")
        print("→ semi-wake (~55%) …")
        hp, ant = _interp_pose(0.55)
        _http_goto(hp, ant)
        return
    raise ValueError(f"unknown pose {pose!r}")


def probe_snapshot() -> dict | None:
    from light_sensor import LightSensor

    sensor = LightSensor()
    try:
        sensor.read()
        sensor.lit()
        return sensor.snapshot()
    except OSError:
        return None
    finally:
        sensor.close()


def record_state(state: dict | None = None) -> dict:
    state = state or load_state()
    label = primary_label(state)
    tags = _tags_from_state(state)
    pose = state.get("pose", "asleep")

    ensure_pose(pose)
    _SCENES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    img_name = f"{stamp}_{label}_{pose}.jpg"
    img_path = _SCENES_DIR / img_name

    print("  📷 capturing …")
    if not capture_frame(img_path):
        return {"ok": False, "msg": "camera failed — try Live preview / SSH"}

    analysis = analyze_path(img_path)
    annot_path = _SCENES_DIR / f"{stamp}_{label}_{pose}_annot.jpg"
    annotate(img_path, annot_path)
    snap = probe_snapshot() or {}

    rec = {
        "ok": True,
        "id": uuid.uuid4().hex[:12],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "label": label,
        "state": {k: state[k] for k in DEFAULT_STATE if k in state},
        "tags": tags,
        "pose": pose,
        "note": state.get("note", ""),
        "image": img_name,
        "annot": annot_path.name,
        "toggle_state": _toggle_state(),
        "regions": analysis.get("regions", {}),
        "sensor": snap,
        "tune_at_capture": load_tune(),
        "on_delta": effective_on_delta(),
        "off_delta": effective_off_delta(),
    }
    with _SCENES_LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")

    full = rec["regions"].get("full", {})
    print(f"  ✓ saved  full={full.get('mean', '?')}  "
          f"lower={rec['regions'].get('lower', {}).get('mean', '?')}")
    print(f"    {human_summary(state)}")
    return rec


def load_scenes() -> list[dict]:
    if not _SCENES_LOG.is_file():
        return []
    out: list[dict] = []
    for line in _SCENES_LOG.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _render_row(title: str, dim: str, state: dict) -> str:
    cur = state.get(dim, "")
    cells: list[str] = []
    for letter, val, short in DIMENSIONS[dim]:
        mark = "*" if cur == val else " "
        cells.append(f"({letter}){short}{mark}")
    return f"  {title:<9} " + "   ".join(cells)


def _print_board(state: dict, probe: dict | None = None) -> None:
    print()
    print("═" * 62)
    print(f"  Peachy Light Scene   {HOST}:{PORT}   robot={_toggle_state()}")
    print("═" * 62)
    print(_render_row("Lights", "lights", state))
    print(_render_row("Peachy", "pose", state))
    print("─" * 62)
    print(f"  Recording:  {human_summary(state)}")
    if state.get("note"):
        print(f"  Note:       {state['note']}  (N to edit — blinds/sky/weather)")
    if probe:
        print(f"  Camera:   ema={probe.get('ema', '?')}  ref={probe.get('ref', '?')}  "
              f"Δ={probe.get('delta', '?')}  lit={probe.get('lit', '?')}")
    else:
        print("  Camera:   (press p to probe)")
    print("─" * 62)
    print("  Toggle: f/n lights   s/e/w pose   Record: Enter   g guided   p probe   q quit")
    print("  Also:   o analyze  m matrix  M matrix-run  t pose-test  x export  L list  N note")
    print("═" * 62)


def _ask_choice(prompt: str, options: list[tuple[str, str, str]], default: str) -> str:
    parts = []
    for letter, val, lbl in options:
        d = "*" if val == default else ""
        parts.append(f"({letter}){lbl}{d}")
    print(f"\n  {prompt}")
    print("  " + "   ".join(parts))
    raw = input("  > ").strip()
    if not raw:
        return default
    ch = raw[0]
    for letter, val, _ in options:
        if ch == letter or ch.lower() == letter.lower():
            return val
    return default


def guided_setup(state: dict) -> dict:
    """Three questions — lights, pose, optional context note."""
    print("\n  ── Quick setup (Enter = keep *) ──\n")
    state = dict(state)
    state["lights"] = _ask_choice("Overhead lights?", DIMENSIONS["lights"], state["lights"])
    state["pose"] = _ask_choice("Peachy pose for capture?", DIMENSIONS["pose"], state["pose"])
    print("\n  Anything else worth noting? (blinds, sky, weather — or Enter to skip)")
    print(f"  current: {state.get('note') or '(none)'}")
    note = input("  > ").strip()
    if note:
        state["note"] = note

    while True:
        print(f"\n  Record as: {human_summary(state)}")
        snap = probe_snapshot()
        if snap:
            print(f"  Camera: ema={snap['ema']} Δ={snap.get('delta', '?')} (compare ON vs OFF later)")
        print("  [Enter] record   [e] edit toggles   [c] cancel")
        raw = input("  > ").strip().lower()
        if raw in ("c", "q"):
            return load_state()
        if raw == "e":
            save_state(state)
            return state
        save_state(state)
        record_state(state)
        return state


def apply_letter(state: dict, letter: str) -> bool:
    if letter not in _LETTER_TO:
        return False
    dim, val = _LETTER_TO[letter]
    state[dim] = val
    save_state(state)
    return True


def menu_loop() -> int:
    state = load_state()
    if not _SESSION_FILE.is_file():
        save_state(state)

    last_probe: dict | None = None
    while True:
        _print_board(state, last_probe)
        raw = input("\n  > ").strip()
        if raw in ("", "r", "R"):
            record_state(state)
            last_probe = probe_snapshot()
            continue
        if raw.lower() in ("q", "quit", "exit"):
            print("bye")
            return 0
        if raw.lower() in ("?", "g", "guide"):
            state = guided_setup(state)
            last_probe = probe_snapshot()
            continue
        if raw.lower() == "p":
            last_probe = probe_snapshot()
            if last_probe:
                print(f"  ema={last_probe['ema']} ref={last_probe['ref']} "
                      f"Δ={last_probe['delta']:+.1f} lit={last_probe['lit']}")
            else:
                print("  probe failed")
            continue
        if raw.lower() == "t":
            pose_test()
            last_probe = probe_snapshot()
            continue
        if raw.lower() == "m":
            cmd_matrix()
            continue
        if raw.lower() == "M":
            guided_matrix()
            continue
        if raw.lower() == "o":
            cmd_analyze()
            continue
        if raw.lower() == "x":
            cmd_export()
            continue
        if raw.lower() == "l":
            cmd_list()
            continue
        if raw.lower() == "n":
            note = input("  note (Enter to clear): ").strip()
            state["note"] = note
            save_state(state)
            continue
        if raw.lower() == "z" and _toggle_state() != "asleep":
            _run_toggle("sleep")
            continue

        if len(raw) == 1 and apply_letter(state, raw):
            continue
        # allow multi-toggle e.g. "fn" flips lights then nothing - only first char
        if len(raw) >= 1 and apply_letter(state, raw[0]):
            continue
        print("  ? — try a letter toggle, Enter to record, g for guided, q quit")


def pose_test() -> None:
    print("\n  Pose test (no save):\n")
    for pose in ("asleep", "semi", "awake"):
        ensure_pose(pose)
        tmp = _SCENES_DIR / "_probe_tmp.jpg"
        _SCENES_DIR.mkdir(parents=True, exist_ok=True)
        if capture_frame(tmp):
            r = analyze_path(tmp).get("regions", {})
            print(f"  {pose:6}  full={r.get('full', {}).get('mean', '?'):>6}  "
                  f"lower={r.get('lower', {}).get('mean', '?'):>6}  "
                  f"upper={r.get('upper', {}).get('mean', '?'):>6}")
    ans = input("\n  Return to sleep? [Y/n] ").strip().lower()
    if ans != "n":
        _run_toggle("sleep")


def cmd_probe() -> int:
    state = load_state()
    snap = probe_snapshot()
    print(f"{HOST}:{PORT}  robot={_toggle_state()}")
    print(f"  Reality: {human_summary(state)}")
    if snap:
        print(f"  ema={snap['ema']} ref={snap['ref']} Δ={snap['delta']:+.1f} lit={snap['lit']}")
    return 0


def _rec_lights_pose(rec: dict) -> tuple[str, str]:
    st = rec.get("state") or {}
    lights = st.get("lights") or ("on" if rec.get("label") == "lights_on" else "off")
    pose = rec.get("pose") or st.get("pose") or "asleep"
    return lights, pose


def matrix_latest() -> dict[tuple[str, str], dict]:
    """Latest recorded scene per (lights, pose) cell."""
    cells: dict[tuple[str, str], dict] = {}
    for rec in load_scenes():
        key = _rec_lights_pose(rec)
        cells[key] = rec  # jsonl append order → last wins
    return cells


def _matrix_cell_line(lights: str, pose: str, rec: dict | None) -> str:
    if not rec:
        return "  — missing —"
    full = rec.get("regions", {}).get("full", {}).get("mean", "?")
    img = rec.get("image", "")
    return f"  full={full}  {rec.get('ts', '?')}  {img}"


def cmd_matrix() -> int:
    cells = matrix_latest()
    print("\n  Capture matrix (full-frame mean) — need all four for pose vs lights:\n")
    print("              asleep                    awake")
    for lights, row in (("off", "Lights OFF"), ("on", "Lights ON ")):
        a = cells.get((lights, "asleep"))
        w = cells.get((lights, "awake"))
        print(f"  {row}  {_matrix_cell_line(lights, 'asleep', a).strip():26}  "
              f"{_matrix_cell_line(lights, 'awake', w).strip()}")
    have = len(cells)
    print(f"\n  {have}/4 cells filled  →  light_scenes.jsonl")
    if have < 4:
        missing = [f"{l}/{p}" for l in ("off", "on") for p in ("asleep", "awake")
                   if (l, p) not in cells]
        print(f"  missing: {', '.join(missing)}")
        print("  run:  python scripts/light-scene.py matrix-run")
    print("\n  Room-watch tuning uses the **asleep** row (OFF vs ON Δ).")
    print("  Awake row shows how much pose alone fakes brightness.\n")
    return 0


def guided_matrix() -> int:
    """Walk through four labeled captures: OFF×2 then ON×2."""
    plan = [
        ("off", "asleep", "1/4  Overhead lights OFF, Peachy asleep (room-watch pose)"),
        ("off", "awake", "2/4  Still OFF — wake Peachy for head-up view"),
        ("on", "asleep", "3/4  Flip classroom lights ON — sleep Peachy first"),
        ("on", "awake", "4/4  Still ON — wake for head-up view"),
    ]
    print("\n  ── Four-shot matrix (Enter = record, s skip, q quit) ──\n")
    for lights, pose, prompt in plan:
        print(f"  {prompt}")
        raw = input("  Ready? [Enter] record  [s] skip  [q] quit  > ").strip().lower()
        if raw == "q":
            return 0
        if raw == "s":
            continue
        state = {"lights": lights, "pose": pose, "note": load_state().get("note", "")}
        save_state(state)
        record_state(state)
    cmd_matrix()
    cmd_analyze()
    return 0


def cmd_list(n: int = 15) -> int:
    scenes = load_scenes()
    for rec in scenes[-n:]:
        st = rec.get("state") or {}
        summary = human_summary({**DEFAULT_STATE, **st}) if st else ",".join(rec.get("tags", [])[:3])
        full = rec.get("regions", {}).get("full", {}).get("mean", "?")
        print(f"  {rec.get('ts')}  full={full}  {summary[:70]}")
    print(f"  ({len(scenes)} → {_SCENES_LOG})")
    return 0


def cmd_analyze() -> int:
    scenes = load_scenes()
    if not scenes:
        print("no scenes — run matrix-run when you can flip classroom lights")
        return 1
    cells = matrix_latest()
    if cells:
        print("\n  2×2 matrix (full mean):")
        print(f"              {'asleep':>8}  {'awake':>8}")
        for lights in ("off", "on"):
            row = []
            for pose in ("asleep", "awake"):
                rec = cells.get((lights, pose))
                m = rec.get("regions", {}).get("full", {}).get("mean") if rec else None
                row.append(f"{m:8.1f}" if m is not None else "     —  ")
            print(f"  lights {lights:3}  {row[0]}  {row[1]}")
        off_a = cells.get(("off", "asleep"), {}).get("regions", {}).get("full", {}).get("mean")
        on_a = cells.get(("on", "asleep"), {}).get("regions", {}).get("full", {}).get("mean")
        if off_a is not None and on_a is not None:
            d = on_a - off_a
            print(f"\n  asleep ON−OFF Δ={d:.1f}  suggested on_delta≈{max(8, d * 0.55):.1f}")
        off_w = cells.get(("off", "awake"), {}).get("regions", {}).get("full", {}).get("mean")
        if off_a is not None and off_w is not None:
            print(f"  pose-only (OFF row): awake−asleep = {off_w - off_a:+.1f}  "
                  f"(why room-watch uses asleep)")
    by_lights: dict[str, list[float]] = {}
    for rec in scenes:
        lights, _ = _rec_lights_pose(rec)
        m = rec.get("regions", {}).get("full", {}).get("mean")
        if m is not None:
            by_lights.setdefault(lights, []).append(m)
    if len(by_lights) > 1:
        off, on = by_lights.get("off", []), by_lights.get("on", [])
        if off and on:
            d = sum(on) / len(on) - sum(off) / len(off)
            print(f"\n  all scenes pooled: ON−OFF Δ≈{d:.1f}")
    return 0


def cmd_export() -> int:
    scenes = load_scenes()
    if not scenes:
        return 1
    out = _RUN / "light_scenes_export.csv"
    cols = ["ts", "lights", "pose", "note", "full_mean", "lower_mean", "ema", "delta", "lit", "image"]
    lines = [",".join(cols)]
    for rec in scenes:
        st = rec.get("state") or {}
        reg, sen = rec.get("regions", {}), rec.get("sensor", {})
        lights = st.get("lights") or ("on" if rec.get("label") == "lights_on" else "off")
        lines.append(",".join(str(x) for x in [
            rec.get("ts"), lights, rec.get("pose"),
            (rec.get("note") or "").replace(",", ";"),
            reg.get("full", {}).get("mean"), reg.get("lower", {}).get("mean"),
            sen.get("ema"), sen.get("delta"), sen.get("lit"), rec.get("image"),
        ]))
    out.write_text("\n".join(lines) + "\n")
    print(f"exported → {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Peachy light scene recorder")
    ap.add_argument("cmd", nargs="?", default="menu",
                    choices=("menu", "probe", "capture", "list", "analyze", "export",
                             "pose-test", "guide", "matrix", "matrix-run"))
    ap.add_argument("-n", type=int, default=15)
    args = ap.parse_args()

    if args.cmd == "menu":
        return menu_loop()
    if args.cmd == "guide":
        guided_setup(load_state())
        return 0
    if args.cmd == "probe":
        return cmd_probe()
    if args.cmd == "list":
        return cmd_list(args.n)
    if args.cmd == "analyze":
        return cmd_analyze()
    if args.cmd == "matrix":
        return cmd_matrix()
    if args.cmd == "matrix-run":
        return guided_matrix()
    if args.cmd == "export":
        return cmd_export()
    if args.cmd == "pose-test":
        pose_test()
        return 0
    if args.cmd == "capture":
        rec = record_state()
        return 0 if rec.get("ok") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
