# HANDOFF — sharing this with students

Goal: hand students a clean, working library to **learn from and extend in
their own Cursor / Claude Code session** — **without exposing personal data**.

**Public repo:** [github.com/rootlake/pomfret_reachy](https://github.com/rootlake/pomfret_reachy)

**Start here for the student:** `README.md` → `STUDENT-RUNBOOK.md` → `STUDENT-PROJECT.md`
**Assignment detail:** `dashboard/student/LIGHT-PANEL.md` (wake-on-light panel spec)

## What must NOT be shared (already `.gitignore`d)

- `.run/` — contains the **dashboard access token**, tailnet URL, calibration,
  PIDs. This is the only real secret. Never include it.
- `reachSSH-ifconfig.txt` — robot MAC/IP/SSH banner.
- `.claude/` — machine-local settings + your permission allowlist.
- `reachy_mini_env/` — the virtualenv (recreate, see below).
- `agents.local.md` — local scratch.
- `glados_fork/`, `configs/` — teacher-only advanced brain / deployment configs.
- `scripts/net-uplink.sh`, `scripts/net-deploy.sh` — infrastructure with VPS defaults.

Everything in the public repo (scripts, dashboard, sounds, docs, apps) is safe
for students. School LAN IPs in docs are fine for same-school use.

## Share with students (preferred: git clone)

```bash
git clone https://github.com/rootlake/pomfret_reachy.git
cd pomfret_reachy
python3 -m venv reachy_mini_env && source reachy_mini_env/bin/activate
pip install -r requirements-student.txt
```

Then: `STUDENT-RUNBOOK.md` (daily ops) → `STUDENT-PROJECT.md` (assignment).

## Alternative: zip bundle (offline / no git)

```bash
./scripts/package-student.sh
# → ../peachy-student.zip (no secrets, no venv, includes sounds/portalturret/)
```

Or specify output path:

```bash
./scripts/package-student.sh ~/Desktop/peachy-student.zip
```

## Student first-run (put this in your message to them)

```bash
git clone https://github.com/rootlake/pomfret_reachy.git && cd pomfret_reachy
python3 -m venv reachy_mini_env && source reachy_mini_env/bin/activate
pip install -r requirements-student.txt
# open README.md, then STUDENT-RUNBOOK.md — daily ops (same flow as teacher)
# then STUDENT-PROJECT.md for the assignment
./scripts/net-connect.sh
./go                               # or ./run.sh for dashboard only
```

`CLAUDE.md` orients the AI assistant automatically. Tell them:
- Robot is already calibrated (`.run/` on teacher machine — they get fresh `.run/` locally)
- First feature: **light wake/sleep dashboard panel** (`dashboard/student/LIGHT-PANEL.md`)
- Test light with `python scripts/light_probe.py --json` before live room watch
- Always try `python scripts/watch-room.py --dry-run` before live movement

## What's in the package

| Included | Purpose |
|---|---|
| `dashboard/` | Web UI + FastAPI (`GET /api/light` stub for their panel) |
| `scripts/` | Robot control, `watch-room.py`, `light_sensor.py`, sounds |
| `sounds/portalturret/` | 14 WAV clips + `manifest.json` (wake/sleep/snap cues) |
| `peachy` | Interactive menu |
| `CLAUDE.md`, `TOOLKIT.md`, `STUDENT-INTRO.md` | Orientation + intro session agenda |
| `requirements-student.txt` | pip deps (no guessing) |

## Push updates to GitHub

From the project root (after verifying `git status` shows no secrets):

```bash
git add -A
git commit -m "Your message"
git push origin main
```

Verify `.run/`, `reachy_mini_env/`, and `glados_fork/` never appear in `git status`.

## Teacher checklist before handoff

- [ ] Robot powered, `./scripts/net-connect.sh` works
- [ ] `./go` or `./dashboard/run.sh` works; student can open dashboard on phone
- [ ] `./scripts/sound_sync.py --list` shows turret clips on robot (or they sync from UI)
- [ ] `python scripts/light_probe.py --json` works on student laptop
- [ ] Student can `git clone` the repo (or send zip from `./scripts/package-student.sh`)
- [ ] Share dashboard `?k=` token (or agree on `PEACHY_TOKEN=off` on trusted LAN)
- [ ] Point student at **`README.md`**, **`STUDENT-RUNBOOK.md`**, and `STUDENT-PROJECT.md`
