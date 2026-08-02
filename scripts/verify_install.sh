#!/usr/bin/env bash
# verify_install.sh — install DDW into throwaway repos and check the result is
# actually usable by each tool. Run it before publishing, and after touching any
# adapter recipe.
#
#   bash scripts/verify_install.sh
#
# It runs every check and exits non-zero if any of them failed, so it works as a
# release gate.
#
# ── Why the counts below are pinned ──────────────────────────────────────────
# A suite that can quietly run fewer checks is worse than no suite: it prints a
# green N/N either way, because the denominator moves with the numerator. A
# A `find` without `-printf`, an absent `md5sum`, a missing `node` — each one
# silently removes a section and leaves the exit code at 0. So: every optional
# dependency is asserted up front, a missing one is a FAILURE and not a skip,
# and the run ends by checking that the number of checks it performed is the
# number it was supposed to perform.
#
# The first two of those are no longer dependencies: asserting a GNU flag is
# present is a way of saying the suite runs a smaller version of itself on
# macOS, which is the thing this file refuses to do everywhere else. They are
# written portably instead, and the pinned total is what catches the next one.
set -uo pipefail

EXPECT_CHECKS=${EXPECT_CHECKS:-431}   # bump this when you add or remove a check, on purpose
EXPECT_SKILLS=17
EXPECT_AGENTS=5
EXPECT_RULES=14
EXPECT_ADAPTERS=6

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILS=0
CHECKS=0

ok()   { CHECKS=$((CHECKS+1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { CHECKS=$((CHECKS+1)); FAILS=$((FAILS+1)); printf '  \033[31m✗\033[0m %s\n' "$1"; }
skip() { CHECKS=$((CHECKS+1)); printf "  \033[33m—\033[0m %s\n" "$1"; }   # counted: a check that did not run is not a check that passed
have() { [ -e "$1" ] && ok "${2:-$1}" || bad "${2:-$1} — MISSING"; }

section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# A tree hash that does not need md5sum, which is GNU-only. When it is absent
# both sides of the idempotency comparison come out as the empty string, so
# "the second install changed nothing" is true by vacuity and every idempotency
# check passes without comparing anything.
ddw_tree_hash() {
  python3 - "$1" <<'PYEOF'
import hashlib, os, sys
h = hashlib.sha256()
root = sys.argv[1]
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(d for d in dirnames if d != ".git")
    for f in sorted(filenames):
        full = os.path.join(dirpath, f)
        h.update(os.path.relpath(full, root).encode())
        with open(full, "rb") as fh:
            h.update(fh.read())
print(h.hexdigest())
PYEOF
}

# ── Preflight ─────────────────────────────────────────────────────────────────
# Every one of these used to be a silent skip.
section "Preflight: this machine can run the whole suite"

for TOOL in git python3 rsync node; do
  command -v "$TOOL" >/dev/null 2>&1 \
    && ok "present: $TOOL" \
    || bad "$TOOL is missing — the checks that need it would skip, and a skip reads as a pass"
done

python3 -c "import tomllib" 2>/dev/null \
  && ok "tomllib available (Codex agents get parsed)" \
  || bad "python < 3.11 — the Codex TOML checks would skip in silence"

python3 -c "import yaml" 2>/dev/null \
  && ok "pyyaml available (agent frontmatter gets parsed)" \
  || bad "pyyaml is missing — frontmatter is the contract every tool reads; it must be validated"

# ── Inventory ─────────────────────────────────────────────────────────────────
# Pinned on purpose. Counting the source and comparing it to itself can never
# detect a deleted skill — which is exactly how deleting one stayed green.
section "Inventory: the method still ships what it claims"

# $1 is a glob pattern, deliberately unquoted at expansion time.
n() { local c=0 x; for x in $1; do [ -e "$x" ] && c=$((c+1)); done; echo "$c"; }
[ "$(n "$SELF/skills/*/")" = "$EXPECT_SKILLS" ] \
  && ok "$EXPECT_SKILLS skills" \
  || bad "expected $EXPECT_SKILLS skills, found $(n "$SELF/skills/*/") — update EXPECT_SKILLS if this was deliberate"
[ "$(n "$SELF/agents/*.md")" = "$EXPECT_AGENTS" ] \
  && ok "$EXPECT_AGENTS agents" \
  || bad "expected $EXPECT_AGENTS agents, found $(n "$SELF/agents/*.md")"
[ "$(n "$SELF/ddw/rules/*.instructions.md")" = "$EXPECT_RULES" ] \
  && ok "$EXPECT_RULES rule files" \
  || bad "expected $EXPECT_RULES rule files, found $(n "$SELF/ddw/rules/*.instructions.md") — a deleted rule file leaves a phase with no instructions"
[ "$(n "$SELF/adapters/*/adapter.json")" = "$EXPECT_ADAPTERS" ] \
  && ok "$EXPECT_ADAPTERS adapter recipes" \
  || bad "expected $EXPECT_ADAPTERS adapters, found $(n "$SELF/adapters/*/adapter.json")"

# ── 0. Source integrity ───────────────────────────────────────────────────────
section "Source integrity"

python3 - "$SELF" <<'PY' && ok "every adapter.json parses and declares id/label" || bad "adapter recipes"
import json, sys, os, glob
root = sys.argv[1]
for p in glob.glob(os.path.join(root, "adapters", "*", "adapter.json")):
    r = json.load(open(p, encoding="utf-8"))
    assert r["id"] == os.path.basename(os.path.dirname(p)), f"{p}: id != dirname"
    assert r["label"], f"{p}: no label"
    for w in r.get("wiring", []):
        src = os.path.join(os.path.dirname(p), w["from"])
        assert os.path.isdir(src), f"{p}: wiring.from '{w['from']}' does not exist"
    if "settings_merge" in r:
        assert os.path.isfile(os.path.join(os.path.dirname(p), r["settings_merge"]["from"]))
    if "snippet" in r:
        assert os.path.isfile(os.path.join(os.path.dirname(p), r["snippet"]))
PY

python3 - "$SELF" <<'PYEOF' && ok "every agents/*.md frontmatter PARSES as YAML" || bad "agent frontmatter is not valid YAML — whatever reads it will drop the agent"
# Parsed with a real YAML loader, not a regex. A regex accepts
# `description: Read-only auditor: Detects ...`, which is not valid YAML at all —
# a plain scalar cannot contain ": " — so the agent silently fails to register
# while the check stays green. Whatever consumes frontmatter uses a parser, so
# this must too.
import sys, os, glob, yaml
root = sys.argv[1]
files = glob.glob(os.path.join(root, "agents", "*.md"))
assert files, "no agents found"
for path in files:
    t = open(path, encoding="utf-8").read()
    assert t.startswith("---\n"), f"{path}: no frontmatter"
    fm = t.split("---\n", 2)[1]
    try:
        d = yaml.safe_load(fm)
    except yaml.YAMLError as e:
        raise AssertionError(f"{os.path.basename(path)}: frontmatter is not valid YAML -> {e}")
    assert isinstance(d, dict), f"{path}: frontmatter is not a mapping"
    for k in ("name", "description", "tools"):
        assert d.get(k), f"{path}: missing {k}"
    assert d["name"] == os.path.basename(path)[:-3], f"{path}: name != filename"
PYEOF

python3 - "$SELF" <<'PY' && ok "every skills/*/SKILL.md has name matching its directory" || bad "skill frontmatter"
import re, sys, os, glob
root = sys.argv[1]
dirs = sorted(glob.glob(os.path.join(root, "skills", "*")))
assert dirs, "no skills found"
for d in dirs:
    p = os.path.join(d, "SKILL.md")
    assert os.path.isfile(p), f"{d}: no SKILL.md"
    fm = re.match(r"^---\n(.*?)\n---\n", open(p, encoding="utf-8").read(), re.S)
    assert fm, f"{p}: no frontmatter"
    name = re.search(r"^name:\s*(.+)$", fm.group(1), re.M)
    assert name, f"{p}: no name"
    assert name.group(1).strip() == os.path.basename(d), f"{p}: name != dirname"
    assert re.search(r"^description:\s*\S", fm.group(1), re.M), f"{p}: no description"
PY

# adapters/adapter.schema.md is what someone adding a seventh tool writes their
# recipe from. A field the installer honours but the schema never names is a
# capability that exists and cannot be found: the recipe is written without it,
# and what it produces is missing something with nothing to say so.
python3 - "$SELF" <<'PYSCHEMA' && ok "every field a recipe actually uses is named in the adapter schema" || bad "an adapter uses a field the schema does not document — the next recipe is written without it"
import glob, json, os, sys
root = sys.argv[1]
schema = open(os.path.join(root, "adapters", "adapter.schema.md"), encoding="utf-8").read()

# Free-form by design: their keys are the target tool's dialect, not DDW's.
OPAQUE = {"agents.frontmatter", "agents.when_readonly", "commands.frontmatter"}

def fields(node, prefix=""):
    for key, value in node.items():
        if key.startswith("_"):
            continue                      # comments the installer strips too
        name = f"{prefix}{key}"
        yield name
        if name in OPAQUE:
            continue
        if isinstance(value, dict):
            yield from fields(value, f"{name}.")
        elif isinstance(value, list):
            yield f"{name}[]"

undocumented, seen = set(), 0
for path in sorted(glob.glob(os.path.join(root, "adapters", "*", "adapter.json"))):
    recipe = json.load(open(path, encoding="utf-8"))
    for name in fields(recipe):
        seen += 1
        # The parent counts: the schema documents `settings_merge` as {from, to,
        # merge_key} in one row rather than a row per subkey. And a list is
        # documented under its `field[]` spelling.
        if any(spelling in schema for spelling in
               (f"`{name}`", f"`{name}[]`", f"`{name.split('.')[0]}`")):
            continue
        undocumented.add(f"{os.path.basename(os.path.dirname(path))}: {name}")
assert seen, "no recipe field was examined — this check measured nothing"
if undocumented:
    print("\n".join("      " + x for x in sorted(undocumented)), file=sys.stderr)
    sys.exit(1)
PYSCHEMA

# `--dialect` decides two things: how the incoming envelope is read, and what a
# refusal has to look like. A name the gate does not know silently gets the
# generic envelope spec — which is right for two tools today and is right by
# coincidence, not by decision. The coincidence is invisible: a renamed dialect,
# or a typo in a hook, keeps parsing and starts parsing the wrong shape.
python3 - "$SELF" <<'PYDIA' && ok "every dialect a hook passes is one the gate declares, and the CLI takes no other" || bad "a hook passes a dialect the gate never declared — it falls back to the generic envelope in silence"
import glob, os, re, sys
root = sys.argv[1]
gate = open(os.path.join(root, "ddw", "scripts", "hook-gate.py"), encoding="utf-8").read()

block = re.search(r"^DIALECTS = \{(.*?)^\}", gate, re.S | re.M)
assert block, "DIALECTS is no longer a literal this check can read"
declared = set(re.findall(r'^\s*"([a-z]+)":', block.group(1), re.M))
assert declared, "no dialect was parsed — this check measured nothing"

# The CLI must not accept a name the table does not carry, or the fallback is
# reachable again through a flag instead of through a lookup. Derived from the
# table is the strongest form of that and needs no comparison; a literal list is
# allowed, and then it has to agree.
choices = re.search(r'add_argument\("--dialect".*?choices=(\S+?),', gate, re.S)
assert choices, "--dialect takes no choices: any string reaches the silent fallback"
if choices.group(1) != "tuple(DIALECTS)":
    literal = re.search(r'add_argument\("--dialect".*?choices=\(([^)]*)\)', gate, re.S)
    assert literal and set(re.findall(r'"([a-z]+)"', literal.group(1))) == declared, \
        "the --dialect choices and the DIALECTS table disagree"

used, seen = set(), 0
sources = glob.glob(os.path.join(root, "adapters", "*", "hooks", "*.sh"))
sources += glob.glob(os.path.join(root, "adapters", "*", "scripts", "*.sh"))
sources += glob.glob(os.path.join(root, "adapters", "*", "plugin", "*.js"))
for path in sources:
    text = open(path, encoding="utf-8").read()
    for m in re.finditer(r'--dialect"?,?\s+"?([a-z]+)"?', text):
        used.add(m.group(1))
        seen += 1
assert seen, "no hook named a dialect — this check measured nothing"
missing = sorted(used - declared)
if missing:
    print("      passed but undeclared: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
PYDIA

# A plugin manifest on its own cannot be installed: Claude Code adds plugins
# through a MARKETPLACE, and without .claude-plugin/marketplace.json the only
# thing `/plugin marketplace add` can say is that there is nothing there. The
# repo is its own marketplace, with one plugin whose source is the root.
python3 - "$SELF" <<'PYMKT' && ok "the repo is a marketplace, so its plugin can actually be added" || bad "plugin.json exists but nothing can install it — /plugin marketplace add needs marketplace.json"
import json, os, sys
root = sys.argv[1]
m = json.load(open(os.path.join(root, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
assert m.get("name") and m.get("owner"), "marketplace.json needs a name and an owner"
names = [p["name"] for p in m["plugins"]]
assert "ddw" in names, f"marketplace lists {names}, not ddw"
src = next(p["source"] for p in m["plugins"] if p["name"] == "ddw")
assert os.path.exists(os.path.join(root, src, ".claude-plugin", "plugin.json")), \
    f"the marketplace points at {src!r}, where there is no plugin manifest"
PYMKT

# Claude Code ships the authority on this schema, so use it rather than
# re-deriving it here. The hand-rolled check below confirmed every path in the
# manifest existed and said nothing about `agents` being the wrong TYPE — which
# is what actually stopped the plugin installing: a string where the schema
# wants an array of files. A check that verifies your own assumptions agrees
# with itself is the failure mode this whole repository is built against.
if command -v claude >/dev/null 2>&1; then
  PV="$WORK/plugin-validate"; rm -rf "$PV"; mkdir -p "$PV"
  cp -R "$SELF/.claude-plugin" "$SELF/ddw" "$SELF/adapters" "$PV/" 2>/dev/null
  rm -f "$PV/.claude-plugin/marketplace.json"    # else it validates the marketplace instead
  claude plugin validate "$PV" --strict >/dev/null 2>&1 \
    && ok "the plugin manifest passes Claude Code's own validator (--strict)" \
    || { bad "plugin.json fails the tool's own schema — the plugin will not install"
         claude plugin validate "$PV" --strict 2>&1 | sed 's/^/      /' | head -8; }
  claude plugin validate "$SELF" --strict >/dev/null 2>&1 \
    && ok "and so does the marketplace that makes it installable" \
    || { bad "marketplace.json fails validation — /plugin marketplace add will refuse it"
         claude plugin validate "$SELF" --strict 2>&1 | sed 's/^/      /' | head -8; }
else
  skip "claude CLI not on PATH — the plugin manifests were not validated against the real schema"
  skip "claude CLI not on PATH — the marketplace was not validated either"
fi

python3 - "$SELF" <<'PYLAYOUT' && ok "the plugin's components sit where the tool discovers them" || bad "plugin layout — see above"
import json, os, sys
root = sys.argv[1]
r = json.load(open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8"))

# Skills and agents are discovered from `skills/` and `agents/` at the plugin
# root, and the manifest names NEITHER on purpose.
#
# It used to declare both, and the agents silently did not load: the `agents`
# field takes an array of files, validates clean, and produces zero components.
# Proven by putting one four-line agent in `agents/` (loaded) and naming that
# same file in the manifest (did not). `skills` did work from a custom path, but
# the asymmetry is not worth defending — the conventional layout is what the
# ecosystem uses, and a manifest that declares nothing cannot declare it wrongly.
for d in ("skills", "agents"):
    path = os.path.join(root, d)
    assert os.path.isdir(path), f"{d}/ must exist at the plugin root, where the tool looks"
    assert os.listdir(path), f"{d}/ is empty"
    assert d not in r, (f"plugin.json declares {d!r}; leave it out and let the default scan find "
                        "them — a custom agents path loads nothing at all")

# Hooks are the exception: the manifest names the file. skills/ and agents/ are
# found by the default scan and must NOT be declared — that is how the agents
# came to load zero.
#
# Naming Claude's file was ALSO believed to leave hooks/hooks.json free for
# Gemini, whose path is fixed and not configurable. That half was wrong, and the
# assertion below is what replaced it: Claude reads the default too, so the path
# is free for nobody and Gemini's extension hooks live in adapters/gemini/.
for k in ("skills", "agents"):
    assert k not in r, f"plugin.json declares {k!r}; the default location is found on its own"

# The same layout has to hold for every tool that installs this repo as a
# plugin, and the reason it is checked rather than declared is Cursor: its docs
# say components are "discovered automatically from their default directories,
# or you can specify custom paths in the manifest" (cursor.com/docs/plugins), so
# `agents/` at the root is found without a key — the same as Claude, where
# naming it is what made it load nothing. What can still go wrong is the
# directory not being there, or a manifest naming a path that is not.
for manifest in (".codex-plugin/plugin.json", ".cursor-plugin/plugin.json"):
    mp = os.path.join(root, manifest)
    if not os.path.isfile(mp):
        continue
    other = json.load(open(mp, encoding="utf-8"))
    for d in ("skills", "agents"):
        assert os.path.isdir(os.path.join(root, d)) and os.listdir(os.path.join(root, d)), \
            f"{manifest}: {d}/ is missing from the plugin root, where the default scan looks"
    for key, value in other.items():
        if isinstance(value, str) and value.startswith("./"):
            assert os.path.exists(os.path.join(root, value)), \
                f"{manifest}: {key} names {value!r}, which is not in this repo"

assert r.get("hooks") == "./adapters/claude/plugin-hooks.json", (
    "plugin.json must name Claude's own hooks file rather than rely on a default")

# NOTHING may sit at hooks/hooks.json in this repository.
#
# Declaring Claude's path was believed to leave that default free for Gemini,
# whose own path is fixed. It does not: Claude Code scans hooks/hooks.json at the
# plugin root REGARDLESS of what the manifest declares, reads whatever is there
# IN ADDITION to the declared file, and reports `Failed to load hooks` on every
# session when it finds Gemini's BeforeTool / AfterTool / PreCompress. Observed
# on a live plugin install (2.1.x), which is the only way this could be observed:
# the suite drives the hooks each tool runs and cannot know which files a tool
# opens on its own initiative.
assert not os.path.exists(os.path.join(root, "hooks", "hooks.json")), (
    "hooks/hooks.json is back at the repository root. Claude scans that path "
    "whatever the manifest says, so a file there in any other tool's dialect "
    "makes every Claude session open with a plugin error")

# ONLY Claude's event names may live in that file. A Gemini `BeforeTool` there
# made Claude load zero hooks from it rather than skip the entry it did not know
# — the plugin still installs, and enforces nothing.
CLAUDE_EVENTS = {"SessionStart", "PreToolUse", "PostToolUse", "PreCompact", "Stop",
                 "SubagentStop", "UserPromptSubmit", "Notification", "SessionEnd"}
hk = json.load(open(os.path.join(root, "adapters", "claude", "plugin-hooks.json"),
                    encoding="utf-8"))["hooks"]
foreign = sorted(set(hk) - CLAUDE_EVENTS)
assert not foreign, (f"Claude's hook file carries {foreign}, which it does not know — one "
                     "foreign name discards the WHOLE file, silently")

# And the mirror: Gemini's file must carry only Gemini's, for the same reason.
gk = json.load(open(os.path.join(root, "adapters", "gemini", "extension-hooks.json"),
                   encoding="utf-8"))["hooks"]
gcmds = [h["command"] for ev in gk.values() for b in ev for h in b["hooks"]]
assert gcmds, "adapters/gemini/extension-hooks.json declares no commands"
# The PATH has to resolve from it, not merely the command string somewhere: the
# command also exports the root as an environment variable for the script to
# read, and "${extensionPath}" appearing there satisfied a substring test while
# the script path itself had gone relative.
bad_g = [c for c in gcmds if "${extensionPath}/adapters/" not in c]
assert not bad_g, f"Gemini hook command(s) not resolving from ${{extensionPath}}: {bad_g[:2]}"
assert not (set(gk) & {"PreToolUse", "PostToolUse", "PreCompact"}), \
    "Claude event names in Gemini's hook file"

# The event name is not enough. `SessionStart` exists in both dialects, so a
# merged file left GEMINI's entry sitting in Claude's slot — pointing at
# ${extensionPath}, a variable Claude never expands — and the inventory still
# said four hooks. It read correct and would have failed at the first write.
cmds = [h["command"] for ev in hk.values() for b in ev for h in b["hooks"]]
assert cmds, "adapters/claude/plugin-hooks.json declares no commands"
wrong = [c for c in cmds if "${CLAUDE_PLUGIN_ROOT}" not in c]
assert not wrong, (f"{len(wrong)} hook command(s) do not resolve from ${{CLAUDE_PLUGIN_ROOT}}: "
                   f"{wrong[:2]} — they will not run, and nothing reports it")
PYLAYOUT

for f in "$SELF"/ddw/scripts/*.py "$SELF"/scripts/*.py; do
  python3 -m py_compile "$f" 2>/dev/null && ok "compiles: ${f#$SELF/}" || bad "syntax error: ${f#$SELF/}"
done
# Both levels spelled out, because `**` is not portable and failing to be is
# silent. macOS ships bash 3.2, where `globstar` does not exist: shopt printed
# `invalid shell option name` to stderr, `**` degraded to a plain `*`, and the
# pattern then matched only `hooks/lib/`. Twenty-one hooks — every adapter's
# entry point — went unparsed on one of the two platforms CI runs, and the run
# stayed green on the checks that did run. The pinned total is what noticed.
shopt -s nullglob
for f in "$SELF"/adapters/*/hooks/*.sh "$SELF"/adapters/*/hooks/*/*.sh \
         "$SELF"/adapters/*/scripts/*.sh "$SELF"/adapters/*/scripts/*/*.sh; do
  [ -e "$f" ] || continue
  bash -n "$f" 2>/dev/null && ok "parses: ${f#$SELF/}" || bad "syntax error: ${f#$SELF/}"
done
for f in "$SELF"/adapters/*/plugin/*.js; do
  [ -e "$f" ] || continue
  if command -v node >/dev/null; then
    node --check "$f" 2>/dev/null && ok "parses: ${f#$SELF/}" || bad "syntax error: ${f#$SELF/}"
  else
    bad "node is missing — ${f#$SELF/} was NOT parsed; that is a gap, not a pass"
  fi
done

# ── 1. Per-target install ─────────────────────────────────────────────────────
# A glob, not `find -printf`: that flag is GNU-only, so on macOS this loop
# produced no targets at all and the suite printed a green total for a section
# that never ran. The preflight had a check for the flag, which meant the whole
# per-target section was optional on one of the two operating systems CI runs.
for MANIFEST in "$SELF"/adapters/*/adapter.json; do
  T="$(basename "$(dirname "$MANIFEST")")"
  section "Install: --target $T"
  R="$WORK/$T"; mkdir -p "$R"; git -C "$R" init -q .
  if OUT="$(bash "$SELF/install.sh" "$R" --target "$T" 2>&1)"; then
    ok "install.sh exits 0"
  else
    bad "install.sh FAILED"; echo "$OUT" | sed 's/^/      /'
  fi
  echo "$OUT" | grep -qiE '\berror\b|traceback|not found|no such file' \
    && { bad "clean output"; echo "$OUT" | sed 's/^/      /'; } || ok "no errors in output"

  # The method, identical for every tool.
  have "$R/.ddw/orchestrator.md"          ".ddw/orchestrator.md"
  have "$R/.ddw/rules/transition-graph.json" ".ddw/rules/transition-graph.json"
  have "$R/.ddw/scripts/transition.py"    ".ddw/scripts/transition.py"
  have "$R/AGENTS.md"                     "AGENTS.md"
  [ -d "$R/.ddw/skills" ] && bad ".ddw/skills should NOT exist (adapters place them)" \
                          || ok ".ddw carries no tool payload"

  # Whatever this tool's recipe promised.
  python3 - "$SELF" "$R" "$T" <<'PY' && ok "recipe honoured (skills, agents, wiring, context)" || bad "recipe NOT honoured"
import json, os, re, sys
root, repo, tid = sys.argv[1:4]
r = json.load(open(os.path.join(root, "adapters", tid, "adapter.json"), encoding="utf-8"))
if "skills" in r:
    d = os.path.join(repo, r["skills"]["dir"])
    n_src = len(os.listdir(os.path.join(root, "skills")))
    got = [x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x, "SKILL.md"))]
    assert len(got) == n_src, f"{r['skills']['dir']}: {len(got)} skills, expected {n_src}"
if "agents" in r:
    spec, d = r["agents"], os.path.join(repo, r["agents"]["dir"])
    src = [f for f in os.listdir(os.path.join(root, "agents")) if f.endswith(".md")]
    for f in src:
        name = f[:-3]
        out = os.path.join(d, spec.get("filename", "{name}.md").replace("{name}", name))
        assert os.path.isfile(out), f"missing transpiled agent {out}"
        text = open(out, encoding="utf-8").read()
        if spec.get("format") == "toml":
            # No frontmatter to find: the whole file is the declaration, and the
            # prompt is a TOML string rather than the body below a fence.
            head = text.split("developer_instructions", 1)[0]
            for k in spec["frontmatter"]:
                assert re.search(rf"^{k} = ", head, re.M), f"{out}: missing '{k}'"
            assert "developer_instructions" in text, f"{out}: the prompt was dropped"
        else:
            fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            assert fm, f"{out}: no frontmatter"
            head = fm.group(1)
            for k in spec["frontmatter"]:
                assert re.search(rf"^{k}:", head, re.M), f"{out}: missing '{k}'"
        assert "{" not in head, f"{out}: unsubstituted placeholder"
for w in r.get("wiring", []):
    d = os.path.join(repo, w["to"])
    assert os.path.isdir(d) and os.listdir(d), f"wiring {w['to']} empty"
    if w.get("chmod") == "+x":
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if f.endswith(".sh"):
                assert os.access(p, os.X_OK), f"{p} not executable"
if "context_file" in r:
    t = open(os.path.join(repo, r["context_file"]), encoding="utf-8").read()
    assert "BEGIN DDW" in t and "END DDW" in t, f"{r['context_file']}: no DDW block"
PY

  # Idempotency: a second run must change nothing and report no collisions.
  B="$(ddw_tree_hash "$R")"
  OUT2="$(bash "$SELF/install.sh" "$R" --target "$T" 2>&1)"
  A="$(ddw_tree_hash "$R")"
  [ "$B" = "$A" ] && ok "idempotent (second run changes nothing)" || bad "NOT idempotent"
  echo "$OUT2" | grep -q "already existed" && bad "reports false collisions" || ok "no false collisions"

  # The state must be gitignored, or it ends up in the user's commits.
  ( cd "$R" && git add -A >/dev/null 2>&1
    printf '{"phase":"IDLE"}' > .ddw-state.json
    git add -A >/dev/null 2>&1
    git status --porcelain | grep -q '\.ddw-state\.json' \
      && exit 1 || exit 0 ) && ok ".ddw-state.json is gitignored" || bad ".ddw-state.json WOULD BE COMMITTED"

  # Running the method's own scripts leaves bytecode inside .ddw/, and a drop-in
  # is meant to be committed — so with no rule for it the user either commits
  # .pyc files or reads the same `git status` noise forever. Found on the first
  # real session, by the model, which mentioned it twice before anyone looked.
  ( cd "$R" && mkdir -p .ddw/scripts/__pycache__ \
    && : > .ddw/scripts/__pycache__/hook-gate.cpython-312.pyc
    git status --porcelain | grep -q '__pycache__' \
      && exit 1 || exit 0 ) && ok "and so is the bytecode the method leaves behind when it runs" \
      || bad "running DDW dirties the user's git status with __pycache__, and a drop-in commits it"
done

# ── 2. The FSM, which every adapter shares ────────────────────────────────────
section "Shared FSM (all adapters call this same validator)"
R="$WORK/fsm"; mkdir -p "$R"; git -C "$R" init -q .
bash "$SELF/install.sh" "$R" --target claude >/dev/null 2>&1
export CLAUDE_PROJECT_DIR="$R"
TR="$R/.ddw/scripts/transition.py"; G="$R/.ddw/rules/transition-graph.json"

python3 "$TR" --to DEFINE --action x --graph "$G" >/dev/null 2>&1 \
  && bad "IDLE->DEFINE should be rejected" || ok "rejects IDLE->DEFINE (not in graph)"
python3 "$TR" --to CLASSIFY --action req --graph "$G" > "$R/.ddw-state.json" 2>/dev/null \
  && ok "accepts IDLE->CLASSIFY" || bad "IDLE->CLASSIFY failed"
python3 "$TR" --to DEFINE --action c --tier FEATURE --graph "$G" > "$R/s" 2>/dev/null \
  && { cp "$R/s" "$R/.ddw-state.json"; ok "accepts CLASSIFY->DEFINE with a tier"; } || bad "CLASSIFY->DEFINE failed"
python3 "$TR" --to CODE --action x --graph "$G" >/dev/null 2>&1 \
  && bad "DEFINE->CODE should need gates" || ok "rejects DEFINE->CODE (FEATURE needs PLAN)"
python3 "$TR" --to PLAN --action p --gate define --graph "$G" >/dev/null 2>&1 \
  && ok "accepts DEFINE->PLAN once the define gate is set" || bad "DEFINE->PLAN with gate failed"
# Every tier in the graph must be reachable through the sanctioned helper. Reset
# to a fresh CLASSIFY each time: the tier is set on the edge leaving CLASSIFY.
for TIER in QUICK-FIX FIX FEATURE DISCOVERY; do
  DEST=DEFINE; [ "$TIER" = "DISCOVERY" ] && DEST=DISCOVERY
  python3 "$TR" --to CLASSIFY --action req --graph "$G" > "$R/.ddw-state.json" 2>/dev/null
  if python3 "$TR" --to "$DEST" --action c --tier "$TIER" --graph "$G" >/dev/null 2>&1; then
    ok "tier $TIER: CLASSIFY->$DEST accepted"
  else
    bad "tier $TIER: CLASSIFY->$DEST REJECTED"
  fi
done
# And the graph must actually enforce each tier's shape, not just accept the tier.
python3 "$TR" --to CLASSIFY --action req --graph "$G" > "$R/.ddw-state.json" 2>/dev/null
python3 "$TR" --to DEFINE --action c --tier QUICK-FIX --graph "$G" > "$R/s" 2>/dev/null && cp "$R/s" "$R/.ddw-state.json"
python3 "$TR" --to PLAN --action x --graph "$G" >/dev/null 2>&1 \
  && bad "QUICK-FIX should have no PLAN phase" || ok "QUICK-FIX: PLAN correctly unreachable"
python3 "$TR" --to CODE --action x --graph "$G" >/dev/null 2>&1 \
  && bad "QUICK-FIX DEFINE->CODE should need the brief gate" || ok "QUICK-FIX: DEFINE->CODE needs the define gate"
python3 "$TR" --to CODE --action x --gate define --graph "$G" >/dev/null 2>&1 \
  && ok "QUICK-FIX: DEFINE->CODE accepted with the define gate" || bad "QUICK-FIX DEFINE->CODE with gate failed"

# extends: a tier that inherits must end up with exactly its parent's edges.
python3 - "$G" "$R" <<'PY' && ok "extends: FIX inherits FEATURE's edges, no duplication" || bad "extends broken"
import importlib.util, json, sys
g = json.load(open(sys.argv[1]))
s = importlib.util.spec_from_file_location("v", f"{sys.argv[2]}/.ddw/scripts/validate-transition.py")
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
assert m._effective_edges(g, "FIX") == m._effective_edges(g, "FEATURE"), "FIX != FEATURE"
assert "extends" not in json.dumps(g["tiers"]["FEATURE"]), "FEATURE should not extend"
assert list(g["tiers"]["FIX"]) == ["extends"], "FIX should only declare extends"
for edges in (m._effective_edges(g, t) for t in g["tiers"]):
    assert "extends" not in edges, "'extends' leaked in as an edge"
PY

# Closing is gated; abandoning is not. This is the guarantee the whole pipeline
# rests on: you cannot reach IDLE from RELEASE without a commit and a PR.
CLOSE="$WORK/close"; mkdir -p "$CLOSE"; git -C "$CLOSE" init -q .
bash "$SELF/install.sh" "$CLOSE" --target claude >/dev/null 2>&1
export CLAUDE_PROJECT_DIR="$CLOSE"
TRC="$CLOSE/.ddw/scripts/transition.py"
step() { python3 "$TRC" "$@" --graph "$G" > "$CLOSE/s" 2>/dev/null && cp "$CLOSE/s" "$CLOSE/.ddw-state.json"; }
python3 "$TRC" --to CLASSIFY --action r --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DEFINE --action c --tier FEATURE
step --to PLAN   --action p --gate define
step --to CODE   --action x --gate spec --gate threat
step --to VERIFY --action x --gate tests --gate sast
step --to RELEASE --action x --gate verify
python3 "$TRC" --to IDLE --action done --graph "$G" >/dev/null 2>&1 \
  && bad "closed WITHOUT commit+pr" || ok "closeout blocked without commit+pr"
python3 "$TRC" --to IDLE --action done --gate commit --graph "$G" >/dev/null 2>&1 \
  && bad "closed with commit but no pr" || ok "closeout blocked with commit but no pr"
python3 - "$CLOSE" <<'PY'
import json, sys
p = f"{sys.argv[1]}/.ddw-state.json"; s = json.load(open(p))
s["gates"].update({"commit": True, "pr": True}); json.dump(s, open(p, "w"))
PY
python3 "$TRC" --to IDLE --action done --graph "$G" >/dev/null 2>&1 \
  && ok "closeout accepted with commit+pr" || bad "closeout rejected even with both gates"
# Abandoning mid-flight stays free — a wrong classification must not trap you —
# but it has to be DECLARED, so it never gets confused with a closeout.
python3 "$TRC" --to CLASSIFY --action r --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DEFINE --action c --tier FEATURE
step --to PLAN --action p --gate define
python3 "$TRC" --to IDLE --action "abandon: wrong classification" --graph "$G" >/dev/null 2>&1 \
  && ok "abandoning from PLAN stays ungated" || bad "abandoning was blocked"
python3 "$TRC" --to IDLE --action "discarded" --graph "$G" >/dev/null 2>&1 \
  && bad "reached IDLE off-graph without declaring the abandon" || ok "an undeclared exit to IDLE is refused"
# The tier built for exploring ideas has to let you drop one that did not hold up.
python3 "$TRC" --to CLASSIFY --action r --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DISCOVERY --action d --tier DISCOVERY
python3 "$TRC" --to IDLE --action done --graph "$G" >/dev/null 2>&1 \
  && bad "DISCOVERY closed without commit+pr" || ok "DISCOVERY closeout still needs commit+pr"
python3 "$TRC" --to IDLE --action "abandon: the idea does not hold up" --graph "$G" >/dev/null 2>&1 \
  && ok "DISCOVERY: a discarded idea can be abandoned" || bad "DISCOVERY traps you in the pipeline"
# And the closeout fallback must not let a corrective loop reuse stale gates.
python3 "$TRC" --to CLASSIFY --action r --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DEFINE --action c --tier FEATURE
step --to PLAN   --action p --gate define
step --to CODE   --action x --gate spec --gate threat
step --to VERIFY --action x --gate tests --gate sast
step --to CODE   --action "corrective loop"
python3 - "$CLOSE" <<'PY'
import json, sys
p = f"{sys.argv[1]}/.ddw-state.json"; s = json.load(open(p))
for k in ("tests", "sast"): s["gates"].pop(k, None)
json.dump(s, open(p, "w"))
PY
python3 "$TRC" --to VERIFY --action x --graph "$G" >/dev/null 2>&1 \
  && bad "corrective loop reused cleared gates" || ok "corrective loop must re-earn tests+sast"
export CLAUDE_PROJECT_DIR="$R"

V="$R/.ddw/scripts/validate-transition.py"
python3 - "$R" > "$R/ev.json" <<'PY'
import json, sys
repo = sys.argv[1]
bad = {"tier":"FEATURE","phase":"RELEASE","gates":{},"history":json.load(open(f"{repo}/.ddw-state.json"))["history"]}
print(json.dumps({"tool_name":"Write","tool_input":{"file_path":f"{repo}/.ddw-state.json","content":json.dumps(bad)}}))
PY
python3 "$V" --mode pre --state "$R/.ddw-state.json" --graph "$G" < "$R/ev.json" >/dev/null 2>&1 \
  && bad "PreToolUse should block a phase jump" || ok "PreToolUse blocks an illegal write (exit 2)"
python3 "$V" --mode post --state "$R/.ddw-state.json" --graph "$G" </dev/null >/dev/null 2>&1 \
  && ok "PostToolUse accepts a legal state on disk" || bad "PostToolUse rejects a legal state"

# ── The two Claude hook manifests must stay the same manifest ─────────────────
# One wires the drop-in install, the other the (in-progress) plugin. Same five
# hooks, different root variable. Two hand-maintained copies drift, and the one
# that drifts is the one nobody runs day to day.
python3 - "$SELF" <<'PY' && ok "the plugin hook manifest matches settings.json" || bad "the two Claude hook manifests have drifted"
import json, sys
root = sys.argv[1]
drop = open(f"{root}/adapters/claude/settings.json", encoding="utf-8").read()
plug = open(f"{root}/adapters/claude/plugin-hooks.json", encoding="utf-8").read()
normalize = lambda t: (t.replace("${CLAUDE_PROJECT_DIR}/.claude/hooks/", "@@")
                        .replace("${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/", "@@"))
a, b = json.loads(normalize(drop)), json.loads(normalize(plug))
# `_comment` is documentation living in a JSON file, not wiring. It is only in
# the plugin copy, where the finding it records — a foreign event name discards
# the whole file — has to be readable by whoever edits it next.
a.pop("_comment", None); b.pop("_comment", None)
assert a == b, "the hook sets differ once the root variable is normalized"
PY

# ── Upgrading must upgrade, and must not touch what you made yours ────────────
# The installer used to read any difference as "the user's file", so a DDW
# update silently left the repo running a mix of two versions — and blamed the
# user for a collision they had nothing to do with.
UP="$WORK/upgrade"; mkdir -p "$UP"; git -C "$UP" init -q .
bash "$SELF/install.sh" "$UP" --target claude >/dev/null 2>&1
# Simulating a newer DDW means mutating DDW. That was done in place on $SELF and
# restored afterwards — so an interrupted run (Ctrl-C, a failing check that
# aborts, two runs at once) left `<!-- upstream change -->` committed into the
# repo being published, with the backup already gone with $WORK. A test suite
# must not be able to damage the thing it tests. It mutates a copy now.
cp -R "$SELF" "$WORK/ddw-newer"
rm -rf "$WORK/ddw-newer/.git"
printf '\n<!-- upstream change -->\n' >> "$WORK/ddw-newer/skills/ddw-status/SKILL.md"
printf '\n<!-- the user made this theirs -->\n' >> "$UP/.claude/skills/ddw-test/SKILL.md"
bash "$WORK/ddw-newer/install.sh" "$UP" --target claude >/dev/null 2>&1
grep -q "upstream change" "$UP/.claude/skills/ddw-status/SKILL.md" \
  && ok "re-installing upgrades DDW's own files" \
  || bad "a DDW update did not reach the installed copy — the repo runs a mix of versions"
grep -q "the user made this theirs" "$UP/.claude/skills/ddw-test/SKILL.md" \
  && ok "re-installing leaves a file the user edited alone" \
  || bad "the installer overwrote the user's edit"

# ── Every adapter must actually refuse ────────────────────────────────────────
# The claim DDW makes is parity: same method, same enforcement, every tool. Two
# an adapter can return "allow" on an illegal write indefinitely — each has
# consumed the event before the validator could read it. Nothing caught it,
# because the suite tested the validator instead of the hooks that call it.
# So: drive each tool's REAL entry point, with that tool's OWN envelope shape.
ALL="$WORK/all"; mkdir -p "$ALL"; git -C "$ALL" init -q .
bash "$SELF/install.sh" "$ALL" --target all >/dev/null 2>&1

# The claim the whole "port it to another tool" exercise rests on: `.ddw/` is
# byte-identical no matter which tool you installed for. It stopped being true
# once the install manifest lived inside it — one file, and the demo that proves
# the method is portable printed a difference at the exact moment it should not.
section "The method is identical across tools"
ONE="$WORK/iso-claude"; mkdir -p "$ONE"; git -C "$ONE" init -q .
bash "$SELF/install.sh" "$ONE" --target claude >/dev/null 2>&1
diff -r "$ONE/.ddw" "$ALL/.ddw" >/dev/null 2>&1 \
  && ok ".ddw/ is byte-identical between a claude install and an all install" \
  || { bad ".ddw/ DIFFERS between two installs — 'the method does not change' is false"
       diff -r "$ONE/.ddw" "$ALL/.ddw" 2>&1 | head -5 | sed 's/^/      /'; }
[ -f "$ONE/.ddw-installed.json" ] \
  && ok "the install manifest sits at the repo root, outside the method" \
  || bad "no .ddw-installed.json at the root — the installer cannot tell an upgrade from your file"
[ -f "$ONE/.ddw/.installed.json" ] \
  && bad "the manifest is still inside .ddw/, which is what made the method differ" \
  || ok ".ddw/ carries no per-install bookkeeping"
printf '{"phase":"IDLE","tier":null,"gates":{},"history":[]}' > "$ALL/.ddw-state.json"

# Written to a file rather than piped: the gate can reach its verdict before
# draining stdin, and under `pipefail` the writer's EPIPE would be misread as
# the hook itself having failed.
EVENT="$WORK/event.json"
ddw_event() {   # $1 = envelope style, $2 = the state JSON being written
  python3 - "$1" "$ALL/.ddw-state.json" "$2" > "$EVENT" <<'PY'
import json, sys
style, path, content = sys.argv[1], sys.argv[2], sys.argv[3]
if style == "camel":
    print(json.dumps({"toolName": "write", "toolArgs": {"path": path, "content": content}}))
else:
    print(json.dumps({"tool_name": "write", "tool_input": {"file_path": path, "content": content}}))
PY
}
ddw_event_path() {   # $1 = envelope style, $2 = the file being written
  python3 - "$1" "$2" > "$EVENT" <<'PY'
import json, sys
style, path = sys.argv[1], sys.argv[2]
if style == "camel":
    print(json.dumps({"toolName": "write", "toolArgs": {"path": path, "content": "x = 1\n"}}))
else:
    print(json.dumps({"tool_name": "write", "tool_input": {"file_path": path, "content": "x = 1\n"}}))
PY
}
ILLEGAL='{"phase":"RELEASE","tier":"FEATURE","gates":{},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"RELEASE"}]}'
LEGAL='{"phase":"CLASSIFY","tier":null,"gates":{},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CLASSIFY","action":"classify"}]}'
IDLE_STATE='{"phase":"IDLE","tier":null,"gates":{},"history":[]}'
# The one rule the pipeline is built to guarantee. The FSM only ever guarded the
# state file, so PLAN forbidding source was a line in a prompt and nothing
# outside the model checked it. Both phases are exercised: a guard that refuses
# everything is as broken as one that refuses nothing.
IN_PLAN='{"phase":"PLAN","tier":"FEATURE","gates":{"define":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"PLAN"}]}'
IN_CODE='{"phase":"CODE","tier":"FEATURE","gates":{"define":true,"spec":true,"threat":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CODE"}]}'

check_adapter() {  # $1 = label, $2 = hook dir, $3 = envelope style, $4 = hook filename
  local label="$1" dir="$ALL/$2" style="$3" hook="${4:-pre-tool-use.sh}"
  if [ ! -f "$dir/$hook" ]; then bad "$label: no pre-write hook was installed"; return; fi
  ddw_event "$style" "$ILLEGAL"
  if (cd "$ALL" && CLAUDE_PROJECT_DIR="$ALL" bash "$dir/$hook" < "$EVENT") >/dev/null 2>&1; then
    bad "$label: an illegal transition was ALLOWED through the tool's own hook"
  else
    ok "$label refuses an illegal transition (exit 2)"
  fi
  ddw_event "$style" "$LEGAL"
  if (cd "$ALL" && CLAUDE_PROJECT_DIR="$ALL" bash "$dir/$hook" < "$EVENT") >/dev/null 2>&1; then
    ok "$label lets a legal transition through"
  else
    bad "$label blocks a LEGAL transition — enforcement that cries wolf gets turned off"
  fi

  printf '%s' "$IN_PLAN" > "$ALL/.ddw-state.json"
  ddw_event_path "$style" "$ALL/src/app.py"
  if (cd "$ALL" && CLAUDE_PROJECT_DIR="$ALL" bash "$dir/$hook" < "$EVENT") >/dev/null 2>&1; then
    bad "$label: source code was written in PLAN — 'no approved spec, no code' is not enforced"
  else
    ok "$label refuses product source while in PLAN"
  fi
  ddw_event_path "$style" "$ALL/docs/ddw/specs/spec-FEAT-001.md"
  if (cd "$ALL" && CLAUDE_PROJECT_DIR="$ALL" bash "$dir/$hook" < "$EVENT") >/dev/null 2>&1; then
    ok "$label still lets PLAN write its own artifacts"
  else
    bad "$label blocks PLAN from writing its own spec"
  fi
  printf '%s' "$IN_CODE" > "$ALL/.ddw-state.json"
  ddw_event_path "$style" "$ALL/src/app.py"
  if (cd "$ALL" && CLAUDE_PROJECT_DIR="$ALL" bash "$dir/$hook" < "$EVENT") >/dev/null 2>&1; then
    ok "$label lets source through once CODE was reached"
  else
    bad "$label blocks source in CODE — the guard refuses everything, which is its own failure"
  fi
  printf '%s' "$IDLE_STATE" > "$ALL/.ddw-state.json"
}
check_adapter "Claude Code"     ".claude/hooks"     snake validate-state-transition.sh
check_adapter "Codex CLI"       ".codex/hooks/ddw"  snake
check_adapter "Copilot CLI"     ".github/hooks/ddw" camel
check_adapter "Cursor"          ".cursor/hooks/ddw" snake
check_adapter "Gemini CLI"      ".gemini/hooks/ddw" snake

# ── The shared gate, driven as the tools drive it ─────────────────────────────
#
# Every check above this point that touched the FSM called validate() as a
# Python library. hook-gate.py — the file all six tools actually run — is a
# different caller, and it had drifted: it dropped the cap that makes one write
# mean one transition, so the whole pipeline in a single Write passed on every
# tool while this suite stayed green. These drive the entry point, not the
# library.
section "The shared gate itself"

GATE="$ALL/.ddw/scripts/hook-gate.py"
GST="$ALL/.ddw-state.json"
gate_pre() {  # $1 = dialect, stdin = event; echoes the exit code
  python3 "$GATE" --dialect "$1" --mode pre --state "$GST" --graph "$G" --repo "$ALL" \
    >/dev/null 2>&1; echo $?
}

WHOLE_RUN='{"tier":"FEATURE","phase":"RELEASE","gates":{"define":true,"spec":true,"threat":true,"tests":true,"sast":true,"verify":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-07-27T10:00:01Z","from":"CLASSIFY","to":"DEFINE","action":"a"},{"timestamp":"2026-07-27T10:00:02Z","from":"DEFINE","to":"PLAN","action":"a"},{"timestamp":"2026-07-27T10:00:03Z","from":"PLAN","to":"CODE","action":"a"},{"timestamp":"2026-07-27T10:00:04Z","from":"CODE","to":"VERIFY","action":"a"},{"timestamp":"2026-07-27T10:00:05Z","from":"VERIFY","to":"RELEASE","action":"a"}]}'

printf '%s' "$IDLE_STATE" > "$GST"
ddw_event snake "$WHOLE_RUN"
[ "$(gate_pre standard < "$EVENT")" = "2" ] \
  && ok "one write, one transition — through the gate the tools call" \
  || bad "ONE write declared the whole pipeline: the sequencing the machine exists for is gone"

# An internal error is not permission to proceed: exit 1 reads as "the hook
# errored" to every harness, and the write goes through.
printf '[]' > "$WORK/broken-graph.json"
python3 "$GATE" --mode pre --state "$GST" --graph "$WORK/broken-graph.json" --repo "$ALL" \
  < "$EVENT" >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "the gate fails CLOSED when it cannot reach a verdict" \
  || bad "the gate exits 1 on an internal error — every harness reads that as 'the hook errored' and allows the write"

# Lexical paths: a symlinked component named the same guarded file under a name
# the gate did not recognise.
printf '%s' "$IN_PLAN" > "$GST"
ln -sfn . "$ALL/selflink"
ddw_event_path snake "$ALL/selflink/src/app.py"
[ "$(gate_pre standard < "$EVENT")" = "2" ] \
  && ok "a symlinked path cannot smuggle product source past the guard" \
  || bad "a symlink in the path defeated the source guard — resolve with realpath, not abspath"
ddw_event snake "$WHOLE_RUN"
python3 - "$ALL/selflink/.ddw-state.json" "$WHOLE_RUN" > "$EVENT" <<'PY'
import json, sys
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": sys.argv[1], "content": sys.argv[2]}}))
PY
[ "$(gate_pre standard < "$EVENT")" = "2" ] \
  && ok "a symlinked path cannot smuggle an illegal state past the FSM" \
  || bad "a symlink in the path bypassed the FSM entirely"
rm -f "$ALL/selflink"

# A decoy path next to the real one: the gate judged whichever key it found
# first, and the tools read a different key.
printf '%s' "$IN_PLAN" > "$GST"
python3 - "$ALL" > "$EVENT" <<'PY'
import json, os, sys
root = sys.argv[1]
print(json.dumps({"tool_name": "write", "tool_input": {
    "file_path": os.path.join(root, "docs", "ok.md"),
    "path": os.path.join(root, "src", "app.py"), "content": "x"}}))
PY
[ "$(gate_pre standard < "$EVENT")" = "2" ] \
  && ok "every path the event names is judged, not just the first one" \
  || bad "a harmless decoy path bought a write for the real one beside it"

# A path that is present but is not a string cannot be judged, and unjudgeable
# is not permitted.
printf '{"tool_name":"Write","tool_input":{"file_path":["src/app.py"],"content":"x"}}' > "$EVENT"
[ "$(gate_pre standard < "$EVENT")" = "2" ] \
  && ok "a non-string path is refused rather than waved through" \
  || bad "a typed-but-wrong path emptied the check and allowed the write"

# A corrupt state used to read as a fresh IDLE — which defeats append-only:
# corrupt the file first, then write any history you like over the "empty" one.
printf 'not json at all' > "$GST"
ddw_event_path snake "$ALL/src/app.py"
[ "$(gate_pre standard < "$EVENT")" = "2" ] \
  && ok "an unreadable state refuses the write instead of assuming IDLE" \
  || bad "a corrupt state disabled the guard — a phase it cannot read is one it cannot vouch for"
python3 "$GATE" --mode post --state "$GST" --graph "$G" --repo "$ALL" </dev/null >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "post mode refuses an unreadable state" \
  || bad "post mode waved a corrupt state through — it is the only net against the Bash/jq bypass"

# Relative paths must anchor to the repo. Resolved against the hook's cwd, every
# relative path escaped both guards the moment the harness ran from elsewhere.
printf '%s' "$IN_PLAN" > "$GST"
printf '{"tool_name":"Write","tool_input":{"file_path":"src/app.py","content":"x"}}' > "$EVENT"
(cd / && python3 "$GATE" --mode pre --state "$GST" --graph "$G" --repo "$ALL" < "$EVENT") \
  >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "a relative path resolves against the repo, not the hook's working directory" \
  || bad "a relative path judged from another cwd escaped the guard"

# The two dialects whose real envelope we had never actually parsed.
python3 - "$ALL" > "$EVENT" <<'PY'
import json, os, sys
# GitHub documents toolArgs as a JSON STRING for external command hooks.
args = json.dumps({"path": os.path.join(sys.argv[1], "src", "app.py"), "content": "x"})
print(json.dumps({"toolName": "create", "toolArgs": args}))
PY
[ "$(gate_pre copilot < "$EVENT")" = "2" ] \
  && ok "Copilot: toolArgs arrives as a JSON string and is parsed" \
  || bad "Copilot's real envelope is double-encoded; unparsed it leaves no path and allows everything"

# Copilot's INTERACTIVE write is apply_patch with toolArgs as the raw patch
# text — not JSON. Captured live from 1.0.75 after src/probe3.ts landed in
# DEFINE with the hook invoked and blind: json.loads failed, no path, allow.
python3 - "$ALL" > "$EVENT" <<'PY'
import json, os, sys
patch = "*** Begin Patch\n*** Add File: src/app.py\n+x = 1\n*** End Patch"
print(json.dumps({"toolName": "apply_patch", "toolArgs": patch}))
PY
[ "$(gate_pre copilot < "$EVENT")" = "2" ] \
  && ok "Copilot: an apply_patch write with raw-text toolArgs is judged, not waved through" \
  || bad "Copilot's interactive writes (apply_patch, raw toolArgs) sail past the gate — the M4 hole is open"

# The other half of that hole: a LEGAL state creation through the same envelope
# was refused for carrying no content, and the refusal pushed the model to a
# shell heredoc — the write path that is only detected, never prevented. An Add
# File patch IS its file; the gate reads the + lines as the content.
APR="$WORK/apr-state"; mkdir -p "$APR"; git -C "$APR" init -q . >/dev/null 2>&1 || true
python3 - > "$EVENT" <<'PY'
import json
state = json.dumps({"tier": None, "phase": "CLASSIFY", "ticket": None, "title": None,
                    "tracker": None, "gates": {}, "block": None, "discovery": None,
                    "history": [{"timestamp": "2026-07-29T20:00:00Z", "from": "IDLE",
                                 "to": "CLASSIFY", "action": "abrir"}]}, indent=2)
patch = ("*** Begin Patch\n*** Add File: .ddw-state.json\n"
         + "\n".join("+" + l for l in state.splitlines()) + "\n*** End Patch")
print(json.dumps({"toolName": "apply_patch", "toolArgs": patch}))
PY
python3 "$SELF/ddw/scripts/hook-gate.py" --dialect copilot --mode pre \
  --state "$APR/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" --repo "$APR" \
  < "$EVENT" >/dev/null 2>&1
[ "$?" = "0" ] \
  && ok "and a LEGAL state creation through that envelope is allowed — no shell-heredoc push" \
  || bad "a legal state write via apply_patch is refused; the refusal drives the model to the undetectable-in-advance shell path"

# Validation stopped being a model-rendered report the day a live run loaded
# create-prd and validate-prd together and "validated" in prose. The script IS
# the validation; PASSED writes a content-hashed receipt; the define gate
# demands it wherever the ticket's PRD exists on disk.
VP="$WORK/vp"; mkdir -p "$VP/docs/ddw/prd"
cat > "$VP/docs/ddw/prd/prd-FEAT-001.md" <<'PRDEOF'
# PRD FEAT-001: Prueba

## Context and Problem
Contexto minimo.

## Goals
- Reducir 30% el tiempo.

## Functional Requirements
- FR-01: El sistema debe exponer un formulario.

## Non-Functional Requirements
- NFR-01: Carga en < 3 s p95.

## Acceptance Criteria
- AC-01 (FR-01): WHEN un usuario abre el formulario, THE sistema SHALL mostrarlo.
- AC-02 (FR-01): IF el envio falla, THEN THE sistema SHALL conservar el texto.

## Out of Scope
- Login de estudiantes.

## Dependencies
- Proveedor de IA.

## Risks and Mitigations
- Riesgo: spam.
PRDEOF
# `compgen -G`, not `ls <glob>`: this file sets nullglob, under which a pattern
# that matches nothing expands to NOTHING — so `ls dir/prd-validated-*` becomes
# a bare `ls`, lists the working directory, and exits 0. The check could not
# fail. compgen expands the pattern itself and returns 1 when nothing matches.
python3 "$SELF/ddw/scripts/validate_prd.py" "$VP/docs/ddw/prd/prd-FEAT-001.md" --tier FEATURE >/dev/null 2>&1 \
  && compgen -G "$VP/.ddw-sessions/prd-validated-*" >/dev/null \
  && ok "validate_prd.py passes a sound PRD and leaves the content-hashed receipt" \
  || bad "the validator rejects a sound PRD or writes no receipt — validation is back to being prose"
sed 's/debe exponer/deberia exponer/' "$VP/docs/ddw/prd/prd-FEAT-001.md" > "$VP/broken.md"
VPOUT="$(python3 "$SELF/ddw/scripts/validate_prd.py" "$VP/broken.md" --tier FEATURE 2>/dev/null || true)"
case "$VPOUT" in
  *"F-PRD-06"*"FR-01"*) ok "and it names the broken rule by ID — the checklist is script output, not model courtesy" ;;
  *) bad "an ambiguous verb sailed through the mechanical validator" ;;
esac
printf '%s' '{"tier":"FEATURE","phase":"DEFINE","ticket":"FEAT-001","title":null,"tracker":null,"gates":{},"block":null,"discovery":null,"history":[{"timestamp":"2026-07-29T20:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-07-29T20:01:00Z","from":"CLASSIFY","to":"DEFINE","action":"b","tier":"FEATURE","ticket":"FEAT-001"}]}' > "$VP/.ddw-state.json"
# Not `sed -i`: BSD sed reads the next argument as a backup suffix, so on macOS
# this edited nothing, the receipt stayed fresh, and the gate opened — the check
# reported the defect it exists to prove is gone.
python3 - "$VP/docs/ddw/prd/prd-FEAT-001.md" <<'PYPRD'
import sys
p = sys.argv[1]
t = open(p, encoding="utf-8").read().replace("debe exponer", "deberia exponer")
open(p, "w", encoding="utf-8").write(t)
PYPRD
python3 "$SELF/ddw/scripts/transition.py" --to PLAN --action p --gate define \
  --state "$VP/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "the define gate refuses when the PRD on disk has no fresh receipt — validated is a fact, not a claim" \
  || bad "the define gate opened on an unvalidated PRD; loading two skills as reading material passes again"

# The helper is the cooperative path. The receipt lived ONLY there, so the same
# state written with the Write tool — judged by the hook, which is the thing that
# cannot be talked past — was allowed: exit 2 through the helper, exit 0 through
# the hook. The one gate resting on evidence rested on the model choosing to ask.
VPSTATE='{"tier":"FEATURE","phase":"PLAN","ticket":"FEAT-001","title":null,"tracker":null,"gates":{"define":true},"block":null,"discovery":null,"history":[{"timestamp":"2026-07-29T20:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-07-29T20:01:00Z","from":"CLASSIFY","to":"DEFINE","action":"b","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:02:00Z","from":"DEFINE","to":"PLAN","action":"c","tier":"FEATURE","ticket":"FEAT-001"}]}'
python3 - "$VP" "$VPSTATE" > "$VP/ev.json" <<'PYEV'
import json, sys
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": sys.argv[1] + "/.ddw-state.json",
                                 "content": sys.argv[2]}}))
PYEV
python3 "$SELF/ddw/scripts/validate-transition.py" --mode pre --state "$VP/.ddw-state.json" \
  --graph "$SELF/ddw/rules/transition-graph.json" < "$VP/ev.json" >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "and the hook refuses it too — the receipt is not optional for a model that writes the state itself" \
  || bad "a plain Write of the same state opens the define gate with no receipt: the guarantee has a way around it"

# The refusal is the most-read sentence this product has, and nothing read it.
# The reason carried a `DDW: ` of its own while every caller adds one — the
# helper stripped it back out by hand, the hook did not, and a live run showed
# `DDW blocked this write: DDW: the define gate…`. Prefixing belongs to whoever
# is speaking, once; a workaround in one caller is not a fix in the other.
VPMSG="$(python3 "$SELF/ddw/scripts/validate-transition.py" --mode pre --state "$VP/.ddw-state.json" \
  --graph "$SELF/ddw/rules/transition-graph.json" < "$VP/ev.json" 2>&1 >/dev/null)"
case "$VPMSG" in
  *"DDW blocked this write: the "*gate*"validation receipt"*)
    ok "and the refusal reads as one sentence — the reason carries no prefix of its own" ;;
  *"write: DDW:"*|*"DDW: DDW:"*)
    bad "the refusal doubles its prefix — the user reads 'DDW blocked this write: DDW: …'" ;;
  *) bad "the refusal no longer names the missing receipt: $VPMSG" ;;
esac

# The shell never reaches a write tool. Post mode is where that write is caught,
# and it asks about the edge the journal has not seen yet — never about the ones
# it already recorded, or editing a PRD two phases later would brick the session.
printf '%s' "$VPSTATE" > "$VP/.ddw-state.json"
python3 "$SELF/ddw/scripts/validate-transition.py" --mode post --state "$VP/.ddw-state.json" \
  --graph "$SELF/ddw/rules/transition-graph.json" >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "and a state written through the shell is caught by the post net for the same missing receipt" \
  || bad "jq/sed writes the state, the define gate opens with no receipt, and nothing objects"

# The receipt has to OPEN the gate, or the check above proves only that the gate
# is shut. A guard that never lets anything through is not a guard.
#
# The PRD is put back first: what broke the receipt was an edit that ALSO makes
# the PRD fail validation, so validating the broken one writes no receipt and
# this would read as "the gate never opens" when nothing was ever offered to it.
python3 - "$VP/docs/ddw/prd/prd-FEAT-001.md" <<'PYFIX'
import sys
p = sys.argv[1]
t = open(p, encoding="utf-8").read().replace("deberia exponer", "debe exponer")
open(p, "w", encoding="utf-8").write(t)
PYFIX
python3 "$SELF/ddw/scripts/validate_prd.py" "$VP/docs/ddw/prd/prd-FEAT-001.md" --tier FEATURE >/dev/null 2>&1
python3 "$SELF/ddw/scripts/validate-transition.py" --mode post --state "$VP/.ddw-state.json" \
  --graph "$SELF/ddw/rules/transition-graph.json" >/dev/null 2>&1 \
  && ok "and validating again opens it: the receipt is what the gate is asking for" \
  || bad "the gate stays shut with a fresh receipt on disk — the pipeline cannot proceed at all"

# ── The other three artifacts earn receipts the same way ──────────────────────
#
# `spec`, `threat` and `verify` were booleans the model wrote about its own work.
# RATIONALE decision 16 said they could follow `define` the day their validators
# wrote receipts, and these are those validators. What each check proves is the
# same shape three times: a sound artifact PASSES and leaves a content-hashed
# receipt, a broken one is refused BY RULE ID, and the gate is shut without the
# receipt and open with it.
VS="$VP/docs/ddw/specs"; mkdir -p "$VS"
cat > "$VS/spec-FEAT-001.md" <<'SPECEOF'
# Spec FEAT-001: Ingesta

| Field | Value |
|-------|-------|
| Ticket | FEAT-001 |
| PRD | docs/ddw/prd/prd-FEAT-001.md |
| Tier | FEATURE |

## Summary
Formulario publico con persistencia.

## Coverage: PRD → blocks
| Requirement | Covered by |
|---|---|
| FR-01 | Block 1 |
| NFR-01 | Strategy: render server-side sin bundle JS, medido p95 bajo 3 s |

## Dependencies between blocks
Block 1 no depende de nadie.

## Block 1 — Formulario publico

**Files**
- `app/routes/public.py` (new) — rutas del formulario

**Logic**
Implementa FR-01.

**API contract**
- Method + path: `POST /tickets`
- Request: titulo (str), email (str)
- Response: id (int)
- Error codes: 400, 422
- Auth: publico, sin autenticacion

**Data model**
- Entidad ticket: id (PK), titulo (not null), estado (default "Pendiente"), index en estado.

**Input validation**
- titulo: str, max 200, requerido.

**Error handling**
- 400 cuando falta un campo requerido.
- 422 cuando el email tiene formato invalido.

**Required tests**
- [ ] test_form_visible — validates AC-01
- [ ] test_campo_faltante_devuelve_400 — validates AC-02, campo requerido faltante
- [ ] test_email_invalido_devuelve_422 — email con formato invalido

**Completion criterion**
Pasan los tres tests y el POST devuelve 201.

## Rollback
La tabla se crea vacia y se descarta; no hay migracion inversa.
SPECEOF
python3 "$SELF/ddw/scripts/validate_spec.py" "$VS/spec-FEAT-001.md" --tier FEATURE >/dev/null 2>&1 \
  && compgen -G "$VP/.ddw-sessions/spec-validated-*" >/dev/null \
  && ok "validate_spec.py passes a sound spec and leaves the content-hashed receipt" \
  || bad "the spec validator rejects a sound spec or writes no receipt — the spec gate has nothing to rest on"
python3 - "$VS/spec-FEAT-001.md" "$VS/broken.md" <<'PYSPEC'
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
open(sys.argv[2], "w", encoding="utf-8").write(
    re.sub(r"\*\*Required tests\*\*.*?\n\n", "", t, flags=re.S))
PYSPEC
VSOUT="$(python3 "$SELF/ddw/scripts/validate_spec.py" "$VS/broken.md" --tier FEATURE \
        --prd "$VP/docs/ddw/prd/prd-FEAT-001.md" 2>/dev/null || true)"
case "$VSOUT" in
  *"F-SPEC-06"*"Block 1"*) ok "and it names the block with no tests by rule ID — the checklist is script output, not model courtesy" ;;
  *) bad "a block with no tests sailed through the mechanical spec validator" ;;
esac

# F-SPEC-16 is the rule that stops a spec passing PLAN with a full error section
# and a happy-path-only test list. It was catalogued, named in the skill, and
# nothing exercised it: the mutation that switched the count off survived the
# whole suite. This is that check — two documented errors, one happy-path test.
python3 - "$VS/spec-FEAT-001.md" "$VS/spec-untested-errors.md" <<'PY16'
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
for line in ("- [ ] test_campo_faltante_devuelve_400 — validates AC-02, campo requerido faltante\n",
             "- [ ] test_email_invalido_devuelve_422 — email con formato invalido\n"):
    t = t.replace(line, "")
open(sys.argv[2], "w", encoding="utf-8").write(t)
PY16
V16OUT="$(python3 "$SELF/ddw/scripts/validate_spec.py" "$VS/spec-untested-errors.md" --tier FEATURE \
         --prd "$VP/docs/ddw/prd/prd-FEAT-001.md" 2>/dev/null || true)"
case "$V16OUT" in
  *"F-SPEC-16"*"2 error(s), 0 test(s)"*)
    ok "F-SPEC-16 counts a block's documented errors against the tests that name one" ;;
  *) bad "a block documented two errors and tested neither, and F-SPEC-16 said nothing" ;;
esac

# The FIX path is a different document with a different shape — no `## Block`
# headings, no PRD to trace to, and two rules of its own. It went untested while
# the FEATURE path was green, and every fix-plan failed for the absence of a PRD
# its tier does not produce.
cat > "$VS/fix-FIX-002.md" <<'FIXEOF'
# Fix-plan FIX-002: El envio pierde el texto

| Field | Value |
|-------|-------|
| Ticket | FIX-002 |
| Tier | FIX |

## Problem
Al fallar la validacion, el formulario se re-renderiza vacio.

## Root cause
El handler construye un contexto nuevo en vez de reusar el body recibido.

## Solution — steps
1. `app/routes/public.py:42` — pasar el body al contexto de re-render.

## Dependencies between steps
Ninguna: es un solo paso.

## Error handling
- 422 con el formulario repoblado cuando el email es invalido.

## Tests
- test_regression_envio_invalido_conserva_texto — regression del bug original, entrada invalida.

## Rollback plan
Revertir el commit; el cambio es de una linea.
FIXEOF
python3 "$SELF/ddw/scripts/validate_spec.py" "$VS/fix-FIX-002.md" --tier FIX >/dev/null 2>&1 \
  && ok "validate_spec.py passes a sound fix-plan: FIX answers to an RCA, not to a PRD" \
  || bad "a sound fix-plan is refused — the FIX tier cannot leave PLAN at all"
grep -v -A 2 '^## Rollback plan' "$VS/fix-FIX-002.md" > "$VS/fix-norollback.md"
VFOUT="$(python3 "$SELF/ddw/scripts/validate_spec.py" "$VS/fix-norollback.md" --tier FIX 2>/dev/null || true)"
case "$VFOUT" in
  *"F-SPEC-15"*) ok "and a fix-plan with no rollback plan is named by its rule ID" ;;
  *) bad "a FIX reached CODE with no rollback plan and nothing said so" ;;
esac

VTM="$VP/docs/ddw/security"; mkdir -p "$VTM"
cat > "$VTM/threat-FEAT-001.md" <<'TMEOF'
# Threat model FEAT-001

| Field | Value |
|-------|-------|
| Ticket | FEAT-001 |
| Spec | docs/ddw/specs/spec-FEAT-001.md |

## Components
| Component | Source in the spec |
|---|---|
| `app/routes/public.py` | Block 1 |

## Trust boundaries
- Internet publico → servidor: entra el formulario anonimo.

## STRIDE analysis
### `app/routes/public.py`
- **Spoofing:** el formulario es anonimo; no hay identidad que suplantar.
- **Tampering:** validacion server-side y parametros ligados.
- **Repudiation:** se registra fecha y hash de IP.
- **Information Disclosure:** la respuesta no expone otros tickets.
- **Denial of Service:** rate limit por IP.
- **Elevation of Privilege:** la ruta no expone backoffice.

## Data classification
| Data | Class | At rest | In transit |
|---|---|---|---|
| email | PII | cifrado en disco | TLS 1.3 |

## Risks and mitigations
| ID | Risk | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| R-01 | Spam masivo | D | High | Medium | rate limit + captcha |

## Supply chain
Dependencias fijadas en el lockfile.
TMEOF
python3 "$SELF/ddw/scripts/validate_threat.py" "$VTM/threat-FEAT-001.md" --tier FEATURE >/dev/null 2>&1 \
  && compgen -G "$VP/.ddw-sessions/threat-validated-*" >/dev/null \
  && ok "validate_threat.py passes a sound threat model and leaves the content-hashed receipt" \
  || bad "the threat validator rejects a sound model or writes no receipt"
grep -v 'Repudiation' "$VTM/threat-FEAT-001.md" > "$VTM/broken.md"
VTOUT="$(python3 "$SELF/ddw/scripts/validate_threat.py" "$VTM/broken.md" --tier FEATURE \
        --spec "$VS/spec-FEAT-001.md" 2>/dev/null || true)"
case "$VTOUT" in
  *"F-TM-01"*Repudiation*) ok "and a missing STRIDE category is named — a five-sixths analysis is not one" ;;
  *) bad "a component analysed against five of the six STRIDE categories passed" ;;
esac

# SAST. Nineteen rules were catalogued here and none of them ran: the report was
# the model's to write and the gate turned true on its say-so. What the receipt
# attests is the REPORT — categories judged, findings located, the verdict
# consistent with the severities, suppressions documented and in date — never
# the code, which DDW does not read.
cat > "$VTM/sast-FEAT-001.md" <<'SASTEOF'
# SAST FEAT-001

| Rule | Verdict | Notes |
|---|---|---|
| F-SAST-01 | ✅ | sin secretos embebidos; la key sale de .env |
| F-SAST-02 | ✅ | consultas parametrizadas |
| F-SAST-03 | ✅ | no se invoca la shell |
| F-SAST-04 | ✅ | sin pickle ni yaml.load |
| F-SAST-05 | ✅ | rutas no controladas por el usuario |
| F-SAST-06 | ✅ | salida escapada |
| F-SAST-07 | ✅ | sin fetch dirigido por entrada del usuario |
| F-SAST-08 | ✅ | bcrypt costo 12 |
| F-SAST-09 | ✅ | debug apagado en producción |
| F-SAST-10 | ✅ | sin PII en los logs |
| F-SAST-11 | ✅ | este ticket no sube archivos |
| F-SAST-12 | ✅ | token CSRF en el formulario público |
| F-SAST-13 | ✅ | auditoría de dependencias limpia |
| F-SAST-14 | ❌ | app/routes/tickets.py:41 — largo del email sin cota |
| F-SAST-15 | ✅ | los errores devuelven un 500 genérico |
| F-SAST-16 | ✅ | sin CVE Medium |
| F-SAST-17 | ✅ | sin eval ni exec |

Total: 16 clean, 1 vulnerability (0 critical, 0 high)
Result: PASSED

### Suppression: F-SAST-14

| Field | Value |
|---|---|
| File | app/routes/tickets.py:41 |
| Category | incomplete input validation |
| Disposition | ACCEPTED_RISK |
| Reviewer | Pablo Di Loreto |
| Date | 2026-08-02 |
| Justification | El validador de email ya lo acota a 254 caracteres. |
| Compensating control | Rate limit por IP en el endpoint público. |
| Review by | 2026-12-01 |
SASTEOF
python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-FEAT-001.md" --tier FEATURE --today 2026-08-02 >/dev/null 2>&1 \
  && compgen -G "$VP/.ddw-sessions/sast-validated-*" >/dev/null \
  && ok "validate_sast.py passes a complete SAST report and leaves the content-hashed receipt" \
  || bad "the SAST validator rejects a complete report or writes no receipt"

# The one contradiction a complete report can still contain, and the one that
# matters: a Critical listed above a PASSED verdict advances the phase.
python3 - "$VTM" <<'PYSAST'
import sys, os
p = os.path.join(sys.argv[1], "sast-FEAT-001.md")
s = open(p, encoding="utf-8").read().replace(
    "| F-SAST-01 | ✅ | sin secretos embebidos; la key sale de .env |",
    "| F-SAST-01 | ❌ | app/config.py:9 — API key embebida |")
open(os.path.join(sys.argv[1], "sast-critical.md"), "w", encoding="utf-8").write(s)
PYSAST
VSAOUT="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-critical.md" --tier FEATURE \
         --today 2026-08-02 2>/dev/null || true)"
case "$VSAOUT" in
  *"F-SAST-VERDICT"*BLOCKED*) ok "and a Critical finding above a PASSED verdict is refused, by the rule that fixes severities" ;;
  *) bad "a report listing a hardcoded secret and declaring PASSED earned a receipt" ;;
esac

# A category with no verdict was not evaluated, and silence is the shape an
# unrun check takes. This is the rule the other nineteen were waiting for.
grep -v 'F-SAST-07' "$VTM/sast-FEAT-001.md" > "$VTM/sast-gap.md"
VSGOUT="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-gap.md" --tier FEATURE \
         --today 2026-08-02 2>/dev/null || true)"
case "$VSGOUT" in
  *"F-SAST-COVERAGE"*F-SAST-07*) ok "and a category left with no verdict is named, not averaged away" ;;
  *) bad "a report that never judged SSRF passed as complete" ;;
esac

# F-SAST-19 reads the clock from the document. A suppression whose review date
# has passed is an unreviewed finding wearing a review.
python3 - "$VTM" <<'PYSUP'
import sys, os
p = os.path.join(sys.argv[1], "sast-FEAT-001.md")
s = open(p, encoding="utf-8").read().replace("2026-12-01", "2026-01-01")
open(os.path.join(sys.argv[1], "sast-expired.md"), "w", encoding="utf-8").write(s)
PYSUP
VSEOUT="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-expired.md" --tier FEATURE \
         --today 2026-08-02 2>/dev/null || true)"
case "$VSEOUT" in
  *"F-SAST-19"*) ok "and a suppression past its review date is refused — six months is the catalog's number" ;;
  *) bad "a suppression that expired seven months ago still opened the gate" ;;
esac

VRP="$VP/docs/ddw/reports"; mkdir -p "$VRP"
cat > "$VRP/verify-FEAT-001.md" <<'VEREOF'
# Verify FEAT-001

## Acceptance criteria
- AC-01 — test_form_visible: PASSED
- AC-02 — test_campo_faltante_devuelve_400 y test_email_invalido_devuelve_422: PASSED (sad path, entrada invalida)

## Blocks
- Block 1 — implementado completo.

## Tests
- test_form_visible: passed
- test_campo_faltante_devuelve_400: passed
- test_email_invalido_devuelve_422: passed

## Coverage
- line: 94%
- branch: 91%
- function: 100%

## Lint
ruff sin errores, mypy sin errores.
VEREOF
python3 "$SELF/ddw/scripts/validate_verify.py" "$VRP/verify-FEAT-001.md" --tier FEATURE >/dev/null 2>&1 \
  && compgen -G "$VP/.ddw-sessions/verify-validated-*" >/dev/null \
  && ok "validate_verify.py passes a complete verdict and leaves the content-hashed receipt" \
  || bad "the verify validator rejects a complete verdict or writes no receipt"
sed 's/- line: 94%/- line: 61%/' "$VRP/verify-FEAT-001.md" > "$VRP/broken.md"
VVOUT="$(python3 "$SELF/ddw/scripts/validate_verify.py" "$VRP/broken.md" --tier FEATURE \
        --prd "$VP/docs/ddw/prd/prd-FEAT-001.md" --spec "$VS/spec-FEAT-001.md" 2>/dev/null || true)"
case "$VVOUT" in
  *"F-VER-03"*"61%"*) ok "and coverage under the minimum is named with its number" ;;
  *) bad "a verdict reporting 61% line coverage passed the 80% floor" ;;
esac

# The three gates, driven through the hook — the thing that cannot be talked
# past. Same proof as the define gate's: shut without the receipt, open with it.
# The artifact is edited rather than deleted, because a missing file is not what
# these gates are about: a STALE receipt is.
#
# The loop variables are prefixed. `G` and `GATE` are the suite's own — the
# graph path and the hook path — and a bare `for G in …` here silently rebound
# both for every check that came after, which is a whole class of green turning
# red for reasons that have nothing to do with the code under test.
for RCP_ROW in spec:specs:spec:PLAN:CODE threat:security:threat:PLAN:CODE sast:security:sast:CODE:VERIFY verify:reports:verify:VERIFY:RELEASE; do
  RCP_GATE="${RCP_ROW%%:*}"; RCP_REST="${RCP_ROW#*:}"
  RCP_DIR="${RCP_REST%%:*}"; RCP_REST="${RCP_REST#*:}"
  RCP_STEM="${RCP_REST%%:*}"; RCP_REST="${RCP_REST#*:}"
  RCP_FROM="${RCP_REST%%:*}"; RCP_TO="${RCP_REST##*:}"
  printf '\n<!-- edited after validating -->\n' >> "$VP/docs/ddw/$RCP_DIR/$RCP_STEM-FEAT-001.md"
  python3 - "$VP" "$RCP_GATE" "$RCP_FROM" "$RCP_TO" > "$VP/gev.json" <<'PYGATE'
import json, sys
root, gate, frm, to = sys.argv[1:5]
LADDER = ["define", "spec", "threat", "tests", "sast", "verify"]
EDGE_GATES = {"CODE": ["spec", "threat"], "VERIFY": ["tests", "sast"], "RELEASE": ["verify"]}
EDGES = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN"),
         ("PLAN", "CODE"), ("CODE", "VERIFY"), ("VERIFY", "RELEASE")]
# The gate under test must be claimed BY THIS WRITE. Evidence is checked for the
# gates a write newly claims — a state that already had them all asked nothing of
# the receipt, and the check passed while proving the opposite of its own name.
cut = LADDER.index(gate)
old_gates = {g: True for g in LADDER[:cut]}
new_gates = dict(old_gates, **{g: True for g in LADDER[:cut + 1] + EDGE_GATES[to]})
def history(upto):
    out = []
    for i, (f, t) in enumerate(EDGES):
        entry = {"timestamp": "2026-07-29T20:0%d:00Z" % i, "from": f, "to": t, "action": "s"}
        if i:
            entry.update(tier="FEATURE", ticket="FEAT-001")
        out.append(entry)
        if t == upto:
            break
    return out
def state(phase, gates):
    return {"tier": "FEATURE", "phase": phase, "ticket": "FEAT-001", "title": None,
            "tracker": None, "gates": gates, "block": None, "discovery": None,
            "history": history(phase)}
# The state ON DISK is the phase before the edge. One write, one transition: an
# event that appended the whole run at once was refused for the SEQUENCING and
# never reached the evidence check — a green that proved nothing.
open(root + "/.ddw-state.json", "w").write(json.dumps(state(frm, old_gates)))
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": root + "/.ddw-state.json",
                                 "content": json.dumps(state(to, new_gates))}}))
PYGATE
  python3 "$SELF/ddw/scripts/validate-transition.py" --mode pre --state "$VP/.ddw-state.json" \
    --graph "$SELF/ddw/rules/transition-graph.json" --repo "$VP" < "$VP/gev.json" >/dev/null 2>&1
  [ "$?" = "2" ] \
    && ok "the $RCP_GATE gate refuses when its artifact was edited after validating" \
    || bad "the $RCP_GATE gate opened on an artifact whose receipt is stale — the boolean is back"
  # No --prd/--spec: each validator finds its counterpart from the header table
  # or the filename convention, and this is also the check that it can.
  python3 "$SELF/ddw/scripts/validate_$RCP_GATE.py" \
    "$VP/docs/ddw/$RCP_DIR/$RCP_STEM-FEAT-001.md" --tier FEATURE >/dev/null 2>&1
  python3 "$SELF/ddw/scripts/validate-transition.py" --mode pre --state "$VP/.ddw-state.json" \
    --graph "$SELF/ddw/rules/transition-graph.json" --repo "$VP" < "$VP/gev.json" >/dev/null 2>&1 \
    && ok "and validating again opens it — the receipt is what the $RCP_GATE gate is asking for" \
    || bad "the $RCP_GATE gate stays shut with a fresh receipt on disk"
done

# QUICK-FIX has no PLAN and no VERIFY. A validator that shrugged and passed the
# artifact it was handed would mint a receipt for a phase that never ran.
for RCP_V in spec threat verify; do
  python3 "$SELF/ddw/scripts/validate_$RCP_V.py" "$VS/spec-FEAT-001.md" --tier QUICK-FIX >/dev/null 2>&1
  [ "$?" = "3" ] \
    && ok "validate_$RCP_V.py refuses QUICK-FIX instead of passing it: that tier has no such phase" \
    || bad "validate_$RCP_V.py returned a verdict for a tier whose phase does not exist"
done

# ── The commit gate asks git, not the model ───────────────────────────────────
#
# Tracked changes only: untracked files are the build output and the scratch
# file of every real repository, and a closeout nobody can satisfy honestly is
# the one thing this repo holds to be worse than no gate at all.
CG="$WORK/commit-gate"; mkdir -p "$CG"; git -C "$CG" init -q .
git -C "$CG" config user.email ddw@example.com; git -C "$CG" config user.name DDW
bash "$SELF/install.sh" "$CG" --target claude >/dev/null 2>&1
printf 'v1\n' > "$CG/src.txt"; git -C "$CG" add -A >/dev/null 2>&1
git -C "$CG" commit -qm base >/dev/null 2>&1
CG_REL='{"tier":"FEATURE","phase":"RELEASE","ticket":"FEAT-001","title":null,"tracker":null,"gates":{"define":true,"spec":true,"threat":true,"tests":true,"sast":true,"verify":true},"block":null,"discovery":null,"history":[{"timestamp":"2026-07-29T20:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-07-29T20:01:00Z","from":"CLASSIFY","to":"DEFINE","action":"b","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:02:00Z","from":"DEFINE","to":"PLAN","action":"c","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:03:00Z","from":"PLAN","to":"CODE","action":"d","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:04:00Z","from":"CODE","to":"VERIFY","action":"e","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:05:00Z","from":"VERIFY","to":"RELEASE","action":"f","tier":"FEATURE","ticket":"FEAT-001"}]}'
printf '%s' "$CG_REL" > "$CG/.ddw-state.json"
python3 - "$CG" "$CG_REL" > "$CG/ev.json" <<'PYCG'
import json, sys
state = json.loads(sys.argv[2])
state["gates"]["commit"] = True
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": sys.argv[1] + "/.ddw-state.json",
                                 "content": json.dumps(state)}}))
PYCG
CGV="$SELF/ddw/scripts/validate-transition.py"; CGG="$SELF/ddw/rules/transition-graph.json"
python3 "$CGV" --mode pre --state "$CG/.ddw-state.json" --graph "$CGG" < "$CG/ev.json" >/dev/null 2>&1 \
  && ok "the commit gate opens on a clean tree" \
  || bad "the commit gate refuses work that IS committed — a gate nobody can satisfy is worse than no gate"
printf 'v2\n' > "$CG/src.txt"
CGOUT="$(python3 "$CGV" --mode pre --state "$CG/.ddw-state.json" --graph "$CGG" < "$CG/ev.json" 2>&1 >/dev/null || true)"
case "$CGOUT" in
  *"src.txt"*) ok "and refuses it with the file named when tracked work is still uncommitted" ;;
  *) bad "gates.commit can be claimed over uncommitted work: the ticket closes on something only your disk has" ;;
esac
printf 'v1\n' > "$CG/src.txt"
python3 - "$CG" >/dev/null 2>&1 <<'PYUT'
import os, sys
open(os.path.join(sys.argv[1], "scratch.tmp"), "w").write("untracked\n")
PYUT
python3 "$CGV" --mode pre --state "$CG/.ddw-state.json" --graph "$CGG" < "$CG/ev.json" >/dev/null 2>&1 \
  && ok "and an untracked file does not block it — build output is not uncommitted work" \
  || bad "an untracked scratch file blocks the closeout; every real repo has one and the gate gets routed around"

# The DEFINE rules used to say create-prd "automatically runs" validate-prd —
# an instruction to load both at once, which read to the user as validating
# from memory. The sequence has to be stated where the model rereads it.
grep -q "never in parallel with \`ddw-create-prd\`" "$SELF/ddw/rules/define.instructions.md" \
  && ok "the DEFINE rules order the sequence: file on disk first, THEN the validator runs" \
  || bad "the DEFINE rules stopped sequencing create→validate — both skills load together again"

# The truncation footgun, measured live: `transition.py … > .ddw-state.json`
# empties the file before the helper reads it. --write is the atomic answer.
TW="$WORK/tw-state"; mkdir -p "$TW"
python3 "$SELF/ddw/scripts/transition.py" --to CLASSIFY --action "probe" \
  --state "$TW/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" --write >/dev/null 2>&1
[ "$(python3 -c "import json; print(json.load(open('$TW/.ddw-state.json'))['phase'])" 2>/dev/null)" = "CLASSIFY" ] \
  && ok "transition.py --write lands the state itself, atomically — no redirect, no truncation" \
  || bad "--write did not write the state; the shell-redirect footgun is the only path again"

python3 - > "$EVENT" <<'PYFIX'
import json
patch = "*** Begin Patch\n*** Add File: src/app.py\n+print(1)\n*** End Patch"
print(json.dumps({"tool_name": "apply_patch", "tool_input": {"command": patch}}))
PYFIX
[ "$(gate_pre codex < "$EVENT")" = "2" ] \
  && ok "Codex: apply_patch names its files inside the patch program, and they are read" \
  || bad "Codex writes through apply_patch, which carries no path field — unread, nothing is ever blocked"

printf '%s' "$IDLE_STATE" > "$GST"

# ── A read is not a write ─────────────────────────────────────────────────────
#
# Claude filters to Edit|Write|NotebookEdit before the gate is called, so for
# months the gate was never handed anything else. Copilot's preToolUse carries
# no matcher and hands over EVERY tool: reads and directory listings arrived
# with a path, were judged as writes, and were refused — including the agent
# reading `.ddw/rules/classify.instructions.md`, the file that tells it what
# CLASSIFY may do. An agent that cannot read is not guarded, it is broken.
section "The gate refuses writes, and only writes"

python3 - "$SELF" <<'PYREAD' && ok "unknown is a write: reads pass, everything else is judged" || bad "the source guard can be walked past by a tool it does not recognise"
import json, os, subprocess, sys, tempfile
root = sys.argv[1]

# Through hook-gate.py with real Copilot envelopes, because that is where an
# event enters. An earlier version of this check called decide_pre directly and
# passed while Copilot wrote source in DEFINE — it tested the layer beneath the
# defect and agreed with itself.
d = tempfile.mkdtemp(); subprocess.run(["git", "-C", d, "init", "-q"], check=True)
os.makedirs(os.path.join(d, ".ddw", "rules"), exist_ok=True)
open(os.path.join(d, ".ddw", "rules", "classify.instructions.md"), "w").write("x")
st = os.path.join(d, ".ddw-state.json")
json.dump({"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "x", "tier": "FEATURE"},
                       {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
                        "action": "x", "tier": "FEATURE"}]}, open(st, "w"))

def gate(event):
    r = subprocess.run([sys.executable, root + "/ddw/scripts/hook-gate.py",
                        "--dialect", "copilot", "--mode", "pre", "--state", st,
                        "--graph", root + "/ddw/rules/transition-graph.json", "--repo", d],
                       input=json.dumps(event), capture_output=True, text=True)
    return r.returncode

def ev(name, args):
    e = {"toolArgs": json.dumps(args)}
    if name is not None:
        e["toolName"] = name
    return e

# Reads pass. `view`, `create` and `edit` are the names GitHub documents for
# Copilot CLI; the rest are shapes other harnesses use.
for name, args in (("view", {"path": ".ddw/rules/classify.instructions.md"}),
                   ("str_replace_editor_view", {"path": ".ddw/rules/classify.instructions.md"}),
                   ("list_directory", {"path": "."}),
                   ("grep", {"path": "app/main.py"}),
                   ("read_file", {"path": ".ddw-state.json"})):
    assert gate(ev(name, args)) == 0, f"{name} refused; a read cannot break a write rule"

# Everything else is a write, INCLUDING what we do not recognise. This is the
# half that shipped backwards: a tool whose name and content key were both
# unfamiliar walked past the guard and wrote source in DEFINE.
for label, name, args in (
        ("create + content",     "create",     {"path": "app/m.py", "content": "x"}),
        ("create + file_text",   "create",     {"path": "app/m.py", "file_text": "x"}),
        ("edit pair",            "edit",       {"path": "app/m.py", "old_str": "a", "new_str": "b"}),
        ("UNKNOWN name+key",     "apply_file", {"path": "app/m.py", "file_text": "x"}),
        ("NO name at all",       None,         {"path": "app/m.py", "file_text": "x"}),
        ("empty name, odd key",  "",           {"path": "app/m.py", "body": "x"}),
        ("a view carrying content", "view",    {"path": "app/m.py", "content": "x"})):
    assert gate(ev(name, args)) == 2, f"{label} was ALLOWED to write source from DEFINE"
PYREAD

# Copilot's hook has no matcher, so the gate is the only filter. Recording that
# here means the day Copilot gains one, this check says so rather than the
# knowledge living in a commit message.
python3 - "$SELF" <<'PYMATCH' && ok "and Copilot's matcher-less hook is a known reason that has to hold" || bad "Copilot's hook config changed shape — recheck what reaches the gate"
import json, sys
d = json.load(open(sys.argv[1] + "/adapters/copilot/hooks/ddw.json", encoding="utf-8"))
pre = d["hooks"]["preToolUse"]
assert all("matcher" not in h for h in pre), \
    "Copilot's preToolUse now has a matcher — good, but the gate's read/write split was sized for its absence"
PYMATCH

# ── Where a post hook cannot refuse ───────────────────────────────────────────
#
# GitHub documents Copilot CLI's postToolUse as able to modify a result or add
# context, and nothing more: `permissionDecision` is exclusive to preToolUse,
# and a non-zero exit is "logged and skipped — agent execution continues". DDW
# was sending it a refusal it ignores, so a forged .ddw-state.json was caught
# correctly by a hook whose verdict went nowhere. The check read as covered and
# the turn carried on.
section "The post-write net speaks the channel each tool actually honours"

PN="$WORK/postnet"; mkdir -p "$PN"; git -C "$PN" init -q .
python3 - "$PN" <<'PYPOST'
import json, sys
json.dump({"phase": "RELEASE", "tier": "FEATURE", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                        "to": "RELEASE", "action": "forged"}]},
          open(sys.argv[1] + "/.ddw-state.json", "w"))
PYPOST

POST_OUT="$(echo '{}' | python3 "$SELF/ddw/scripts/hook-gate.py" --dialect copilot --mode post --state "$PN/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" --repo "$PN" 2>/dev/null)"

case "$POST_OUT" in
  *additionalContext*)
    ok "Copilot gets the finding as additionalContext, which its post hook honours" ;;
  *permissionDecision*)
    bad "Copilot is sent a permissionDecision its postToolUse ignores — the forged state is caught and nothing happens" ;;
  *)
    bad "the post net says nothing at all to Copilot" ;;
esac

case "$POST_OUT" in
  *"STOP."*)
    ok "and it tells the model to stop rather than repair, since it cannot force it" ;;
  *)
    bad "the report does not say what to do, so a model that reads it carries on" ;;
esac

echo '{}' | python3 "$SELF/ddw/scripts/hook-gate.py" --dialect standard --mode post --state "$PN/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" --repo "$PN" >/dev/null 2>&1
if [ "$?" = "2" ]; then
  ok "and the tools whose post hook CAN refuse still get a refusal"
else
  bad "the post net stopped blocking where exit 2 is honoured — the sed/jq bypass is open there"
fi

# The first drop-in that walked a split, live: the pause entry carried the
# ticket it paused — legal, the pre gate accepted it on the old side — and post
# mode, replaying the now-ticketless run from a ticketless IDLE prior, judged
# membership against the empty set and condemned every stamped entry. The rule
# on a paused/closed replay is consistency (one run, one ticket), not
# membership in nothing.
PS="$WORK/paused-split"; mkdir -p "$PS"; git -C "$PS" init -q . >/dev/null 2>&1 || true
python3 - "$PS" <<'PYPAUSE'
import json, sys
hist = [
    {"timestamp": "2026-07-29T15:48:08Z", "from": "IDLE", "to": "CLASSIFY",
     "action": "implementar PRD-001"},
    {"timestamp": "2026-07-29T15:50:29Z", "from": "CLASSIFY", "to": "DEFINE",
     "action": "clasificado FEATURE", "tier": "FEATURE", "ticket": "FEAT-001"},
    {"timestamp": "2026-07-29T15:56:39Z", "from": "DEFINE", "to": "IDLE",
     "action": "pause: split into FEAT-001a/b/c/d", "tier": "FEATURE", "ticket": "FEAT-001"},
]
json.dump({"tier": None, "phase": "IDLE", "ticket": None, "title": None, "tracker": None,
           "gates": {}, "block": None, "discovery": None, "history": hist},
          open(sys.argv[1] + "/.ddw-state.json", "w"))
PYPAUSE
echo '{}' | python3 "$SELF/ddw/scripts/hook-gate.py" --dialect standard --mode post \
  --state "$PS/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" --repo "$PS" >/dev/null 2>&1
[ "$?" = "0" ] \
  && ok "a paused split with its entries stamped survives the post replay" \
  || bad "post condemns a legal paused split — the M1 false positive is back and every later call refuses"

python3 - "$PS" <<'PYMIX'
import json, sys
p = sys.argv[1] + "/.ddw-state.json"
d = json.load(open(p))
d["history"][2]["ticket"] = "FEAT-999"     # a closeout credited to work that never ran
json.dump(d, open(p, "w"))
PYMIX
echo '{}' | python3 "$SELF/ddw/scripts/hook-gate.py" --dialect standard --mode post \
  --state "$PS/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" --repo "$PS" >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "and entries that disagree on the ticket are still refused: one run, one ticket" \
  || bad "a replayed run may now mix tickets — a closeout can be credited to work that never ran"
rm -f "$PS/.ddw-journal.jsonl"

# ── Copilot as a plugin ───────────────────────────────────────────────────────
#
# Copilot installs Claude-format plugins (skills included) and ignores their
# Claude-format hooks manifest — measured live: a forged state sailed through.
# Its channel for plugin enforcement is user-level hooks in ~/.copilot/config.json
# pointing at the installed plugin, so the hook scripts resolve the method
# repo-first, plugin-root second, and the user-level copy stands down where the
# repo wires its own hook — otherwise every write is judged twice.
section "Copilot as a plugin: user-level hooks enforce, and yield to the drop-in"

CPP="$WORK/cp-plugin"; mkdir -p "$CPP"
cp -r "$SELF/ddw" "$CPP/ddw"
CPR="$WORK/cp-repo"; mkdir -p "$CPR"; git -C "$CPR" init -q . >/dev/null 2>&1 || true
CPEV="$(python3 - "$CPR" <<'PY'
import json, os, sys
state = json.dumps({"phase": "RELEASE", "tier": "FEATURE", "gates": {},
                    "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                                 "to": "RELEASE", "action": "forged"}]})
args = json.dumps({"path": os.path.join(sys.argv[1], ".ddw-state.json"), "content": state})
print(json.dumps({"toolName": "create", "toolArgs": args}))
PY
)"
( cd "$CPR" && printf '%s' "$CPEV" | DDW_PLUGIN_ROOT="$CPP" bash "$SELF/adapters/copilot/scripts/pre-tool-use.sh" >/dev/null 2>&1 )
[ "$?" = "2" ] \
  && ok "Copilot user-level hook enforces with no .ddw/ in the repo (method from the plugin root)" \
  || bad "Copilot as a plugin loads skills and enforces NOTHING — the drop-in-only resolution is back"

mkdir -p "$CPR/.github/hooks/ddw" && : > "$CPR/.github/hooks/ddw/pre-tool-use.sh"
( cd "$CPR" && printf '%s' "$CPEV" | DDW_PLUGIN_ROOT="$CPP" bash "$SELF/adapters/copilot/scripts/pre-tool-use.sh" >/dev/null 2>&1 )
[ "$?" = "0" ] \
  && ok "and stands down where the repo wires its own hook — one verdict per write, not two" \
  || bad "the user-level hook double-judges a drop-in repo"

# The plugin's one channel to the model carries the two prohibitions learned
# live on OpenCode: no self-install, no DDW content in the project's context
# file. Shared in session-boot so Claude's plugin says it too.
BOOTMSG="$(python3 "$SELF/ddw/scripts/session-boot.py" --repo "$CPR" --session-id probe --method "$CPP/ddw" 2>/dev/null)"
case "$BOOTMSG" in
  *"Do NOT install DDW"*) ok "the plugin boot forbids the self-install, on every adapter that boots" ;;
  *) bad "a plugin-booted agent is never told not to install — the PRD-to-drop-in failure is back" ;;
esac
case "$BOOTMSG" in
  *"NEVER by writing code first"*) ok "and it says classify-first — the one line whose absence coded an MVP from IDLE" ;;
  *) bad "the plugin boot never says classify-first; on Copilot that omission implemented a whole PRD in IDLE" ;;
esac

# Hooks written to ~/.copilot/config.json are only migrated to settings.json on
# a later start; every session until then runs with no gates and looks fine.
# Measured live: a full DEFINE-phase source write landed that way.
grep -q 'settings.json`\*\* (NOT' "$SELF/.github/INSTALL.md" \
  && ok "the Copilot installer sends hooks to settings.json, where they load on the next start" \
  || bad "the Copilot installer points hooks at config.json again — sessions run gateless until a migration nobody sees"

grep -q "remove the \`hooks\` key" "$SELF/.github/INSTALL.md" \
  && ok "and its uninstall removes the hooks — orphaned hooks fail closed and deny every tool everywhere" \
  || bad "the Copilot uninstall leaves user-level hooks pointing at nothing; measured live, that denies ALL tools in ALL repos"

# Under a plugin the state is born mid-session, after the boot already ran —
# the only other gitignore writer — so the first commit could take the runtime
# with it. The post net closes that window when it blesses the state.
GW="$WORK/gitignore-window"; mkdir -p "$GW"; git -C "$GW" init -q . >/dev/null 2>&1 || true
python3 - "$GW" <<'PYGW'
import json, sys
json.dump({"tier": None, "phase": "CLASSIFY", "ticket": None, "title": None, "tracker": None,
           "gates": {}, "block": None, "discovery": None,
           "history": [{"timestamp": "2026-07-29T12:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "abrir ticket"}]},
          open(sys.argv[1] + "/.ddw-state.json", "w"))
PYGW
echo '{}' | python3 "$SELF/ddw/scripts/hook-gate.py" --dialect standard --mode post \
  --state "$GW/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" --repo "$GW" >/dev/null 2>&1
grep -q ".ddw-state.json" "$GW/.gitignore" 2>/dev/null \
  && ok "the post net gitignores the runtime the moment a state exists — no gateless first-session commit window" \
  || bad "a plugin-born state sits uncommittable-guarded by NOTHING until the next session boot"
DROPMSG="$(python3 "$SELF/ddw/scripts/session-boot.py" --repo "$ALL" --session-id probe 2>/dev/null)"
case "$DROPMSG" in
  *"Do NOT install DDW"*) bad "the drop-in boot carries the plugin's prohibitions — noise for the install that chose files" ;;
  *) ok "and the drop-in boot does not say it: those rules are the plugin's, not the method's" ;;
esac

# ── The method, found from wherever it lives ──────────────────────────────────
#
# Installed as a plugin the method is not in the repo, and the hooks that never
# learned that loaded skills while enforcing nothing — a pipeline that looks
# installed and does not hold. `ddw_method` is the one place that decides, and
# these checks are what stop it being inlined in two hooks and missing from the
# rest again.
section "The hooks find the method whether it is in the repo or in a plugin"

HK="$SELF/adapters/claude/hooks"
grep -q "ddw_method()" "$HK/lib/guard.sh" \
  && ok "the resolution lives once, in the shared guard" \
  || bad "no ddw_method in lib/guard.sh — every hook resolves the method its own way again"

MISSING_RESOLVE=""
for h in session-start.sh enforce.sh pre-compact.sh \
         validate-state-transition.sh validate-state-postwrite.sh; do
  grep -q "ddw_method" "$HK/$h" || MISSING_RESOLVE="$MISSING_RESOLVE $h"
done
[ -z "$MISSING_RESOLVE" ] \
  && ok "and every hook that needs the method calls it" \
  || bad "hooks that only look in the repo, so a plugin install skips them:${MISSING_RESOLVE}"

PM="$WORK/plugin-mode"; mkdir -p "$PM"; git -C "$PM" init -q .
PMOUT="$(python3 "$SELF/ddw/scripts/session-boot.py" --repo "$PM" --session-id pm1 \
         --method "$SELF/ddw" 2>&1)"
case "$PMOUT" in
  *"$SELF/ddw/orchestrator.md"*)
    ok "the boot nudge names the orchestrator's real path, not a relative .ddw/" ;;
  *) bad "the nudge points at .ddw/orchestrator.md, which does not exist under a plugin" ;;
esac

# A plugin at user scope is loaded in every repo you open, including one cloned
# to read for five minutes. Leaving a state file and an edited .gitignore in each
# is not a pipeline, it is litter.
[ ! -e "$PM/.ddw-state.json" ] && [ ! -e "$PM/.gitignore" ] && [ ! -e "$PM/.ddw-sessions" ] \
  && ok "and a repo that never started a pipeline is left untouched" \
  || bad "merely opening a repo under a plugin leaves DDW files behind"

# Drop-in earned its writes by existing: someone put .ddw/ here on purpose.
DI="$WORK/dropin-writes"; mkdir -p "$DI"; git -C "$DI" init -q .
bash "$SELF/install.sh" "$DI" --target claude >/dev/null 2>&1
python3 "$DI/.ddw/scripts/session-boot.py" --repo "$DI" --session-id di1 >/dev/null 2>&1
[ -f "$DI/.ddw-state.json" ] \
  && ok "while a drop-in still materialises the state, as it always did" \
  || bad "the drop-in stopped creating its state file — every existing install regressed"

# ── A plugin manifest is only as good as the paths in it ─────────────────────
#
# Every path in a plugin manifest is resolved on the user's machine, at load
# time, by the tool. A command naming a file that is not there is not an error
# anyone sees: the hook does not run, and the plugin installs looking complete
# while enforcing nothing — the same failure Claude's manifest is pinned against
# above, one directory deeper. Reading the manifest as JSON cannot catch it;
# only following what it points at can.
section "Every plugin manifest points at a script that exists"

# A plugin's description is not release notes. It is loaded, as text, into the
# session of an agent that has already installed the plugin — and an agent that
# reads "install with install.sh for now" does exactly that, in the user's repo,
# on top of the copy it is already running from. Written for a human choosing,
# read by a model executing.
python3 - "$SELF" <<'PYAD' && ok "no published manifest tells its reader to install DDW some other way" || bad "a plugin manifest directs its own reader to another installation route — an agent follows that"
import json, os, sys
root = sys.argv[1]
REDIRECTS = ("install.sh", "install with", "for now", "in progress", "not yet",
             "use the installer")
manifests = [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
             ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json",
             "gemini-extension.json"]
found, seen = [], 0
for rel in manifests:
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        continue
    blob = json.load(open(path, encoding="utf-8"))
    texts = [blob.get("description", "")]
    texts += [p.get("description", "") for p in blob.get("plugins", [])]
    for text in texts:
        if not text:
            continue
        seen += 1
        for phrase in REDIRECTS:
            if phrase in text.lower():
                found.append(f"{rel}: {phrase!r}")
assert seen, "no manifest description was examined — this check measured nothing"
if found:
    print("\n".join("      " + x for x in found), file=sys.stderr)
    sys.exit(1)
PYAD

python3 - "$SELF" <<'PYPM' && ok "every plugin-rooted command resolves to a file that ships" || bad "a plugin manifest names a script that is not in this repo — that hook never runs"
import json, os, re, sys
root = sys.argv[1]
# Each tool expands its own root variable. Which one it is does not matter here;
# what matters is the rest of the path, which is this repo's to get right.
ROOTVAR = re.compile(r"\$\{?(?:CLAUDE_PLUGIN_ROOT|CODEX_PLUGIN_ROOT|CURSOR_PLUGIN_ROOT|extensionPath)\}?/")

def commands(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "command" and isinstance(v, str):
                yield v
            else:
                yield from commands(v)
    elif isinstance(node, list):
        for item in node:
            yield from commands(item)

adapters = os.path.join(root, "adapters")
manifests = [os.path.join(root, "hooks", "hooks.json")]
manifests += [os.path.join(adapters, d, "plugin-hooks.json") for d in sorted(os.listdir(adapters))]

missing, seen = [], 0
for m in manifests:
    if not os.path.isfile(m):
        continue
    for cmd in commands(json.load(open(m, encoding="utf-8"))):
        seen += 1
        # A command with no plugin-rooted path at all is the same defect wearing
        # another hat: whatever it resolves against, it is not the directory the
        # tool installed. Passing over those let one go relative unnoticed.
        if not ROOTVAR.search(cmd):
            missing.append(f"{os.path.relpath(m, root)} -> nothing roots this at the plugin: {cmd}")
            continue
        rel = ROOTVAR.split(cmd, 1)[1].strip().strip('"').split('"')[0]
        if not os.path.isfile(os.path.join(root, rel)):
            missing.append(f"{os.path.relpath(m, root)} -> {rel}")
assert seen, "no plugin command was examined — this check measured nothing"
if missing:
    print("\n".join("      " + x for x in missing), file=sys.stderr)
    sys.exit(1)
PYPM

# A manifest that resolves is half of it. The script it names has to find the
# method too: under a plugin there is no .ddw/ in the repo, and a hook that
# looks only there exits 0 on every write it was installed to judge.
PLR="$WORK/plugin-root"; mkdir -p "$PLR"; cp -r "$SELF/ddw" "$PLR/ddw"
PLEV='{"tool_name":"Write","tool_input":{"file_path":"src/app.ts","content":"x"}}'
for T in codex cursor gemini; do
  PR="$WORK/plugin-repo-$T"; mkdir -p "$PR"; git -C "$PR" init -q . >/dev/null 2>&1 || true
  python3 - "$PR" <<'PYPS'
import json, sys
json.dump({"tier": "FEATURE", "phase": "DEFINE", "ticket": "FEAT-001", "title": None,
           "tracker": None, "gates": {}, "block": None, "discovery": None,
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "open", "ticket": "FEAT-001", "tier": "FEATURE"},
                       {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
                        "action": "define it", "ticket": "FEAT-001", "tier": "FEATURE"}]},
          open(sys.argv[1] + "/.ddw-state.json", "w"))
PYPS
  # Each tool gets only the variable it can actually supply: codex and gemini
  # run their hook through a shell, so the manifest exports DDW_PLUGIN_ROOT;
  # cursor executes the script directly and can only pass its own environment.
  case "$T" in
    cursor) ( cd "$PR" && printf '%s' "$PLEV" | CURSOR_PLUGIN_ROOT="$PLR" \
                bash "$SELF/adapters/$T/hooks/pre-tool-use.sh" >/dev/null 2>&1 ) ;;
    *)      ( cd "$PR" && printf '%s' "$PLEV" | DDW_PLUGIN_ROOT="$PLR" \
                bash "$SELF/adapters/$T/hooks/pre-tool-use.sh" >/dev/null 2>&1 ) ;;
  esac
  [ "$?" = "2" ] \
    && ok "$T enforces as a plugin: source in DEFINE is refused with the method outside the repo" \
    || bad "$T as a plugin loads its skills and enforces NOTHING — its hook only ever looks in the repo"

  # Enforcing is half a pipeline. The boot nudge is the one channel that tells
  # the model where the method is, and a nudge naming a relative .ddw/ under a
  # plugin points at a file the model cannot open: gates with nothing steering.
  BOOTOUT="$( cd "$PR" && printf '{}' | DDW_PLUGIN_ROOT="$PLR" CURSOR_PLUGIN_ROOT="$PLR" \
                bash "$SELF/adapters/$T/hooks/session-start.sh" 2>/dev/null )"
  case "$BOOTOUT" in
    *"$PLR/ddw/orchestrator.md"*)
      ok "and its boot names the orchestrator where the plugin actually put it" ;;
    *) bad "$T boots a plugin install pointing at .ddw/orchestrator.md, which is not there" ;;
  esac
done

# ── What the repository shows the outside world ───────────────────────────────
#
# A malformed issue form is not an error on GitHub: the form simply does not
# appear, and people fall back to a blank box that never contains the state or
# the verbatim refusal — the two things that make a report actionable here.
section "The repository's own front door is well formed"

python3 - "$SELF" <<'PYEOF' && ok "every workflow, issue form and dependabot file parses as YAML" || bad "a .github YAML file is malformed — GitHub ignores those silently"
import glob, os, sys
try:
    import yaml
except ImportError:
    sys.exit(0)                       # asserted elsewhere; not this check's job
root = sys.argv[1]
for f in sorted(glob.glob(os.path.join(root, ".github/**/*.yml"), recursive=True)):
    try:
        yaml.safe_load(open(f, encoding="utf-8"))
    except Exception as exc:
        print(f"{f}: {exc}", file=sys.stderr); sys.exit(1)
sys.exit(0)
PYEOF

for f in CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md LICENSE NOTICE CHANGELOG.md docs/AI-POLICY.md \
         .github/PULL_REQUEST_TEMPLATE.md .github/ISSUE_TEMPLATE/config.yml; do
  [ -f "$SELF/$f" ] || MISSING_FRONT="$MISSING_FRONT $f"
done
[ -z "${MISSING_FRONT:-}" ] \
  && ok "and the files a reader looks for before adopting anything are all there" \
  || bad "missing from the repository root:${MISSING_FRONT}"

# SECURITY.md tells people to open a private advisory. That route only exists if
# the repository has private vulnerability reporting switched on — a setting, not
# a file. Pointing at a door that is not there sends the finding to a public
# issue instead, which is the one outcome the file exists to prevent.
grep -q "security/advisories/new" "$SELF/.github/ISSUE_TEMPLATE/config.yml" \
  && ok "the advisory link is offered where someone would otherwise open a public issue" \
  || bad "nothing routes a vulnerability away from the public issue tracker"

# ── Versions that describe something ──────────────────────────────────────────
section "Every version in this repo is checked, not decorative"

python3 "$SELF/scripts/check_versions.py" --repo "$SELF" >/dev/null 2>&1 \
  && ok "the product version, the graph format and every rule agree" \
  || { bad "versions disagree — run scripts/check_versions.py"
       python3 "$SELF/scripts/check_versions.py" --repo "$SELF" 2>&1 | sed 's/^/      /' | head -10; }

# A graph is data a program reads, and `.ddw/` can be upgraded in halves — the
# scripts from one version beside the graph of another. Reading a shape it does
# not understand and reaching a verdict anyway is worse than refusing, because
# the verdict decides whether source code may be written.
VG="$WORK/graph-format"; mkdir -p "$VG"
python3 - "$SELF" "$VG" <<'PYEOF'
import json, sys
graph = json.load(open(sys.argv[1] + "/ddw/rules/transition-graph.json", encoding="utf-8"))
graph["format_version"] = "9.0"
json.dump(graph, open(sys.argv[2] + "/future.json", "w"))
graph.pop("format_version")
json.dump(graph, open(sys.argv[2] + "/legacy.json", "w"))
json.dump({"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "x", "tier": "FEATURE"},
                       {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
                        "action": "x", "tier": "FEATURE"}]},
          open(sys.argv[2] + "/state.json", "w"))
PYEOF
echo '{}' | python3 "$SELF/ddw/scripts/validate-transition.py" --mode post \
  --state "$VG/state.json" --graph "$VG/future.json" >/dev/null 2>&1
[ "$?" = "2" ] \
  && ok "and a graph whose format these scripts do not read is refused, not guessed at" \
  || bad "a graph declaring an unknown format is read anyway — half an upgrade decides whether code may be written"

echo '{}' | python3 "$SELF/ddw/scripts/validate-transition.py" --mode post \
  --state "$VG/state.json" --graph "$VG/legacy.json" >/dev/null 2>&1 \
  && ok "while a graph written before the field existed keeps working" \
  || bad "graphs with no format_version are refused — that is every repo that installed DDW earlier"

# ── The commit convention, applied to the repository that publishes it ────────
#
# DDW requires `AI-assisted: yes` or `AI-full: yes` on every commit made with a
# model, and forbids Co-Authored-By by name — authorship is where responsibility
# sits, and a trailer naming the tool as an author spreads it onto something that
# cannot hold it. That rule governed every repo DDW is installed in and nothing
# here. Driven against real commits, because a checker for git history that is
# never handed any is a checker of nothing.
section "The attribution rule holds in this repository too"

# ── The version moves when what people install moves ──────────────────────────
#
# `--since` is the half of check_versions.py that makes the number mean
# something, and nothing drove it: the suite called the script without a range,
# so the rule existed and was never once exercised. A synthetic repo is what
# gives it commits to have an opinion about — same reason check_commits.py has
# one below.
VB="$WORK/version-bump"; mkdir -p "$VB"
git -C "$VB" init -q -b main .
git -C "$VB" config user.email ddw@test; git -C "$VB" config user.name ddw
git -C "$VB" config commit.gpgsign false
python3 - "$SELF" "$VB" <<'PYVBSETUP'
import json, os, shutil, sys
src, dst = sys.argv[1], sys.argv[2]
for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
            ".cursor-plugin/plugin.json", "gemini-extension.json", "package.json",
            "CHANGELOG.md", "LICENSE", "README.md", "install.sh",
            "ddw/rules/transition-graph.json", "ddw/scripts/validate-transition.py"):
    out = os.path.join(dst, rel)
    os.makedirs(os.path.dirname(out) or dst, exist_ok=True)
    shutil.copyfile(os.path.join(src, rel), out)
os.makedirs(os.path.join(dst, "ddw", "rules"), exist_ok=True)
for rel in os.listdir(os.path.join(src, "ddw", "rules")):
    if rel.endswith(".instructions.md"):
        shutil.copyfile(os.path.join(src, "ddw", "rules", rel),
                        os.path.join(dst, "ddw", "rules", rel))
PYVBSETUP
git -C "$VB" add -A >/dev/null 2>&1; git -C "$VB" commit -q -m "base"
VB_BASE="$(git -C "$VB" rev-parse HEAD)"

# A shipped file changes and the version does not: the exact shape that left a
# live plugin cache serving a file which had been deleted upstream.
#
# `install.sh`, deliberately, and NOT a rule file. A rule file carries its own
# version, so touching one without bumping it fails the per-file rule as well —
# and a fixture that can fail for two reasons proves neither. It made this exact
# check survive its own mutation while reading green.
python3 - "$VB" <<'PYVBTOUCH'
import os, sys
p = os.path.join(sys.argv[1], "install.sh")
open(p, "a", encoding="utf-8").write("\n# una linea mas\n")
PYVBTOUCH
git -C "$VB" add -A >/dev/null 2>&1; git -C "$VB" commit -q -m "ship a change, say nothing"
python3 "$SELF/scripts/check_versions.py" --repo "$VB" --since "$VB_BASE" >/dev/null 2>&1 \
  && bad "a shipped file changed and the product version did not, and nothing objected" \
  || ok "a change to what people install cannot ship on the version that came before it"

# And it has to PASS once the numbers move, or the rule is just a wall.
python3 - "$VB" <<'PYVBFIX'
import json, os, re, sys
root = sys.argv[1]
for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
            ".cursor-plugin/plugin.json", "gemini-extension.json", "package.json"):
    p = os.path.join(root, rel)
    d = json.load(open(p, encoding="utf-8"))
    d["version"] = "9.9.9"
    json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
c = os.path.join(root, "CHANGELOG.md")
t = open(c, encoding="utf-8").read()
open(c, "w", encoding="utf-8").write(t.replace("# Changelog", "# Changelog\n\n## [9.9.9] — test", 1))
PYVBFIX
git -C "$VB" add -A >/dev/null 2>&1; git -C "$VB" commit -q -m "and say so"
python3 "$SELF/scripts/check_versions.py" --repo "$VB" --since "$VB_BASE" >/dev/null 2>&1 \
  && ok "and it passes once the manifests and the changelog say the new number" \
  || bad "the bump rule refuses a correctly bumped change — a rule nobody can satisfy gets removed"

# The other half, and the one people actually argue about: a rule file carries
# its own version, and editing it without moving that number leaves a field
# describing a file it no longer describes. The product version is bumped here
# too, so only the per-file rule can object.
python3 - "$VB" <<'PYVBRULE'
import json, os, sys
root = sys.argv[1]
open(os.path.join(root, "ddw", "rules", "code.instructions.md"), "a",
     encoding="utf-8").write("\nUna linea mas.\n")
for rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
            ".cursor-plugin/plugin.json", "gemini-extension.json", "package.json"):
    p = os.path.join(root, rel)
    d = json.load(open(p, encoding="utf-8")); d["version"] = "9.9.10"
    json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
c = os.path.join(root, "CHANGELOG.md")
t = open(c, encoding="utf-8").read()
open(c, "w", encoding="utf-8").write(t.replace("# Changelog", "# Changelog\n\n## [9.9.10] — test", 1))
PYVBRULE
git -C "$VB" add -A >/dev/null 2>&1; git -C "$VB" commit -q -m "edit a rule, leave its number"
python3 "$SELF/scripts/check_versions.py" --repo "$VB" --since "$VB_BASE" >/dev/null 2>&1 \
  && bad "a rule file can be rewritten while its own version stands still" \
  || ok "and a rule that changed has to move its own number, not just the product's"
python3 - "$VB" <<'PYVBRULEFIX'
import os, re, sys
r = os.path.join(sys.argv[1], "ddw", "rules", "code.instructions.md")
s = open(r, encoding="utf-8").read()
open(r, "w", encoding="utf-8").write(
    re.sub(r"^version:\s*\S+$", "version: 99.0.0", s, count=1, flags=re.M))
PYVBRULEFIX
git -C "$VB" add -A >/dev/null 2>&1; git -C "$VB" commit -q -m "and move it"
python3 "$SELF/scripts/check_versions.py" --repo "$VB" --since "$VB_BASE" >/dev/null 2>&1 \
  && ok "and moving it is what clears the objection" \
  || bad "the per-file rule stays red after the bump it asked for"

# One manifest left behind is the failure this exists to make impossible: five
# tools reporting one version and the sixth reporting another, from one commit.
python3 - "$VB" <<'PYVBDRIFT'
import json, os, sys
p = os.path.join(sys.argv[1], "package.json")
d = json.load(open(p, encoding="utf-8")); d["version"] = "9.9.8"
json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
PYVBDRIFT
python3 "$SELF/scripts/check_versions.py" --repo "$VB" >/dev/null 2>&1 \
  && bad "one manifest can name a different version than the other four" \
  || ok "and every manifest has to name the same one — six wirings, one product"

# CI has to run the ranged form on a PUSH too. This repository's own work lands
# straight on main, so a rule that only applies to pull requests is a rule it
# exempts itself from — the shape the commit-attribution check was written for.
python3 - "$SELF" <<'PYVBCI' && ok "and CI applies the rule to pushes, not only to pull requests" || bad "the version rule runs on pull requests alone, and this repo pushes to main"
import re, sys, os
y = open(os.path.join(sys.argv[1], ".github/workflows/verify.yml"), encoding="utf-8").read()
step = re.search(r"Versions describe what they are attached to.*?(?=\n      - name:|\Z)", y, re.S)
assert step, "verify.yml has no step running the version rule"
body = step.group(0)
assert "--since" in body, "the step never passes --since, so the bump rule never runs"
assert "HEAD~1" in body, ("the step only uses --since on pull_request; a push lands with no "
                          "range and the rule does not apply to this repo's own commits")
PYVBCI

CM="$WORK/commits"; mkdir -p "$CM"
git -C "$CM" init -q -b main .
git -C "$CM" config user.email ddw@test; git -C "$CM" config user.name ddw
git -C "$CM" config commit.gpgsign false
echo one > "$CM/a.txt"; git -C "$CM" add -A
git -C "$CM" commit -q -m "base, before the range"
CM_BASE="$(git -C "$CM" rev-parse HEAD)"

echo two > "$CM/a.txt"; git -C "$CM" add -A
git -C "$CM" commit -q -F - <<'CMEOF'
✨ a change that discloses how it was made

AI-assisted: yes
CMEOF
python3 "$SELF/scripts/check_commits.py" --repo "$CM" --since "$CM_BASE" >/dev/null 2>&1 \
  && ok "an attributed commit passes" \
  || bad "the attribution check rejects a commit that carries the trailer it asks for"

# Carries the right trailer AND the forbidden one, which is the realistic shape:
# the harness appends Co-Authored-By by default and the author adds the
# disclosure. Testing it without `AI-assisted` would pass for the other reason —
# no attribution at all — and the Co-Authored-By rule would go unmeasured.
echo three > "$CM/a.txt"; git -C "$CM" add -A
git -C "$CM" commit -q -F - <<'CMEOF'
✨ a change that discloses the help and still names the tool as an author

AI-assisted: yes
Co-Authored-By: Some Model <noreply@example.com>
CMEOF
python3 "$SELF/scripts/check_commits.py" --repo "$CM" --since "$CM_BASE" >/dev/null 2>&1 \
  && bad "Co-Authored-By passes — the tool is credited as an author and nothing objects" \
  || ok "and a Co-Authored-By trailer is refused, by the rule DDW ships to everyone else"

git -C "$CM" reset -q --hard HEAD~1
echo four > "$CM/a.txt"; git -C "$CM" add -A
git -C "$CM" commit -q -m "✨ a change that discloses nothing at all"
python3 "$SELF/scripts/check_commits.py" --repo "$CM" --since "$CM_BASE" >/dev/null 2>&1 \
  && bad "a commit with no attribution trailer at all passes" \
  || ok "and so is a commit that discloses nothing"

# A range git cannot read is not a range that passed. This is what a shallow
# clone produces, and reporting it as success is how the check disappears.
python3 "$SELF/scripts/check_commits.py" --repo "$CM" --since "no-such-ref" >/dev/null 2>&1 \
  && bad "an unreadable range reports success — the check silently did not run" \
  || ok "and an unreadable range is a failure, not a pass"

# Dependabot opens a pull request every week and signs nothing: the rule asks a
# person whether a model helped, and there is no person here. Without this the
# dependency PRs are red on arrival, every one of them, and a rule that is red
# for a reason nobody can act on is a rule people learn to click past.
git -C "$CM" reset -q --hard HEAD~1
echo bumped > "$CM/a.txt"; git -C "$CM" add -A
git -C "$CM" -c user.name='dependabot[bot]' \
    -c user.email='49699333+dependabot[bot]@users.noreply.github.com' \
    commit -q -m "⬆️ chore(ci): bump actions/checkout from 7.0.0 to 7.0.1"
CM_BOT="$(python3 "$SELF/scripts/check_commits.py" --repo "$CM" --since "$CM_BASE" 2>&1)" \
  && ok "a bot's dependency bump is not asked to disclose help nobody gave it" \
  || bad "the attribution check rejects Dependabot, so every dependency PR lands red"

# An exemption that does not say who it exempted is indistinguishable from a
# check that stopped running. The count going down has to be visible.
case "$CM_BOT" in
  *"skipped"*"dependabot[bot]"*)
    ok "and it names the commit it skipped instead of quietly subtracting it" ;;
  *) bad "the bot commit vanishes from the count with nothing said about it" ;;
esac

# The exemption is for the bot, not for the shape of its message. A person who
# forgets the trailer is still refused, in the same range, right after.
echo human > "$CM/a.txt"; git -C "$CM" add -A
git -C "$CM" commit -q -m "✨ a person's change, disclosing nothing"
python3 "$SELF/scripts/check_commits.py" --repo "$CM" --since "$CM_BASE" >/dev/null 2>&1 \
  && bad "one bot commit in the range excuses the humans in it too" \
  || ok "and a person in the same range is still held to the rule"
git -C "$CM" reset -q --hard HEAD~2

# A checker nothing invokes is a file, not a gate. The pull request is the only
# place the range exists, which is the one event it has to run on.
python3 - "$SELF" <<'PYCI' && ok "and CI runs it on pull requests, where the commits arrive" || bad "check_commits.py is in the repo and nothing calls it — see above"
import os, sys
try:
    import yaml
except ImportError:
    sys.exit(0)                       # asserted in preflight; not this check's job
wf = yaml.safe_load(open(os.path.join(sys.argv[1], ".github/workflows/verify.yml"),
                        encoding="utf-8"))
steps = [s for job in wf["jobs"].values() for s in job.get("steps", [])]
runs = [s for s in steps if "check_commits.py" in str(s.get("run", ""))]
assert runs, "verify.yml never runs scripts/check_commits.py"
assert any("pull_request" in str(s.get("if", "")) for s in runs), \
    "the attribution step is not gated on pull_request, where the range it needs exists"
PYCI

# ── The prose against the data ────────────────────────────────────────────────
section "Every claim the method makes is backed by the method"

python3 "$SELF/scripts/lint_method.py" --repo "$SELF" >/dev/null 2>&1 \
  && ok "prose, graph, rule catalog and filesystem all agree" \
  || { bad "the method's prose claims something the repo does not support — run scripts/lint_method.py"
       python3 "$SELF/scripts/lint_method.py" --repo "$SELF" 2>&1 | sed 's/^/      /' | head -20; }

# ── The shell goes around the pre-write guard ─────────────────────────────────
#
# `bash -c 'cat > src/x.py'` never reaches the PreToolUse matcher. Parsing shell
# to catch it would fail open on the first spelling nobody anticipated — and a
# guard that looks total and is not is worse than an honest gap. So the
# post-write net, which does run after every shell command, reports it.
section "Source written through a shell is noticed, and only when it should be"

SH="$WORK/shell-gap"; mkdir -p "$SH"; git -C "$SH" init -q .
bash "$SELF/install.sh" "$SH" --target claude >/dev/null 2>&1
python3 - "$SH" <<'PYEOF'
import json, sys
h = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
      "action": "x", "tier": "FEATURE", "ticket": "FEAT-001"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN")])]
json.dump({"tier": "FEATURE", "phase": "PLAN", "ticket": "FEAT-001",
           "gates": {"define": True}, "history": h},
          open(sys.argv[1] + "/.ddw-state.json", "w"), indent=2)
PYEOF
mkdir -p "$SH/docs/ddw/specs" && printf 'spec\n' > "$SH/docs/ddw/specs/spec-FEAT-001.md"

post_note() {
  echo '{}' | python3 "$SH/.ddw/scripts/hook-gate.py" --dialect standard --mode post \
    --state "$SH/.ddw-state.json" --graph "$SH/.ddw/rules/transition-graph.json" \
    --repo "$SH" 2>&1
}

# Quiet on this phase's own artifacts, and on DDW's own footprint: a freshly
# installed repo has .ddw/ untracked until someone commits it, and a warning
# that fires every time is one nobody reads by the third.
[ -z "$(post_note)" ] \
  && ok "silent on the phase's own artifacts and on DDW's own files" \
  || { bad "the post net warns about docs/ or .ddw/ — noise that teaches you to ignore the real one"
       post_note | sed 's/^/      /' | head -3; }

mkdir -p "$SH/app" && printf 'x = 1\n' > "$SH/app/health.py"
post_note | grep -q "product source has changed while the pipeline is in PLAN" \
  && ok "and reports product source that appeared in a phase that does not write source" \
  || bad "source written through a shell in PLAN goes entirely unnoticed"

echo '{}' | python3 "$SH/.ddw/scripts/hook-gate.py" --dialect standard --mode post \
  --state "$SH/.ddw-state.json" --graph "$SH/.ddw/rules/transition-graph.json" \
  --repo "$SH" >/dev/null 2>&1 \
  && ok "and allows the call — it cannot tell your own editing from the agent's" \
  || bad "the report became a refusal: editing your own code in another terminal would now be blocked"

rm -rf "$SH/app"
[ -z "$(post_note)" ] \
  && ok "and goes quiet again once the source is gone" \
  || bad "the warning latched on and no longer reflects what is on disk"

# ── Taking it back out ────────────────────────────────────────────────────────
#
# The hard part of an uninstaller is not deleting. It is knowing what is yours:
# `.claude/` is Claude Code's directory, and your own skills live there too.
# Removing it wholesale would be the defect the installer spends its life
# avoiding, run in reverse and with no undo.
section "Uninstalling removes what DDW put there, and only that"

UN="$WORK/uninstall"; mkdir -p "$UN/.claude/skills/my-skill" "$UN/docs/mine"; git -C "$UN" init -q .
printf 'MY OWN SKILL\n'  > "$UN/.claude/skills/my-skill/SKILL.md"
printf 'my own doc\n'    > "$UN/docs/mine/note.md"
printf 'node_modules/\n' > "$UN/.gitignore"
printf '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo MY OWN HOOK"}]}]},"model":"opus"}\n' \
  > "$UN/.claude/settings.json"
bash "$SELF/install.sh" "$UN" --target claude,gemini >/dev/null 2>&1
printf '\nMY OWN NOTES\n' >> "$UN/AGENTS.md"
mkdir -p "$UN/docs/ddw/prd" && printf '# PRD\n' > "$UN/docs/ddw/prd/prd-FEAT-001.md"

# The plan runs first and must change nothing — it is what you read before
# approving, and a plan with side effects is not a plan.
# ddw_tree_hash, not md5sum: the helper exists for exactly this and these two
# lines went around it. Without md5sum both sides came out empty, so on macOS
# "--plan changed nothing" was true because nothing was compared — the vacuous
# green the helper's own comment warns about, in the check it was written for.
BEFORE="$(ddw_tree_hash "$UN")"
PLANOUT="$(bash "$SELF/uninstall.sh" "$UN" --plan 2>&1)"
[ "$(ddw_tree_hash "$UN")" = "$BEFORE" ] \
  && ok "--plan changes nothing" \
  || bad "--plan already deleted things — you approve after reading it, not before"

case "$PLANOUT" in
  *"skills/ddw-commit"*) ok "and the plan names the skills, not only the hooks" ;;
  *) bad "the plan misses skills and agents: the manifest records those relative to the adapter's dir, and reading them as repo paths silently skips every one" ;;
esac

bash "$SELF/uninstall.sh" "$UN" --yes >/dev/null 2>&1

[ -f "$UN/.claude/skills/my-skill/SKILL.md" ] \
  && ok "a skill of yours inside .claude/ survives" \
  || bad "the uninstaller removed .claude/ wholesale and took the user's own skills with it"
[ -f "$UN/docs/mine/note.md" ] && [ -f "$UN/docs/ddw/prd/prd-FEAT-001.md" ] \
  && ok "docs/ is untouched, DDW's artifacts included" \
  || bad "uninstalling destroyed the record of what was decided"
[ ! -d "$UN/.ddw" ] && [ ! -f "$UN/.ddw-installed.json" ] \
  && ok "the method and the manifest are gone" \
  || bad "the method survived an uninstall"
[ ! -d "$UN/.gemini" ] \
  && ok "and a tool directory that was entirely DDW's goes with it" \
  || bad ".gemini/ was left behind holding nothing but DDW's own leftovers"
grep -q "MY OWN NOTES" "$UN/AGENTS.md" && ! grep -q "BEGIN DDW" "$UN/AGENTS.md" \
  && ok "AGENTS.md keeps your content and loses the block" \
  || bad "AGENTS.md was either destroyed or left with a DDW block pointing at nothing"
[ ! -f "$UN/CLAUDE.md" ] \
  && ok "and a file that held nothing but DDW's pointer is removed rather than left empty" \
  || bad "CLAUDE.md was left behind as an empty husk"
grep -q "node_modules/" "$UN/.gitignore" && ! grep -q "BEGIN DDW" "$UN/.gitignore" \
  && ok ".gitignore keeps your rules and loses DDW's" \
  || bad ".gitignore was mangled by the uninstall"

# The settings file is MERGED into on install, so it may be yours. Leaving DDW's
# hooks in it is not untidiness: they point at scripts that no longer exist, and
# every session in the repo would fail on a command not found.
grep -q "MY OWN HOOK" "$UN/.claude/settings.json" && grep -q '"model"' "$UN/.claude/settings.json" \
  && ok "settings.json keeps your hooks and your other settings" \
  || bad "the uninstall overwrote settings.json instead of removing only DDW's blocks"
grep -q "ddw" "$UN/.claude/settings.json" \
  && bad "DDW's hooks are still wired to scripts that were just deleted — every session fails on a missing command" \
  || ok "and DDW's own hook blocks are unwired"

# Reinstalling on top must be as clean as the first time.
bash "$SELF/install.sh" "$UN" --target claude >/dev/null 2>&1
[ -d "$UN/.ddw" ] && [ -f "$UN/CLAUDE.md" ] && grep -q "MY OWN HOOK" "$UN/.claude/settings.json" \
  && ok "and installing again afterwards works, still without touching what is yours" \
  || bad "a repo cannot be reinstalled cleanly after an uninstall"

# ── Stale bases and branches that land nowhere ────────────────────────────────
#
# These assert that an instruction is present in the file the model loads for
# that phase. That is the whole of what is testable about a rule made of prose —
# and it is not nothing: every one of these was absent once, and its absence is
# what let a branch be cut from a stale base, or a ticket close leaving its work
# stranded on a branch nobody would ever merge.
section "The pipeline never builds on a stale base, and never strands a branch"

BR="$SELF/ddw/rules/branches.instructions.md"
REL="$SELF/ddw/rules/release.instructions.md"
DEF="$SELF/ddw/rules/define.instructions.md"

grep -q 'git switch -c .* origin/' "$BR" \
  && ok "the branch is cut from the fetched ref, not from whatever the local base happens to be" \
  || bad "nothing tells the agent to branch from origin/{base} — it will branch from a stale local base"

grep -qi 'do not .*git pull\|never .*git pull' "$BR" \
  && ok "and git pull is ruled out by name (it needs a clean tree on the base and can merge unasked)" \
  || bad "git pull is not ruled out, so the agent will reach for it and merge on a tree it did not check"

grep -q 'rev-list --count HEAD\.\.origin/' "$BR" \
  && ok "drift against the base is measured, not estimated" \
  || bad "no command measures how far the base moved — the drift is discovered at merge time"

grep -q 'rev-list --count HEAD\.\.origin/' "$DEF" \
  && ok "DEFINE measures it when it resumes a branch that already existed" \
  || bad "a branch resumed days later is worked on without anyone checking how far behind it is"

# The README's status section is a claim about what is actually known. It stops
# being true the moment a tool passes acceptance and nobody updates it — in
# either direction.
ACC="$SELF/scripts/acceptance.md"
# The drop-in row specifically. There are two now — plugin mode is a separate
# install path with its own row — and matching both meant one incomplete row
# made the check read the other as incomplete too.
CLAUDE_ROW="$(grep '^| Claude Code | drop-in |' "$ACC" || true)"
# Keyed on the claim itself, not on a phrase the README also uses for the five
# tools nobody has driven yet — grepping for that one passed either way, which
# is a check that reads as green while measuring nothing.
case "$CLAUDE_ROW" in
  *"| — |"*)
    grep -q "all five acceptance checks pass" "$SELF/README.md" \
      && bad "the README says Claude passed all five, and acceptance.md records fewer" \
      || ok "the README claims no more for Claude than the record holds" ;;
  *)
    grep -q "all five acceptance checks pass" "$SELF/README.md" \
      && ok "the README reports Claude's five acceptance checks, as the record does" \
      || bad "acceptance.md records five passes for Claude and the README never says so" ;;
esac

# That check reads one row. The status section is a claim about all of them, and
# it went stale in the other direction: OpenCode and Copilot were driven live and
# the README went on calling five tools unverified in the wild, because nothing
# compared the sentence to the table. Understating what is known is a smaller sin
# than overstating it and the same defect — a reader cannot tell which tools have
# been watched from a paragraph that is a day behind the record.
python3 - "$SELF" <<'PYACC' && ok "the README's status names exactly the tools the record has never driven" || bad "README status vs acceptance.md — see above"
import os, re, sys
root = sys.argv[1]
acc = open(os.path.join(root, "scripts/acceptance.md"), encoding="utf-8").read()
readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()

# A tool is "driven" if any install path shows a live pass, because that is what
# the sentence is about: whether anyone has ever watched this tool run, not how
# far they got. The row width comes from the header rather than a literal — it
# was pinned at eight, the ritual grew a fifth observation, and every row stopped
# matching at once. A parser that silently matches nothing reports whatever the
# check's default is, which here was "the README is fine".
rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in acc.splitlines() if ln.strip().startswith("|")]
header = next((r for r in rows if r and r[0] == "Tool"), None)
assert header, "acceptance.md has no record table with a Tool column"
width = len(header)
driven, known = set(), set()
for cells in rows:
    if len(cells) != width:
        continue
    tool = cells[0].replace("*", "").strip()
    if tool == "Tool" or set(tool) <= set("- "):
        continue
    known.add(tool)
    if any("✅" in c for c in cells[4:]):
        driven.add(tool)
assert known, "no rows parsed out of acceptance.md: this check is measuring nothing"

status = readme.split("## Status", 1)
assert len(status) == 2, "the README has no Status section for this to be about"
m = re.search(r"\*\*([^*]+?)\*\* — each adapter is driven", status[1])
assert m, "the README no longer names which tools are verified at the boundary only"
claimed = {t.strip() for t in m.group(1).split(",")}

late = sorted(claimed & driven)
assert not late, (f"the README calls {late} unverified in the wild and the record has driven it "
                  "live — the status is behind the table it summarises")
missing = sorted((known - driven) - claimed)
assert not missing, (f"{missing} has no live pass on the record and the README does not say so — "
                     "nothing tells a reader it apart from the tools that were watched")
PYACC

grep -qi "impatience is not approval" "$SELF/ddw/rules/define.instructions.md" \
  && ok "an impatient user is not read as having approved the PRD" \
  || bad "\"just start already\" can be taken as PRD approval — an approval lands in the history that never happened"

grep -q '^## Step 4: Integration' "$REL" \
  && ok "RELEASE asks where the branch lands before it closes the ticket" \
  || bad "nothing asks where the branch lands: a closed ticket can leave its work on a branch forever"

grep -q '│  Integration:' "$REL" \
  && ok "and the closeout cannot be presented with that answer missing" \
  || bad "the closeout summary has no Integration line, so the step can be skipped in silence"

# ── Upgrading a repo that already has DDW ─────────────────────────────────────
#
# The activation block is what loads the orchestrator. Finding it and leaving it
# meant a version that changed it would never reach any repo that already had
# DDW — and the installer printed a green tick over an install that no longer
# matched the method sitting beside it in .ddw/.
section "An existing install is upgraded, not just recognised"

# The instructions live in AGENTS.md whatever tool you installed — one answer to
# "where are DDW's instructions?" instead of six, and nothing to move when the
# pipeline is ported. The tools that do not read AGENTS.md get a pointer, and
# nothing else.
ONE="$WORK/one-place"; mkdir -p "$ONE"; git -C "$ONE" init -q .
bash "$SELF/install.sh" "$ONE" --target claude >/dev/null 2>&1
grep -q "Boot Sequence" "$ONE/AGENTS.md" \
  && ok "the activation block lands in AGENTS.md even for a tool that does not read it" \
  || bad "AGENTS.md has no DDW block on a Claude install — the instructions live in one place per tool again"
grep -q "Boot Sequence" "$ONE/CLAUDE.md" \
  && bad "CLAUDE.md carries the instructions too — two copies to keep in step, and one will drift" \
  || ok "and CLAUDE.md carries only the pointer"
grep -q "@AGENTS.md" "$ONE/CLAUDE.md" && grep -q "@.ddw/orchestrator.md" "$ONE/CLAUDE.md" \
  && ok "which imports AGENTS.md and the orchestrator, one hop from the root" \
  || bad "CLAUDE.md lost an import — Claude reads it and reaches neither the context nor the orchestrator"

# Gemini documents @file.md but not nested imports, so the orchestrator import
# must sit in GEMINI.md itself rather than be reached through AGENTS.md.
GEM="$WORK/gemini-hop"; mkdir -p "$GEM"; git -C "$GEM" init -q .
bash "$SELF/install.sh" "$GEM" --target gemini >/dev/null 2>&1
grep -q "@.ddw/orchestrator.md" "$GEM/GEMINI.md" \
  && ok "and Gemini reaches the orchestrator without depending on nested imports" \
  || bad "Gemini's orchestrator import moved behind a second hop that its docs never promised"

UPG="$WORK/upgrade"; mkdir -p "$UPG"; git -C "$UPG" init -q .
bash "$SELF/install.sh" "$UPG" --target claude >/dev/null 2>&1

# NOTE: capture, then grep. Piping the installer straight into `grep -q` closes
# the pipe on the first match, the installer dies of SIGPIPE, and `pipefail`
# turns a passing check into a failing one — with the installer having done
# exactly the right thing. It cost an hour once already.
#
# The repo already records which tools it was wired for. A second run that asks
# "which tool will you be working with?" invites an answer that lands beside the
# first install instead of refreshing it.
RERUN="$(bash "$SELF/install.sh" "$UPG" --target claude 2>&1)"
case "$RERUN" in
  *"updating:"*) ok "a second run reports itself as an update, not an install" ;;
  *) bad "a re-run still says 'installing into' — nothing tells the user this repo already had DDW" ;;
esac

MENU="$(printf '1\n' | bash "$SELF/install.sh" "$UPG" 2>&1)"
case "$MENU" in
  *"already installed in this repo"*)
    ok "and with no --target it offers to update what is here rather than asking from scratch" ;;
  *) bad "the menu asks which tool to install on a repo that answered that months ago" ;;
esac

# A tool left out of the run keeps its old wiring while .ddw/ moves on. Fine on
# purpose; silently fine is how one tool ends up enforcing a method that is no
# longer the one beside it.
PARTIAL="$(bash "$SELF/install.sh" "$UPG" --target opencode 2>&1)"
case "$PARTIAL" in
  *"NOT updated by this run"*)
    ok "and an installed tool left out of the run is named, not passed over" ;;
  *) bad "claude stayed at the old wiring and nothing said so" ;;
esac

bash "$SELF/install.sh" "$UPG" --target claude,claude >/dev/null 2>&1 \
  && ok "a repeated target is wired once, not twice against itself" \
  || bad "the same target listed twice fails or collides with its own files"

bash "$SELF/install.sh" "$UPG" --target claude >/dev/null 2>&1
python3 - "$UPG" <<'PYEOF'
import re, sys
p = sys.argv[1] + "/CLAUDE.md"
s = open(p, encoding="utf-8").read()
s = re.sub(r"<!-- BEGIN DDW.*?<!-- END DDW -->",
           "<!-- BEGIN DDW (managed by DDW — do not edit by hand) -->\nAN OLDER BLOCK\n<!-- END DDW -->",
           s, flags=re.S)
open(p, "w", encoding="utf-8").write("MY OWN NOTES ABOVE\n\n" + s + "\nMY OWN NOTES BELOW\n")
PYEOF
bash "$SELF/install.sh" "$UPG" --target claude >/dev/null 2>&1

grep -q "AN OLDER BLOCK" "$UPG/CLAUDE.md" \
  && bad "a stale activation block survives reinstall — the orchestrator is loaded by whatever the old version said, forever" \
  || ok "a stale activation block is replaced on reinstall"

grep -q "@.ddw/orchestrator.md" "$UPG/CLAUDE.md" \
  && ok "and the current one is in place" \
  || bad "the block was removed and not replaced — nothing loads the orchestrator"

grep -q "MY OWN NOTES ABOVE" "$UPG/CLAUDE.md" && grep -q "MY OWN NOTES BELOW" "$UPG/CLAUDE.md" \
  && ok "and everything outside the markers is left exactly where it was" \
  || bad "the upgrade ate the user's own content in the context file"

# A repo that already had its own AGENTS.md never gets the template, so none of
# the headings the method reads by name exist — and `## Stack` alone is read by
# CLASSIFY, CODE and seven skills. Every one of those lookups finds nothing.
OWN="$WORK/own-agents"; mkdir -p "$OWN"; git -C "$OWN" init -q .
printf '# Our project\n\n## How to run it\ndocker compose up\n' > "$OWN/AGENTS.md"
OWNOUT="$(bash "$SELF/install.sh" "$OWN" --target opencode 2>&1)"
case "$OWNOUT" in
  *"missing headings the method reads"*)
    ok "a pre-existing AGENTS.md is told which headings the method will look for and not find" ;;
  *) bad "the installer congratulated a file with no ## Stack — every lookup for it finds nothing, silently" ;;
esac
case "$OWNOUT" in
  *"## How to run it"*|*"Our project"*)
    bad "the installer rewrote the user's own AGENTS.md instead of reporting what was missing" ;;
  *) ok "and nothing of theirs is rewritten to make room for them" ;;
esac
grep -q "## How to run it" "$OWN/AGENTS.md" \
  && ok "their own content survives untouched" \
  || bad "installing over a pre-existing AGENTS.md destroyed it"

# And it stays quiet on a file that has them: a warning that fires every run is
# a warning nobody reads by the third install.
TPL="$WORK/tpl-agents"; mkdir -p "$TPL"; git -C "$TPL" init -q .
bash "$SELF/install.sh" "$TPL" --target opencode >/dev/null 2>&1
TPLOUT="$(bash "$SELF/install.sh" "$TPL" --target opencode 2>&1)"
case "$TPLOUT" in
  *"missing headings"*) bad "the heading warning fires on a file created from DDW's own template" ;;
  *) ok "and says nothing when the headings are all there" ;;
esac

printf '\n# MY STACK, MY WORDS\n' >> "$UPG/AGENTS.md"
bash "$SELF/install.sh" "$UPG" --target claude >/dev/null 2>&1
grep -q "MY STACK, MY WORDS" "$UPG/AGENTS.md" \
  && ok "AGENTS.md keeps what the user wrote in it" \
  || bad "the upgrade overwrote AGENTS.md — the user's stack and conventions are gone"

# And again on an adapter where AGENTS.md IS the context file. Four of the six
# — Codex, Copilot, Cursor, OpenCode — put the DDW block inside AGENTS.md, so
# there the same file holds the user's stack AND a managed block. Testing the
# upgrade only on Claude proved nothing about the case where the two live
# together, which is the majority of adapters.
UPO="$WORK/upgrade-agentsmd"; mkdir -p "$UPO"; git -C "$UPO" init -q .
bash "$SELF/install.sh" "$UPO" --target opencode >/dev/null 2>&1
printf '\n# MY STACK, MY WORDS\n' >> "$UPO/AGENTS.md"
python3 - "$UPO" <<'PYEOF'
import re, sys
p = sys.argv[1] + "/AGENTS.md"
s = open(p, encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(
    re.sub(r"<!-- BEGIN DDW.*?<!-- END DDW -->",
           "<!-- BEGIN DDW (managed by DDW — do not edit by hand) -->\nAN OLDER BLOCK\n<!-- END DDW -->",
           s, flags=re.S))
PYEOF
bash "$SELF/install.sh" "$UPO" --target opencode >/dev/null 2>&1

grep -q "MY STACK, MY WORDS" "$UPO/AGENTS.md" \
  && ok "and keeps it when AGENTS.md is also the tool's context file" \
  || bad "upgrading an AGENTS.md-based adapter ate the user's stack"

grep -q "AN OLDER BLOCK" "$UPO/AGENTS.md" \
  && bad "the DDW block inside AGENTS.md is never refreshed on those four adapters" \
  || ok "and the DDW block inside it is refreshed like any other"

# ── What the repo already says, and what DDW was told ─────────────────────────
section "The repo's own tooling does not stay invisible to the pipeline"

CC="$SELF/skills/ddw-context-check/SKILL.md"

[ -f "$CC" ] \
  && ok "ddw-context-check exists" \
  || bad "the skill is gone — a repo's linter, CI commands and pre-commit go unnoticed again"

grep -q 'ddw-context-check' "$SELF/ddw/rules/classify.instructions.md" \
  && ok "and CLASSIFY runs it once per ticket, before the pipeline spends time on wrong commands" \
  || bad "the skill exists but no phase invokes it — a check nobody runs"

# The restriction IS the skill: a study across 138 repositories found context
# files gave no gain and cost >20% more inference, so a skill that grows one is
# not neutral. Without this line it becomes the problem that study describes.
grep -q 'never proposes prose, conventions, architecture' "$CC" \
  && ok "and it is restricted to what the agent cannot discover on its own" \
  || bad "the minimalism restriction is gone — the skill will bloat the context file, which the evidence says costs more and helps less"

grep -qi 'never blocks\|never sets a gate' "$CC" \
  && ok "and it reports rather than blocks — DDW cannot know your project ought to have a linter" \
  || bad "the skill can block: an inference about someone else's stack became a gate"

# A decline that vanishes forever is worse than the question it silenced.
DC="$WORK/declined"; mkdir -p "$DC"; git -C "$DC" init -q .
bash "$SELF/install.sh" "$DC" --target claude >/dev/null 2>&1
printf '\n<!-- ddw:declined FEAT-001 lint typecheck -->\n' >> "$DC/AGENTS.md"
python3 "$DC/.ddw/scripts/session-boot.py" --repo "$DC" --session-id d1 | grep -q 'ddw-context-check' \
  && ok "a declined recommendation is still named at boot, in one line" \
  || bad "declining hides a known gap permanently — the day it costs something, nothing says it was known"

# ── The error nobody wrote down is the error nobody tests ─────────────────────
#
# The observed failure this closes: a spec passed PLAN with a full error-handling
# section and a happy-path-only test list. VERIFY caught it two phases later,
# under F-VER-04 — by which point the code existed, so the missing tests could
# not be written first, and Rule #-1 no longer applied to them.
section "Error paths are demanded where they can still be met"

VR="$SELF/ddw/rules/validation-rules.instructions.md"

# The rule said "paste it verbatim, not a summary" and a live run pasted five
# complete tables and then collapsed the SIXTH — a re-validation of an unchanged
# artifact — to "PASSED (7 checks)", at the moment approval was being asked for.
# The protocol never named that case, so the model reasoned its way out of it.
grep -q 'A re-validation is a validation' "$VR" \
  && ok "a re-validation shows the whole table too, and the protocol says so" \
  || bad "nothing tells a re-run to print the table; 'you already saw this' collapses it again"

# And in the SCRIPT'S OWN OUTPUT, which is the only one of the three that is
# guaranteed to be in the room. Both live collapses ran the validator directly —
# `Ran 1 shell command`, no skill loaded — so the rule in the skill and the rule
# in the catalog were both in files nobody had opened. This one arrives attached
# to the table it governs.
VRSCRIPTS=""
for S in validate_prd validate_spec validate_threat validate_verify; do
  grep -q 'Show the user this table IN FULL' "$SELF/ddw/scripts/$S.py" || VRSCRIPTS="$VRSCRIPTS $S"
done
[ -z "$VRSCRIPTS" ] \
  && ok "and every validator demands it in its own output, where the model is already looking" \
  || bad "these validators print a table and nothing that says to show it:$VRSCRIPTS"

# In the catalog AND in each skill: the skill is what the model loads and
# executes. The one that collapsed the table had read the skill, not the catalog.
VRMISS=""
for S in ddw-validate-prd ddw-validate-spec ddw-threat-modeling ddw-verify-module; do
  grep -qi 'including a re-validation' "$SELF/skills/$S/SKILL.md" || VRMISS="$VRMISS $S"
done
[ -z "$VRMISS" ] \
  && ok "and every validation skill repeats it where the protocol is actually executed" \
  || bad "the catalog says it and these skills do not, which is where it gets read:$VRMISS"

grep -q '^| F-SPEC-16 |' "$VR" \
  && ok "PLAN requires a test for every error a block documents" \
  || bad "nothing links F-SPEC-10's documented errors to F-SPEC-06's test list — the gap is open again"

# Both places, separately: the skill's FAIL table is what a reader consults, and
# the protocol steps are what gets executed. Grepping the file as a whole passes
# on either one alone, which is how a rule comes to be listed and not run — or
# run and not listed.
grep -q '^| F-SPEC-16 |' "$SELF/skills/ddw-validate-spec/SKILL.md" \
  && ok "and the skill's own FAIL table carries it" \
  || bad "F-SPEC-16 is missing from ddw-validate-spec's table of FAIL rules"

# Both branches of the protocol, not either: FEATURE evaluates it per block,
# FIX over the fix-plan's steps. An OR here passes while one whole tier stops
# checking that its documented errors are tested.
# The protocol used to enumerate the rules in prose, and this check grepped for
# the enumeration. The script is what evaluates them now, so the anchor moved to
# where the evaluation lives — and to the FIX fallback, without which a fix-plan
# (which has no `## Block` headings) would be checked against zero units and
# pass F-SPEC-16 by having nothing to compare.
grep -q 'F-SPEC-16' "$SELF/ddw/scripts/validate_spec.py" \
  && grep -q 'units = \[("Fix-plan", text)\]' "$SELF/ddw/scripts/validate_spec.py" \
  && ok "and the validator evaluates it on both the FEATURE and the FIX path" \
  || bad "F-SPEC-16 is catalogued but a tier's path through validate_spec.py never evaluates it"

grep -q '^| F-PRD-09 |' "$VR" && grep -q 'IF <trigger>, THEN THE <system> SHALL' "$VR" \
  && ok "ACs are written in EARS, whose fifth pattern is the one for failures" \
  || bad "no EARS requirement on ACs — an absent error case looks the same as a feature that has none"

grep -q 'SHALL' "$SELF/skills/ddw-create-prd/SKILL.md" \
  && ok "and the PRD template emits that shape rather than free prose" \
  || bad "the template still writes ACs the validator cannot match on"

grep -q 'F-PRD-09\|F-PRD-01 to F-PRD-09' "$SELF/skills/ddw-validate-prd/SKILL.md" \
  && ok "and ddw-validate-prd applies it" \
  || bad "F-PRD-09 is catalogued but the PRD validator never evaluates it"

# ── Work that was defined and never run ───────────────────────────────────────
section "A split PRD does not lose its unfinished sub-tickets"

SUB="$WORK/subtickets"; mkdir -p "$SUB"; git -C "$SUB" init -q .
bash "$SELF/install.sh" "$SUB" --target claude >/dev/null 2>&1
mkdir -p "$SUB/docs/ddw/prd"
for f in prd-FEAT-001.md prd-FEAT-001a.md prd-FEAT-001b.md prd-FEAT-001c.md prd-DISC-002-01.md; do
  printf '# %s\n' "$f" > "$SUB/docs/ddw/prd/$f"
done

# `a` closed; `b` and `c` never ran. Nothing records that anywhere: it is the
# difference between the files on disk and the closeouts in the history.
python3 - "$SUB" <<'PYEOF'
import json, sys
json.dump({"tier": None, "phase": "IDLE", "ticket": None, "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "RELEASE", "to": "IDLE",
                        "action": "closeout", "ticket": "FEAT-001a", "tier": "FEATURE"}]},
          open(sys.argv[1] + "/.ddw-state.json", "w"))
PYEOF
BOOTOUT="$(python3 "$SUB/.ddw/scripts/session-boot.py" --repo "$SUB" --session-id sub1)"

echo "$BOOTOUT" | grep -q "FEAT-001b" && echo "$BOOTOUT" | grep -q "FEAT-001c" \
  && ok "the boot names the sub-tickets that have a PRD and no closeout" \
  || bad "unfinished sub-tickets are invisible at boot — the only record of them is the user's memory"

echo "$BOOTOUT" | grep -q "FEAT-001a" \
  && bad "a closed sub-ticket is still offered as pending — the history entry's ticket is ignored" \
  || ok "and drops the one whose closeout is in the history"

echo "$BOOTOUT" | grep -q "DISC-002" \
  && bad "a DISCOVERY PRD (prd-DISC-002-01.md) is being read as a sub-ticket: its trailing -01 is not a letter suffix" \
  || ok "a DISCOVERY PRD is not mistaken for a sub-ticket"

# Same repo mid-ticket: the panel belongs to IDLE, where you are deciding what
# to pick up next. Mid-flight it is noise about work you are not doing.
python3 - "$SUB" <<'PYEOF'
import json, sys
json.dump({"tier": "FEATURE", "phase": "CODE", "ticket": "FEAT-001b", "gates": {},
           "history": []}, open(sys.argv[1] + "/.ddw-state.json", "w"))
PYEOF
python3 "$SUB/.ddw/scripts/session-boot.py" --repo "$SUB" --session-id sub2 | grep -q "still have a PRD" \
  && bad "the pending-work panel fires mid-ticket, where it is noise" \
  || ok "and says nothing while a ticket is mid-flight"

# The record the derivation rests on: an entry may not name a ticket that is not
# the one in hand, or a closeout could be credited to work that never ran.
python3 - "$SUB" <<'PYEOF' && ok "a history entry cannot stamp a ticket other than the one in hand" || bad "an entry can claim any ticket — a forged closeout would erase real pending work from the boot"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("vt", sys.argv[1] + "/.ddw/scripts/validate-transition.py")
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)
graph = json.load(open(sys.argv[1] + "/.ddw/rules/transition-graph.json"))
old = {"tier": "FEATURE", "phase": "CODE", "ticket": "FEAT-001b",
       "gates": {"define": True, "spec": True, "threat": True}, "history": []}
new = dict(old, phase="VERIFY", gates={**old["gates"], "tests": True, "sast": True},
           history=[{"timestamp": "2026-01-01T00:00:00Z", "from": "CODE", "to": "VERIFY",
                     "action": "done", "ticket": "FEAT-001c", "tier": "FEATURE"}])
try:
    vt.validate(old, new, graph)
except vt.Block:
    sys.exit(0)
sys.exit(1)
PYEOF

# ── Nothing DDW installs may destroy something of yours ───────────────────────
section "The installer never eats a file that is not its own"

DL="$WORK/dataloss"; mkdir -p "$DL/.claude/hooks/lib"; git -C "$DL" init -q .
printf '#!/usr/bin/env bash\n# THE USER OWN HOOK\n' > "$DL/.claude/hooks/session-start.sh"
printf '# THE USER OWN GUARD\n' > "$DL/.claude/hooks/lib/guard.sh"
OUT="$(bash "$SELF/install.sh" "$DL" --target claude 2>&1)"
grep -q "THE USER OWN HOOK" "$DL/.claude/hooks/session-start.sh" \
  && ok "a pre-existing hook of the user's survives the first install" \
  || bad "the installer destroyed a file the user already had — silently, on a FIRST install"
grep -q "THE USER OWN GUARD" "$DL/.claude/hooks/lib/guard.sh" \
  && ok "and so does one nested inside the wiring" \
  || bad "a nested wiring file of the user's was overwritten"
echo "$OUT" | grep -q "session-start.sh" \
  && ok "and the collision is reported rather than passed over in silence" \
  || bad "the user's files were kept but never mentioned — they cannot know what DDW skipped"

# A file the user drops INSIDE a DDW skill directory. The comparison only walked
# source -> destination, so an extra file on the destination side was invisible:
# the directory read as current, got stamped into the manifest as ours, and the
# next upgrade deleted the whole thing.
DL2="$WORK/dataloss2"; mkdir -p "$DL2"; git -C "$DL2" init -q .
bash "$SELF/install.sh" "$DL2" --target claude >/dev/null 2>&1
printf 'MY OWN NOTES\n' > "$DL2/.claude/skills/ddw-status/my-notes.md"
bash "$SELF/install.sh" "$DL2" --target claude >/dev/null 2>&1
bash "$SELF/install.sh" "$DL2" --target claude >/dev/null 2>&1
[ -f "$DL2/.claude/skills/ddw-status/my-notes.md" ] \
  && ok "a file added inside a DDW skill survives repeated reinstalls" \
  || bad "the installer absorbed the user's file into the manifest and then deleted it"

# ── The runtime cannot be destroyed by its own housekeeping ──────────────────
section "Session bookkeeping cannot damage the state"

SB="$WORK/sessions"; mkdir -p "$SB"; git -C "$SB" init -q .
bash "$SELF/install.sh" "$SB" --target claude >/dev/null 2>&1
python3 - "$SB" <<'PYEOF' && ok "a path-shaped session id cannot reach outside .ddw-sessions/" || bad "the session id is used as a filename unvalidated — an id with ../ destroys the state"
import json, os, subprocess, sys
repo = sys.argv[1]
state = os.path.join(repo, ".ddw-state.json")
boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")
live = {"phase": "CODE", "tier": "FEATURE", "ticket": "FEAT-001",
        "gates": {"define": True, "spec": True}, "history": []}
for evil in ("../.ddw-state.json", "../../etc/passwd", "a/b/c", "..", "."):
    json.dump(live, open(state, "w"))
    subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", evil],
                   capture_output=True, text=True)
    back = json.load(open(state))
    assert back.get("ticket") == "FEAT-001", f"session id {evil!r} clobbered the state"
PYEOF

python3 - "$SB" <<'PYEOF' && ok "a .gitignore reduced to comments is repaired, not read as complete" || bad "the runtime gets staged for commit: the check matched DDW's own comment text"
import os, subprocess, sys
repo = sys.argv[1]
boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")
gi = os.path.join(repo, ".gitignore")
# DDW's own installed block explains each entry in a comment, and the check
# split the file on whitespace — so the comments alone satisfied it forever.
open(gi, "w").write("# BEGIN DDW\n#   .ddw-state.json  = your phase\n"
                    "#   .ddw-paused/     = paused tickets\n"
                    "#   .ddw-sessions/   = live session markers\n# END DDW\n")
subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", "gi"],
               capture_output=True, text=True)
rules = {ln.strip() for ln in open(gi) if ln.strip() and not ln.lstrip().startswith("#")}
for e in (".ddw-state.json", ".ddw-paused/", ".ddw-sessions/"):
    assert e in rules, f"{e} was never added back"
PYEOF

python3 - "$SB" <<'PYEOF' && ok "an unreadable state says so instead of reporting IDLE" || bad "a corrupt state is announced as idle, clearing the agent to start work over a live ticket"
import os, subprocess, sys
repo = sys.argv[1]
boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")
open(os.path.join(repo, ".ddw-state.json"), "w").write("{ truncated")
out = subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", "corrupt"],
                     capture_output=True, text=True).stdout
assert "cannot be read" in out, f"reported: {out.strip()[:100]}"
assert "phase IDLE" not in out, "a state it cannot read was announced as IDLE"
PYEOF

# ── The state machine's invariants, through the real gate ─────────────────────
section "The tier and the idle state cannot be tampered with"

python3 - "$ALL" <<'PYEOF' && ok "the tier is locked, the poison values are refused, and IDLE stays empty" || bad "the FSM invariants can be walked around with an in-phase write"
import json, os, subprocess, sys
repo = sys.argv[1]
gate = os.path.join(repo, ".ddw", "scripts", "hook-gate.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")

def h(f, t, tier=None):
    e = {"timestamp": "2026-01-01T00:00:00Z", "from": f, "to": t, "action": "a"}
    if tier:
        e["tier"] = tier
    return e

def rc(disk, new):
    open(state, "w").write(json.dumps(disk))
    ev = json.dumps({"tool_name": "Write",
                     "tool_input": {"file_path": state, "content": json.dumps(new)}})
    return subprocess.run([sys.executable, gate, "--mode", "pre", "--state", state,
                           "--graph", graph, "--repo", repo],
                          input=ev, capture_output=True, text=True).returncode

mid = {"tier": "FEATURE", "phase": "DEFINE", "gates": {"define": True},
       "history": [h("IDLE", "CLASSIFY"), h("CLASSIFY", "DEFINE", "FEATURE")]}

# A write that appends no history entry can still change the tier, and that was
# the whole exploit: flip to QUICK-FIX, then take its shortcut and reach RELEASE
# without PLAN, VERIFY, spec, threat or verify. Post mode replays against the
# FINAL tier, under which the path is legal, so it never noticed.
hop = dict(mid); hop["tier"] = "QUICK-FIX"
assert rc(mid, hop) == 2, "a FEATURE hopped tier mid-run and can walk QUICK-FIX's shortcut"

# Falsy-but-not-null poison: it resolved to the previous tier (so every check
# passed) while landing on disk and making the lock's own truthiness test false.
for poison in ("", [], 0, False):
    bad_tier = dict(mid); bad_tier["tier"] = poison
    assert rc(mid, bad_tier) == 2, f"tier={poison!r} was accepted and disarms the lock"

# An idle state carries no ticket — every time it is written, not only on the
# edge that lands there. Otherwise the next write re-plants a full set of gates.
idle = {"tier": None, "phase": "IDLE", "gates": {},
        "history": [h("IDLE", "CLASSIFY"), h("CLASSIFY", "IDLE")]}
plant = dict(idle)
plant["tier"] = "FEATURE"
plant["gates"] = {"define": True, "spec": True, "threat": True,
                  "tests": True, "sast": True, "verify": True}
assert rc(idle, plant) == 2, "a tier and six gates were planted onto an idle state"
only_gates = dict(idle); only_gates["gates"] = {"spec": True}
assert rc(idle, only_gates) == 2, "gates were planted onto an idle state"

# ...and none of that may cost the legal moves.
mark = dict(mid); mark["gates"] = {"define": True, "spec": True}
assert rc(mid, mark) == 0, "marking a gate in-phase is legal and was refused"
classified = {"tier": None, "phase": "CLASSIFY", "gates": {}, "history": [h("IDLE", "CLASSIFY")]}
assigned = {"tier": "FEATURE", "phase": "DEFINE", "gates": {},
            "history": [h("IDLE", "CLASSIFY"), h("CLASSIFY", "DEFINE", "FEATURE")]}
assert rc(classified, assigned) == 0, "CLASSIFY assigning the tier is legal and was refused"
PYEOF
# These fixtures wrote to the shared state; hand it back the way it was found.
printf '%s' "$IDLE_STATE" > "$ALL/.ddw-state.json"

# ── Each recipe against its tool's real contract ──────────────────────────────
#
# Adapter defects share one shape: a guess about the shape of someone
# else's envelope, wrote the test with the same assumption, and shipped an
# adapter that enforced nothing while the suite went green. These assert the
# things the official docs say, not the things we guessed.
section "The recipes match what each tool actually does"

python3 - "$SELF" "$ALL" <<'PYEOF' && ok "each tool's wiring names events and files that exist" || bad "a recipe wires an event or a script its tool will never call"
import json, os, sys
src, repo = sys.argv[1], sys.argv[2]

cur = json.load(open(os.path.join(repo, ".cursor", "hooks.json"), encoding="utf-8"))
hooks = cur["hooks"]
# cursor.com/docs/agent/hooks: afterFileEdit "supports no output fields" and
# only fires when the AGENT edits a file — it can neither refuse a write nor see
# a shell rewriting the state. The net has to hang off postToolUse.
assert "afterFileEdit" not in hooks, "cursor: the post net hangs off an event that cannot block"
assert "postToolUse" in hooks, "cursor: no postToolUse — nothing catches a state written by Shell"
assert "sessionStart" in hooks, "cursor: sessionStart is not wired, so the pipeline never boots"
for ev in ("preToolUse", "postToolUse"):
    m = hooks[ev][0].get("matcher", "")
    # Cursor has no `Edit` tool: its own compatibility table maps Claude Code's
    # Edit onto Write. `Shell` is how the state gets rewritten behind the gate.
    assert "Write" in m and "Shell" in m, f"cursor {ev}: matcher {m!r} lets writes or shell through"
    assert hooks[ev][0].get("failClosed") is True, f"cursor {ev}: not failClosed"
for ev, entries in hooks.items():
    for e in entries:
        f = os.path.join(repo, e["command"].split()[-1])
        assert os.path.isfile(f), f"cursor {ev} -> {e['command']} does not exist"

js = open(os.path.join(repo, ".opencode", "plugins", "ddw.js"), encoding="utf-8").read()
# opencode.ai/docs/plugins: the Hooks interface has no "session.created" key —
# that is an event TYPE delivered through the generic `event` hook. Registered
# under the wrong key it is never called, so nothing ever boots.
assert '"session.created":' not in js, "opencode: session.created is an event type, not a hook key"
assert "event:" in js, "opencode: the generic event hook is missing, so the pipeline never boots"
# opencode.ai/docs/tools: the real ids. `patch` and `multiedit` do not exist.
assert '"apply_patch"' in js, "opencode: apply_patch is a real write tool and is not gated"
assert '"multiedit"' not in js and '"patch"' not in js, "opencode: gating tool ids that do not exist"
assert '"bash"' in js, "opencode: the post net cannot see the shell, which is what forges a state"

oc = json.load(open(os.path.join(src, "adapters", "opencode", "adapter.json"), encoding="utf-8"))
perm = oc["agents"]["when_readonly"]["permission"]
# opencode.ai/docs/agents: the permission keys are read/edit/bash/… — no `write`.
assert "write" not in perm, "opencode: `write` is not a permission key; edit covers it"

# OpenCode discovers skills and never turns them into /name, so without the
# commands block its seventeen skills load and have no entry point at all. The
# absence is quiet in both directions: nothing is promised and nothing is there,
# so a consistency check between the two agrees either way.
cmds = oc.get("commands")
assert cmds, "opencode: no commands block — its skills load with no way to invoke them by name"
# The directory is a fact about someone else's product, so it is held to the
# note that cites the docs for it. Singular `.opencode/command` is the spelling
# OpenCode does not read, and it is a substring of the plural, so the boundary
# is what makes the comparison mean anything.
import re as _re
assert _re.search(_re.escape(cmds["dir"]) + r"(?![\w-])", cmds.get("note", "")), \
    f"opencode: commands.dir is {cmds['dir']!r}, which its own sourced note does not name"
PYEOF

# ── The pipeline has to survive the summary, on all six ──────────────────────
#
# Compaction drops the middle of the conversation, and what it drops is the boot
# — the phase router and the state. The model keeps answering from a summary of
# the pipeline instead of the pipeline, which is the one thing the orchestrator
# forbids inferring. Every one of the six compacts, and every one spells the
# event differently; each name below comes from that vendor's own hook
# reference, not from a guess about the shape of someone else's product.
section "Compaction cannot quietly end the pipeline"

python3 - "$SELF" <<'PYCOMPACT' && ok "every adapter answers its tool's compaction event" || bad "a tool compacts and DDW says nothing — see above"
import json, os, sys
root = sys.argv[1]
# tool -> (wiring file, event key). Sources, in order:
#   claude   docs.claude.com/en/docs/claude-code/hooks
#   codex    developers.openai.com/codex/hooks
#   cursor   cursor.com/docs/agent/hooks
#   gemini   geminicli.com/docs/hooks/reference
#   copilot  docs.github.com/en/copilot/reference/hooks-reference
WIRING = {
    "claude":  ("adapters/claude/settings.json", "PreCompact"),
    "codex":   ("adapters/codex/hooks.json", "PreCompact"),
    "cursor":  ("adapters/cursor/hooks.json", "preCompact"),
    "gemini":  ("adapters/gemini/settings.json", "PreCompress"),
    "copilot": ("adapters/copilot/hooks/ddw.json", "preCompact"),
}
for tool, (rel, event) in sorted(WIRING.items()):
    blob = json.load(open(os.path.join(root, rel), encoding="utf-8"))
    assert event in blob["hooks"], f"{tool}: {rel} does not wire {event}"
    assert "pre-compact.sh" in json.dumps(blob["hooks"][event]), \
        f"{tool}: {event} is wired to something other than the compaction hook"

# OpenCode has no hook file: the plugin subscribes to the event by type, and its
# stdout never reaches the model, so the reminder has to ride a user message.
js = open(os.path.join(root, "adapters/opencode/plugin/ddw.js"), encoding="utf-8").read()
assert '"session.compacted"' in js, "opencode: the compaction event type is not handled"
assert "compactionNudge" in js and "messages.transform" in js, \
    "opencode: the reminder is never put on a channel the model reads"
PYCOMPACT

# Wiring the event and saying something are different things. What makes the
# reminder work is that it names the boot sequence: a reminder that fires and
# says "carry on" is the same outcome as no reminder, arrived at expensively.
CN="$WORK/compact-nudge"; mkdir -p "$CN"; git -C "$CN" init -q .
CNOUT="$(python3 "$SELF/ddw/scripts/session-boot.py" --repo "$CN" --method "$SELF/ddw" \
          --compact --format text 2>&1)"
CN_MISS=""
for NEEDLE in "orchestrator.md" ".ddw-state.json" "Router: Phase" "status line" "Do NOT answer"; do
  case "$CNOUT" in *"$NEEDLE"*) ;; *) CN_MISS="$CN_MISS '$NEEDLE'" ;; esac
done
[ -z "$CN_MISS" ] \
  && ok "and it names the boot sequence it exists to demand, not just that something happened" \
  || bad "the compaction reminder no longer says:${CN_MISS} — it fires and asks for nothing"
# Grepping for "orchestrator.md" alone passed a hardcoded `.ddw/orchestrator.md`
# — the substring is in both — so a plugin install could be sent to re-read a
# path that does not exist in the repo, and the reminder that exists to restart
# the pipeline would point at nothing. The path has to be the METHOD's.
case "$CNOUT" in
  *"$SELF/ddw/orchestrator.md"*) ok "and the path it names is the method's, which under a plugin is not in the repo" ;;
  *) bad "the compaction reminder names a relative .ddw/ a plugin install does not have — it points the model at a missing file" ;;
esac

# One paragraph, six tools. Written into each hook it would be five copies
# nobody remembers to edit — the failure `a rule written twice` names.
python3 - "$SELF" <<'PYONCE' && ok "and the wording is the method's, not copied into six hooks" || bad "a hook writes its own compaction reminder — the method's message now has a fork"
import glob, os, sys
root = sys.argv[1]
sources = (glob.glob(os.path.join(root, "adapters/*/hooks/*.sh"))
           + glob.glob(os.path.join(root, "adapters/*/scripts/*.sh"))
           + glob.glob(os.path.join(root, "adapters/*/plugin/*.js")))
assert sources, "no adapter sources were read — this check measured nothing"
owns = [p for p in sources
        if "POST-COMPACTION" in open(p, encoding="utf-8").read()]
assert not owns, ("these carry their own copy of the reminder: "
                  + ", ".join(os.path.relpath(p, root) for p in owns))
PYONCE

# ── Where /ddw-status is promised, /ddw-status has to exist ──────────────────
#
# Claude Code turns every skill into a slash command by itself, DDW was built on
# it, and the installer's closing line said "Commands: /ddw-status, /ddw-self-check,
# /ddw-help" to all six targets. On OpenCode skills are discovered and loaded
# but never become `/name` — that is a separate feature reading a separate
# directory — so the first user to follow DDW's own last line of output typed
# /ddw-status and was told no such command exists.
section "The entry point DDW advertises is the entry point that exists"

python3 - "$SELF" "$ALL" <<'PYEOF' && ok "every skill has a command on the tools that need one, and none where they would double up" || bad "commands and skills are out of step — see above"
import json, os, re, sys
src, repo = sys.argv[1], sys.argv[2]

skills = sorted(d for d in os.listdir(os.path.join(src, "skills"))
                if os.path.isfile(os.path.join(src, "skills", d, "SKILL.md")))
assert skills, "no skills to check against"

for aid in sorted(os.listdir(os.path.join(src, "adapters"))):
    rp = os.path.join(src, "adapters", aid, "adapter.json")
    if not os.path.isfile(rp):
        continue
    r = json.load(open(rp, encoding="utf-8"))
    cmd = r.get("commands")
    # Generating commands for a tool that already exposes skills as /name ships
    # each one twice, and the two would drift the moment a skill is renamed.
    assert not (cmd and r.get("skills_are_slash")), \
        f"{aid}: declares both commands and skills_are_slash — that is every skill twice"
    if not cmd:
        continue
    d = os.path.join(repo, cmd["dir"])
    assert os.path.isdir(d), f"{aid}: {cmd['dir']} was declared and not created"
    got = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
    assert got == skills, (f"{aid}: commands and skills are out of step — "
                           f"missing {sorted(set(skills) - set(got))}, "
                           f"extra {sorted(set(got) - set(skills))}")
    for name in got:
        text = open(os.path.join(d, name + ".md"), encoding="utf-8").read()
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        assert m, f"{aid}/{name}: no frontmatter, so the TUI cannot list it"
        desc = re.search(r'^description:\s*"?(.+?)"?\s*$', m.group(1), re.M)
        assert desc and desc.group(1).strip(), \
            f"{aid}/{name}: empty description — a command with no text beside it"
        # The command is an ENTRY POINT, not a second copy of the behaviour. A
        # body that restates the skill is a fork that no one edits twice.
        assert name in m.group(2), f"{aid}/{name}: the body never names the skill it delegates to"
        assert len(m.group(2)) < 400, \
            f"{aid}/{name}: the body is long enough to be a copy of the skill, not a pointer to it"
PYEOF

# The recipes above can be right and the closing line still lie: what a user
# acts on is what the installer PRINTS.
ADVICE="$(bash "$SELF/install.sh" "$ALL" --target all 2>&1)"
python3 - "$SELF" <<PYEOF && ok "and the installer only tells you to type /ddw-… on the tools where that works" || bad "the installer advertises slash commands to a tool that has none"
import json, os, sys
src = sys.argv[1]
out = """$ADVICE"""
# install.sh must not carry its own copy of the promise: the recipe is the only
# thing that knows whether this tool has slash commands.
sh = open(os.path.join(src, "install.sh"), encoding="utf-8").read()
for line in sh.splitlines():
    if line.startswith("echo") and "/ddw-" in line:
        raise AssertionError(f"install.sh promises slash commands itself: {line.strip()}")

blocks = {}
current = None
for line in out.splitlines():
    if "── wiring:" in line:
        current = line.split("── wiring:", 1)[1].strip()
        blocks[current] = []
    elif current:
        blocks[current].append(line)

for aid in sorted(os.listdir(os.path.join(src, "adapters"))):
    rp = os.path.join(src, "adapters", aid, "adapter.json")
    if not os.path.isfile(rp):
        continue
    r = json.load(open(rp, encoding="utf-8"))
    label = r.get("label", aid)
    assert label in blocks, f"{aid}: the installer printed no wiring block for it"
    said = any("try: /ddw-" in l for l in blocks[label])
    has = bool(r.get("commands") or r.get("skills_are_slash"))
    assert said == has, (f"{aid}: installer says slash commands = {said}, "
                         f"the recipe provides them = {has}")
PYEOF

python3 - "$ALL" <<'PYEOF' && ok "each tool gets its context nudge in the spelling it reads" || bad "the session nudge is emitted in a shape that tool ignores — it boots nothing, silently"
import os, subprocess, sys, json
repo = sys.argv[1]
boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")
# Same concept, four incompatible spellings. Getting one wrong is silent.
want = {
    "json":   lambda d: "additionalContext" in d,                       # copilot
    "cursor": lambda d: "additional_context" in d,                      # cursor
    "nested": lambda d: "additionalContext" in d.get("hookSpecificOutput", {}),  # codex, gemini
}
for fmt, check in want.items():
    out = subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", f"t-{fmt}",
                          "--format", fmt], capture_output=True, text=True).stdout.strip()
    assert out, f"{fmt}: no output"
    assert check(json.loads(out)), f"{fmt}: emitted {out[:80]} — that tool will drop it"
PYEOF

# The recipe field that told the user what was still missing, and that nothing
# printed. Codex and Gemini quarantine project hooks: on those two the install
# completes and the enforcement does not, and silence about that ships exactly
# the failure the schema warns against.
python3 - "$SELF" "$WORK" <<'PYEOF' && ok "a recipe's trust_note reaches the user at install time" || bad "trust_note is declared and printed nowhere — on Codex and Gemini the pipeline looks installed and enforces nothing"
import glob, json, os, subprocess, sys
src, work = sys.argv[1], sys.argv[2]
for recipe_path in glob.glob(os.path.join(src, "adapters", "*", "adapter.json")):
    recipe = json.load(open(recipe_path, encoding="utf-8"))
    note = recipe.get("trust_note")
    if not note:
        continue
    repo = os.path.join(work, "trust-" + recipe["id"])
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "-C", repo, "init", "-q", "."], check=True)
    out = subprocess.run(["bash", os.path.join(src, "install.sh"), repo,
                          "--target", recipe["id"]],
                         capture_output=True, text=True).stdout
    head = " ".join(note.split()[:6])
    assert head in " ".join(out.split()), f"{recipe['id']}: the install never mentioned its trust_note"
PYEOF

# ── A corrupt state is an incident, not a chore ───────────────────────────────
#
# Every fault below came out of one OpenCode run, and they compound: the split
# protocol ordered a write pre mode accepted and post mode condemned; the refusal
# ordered a repair the graph makes impossible; it repeated on every tool call;
# and the one move that did work was deleting the file.
section "A corrupt state can be reported, and cannot be repaired away"

# The install gitignores the state, so `git checkout -- .ddw-state.json` can
# never restore it. The first live OpenCode run watched the old advice send an
# agent there: the pathspec failed and the agent misread the failure as "the
# committed file is corrupt too". Advice that points at a painted door is worse
# than no advice.
! grep -rq 'git checkout -- \.ddw-state\.json' "$SELF/ddw/scripts" \
  && ok "the recovery advice never points at git for a file git never had" \
  || bad "a runtime message recommends git checkout for a gitignored file — that door is painted on"

# A mutation whose anchor moved is a line in a list. The run says so — apart from
# the kill rate, so it cannot be read as a pass — but it says so after injecting
# the other two hundred, which is half an hour in CI and hours in one process.
# Whether the anchor is still there is a substring search. Asking it here means
# whoever edits a file the list quotes finds out from the suite that runs in two
# minutes; it went the other way once, and the answer arrived from the last job.
python3 "$SELF/scripts/mutate.py" --check-anchors >/dev/null 2>&1 \
  && ok "every mutation still finds the thing it is supposed to break" \
  || { python3 "$SELF/scripts/mutate.py" --check-anchors 2>&1 | sed 's/^/    /' >&2
       bad "a mutation's anchor moved — it injects nothing and proves nothing"; }

# The second painted door, found live on Claude Code: the refusal tells the model
# to write the corrected state to a scratch path OUTSIDE the repo and hand the
# user one copy command — and the same guard refused that write too, because a
# corrupt state raises before any target is looked at. The model did exactly what
# it had just been told to do and was stopped for it.
python3 - "$SELF" <<'PYEOF' && ok "and the scratch file the refusal asks for can actually be written" || bad "the corrupt-state advice orders a write the corrupt-state guard forbids — painted door, again"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")
CORRUPT = {"phase": "RELEASE", "tier": "FEATURE", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                        "to": "RELEASE", "action": "forged"}]}


def write_to(repo, path):
    state = os.path.join(repo, ".ddw-state.json")
    ev = json.dumps({"tool_name": "Write", "tool_input": {"file_path": path, "content": "{}"}})
    p = subprocess.run([sys.executable, gate, "--dialect", "standard", "--mode", "pre",
                        "--state", state, "--graph", graph, "--repo", repo],
                       input=ev, capture_output=True, text=True)
    return p.returncode


with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["git", "init", "-q", repo], check=True)
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "w") as fh:
        fh.write('{"from":"IDLE","to":"CLASSIFY"}\n{"from":"CLASSIFY","to":"DEFINE"}\n')
    with open(os.path.join(repo, ".ddw-state.json"), "w") as fh:
        json.dump(CORRUPT, fh)
    with tempfile.TemporaryDirectory() as elsewhere:
        rc = write_to(repo, os.path.join(elsewhere, "state-fixed.json"))
    assert rc == 0, ("a corrupt state refuses a write outside the repository, which is the one "
                     f"recovery the refusal itself prescribes (exit {rc})")
PYEOF

python3 - "$SELF" <<'PYEOF' && ok "and nothing inside the repository got easier while that door opened" || bad "the outside-the-repo exit softened the corrupt-state rule for the repo itself"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")
CORRUPT = {"phase": "RELEASE", "tier": "FEATURE", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                        "to": "RELEASE", "action": "forged"}]}


def write_paths(repo, paths):
    state = os.path.join(repo, ".ddw-state.json")
    ti = {"file_path": paths[0], "content": "{}"}
    if len(paths) > 1:
        ti["path"] = paths[1]                 # the decoy shape: two paths, one event
    ev = json.dumps({"tool_name": "Write", "tool_input": ti})
    p = subprocess.run([sys.executable, gate, "--dialect", "standard", "--mode", "pre",
                        "--state", state, "--graph", graph, "--repo", repo],
                       input=ev, capture_output=True, text=True)
    return p.returncode


with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["git", "init", "-q", repo], check=True)
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "w") as fh:
        fh.write('{"from":"IDLE","to":"CLASSIFY"}\n{"from":"CLASSIFY","to":"DEFINE"}\n')
    state = os.path.join(repo, ".ddw-state.json")
    with open(state, "w") as fh:
        json.dump(CORRUPT, fh)
    assert write_paths(repo, [os.path.join(repo, "src", "x.py")]) == 2, \
        "product source is writable while the state on disk is corrupt"
    assert write_paths(repo, [state]) == 2, \
        "the corrupt state can be overwritten by the model, which is what a human is for"
    with tempfile.TemporaryDirectory() as elsewhere:
        assert write_paths(repo, [os.path.join(elsewhere, "ok.json"), state]) == 2, \
            "an event naming one outside path alongside the state buys the state a free write"
PYEOF

python3 - "$SELF" <<'PYEOF' && ok "a run's ticket cannot change under it, and the refusal names the path that works" || bad "the split still writes a state post mode will condemn — see above"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")

HIST = [{"timestamp": "2026-07-29T06:00:00Z", "from": "IDLE", "to": "CLASSIFY",
         "action": "x", "ticket": "FEAT-001", "tier": "FEATURE"},
        {"timestamp": "2026-07-29T06:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
         "action": "y", "ticket": "FEAT-001", "tier": "FEATURE"}]


def run(repo, mode, content=None):
    state = os.path.join(repo, ".ddw-state.json")
    ev = json.dumps({"tool_name": "Write",
                     "tool_input": {"file_path": state, "content": content}}) if content else "{}"
    p = subprocess.run([sys.executable, gate, "--dialect", "standard", "--mode", mode,
                        "--state", state, "--graph", graph, "--repo", repo],
                       input=ev, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["git", "init", "-q", repo], check=True)
    state = os.path.join(repo, ".ddw-state.json")
    parent = {"tier": "FEATURE", "phase": "DEFINE", "ticket": "FEAT-001",
              "gates": {}, "history": HIST}
    json.dump(parent, open(state, "w"))

    # What the Split Protocol used to instruct, verbatim: retarget the header.
    rc, out = run(repo, "pre", json.dumps(dict(parent, ticket="FEAT-001a")))
    assert rc == 2, "pre still accepts a mid-run ticket change; post will condemn it forever"
    assert "pause" in out and "IDLE" in out and "CLASSIFY" in out, \
        f"the refusal does not name the sanctioned split path: {out!r}"

    # And the path it names has to actually be in the graph.
    leave = dict(parent, tier=None, phase="IDLE", ticket=None, gates={},
                 history=HIST + [{"timestamp": "2026-07-29T06:05:00Z", "from": "DEFINE",
                                  "to": "IDLE", "action": "pause: split into FEAT-001a/b/c",
                                  "ticket": "FEAT-001", "tier": "FEATURE"}])
    rc, out = run(repo, "pre", json.dumps(leave))
    assert rc == 0, f"the refusal recommends a write that is itself refused: {out!r}"
PYEOF

python3 - "$SELF" <<'PYEOF' && ok "deleting the state is no longer a way out of it" || bad "rm .ddw-state.json still resets the run — see above"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")


def post(repo):
    p = subprocess.run([sys.executable, gate, "--dialect", "standard", "--mode", "post",
                        "--state", os.path.join(repo, ".ddw-state.json"), "--graph", graph,
                        "--repo", repo], input="{}", capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["git", "init", "-q", repo], check=True)
    state = os.path.join(repo, ".ddw-state.json")
    hist = [{"timestamp": "2026-07-29T06:00:00Z", "from": "IDLE", "to": "CLASSIFY",
             "action": "x", "ticket": "FEAT-001", "tier": "FEATURE"},
            {"timestamp": "2026-07-29T06:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
             "action": "y", "ticket": "FEAT-001", "tier": "FEATURE"}]
    json.dump({"tier": "FEATURE", "phase": "DEFINE", "ticket": "FEAT-001",
               "gates": {}, "history": hist}, open(state, "w"))

    rc, _ = post(repo)
    assert rc == 0, "a legal state was refused"
    journal = os.path.join(repo, ".ddw-journal.jsonl")
    assert os.path.exists(journal), "nothing was journalled, so the state is still the only record"

    os.remove(state)
    rc, out = post(repo)
    assert rc == 2, "the state was deleted and the net said nothing — the escape is still open"
    assert "gone" in out, f"the reason does not say what happened: {out!r}"

    # And the same escape wearing a disguise: put back a shorter history.
    json.dump({"tier": None, "phase": "IDLE", "ticket": None, "gates": {}, "history": []},
              open(state, "w"))
    rc, out = post(repo)
    assert rc == 2, "a truncated history passed as a fresh start"

    # The refusal must not ask the model to fix it — that order is what produced
    # the deletion in the first place, and the graph often makes it impossible.
    low = out.lower()
    assert "stop" in low and "do not repair" in low, f"the refusal does not say to stop: {out!r}"
    for order in ("fix the state and redo", "redo the transition with the write tool"):
        assert order not in low, f"the refusal still orders a repair: {order!r}"
PYEOF

python3 - "$SELF" <<'PYEOF' && ok "and it says the whole finding once, not on every tool call" || bad "the same corrupt state is re-reported in full forever — see above"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")

with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["git", "init", "-q", repo], check=True)
    state = os.path.join(repo, ".ddw-state.json")
    json.dump({"tier": "FEATURE", "phase": "RELEASE", "gates": {},
               "history": [{"timestamp": "2026-07-29T06:00:00Z", "from": "IDLE",
                            "to": "CLASSIFY", "action": "x", "tier": "FEATURE"}]},
              open(state, "w"))

    def post():
        p = subprocess.run([sys.executable, gate, "--dialect", "standard", "--mode", "post",
                            "--state", state, "--graph", graph, "--repo", repo],
                           input="{}", capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    rc1, first = post()
    rc2, second = post()
    assert rc1 == 2 and rc2 == 2, "a corrupt state stopped being refused after the first report"
    assert "ILLEGAL" in first, "the first report is not the full finding"
    assert len(second) < len(first), (
        "the second call repeats the whole finding — twenty of these is what buries the "
        "instruction to stop and pushes a model into manoeuvring")
    assert "STOP" in second, "the short form dropped the one instruction that matters"

    # A DIFFERENT corruption is a different finding and is said in full.
    json.dump({"tier": "FEATURE", "phase": "CODE", "gates": {},
               "history": [{"timestamp": "2026-07-29T06:00:00Z", "from": "IDLE",
                            "to": "CLASSIFY", "action": "x", "tier": "FEATURE"}]},
              open(state, "w"))
    rc3, third = post()
    assert rc3 == 2 and "ILLEGAL" in third, "a new corruption was silenced by the previous one"
PYEOF

# ── Every hook a tool wires must actually do something ────────────────────────
#
# check_adapter drives each tool's PRE hook. The post nets, the session boot and
# the per-write housekeeping were syntax-checked and never executed — so any of
# them could be turned into `exit 0` and every check stayed green. The post net
# is the only thing that catches a state written with sed or jq.
section "The hooks nothing used to execute"

FORGED_STATE='{"tier":"FEATURE","phase":"RELEASE","gates":{"define":true,"spec":true,"threat":true,"tests":true,"sast":true,"verify":true,"commit":true,"pr":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"RELEASE","action":"forged with sed","tier":"FEATURE"}]}'

# $3 = "report" when this tool's post hook cannot refuse, only speak. Copilot is
# the one: GitHub documents postToolUse as unable to deny, and a non-zero exit
# there is logged and skipped. Demanding exit 2 from it asserted a capability the
# tool does not have — and a check that demands the impossible gets "fixed" by
# weakening it, which is how a real gap ends up looking covered.
check_post_hook() {  # $1 = label, $2 = hook path, $3 = "report" | ""
  local label="$1" hook="$ALL/$2" mode="${3:-block}"
  if [ ! -f "$hook" ]; then bad "$label: no post-write hook was installed"; return; fi
  printf '%s' "$FORGED_STATE" > "$ALL/.ddw-state.json"
  # Each tool is asked about a state it has not been told about yet. The net says
  # the whole finding once per corrupt file and a short line after that, so
  # without this the second adapter tested would be judged on the short line and
  # the six checks would silently depend on their own order.
  rm -f "$ALL/.ddw-sessions/corrupt-reported" "$ALL/.ddw-journal.jsonl"
  local out rc
  out="$( (cd "$ALL" && CLAUDE_PROJECT_DIR="$ALL" bash "$hook" </dev/null) 2>&1 )"; rc=$?
  if [ "$mode" = "report" ]; then
    case "$out" in
      *ILLEGAL*) ok "$label reports a state forged with sed or jq (its post hook cannot refuse)" ;;
      *) bad "$label: a forged state produced no report, and its post hook cannot block either" ;;
    esac
  elif [ "$rc" != "0" ]; then
    ok "$label catches a state forged with sed or jq"
  else
    bad "$label: a state forged behind the pre-write hook survived the post net"
  fi
  printf '%s' "$IDLE_STATE" > "$ALL/.ddw-state.json"
  out="$( (cd "$ALL" && CLAUDE_PROJECT_DIR="$ALL" bash "$hook" </dev/null) 2>&1 )"; rc=$?
  case "$out$rc" in
    *ILLEGAL*) bad "$label objects to a perfectly legal state — a net that cries wolf gets removed" ;;
    *) [ "$rc" = "0" ] && ok "$label stays quiet on a legal state" \
         || bad "$label objects to a perfectly legal state — a net that cries wolf gets removed" ;;
  esac
}
check_post_hook "Claude Code"  ".claude/hooks/validate-state-postwrite.sh"
check_post_hook "Codex CLI"    ".codex/hooks/ddw/post-write.sh"
check_post_hook "Cursor"       ".cursor/hooks/ddw/post-write.sh"
check_post_hook "Gemini CLI"   ".gemini/hooks/ddw/post-write.sh"
check_post_hook "Copilot CLI"  ".github/hooks/ddw/post-write.sh" report

# The session boot is what puts the orchestrator in front of the model. If it
# stops emitting, the pipeline simply never starts and nothing says so.
SB2="$WORK/bootcheck"; mkdir -p "$SB2"; git -C "$SB2" init -q .
bash "$SELF/install.sh" "$SB2" --target claude >/dev/null 2>&1
OUT="$( (cd "$SB2" && CLAUDE_PROJECT_DIR="$SB2" bash "$SB2/.claude/hooks/session-start.sh" </dev/null) 2>/dev/null )"
printf '%s' "$OUT" | grep -q "orchestrator" \
  && ok "Claude's session boot puts the orchestrator in front of the model" \
  || bad "the session boot emitted nothing — the pipeline never starts and nothing reports it"
[ -f "$SB2/.ddw-state.json" ] \
  && ok "and it materialises the state file" \
  || bad "the session boot did not create the state, so the first write has nothing to judge"

# ── Each dialect's verdict, in that dialect ───────────────────────────────────
# Only Copilot's JSON was ever asserted. The other three read a different field,
# and a refusal in the wrong shape is a refusal the tool does not see.
section "A refusal has to be a refusal in the tool's own words"

printf '%s' "$IN_PLAN" > "$GST"
ddw_event_path snake "$ALL/src/app.py"
check_verdict() {  # $1 = dialect, $2 = python expression over the parsed JSON
  python3 "$GATE" --dialect "$1" --mode pre --state "$GST" --graph "$G" --repo "$ALL" \
    < "$EVENT" > "$WORK/verdict-$1.json" 2>/dev/null
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if ($2) else 1)" \
    "$WORK/verdict-$1.json" \
    && ok "$1's refusal carries the field $1 reads" \
    || bad "$1 exits 2 but its JSON says nothing $1 understands — the tool sees no verdict"
}
check_verdict cursor  'd.get("permission")=="deny"'
check_verdict gemini  'd.get("decision")=="deny"'
check_verdict codex   'd.get("hookSpecificOutput",{}).get("permissionDecision")=="deny"'
check_verdict copilot 'd.get("permissionDecision")=="deny"'

# An allow that says nothing is not the same as an allow. Cursor reads the
# verdict, and an empty object there means "no decision" — which under
# failClosed refuses every legal write.
printf '%s' "$IDLE_STATE" > "$GST"
ddw_event_path snake "$ALL/docs/ddw/notes.md"
python3 "$GATE" --dialect cursor --mode pre --state "$GST" --graph "$G" --repo "$ALL" \
  < "$EVENT" > "$WORK/verdict-allow.json" 2>/dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get("permission")=="allow" else 1)' \
  "$WORK/verdict-allow.json" \
  && ok "and an allow is stated explicitly, not implied by silence" \
  || bad "Cursor gets no verdict on a legal write, which under failClosed refuses it"

# ── Codex writes through apply_patch, in both directions ──────────────────────
# Only "Add File" was ever exercised; modifying an existing file is the common
# case and went unjudged.
for MARKER in "Add File" "Update File" "Delete File"; do
  python3 - "$MARKER" > "$EVENT" <<'PYEOF'
import json, sys
patch = f"*** Begin Patch\n*** {sys.argv[1]}: src/app.py\n+x = 1\n*** End Patch"
print(json.dumps({"tool_name": "apply_patch", "tool_input": {"command": patch}}))
PYEOF
  printf '%s' "$IN_PLAN" > "$GST"
  [ "$(gate_pre codex < "$EVENT")" = "2" ] \
    && ok "Codex: apply_patch '$MARKER' names a file and it is judged" \
    || bad "Codex: apply_patch '$MARKER' writes to a file nothing looked at"
done

# OpenCode names an edit's arguments in camelCase. Unmapped, the validator cannot
# reconstruct the pending state — and since it fails closed on the state file, a
# perfectly LEGAL edit is refused. That is the direction that discriminates: an
# illegal one is refused either way, so refusing it proves nothing.
printf '%s' "$IN_PLAN" > "$GST"
python3 - "$GST" > "$EVENT" <<'PYEOF'
import json, sys
# An in-phase gate update: legal, and the everyday shape of a write to the state.
disk = open(sys.argv[1]).read()
old = '"gates":{"define":true}'
assert old in disk, f"fixture drifted: {disk[:120]}"
print(json.dumps({"tool_name": "edit", "tool_input": {
    "filePath": sys.argv[1],
    "oldString": old,
    "newString": '"gates":{"define":true,"spec":true}'}}))
PYEOF
[ "$(gate_pre standard < "$EVENT")" = "0" ] \
  && ok "a legal edit in camelCase is understood, not refused for being unreadable" \
  || bad "OpenCode's edit arguments went unmapped: the state cannot be reconstructed, so every legal edit fails closed"

# ── The QUICK-FIX guard blocks more than a line count ─────────────────────────
section "QUICK-FIX cannot slip through a sensitive path"

QF2="$WORK/qf-sensitive"; mkdir -p "$QF2/src/auth" "$QF2/src/ui"
git -C "$QF2" init -q -b main .
git -C "$QF2" config user.email ddw@test; git -C "$QF2" config user.name ddw
git -C "$QF2" config commit.gpgsign false
echo "x = 1" > "$QF2/src/auth/login.py"; echo "y = 1" > "$QF2/src/ui/button.py"
bash "$SELF/install.sh" "$QF2" --target claude >/dev/null 2>&1
git -C "$QF2" add -A && git -C "$QF2" commit -qm base
printf '{"tier":"QUICK-FIX","phase":"CODE","gates":{},"history":[]}' > "$QF2/.ddw-state.json"
git -C "$QF2" checkout -qb fix/QF-9
qf2_write() { printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$1" \
  | python3 "$QF2/.ddw/scripts/hook-gate.py" --dialect standard --mode pre \
      --state "$QF2/.ddw-state.json" --graph "$QF2/.ddw/rules/transition-graph.json" --repo "$QF2"; }
qf2_write "$QF2/src/auth/login.py" >/dev/null 2>&1 \
  && bad "QUICK-FIX wrote to an auth path — the sensitive-path list guards nothing" \
  || ok "QUICK-FIX refuses a security-sensitive path"
qf2_write "$QF2/src/ui/button.py" >/dev/null 2>&1 \
  && ok "and still allows an ordinary one" \
  || bad "the sensitive-path guard refuses everything, which is its own failure"

# The tier is in the state and the budget is in the rules, so the ceiling on a
# QUICK-FIX is a fact about the METHOD. Shipped as one tool's hook it held for
# that tool and nobody else, and the same ticket was refused or waved through
# depending on which agent happened to be open — which is the one thing a recipe
# is forbidden to decide.
QFP_MISS=""
for D in standard codex copilot cursor gemini; do
  case "$D" in
    copilot) QFP_EV="$(python3 -c "import json,sys; print(json.dumps({'toolName':'create','toolArgs':json.dumps({'path':sys.argv[1],'content':'x'})}))" "$QF2/src/auth/login.py")" ;;
    *)       QFP_EV="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$QF2/src/auth/login.py\",\"content\":\"x\"}}" ;;
  esac
  printf '%s' "$QFP_EV" | python3 "$SELF/ddw/scripts/hook-gate.py" --dialect "$D" --mode pre \
    --state "$QF2/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$QF2" >/dev/null 2>&1
  [ "$?" = "2" ] || QFP_MISS="$QFP_MISS $D"
done
[ -z "$QFP_MISS" ] \
  && ok "and every dialect refuses it, not only the tool that shipped the guard" \
  || bad "QUICK-FIX reaches a sensitive path on:${QFP_MISS} — the budget belongs to the method, not to an adapter"

printf '%s' "$IDLE_STATE" > "$GST"

# ── Two sessions on one directory ─────────────────────────────────────────────
python3 - "$SB2" <<'PYEOF' && ok "a second session on the same directory is warned about the first" || bad "the concurrency guard never fires — two sessions clobber one state with no notice"
import os, subprocess, sys
repo = sys.argv[1]
boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")
subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", "sess-A"],
               capture_output=True, text=True)
out = subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", "sess-B"],
                     capture_output=True, text=True).stdout
assert "other session" in out, f"no warning: {out.strip()[:120]}"
PYEOF

# ── The guard cannot exempt its own rulebook ──────────────────────────────────
section "What a blocked phase still cannot touch"

printf '%s' "$IN_PLAN" > "$GST"
# The graph and the gate ARE the enforcement. Allowing a phase to write there let
# an agent that could not write code rewrite the rules that stopped it: add an
# edge from PLAN and a FEATURE closes with no spec, no threat model, no tests and
# no verification, with both hooks green.
for TARGET in .ddw/rules/transition-graph.json .ddw/scripts/hook-gate.py \
              .ddw/scripts/validate-transition.py .ddw/orchestrator.md; do
  ddw_event_path snake "$ALL/$TARGET"
  [ "$(gate_pre standard < "$EVENT")" = "2" ] \
    && ok "a blocked phase cannot rewrite $TARGET" \
    || bad "a blocked phase rewrote $TARGET — the guard exempts its own rulebook"
done

# ...while the runtime the protocol needs stays writable. Pause is advertised as
# available from any phase, and step one is saving the state to .ddw-paused/.
ddw_event_path snake "$ALL/.ddw-paused/TICKET-1.ddw-state.json"
[ "$(gate_pre standard < "$EVENT")" = "0" ] \
  && ok "and pausing from a blocked phase still works" \
  || bad "the pause protocol is unusable from the phases that most need it"

python3 - "$ALL" <<'PYEOF' && ok "a resume requires a pause, from the phase it paused at" || bad "the word resume is a skeleton key: it opens an edge from IDLE to any phase, with any gates"
import json, os, subprocess, sys
repo = sys.argv[1]
gate = os.path.join(repo, ".ddw", "scripts", "hook-gate.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")

def h(f, t, a="a", tier="FEATURE"):
    e = {"timestamp": "2026-01-01T00:00:00Z", "from": f, "to": t, "action": a}
    if tier:
        e["tier"] = tier
    return e

def rc(disk, new):
    open(state, "w").write(json.dumps(disk))
    ev = json.dumps({"tool_name": "Write",
                     "tool_input": {"file_path": state, "content": json.dumps(new)}})
    return subprocess.run([sys.executable, gate, "--mode", "pre", "--state", state,
                           "--graph", graph, "--repo", repo],
                          input=ev, capture_output=True, text=True).returncode

# A virgin repo. No ticket has ever existed, so there is nothing to resume — and
# this used to close a FEATURE in a single write.
virgin = {"tier": None, "phase": "IDLE", "gates": {}, "history": []}
forged = {"tier": "FEATURE", "phase": "RELEASE", "gates": {"commit": True, "pr": True},
          "history": [h("IDLE", "RELEASE", "resume: EVIL-1")]}
assert rc(virgin, forged) == 2, "a resume with no pause behind it walked the whole pipeline"

paused = [h("IDLE", "CLASSIFY", tier=None), h("CLASSIFY", "DEFINE"), h("DEFINE", "PLAN"),
          h("PLAN", "IDLE", "pause: waiting on product")]
idle = {"tier": None, "phase": "IDLE", "gates": {}, "history": paused}

good = {"tier": "FEATURE", "phase": "PLAN", "gates": {"define": True},
        "history": paused + [h("IDLE", "PLAN", "resume: FEAT-001")]}
assert rc(idle, good) == 0, "a legitimate resume was refused"

elsewhere = {"tier": "FEATURE", "phase": "CODE", "gates": {"define": True},
             "history": paused + [h("IDLE", "CODE", "resume: FEAT-001")]}
assert rc(idle, elsewhere) == 2, "a resume landed in a phase the ticket was never paused at"

dropped = paused[:-1] + [h("PLAN", "IDLE", "abandon: not worth it")]
assert rc({"tier": None, "phase": "IDLE", "gates": {}, "history": dropped},
          {"tier": "FEATURE", "phase": "PLAN", "gates": {"define": True},
           "history": dropped + [h("IDLE", "PLAN", "resume: FEAT-001")]}) == 2, \
    "an abandoned ticket was resumed — abandoning is supposed to be final"
PYEOF

python3 - "$ALL" <<'PYEOF' && ok "post mode's compatibility hatch is not a way to disable post mode" || bad "one untiered entry ending at IDLE turned off the only net against a state forged with sed"
import json, os, subprocess, sys
repo = sys.argv[1]
gate = os.path.join(repo, ".ddw", "scripts", "hook-gate.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
# The hatch exists so a ticket closed before edges carried their tier is not
# called illegal. Returning early skipped append-only and the IDLE invariant too,
# so this shape — mid-phase, every gate set, one entry — walked straight through.
json.dump({"tier": None, "phase": "CODE",
           "gates": {k: True for k in ("define", "spec", "threat", "tests", "sast", "verify")},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "RELEASE",
                        "to": "IDLE", "action": "x"}]}, open(state, "w"))
r = subprocess.run([sys.executable, gate, "--mode", "post", "--state", state,
                    "--graph", graph, "--repo", repo],
                   capture_output=True, text=True)
assert r.returncode == 2, "a forged state slipped through the compatibility hatch"
PYEOF

printf '%s' "$IDLE_STATE" > "$GST"

# ── The holes the mutation run exposed ────────────────────────────────────────
#
# Each of these exists because a deliberately injected fault survived: the suite
# had no way to see it. They are written to fail for ONE reason, because several
# of the checks above passed for the wrong one — a symlinked path was refused,
# but by the source guard rather than by path resolution, so replacing realpath
# with abspath changed nothing observable.
section "The faults the suite used to miss"

# An internal error is not a refusal. The wrapper that turns an unexpected
# exception into a deny is only reachable through a fault the Block path does
# not already handle — a state file that is a DIRECTORY raises IsADirectoryError
# deep inside, which is exactly the shape that used to exit 1 and be read as
# "the hook errored, let it through".
# It has to be a fault the Block path does NOT already handle, or the outer
# wrapper is never reached and the check passes without testing it. A graph whose
# `tiers` is a string is well-formed JSON that explodes deep inside with an
# AttributeError — the exact shape that used to exit 1.
printf '{"common": "not a mapping", "tiers": {}}' > "$WORK/weird-graph.json"
printf '%s' "$IN_PLAN" > "$GST"
# The append-only check runs before the graph is ever consulted, so the event has
# to be a legitimate single-edge append — otherwise it is refused long before the
# code path this is trying to reach.
python3 - "$GST" > "$EVENT" <<'PYEOF'
import json, sys
disk = json.load(open(sys.argv[1]))
nxt = json.loads(json.dumps(disk))
nxt["phase"] = "CODE"
nxt["gates"] = {"define": True, "spec": True, "threat": True}
nxt["history"].append({"timestamp": "2026-07-27T10:01:00Z", "from": "PLAN",
                       "to": "CODE", "action": "x", "tier": "FEATURE"})
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": sys.argv[1], "content": json.dumps(nxt)}}))
PYEOF
python3 "$GATE" --mode pre --state "$GST" --graph "$WORK/weird-graph.json" --repo "$ALL" \
  < "$EVENT" >/dev/null 2>&1
GOT=$?
python3 "$GATE" --mode pre --state "$GST" --graph "$WORK/weird-graph.json" --repo "$ALL" \
  < "$EVENT" 2>"$WORK/weird.err" >/dev/null
if [ "$GOT" = "2" ] && grep -q "could not reach a verdict" "$WORK/weird.err"; then
  ok "an unexpected internal error still refuses (exit 2, not 1)"
else
  bad "the gate exited $GOT on an unexpected error, or handled it as a Block — either way the fail-closed wrapper is untested and exit 1 reads as permission to proceed"
fi

# Path resolution, isolated. `docs/` is allowlisted and `src/` is not, so a
# symlink from one to the other is refused ONLY if the path is resolved. Under
# lexical resolution this reads as a plain docs/ write and is allowed.
printf '%s' "$IN_PLAN" > "$GST"
mkdir -p "$ALL/docs" "$ALL/src"
ln -sfn ../src/app.py "$ALL/docs/alias.md"
ddw_event_path snake "$ALL/docs/alias.md"
[ "$(gate_pre standard < "$EVENT")" = "2" ] \
  && ok "a symlink from an allowed directory into source is resolved, not taken at face value" \
  || bad "docs/alias.md -> ../src/app.py shipped source during PLAN: the path was resolved lexically"
rm -f "$ALL/docs/alias.md"

# The guard covers five phases and only two were ever exercised.
for PH in CLASSIFY DEFINE VERIFY DISCOVERY; do
  python3 - "$GST" "$PH" <<'PYEOF'
import json, sys
json.dump({"phase": sys.argv[2], "tier": "FEATURE", "gates": {},
           "history": [{"timestamp": "2026-07-27T10:00:00Z", "from": "IDLE",
                        "to": sys.argv[2], "action": "x"}]}, open(sys.argv[1], "w"))
PYEOF
  ddw_event_path snake "$ALL/src/app.py"
  [ "$(gate_pre standard < "$EVENT")" = "2" ] \
    && ok "product source is refused in $PH too" \
    || bad "$PH writes product source — the guard covers it on paper only"
done

# A refusal has to be a refusal in the dialect the tool reads, not merely a
# non-zero exit that happens to also mean no.
printf '%s' "$IN_PLAN" > "$GST"
python3 - "$ALL" > "$EVENT" <<'PYEOF'
import json, os, sys
print(json.dumps({"toolName": "create", "toolArgs": json.dumps(
    {"path": os.path.join(sys.argv[1], "src", "app.py"), "content": "x"})}))
PYEOF
# Captured first: the gate exits 2 on a refusal, and under `pipefail` that would
# decide the pipeline's result regardless of what the parser found.
python3 "$GATE" --dialect copilot --mode pre --state "$GST" --graph "$G" --repo "$ALL" \
  < "$EVENT" > "$WORK/copilot-verdict.json" 2>/dev/null
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get("permissionDecision")=="deny" else 1)' \
  "$WORK/copilot-verdict.json" \
  && ok "Copilot's refusal says deny in the field Copilot reads" \
  || bad "Copilot exits 2 but its JSON does not carry permissionDecision — the reason never reaches the model"

# The history is the audit trail. Rewriting a past entry, or dating one with
# something that is not a timestamp, has to be refused.
python3 - "$ALL" <<'PYEOF' && ok "the audit trail cannot be rewritten or misdated" || bad "a past history entry was rewritten, or a non-timestamp accepted — the trail is forgeable"
import json, os, subprocess, sys
repo = sys.argv[1]
gate = os.path.join(repo, ".ddw", "scripts", "hook-gate.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")

def h(f, t, a="a", ts="2026-01-01T00:00:00Z", tier="FEATURE"):
    return {"timestamp": ts, "from": f, "to": t, "action": a, "tier": tier}

def rc(disk, new):
    open(state, "w").write(json.dumps(disk))
    ev = json.dumps({"tool_name": "Write",
                     "tool_input": {"file_path": state, "content": json.dumps(new)}})
    return subprocess.run([sys.executable, gate, "--mode", "pre", "--state", state,
                           "--graph", graph, "--repo", repo],
                          input=ev, capture_output=True, text=True).returncode

base = {"tier": "FEATURE", "phase": "PLAN", "gates": {"define": True},
        "history": [h("IDLE", "CLASSIFY", tier=None), h("CLASSIFY", "DEFINE"),
                    h("DEFINE", "PLAN")]}
rewritten = json.loads(json.dumps(base))
rewritten["history"][1]["action"] = "FALSIFIED"
rewritten["phase"] = "CODE"
rewritten["history"].append(h("PLAN", "CODE"))
rewritten["gates"] = {"define": True, "spec": True, "threat": True}
assert rc(base, rewritten) == 2, "a past history entry was rewritten and accepted"

undated = json.loads(json.dumps(base))
undated["phase"] = "CODE"
undated["gates"] = {"define": True, "spec": True, "threat": True}
undated["history"].append(h("PLAN", "CODE", ts="whenever"))
assert rc(base, undated) == 2, "a history entry with no real timestamp was accepted"
PYEOF

# Every tier must have a route out. A tier that cannot finish traps whoever gets
# classified into it, and nothing above would have noticed.
python3 - "$SELF/ddw/rules/transition-graph.json" <<'PYEOF' && ok "every tier can reach IDLE from CLASSIFY" || bad "a tier has no route out — the pipeline traps whoever lands in it"
import json, sys
g = json.load(open(sys.argv[1], encoding="utf-8"))

def edges(tier):
    out = dict(g.get("common", {}))
    chain, cur, seen = [], tier, set()
    while cur in g["tiers"] and cur not in seen:
        seen.add(cur); chain.append(cur); cur = g["tiers"][cur].get("extends")
    for name in reversed(chain):
        out.update({k: v for k, v in g["tiers"][name].items() if k != "extends"})
    return out

for tier in g["tiers"]:
    adj = {}
    for key in edges(tier):
        src, _, dst = key.partition("->")
        adj.setdefault(src, set()).add(dst)
    # Forward: what can be reached from IDLE at all.
    seen, stack = set(), ["IDLE"]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, ()))
    reachable = {p for p in seen if p != "IDLE"}
    assert reachable, f"{tier}: nothing is reachable from IDLE"

    # Backward: what can still get back. Walking the edges in reverse is the
    # whole point — CODE reaches IDLE through VERIFY and RELEASE, so any check
    # that only looks one hop ahead invents a trap that is not there.
    rev = {}
    for src, dsts in adj.items():
        for dst in dsts:
            rev.setdefault(dst, set()).add(src)
    can_exit, stack = set(), ["IDLE"]
    while stack:
        cur = stack.pop()
        if cur in can_exit:
            continue
        can_exit.add(cur)
        stack.extend(rev.get(cur, ()))
    trapped = reachable - can_exit
    assert not trapped, f"{tier}: {', '.join(sorted(trapped))} cannot reach IDLE by any route"
PYEOF

# Resuming a paused ticket may only re-enter a phase the graph lists.

# The tier's type is checked on the value WRITTEN, not on the value it resolves
# to. When there is no previous tier the two differ, and that is the gap a poison
# value used to slip through.
python3 - "$ALL" <<'PYEOF' && ok "a falsy tier is refused even when there is no previous tier to fall back on" || bad "an empty tier was written at CLASSIFY and disarms the lock for every write after it"
import json, os, subprocess, sys
repo = sys.argv[1]
gate = os.path.join(repo, ".ddw", "scripts", "hook-gate.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
h = {"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"}
disk = {"tier": None, "phase": "CLASSIFY", "gates": {}, "history": [h]}
# In-phase, appending nothing: with a transition, a falsy tier also breaks the
# edge lookup and is refused for that reason instead — which is not evidence
# that the type check works. Here the type check is the only thing standing.
for poison in ("", [], 0, False):
    open(state, "w").write(json.dumps(disk))
    new = {"tier": poison, "phase": "CLASSIFY", "gates": {}, "history": [h]}
    ev = json.dumps({"tool_name": "Write",
                     "tool_input": {"file_path": state, "content": json.dumps(new)}})
    r = subprocess.run([sys.executable, gate, "--mode", "pre", "--state", state,
                        "--graph", graph, "--repo", repo],
                       input=ev, capture_output=True, text=True)
    assert r.returncode == 2, f"tier={poison!r} accepted with no previous tier"
PYEOF

printf '%s' "$IDLE_STATE" > "$GST"

# The frontmatter emitter, directly. Today's descriptions happen not to contain
# ": ", so nothing installed exercises the quoting — and that is precisely how
# two agents shipped unparseable.
python3 - "$SELF" <<'PYEOF' && ok "the frontmatter emitter quotes anything, including a value with a colon" || bad "the emitter would ship unparseable frontmatter the moment a description contains ': '"
import importlib.util, os, sys, yaml
spec = importlib.util.spec_from_file_location(
    "it", os.path.join(sys.argv[1], "scripts", "install_target.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
block = "\n".join(m.yaml_block({
    "name": "ddw-x",
    "description": "Read-only auditor: detects violations. Also: quotes \" and \\ backslashes.",
    "tools": "Read, Grep",
    "readonly": True,
}))
parsed = yaml.safe_load(block)
assert isinstance(parsed, dict), "the emitted frontmatter does not parse as a mapping"
assert parsed["description"].startswith("Read-only auditor: detects"), parsed["description"]
assert parsed["readonly"] is True, parsed["readonly"]
PYEOF

# An upgrade must not take a file of the user's with it. This needs a genuine
# upstream change, because that is the path where the old directory is removed.
UP2="$WORK/upgrade-userfile"; mkdir -p "$UP2"; git -C "$UP2" init -q .
cp -R "$SELF" "$WORK/ddw-next" 2>/dev/null
rm -rf "$WORK/ddw-next/.git"
bash "$WORK/ddw-next/install.sh" "$UP2" --target claude >/dev/null 2>&1
printf 'MY OWN NOTES\n' > "$UP2/.claude/skills/ddw-status/my-notes.md"
# This middle run is the whole mechanism: comparing only source -> destination,
# the directory reads as identical, gets fingerprinted WITH the user's file
# counted as ours, and only then does an upgrade remove it.
bash "$WORK/ddw-next/install.sh" "$UP2" --target claude >/dev/null 2>&1
printf '\n<!-- upstream change -->\n' >> "$WORK/ddw-next/skills/ddw-status/SKILL.md"
bash "$WORK/ddw-next/install.sh" "$UP2" --target claude >/dev/null 2>&1
[ -f "$UP2/.claude/skills/ddw-status/my-notes.md" ] \
  && ok "an upgrade of a skill leaves a file the user added inside it alone" \
  || bad "the upgrade removed the directory wholesale, taking the user's file with it"

# ── A whole legal run must stay green ─────────────────────────────────────────
#
# Half of the enforcement bugs were false POSITIVES: post mode rejected the
# corrective loop, and then every legitimate closeout, firing on every tool call
# from then on. A gate that cries wolf gets switched off, so this drives a
# complete run — including the recovery path — and asserts silence.
section "A legal run, end to end, stays silent"

RUN="$WORK/legalrun"; mkdir -p "$RUN"; git -C "$RUN" init -q .
bash "$SELF/install.sh" "$RUN" --target claude >/dev/null 2>&1
RST="$RUN/.ddw-state.json"; RG="$RUN/.ddw/rules/transition-graph.json"
rstep() { python3 "$RUN/.ddw/scripts/transition.py" "$@" --state "$RST" --graph "$RG" \
            > "$RUN/.s" 2>/dev/null && mv "$RUN/.s" "$RST"; }
rpost() { python3 "$RUN/.ddw/scripts/hook-gate.py" --mode post --state "$RST" --graph "$RG" \
            --repo "$RUN" </dev/null >/dev/null 2>&1; }
python3 "$RUN/.ddw/scripts/transition.py" --to CLASSIFY --action start --state "$RST" \
        --graph "$RG" > "$RST" 2>/dev/null
rstep --to DEFINE  --action classify --tier FEATURE
rstep --to PLAN    --action define   --gate define
rstep --to CODE    --action plan     --gate spec --gate threat
rstep --to VERIFY  --action code     --gate tests --gate sast
rpost && ok "a run up to VERIFY raises nothing" || bad "post mode flags a legal run"
rstep --to CODE --action "corrective loop: verification found problems" \
      --clear-gate tests --clear-gate sast --clear-gate verify
rpost && ok "the corrective loop — the pipeline's own recovery path — raises nothing" \
      || bad "post mode rejects the corrective loop, wedging the session on every later tool call"
rstep --to VERIFY  --action recode  --gate tests --gate sast
rstep --to RELEASE --action verify  --gate verify
python3 - "$RST" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["gates"].update(commit=True, pr=True)
json.dump(d, open(sys.argv[1], "w"))
PY
rstep --to IDLE --action "closeout: shipped"
rpost && ok "a legitimate closeout raises nothing" \
      || bad "every finished ticket is reported as an illegal state, on every tool call after it"
rpost && ok "and it keeps raising nothing on the calls after it" \
      || bad "the session is wedged after the closeout"

# ...while a forged one is still caught. The closeout check is what makes an
# illegal ticket visible the moment it completes.
python3 - "$RST" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
d["history"] += [
    {"timestamp": "2026-07-27T11:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "r"},
    {"timestamp": "2026-07-27T11:01:00Z", "from": "CLASSIFY", "to": "RELEASE",
     "action": "teleport", "tier": "FEATURE"},
    {"timestamp": "2026-07-27T11:02:00Z", "from": "RELEASE", "to": "IDLE",
     "action": "closeout", "tier": "FEATURE"}]
d["phase"] = "IDLE"; d["tier"] = None; d["gates"] = {}
json.dump(d, open(sys.argv[1], "w"))
PY
rpost && bad "a forged closeout that skipped the whole pipeline went unnoticed" \
      || ok "a forged closeout is still caught"

# OpenCode wires a JS plugin rather than a shell hook: drive the plugin itself.
if command -v node >/dev/null 2>&1; then
  cat > "$WORK/opencode-probe.mjs" <<PROBE
import { DdwPlugin } from "$ALL/.opencode/plugins/ddw.js"
const p = await DdwPlugin({ directory: "$ALL" })
let blocked = false
try {
  await p["tool.execute.before"]({ tool: "write" },
    { args: { filePath: "$ALL/.ddw-state.json", content: process.argv[2] } })
} catch { blocked = true }
process.exit(blocked ? 2 : 0)
PROBE
  node "$WORK/opencode-probe.mjs" "$ILLEGAL" >/dev/null 2>&1 \
    && bad "OpenCode: an illegal transition was ALLOWED through the plugin" \
    || ok "OpenCode refuses an illegal transition (the plugin throws)"
  node "$WORK/opencode-probe.mjs" "$LEGAL" >/dev/null 2>&1 \
    && ok "OpenCode lets a legal transition through" \
    || bad "OpenCode blocks a LEGAL transition"

  cat > "$WORK/opencode-src-probe.mjs" <<PROBE
import { DdwPlugin } from "$ALL/.opencode/plugins/ddw.js"
const p = await DdwPlugin({ directory: "$ALL" })
let blocked = false
try {
  await p["tool.execute.before"]({ tool: "write" },
    { args: { filePath: process.argv[2], content: "x = 1\n" } })
} catch { blocked = true }
process.exit(blocked ? 2 : 0)
PROBE
  printf '%s' "$IN_PLAN" > "$ALL/.ddw-state.json"
  node "$WORK/opencode-src-probe.mjs" "$ALL/src/app.py" >/dev/null 2>&1 \
    && bad "OpenCode: source code was written in PLAN — the core rule is not enforced" \
    || ok "OpenCode refuses product source while in PLAN"
  printf '%s' "$IN_CODE" > "$ALL/.ddw-state.json"
  node "$WORK/opencode-src-probe.mjs" "$ALL/src/app.py" >/dev/null 2>&1 \
    && ok "OpenCode lets source through once CODE was reached" \
    || bad "OpenCode blocks source in CODE — the guard refuses everything"
  printf '%s' "$IDLE_STATE" > "$ALL/.ddw-state.json"

  # The global install (~/.config/opencode/plugins/ + ~/.config/opencode/ddw/)
  # has no .ddw/ in the project. If ddw.js only ever looked in the repo, that
  # install would load, enforce nothing, and look identical to working.
  mkdir -p "$WORK/fakecfg/plugins" "$WORK/blankrepo"
  cp "$SELF/adapters/opencode/plugin/ddw.js" "$WORK/fakecfg/plugins/ddw.js"
  cp -r "$SELF/ddw" "$WORK/fakecfg/ddw"
  cat > "$WORK/opencode-global-probe.mjs" <<PROBE
import { DdwPlugin } from "$WORK/fakecfg/plugins/ddw.js"
const p = await DdwPlugin({ directory: "$WORK/blankrepo" })
let blocked = false
try {
  await p["tool.execute.before"]({ tool: "write" },
    { args: { filePath: "$WORK/blankrepo/.ddw-state.json", content: process.argv[2] } })
} catch { blocked = true }
process.exit(blocked ? 2 : 0)
PROBE
  node "$WORK/opencode-global-probe.mjs" "$ILLEGAL" >/dev/null 2>&1 \
    && bad "OpenCode global install: no .ddw/ in the repo and the plugin enforced NOTHING" \
    || ok "OpenCode global install still enforces: the method is found next to the plugin"

  # A plugin install that enforces but never steers is the failure the first
  # live PRD run showed: the model coded a monorepo straight from IDLE. The
  # steering is two hooks — skills registered with OpenCode's discovery, and a
  # bootstrap prefixed to the first user message — and both have to survive.
  mkdir -p "$WORK/fakecfg/skills/ddw-classify"
  printf '%s\n' "name: ddw-classify" > "$WORK/fakecfg/skills/ddw-classify/SKILL.md"
  cat > "$WORK/opencode-steer-probe.mjs" <<PROBE
import { DdwPlugin } from "$WORK/fakecfg/plugins/ddw.js"
const p = await DdwPlugin({ directory: "$WORK/blankrepo" })
const config = {}
await p["config"](config)
const registered = (config.skills?.paths ?? []).some((x) => x.includes("fakecfg/skills"))
const output = { messages: [{ info: { role: "user" }, parts: [{ type: "text", text: "implement the PRD" }] }] }
await p["experimental.chat.messages.transform"]({}, output)
const first = output.messages[0].parts[0]
const steered = first.type === "text" && first.text.includes("DDW_BOOTSTRAP") && first.text.includes("CLASSIFYING")
  && first.text.includes("do NOT install DDW into this repo")
  && first.text.includes("Never put DDW content in it")
await p["experimental.chat.messages.transform"]({}, output)
const once = output.messages[0].parts.filter((x) => x.text?.includes("DDW_BOOTSTRAP")).length === 1
process.exit(registered && steered && once ? 0 : 2)
PROBE
  node "$WORK/opencode-steer-probe.mjs" >/dev/null 2>&1 \
    && ok "OpenCode plugin steers: skills registered, bootstrap rides the first message, once" \
    || bad "OpenCode plugin install enforces but does not steer — the PRD-to-monorepo failure is back"
else
  echo "  · node not available — OpenCode's plugin was not exercised"
fi

# OpenCode's package manager reaches ddw.js through package.json. An entry
# point that names a file that moved loads as undefined and hooks nothing.
ENTRY=$(python3 -c "import json; print(json.load(open('$SELF/package.json'))['main'])" 2>/dev/null)
[ -n "$ENTRY" ] && [ -f "$SELF/$ENTRY" ] \
  && ok "package.json points OpenCode at a ddw.js that exists" \
  || bad "package.json's entry point does not resolve to a file — the npm install would hook nothing"

# Codex takes its subagents as TOML, so a broken emitter is a silent no-op.
if python3 -c "import tomllib" 2>/dev/null; then
  python3 - "$ALL" <<'PY' && ok "Codex subagents are valid TOML with their prompt intact" || bad "Codex TOML agents are malformed"
import glob, sys, tomllib
files = sorted(glob.glob(f"{sys.argv[1]}/.codex/agents/*.toml"))
assert files, "no agents were installed for Codex"
for f in files:
    d = tomllib.load(open(f, "rb"))
    for key in ("name", "description", "developer_instructions"):
        assert d.get(key), f"{f} has no {key}"
    assert len(d["developer_instructions"]) > 200, f"{f} lost its prompt body"
PY
fi

# ── The ways out of a ticket, and the ways they were bypassable ───────────────
# Each of these passed before the fix. The closeout gate is the pipeline's one
# hard promise, so every route around it gets a test.
python3 - "$G" "$R" <<'PY' && ok "walking away cannot dodge the closeout gates" || bad "the closeout gate is bypassable"
import importlib.util, json, sys
g = json.load(open(sys.argv[1]))
s = importlib.util.spec_from_file_location("v", f"{sys.argv[2]}/.ddw/scripts/validate-transition.py")
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
T = "2026-07-27T10:00:00Z"
run = [{"timestamp": T, "from": a, "to": b} for a, b in
       (("IDLE","CLASSIFY"),("CLASSIFY","DEFINE"),("DEFINE","PLAN"),
        ("PLAN","CODE"),("CODE","VERIFY"),("VERIFY","RELEASE"))]
earned = {k: True for k in ("define","spec","threat","tests","sast","verify")}   # no commit, no pr
def attempt(action, src="RELEASE", tier="FEATURE", gates=None, hist=None):
    h = hist if hist is not None else run
    entry = {"timestamp": T, "from": src, "to": "IDLE", "action": action}
    return ({"phase": src, "tier": tier, "gates": gates if gates is not None else earned, "history": h},
            {"phase": "IDLE", "tier": None, "gates": {}, "history": h + [entry]})
def blocked(*a, **k):
    try:
        m.validate(*attempt(*a, **k), graph=g, max_appended=1); return False
    except m.Block:
        return True
assert blocked("abandon"),                  "abandon walked out of RELEASE without commit+pr"
assert blocked("pause: later"),             "pause walked out of RELEASE without commit+pr"
assert blocked("abandonware cleanup"),      "an unanchored prefix match counted as an abandon"
assert blocked("done"),                     "a plain closeout skipped its gates"
# ...while walking away from a phase that IS abandonable still works.
mid = run[:4]
try:
    m.validate(*attempt("abandon: wrong call", src="CODE",
                        gates={"define": True, "spec": True, "threat": True}, hist=mid),
               graph=g, max_appended=1)
except m.Block as exc:
    raise AssertionError(f"abandoning from CODE was refused: {exc}")
PY

python3 - "$G" "$R" <<'PY' && ok "one write, one transition; tier and gates cannot leak past IDLE" || bad "sequencing or gate isolation is broken"
import importlib.util, json, sys
g = json.load(open(sys.argv[1]))
s = importlib.util.spec_from_file_location("v", f"{sys.argv[2]}/.ddw/scripts/validate-transition.py")
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
T = "2026-07-27T10:00:00Z"
run = [{"timestamp": T, "from": a, "to": b} for a, b in
       (("IDLE","CLASSIFY"),("CLASSIFY","DEFINE"),("DEFINE","PLAN"),
        ("PLAN","CODE"),("CODE","VERIFY"),("VERIFY","RELEASE"))]
full = {k: True for k in ("define","spec","threat","tests","sast","verify")}
def blocked(old, new, **kw):
    try:
        m.validate(old, new, g, **kw); return False
    except m.Block:
        return True
# the whole pipeline asserted in a single write
assert blocked({"phase":"IDLE","tier":None,"gates":{},"history":[]},
               {"phase":"RELEASE","tier":"FEATURE","gates":full,"history":run},
               max_appended=1), "a single write declared six transitions"
# closing out while keeping the tier / the gates
closed = run + [{"timestamp": T, "from":"RELEASE","to":"IDLE","action":"done"}]
paid = dict(full, commit=True, pr=True)
assert blocked({"phase":"RELEASE","tier":"FEATURE","gates":paid,"history":run},
               {"phase":"IDLE","tier":"FEATURE","gates":{},"history":closed},
               max_appended=1), "the tier survived the closeout"
assert blocked({"phase":"RELEASE","tier":"FEATURE","gates":paid,"history":run},
               {"phase":"IDLE","tier":None,"gates":paid,"history":closed},
               max_appended=1), "the gates survived the closeout"
# hopping tier mid-run to reach an edge the real tier gates
mid = run[:5]
assert blocked({"phase":"VERIFY","tier":"FEATURE",
                "gates":{"define":True,"spec":True,"threat":True,"tests":True,"sast":True},
                "history":mid},
               {"phase":"RELEASE","tier":"QUICK-FIX",
                "gates":{"define":True,"tests":True,"sast":True},
                "history":mid+[{"timestamp":T,"from":"VERIFY","to":"RELEASE"}]},
               max_appended=1), "the tier changed mid-run to dodge a gate"
# a state whose types are nonsense must be refused, not crash into a fail-open
assert blocked({"phase":"IDLE","tier":None,"gates":{},"history":[]},
               {"phase":"CLASSIFY","tier":["FEATURE"],"gates":{},
                "history":[{"timestamp":T,"from":"IDLE","to":"CLASSIFY"}]},
               max_appended=1), "a list-valued tier crashed instead of blocking"
PY

# The corrective loop is the pipeline's own recovery path: post mode must accept
# it. It used to reject it, because it replayed old edges against today's gates.
LOOP="$WORK/loop"; mkdir -p "$LOOP"; git -C "$LOOP" init -q .
bash "$SELF/install.sh" "$LOOP" --target claude >/dev/null 2>&1
TRL="$LOOP/.ddw/scripts/transition.py"
lstep() { python3 "$TRL" "$@" --state "$LOOP/.ddw-state.json" --graph "$G" > "$LOOP/s" 2>/dev/null \
          && cp "$LOOP/s" "$LOOP/.ddw-state.json"; }
python3 "$TRL" --to CLASSIFY --action r --state "$LOOP/.ddw-state.json" --graph "$G" > "$LOOP/.ddw-state.json"
lstep --to DEFINE --action c --tier FEATURE
lstep --to PLAN   --action p --gate define
lstep --to CODE   --action x --gate spec --gate threat
lstep --to VERIFY --action x --gate tests --gate sast
lstep --to CODE   --action "corrective loop" --clear-gate tests --clear-gate sast
python3 "$LOOP/.ddw/scripts/validate-transition.py" --mode post --state "$LOOP/.ddw-state.json" --graph "$G" >/dev/null 2>&1 \
  && ok "post mode accepts the corrective loop it used to reject" \
  || bad "post mode rejects the documented corrective loop"
python3 "$TRL" --to VERIFY --action x --state "$LOOP/.ddw-state.json" --graph "$G" >/dev/null 2>&1 \
  && bad "the corrective loop returned to VERIFY on gates it had already invalidated" \
  || ok "--clear-gate makes the fix re-earn tests+sast"

# ── QUICK-FIX scope guard ─────────────────────────────────────────────────────
# Two ways this guard has silently stopped guarding: a trunk not called `main`
# (git errors, the count reads 0, anything passes) and counting the phase's own
# committed artifacts against a budget meant for code.
QF="$WORK/qf"; mkdir -p "$QF"
git -C "$QF" init -q -b master .
git -C "$QF" config user.email ddw@test && git -C "$QF" config user.name ddw
# This is the only fixture that commits. Whoever runs the suite may sign their
# commits by default; a throwaway repo must not ask them for a passphrase, and
# a signing timeout must not read as "the size guard is broken".
git -C "$QF" config commit.gpgsign false
mkdir -p "$QF/src" "$QF/docs/ddw/prd"
echo "x = 1" > "$QF/src/a.py"
bash "$SELF/install.sh" "$QF" --target claude >/dev/null 2>&1
# DDW's own files belong to the trunk, like any other tooling: commit them there
# so they are not part of a later branch's diff.
git -C "$QF" add -A && git -C "$QF" commit -qm "base + ddw"
echo '{"tier":"QUICK-FIX","phase":"CODE","gates":{},"history":[]}' > "$QF/.ddw-state.json"
qf_write() { printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$QF/src/a.py" \
  | python3 "$QF/.ddw/scripts/hook-gate.py" --dialect standard --mode pre \
      --state "$QF/.ddw-state.json" --graph "$QF/.ddw/rules/transition-graph.json" --repo "$QF"; }

git -C "$QF" checkout -qb fix/QF-1
seq 1 40 >> "$QF/src/a.py"
git -C "$QF" add -A && git -C "$QF" commit -qm oversized
qf_write >/dev/null 2>&1 \
  && bad "QUICK-FIX size guard failed open on a repo whose trunk is not 'main'" \
  || ok "QUICK-FIX size guard detects the base branch (not hardcoded to main)"

git -C "$QF" checkout -q master && git -C "$QF" checkout -qb fix/QF-2
seq 1 30 | sed 's/^/brief line /' > "$QF/docs/ddw/prd/fix-QF-2.md"
echo "y = 2" >> "$QF/src/a.py"
git -C "$QF" add -A && git -C "$QF" commit -qm "brief + one line of code"
qf_write >/dev/null 2>&1 \
  && ok "QUICK-FIX budget counts code, not the phase's own committed artifacts" \
  || bad "QUICK-FIX blocked by its own fix-brief (docs/ddw/ must not count)"

# ── Did the whole suite actually run? ─────────────────────────────────────────
# The single highest-leverage line in this file. Everything above can be made to
# pass by not running: an absent tool, an unsupported `find`, a loop over an
# empty list. Each of those printed a green N/N with a smaller N, and nobody can
# eyeball a total they never memorised. So the run declares up front how many
# checks it owes, and this is where it settles the account.
section "The suite ran in full"
if [ "$EXPECT_CHECKS" -eq 0 ]; then
  ok "check total not pinned yet (set EXPECT_CHECKS to $((CHECKS + 1)) at the top of this file)"
elif [ "$CHECKS" -eq "$((EXPECT_CHECKS - 1))" ]; then
  ok "all $EXPECT_CHECKS checks ran"
else
  bad "only $((CHECKS + 1)) of $EXPECT_CHECKS checks ran — something skipped itself and a smaller green total hid it"
fi

# ── Verdict ───────────────────────────────────────────────────────────────────
printf '\n\033[1m%s\033[0m\n' "──────────────────────────────────────────"
if [ "$FAILS" -eq 0 ]; then
  printf '\033[32m%d/%d checks passed.\033[0m\n' "$CHECKS" "$CHECKS"
else
  printf '\033[31m%d of %d checks FAILED.\033[0m\n' "$FAILS" "$CHECKS"
fi
exit $((FAILS > 0))
