"""Default Peachy conversation voice — Ballad (OpenAI realtime)."""

from __future__ import annotations

import os

PEACHY_DEFAULT_VOICE = "ballad"


def apply_voice_default() -> None:
    """Prefer Ballad when no startup voice is persisted."""
    try:
        from reachy_mini_conversation_app import config
        from reachy_mini_conversation_app import startup_settings
    except ImportError:
        return

    config.OPENAI_DEFAULT_VOICE = PEACHY_DEFAULT_VOICE
    config.DEFAULT_VOICE_BY_BACKEND = {
        **config.DEFAULT_VOICE_BY_BACKEND,
        config.OPENAI_BACKEND: PEACHY_DEFAULT_VOICE,
    }

    _orig_read = startup_settings.read_startup_settings

    def _read(instance_path):  # type: ignore[no-untyped-def]
        settings = _orig_read(instance_path)
        if os.environ.get("PEACHY_VOICE_LOCK", "").lower() in ("1", "true", "yes"):
            return settings
        return startup_settings.StartupSettings(
            profile=settings.profile,
            voice=PEACHY_DEFAULT_VOICE,
        )

    startup_settings.read_startup_settings = _read  # type: ignore[assignment]
