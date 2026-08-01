#!/usr/bin/env bash
# Hook: PreCompact — DDW.
#
# After a compaction, reminds the agent to re-run the orchestrator's boot
# sequence (re-read state + the phase instructions). Plain stdout, NOT JSON
# (the runtime rejects hookSpecificOutput for PreCompact).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/lib/guard.sh"
DDW="$(ddw_method)" || exit 0

# Plain stdout, NOT JSON: the runtime rejects hookSpecificOutput for PreCompact.
#
# The wording used to live here, in a heredoc, and every other tool compacts
# too — six copies of one paragraph, five of which nobody would remember to
# edit. It is the method's message now; what stays here is the event name and
# the envelope, which is all that was ever Claude's.
command -v python3 >/dev/null 2>&1 || exit 0
exec python3 "$DDW/scripts/session-boot.py" --repo "$CLAUDE_PROJECT_DIR" \
  --method "$DDW" --compact --format text --event PreCompact
