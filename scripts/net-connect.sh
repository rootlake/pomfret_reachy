#!/usr/bin/env bash
# Find Peachy and connect — one command from anywhere.
#
# Usage:
#   ./scripts/net-connect.sh           # auto: probe → LAN tunnel → uplink tunnel
#   ./scripts/net-connect.sh --status  # probe only, no tunnel setup
#   ./scripts/net-connect.sh --fix     # same as auto, but also restarts daemon if
#                                      #   backend is up but hardware is down
#   ./scripts/net-connect.sh --via-uplink  # force uplink path (VPS reverse tunnel)
#   ./scripts/net-connect.sh --tunnel      # force LAN SSH tunnel
#
# After success: scripts auto-resolve the host; no `source` needed.
# reachy.env is written with REACHY_HOST + REACHY_SSH[_PORT] for sub-tools.

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${ROOT}/.run"; mkdir -p "${RUN}"
ENVFILE="${RUN}/reachy.env"
[ -f "${ENVFILE}" ] && set -a && source "${ENVFILE}" && set +a

PORT="${REACHY_PORT:-8000}"
GRADIO_PORT="${REACHY_GRADIO_PORT:-7860}"
LASTFILE="${RUN}/reachy_host"
FQDNFILE="${RUN}/peachy_fqdn"
MODE="${1:-}"

# ── VPS uplink config ─────────────────────────────────────────────────────
UPLINK_HOST="${REACHY_UPLINK_HOST:-100.88.209.10}"
UPLINK_SSH_PORT="${REACHY_UPLINK_SSH_PORT:-2222}"

# ── LAN SSH target (direct or tunnel) ────────────────────────────────────
LAN_SSH="${REACHY_SSH_LAN:-pollen@reachy-mini.local}"

# SSH ControlMaster socket — one shared connection per target, avoids VPS floods
CTL_DIR="${RUN}/ssh-ctl"; mkdir -p "${CTL_DIR}"
ssh_ctl(){ echo "${CTL_DIR}/$(echo "$1" | tr '/.:@' '_')"; }

ssh_probe(){   # $1=target [$2=port]
  local port_args=(); [ -n "${2:-}" ] && port_args=(-p "$2")
  ssh ${port_args[@]+"${port_args[@]}"} \
      -o ControlMaster=auto \
      -o "ControlPath=$(ssh_ctl "$1${2:+:$2}")" \
      -o ControlPersist=60 \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=no \
      -o ConnectTimeout=8 \
      "$1" true 2>/dev/null
}

ssh_close(){   # $1=target [$2=port]
  local port_args=(); [ -n "${2:-}" ] && port_args=(-p "$2")
  ssh ${port_args[@]+"${port_args[@]}"} \
      -o "ControlPath=$(ssh_ctl "$1${2:+:$2}")" \
      -O exit "$1" 2>/dev/null || true
}

# ── Daemon probe ──────────────────────────────────────────────────────────
probe(){  # $1=host → 0 healthy / 2 backend-down / 1 unreachable
  local body
  body="$(curl -s -m3 "http://$1:${PORT}/api/state/full" 2>/dev/null)" || return 1
  [ -z "${body}" ] && return 1
  case "${body}" in
    *head_pose*)              return 0 ;;
    *"Backend not running"*)  return 2 ;;
    *)                        return 1 ;;
  esac
}

# ── Persist connection details ────────────────────────────────────────────
save_ok(){  # $1=host  $2=REACHY_SSH  [$3=REACHY_SSH_PORT]
  {
    printf 'export REACHY_HOST=%s\n' "$1"
    [ -n "${2:-}" ] && printf 'export REACHY_SSH=%s\n' "$2"
    [ -n "${3:-}" ] && printf 'export REACHY_SSH_PORT=%s\n' "$3"
  } > "${ENVFILE}"
  printf '%s' "$1" > "${LASTFILE}"
  echo
  echo "✓ Peachy is UP at $1:${PORT}"
  echo "  Next:  ./go   or   ./run.sh --restart"
  echo "  Status: python scripts/ctl-toggle.py status"
  [ -n "${2:-}" ] && echo "  SSH:    ${2}${3:+  port $3}"
}

tailscale_ok(){
  command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1
}

# ── Daemon restart over SSH ───────────────────────────────────────────────
restart_daemon(){  # $1=daemon-host  $2=ssh-target  [$3=ssh-port]
  local port_args=(); [ -n "${3:-}" ] && port_args=(-p "$3")
  echo "  → restarting daemon over SSH ($2${3:+:$3})…"
  ssh ${port_args[@]+"${port_args[@]}"} -o BatchMode=yes -o StrictHostKeyChecking=no \
      -o ConnectTimeout=8 "$2" \
      'sudo systemctl restart reachy-mini-daemon' 2>/dev/null \
    || { echo "  ✗ SSH restart failed"; return 1; }
  printf "  waiting for daemon"
  for _ in $(seq 1 24); do
    sleep 5; printf "."
    probe "$1" && { echo " up."; return 0; }
  done
  echo " not healthy after 2 min."; return 1
}

# ── Open local port-forward tunnels ──────────────────────────────────────
open_tunnel(){  # $1=ssh-target  [$2=ssh-port]
  local port_args=(); [ -n "${2:-}" ] && port_args=(-p "$2")
  local ctl; ctl="$(ssh_ctl "$1${2:+:$2}")"
  # kill any stale tunnel for this target
  pkill -f "ssh.*-L ${PORT}:127.0.0.1:${PORT}.*$1" 2>/dev/null || true
  ssh ${port_args[@]+"${port_args[@]}"} \
      -f -N -M \
      -S "${ctl}" \
      -o ControlPersist=600 \
      -o StrictHostKeyChecking=no \
      -o ConnectTimeout=10 \
      -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 \
      -L "${PORT}:127.0.0.1:${PORT}" \
      -L "${GRADIO_PORT}:127.0.0.1:${GRADIO_PORT}" \
      "$1"
}

# ═════════════════════════════════════════════════════════════════════════
# Forced modes (explicit flags)
# ═════════════════════════════════════════════════════════════════════════

if [ "${MODE}" = "--via-uplink" ]; then
  echo "Uplink path: tailnet → ${UPLINK_HOST}:${UPLINK_SSH_PORT} → Peachy…"
  if probe 127.0.0.1; then
    # Tunnel already active — just refresh creds and exit
    save_ok 127.0.0.1 "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
    echo "  (tunnel already active)"
    exit 0
  fi
  if ! ssh_probe "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"; then
    ssh_close "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
    echo "✗ SSH to Peachy via uplink failed."
    echo "  Check: ssh root@31.97.131.165 'ss -tln | grep ${UPLINK_SSH_PORT}'"
    exit 1
  fi
  echo "  SSH ok — opening local port forwards…"
  open_tunnel "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
  ssh_close "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
  sleep 2
  if probe 127.0.0.1; then
    save_ok 127.0.0.1 "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
    echo "  Gradio (after --gradio): http://127.0.0.1:${GRADIO_PORT}/"
    exit 0
  fi
  echo "✗ Daemon not answering after tunnel. Try: ./scripts/net-connect.sh --fix"
  exit 1
fi

if [ "${MODE}" = "--tunnel" ]; then
  echo "LAN tunnel via ${LAN_SSH}…"
  if probe 127.0.0.1; then
    save_ok 127.0.0.1 "${LAN_SSH}"
    echo "  (tunnel already active)"
    exit 0
  fi
  if ! ssh_probe "${LAN_SSH}"; then
    ssh_close "${LAN_SSH}"
    echo "✗ SSH to ${LAN_SSH} failed — same Wi-Fi as Peachy?"
    exit 1
  fi
  open_tunnel "${LAN_SSH}"
  ssh_close "${LAN_SSH}"
  sleep 2
  probe 127.0.0.1 && { save_ok 127.0.0.1 "${LAN_SSH}"; exit 0; }
  echo "✗ Tunnel opened but daemon not answering."; exit 1
fi

# ═════════════════════════════════════════════════════════════════════════
# Auto-connect (no args or --fix / --status)
# Strategy: already up → direct LAN → LAN tunnel → uplink tunnel
# ═════════════════════════════════════════════════════════════════════════
FIX="${MODE}"  # "--fix" or "--status" or ""

echo "Connecting to Peachy…"

# 1. Already tunneled?
if probe 127.0.0.1; then
  echo "  127.0.0.1  already connected ✓"
  # Ensure reachy.env SSH creds are intact (may have been wiped)
  if ! grep -q REACHY_SSH "${ENVFILE}" 2>/dev/null; then
    ssh_key="$(grep -E '^export REACHY_SSH=' "${ENVFILE}" 2>/dev/null | head -1 || true)"
    [ -z "${ssh_key}" ] && printf 'export REACHY_SSH=pollen@%s\n' "${UPLINK_HOST}" >> "${ENVFILE}"
  fi
  save_ok 127.0.0.1 \
    "$(grep -E '^export REACHY_SSH=' "${ENVFILE}" 2>/dev/null | cut -d= -f2- || echo "pollen@${UPLINK_HOST}")" \
    "$(grep -E '^export REACHY_SSH_PORT=' "${ENVFILE}" 2>/dev/null | cut -d= -f2- || true)"
  exit 0
fi

# 2. Direct LAN candidates (no tunnel needed)
LAN_CANDS=()
add_cand(){ [ -n "${1:-}" ] && LAN_CANDS+=("$1"); }
add_cand "${REACHY_HOST:-}"
[ -f "${LASTFILE}" ] && add_cand "$(cat "${LASTFILE}" 2>/dev/null)"
[ -f "${FQDNFILE}" ]  && add_cand "$(cat "${FQDNFILE}" 2>/dev/null)"
add_cand "reachy-mini.local"
add_cand "192.168.99.2"
add_cand "100.102.55.20"

BACKEND_DOWN_HOST=""
seen=" "
for h in "${LAN_CANDS[@]}"; do
  [ "${h}" = "127.0.0.1" ] && continue  # already checked
  case "${seen}" in *" ${h} "*) continue ;; esac
  seen="${seen}${h} "
  printf "  %-24s" "${h}"
  probe "${h}"; r=$?
  if [ $r -eq 0 ]; then
    echo "direct ✓"
    save_ok "${h}" "pollen@${h}"
    exit 0
  elif [ $r -eq 2 ]; then
    echo "daemon up, BACKEND DOWN"
    BACKEND_DOWN_HOST="${h}"
  else
    echo "no answer"
  fi
done

# Handle backend-down before trying tunnels
if [ -n "${BACKEND_DOWN_HOST}" ]; then
  echo
  echo "Daemon reachable at ${BACKEND_DOWN_HOST} but hardware backend is down."
  if [ "${FIX}" = "--fix" ]; then
    restart_daemon "${BACKEND_DOWN_HOST}" "pollen@${BACKEND_DOWN_HOST}" \
      && save_ok "${BACKEND_DOWN_HOST}" "pollen@${BACKEND_DOWN_HOST}" && exit 0
    exit 1
  fi
  echo "  Run:  ./scripts/net-connect.sh --fix"
  exit 2
fi

[ "${MODE}" = "--status" ] && echo "✗ Not reachable directly. Run without --status to try tunnels." && exit 1

# 3. LAN SSH tunnel
echo
echo "  Direct probe failed — trying LAN SSH tunnel (${LAN_SSH})…"
if ssh_probe "${LAN_SSH}"; then
  open_tunnel "${LAN_SSH}"
  ssh_close "${LAN_SSH}"
  sleep 2
  if probe 127.0.0.1; then
    save_ok 127.0.0.1 "${LAN_SSH}"
    exit 0
  fi
fi
ssh_close "${LAN_SSH}" 2>/dev/null || true

# 4. Uplink tunnel (VPS reverse tunnel, needs Tailscale)
echo "  LAN tunnel failed — trying uplink (${UPLINK_HOST}:${UPLINK_SSH_PORT})…"
if ! tailscale_ok; then
  echo "  ✗ Tailscale not running — start it for off-LAN access."
  echo
  echo "✗ Could not reach Peachy. Check it is powered on."
  exit 1
fi
if ssh_probe "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"; then
  open_tunnel "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
  ssh_close "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
  sleep 2
  if probe 127.0.0.1; then
    save_ok 127.0.0.1 "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}"
    echo "  Gradio (after --gradio): http://127.0.0.1:${GRADIO_PORT}/"
    exit 0
  fi
  echo "  ✗ Uplink SSH ok but daemon not answering."
  echo "    Try: ssh -p ${UPLINK_SSH_PORT} pollen@${UPLINK_HOST} 'sudo systemctl restart reachy-mini-daemon'"
else
  echo "  ✗ Uplink SSH failed — is Peachy powered on at school?"
  echo "    Check: ssh root@31.97.131.165 'ss -tln | grep ${UPLINK_SSH_PORT}'"
fi
ssh_close "pollen@${UPLINK_HOST}" "${UPLINK_SSH_PORT}" 2>/dev/null || true

echo
echo "✗ Could not connect via any path."
exit 1
