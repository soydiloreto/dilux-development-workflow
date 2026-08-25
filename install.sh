#!/usr/bin/env bash
# install.sh — install DDW (Dilux Development Workflow) into any repo.
#
#   bash install.sh [/path/to/repo] [--target <tool>|all] [--mode plugin|dropin]
#
# Two ways in. `--mode plugin` hands the job to each tool's own plugin CLI and
# wires what a manifest cannot carry (Copilot's gates are user-level hooks);
# it covers Claude Code, Copilot CLI and OpenCode. `--mode dropin` copies the
# method into the repo and works for all six tools. Without --mode it always
# asks — naming a tool does not answer this — and falls to drop-in only where
# there is no terminal to ask on, saying so when it does.
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

# ── Pasted from a URL, with no repository around it ───────────────────────────
#
# The installer is not self-sufficient: it copies `ddw/`, `adapters/`,
# `scripts/` and the manifest from its own tree. A line pasted into a terminal
# has none of the four — and until today it did not even get to say so: under
# `bash -s` the variable `BASH_SOURCE[0]` does not exist, and with `set -u`
# that is an "unbound variable" on the next line, without a word about what
# happened.
#
# So if it cannot find itself, it fetches the tree and re-runs from there. It
# is the rustup and nvm pattern, for the same reason: the line someone pastes
# has to BE the installer, not a step before the installer. The plugin path
# was already one line and the drop-in demanded cloning first, which is the
# only door three of the six tools have.
#
# `DDW_REF` chooses what gets fetched. `main` by default, and that is a debt
# said out loud: `release.yml` cuts releases with `v*` tags and none has been
# cut yet, so today there is no version to point at.
SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" && pwd)"
DDW_REF="${DDW_REF:-main}"
if ! { [ -f "$SELF/.claude-plugin/plugin.json" ] && [ -d "$SELF/ddw" ] && [ -d "$SELF/adapters" ]; }; then
  # Once. If the tree it fetched does not have them either, the problem is
  # not fixed by fetching it again, and a bootstrap that calls itself is a
  # bottomless recursion — the shape this repository has already paid for once.
  if [ -n "${DDW_BOOTSTRAPPED:-}" ]; then
    echo "install.sh: what was downloaded from '$DDW_REF' does not carry the method (ddw/, adapters/)." >&2
    echo "  Check that the ref exists, or clone the repository and run install.sh from there." >&2
    exit 1
  fi
  FETCH=""
  if command -v curl >/dev/null 2>&1; then FETCH="curl -fsSL"
  elif command -v wget >/dev/null 2>&1; then FETCH="wget -qO-"
  else
    echo "install.sh: fetching the method needs curl or wget, and neither is present." >&2
    exit 1
  fi
  command -v tar >/dev/null 2>&1 || {
    echo "install.sh: unpacking the method needs tar, and it is not present." >&2; exit 1; }
  DDW_TARBALL="${DDW_TARBALL:-https://codeload.github.com/soydiloreto/dilux-development-workflow/tar.gz/$DDW_REF}"
  DDW_BOOT_DIR="$(mktemp -d)"
  trap 'rm -rf "$DDW_BOOT_DIR"' EXIT
  echo "  Fetching DDW ($DDW_REF)…"
  $FETCH "$DDW_TARBALL" | tar xz -C "$DDW_BOOT_DIR" || {
    echo "install.sh: could not fetch $DDW_TARBALL" >&2; exit 1; }
  DDW_REAL="$(find "$DDW_BOOT_DIR" -maxdepth 2 -name install.sh -type f | head -1)"
  [ -n "$DDW_REAL" ] || {
    echo "install.sh: the downloaded tree does not carry an install.sh." >&2; exit 1; }
  DDW_BOOT_RC=0
  DDW_BOOTSTRAPPED=1 bash "$DDW_REAL" "$@" || DDW_BOOT_RC=$?
  exit $DDW_BOOT_RC
fi

# Is there a terminal to ask? The answer is NOT stdin.
#
# All eight reads in this file read from `/dev/tty`, and that is right: under
# `curl | bash` stdin is the script. But the three decisions about WHETHER to
# ask looked at `[ -t 0 ]`, which is stdin — so with the installer arriving
# through a pipe, terminal right there beside it, it went non-interactive in
# silence: it chose drop-in without saying so and skipped the whole question
# of where the install lands. It asks on the same channel it reads from.
have_tty() { { : < /dev/tty; } 2>/dev/null; }
TARGET_DIR=""
TARGETS=""
MODE=""

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
    # plugin | dropin. Absent and non-interactive means dropin, which is what
    # every caller of this script has always got.
    --mode)
      [ $# -ge 2 ] || { echo "--mode needs a value: plugin or dropin." >&2; exit 1; }
      MODE="$2"; shift 2 ;;
    --mode=*) MODE="${1#*=}"; shift ;;
    --plugin) MODE="plugin"; shift ;;
    --dropin) MODE="dropin"; shift ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) TARGET_DIR="$1"; shift ;;
  esac
done

TARGET="$(cd "${TARGET_DIR:-$PWD}" && pwd)"
[ "$TARGET" = "$SELF" ] && { echo "The destination is the DDW repo itself; nothing to do." >&2; exit 1; }

# Which of the files this installer EDITS (rather than creates) were already
# dirty before it ran. Captured now, because at offer time — after the write —
# "dirty" no longer distinguishes the user's own uncommitted work from the
# block the installer appended, and staging a file that mixes both would sweep
# somebody's half-written notes into an installation commit.
# `|| true` is load-bearing: this file runs under `set -euo pipefail`, and on a
# target that is not a git repository this pipeline exits 128 — which killed
# the WHOLE installer, silently, before it had printed one line. Measured.
PREDIRTY="$(git -C "$TARGET" status --porcelain -- AGENTS.md CLAUDE.md GEMINI.md .gitignore .claude/settings.json opencode.json 2>/dev/null | awk '{print $2}' || true)"

# ── The banner ────────────────────────────────────────────────────────────────
#
# Someone running this has usually been sent a one-line command and has no idea
# what is about to be written into their repository. The installer used to open
# with "Which tool will you be working with?", which asks them to decide
# something before telling them what it is for. So: what DDW is, and what this
# is about to do, before it does any of it.
RULE="────────────────────────────────────────────────────────────────────────"
VERSION="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" \
  "$SELF/.claude-plugin/plugin.json" 2>/dev/null || echo "")"

# What we are running on. It is printed because half of what can go wrong here
# is environmental — a CLI that is not on PATH, a Windows shell that is not the
# one the tool installed itself into — and a user who can see what was detected
# can tell in one glance whether the installer is looking at the same machine
# they think they are on.
case "$(uname -s)" in
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then
      OS_NAME="WSL2 · $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo Linux)"
    else
      OS_NAME="$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo Linux)"
    fi ;;
  Darwin)  OS_NAME="macOS $(sw_vers -productVersion 2>/dev/null || true)" ;;
  MINGW*|MSYS*|CYGWIN*) OS_NAME="Windows · $(uname -o 2>/dev/null || echo "POSIX shell")" ;;
  *)       OS_NAME="$(uname -s)" ;;
esac

echo
echo "$RULE"
if [ -n "$VERSION" ]; then
  echo "  Dilux Development Workflow (DDW)  ·  v$VERSION"
else
  echo "  Dilux Development Workflow (DDW)"
fi
echo "$RULE"
cat <<'ABOUT'

  A pipeline your coding agent has to walk, instead of a prompt asking it
  nicely to be careful. Six phases, and it cannot cross into the next one
  until the evidence for this one is on disk. Hooks refuse the writes that
  would skip a step.

ABOUT
echo "  Running on: $OS_NAME"
echo

# ── Plugin or drop-in ─────────────────────────────────────────────────────────
#
# Always asked, unless --mode already answered it. Naming a tool says which
# agent you work with; it does not say whether you want the method copied into
# the repository or managed by that agent, and the two leave very different
# repositories behind. A default nobody was shown is how someone ends up with
# `.ddw/` committed when they wanted a plugin.
#
# With no terminal to ask on there is no decision to be had, so it falls to
# drop-in and says which way it went. Silence is the thing being removed here.
if [ -z "$MODE" ] && have_tty; then
  cat <<'MODES'
  How do you want DDW installed?

    1) Plugin   — your tool fetches and manages it. Nothing of DDW is
                  committed to this repo, and updates come from the tool.
                  Available for Claude Code, Copilot CLI and OpenCode.
    2) Drop-in  — the method is copied into this repo, under .ddw/. Your
                  teammates get it on clone, and you can edit the rules.
                  Available for all six tools.

MODES
  printf "Choice [1]: "
  { read -r MOPT < /dev/tty; } 2>/dev/null || MOPT=1
  case "${MOPT:-1}" in
    1) MODE="plugin" ;;
    2) MODE="dropin" ;;
    *) echo "Invalid choice." >&2; exit 1 ;;
  esac
  echo
elif [ -z "$MODE" ]; then
  echo "  No --mode given and no terminal to ask on: installing as a drop-in."
  echo "  Pass --mode plugin to have your tool manage DDW instead."
  echo
fi
MODE="${MODE:-dropin}"
case "$MODE" in
  plugin|dropin) ;;
  *) echo "--mode takes plugin or dropin, not '$MODE'." >&2; exit 1 ;;
esac

label_of() {  # read the human label out of a recipe
  python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['label'])" \
    "$SELF/adapters/$1/adapter.json" 2>/dev/null || echo "$1"
}

plugin_install_of() {  # does this tool have a plugin install procedure? its recipe answers
  python3 -c "import json,sys;print('true' if json.load(open(sys.argv[1])).get('plugin_install') is True else 'false')" \
    "$SELF/adapters/$1/adapter.json" 2>/dev/null || echo "false"
}

# ── Is DDW already here, and for which tools? ────────────────────────────────
#
# The manifest keys are "<target>:<path>", so the repo already knows which tools
# were wired into it. Asking "which tool will you be working with?" on a repo
# that answered that question months ago is how a second install lands beside
# the first instead of refreshing it — and how one tool's wiring silently stays
# a version behind while the method in .ddw/ moves on.
INSTALLED="$(python3 - "$TARGET" "$SELF" <<'PY' 2>/dev/null || true
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
# Only the prefixes that name an adapter. The manifest also carries
# `method:.ddw/...`, which is not a tool: unfiltered, an already-installed
# repo offered "claude method", and choosing that died on `Unknown target:
# method`. With --target, it warned about a "target" not updated and gave the
# command to include it, which also exits 1. The adapter list is on disk; it
# is the one in charge.
adapters = os.path.join(sys.argv[2], "adapters") if len(sys.argv) > 2 else ""
known = ({d for d in os.listdir(adapters)
          if os.path.isfile(os.path.join(adapters, d, "adapter.json"))}
         if os.path.isdir(adapters) else None)
seen = sorted({k.split(":", 1)[0] for k in keys if ":" in k
               if known is None or k.split(":", 1)[0] in known})
print(" ".join(seen))
PY
)"

# ── Pick target(s) ────────────────────────────────────────────────────────────
if [ -z "$TARGETS" ] && [ -n "$INSTALLED" ] && [ "$MODE" = "dropin" ]; then
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

LABELS=""
for t in $TARGETS; do LABELS="$LABELS, $(label_of "$t")"; done
LABELS="${LABELS#, }"

# ── Plugin mode ───────────────────────────────────────────────────────────────
#
# Three tools have a way in that somebody has actually driven: Claude Code and
# Copilot CLI through their own plugin CLIs, OpenCode through one entry in its
# config. Codex, Cursor and Gemini ship a manifest in this repository and no
# install procedure exists for them anywhere — so this says that, rather than
# running something plausible and reporting success.
#
# Nothing here needs administrator rights on any platform: every path written
# is under $HOME or inside the repo you named.
# Which tools have one is the adapter's answer, not a list kept by hand here.
# It was a hand-kept list, and this file's own header promises the opposite —
# "the target list below is discovered from the adapters directory". A name
# typed into a script is a second source of truth that nothing compares against
# the first, which is how the check that measured one job by name left the
# other unmeasured for as long as it existed.
PLUGIN_CAPABLE=" "
for _a in "${AVAILABLE[@]}"; do
  [ "$(plugin_install_of "$_a")" = "true" ] && PLUGIN_CAPABLE="${PLUGIN_CAPABLE}${_a} "
done
unset _a

# Copilot's hooks, and the one thing that decides where they go: FOLDER TRUST.
#
# The whole recipe is in the adapter — `adapters/copilot/wire-user-hooks.py`,
# which says what was measured and why there is exactly one wiring location.
# It is a script and not a here-doc inside this file so that the checks can run
# the real thing against a sandboxed HOME: a wiring nothing can execute is a
# wiring nothing can verify.
#
# $1 = an absolute plugin root (plugin mode) or nothing at all (drop-in).
copilot_hooks() {
  python3 "$SELF/adapters/copilot/wire-user-hooks.py" "${1:-}"
}

opencode_register() {
  python3 - <<'PY'
import json, os, re
home = os.path.expanduser("~")
base = os.path.join(home, ".config", "opencode")
path = None
for name in ("opencode.json", "opencode.jsonc"):
    if os.path.exists(os.path.join(base, name)):
        path = os.path.join(base, name)
        break
path = path or os.path.join(base, "opencode.json")
raw = ""
try:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
except OSError:
    pass
try:
    # jsonc: strip whole-line comments only, which is what this file ever has.
    cfg = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M)) if raw.strip() else {}
except ValueError:
    print("  ⚠ opencode: %s is not readable as JSON, so it was left untouched." % path)
    print("    Add \"plugin\": [\"ddw@git+https://github.com/soydiloreto/"
          "dilux-development-workflow.git\"] by hand.")
    raise SystemExit(0)
entry = "ddw@git+https://github.com/soydiloreto/dilux-development-workflow.git"
plugins = cfg.get("plugin")
plugins = list(plugins) if isinstance(plugins, list) else []
if not any(isinstance(p, str) and p.startswith("ddw@") for p in plugins):
    plugins.append(entry)
cfg["plugin"] = plugins          # merge: every other key of yours is preserved
os.makedirs(base, exist_ok=True)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
print("  ✓ %s  plugin registered" % path)
print("    OpenCode clones it on the next start, so that first launch is slower.")
PY
}

if [ "$MODE" = "plugin" ]; then
  echo "$RULE"
  echo "  DDW is installing as a plugin"
  echo "  Wiring for:  $LABELS"
  echo "  Into:        $TARGET"
  echo "$RULE"
  echo
  # What this says used to be "nothing of DDW is written into your repo", and
  # thirty lines below the same run printed "scope: project — your teammates get
  # it on clone". Both cannot be true: a project-scope install records the
  # activation in the repo's own settings file. The promise a plugin can keep is
  # about the METHOD, not about every byte.
  echo "  The method is not copied into your repo — it lives in the tool's own"
  echo "  plugin store. What lands here is at most the activation your tool needs"
  echo "  (Claude Code records it in .claude/settings.json, which is how a"
  echo "  teammate gets the pipeline on clone), plus .ddw-state.json when the"
  echo "  first ticket starts — and that one is gitignored."
  echo
  PLUGIN_FAILED=""
  for t in $TARGETS; do
    case "$PLUGIN_CAPABLE" in
      *" $t "*) ;;
      *)
        echo "  ⚠ $(label_of "$t"): no plugin install exists for it."
        echo "    The manifest is in this repository, but no procedure for putting it"
        echo "    in place has been written or driven. Use --mode dropin for this one."
        PLUGIN_FAILED="yes"; continue ;;
    esac
    echo "  ── $(label_of "$t")"
    case "$t" in
      claude|copilot)
        # The tool's own package manager, not a reimplementation of it: writing
        # its cache layout and manifests by hand is how an installer comes to own
        # a format that belongs to somebody else's product.
        if ! command -v "$t" >/dev/null 2>&1; then
          echo "  ⚠ \`$t\` is not on PATH, so its plugin CLI cannot be reached."
          echo "    Install the CLI first, or use --mode dropin."
          PLUGIN_FAILED="yes"; continue
        fi
        # The marketplace is this working copy, so what gets installed is what is
        # in front of you — including changes not pushed anywhere yet.
        "$t" plugin marketplace add "$SELF" >/dev/null 2>&1 \
          || "$t" plugin marketplace update dilux >/dev/null 2>&1 || true
        if [ "$t" = "claude" ]; then
          ( cd "$TARGET" && claude plugin install ddw@dilux --scope project ) \
            && echo "  ✓ installed  ddw@dilux (scope: project — recorded in .claude/settings.json, your teammates get it on clone)" \
            || { echo "  ⚠ claude: the plugin install did not complete."; PLUGIN_FAILED="yes"; }
        else
          copilot plugin install ddw@dilux \
            && echo "  ✓ installed  ddw@dilux (the 17 skills)" \
            || { echo "  ⚠ copilot: the plugin install did not complete."; PLUGIN_FAILED="yes"; }
          copilot_hooks "$SELF"
        fi ;;
      opencode) opencode_register ;;
    esac
    echo
  done
  echo "$RULE"
  echo "  DDW installed as a plugin"
  echo "$RULE"
  echo
  echo "  Open your agent in $TARGET and ask for the work you want done."
  echo "  If a session was already open, it is running the previous wiring:"
  echo "  hooks and settings are read at startup."
  echo
  [ -n "$PLUGIN_FAILED" ] && exit 1
  exit 0
fi

echo "$RULE"
if [ -n "$INSTALLED" ]; then
  # The two verbs stay exactly as they were. A check asserts a first run says
  # one and a re-run the other, and a mutation flips them to prove the check
  # bites; rewording them here would have made that mutation a no-op — an
  # unkillable mutant reads as a hole in the suite, and it is not one.
  echo "  DDW is updating: $TARGET"
  echo "  Wiring for:      $LABELS"
  echo "$RULE"
  cat <<'PLAN_UPDATE'

  What this refreshes
    .ddw/                the method — rules, phase graph, validators
    the tool's wiring    skills, agents, hooks, settings

  What it leaves exactly as it is
    Your code, your documents, and your phase: `.ddw-state.json` is never
    touched, so a ticket in flight stays where it is. Any file of yours
    whose name DDW also uses is reported and left alone.

  Nothing is deleted. `uninstall.sh` reverses the install using the
  manifest it wrote.

PLAN_UPDATE
else
  echo "  DDW is installing into: $TARGET"
  echo "  Wiring for:             $LABELS"
  echo "$RULE"
  cat <<'PLAN_INSTALL'

  What lands in your repo
    .ddw/                the method — rules, phase graph, validators
    the tool's directory skills, agents, hooks and settings for your agent
    .ddw-installed.json  the manifest of everything DDW put here
    AGENTS.md            a short activation block appended at the end
    .gitignore           a block so the pipeline's runtime is never committed

  What it will not touch
    Your code and your documents. If you already have a file whose name DDW
    also uses, yours stays and the collision is reported at the end.

  Nothing is deleted, here or on an update. `uninstall.sh` reverses this
  using the manifest.

PLAN_INSTALL
fi

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

# ── Where does the installation land, git-wise? ───────────────────────────────
#
# Asked BEFORE a byte is written, because the answer decides where the bytes
# go: a setup branch is created now, so even a half-failed install lands on it
# and not on the user's branch.
#
# Asked on an UPDATE too, which it was not. The reasoning for skipping it was
# "an update is a refresh of what a branch already carries, and a new branch per
# refresh would be noise" — true while you are standing on the branch DDW lives
# on, false the moment you are not. Reported from real use: an update run in the
# middle of a ticket committed the whole framework onto that ticket's branch,
# which is the exact failure the question exists to prevent, and which already
# cost one pull request 66 framework files. A refresh is dozens of files; there
# is nothing smaller about it than a first install.
#
# `DDW_GIT_FLOW=setup|current|none` answers the question without a terminal
# (tests, scripted installs); the prompt is the interactive spelling of it.
DDW_GIT_CHOICE=""            # setup | current | none | "" (never asked)
DDW_SETUP_BRANCH=""
CURBRANCH=""
# The same question, and the right noun for it: calling a refresh "the
# installation" is half of why it read as a question that did not apply here.
DDW_LANDS="installation"; [ -n "$INSTALLED" ] && DDW_LANDS="update"
if git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
   && { [ -n "${DDW_GIT_FLOW:-}" ] || have_tty; }; then
  if git -C "$TARGET" rev-parse -q --verify HEAD >/dev/null 2>&1; then
    CURBRANCH="$(git -C "$TARGET" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
    # Six hex characters, and asked of python — which this script has already
    # depended on for four hundred lines. It was
    # `tr -dc 'a-f0-9' < /dev/urandom | head -c6`, and on macOS that HANGS: BSD
    # `tr` hands nothing down the pipe, `head` waits for six bytes that never
    # come, and neither process ever exits. The installer stops dead here —
    # before it prints the question it stopped to ask — in any git repository
    # carrying at least one commit, which is every repository anybody installs
    # into. It shipped that way from #20 and no check reached this line: every
    # install in the suite ran against a `git init` with nothing committed, so
    # `rev-parse --verify HEAD` failed and this whole block was skipped.
    # The lesson is not about `tr`. A pipeline that only terminates because the
    # reader closes the pipe is a pipeline betting on SIGPIPE arriving, and that
    # bet is settled differently by two implementations of the same POSIX tool.
    # There is no unbounded read here any more.
    DDW_SETUP_BRANCH="ddw-setup-$(python3 -c 'import secrets; print(secrets.token_hex(3))' 2>/dev/null)"
    [ "$DDW_SETUP_BRANCH" = "ddw-setup-" ] && DDW_SETUP_BRANCH="ddw-setup-$$"
    case "${DDW_GIT_FLOW:-}" in
      setup)   GOPT=1 ;;
      current) GOPT=2 ;;
      none)    GOPT=3 ;;
      *)
        echo "  This is a git repository · current branch: $CURBRANCH"
        echo
        echo "  Where should the $DDW_LANDS land?"
        echo "    1. On a new setup branch — $DDW_SETUP_BRANCH   (recommended)"
        echo "       Written and committed there; your branches stay untouched."
        echo "       After the commit you choose: push it & open a PR, or keep it local."
        echo "    2. On the current branch ($CURBRANCH)"
        echo "       Written and committed right here."
        echo "    3. Files only — no commit"
        echo "       Everything lands, nothing is committed; you handle git yourself."
        printf "  [1/2/3] (1): "
        { read -r GOPT < /dev/tty; } 2>/dev/null || GOPT=1
        echo ;;
    esac
    case "$GOPT" in
      2) DDW_GIT_CHOICE="current" ;;
      3) DDW_GIT_CHOICE="none" ;;
      *) DDW_GIT_CHOICE="setup"
         if git -C "$TARGET" checkout -q -b "$DDW_SETUP_BRANCH" 2>/dev/null; then
           echo "  ✓ On $DDW_SETUP_BRANCH — installing here."
           echo
         else
           echo "  ⚠ Could not create $DDW_SETUP_BRANCH — staying on $CURBRANCH, committing nothing."
           echo
           DDW_GIT_CHOICE="none"
         fi ;;
    esac
  else
    # `git init` with no commits yet: there is no base to branch from or open
    # a PR against, so the branch question would offer choices that cannot be
    # kept. The installation is offered as this repository's first commit.
    echo "  This is a git repository with no commits yet: the installation will be"
    echo "  offered as its first commit, on the branch you are on."
    echo
    DDW_GIT_CHOICE="current"
  fi
fi

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
  # Copilot's gates do not live in the repo, because Copilot loads a repo-level
  # hooks manifest only in a folder the user has trusted — and trust is answered
  # in a dialog `-p` cannot show, so a fresh clone or a CI checkout enforces
  # nothing. The recipe puts the SCRIPTS here; the thing that points at them is
  # written once, at user level, and serves every drop-in repo on this machine.
  if [ "$t" = "copilot" ]; then
    copilot_hooks
    # A manifest an older DDW left in the repo still runs wherever the folder is
    # trusted, and there every source's hooks are combined and all of them run —
    # so leaving it judges every write twice in exactly the repos that work.
    if [ -f "$TARGET/.github/hooks/ddw.json" ]; then
      rm -f "$TARGET/.github/hooks/ddw.json"
      echo "  ✓ .github/hooks/ddw.json  removed — unread in an untrusted folder, doubled where trusted"
    fi
  fi
done

# ── 4. .gitignore ─────────────────────────────────────────────────────────────
echo
GITIGNORE="$TARGET/.gitignore"
# An existing block is REPLACED, not left alone. "Already has the DDW block" was
# true and useless: the day the pipeline started writing a new runtime file, an
# updated repo kept a block that did not mention it, and the first `git add -A`
# committed somebody's scratch. The block is DDW's, delimited by its own markers,
# and every line outside them is untouched.
if [ -f "$GITIGNORE" ] && grep -qF "# BEGIN DDW" "$GITIGNORE"; then
  python3 - "$GITIGNORE" <<'PY'
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    lines = fh.read().splitlines()
out, skipping = [], False
for line in lines:
    if line.startswith("# BEGIN DDW"):
        skipping = True
        continue
    if skipping:
        if line.startswith("# END DDW"):
            skipping = False
        continue
    out.append(line)
while out and not out[-1].strip():
    out.pop()
with open(path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + ("\n" if out else ""))
PY
  DDW_GITIGNORE_NOTE="refreshed"
fi
if [ -f "$GITIGNORE" ] && grep -qF "# BEGIN DDW" "$GITIGNORE"; then
  echo "  ✓ .gitignore             already has the DDW block"
else
  { [ -s "$GITIGNORE" ] && printf '\n'
    printf '%s\n' \
      '# BEGIN DDW — pipeline runtime, NOT committed (managed by DDW)' \
      '#   .ddw-state.json  = which phase you are in; yours, not the repo'"'"'s' \
      '#   .ddw-paused/     = paused tickets' \
      '#   .ddw-sessions/   = live session markers' \
      '#   .ddw-work/       = scratch the pipeline writes and re-reads (the commit message)' \
      '#   .ddw-journal.jsonl = transitions that landed; outlives the state file' \
      '#   .ddw/**/__pycache__/ = bytecode from running the method'"'"'s own scripts' \
      '.ddw-state.json' \
      '.ddw-paused/' \
      '.ddw-sessions/' \
      '.ddw-work/' \
      '.ddw-journal.jsonl' \
      '.ddw/**/__pycache__/' \
      '# END DDW'
  } >> "$GITIGNORE"
  if [ "${DDW_GITIGNORE_NOTE:-}" = "refreshed" ]; then
    echo "  ✓ .gitignore             DDW block refreshed (the runtime it names has changed)"
  else
    echo "  ✓ .gitignore             DDW block added (the state is never committed)"
  fi
fi

if [ -n "$COLLISIONS" ]; then
  echo
  echo "  ⚠ These already existed in the repo, so they were left alone (they are yours):"
  echo "${COLLISIONS#,}" | tr ',' '\n' | sed '/^$/d' | sort -u | sed 's/^/      /'
  echo "    DDW ships its own version of those names. If you want DDW's,"
  echo "    rename yours and re-run the installer: it is idempotent."
fi

echo
echo "$RULE"
if [ -n "$INSTALLED" ]; then
  echo "  DDW updated  ·  $TARGET"
else
  echo "  DDW installed  ·  $TARGET"
fi
echo "$RULE"
echo
if [ -z "$INSTALLED" ]; then
  cat <<'NEXT'
  Before you start
    1. Fill in the "Stack" section of AGENTS.md — how your project is built,
       how its tests run, how it is linted. The pipeline reads that section
       to know which commands are yours; guessing them is not allowed.
    2. Open your agent in this repo. The pipeline activates on its own, on
       your first message. You do not have to invoke it.
    3. Ask for the work you want done, in your own words. It classifies the
       request and takes it from there, one step at a time, waiting for you
       at each one.

NEXT
else
  cat <<'NEXT_UPDATE'
  Next
    1. Restart any agent session open on this repo — hooks and settings are
       read at startup, so a running session keeps the previous wiring.
    2. Carry on where you were. Your phase was not touched.

NEXT_UPDATE
fi
# How to invoke DDW is printed per target above, by the adapter that knows: not
# every tool exposes skills as /name, and this line used to promise /ddw-status
# to all six.
echo "  The \"try:\" line above shows how to call DDW by hand in your tool."
echo

# ── Offer to commit the installation ──────────────────────────────────────────
#
# An installation that is never committed is a bomb with a long fuse: the first
# closeout's commit gate demands a clean tree, and the first ticket unlucky
# enough to get there sweeps the WHOLE framework into its feature PR. Measured:
# 68 files and 16,568 lines of DDW inside a pull request about a web form. The
# moment the user can still say no cheaply is now — so ask now, stage exactly
# what the manifest says was written, and leave anything that was already dirty
# before this run alone, with a warning naming it.
DDW_IS_GIT=0
git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1 && DDW_IS_GIT=1
# The warning that survives the commit landing: a commit the remote never got
# rides into the first ticket's pull request. Round 5 proved it the expensive
# way — the installation was committed on the LOCAL default branch, nobody
# pushed it, and the ticket's PR showed 66 framework files to its reviewer.
ddw_warn_unpushed() {
  echo "  ⚠ THIS COMMIT IS NOT ON YOUR REMOTE. YOU MUST GET IT ONTO YOUR DEFAULT"
  echo "    BRANCH — push it, or open and merge its PR — BEFORE THE FIRST TICKET"
  echo "    STARTS. A ticket branched off a base the remote does not have drags"
  echo "    every missing commit into its own pull request."
}
if [ "$DDW_IS_GIT" = 1 ] && { have_tty || [ -n "${DDW_GIT_FLOW:-}" ]; }; then
  DDW_COMMIT_PATHS="$(python3 - "$TARGET" "$PREDIRTY" <<'PYPATHS'
import json, os, subprocess, sys
target, predirty = sys.argv[1], set(filter(None, sys.argv[2].split("\n")))
paths = set()
mp = os.path.join(target, ".ddw-installed.json")
if os.path.exists(mp):
    try:
        for key in json.load(open(mp, encoding="utf-8")):
            paths.add(key.split(":", 1)[1] if ":" in key else key)
    except ValueError:
        pass
    paths.add(".ddw-installed.json")
# The files DDW writes or edits OUTSIDE the manifest: the activation blocks,
# the gitignore block, and the settings the adapter merges rather than copies.
for extra in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".gitignore",
              ".claude/settings.json", "opencode.json"):
    if extra not in predirty and os.path.exists(os.path.join(target, extra)):
        paths.add(extra)
# Only what git actually sees as new or changed: an update run that rewrote
# nothing should not offer an empty commit.
try:
    # `-uall`: untracked files are listed one by one — without it an untracked
    # DIRECTORY collapses to one `?? .claude/skills/` line and every file
    # beneath it silently misses the commit. Measured on the first dry run.
    out = subprocess.run(["git", "-C", target, "status", "--porcelain", "-uall", "--"] + sorted(paths),
                         capture_output=True, text=True, timeout=15)
    dirty = {ln[3:].strip().strip('"') for ln in out.stdout.splitlines() if len(ln) > 3}
except Exception:
    dirty = set()
# A manifest entry can be a DIRECTORY (`.claude/skills/ddw-commit`): what git
# reports dirty is the files beneath it, so the match is by prefix.
print("\n".join(sorted(p for p in paths
                       if p in dirty or any(d.startswith(p + "/") for d in dirty))))
PYPATHS
)"
  DDW_DID_COMMIT=0
  # An update committed "install DDW v0.34.0": the log said the wrong thing about
  # every refresh this script has ever made.
  DDW_COMMIT_MSG="🔧 chore(ddw): install DDW v${VERSION:-?} (drop-in)"
  [ -n "$INSTALLED" ] && DDW_COMMIT_MSG="🔧 chore(ddw): update DDW to v${VERSION:-?} (drop-in)"
  if [ -n "$DDW_COMMIT_PATHS" ]; then
    N_PATHS="$(printf '%s\n' "$DDW_COMMIT_PATHS" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [ -n "$PREDIRTY" ]; then
      echo "  ⚠ Left out (they were already modified before this run — review them yourself):"
      printf '%s\n' "$PREDIRTY" | sed '/^$/d' | sed 's/^/      /'
    fi
    if [ "$DDW_GIT_CHOICE" = "none" ]; then
      echo "  Files landed on $(git -C "$TARGET" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?'); nothing committed — your choice."
      echo "  Commit the $N_PATHS path(s) yourself before the first ticket closes, or its"
      echo "  PR will carry the framework."
    elif [ "$DDW_GIT_CHOICE" = "setup" ] || [ "$DDW_GIT_CHOICE" = "current" ]; then
      # The consent was given up front, with the destination named: the choice
      # WAS "installed and committed there". Asking again would be the second
      # signature on the same line.
      ADDED=1
      while IFS= read -r p; do
        [ -z "$p" ] && continue
        git -C "$TARGET" add -- "$p" || ADDED=0
      done <<EOF_DDW_PATHS
$DDW_COMMIT_PATHS
EOF_DDW_PATHS
      if [ "$ADDED" = 1 ] \
         && git -C "$TARGET" commit -q -m "$DDW_COMMIT_MSG"; then
        echo "  ✓ ${DDW_LANDS} committed on $(git -C "$TARGET" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?'): $N_PATHS path(s) ($(git -C "$TARGET" rev-parse --short HEAD))"
        DDW_DID_COMMIT=1
      else
        echo "  ⚠ The commit did not land (a signing prompt, a hook?). The paths are"
        echo "    staged; commit them yourself before the first ticket closes."
      fi
    else
      # An update run, or a fresh install where the question was never asked:
      # the standing offer, on whatever branch the repo is on.
      echo "  The installation is not committed yet ($N_PATHS path(s)). Left uncommitted, the"
      echo "  first ticket's closeout will sweep it into that ticket's own pull request."
      printf "  Commit the installation now? [Y/n] "
      { read -r DOCOMMIT < /dev/tty; } 2>/dev/null || DOCOMMIT=n
      case "$DOCOMMIT" in
        n|N|no|NO) echo "  Skipped. Commit it yourself before the first ticket closes." ;;
        *)
          ADDED=1
          while IFS= read -r p; do
            [ -z "$p" ] && continue
            git -C "$TARGET" add -- "$p" || ADDED=0
          done <<EOF_DDW_PATHS2
$DDW_COMMIT_PATHS
EOF_DDW_PATHS2
          if [ "$ADDED" = 1 ] \
             && git -C "$TARGET" commit -q -m "$DDW_COMMIT_MSG"; then
            # The branch, and the warning that goes with it. This path — the
            # standing offer, taken when the question above was never asked —
            # printed a bare sha: it never said WHERE the commit landed and
            # never said it was not on the remote, while both other paths did.
            # A commit the remote does not have drags every missing commit into
            # the first ticket's pull request.
            echo "  ✓ Committed on $(git -C "$TARGET" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?'): $N_PATHS path(s) ($(git -C "$TARGET" rev-parse --short HEAD))"
            ddw_warn_unpushed
          else
            echo "  ⚠ The commit did not land (a signing prompt, a hook?). The paths are"
            echo "    staged; commit them yourself before the first ticket closes."
          fi ;;
      esac
    fi
    echo
  elif [ "$DDW_GIT_CHOICE" = "setup" ] && [ -n "$DDW_SETUP_BRANCH" ] && [ -n "$CURBRANCH" ]; then
    # Nothing was written — a refresh onto the version already there. Without
    # this you are left standing on a branch that was created for a commit that
    # never happened, off the branch you were working on, and the reason is
    # invisible. The branch is only cleaned up when it is EMPTY: `--delete`
    # without `-D` refuses to throw away anything that is not merged, so a
    # commit that did land can never be lost here.
    if git -C "$TARGET" checkout -q "$CURBRANCH" 2>/dev/null; then
      git -C "$TARGET" branch -q --delete "$DDW_SETUP_BRANCH" >/dev/null 2>&1
      echo "  Nothing changed — you already had this version. Back on $CURBRANCH."
      echo
    fi
  fi
  if [ "$DDW_GIT_CHOICE" = "setup" ] && [ "$DDW_DID_COMMIT" = 1 ]; then
    PUSHOPT="${DDW_GIT_PUSH:-}"
    if [ -z "$PUSHOPT" ]; then
      # Not "a draft PR". `gh pr create` below passes no --draft, and it must
      # not: a draft is one nobody can approve or merge, and the very next thing
      # this prints is that you have to merge it before the first ticket.
      printf "  Push %s and open a PR? [y/N] " "$DDW_SETUP_BRANCH"
      { read -r PUSHOPT < /dev/tty; } 2>/dev/null || PUSHOPT=n
    fi
    case "$PUSHOPT" in
      y|Y|yes|YES)
        if git -C "$TARGET" push -q -u origin "$DDW_SETUP_BRANCH" 2>/dev/null; then
          if (cd "$TARGET" && gh pr create \
                --title "🔧 Install DDW v${VERSION:-?}" \
                --body "Drop-in installation of DDW v${VERSION:-?}: the method under .ddw/, the agent wiring, and the activation blocks. Committed by the installer, exactly the paths its manifest names." \
                >/dev/null 2>&1); then
            echo "  ✓ Pushed and PR opened. Merge that PR into your default branch BEFORE"
            echo "    the first ticket starts — a ticket branched off a base without it"
            echo "    drags the framework into its own pull request."
          else
            echo "  ✓ Pushed. The PR could not be opened (no gh? not authenticated?) —"
            echo "    open it yourself from $DDW_SETUP_BRANCH and merge it before the"
            echo "    first ticket starts."
          fi
        else
          echo "  ⚠ Push failed (no remote? no permission?). The branch stays local:"
          echo "    git checkout $CURBRANCH && git merge $DDW_SETUP_BRANCH"
          ddw_warn_unpushed
        fi ;;
      *)
        echo "  The branch stays local. Merge it when you like:"
        echo "    git checkout $CURBRANCH && git merge $DDW_SETUP_BRANCH"
        ddw_warn_unpushed ;;
    esac
    echo
  fi
  if [ "$DDW_GIT_CHOICE" = "current" ] && [ "$DDW_DID_COMMIT" = 1 ]; then
    if git -C "$TARGET" remote get-url origin >/dev/null 2>&1; then
      DDW_CURB="$(git -C "$TARGET" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
      PUSHOPT="${DDW_GIT_PUSH:-}"
      if [ -z "$PUSHOPT" ]; then
        printf "  Push %s to origin now? [y/N] " "$DDW_CURB"
        { read -r PUSHOPT < /dev/tty; } 2>/dev/null || PUSHOPT=n
      fi
      case "$PUSHOPT" in
        y|Y|yes|YES)
          if git -C "$TARGET" push -q origin "$DDW_CURB" 2>/dev/null; then
            echo "  ✓ Pushed: origin/$DDW_CURB now carries the installation."
          else
            echo "  ⚠ Push failed (no permission? branch protection?)."
            ddw_warn_unpushed
          fi ;;
        *) ddw_warn_unpushed ;;
      esac
      echo
    fi
  fi
elif [ "$DDW_IS_GIT" = 1 ]; then
  echo "  Note: this repo is git-tracked and the installation is not committed."
  echo "  Commit it before the first ticket closes, or that ticket's PR will carry it."
  echo
else
  # Not validated away on purpose: DDW installs fine into a bare directory,
  # but its pipeline branches, commits and opens pull requests — the first
  # ticket dies at CLASSIFY creating a branch that has nowhere to exist.
  # Installing silently and letting that happen two steps later would blame
  # the pipeline for the installer's silence.
  echo "  ⚠ This directory is not a git repository. DDW's pipeline branches, commits"
  echo "    and opens pull requests — run \`git init\` (and make a first commit) before"
  echo "    the first ticket, or it will fail at CLASSIFY creating its branch."
  echo
fi
