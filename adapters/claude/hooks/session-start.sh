#!/usr/bin/env bash
# Hook: SessionStart — DDW drop-in.
#
# Drop-in: the orchestrator arrives through the `@.ddw/orchestrator.md` import in
# the repo's context file, and this hook is defence in depth — it nudges the
# model to RUN the boot sequence and covers the headless case.
#
# Installed as a plugin there is no import to write, so this hook is not defence
# in depth: **it is the only channel**. Its stdout is the one thing that puts the
# orchestrator in front of the model, which is why it now passes the resolved
# method root rather than assuming `.ddw/`. A SessionStart's stdout enters the
# context through the harness (system-reminder), bypassing no gate.
#
# What to say, and the concurrent-session check behind it, is the method's
# business and lives in .ddw/scripts/session-boot.py — shared by every tool, so
# the two-hour marker cutoff exists once instead of once per adapter.
set -euo pipefail

STDIN_JSON="$(cat 2>/dev/null || true)"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/lib/guard.sh"

[ -n "${CLAUDE_PROJECT_DIR:-}" ] || exit 0
DDW="$(ddw_method)" || exit 0        # neither the repo nor a plugin has the method
BOOT="$DDW/scripts/session-boot.py"
[ -f "$BOOT" ] || exit 0

SID="$(printf '%s' "${STDIN_JSON:-}" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get('session_id') or '')
except Exception: print('')" 2>/dev/null || true)"
[ -n "$SID" ] || SID="pid-$$"

# --method: where the orchestrator actually is. In the drop-in case it is
# `.ddw/` inside the repo and the nudge can say so; installed as a plugin the
# method is somewhere under the plugin root, and a nudge pointing at a relative
# `.ddw/orchestrator.md` names a file that is not there.
exec python3 "$BOOT" --repo "$CLAUDE_PROJECT_DIR" --session-id "$SID" --method "$DDW"
