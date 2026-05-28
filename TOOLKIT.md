# Peachy Toolkit — a guided tour (for the student)

You're inheriting a working set of scripts that control a **Reachy Mini**
("Peachy"). Goal: *understand* them, then extend them — not just run them.
Work through these in order. Each is small and commented; open it, read it,
run it, then do the **Try / Modify** exercise before moving on.

> First, connect: `./scripts/net-connect.sh` (finds the robot on the network).
> Then any script "just works" — they auto-resolve the robot via `hostfind.py`.
> Nothing to `source`. `REACHY_HOST=<ip>` overrides if you ever need to.

## How Peachy is controlled (the one big idea)

A **daemon** runs on the robot exposing an HTTP REST API on port 8000
(`/api/...`). Our scripts are just HTTP clients — `urllib` POSTing JSON. That's
it. No magic. `curl http://<robot>:8000/docs` shows the whole API.
The **camera/audio** are the exception: no REST for frames, so camera work
uses the Python SDK and must run **on the robot** (`cam-snap.py`).

Naming: `tag-verb` so `ls scripts/` self-organizes — `ctl-` control,
`watch-` autonomous, `cam-` camera, `cal-` calibration, `diag-` diagnostics,
`net-` connectivity, `app-` conversation app, `tool-` misc, `hostfind.py` lib.

---

### 1. `ctl-wake.py` — the absolute basics
Wake/sleep via two REST calls. Read it first; it's the smallest real example.
- **Run:** `python scripts/ctl-wake.py wake` then `... sleep`
- **Try:** open the URL it prints in a browser → `/docs`. Find `/api/move/play`.
- **Modify:** add a `--print-state` flag that GETs `/api/state/full` and prints
  the head pose. (Pattern you'll reuse everywhere.)

### 2. `ctl-toggle.py` — state + safety
Same idea but tracks state in `.run/reachy_toggle_state.json`, has
`calibrate`, and disables/holds motors on sleep (`REACHY_SLEEP_MODE`).
- **Run:** `python scripts/ctl-toggle.py calibrate` (records this robot's real
  sleep/wake poses — needed by the pose scripts), then `... status`.
- **Concept:** why a *state file* instead of reading pose? Motors-disabled =
  the head flops; pose alone is ambiguous. Engineering around hardware reality.
- **Modify:** add a `nap` command = sleep for 10s then wake.

### 3. `ctl-express.py` — animation = keyframes
Expressions are lists of `(head_pose, antennas, duration)` interpolated
between the calibrated sleep/wake poses. Read `_expr_frames()`.
- **Run:** `python scripts/ctl-express.py wake` → pick expressions in the menu.
- **Modify:** add a new expression (e.g. `"dizzy"` — roll back and forth).
  This is the core skill for making Peachy expressive.

### 4. `cam-snap.py` — the camera (runs ON the robot)
SDK demo: `mini.media.get_frame()` → JPEG. Teaches why some things must run
on the robot, not the laptop.
- **Run (on robot):** `ssh pollen@reachy-mini.local`,
  `source /venvs/apps_venv/bin/activate`, `python ~/peachy/scripts/cam-snap.py`
- **Modify:** save 5 frames 1s apart; compute which is brightest (numpy).

### 5. `cal-head.py` — tuning against the real world
Jogs the head live to find a neutral pose offset; **must type `save`** in the
REPL or nothing persists. See the antenna **plumb-line** trick (the crossing
point should sit directly above the neck/base when roll is level). For an
example of how messy real sensors are (auto-exposure, daylight drift) see
`scripts/archive/cal-light.py` — a deliberately-shelved approach that taught
us to use a light-bank ROI instead.

### 6. `watch-room.py` — the capstone (the dream)
A state machine: **light + camera-motion + speech** →
`RESTING → SEMI_WAKE → AWAKE → (nod + conversation app) → idle/dark → DEEP_SLEEP`.
Read `LightSensor` (adaptive ambient tracker, EMA, hysteresis) and the
`apply()` / debounce loop — that's real reactive-robotics structure.
- **Run safely first:** `python scripts/watch-room.py --dry-run` (sensors,
  **no movement**). Flip lights / talk / walk by; watch the state column.
- **Then live:** `python scripts/watch-room.py` (needs `ctl-toggle.py
  calibrate` done first).
- **Tunables (env):** `REACHY_IDLE_SLEEP_S`, `REACHY_MOTION_THRESH`,
  `REACHY_SLEEP_MODE` (`gravcomp` keeps antennae down but hums / `limp` silent
  but antennae rise / `hold`), `REACHY_CONVO`, `REACHY_GREET`.
- **First real feature to build:** make the greeting better — e.g. a wave +
  a spoken line before the conversation app starts (see `cal-light.py`'s
  `Voice` class for the TTS→speaker pattern).

---

## Architecture notes worth knowing

- **`hostfind.py`** — every script's host auto-resolves: `REACHY_HOST` env →
  `.run/reachy_host` cache → probe LAN/Tailscale/IP. That's why nothing needs
  `source`-ing.
- **The dashboard** (`dashboard/`) is a phone UI; `net-deploy.sh` installs it
  *on the robot* as a service so a phone controls Peachy. It just calls these
  same scripts — single source of truth.
- **Sensor abstraction:** `watch-room.py`'s `LightSensor` has a clean
  `.lit()/.read()` contract so it can be swapped (laptop webcam → robot cam →
  hardware sensor) without touching the state machine. Good design to imitate.
- **Network reality (important):** the school firewall (Fortinet) blocks
  Tailscale, so *remote* access is limited at school — but **everything you
  build runs locally / on the robot and is unaffected.** Don't fight this.

## When you continue with your own Claude Code / Cursor session

Point it at **`CLAUDE.md`** (repo root) — it orients an AI assistant to the
constraints and conventions in one read. Also see `docs/` for the distilled
Reachy Mini API/SDK references. Build small, run `--dry-run` first, keep the
`tag-verb` naming.
