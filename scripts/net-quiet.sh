#!/usr/bin/env bash
# Definitive "is Peachy messing with the room Wi-Fi?" toggle.
#
#   ./scripts/net-quiet.sh quiet   # stop all our services + drop wlan0 (Peachy
#                                  # goes silent on Wi-Fi — wait 60–120s, ask
#                                  # students if Wi-Fi recovered)
#   ./scripts/net-quiet.sh loud    # reverse — bring wlan0 up + start services
#   ./scripts/net-quiet.sh watch   # 15s traffic snapshot (bytes in/out on wlan0)
#   ./scripts/net-quiet.sh status  # current services + interface (read-only)
#
# YOU MUST BE WIRED to Peachy (eth1 / 192.168.99.2) before `quiet` — taking
# wlan0 down kills any Wi-Fi-based SSH path. Wired SSH session continues fine.
set -u
REACHY_SSH="${REACHY_SSH:-pollen@reachy-mini.local}"
CMD="${1:-status}"

run_ssh_t() { ssh -t -o ConnectTimeout=8 "${REACHY_SSH}" "$@"; }
run_ssh()   { ssh    -o ConnectTimeout=8 "${REACHY_SSH}" "$@"; }

case "$CMD" in

  status)
    run_ssh '
      echo "=== services ==="
      systemctl is-active reachy-mini-daemon peachy-dashboard peachy-uplink \
        2>/dev/null | paste -d" " - - - | xargs -I{} echo "  daemon/dashboard/uplink: {}"
      echo "=== wlan0 ==="
      ip -br addr show wlan0 2>/dev/null
      echo "=== AP mode? (should be inactive) ==="
      systemctl is-active hostapd 2>/dev/null || echo "  inactive"
      echo "=== outbound TCP connections ==="
      ss -tn state established 2>/dev/null | tail -n +2 | wc -l
    '
    ;;

  watch)
    echo "Sampling wlan0 traffic for 15s on the robot…"
    run_ssh '
      read _ _ rx0 _ _ _ _ _ _ tx0 _ < <(grep -E "^\s*wlan0:" /proc/net/dev | tr ":" " ")
      sleep 15
      read _ _ rx1 _ _ _ _ _ _ tx1 _ < <(grep -E "^\s*wlan0:" /proc/net/dev | tr ":" " ")
      drx=$((rx1-rx0)); dtx=$((tx1-tx0))
      printf "  RX %d bytes in 15s (%.1f KB/s)\n" "$drx" "$(echo "$drx/15/1024" | bc -l)"
      printf "  TX %d bytes in 15s (%.1f KB/s)\n" "$dtx" "$(echo "$dtx/15/1024" | bc -l)"
      echo "  (a quiet idle robot: under ~5 KB/s combined.  Bursts during"
      echo "   conversation/LLM calls are higher but transient.)"
    '
    ;;

  quiet)
    echo "── QUIETING Peachy (stopping services + dropping wlan0) ──"
    echo "Make sure you are WIRED to the robot — Wi-Fi SSH will die."
    read -p "Continue? [y/N] " a; [[ "$a" =~ ^[Yy]$ ]] || { echo skipped; exit 0; }
    run_ssh_t '
      set +e
      ~/peachy/scripts/app-conversation.sh stop 2>/dev/null
      sudo systemctl stop peachy-uplink peachy-dashboard reachy-mini-daemon
      if command -v nmcli >/dev/null; then sudo nmcli radio wifi off
      else sudo ip link set wlan0 down; fi
      echo "✓ all services stopped + wlan0 down"
      ip -br addr show wlan0 2>/dev/null
    '
    echo
    echo "Now wait 1–2 min and ask students if Wi-Fi recovered."
    echo "  Wi-Fi recovers  → Peachy was contributing.  Run \`loud\` then we'll diagnose which service."
    echo "  No change       → not Peachy.  Look at the room AP / channel / a flooding student device."
    ;;

  loud)
    echo "── RESTORING Peachy (wlan0 up + services on) ──"
    run_ssh_t '
      set +e
      if command -v nmcli >/dev/null; then sudo nmcli radio wifi on
      else sudo ip link set wlan0 up; fi
      sleep 4
      sudo systemctl start reachy-mini-daemon
      sleep 5
      sudo systemctl start peachy-dashboard peachy-uplink
      echo "✓ wlan0 up + services started"
      ip -br addr show wlan0 2>/dev/null
      systemctl is-active reachy-mini-daemon peachy-dashboard peachy-uplink \
        2>/dev/null | paste -d" " - - - | xargs -I{} echo "  daemon/dashboard/uplink: {}"
    '
    echo "(Conversation app NOT auto-started; use ./peachy option 11 if desired.)"
    ;;

  *)
    echo "usage: $0 {quiet|loud|watch|status}" >&2; exit 2 ;;
esac
