#!/usr/bin/env bash
# Hook: PreToolUse (Edit|Write|NotebookEdit) — DDW drop-in.
#
# Housekeeping before every write: make sure the state file exists, keep the
# runtime out of git, and refresh this session's marker so the concurrency guard
# knows we are still here. All of it is the method's business, so all of it
# lives in .ddw/scripts/session-boot.py and every tool gets the same behaviour.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/lib/guard.sh"
ddw_guard

DDW="$(ddw_method)" || exit 0        # neither the repo nor a plugin has the method
BOOT="$DDW/scripts/session-boot.py"
[ -f "$BOOT" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

# The session id, from the event the tool is already handing us — the same field
# the session-start hook reads. `pid-$$` was this hook's own shell, a new one on
# every single write: the marker was never refreshed, it was re-created under
# another name, and after a dozen edits the next session-start warned about a
# dozen people working in a directory holding one. No id, no marker: the boot
# leaves the identity unclaimed rather than inventing one.
SID="$(cat 2>/dev/null | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('session_id') or '')
except Exception: print('')" 2>/dev/null || true)"

# --quiet: this runs on EVERY write. It does the housekeeping and says nothing —
# a hook that narrates on each edit trains you to stop reading it.
python3 "$BOOT" --repo "$CLAUDE_PROJECT_DIR" --session-id "$SID" --quiet || true

exit 0
