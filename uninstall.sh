#!/usr/bin/env bash
# uninstall.sh — take DDW back out of a repo.
#
#   bash uninstall.sh [/path/to/repo] [--plan] [--force] [--yes]
#
# Removes the method (.ddw/), the runtime (.ddw-state.json, .ddw-paused/,
# .ddw-sessions/, .ddw-work/), each installed tool's wiring, and the DDW block
# from the context files and .gitignore.
#
# It does NOT remove docs/. The PRDs, specs, threat models and verification
# reports are the record of what was decided and why; uninstalling the tool is
# not a reason to lose them.
#
# It does NOT remove files you have edited since installing, unless --force.
# What is DDW's is known from .ddw-installed.json, not guessed from directory
# names: `.claude/` is Claude Code's directory, and your own skills live there
# too.
#
#   --plan    print what would happen and change nothing
#   --yes     skip the confirmation
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR=""; PLAN=""; FORCE=""; YES=""

while [ $# -gt 0 ]; do
  case "$1" in
    --plan) PLAN="--plan"; shift ;;
    --force) FORCE="--force"; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) TARGET_DIR="$1"; shift ;;
  esac
done

TARGET="$(cd "${TARGET_DIR:-$PWD}" && pwd)"
[ "$TARGET" = "$SELF" ] && { echo "That is the DDW repo itself, not a repo DDW is installed into." >&2; exit 1; }

if [ ! -d "$TARGET/.ddw" ] && [ ! -f "$TARGET/.ddw-installed.json" ]; then
  echo "DDW does not appear to be installed in $TARGET (no .ddw/ and no manifest)."
  exit 0
fi

echo "DDW → uninstalling from: $TARGET"

# Show the plan first, always. This deletes files, and the one thing worse than
# an uninstaller is one that acts before you have read what it is about to do.
python3 "$SELF/scripts/uninstall_repo.py" --repo "$TARGET" --self "$SELF" --plan $FORCE

if [ -z "$PLAN" ]; then
  if [ -z "$YES" ]; then
    echo
    printf "Go ahead? [y/N]: "
    { read -r ANS < /dev/tty; } 2>/dev/null || ANS=""
    case "${ANS:-}" in
      y|Y|yes|YES) ;;
      *) echo "Nothing was changed."; exit 0 ;;
    esac
  fi
  HAD_COPILOT=""
  [ -d "$TARGET/.github/hooks/ddw" ] && HAD_COPILOT=1
  python3 "$SELF/scripts/uninstall_repo.py" --repo "$TARGET" --self "$SELF" $FORCE >/dev/null
  # Copilot's hooks are wired once per MACHINE, not per repo, because a
  # repo-level manifest is not read in `copilot -p`. So this uninstall does not
  # remove them: the same file is what gates every other repo here. It is inert
  # where DDW is gone — the wiring runs the repo's own hook only `if [ -f ]` —
  # but the user is the one who knows whether this was the last repo.
  [ -n "$HAD_COPILOT" ] && [ -f "$HOME/.copilot/hooks/ddw.json" ] && {
    echo
    echo "  Copilot's gates are wired at user level and were left in place:"
    echo "    ~/.copilot/hooks/ddw.json"
    echo "  They do nothing in a repo without DDW. If this was the last one,"
    echo "  remove that file."
  }
  echo
  echo "Done. To install again: bash $SELF/install.sh $TARGET"
fi
