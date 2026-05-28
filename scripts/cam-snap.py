#!/usr/bin/env python3
"""Wake up and take a picture. Simple camera demo — RUNS ON THE ROBOT.

Why on the robot: the daemon exposes no camera-over-REST; frames come from the
SDK, which is only reliable on localhost (the robot itself). So this is meant
to run on Reachy (the dashboard subprocesses it there), not from the laptop.

  python cam-snap.py                       # wake, snap → ~/peachy_snap.jpg
  python cam-snap.py --out /path/img.jpg   # choose where to save
  python cam-snap.py --no-wake             # don't move; just snap

Teaching notes (for the student):
  * ReachyMini(media_backend="default") gives you mini.media.get_frame()
  * a frame is a numpy uint8 array, shape (H, W, 3), BGR (SDK media.get_frame())
  * .wake_up() / .goto_sleep() are canned moves built into the SDK
"""

from __future__ import annotations

import argparse
import os
import sys
import time


def _save_jpg(frame, path: str, quality: int = 90, scale: float = 1.0) -> None:
    """frame = HxWx3 uint8 BGR from SDK. Save as JPEG in true RGB order."""
    q = max(1, min(100, int(quality)))
    sc = max(0.12, min(1.0, float(scale)))
    try:
        import cv2
        if sc < 0.99:
            h, w = frame.shape[:2]
            nw = max(48, int(w * sc))
            nh = max(36, int(h * sc))
            frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        return
    except Exception:
        pass
    try:
        from PIL import Image
        rgb = frame[:, :, ::-1]  # BGR → RGB for Pillow / JPEG viewers
        img = Image.fromarray(rgb)
        if sc < 0.99:
            w, h = img.size
            nw = max(48, int(w * sc))
            nh = max(36, int(h * sc))
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        img.save(path, quality=q)
        return
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            f"Could not save image ({e}). Need OpenCV or Pillow in this venv."
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Wake up and take a picture")
    ap.add_argument("--out", default=os.path.expanduser("~/peachy_snap.jpg"),
                    help="output JPEG path (default ~/peachy_snap.jpg)")
    ap.add_argument("--no-wake", action="store_true",
                    help="don't wake/move — just capture")
    ap.add_argument("--warmup", type=float, default=1.0,
                    help="seconds to let auto-exposure settle (default 1.0)")
    ap.add_argument("--quality", type=int, default=90,
                    help="JPEG quality 1–100 (default 90)")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="output width fraction 0.12–1.0 (default 1.0)")
    ap.add_argument("--fast", action="store_true",
                    help="light-probe mode: tiny JPEG, short warmup, no wake")
    args = ap.parse_args()
    if args.fast:
        args.no_wake = True
        args.warmup = min(args.warmup, 0.08)
        args.quality = min(args.quality, 28)
        args.scale = min(args.scale, 0.32)

    try:
        from reachy_mini import ReachyMini
    except ImportError:
        raise SystemExit(
            "reachy_mini SDK not found — run this ON the robot "
            "(source /venvs/apps_venv/bin/activate)."
        )

    print("Connecting to Reachy (camera on)…")
    with ReachyMini(media_backend="default") as mini:
        if not args.no_wake:
            print("wake_up()…")
            try:
                mini.wake_up()
            except Exception as e:  # noqa: BLE001
                print(f"  (wake_up skipped: {e})")
        time.sleep(args.warmup)  # let the camera's auto-exposure settle

        frame = None
        for _ in range(10):  # first frames can be None while the stream starts
            frame = mini.media.get_frame()
            if frame is not None:
                break
            time.sleep(0.2)
        if frame is None:
            raise SystemExit("No camera frame — is media available / not held "
                             "by another app?")

        _save_jpg(frame, args.out, args.quality, args.scale)
        h, w = frame.shape[:2]
        print(f"✓ saved {args.out}  ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
