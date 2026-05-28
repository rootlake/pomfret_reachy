#!/usr/bin/env python3
"""v0.1 stub WebSocket server — runs on the VPS.

Replaces nothing yet. Proves end-to-end audio plumbing:
- Authenticates the bridge via Bearer token
- Counts mic frames received
- Every 3 seconds, sends a pre-recorded WAV back to every connected bridge
- Logs connect/disconnect events

This is the dumbest thing that could possibly work; v0.2 replaces it with
``peachy-ws-proxy.py`` that pipes between bridge and GlaDOS audio backend.

Bind:
    Defaults to 100.88.209.10 (Tailscale interface), NOT 0.0.0.0.
    School/Internet cannot reach this port — only the tailnet.

Token:
    Read from ``$PEACHY_TOKEN`` env var (set by systemd). Generate with
    ``openssl rand -hex 16``; keep the same value in ``~/.peachy_token``
    on every bridge.

Reply WAV:
    Set ``$PEACHY_REPLY_WAV`` (default looks for ``wake_up.wav`` next to
    this script). Should be 16 kHz mono S16 PCM WAV for cleanest playback
    on the reSpeaker.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Set

import websockets
from websockets.asyncio.server import ServerConnection, serve

# ── config ───────────────────────────────────────────────────────────────
BIND_HOST = os.environ.get("PEACHY_BIND", "100.88.209.10")
BIND_PORT = int(os.environ.get("PEACHY_PORT", "8765"))
TOKEN = os.environ.get("PEACHY_TOKEN", "")
REPLY_WAV = Path(os.environ.get(
    "PEACHY_REPLY_WAV",
    Path(__file__).resolve().parent.parent / ".run" / "v01_reply.wav",
))
REPLY_INTERVAL = float(os.environ.get("PEACHY_REPLY_INTERVAL", "3.0"))

# ── logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("v01-echo")

# ── shared state ─────────────────────────────────────────────────────────
clients: Set[ServerConnection] = set()
total_frames = 0
session_start = time.time()


async def authenticate(conn: ServerConnection) -> bool:
    """Verify Bearer token from request headers. Reject if missing/wrong."""
    if not TOKEN:
        log.error("PEACHY_TOKEN env not set — refusing all connections")
        return False
    auth = conn.request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return secrets.compare_digest(auth[7:].strip(), TOKEN)


async def handle(conn: ServerConnection) -> None:
    global total_frames
    peer = conn.remote_address[0] if conn.remote_address else "?"

    if not await authenticate(conn):
        log.warning("Auth failed from %s — closing", peer)
        await conn.close(code=4401, reason="auth")
        return

    clients.add(conn)
    log.info("CONNECT %s — %d client(s)", peer, len(clients))
    frame_count = 0
    try:
        async for msg in conn:
            if isinstance(msg, (bytes, bytearray)):
                frame_count += 1
                total_frames += 1
                # Lightweight logging — every 100 frames (~2s of audio)
                if frame_count % 100 == 0:
                    log.info("  %s: %d frames received (%d total)",
                             peer, frame_count, total_frames)
            elif isinstance(msg, str):
                log.info("  %s text: %s", peer, msg[:200])
    except websockets.exceptions.ConnectionClosed as e:
        log.info("DISCONNECT %s (%s) after %d frames", peer, e, frame_count)
    finally:
        clients.discard(conn)


async def reply_loop() -> None:
    """Every REPLY_INTERVAL, broadcast the reply WAV to all connected clients."""
    while True:
        await asyncio.sleep(REPLY_INTERVAL)
        if not clients:
            continue
        if not REPLY_WAV.exists():
            log.warning("Reply WAV missing: %s (skipping broadcast)", REPLY_WAV)
            continue
        data = REPLY_WAV.read_bytes()
        log.info("BROADCAST %d bytes to %d client(s)", len(data), len(clients))
        # Snapshot clients in case set mutates during await
        for c in list(clients):
            try:
                await c.send(data)
            except websockets.exceptions.ConnectionClosed:
                pass


async def stats_loop() -> None:
    """Periodic uptime/throughput log so we can tell the service is alive."""
    while True:
        await asyncio.sleep(60)
        up = time.time() - session_start
        log.info("STATS uptime=%.0fs clients=%d total_frames=%d (~%.1fs of audio)",
                 up, len(clients), total_frames, total_frames * 0.02)


async def main() -> None:
    if not TOKEN:
        log.error("Refusing to start without PEACHY_TOKEN")
        sys.exit(2)
    log.info("Listening on ws://%s:%d (reply every %.1fs from %s)",
             BIND_HOST, BIND_PORT, REPLY_INTERVAL, REPLY_WAV)
    async with serve(handle, BIND_HOST, BIND_PORT, max_size=2**22):
        await asyncio.gather(reply_loop(), stats_loop())


if __name__ == "__main__":
    asyncio.run(main())
