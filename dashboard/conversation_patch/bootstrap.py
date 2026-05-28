"""Import before reachy_mini_conversation_app.main — Peachy conversation defaults."""

import os
from pathlib import Path

_PATCH = Path(__file__).resolve().parent

from idle_motion import apply_patches
from sleep_on_phrase import apply_sleep_phrase_patch
from voice_default import apply_voice_default

# External tool: go_to_sleep
os.environ.setdefault("REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY", str(_PATCH))
os.environ.setdefault("AUTOLOAD_EXTERNAL_TOOLS", "1")

apply_patches()
apply_voice_default()
apply_sleep_phrase_patch()

# Tell the model about sleep phrases + tool (appended to profile instructions).
_SLEEP_HINT = (
    "\n\nWhen the user says goodnight Peachy, go to sleep, they're leaving, "
    "or clearly wants to end the session, say a brief warm goodbye and call "
    "go_to_sleep. Do not keep chatting after they ask to sleep."
)


def _patch_session_instructions() -> None:
    import reachy_mini_conversation_app.prompts as prompts

    if getattr(prompts, "_peachy_sleep_instr_patched", False):
        return
    _orig = prompts.get_session_instructions

    def _wrapped() -> str:
        base = _orig()
        if _SLEEP_HINT.strip() in base:
            return base
        return base + _SLEEP_HINT

    prompts.get_session_instructions = _wrapped  # type: ignore[assignment]
    prompts._peachy_sleep_instr_patched = True  # type: ignore[attr-defined]


_patch_session_instructions()
