# Archived scripts

Kept for history / reference, **not** loaded by `./peachy` or the docs. Move
one back up into `scripts/` if you want to revive it.

| File | Why archived |
|---|---|
| `cal-light.py` | Voice-guided light sweep using the laptop webcam. The approach didn't pan out (auto-exposure crushed the signal). Superseded by the planned **light-bank ROI** detector. The TTS-via-Reachy-speaker pattern in `Voice` is still a useful reference snippet. |
| `app-roommode.sh` | `greet` / `leave` macros (wake+conversation / stop+sleep). Superseded by the dashboard's one-tap **"Start a conversation"** and `watch-room.py`'s built-in AWAKE→conversation handoff. |
| `app-run-conversation.sh` | Foreground launcher for `reachy-mini-conversation-app`. Redundant with `scripts/app-conversation.sh start` (background, PID-tracked). |
| `diag-sim.py` | Old MuJoCo simulator smoketest — unused on the wireless robot. |
| `diag-wired.py` | Old wired-LAN smoketest — `./scripts/net-connect.sh` + `ctl-toggle.py status` cover this better now. |
| `diag-audio.py` | Old daemon-audio probe — never used; the daemon's own `reachyminios_check` (with daemon stopped) is the right tool. |

Still **active** in `scripts/`: `ctl-toggle.py`, `ctl-wake.py` (kept as
TOOLKIT.md lesson #1 — intentionally minimal), `ctl-express.py`, `cal-head.py`,
`cam-snap.py`, `watch-room.py`, `light_sensor.py`, `light_probe.py`,
`sound_sync.py`, `diag-yaw.py`, `net-connect.sh`,
`net-deploy.sh`, `net-uplink.sh`, `app-conversation.sh`, `tool-qr.py`,
`hostfind.py` (library).
