# Build your own Peachy app

Three ways to extend the robot, from simplest to most capable. Pick based on what you need.

| Approach | You write… | Runs where | Best for |
|---|---|---|---|
| **REST script** | Python/bash calling `http://<robot>:8000/api/...` | Your laptop | One-off commands, cron jobs, learning the API |
| **Dashboard panel** | HTML/JS in `dashboard/static/` + optional API in `server.py` | Your laptop (serves UI) | Phone controls, room automation, shared classroom UI |
| **ReachyMiniApp** | Python subclass of `ReachyMiniApp` | Robot daemon (or laptop sim) | Voice loops, IMU, camera, always-on behavior |

Official upstream docs: [Reachy Mini SDK — Apps](https://huggingface.co/docs/reachy_mini/SDK/apps)

---

## Path 1: REST scripts (start here)

The daemon on the robot exposes HTTP on port **8000**. Our scripts are thin clients — no magic.

**Smallest example:** `scripts/ctl-wake.py`

```python
# Pattern used everywhere:
POST /api/motors/set_mode/enabled   # ALWAYS first — or moves are silent no-ops
POST /api/move/play/wake_up
POST /api/move/play/goto_sleep
GET  /api/state/full                # read pose, motor mode, etc.
POST /api/move/goto                 # custom head/antenna/body pose
```

**Try it:**

```bash
python scripts/ctl-wake.py wake
python scripts/ctl-toggle.py status
python scripts/ctl-express.py express curious
```

**Build something new:**

1. Copy `scripts/ctl-wake.py` → `scripts/my-thing.py`
2. Use `from hostfind import resolve_host` — scripts auto-find the robot
3. Add `--dry-run` if your script moves the robot autonomously
4. Follow the `tag-verb` naming: `ctl-`, `watch-`, `cam-`, etc.

**Capstone to study:** `scripts/watch-room.py` — a real state machine (light + motion + speech → wake → greet → sleep).

Work through exercises in [`TOOLKIT.md`](../TOOLKIT.md) before building your own.

---

## Path 2: Dashboard extension

The dashboard is a **FastAPI** server (`dashboard/server.py`) + a single-page app (`dashboard/static/index.html`).

### Add a UI panel

1. Open `dashboard/static/index.html`
2. Find an existing collapsible panel (e.g. Head tune, Portal turret)
3. Copy the `<details class="tune-fold">` pattern
4. Wire buttons to existing API routes, or add new ones in `server.py`

**Existing APIs you can call from JavaScript:**

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Robot pose, control mode, room-watch state |
| `GET /api/light` | Brightness, lit/dark, motion (Peachy camera) |
| `POST /api/do/{wake\|sleep\|toggle}` | Wake/sleep |
| `POST /api/express/{name}` | Run an expression |
| `POST /api/roomwatch/{start\|stop}` | Start/stop `watch-room.py` |
| `POST /api/converse/{start\|stop}` | Conversation app |
| `GET /api/log` | Activity log |

**First assignment:** [`dashboard/student/LIGHT-PANEL.md`](../dashboard/student/LIGHT-PANEL.md)

### Add a new API route

In `dashboard/server.py`, follow existing patterns:

```python
@app.post("/api/my-feature")
def my_feature():
    # Delegate to a script — keep server.py thin
    subprocess.run([sys.executable, str(SCRIPTS / "my-thing.py"), "--flag"], ...)
    return {"ok": True}
```

Restart the dashboard after changes:

```bash
./run.sh --restart
```

Hard-refresh the browser (Cmd+Shift+R) — `index.html` is aggressively cached.

---

## Path 3: ReachyMiniApp (full apps)

For apps that need the SDK (camera frames, IMU, tight control loops, voice), subclass **`ReachyMiniApp`**.

**Example in this repo:** [`apps/boo_hide/`](../apps/boo_hide/)

- Say **"boo"** → robot sleeps
- Three knocks on the head → wake (wireless IMU)
- Small web UI for testing

### Scaffold a new app

With your venv active:

```bash
reachy-mini-app-assistant create my_app_name ./apps/my_app_name
cd apps/my_app_name
pip install -e .
```

This generates the official project layout: `main.py`, `pyproject.toml`, static UI, Hugging Face metadata.

### Minimal app skeleton

```python
from reachy_mini import ReachyMini, ReachyMiniApp

class MyApp(ReachyMiniApp):
    def run(self, reachy_mini: ReachyMini, stop_event) -> None:
        while not stop_event.is_set():
            # read IMU, camera, etc.
            # reachy_mini.goto_sleep() / wake_up() / goto(...)
            stop_event.wait(0.05)

if __name__ == "__main__":
    MyApp().wrapped_run()
```

### Run locally (laptop talks to robot over LAN)

```bash
export REACHY_HOST=192.168.99.2   # or let hostfind resolve it
python -m my_app_name.main
```

Or install and start from **Reachy Mini Control** → Apps.

### Deploy to the robot (optional)

```bash
scp -r apps/my_app_name pollen@reachy-mini.local:~/peachy/apps/
ssh pollen@reachy-mini.local
source /venvs/apps_venv/bin/activate
pip install -e ~/peachy/apps/my_app_name
```

Then start from Control, or:

```bash
curl -X POST http://192.168.99.2:8000/api/apps/start-app/my_app_name
```

---

## Design tips

### Always enable motors first

```python
POST /api/motors/set_mode/enabled
```

Without this, `wake_up`, `goto_sleep`, and `goto` do nothing — no error, just silence. Every `ctl-*` script does this; your code should too.

### Camera and audio

- **No REST endpoint for camera frames.** Use the SDK on the robot, or SSH + `cam-snap.py`, or the dashboard live preview.
- **WebRTC from a laptop often times out** on school networks. Set `no_media=True` on the SDK if you only need motion (see `boo_hide`).

### Test safely

```bash
python scripts/watch-room.py --dry-run    # autonomous scripts
python scripts/ctl-toggle.py status       # verify connection first
```

### Use the activity log

The dashboard `/api/log` shows every action. When debugging your panel or script, watch the log in real time.

### Ask the AI

Open this repo in Cursor/Claude Code. **`CLAUDE.md`** tells the assistant the golden rules and file map. Point it at your file: *"Add a dashboard panel that …"*

---

## Where to go next

| Goal | Start here |
|---|---|
| Learn REST control | [`TOOLKIT.md`](../TOOLKIT.md) exercises 1–3 |
| Room automation | `scripts/watch-room.py`, `scripts/light_sensor.py` |
| Expressions / animation | `scripts/ctl-express.py` |
| Voice + IMU app | [`apps/boo_hide/`](../apps/boo_hide/) |
| API reference | [`reachy_mini_build_reference.md`](reachy_mini_build_reference.md) |
| Upstream app docs | [HF SDK Apps](https://huggingface.co/docs/reachy_mini/SDK/apps) |
