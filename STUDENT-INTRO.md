# Intro session with the student — runnable agenda

~45 min, can compress to 20. Goal: by the end, the student can drive Peachy
themselves, understands the constraints, and has **one concrete feature to
build first** (the dream's missing piece).

Before they arrive: robot powered on, you wired in, `./peachy` works.

---

## 1. The big picture (3 min) — talk

> "Peachy is a Reachy Mini — a desktop humanoid with a head, antennae,
> camera, mic, speaker. About 80% of *your dream* is built:
> sense the room → wake → greet → conversation → sleep when empty."

What's already working:
- Daemon REST control (wake/sleep, custom poses, expressions)
- A state machine that watches light + camera motion + speech
- A phone dashboard you can drive from any device
- Conversation-app handoff on AWAKE (basic version)

What's *not* done (your project): a **richer greet** before the LLM takes
over, and detection that's robust to bright classroom sun.

What to NOT chase: Tailscale at school (school firewall blocks it — solved
differently); the body's yaw not turning (mechanical issue, software can't
fix it); a faint head whine (the CM4 cooling fan, normal).

---

## 2. Tour the repo (3 min) — open in Cursor/Claude Code

Open the folder. Point at, in order:
- **`README.md`** — GitHub landing + quick start
- **`CLAUDE.md`** — auto-orients any AI assistant; read top to bottom *with* them
- **`TOOLKIT.md`** — graduated lessons; what they'll work through
- **`STUDENT-PROJECT.md`** — what to build (light panel) + repo map
- **`docs/BUILD-YOUR-APP.md`** — how to create their own Reachy apps
- **`dashboard/student/LIGHT-PANEL.md`** — assignment spec
- **`scripts/`** — `tag-verb` naming: `ctl-` `watch-` `cam-` `cal-` `diag-` `net-` `app-` `tool-`
- **`scripts/archive/`** — *deliberately* shelved approaches (history matters)
- **`dashboard/`** — phone UI (runs on the robot)

---

## 3. Hands-on demo (~10 min) — run `./peachy` together

```bash
./peachy
```
Walk these in order, narrating *why*, not just *what*:

| Pick | Show | What to say |
|---|---|---|
| **1** | status | "Every script auto-finds the robot — no hostname juggling" |
| **4** | toggle | "Smart wake/sleep; tracks state in `.run/`" |
| **5** | expressions → pick `curious` | "Animations = keyframes between calibrated poses" |
| **8** | take a photo | "Camera only works *on* the robot — the menu does the SSH dance" |
| **6** | room watch — dry-run | flip lights / talk while running; watch state column |
| **13** | QR for phone | scan it on **their** phone; show the dashboard live |

End: `q` to quit.

---

## 4. The 7 Golden Rules (5 min) — read CLAUDE.md together

Page down in `CLAUDE.md` to *"Golden rules"*. Read all 7 aloud. These are
what cost days to learn. Emphasize:
1. **Motors must be `enabled` before any `play`** (silent no-op otherwise — biggest bug we hit)
2. **No camera over REST** → camera scripts run on-robot
3. **Sleep mode is a tradeoff** — `gravcomp` (held pose, hums) vs `limp` (silent, antennae rise)
4. **Daemon backend flakes after power-cycle** — `./scripts/net-connect.sh --fix` is the fix
5. **Body yaw is mechanically decoupled** — head-yaw offset cosmetically faces it forward
6. **Fan in the head is normal** — not a defect
7. **Tailscale is blocked at school** — we route around it; don't fight it

---

## 5. Hand them their AI assistant (5 min) — demo a fresh session

In Cursor/Claude Code, **with this repo open**, have *them* type something like:

> "Read CLAUDE.md and then explain how `ctl-toggle.py` works."

Watch the AI orient itself. This is how they'll work going forward:
**point Claude at this repo; CLAUDE.md does the rest.**

---

## 6. Their project: light wake / sleep panel (~15 min) — orient, then they build

Open `dashboard/student/LIGHT-PANEL.md` together. Show the stub panel on the
dashboard (**Light wake / sleep — student panel**). Walk through:

```bash
python scripts/light_probe.py --json    # Peachy cam via SSH — start Live first
python scripts/watch-room.py --dry-run  # safe — prints states, no movement
```

**Their job:** replace the stub with a real panel — live lit/dark, start/stop
room watch, clear on a phone. The brain (`watch-room.py`) and light sensor
(`light_sensor.py`) already exist; they're wiring the UI.

Stretch (after panel ships): richer greet in `watch-room.py` before conversation;
pick different turret sleep sounds from `sounds/portalturret/manifest.json`.

---

## 7. Wrap-up: where help lives (2 min)

- **Their AI session** with the repo open — CLAUDE.md does the orientation
- **`TOOLKIT.md`** — graduated exercises if they want to learn deeper
- **`scripts/archive/README.md`** — *why* things were shelved (good history)
- **`docs/reachy_mini_build_reference.md`** — the deeper REST/SDK reference
- You (via text/message) for anything blocking

---

## 8. Success metric for their build window

By the end of their time: **flip the room lights → dashboard shows lit → room
watch running → Peachy wakes with the turret "Activated" clip → sleeps when dark.**
That's the core loop — the light panel makes it operable without the terminal.

---

## Cheatsheet (give them this)

```
./peachy                              # the menu — start here
./scripts/net-connect.sh              # find/revive the robot
./scripts/net-connect.sh --fix        # if "Backend not running"

# from a script-naming logic:
ctl-*    control       cal-*  tuning      cam-*  camera (on-robot)
watch-*  sensing       diag-* probes      net-*  connectivity
app-*    services      tool-* misc        hostfind.py = lib

# don't forget:
1) enable motors before moving        4) only --dry-run for first try of watch-room
2) camera = on-robot only             5) calibrate once via ./peachy option 9
3) save head_offset in cal-head       6) when stuck, ask Claude with CLAUDE.md open
```
