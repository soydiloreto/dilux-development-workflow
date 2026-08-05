#!/usr/bin/env bash
# DDW — cursor · before a write: refuse the ones that would break the FSM.
#
# A thin shim on purpose. Which transitions are legal, which gate is missing and
# what to say about it are the method's business and live in
# .ddw/scripts/hook-gate.py, shared by every tool. What belongs HERE is only
# what is true of this tool: where its repo root comes from, and which dialect
# its refusal has to be written in.
set -uo pipefail

REPO="$([ -n "${CURSOR_PROJECT_DIR:-}" ] && printf "%s" "$CURSOR_PROJECT_DIR" || git rev-parse --show-toplevel 2>/dev/null || pwd)"
# Repo first, plugin second — the order every adapter resolves in. A `.ddw/` in
# the project is the copy the user can read and edit, so it wins; under a plugin
# there is none, and a hook that looks only there allows every write it was
# installed to judge while the skills load and the pipeline looks installed.
PLUGIN_ROOT="${DDW_PLUGIN_ROOT:-${CURSOR_PLUGIN_ROOT:-}}"
DDW="$REPO/.ddw"
if [ ! -f "$DDW/scripts/hook-gate.py" ] && [ -n "$PLUGIN_ROOT" ] \
   && [ -f "$PLUGIN_ROOT/ddw/scripts/hook-gate.py" ]; then
  DDW="$PLUGIN_ROOT/ddw"
fi
GATE="$DDW/scripts/hook-gate.py"
STATE="$REPO/.ddw-state.json"
GRAPH="$DDW/rules/transition-graph.json"

# Not installed here → say nothing and allow. A hook is not the place to
# complain about a repo that never asked for DDW.
if [ ! -f "$GATE" ]; then exit 0; fi   # DDW is not installed here
command -v python3 >/dev/null 2>&1 || {
  echo "DDW cannot enforce anything without python3 on PATH. Refusing the write." >&2
  exit 2
}

exec python3 "$GATE" --dialect cursor --mode pre --state "$STATE" --graph "$GRAPH" --repo "$REPO" --method "$DDW"
