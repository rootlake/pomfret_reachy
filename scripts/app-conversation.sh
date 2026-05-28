#!/usr/bin/env bash
# Start / stop the official conversation app in the background.
#
# Mic, camera, and the SDK must run ON THE ROBOT — not on the laptop over an
# SSH tunnel. When REACHY_SSH is set (typical classroom / uplink), start/stop
# goes over SSH and uses /venvs/apps_venv on Peachy.
#
#   ./scripts/app-conversation.sh start            # headless — talk to Peachy
#   ./scripts/app-conversation.sh start --gradio   # + Gradio UI on robot :7860
#   ./scripts/app-conversation.sh stop
#   ./scripts/app-conversation.sh status
#   ./scripts/app-conversation.sh log              # tail remote/local log
#
# Local PID/log:  .run/conversation_app.{pid,log}
# Remote PID/log: ~/.run/conversation_app.{pid,log} on the robot
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${ROOT}/.run"
ENVFILE="${RUN}/reachy.env"
# shellcheck source=/dev/null
[ -f "${ENVFILE}" ] && set -a && source "${ENVFILE}" && set +a

PIDFILE="${RUN}/conversation_app.pid"
LOG="${RUN}/conversation_app.log"
GRADIOFILE="${RUN}/conversation_app.gradio"
ROBOT_PY="${PEACHY_ROBOT_PY:-/venvs/apps_venv/bin/python}"
REMOTE_PIDF="${HOME}/.run/conversation_app.pid"
REMOTE_LOG="${HOME}/.run/conversation_app.log"
REMOTE_PEACHY="${HOME}/peachy"
LAUNCHER="${ROOT}/scripts/conversation-launch.py"

_ssh() {
  local port=()
  [ -n "${REACHY_SSH_PORT:-}" ] && port=(-p "${REACHY_SSH_PORT}")
  ssh "${port[@]}" -o ConnectTimeout=10 "${REACHY_SSH}" "$@"
}

_ssh_batch() {
  local port=()
  [ -n "${REACHY_SSH_PORT:-}" ] && port=(-p "${REACHY_SSH_PORT}")
  ssh "${port[@]}" -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
    "${REACHY_SSH}" "$@"
}

_rsync_ssh() {
  local -a ssh_e=(ssh -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
  [ -n "${REACHY_SSH_PORT:-}" ] && ssh_e+=(-p "${REACHY_SSH_PORT}")
  rsync -az -e "${ssh_e[*]}" "$@"
}

_sync_remote_patch() {
  if ! _ssh_batch true 2>/dev/null; then
    echo "⚠ SSH to ${REACHY_SSH} failed — skipping patch sync" >&2
    echo "  Run: ./scripts/net-connect.sh --via-uplink" >&2
    echo "  Test: ssh -p ${REACHY_SSH_PORT:-22} ${REACHY_SSH} true" >&2
    return 0
  fi
  if ! _rsync_ssh \
    "${ROOT}/dashboard/conversation_patch/" \
    "${REACHY_SSH}:${REMOTE_PEACHY}/conversation_patch/"; then
    echo "⚠ patch rsync failed — conversation will start without idle-motion patch" >&2
    return 0
  fi
  _rsync_ssh "${LAUNCHER}" "${REACHY_SSH}:${REMOTE_PEACHY}/conversation-launch.py" || true
}

_launch_cmd() {
  local py="$1"
  shift
  if [ -x "${LAUNCHER}" ] && "${py}" -c "import reachy_mini_conversation_app" 2>/dev/null; then
    echo "${py} ${LAUNCHER}"
    return 0
  fi
  if command -v reachy-mini-conversation-app >/dev/null 2>&1; then
    echo "reachy-mini-conversation-app"
    return 0
  fi
  if "${py}" -c "import reachy_mini_conversation_app" 2>/dev/null; then
    echo "${py} -m reachy_mini_conversation_app.main"
    return 0
  fi
  return 1
}

_use_remote() {
  [ "${REACHY_ON_ROBOT:-}" = "1" ] && return 1
  [ -n "${REACHY_SSH:-}" ] || return 1
  return 0
}

_local_py() {
  if [ "${REACHY_ON_ROBOT:-}" = "1" ] && [ -x "${ROBOT_PY}" ]; then
    echo "${ROBOT_PY}"
    return
  fi
  if [ -x "${ROOT}/reachy_mini_env/bin/python" ]; then
    echo "${ROOT}/reachy_mini_env/bin/python"
    return
  fi
  if [ -x "${ROBOT_PY}" ]; then
    echo "${ROBOT_PY}"
    return
  fi
  echo ""
}

_remote_start() {
  local quoted=""
  for a in "$@"; do quoted+="$(printf ' %q' "$a")"; done
  if ! _ssh_batch true 2>/dev/null; then
    echo "✗ Cannot SSH to ${REACHY_SSH} (port ${REACHY_SSH_PORT:-22})" >&2
    echo "  1. Power Peachy on and wait ~45s" >&2
    echo "  2. ./scripts/net-connect.sh --via-uplink" >&2
    echo "  3. Test: ssh -p ${REACHY_SSH_PORT:-22} ${REACHY_SSH} true" >&2
    return 1
  fi
  _sync_remote_patch
  _ssh_batch bash <<EOF
set -euo pipefail
mkdir -p "\${HOME}/.run" "\${HOME}/peachy"
PIDF="\${HOME}/.run/conversation_app.pid"
RLOG="\${HOME}/.run/conversation_app.log"
if [ -f "\${PIDF}" ] && kill -0 "\$(cat "\${PIDF}")" 2>/dev/null; then
  echo "already running PID \$(cat "\${PIDF}")"
  exit 0
fi
if [ ! -x "${ROBOT_PY}" ]; then
  echo "missing ${ROBOT_PY} on robot" >&2
  exit 127
fi
if "${ROBOT_PY}" -c "import reachy_mini_conversation_app" 2>/dev/null \
   && [ -f "\${HOME}/peachy/conversation-launch.py" ]; then
  BIN=("${ROBOT_PY}" "\${HOME}/peachy/conversation-launch.py")
elif "${ROBOT_PY}" -c "import reachy_mini_conversation_app" 2>/dev/null; then
  BIN=("${ROBOT_PY}" -m reachy_mini_conversation_app.main)
elif command -v reachy-mini-conversation-app >/dev/null 2>&1; then
  BIN=(reachy-mini-conversation-app)
else
  echo "reachy_mini_conversation_app not installed on robot" >&2
  exit 127
fi
nohup "\${BIN[@]}"${quoted} >>"\${RLOG}" 2>&1 &
echo \$! > "\${PIDF}"
echo "remote PID \$(cat "\${PIDF}")"
EOF
}

_remote_stop() {
  _ssh bash <<'EOF'
set -euo pipefail
PIDF="${HOME}/.run/conversation_app.pid"
if [ ! -f "${PIDF}" ]; then
  echo "not running (no pid file)"
  exit 0
fi
PID="$(cat "${PIDF}")"
if kill -0 "${PID}" 2>/dev/null; then
  kill "${PID}" || true
  echo "stopped ${PID}"
else
  echo "stale pid ${PID}"
fi
rm -f "${PIDF}"
EOF
}

_remote_status() {
  _ssh bash <<'EOF'
PIDF="${HOME}/.run/conversation_app.pid"
if [ -f "${PIDF}" ] && kill -0 "$(cat "${PIDF}")" 2>/dev/null; then
  echo "running PID $(cat "${PIDF}")"
  exit 0
fi
echo "stopped"
exit 1
EOF
}

_remote_pid() {
  _ssh 'cat "${HOME}/.run/conversation_app.pid" 2>/dev/null' || true
}

case "${1:-}" in
  start)
    shift
    if echo " $* " | grep -qE ' (--gradio | --gradio$|^--gradio )'; then
      echo "1" >"${GRADIOFILE}"
    else
      rm -f "${GRADIOFILE}"
    fi
    if _use_remote; then
      echo "Starting conversation app on ${REACHY_SSH} (mic/camera live on robot)…"
      out="$(_remote_start "$@")"
      echo "${out}"
      pid="$(echo "${out}" | awk '/remote PID/{print $NF}')"
      if [ -n "${pid}" ]; then
        mkdir -p "${RUN}"
        echo "${pid}" >"${PIDFILE}"
        echo "remote" >"${RUN}/conversation_app.mode"
      fi
      echo "Log on robot: ~/.run/conversation_app.log"
      exit 0
    fi
    mkdir -p "${RUN}"
    if [[ -f "${PIDFILE}" ]] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
      echo "Conversation app already running PID $(cat "${PIDFILE}")" >&2
      exit 1
    fi
    py="$(_local_py)"
    [ -n "${py}" ] || { echo "No python/venv found" >&2; exit 127; }
    cmd="$(_launch_cmd "${py}")" || { echo "Install: uv pip install reachy_mini_conversation_app" >&2; exit 127; }
    echo "Logging to ${LOG}"
    # shellcheck disable=SC2086
    nohup ${cmd} "$@" >>"${LOG}" 2>&1 &
    echo $! >"${PIDFILE}"
    rm -f "${RUN}/conversation_app.mode"
    echo "Started PID $(cat "${PIDFILE}")"
    ;;

  stop)
    if [ -f "${RUN}/conversation_app.mode" ] && _use_remote; then
      _remote_stop
      rm -f "${PIDFILE}" "${RUN}/conversation_app.mode" "${GRADIOFILE}"
      exit 0
    fi
    if _use_remote && _remote_status >/dev/null 2>&1; then
      _remote_stop
      rm -f "${PIDFILE}" "${RUN}/conversation_app.mode" "${GRADIOFILE}"
      exit 0
    fi
    if [[ ! -f "${PIDFILE}" ]]; then
      echo "No PID file (not running?)" >&2
      exit 1
    fi
    PID="$(cat "${PIDFILE}")"
    if kill -0 "${PID}" 2>/dev/null; then
      kill "${PID}" || true
      echo "Sent SIGTERM to ${PID}"
    else
      echo "Stale PID file (${PID} not running)" >&2
    fi
    rm -f "${PIDFILE}" "${RUN}/conversation_app.mode" "${GRADIOFILE}"
    ;;

  status)
    if [ -f "${RUN}/conversation_app.mode" ] && _use_remote; then
      _remote_status
      exit $?
    fi
    if _use_remote; then
      if _remote_status; then
        pid="$(_remote_pid)"
        [ -n "${pid}" ] && echo "${pid}" >"${PIDFILE}"
        echo "remote" >"${RUN}/conversation_app.mode"
        exit 0
      fi
      rm -f "${PIDFILE}" "${RUN}/conversation_app.mode" "${GRADIOFILE}"
      exit 1
    fi
    if [[ -f "${PIDFILE}" ]] && kill -0 "$(cat "${PIDFILE}")" 2>/dev/null; then
      echo "running PID $(cat "${PIDFILE}")"
      exit 0
    fi
    echo "stopped"
    exit 1
    ;;

  log)
    n="${2:-40}"
    if _use_remote; then
      _ssh "tail -n ${n} \"\${HOME}/.run/conversation_app.log\" 2>/dev/null || echo '(no log yet)'"
      exit 0
    fi
    tail -n "${n}" "${LOG}" 2>/dev/null || echo "(no log yet)"
    ;;

  *)
    echo "usage: $0 {start [-- ARGS]|stop|status|log [N]}" >&2
    exit 2
    ;;
esac
