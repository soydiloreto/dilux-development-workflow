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

# --quiet: this runs on EVERY write. It does the housekeeping and says nothing —
# a hook that narrates on each edit trains you to stop reading it.
python3 "$BOOT" --repo "$CLAUDE_PROJECT_DIR" --session-id "${CLAUDE_SESSION_ID:-pid-$$}" --quiet || true

exit 0
