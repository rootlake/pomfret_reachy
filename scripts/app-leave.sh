#!/usr/bin/env bash
# Graceful classroom exit: gentle sleep, then stop conversation app.
#
#   ./scripts/app-leave.sh
#
# Also triggered by conversation phrase hook (see conversation_patch/sleep_on_phrase.py).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

python scripts/ctl-toggle.py sleep
./scripts/app-conversation.sh stop || true
echo "✓ Peachy asleep, conversation stopped"
