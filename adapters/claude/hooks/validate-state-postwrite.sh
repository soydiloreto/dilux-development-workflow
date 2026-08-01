#!/usr/bin/env bash
# Hook PostToolUse (Bash|Edit|Write|NotebookEdit) — DDW.
#
# Refuses a write to .ddw-state.json that is not a legal FSM transition. The
# decision — per-tier graph, mandatory gates, the append-only invariant — is the
# method's, and it is made once for every tool in .ddw/scripts/hook-gate.py.
# This wrapper only supplies what is true of Claude Code: where the project root
# comes from, and that a refusal is exit 2 with the reason on stderr.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/lib/guard.sh"
ddw_guard   # FIRST: under `set -u` the lines below would abort the hook before
            # the guard could bow out cleanly, and an aborted hook exits 1 —
            # which no harness reads as a refusal.

# The method lives in the repo (drop-in) or in the plugin. `ddw_method` decides,
# once, for all six hooks — this used to be inlined here and in one other place,
# and missing from four.
DDW="$(ddw_method)" || exit 0

# Without python3 there is nothing to validate with. Explicit fail-open (exit 0).
command -v python3 >/dev/null 2>&1 || {
  echo "DDW cannot enforce anything without python3 on PATH. Refusing the write." >&2
  exit 2
}
[ -f "$DDW/scripts/hook-gate.py" ] || exit 0

exec python3 "$DDW/scripts/hook-gate.py" --mode post \
  --state "${CLAUDE_PROJECT_DIR}/.ddw-state.json" \
  --graph "$DDW/rules/transition-graph.json" \
  --repo "${CLAUDE_PROJECT_DIR}"
