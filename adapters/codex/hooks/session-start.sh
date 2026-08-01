#!/usr/bin/env bash
# DDW — codex · session start: materialize the state and boot the pipeline.
set -uo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# Repo first, plugin second — the order every adapter resolves in. A `.ddw/` in
# the project is the copy the user can read and edit, so it wins; under a plugin
# there is none, and a hook that looks only there allows every write it was
# installed to judge while the skills load and the pipeline looks installed.
PLUGIN_ROOT="${DDW_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-}}"
DDW="$REPO/.ddw"
if [ ! -d "$DDW" ] && [ -n "$PLUGIN_ROOT" ] && [ -d "$PLUGIN_ROOT/ddw" ]; then
  DDW="$PLUGIN_ROOT/ddw"
fi
BOOT="$DDW/scripts/session-boot.py"
[ -f "$BOOT" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

IN="$(cat 2>/dev/null || true)"
SID="$(printf '%s' "$IN" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('session_id') or '')
except Exception: print('')" 2>/dev/null || true)"
[ -n "$SID" ] || SID="codex-$$"

exec python3 "$BOOT" --repo "$REPO" --session-id "$SID" --format text --method "$DDW"
