#!/usr/bin/env python3
"""Wired-classroom smoke test: wake motion via SDK + bundled sound via daemon HTTP.

Order: ``wake_up()`` first (built-in mid-sequence sounds are skipped when using
``no_media``), then one ``play_sound`` via HTTP so macOS does not need WebRTC/GStreamer.

Uses ``media_backend="no_media"`` so the client skips local media; audio is only
``POST /api/media/play_sound`` on the robot.

Run (venv active, dongle link up):

  export REACHY_HOST=192.168.99.2   # optional if default is fine
  python scripts/diag-wired.py

  python scripts/diag-wired.py --host 192.168.99.2
"""

from __future__ import annotations

import argparse
import os
import sys

from reachy_daemon_audio import play_sound_http


def main() -> int:
    parser = argparse.ArgumentParser(description="Reachy Mini wired SDK + sound smoke test")
    parser.add_argument(
        "--host",
        default=os.environ.get("REACHY_HOST", "192.168.99.2"),
        help="Robot IPv4 (default: env REACHY_HOST or 192.168.99.2)",
    )
    parser.add_argument("--port", type=int, default=8000, help="Daemon port")
    parser.add_argument(
        "--sound",
        default="wake_up.wav",
        help=(
            "Bundled sound on daemon, played after motion via HTTP "
            "(e.g. wake_up.wav, go_sleep.wav, impatient1.wav)"
        ),
    )
    parser.add_argument(
        "--skip-motion",
        action="store_true",
        help="Only play sound (no SDK / no joints)",
    )
    parser.add_argument(
        "--skip-sound",
        action="store_true",
        help="Only run wake motion (no HTTP play_sound; mid-sequence sounds are no-ops with no_media)",
    )
    args = parser.parse_args()

    if args.skip_motion:
        if not args.skip_sound:
            print(f"Playing {args.sound} on http://{args.host}:{args.port}/ …")
            play_sound_http(args.host, args.port, args.sound)
            print("  sound OK")
        return 0

    from reachy_mini import ReachyMini

    print(f"Connecting SDK (network, no_media) to {args.host} …")
    with ReachyMini(
        connection_mode="network",
        host=args.host,
        port=args.port,
        media_backend="no_media",
    ) as mini:
        # Full wake motion; play_sound calls inside wake_up() do nothing with no_media.
        mini.wake_up()
        print("  motion OK")

    if not args.skip_sound:
        print(f"Playing {args.sound} (HTTP) …")
        play_sound_http(args.host, args.port, args.sound)
        print("  sound OK")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
