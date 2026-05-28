# Student runbook — run Peachy the same way as Mr. Lake

One-page operational guide. Goal: **connect → dashboard → room watch → lights/speech → warmup → conversation → sleep.**

Read **`CLAUDE.md`** once so your AI assistant knows the rules. This doc is the **daily checklist**.

---

## What Mr. Lake gives you

| Item | What it is |
|---|---|
| **Git repo** | `git clone https://github.com/rootlake/pomfret_reachy.git` (or teacher's zip) |
| **Dashboard token** | String in `.run/peachy_token` on teacher machine — open links with `?k=<token>` |
| **Network access** | **At school:** same Wi‑Fi as Peachy (LAN). **From home:** ask teacher for remote access setup |
| **Optional tune file** | Copy `.run/light_tune.json` from teacher for seminar room thresholds (or tune yourself on `/lights`) |

**Never share publicly:** `.run/` (token, calibration, SSH cache), `reachy_mini_env/`, `reachSSH-ifconfig.txt`.

---

## One-time Mac setup (~10 min)

```bash
git clone https://github.com/rootlake/pomfret_reachy.git
cd pomfret_reachy
python3 -m venv reachy_mini_env
source reachy_mini_env/bin/activate
pip install -r requirements-student.txt
```

**Also need (teacher helps if missing):**

- **SSH key** — `ssh-keygen -t ed25519` then send teacher your `~/.ssh/id_ed25519.pub` for remote/uplink access
- **Tailscale** (optional) — only for connecting from home/off-LAN via uplink
- **Robot powered on** — hard power button on Peachy must be **ON** (easy to forget)

Open this folder in **Cursor** or **Claude Code**. Tell the AI: *"Read CLAUDE.md"*.

---

## Every session — startup (same as teacher)

### Fast path (recommended)

```bash
cd reachymini
source reachy_mini_env/bin/activate
./go
```

`./go` connects to Peachy, prints status, starts the dashboard if needed, and shows URLs.

| Flag | Use |
|---|---|
| `./go --lan` | Classroom — probe school Wi‑Fi (`192.168.99.2`, `reachy-mini.local`) |
| `./go --uplink` | Off-LAN — Tailscale → robot uplink → tunnel to `127.0.0.1:8000` |
| `./go --restart` | Restart dashboard |
| `./go --wake` | Connect + wake Peachy |
| `./go --open` | Open dashboard in browser |

### Manual path (if `./go` fails)

```bash
# 1. Connect
./scripts/net-connect.sh              # classroom LAN
./scripts/net-connect.sh --via-uplink # home / Tailscale
./scripts/net-connect.sh --fix        # daemon up but "Backend not running"

# 2. Verify
python scripts/ctl-toggle.py status   # must not say "Cannot reach daemon"

# 3. Dashboard
./run.sh                              # or ./run.sh --restart
```

**Success looks like:**

```
✓ Peachy is UP at 127.0.0.1:8000    # or 192.168.99.2:8000 on LAN
host             : …
control_mode     : enabled (or disabled before wake — both OK)
```

---

## Dashboard URLs (phone or laptop)

After `./run.sh`, open the printed links **once with `?k=`** (sets a cookie):

| Page | Purpose |
|---|---|
| **`/`** | Main control — wake, sleep, expressions, conversation, preview |
| **`/watch`** | Room watch lab — LIGHTS ON/OFF hero, start/stop watcher, confirmation |
| **`/lights`** | Tune light thresholds |
| **`/conversation`** | Transcript / convo status |

Token is in `.run/peachy_token` on your machine after first `./run.sh`.

---

## Full classroom demo (same flow as teacher)

### Before visitors

1. **Power** — Peachy hard switch ON; wait ~60–90s for boot
2. **`./go`** or connect + `./run.sh --restart`
3. **`/watch`** → **Start room watch**
4. Confirm **watching** badge and **LIGHTS ON/OFF** matches the room
5. Optional: **Live preview** on (faster light reads)

### Trigger the dream sequence

Lights **ON** → Peachy reads lit → **say something** near the mic:

> *"Hey Peachy, are you there?"*

State machine:

```
RESTING → SEMI_WAKE (speech) → AWAKE → warmup bridge → conversation
```

**Warmup** (~15–20s): stretch, look-around, turret sounds, *"Conversation mode starting shortly…"*, countdown, handoff.

### Voice (avoid the weird default→Ballad swap)

Use turret sounds for warmup; skip mid-bridge voice patch:

```bash
export PEACHY_VOICE_LOCK=1
export REACHY_WARMUP_TTS=0
```

Or set before starting room watch from the same terminal:

```bash
PEACHY_VOICE_LOCK=1 REACHY_WARMUP_TTS=0 python scripts/watch-room.py
```

### End session

- Say **"Goodnight Peachy"** / **"Go to sleep"** / **"I'm leaving"** (conversation patch), or
- `./scripts/app-leave.sh`, or
- Dashboard **Stop** room watch + **Sleep**

---

## CLI equivalents (no dashboard)

```bash
# Safe — sensors only, no movement
python scripts/watch-room.py --dry-run

# Live room watch (capstone)
python scripts/watch-room.py

# One-shot light read
python scripts/light_probe.py --json

# Warmup test (Peachy must be awake)
PEACHY_VOICE_LOCK=1 python scripts/warmup_bridge.py

# Interactive menu
./peachy
```

---

## Environment variables cheat sheet

| Variable | Default | Meaning |
|---|---|---|
| `REACHY_HOST` | auto (`hostfind`) | Robot daemon IP — usually `127.0.0.1` (tunnel) or `192.168.99.2` (LAN) |
| `REACHY_SSH` | `pollen@reachy-mini.local` | SSH target for camera/conversation on robot |
| `REACHY_SSH_PORT` | `22` / `2222` | `2222` when using uplink (`100.88.209.10`) |
| `PEACHY_TOKEN` | auto in `.run/` | Dashboard auth; `PEACHY_TOKEN=off` on trusted LAN only |
| `REACHY_WARMUP` | `1` | Stretch + bridge before conversation |
| `REACHY_WARMUP_TTS` | `1` | Mac `say` during warmup; `0` = turret WAVs only |
| `REACHY_WARMUP_S` | `19` | Max seconds for warmup bridge |
| `PEACHY_VOICE_LOCK` | off | `1` = don't force Ballad voice at convo start |
| `REACHY_LIGHT_ON_DELTA` | `25` | Lit threshold (tune on `/lights`) |
| `REACHY_LIGHT_OFF_DELTA` | `12` | Dark threshold |
| `REACHY_SLEEP_MODE` | `gravcomp` | `gravcomp` / `limp` / `hold` — see CLAUDE.md |

Scripts **auto-find the robot** — no `source .run/reachy.env` required (but `net-connect` writes it).

---

## The 7 golden rules (read `CLAUDE.md` for why)

1. **Enable motors before moves** — disabled = silent no-op
2. **No camera over REST** — frames via SDK on robot; laptop uses SSH/preview
3. **Sleep pose is ambiguous** — state lives in `.run/reachy_toggle_state.json`
4. **Daemon flaky after power-cycle** — `./scripts/net-connect.sh --fix`, wait ~45s
5. **Sleep mode tradeoff** — gravcomp hums; limp is silent
6. **Head fan whine is normal** — CM4 cooling, not broken motors
7. **Tailscale broken at school** — use LAN at school; uplink from home with Tailscale

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot reach daemon` | Power button ON → wait 90s → `./scripts/net-connect.sh` or `--via-uplink` |
| `Connection refused` on `:8000` | SSH tunnel died — re-run `net-connect --via-uplink` |
| `Backend not running` | `./scripts/net-connect.sh --fix` |
| Watch stuck **LIGHTS OFF** with lights on | Restart room watch; tap **Confirmation → Lights OFF** to re-anchor, then ON |
| Light reads all **0.0** | Start **Live preview**; wait for camera after boot |
| Confirm buttons **unknown command** | `./run.sh --restart` + hard-refresh `/watch` |
| Dashboard errors while page works | Brief disconnect during `./run.sh --restart` — normal |
| SSH `Permission denied` | Ask teacher to add your SSH public key |
| Uplink `Connection refused :2222` | Robot off or uplink service down — use LAN at school |

---

## Project assignment (your build)

**First feature:** light wake/sleep panel — `dashboard/student/LIGHT-PANEL.md`

Brain already exists: `watch-room.py`, `light_sensor.py`, `/api/light`. You wire the UI.

**Learning path:** `TOOLKIT.md` (exercises 1–6) → `STUDENT-PROJECT.md` (map).

---

## Teacher checklist before handoff

- [ ] `./scripts/package-student.sh` → send zip
- [ ] Send dashboard `?k=` token (or agree on `PEACHY_TOKEN=off` on LAN)
- [ ] Student SSH key on robot (if uplink from home)
- [ ] Robot powered; `./go` works on student laptop at school
- [ ] Optional: copy `.run/light_tune.json` + calibration notes
- [ ] Point student at **this file** + `STUDENT-PROJECT.md`

---

## Doc map

| Read when… | File |
|---|---|
| Start here | `README.md` |
| Daily ops | **This file** (`STUDENT-RUNBOOK.md`) |
| AI orientation | `CLAUDE.md` |
| First meeting agenda | `STUDENT-INTRO.md` |
| Build your own app | `docs/BUILD-YOUR-APP.md` |
| Your assignment | `STUDENT-PROJECT.md`, `dashboard/student/LIGHT-PANEL.md` |
| Learn scripts | `TOOLKIT.md` |
| REST/API deep dive | `docs/reachy_mini_build_reference.md` |
