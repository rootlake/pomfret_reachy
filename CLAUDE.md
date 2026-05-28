# CLAUDE.md — orientation for this repo

Controlling a **Reachy Mini** wireless robot ("Peachy") in a classroom.
If you're an AI assistant picking this up: read this once, then `TOOLKIT.md`
for the guided script tour. Build small, test with `--dry-run` first, keep the
naming scheme.

**Friendliest entry points:**
- **`README.md`** — clone, install, doc map (start here if you're new)
- `./peachy` — interactive menu (auto-sources venv, wraps day-to-day scripts)
- `./run.sh` — start the phone dashboard (`--restart` to replace, `--qr` to print QR)
- `./scripts/net-connect.sh` — raw robot connect/find step

Power users / scripts call the underlying tools directly; the menu is for humans.

## What this is

A set of small Python/bash tools that drive the robot over its **daemon REST
API** (`http://<robot>:8000/api/...`), plus a phone **dashboard**. The headline
behaviour is `watch-room.py`: sense the room → wake → greet → hand off to the
conversation app → sleep when empty.

## Golden rules (hard-won — don't relearn these the hard way)

1. **Enable motors before any move.** `play/wake_up`, `goto_sleep`, `goto` are
   silent no-ops if `motor_control_mode` is `disabled`. Always
   `POST /api/motors/set_mode/enabled` first. (`ctl-*` scripts now do.)
2. **No camera over REST.** Frames come from the Python SDK and only work
   reliably **on the robot** (localhost). `cam-snap.py` runs there.
3. **Motors-disabled pose is ambiguous** (head flops under gravity) — that's
   why state lives in `.run/reachy_toggle_state.json`, not read from pose.
4. **Daemon backend can come up degraded** after power-cycles ("Backend not
   running" / moves don't actuate). Fix: `./scripts/net-connect.sh --fix`
   (restarts the daemon over SSH) or `sudo systemctl restart
   reachy-mini-daemon` then wait ~45s.
5. **Sleep is a tradeoff** (`REACHY_SLEEP_MODE`): `gravcomp` (default) keeps
   the asleep pose but the gravity-hold hums; `limp` is silent but the head
   relaxes / antennae rise; `hold` is firmest/loudest. Not a fault — physics.
6. **The whine is the head's CM4 cooling fan**, not the motors. Normal. Don't
   chase it as a defect.
7. **Body yaw works** — the turntable servo is functional. Use `body_yaw` in
 `goto` (±160°) or the dashboard "Body turn" panel. `diag-yaw.py` confirms
 both head and body servos respond. `cal-head.py` still handles the head-yaw
 cosmetic offset if facing looks off.

## Connect & run (no fuss)

```bash
./scripts/net-connect.sh         # finds the robot (LAN/SSH); caches it
python scripts/ctl-toggle.py status   # any script auto-resolves the host
```
Scripts find the robot via `hostfind.py` (env `REACHY_HOST` → `.run/reachy_host`
cache → probe). **No `source` needed.** `--dry-run` (on `watch-room.py`) =
sensors only, no movement — always try that first.

## Script map (`tag-verb` — `ls scripts/` self-organizes)

| Tag | Scripts | Purpose |
|---|---|---|
| `ctl-` | `ctl-toggle.py` (sleep/wake/calibrate/status), `ctl-wake.py` (raw REST), `ctl-express.py` (expressions + `express <name>`) | direct control |
| `watch-` | `watch-room.py` | the capstone state machine (the dream) |
| `cam-` | `cam-snap.py` | camera (run **on the robot**) |
| `cal-` | `cal-head.py` (neutral-offset jog — must type `save`) | tuning |
| `diag-` | `diag-yaw.py` | diagnostics |
| `net-` | `net-connect.sh` (find/revive), `net-deploy.sh` (dashboard→robot+Funnel), `net-uplink.sh` (Fortinet-proof remote SSH + tunnel via VPS) | connectivity |
| `app-` | `app-conversation.sh` (start/stop the official conversation app) | conversation-app service |
| `tool-` | `tool-qr.py` | QR for the dashboard URL |
| lib | `hostfind.py` | host auto-resolver (imported; keep importable) |

`dashboard/` = phone UI; `net-deploy.sh` installs it **on the robot** as a
systemd service. It just calls these same scripts (single source of truth).

## Calibration first

`ctl-express.py` and `watch-room.py` need real poses:
`python scripts/ctl-toggle.py calibrate` (records this robot's sleep/wake
poses to `.run/`). `cal-head.py` adds a `head_offset` applied to every pose —
**you must type `save`** in its REPL or it doesn't persist.

## Network reality (don't fight it)

The school Fortinet does TLS interception that **permanently breaks
Tailscale** on the robot (and the laptop). Confirmed, unfixable robot-side.
**But everything the project needs runs on the school LAN / on the robot** —
local control + the LLM conversation app both work. Remote/off-LAN access is
optional and currently dropped. `tailscaled` is disabled on the robot at
school by design (re-enable only if it moves to a network where TS works).

## Deeper references

- `TOOLKIT.md` — guided, exercise-driven tour of every script (start here)
- `docs/reachy_mini_reference.md` — network/SSH handbook + command table
- `docs/reachy_mini_build_reference.md` — distilled REST API + SDK + app contract

## Conventions for extending

`tag-verb` filenames; host via `from hostfind import resolve_host`; REST for
motion/state, SDK-on-robot for camera/audio; enable motors before moving;
add `--dry-run` to anything autonomous; keep the dashboard delegating to
scripts rather than duplicating logic.
