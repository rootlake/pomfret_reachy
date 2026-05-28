#!/usr/bin/env bash
# Quick room modes without Reachy Control (combine wake/sleep + conversation service).
#
#   ./scripts/app-roommode.sh greet   # wake robot + start conversation app (background)
#   ./scripts/app-roommode.sh leave   # stop conversation app + sleep robot
#
# Uses REACHY_HOST / REACHY_PORT (defaults in ctl-wake.py).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

case "${1:-}" in
  greet)
    python scripts/ctl-wake.py wake
    scripts/app-conversation.sh start
    echo "Conversation PID file: ${ROOT}/.run/conversation_app.pid — logs: ${ROOT}/.run/conversation_app.log"
    ;;
  leave)
    scripts/app-conversation.sh stop || true
    python scripts/ctl-wake.py sleep
    ;;
  *)
    echo "usage: $0 {greet|leave}" >&2
    exit 2
    ;;
esac
