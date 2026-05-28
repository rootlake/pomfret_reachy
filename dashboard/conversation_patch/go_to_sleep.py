"""Tool: end conversation and put Peachy to sleep."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)
_REPO = Path(__file__).resolve().parents[2]
_LEAVE = _REPO / "scripts" / "app-leave.sh"


class GoToSleep(Tool):
    name = "go_to_sleep"
    description = (
        "End the conversation and put Peachy to sleep. Use when the user says "
        "goodnight, go to sleep, they're leaving, or clearly wants Peachy to rest."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Brief reason, e.g. user said goodnight",
            },
        },
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        reason = kwargs.get("reason", "user requested sleep")
        logger.info("Tool call: go_to_sleep reason=%s", reason)

        async def _leave() -> None:
            await asyncio.sleep(2.5)  # let goodbye audio finish
            if _LEAVE.is_file():
                subprocess.run(["/bin/bash", str(_LEAVE)], cwd=_REPO, check=False)
            else:
                subprocess.run(
                    [sys.executable, str(_REPO / "scripts" / "ctl-toggle.py"), "sleep"],
                    cwd=_REPO,
                    check=False,
                )

        asyncio.create_task(_leave(), name="peachy-go-to-sleep")
        return {"ok": True, "message": "Goodnight — going to sleep now."}
