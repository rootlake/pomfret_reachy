#!/usr/bin/env bash
# Launch the official Reachy Mini Conversation App from the CLI.
#
# Same package Control uses: https://github.com/pollen-robotics/reachy_mini_conversation_app
# Install into this repo's venv:
#   uv pip install reachy_mini_conversation_app
#
# Examples:
#   ./scripts/app-run-conversation.sh
#   ./scripts/app-run-conversation.sh --gradio
#   ./scripts/app-run-conversation.sh --debug --no-camera
#
# Connection: ReachyMini auto mode (localhost, then reachy-mini.local). For classroom IP only,
# add a hosts line:  192.168.99.2  reachy-mini.local
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/reachy_mini_env/bin/activate"

if command -v reachy-mini-conversation-app >/dev/null 2>&1; then
  exec reachy-mini-conversation-app "$@"
fi

if python -c "import reachy_mini_conversation_app" 2>/dev/null; then
  # Same entry as Control: ReachyMiniApp.wrapped_run (loads instance .env beside package).
  exec python -m reachy_mini_conversation_app.main "$@"
fi

echo "reachy_mini_conversation_app is not installed in reachy_mini_env." >&2
echo "Install with:" >&2
echo "  uv pip install \"reachy_mini_conversation_app @ git+https://github.com/pollen-robotics/reachy_mini_conversation_app.git\"" >&2
exit 127
