#!/usr/bin/env bash
# install.sh — install DDW (Dilux Development Workflow) into any repo.
#
#   bash install.sh [/path/to/repo] [--target <tool>|all]
#
# The same command installs and updates. On a repo that already has DDW it says
# so, defaults to refreshing the tools already wired there, and names any it is
# leaving behind.
#
# Tools are discovered from adapters/: claude, codex, copilot, cursor, gemini,
# opencode. Pass several with commas.
#
# Without --target it asks. Without a path it uses the current directory.
# Idempotent.
#
# It always installs the METHOD into `.ddw/` — identical for every tool — and
# then the WIRING for the target(s) you pick. Skills and agents have exactly one
# source (skills, agents); each adapter only declares where its tool
# looks for them and what frontmatter dialect it speaks.
#
# Supporting a new tool: create adapters/<id>/adapter.json (plus that tool's
# hook scripts). This script and the install engine stay untouched — the target
# list below is discovered from the adapters directory.
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR=""
TARGETS=""

# Every directory under adapters/ holding an adapter.json is a valid target.
AVAILABLE=()
for d in "$SELF"/adapters/*/; do
  [ -f "$d/adapter.json" ] && AVAILABLE+=("$(basename "$d")")
done
IFS=$'\n' AVAILABLE=($(printf '%s\n' "${AVAILABLE[@]:-}" | sed '/^$/d' | sort)); unset IFS
[ ${#AVAILABLE[@]} -gt 0 ] || { echo "No adapters found under $SELF/adapters." >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      [ $# -ge 2 ] || { echo "--target needs a value (a tool id, several comma-separated, or 'all')." >&2; exit 1; }
      TARGETS="$2"; shift 2 ;;
    --target=*) TARGETS="${1#*=}"; shift ;;
    # The method and nothing else. This is what `/ddw-eject` needs and could not
    # have: the skill told the model to copy the plugin's method into `.ddw/`,
    # and every write to `.ddw/` is refused in every phase — that seal is what
    # stops a pipeline editing the rules that stop it, and it does not know the
    # difference between disarming the method and installing it. So ejecting is
    # what installing and uninstalling already are: something the user runs,
    # outside the ticket, with the hooks looking on.
    --method-only) METHOD_ONLY=1; shift ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) TARGET_DIR="$1"; shift ;;
  esac
done

TARGET="$(cd "${TARGET_DIR:-$PWD}" && pwd)"
[ "$TARGET" = "$SELF" ] && { echo "The destination is the DDW repo itself; nothing to do." >&2; exit 1; }

label_of() {  # read the human label out of a recipe
  python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['label'])" \
    "$SELF/adapters/$1/adapter.json" 2>/dev/null || echo "$1"
}

# ── Is DDW already here, and for which tools? ────────────────────────────────
#
# The manifest keys are "<target>:<path>", so the repo already knows which tools
# were wired into it. Asking "which tool will you be working with?" on a repo
# that answered that question months ago is how a second install lands beside
# the first instead of refreshing it — and how one tool's wiring silently stays
# a version behind while the method in .ddw/ moves on.
INSTALLED="$(python3 - "$TARGET" <<'PY' 2>/dev/null || true
import json, os, sys
keys = None
for rel in (".ddw-installed.json", os.path.join(".ddw", ".installed.json")):
    try:
        keys = json.load(open(os.path.join(sys.argv[1], rel), encoding="utf-8")).keys()
        break
    except (OSError, ValueError, AttributeError):
        continue
if keys is None:
    sys.exit(0)
seen = sorted({k.split(":", 1)[0] for k in keys if ":" in k})
print(" ".join(seen))
PY
)"

# ── Pick target(s) ────────────────────────────────────────────────────────────
if [ -z "$TARGETS" ] && [ -n "$INSTALLED" ]; then
  echo "DDW is already installed in this repo, wired for: $INSTALLED"
  echo
  echo "  1) Update it — refresh those and leave everything of yours alone"
  echo "  2) Update it and add another tool"
  printf "Choice [1]: "
  { read -r OPT < /dev/tty; } 2>/dev/null || OPT=1
  case "${OPT:-1}" in
    1) TARGETS="$INSTALLED" ;;
    2)
      echo
      echo "Which tool do you want to add?"
      i=1
      for a in "${AVAILABLE[@]}"; do echo "  $i) $(label_of "$a")"; i=$((i+1)); done
      echo "  $i) All of them"
      printf "Choice [1]: "
      { read -r ADD < /dev/tty; } 2>/dev/null || ADD=1
      ADD="${ADD:-1}"
      if [ "$ADD" = "$i" ]; then
        TARGETS="all"
      elif [ "$ADD" -ge 1 ] 2>/dev/null && [ "$ADD" -lt "$i" ]; then
        TARGETS="$INSTALLED ${AVAILABLE[$((ADD-1))]}"
      else
        echo "Invalid choice." >&2; exit 1
      fi ;;
    *) echo "Invalid choice." >&2; exit 1 ;;
  esac
  echo
elif [ -z "$TARGETS" ]; then
  echo "Which tool will you be working with in this repo?"
  i=1
  for a in "${AVAILABLE[@]}"; do echo "  $i) $(label_of "$a")"; i=$((i+1)); done
  echo "  $i) All of them"
  printf "Choice [1]: "
  { read -r OPT < /dev/tty; } 2>/dev/null || OPT=1
  OPT="${OPT:-1}"
  if [ "$OPT" = "$i" ]; then
    TARGETS="all"
  elif [ "$OPT" -ge 1 ] 2>/dev/null && [ "$OPT" -lt "$i" ]; then
    TARGETS="${AVAILABLE[$((OPT-1))]}"
  else
    echo "Invalid choice." >&2; exit 1
  fi
fi
[ "$TARGETS" = "all" ] && TARGETS="${AVAILABLE[*]}"
TARGETS="${TARGETS//,/ }"
# "claude claude" wires the same tool twice and reports every one of its files
# as a collision with itself on the second pass.
TARGETS="$(printf '%s\n' $TARGETS | awk '!seen[$0]++' | tr '\n' ' ')"
TARGETS="${TARGETS% }"
for t in $TARGETS; do
  [ -f "$SELF/adapters/$t/adapter.json" ] || { echo "Unknown target: $t" >&2; exit 1; }
done

if [ -n "$INSTALLED" ]; then
  echo "DDW → updating: $TARGET"
else
  echo "DDW → installing into: $TARGET"
fi
echo "       target(s): $TARGETS"

# A tool that is wired into this repo and not in this run keeps the wiring it
# had. That is fine on purpose — but silently fine is how one tool ends up
# enforcing a version of the method that no longer matches the .ddw/ sitting
# next to it, with nothing on screen having suggested anything was out of step.
SKIPPED=""
for inst in $INSTALLED; do
  case " $TARGETS " in *" $inst "*) ;; *) SKIPPED="$SKIPPED $inst" ;; esac
done
[ -n "$SKIPPED" ] && {
  echo
  echo "  ⚠ Also installed here and NOT updated by this run:${SKIPPED}"
  echo "    Their wiring stays as it is while .ddw/ moves to this version."
  echo "    To bring them along: --target $(echo "$TARGETS$SKIPPED" | tr ' ' ',' | sed 's/^,//;s/,,*/,/g')"
}
echo

# ── 0. Can this land at all? ─────────────────────────────────────────────────
#
# Asked before a single byte is written, for every target at once. A path the
# install needs as a directory and finds occupied — `.claude` as a file — used to
# surface as a NotADirectoryError halfway through, with the method already copied
# and no wiring: a repo that looks installed and is not. A refusal that says
# "nothing has been written" has to be true when it says it, which means asking
# here rather than after step 1.
for t in $TARGETS; do
  python3 "$SELF/scripts/install_target.py" --self "$SELF" --target "$TARGET" --id "$t" --preflight || exit 1
done

# ── 1. THE METHOD (identical for every tool) ─────────────────────────────────
mkdir -p "$TARGET/.ddw"
# Skills and agents are the adapters' business, not the method payload's: they
# get transpiled into each tool's native location by the install engine.
rsync -a --exclude 'skills/' --exclude 'agents/' --exclude '__pycache__/' \
      "$SELF/ddw/" "$TARGET/.ddw/" 2>/dev/null || {
  cp -R "$SELF/ddw/." "$TARGET/.ddw/"
  rm -rf "$TARGET/.ddw/skills" "$TARGET/.ddw/agents"
  find "$TARGET/.ddw" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
}
echo "  ✓ .ddw/                  the method: orchestrator, rules, graph, scripts"

if [ -n "${METHOD_ONLY:-}" ]; then
  # Recorded, or the drift detector cannot see a shell rewriting what was just
  # ejected — and an ejected method is precisely the one people go on to edit.
  python3 "$SELF/scripts/install_target.py" --self "$SELF" --target "$TARGET" --method-only >/dev/null
  echo
  echo "The method is now in .ddw/ and this repo runs ITS copy: every hook resolves"
  echo "the repo first and the plugin second. The wiring stayed where it was."
  echo "Commit it — a method sitting uncommitted is taken by the next checkout."
  exit 0
fi

# ── 2. AGENTS.md: the PROJECT's context (the user fills it in) ───────────────
if [ -f "$TARGET/AGENTS.md" ]; then
  # "left alone" was a lie on four of the six adapters. Codex, Copilot, Cursor
  # and OpenCode use AGENTS.md as their context file, so the wiring step below
  # goes on to refresh the DDW block inside it — and the user read two lines,
  # one saying the file was untouched and the next saying it had been updated.
  # What is true on every adapter is narrower: the file is not replaced, and
  # nothing the user wrote in it is read or rewritten.
  echo "  ✓ AGENTS.md              already exists (your content kept as it is)"
  # The template is applied once, and only when there is no AGENTS.md — the
  # file is the user's. So a repo that already had one gets the activation
  # block appended and NOT a single one of the headings the method reads.
  # `## Stack` alone is read by CLASSIFY, CODE and seven skills; missing, every
  # one of those lookups finds nothing and says nothing. The closing line then
  # told the user to fill in a section that was not there.
  MISSING=""
  for h in "## Stack" "## Architecture conventions" "## Domain glossary"; do
    grep -qF "$h" "$TARGET/AGENTS.md" || MISSING="$MISSING|$h"
  done
  [ -n "$MISSING" ] && {
    echo "  ⚠ AGENTS.md              is missing headings the method reads:"
    echo "${MISSING#|}" | tr '|' '\n' | sed 's/^/                             /'
    echo "                             Add them (empty is fine) or run /ddw-context-check,"
    echo "                             which reports them with what reads each one."
  }
else
  cp "$SELF/ddw/AGENTS.template.md" "$TARGET/AGENTS.md"
  echo "  ✓ AGENTS.md              created from the template — FILL IT IN before working"
fi

# ── 3. THE WIRING, per target, driven by each adapter's recipe ───────────────
COLLISIONS=""
for t in $TARGETS; do
  echo
  OUT="$(python3 "$SELF/scripts/install_target.py" --self "$SELF" --target "$TARGET" --id "$t")"
  echo "$OUT" | grep -v '^COLLISIONS:' || true
  C="$(echo "$OUT" | sed -n 's/^COLLISIONS://p')"
  [ -n "$C" ] && COLLISIONS="$COLLISIONS,$C"
done

# ── 4. .gitignore ─────────────────────────────────────────────────────────────
echo
GITIGNORE="$TARGET/.gitignore"
if [ -f "$GITIGNORE" ] && grep -qF "# BEGIN DDW" "$GITIGNORE"; then
  echo "  ✓ .gitignore             already has the DDW block"
else
  { [ -s "$GITIGNORE" ] && printf '\n'
    printf '%s\n' \
      '# BEGIN DDW — pipeline runtime, NOT committed (managed by DDW)' \
      '#   .ddw-state.json  = which phase you are in; yours, not the repo'"'"'s' \
      '#   .ddw-paused/     = paused tickets' \
      '#   .ddw-sessions/   = live session markers' \
      '#   .ddw-journal.jsonl = transitions that landed; outlives the state file' \
      '#   .ddw/**/__pycache__/ = bytecode from running the method'"'"'s own scripts' \
      '.ddw-state.json' \
      '.ddw-paused/' \
      '.ddw-sessions/' \
      '.ddw-journal.jsonl' \
      '.ddw/**/__pycache__/' \
      '# END DDW'
  } >> "$GITIGNORE"
  echo "  ✓ .gitignore             DDW block added (the state is never committed)"
fi

if [ -n "$COLLISIONS" ]; then
  echo
  echo "  ⚠ These already existed in the repo, so they were left alone (they are yours):"
  echo "${COLLISIONS#,}" | tr ',' '\n' | sed '/^$/d' | sort -u | sed 's/^/      /'
  echo "    DDW ships its own version of those names. If you want DDW's,"
  echo "    rename yours and re-run the installer: it is idempotent."
fi

echo
echo "Done. Fill in the \"Stack\" section of AGENTS.md and open your agent in $TARGET."
# How to invoke DDW is printed per target above, by the adapter that knows: not
# every tool exposes skills as /name, and this line used to promise /ddw-status
# to all six.
echo "The pipeline starts on its own. See the \"try:\" line above for how to call it."
