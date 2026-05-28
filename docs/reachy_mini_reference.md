# Reachy Mini — local developer reference

**Canonical docs:** [Reachy Mini on Hugging Face](https://huggingface.co/docs/reachy_mini/index)  
This file is a **condensed handbook** for day-to-day work in this repo. When in doubt, use the HF links below — upstream changes often.

**See also:** [`reachy_mini_build_reference.md`](reachy_mini_build_reference.md) — build-focused distillation (REST endpoints verified live, SDK signatures, `ReachyMiniApp` contract, scaffolding/publish, design gotchas).

---

## Quick links

| Topic | HF doc |
| --- | --- |
| Index / overview | [index](https://huggingface.co/docs/reachy_mini/index) |
| **Wireless:** first boot & Wi‑Fi | [get_started](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/get_started) |
| Wireless: usage | [usage](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/usage) |
| Lite (USB): get started | [reachy_mini_lite/get_started](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini_lite/get_started) |
| Simulation (MuJoCo) | [simulation/get_started](https://huggingface.co/docs/reachy_mini/platforms/simulation/get_started) |
| SDK installation | [SDK/installation](https://huggingface.co/docs/reachy_mini/SDK/installation) |
| Quickstart | [SDK/quickstart](https://huggingface.co/docs/reachy_mini/SDK/quickstart) |
| Python SDK | [SDK/python-sdk](https://huggingface.co/docs/reachy_mini/SDK/python-sdk) |
| Core concepts | [SDK/core-concept](https://huggingface.co/docs/reachy_mini/SDK/core-concept) |
| Media / camera-audio internals | [SDK/media-architecture](https://huggingface.co/docs/reachy_mini/SDK/media-architecture) |
| GStreamer (Linux + remote WebRTC clients) | [SDK/gstreamer-installation](https://huggingface.co/docs/reachy_mini/SDK/gstreamer-installation) |
| Integrations & HTTP API | [SDK/integration](https://huggingface.co/docs/reachy_mini/SDK/integration) |
| Apps & publishing | [SDK/apps](https://huggingface.co/docs/reachy_mini/SDK/apps) |
| JavaScript SDK / web apps | [SDK/javascript-sdk](https://huggingface.co/docs/reachy_mini/SDK/javascript-sdk) |
| Tutorials / notebooks | [sdk-tutorials](https://huggingface.co/docs/reachy_mini/sdk-tutorials) |
| Troubleshooting & FAQ | [troubleshooting](https://huggingface.co/docs/reachy_mini/troubleshooting) |
| Examples (GitHub) | [examples/](https://github.com/pollen-robotics/reachy_mini/tree/main/examples) |
| Main repo | [pollen-robotics/reachy_mini](https://github.com/pollen-robotics/reachy_mini) |
| Issues | [reachy_mini/issues](https://github.com/pollen-robotics/reachy_mini/issues) |

**Community:** Discord invite links appear on the [index page](https://huggingface.co/docs/reachy_mini/index) (marketing vs community invites may differ between sections upstream).

---

## Product lines (choose one workflow)

| Platform | What it is |
| --- | --- |
| **Wireless** | Raspberry Pi CM4 onboard, battery, Wi‑Fi, IMU |
| **Lite** | Developer unit: USB to your PC |
| **Simulation** | MuJoCo — no hardware |

Wireless hardware overview: [platforms/reachy_mini/hardware](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/hardware).

---

## Wireless: first boot, Wi‑Fi, updates

1. **Assembly:** ~2–3 hours; interactive guide: [Assembly Space](https://huggingface.co/spaces/pollen-robotics/Reachy_Mini_Assembly_Guide); video linked from [wireless get_started](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/get_started).
2. **Wi‑Fi:** Install **Reachy Mini Control** from [hf.co/reachy-mini `#/download`](https://hf.co/reachy-mini/#/download); use **“First time connecting…”** — join robot AP → push your Wi‑Fi credentials.
3. **Updates:** In Control → **Settings** → system updates — do this before deeper debugging ([troubleshooting](https://huggingface.co/docs/reachy_mini/troubleshooting) stresses update + reboot first).

---

## SSH (Wireless Raspberry Pi)

Default credentials ([get_started](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/get_started)):

- User: `pollen`
- Password: `root`

Example:

```bash
ssh pollen@reachy-mini
# or pollen@reachy-mini.local depending on resolver / hotspot
```

On-robot sanity check:

```bash
reachyminios_check
```

**Important:** Wireless units **do not** expose robot control via USB‑C like Lite. Official guidance: Wi‑Fi (or SSH on the Pi); for wired transport use **USB‑C → Ethernet** + cable ([troubleshooting](https://huggingface.co/docs/reachy_mini/troubleshooting)).

### Head board switch (AP missing)

If the AP never appears: a switch in the head must be in **debug** (not **download**) position — see [troubleshooting](https://huggingface.co/docs/reachy_mini/troubleshooting). Wrong position can masquerade as boot/AP failure.

---

## Running SDK **on** the Wireless robot (optional)

Low latency; less CPU than a laptop ([quickstart](https://huggingface.co/docs/reachy_mini/SDK/quickstart)):

```bash
ssh pollen@reachy-mini
source /venvs/apps_venv/bin/activate
```

Use `ReachyMini()` as usual (localhost / auto mode).

---

## Dev machine: install SDK

**Supported:** Linux, macOS, Windows ([installation](https://huggingface.co/docs/reachy_mini/SDK/installation)).

- **Python:** 3.10–3.12 (3.12 recommended).
- **Tools:** `git`, `git lfs` (`git lfs install`).
- **Package manager:** `uv` recommended — [install uv](https://docs.astral.sh/uv/getting-started/installation/).

Typical venv + install:

```bash
uv venv reachy_mini_env --python 3.12
source reachy_mini_env/bin/activate   # Windows: reachy_mini_env\Scripts\activate
uv pip install "reachy-mini"
```

Simulation extra:

```bash
uv pip install "reachy-mini[mujoco]"
```

**Linux only:** GStreamer system packages — [gstreamer-installation](https://huggingface.co/docs/reachy_mini/SDK/gstreamer-installation).  
**Linux + Lite USB:** udev rules for USB IDs — copy from [installation](https://huggingface.co/docs/reachy_mini/SDK/installation) (`99-reachy-mini.rules`, `dialout` group, re-login).

**From source** (contributors): clone [reachy_mini](https://github.com/pollen-robotics/reachy_mini), then `uv sync` (and optional `--extra mujoco`).

---

## Daemon (required for client code)

- **Wireless:** daemon runs on power-on; laptop and robot must be **reachable on the network** (same or routed — school VLANs may block this).
- **Lite / sim:** run `reachy-mini-daemon` (or Control app). Simulation: `reachy-mini-daemon --sim`; macOS MuJoCo nuance: see [simulation get_started](https://huggingface.co/docs/reachy_mini/platforms/simulation/get_started).

**Verify:** open [http://localhost:8000/docs](http://localhost:8000/docs) when the daemon is local; for Wireless, use the robot’s host/IP.

`ReachyMini()` **auto-detects** Lite vs Wireless (localhost vs network). Override if needed: `connection_mode="localhost_only"` | `"network"` ([quickstart](https://huggingface.co/docs/reachy_mini/SDK/quickstart)).

---

## Minimal SDK examples

**Hello motion** ([index](https://huggingface.co/docs/reachy_mini/index)):

```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

with ReachyMini() as mini:
    mini.goto_target(
        head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
        duration=1.0
    )
```

**Antennas** ([quickstart](https://huggingface.co/docs/reachy_mini/SDK/quickstart)): use `goto_target(antennas=[...], duration=...)`.

**Movement:** `goto_target` — interpolated (`method`: `linear`, `minjerk` (default), `ease_in_out`, `cartoon`). `set_target` — immediate, for high‑rate loops ([python-sdk](https://huggingface.co/docs/reachy_mini/SDK/python-sdk)).

**Camera:** `with ReachyMini(media_backend="default") as mini: frame = mini.media.get_frame()` — `uint8` H×W×3.

**IMU:** Wireless only — `mini.imu` keys: accelerometer (m/s²), gyroscope (rad/s), quaternion (w,x,y,z), temperature ([python-sdk](https://huggingface.co/docs/reachy_mini/SDK/python-sdk)).

**Audio:** `start_recording` / `get_audio_sample` / `push_audio_sample` / `stop_*`; formats and sample rates in [python-sdk](https://huggingface.co/docs/reachy_mini/SDK/python-sdk).

**Media backends:** `default` (auto), `local`, `webrtc`, `no_media` (hands hardware to OpenCV/sounddevice, etc.). WebRTC remote: GStreamer on client — **Linux most mature** today ([python-sdk](https://huggingface.co/docs/reachy_mini/SDK/python-sdk)).

---

## Architecture snapshot ([core-concept](https://huggingface.co/docs/reachy_mini/SDK/core-concept))

- **Daemon (server):** hardware I/O, safety, REST + WebSocket (e.g. port `8000`).
- **SDK (client):** your Python — can run on another machine **if network allows**.

**Safety limits (software clamp):**

| Joint / axis | Range |
| --- | --- |
| Head pitch/roll | ±40° |
| Head yaw | ±180° |
| Body yaw | ±160° |
| Head vs body yaw delta | ≤ 65° |

**Motor helpers:** `enable_motors()`, `disable_motors()`, `enable_gravity_compensation()` (Placo backend).

---

## HTTP / WebSocket ([integration](https://huggingface.co/docs/reachy_mini/SDK/integration))

- OpenAPI docs: `/docs` on the daemon host.
- Example REST: `GET /api/state/full`
- WebSocket: `ws://.../api/state/ws/full`

---

## Apps (HF Spaces ecosystem) ([apps](https://huggingface.co/docs/reachy_mini/SDK/apps))

- **AI agents:** upstream [`AGENTS.md`](https://github.com/pollen-robotics/reachy_mini/blob/main/AGENTS.md) — recommended prompt appears in HF **apps** doc.
- Scaffold: `reachy-mini-app-assistant create my_app_name /path` (templates e.g. `--template conversation`).
- Contract: subclass `ReachyMiniApp`, implement `run(reachy_mini, stop_event)`, use `wrapped_run()` / `stop()` pattern as generated.
- **Wireless app venv:** `/venvs/apps_venv/` when installed on robot.
- **Offline install:** `scp` tree to robot → `pip install` into that venv (see [apps](https://huggingface.co/docs/reachy_mini/SDK/apps)).

Blog walkthrough: [Make and Publish Your Reachy Mini Apps](https://huggingface.co/blog/pollen-robotics/make-and-publish-your-reachy-mini-apps).

---

## Local CLI helpers (this repo, laptop venv)

Skip Reachy Control for routine wake/sleep and starting/stopping the **official conversation app** ([`reachy_mini_conversation_app`](https://github.com/pollen-robotics/reachy_mini_conversation_app)).

**Install conversation app** (not always on PyPI; use Git):

```bash
source reachy_mini_env/bin/activate
uv pip install "reachy_mini_conversation_app @ git+https://github.com/pollen-robotics/reachy_mini_conversation_app.git"
```

**Environment:** `REACHY_HOST` (default in helpers: `192.168.99.2`), `REACHY_PORT` (default `8000`).

| Goal | Command |
| --- | --- |
| **`./peachy`** (interactive menu — start here) | auto-sources venv; wraps day-to-day actions with verbose feedback |
| Scripts now **auto-find the robot** (`hostfind.resolve_host`) | just run them — no `source` needed; `REACHY_HOST` still overrides |
| **Find & revive the robot** (diagnose/tunnel/fix) | `./scripts/net-connect.sh` (or `--tunnel` / `--fix`) |
| **Deploy dashboard to robot + Funnel (school access)** | `./scripts/net-deploy.sh` → public `https://<node>.ts.net/?k=<token>` |
| **Fortinet-proof remote access** (Tailscale blocked at school) | `SRV=user@srv993267 ./scripts/net-uplink.sh` — autossh reverse tunnel via cloud box |
| Wake / sleep only (daemon REST) | `python scripts/ctl-wake.py wake` / `sleep` |
| **Sleep/wake toggle** (state-aware) | `python scripts/ctl-toggle.py` — also `status` / `sleep` / `wake` / `calibrate` |
| **Toggle + expression demo menu** | `python scripts/ctl-express.py` — wakes then CLI menu (Enter = back; run again to sleep) |
| **Room-aware watcher** (laptop cam light + speech) | `python scripts/watch-room.py` — add `--dry-run` to test sensors without moving |
| **Body-yaw diagnostic** (network, no SSH) | `python scripts/diag-yaw.py` — commands small yaw + head-yaw control test, prints verdict |
| **Head jog / neutral-offset tuner** | `python scripts/cal-head.py` — live REPL; `save` writes `head_offset` applied by show/room_watch |
| **Phone dashboard** (big-button web UI) | `./dashboard/run.sh` — opens `http://<laptop-ip>:8080/`; phones tap to drive Peachy, incl. one-tap **Start a conversation** (wake + conversation app) |
| Single expression (non-interactive) | `python scripts/ctl-express.py express <yes\|no\|curious\|lookaround\|excited\|shy\|stretch>` |
| Conversation app background | `./scripts/app-conversation.sh start` — optional flags e.g. `--gradio` |
| Stop conversation | `./scripts/app-conversation.sh stop` |

REST used for motion: `POST /api/move/play/wake_up`, `POST /api/move/play/goto_sleep` (see daemon OpenAPI at `http://<REACHY_HOST>:8000/docs`).

**Note:** Installing the conversation stack may adjust shared deps (e.g. `pydantic`). If the SDK starts misbehaving, run `./scripts/net-connect.sh` + `python scripts/ctl-toggle.py status` and reinstall `reachy-mini` to match your daemon if needed.

---

## Troubleshooting cheat sheet

Full expandable FAQ: [troubleshooting](https://huggingface.co/docs/reachy_mini/troubleshooting).

**Always first:** firmware/app **up to date** + cold reboot (OFF, 5s, ON). Wireless: `reachyminios_check`.

| Symptom | Where to look |
| --- | --- |
| Motors / red blink / overload | [motors_diagnosis](https://huggingface.co/docs/reachy_mini/troubleshooting/motors_diagnosis), Testbench app |
| AP missing / no boot | Head switch **debug** vs **download**; else reflash ISO ([reflash](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/reflash_the_rpi_ISO)) |
| Mic silent | Cable orientation; possibly FPC replacement guide in FAQ |
| Control bootstrap / broken venv | Control **Reset apps env** → **Full environment reset** (FAQ) |
| Antenna shaking at 0° | Offset angles; PID tuning notes in FAQ |

Expert wireless topics: [reflash ISO](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/reflash_the_rpi_ISO), [daemon branch install](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/install_daemon_from_branch), [development workflow](https://huggingface.co/docs/reachy_mini/platforms/reachy_mini/development_workflow).

---

## Licenses

Apache 2.0 software — see [LICENSE](https://github.com/pollen-robotics/reachy_mini/tree/main/LICENSE). Hardware design: CC BY-SA-NC ([index](https://huggingface.co/docs/reachy_mini/index)).

---

## Classroom network note (this deployment)

Upstream assumes normal home/office Wi‑Fi. **Enterprise / isolated IoT VLANs** (captive portals, WPA2‑Enterprise, no routing from staff LAN) are deployment-specific — coordinate with IT; see project notes separately if you maintain them (e.g. `reachSSH-ifconfig.txt`).
