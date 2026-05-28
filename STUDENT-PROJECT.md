# Peachy — student project package

Everything you need to extend Peachy in your own Cursor / Claude Code session.
**Read this first**, then `CLAUDE.md` (AI orientation), then `TOOLKIT.md` (lessons).

---

## What Peachy already does (don't rebuild this)

| Feature | Where |
|---|---|
| Wake / sleep / toggle | Dashboard buttons → `scripts/ctl-toggle.py` |
| Phone dashboard | `./dashboard/run.sh` → `http://<laptop>:8080/?k=<token>` |
| Expressions, camera snap, head tune | Dashboard panels |
| Room state machine (light → wake → greet → sleep) | `scripts/watch-room.py` |
| Portal turret sounds + auto cues | `sounds/portalturret/`, dashboard sound panel |
| Conversation app handoff | Dashboard **Talk** buttons |

**The dream:** someone walks in → lights come on → Peachy wakes → greets → conversation → sleeps when the room goes dark and quiet.

~80% of that pipeline exists. **Your job** is the missing polish — starting with the dashboard **light panel**.

---

## Your assignment: Light wake / sleep panel

Build a **collapsible dashboard panel** that lets anyone see and control room-light automation:

1. **Live brightness** — poll `/api/light` (laptop webcam mean-luma)
2. **Lit / dark indicator** — clear visual (not just numbers)
3. **Start / stop** auto mode — wire to existing `/api/roomwatch/start|stop` (runs `watch-room.py`)
4. **Nice to have:** recalibrate baseline, threshold hints, link to activity log

Full spec: **`dashboard/student/LIGHT-PANEL.md`**

Starter stub is already in `dashboard/static/index.html` (`#studentLightFold`).
Replace the stub readout with your UI — keep the collapsible `<details>` pattern used by Head tune / Portal turret.

### How light detection works

- **`scripts/light_sensor.py`** — mean brightness from **Peachy's camera** (preview JPEG or fast snap over SSH)
- **`scripts/watch-room.py`** — state machine: dark → RESTING, lights on → wake path
- **`scripts/light_probe.py`** — one-shot JSON test

Start dashboard **Live** first for fast reads. No laptop webcam anywhere.

```bash
python scripts/light_probe.py --json
python scripts/watch-room.py --dry-run
python scripts/watch-room.py
```

Env knobs (optional): `REACHY_LIGHT_ON_DELTA` (default 25), `REACHY_LIGHT_OFF_DELTA` (12).

### Sounds (already wired)

When you wake/sleep/snap from the dashboard, Portal turret clips play automatically:
- Wake → **Activated**
- Sleep → **Goodnight**
- Snap → **Searching**

Change mappings in `sounds/portalturret/manifest.json`. Sync clips: dashboard → **Portal turret** → **Sync to robot**.

---

## First run on your machine

```bash
git clone https://github.com/rootlake/pomfret_reachy.git
cd pomfret_reachy

python3 -m venv reachy_mini_env
source reachy_mini_env/bin/activate
pip install -r requirements-student.txt

# connect to the robot (same Wi‑Fi as Peachy at school)
./scripts/net-connect.sh

# dashboard (recommended)
./go
# open the printed URL with ?k= token once; cookie lasts 90 days
```

Or use the menu: `./peachy`

**Build your own app:** see [`docs/BUILD-YOUR-APP.md`](docs/BUILD-YOUR-APP.md)

---

## Golden rules (read `CLAUDE.md` for detail)

1. **Enable motors before any move** — silent no-op otherwise
2. **Camera on robot only** — room light uses Peachy's head camera; laptop webcam is not used
3. **Try `--dry-run` first** on anything autonomous
4. **Daemon flaky after power-cycle?** `./scripts/net-connect.sh --fix`
5. **Don't lower fan trip** — default 45°C is quietest; see `/fan` monitor
6. **Body yaw doesn't turn** — mechanical; use head yaw offset only
7. **School blocks Tailscale** — use LAN or teacher's SSH tunnel

---

## Repo map

```
peachy                  interactive menu (human entry)
CLAUDE.md               AI assistant orientation
TOOLKIT.md              graduated exercises
STUDENT-PROJECT.md      this file
dashboard/              phone + desktop web UI
  server.py               FastAPI backend
  static/index.html       single-page app (your panel goes here)
  student/LIGHT-PANEL.md  your assignment spec
scripts/
  ctl-toggle.py           wake / sleep / calibrate
  watch-room.py           light → state machine (the brain)
  light_sensor.py         webcam brightness (reuse this)
  light_probe.py          one-shot light JSON
  sound_sync.py           upload WAVs to robot speaker
sounds/portalturret/      Portal turret WAVs + manifest.json
docs/                   deeper Reachy REST/SDK reference
  BUILD-YOUR-APP.md       how to build scripts, dashboard panels, and apps
apps/boo_hide/          example ReachyMiniApp (say "boo" → sleep)
```

---

## Success criteria

By the end of your build window:

1. **Dashboard light panel** — live lit/dark, start/stop room watch, looks good on phone
2. **Demo** — flip room lights → Peachy wakes with turret sound → goes back to sleep when dark
3. **You can explain** how `LightSensor` and `watch-room.py` connect

Stretch goals (after the panel ships):
- Richer greet animation before conversation (`watch-room.py` → `apply("AWAKE")`)
- Pick different sleep sound (resting, hibernating) from the turret board
- Robot camera instead of laptop webcam for light (swap `LightSensor` source)

---

## Getting help

- Open this folder in **Cursor or Claude Code** — `CLAUDE.md` orients the AI
- `TOOLKIT.md` for deeper learning
- Teacher for robot access / tunnel / blocked issues
- Activity log on the dashboard for debugging (`/api/log`)

---

## Cheatsheet

```bash
./peachy                              # menu
./dashboard/run.sh                    # web UI
./scripts/net-connect.sh              # find robot
./scripts/net-connect.sh --fix        # revive daemon
python scripts/light_probe.py --json  # light readout
python scripts/watch-room.py --dry-run
python scripts/sound_sync.py --list   # turret sounds on robot?
```
