# Pomfret Reachy Mini ("Peachy")

Python tools and a phone-friendly dashboard for controlling a **Reachy Mini** robot in the classroom — wake/sleep, expressions, room sensing, conversation handoff, and a path to **build your own apps**.

Built for Pomfret School students. Works on any Reachy Mini on the same Wi‑Fi as your laptop.

**Repository:** [github.com/rootlake/pomfret_reachy](https://github.com/rootlake/pomfret_reachy)

---

## What you get

| Piece | What it does |
|---|---|
| **`./peachy`** | Interactive menu — the human-friendly entry point |
| **`./go`** | Connect to the robot, start the dashboard, print URLs |
| **`./run.sh`** | Phone/web dashboard (wake, sleep, expressions, room watch) |
| **`scripts/`** | Small Python/bash tools — REST control, sensing, calibration |
| **`dashboard/`** | FastAPI backend + single-page web UI |
| **`apps/boo_hide/`** | Example Reachy Mini app (say "boo" → sleep) |
| **`sounds/portalturret/`** | Portal turret WAV cues for wake/sleep |

The headline behavior is **`watch-room.py`**: sense the room → wake → greet → hand off to conversation → sleep when the room goes dark and quiet. About 80% of that pipeline is built; your job is to polish and extend it.

---

## Quick start (students)

### 1. Clone and install

```bash
git clone https://github.com/rootlake/pomfret_reachy.git
cd pomfret_reachy

python3 -m venv reachy_mini_env
source reachy_mini_env/bin/activate
pip install -r requirements-student.txt
```

Open this folder in **Cursor** or **Claude Code** and tell the AI: *"Read CLAUDE.md"* — it orients itself to this project automatically.

### 2. Connect to the robot

Peachy must be **powered on** (hard switch on the robot). Wait ~60–90 seconds after boot.

```bash
./scripts/net-connect.sh          # finds Peachy on the school LAN
python scripts/ctl-toggle.py status   # should NOT say "Cannot reach daemon"
```

If the daemon is flaky after a power cycle:

```bash
./scripts/net-connect.sh --fix    # restarts daemon over SSH; wait ~45s
```

### 3. Run the dashboard

```bash
./go                              # connect + dashboard URLs (recommended)
# or
./run.sh                          # dashboard only
```

Open the printed URL on your phone or laptop. On first visit, use the link with `?k=<token>` (your teacher provides the token, or it is auto-created in `.run/peachy_token` on your machine).

### 4. Try it safely

```bash
python scripts/watch-room.py --dry-run   # sensors only — NO movement
python scripts/light_probe.py --json     # read room brightness
./peachy                                 # interactive menu
```

Always use **`--dry-run`** the first time you run anything autonomous.

---

## Documentation map

| Read when… | File |
|---|---|
| **Daily use** (start here after setup) | [`STUDENT-RUNBOOK.md`](STUDENT-RUNBOOK.md) |
| **Your first project** | [`STUDENT-PROJECT.md`](STUDENT-PROJECT.md) |
| **Assignment spec** (light panel) | [`dashboard/student/LIGHT-PANEL.md`](dashboard/student/LIGHT-PANEL.md) |
| **Learn the scripts** (exercises 1–6) | [`TOOLKIT.md`](TOOLKIT.md) |
| **Build your own Reachy app** | [`docs/BUILD-YOUR-APP.md`](docs/BUILD-YOUR-APP.md) |
| **AI assistant orientation** | [`CLAUDE.md`](CLAUDE.md) |
| **First meeting with teacher** | [`STUDENT-INTRO.md`](STUDENT-INTRO.md) |
| **REST API deep dive** | [`docs/reachy_mini_build_reference.md`](docs/reachy_mini_build_reference.md) |

---

## The 7 golden rules

These save days of debugging. Full explanations are in [`CLAUDE.md`](CLAUDE.md).

1. **Enable motors before any move** — `disabled` = silent no-op
2. **No camera over REST** — camera scripts run **on the robot** (SSH)
3. **Sleep pose is ambiguous** — state lives in `.run/reachy_toggle_state.json`
4. **Daemon flaky after power-cycle** — `./scripts/net-connect.sh --fix`
5. **Sleep mode is a tradeoff** — `gravcomp` (held pose, hums) vs `limp` (silent, antennae rise)
6. **Head fan whine is normal** — CM4 cooling, not broken motors
7. **School blocks Tailscale** — use LAN at school; ask teacher for remote access from home

---

## Your first assignment

Build a **light wake/sleep panel** on the dashboard:

- Live lit/dark indicator (poll `GET /api/light`)
- Start/stop room watch (`POST /api/roomwatch/start|stop`)
- Looks good on a phone

Full spec: [`dashboard/student/LIGHT-PANEL.md`](dashboard/student/LIGHT-PANEL.md)

**Success:** flip room lights → dashboard shows lit → Peachy wakes with turret **Activated** sound → sleeps when dark.

---

## Build your own app

Three paths, from simplest to richest:

| Path | Best for | Guide |
|---|---|---|
| **REST scripts** | Quick automations, no daemon install | [`TOOLKIT.md`](TOOLKIT.md) → start with `ctl-wake.py` |
| **Dashboard extension** | Phone UI panels, room automation | [`docs/BUILD-YOUR-APP.md`](docs/BUILD-YOUR-APP.md) |
| **ReachyMiniApp** | Full apps (voice, IMU, loops) | [`apps/boo_hide/`](apps/boo_hide/) + [`docs/BUILD-YOUR-APP.md`](docs/BUILD-YOUR-APP.md) |

Scaffold a new official-style app:

```bash
reachy-mini-app-assistant create my_app_name ./apps/my_app_name
```

---

## Repo layout

```
peachy                  interactive menu
go                      morning startup (connect + dashboard)
run.sh                  start dashboard
scripts/                ctl-* watch-* cam-* cal-* diag-* net-* app-* tool-*
dashboard/              web UI (FastAPI + static SPA)
apps/                   student Reachy Mini apps
sounds/portalturret/    wake/sleep sound cues
docs/                   Reachy API reference + app-building guide
```

Scripts use **`tag-verb`** naming so `ls scripts/` self-organizes.

---

## Requirements

- **Python 3.10+** (3.12 recommended)
- **macOS or Linux** laptop on the same network as the robot
- **SSH access** to the robot (`pollen@reachy-mini.local`) — teacher sets this up
- Dependencies: `pip install -r requirements-student.txt`

---

## For teachers

- [`HANDOFF.md`](HANDOFF.md) — packaging, secrets, what not to commit
- [`scripts/package-student.sh`](scripts/package-student.sh) — zip bundle (alternative to git clone)
- Never commit `.run/` (tokens, calibration), `reachy_mini_env/`, or `reachSSH-ifconfig.txt`

---

## License

MIT — see [LICENSE](LICENSE).
