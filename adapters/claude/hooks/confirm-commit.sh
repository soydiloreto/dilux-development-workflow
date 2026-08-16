#!/usr/bin/env bash
# Hook PreToolUse (Bash) — DDW.
#
# Hands a `git commit` to the user for approval while autonomy is `assisted`.
# `ddw-commit` has always said "present the message for approval; only after
# approval create the commit", and `assisted` says every step waits — but the
# pre matcher only ever covered Edit|Write|NotebookEdit, so a commit is the one
# act in the pipeline that nothing enforced. It ran, and the user read the hash
# afterwards. The decision is the method's and is made once for every tool in
# .ddw/scripts/hook-gate.py; this wrapper only supplies what is true of Claude
# Code: where the project root comes from.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/lib/guard.sh"
ddw_guard   # FIRST, for the reason spelled out in the other hooks.

DDW="$(ddw_method)" || exit 0

# Fails OPEN, unlike the state gate: what is missing here is a confirmation
# prompt, not a verdict on a write. Refusing every shell command in the repo
# because python3 is absent would be a far larger failure than the one it
# prevents, and the state gate already fails closed over the bytes that matter.
command -v python3 >/dev/null 2>&1 || exit 0
[ -f "$DDW/scripts/hook-gate.py" ] || exit 0

exec python3 "$DDW/scripts/hook-gate.py" --mode commit \
  --state "${CLAUDE_PROJECT_DIR}/.ddw-state.json" \
  --graph "$DDW/rules/transition-graph.json" \
  --repo "${CLAUDE_PROJECT_DIR}"
