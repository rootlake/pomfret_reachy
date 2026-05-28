# Assignment — Light wake / sleep panel

Build a collapsible sub-panel on the Peachy dashboard for **room-light automation**.

A stub exists at `#studentLightFold` in `dashboard/static/index.html`. Replace the stub readout with your finished UI.

**Important:** all light and camera reads use **Peachy's head camera** (SSH / live preview). The laptop webcam is never used.

---

## Must have

### 1. Live light readout

Poll **`GET /api/light`** every 2–3 seconds **only while your panel is open** (don't poll in the background — each read pulls a frame from Peachy).

Response shape:

```json
{
  "ok": true,
  "raw": 82.4,
  "ema": 79.1,
  "ref": 75.0,
  "delta": 4.1,
  "lit": false,
  "motion": 2.1,
  "on_delta": 25,
  "off_delta": 12,
  "source": "peachy_camera",
  "roomwatch": false,
  "preview": true
}
```

Show at minimum:
- **Lit vs dark** (big, obvious)
- `ema` and `ref` (or a bar vs threshold)

If `preview` is false, suggest tapping **Live (Peachy cam)** first — reads are slower without it.

### 2. Start / stop auto mode

- `POST /api/roomwatch/start` — starts `watch-room.py` (auto-starts live preview if needed)
- `POST /api/roomwatch/stop` — stops it

When watch is running, Peachy should wake when the room brightens and sleep when dark + quiet.

### 3. Collapsible panel

Same `<details class="tune-fold">` pattern as Head tune / Portal turret.

---

## Code pointers

| What | Where |
|---|---|
| Light sensor (Peachy cam) | `scripts/light_sensor.py` |
| State machine | `scripts/watch-room.py` |
| CLI test | `python scripts/light_probe.py --json` |
| API | `GET /api/light`, `POST /api/roomwatch/...` |
| Frontend stub | `#studentLightFold` in `index.html` |

---

## Testing safely

1. Start **Live** on the dashboard (Peachy camera stream)
2. `python scripts/light_probe.py --json` — flip lights, watch `lit`
3. `python scripts/watch-room.py --dry-run` — no movement
4. Your panel → start room watch → flip lights

---

## Done when

Teacher opens your panel on a phone, starts room watch, flips lights — Peachy wakes with turret **Activated**, sleeps when dark.
