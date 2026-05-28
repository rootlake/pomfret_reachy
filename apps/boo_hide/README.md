---
title: Boo Hide
emoji: 👋
colorFrom: red
colorTo: blue
sdk: static
pinned: false
short_description: Say boo → Reachy goes to sleep (or tap Simulate boo).
tags:
 - reachy_mini
 - reachy_mini_python_app
---

Say **“boo”** (or **Simulate boo**) → `goto_sleep()`. **Wireless:** three gentle knocks on the **head** → `wake_up()` (IMU spikes). **Sim / Lite:** **Simulate wake** or `POST /wake`.

Tune knocks with env, e.g. `REACHY_KNOCK_DELTA` (default `2.8` m/s²), `REACHY_KNOCK_MIN_GAP`, `REACHY_KNOCK_MAX_GAP`, `REACHY_KNOCK_DEBOUNCE`.

## Local install

From this directory, with your Reachy venv active:

```bash
uv pip install -e .
```

Voice capture needs PyAudio on macOS:

```bash
brew install portaudio
uv pip install pyaudio
```

Then install or run the app from Reachy Mini Control.

## Run with Reachy Mini Control (your LAN setup)

1. Robot reachable at **`192.168.99.2`** — wake it in Control if needed.
2. **Apps** → pick **boo_hide** → **Start** (venv where you ran `pip install -e` must be the one Control uses for local Python apps, if Control shells out to your env).
3. Open the app settings page: **`http://127.0.0.1:8042`** — button **Simulate “boo”** queues `goto_sleep()` without voice.
4. **Voice:** with Control running this app on your Mac, the mic is usually the **laptop**; say “boo” clearly. Recognition uses **Google** (needs internet). Wake Reachy again from Control after sleep.

**Classroom IP:** if the app cannot find `reachy-mini.local`, start Control (or your terminal) with  
`export REACHY_HOST=192.168.99.2`  
so the SDK connects over **network** mode to that daemon.

**Media:** this app sets **`no_media`** on the SDK so it does not open WebRTC (signalling on port **8443** often **times out** from a laptop on wired LAN). `goto_sleep()` may log that audio is unavailable; motion still runs.

**Optional CLI:** `REACHY_HOST=192.168.99.2 python -m boo_hide.main` from your venv; Ctrl+C to stop.