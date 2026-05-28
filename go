#!/usr/bin/env bash
# Morning startup — connect, verify Peachy, launch your browser control panel.
#
#   ./go                 # connect + dashboard URLs (reuse if already running)
#   ./go --wake            # also wake Peachy
#   ./go --restart         # restart dashboard
#   ./go --status          # connect + status only (no dashboard)
#   ./go --lan             # LAN probe (classroom Wi‑Fi) instead of uplink
#   ./go --open            # open dashboard + desk in default browser
#
# Your control surface is the browser dashboard (phone + desk panel) — scripts
# stay the single source of truth; the web UI just calls them.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
RUN="${ROOT}/.run"
mkdir -p "${RUN}"

WAKE=0
RESTART=0
STATUS_ONLY=0
OPEN=0
MODE="auto"

for arg in "$@"; do
  case "$arg" in
    --wake)     WAKE=1 ;;
    --restart)  RESTART=1 ;;
    --status)   STATUS_ONLY=1 ;;
    --open)     OPEN=1 ;;
    --lan)      MODE="lan" ;;
    --uplink)   MODE="uplink" ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown flag: $arg (try --help)" >&2; exit 2 ;;
  esac
done

if [ -z "${VIRTUAL_ENV:-}" ] && [ -f reachy_mini_env/bin/activate ]; then
  # shellcheck source=/dev/null
  source reachy_mini_env/bin/activate
fi

connect() {
  case "${MODE}" in
    lan)
      echo "── Connect (LAN tunnel) ──"
      ./scripts/net-connect.sh --tunnel
      ;;
    uplink)
      echo "── Connect (uplink) ──"
      ./scripts/net-connect.sh --via-uplink
      ;;
    auto)
      echo "── Connect ──"
      ./scripts/net-connect.sh
      ;;
  esac
}

print_robot_summary() {
  echo
  echo "── Robot ──"
  REACHY_QUIET=1 python scripts/ctl-toggle.py status 2>/dev/null | sed 's/^/  /'
}

start_dashboard() {
  echo
  echo "── Dashboard ──"
  local port="${PEACHY_PORT:-8080}"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null | grep -q 'dashboard/server'; then
    if [ "${RESTART}" = "1" ]; then
      ./run.sh --restart &
      sleep 2
    fi
  else
    nohup ./run.sh >>"${RUN}/go.log" 2>&1 &
    sleep 2
  fi
  ./run.sh
}

open_browser() {
  local tok port ip
  tok="$(cat "${RUN}/peachy_token" 2>/dev/null || true)"
  port="$(cat "${RUN}/peachy_dashboard.port" 2>/dev/null || echo 8080)"
  ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo localhost)"
  [ -n "${tok}" ] || { echo "  (no token — dashboard not started?)"; return 0; }
  command -v open >/dev/null 2>&1 || return 0
  open "http://localhost:${port}/desk?k=${tok}"
  open "http://localhost:${port}/?k=${tok}"
}

echo "Peachy — all systems go"
connect
print_robot_summary

if [ "${WAKE}" = "1" ]; then
  echo
  echo "── Wake ──"
  python scripts/ctl-toggle.py wake
fi

if [ "${STATUS_ONLY}" = "1" ]; then
  echo
  echo "── Dashboard ──"
  python scripts/tool-print-links.py --no-meta 2>/dev/null || echo "  (run ./run.sh to start dashboard)"
  exit 0
fi

start_dashboard

if [ "${OPEN}" = "1" ]; then
  echo
  echo "── Opening browser ──"
  open_browser
fi

echo
echo "Next steps from the dashboard:"
echo "  • Wake / Sleep / expressions"
echo "  • Start conversation (or Start + Gradio for desk panel voice/idle slider)"
echo "  • Room watch lives in scripts — not auto-started (by design)"
