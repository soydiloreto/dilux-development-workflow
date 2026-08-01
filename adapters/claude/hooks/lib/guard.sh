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
ddw_method() {
  if [ -d "${CLAUDE_PROJECT_DIR:-}/.ddw" ]; then
    printf '%s' "${CLAUDE_PROJECT_DIR}/.ddw"
    return 0
  fi
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "${CLAUDE_PLUGIN_ROOT}/ddw" ]; then
    printf '%s' "${CLAUDE_PLUGIN_ROOT}/ddw"
    return 0
  fi
  return 1
}
