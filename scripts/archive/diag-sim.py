#!/usr/bin/env python3
"""Motion exercises against the MuJoCo sim daemon on localhost.

Prerequisite (separate terminal):

  mjpython -m reachy_mini.daemon.app.main --sim
  # Do **not** pass ``--no-media`` if you want wake/sleep WAVs (HTTP ``play_sound``).

Verify: http://localhost:8000/docs

Run (venv active):

  python scripts/diag-sim.py
  python scripts/diag-sim.py --poses-only
  python scripts/diag-sim.py --no-daemon-sounds   # daemon started with --no-media
"""

from __future__ import annotations

import argparse
import sys

from reachy_daemon_audio import play_sound_http


def run_pose_sweep(mini: object) -> None:
    from reachy_mini.utils import create_head_pose

    mini.goto_target(
        head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
        antennas=[0.35, -0.35],
        duration=1.0,
    )
    mini.goto_target(
        head=create_head_pose(z=-5, yaw=-20, pitch=-10, degrees=True, mm=True),
        antennas=[-0.2, 0.2],
        duration=1.0,
    )
    mini.goto_target(
        head=create_head_pose(z=0, roll=0, pitch=0, yaw=0, degrees=True, mm=True),
        antennas=[0.0, 0.0],
        duration=1.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Reachy Mini simulator motion smoke test")
    parser.add_argument("--host", default="127.0.0.1", help="Daemon host")
    parser.add_argument("--port", type=int, default=8000, help="Daemon port")
    parser.add_argument(
        "--poses-only",
        action="store_true",
        help="Skip wake_up / goto_sleep (faster iteration)",
    )
    parser.add_argument(
        "--media-backend",
        default="no_media",
        help='SDK media backend (default: no_media — avoids camera/WebRTC in sim)',
    )
    parser.add_argument(
        "--no-daemon-sounds",
        action="store_true",
        help="Skip POST /api/media/play_sound (use when daemon has --no-media)",
    )
    args = parser.parse_args()

    daemon_sounds = not args.no_daemon_sounds and not args.poses_only

    from reachy_mini import ReachyMini

    print(f"Connecting to sim daemon at http://{args.host}:{args.port}/ …")
    with ReachyMini(
        connection_mode="localhost_only",
        host=args.host,
        port=args.port,
        media_backend=args.media_backend,
    ) as mini:
        mini.enable_motors()

        if not args.poses_only:
            print("  wake_up …")
            mini.wake_up()
            if daemon_sounds:
                print("  wake_up.wav (daemon HTTP) …")
                play_sound_http(args.host, args.port, "wake_up.wav")

        print("  pose sweep …")
        run_pose_sweep(mini)

        if not args.poses_only:
            if daemon_sounds:
                print("  go_sleep.wav (daemon HTTP) …")
                play_sound_http(args.host, args.port, "go_sleep.wav")
            print("  goto_sleep …")
            mini.goto_sleep()

    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
