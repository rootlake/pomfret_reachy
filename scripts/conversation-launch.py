#!/usr/bin/env python3
"""Start conversation app with Peachy idle-motion patch applied."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if (HERE.parent / "dashboard" / "conversation_patch").is_dir():
    _PATCH = HERE.parent / "dashboard" / "conversation_patch"
else:
    _PATCH = HERE / "conversation_patch"
sys.path.insert(0, str(_PATCH))

import bootstrap  # noqa: F401 — patches BreathingMove + mounts /idle-motion routes

from reachy_mini_conversation_app.main import main

if __name__ == "__main__":
    main()
