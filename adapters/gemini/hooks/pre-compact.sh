#!/usr/bin/env bash
# DDW — gemini · PreCompress: the pipeline survives the summary.
#
# Compaction drops the middle of the conversation, and what it drops is the
# phase router and the state read at boot. The model keeps answering, now from a
# summary of the pipeline instead of the pipeline — the one thing the
# orchestrator forbids inferring. The wording is the method's; this names the
# event and the envelope, which is all that is this tool's.
set -uo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${DDW_PLUGIN_ROOT:-}"
DDW="$REPO/.ddw"
if [ ! -d "$DDW" ] && [ -n "$PLUGIN_ROOT" ] && [ -d "$PLUGIN_ROOT/ddw" ]; then
  DDW="$PLUGIN_ROOT/ddw"
fi
BOOT="$DDW/scripts/session-boot.py"
[ -f "$BOOT" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

cat > /dev/null   # drain the event; this reads the disk, not stdin

exec python3 "$BOOT" --repo "$REPO" --method "$DDW" --compact \
  --format nested --event PreCompress
