"""Daemon HTTP audio helper — no ReachyMini media stack required."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def play_sound_http(host: str, port: int, filename: str, timeout: float = 15.0) -> None:
    """POST ``/api/media/play_sound`` so the daemon plays a bundled or uploaded WAV."""
    url = f"http://{host}:{port}/api/media/play_sound"
    body = json.dumps({"file": filename}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"play_sound HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"play_sound failed: {e.code} {e.read().decode(errors='replace')}"
        ) from e
