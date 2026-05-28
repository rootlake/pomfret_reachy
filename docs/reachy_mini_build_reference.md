# Reachy Mini — build reference (distilled for this repo)

Working notes for building against **our** wireless robot over the LAN
(`REACHY_HOST=192.168.99.2`, daemon port `8000`). Distilled from the HF docs
([apps](https://huggingface.co/docs/reachy_mini/SDK/apps),
[rest-api](https://huggingface.co/docs/reachy_mini/API/rest-api),
[quickstart](https://huggingface.co/docs/reachy_mini/SDK/quickstart)) plus the
live OpenAPI spec at `http://192.168.99.2:8000/openapi.json`. See
`reachy_mini_reference.md` for the network/SSH/troubleshooting handbook.

---

## 1. Two ways to control the robot

| Path | When we use it | Notes |
|---|---|---|
| **Daemon REST** (this repo's scripts) | Laptop-driven, beamed over LAN; no SSH, no WebRTC | `ctl-toggle.py`, `ctl-express.py`, `watch-room.py`. Robust on the classroom VLAN. |
| **Python SDK** (`ReachyMini`) | Apps, tight control loops, camera/audio frames | Camera/audio over the network = WebRTC (flaky on our wired LAN). Best when run **on the robot** (`/venvs/apps_venv/`). |
| **`ReachyMiniApp`** | Installable apps managed by the daemon | One app at a time; daemon owns the hardware connection. |

**Rule of thumb for us:** motion + state + speech-flag → REST from the laptop.
Camera frames / raw audio → SDK on the robot (or an installed app).

---

## 2. Daemon REST API (verified live on our robot)

Base: `http://192.168.99.2:8000`. Swagger: `/docs`. Spec: `/openapi.json`.

### Motors — enable before any move
- `POST /api/motors/set_mode/{mode}` — `mode` ∈ `enabled` | `disabled` | `gravity_compensation`. **`enabled` is required before `goto`/`set_target` do anything.**
- `GET /api/motors/status`

### State (read-only, cheap, no media needed)
- `GET /api/state/full` →
  `{control_mode, head_pose:{x,y,z,roll,pitch,yaw}, head_joints, body_yaw,
   antennas_position:[L,R], timestamp, passive_joints, doa}`
  Units: position **metres**, angles **radians**. With motors `disabled` the
  head rests under gravity → pose is **ambiguous** (why our toggle uses a state
  file, not pose alone).
- `GET /api/state/doa` → `{"angle": <rad>, "speech_detected": <bool>}` —
  **built-in voice-activity flag over plain REST.** This is what
  `watch-room.py` uses for the "someone spoke → AWAKE" transition.
- `GET /api/state/present_head_pose`, `/present_body_yaw`,
  `/present_antenna_joint_positions`
- WebSocket stream: `ws://<host>:8000/api/state/ws/full`

### Move
- `POST /api/move/play/wake_up` and `.../play/goto_sleep` — known-good canned
  postures. Body `{}`. Can take a few seconds; use a long client timeout.
- `POST /api/move/play/recorded-move-dataset/{dataset}/{move}` — pulls the
  dataset from **huggingface.co** (404 without a real HF `repo_id`; not usable
  offline — we synthesize expressions instead).
- `POST /api/move/goto` — interpolated move. Body `GotoModelRequest`:
  ```json
  {"head_pose": {"x":0,"y":0,"z":0,"roll":0,"pitch":0,"yaw":0},
   "antennas": [0.0, 0.0], "body_yaw": 0.0,
   "duration": 1.2, "interpolation": "minjerk"}
  ```
  `duration` **required**. `interpolation` ∈ `linear|minjerk|ease_in_out|cartoon`
  (default `minjerk`). `head_pose`/`antennas`/`body_yaw` nullable (omit = hold).
- `POST /api/move/set_target` — immediate, for high-rate loops. Body
  `FullBodyTarget`: `{target_head_pose, target_antennas:[L,R],
  target_body_yaw, timestamp}`.
- `POST /api/move/stop`, `GET /api/move/running`

### Media / audio / camera
- `GET /api/camera/specs` — resolutions + intrinsics **only**. There is **no
  REST camera-frame/snapshot endpoint** → room-light sensing can't use the
  robot cam over REST (hence laptop webcam for the easy-win build).
- `POST /api/media/acquire` · `/release`, `GET /api/media/status`
  (`{available, released, no_media}`)
- `POST /api/media/play_sound` · `/stop_sound`, `GET/POST /api/media/sounds...`
- `GET/POST /api/volume...`, `/api/volume/microphone...`

### Apps (lifecycle, all over REST)
- `GET /api/apps/list-available`, `/current-app-status`
- `POST /api/apps/install` `{ "url": "https://huggingface.co/spaces/<u>/<app>" }`
- `POST /api/apps/start-app/{app_name}` · `/stop-current-app` · `/restart-current-app`
- `POST /api/apps/remove/{app_name}`, `GET /api/apps/job-status/{job_id}`

### Safety clamps (daemon enforces; stay just inside)
| Axis | Limit |
|---|---|
| Head pitch / roll | ±40° (~±0.70 rad) |
| Head yaw | ±180° |
| Body yaw | ±160° |
| Head-vs-body yaw delta | ≤ 65° |

---

## 3. SDK quickstart essentials

```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

with ReachyMini() as mini:                       # auto: localhost(Lite/on-robot) vs network(Wireless)
    mini.goto_target(antennas=[0.5, -0.5], duration=0.5)
```

- **Constructor**: `ReachyMini(connection_mode=..., media_backend=..., host=...)`.
  Auto-detects Lite vs Wireless. Override: `connection_mode="network"` |
  `"localhost_only"`; `host="192.168.99.2"` for our classroom IP (no `.local`
  DNS). `media_backend`: `default|local|webrtc|no_media`.
- **`goto_target(head=, antennas=, body_yaw=, duration=, method=)`** —
  interpolated (`method` = interpolation technique, default `minjerk`).
- **`set_target(...)`** — immediate, for high-rate (~50 Hz) loops.
- **`create_head_pose(x=,y=,z=, roll=,pitch=,yaw=, degrees=False, mm=False)`** —
  pass `degrees=True`/`mm=True` to use degrees/mm instead of rad/m.
- **IMU (Wireless only)**: `mini.imu` → keys `accelerometer` (m/s²),
  `gyroscope` (rad/s), `quaternion` (w,x,y,z), `temperature`.
- **Camera**: `ReachyMini(media_backend="default")` then
  `mini.media.get_frame()` → `uint8` H×W×3.
- **Audio**: `start_recording()` / `get_audio_sample()` /
  `push_audio_sample()` / `play_sound()` / `stop_*`.
- **Motors**: `enable_motors()`, `disable_motors()`,
  `enable_gravity_compensation()`. Canned: `wake_up()`, `goto_sleep()`.

### Run SDK on the robot (low latency, no network/WebRTC)
```bash
ssh pollen@reachy-mini            # pw: root
source /venvs/apps_venv/bin/activate
python my_script.py               # ReachyMini() stays on localhost automatically
```

---

## 4. ReachyMiniApp contract (for installable apps)

```python
import threading, time
from reachy_mini import ReachyMini, ReachyMiniApp

class MyApp(ReachyMiniApp):
    custom_app_url: str | None = "http://0.0.0.0:8042"   # or None for no web UI

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event):
        @self.settings_app.post("/my_endpoint")           # FastAPI on settings_app
        def my_endpoint(): return {"status": "ok"}
        while not stop_event.is_set():
            reachy_mini.set_target(...)
            time.sleep(0.02)

if __name__ == "__main__":
    app = MyApp()
    try: app.wrapped_run()
    except KeyboardInterrupt: app.stop()
```

- Implement **only `run(reachy_mini, stop_event)`**; `reachy_mini` is already
  connected. Poll `stop_event`. `wrapped_run()` wires connection + services;
  `stop()` sets the event (daemon sends `SIGINT` on stop).
- Daemon runs it as `python -u -m your_app.main` — the `__main__` block is
  mandatory. **One app at a time**; daemon owns hardware + restores default
  pose on exit.
- `custom_app_url` set → FastAPI server auto-serves `your_app/static/`;
  routes go on `self.settings_app`. Reachable at
  `http://reachy-mini.local:8042` (Wireless) / `http://localhost:8042` (Lite).
- App subprocess **inherits the daemon's env vars** (no injection). Runtime
  config → the web UI settings page, or a `.env`/known path.
- On Wireless, apps run in the shared venv **`/venvs/apps_venv/`**.

### Scaffolding / publish (never hand-create the folder)
```bash
uv pip install reachy-mini
reachy-mini-app-assistant create my_app /path [--publish]
reachy-mini-app-assistant create --template conversation my_app /path   # LLM/voice stack
reachy-mini-app-assistant check /path/to/my_app
python -m my_app.main                       # quick local run (daemon must be up)
uv pip install -e /path/to/my_app           # test via dashboard
reachy-mini-app-assistant publish /path/to/my_app
```
- `pyproject.toml` entry point group is **`reachy_mini_apps`**:
  `my_app = "my_app.main:MyApp"`. Add deps here too.
- `README.md` YAML frontmatter **must** include tag `reachy_mini_python_app`
  for app-store discoverability.
- Templates: **Default** (most apps) · **Conversation** (LLM + audio pipeline +
  movement fusion — the basis for the native conversation app we're priming).

### Offline deploy to our Wireless unit
```bash
scp -r /path/to/my_app pollen@reachy-mini.local:/tmp/my_app
ssh pollen@reachy-mini.local "/venvs/apps_venv/bin/pip install /tmp/my_app"
# then restart app/daemon; clear __pycache__ if code didn't refresh
```

### Debugging on the robot
```bash
ssh pollen@reachy-mini.local
sudo journalctl -u reachy-mini-daemon -f
sudo journalctl -u reachy-mini-daemon --since '5 min ago' | grep -v "uvicorn\|GET \|POST "
sudo systemctl restart reachy-mini-daemon     # wait ~30s before starting an app
```

---

## 5. Gotchas that bit us / shape our design

- **No camera over REST** → robot-POV light sensing must run on-robot; the
  laptop-webcam build sidesteps this.
- **WebRTC signalling (`:8443`) times out** from a laptop on our wired LAN →
  apps use `request_media_backend="no_media"`; SDK media wants on-robot.
- **Motors-disabled pose is ambiguous** → toggle state lives in a file
  (`.run/reachy_toggle_state.json`); pose is only a cross-check.
- **`speech_detected` is free over REST** (`/api/state/doa`) — no audio
  pipeline needed for "someone spoke."
- **`goto` needs motors `enabled`** and a `duration`; canned `play/*` moves
  are slow → use long HTTP timeouts.
- **AGENTS.md** upstream is the canonical agent guide if we build a real app:
  `https://github.com/pollen-robotics/reachy_mini/blob/main/AGENTS.md`.
