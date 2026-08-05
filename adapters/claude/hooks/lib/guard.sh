#!/usr/bin/env bash
# Shared preamble for the DDW hooks. Source this file, then call `ddw_guard`
# and `ddw_method` — in that order.
#
# `ddw_guard` exits 0 (silently) when CLAUDE_PROJECT_DIR is unset or the
# directory is not a git repo, so the hooks stay out of the way outside a git
# project.
ddw_guard() {
  [ -n "${CLAUDE_PROJECT_DIR:-}" ] || exit 0
  git -C "$CLAUDE_PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
}

# Where the method lives, printed on stdout. **The repo wins**: a `.ddw/` in the
# project is either a drop-in install or a deliberate customisation of the
# plugin's default, and either way it is the copy the user can read and edit.
# The plugin is the fallback.
#
# This exists once because it was written twice and omitted four times. Two of
# the six hooks resolved both locations; the other four looked only in the repo
# — including session-start, the one that boots the pipeline. Installed as a
# plugin, DDW loaded its skills and its agents and enforced **nothing**: a
# pipeline that looks installed and does not hold, which is the exact failure
# `scripts/acceptance.md` opens by naming. Meanwhile `docs/DEVELOPMENT.md` said
# all six handled both.
#
# Returns non-zero when neither location has the method, so a caller can bow out
# rather than build paths under an empty prefix.
# Chosen by the GATE being there, not by the directory being there. Picking it
# by directory made `mkdir .ddw` — one command, no privileges, no content —
# resolve the method to an empty folder; every hook then hit its
# `[ -f "$DDW/scripts/hook-gate.py" ] || exit 0` and bowed out, two lines below
# a python3 branch that deliberately fails CLOSED. Measured: a write refused
# with exit 2 was allowed with exit 0 after that one command, on both the pre
# and post hooks. Under a plugin install the fallback it skipped is the only
# copy there is, so an empty directory disabled enforcement for the repo.
#
# The comment above is the reason this shape was reachable at all: a repo `.ddw`
# is treated as a deliberate customisation, so the input that disarms DDW is the
# input the design invites. `adapters/codex/hooks/pre-tool-use.sh` already asked
# the question this way.
ddw_method() {
  if [ -f "${CLAUDE_PROJECT_DIR:-}/.ddw/scripts/hook-gate.py" ]; then
    printf '%s' "${CLAUDE_PROJECT_DIR}/.ddw"
    return 0
  fi
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "${CLAUDE_PLUGIN_ROOT}/ddw" ]; then
    printf '%s' "${CLAUDE_PLUGIN_ROOT}/ddw"
    return 0
  fi
  return 1
}
