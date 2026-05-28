"""Detect leave phrases in user transcripts → app-leave.sh."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_LEAVE = _REPO / "scripts" / "app-leave.sh"

# PEACHY_SLEEP_PHRASES=goodnight peachy,go to sleep,i'm leaving
_DEFAULT = (
    r"good\s*night\s*peach",
    r"goodbye\s*peach",
    r"\bgo\s+to\s+sleep\b",
    r"\btime\s+to\s+sleep\b",
    r"\bi'?m\s+leaving\b",
    r"\bpeachy\s+sleep\b",
    r"\bsleep\s+peachy\b",
)

_lock = threading.Lock()
_last_trigger = 0.0
_COOLDOWN_S = 45.0


def _patterns() -> list[re.Pattern[str]]:
    import os

    raw = os.environ.get("PEACHY_SLEEP_PHRASES", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()] if raw else list(_DEFAULT)
    return [re.compile(p, re.I) for p in parts]


def _matches(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(p.search(t) for p in _patterns())


def _trigger_leave(source: str, text: str) -> None:
    global _last_trigger
    with _lock:
        now = time.time()
        if now - _last_trigger < _COOLDOWN_S:
            return
        _last_trigger = now
    logger.info("Sleep phrase (%s): %r", source, text[:80])
    if not _LEAVE.is_file():
        logger.error("missing %s", _LEAVE)
        return
    subprocess.Popen(
        ["/bin/bash", str(_LEAVE)],
        cwd=_REPO,
        start_new_session=True,
    )


def check_user_transcript(text: str) -> bool:
    """Return True if leave was triggered."""
    if not _matches(text):
        return False
    _trigger_leave("transcript", text)
    return True


def apply_sleep_phrase_patch() -> None:
    from fastrtc.utils import AdditionalOutputs

    if getattr(AdditionalOutputs, "_peachy_sleep_patched", False):
        return

    _orig_init = AdditionalOutputs.__init__

    def _patched_init(self, *args, **kwargs) -> None:
        _orig_init(self, *args, **kwargs)
        if len(args) == 1 and isinstance(args[0], dict):
            payload = args[0]
            if payload.get("role") == "user":
                check_user_transcript(str(payload.get("content", "")))

    AdditionalOutputs.__init__ = _patched_init  # type: ignore[method-assign]
    AdditionalOutputs._peachy_sleep_patched = True  # type: ignore[attr-defined]

    logger.info(
        "Peachy sleep-phrase hook active (phrases: %s)",
        "PEACHY_SLEEP_PHRASES" if __import__("os").environ.get("PEACHY_SLEEP_PHRASES") else "defaults",
    )
