#!/usr/bin/env bash
# Hook UserPromptSubmit — DDW.
#
# Counts the turns the user takes. Nothing else reads a human's presence: the
# commit gate holds a commit until this counter moves, which is what "assisted
# waits for the user" means once it has to be enforced rather than asked for.
#
# Prints nothing, ever: whatever a UserPromptSubmit hook writes to stdout is
# prepended to the user's own message.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/lib/guard.sh"
ddw_guard   # FIRST, for the reason spelled out in the other hooks.

DDW="$(ddw_method)" || exit 0

# Fails OPEN in every direction. This hook decides nothing; a turn that went
# uncounted costs one extra confirmation, and refusing the user's message would
# be an enormous failure to prevent a tiny one.
command -v python3 >/dev/null 2>&1 || exit 0
[ -f "$DDW/scripts/hook-gate.py" ] || exit 0

python3 "$DDW/scripts/hook-gate.py" --mode turn \
  --state "${CLAUDE_PROJECT_DIR}/.ddw-state.json" \
  --graph "$DDW/rules/transition-graph.json" \
  --repo "${CLAUDE_PROJECT_DIR}" >/dev/null 2>&1 || true
exit 0
