#!/usr/bin/env python3
"""Wake / sleep Reachy via daemon REST (no Control, no SDK session).

Uses POST /api/move/play/wake_up and /api/move/play/goto_sleep.

Environment:
  REACHY_HOST   daemon IP or hostname (default: 192.168.99.2)
  REACHY_PORT   default 8000

Examples:
  python scripts/ctl-wake.py wake
  python scripts/ctl-wake.py sleep
  REACHY_HOST=172.18.1.187 python scripts/ctl-wake.py wake
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _post_move(host: str, port: int, path: str, timeout: float = 120.0) -> dict:
    url = f"http://{host}:{port}/api/move{path}"
    req = urllib.request.Request(url, method="POST", data=b"{}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"HTTP {e.code}: {e.read().decode(errors='replace')}"
        ) from e


def _enable(host: str, port: int) -> None:
    """Motors MUST be enabled or play/wake_up/goto_sleep are silent no-ops."""
    req = urllib.request.Request(
        f"http://{host}:{port}/api/motors/set_mode/enabled",
        method="POST", data=b"{}")
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.URLError:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description="Reachy daemon wake/sleep via REST")
    p.add_argument(
        "command",
        choices=("wake", "sleep"),
        help="wake → play/wake_up, sleep → play/goto_sleep",
    )
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hostfind import resolve_host
    p.add_argument("--host", default=resolve_host())
    p.add_argument("--port", type=int, default=int(os.environ.get("REACHY_PORT", "8000")))
    p.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout seconds (sleep motion can be slow)",
    )
    args = p.parse_args()

    path = "/play/wake_up" if args.command == "wake" else "/play/goto_sleep"
    print(f"POST http://{args.host}:{args.port}/api/move{path} …")
    _enable(args.host, args.port)            # else the move is a silent no-op
    out = _post_move(args.host, args.port, path, timeout=args.timeout)
    if args.command == "wake":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from head_pose import settle_home

        def _h(host, port, p, m, timeout=30.0, body=None):
            url = f"http://{host}:{port}{p}"
            data = json.dumps(body).encode() if body is not None else (b"{}" if m == "POST" else None)
            req = urllib.request.Request(url, method=m, data=data)
            if data is not None:
                req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                t = resp.read().decode()
                return json.loads(t) if t else {}

        if settle_home(_h, args.host, args.port):
            print("  (settled to saved head home)")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
