#!/usr/bin/env python3
"""Motion-gated camera on the robot — only writes a JPEG when the scene changes.

Same env as cam-preview-loop.py (INTERVAL, QUALITY, SCALE). Use for visitor
detection / watch-room: poll mtime or read the file when it updates; major
motion → greet / wake pipeline (see watch-room.py MOTION_THRESH on laptop today).

  PEACHY_MOTION_THRESH   mean abs gray frame Δ (0–255), default 8.0
  PEACHY_PREVIEW_INTERVAL  min seconds between checks (default 0.85)

  python cam-motion-watch.py /tmp/peachy_live.jpg
"""
from __future__ import annotations

import os
import signal
import sys
import time

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/peachy_live.jpg"
INTERVAL = float(os.environ.get("PEACHY_PREVIEW_INTERVAL", "0.85"))
QUALITY = max(20, min(90, int(os.environ.get("PEACHY_PREVIEW_QUALITY", "45"))))
SCALE = max(0.2, min(1.0, float(os.environ.get("PEACHY_PREVIEW_SCALE", "0.5")))
MOTION_THRESH = float(os.environ.get("PEACHY_MOTION_THRESH", "8.0"))

_running = True
_prev = None


def _stop(*_args) -> None:
    global _running
    _running = False


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _gray_small(frame):
    import cv2

    h, w = frame.shape[:2]
    nw = max(64, int(w * SCALE))
    nh = max(48, int(h * SCALE))
    small = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _motion_delta(gray) -> float:
    global _prev
    import cv2

    if _prev is None or _prev.shape != gray.shape:
        _prev = gray.copy()
        return 0.0
    diff = cv2.absdiff(gray, _prev)
    _prev = gray.copy()
    return float(diff.mean())


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
        f"motion watch → {OUT} every {INTERVAL}s "
        f"thresh={MOTION_THRESH} q={QUALITY} scale={SCALE:.2f}",
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
                    mot = _motion_delta(_gray_small(frame))
                    if mot >= MOTION_THRESH:
                        _save(frame, OUT)
                        print(f"motion {mot:.1f} → saved", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"frame error: {e}", flush=True)
            time.sleep(INTERVAL)
    print("motion watch stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
