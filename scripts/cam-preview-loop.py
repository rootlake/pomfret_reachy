#!/usr/bin/env python3
"""Write robot camera frames to a JPEG in a loop — RUN ON THE ROBOT.

Keeps one ReachyMini media session open so preview frames are fast (~1/s).
Started/stopped by the dashboard via SSH (see /api/preview/start|stop).

Env (set by dashboard when starting):
  PEACHY_PREVIEW_INTERVAL   seconds between captures (default 0.85)
  PEACHY_PREVIEW_QUALITY    JPEG 1–100 (default 45)
  PEACHY_PREVIEW_SCALE      width fraction 0.2–1.0 (default 0.5)

Future visitor / watch-room path: cam-motion-watch.py (motion-gated, same env).

  python cam-preview-loop.py /tmp/peachy_live.jpg
"""
from __future__ import annotations

import os
import signal
import sys
import time

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/peachy_live.jpg"
INTERVAL = float(os.environ.get("PEACHY_PREVIEW_INTERVAL", "0.85"))
QUALITY = max(20, min(90, int(os.environ.get("PEACHY_PREVIEW_QUALITY", "45"))))
SCALE = max(0.2, min(1.0, float(os.environ.get("PEACHY_PREVIEW_SCALE", "0.5"))))

_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _save(frame, path: str) -> None:
    import cv2

    h, w = frame.shape[:2]
    if SCALE < 0.99:
        nw = max(64, int(w * SCALE))
        nh = max(48, int(h * SCALE))
        frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), QUALITY])


def main() -> int:
    from reachy_mini import ReachyMini

    print(
        f"preview stream → {OUT} every {INTERVAL}s "
        f"q={QUALITY} scale={SCALE:.2f}",
        flush=True,
    )
    with ReachyMini(media_backend="default") as mini:
        while _running:
            frame = None
            for _ in range(6):
                frame = mini.media.get_frame()
                if frame is not None:
                    break
                time.sleep(0.04)
            if frame is not None:
                try:
                    _save(frame, OUT)
                except Exception as e:  # noqa: BLE001
                    print(f"save failed: {e}", flush=True)
            time.sleep(INTERVAL)
    print("preview loop stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
