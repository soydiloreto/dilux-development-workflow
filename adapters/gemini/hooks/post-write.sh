#!/usr/bin/env bash
# DDW — gemini · after a write: revalidate the state on disk.
#
# The net under the net. The pre-write hook only sees the tools its matcher
# names; this one re-reads the file however it got there, which is what catches
# a state edited with sed or jq.
set -uo pipefail

REPO="$([ -n "${GEMINI_PROJECT_DIR:-}" ] && printf "%s" "$GEMINI_PROJECT_DIR" || git rev-parse --show-toplevel 2>/dev/null || pwd)"
# Repo first, plugin second — the order every adapter resolves in. A `.ddw/` in
# the project is the copy the user can read and edit, so it wins; under a plugin
# there is none, and a hook that looks only there allows every write it was
# installed to judge while the skills load and the pipeline looks installed.
PLUGIN_ROOT="${DDW_PLUGIN_ROOT:-}"
DDW="$REPO/.ddw"
if [ ! -f "$DDW/scripts/hook-gate.py" ] && [ -n "$PLUGIN_ROOT" ] \
   && [ -f "$PLUGIN_ROOT/ddw/scripts/hook-gate.py" ]; then
  DDW="$PLUGIN_ROOT/ddw"
fi
GATE="$DDW/scripts/hook-gate.py"
STATE="$REPO/.ddw-state.json"
GRAPH="$DDW/rules/transition-graph.json"

cat > /dev/null   # drain the event; post mode reads the disk, not stdin

if [ ! -f "$GATE" ]; then exit 0; fi   # DDW is not installed here
command -v python3 >/dev/null 2>&1 || {
  echo "DDW cannot enforce anything without python3 on PATH. Refusing the write." >&2
  exit 2
}

exec python3 "$GATE" --dialect gemini --mode post --state "$STATE" --graph "$GRAPH" --repo "$REPO"
