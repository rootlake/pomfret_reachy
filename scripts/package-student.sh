#!/usr/bin/env bash
# Bundle a clean student handoff zip (no secrets, no venv).
#
#   ./scripts/package-student.sh
#   ./scripts/package-student.sh ../peachy-student.zip
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-${ROOT}/../peachy-student.zip}"
NAME="$(basename "$OUT" .zip)"

echo "Packaging ${NAME}.zip from ${ROOT}…"

cd "$(dirname "$ROOT")"
zip -r "$OUT" "$(basename "$ROOT")" \
  -x "$(basename "$ROOT")/.run/*" \
     "$(basename "$ROOT")/reachy_mini_env/*" \
     "$(basename "$ROOT")/.claude/*" \
     "$(basename "$ROOT")/.git/*" \
     "$(basename "$ROOT")/**/__pycache__/*" \
     "$(basename "$ROOT")/**/*.pyc" \
     "$(basename "$ROOT")/reachSSH-ifconfig.txt" \
     "$(basename "$ROOT")/agents.local.md" \
     "$(basename "$ROOT")/.DS_Store"

echo ""
echo "✓ Wrote $(realpath "$OUT")"
echo ""
echo "Includes:"
echo "  • dashboard/ + scripts/ + sounds/portalturret/"
echo "  • STUDENT-RUNBOOK.md, STUDENT-PROJECT.md, HANDOFF.md, CLAUDE.md, TOOLKIT.md"
echo "  • requirements-student.txt"
echo ""
echo "NOT included (by design): .run/ tokens, reachy_mini_env/, .git/"
echo ""
echo "Student first run:"
echo "  git clone https://github.com/rootlake/pomfret_reachy.git && cd pomfret_reachy"
echo "  python3 -m venv reachy_mini_env && source reachy_mini_env/bin/activate"
echo "  pip install -r requirements-student.txt"
echo "  open README.md"
