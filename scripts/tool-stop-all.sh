#!/usr/bin/env bash
# Stop Peachy automation — one command when too many things are running.
#
#   ./scripts/tool-stop-all.sh           # halt moves, conversation, room watch, preview
#   ./scripts/tool-stop-all.sh --sleep   # same + gentle sleep
#
# Does not stop the dashboard or the robot daemon.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${ROOT}/.run"
ENVFILE="${RUN}/reachy.env"
# shellcheck source=/dev/null
[ -f "${ENVFILE}" ] && set -a && source "${ENVFILE}" && set +a

HOST="${REACHY_HOST:-127.0.0.1}"
PORT="${REACHY_PORT:-8000}"
SSH_TARGET="${REACHY_SSH:-}"
SSH_PORT="${REACHY_SSH_PORT:-}"
SLEEP=0
for arg in "$@"; do
  case "$arg" in
    --sleep|-s) SLEEP=1 ;;
  esac
done

msgs=()

curl -sf -m4 -X POST "http://${HOST}:${PORT}/api/move/stop" \
  -H "Content-Type: application/json" -d '{}' >/dev/null 2>&1 \
  && msgs+=("move halted") || msgs+=("move halt skipped")

if [ -f "${RUN}/dashboard_roomwatch.pid" ]; then
  pid="$(cat "${RUN}/dashboard_roomwatch.pid" 2>/dev/null || true)"
  if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    sleep 0.3
    kill -9 "${pid}" 2>/dev/null || true
    msgs+=("room watch stopped")
  fi
  rm -f "${RUN}/dashboard_roomwatch.pid"
fi

if [ -n "${SSH_TARGET}" ]; then
  ssh_args=(-o ConnectTimeout=8 -o BatchMode=yes)
  [ -n "${SSH_PORT}" ] && ssh_args+=(-p "${SSH_PORT}")
  ssh "${ssh_args[@]}" "${SSH_TARGET}" \
    "pkill -f cam-preview-loop.py 2>/dev/null; pkill -f cam-motion-watch.py 2>/dev/null; true" \
    >/dev/null 2>&1 && msgs+=("preview stopped") || true
fi
rm -f "${RUN}/cam_preview_on"

if "${ROOT}/scripts/app-conversation.sh" stop 2>/dev/null || true; then
  :
fi
if ! "${ROOT}/scripts/app-conversation.sh" status >/dev/null 2>&1; then
  msgs+=("conversation stopped")
fi

if [ "${SLEEP}" = "1" ]; then
  if python "${ROOT}/scripts/ctl-toggle.py" sleep 2>&1 | tail -1 | grep -q "asleep"; then
    msgs+=("asleep")
  elif python "${ROOT}/scripts/ctl-toggle.py" sleep >/dev/null 2>&1; then
    msgs+=("asleep")
  else
    msgs+=("sleep failed")
  fi
fi

if [ "${#msgs[@]}" -eq 0 ]; then
  echo "nothing running — Peachy idle"
else
  (IFS=' · '; echo "${msgs[*]}")
fi
