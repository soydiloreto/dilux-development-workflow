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

# Bump this when you add or remove a check, on purpose. NOT read from the
# environment: `EXPECT_CHECKS=0` used to print "check total not pinned yet" as a
# PASS, so a run of 43 of 523 checks exited 0 — the pinned total is the one thing
# standing between "the suite passed" and "the suite stopped early", and it was
# a knob anyone could turn from outside the file. `docs/AI-POLICY.md` and
# `CONTRIBUTING.md` both name this variable as the thing not to soften; it was
# softenable without editing the file they were talking about.
EXPECT_CHECKS=665
EXPECT_SKILLS=20
EXPECT_AGENTS=5
EXPECT_RULES=14
EXPECT_ADAPTERS=6
# The mutation list is the coverage figure, and its length was pinned nowhere:
# `grep -rn 366` over the whole tree returned nothing. Deleting entries left
# `--check-anchors`, `--cover` and every check in this file green, and the
# published percentage went on being a percentage of a smaller list. The same
# reason `EXPECT_CHECKS` exists, one file over.
EXPECT_MUTATIONS=758

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# EXPORTED, because the Python blocks below anchor their own temporary
# directories to it: `tempfile.mkdtemp(dir=os.environ["WORK"])` registers no finaliser and cleans up
# nothing, so fifty-four of them per run were left behind for good. One run of
# this file leaked ~50 directories and nobody noticed; one mutation run, which
# is this file once per fault across ten parallel shards, put 38 GB and 36,000
# entries into /tmp in two hours. The leak was never in `mutate.py` — it was
# here, and the mutations only multiplied it.
#
# One place is responsible for cleanup, and it is the trap on the next line.
export WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILS=0
CHECKS=0
SKIPS=0

ok()   { CHECKS=$((CHECKS+1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
# `DDW_STOP_ON_FIRST_FAILURE` stops the run at the first ✗, and it exists for one
# caller: `scripts/mutate.py`, which asks a yes/no question — did the suite go
# red — four hundred times. Answering it costs a full pass today, and most faults
# die in the first minute of one, so the run spends the rest of the pass proving
# something nobody asked. This can only ever make a FAILING run shorter: it is
# reached from `bad` and nowhere else, and it exits 1. There is no value of this
# variable that turns a red run green, which is what separates it from
# `EXPECT_CHECKS` — a knob that could soften a verdict, and therefore one this
# file refuses to read from the environment.
bad()  {
  CHECKS=$((CHECKS+1)); FAILS=$((FAILS+1)); printf '  \033[31m✗\033[0m %s\n' "$1"
  if [ -n "${DDW_STOP_ON_FIRST_FAILURE:-}" ]; then
    printf '\n\033[31mStopped at the first failure (DDW_STOP_ON_FIRST_FAILURE), after %d checks.\033[0m\n' "$CHECKS"
    printf 'This run answers "did the suite go red", not "how many checks pass". Unset the\n'
    printf 'variable for the full report.\n'
    exit 1
  fi
}
skip() { CHECKS=$((CHECKS+1)); SKIPS=$((SKIPS+1)); printf "  \033[33m—\033[0m %s\n" "$1"; }   # counted, and counted SEPARATELY: a check that did not run is not a check that passed, and the verdict has to say so
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

for TOOL in git python3 rsync node claude; do
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

MUT_N="$(python3 "$SELF/scripts/mutate.py" --list | grep -cE '^ *[0-9]+\.')"
[ "$MUT_N" = "$EXPECT_MUTATIONS" ] \
  && ok "$EXPECT_MUTATIONS mutations, the number the coverage figure is a percentage of" \
  || bad "expected $EXPECT_MUTATIONS mutations, found $MUT_N — deleting one deletes the measurement, not the cost"

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

# WHICH tools, and not merely that the field is there. Four of the five agents
# exist to look and report — the security auditor, the architecture auditor, the
# impact scanner and the module verifier — and every one of them is spawned to
# JUDGE something: the code, the reports, the verdict a gate will rest on. A
# judge that can edit what it is judging is not a judge, and the only thing
# standing between the two is a line of frontmatter that nothing read. Add
# `Write` to the security auditor and no check in this repository goes red.
#
# The implementer is the exception and the reason the list is spelled out rather
# than inferred: it writes code, that IS its job, and what stops it from writing
# DDW's own files is the hook rather than its tool list.
python3 - "$SELF" <<'PYAGENTTOOLS' && ok "the four agents that only judge cannot write, and the one that implements is the only one that can" || bad "an agent spawned to audit something carries a tool that edits it"
import glob, os, sys, yaml
root = sys.argv[1]
WRITERS = {"ddw-implementer"}
FORBIDDEN = {"write", "edit", "notebookedit", "multiedit", "apply_patch", "patch"}
seen = set()
for path in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
    d = yaml.safe_load(open(path, encoding="utf-8").read().split("---\n", 2)[1])
    name = d["name"]
    seen.add(name)
    tools = {t.strip().lower() for t in str(d["tools"]).split(",") if t.strip()}
    writes = sorted(tools & FORBIDDEN)
    if name in WRITERS:
        assert writes, "%s is the agent that implements and carries no writing tool" % name
        continue
    assert not writes, (
        "%s is spawned to judge and carries %s. It can edit the thing it was asked to report on."
        % (name, ", ".join(writes)))
assert WRITERS <= seen, "the implementer is gone from agents/, so this check is judging nothing"
assert len(seen - WRITERS) >= 3, \
    "fewer than three read-only agents remain (%s) — this check was written for four" % sorted(seen)
PYAGENTTOOLS

# `/ddw-eject` told the model to copy the plugin's method into `.ddw/`, and every
# write to `.ddw/` is refused in every phase — the seal that stops a pipeline
# editing the rules that stop it, which cannot tell installing the method apart
# from disarming it. A painted door: the model does exactly what the skill says
# and is refused, in any phase, with the ticket open. So the skill hands over a
# command instead, and the command has to exist and work.
python3 - "$SELF" <<'PYEJECTCMD' && ok "/ddw-eject prescribes a command the user runs, and that command lands the method and records it" || bad "the eject skill orders a write its own enforcement refuses, or prescribes a command that does not work"
import json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
skill = open(os.path.join(src, "skills/ddw-eject/SKILL.md"), encoding="utf-8").read()
import re as _re
assert _re.search(r"^\s*bash .*install\.sh.* --method-only", skill, _re.M), \
    ("the eject skill no longer carries the command the user runs. Naming the flag in prose is "
     "not the same as handing over the line to paste — and the write it used to prescribe "
     "instead is refused by the hook in every phase.")

# The refusal is real, and it is what the skill has to route around: a write to
# `.ddw/` mid-ticket, judged by the gate every tool runs.
work = tempfile.mkdtemp(dir=os.environ["WORK"])
plug = os.path.join(work, "plugin")
shutil.copytree(src, plug, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
repo = os.path.join(work, "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
state = os.path.join(repo, ".ddw-state.json")
json.dump({"phase": "CODE", "ticket": "T-1", "tier": "FEATURE",
           "gates": {"define": True, "spec": True, "threat": True},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "a"},
                       {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
                        "action": "b", "tier": "FEATURE", "ticket": "T-1"}]},
          open(state, "w", encoding="utf-8"))
ev = json.dumps({"tool_name": "Write",
                 "tool_input": {"file_path": os.path.join(repo, ".ddw/rules/code.instructions.md"),
                                "content": "x"}})
r = subprocess.run([sys.executable, os.path.join(plug, "ddw/scripts/hook-gate.py"),
                    "--dialect", "standard", "--mode", "pre", "--state", state,
                    "--graph", os.path.join(plug, "ddw/rules/transition-graph.json"),
                    "--repo", repo, "--method", os.path.join(plug, "ddw")],
                   input=ev, capture_output=True, text=True)
assert r.returncode == 2, \
    "a write into `.ddw/` was allowed — the seal this skill has to route around is gone"

# And the way around it lands the method AND records it: an ejected method the
# drift detector cannot see is the one people go on to edit.
r = subprocess.run(["bash", os.path.join(plug, "install.sh"), repo, "--method-only"],
                   capture_output=True, text=True)
assert r.returncode == 0, "install.sh --method-only failed: " + (r.stdout + r.stderr)[-300:]
assert os.path.isfile(os.path.join(repo, ".ddw/rules/transition-graph.json")), \
    "the method did not land in .ddw/"
manifest = json.load(open(os.path.join(repo, ".ddw-installed.json"), encoding="utf-8"))
assert [k for k in manifest if k.startswith("method:")], \
    "the ejected method is in no manifest, so no drift check can see it change"
assert not os.path.exists(os.path.join(repo, ".claude")), \
    "--method-only touched the wiring; the skill promises it does not"
PYEJECTCMD

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
# A validated phase artifact, the way a PASSED validation leaves it: the document
# on disk, and the content-hashed receipt in .ddw-sessions/ naming it. Six of the
# eight gates read exactly this pair, and a gate claimed with neither is refused —
# so a fixture that claims one has to have earned it, or it is refused for the
# wrong reason and whatever it was testing goes untested.
#
#   ddw_earn <repo> <gate> <ticket>
ddw_earn() {
  python3 - "$1" "$2" "$3" <<'DDWEARN'
import hashlib, json, os, sys
repo, gate, ticket = sys.argv[1:4]
WHERE = {"define": ("prd", "prd", "prd"), "spec": ("specs", "spec", "spec"),
         "threat": ("security", "threat", "threat"), "verify": ("reports", "verify", "verify"),
         "tests": ("reports", "tests", "tests"), "sast": ("security", "sast", "sast")}
subdir, stem, receipt = WHERE[gate]
d = os.path.join(repo, "docs", "ddw", subdir)
os.makedirs(d, exist_ok=True)
path = os.path.join(d, "%s-%s.md" % (stem, ticket))
if not os.path.exists(path):
    open(path, "w", encoding="utf-8").write("# %s for %s\n" % (stem, ticket))
text = open(path, encoding="utf-8").read()
sess = os.path.join(repo, ".ddw-sessions")
os.makedirs(sess, exist_ok=True)
digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
name = "%s-validated-%s" % (receipt, digest)
open(os.path.join(sess, name), "w").write(os.path.basename(path))
# …and the journal line a real validator leaves, because the gate asks for both:
# a receipt nobody's validator is recorded as having written is a forged one.
with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"record": "receipt", "name": name,
                         "file": os.path.basename(path)}, sort_keys=True) + "\n")
DDWEARN
}

R="$WORK/fsm"; mkdir -p "$R"; git -C "$R" init -q .
bash "$SELF/install.sh" "$R" --target claude >/dev/null 2>&1
export CLAUDE_PROJECT_DIR="$R"
TR="$R/.ddw/scripts/transition.py"; G="$R/.ddw/rules/transition-graph.json"
for _g in define spec threat tests sast verify; do ddw_earn "$R" "$_g" T-1; done

python3 "$TR" --to DEFINE --action x --graph "$G" >/dev/null 2>&1 \
  && bad "IDLE->DEFINE should be rejected" || ok "rejects IDLE->DEFINE (not in graph)"
python3 "$TR" --to CLASSIFY --action req --ticket T-1 --graph "$G" > "$R/.ddw-state.json" 2>/dev/null \
  && ok "accepts IDLE->CLASSIFY" || bad "IDLE->CLASSIFY failed"
python3 "$TR" --to DEFINE --action c --tier FEATURE --title "the fixture ticket" --graph "$G" > "$R/s" 2>/dev/null \
  && { cp "$R/s" "$R/.ddw-state.json"; ok "accepts CLASSIFY->DEFINE with a tier"; } || bad "CLASSIFY->DEFINE failed"
python3 "$TR" --to CODE --action x --graph "$G" >/dev/null 2>&1 \
  && bad "DEFINE->CODE should need gates" || ok "rejects DEFINE->CODE (FEATURE needs PLAN)"
python3 "$TR" --to PLAN --action p --gate define --graph "$G" >/dev/null 2>&1 \
  && ok "accepts DEFINE->PLAN once the define gate is set" || bad "DEFINE->PLAN with gate failed"
# Every tier in the graph must be reachable through the sanctioned helper. Reset
# to a fresh CLASSIFY each time: the tier is set on the edge leaving CLASSIFY.
#
# The list is DERIVED, and the sentence above is why. It was typed — QUICK-FIX,
# FIX, FEATURE, DISCOVERY — under a comment claiming to cover the graph, and the
# day a fifth tier was added the loop went on testing four and stayed green.
# FREE was reachable in the graph, listed in the state schema, refused by the
# sanctioned helper (whose own tier list was typed too), and no check noticed for
# a day. Each tier's destination comes from the graph as well: whatever
# `CLASSIFY->X` that tier defines.
TIER_DESTS="$(python3 - "$G" <<'PYTIERS'
import json, sys
graph = json.load(open(sys.argv[1], encoding="utf-8"))
tiers = graph.get("tiers", {})


def edges(tier):
    """The tier's own edges plus the ones it inherits — `extends`, walked."""
    out = {k for k in graph.get("common", {}) if not k.startswith("_")}
    seen, cur = set(), tier
    while cur in tiers and cur not in seen:
        seen.add(cur)
        out |= {k for k in tiers[cur] if "->" in k and not k.startswith("_")}
        cur = tiers[cur].get("extends")
    return out


for tier in sorted(tiers):
    dest = [e.split("->", 1)[1] for e in sorted(edges(tier)) if e.startswith("CLASSIFY->")]
    if dest:
        print("%s:%s" % (tier, dest[0]))
PYTIERS
)"
[ -n "$TIER_DESTS" ] || bad "no tier in the graph declares an edge out of CLASSIFY"
# Word splitting, not a pipe: `... | while read` runs the body in a subshell, and
# every `ok` in there increments a counter that dies with it — a loop of checks
# that never reach the total this file pins.
for PAIR in $TIER_DESTS; do
  TIER="${PAIR%%:*}"; DEST="${PAIR##*:}"
  python3 "$TR" --to CLASSIFY --action req --ticket T-1 --graph "$G" > "$R/.ddw-state.json" 2>/dev/null
  # FREE is the one tier whose edge costs the user's own words, quoted. Every
  # other tier takes any action at all, and that asymmetry is the point: the
  # loop would pass just as well with `free: "…"` everywhere, and then nothing
  # here would notice the day the requirement spread to tiers the user never
  # has to ask for.
  CACT=c
  [ "$TIER" = "FREE" ] && CACT='free: "hacelo sin pipeline, me hago cargo"'
  if python3 "$TR" --to "$DEST" --action "$CACT" --tier "$TIER" --title "the fixture ticket" --graph "$G" >/dev/null 2>&1; then
    ok "tier $TIER: CLASSIFY->$DEST accepted"
  else
    bad "tier $TIER: CLASSIFY->$DEST REJECTED"
  fi
done
# And the graph must actually enforce each tier's shape, not just accept the tier.
python3 "$TR" --to CLASSIFY --action req --ticket T-1 --graph "$G" > "$R/.ddw-state.json" 2>/dev/null
python3 "$TR" --to DEFINE --action c --tier QUICK-FIX --title "the fixture ticket" --graph "$G" > "$R/s" 2>/dev/null && cp "$R/s" "$R/.ddw-state.json"
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
# rests on: you cannot reach IDLE from CLOSEOUT without a commit and a PR.
CLOSE="$WORK/close"; mkdir -p "$CLOSE"; git -C "$CLOSE" init -q .
bash "$SELF/install.sh" "$CLOSE" --target claude >/dev/null 2>&1
export CLAUDE_PROJECT_DIR="$CLOSE"
TRC="$CLOSE/.ddw/scripts/transition.py"
for _g in define spec threat tests sast verify; do ddw_earn "$CLOSE" "$_g" T-1; done
step() { python3 "$TRC" "$@" --graph "$G" > "$CLOSE/s" 2>/dev/null && cp "$CLOSE/s" "$CLOSE/.ddw-state.json"; }
python3 "$TRC" --to CLASSIFY --action r --ticket T-1 --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DEFINE --action c --tier FEATURE --title "the fixture ticket"
step --to PLAN   --action p --gate define
step --to CODE   --action x --gate spec --gate threat
step --to VERIFY --action x --gate tests --gate sast
step --to CLOSEOUT --action x --gate verify
python3 "$TRC" --to IDLE --action done --graph "$G" >/dev/null 2>&1 \
  && bad "closed WITHOUT commit+pr" || ok "closeout blocked without commit+pr"
# `--claim commit`, which is what the product orders, and not `--gate commit`:
# that flag is rejected outright on `--to IDLE` — "--gate is not read on --to
# IDLE" — so this check was sending exactly the same input as the one above and
# could not tell "commit paid and pr missing" from "neither of the two". Two
# checks, one single question, and the second green for lack of anything else
# to say.
python3 "$TRC" --claim commit --graph "$G" >/dev/null 2>&1
python3 "$TRC" --to IDLE --action done --graph "$G" >/dev/null 2>&1 \
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
python3 "$TRC" --to CLASSIFY --action r --ticket T-1 --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DEFINE --action c --tier FEATURE --title "the fixture ticket"
step --to PLAN --action p --gate define
python3 "$TRC" --to IDLE --action "abandon: wrong classification" --graph "$G" >/dev/null 2>&1 \
  && ok "abandoning from PLAN stays ungated" || bad "abandoning was blocked"
python3 "$TRC" --to IDLE --action "discarded" --graph "$G" >/dev/null 2>&1 \
  && bad "reached IDLE off-graph without declaring the abandon" || ok "an undeclared exit to IDLE is refused"
# The tier built for exploring ideas has to let you drop one that did not hold up.
python3 "$TRC" --to CLASSIFY --action r --ticket T-1 --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DISCOVERY --action d --tier DISCOVERY --title "the fixture ticket"
python3 "$TRC" --to IDLE --action done --graph "$G" >/dev/null 2>&1 \
  && bad "DISCOVERY closed without commit+pr" || ok "DISCOVERY closeout still needs commit+pr"
python3 "$TRC" --to IDLE --action "abandon: the idea does not hold up" --graph "$G" >/dev/null 2>&1 \
  && ok "DISCOVERY: a discarded idea can be abandoned" || bad "DISCOVERY traps you in the pipeline"
# And the closeout fallback must not let a corrective loop reuse stale gates.
python3 "$TRC" --to CLASSIFY --action r --ticket T-1 --graph "$G" > "$CLOSE/.ddw-state.json" 2>/dev/null
step --to DEFINE --action c --tier FEATURE --title "the fixture ticket"
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
bad = {"tier":"FEATURE","phase":"CLOSEOUT","gates":{},"history":json.load(open(f"{repo}/.ddw-state.json"))["history"]}
print(json.dumps({"tool_name":"Write","tool_input":{"file_path":f"{repo}/.ddw-state.json","content":json.dumps(bad)}}))
PY
python3 "$V" --mode pre --state "$R/.ddw-state.json" --graph "$G" < "$R/ev.json" >/dev/null 2>&1 \
  && bad "PreToolUse should block a phase jump" || ok "PreToolUse blocks an illegal write (exit 2)"
python3 "$V" --mode post --state "$R/.ddw-state.json" --graph "$G" </dev/null >/dev/null 2>&1 \
  && ok "PostToolUse accepts a legal state on disk" || bad "PostToolUse rejects a legal state"

# ── The two Claude hook manifests must stay the same manifest ─────────────────
# One wires the drop-in install, the other the (in-progress) plugin. Same seven
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
# The tickets the fixtures below claim gates for, with the artifacts and receipts
# that make those claims legal. A negative fixture refused for the wrong reason
# proves nothing about the rule it was written for.
for _t in T-1 FEAT-001 EVIL-1 Q-1; do
  for _g in define spec threat tests sast verify; do ddw_earn "$ALL" "$_g" "$_t"; done
done

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
ILLEGAL='{"phase":"CLOSEOUT","tier":"FEATURE","gates":{},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CLOSEOUT"}]}'
LEGAL='{"phase":"CLASSIFY","tier":null,"gates":{},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CLASSIFY","action":"classify"}]}'
IDLE_STATE='{"phase":"IDLE","tier":null,"gates":{},"history":[]}'
# The one rule the pipeline is built to guarantee. The FSM only ever guarded the
# state file, so PLAN forbidding source was a line in a prompt and nothing
# outside the model checked it. Both phases are exercised: a guard that refuses
# everything is as broken as one that refuses nothing.

IN_PLAN='{"ticket":"T-1","phase":"PLAN","tier":"FEATURE","gates":{"define":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"PLAN"}]}'
IN_CODE='{"ticket":"T-1","phase":"CODE","tier":"FEATURE","gates":{"define":true,"spec":true,"threat":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CODE"}]}'

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

WHOLE_RUN='{"tier":"FEATURE","phase":"CLOSEOUT","ticket":"T-1","gates":{"define":true,"spec":true,"threat":true,"tests":true,"sast":true,"verify":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-07-27T10:00:01Z","from":"CLASSIFY","to":"DEFINE","action":"a"},{"timestamp":"2026-07-27T10:00:02Z","from":"DEFINE","to":"PLAN","action":"a"},{"timestamp":"2026-07-27T10:00:03Z","from":"PLAN","to":"CODE","action":"a"},{"timestamp":"2026-07-27T10:00:04Z","from":"CODE","to":"VERIFY","action":"a"},{"timestamp":"2026-07-27T10:00:05Z","from":"VERIFY","to":"CLOSEOUT","action":"a"}]}'

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
  *"❌ F-PRD-06"*"FR-01"*) ok "and it names the broken rule by ID — the checklist is script output, not model courtesy" ;;
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

# A claim EVENT is an audit record, and an audit record nothing backs is the
# laundering it exists to prevent: a hand-written history that appends
# `claim: define` and flips the gate, with no receipt on disk and no journal
# blessing, must be refused by the post net — that demand lives in the claim
# branch of the replay itself, and a fault that silences it (mutation: "a claim
# event stops owing its receipt") has to turn THIS check red.
FC="$WORK/forged-claim"; mkdir -p "$FC"
python3 - "$FC" "$SELF" <<'PYFORGEDCLAIM' && ok "a forged claim event with no receipt behind it is refused by the post net" || bad "a hand-written 'claim: define' entry opens the gate with no receipt — history can launder gates"
import json, os, subprocess, sys
repo = sys.argv[1]
self_dir = sys.argv[2]
e = lambda f, t, a: {"timestamp": "2026-01-01T00:00:00Z", "from": f, "to": t,
                     "action": a, "tier": "FEATURE", "ticket": "T-1"}
# CLASSIFY only, then the forged claim: this history has NO edge that owes
# `define`, so the ONLY net that can refuse it is the claim branch itself —
# which is exactly what makes this check able to kill the mutation. A longer
# history (with DEFINE->PLAN in it) is refused by the edge-owed arm too, and
# a check two nets protect cannot tell when one of them dies.
h = [e("IDLE", "CLASSIFY", "clasificar: probar"),
     e("CLASSIFY", "CLASSIFY", "claim: define")]
st = {"tier": "FEATURE", "phase": "CLASSIFY", "ticket": "T-1", "title": "t",
      "autonomy": None, "gates": {"define": True}, "block": None,
      "discovery": None, "tracker": None, "history": h}
with open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8") as fh:
    json.dump(st, fh)
r = subprocess.run([sys.executable, os.path.join(self_dir, "ddw/scripts/validate-transition.py"),
                    "--mode", "post", "--state", os.path.join(repo, ".ddw-state.json"),
                    "--graph", os.path.join(self_dir, "ddw/rules/transition-graph.json")],
                   capture_output=True, text=True)
assert r.returncode == 2, "the forged claim passed the post net: " + (r.stdout + r.stderr)[:220]
said = (r.stdout + r.stderr).lower()
assert "evidence" in said or "receipt" in said, \
    "the refusal does not say what the claim is missing: " + (r.stdout + r.stderr)[:220]
PYFORGEDCLAIM

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
  *"❌ F-SPEC-06"*"Block 1"*) ok "and it names the block with no tests by rule ID — the checklist is script output, not model courtesy" ;;
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

# F-SPEC-01 reads the coverage table and reports every FR covered; W-SPEC-01 read
# only the block's own body. One run printed "all FR are referenced by a block"
# and "block referencing no FR" about the same block, three lines apart — and a
# validator that contradicts itself in one output teaches the reader to skip both
# rows, which is how a real warning stops being read.
python3 - "$VS/spec-FEAT-001.md" "$VS/spec-covered-elsewhere.md" <<'PYWSPEC'
import sys
t = open(sys.argv[1], encoding="utf-8").read()
open(sys.argv[2], "w", encoding="utf-8").write(t.replace("Implementa FR-01.", "Implementa el alta."))
PYWSPEC
WSPOUT="$(python3 "$SELF/ddw/scripts/validate_spec.py" "$VS/spec-covered-elsewhere.md" --tier FEATURE \
         --prd "$VP/docs/ddw/prd/prd-FEAT-001.md" 2>/dev/null || true)"
case "$WSPOUT" in
  *"W-SPEC-01"*) bad "W-SPEC-01 warns that a block references no FR while F-SPEC-01 reports that same block covering one" ;;
  *) ok "a block the coverage table maps to an FR raises no warning about referencing none — one output, one answer" ;;
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
# Built with python3, not `grep -v -A`: that combination prints the WHOLE file
# (the -A window re-adds every line -v removed), so the "broken" fixture was
# byte-identical to the sound one and the check asserted the opposite of what it
# says. It was green either way, twice over — the pattern also matched the ✅ row.
python3 - "$VS" <<'PYNOROLL'
import os, re, sys
p = os.path.join(sys.argv[1], "fix-FIX-002.md")
s = open(p, encoding="utf-8").read()
s = re.sub(r"^## Rollback plan.*?(?=^## |\Z)", "", s, flags=re.S | re.M)
open(os.path.join(sys.argv[1], "fix-norollback.md"), "w", encoding="utf-8").write(s)
PYNOROLL
VFOUT="$(python3 "$SELF/ddw/scripts/validate_spec.py" "$VS/fix-norollback.md" --tier FIX 2>/dev/null || true)"
case "$VFOUT" in
  *"❌ F-SPEC-15"*) ok "and a fix-plan with no rollback plan is named by its rule ID" ;;
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
# The refusal has to say the category is ABSENT. Asking only for the ID and the
# name accepted the wrong diagnosis: with the missing-category branch dead the
# validator still refused and still said "Repudiation", but as "still the
# template's placeholder" — a category that was deleted reported as one that was
# left unfilled. The author is told to fill in a line that is not in the file.
case "$VTOUT" in
  *"❌ F-TM-01"*missing*Repudiation*) ok "and a missing STRIDE category is named as missing — a five-sixths analysis is not one" ;;
  *"❌ F-TM-01"*Repudiation*) bad "a deleted STRIDE category is reported as an unfilled one: $VTOUT" ;;
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

# W-SAST-01 counts the WORD "low". A report whose summary says `0 Low` is the
# report stating there are none, and warning about those made a clean report
# carry a warning about findings it does not have — while a report that really
# lists Low findings has to keep raising it.
python3 - "$VTM" <<'PYWSAST'
import os, sys
p = os.path.join(sys.argv[1], "sast-FEAT-001.md")
s = open(p, encoding="utf-8").read()
open(os.path.join(sys.argv[1], "sast-zero-low.md"), "w", encoding="utf-8").write(
    s.replace("Total: 16 clean, 1 vulnerability (0 critical, 0 high)",
              "Total: 16 clean, 1 vulnerability (0 critical, 0 high, 0 low)\nLow: 0"))
open(os.path.join(sys.argv[1], "sast-three-low.md"), "w", encoding="utf-8").write(
    s.replace("Total: 16 clean, 1 vulnerability (0 critical, 0 high)",
              "Total: 16 clean, 1 vulnerability (0 critical, 0 high, 3 low)\nLow: 3 sin registrar"))
PYWSAST
WSAZ="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-zero-low.md" --tier FEATURE \
       --today 2026-08-02 2>/dev/null || true)"
WSAT="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-three-low.md" --tier FEATURE \
       --today 2026-08-02 2>/dev/null || true)"
case "$WSAZ$WSAT" in
  *"W-SAST-01"*) case "$WSAZ" in
                   *"W-SAST-01"*) bad "a report that says it found zero Low findings is warned about its Low findings" ;;
                   *) ok "a count of zero closes W-SAST-01, and three still open it — the rule reads the number next to the word" ;;
                 esac ;;
  *) bad "W-SAST-01 stopped firing on a report with three undocumented Low findings" ;;
esac

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
  *"❌ F-SAST-VERDICT"*) ok "and a Critical finding above a PASSED verdict is refused, by the rule that fixes severities" ;;
  *) bad "a report listing a hardcoded secret and declaring PASSED earned a receipt" ;;
esac

# The cheapest bypass either script had: a Critical filed under a warning marker
# owed no location, no BLOCKED verdict and no suppression — all three rules read
# only `found`. The catalog fixes the severity per category and says a confirmed
# vulnerability can never be a WARNING.
python3 - "$VTM" <<'PYSEV'
import sys, os
p = os.path.join(sys.argv[1], "sast-FEAT-001.md")
s = open(p, encoding="utf-8").read().replace(
    "| F-SAST-01 | ✅ | sin secretos embebidos; la key sale de .env |",
    "| F-SAST-01 | ⚠️ | app/config.py:9 — clave embebida, la juzgo un fixture |")
open(os.path.join(sys.argv[1], "sast-warned.md"), "w", encoding="utf-8").write(s)
PYSEV
VSWOUT="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-warned.md" --tier FEATURE \
         --today 2026-08-02 2>/dev/null || true)"
case "$VSWOUT" in
  *"❌ F-SAST-SEVERITY"*) ok "and a Critical filed under a warning marker is refused — a marker does not change a severity" ;;
  *) bad "a hardcoded secret marked ⚠️ skipped location, verdict and suppression at once" ;;
esac

# §4.1: Critical and High are not suppressible. The seven fields were being
# validated for a finding the catalog says has to be fixed.
python3 - "$VTM" <<'PYSUPC'
import sys, os
p = os.path.join(sys.argv[1], "sast-FEAT-001.md")
s = open(p, encoding="utf-8").read() + """

### Suppression: F-SAST-01

| Field | Value |
|---|---|
| File | app/config.py:9 |
| Category | hardcoded secrets |
| Disposition | FALSE_POSITIVE |
| Reviewer | Pablo Di Loreto |
| Date | 2026-08-02 |
| Justification | es un fixture de test |
| Review by | 2026-12-01 |
"""
open(os.path.join(sys.argv[1], "sast-supcrit.md"), "w", encoding="utf-8").write(s)
PYSUPC
VSCOUT="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-supcrit.md" --tier FEATURE \
         --today 2026-08-02 2>/dev/null || true)"
case "$VSCOUT" in
  *"❌ F-SAST-SUPPRESS"*) ok "and a Critical filed as suppressed is refused — those get fixed, not documented" ;;
  *) bad "a hardcoded secret was suppressed with seven tidy fields and earned the gate" ;;
esac

# A category with no verdict was not evaluated, and silence is the shape an
# unrun check takes. This is the rule the other nineteen were waiting for.
grep -v 'F-SAST-07' "$VTM/sast-FEAT-001.md" > "$VTM/sast-gap.md"
VSGOUT="$(python3 "$SELF/ddw/scripts/validate_sast.py" "$VTM/sast-gap.md" --tier FEATURE \
         --today 2026-08-02 2>/dev/null || true)"
case "$VSGOUT" in
  *"❌ F-SAST-COVERAGE"*F-SAST-07*) ok "and a category left with no verdict is named, not averaged away" ;;
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
  *"❌ F-SAST-19"*) ok "and a suppression past its review date is refused — six months is the catalog's number" ;;
  *) bad "a suppression that expired seven months ago still opened the gate" ;;
esac

# …and the day that rule is measured against is the CALLER'S to choose. `--today`
# decides which suppressions have expired, and nothing recorded the answer: a
# report whose reviews lapsed months ago passed by naming a day they were still
# fresh, and left a receipt byte-identical to one earned this morning. The tier
# had exactly this shape and was closed the same way — the receipt records the
# clock, and the gate asks.
python3 - "$SELF" "$VTM/sast-FEAT-001.md" <<'PYASOF' && ok "the SAST receipt records the clock its suppressions were aged against, and the gate refuses one earned against another day" || bad "the day the suppressions were judged against is the caller's to pick and nothing records it"
import datetime, importlib.util, json, os, shutil, subprocess, sys, tempfile
src, fixture = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)

repo = tempfile.mkdtemp(dir=os.environ["WORK"])
subprocess.run(["git", "init", "-q", repo], check=True)
os.makedirs(os.path.join(repo, "docs/ddw/security"))
report = os.path.join(repo, "docs/ddw/security/sast-T-1.md")
shutil.copyfile(fixture, report)
state = {"phase": "CODE", "ticket": "T-1", "tier": "FEATURE", "gates": {}, "history": []}


def validate(*extra):
    return subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate_sast.py"),
                           report, "--tier", "FEATURE", *extra],
                          capture_output=True, text=True, cwd=repo)


other_day = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
r = validate("--today", other_day)
assert r.returncode == 0, "the fixture report no longer passes: " + (r.stdout + r.stderr)[-300:]
receipts = [f for f in os.listdir(os.path.join(repo, ".ddw-sessions")) if f.startswith("sast-")]
assert receipts, "no receipt was written, so there is nothing to ask about"
body = open(os.path.join(repo, ".ddw-sessions", receipts[0]), encoding="utf-8").read()
assert "asof: %s" % other_day in body, "the receipt does not record the clock it used: " + body

reason = vt.gate_evidence_missing(repo, state, ["sast"])
assert reason and other_day in reason, \
    ("a receipt earned against another day opened the sast gate — %r" % reason)

# …and re-running it today, which is what the refusal asks for, is what fixes it.
assert validate().returncode == 0, "the report no longer passes under today's clock"
assert vt.gate_evidence_missing(repo, state, ["sast"]) is None, \
    "re-validating under today's clock does not open the gate — the refusal asks for a move that does not work"
PYASOF


# The mutation run has to ask whether its own faults still apply BEFORE it starts
# injecting them, and it has to ask against the tree as it is. This check lived
# in the mutated copy for one afternoon and fabricated 180 kills: the suite ran
# inside the copy where the fault under test had just deleted its own anchor, so
# the suite went red by construction and every one of those faults was recorded
# as caught. An instrument that reports success for its own side effect is not a
# weak measurement, it is not a measurement.
python3 - "$SELF" <<'PYPRE' && ok "the mutation run verifies its anchors before injecting, against the real tree" || bad "nothing checks the anchors, or it checks them from inside the copy and scores its own footprint"
import os, re, sys
src = open(os.path.join(sys.argv[1], "scripts/mutate.py"), encoding="utf-8").read()
main = src[src.index("def main("):]
assert re.search(r"if check_anchors\(\) != 0:\s*\n\s*return 1", main), \
    "main() does not run the anchor preflight"
assert main.index("check_anchors()") < main.index("for i, (label, mutate) in chosen"), \
    "the preflight runs after the injection loop, which is not a preflight"
suite = open(os.path.join(sys.argv[1], "scripts/verify_install.sh"), encoding="utf-8").read()
assert not re.search(r"mutate\.py\S*\s+--check-anchors", suite), (
    "the suite INVOKES the anchor check — inside the mutated copy it goes red for the "
    "mutation's own footprint and hands it a kill it did not earn")
PYPRE

# One fault is one full run of the suite, and most faults die in the first
# minute of a pass that then runs to the end proving something nobody asked.
# Four hundred times, that is the difference between a measurement anyone runs
# and a measurement people start deleting faults from — and deleting faults
# deletes the measurement, not the cost.
python3 - "$SELF" <<'PYFAST' && ok "the mutation runner can stop the suite at the first ✗, and that switch can only ever shorten a failing run" || bad "the suite runs to the end for a yes/no question, or the switch that shortens it could change a verdict"
import os, re, shutil, subprocess, sys, tempfile
src = sys.argv[1]
suite = open(os.path.join(src, "scripts/verify_install.sh"), encoding="utf-8").read()

# It is read from `bad` and nowhere else. Anywhere else it could skip a check
# rather than end a run that has already failed, which is the difference between
# a shortcut and a softened verdict — `EXPECT_CHECKS` is the cautionary tale, and
# it is refused from the environment for exactly this reason.
# The needle is built rather than written, so this check does not count itself.
# And the runner that pays for it has to ASK for it. Without this, every fault
# runs the entire suite after having proven what it had to prove: the full run
# went from ~13 minutes to over an hour, and the saving shows in no ✗ —
# nothing fails, it just takes longer. The baseline is the exception and has to
# stay one: it measures that the suite is green WHOLE, not up to the first problem.
runner = open(os.path.join(src, "scripts/mutate.py"), encoding="utf-8").read()
# Asked of the FUNCTION, not of the file. The file also holds the list of faults,
# and one of those faults is written as the literal this looks for — so read
# whole, the runner answers "yes" out of the description of removing it. Measured
# live: the fault survived, found by its own text.
_run_one = runner[runner.index("def run_one("):]
_run_one = _run_one[:_run_one.index("\ndef ", 1)]
assert 'DDW_STOP_ON_FIRST_FAILURE' in _run_one, \
    ("the runner no longer asks the suite to stop at the first failure, so every fault pays the "
     "whole suite after the answer is already known — a cost that shows up as an hour of wall "
     "clock and never as a red check")
_base = runner[runner.index("def baseline("):]
_base = _base[:_base.index("\ndef ", 1)]
assert "DDW_STOP_ON_FIRST_FAILURE" not in _base, \
    ("the baseline stops at the first failure too, so it stops being a baseline: it would report "
     "an already-red suite as red for one reason and never see the others")

needle = "${" + "DDW_STOP_ON_FIRST_FAILURE:-}"
assert suite.count(needle) == 1, \
    "the stop switch is read in %d places; it belongs in `bad` alone" % suite.count(needle)
body = suite[suite.index("bad()  {"):]
body = body[:body.index("\nskip()")]
assert needle in body and "exit 1" in body, \
    "the stop switch is not in `bad`, or no longer exits non-zero from it:\n" + body

# Driven: a copy whose first check fails, run with the switch on. It has to end
# straight away, non-zero, saying which question it answered.
probe = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "method")
shutil.copytree(src, probe, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
victim = os.path.join(probe, "scripts/verify_install.sh")
text = open(victim, encoding="utf-8").read()
anchor = "section() {"
assert anchor in text, "the suite no longer defines section() where this check looks"
at = text.index(anchor)
end = text.index("\n", text.index("}", at))
open(victim, "w", encoding="utf-8").write(
    text[:end + 1] + '\nbad "a failure planted by the suite\'s own check on the stop switch"\n'
    + text[end + 1:])
r = subprocess.run(["bash", victim], capture_output=True, text=True, cwd=probe,
                   env=dict(os.environ, DDW_STOP_ON_FIRST_FAILURE="1"), timeout=300)
assert r.returncode != 0, "a run with a planted failure exited 0 under the stop switch"
assert "Stopped at the first failure" in r.stdout, \
    "the run did not say it had stopped early: " + r.stdout[-300:]
ran = len([ln for ln in r.stdout.splitlines() if "✓" in ln or "✗" in ln])
assert ran < 20, \
    "the run kept going for %d checks after the first failure — the switch did nothing" % ran
PYFAST

# And the other half of the same cost: a pull request does not have to ask
# whether the suite can fail EVERYWHERE, only whether it can still fail where
# the diff went. The whole list stays whole and runs on main and on the weekly
# schedule; that run is the coverage figure and this one is not.
python3 - "$SELF" <<'PYCHANGED' && ok "a diff selects the mutations that name its files, the suite and the runner select all of them, and a narrowed run says so" || bad "the pull request's mutation run silently measures a subset, or a diff touching the instrument narrows anything at all"
import importlib.util, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "method")
shutil.copytree(src, work, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
subprocess.run(["git", "-C", work, "init", "-q"], check=True)
for k, v in (("user.email", "t@e.st"), ("user.name", "t"), ("commit.gpgsign", "false")):
    subprocess.run(["git", "-C", work, "config", k, v], check=True)
subprocess.run(["git", "-C", work, "add", "-A"], check=True, capture_output=True)
subprocess.run(["git", "-C", work, "commit", "-qm", "base"], check=True, capture_output=True)
base = subprocess.run(["git", "-C", work, "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()

spec = importlib.util.spec_from_file_location("mut", os.path.join(work, "scripts/mutate.py"))
mut = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mut)
total = len(mut.MUTATIONS)


def after_touching(rel):
    path = os.path.join(work, rel)
    open(path, "a", encoding="utf-8").write("\n")
    subprocess.run(["git", "-C", work, "commit", "-qam", "touch " + rel],
                   check=True, capture_output=True)
    return mut.changed_mutations(base)


# A validator: only the faults that name it.
picked = after_touching("ddw/scripts/validate_threat.py")
assert 0 < len(picked) < total, \
    "touching one validator selected %d of %d mutations" % (len(picked), total)
assert all(mut.MUTATIONS[i - 1][1].probe[1] == "ddw/scripts/validate_threat.py"
           for i in picked if getattr(mut.MUTATIONS[i - 1][1], "probe", None)), \
    "the selection includes faults that name another file"

# The suite itself: every fault, because the answer for all of them may have moved.
assert len(after_touching("scripts/verify_install.sh")) == total, \
    "a diff touching the suite narrowed the run — the one file whose change can flip any fault"

# And a diff no mutation names at all — a docs-only change, the ordinary case —
# has to SAY that it injected nothing. A run that prints a percentage over an
# empty selection, or prints nothing and exits 0, is the quiet cap this file
# refuses everywhere else.
subprocess.run(["git", "-C", work, "checkout", "-q", "-b", "docs-only", base], check=True)
open(os.path.join(work, "SECURITY.md"), "a", encoding="utf-8").write("\n")
subprocess.run(["git", "-C", work, "commit", "-qam", "docs"], check=True, capture_output=True)
r = subprocess.run([sys.executable, os.path.join(work, "scripts/mutate.py"), "--changed", base],
                   capture_output=True, text=True, cwd=work, timeout=120)
assert r.returncode == 0, "a docs-only diff failed the mutation run: " + (r.stdout + r.stderr)[-300:]
assert "injects nothing" in r.stdout, \
    "the run said nothing about having injected nothing: " + r.stdout[-300:]
assert "faults caught" not in r.stdout, \
    "an empty selection printed a percentage: " + r.stdout[-300:]
PYCHANGED

# The state a session materialises has to carry the field, or the mode has
# nowhere to live: `session-boot.py` writes the first state every repo ever gets.
SBA="$WORK/autonomy-boot"; mkdir -p "$SBA"; git -C "$SBA" init -q .
mkdir -p "$SBA/.ddw"
python3 "$SELF/ddw/scripts/session-boot.py" --repo "$SBA" --session-id a1 >/dev/null 2>&1
python3 - "$SBA" <<'PYSB' && ok "a freshly materialised state carries `autonomy`, so the mode has somewhere to live" || bad "the state template dropped the field the whole mode is carried in"
import json, os, sys
st = json.load(open(os.path.join(sys.argv[1], ".ddw-state.json"), encoding="utf-8"))
assert "autonomy" in st, "the materialised state has no `autonomy` key"
assert st["autonomy"] is None, f"a fresh state opts into a mode: {st['autonomy']!r}"
PYSB

# `ticket` was the only header field with no shape check. A ticket of the wrong
# STRING was refused and a ticket of the wrong TYPE was accepted, because every
# downstream comparison filters with `isinstance(t, str)` first — so the guards
# written to keep the checks from crashing were doubling as escape hatches.
# A family repo does not leave CLASSIFY unanalysed. The impact gate on
# CLASSIFY->DEFINE demands the verdict file AND its content-hashed receipt;
# a verdict edited after validation is a dead receipt. Three doors in one
# fixture: refused empty-handed (kills "the impact gate vanishes from the
# family's classify edge"), opened by a validated verdict, and shut again by
# one appended byte (kills "an impact verdict edited after validation keeps
# its dead receipt").
# The one-approve index's two safety properties, against a forge shim.
# Door one — the LEASH: a PR touching code is refused BEFORE the forge is
# asked to merge (kills "the leash stops reading the diff"). Door two — the
# LAW: `done` without a MERGED child PR is refused naming the declared out
# (kills "a row says done on anyone's word").
# The walk's conductor decides over the FORGE, in the order that cannot
# mislead: a stale row (child merged, row not done) outranks the walk, and a
# dependency is satisfied only by a MERGE — never by another row's recorded
# status. Pure function, no forge needed; kills "the stale index stops
# outranking the walk" and "dependencies become satisfied by the index's word".
python3 - "$SELF" <<'PYWALK' && ok "the conductor corrects the stale row first, and only a MERGE unblocks a dependency" || bad "the walk trusts the index over the forge — a recorded status unblocked a child, or a stale row was walked past"
import importlib.util, os, sys
src = sys.argv[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(src, path))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
vt = load("vt", "ddw/scripts/validate-transition.py")
fnx = load("fnx", "ddw/scripts/family_next.py")
def rows(*specs):
    lines = ["| Repo | Ticket | Scope | Depends on | Status |", "|---|---|---|---|---|"]
    for repo, deps, status in specs:
        lines.append("| acme/%s | T-1 | parte %s | %s | %s |" % (repo, repo, deps, status))
    return vt.parse_family_rows("\n".join(lines) + "\n")
# Door one: index SAYS done, forge shows no merge -> nothing unblocks.
v = fnx.decide(rows(("pagos", "none", "done"), ("back", "pagos", "pending")),
               {"pagos": None, "back": None})
assert v["kind"] == "waiting" and v["waits"][0]["on"] == ["pagos"], \
    "a recorded `done` with no merge at the forge unblocked a dependent: %r" % v
# Door two: child merged, row still active -> the update outranks the walk.
v = fnx.decide(rows(("pagos", "none", "active"), ("back", "pagos", "pending")),
               {"pagos": 7, "back": None})
assert v["kind"] == "update" and v["pr"] == 7, \
    "a merged child with a stale row was walked past instead of corrected: %r" % v
# Door three — the PARALLEL set: only forge-unblocked, never-merged rows ride
# (kills "a blocked child rides the parallel set" and "a merged child is
# launched again by the parallel set").
three = rows(("pagos", "none", "active"), ("catalogo", "none", "pending"),
             ("back", "pagos", "pending"))
listos = [r["repo"] for r in fnx.ready(three, {"pagos": None, "catalogo": None,
                                               "back": None})]
assert listos == ["acme/pagos", "acme/catalogo"], \
    "the parallel set carries a child whose dependency never merged: %r" % listos
listos = [r["repo"] for r in fnx.ready(three, {"pagos": 3, "catalogo": None,
                                               "back": None})]
assert listos == ["acme/catalogo", "acme/back"], \
    "a merged child stayed in the parallel set, or its merge unblocked nobody: %r" % listos
PYWALK

LSH="$WORK/leash"; mkdir -p "$LSH/ws" "$LSH/bin"; git -C "$LSH/ws" init -q .
git -C "$LSH/ws" remote add origin https://github.com/acme/ws.git
# The DEPRECATED map name, on purpose: existing families must keep working
# while new maps are born as ddw-family.md — this fixture is the fallback's proof.
printf '# familia\n' > "$LSH/ws/familia.md"
cat > "$LSH/bin/gh" <<'LSHGH'
#!/usr/bin/env python3
import json, os, sys
open(os.environ["LSH_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a[:2] == ["pr", "view"]:
    print(json.dumps({"state": "OPEN", "baseRefName": "main",
                      "files": [{"path": "docs/ddw/prd/prd-T-1.md"},
                                {"path": "app/main.py"}]})); sys.exit(0)
if a[:2] == ["pr", "list"]:
    print("[]"); sys.exit(0)
print("{}"); sys.exit(0)
LSHGH
chmod +x "$LSH/bin/gh"
: > "$LSH/calls.log"
if LSH_LOG="$LSH/calls.log" PATH="$LSH/bin:$PATH" \
   python3 "$SELF/ddw/scripts/family_index_pr.py" merge --pr 7 --root "$LSH/ws" >/dev/null 2>"$LSH/err"; then
  bad "a PR with app/main.py in it was merged by the one-approve leash"
else
  grep -q "app/main.py" "$LSH/err" && ! grep -q '"pr", "merge"' "$LSH/calls.log" \
    && ok "the leash refuses a PR that touches code, before the forge is ever asked to merge" \
    || bad "the leash refused without naming the file, or refused after asking the forge: $(tail -1 "$LSH/err")"
fi
: > "$LSH/calls.log"
if LSH_LOG="$LSH/calls.log" PATH="$LSH/bin:$PATH" \
   python3 "$SELF/ddw/scripts/family_index_pr.py" update-row --ticket T-1 \
     --repo-row acme/child --status done --root "$LSH/ws" >/dev/null 2>"$LSH/err"; then
  bad "a row said done with no MERGED child PR at the forge"
else
  grep -q "MERGED" "$LSH/err" && grep -q "unverified" "$LSH/err" \
    && ok "done is not anyone's to write: no merged child PR, no row — and the declared out is taught" \
    || bad "the done refusal neither names the missing merge nor teaches the declared out: $(tail -1 "$LSH/err")"
fi

# The organization sweep: the forge lists EVERY repo, each AGENTS.md is read
# by API, and the report buckets every single one. Door one — the account:
# five repos in, five accounted, the unreachable one NAMED (kills "an
# unreachable repo vanishes from the sweep's account"). Door two — membership
# is what a repo DECLARES: the standalone never rides into a family (kills
# "a repo with no family reads as family material").
ORG="$WORK/orgsweep"; mkdir -p "$ORG/bin"
cat > "$ORG/bin/gh" <<'ORGGH'
#!/usr/bin/env python3
import base64, json, sys
a = sys.argv[1:]
arg = a[1] if len(a) > 1 else ""
FAM = ("## Repo family\n\n| Field | Value |\n|---|---|\n| Family | tienda |\n"
       "| Workspace | acme/ws |\n| Provides | api |\n| Consumed by | none |\n"
       "| Consumes | none |\n")
REPOS = {"ws": FAM, "api": FAM, "web": FAM, "solo": "# solo\n", "ghost": None}
if a[:1] == ["api"] and arg.endswith("/repos"):
    print("\n".join(sorted(REPOS))); sys.exit(0)
if a[:1] == ["api"] and "/contents/AGENTS.md" in arg:
    t = REPOS.get(arg.split("repos/")[1].split("/contents")[0].split("/")[-1])
    if t is None:
        sys.exit(1)
    print(json.dumps({"sha": "abc",
                      "content": base64.b64encode(t.encode()).decode()}))
    sys.exit(0)
sys.exit(1)
ORGGH
chmod +x "$ORG/bin/gh"
if ORGOUT="$(PATH="$ORG/bin:$PATH" python3 "$SELF/ddw/scripts/family_catalog.py" --org acme 2>"$ORG/err")"; then
  echo "$ORGOUT" | grep -q "5 repos listados" && echo "$ORGOUT" | grep -q "1 inalcanzables" \
    && echo "$ORGOUT" | grep -q "✗ ghost" \
    && ok "the org sweep accounts for every repo the forge lists, and an unreachable one is NAMED — never a smaller green total" \
    || bad "the sweep's account lost a bucket, or the unreachable repo went unnamed: $(echo "$ORGOUT" | head -1)"
  echo "$ORGOUT" | grep -q "· api" && ! echo "$ORGOUT" | grep -q "· solo" \
    && echo "$ORGOUT" | grep -q "1 sin sección" \
    && ok "membership is what a repo DECLARES — the sweep never drafts a standalone into a family" \
    || bad "a standalone repo rode into a family, or was not counted apart: $(echo "$ORGOUT" | head -1)"
else
  bad "the org sweep failed on a healthy five-repo fixture: $(tail -1 "$ORG/err")"
  bad "membership unmeasured — the sweep did not run"
fi

# A truncated audit and a finished one look identical — unless the contract
# demands the closing tally on BOTH sides: the auditor writes it, the caller
# refuses a report without it (kills "the auditor's closing tally quietly
# disappears").
grep -q "HALLAZGOS: <N> — lista completa" "$SELF/agents/ddw-arch-auditor.md" \
  && grep -q "HALLAZGOS: <N> — lista completa" "$SELF/agents/ddw-sec-auditor.md" \
  && grep -q "HALLAZGOS: <N> — lista completa" "$SELF/ddw/rules/code.instructions.md" \
  && grep -q "HALLAZGOS: <N> — lista completa" "$SELF/ddw/rules/plan.instructions.md" \
  && ok "a truncated audit cannot pass as finished: the closing tally is demanded by the auditors and by every caller" \
  || bad "the closing-tally contract is gone from an auditor or a caller — a cut report reads as complete again"

# Parallel tickets ride one worktree each, and `close` carries the guards the
# install must prove where it stands: a DIRTY worktree stands whatever the
# forge says (kills "a dirty worktree is removed anyway, work and all"), and a
# clean one still needs the forge's MERGED word or an explicit drop (kills
# "a worktree closes on anyone's word").
WTR="$WORK/worktree"; mkdir -p "$WTR/bin" "$WTR/seed"; git -C "$WTR/seed" init -q .
git -C "$WTR/seed" -c user.email=t@t -c user.name=t commit -q --allow-empty -m seed
git clone -q --bare "$WTR/seed" "$WTR/origin.git" 2>/dev/null
git clone -q "$WTR/origin.git" "$WTR/repo" 2>/dev/null
printf '{"ticket": "OLD-1"}\n' > "$WTR/repo/.ddw-state.json"
# The standing tree is mid-ticket: a local commit ahead of origin. The new
# worktree must NOT start there — origin's default is the only honest base
# (kills "the new worktree starts where the standing tree stands").
git -C "$WTR/repo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m half-done
WTT="$WTR/repo--wt-t-9"
if python3 "$SELF/ddw/scripts/ticket_worktree.py" open --ticket T-9 --root "$WTR/repo" >/dev/null 2>"$WTR/err"; then
  [ -d "$WTT" ] && [ ! -f "$WTT/.ddw-state.json" ] \
    && [ "$(git -C "$WTT" rev-parse HEAD)" = "$(git -C "$WTR/repo" rev-parse origin/HEAD)" ] \
    && ok "a ticket opens its own worktree — fresh at origin's default, no state inherited" \
    || bad "the worktree is missing, inherited the standing state, or did not start at origin"
else
  bad "ticket_worktree open failed on a plain repo: $(tail -1 "$WTR/err")"
fi
git -C "$WTR/repo" remote set-url origin https://github.com/acme/child.git
cat > "$WTR/bin/gh" <<'WTGH'
#!/usr/bin/env python3
print('[{"number": 7, "headRefName": "feat/T-9-x"}]')
WTGH
chmod +x "$WTR/bin/gh"
echo "x = 1" > "$WTT/avance.py"
if PATH="$WTR/bin:$PATH" python3 "$SELF/ddw/scripts/ticket_worktree.py" close --ticket T-9 --root "$WTR/repo" >/dev/null 2>"$WTR/err"; then
  bad "a DIRTY worktree was closed — uncommitted work removed with the forge's blessing"
else
  grep -q "avance.py" "$WTR/err" && [ -d "$WTT" ] \
    && ok "a dirty worktree stands, whatever the forge says, and the refusal names the file" \
    || bad "the dirty refusal lost the worktree or does not name the file: $(tail -1 "$WTR/err")"
fi
rm -f "$WTT/avance.py"
cat > "$WTR/bin/gh" <<'WTGH2'
#!/usr/bin/env python3
print("[]")
WTGH2
chmod +x "$WTR/bin/gh"
if PATH="$WTR/bin:$PATH" python3 "$SELF/ddw/scripts/ticket_worktree.py" close --ticket T-9 --root "$WTR/repo" >/dev/null 2>"$WTR/err"; then
  bad "a clean worktree closed on nobody's word — no merged PR, no drop"
else
  grep -q "MERGED" "$WTR/err" && grep -q "drop" "$WTR/err" \
    && ok "a worktree does not close on anyone's word: no merged PR, no removal — and the declared out is taught" \
    || bad "the close refusal neither names the missing merge nor teaches the drop: $(tail -1 "$WTR/err")"
fi
if PATH="$WTR/bin:$PATH" python3 "$SELF/ddw/scripts/ticket_worktree.py" close --ticket T-9 --drop "se descartó" --root "$WTR/repo" >/dev/null 2>"$WTR/err"; then
  [ ! -d "$WTT" ] \
    && ok "the declared drop, with its reason, is what removes an unmerged worktree" \
    || bad "the drop said yes but the worktree is still there"
else
  bad "the declared drop was refused on a clean worktree: $(tail -1 "$WTR/err")"
fi

IMP="$WORK/impact-gate"; mkdir -p "$IMP/.ddw-work" "$IMP/.ddw-sessions"; git -C "$IMP" init -q .
printf 'Nothing to report.\n' > "$IMP/.ddw-work/context-check-T-1.md"
python3 - "$SELF" "$IMP" <<'PYIMPACT' && ok "a family repo owes the impact verdict to leave CLASSIFY, honours its receipt, and shuts on a post-validation edit" || bad "a family repo left CLASSIFY with no impact analysis, or with a verdict its receipt no longer matches"
import hashlib, json, os, subprocess, sys
self_dir, repo = sys.argv[1], sys.argv[2]
open(os.path.join(repo, "AGENTS.md"), "w", encoding="utf-8").write(
    "# r\n\n## Repo family\n\n| Field | Value |\n|---|---|\n"
    "| Family | tienda |\n| Workspace | acme/ws |\n| Provides | api |\n"
    "| Consumed by | none |\n| Consumes | none |\n")
state = os.path.join(repo, ".ddw-state.json")
open(state, "w", encoding="utf-8").write(json.dumps({
    "tier": "FEATURE", "phase": "CLASSIFY", "ticket": "T-1", "title": "t",
    "tracker": None, "autonomy": None, "gates": {}, "block": None,
    "discovery": None,
    "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                 "to": "CLASSIFY", "action": "c", "tier": "FEATURE",
                 "ticket": "T-1"}]}))
START = open(state, encoding="utf-8").read()
def helper():
    return subprocess.run(
        [sys.executable, os.path.join(self_dir, "ddw/scripts/transition.py"),
         "--state", state, "--graph",
         os.path.join(self_dir, "ddw/rules/transition-graph.json"),
         "--to", "DEFINE", "--action", "definir", "--write"],
        capture_output=True, text=True, cwd=repo,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=repo))
r = helper()
assert r.returncode == 2 and "family_impact.py" in r.stderr, \
    "no verdict on disk and the edge opened anyway: " + (r.stderr or r.stdout)[:200]
verdict = "impacta: este repo. Sin impacto: el resto, porque nadie consume lo nuevo."
open(os.path.join(repo, ".ddw-work", "impact-T-1.md"), "w", encoding="utf-8").write(verdict)
digest = hashlib.sha256(verdict.encode("utf-8")).hexdigest()[:12]
open(os.path.join(repo, ".ddw-sessions", "impact-validated-" + digest), "w").write("x")
r = helper()
assert r.returncode == 0, "a validated verdict was refused: " + (r.stderr or r.stdout)[:200]
open(state, "w", encoding="utf-8").write(START)   # back to CLASSIFY for door three
open(os.path.join(repo, ".ddw-work", "impact-T-1.md"), "a", encoding="utf-8").write("!")
r = helper()
assert r.returncode == 2 and "edited after" in r.stderr, \
    "one byte after validation and the edge still opened: " + (r.stderr or r.stdout)[:200]
PYIMPACT

TKS="$WORK/ticket-shape"; mkdir -p "$TKS/.ddw-work"; git -C "$TKS" init -q .
# The classify edge's context check — a different gate than the one under test.
printf 'Nothing to report.\n' > "$TKS/.ddw-work/context-check-T-1.md"
python3 - "$SELF" "$TKS" <<'PYTICKET' && ok "a `ticket` of the wrong TYPE is refused, like every other header field" || bad "the state header takes a ticket of any type — the one field whose shape nothing checks"
import json, os, subprocess, sys
src, repo = sys.argv[1], sys.argv[2]
graph = os.path.join(src, "ddw/rules/transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
helper = os.path.join(src, "ddw/scripts/transition.py")
for args in (["--to", "CLASSIFY", "--action", "classify the request"],
             ["--to", "DEFINE", "--tier", "FEATURE", "--ticket", "T-1", "--action", "a feature",
              "--title", "the fixture ticket"]):
    r = subprocess.run([sys.executable, helper, *args, "--state", state, "--graph", graph, "--write"],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the helper could not build the fixture: " + (r.stdout + r.stderr)[:200]
good = json.load(open(state, encoding="utf-8"))


def rc(ticket):
    json.dump(dict(good, ticket=ticket), open(state, "w", encoding="utf-8"))
    return subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate-transition.py"),
                           "--mode", "post", "--state", state, "--graph", graph],
                          capture_output=True, text=True).returncode


assert rc("T-1") == 0, "the run that was just built is refused with its own ticket"
for wrong in (["T-1"], {"id": "T-1"}, 5, True, ""):
    assert rc(wrong) == 2, f"a ticket of type {type(wrong).__name__} was accepted: {wrong!r}"
PYTICKET

# A refusal that states the fact and not the move is where a model starts
# improvising, and what it improvises is editing the state by hand — which the
# hook then refuses for a second reason, in a message just as final. These three
# are the ones a real run hits most, and each has to name the command that
# resolves it.
python3 - "$SELF" <<'PYSAYSHOW' && ok "the refusals a run actually hits name the move, not only the fact" || bad "a refusal states what is wrong and nothing about what to do — which is where hand-editing the state starts"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt3", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json")))


def refusal(old, new):
    try:
        m.validate(old, new, g, max_appended=1)
    except m.Block as exc:
        return str(exc)
    raise AssertionError("this write was accepted, so it refuses nothing to read")


def st(phase, hist, gates=None, tier="FEATURE", ticket="T-1"):
    return {"tier": tier, "phase": phase, "ticket": ticket, "title": None, "tracker": None,
            "autonomy": None, "gates": dict(gates or {}), "block": None, "discovery": None,
            "history": list(hist)}


H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "tier": "FEATURE", "ticket": "T-1"}]

# A gate that is not paid: the message has to name the validator that earns it
# and the command that claims it.
said = refusal(st("DEFINE", H), st("PLAN", H + [{"timestamp": "2026-01-01T00:02:00Z",
                                                 "from": "DEFINE", "to": "PLAN", "action": "c",
                                                 "tier": "FEATURE", "ticket": "T-1"}]))
assert "validate_prd.py" in said and "--claim define" in said, \
    "the gate refusal names neither the validator that earns it nor the claim: " + said[:200]

# A self-edge that is not a claim event: the one in-phase entry the history
# accepts is `action: "claim: <gates>"` — anything else at `from == to` is the
# malformed history it always was, and the refusal has to teach the one shape
# that passes, or a model pokes at the wall until it invents a worse one.
same = refusal(st("DEFINE", H), st("DEFINE", H + [{"timestamp": "2026-01-01T00:02:00Z",
                                                   "from": "DEFINE", "to": "DEFINE", "action": "c",
                                                   "tier": "FEATURE", "ticket": "T-1"}]))
assert "one in-phase entry" in same.lower() and "--claim" in same, \
    "a self-edge refusal does not teach the claim event that passes: " + same[:200]

# History appended from a phase the disk is not at: re-read and append from there.
apart = refusal(st("DEFINE", H), st("CODE", H + [{"timestamp": "2026-01-01T00:02:00Z",
                                                  "from": "PLAN", "to": "CODE", "action": "c",
                                                  "tier": "FEATURE", "ticket": "T-1"}]))
assert "re-read" in apart.lower() and ".ddw-state.json" in apart, \
    "the mismatch names the two phases and no way back: " + apart[:200]
PYSAYSHOW

# A pause at CLOSEOUT is allowed once the work is committed and the pull request
# is open — you are waiting on a person, not dodging a gate. An abandon there is
# still refused, which is what the rule was written for: relabel the exit and
# ship with no commit and no PR.
python3 - "$SELF" <<'PYPAUSE' && ok "CLOSEOUT takes a pause once commit and pr are paid, and still refuses an abandon" || bad "the pause exception at CLOSEOUT is a skeleton key, or it refuses the case it exists for"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json")))
EDGES = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN"), ("PLAN", "CODE"),
         ("CODE", "VERIFY"), ("VERIFY", "CLOSEOUT")]
H = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
      "tier": "FEATURE", "ticket": "T-1"} for i, (f, t) in enumerate(EDGES)]
FULL = {"define": True, "spec": True, "threat": True, "tests": True, "sast": True,
        "verify": True, "commit": True, "pr": True}


def rel(gates):
    return {"tier": "FEATURE", "phase": "CLOSEOUT", "ticket": "T-1", "title": None, "tracker": None,
            "autonomy": None, "gates": dict(gates), "block": None, "discovery": None, "history": H}


def out(action):
    return {"tier": None, "phase": "IDLE", "ticket": None, "title": None, "tracker": None,
            "autonomy": None, "gates": {}, "block": None, "discovery": None,
            "history": H + [{"timestamp": "2026-01-01T02:00:00Z", "from": "CLOSEOUT", "to": "IDLE",
                             "action": action, "tier": "FEATURE", "ticket": "T-1"}]}


def blocked(old, new):
    try:
        m.validate(old, new, g, max_appended=1)
        return False
    except m.Block:
        return True


assert not blocked(rel(FULL), out("pause: waiting on review")), \
    "a pause at CLOSEOUT with the work committed and the PR open is refused"
assert blocked(rel({k: v for k, v in FULL.items() if k != "pr"}), out("pause: later")), \
    "a pause at CLOSEOUT with no pull request open — the skeleton key, wearing the other word"
assert blocked(rel(FULL), out("abandon: no")), "an abandon at CLOSEOUT is allowed"
# And coming back has to ask again about the world outside this repository.
resumed = dict(rel({k: v for k, v in FULL.items() if k not in ("commit", "pr")}),
               history=out("pause: waiting on review")["history"] + [
                   {"timestamp": "2026-01-01T03:00:00Z", "from": "IDLE", "to": "CLOSEOUT",
                    "action": "resume: changes requested", "tier": "FEATURE", "ticket": "T-1"}])
idle = out("pause: waiting on review")
assert not blocked(idle, resumed), "resuming a ticket paused at CLOSEOUT is refused"
kept = dict(resumed, gates=dict(resumed["gates"], commit=True, pr=True))
assert blocked(idle, kept), \
    "resuming brings `commit` and `pr` back true — the closeout is then satisfied by evidence from before the wait"

# And the same pause, replayed by POST mode, which is where this rule is most
# dangerous. Post replays the whole run against a synthetic IDLE prior whose
# gates are empty, so a `paid` check that reads that prior finds nothing paid and
# refuses — on every tool call, forever, over a pause that was legal when it was
# made. Scoping is what makes the rule survive its own replay, and it can only be
# seen by replaying: driven through the real script, on disk.
import subprocess, tempfile
paused_disk = out("pause: waiting on review")
work = tempfile.mkdtemp(dir=os.environ["WORK"])
state = os.path.join(work, ".ddw-state.json")
json.dump(paused_disk, open(state, "w", encoding="utf-8"))
# With the journal the run really has by then: post mode fired on every edge
# that landed, so the six steps before the pause are recorded. A fixture with an
# empty journal is not a legal pause being replayed — it is a whole run that
# reached CLOSEOUT without a single hook seeing it, which post mode is supposed
# to owe evidence for.
with open(os.path.join(work, ".ddw-journal.jsonl"), "w", encoding="utf-8") as fh:
    for entry in paused_disk["history"][:-1]:
        fh.write(json.dumps(entry) + "\n")
r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate-transition.py"),
                    "--mode", "post", "--state", state,
                    "--graph", os.path.join(src, "ddw/rules/transition-graph.json")],
                   capture_output=True, text=True)
assert r.returncode == 0, \
    "post mode refuses a legal pause at CLOSEOUT, which bricks the repo: " + (r.stdout + r.stderr)[:220]
PYPAUSE

# ── The pr gate asks the forge, and had no check of any kind ─────────────────
#
# It is the only evidence in the pipeline the model cannot produce by writing a
# file, and it shipped untested. Worse, its first version read ANY `gh` failure
# as "the branch has no pull request": offline, rate-limited, a fork with no
# default remote — each one refused a closeout while asserting a fact it never
# established. Driven against a stub `gh` on PATH, which is the only way to
# exercise a guard that talks to a network service.
PRT="$WORK/prgate"; mkdir -p "$PRT/bin"
cat > "$PRT/bin/gh" <<'GHEOF'
#!/usr/bin/env bash
[ -n "${GH_STUB_ERR:-}" ] && echo "$GH_STUB_ERR" >&2
echo "${GH_STUB_OUT:-[]}"
exit "${GH_STUB_RC:-0}"
GHEOF
chmod +x "$PRT/bin/gh"
PRR="$PRT/repo"; mkdir -p "$PRR"; git -C "$PRR" init -q .
git -C "$PRR" -c user.email=ddw@test -c user.name=ddw -c commit.gpgsign=false \
  commit -q --allow-empty -m "base"
python3 - "$SELF" "$PRR" "$PRT/bin" <<'PYPR' && ok "the pr gate refuses a branch with no PR and one whose PR was closed, and never mistakes an error for an answer" || bad "the pr gate reads a network failure as a verdict, or takes a closed PR as an open one"
import importlib.util, os, subprocess, sys
src, repo, binpath = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def ask(out="[]", rc="0", err=""):
    env = dict(os.environ, PATH=binpath + os.pathsep + os.environ["PATH"],
               GH_STUB_OUT=out, GH_STUB_RC=rc, GH_STUB_ERR=err)
    old = os.environ.copy()
    os.environ.clear(); os.environ.update(env)
    try:
        return m._pr_evidence_missing(repo, {"ticket": "T-1"})
    finally:
        os.environ.clear(); os.environ.update(old)


# No remote at all: nothing to open a pull request against, nothing owed.
assert ask() is None, "a repo with no remote is asked for a pull request it cannot have"
subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                "https://github.com/example/example.git"], check=True)
assert ask("[]") is not None, "a branch with no pull request opens the gate"
assert ask('[{"number":7,"state":"CLOSED"}]') is not None, \
    "a pull request closed without merging counts as one that was opened"
assert ask('[{"number":7,"state":"OPEN"}]') is None, "an open pull request does not satisfy the gate"
assert ask('[{"number":7,"state":"MERGED"}]') is None, "a merged pull request does not satisfy it"
for rc, err in (("1", "error connecting to api.github.com"),
                ("1", "no default remote repository"),
                ("1", "API rate limit exceeded"),
                ("4", "gh auth login")):
    assert ask("", rc, err) is None, (
        f"gh failing with {err!r} is read as 'the forge has none' — a refusal asserting a fact "
        "the guard never established")
PYPR

# Through the GATE TABLE, not through the function. The checks above call
# `_pr_evidence_missing` directly, so removing the gate from the table that
# consults it was invisible to every one of them — a check that tests the part
# instead of the path, which is the failure this file is about. Evidence is owed
# when the claim is MADE, so the write under test is the one that turns `pr` on
# while still in CLOSEOUT, not the closeout that follows it.
PRS="$PRT/state"; mkdir -p "$PRS"; git -C "$PRS" init -q .
git -C "$PRS" -c user.email=ddw@test -c user.name=ddw -c commit.gpgsign=false \
  commit -q --allow-empty -m base
git -C "$PRS" remote add origin https://github.com/example/example.git
PRHIST='[{"timestamp":"2026-07-29T20:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-07-29T20:01:00Z","from":"CLASSIFY","to":"DEFINE","action":"b","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:02:00Z","from":"DEFINE","to":"PLAN","action":"c","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:03:00Z","from":"PLAN","to":"CODE","action":"d","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:04:00Z","from":"CODE","to":"VERIFY","action":"e","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:05:00Z","from":"VERIFY","to":"CLOSEOUT","action":"f","tier":"FEATURE","ticket":"FEAT-001"}]'
python3 - "$PRS" "$PRHIST" <<'PYPRST'
import json, os, sys
repo, hist = sys.argv[1], json.loads(sys.argv[2])
base = {"tier": "FEATURE", "phase": "CLOSEOUT", "ticket": "FEAT-001", "title": None,
        "tracker": None, "autonomy": None, "block": None, "discovery": None, "history": hist,
        "gates": {"define": True, "spec": True, "threat": True, "tests": True,
                  "sast": True, "verify": True, "commit": True}}
json.dump(base, open(os.path.join(repo, ".ddw-state.json"), "w"))
claim = dict(base, gates=dict(base["gates"], pr=True))
json.dump({"tool_name": "Write",
           "tool_input": {"file_path": os.path.join(repo, ".ddw-state.json"),
                          "content": json.dumps(claim)}},
          open(os.path.join(repo, "ev.json"), "w"))
PYPRST
( export PATH="$PRT/bin:$PATH" GH_STUB_OUT="[]" GH_STUB_RC=0
  python3 "$SELF/ddw/scripts/validate-transition.py" --mode pre --state "$PRS/.ddw-state.json" \
    --graph "$SELF/ddw/rules/transition-graph.json" --repo "$PRS" < "$PRS/ev.json" >/dev/null 2>&1 )
[ "$?" = "2" ] \
  && ok "and claiming the pr gate is refused through the gate table, not only by the function" \
  || bad "the pr gate is in the code and the table that consults it does not name it"

# ── The notice about pull requests waiting on a reviewer ─────────────────────
#
# It prints on every session start, to every user, and it is the one place DDW
# speaks about something it cannot see from disk. Every failure of `gh` has to
# arrive as a sentence saying which failure it was: an empty answer and an
# unanswerable question are different things, and printing nothing for both is
# how a tool teaches people it has nothing to say.
python3 - "$SELF" "$PRR" "$PRT/bin" <<'PYAWAIT' && ok "the pending-PR notice reports every way gh can fail, survives a shape it did not expect, and never truncates in silence" || bad "the pending-PR notice crashes the boot, lies about why it could not look, or drops PRs without saying so"
import importlib.util, os, subprocess, sys
src, repo, binpath = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("sb", os.path.join(src, "ddw/scripts/session-boot.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def ask(out="[]", rc="0", err="", path=None):
    # `path` REPLACES the search path rather than prefixing it — the point of the
    # last case is a machine with no gh at all, and prefixing leaves the real one
    # findable, so the check passed by talking to the actual forge.
    env = dict(os.environ,
               PATH=(binpath + os.pathsep + os.environ["PATH"]) if path is None else path,
               GH_STUB_OUT=out, GH_STUB_RC=rc, GH_STUB_ERR=err)
    old = os.environ.copy()
    os.environ.clear(); os.environ.update(env)
    try:
        return m.awaiting_review(repo, timeout=5)
    finally:
        os.environ.clear(); os.environ.update(old)


CANNOT = "could not check your open pull requests"
# The repo has a remote by now (the pr-gate checks added one), so it asks.
assert ask("[]") == [], "an empty answer should be silence, not a line"
one = ask('[{"number":4,"headRefName":"feat/x","reviewDecision":"CHANGES_REQUESTED"}]')
assert any("#4" in l for l in one), "an open pull request was not reported"
assert any("changes requested" in l for l in one), "a review asking for changes was not called out"
# Every failure mode says which one it was.
for rc, err in (("1", "gh auth login"), ("1", "error connecting to api.github.com"),
                ("4", "API rate limit exceeded")):
    said = ask("", rc, err)
    assert said and CANNOT in said[0] and err.split()[0] in said[0], \
        f"gh failing with {err!r} was reported as {said!r}"
# A timeout is its own sentence. Every other failure used to be reported as one,
# which asserts a fact about the network that nobody established.
slow = os.path.join(repo, "slowbin"); os.makedirs(slow, exist_ok=True)
open(os.path.join(slow, "gh"), "w").write("#!/bin/sh\nsleep 5\n")
os.chmod(os.path.join(slow, "gh"), 0o755)
old = os.environ.copy()
os.environ["PATH"] = slow + os.pathsep + os.environ["PATH"]
try:
    said = m.awaiting_review(repo, timeout=1)
finally:
    os.environ.clear(); os.environ.update(old)
assert said and "did not answer in 1s" in said[0], f"a timeout reported: {said!r}"
# A shape nobody expected must not take the boot down with it: the phase line is
# the one thing that has to survive, and `pr.get` on a string raises.
for weird in ('{"not": "a list"}', '["just a string"]', 'null'):
    said = ask(weird)
    assert isinstance(said, list), f"gh returning {weird} crashed the notice"
    assert not any("#None" in l for l in said), f"gh returning {weird} was rendered as a PR"
# And it never truncates in silence: the ones it drops are the oldest, which are
# the forgotten reviews this notice exists to surface.
many = "[" + ",".join('{"number":%d,"headRefName":"b%d"}' % (i, i) for i in range(1, 13)) + "]"
said = ask(many)
assert any("12 open pull request" in l for l in said), "the count is not the count of what gh returned"
assert any("and 4 more" in l for l in said), "four pull requests were dropped without a word"
# `gh` missing at all is its own sentence, not a timeout. A path with git on it
# and nothing else: strip git too and the honest answer is about git, not gh.
import shutil
onlygit = os.path.join(repo, "onlygit"); os.makedirs(onlygit, exist_ok=True)
link = os.path.join(onlygit, "git")
if not os.path.exists(link):
    os.symlink(shutil.which("git"), link)
said = ask(path=onlygit)
assert said and "not installed" in said[0], f"a missing gh reported: {said!r}"
# And git failing where a repo plainly is one is its own sentence too, never
# silence — silence there is indistinguishable from "you have no open PRs".
said = ask(path=os.path.join(repo, "no-such-bin"))
assert said and "git could not read" in said[0], f"a broken git reported: {said!r}"
PYAWAIT

# Through the BOOT, not through the function — the checks above call
# `awaiting_review` directly, so deleting the line that calls it was invisible to
# every one of them. And the boot is where the cost lives: a network round trip
# on every session start, in every repo DDW is installed in.
python3 - "$SELF" "$PRT" <<'PYBOOT' && ok "the boot prints what is waiting for review, and asks the forge only when it is going to say something" || bad "the notice never reaches the boot, or the boot calls the forge on quiet runs and in repos that have never run DDW"
import json, os, subprocess, sys
src, work = sys.argv[1], sys.argv[2]
binp = os.path.join(work, "boot-bin"); os.makedirs(binp, exist_ok=True)
calls = os.path.join(work, "gh-calls")
# A stub that RECORDS being run: "did it ask?" is the question, and it cannot be
# answered by looking at the output of a call that may not have happened.
open(os.path.join(binp, "gh"), "w").write(
    '#!/bin/sh\necho call >> "$GH_CALLS"\n[ -n "$GH_SLEEP" ] && sleep "$GH_SLEEP"\n'
    'printf "%s" "${GH_STUB_OUT:-[]}"\nexit 0\n')
os.chmod(os.path.join(binp, "gh"), 0o755)
repo = os.path.join(work, "bootrepo")
os.makedirs(repo, exist_ok=True)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["git", "-C", repo, "remote", "add", "origin",
                "https://github.com/example/example.git"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")


def run(out="[]", quiet=False, sleep="", state=True):
    open(os.path.join(work, "gh-calls"), "w").close()
    live = os.path.join(repo, ".ddw-state.json")
    if state and not os.path.exists(live):
        json.dump({"tier": None, "phase": "IDLE", "ticket": None, "gates": {}, "history": []},
                  open(live, "w"))
    if not state and os.path.exists(live):
        os.remove(live)
    env = dict(os.environ, PATH=binp + os.pathsep + os.environ["PATH"],
               GH_CALLS=calls, GH_STUB_OUT=out, GH_SLEEP=sleep)
    cmd = [sys.executable, boot, "--repo", repo, "--session-id", "s"]
    if quiet:
        cmd.append("--quiet")
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    asked = len(open(calls).read().split())
    return r.stdout, asked


out, asked = run('[{"number":9,"headRefName":"feat/z","reviewDecision":"CHANGES_REQUESTED"}]')
assert asked == 1, "the boot never asked the forge"
assert "#9" in out and "changes requested" in out, \
    "the boot asked and said nothing about the answer:\n" + out[-400:]
# A quiet run prints nothing, so paying for a round trip it will discard is pure
# cost — and it is a cost the user cannot see to complain about.
_, asked = run(quiet=True)
assert asked == 0, "a --quiet boot still called the forge"
# And under a plugin — no `.ddw/` in the repo, no state file — DDW has never run
# here and there is nothing of yours to be waiting on. `started` is what says so.
plain = os.path.join(work, "plainrepo"); os.makedirs(plain, exist_ok=True)
subprocess.run(["git", "-C", plain, "init", "-q"], check=True)
subprocess.run(["git", "-C", plain, "remote", "add", "origin",
                "https://github.com/example/example.git"], check=True)
open(calls, "w").close()
subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/session-boot.py"),
                "--repo", plain, "--session-id", "s"], capture_output=True, text=True,
               env=dict(os.environ, PATH=binp + os.pathsep + os.environ["PATH"],
                        GH_CALLS=calls, GH_STUB_OUT="[]", GH_SLEEP=""))
assert len(open(calls).read().split()) == 0, \
    "the boot called the forge in a repo where DDW has never run"
PYBOOT

# The corrective loop's ceiling, which was a number in four documents and a
# comparison in none of them. `PRD loops` and `Spec loops` were incremented by
# the skills and measured against nothing, so one of the three stops that are
# supposed to hold under `minimal` could never be reached.
python3 - "$VP" <<'PYLOOP'
import os, re, sys
p = os.path.join(sys.argv[1], "docs/ddw/prd/prd-FEAT-001.md")
s = open(p, encoding="utf-8").read()
s = re.sub(r"^\|\s*PRD loops\s*\|.*$", "| PRD loops | 4 |", s, count=1, flags=re.M)
if "PRD loops" not in s:
    s = s.replace("\n## ", "\n| PRD loops | 4 |\n\n## ", 1)
open(os.path.join(sys.argv[1], "docs/ddw/prd/prd-looped.md"), "w", encoding="utf-8").write(s)
PYLOOP
VLOUT="$(python3 "$SELF/ddw/scripts/validate_prd.py" "$VP/docs/ddw/prd/prd-looped.md" --tier FEATURE 2>/dev/null || true)"
case "$VLOUT" in
  *"❌ F-PRD-LOOP"*) ok "a PRD past its corrective-loop ceiling is refused — the counter is compared, not just kept" ;;
  *) bad "the loop ceiling is a number nothing measures against, and minimal has one fewer stop" ;;
esac

# The second counter is what the ceiling actually reads, and for a while NO
# template emitted it — so every document fell back to the running total and the
# distinction Pablo asked for existed only in the rules file. A field the method
# never writes is a field the validator can only guess at.
python3 - "$SELF" <<'PYSINCE' && ok "the templates emit both counters, and a since-count above the running total is refused" || bad "the ceiling reads a field no template writes, or the two counters can disagree in the direction that loops forever"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
ROW = r"^\|\s*Loops since (?:the )?last human decision\s*\|"
# EVERY table that carries the running total carries the second counter too. A
# skill with two copies of its template (one in the protocol, one in the example)
# had the row in one of them, and "it is in the file somewhere" is not what the
# validator reads — it reads the header of the document that gets written.
for skill, total in (("ddw-create-prd", r"^\|\s*PRD loops\s*\|"),
                     ("ddw-create-spec", r"^\|\s*Spec loops\s*\|")):
    t = open(os.path.join(src, "skills", skill, "SKILL.md"), encoding="utf-8").read()
    totals = len(re.findall(total, t, re.M | re.I))
    sinces = len(re.findall(ROW, t, re.M | re.I))
    assert totals and sinces == totals, \
        f"{skill} emits the running total {totals} time(s) and the counter the ceiling reads {sinces}"
# Both counters kept, and the impossible pair refused: `since` counts a subset of
# the rounds the total counts, so it cannot be the larger of the two — and the
# one the ceiling reads is the one that would then let the document loop forever.
HEADER = ("# PRD\n\n| Field | Value |\n|-------|-------|\n| Ticket | T-1 |\n"
          "| PRD loops | %d |\n| Loops since last human decision | %d |\n")


def loop_row(total, since):
    path = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "prd-T-1.md")
    open(path, "w", encoding="utf-8").write(HEADER % (total, since))
    out = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate_prd.py"), path,
                          "--tier", "FEATURE"], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if "F-PRD-LOOP" in l]


skew = loop_row(1, 2)
assert any("❌" in l for l in skew), \
    "a since-count above the running total was accepted: %r" % (skew,)
# …and the everyday pair, where the total is the larger one, still passes: this
# has to catch the impossible combination, not one loop into the budget.
fine = loop_row(2, 1)
assert fine and not any("❌" in l for l in fine), \
    "a document one loop into its budget was refused: %r" % (fine,)
PYSINCE

# A phase that was renamed has to be renamed in the PROSE too, and the search for
# it is not the word — it is the stem. `RELEASE` → `CLOSEOUT` left `Releasing` in
# the orchestrator's status line, the string the agent prints on every single
# response while in that phase, because `\brelease\b` does not match `Releasing`.
# It also left it in an agent file the rename never opened. Both passed every
# check, the linter and the whole mutation run.
python3 - "$SELF" <<'PYRENAMED' && ok "no phase carries its old name in the method, the skills or the agents — stem, not word" || bad "a renamed phase is still called by its old name where a user reads it — see above"
import os, re, sys
src = sys.argv[1]
vt = open(os.path.join(src, "ddw/scripts/validate-transition.py"), encoding="utf-8").read()
pairs = re.findall(r'"(\w+)":\s*"(\w+)"', re.search(r"RENAMED_PHASES = \{([^}]*)\}", vt).group(1))
assert pairs, "RENAMED_PHASES is empty — this check has nothing to look for"

# The other meaning of the same stem, each one deliberate and each one named.
ALLOWED = (
    "unreleased",                 # Keep a Changelog's own heading
    "deploy / release",           # the gitmoji table: a deploy is not this phase
    "for one release",            # prose about a version of DDW
    "`release`)",                 # a git BRANCH called release, in a list of them
)
bad = []
for root, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "docs", "scripts", ".github")]
    rel_root = os.path.relpath(root, src)
    if not (rel_root.startswith("ddw") or rel_root.startswith("agents")
            or rel_root.startswith("skills") or rel_root.startswith("adapters")):
        continue
    for name in files:
        if not name.endswith((".md", ".py", ".sh", ".js", ".json")):
            continue
        path = os.path.join(root, name)
        for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            low = line.lower()
            for old, new in pairs:
                stem = old.lower()[:-1] if old.lower().endswith("e") else old.lower()
                if stem not in low:
                    continue
                if new.lower() in low:          # names both: this is the migration notice
                    continue
                if any(a in low for a in ALLOWED):
                    continue
                bad.append(f"{os.path.relpath(path, src)}:{n}: {line.strip()[:88]}")
if bad:
    print("these still call a renamed phase by its old name:")
    for b in bad:
        print("   " + b)
assert not bad, f"{len(bad)} line(s) still name a renamed phase"
PYRENAMED

# A state written by an older DDW is not a forgery. When a phase is renamed, the
# state that still names the old one fails the graph lookup — and the refusal for
# that says "you probably wrote it with Bash/jq/sed", which is both wrong and
# accusatory: it sends someone to fix a state they never touched, with the one
# explanation that cannot be true.
OLDP="$WORK/old-phase"; mkdir -p "$OLDP"; git -C "$OLDP" init -q .
printf '%s' '{"tier":"FEATURE","phase":"RELEASE","ticket":"T-1","title":null,"tracker":null,"gates":{"verify":true},"block":null,"discovery":null,"history":[{"timestamp":"2026-01-01T00:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-01-01T00:05:00Z","from":"VERIFY","to":"RELEASE","action":"f","tier":"FEATURE","ticket":"T-1"}]}' > "$OLDP/.ddw-state.json"
OLDOUT="$(python3 "$SELF/ddw/scripts/validate-transition.py" --mode post --state "$OLDP/.ddw-state.json" \
         --graph "$SELF/ddw/rules/transition-graph.json" 2>&1 || true)"
case "$OLDOUT" in
  *"written by an older DDW"*RELEASE*CLOSEOUT*)
    ok "a state naming a renamed phase is told so, not accused of being forged" ;;
  *) bad "an upgraded user is told they wrote their own state with sed — the one explanation that cannot be true" ;;
esac

# ── Going back, and what going back costs ────────────────────────────────────
#
# The corrective loop used to launder a rewritten artifact: step back to DEFINE,
# rewrite the PRD, step forward claiming `define` — and nothing asked for a
# receipt, because evidence is owed only when a gate is claimed for the FIRST
# time and this one had never stopped being true. The helper refused it and the
# hook did not, which is the same shape as the defect that moved the receipt
# check into the hook in the first place.
python3 - "$SELF" <<'PYBACK' && ok "stepping back gives up what that phase granted, and the hook refuses a step that keeps it" || bad "a backward transition can keep its gates — the corrective loop launders a rewritten artifact again"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json")))
EDGES = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN"), ("PLAN", "CODE"),
         ("CODE", "VERIFY"), ("VERIFY", "CLOSEOUT")]


def hist(n):
    return [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
             "tier": "FEATURE", "ticket": "T-1"} for i, (f, t) in enumerate(EDGES[:n])]


def st(phase, gates, n, block=None):
    return {"tier": "FEATURE", "phase": phase, "ticket": "T-1", "title": None, "tracker": None,
            "autonomy": None, "gates": dict(gates), "block": block, "discovery": None,
            "history": hist(n)}


def step(old, dst, gates, block=None):
    new = st(dst, gates, len(old["history"]), block)
    new["history"] = old["history"] + [{"timestamp": "2026-01-01T01:00:00Z",
                                        "from": old["phase"], "to": dst, "action": "review: back",
                                        "tier": "FEATURE", "ticket": "T-1"}]
    return new


def blocked(old, new):
    try:
        m.validate(old, new, g, max_appended=1)
        return False
    except m.Block:
        return True


SIX = {"define": True, "spec": True, "threat": True, "tests": True, "sast": True, "verify": True}
rel = st("CLOSEOUT", SIX, 6, block="Block 3")
# Every backward edge must refuse to keep what it gives up …
assert blocked(rel, step(rel, "VERIFY", SIX)), "CLOSEOUT->VERIFY kept `verify`"
ver = st("VERIFY", {k: v for k, v in SIX.items() if k != "verify"}, 6)
assert blocked(ver, step(ver, "CODE", ver["gates"])), "VERIFY->CODE kept tests/sast"
cod = st("CODE", {"define": True, "spec": True, "threat": True}, 6)
assert blocked(cod, step(cod, "PLAN", cod["gates"])), "CODE->PLAN kept spec/threat"
pln = st("PLAN", {"define": True}, 6)
assert blocked(pln, step(pln, "DEFINE", pln["gates"])), "PLAN->DEFINE kept `define`"
# … and allow the same step once they are given up.
assert not blocked(pln, step(pln, "DEFINE", {})), "a correct step back is refused"


# QUICK-FIX has its own way back, and it had no check at all: that tier skips
# PLAN and VERIFY, so a review sends it from CLOSEOUT straight to CODE, giving up
# `tests`, `sast`, `commit` and `pr` — the two that say it shipped included.
def qf(phase, gates, entries, action="review: back"):
    hist = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
             "tier": "QUICK-FIX", "ticket": "Q-1"} for i, (f, t) in enumerate(entries)]
    return {"tier": "QUICK-FIX", "phase": phase, "ticket": "Q-1", "title": None, "tracker": None,
            "autonomy": None, "gates": dict(gates), "block": None, "discovery": None,
            "history": hist}


QF_PATH = [("IDLE", "CLASSIFY"), ("CLASSIFY", "CODE"), ("CODE", "CLOSEOUT")]
QF_HELD = {"tests": True, "sast": True, "commit": True, "pr": True}
qrel = qf("CLOSEOUT", QF_HELD, QF_PATH)


def qstep(gates):
    new = qf("CODE", gates, QF_PATH)
    new["history"] = qrel["history"] + [{"timestamp": "2026-01-01T01:00:00Z", "from": "CLOSEOUT",
                                         "to": "CODE", "action": "review: back",
                                         "tier": "QUICK-FIX", "ticket": "Q-1"}]
    return new


assert blocked(qrel, qstep(QF_HELD)), "QUICK-FIX's CLOSEOUT->CODE kept everything it grants"
assert blocked(qrel, qstep({"commit": True})), "it kept the commit that says the work shipped"
assert not blocked(qrel, qstep({})), "the correct QUICK-FIX step back is refused"
PYBACK

# ── The ticket a gate is earned for ───────────────────────────────────────────
#
# Every receipt gate resolves its document through the ticket, and the absent-
# document case reads as "no claim to check". So `ticket: null` opened all six at
# once, one `jq` away, and nothing anywhere said otherwise.
python3 - "$SELF" <<'PYTICK' && ok "a receipt gate cannot be claimed with a null ticket, and naming the ticket is the way back" || bad "clearing the ticket still opens the six receipt gates — the emptiest state claims the most"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json")))
H = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
      "tier": "FEATURE", "ticket": "T-1"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE")])]


def st(ticket, gates):
    return {"tier": "FEATURE", "phase": "DEFINE", "ticket": ticket, "title": None,
            "tracker": None, "autonomy": None, "gates": dict(gates), "block": None,
            "discovery": None, "history": list(H)}


def blocked(old, new):
    try:
        m.validate(old, new, g, max_appended=1)
        return False
    except m.Block:
        return True


named = st("T-1", {})
for gate in ("define", "spec", "threat", "tests", "sast", "verify"):
    assert blocked(named, st(None, {gate: True})), "%s was claimed against a null ticket" % gate
# Not a brick: a repo already in that state gets out by naming the ticket, which
# is what the refusal tells it to do. If this ever fails, the message lies.
stuck = st(None, {"define": True})
assert not blocked(stuck, st("T-1", {"define": True})), "the way out of the refusal is refused too"
# And the gates that ask git and the forge are not receipt gates: they resolve
# nothing through the ticket, so they are not this rule's business.
assert not blocked(named, st(None, {})), "an empty state with no ticket was refused"
PYTICK

# ── A gate turned on without declaring a transition ───────────────────────────
#
# Post mode owed evidence only for the gates the LANDED EDGES declared, so a
# write that appends no history entry — `jq '.gates.tests = true'` — owed
# nothing. The pre path does not catch it either: by the time it runs, the forged
# `true` is already the prior, so nothing is newly claimed. Driven through the
# real hook, on disk, which is where that write lands.
python3 - "$SELF" <<'PYSNAP' && ok "a gate flipped on disk with no transition is caught against the last blessed snapshot" || bad "jq can turn on any gate without writing a transition — post mode has nothing to compare it to"
import json, os, subprocess, sys, tempfile, hashlib
src = sys.argv[1]
vt = os.path.join(src, "ddw/scripts/validate-transition.py")
graph = os.path.join(src, "ddw/rules/transition-graph.json")
repo = tempfile.mkdtemp(dir=os.environ["WORK"])
os.makedirs(os.path.join(repo, "docs/ddw/prd"))
os.makedirs(os.path.join(repo, ".ddw-sessions"))
state = os.path.join(repo, ".ddw-state.json")
prd = os.path.join(repo, "docs/ddw/prd/prd-T-1.md")
open(prd, "w", encoding="utf-8").write("# PRD\n")
H = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
      "tier": "FEATURE", "ticket": "T-1"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE")])]


def write(**over):
    d = {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "title": None, "tracker": None,
         "autonomy": "minimal", "gates": {}, "block": None, "discovery": None, "history": H}
    d.update(over)
    json.dump(d, open(state, "w", encoding="utf-8"))


def post():
    return subprocess.run([sys.executable, vt, "--mode", "post", "--state", state,
                           "--graph", graph], capture_output=True, text=True).returncode


# A real run that chose a mode. It replays as ONE batch against a synthetic IDLE
# prior, so the autonomy check saw `appended[0]` coming from IDLE rather than the
# CLASSIFY edge that set it — and refused every ticket that used the feature,
# on every tool call after DEFINE. Nothing drove it end to end.
write()
assert post() == 0, "post mode refuses a legitimate run that chose an autonomy mode"
write(gates={"define": True})
assert post() == 2, "a gate turned on with no transition and no receipt was accepted"
digest = hashlib.sha256(open(prd, encoding="utf-8").read().encode("utf-8")).hexdigest()[:12]
open(os.path.join(repo, ".ddw-sessions", "prd-validated-%s" % digest), "w").write("prd-T-1.md")
with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"record": "receipt", "name": "prd-validated-%s" % digest,
                         "file": "prd-T-1.md"}, sort_keys=True) + "\n")
assert post() == 0, "the same claim with its receipt on disk was refused"
# The snapshot shares the journal so that removing it costs the transitions too —
# and a journal that comes back empty makes post mode stricter, never weaker.
lines = [json.loads(l) for l in open(os.path.join(repo, ".ddw-journal.jsonl"), encoding="utf-8")
         if l.strip()]
assert [e for e in lines if e.get("record") == "gates"], "no gate snapshot was ever recorded"
assert len([e for e in lines if "from" in e]) == len(H), \
    "snapshot lines are counted as transitions, which slides the index that finds what just landed"
PYSNAP

# ── Pause, work on something else, come back ─────────────────────────────────
#
# `_paused_at` read the entry immediately before the resume, which assumed the
# pause was the last thing that ever happened — the one thing a pause is for NOT
# being. Pause A, run B, come back for A, and the resume was refused as having no
# paused ticket: the feature failed at exactly the workflow it exists for.
python3 - "$SELF" <<'PYRESUME' && ok "a ticket paused before other work resumes, and a pause already picked up cannot be used twice" || bad "pausing only works if you never work on anything else — or one pause resumes forever"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json")))
N = [0]


def e(f, t, action, ticket="T-1", tier="FEATURE"):
    N[0] += 1
    return {"timestamp": "2026-01-01T00:%02d:00Z" % N[0], "from": f, "to": t,
            "action": action, "tier": tier, "ticket": ticket}


RUN = [e("IDLE", "CLASSIFY", "classify"), e("CLASSIFY", "DEFINE", "d"),
       e("DEFINE", "PLAN", "p"), e("PLAN", "CODE", "c"),
       e("CODE", "IDLE", "pause: waiting on product")]
OTHER = [e("IDLE", "CLASSIFY", "classify", "T-2", "QUICK-FIX"),
         e("CLASSIFY", "IDLE", "abandon: not worth it", "T-2", "QUICK-FIX")]


def idle(history, ticket=None):
    return {"tier": None, "phase": "IDLE", "ticket": ticket, "title": None, "tracker": None,
            "autonomy": None, "gates": {}, "block": None, "discovery": None,
            "history": list(history)}


def resumed(history, dst="CODE"):
    entry = e("IDLE", dst, "resume: back to it")
    return dict(idle(history, "T-1"), tier="FEATURE", phase=dst,
                gates={"define": True, "spec": True, "threat": True},
                history=list(history) + [entry]), entry


def blocked(old, new):
    try:
        m.validate(old, new, g, max_appended=1)
        return False
    except m.Block:
        return True


after_other = RUN + OTHER
new, _ = resumed(after_other)
assert not blocked(idle(after_other, "T-1"), new), \
    "a ticket paused before an unrelated ticket ran could not be resumed"
# The pause is consumed: resuming the same one twice would re-enter a phase whose
# ticket is long since closed, carrying whatever gates the write cares to declare.
used = new["history"] + [e("CODE", "IDLE", "closeout", "T-1")]
again, _ = resumed(used)
assert blocked(idle(used, "T-1"), again), "one pause resumed twice"
# Still anchored to the phase it paused at.
elsewhere, _ = resumed(after_other, "VERIFY")
assert blocked(idle(after_other, "T-1"), elsewhere), "a resume landed where the ticket never paused"
# And another ticket's pause is not this ticket's way back in. The destination
# has to be a phase only a resume can reach: IDLE->CLASSIFY is an ordinary edge,
# so a "resume" landing there proves nothing about resuming.
theirs = [e("IDLE", "CLASSIFY", "classify", "T-9"), e("CLASSIFY", "DEFINE", "d", "T-9"),
          e("DEFINE", "PLAN", "p", "T-9"), e("PLAN", "CODE", "c", "T-9"),
          e("CODE", "IDLE", "pause: theirs", "T-9")]
mine, _ = resumed(theirs, "CODE")
assert blocked(idle(theirs, "T-1"), mine), "one ticket resumed on another ticket's pause"
# The word has to be the marker, not a prefix of it. Bare `startswith` once let
# "abandonware cleanup" read as an abandon; the same shape here would make
# "pause-the-build until Friday" a pause you can resume out of.
NOT_A_PAUSE = RUN[:4] + [e("CODE", "IDLE", "pause-the-build until Friday")]
back, _ = resumed(NOT_A_PAUSE)
assert blocked(idle(NOT_A_PAUSE, "T-1"), back), \
    "an action that merely starts with the word pause was read as a pause"
PYRESUME

# ── The helper can name the ticket it is earning gates for ───────────────────
#
# With `--write` there is no later Write to fill it in, so the state landed with
# `ticket: null` while claiming gates — the shape the hook now refuses. A rule
# the sanctioned path cannot satisfy is a rule that gets routed around.
python3 - "$SELF" <<'PYTKFLAG' && ok "transition.py --ticket names the ticket in the header and stamps it on the entry" || bad "the helper cannot name a ticket, so its own output is a state the hook refuses"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
tr = os.path.join(src, "ddw/scripts/transition.py")
graph = os.path.join(src, "ddw/rules/transition-graph.json")
repo = tempfile.mkdtemp(dir=os.environ["WORK"])
state = os.path.join(repo, ".ddw-state.json")
r = subprocess.run([sys.executable, tr, "--to", "CLASSIFY", "--action", "classify",
                    "--tier", "FEATURE", "--ticket", "FEAT-007", "--state", state,
                    "--graph", graph, "--write"], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
d = json.load(open(state, encoding="utf-8"))
assert d["ticket"] == "FEAT-007", "the header does not carry the ticket"
# The entry too: the closeout wipes the header's ticket, so an unstamped entry is
# unattributable forever after — and the boot reads it to find open sub-tickets.
assert d["history"][-1].get("ticket") == "FEAT-007", "the history entry is unattributable"
PYTKFLAG

# ── autonomy: the field that decides whether a human is in the loop ──────────
#
# It shipped with no validation at all: a model could write itself `minimal` in
# any state, `"banana"` was accepted, and the value survived the closeout into
# the next ticket — which is the one field where "the model set it" is the whole
# problem. Driven through validate(), the function the hook calls.
python3 - "$SELF" <<'PYAUTO' && ok "autonomy is refused outside CLASSIFY, refused unknown, and cleared at IDLE" || bad "the field that removes the human from the loop can be set by the model — see above"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json")))
H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "ticket": "T-1", "tier": "FEATURE"}]
NXT = H + [{"timestamp": "2026-01-01T00:02:00Z", "from": "DEFINE", "to": "PLAN", "action": "c",
            "ticket": "T-1", "tier": "FEATURE"}]


def st(phase, auto, hist=None, gates=None, tier="FEATURE", ticket="T-1"):
    return {"tier": tier, "phase": phase, "ticket": ticket, "title": None, "tracker": None,
            "autonomy": auto, "gates": gates or {}, "block": None, "discovery": None,
            "history": hist or H}


def blocked(old, new):
    try:
        m.validate(old, new, g, max_appended=1)
        return False
    except m.Block:
        return True


assert blocked(st("DEFINE", "assisted"), st("PLAN", "minimal", NXT, {"define": True})), \
    "a model can grant itself minimal mid-run"
assert blocked(st("DEFINE", "assisted"), st("PLAN", "banana", NXT, {"define": True})), \
    "an unrecognised autonomy value is accepted"
assert blocked(st("DEFINE", "minimal"),
               st("IDLE", "minimal", NXT, tier=None, ticket=None)), \
    "minimal survives the closeout into the next ticket"
assert not blocked(st("CLASSIFY", None), st("CLASSIFY", "minimal")), \
    "the mode cannot be chosen where it is supposed to be chosen"
assert not blocked(st("DEFINE", "minimal"), st("PLAN", "minimal", NXT, {"define": True})), \
    "an ordinary transition under minimal is refused"

# Resuming is the one other moment the mode is chosen. Without it the setting is
# simply lost across a pause — reaching IDLE clears it, and the only way back
# would be abandoning the ticket. It is narrow because a resume cannot be
# manufactured: it needs a real, unresumed pause of this ticket, from the exact
# phase being re-entered.
PAUSED = H + [{"timestamp": "2026-01-01T00:03:00Z", "from": "DEFINE", "to": "IDLE",
               "action": "pause: waiting on product", "ticket": "T-1", "tier": "FEATURE",
               "autonomy": "minimal"}]
BACK = PAUSED + [{"timestamp": "2026-01-01T02:00:00Z", "from": "IDLE", "to": "DEFINE",
                  "action": "resume: back to it", "ticket": "T-1", "tier": "FEATURE"}]
idle_after = st(IDLE_PHASE := "IDLE", None, PAUSED, tier=None, ticket=None)
for answer in ("minimal", "assisted"):
    assert not blocked(idle_after, st("DEFINE", answer, BACK)), \
        f"resuming and answering {answer!r} about the mode is refused"
# …and it is still an enum, and still not a door anywhere else.
assert blocked(idle_after, st("DEFINE", "banana", BACK)), "a resume accepts an unrecognised mode"
NOT_RESUME = PAUSED + [{"timestamp": "2026-01-01T02:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "classify: something else", "ticket": "T-2", "tier": "FEATURE"}]
assert blocked(st("PLAN", "assisted", NXT, {"define": True}),
               st("CODE", "minimal", NXT + [{"timestamp": "2026-01-01T03:00:00Z", "from": "PLAN",
                                             "to": "CODE", "action": "resume: nice try",
                                             "ticket": "T-1", "tier": "FEATURE"}],
                  {"define": True, "spec": True, "threat": True})), \
    "the word resume on an ordinary forward edge sets the mode — it is a skeleton key again"

# The hook can prove a pause is being resumed. It cannot prove a question was
# put — so that stop lives in the method, and a stop that lives in prose has to
# be checked as prose or it quietly stops existing.
protocol = open(os.path.join(src, "ddw/orchestrator.md"), encoding="utf-8").read()
start = protocol.find("When the user wants to resume a paused ticket")
assert start > 0, "the pause protocol no longer says how to resume"
resume_protocol = protocol[start:start + 2000].lower()
for phrase in ("ask about the mode", "autonomy"):
    assert phrase in resume_protocol, \
        f"the resume protocol never says to {phrase!r}: the mode comes back with nobody deciding"
PYAUTO

# And the sanctioned helper has to be able to write what the method promises:
# the mode on the header, the stamp on the entry, both cleared at the closeout.
python3 - "$SELF" <<'PYAUTOH' && ok "and the helper sets it, stamps every autonomous edge, and clears it on closeout" || bad "the record that says nobody was watching cannot be written by the sanctioned path"
import importlib.util, json, os, subprocess, sys, tempfile
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("tr", os.path.join(src, "ddw/scripts/transition.py"))
tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)
idle = {"tier": None, "phase": "IDLE", "ticket": None, "title": None, "tracker": None,
        "autonomy": None, "gates": {}, "block": None, "discovery": None, "history": []}
s1 = tr.build_next_state(idle, "CLASSIFY", "classify", [], None, autonomy="minimal")
assert s1["autonomy"] == "minimal", "--autonomy does not reach the state"
assert s1["history"][-1].get("autonomy") == "minimal", "the edge is not stamped"
s2 = tr.build_next_state(s1, "DEFINE", "confirmed", [], "FEATURE")
assert s2["history"][-1].get("autonomy") == "minimal", "only the first edge is stamped"
s3 = tr.build_next_state(s2, "IDLE", "closeout", [], None)
assert s3["autonomy"] is None, "the closeout leaves the mode behind for the next ticket"
PYAUTOH

# `block` — the field the phase rules order updated once per block, for which
# the helper had NO operation: the paths left were a hand Edit the
# reconstruction guard fails closed on, or the shell the method forbids.
# Measured live (2026-08-25): a run took each once. Four checks: the sanctioned
# update works, the edge combination is refused, the journal records it, and
# the record does not repeat for an unchanged value.
BLK="$WORK/block"; mkdir -p "$BLK"; git -C "$BLK" init -q .
python3 - "$BLK" <<'PYBST'
import json, sys
h = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
      "action": "x", "tier": "FEATURE", "ticket": "FEAT-001"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"),
                                 ("DEFINE", "PLAN"), ("PLAN", "CODE")])]
json.dump({"tier": "FEATURE", "phase": "CODE", "ticket": "FEAT-001", "title": "x",
           "tracker": None, "autonomy": None, "gates": {"define": True, "spec": True,
           "threat": True}, "block": None, "discovery": None, "history": h},
          open(sys.argv[1] + "/.ddw-state.json", "w"), indent=2)
PYBST
# The reviews the marker now spends — a different gate than the one under test.
mkdir -p "$BLK/.ddw-work"
printf 'verifier: PASSED\narch: PASSED\n' > "$BLK/.ddw-work/review-block-2.md"
python3 "$SELF/ddw/scripts/transition.py" --block 2/5 --state "$BLK/.ddw-state.json" \
    --graph "$SELF/ddw/rules/transition-graph.json" --write >/dev/null 2>&1 \
  && python3 -c "import json,sys; s=json.load(open(sys.argv[1])); sys.exit(0 if s['block']=='2/5' and len(s['history'])==4 else 1)" "$BLK/.ddw-state.json" \
  && ok "--block updates the marker in-phase through the helper: no entry, no phase change" \
  || bad "the sanctioned path for the block marker does not exist or does not land — hand Edits and shell writes are all that is left"

# Against an edge that would otherwise LAND (CODE->PLAN clears its own gates),
# and asserting the reason, not the exit code: the first version aimed at an
# edge whose gates fail anyway, so gutting the guard changed nothing the check
# could see — the fault survived, and the ledger asked for this sentence.
BLKOUT="$(python3 "$SELF/ddw/scripts/transition.py" --block 2/5 --to PLAN --action "loop" --write \
    --state "$BLK/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" 2>&1 || true)"
case "$BLKOUT" in
  *"does not go with --to"*) ok "and --block on an edge is refused with the reason" ;;
  *) bad "--block rode an edge — the edges manage the field themselves and this hides a state change inside a transition" ;;
esac

python3 - "$SELF" "$BLK" <<'PYBJR'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(sys.argv[1], "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)
state = os.path.join(sys.argv[2], ".ddw-state.json")
vt.record_journal(state)
vt.record_journal(state)   # unchanged: must not repeat
lines = open(os.path.join(sys.argv[2], ".ddw-journal.jsonl")).read().splitlines()
blocks = [ln for ln in lines if '"record": "block"' in ln]
assert len(blocks) == 1, "expected one block record, got %d" % len(blocks)
assert '"block": "2/5"' in blocks[0], blocks[0]
PYBJR
[ $? -eq 0 ] \
  && ok "the journal records the block change once — 'advanced by the helper' and 'never touched' stopped being indistinguishable" \
  || bad "a block change leaves no journal trace, or an unchanged one repeats — the audit cannot see the field"

# The model field is covered or its absence is a decision on file — never a
# hole. Measured live: three recipes carried `model`, one omitted the key, and
# the omitted tool ran every DDW subagent on a model the user never chose. The
# old frontmatter check validated the output against the same recipe, so this
# omission could not go red by construction.
python3 - "$SELF" <<'PYMODEL'
import json, os, re, sys
root = sys.argv[1]
bad = []
for tool in sorted(os.listdir(os.path.join(root, "adapters"))):
    aj = os.path.join(root, "adapters", tool, "adapter.json")
    if not os.path.isfile(aj):
        continue
    spec = json.load(open(aj, encoding="utf-8"))
    agents = spec.get("agents")
    if not isinstance(agents, dict) or not agents.get("dir"):
        continue
    fm = agents.get("frontmatter") or {}
    if "model" in fm:
        if "{model}" not in str(fm.get("model")):
            bad.append("%s: model is a literal, not the {model} template — a copy the source "
                       "cannot correct" % tool)
        continue
    if not (agents.get("_model_note") or "").strip():
        bad.append("%s: agents.frontmatter has no model and no _model_note" % tool)
for f in sorted(os.listdir(os.path.join(root, "agents"))):
    if not f.endswith(".md"):
        continue
    head = open(os.path.join(root, "agents", f), encoding="utf-8").read(400)
    if not re.search(r"^model:\s*\S", head, re.M):
        bad.append("agents/%s: no model field — {model} renders empty everywhere" % f)
assert not bad, "; ".join(bad)
PYMODEL
[ $? -eq 0 ] \
  && ok "every adapter either emits the agents' model from the one source or says on file why it cannot" \
  || bad "an agent recipe lost the model with no note — that tool's subagents run on whatever its defaults pick, silently"

# Copilot's partial commit/merge gate. No UserPromptSubmit equivalent means no
# seal — and for a long time it meant NOTHING: a `git commit -m` in a Copilot
# session was gated by nobody (measured live: the probe committed straight from
# IDLE, exit 0). What its preToolUse can hold, it holds now, and says the rest
# is Claude's guarantee.
CPG="$WORK/cp-gate"; mkdir -p "$CPG/.ddw-work"; git -C "$CPG" init -q .
printf '{"tier": "FEATURE", "phase": "CODE", "ticket": "F-1", "autonomy": null, "gates": {}, "history": []}' > "$CPG/.ddw-state.json"
cpg() {  # $1 = shell command inside a copilot pre envelope
  python3 -c "import json,sys;print(json.dumps({'toolName':'bash','toolArgs':json.dumps({'command':sys.argv[1]})}))" "$1" \
    | python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect copilot \
        --state "$CPG/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
        --repo "$CPG" >/dev/null 2>&1
}
cpg 'git add x && git commit -m "test: probe"' \
  && bad "a Copilot commit with -m sailed through — the message never had to come from the shown file" \
  || ok "Copilot's preToolUse holds a commit to the shown file (-F), the part of the gate that needs no seal"

printf 'x feat: y\n\nRefs: F-1\nAI-assisted: yes\n' > "$CPG/.ddw-work/commit-message.txt"
cpg 'git commit -F .ddw-work/commit-message.txt' \
  && ok "and allows the sanctioned form with a clean proposal — partial is not closed" \
  || bad "the partial gate refuses the exact flow the skill teaches, which pushes models around it"

printf '{"tier": "FEATURE", "phase": "CODE", "ticket": "F-1", "autonomy": "minimal", "gates": {}, "history": []}' > "$CPG/.ddw-state.json"
cpg 'gh pr merge 2 --squash' \
  && bad "a merge ran in Copilot with no proposal on disk — the one irreversible act, ungated again" \
  || ok "and a merge without its proposal on disk is refused there too, minimal included"

# The go-back gate. "Under `assisted`, the question comes BEFORE the edge" was
# prose, the fix that introduced it touched only prose, and a live run took the
# edge first and asked after — the one-arrow counter only ever refuses a SECOND
# arrow, so the first arrow of any turn landed free. Now the reason rides a
# file: `correction:` announces and goes, `ask:` waits for the user's sealed
# turn, and both leave a record.
GBK="$WORK/goback"; mkdir -p "$GBK/.ddw-sessions" "$GBK/.ddw-work"; git -C "$GBK" init -q .
echo 3 > "$GBK/.ddw-sessions/turn"
gbk_state() {  # reset to CODE with spec+threat held
python3 - "$GBK" <<'PYGBS'
import json, sys
h = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
      "action": "x", "tier": "FEATURE", "ticket": "FEAT-001"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"),
                                 ("DEFINE", "PLAN"), ("PLAN", "CODE")])]
json.dump({"tier": "FEATURE", "phase": "CODE", "ticket": "FEAT-001", "title": "x",
           "tracker": None, "autonomy": "assisted", "gates": {"define": True,
           "spec": True, "threat": True}, "block": None, "discovery": None,
           "history": h}, open(sys.argv[1] + "/.ddw-state.json", "w"), indent=2)
PYGBS
}
gbk_edge() {
  python3 "$SELF/ddw/scripts/transition.py" --to PLAN --action "loop" --write \
    --state "$GBK/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" 2>&1
}
gbk_state
GBOUT="$(gbk_edge || true)"
case "$GBOUT" in
  *"goes back a phase under"*)
    ok "a backward edge under assisted with no reason on disk is refused, first arrow of the turn included" ;;
  *) bad "the go-back edge landed with nothing on disk showing the user was told — execute-then-ask is back" ;;
esac

printf 'correction: the block names the wrong file — CODE -> PLAN\n' > "$GBK/.ddw-work/goback-proposal.txt"
gbk_edge >/dev/null 2>&1 \
  && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))['phase']=='PLAN' else 1)" "$GBK/.ddw-state.json" \
  && ok "and a correction: on file announces and goes — the mandatory loop still never asks permission" \
  || bad "the correction lane is blocked, which turns the mandatory corrective loop into a question again"

gbk_state
printf 'ask: which of the two stacks stands? CODE -> PLAN\n' > "$GBK/.ddw-work/goback-proposal.txt"
GBOUT="$(gbk_edge || true)"
case "$GBOUT" in
  *"has not been in front of the user"*)
    ok "an ask: without the user's turn is held at the edge" ;;
  *) bad "a question executed the loop before anyone answered it — the measured defect, still open" ;;
esac

python3 "$SELF/ddw/scripts/hook-gate.py" --mode turn --state "$GBK/.ddw-state.json" \
  --graph "$SELF/ddw/rules/transition-graph.json" --repo "$GBK" < /dev/null >/dev/null 2>&1 || true
gbk_edge >/dev/null 2>&1 \
  && python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))['phase']=='PLAN' else 1)" "$GBK/.ddw-state.json" \
  && ok "and the sealed answer arms the same edge — asked before, taken with the answer in hand" \
  || bad "the user answered and the edge still refuses — the seal is not being read"

# The hook path judges the same thing for a state written with the Write tool.
gbk_state
rm -f "$GBK/.ddw-work/goback-proposal.txt"
python3 - "$GBK" <<'PYGBE'
import json, sys
root = sys.argv[1]
s = json.load(open(root + "/.ddw-state.json"))
s["phase"] = "PLAN"; s["gates"] = {"define": True}
s["history"].append({"timestamp": "2026-01-01T00:09:00Z", "from": "CODE", "to": "PLAN",
                     "action": "loop", "tier": "FEATURE", "ticket": "FEAT-001"})
open(root + "/event.json", "w").write(json.dumps(
    {"tool_name": "Write", "tool_input": {"file_path": ".ddw-state.json",
                                          "content": json.dumps(s)}}))
PYGBE
python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$GBK/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$GBK" < "$GBK/event.json" >/dev/null 2>&1 \
  && bad "a Write-tool backward edge sailed past the hook with no reason on disk" \
  || ok "and the Write-tool path is held to the same gate as the helper"

# ── The steps prose alone could not hold ──────────────────────────────────────
#
# Three rules the least obedient models skipped on live general runs, measured
# twice each, previously enforced by nothing: the context check CLASSIFY orders
# once per ticket, the decisions record CODE's block loop orders per approval,
# and the two-stage review each block-marker advance spends. Each now leaves a
# file a gate can ask for. The files are model-written — the receipt's honest
# bargain, stated in ddw_receipt.py — so what these checks prove is that
# skipping the step is no longer SILENT, never that it was done well.
section "The steps prose alone could not hold now leave files gates demand"

PG="$WORK/prose-gates"; mkdir -p "$PG/.ddw-work" "$PG/docs/ddw/specs"; git -C "$PG" init -q .
pg_tr() {
  python3 "$SELF/ddw/scripts/transition.py" --state "$PG/.ddw-state.json" \
    --graph "$SELF/ddw/rules/transition-graph.json" "$@" 2>&1
}

printf '{"phase": "IDLE", "tier": null, "ticket": null, "title": null, "gates": {}, "history": []}\n' > "$PG/.ddw-state.json"
pg_tr --to CLASSIFY --ticket F-9 --title "prose gates" --action "clasificar" --write >/dev/null \
  || bad "fixture: IDLE->CLASSIFY failed and the three checks below measure nothing"
PGOUT="$(pg_tr --to DEFINE --tier FEATURE --ticket F-9 --title "prose gates" --action "definir" --write || true)"
case "$PGOUT" in
  *ddw-context-check*)
    ok "CLASSIFY does not close without the context check's file — the step prose lost twice" ;;
  *) bad "the classify edge opened with no context check on disk — the twice-measured skip is silent again" ;;
esac
printf 'Nothing to report: the context file matches the repo.\n' > "$PG/.ddw-work/context-check-F-9.md"
PGOUT="$(pg_tr --to DEFINE --tier FEATURE --ticket F-9 --title "prose gates" --action "definir" --write 2>&1)" \
  && ok "and opens the moment the file exists" \
  || bad "the context-check gate refuses the edge even with the file on disk"
case "$PGOUT" in
  *"── DDW ─ DEFINE"*)
    ok "and the landed write prints where the run stands — the status line models kept skipping, now printed by the tool" ;;
  *) bad "the write lands silently; where-are-we is prose again, and prose measured near zero" ;;
esac

# The block marker spends the block's reviews. Setting it on ENTERING the phase
# — the misreading every live run makes — is refused with the semantics named.
python3 - "$PG" <<'PYPGC'
import json, sys
h = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
      "action": "x", "tier": "FEATURE", "ticket": "F-9"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"),
                                 ("DEFINE", "PLAN"), ("PLAN", "CODE")])]
json.dump({"tier": "FEATURE", "phase": "CODE", "ticket": "F-9", "title": "prose gates",
           "tracker": None, "autonomy": "assisted", "gates": {"define": True,
           "spec": True, "threat": True}, "block": None, "discovery": None,
           "history": h}, open(sys.argv[1] + "/.ddw-state.json", "w"), indent=2)
PYPGC
PGOUT="$(pg_tr --block 1/5 --write || true)"
case "$PGOUT" in
  *FINISHED*)
    ok "--block N/M means block N FINISHED, and without its two review verdicts on disk it is refused" ;;
  *) bad "the marker advanced with no review on disk — the measured self-audit collapse is silent again" ;;
esac
printf 'verifier: PASSED — matches the spec, TDD evidence shown\narch: PASSED — conventions hold\n' > "$PG/.ddw-work/review-block-1.md"
pg_tr --block 1/5 --write >/dev/null 2>&1 \
  && ok "and advances once both verdicts are on file" \
  || bad "the review gate refuses the marker even with both verdicts on disk"

# CODE does not close without the decisions record — even when the record says
# there was nothing to record, because \"nobody wrote it\" and \"nothing to
# write\" have to be different states on disk.
ddw_earn "$PG" tests F-9
ddw_earn "$PG" sast F-9
python3 - "$PG" <<'PYPGD'
import json, sys
s = json.load(open(sys.argv[1] + "/.ddw-state.json"))
s["gates"].update({"tests": True, "sast": True}); s["block"] = None
json.dump(s, open(sys.argv[1] + "/.ddw-state.json", "w"), indent=2)
PYPGD
PGOUT="$(pg_tr --to VERIFY --action "code cerrado" --write || true)"
case "$PGOUT" in
  *decisions-F-9.md*)
    ok "CODE does not close without docs/ddw/specs/decisions-F-9.md — approvals leave the conversation" ;;
  *) bad "CODE closed with every picker-approval unrecorded — the measured hole is open again" ;;
esac
printf 'No decisions were approved outside the spec during this ticket.\n' > "$PG/docs/ddw/specs/decisions-F-9.md"
pg_tr --to VERIFY --action "code cerrado" --write >/dev/null 2>&1 \
  && ok "and closes with the record on disk, 'nothing' spelled out included" \
  || bad "the decisions gate refuses the edge even with the record on disk"

# The hook path judges the same three for a state written with the Write tool —
# a gate only the sanctioned helper enforces is decoration.
python3 - "$PG" <<'PYPGE'
import json, sys
root = sys.argv[1]
h = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
      "action": "x", "tier": "FEATURE", "ticket": "F-8"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY")])]
state = {"tier": "FEATURE", "phase": "CLASSIFY", "ticket": "F-8", "title": "x",
         "tracker": None, "autonomy": "assisted", "gates": {}, "block": None,
         "discovery": None, "history": h}
json.dump(state, open(root + "/.ddw-state.json", "w"), indent=2)
new = json.loads(json.dumps(state))
new["phase"] = "DEFINE"
new["history"].append({"timestamp": "2026-01-01T00:05:00Z", "from": "CLASSIFY",
                       "to": "DEFINE", "action": "x", "tier": "FEATURE", "ticket": "F-8"})
open(root + "/event.json", "w").write(json.dumps(
    {"tool_name": "Write", "tool_input": {"file_path": ".ddw-state.json",
                                          "content": json.dumps(new)}}))
PYPGE
PGOUT="$(python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$PG/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$PG" < "$PG/event.json" 2>&1 || true)"
case "$PGOUT" in
  *ddw-context-check*)
    ok "and the Write-tool path demands the context check like the helper does" ;;
  *) bad "a Write-tool classify edge sailed past the hook with no context check on disk" ;;
esac

# CODE closing by hand-written Write is held to the decisions record too.
ddw_earn "$PG" tests F-8
ddw_earn "$PG" sast F-8
python3 - "$PG" <<'PYPGG'
import json, sys
root = sys.argv[1]
h = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
      "action": "x", "tier": "FEATURE", "ticket": "F-8"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"),
                                 ("DEFINE", "PLAN"), ("PLAN", "CODE")])]
state = {"tier": "FEATURE", "phase": "CODE", "ticket": "F-8", "title": "x",
         "tracker": None, "autonomy": "assisted", "gates": {"define": True,
         "spec": True, "threat": True, "tests": True, "sast": True},
         "block": None, "discovery": None, "history": h}
json.dump(state, open(root + "/.ddw-state.json", "w"), indent=2)
new = json.loads(json.dumps(state))
new["phase"] = "VERIFY"
new["history"].append({"timestamp": "2026-01-01T00:07:00Z", "from": "CODE",
                       "to": "VERIFY", "action": "x", "tier": "FEATURE", "ticket": "F-8"})
open(root + "/event.json", "w").write(json.dumps(
    {"tool_name": "Write", "tool_input": {"file_path": ".ddw-state.json",
                                          "content": json.dumps(new)}}))
PYPGG
PGOUT="$(python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$PG/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$PG" < "$PG/event.json" 2>&1 || true)"
case "$PGOUT" in
  *decisions-F-8.md*)
    ok "and a hand-written CODE close is held to the decisions record" ;;
  *) bad "a Write-tool CODE close sailed past the hook with no decisions record on disk" ;;
esac

python3 - "$PG" <<'PYPGF'
import json, sys
root = sys.argv[1]
s = json.load(open(root + "/.ddw-state.json"))
new = json.loads(json.dumps(s))
new["phase"] = "CODE"; new["block"] = "3/5"
new["gates"] = {"define": True, "spec": True, "threat": True}
s["phase"] = "CODE"; s["gates"] = {"define": True, "spec": True, "threat": True}
s["history"] = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
                 "action": "x", "tier": "FEATURE", "ticket": "F-8"}
                for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"),
                                            ("DEFINE", "PLAN"), ("PLAN", "CODE")])]
new["history"] = list(s["history"])
json.dump(s, open(root + "/.ddw-state.json", "w"), indent=2)
open(root + "/event.json", "w").write(json.dumps(
    {"tool_name": "Write", "tool_input": {"file_path": ".ddw-state.json",
                                          "content": json.dumps(new)}}))
PYPGF
PGOUT="$(python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$PG/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$PG" < "$PG/event.json" 2>&1 || true)"
case "$PGOUT" in
  *FINISHED*)
    ok "and a hand-written block advance is held to the same reviews" ;;
  *) bad "a Write-tool block advance sailed past the hook with no reviews on disk" ;;
esac

# The state's refusals name the door. The bare finding sent a live model on a
# six-call hunt through the hook's own source for a way around it; a refusal
# that names `transition.py --write` is answered with one command instead.
printf '{"tool_name": "Edit", "tool_input": {"file_path": ".ddw-state.json"}}' > "$PG/event.json"
PGOUT="$(python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$PG/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$PG" < "$PG/event.json" 2>&1 || true)"
case "$PGOUT" in
  *transition.py*)
    ok "a hand edit of the state is refused WITH the sanctioned command in the refusal" ;;
  *) bad "the state's refusal is a puzzle again — the measured six-call bypass hunt starts here" ;;
esac

# ── The family index: the document that cannot lie ────────────────────────────
#
# A multirepo initiative's parent is a committed document whose rows speak for
# OTHER repositories — the one thing in the method that does. The write gate
# holds one sentence: a row says `done` only when the forge confirms that
# repo's child PR merged. Two declared outs, both carrying a reason.
section "The family index cannot say done without the forge"

FAM="$WORK/family"; mkdir -p "$FAM/docs/ddw/prd" "$FAM/bin"; git -C "$FAM" init -q .
cat > "$FAM/docs/ddw/prd/prd-CHK-1.md" <<'FAMEOF'
# Parent PRD: Checkout

| Metric | Value |
|--------|-------|
| Ticket | CHK-1 |
| Status | Multirepo split |

## Repos

| Repo | Ticket | Scope | Depends on | Status |
|---|---|---|---|---|
| acme/tienda-back | CHK-1 | api de pagos | none | active |
| acme/tienda-bff | CHK-1 | exponer pagos | tienda-back | pending |
FAMEOF
printf '{"phase": "IDLE", "tier": null, "ticket": null, "gates": {}, "history": []}\n' > "$FAM/.ddw-state.json"

FAMOUT="$(python3 "$SELF/ddw/scripts/validate_prd.py" "$FAM/docs/ddw/prd/prd-CHK-1.md" --tier FEATURE 2>&1)" \
  && compgen -G "$FAM/.ddw-sessions/prd-validated-*" >/dev/null \
  && ok "a well-formed family index passes F-PRD-12 and earns the ordinary receipt" \
  || bad "the healthy multirepo index is refused by its own validator, or earns no receipt: $(echo "$FAMOUT" | tail -2)"

sed 's/| tienda-back | pending |/| tienda-pagos | pending |/' \
  "$FAM/docs/ddw/prd/prd-CHK-1.md" > "$FAM/docs/ddw/prd/prd-CHK-9.md"
python3 "$SELF/ddw/scripts/validate_prd.py" "$FAM/docs/ddw/prd/prd-CHK-9.md" --tier FEATURE >/dev/null 2>&1 \
  && bad "a family row depending on a repo no row lists passed validation" \
  || ok "and a dependency outside the table is refused — a row the order cannot schedule"
rm -f "$FAM/docs/ddw/prd/prd-CHK-9.md"

# The map's double close. With ddw-family.md beside the index, F-PRD-12 also
# holds the split to the FAMILY: a row the map does not know cannot be
# scheduled, and a member the index forgets — neither row nor exclusion — is
# the impact analysis failing at DEFINE after passing at CLASSIFY. On a copy,
# so the fixtures above stay exactly what later checks expect.
FAM2="$WORK/family-map"; rm -rf "$FAM2"; cp -r "$FAM" "$FAM2"
cat > "$FAM2/ddw-family.md" <<'MAPEOF'
# Familia
| Repo | Qué hace | Expone | Consumed by | Consume |
|---|---|---|---|---|
| acme/tienda-back | api | api | tienda-bff | none |
| acme/tienda-bff | bff | ui | none | tienda-back |
| acme/tienda-worker | worker | jobs | none | none |
MAPEOF
printf '\n## Sin impacto\n- tienda-worker: Sin impacto — no consume nada de esto\n' \
  >> "$FAM2/docs/ddw/prd/prd-CHK-1.md"
python3 "$SELF/ddw/scripts/validate_prd.py" "$FAM2/docs/ddw/prd/prd-CHK-1.md" --tier FEATURE >/dev/null 2>&1 \
  && ok "an index that accounts for every member of ddw-family.md passes the map's double close" \
  || bad "the honest index was refused the moment ddw-family.md appeared beside it"
# Ghost the BFF row (its dependency on tienda-back stays satisfiable), so the
# ONLY rule that can refuse this index is the map's double close — under the
# "index stops checking the map" fault it passes, and the bad below fires.
sed 's#| acme/tienda-bff |#| acme/tienda-ghost |#' "$FAM2/docs/ddw/prd/prd-CHK-1.md" \
  > "$FAM2/docs/ddw/prd/prd-CHK-7.md"
if MAPOUT="$(python3 "$SELF/ddw/scripts/validate_prd.py" "$FAM2/docs/ddw/prd/prd-CHK-7.md" --tier FEATURE 2>&1)"; then
  bad "an index scheduling a repo the family map never heard of passed validation: $(echo "$MAPOUT" | tail -1)"
else
  echo "$MAPOUT" | grep -q "family map" \
    && ok "and a row the map does not know — plus the member it displaced — is refused naming the map" \
    || bad "the phantom row is refused without naming the map — the message teaches nothing: $(echo "$MAPOUT" | tail -1)"
fi

cat > "$FAM/bin/gh" <<'FAMGH'
#!/bin/bash
echo "${FAM_GH_OUT:-[]}"; exit "${FAM_GH_RC:-0}"
FAMGH
chmod +x "$FAM/bin/gh"

fam_write() {  # $1 = the status cell for tienda-back's row
  python3 - "$FAM" "$1" > "$FAM/event.json" <<'FAMEV'
import json, sys
root, status = sys.argv[1], sys.argv[2]
idx = open(root + "/docs/ddw/prd/prd-CHK-1.md", encoding="utf-8").read()
new = idx.replace("| none | active |", "| none | %s |" % status)
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": "docs/ddw/prd/prd-CHK-1.md",
                                 "content": new}}))
FAMEV
  PATH="$FAM/bin:$PATH" python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$FAM/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$FAM" < "$FAM/event.json" 2>&1
}

FAMOUT="$(FAM_GH_OUT='[{"headRefName":"feat/CHK-1-pagos","state":"OPEN","number":7}]' fam_write done || true)"
case "$FAMOUT" in
  *tienda-back*MERGED*|*MERGED*tienda-back*)
    ok "a row marked done over an OPEN pull request is refused, naming the repo — the epic cannot lie" ;;
  *) bad "the family index said done over an unmerged PR and the hook let it land" ;;
esac

FAM_GH_OUT='[{"headRefName":"feat/CHK-1-pagos","state":"MERGED","number":7}]' fam_write done >/dev/null 2>&1 \
  && ok "and a forge-confirmed merge opens the same row" \
  || bad "the gate refuses a done the forge confirms — a guard that never lets anything through"

FAMOUT="$(FAM_GH_RC=1 fam_write done || true)"
case "$FAMOUT" in
  *unverified*)
    ok "an unreachable forge refuses AND names the declared way out — the count never degrades in silence" ;;
  *) bad "with the forge down the index either lied quietly or refused with no way out" ;;
esac

FAM_GH_RC=1 fam_write "done (unverified: gh caido, PR visto por un humano)" >/dev/null 2>&1 \
  && FAM_GH_RC=1 fam_write "dropped: esa parte se pospone" >/dev/null 2>&1 \
  && ok "and both declared outs pass with the forge down — an escape hatch on the record, not a hole" \
  || bad "a declared out (dropped/unverified with reason) is refused, which teaches people to route around the gate"

# The three closures of the layer's own determinism audit (2026-08-26): a
# status in other words, a silently vanished row, and a dismissed judge —
# each a failure that would be INVISIBLE afterwards, which is the standard.
FAMOUT="$(fam_write merged || true)"
case "$FAMOUT" in
  *vocabulary*)
    ok "a status outside the vocabulary is refused — merged sounds like done and is checked by nobody" ;;
  *) bad "a row saying 'merged' landed unjudged: completion nothing verified" ;;
esac

python3 - "$FAM" > "$FAM/event.json" <<'FAMDEL'
import json, sys
idx = open(sys.argv[1] + "/docs/ddw/prd/prd-CHK-1.md", encoding="utf-8").read()
new = "\n".join(l for l in idx.splitlines() if "tienda-bff" not in l)
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": "docs/ddw/prd/prd-CHK-1.md",
                                 "content": new}}))
FAMDEL
FAMOUT="$(PATH="$FAM/bin:$PATH" python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$FAM/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$FAM" < "$FAM/event.json" 2>&1 || true)"
case "$FAMOUT" in
  *tienda-bff*vanish*|*vanish*tienda-bff*|*tienda-bff*dropped*)
    ok "a vanished row is refused by name — the count cannot quietly stop counting" ;;
  *) bad "a row was deleted from the index with no dropped reason and the hook let it land" ;;
esac

python3 - "$FAM" > "$FAM/event.json" <<'FAMMARK'
import json, sys
idx = open(sys.argv[1] + "/docs/ddw/prd/prd-CHK-1.md", encoding="utf-8").read()
print(json.dumps({"tool_name": "Write",
                  "tool_input": {"file_path": "docs/ddw/prd/prd-CHK-1.md",
                                 "content": idx.replace("| Status | Multirepo split |",
                                                        "| Status | done |")}}))
FAMMARK
PATH="$FAM/bin:$PATH" python3 "$SELF/ddw/scripts/hook-gate.py" --mode pre --dialect standard \
    --state "$FAM/.ddw-state.json" --graph "$SELF/ddw/rules/transition-graph.json" \
    --repo "$FAM" < "$FAM/event.json" >/dev/null 2>&1 \
  && bad "the write that removes the Multirepo marker dismissed the judge and landed" \
  || ok "and removing the marker that makes the document judged is itself refused"

# The multirepo pause spends the index's receipt — the orphaned-receipt hole.
FPP="$WORK/fam-pause"; mkdir -p "$FPP/docs/ddw/prd"; git -C "$FPP" init -q .
cp "$FAM/docs/ddw/prd/prd-CHK-1.md" "$FPP/docs/ddw/prd/prd-CHK-1.md"
python3 - "$FPP" <<'FPPST'
import json, sys
h = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t,
      "action": "x", "tier": "FEATURE", "ticket": "CHK-1"}
     for i, (f, t) in enumerate([("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE")])]
json.dump({"tier": "FEATURE", "phase": "DEFINE", "ticket": "CHK-1", "title": "x",
           "tracker": None, "autonomy": "assisted", "gates": {}, "block": None,
           "discovery": None, "history": h},
          open(sys.argv[1] + "/.ddw-state.json", "w"), indent=2)
FPPST
fpp_pause() {
  python3 "$SELF/ddw/scripts/transition.py" --state "$FPP/.ddw-state.json" \
    --graph "$SELF/ddw/rules/transition-graph.json" --to IDLE \
    --action "pause: multirepo split into back/bff" --write 2>&1
}
FAMOUT="$(fpp_pause || true)"
case "$FAMOUT" in
  *vouched*)
    ok "a multirepo pause on an index the validator never vouched for is refused" ;;
  *) bad "an unvalidated index went on to govern its repos — the receipt nobody consumes" ;;
esac
( cd "$FPP" && python3 "$SELF/ddw/scripts/validate_prd.py" docs/ddw/prd/prd-CHK-1.md --tier FEATURE >/dev/null 2>&1 )
fpp_pause >/dev/null 2>&1 \
  && ok "and the validated index's pause goes through — the receipt is what was being asked for" \
  || bad "the pause refuses a receipt that exists, which walls the protocol's own mandated exit"

# A receipt re-validated with identical bytes is one event, not two journal
# lines (measured: identical consecutive records, one validator run). And a
# `spent` record belongs to ITS ticket: a closed ticket's receipts used to read
# as spent the moment a later ticket's loop touched the same gate.
python3 - "$SELF" "$WORK" <<'PYRDUP'
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location(
    "dr", os.path.join(sys.argv[1], "ddw/scripts/ddw_receipt.py"))
dr = importlib.util.module_from_spec(spec); spec.loader.exec_module(dr)
root = os.path.join(sys.argv[2], "receipt-dup"); os.makedirs(os.path.join(root, "docs"), exist_ok=True)
open(os.path.join(root, ".ddw-state.json"), "w").write("{}")
art = os.path.join(root, "docs", "prd-X.md"); open(art, "w").write("# X\n")
dr.write(art, "prd", "# X\n", tier="FEATURE")
dr.write(art, "prd", "# X\n", tier="FEATURE")
lines = [ln for ln in open(os.path.join(root, ".ddw-journal.jsonl")).read().splitlines() if ln]
assert len(lines) == 1, "expected one receipt record, got %d" % len(lines)

spec2 = importlib.util.spec_from_file_location(
    "vt", os.path.join(sys.argv[1], "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(vt)
with open(os.path.join(root, ".ddw-journal.jsonl"), "a") as fh:
    fh.write(json.dumps({"record": "spent", "gates": ["spec"], "ticket": "FEAT-002",
                         "phase": "PLAN"}) + "\n")
    fh.write(json.dumps({"record": "receipt", "name": "spec-validated-aaa", "file": "s.md"}) + "\n")
    fh.write(json.dumps({"record": "spent", "gates": ["spec"], "ticket": "FEAT-003",
                         "phase": "PLAN"}) + "\n")
assert vt._receipt_spent(root, "spec", "spec-validated-aaa", ticket="FEAT-002") is None, \
    "another ticket's spending spent this one's receipt"
assert vt._receipt_spent(root, "spec", "spec-validated-aaa", ticket="FEAT-003") is not None, \
    "the ticket's own spending stopped counting"
PYRDUP
[ $? -eq 0 ] \
  && ok "identical re-validation writes one journal line, and a spent gate binds only its own ticket" \
  || bad "the journal duplicates unchanged receipts, or a closed ticket's receipts are spent by a later ticket's loop"

# The test run report. `tests: true` used to be a sentence — no runner, no
# command, no numbers, no names, nothing anyone could reproduce. DDW still does
# not run your suite; what it refuses now is the account being absent, vague or
# arithmetically impossible.
mkdir -p "$VP/docs/ddw/reports"
cat > "$VP/docs/ddw/reports/tests-FEAT-001.md" <<'TSTEOF'
# Test run — FEAT-001

| Field | Value |
|---|---|
| Runner | pytest 8.2 |
| Command | uv run pytest -q --cov=app |
| Total | 42 |
| Passed | 40 |
| Failed | 0 |
| Skipped | 2 |
| Line coverage | 87% |
| Branch coverage | 81% |
| Function coverage | 92% |
| Coverage floor | 80% (AGENTS.md) |
| Lint | ruff clean |

## Skipped
- `tests/test_email.py::test_send` — reason: needs network credentials, covered by the fake
- `tests/test_kb.py::test_big` — reason: 50 MB fixture, runs nightly
TSTEOF
python3 "$SELF/ddw/scripts/validate_tests.py" "$VP/docs/ddw/reports/tests-FEAT-001.md" --tier FEATURE >/dev/null 2>&1 \
  && compgen -G "$VP/.ddw-sessions/tests-validated-*" >/dev/null \
  && ok "validate_tests.py passes a complete run report and leaves the content-hashed receipt" \
  || bad "the test-report validator rejects a complete report or writes no receipt"

# Arithmetic is the one thing a report cannot get wrong quietly.
python3 - "$VP" <<'PYTC'
import sys, os
p = os.path.join(sys.argv[1], "docs/ddw/reports/tests-FEAT-001.md")
s = open(p, encoding="utf-8").read().replace("| Total | 42 |", "| Total | 50 |")
open(os.path.join(sys.argv[1], "docs/ddw/reports/tests-bad.md"), "w", encoding="utf-8").write(s)
PYTC
# A run nobody can reproduce is an anecdote, and this is the rule that says so.
python3 - "$VP" <<'PYTR'
import sys, os
p = os.path.join(sys.argv[1], "docs/ddw/reports/tests-FEAT-001.md")
s = open(p, encoding="utf-8").read().replace("| Command | uv run pytest -q --cov=app |\n", "")
open(os.path.join(sys.argv[1], "docs/ddw/reports/tests-norun.md"), "w", encoding="utf-8").write(s)
PYTR
VTROUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$VP/docs/ddw/reports/tests-norun.md" 2>/dev/null || true)"
case "$VTROUT" in
  *"❌ F-TEST-01"*Command*) ok "and a run report that does not say how it was produced is refused" ;;
  *) bad "a test report with no command earned the tests gate — nobody can re-run it" ;;
esac

VTCOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$VP/docs/ddw/reports/tests-bad.md" 2>/dev/null || true)"
case "$VTCOUT" in
  *"❌ F-TEST-02"*"do not add up"*) ok "and counts that do not add up are refused — that is two runs in one report" ;;
  *) bad "a report claiming 50 tests over 40 passed + 0 failed + 2 skipped earned a receipt" ;;
esac

# The rule the script never had: `ddw-test` says 0 failing tests earns the gate,
# and the validator that writes that gate's receipt was not checking it.
python3 - "$VP" <<'PYRED'
import sys, os
p = os.path.join(sys.argv[1], "docs/ddw/reports/tests-FEAT-001.md")
s = open(p, encoding="utf-8").read().replace("| Passed | 40 |", "| Passed | 33 |") \
    .replace("| Failed | 0 |", "| Failed | 7 |")
s += "\n## Failures\n" + "\n".join(f"- `tests/test_x.py::test_{i}` fails" for i in range(7)) + "\n"
open(os.path.join(sys.argv[1], "docs/ddw/reports/tests-red.md"), "w", encoding="utf-8").write(s)
PYRED
VTDOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$VP/docs/ddw/reports/tests-red.md" 2>/dev/null || true)"
case "$VTDOUT" in
  *"❌ F-TEST-08"*) ok "and a report of a red run does not earn the tests gate, however complete it is" ;;
  *) bad "seven failing tests, named and adding up, earned the gate that claims the suite is green" ;;
esac

# One report, one run. `_field` takes the first match, so a per-suite breakdown
# was read as its first suite and the rest of the run disappeared.
printf '%s\n' '## Unit' '| Runner | pytest |' '| Command | pytest -q |' '| Total | 12 |' \
  '| Passed | 12 |' '| Failed | 0 |' '| Line coverage | 91% |' '| Branch coverage | 88% |' \
  '| Function coverage | 95% |' '| Coverage floor | 80% (AGENTS.md) |' '' '## Integration' \
  '| Total | 30 |' '| Passed | 25 |' '| Failed | 5 |' '| Line coverage | 44% |' \
  > "$VP/docs/ddw/reports/tests-multi.md"
VTMOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$VP/docs/ddw/reports/tests-multi.md" 2>/dev/null || true)"
case "$VTMOUT" in
  *"❌ F-TEST-07"*) ok "and a report describing two runs is refused rather than read as its first one" ;;
  *) bad "a green unit suite above a red integration suite passed as one green run" ;;
esac

# The floor belongs to the project. A report that picks its own passes itself.
python3 - "$VP" <<'PYTF'
import sys, os
p = os.path.join(sys.argv[1], "docs/ddw/reports/tests-FEAT-001.md")
s = open(p, encoding="utf-8").read().replace("| Line coverage | 87% |", "| Line coverage | 61% |")
open(os.path.join(sys.argv[1], "docs/ddw/reports/tests-low.md"), "w", encoding="utf-8").write(s)
PYTF
VTFOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$VP/docs/ddw/reports/tests-low.md" 2>/dev/null || true)"
case "$VTFOUT" in
  *"❌ F-TEST-04"*"under the floor"*61*) ok "and coverage under the quoted floor is named with its number" ;;
  *) bad "61% line coverage passed a report quoting an 80% floor" ;;
esac

# The floor's SOURCE is read back, not pattern-matched. Measured live
# (2026-08-25): the project's AGENTS.md declared no floor, and the report wrote
# "80% (docs/ddw — .ddw/rules/testing.instructions.md)" — an attribution built
# to contain the substring the old check accepted. Four doors, one check each.
FLR="$WORK/floor"; mkdir -p "$FLR/docs/ddw/reports"
printf '# Proj\n\n## Testing\n- Runner: pytest\n' > "$FLR/AGENTS.md"
floor_report() {  # $1 = floor row value, $2 = output name
  sed "s#| Coverage floor | 80% (AGENTS.md) |#| Coverage floor | $1 |#" \
    "$VP/docs/ddw/reports/tests-FEAT-001.md" > "$FLR/docs/ddw/reports/$2"
}
floor_report "80% (AGENTS.md)" tests-fabricated.md
FLAOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$FLR/docs/ddw/reports/tests-fabricated.md" 2>/dev/null || true)"
case "$FLAOUT" in
  *"❌ F-TEST-05"*"does not state that number"*) ok "a floor attributed to an AGENTS.md that never states it is refused" ;;
  *) bad "the report attributes its floor to AGENTS.md, AGENTS.md is silent, and the attribution passes" ;;
esac

printf '# Proj\n\n## Testing\n- Runner: pytest\n- Coverage floor: 85%%\n' > "$FLR/AGENTS.md"
floor_report "85% (AGENTS.md)" tests-honest.md
FLBOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$FLR/docs/ddw/reports/tests-honest.md" 2>/dev/null || true)"
case "$FLBOUT" in
  *"✅ F-TEST-05"*"read back"*) ok "and one AGENTS.md actually states is verified against the file" ;;
  *) bad "a floor AGENTS.md really declares is not read back as verified" ;;
esac

floor_report "80% (method default — .ddw/rules/testing.instructions.md)" tests-default.md
FLCOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$FLR/docs/ddw/reports/tests-default.md" 2>/dev/null || true)"
case "$FLCOUT" in
  *"✅ F-TEST-05"*"method default"*) ok "the method's own 80 passes named as what it is — the default" ;;
  *) bad "the honest wording for the method default is refused, which pushes reports back to fabricating" ;;
esac

floor_report "90% (.ddw/rules/testing.instructions.md)" tests-inflated.md
FLDOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$FLR/docs/ddw/reports/tests-inflated.md" 2>/dev/null || true)"
case "$FLDOUT" in
  *"❌ F-TEST-05"*"whose default is 80"*) ok "and a floor the method never set cannot be attributed to it" ;;
  *) bad "90% attributed to a method whose default is 80 passed as sourced" ;;
esac

# F-VER-03 reads the PROJECT's floor too — the catalog said so and the code
# said 80, always. AGENTS.md raises it to 90; 85% has to fail.
printf '# Proj\n\n## Testing\n- Coverage floor: 90%%\n' > "$FLR/AGENTS.md"
cat > "$FLR/docs/ddw/reports/verify-floor.md" <<'VFLEOF'
# Verification — FEAT-009
- Line coverage: 85%
- Branch coverage: 85%
- Function coverage: 85%
Sad-path testing: invalid inputs covered.
Lint: clean.
VFLEOF
FLVOUT="$(python3 "$SELF/ddw/scripts/validate_verify.py" "$FLR/docs/ddw/reports/verify-floor.md" --tier FEATURE 2>/dev/null || true)"
case "$FLVOUT" in
  *"❌ F-VER-03"*"below the 90% minimum"*) ok "the verify floor is the project's: 85% fails a repo whose AGENTS.md says 90" ;;
  *) bad "AGENTS.md raised the floor to 90 and validate_verify still measured against 80" ;;
esac

# The spec skill's schema-reuse sentence, validated by the spec validator — the
# phrase is EXTRACTED from the skill, so if either side drifts this goes red.
# Two different models failed F-SPEC-08 three times on exactly this block shape
# ("same table as above" names no constraint); the skill now teaches the shape
# that passes, and this is the check that the taught shape and the accepted
# shape are the same bytes.
TPL="$WORK/spec-teaches"; mkdir -p "$TPL/docs/ddw/specs"
REUSE="$(sed -n '/^- Reuses /,+1p' "$SELF/skills/ddw-create-spec/SKILL.md" | head -2)"
[ -n "$REUSE" ] || REUSE="(the skill no longer contains the reuse sentence)"
cat > "$TPL/docs/ddw/specs/spec-FEAT-001.md" <<TPLEOF
# Spec FEAT-001: harness

| Field | Value |
|-------|-------|
| Ticket | FEAT-001 |
| Spec loops | 0 |
| Loops since last human decision | 0 |

## Block 1 — schema
**Files**
- \`app/db.py\` (new)

**Logic**
Creates the table.

**Data model**
- Entity ticket: id (PK), titulo (not null), estado (default "Pendiente"), index on estado.

**Error handling**
- None — this block takes no input of its own.

**Required tests**
- [ ] test_schema — validates AC-01

**Completion criterion**
test_schema passes.

## Block 2 — listing
**Files**
- \`app/listing.py\` (new)

**Logic**
Reads the table Block 1 declares.

**Data model**
$REUSE

**Error handling**
- None — this block takes no input of its own.

**Required tests**
- [ ] test_listado — validates AC-02

**Completion criterion**
test_listado passes.
TPLEOF
TPLOUT="$(python3 "$SELF/ddw/scripts/validate_spec.py" "$TPL/docs/ddw/specs/spec-FEAT-001.md" --tier FEATURE 2>/dev/null || true)"
case "$TPLOUT" in
  *"✅ F-SPEC-08"*) ok "the reuse sentence the spec skill teaches is one its own validator accepts" ;;
  *) bad "the spec skill teaches a schema-reuse phrasing that validate_spec rejects — the template its own gate refuses, again" ;;
esac

# The two layouts a real report arrives in, both of which used to be read as an
# absence: coverage as the two-column table every coverage tool prints, whose
# metric name is the bare word, and the lint result under its own heading rather
# than on a `Lint:` line. Refusing either says "coverage missing" or "no lint
# result" about a document that has both — which sends the author looking for
# something that is already there.
cat > "$VP/docs/ddw/reports/tests-layout.md" <<'TSTLAY'
# Test run — FEAT-002

| Field | Value |
|---|---|
| Runner | pytest 8.2 |
| Command | uv run pytest -q --cov=app |
| Total | 10 |
| Passed | 10 |
| Failed | 0 |
| Skipped | 0 |
| Coverage floor | 80% (AGENTS.md) |

## Coverage
| Metric | % |
|---|---|
| Line | 88% |
| Branch | 84% |
| Function | 90% |

## Lint
ruff clean
TSTLAY
VTLOUT="$(python3 "$SELF/ddw/scripts/validate_tests.py" "$VP/docs/ddw/reports/tests-layout.md" 2>/dev/null || true)"
case "$VTLOUT" in
  *"✅ F-TEST-04"*"line 88%"*"branch 84%"*"function 90%"*)
    ok "and a two-column coverage table is read by its bare metric names, not called missing" ;;
  *) bad "coverage written as \`| Line | 88% |\` — the shape every coverage tool prints — read as absent" ;;
esac
case "$VTLOUT" in
  *"W-TEST-01"*) bad "a lint result under its own \`## Lint\` heading is reported as no lint result at all" ;;
  *) ok "and a lint result under its own heading counts, so W-TEST-01 does not send the reader hunting" ;;
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
  *"❌ F-VER-03"*"61%"*) ok "and coverage under the minimum is named with its number" ;;
  *) bad "a verdict reporting 61% line coverage passed the 80% floor" ;;
esac

# The report written in the shape the verify SKILL mandates, with every
# criterion marked FAILED. `❌` is not a word character, so the `\b(...)\b` this
# rule used demanded one on both sides of the mark — and no shape the skill
# teaches has that. The mark was unmatchable in the document it was designed
# for: F-VER-01 answered "all AC carry a passing verdict" about a verdict where
# none did, and the receipt was written. Everything else in this report is
# sound, so the mark is the only thing under test.
VFD="$WORK/verify-failed/docs/ddw"; mkdir -p "$VFD/reports" "$VFD/prd" "$VFD/specs"
cp "$VP/docs/ddw/prd/prd-FEAT-001.md" "$VFD/prd/prd-FEAT-001.md"
cp "$VS/spec-FEAT-001.md" "$VFD/specs/spec-FEAT-001.md"
cat > "$VFD/reports/verify-FEAT-001.md" <<'VERFAIL'
# Verification FEAT-001

| Field | Value |
|---|---|
| Module | app/routes/public.py |
| Line coverage | 94% |
| Branch coverage | 91% |
| Function coverage | 100% |
| Coverage floor | 80% (AGENTS.md, "Testing") |
| Lint | `ruff check .` — clean |

## Acceptance criteria
- ❌ AC-01 — `test_form_visible` never ran
- ❌ AC-02 — `test_campo_faltante_devuelve_400` not implemented

## Spec blocks
- Block 1 — implementado completo.

## Tests
- Sad-path tests: `test_email_invalido_devuelve_422` covers the documented 422 path

Result: FAILED
VERFAIL
VFOUT="$(python3 "$SELF/ddw/scripts/validate_verify.py" "$VFD/reports/verify-FEAT-001.md" \
        --tier FEATURE --prd "$VFD/prd/prd-FEAT-001.md" --spec "$VFD/specs/spec-FEAT-001.md" \
        2>/dev/null || true)"
case "$VFOUT" in
  *"❌ F-VER-01"*"AC-01"*"AC-02"*)
    ok "and an AC marked ❌ in the shape the skill teaches is read as failing, not as a passing verdict" ;;
  *) bad "every AC marked ❌ and F-VER-01 called it a passing verdict — the mark the skill mandates never matched" ;;
esac

# Which documents the verdict is checked AGAINST is chosen by whoever runs the
# validator, and nothing tied that choice to the ticket. Point `--prd` and
# `--spec` at a file with no AC bullets and no `## Block` headings and the run
# printed "all 0 AC", "all 0 spec block(s)", "all 0 test(s)" and PASSED — three
# green rules whose subject was empty, and a receipt for them.
VEMPTY="$WORK/verify-empty/docs/ddw"; mkdir -p "$VEMPTY/reports" "$VEMPTY/prd" "$VEMPTY/specs"
printf '# Nothing here\n\nA document with no acceptance criteria and no blocks.\n' \
  > "$VEMPTY/prd/prd-FEAT-009.md"
cp "$VEMPTY/prd/prd-FEAT-009.md" "$VEMPTY/specs/spec-FEAT-009.md"
cat > "$VEMPTY/reports/verify-FEAT-009.md" <<'VEREMPTY'
# Verification FEAT-009

| Field | Value |
|---|---|
| Line coverage | 94% |
| Branch coverage | 91% |
| Function coverage | 100% |
| Lint | `ruff check .` — clean |

## Tests
- Sad-path tests: `test_invalid` covers the documented 422 path

Result: PASSED
VEREMPTY
VEOUT="$(python3 "$SELF/ddw/scripts/validate_verify.py" "$VEMPTY/reports/verify-FEAT-009.md" \
        --tier FEATURE --prd "$VEMPTY/prd/prd-FEAT-009.md" \
        --spec "$VEMPTY/specs/spec-FEAT-009.md" 2>/dev/null || true)"
case "$VEOUT" in
  *"❌ F-VER-01"*"❌ F-VER-02"*)
    ok "a PRD with no criteria and a spec with no blocks are refused, not counted as all zero of them" ;;
  *) bad "\"all 0 AC\" and \"all 0 spec block(s)\" passed as a complete verdict — the rules were green over nothing" ;;
esac
python3 "$SELF/ddw/scripts/validate_verify.py" "$VEMPTY/reports/verify-FEAT-009.md" --tier FEATURE \
  --prd "$VP/docs/ddw/prd/prd-FEAT-001.md" --spec "$VS/spec-FEAT-001.md" >/dev/null 2>&1
[ "$?" = "3" ] \
  && ok "and a verdict cannot be checked against another ticket's documents" \
  || bad "FEAT-009's verdict was validated against FEAT-001's PRD and spec — the flags were untied from the ticket"

# ── The catalogued rules nothing had ever broken on purpose ──────────────────
#
# Eight rules across four validators were catalogued, implemented, and never
# exercised by a fixture that violates them: delete the line that finds the
# offence and the whole suite stayed green. Each case below takes the SOUND
# document, breaks exactly one thing, and asserts that rule ID appears with a ❌
# — and that the sound document does not carry it, which is what makes the
# fixture discriminating rather than merely red.
python3 - "$SELF" "$VP" "$VS" "$VTM" "$VRP" <<'PYRULES' && ok "eight catalogued rules — orphan FRs, unmeasurable NFRs, non-EARS criteria, uncovered FRs, untested ACs, unlisted trust boundaries, untreated threats, unmentioned criteria — each fail on a document that breaks them" || bad "a catalogued rule passes a document that violates it: the rule is implemented and nothing had ever broken it on purpose"
import os, re, subprocess, sys, tempfile
src, vp, vs, vtm, vrp = sys.argv[1:6]
PRD = os.path.join(vp, "docs/ddw/prd/prd-FEAT-001.md")
SPEC = os.path.join(vs, "spec-FEAT-001.md")
TM = os.path.join(vtm, "threat-FEAT-001.md")
VER = os.path.join(vrp, "verify-FEAT-001.md")
tmp = tempfile.mkdtemp(dir=os.environ["WORK"])


def run(script, path, *extra):
    return subprocess.run([sys.executable, os.path.join(src, "ddw/scripts", script), path,
                           "--tier", "FEATURE", *extra],
                          capture_output=True, text=True).stdout


def broken(base, fn, name):
    text = fn(open(base, encoding="utf-8").read())
    path = os.path.join(tmp, name)
    open(path, "w", encoding="utf-8").write(text)
    return path


VEXTRA = ("--prd", PRD, "--spec", SPEC)
CASES = [
    # rule, validator, sound doc, how to break it, extra args
    ("F-PRD-01", "validate_prd.py", PRD,
     lambda t: t.replace("- FR-01: El sistema debe exponer un formulario.",
                         "- FR-01: El sistema debe exponer un formulario.\n"
                         "- FR-02: El sistema debe enviar un correo."), ()),
    ("F-PRD-03", "validate_prd.py", PRD,
     lambda t: t.replace("- NFR-01: Carga en < 3 s p95.",
                         "- NFR-01: La carga debe ser rapida."), ()),
    ("F-PRD-09", "validate_prd.py", PRD,
     lambda t: t.replace("- AC-01 (FR-01): WHEN un usuario abre el formulario, "
                         "THE sistema SHALL mostrarlo.",
                         "- AC-01 (FR-01): el formulario se muestra correctamente."), ()),
    ("F-SPEC-01", "validate_spec.py", SPEC,
     lambda t: t.replace("FR-01", "FR-99"), ("--prd", PRD)),   # every mention: the rule reads the whole spec
    ("F-SPEC-02", "validate_spec.py", SPEC,
     lambda t: t.replace("- [ ] test_form_visible — validates AC-01",
                         "- [ ] test_form_visible — smoke"), ("--prd", PRD)),
    ("F-VER-01", "validate_verify.py", VER,
     lambda t: t.replace("- AC-01 — test_form_visible: PASSED", ""), VEXTRA),
]
for rule, script, base, fn, extra in CASES:
    sound = run(script, base, *extra)
    assert f"❌ {rule}" not in sound, \
        f"{rule} already fails on the SOUND document — the fixture proves nothing"
    out = run(script, broken(base, fn, f"{rule}.md"), *extra)
    assert f"❌ {rule}" in out, \
        f"{rule} passed a document that violates it:\n" + "\n".join(
            l for l in out.splitlines() if rule in l or "❌" in l)[:400]

# The threat model's two, which need the spec beside them.
TMEXTRA = ("--spec", SPEC)
sound_tm = run("validate_threat.py", TM, *TMEXTRA)
for rule, fn in (
    ("F-TM-02", lambda t: re.sub(r"(?m)^- .*$", "Prosa sin lista.",
                                 t[t.index("## Trust boundaries"):], count=3)
     if "## Trust boundaries" in t else t),
    # The last cell of a risk row IS the treatment. Emptying it is the shape the
    # rule looks for: a threat identified and then left with nothing said about it.
    ("F-TM-03", lambda t: t.replace("| R-01 | Spam masivo | D | High | Medium | rate limit + captcha |",
                                    "| R-01 | Spam masivo | D | High | Medium |  |")),
):
    if f"❌ {rule}" in sound_tm:
        continue                       # the sound fixture does not exercise it; not this check's job
    out = run("validate_threat.py", broken(TM, fn, f"{rule}.md"), *TMEXTRA)
    assert f"❌ {rule}" in out, f"{rule} passed a threat model that violates it"
PYRULES

# The three gates, driven through the hook — the thing that cannot be talked
# past. Same proof as the define gate's: shut without the receipt, open with it.
# The artifact is edited rather than deleted, because a missing file is not what
# these gates are about: a STALE receipt is.
#
# The loop variables are prefixed. `G` and `GATE` are the suite's own — the
# graph path and the hook path — and a bare `for G in …` here silently rebound
# both for every check that came after, which is a whole class of green turning
# red for reasons that have nothing to do with the code under test.
# The CODE->VERIFY rows land that edge, which now also demands the decisions
# record — a different gate than the one under test here, satisfied up front.
printf 'No decisions were approved outside the spec during this ticket.\n' \
  > "$VP/docs/ddw/specs/decisions-FEAT-001.md"
for RCP_ROW in spec:specs:spec:PLAN:CODE threat:security:threat:PLAN:CODE sast:security:sast:CODE:VERIFY tests:reports:tests:CODE:VERIFY verify:reports:verify:VERIFY:CLOSEOUT; do
  RCP_GATE="${RCP_ROW%%:*}"; RCP_REST="${RCP_ROW#*:}"
  RCP_DIR="${RCP_REST%%:*}"; RCP_REST="${RCP_REST#*:}"
  RCP_STEM="${RCP_REST%%:*}"; RCP_REST="${RCP_REST#*:}"
  RCP_FROM="${RCP_REST%%:*}"; RCP_TO="${RCP_REST##*:}"
  printf '\n<!-- edited after validating -->\n' >> "$VP/docs/ddw/$RCP_DIR/$RCP_STEM-FEAT-001.md"
  python3 - "$VP" "$RCP_GATE" "$RCP_FROM" "$RCP_TO" > "$VP/gev.json" <<'PYGATE'
import json, sys
root, gate, frm, to = sys.argv[1:5]
LADDER = ["define", "spec", "threat", "tests", "sast", "verify"]
EDGE_GATES = {"CODE": ["spec", "threat"], "VERIFY": ["tests", "sast"], "CLOSEOUT": ["verify"]}
EDGES = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN"),
         ("PLAN", "CODE"), ("CODE", "VERIFY"), ("VERIFY", "CLOSEOUT")]
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

# ── The receipt says which rules it was earned under ──────────────────────────
#
# `--tier` picks which rules run, and no validator constrained it or recorded
# it. So the same bytes could be judged by a shorter set of rules on request,
# and the receipt — named by a digest of the content alone — came out
# byte-identical either way. The gate, which knows the ticket's tier perfectly
# well, had nothing to compare against and opened.
#
# The tiers are read from the graph that defines them, so this cannot pass by
# agreeing with a list typed twice.
python3 - "$SELF" <<'PYTIERARG' && ok "every validator refuses a --tier the graph does not define" || bad "a validator accepts any --tier at all, and the tier is what decides which rules run"
import json, os, subprocess, sys
src = sys.argv[1]
tiers = sorted(json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"),
                              encoding="utf-8"))["tiers"])
assert tiers, "the graph defines no tiers, so this check has nothing to hold the validators to"
scripts = sorted(f for f in os.listdir(os.path.join(src, "ddw/scripts"))
                 if f.startswith("validate_") and f.endswith(".py"))
assert len(scripts) == 7, "expected the seven document validators, found: %s" % scripts
for name in scripts:
    path = os.path.join(src, "ddw/scripts", name)
    r = subprocess.run([sys.executable, path, os.devnull, "--tier", "WHATEVER"],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "WHATEVER" in (r.stdout + r.stderr), \
        "%s accepted `--tier WHATEVER`: any string at all selected the rules it runs" % name
    # …and it still accepts every tier that does exist. A flag constrained to
    # nothing is not a fix, it is the same gate shut a different way.
    for tier in tiers:
        r = subprocess.run([sys.executable, path, os.devnull, "--tier", tier],
                           capture_output=True, text=True)
        assert "invalid choice" not in (r.stdout + r.stderr), \
            "%s rejects `--tier %s`, which the graph defines" % (name, tier)
PYTIERARG

python3 - "$SELF" <<'PYTIERRCP' && ok "and a receipt earned under another tier does not open the gate" || bad "a document validated under QUICK-FIX rules opens a FEATURE's gate — the tier was decoration"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
prd_dir = os.path.join(repo, "docs", "ddw", "prd")
os.makedirs(prd_dir, exist_ok=True)
prd = os.path.join(prd_dir, "prd-T-1.md")
# The body the finding used: it FAILS as a FEATURE and PASSES as a QUICK-FIX,
# which is the whole point — one document, two verdicts, one receipt.
open(prd, "w", encoding="utf-8").write(
    "# PRD T-1\n\nbug: none. change: everything. regression test: none. risk: none.\n")
val = os.path.join(repo, ".ddw", "scripts", "validate_prd.py")
assert subprocess.run([sys.executable, val, prd, "--tier", "FEATURE"],
                      capture_output=True).returncode != 0, \
    "this PRD is supposed to fail FEATURE rules; the fixture no longer demonstrates anything"
assert subprocess.run([sys.executable, val, prd, "--tier", "QUICK-FIX"],
                      capture_output=True).returncode == 0, \
    "…and to pass QUICK-FIX rules, which is what makes the two receipts comparable"

sess = os.path.join(repo, ".ddw-sessions")
marker = os.path.join(sess, next(f for f in os.listdir(sess) if f.startswith("prd-validated-")))
assert "tier: QUICK-FIX" in open(marker, encoding="utf-8").read(), \
    "the receipt does not record which rules earned it, so nothing downstream can ask"

state_p = os.path.join(repo, ".ddw-state.json")
H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "tier": "FEATURE", "ticket": "T-1"}]
state = {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {}, "history": H}
open(state_p, "w", encoding="utf-8").write(json.dumps(state))
ev = json.dumps({"tool_name": "Write",
                 "tool_input": {"file_path": state_p,
                                "content": json.dumps(dict(state, gates={"define": True}))}})
r = subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/validate-transition.py"),
                    "--mode", "pre", "--state", state_p, "--repo", repo,
                    "--graph", os.path.join(repo, ".ddw/rules/transition-graph.json")],
                   input=ev, capture_output=True, text=True)
assert r.returncode == 2, "the define gate opened on a receipt earned under QUICK-FIX rules"
assert "QUICK-FIX" in (r.stdout + r.stderr) and "FEATURE" in (r.stdout + r.stderr), \
    "the refusal does not name both tiers, so it does not say what to re-run: " + \
    (r.stdout + r.stderr)[:200]

# A receipt written before validators recorded the tier has no line to compare,
# and refusing those would strand every ticket in flight at upgrade for a
# document that really was validated. It is honoured as it was.
open(marker, "w", encoding="utf-8").write("prd-T-1.md\n")
r = subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/validate-transition.py"),
                    "--mode", "pre", "--state", state_p, "--repo", repo,
                    "--graph", os.path.join(repo, ".ddw/rules/transition-graph.json")],
                   input=ev, capture_output=True, text=True)
assert r.returncode == 0, \
    "a pre-upgrade receipt, which records no tier, is now refused — every ticket in flight " \
    "at upgrade is stranded: " + (r.stdout + r.stderr)[:200]
PYTIERRCP

# ── The commit gate asks git, not the model ───────────────────────────────────
#
# Tracked changes only: untracked files are the build output and the scratch
# file of every real repository, and a closeout nobody can satisfy honestly is
# the one thing this repo holds to be worse than no gate at all.
CG="$WORK/commit-gate"; mkdir -p "$CG"; git -C "$CG" init -q .
git -C "$CG" config user.email ddw@example.com; git -C "$CG" config user.name DDW
# Signing off, like every other fixture that commits: a contributor with
# `commit.gpgsign` on globally has no key this fixture can reach, the base
# commit never lands, and the three checks below report a gate defect for a
# tree that was never committed in the first place.
git -C "$CG" config commit.gpgsign false
bash "$SELF/install.sh" "$CG" --target claude >/dev/null 2>&1
printf 'v1\n' > "$CG/src.txt"; git -C "$CG" add -A >/dev/null 2>&1
git -C "$CG" commit -qm base >/dev/null 2>&1
# And a fixture that failed to commit says so as itself, rather than handing the
# next three checks a tree they will describe as the gate's fault.
git -C "$CG" rev-parse --verify -q HEAD >/dev/null \
  && ok "the commit-gate fixture has a base commit to judge" \
  || bad "the commit-gate fixture never committed: the three checks below measure the fixture, not the gate"
CG_REL='{"tier":"FEATURE","phase":"CLOSEOUT","ticket":"FEAT-001","title":null,"tracker":null,"gates":{"define":true,"spec":true,"threat":true,"tests":true,"sast":true,"verify":true},"block":null,"discovery":null,"history":[{"timestamp":"2026-07-29T20:00:00Z","from":"IDLE","to":"CLASSIFY","action":"a"},{"timestamp":"2026-07-29T20:01:00Z","from":"CLASSIFY","to":"DEFINE","action":"b","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:02:00Z","from":"DEFINE","to":"PLAN","action":"c","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:03:00Z","from":"PLAN","to":"CODE","action":"d","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:04:00Z","from":"CODE","to":"VERIFY","action":"e","tier":"FEATURE","ticket":"FEAT-001"},{"timestamp":"2026-07-29T20:05:00Z","from":"VERIFY","to":"CLOSEOUT","action":"f","tier":"FEATURE","ticket":"FEAT-001"}]}'
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

# QUICK-FIX runs `sast` on CODE→CLOSEOUT and has no VERIFY at all. All three
# sentences in the SAST skill sent that reader to a phase their tier does not
# have, and the last one named a transition that does not exist for them.
SKQ="$SELF/skills/ddw-security-sast/SKILL.md"
! grep -q "advance to VERIFY\|advance to the VERIFY phase\|the CODE→VERIFY transition refuses" "$SKQ" \
  && grep -q "CLOSEOUT in QUICK-FIX" "$SKQ" \
  && ok "the SAST skill names the gate by the receipt it needs, not by a phase QUICK-FIX does not have" \
  || bad "the SAST skill sends a QUICK-FIX ticket to VERIFY — a phase its own tier does not have"

# `--ticket` has been a flag on transition.py all along. The CLASSIFY rules
# showed a command without it and then said the helper does not set the ticket,
# which left the one field every receipt resolves its document by to be
# hand-assembled in the write.
CLS="$SELF/ddw/rules/classify.instructions.md"
grep -q -- "--to DEFINE --tier <TIER> --ticket <ID>" "$CLS" \
  && ! grep -q "filling in \`ticket\`, \`title\` and \`tracker\`" "$CLS" \
  && ok "the CLASSIFY rules hand the ticket to the helper, which is where the helper has a flag for it" \
  || bad "the CLASSIFY rules still say the helper cannot set the ticket, against transition.py --ticket"

# And the same file judged by the gate it feeds, rather than by grep. Every
# command the CLASSIFY rules teach is a command a model copies verbatim, so a
# template the FSM refuses is a first ticket that cannot leave CLASSIFY — and
# the only thing a `grep -q -- "--title"` proves is that somebody typed the
# string into the document. `--title` went into the rules and into the gate in
# the same change; the mutation that took it back out of the rules survived,
# because nothing here had ever RUN what the rules say to run.
python3 - "$SELF" <<'PYCLSCMD' && ok "every transition.py command the CLASSIFY rules teach is accepted by the FSM those rules feed — the template a model copies is one its own gate takes" || bad "the CLASSIFY rules teach a command their own gate refuses: the first ticket of a new install cannot leave CLASSIFY"
import os, re, shlex, subprocess, sys, tempfile
src = sys.argv[1]
rules = open(os.path.join(src, "ddw/rules/classify.instructions.md"), encoding="utf-8").read()
helper = os.path.join(src, "ddw/scripts/transition.py")
graph = os.path.join(src, "ddw/rules/transition-graph.json")

# Continuation lines joined first: the command is what a reader copies, not the
# line it happens to be broken across.
body = re.sub(r"\\\n\s*", " ", rules)
cmds = [ln.strip() for ln in body.splitlines()
        if ".ddw/scripts/transition.py" in ln and not ln.lstrip().startswith("#")]
assert len(cmds) >= 3, "the CLASSIFY rules no longer show the commands they teach: %r" % cmds

FILL = {"<TIER>": "FEATURE", "<ID>": "T-1"}


def fill(tok):
    for k, v in FILL.items():
        tok = tok.replace(k, v)
    # Every other placeholder answered with its own prose — which is what a
    # reader does with `<the sentence in which they asked for it>`.
    return re.sub(r"<[^<>]+>", lambda m: m.group(0)[1:-1], tok)


for cmd in cmds:
    argv = [fill(a) for a in shlex.split(cmd)[1:]]
    d = tempfile.mkdtemp(dir=os.environ["WORK"])
    state = os.path.join(d, ".ddw-state.json")
    # A command that is not the entry into CLASSIFY needs the state to be
    # standing where the command starts. The ticket is seeded only when the
    # command itself names one — the arrows that carry no `--ticket` are the
    # arrows for work that has none.
    if argv[argv.index("--to") + 1] != "CLASSIFY":
        seed = ["--to", "CLASSIFY", "--action", "clasificar"]
        if "--ticket" in argv:
            seed += ["--ticket", "T-1"]
        r = subprocess.run([sys.executable, helper, *seed, "--state", state, "--graph", graph,
                            "--write"], capture_output=True, text=True, cwd=d)
        assert r.returncode == 0, "the fixture for %r could not be built: %s" % (cmd, r.stdout + r.stderr)
        # The context check the classify edge demands. The rules order it
        # written before the edge is taken; seeding it is standing where the
        # command starts, for a ticketed arrow and a ticketless one alike.
        os.makedirs(os.path.join(d, ".ddw-work"), exist_ok=True)
        for name in ("context-check-T-1.md", "context-check.md"):
            open(os.path.join(d, ".ddw-work", name), "w", encoding="utf-8").write(
                "Nothing to report.\n")
    r = subprocess.run([sys.executable, helper, *argv, "--state", state, "--graph", graph,
                        "--write"], capture_output=True, text=True, cwd=d)
    assert r.returncode == 0, \
        "the CLASSIFY rules teach a command the FSM refuses:\n  %s\n  %s" % (
            cmd, (r.stdout + r.stderr).strip().replace("\n", " ")[:300])
PYCLSCMD

# The document the model actually copies, judged by the rule that reads it.
# F-PRD-01 asks whether every FR is named inside some acceptance criterion, and
# the shipped template used to produce a PRD where none were — so the first
# document of every new install failed the gate it was written to pass. The fix
# lived entirely in the template, which nothing in this suite had ever read: a
# mutation for it existed and survived, because a template is only a defect
# once somebody validates it.
python3 - "$SELF" <<'PYTEMPLATE' && ok "the shipped PRD template names an FR in every acceptance criterion, so the first PRD of a new install passes F-PRD-01" || bad "the canonical PRD template cannot pass the define gate — every new install fails on the document DDW told it to write"
import re, sys, os
tpl = open(os.path.join(sys.argv[1], "skills/ddw-create-prd/SKILL.md"), encoding="utf-8").read()
frs = re.findall(r"^- (FR-\d+):", tpl, re.MULTILINE)
acs = re.findall(r"^- (AC-\d+)([^\n]*)", tpl, re.MULTILINE)
assert frs and acs, "the template no longer shows an FR and AC section to check"
# The rule's own arithmetic, over the template's own text.
ac_text = " ".join(t for _, t in acs)
orphans = [i for i in frs if i not in ac_text]
assert not orphans, \
    "the template writes %s with no acceptance criterion naming it: F-PRD-01 fails on the " \
    "first PRD of every install" % ", ".join(orphans)
unnamed = [i for i, t in acs if not re.search(r"\bFR-\d+\b", t)]
assert not unnamed, \
    "the template's %s name no FR, so a PRD copied from it reads as criteria validating " \
    "nothing" % ", ".join(unnamed)
PYTEMPLATE

# The same question asked of the whole document rather than one rule, in both
# directions — and both directions were wrong. A PRD written exactly as the
# template teaches was refused (`## Out of Scope` in prose against a rule that
# demands explicit items; an `AC-03 (FR-02): ...` whose ellipsis matches no EARS
# pattern), and the QUICK-FIX fix-brief was accepted with nothing written in it
# at all: the four labels were the whole test, so `**Bug**: {one descriptive
# line}` passed and wrote the receipt for the one gate that tier has before
# CODE.
python3 - "$SELF" <<'PYPRDSHAPE' && ok "a PRD and a fix-brief written the way ddw-create-prd teaches pass, and the same documents unwritten are refused" || bad "the PRD template is refused by its own gate, or an unfilled fix-brief earns the QUICK-FIX define gate"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
skill = open(os.path.join(src, "skills/ddw-create-prd/SKILL.md"), encoding="utf-8").read()
fenced = [m.group(1) for m in re.finditer(r"```markdown\n(.*?)```", skill, re.S)]
assert len(fenced) >= 2, "ddw-create-prd no longer carries both templates"
brief, prd = fenced[0], fenced[1]
d = tempfile.mkdtemp(dir=os.environ["WORK"])


def run(body, tier, name):
    path = os.path.join(d, name)
    open(path, "w", encoding="utf-8").write(body.replace("{ticket}", "T-1"))
    r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate_prd.py"),
                        path, "--tier", tier], capture_output=True, text=True, cwd=d)
    return r, [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]


# Filled the way anybody fills a template: every bracketed slot answered, the
# words the template itself supplies (WHEN … SHALL, the section names) kept.
filled = re.sub(r"\[[^\[\]]*\]", "the public form within 300 ms", prd)
r, refused = run(filled, "FEATURE", "prd-T-1.md")
assert r.returncode == 0 and not refused, (
    "validate_prd refuses a PRD written exactly as its own template teaches:\n" + "\n".join(refused))

# Refused, and refused FOR the placeholders. `returncode != 0` was the whole
# assertion here and it was satisfied by ONE unrelated rule: the raw template
# fails F-PRD-03 because its NFR carries no number, and that is all it failed.
# Fill in that single line and the twenty-line document of brackets came out
# `PASSED — 8 passed, 0 failed` with its receipt written. A check that passes
# because something else is broken is not checking what it says.
r, refused = run(prd, "FEATURE", "prd-T-2.md")
assert r.returncode != 0, "the PRD template passes unfilled — the placeholders are the document"
assert any("F-PRD-08" in ln and "placeholder" in ln for ln in refused), \
    "the unfilled template is refused, but not for being unfilled: " + "\n".join(refused)

# And with the one rule that was doing the work satisfied, so the placeholders
# are the only thing left to object to.
one_field = prd.replace("- NFR-01: [performance, security, etc. — always with a number]",
                        "- NFR-01: p95 under 200 ms.")
r, refused = run(one_field, "FEATURE", "prd-T-5.md")
assert r.returncode != 0, (
    "the shipped template with a single line filled in passes and earns the `define` receipt — "
    "a PRD whose problem, goals, requirements and criteria are all still `[like this]`")
assert any("placeholder" in ln for ln in refused), \
    "it is refused for something other than being unwritten: " + "\n".join(refused)

# The fix-brief, which is the whole of DEFINE under QUICK-FIX.
sessions = os.path.join(d, ".ddw-sessions")
before = set(os.listdir(sessions)) if os.path.isdir(sessions) else set()
r, refused = run(brief, "QUICK-FIX", "prd-T-3.md")
assert r.returncode != 0 and any("QUICK-FIX" in ln for ln in refused), (
    "the fix-brief passed with every field still `{like this}`: " + r.stdout[:300])
after = set(os.listdir(sessions)) if os.path.isdir(sessions) else set()
assert after == before, \
    "a receipt was written for a fix-brief that was refused: %s" % sorted(after - before)

filled_brief = re.sub(r"\{[^{}]*\}", "src/config/loader.ts:41 keeps the trailing newline",
                      brief).replace("[Title]", "the loader")
r, refused = run(filled_brief, "QUICK-FIX", "prd-T-4.md")
assert r.returncode == 0 and not refused, (
    "a fix-brief filled in as the template teaches is refused:\n" + "\n".join(refused))
PYPRDSHAPE

# The other two documents a phase writes had no canonical shape at all, so three
# plausible renderings of a complete run were refused for their LAYOUT: a
# coverage table whose rows are labelled `Line`, a lint result under its own
# heading, `sad-path` with the hyphen English actually uses, a failure named by
# test rather than by `path::test`. Each one read to the user as "your report is
# incomplete" about a report that was not. Both skills now carry the shape, and
# the shape is run through the validator that reads it.
python3 - "$SELF" <<'PYSHAPES' && ok "the test report and the verification verdict DDW ships as templates pass the validators that read them" || bad "the document a phase is told to write is refused by the gate it is written for"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]


def template(rel, after):
    text = open(os.path.join(src, rel), encoding="utf-8").read()
    at = text.index(after)
    m = re.search(r"```markdown\n(.*?)```", text[at:], re.S)
    assert m, "%s no longer carries a markdown template under %r" % (rel, after[:40])
    return m.group(1).replace("{ticket}", "T-1")


d = tempfile.mkdtemp(dir=os.environ["WORK"])
for sub in ("prd", "specs", "reports"):
    os.makedirs(os.path.join(d, "docs/ddw", sub))
open(os.path.join(d, "docs/ddw/prd/prd-T-1.md"), "w", encoding="utf-8").write(
    "# PRD T-1\n\n## Functional Requirements\n- FR-01: el formulario publico\n"
    "- FR-02: la persistencia\n\n## Acceptance Criteria\n"
    "- AC-01 (FR-01): WHEN el usuario abre la pagina, THE sistema SHALL mostrar el formulario.\n"
    "- AC-02 (FR-01): IF falta un campo, THEN THE sistema SHALL devolver 400.\n"
    "- AC-03 (FR-02): WHEN el email es invalido, THE sistema SHALL devolver 422.\n")
open(os.path.join(d, "docs/ddw/specs/spec-T-1.md"), "w", encoding="utf-8").write(
    "# Spec T-1\n\n| Field | Value |\n|---|---|\n| Ticket | T-1 |\n\n"
    "## Block 1 — Formulario publico\n\n**Required tests**\n"
    "- [ ] test_form_visible — validates AC-01\n"
    "- [ ] test_campo_faltante_devuelve_400 — validates AC-02\n"
    "- [ ] test_email_invalido_devuelve_422 — validates AC-03\n")

for skill, after, validator, doc in (
        ("skills/ddw-test/SKILL.md", "### The report, in the shape the validator reads",
         "validate_tests.py", "docs/ddw/reports/tests-T-1.md"),
        ("skills/ddw-verify-module/SKILL.md", "### The verdict document, in the shape the validator reads",
         "validate_verify.py", "docs/ddw/reports/verify-T-1.md")):
    path = os.path.join(d, doc)
    open(path, "w", encoding="utf-8").write(template(skill, after))
    r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts", validator), path,
                        "--tier", "FEATURE"], capture_output=True, text=True, cwd=d)
    # The rule ROWS, which start with the marker. The footer that tells the user
    # to paste every "✅ / ⚠️ / ❌" contains all three symbols and is on every
    # run: matched anywhere in the line, this check could never pass.
    refused = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]
    assert r.returncode == 0 and not refused, (
        "%s refuses the template %s tells the model to write:\n%s"
        % (validator, os.path.basename(os.path.dirname(skill)), "\n".join(refused[:4]) or r.stderr[-200:]))
PYSHAPES

# The third document with the same defect, and the last one that had no worked
# shape: a fix-plan written exactly as the FIX template teaches was refused by
# F-SPEC-10 for its layout. The template put the error handling in prose; the
# validator counts errors as a list, because F-SPEC-16 pairs each one with the
# test that names it, and prose counts as none. The user's reading was "your
# plan documents no error handling" about a plan that documented it.
python3 - "$SELF" <<'PYFIXPLAN' && ok "a fix-plan written the way ddw-create-spec teaches passes validate_spec --tier FIX" || bad "the fix-plan template and the validator that reads it disagree about what documented error handling looks like"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
skill = os.path.join(src, "skills/ddw-create-spec/SKILL.md")
text = open(skill, encoding="utf-8").read()

# The skeleton has to TEACH the shape, not only carry a worked copy of it: the
# errors are a list, and the one below is what a reader copies.
at = text.index("## Fix-Plan Template (FIX) — canonical")
skeleton = re.search(r"```markdown\n(.*?)```", text[at:], re.S)
assert skeleton, "the canonical fix-plan template is gone"
errors = re.search(r"^## Error handling\n(.*?)(?=^## |\Z)", skeleton.group(1), re.S | re.M)
assert errors and re.search(r"^\s*[-*]\s+\S", errors.group(1), re.M), \
    ("the canonical fix-plan template writes its error handling as prose; the validator counts "
     "errors as a list and reads prose as none: " + (errors.group(1) if errors else "no section")[:160])

at = text.index("### The fix-plan, in the shape the validator reads")
m = re.search(r"```markdown\n(.*?)```", text[at:], re.S)
assert m, "ddw-create-spec no longer carries a worked fix-plan"
d = tempfile.mkdtemp(dir=os.environ["WORK"])
os.makedirs(os.path.join(d, "docs/ddw/specs"))
path = os.path.join(d, "docs/ddw/specs/spec-T-9.md")
open(path, "w", encoding="utf-8").write(m.group(1).replace("{ticket}", "T-9"))
r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate_spec.py"), path,
                    "--tier", "FIX"], capture_output=True, text=True, cwd=d)
refused = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]
assert r.returncode == 0 and not refused, (
    "validate_spec refuses the fix-plan ddw-create-spec tells the model to write:\n"
    + ("\n".join(refused[:4]) or r.stderr[-200:]))
PYFIXPLAN

# The FEATURE spec had the same defect one document over, and it was the last
# worked shape missing: the first live FEATURE run wrote a spec from the
# skeleton alone and was refused by F-SPEC-07, F-SPEC-09 and F-SPEC-16 — and
# the model's way out was READING THE VALIDATOR'S SOURCE to learn what shape
# the parser wanted. Knowledge that lives in the parser is knowledge the
# template failed to teach. The skill now carries a worked FEATURE spec, and
# this runs it against the validator that reads it, with the minimal PRD its
# coverage table names.
python3 - "$SELF" <<'PYFEATSPEC' && ok "a FEATURE spec written the way ddw-create-spec teaches passes validate_spec --tier FEATURE" || bad "the FEATURE spec template and the validator that reads it disagree — the model's way out is reading the parser again"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
skill = os.path.join(src, "skills/ddw-create-spec/SKILL.md")
text = open(skill, encoding="utf-8").read()
at = text.index("### The spec, in the shape the validator reads")
m = re.search(r"```markdown\n(.*?)```", text[at:], re.S)
assert m, "ddw-create-spec no longer carries a worked FEATURE spec"
d = tempfile.mkdtemp(dir=os.environ["WORK"])
os.makedirs(os.path.join(d, "docs/ddw/specs"))
os.makedirs(os.path.join(d, "docs/ddw/prd"))
open(os.path.join(d, "docs/ddw/prd/prd-T-9.md"), "w", encoding="utf-8").write(
    "# PRD T-9\n\n- **FR-01**: el formulario publico da de alta un ticket.\n"
    "- **NFR-01**: p95 bajo 3 s.\n"
    "- **AC-01**: WHEN se envia el formulario THEN se devuelve el id.\n")
path = os.path.join(d, "docs/ddw/specs/spec-T-9.md")
open(path, "w", encoding="utf-8").write(m.group(1).replace("{ticket}", "T-9"))
r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate_spec.py"), path,
                    "--tier", "FEATURE"], capture_output=True, text=True, cwd=d)
refused = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]
assert r.returncode == 0 and not refused, (
    "validate_spec refuses the FEATURE spec ddw-create-spec tells the model to write:\n"
    + ("\n".join(refused[:4]) or r.stderr[-200:]))
PYFEATSPEC

# CLASSIFY's ticket intake was a chain of questions — "is there a ticket?",
# "do you want me to propose one?", "shall we use the internal one?" — three
# interruptions before the confirmation box asked a fourth, measured on a live
# run. The consolidated protocol lives in TWO files (the phase's steps and the
# tracker convention), so each is held to it separately: the one that drifts
# back to the chain is the one a model reads that day.
CLS2="$SELF/ddw/rules/classify.instructions.md"
TRK2="$SELF/ddw/rules/tracker.instructions.md"
grep -q "never in a chain of questions before it" "$CLS2" \
  && ! grep -q "Do you want me to propose a tracker ticket for this?" "$CLS2" \
  && grep -q "answer with its ID and I will" "$CLS2" \
  && ok "the CLASSIFY rules resolve the ticket in one stop, inside the box that confirms the classification" \
  || bad "the CLASSIFY rules ask about the ticket in a chain of questions again — four interruptions to start one ticket"
grep -q "One stop, not a chain." "$TRK2" \
  && ! grep -q "Do you want me to propose one so you can file it later?" "$TRK2" \
  && ok "the tracker convention agrees: the ticket is one stop, and filing text is CLOSEOUT's offer" \
  || bad "the tracker convention re-grew its question chain, contradicting the CLASSIFY rules it feeds"

# A backward edge under `assisted` used to be taken first and explained after:
# measured live, the helper took PLAN→DEFINE and then asked which stack should
# prevail — into a phase already re-entered and a gate already spent, when the
# answer could have been "neither". The doctrine lives in state (the FSM's
# reference) and in plan (the phase that loops most); both have to say
# question-first or the one a model reads is the one that transitions first.
ST2="$SELF/ddw/rules/state.instructions.md"
PLN2="$SELF/ddw/rules/plan.instructions.md"
grep -q "the question comes BEFORE the edge" "$ST2" \
  && ! grep -q "And taking one is not a question" "$ST2" \
  && ok "the state rules take a backward edge WITH the user's answer in hand, not before it" \
  || bad "the state rules take the backward edge first and ask after — the user answers into a gate already spent"
grep -q "put the motivating question FIRST" "$PLN2" \
  && grep -q "before step 2 takes the loop" "$PLN2" \
  && ok "the PLAN corrective loop asks the motivating question before taking the edge" \
  || bad "the PLAN corrective loop transitions before the user has answered the question that motivates it"

# W-PRD-06 says "legitimate if it was decided" and names the user as the one
# who decides — and a live run watched the model decide instead: 17 ACs, the
# warning shown verbatim, self-judged "does not block" in the next sentence,
# and approval requested as if the report were clean. The DEFINE steps now bind
# the warning to the Scope Check box.
DEF2="$SELF/ddw/rules/define.instructions.md"
grep -q "A ⚠️ W-PRD-06 in the report you just showed IS this" "$DEF2" \
  && grep -q "W-PRD-06 in the validation report means it is" "$DEF2" \
  && ok "a W-PRD-06 warning routes to the Scope Check box: the scope decision is the user's, not the model's" \
  || bad "W-PRD-06 is a warning the model may wave through again — the scope decision nobody made"

# The threat gate was decorative for anyone who did what the skill says. The
# canonical threat model — every field a bracketed placeholder — passed all
# seven rules and wrote the receipt that opens PLAN→CODE: six STRIDE labels with
# `[analysis]` after each counted as full coverage, `**Accepted by:** [who]`
# counted as an approval, `[PII / credentials / financial / public]` counted as
# a classification AND as the PII that then had to be encrypted, which the
# `[control]` columns paid for. Change `path/to/file.py` to a real file and the
# document passed. Every other validator here drops bracketed placeholders on
# purpose; this one, the only one nobody had ever audited, had no such notion.
python3 - "$SELF" <<'PYTHREAT' && ok "an unfilled threat model is refused, the worked one passes, and the encryption rule reads what the document actually says" || bad "a threat model copied from the template and never written earns the gate that stands between PLAN and CODE"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
skill = open(os.path.join(src, "skills/ddw-threat-modeling/SKILL.md"), encoding="utf-8").read()


def template(after, ticket):
    at = skill.index(after)
    m = re.search(r"```markdown\n(.*?)```", skill[at:], re.S)
    assert m, "ddw-threat-modeling no longer carries a template under %r" % after[:40]
    return m.group(1).replace("{ticket}", ticket)


d = tempfile.mkdtemp(dir=os.environ["WORK"])
os.makedirs(os.path.join(d, "docs/ddw/security"))
os.makedirs(os.path.join(d, "docs/ddw/specs"))
SPEC = ("# Spec T-1\n\n| Field | Value |\n|---|---|\n| Ticket | T-1 |\n\n"
        "## Block 1 — Password login\n- `src/auth/login.ts` — validates credentials\n"
        "- POST /api/login\nCovers FR-01.\n")
spec = os.path.join(d, "docs/ddw/specs/spec-T-1.md")
open(spec, "w", encoding="utf-8").write(SPEC)


def run(body, name="T-1"):
    path = os.path.join(d, "docs/ddw/security/threat-%s.md" % name)
    open(path, "w", encoding="utf-8").write(body)
    r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts/validate_threat.py"),
                        path, "--tier", "FEATURE", "--spec", spec],
                       capture_output=True, text=True, cwd=d)
    return r, [ln for ln in r.stdout.splitlines() if ln.strip().startswith("❌")]


# 1. The skeleton, with only the component renamed to a file the spec names —
#    the one edit that used to be enough.
skeleton = template("### Threat model template — canonical", "T-1").replace("path/to/file.py", "src/auth/login.ts")
r, refused = run(skeleton)
assert r.returncode != 0, "the unfilled threat model passed and earned its receipt"
for rule in ("F-TM-01", "F-TM-02", "F-TM-04", "F-TM-05"):
    assert any(rule in ln for ln in refused), \
        "%s accepted the template's placeholders: %s" % (rule, "\n".join(refused))
assert not os.path.exists(os.path.join(d, ".ddw-sessions")) or not [
    f for f in os.listdir(os.path.join(d, ".ddw-sessions")) if f.startswith("threat-")], \
    "a receipt was written for a document that was refused"

# 2. …and the worked one, which is what the skill now carries, passes whole.
worked = template("### The threat model, in the shape the validator reads", "T-1")
r, refused = run(worked)
assert r.returncode == 0 and not refused, (
    "validate_threat refuses the threat model ddw-threat-modeling tells the model to write:\n"
    + ("\n".join(refused[:4]) or r.stderr[-200:]))

# 3. The encryption rule read two sections only, so a model declaring its
#    controls under `## Encryption` — the obvious heading — was told it had
#    none. And it matched the words anywhere, so a sentence DENYING the control
#    satisfied the rule it contradicts.
plain = worked.replace("| Data | Class | At rest | In transit |\n|---|---|---|---|", "| Data | Class |\n|---|---|")
plain = re.sub(r"^\| (password|session token|email) \| ([^|]+) \|.*$",
               lambda m: "| %s | %s |" % (m.group(1), m.group(2).strip()), plain, flags=re.M)
r, refused = run(plain + "\n## Encryption\nEverything above is encrypted at rest and travels over TLS.\n", "T-2")
assert r.returncode == 0, \
    "a model that states its encryption under its own heading is refused for having none: " + \
    "\n".join(refused)
r, refused = run(plain + "\n## Encryption\nWe do not encrypt at rest, and nothing uses TLS.\n", "T-3")
assert any("F-TM-07" in ln for ln in refused), \
    "a sentence denying the control satisfied the rule that demands it"

# 4. A category answered for by a word inside somebody else's sentence. `dos\b`
#    carried no boundary in front of it, so "parametros ligados" credited the
#    model with a denial-of-service analysis it does not contain — and the
#    label, not a word anywhere in the line, is what names a category.
dropped = re.sub(r"^- \*\*Denial of Service:.*$", "- **Tampering (continued):** parametros ligados.",
                 worked, flags=re.M)
r, refused = run(dropped, "T-4")
assert any("F-TM-01" in ln and "Denial of Service" in ln for ln in refused), \
    ("a model with no denial-of-service analysis passed because another line ends in `dos`: "
     + "\n".join(refused))

# 5. And the general case the boundary above is one instance of: the category's
#    own word, spelled out, inside a line that is about something else. What
#    names a category is the LABEL — the position, not the presence. Here the
#    Spoofing analysis is deleted and the word "spoofing" is left in the middle
#    of the Tampering sentence, which is how it reads in a document somebody
#    actually wrote. Matched anywhere in the line, that sentence answers for a
#    category nobody analysed, and what comes back as "the analysis" is the tail
#    of a sentence about validation.
_spoof = re.search(r"^- \*\*Spoofing:\*\*.*$", worked, re.M)
_tamper = re.search(r"^- \*\*Tampering:\*\*.*$", worked, re.M)
assert _spoof and _tamper, "the template's STRIDE lines are not shaped as this probe expects"
elsewhere = worked.replace(_spoof.group(0) + "\n", "", 1)
elsewhere = elsewhere.replace(
    _tamper.group(0),
    _tamper.group(0).rstrip(". ") + "; no hay spoofing posible sin identidad propia.", 1)
assert "spoofing" in elsewhere and _spoof.group(0) not in elsewhere, \
    "the probe did not plant the case it is about"
r, refused = run(elsewhere, "T-5")
assert any("F-TM-01" in ln and "Spoofing" in ln for ln in refused), \
    ("a category answered for by its own word inside another category's sentence: "
     + "\n".join(refused))
PYTHREAT

# A plugin install writes NOTHING into the repo, so it leaves no AGENTS.md — and
# AGENTS.md is where the stack is read from. CLASSIFY had two branches, both
# assuming the file exists, so the third case (the ordinary one under a plugin)
# fell into "fill in the Stack section of AGENTS.md and we start over", naming a
# file that is not there. The way out has to be written down where the model
# rereads it, and it has to say what must NOT go in: under a plugin the repo
# comes away with nothing of DDW's in it.
CLSF="$SELF/ddw/rules/classify.instructions.md"
grep -q "does not exist at all" "$CLSF" \
  && grep -q "no activation block, no phase references, no template boilerplate" "$CLSF" \
  && grep -q "no \`AGENTS.md\` is created either" -i "$SELF/docs/INSTALL.md" \
  && ok "the rules cover a repo with no context file at all — the ordinary state of a plugin install" \
  || bad "CLASSIFY sends a plugin user to fill in a file that does not exist, and no document names the third case"

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

# A worktree is a repository whose `.git` is a FILE, and the root walk asked
# whether it was a directory. The layout the boot itself recommends — `git
# worktree add ../<repo>-<TICKET>` — could not resolve a root at all, and a
# worktree nested inside another checkout resolved to the ENCLOSING repo, so the
# ticket's state landed beside somebody else's.
python3 - "$SELF" <<'PYWORKTREE' && ok "a git worktree resolves to its own root, so the ticket's state lands in the checkout the ticket is in" || bad "the state file lands in the enclosing repository, or the helper cannot find a root at all — in the layout DDW itself recommends"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
main = os.path.join(work, "main")
os.makedirs(main)
env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
run = lambda *a, **kw: subprocess.run(list(a), capture_output=True, text=True, env=env, **kw)
run("git", "-C", main, "init", "-q")
for k, v in (("user.email", "ddw@test"), ("user.name", "ddw"), ("commit.gpgsign", "false")):
    run("git", "-C", main, "config", k, v)
open(os.path.join(main, "README.md"), "w", encoding="utf-8").write("x\n")
run("git", "-C", main, "add", "-A")
run("git", "-C", main, "commit", "-qm", "base")
sibling = os.path.join(work, "main-T-1")
r = run("git", "-C", main, "worktree", "add", "-q", sibling, "-b", "feat/T-1")
assert os.path.isfile(os.path.join(sibling, ".git")), \
    "this git does not make .git a file in a worktree, so the case cannot be exercised: " + r.stderr[:150]
helper = os.path.join(src, "ddw/scripts/transition.py")
graph = os.path.join(src, "ddw/rules/transition-graph.json")
r = run(sys.executable, helper, "--to", "CLASSIFY", "--action", "start", "--graph", graph,
        "--write", cwd=sibling)
assert r.returncode == 0, "the helper could not resolve a root inside a worktree: " + (r.stdout + r.stderr)[:200]
assert os.path.exists(os.path.join(sibling, ".ddw-state.json")), \
    "the worktree's own root was skipped"
assert not os.path.exists(os.path.join(main, ".ddw-state.json")), \
    "the state landed in the main checkout, not in the worktree the work is in"
PYWORKTREE

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
d = tempfile.mkdtemp(dir=os.environ["WORK"]); subprocess.run(["git", "-C", d, "init", "-q"], check=True)
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
python3 - "$SELF" "$WORK" <<'PYMATCH' && ok "and Copilot's matcher-less hook is a known reason that has to hold" || bad "Copilot's hook config changed shape — recheck what reaches the gate"
import json, os, subprocess, sys
# Read the wiring the INSTALLER writes, by running it — there is no longer a
# manifest checked into the repo to read instead, and there must not be: a
# repo-level Copilot manifest is not read in `copilot -p`.
root, work = sys.argv[1], sys.argv[2]
home = os.path.join(work, "copilot-matcher-home")
os.makedirs(home, exist_ok=True)
subprocess.run([sys.executable, os.path.join(root, "adapters/copilot/wire-user-hooks.py"), ""],
               env=dict(os.environ, HOME=home), check=True, capture_output=True)
d = json.load(open(os.path.join(home, ".copilot/hooks/ddw.json"), encoding="utf-8"))
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
json.dump({"phase": "CLOSEOUT", "tier": "FEATURE", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                        "to": "CLOSEOUT", "action": "forged"}]},
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

# ── Copilot: the gates ride USER-LEVEL hooks, in both install modes ──────────
#
# Copilot installs Claude-format plugins (skills included) and ignores their
# Claude-format hooks manifest — measured live: a forged state sailed through.
# Its channel is user-level hooks pointing at the method, so the hook scripts
# resolve repo-first, plugin-root second.
#
# And user level rather than the repo, because Copilot loads REPOSITORY hooks
# only in a folder the user has trusted — GitHub's reference says policy hooks
# work "regardless of folder trust state", which is the only place it says the
# others do not. Trust is answered in a dialog `-p` cannot show. Measured with
# `trustedFolders` as the only variable: trusted, the hooks ran and the write
# was refused; not trusted, zero ran and the file was written. The repo a
# developer opens interactively is trusted and enforces; the same repo on CI is
# not, and does not.
#
# There is no stand-down any more, and this section is where that is held. It
# used to read: the user-level copy keeps quiet where the repo wires its own
# hook. That was right only while a repo-level manifest existed to take over.
# DDW writes none, so a copy that stepped aside for a repo hook would be
# stepping aside for nothing. Standing down HERE means enforcing nowhere.
section "Copilot: user-level hooks enforce, and never step aside for a repo hook"

CPP="$WORK/cp-plugin"; mkdir -p "$CPP"
cp -r "$SELF/ddw" "$CPP/ddw"
CPR="$WORK/cp-repo"; mkdir -p "$CPR"; git -C "$CPR" init -q . >/dev/null 2>&1 || true
CPEV="$(python3 - "$CPR" <<'PY'
import json, os, sys
state = json.dumps({"phase": "CLOSEOUT", "tier": "FEATURE", "gates": {},
                    "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                                 "to": "CLOSEOUT", "action": "forged"}]})
args = json.dumps({"path": os.path.join(sys.argv[1], ".ddw-state.json"), "content": state})
print(json.dumps({"toolName": "create", "toolArgs": args}))
PY
)"
( cd "$CPR" && printf '%s' "$CPEV" | DDW_PLUGIN_ROOT="$CPP" bash "$SELF/adapters/copilot/scripts/pre-tool-use.sh" >/dev/null 2>&1 )
[ "$?" = "2" ] \
  && ok "Copilot user-level hook enforces with no .ddw/ in the repo (method from the plugin root)" \
  || bad "Copilot as a plugin loads skills and enforces NOTHING — the drop-in-only resolution is back"

# The drop-in repo, seen by a machine wired for the plugin. The repo carries the
# scripts and NO manifest of its own, so this copy is the only thing that can
# judge the write. The old stand-down fired exactly here.
mkdir -p "$CPR/.github/hooks/ddw" && : > "$CPR/.github/hooks/ddw/pre-tool-use.sh"
( cd "$CPR" && printf '%s' "$CPEV" | DDW_PLUGIN_ROOT="$CPP" bash "$SELF/adapters/copilot/scripts/pre-tool-use.sh" >/dev/null 2>&1 )
[ "$?" = "2" ] \
  && ok "and still enforces in a repo carrying its own hook scripts — no stand-down, because nothing would take over" \
  || bad "the user-level hook stands down for a repo hook that `copilot -p` never runs — the gates are back to enforcing nothing"

# And the repo-level manifest is not written by anything, on any path. It is the
# file whose presence made the drop-in look gated while `copilot -p` wrote
# whatever it liked.
# Asked of the `wiring` list and not of the file's text: the recipe explains
# this decision in a `hooks_note` that necessarily QUOTES the path, so a grep
# over the file finds its own explanation and reports the defect it exists to
# prevent. A check has to read the thing that acts, not the prose beside it.
python3 - "$SELF" <<'PYNOMANIFEST' && ok "the Copilot recipe wires no repo-level manifest: the scripts land in the repo, the wiring does not" || bad "the Copilot recipe wires a repo-level hooks manifest again — unread in a folder nobody trusted"
import json, sys
d = json.load(open(sys.argv[1] + "/adapters/copilot/adapter.json", encoding="utf-8"))
for w in d.get("wiring") or []:
    assert w.get("from") != "hooks", \
        "the recipe copies a hooks manifest into the repo; Copilot reads one only where the "\
        "folder is trusted, and `-p` cannot ask for trust"
assert "hooks_note" in d, "the recipe is silent about why it wires no manifest — the next person restores it"
PYNOMANIFEST

# The post net has to hold the same line. The check above exercises the pre
# hook, and a stand-down restored in `post-write.sh` alone would pass it while
# every shell-written state went unjudged — which is the one thing the post net
# exists for.
#
# Two things this check had to be taught, and both are the difference between
# measuring the stand-down and measuring something else:
#
#   Post mode reads the DISK, not the event, so the forged state has to be
#   there — above, the pre hook refused the write and left no file behind.
#
#   And the verdict is not an exit code. GitHub documents Copilot's postToolUse
#   as unable to refuse: a non-zero exit is "logged and skipped". DDW answers it
#   in `additionalContext` instead, which the model heeds. So what separates a
#   net that ran from one that stood down is whether the finding is IN that
#   answer — a stand-down prints a bare `{}` and exits 0, and asking the exit
#   code calls both of them the same thing.
python3 - "$CPR" <<'PYCPPOST'
import json, sys
json.dump({"phase": "CLOSEOUT", "tier": "FEATURE", "ticket": "T-1", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                        "to": "CLOSEOUT", "action": "forged"}]},
          open(sys.argv[1] + "/.ddw-state.json", "w"))
PYCPPOST
: > "$CPR/.github/hooks/ddw/post-write.sh"
CPPOST="$( cd "$CPR" && echo '{}' | DDW_PLUGIN_ROOT="$CPP" bash "$SELF/adapters/copilot/scripts/post-write.sh" 2>/dev/null )"
case "$CPPOST" in
  *ILLEGAL*additionalContext*|*additionalContext*ILLEGAL*)
    ok "and the post net does too — it is the half that catches a state written through the shell" ;;
  *) bad "Copilot's post net stands down for a repo hook that never runs; a forged state through the shell is unjudged" ;;
esac
rm -f "$CPR/.ddw-state.json"

CPHOME="$WORK/copilot-level-home"; mkdir -p "$CPHOME"
HOME="$CPHOME" python3 "$SELF/adapters/copilot/wire-user-hooks.py" "" >/dev/null 2>&1
python3 - "$CPHOME" <<'PYLEVEL' && ok "the drop-in wiring runs each repo's own hook, and a refusal stays a refusal" || bad "the user-level wrapper turns a Copilot deny into an allow — see above"
import json, os, sys
d = json.load(open(os.path.join(sys.argv[1], ".copilot/hooks/ddw.json"), encoding="utf-8"))
for event, hooks in d["hooks"].items():
    for h in hooks:
        cmd = h["bash"]
        assert cmd.startswith("if [ -f "), f"{event}: not the guarded spelling: {cmd}"
        # `[ -f x ] && bash x || echo '{}'` is the spelling that must never come
        # back: the gate exits 2, `||` catches it, `echo` exits 0, and Copilot
        # reads 0 as allow. Every refusal becomes permission while the install
        # still reports the gates as wired.
        assert "||" not in cmd, f"{event}: the `||` wrapper converts every deny into an allow: {cmd}"
        assert "exec bash" in cmd, f"{event}: the hook's exit code is not the wrapper's: {cmd}"
PYLEVEL

# And the drop-in ACTUALLY wires it. Everything above judges the recipe, the
# scripts and the wiring script; none of it notices `install.sh` never calling
# the last one. That was the whole defect — for as long as it existed, the
# drop-in shipped the scripts, printed a green install, and wired nothing that
# an untrusted folder would ever read.
DIH="$WORK/copilot-dropin-home"; DIR2="$WORK/copilot-dropin-repo"
mkdir -p "$DIH" "$DIR2"; git -C "$DIR2" init -q .
git -C "$DIR2" config user.email e@example.com; git -C "$DIR2" config user.name e
git -C "$DIR2" config commit.gpgsign false
echo "# fixture" > "$DIR2/README.md"
git -C "$DIR2" add -A >/dev/null 2>&1; git -C "$DIR2" commit -qm init >/dev/null 2>&1
HOME="$DIH" DDW_GIT_FLOW=none bash "$SELF/install.sh" "$DIR2" --target copilot >/dev/null 2>&1
[ -f "$DIH/.copilot/hooks/ddw.json" ] \
  && ok "a drop-in install for Copilot wires the gates at user level, where an untrusted folder still reads them" \
  || bad "the drop-in installs Copilot and wires no user-level hooks — a fresh clone enforces nothing and says it is installed"
[ -f "$DIR2/.github/hooks/ddw/pre-tool-use.sh" ] && [ ! -f "$DIR2/.github/hooks/ddw.json" ] \
  && ok "and it leaves the scripts in the repo with no manifest beside them — one wiring, not two" \
  || bad "the drop-in wrote a repo-level manifest, or no scripts at all"

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

# The agent-driven installer must RUN the adapter's wiring script, not retype
# its JSON. Two things about that JSON look right and are wrong — the level and
# the wrapper — and both were live defects. A document that shows the shape
# invites a transcription; one that shows a command does not.
grep -q "wire-user-hooks.py" "$SELF/.github/INSTALL.md" \
  && ok "the Copilot installer runs the adapter's wiring script rather than dictating JSON to retype" \
  || bad "the Copilot installer is back to hand-written hook JSON — the level and the wrapper are both retypeable wrong"

grep -q "Repository hooks load only in a folder the" "$SELF/.github/INSTALL.md" \
  && ok "and it says WHY user level: repository hooks need a trusted folder, and \`-p\` cannot ask for trust" \
  || bad "the Copilot doc no longer names folder trust; the next person wires the gates where a fresh clone never runs them"

grep -q "delete \`~/.copilot/hooks/ddw.json\`" "$SELF/.github/INSTALL.md" \
  && ok "and its uninstall names the file to remove — orphaned hooks pointing at a deleted plugin gate nothing" \
  || bad "the Copilot uninstall no longer says what to remove; the wiring outlives the plugin it points at"

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

# Initialized, and it is not a style detail: this file runs with `set -u`, so
# the first time one of the nine was missing the line below killed bash on the
# spot — `MISSING_FRONT: unbound variable`, exit 1, and EVERYTHING that follows
# never ran. The fault that deletes `CODE_OF_CONDUCT.md` counted as caught
# without a single check having spoken, and the five that did have something to
# say about it never got to say it. A kill by crash is not a kill.
MISSING_FRONT=""
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

# The commit a pull request is actually tested on is one GitHub fabricates —
# `refs/pull/N/merge`, authored by GitHub, carrying no trailer, never landing in
# anyone's history. Held to the rule, it fails every pull request forever, over a
# commit nobody wrote. Found the first time this check ever ran on a real one.
git -C "$CM" checkout -q -b cm-branch
echo merged > "$CM/b.txt"; git -C "$CM" add -A
git -C "$CM" commit -q -F - <<'CMEOF'
✨ work on the branch

AI-assisted: yes
CMEOF
git -C "$CM" checkout -q main
git -C "$CM" merge -q --no-ff cm-branch -m "Merge cm-branch into main" >/dev/null 2>&1
python3 "$SELF/scripts/check_commits.py" --repo "$CM" --since "$CM_BASE" >/dev/null 2>&1 \
  && ok "the merge commit a pull request is tested on is not held to a rule about authorship" \
  || bad "every pull request fails on GitHub's own merge commit — a rule applied to a commit nobody wrote"
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

# The required status contexts are the JOB names, not the steps inside them. So a
# pull request that deletes the two lines that actually run the suite and the
# linter keeps every context green — all fifteen — and with zero required
# approvals it merges itself. What protects main has to be the CONTENT of the
# job, and nothing was checking it.
LOADBEARING = ("scripts/verify_install.sh", "scripts/lint_method.py",
               "scripts/check_versions.py", "scripts/lint_kill_map.py")
for needle in LOADBEARING:
    owning = [s for s in steps if needle in str(s.get("run", ""))]
    assert owning, f"verify.yml no longer runs {needle} — the job name stays green either way"
    for s in owning:
        assert not s.get("continue-on-error"), f"{needle} runs with continue-on-error"
        assert "|| true" not in str(s.get("run", "")), f"{needle}'s failure is swallowed by || true"
# The suite's own dependency, which used to be skipped in silence: two plugin
# manifests had never been validated against the real schema in CI, because the
# CLI that does it was not installed and a skip counted as a pass.
assert any("@anthropic-ai/claude-code" in str(s.get("run", "")) for s in steps), \
    "CI does not install the CLI the manifest checks need, so they skip — and a skip is not a pass"

# The release workflow: the one that publishes. Nothing checked it existed, so
# deleting it left the suite green and the next tag would have shipped whatever
# was on the branch, unvalidated.
rel_path = os.path.join(sys.argv[1], ".github/workflows/release.yml")
assert os.path.exists(rel_path), \
    "there is no release workflow — a tag would publish without running anything"
rel = yaml.safe_load(open(rel_path, encoding="utf-8"))
on = rel.get("on") or rel.get(True)          # PyYAML reads a bare `on:` as True
assert "push" in str(on) and "tag" in str(on), \
    "the release workflow does not trigger on a tag: %r" % (on,)
rsteps = [s for job in rel["jobs"].values() for s in job.get("steps", [])]
for needle in ("scripts/verify_install.sh", "scripts/lint_method.py", "scripts/check_versions.py"):
    owning = [s for s in rsteps if needle in str(s.get("run", ""))]
    assert owning, f"the release workflow never runs {needle} — it would publish unvalidated"
    for s in owning:
        assert not s.get("continue-on-error") and "|| true" not in str(s.get("run", "")), \
            f"{needle}'s failure is swallowed in the release workflow"

# The mutation workflow, judged the same way: a shard that cannot fail is a
# coverage number nobody earned.
mut = yaml.safe_load(open(os.path.join(sys.argv[1], ".github/workflows/mutations.yml"),
                          encoding="utf-8"))
msteps = [s for job in mut["jobs"].values() for s in job.get("steps", [])]
for needle in ("scripts/mutate.py --shard", "--check-anchors", "--cover"):
    owning = [s for s in msteps if needle in str(s.get("run", ""))]
    assert owning, f"mutations.yml no longer runs `{needle}`"
    for s in owning:
        assert not s.get("continue-on-error"), f"`{needle}` runs with continue-on-error"
        assert "|| true" not in str(s.get("run", "")), f"`{needle}`'s failure is swallowed"

# The behavioral layer, which is the only one that costs money and therefore
# the only one run on demand. Nothing verified it exists: deleting the
# workflow, the measurement that needs a model simply stops existing and no
# required context goes red, because it was not one.
#
# And the CONTROL apart from the normal run, because it is the one that
# discriminates: a behavioral scenario that passes and does not go red with its
# regression in place is applauding the model's prose. A workflow that runs
# only the normal half reports green over that.
beh_path = os.path.join(sys.argv[1], ".github/workflows/behavioral.yml")
assert os.path.exists(beh_path), \
    "there is no behavioral workflow — the layer that puts the instructions in front of a model"
beh = yaml.safe_load(open(beh_path, encoding="utf-8"))
bsteps = [s for job in beh["jobs"].values() for s in job.get("steps", [])]
runs = [str(s.get("run", "")) for s in bsteps]
assert any("evals/runner.py" in r and "--kinds behavioral" in r for r in runs), \
    "behavioral.yml never runs the behavioral scenarios"
assert any("--control" in r for r in runs), \
    "behavioral.yml runs the scenarios and never their controls — the half that discriminates"
for s in bsteps:
    if "evals/runner.py" in str(s.get("run", "")):
        assert not s.get("continue-on-error") and "|| true" not in str(s.get("run", "")), \
            "a behavioral run's failure is swallowed, so the layer reports green either way"
assert any("OPENCODE_API_KEY" in str(s.get("run", "")) and "exit 1" in str(s.get("run", ""))
           for s in bsteps), \
    ("behavioral.yml does not fail when the key is absent — a run that called no model would "
     "finish green, saying the instructions were measured when nothing measured them")

# Every job that RUNS the suite has to be a machine the suite's own preflight
# accepts — asked of all workflows, not of a hand-listed three, because the one
# that forgets is always the one nobody thought to list.
#
# The preflight calls `bad()` for a missing tool and `bad()` decides the exit
# code, so a job without the CLI exits non-zero on a tree with nothing wrong
# with it. In `verify` that is a loud false failure. In `mutations` it was
# silent and worse: the runner reads a non-zero exit as "the fault was caught",
# so all ten shards reported every mutation killed without one being examined,
# and the job printed 100%. `release` had the same shape, unfired only because
# no tag has been pushed.
#
# Which tool is derived from the preflight loop rather than restated here: add
# one there and this starts asking about it.
import glob, re
suite_src = open(os.path.join(sys.argv[1], "scripts/verify_install.sh"), encoding="utf-8").read()
loop = re.search(r"^for TOOL in ([A-Za-z0-9 _-]+); do", suite_src, re.M)
assert loop, "the preflight no longer loops over the tools it requires — this check reads that list"
if "claude" in loop.group(1).split():
    RUNS_SUITE = ("scripts/verify_install.sh", "scripts/mutate.py --shard", "scripts/mutate.py --only")
    for path in sorted(glob.glob(os.path.join(sys.argv[1], ".github/workflows/*.yml"))):
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            jsteps = job.get("steps", []) or []
            if not any(n in str(s.get("run", "")) for s in jsteps for n in RUNS_SUITE):
                continue
            assert any("@anthropic-ai/claude-code" in str(s.get("run", "")) for s in jsteps), \
                ("%s: job `%s` runs the suite without installing the CLI its preflight requires — "
                 "the suite exits non-zero on a clean tree, and in a mutation job that reads as "
                 "every fault caught" % (os.path.basename(path), job_name))
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
ddw_earn "$SH" define FEAT-001

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
# Captured, not piped: post mode never reads stdin, so the `echo` feeding it can
# lose the race and die of SIGPIPE — and under `pipefail` that 141 was the
# pipeline's verdict on macOS while the note sat right there in the output.
PNOUT="$(post_note || true)"
case "$PNOUT" in
  *"product source has changed while the pipeline is in PLAN"*)
    ok "and reports product source that appeared in a phase that does not write source" ;;
  *) bad "source written through a shell in PLAN goes entirely unnoticed" ;;
esac

# The note must ride each tool's documented context channel, ON STDOUT. stderr
# next to an exit 0 reaches no model in any harness — measured live (Copilot
# CLI 1.0.80, 2026-08-25): the note was computed, printed, and dropped, and the
# session's own probe read "no hook output". This suite missed it for the same
# reason it existed: `post_note` captures 2>&1, so the check above proves the
# note is COMPUTED. These two prove it ARRIVES — they read stdout alone.
python3 "$SH/.ddw/scripts/hook-gate.py" --dialect standard --mode post \
  --state "$SH/.ddw-state.json" --graph "$SH/.ddw/rules/transition-graph.json" \
  --repo "$SH" < /dev/null 2>/dev/null | python3 -c '
import json, sys
d = json.loads(sys.stdin.read().strip())
hso = d["hookSpecificOutput"]
assert hso["hookEventName"] == "PostToolUse", hso
assert "product source has changed" in hso["additionalContext"], hso
' && ok "the note reaches Claude Code on stdout, as PostToolUse additionalContext" \
  || bad "the note dies on stderr for Claude Code — computed, printed, and never shown to the model"

python3 "$SH/.ddw/scripts/hook-gate.py" --dialect copilot --mode post \
  --state "$SH/.ddw-state.json" --graph "$SH/.ddw/rules/transition-graph.json" \
  --repo "$SH" < /dev/null 2>/dev/null | python3 -c '
import json, sys
d = json.loads(sys.stdin.read().strip())
assert "product source has changed" in d["additionalContext"], d
' && ok "and reaches Copilot as additionalContext — the one channel its non-blocking hooks have" \
  || bad "the note dies on stderr for Copilot — logged and skipped, never shown to the model"

# The notice, KEPT. On the tools that swallow the context channel the journal
# is all that remains, and the question the notice exists for — did the
# detection fire? — must have an answer after the run. Measured on a general
# run (Copilot, 2026-08-25): shell writes in the transcript, an empty journal,
# and no way to tell fired-and-swallowed from never-fired.
python3 - "$SH" <<'PYNJ' && ok "the notice lands in the journal, so fired-and-swallowed and never-fired are different states" || bad "the notice leaves no record — the run over, nobody can say whether detection fired"
import json, sys
recs = [json.loads(l) for l in open(sys.argv[1] + "/.ddw-journal.jsonl", encoding="utf-8")
        if l.strip()]
notes = [r for r in recs if isinstance(r, dict) and r.get("record") == "notice"]
assert notes, "no notice record in the journal"
assert "product source has changed" in notes[-1].get("note", ""), notes[-1]
PYNJ

# …and lands ONCE per distinct finding: the post matcher fires on every tool
# call, and the same dirty file must not write the same sentence forty times.
post_note >/dev/null; post_note >/dev/null
python3 - "$SH" <<'PYND' && ok "and an unchanged finding is one journal line, not one per tool call" || bad "the journal repeats the same notice on every Bash — noise the audit then has to explain"
import json, sys
recs = [json.loads(l) for l in open(sys.argv[1] + "/.ddw-journal.jsonl", encoding="utf-8")
        if l.strip()]
notes = [r for r in recs if isinstance(r, dict) and r.get("record") == "notice"]
assert len(notes) == 1, "expected one notice record, got %d" % len(notes)
PYND

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
# By the scripts' NAME, not by the string `ddw`. Claude is the only one of the
# six whose wiring does not hang off a `ddw/` subdirectory — `bash
# ${CLAUDE_PROJECT_DIR}/.claude/hooks/enforce.sh` — so searching for "ddw" here
# found nothing even when all five blocks were left in place pointing at
# freshly deleted scripts. Verified by undoing the entire un-merge: three
# neighboring checks in red and this one reporting ✓. A check that cannot fail
# reports green for lack of anything else to say.
grep -qE "enforce\.sh|session-start\.sh|validate-state-transition\.sh" "$UN/.claude/settings.json" \
  && bad "DDW's hooks are still wired to scripts that were just deleted — every session fails on a missing command" \
  || ok "and DDW's own hook blocks are unwired"

# Nothing DDW installed may be left behind, for ANY tool. The manifest speaks in
# repo paths now, but it used to record skills, agents and commands relative to
# the adapter's own directory — and the resolver knew two of those three, so
# every generated slash command survived every uninstall. On OpenCode, whose
# whole surface is commands plus one plugin file, that is most of the install.
python3 - "$SELF" <<'PYUNINST' && ok "uninstalling leaves nothing DDW installed behind, on any of the six tools, and keeps a file you edited unless you force it" || bad "an uninstall leaves DDW files behind, or destroys a file you had changed"
import glob, json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
for target in ("claude", "codex", "copilot", "cursor", "gemini", "opencode"):
    repo = os.path.join(work, target)
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", target],
                   capture_output=True, text=True)
    recorded = json.load(open(os.path.join(repo, ".ddw-installed.json"), encoding="utf-8"))
    installed = [k.split(":", 1)[-1] for k in recorded]
    subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes"],
                   capture_output=True, text=True)
    left = [rel for rel in installed if os.path.exists(os.path.join(repo, rel))]
    assert not left, f"{target}: uninstall left {len(left)} installed file(s) behind: {left[:4]}"

# The other half of the promise, which had no check at all: a DDW file YOU
# edited is kept, and only `--force` takes it. Deleting a user's edit silently is
# the one thing an uninstaller must never do.
repo = os.path.join(work, "edited")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
MINE = "\n# I changed this on purpose\n"
edited = os.path.join(repo, ".claude", "hooks", "enforce.sh")
open(edited, "a", encoding="utf-8").write(MINE)
subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes"],
               capture_output=True, text=True)
assert os.path.exists(edited), "a DDW file the user had edited was deleted without --force"
assert MINE in open(edited, encoding="utf-8").read(), "the user's edit was lost"
subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes", "--force"],
               capture_output=True, text=True)
assert not os.path.exists(edited), "--force did not remove the file it exists to remove"

# A manifest an OLDER install left behind. Those recorded skills, agents and
# commands relative to the adapter's own directory (`claude:skills/ddw-commit`)
# rather than to the repo, and the resolver knew two of those three dialects — so
# every generated slash command survived every uninstall. The repo-relative keys
# written from this version on make the translation unnecessary, which is exactly
# why it has to be checked against the shape that still needs it.
legacy = os.path.join(work, "legacy")
os.makedirs(legacy)
subprocess.run(["git", "-C", legacy, "init", "-q"], check=True)
# OpenCode, because it is the target whose surface IS commands: seventeen of
# them, plus one plugin file. Claude generates none, so the case would not exist.
subprocess.run(["bash", os.path.join(src, "install.sh"), legacy, "--target", "opencode"],
               capture_output=True, text=True)
mpath = os.path.join(legacy, ".ddw-installed.json")
current = json.load(open(mpath, encoding="utf-8"))
old_style, samples = {}, []
for key, digest in current.items():
    tool, _, rel = key.partition(":")
    for kind in ("skills", "agents", "commands"):
        marker = "/%s/" % kind
        if marker in rel:
            rel = kind + "/" + rel.split(marker, 1)[1]
            samples.append(rel)
            break
    old_style["%s:%s" % (tool, rel)] = digest
assert any(s.startswith("commands/") for s in samples), \
    "this install generated no slash commands, so the case cannot be exercised"
json.dump(old_style, open(mpath, "w", encoding="utf-8"), indent=2, sort_keys=True)
subprocess.run(["bash", os.path.join(src, "uninstall.sh"), legacy, "--yes"],
               capture_output=True, text=True)
survivors = [d for d in (".opencode/skills", ".opencode/agent", ".opencode/commands")
             if os.path.isdir(os.path.join(legacy, d)) and os.listdir(os.path.join(legacy, d))]
assert not survivors, \
    f"a manifest written by an older install left {survivors} behind — an upgrade never gets clean"

# And the settings block that older install WIRED. Byte-for-byte against what
# this version ships answers "is this ours?" only for the version asking: rename
# a hook script between releases and the block from before belongs to nobody, so
# it survives the uninstall while the script it names is deleted — a repository
# that cannot be left, failing on `command not found` at every write, with DDW
# gone and nothing left to explain it. The manifest says what DDW installed; a
# block naming one of those files is DDW's whichever version wired it.
stale = os.path.join(work, "stale")
os.makedirs(stale)
subprocess.run(["git", "-C", stale, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), stale, "--target", "claude"],
               capture_output=True, text=True)
spath = os.path.join(stale, ".claude", "settings.json")
settings = json.load(open(spath, encoding="utf-8"))
hooks = settings.get("hooks", {})
touched = 0
for event, groups in hooks.items():
    for group in groups:
        for h in group.get("hooks", []):
            # The same hook file, wired the way another version wrote it. Not
            # byte-identical to anything this version ships; still DDW's.
            if ".claude/hooks/" in h.get("command", ""):
                h["command"] = h["command"].replace("bash ", "bash -- ", 1)
                touched += 1
assert touched, "the install wired no hook command, so the case cannot be planted"
json.dump(settings, open(spath, "w", encoding="utf-8"), indent=2)
subprocess.run(["bash", os.path.join(src, "uninstall.sh"), stale, "--yes"],
               capture_output=True, text=True)
left = json.load(open(spath, encoding="utf-8")) if os.path.exists(spath) else {}
orphans = [h.get("command") for groups in left.get("hooks", {}).values()
           for g in groups for h in g.get("hooks", [])
           if ".claude/hooks/" in h.get("command", "")]
assert not orphans, \
    ("the uninstall left %d hook block(s) an older version wired: %s — every write in that "
     "repository now fails on a script the uninstall deleted" % (len(orphans), orphans[:2]))

# The context file of every tool that has one. `GEMINI.md` was written and not
# removed: it stayed in the repo importing `@.ddw/orchestrator.md` with `.ddw/`
# already deleted, and every Gemini session there starts by reading a file that
# is not there. Derived from the adapters, not from a list here: a list here is
# a second copy, and the second copy is the one that misses the tool added
# tomorrow.
for _recipe in sorted(glob.glob(os.path.join(src, "adapters/*/adapter.json"))):
    _tool = os.path.basename(os.path.dirname(_recipe))
    _ctx = (json.load(open(_recipe, encoding="utf-8")) or {}).get("context_file")
    if not _ctx:
        continue
    _repo = os.path.join(work, "ctx-" + _tool)
    os.makedirs(_repo)
    subprocess.run(["git", "-C", _repo, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), _repo, "--target", _tool],
                   capture_output=True, text=True)
    _path = os.path.join(_repo, _ctx)
    assert os.path.exists(_path), \
        "%s declares `context_file` %s and the installation did not write it" % (_tool, _ctx)
    subprocess.run(["bash", os.path.join(src, "uninstall.sh"), _repo, "--yes"],
                   capture_output=True, text=True)
    if os.path.exists(_path):
        _left = open(_path, encoding="utf-8").read()
        assert "BEGIN DDW" not in _left, \
            ("%s was left with DDW's block after uninstalling: it imports a method that is "
             "no longer there, and every session in that repo starts by reading a deleted file" % _ctx)

# And the plan that gets approved has to be the deletion that runs. With
# `--force`, the plan was printed WITHOUT `--force`: it said "Kept 1 file(s) …
# re-run with --force" and then deleted that file. You read "kept" and lose
# your own file — the worst possible order, because the plan exists precisely
# to be read before saying yes.
_pf = os.path.join(work, "plan-force")
os.makedirs(_pf)
subprocess.run(["git", "-C", _pf, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), _pf, "--target", "claude"],
               capture_output=True, text=True)
_mine = os.path.join(_pf, ".claude", "hooks", "enforce.sh")
open(_mine, "a", encoding="utf-8").write("\n# una línea mía\n")
_plan = subprocess.run(["bash", os.path.join(src, "uninstall.sh"), _pf, "--plan", "--force"],
                       capture_output=True, text=True).stdout
subprocess.run(["bash", os.path.join(src, "uninstall.sh"), _pf, "--yes", "--force"],
               capture_output=True, text=True)
assert "enforce.sh" in _plan, \
    ("the plan of a `--force` does not name the edited file `--force` is about to delete: "
     + _plan[-400:])
assert not os.path.exists(_mine), "the `--force` did not delete what its own plan said it would delete"
assert "Kept" not in _plan or "--force" not in _plan.split("Kept")[1][:200], \
    ("the plan of a `--force` says it keeps files and suggests re-running with "
     "`--force`, which is what was just asked for — and then deletes them: " + _plan[-400:])
PYUNINST

# The manifest is COMMITTED, so it arrives with the clone, from whoever wrote it —
# and the uninstaller removes what its keys name. Four keys, each a different way
# to name something that is not DDW's: out of the repo, an absolute path, the
# repository ITSELF (which passed a containment check written as "is it inside?"
# and was handed to rmtree), and `.git`. A mutation for this existed and killed
# nothing, because no check drove it: the guard was measured by reading it.
python3 - "$SELF" <<'PYESCAPE' && ok "an uninstall refuses a manifest entry naming anything outside the repo, the repo root itself, or .git — and says so" || bad "a committed manifest can make the uninstaller delete a path DDW never installed, up to and including the working tree"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
repo = os.path.join(work, "victim")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
neighbour = os.path.join(work, "NEIGHBOUR")
os.makedirs(neighbour)
open(os.path.join(neighbour, "important.txt"), "w", encoding="utf-8").write("not yours\n")
absolute = os.path.join(work, "ABSOLUTE")
os.makedirs(absolute)
open(os.path.join(absolute, "x.txt"), "w", encoding="utf-8").write("not yours either\n")
mine = os.path.join(repo, "main.py")
open(mine, "w", encoding="utf-8").write("print('mine')\n")

mpath = os.path.join(repo, ".ddw-installed.json")
manifest = json.load(open(mpath, encoding="utf-8"))
manifest.update({"claude:../NEIGHBOUR": "x", "claude:" + absolute: "x",
                 "claude:.": "x", "claude:.git": "x"})
json.dump(manifest, open(mpath, "w", encoding="utf-8"), indent=2, sort_keys=True)

# --force, because it is the run that skips the fingerprint comparison: the
# containment guard is then the only thing between a hostile manifest and rmtree.
out = subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes", "--force"],
                     capture_output=True, text=True)
report = out.stdout + out.stderr
assert os.path.isdir(neighbour) and os.path.exists(os.path.join(neighbour, "important.txt")), \
    "the uninstaller followed `../NEIGHBOUR` out of the repository and deleted it"
assert os.path.isdir(absolute) and os.path.exists(os.path.join(absolute, "x.txt")), \
    "an absolute path in the manifest was removed"
assert os.path.isdir(repo), "the uninstaller removed the repository itself"
assert os.path.isdir(os.path.join(repo, ".git")), \
    "the uninstaller removed .git — the history of a repo that only wanted DDW gone"
assert os.path.exists(mine), "the user's own file was removed with the repository root"
assert "REFUSED" in report, \
    "four entries naming paths DDW never installed were skipped in silence: " + report[-300:]
# And the ordinary uninstall still happened around them.
assert not os.path.isdir(os.path.join(repo, ".ddw")), \
    "a hostile manifest entry stopped the uninstall it was mixed into"
PYESCAPE

# The sanctioned helper could not close a ticket in ANY tier. CLOSEOUT->IDLE
# demands `commit` and `pr`; reaching IDLE wipes the gates, so `--gate` on that
# edge was silently discarded — and the refusal that followed blamed a missing
# `--tier`, a flag that edge ignores. The only way through was a hand-written
# Write, which is what the helper exists to avoid.
python3 - "$SELF" <<'PYCLAIM' && ok "a gate is claimed in the phase that owns it, and a whole ticket closes through the helper alone" || bad "the helper cannot close a ticket, or --claim opens a gate with no evidence"
import hashlib, json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
for k, v in (("user.email", "ddw@test"), ("user.name", "ddw"), ("commit.gpgsign", "false")):
    subprocess.run(["git", "-C", repo, "config", k, v], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
tr = os.path.join(repo, ".ddw", "scripts", "transition.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
WHERE = {"define": ("prd", "prd", "prd"), "spec": ("specs", "spec", "spec"),
         "threat": ("security", "threat", "threat"), "verify": ("reports", "verify", "verify"),
         "tests": ("reports", "tests", "tests"), "sast": ("security", "sast", "sast")}
sess = os.path.join(repo, ".ddw-sessions")
os.makedirs(sess, exist_ok=True)
for gate, (sub, stem, receipt) in WHERE.items():
    d = os.path.join(repo, "docs", "ddw", sub)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "%s-T-1.md" % stem)
    open(p, "w", encoding="utf-8").write("# %s\n" % stem)
    dg = hashlib.sha256(open(p, encoding="utf-8").read().encode("utf-8")).hexdigest()[:12]
    nm = "%s-validated-%s" % (receipt, dg)
    open(os.path.join(sess, nm), "w").write(os.path.basename(p))
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": "receipt", "name": nm,
                             "file": os.path.basename(p)}, sort_keys=True) + "\n")


def run(*args):
    return subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                           *args], capture_output=True, text=True)


def step(*args):
    r = run(*args)
    assert r.returncode == 0, "%s refused: %s" % (" ".join(args), r.stderr.strip()[:200])


# The classify edge's context check and CODE's decisions record — other gates
# than the ones under test here, satisfied the way a real run leaves them.
os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
open(os.path.join(repo, ".ddw-work", "context-check-T-1.md"), "w", encoding="utf-8").write(
    "Nothing to report.\n")
open(os.path.join(repo, "docs", "ddw", "specs", "decisions-T-1.md"), "w", encoding="utf-8").write(
    "No decisions were approved outside the spec during this ticket.\n")

step("--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE", "--ticket", "T-1")
step("--to", "DEFINE", "--action", "d", "--title", "the fixture ticket")
step("--to", "PLAN", "--action", "p", "--gate", "define")
step("--to", "CODE", "--action", "co", "--gate", "spec", "--gate", "threat")
step("--to", "VERIFY", "--action", "v", "--gate", "tests", "--gate", "sast")
step("--to", "CLOSEOUT", "--action", "cl", "--gate", "verify")
# `--gate` on the closing edge is a mistake, and it has to SAY so rather than
# accept the flag, drop it, and blame the tier.
r = run("--to", "IDLE", "--action", "done", "--gate", "commit", "--gate", "pr")
assert r.returncode == 2 and "--claim" in r.stderr, \
    "the closing edge accepted --gate silently, or its refusal points nowhere useful: " + r.stderr[:220]
assert "--gate is not read on --to IDLE" in r.stderr, \
    ("the flag was dropped and the refusal came from somewhere else — a silently ignored "
     "flag is how the helper came to be unable to close a ticket: " + r.stderr[:220])
assert "tier is missing" not in r.stderr, "the refusal still blames the tier on the IDLE edge"
# And the same question with NO --gate at all, which is the path that actually
# reaches the hint: with the flag present the run stops at the explicit refusal
# above, so the hint is never composed and the assertion holds for free.
r = run("--to", "IDLE", "--action", "done")
assert r.returncode == 2, "the closeout was accepted with commit and pr unpaid"
assert "tier is missing" not in r.stderr, \
    ("the refusal blames a missing --tier on the closing edge, where --tier is ignored and the "
     "real answer is a gate: " + r.stderr[:220])
assert "--claim" in r.stderr, "the refusal does not say how to earn the gate: " + r.stderr[:220]
# …and --claim earns it where it is earned: with the evidence, in the phase.
subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
subprocess.run(["git", "-C", repo, "commit", "-qm", "the work"], capture_output=True)
open(os.path.join(repo, "docs", "ddw", "prd", "prd-T-1.md"), "a", encoding="utf-8").write("more\n")
r = run("--claim", "commit")
assert r.returncode == 2, "the commit gate was claimed with tracked changes uncommitted"
subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
subprocess.run(["git", "-C", repo, "commit", "-qm", "the rest"], capture_output=True)
step("--claim", "commit")
assert json.load(open(state, encoding="utf-8"))["gates"].get("commit") is True, \
    "--claim did not mark the gate"
claim_events = [e for e in json.load(open(state, encoding="utf-8"))["history"]
                if e.get("from") == e.get("to")]
assert len(claim_events) >= 1 and claim_events[-1]["action"].startswith("claim:"), \
    "--claim left no claim event — the audit trail lost where the gate was earned"
r = run("--claim", "banana")
assert r.returncode == 2, "--claim accepted a gate that does not exist"
r = run("--claim", "commit", "--to", "IDLE", "--action", "x")
assert r.returncode == 2, "--claim and a transition in one run — two writes wearing one"
PYCLAIM

# Two refusals that sent the reader in a circle. Both hints were written for one
# state and printed for every state that reached the same branch.
python3 - "$SELF" <<'PYHINTS' && ok "an edge to IDLE that does not exist says which phase closes a ticket, instead of prescribing gates that change nothing" || bad "a refused edge to IDLE still prescribes a claim that succeeds and leaves the same refusal in place"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
tr = os.path.join(src, "ddw/scripts/transition.py")
graph = os.path.join(src, "ddw/rules/transition-graph.json")
work = tempfile.mkdtemp(dir=os.environ["WORK"])
state = os.path.join(work, "mid.json")
open(state, "w", encoding="utf-8").write(json.dumps({
    "phase": "CODE", "ticket": "T-1", "tier": "FEATURE",
    "gates": {"define": True, "spec": True, "threat": True},
    "history": [{"from": "IDLE", "to": "CLASSIFY", "action": "c", "ticket": "T-1"}]}))
r = subprocess.run([sys.executable, tr, "--state", state, "--graph", graph,
                    "--to", "IDLE", "--action", "done"], capture_output=True, text=True, cwd=work)
assert r.returncode == 2, "CODE->IDLE was accepted"
assert "CLOSEOUT" in r.stderr, "the refusal never says which phase closes a ticket: " + r.stderr[-300:]
assert "--claim commit" not in r.stderr, \
    ("the refusal prescribes claiming gates on an edge that does not exist — from CODE both "
     "claims exit 0 and the retry prints this same sentence: " + r.stderr[-300:])
PYHINTS

python3 - "$SELF" <<'PYRESUME' && ok "out of IDLE, a paused ticket is pointed at the resume that works — and a state with nothing paused is still sent to CLASSIFY" || bad "the way out of IDLE is described by a hint the state contradicts"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
tr = os.path.join(src, "ddw/scripts/transition.py")
graph = os.path.join(src, "ddw/rules/transition-graph.json")
work = tempfile.mkdtemp(dir=os.environ["WORK"])

def run(state, *args):
    return subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, *args],
                          capture_output=True, text=True, cwd=work)

def write(name, obj):
    path = os.path.join(work, name)
    open(path, "w", encoding="utf-8").write(json.dumps(obj))
    return path

paused = write("paused.json", {
    "phase": "IDLE", "ticket": "T-2", "tier": None, "gates": {},
    "history": [{"from": "CODE", "to": "IDLE", "action": "pause: review", "ticket": "T-2"}]})
r = run(paused, "--to", "CODE", "--action", "keep going")
assert r.returncode == 2 and "resume" in r.stderr, \
    "a paused ticket is not told that the way back is a resume: " + r.stderr[-300:]
assert "only transition" not in r.stderr, \
    ("the refusal says CLASSIFY is the only way out of IDLE, which for this state means "
     "throwing the ticket away: " + r.stderr[-300:])
# The sentence it prints has to be true: the edge it points at is legal.
r = run(paused, "--to", "CODE", "--action", "resume: back to it")
assert r.returncode == 0, "the resume the hint prescribes is itself refused: " + r.stderr[-300:]
r = run(paused, "--to", "DEFINE", "--action", "resume: wrong phase")
assert r.returncode == 2 and "CODE" in r.stderr, \
    "a resume into a phase this ticket was never paused in does not name the one it was: " + r.stderr[-300:]
# And with nothing paused, CLASSIFY really is the only way out.
fresh = write("fresh.json", {"phase": "IDLE", "ticket": None, "tier": None, "gates": {}, "history": []})
r = run(fresh, "--to", "CODE", "--action", "straight to work")
assert r.returncode == 2 and "CLASSIFY" in r.stderr, \
    "an IDLE state with no pause behind it is not sent to CLASSIFY: " + r.stderr[-300:]
PYRESUME

# Four rules the mutation run found uncovered: a tool nobody mapped, the pr
# gate's `list` vs `view`, the tier chain's direction, and a skill named in the
# prose that does not exist.
python3 - "$SELF" <<'PYFOUR' && ok "an unmapped tool cannot write the state, the pr gate asks by branch, a child tier overrides its parent, and a dangling skill reference is caught" || bad "one of the four: an unknown tool writes the state unexamined, `gh pr view` takes any PR, the tier chain is inverted, or the linter stopped reading the prose"
import importlib.util, json, os, subprocess, sys, tempfile
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

# 1. A tool the mapper does not know must not be able to produce a new state.
try:
    m._reconstruct_new_text("SomeFutureTool", {"content": "{}"}, "{}")
    raise AssertionError("an unmapped tool reconstructed the state and would be judged as legal")
except m.Block:
    pass

# 2. The pr gate asks `gh pr list --head <branch>`, never `gh pr view <branch>`:
#    `view` takes a number OR a branch, so a branch named `123` resolved to PR
#    #123 — any state, any topic — and opened the gate.
source = open(os.path.join(src, "ddw/scripts/validate-transition.py"), encoding="utf-8").read()
assert '"gh", "pr", "list", "--head"' in source, \
    "the pr gate no longer asks by branch; `gh pr view <branch>` opens on someone else's PR"

# 3. The tier chain: a child must be able to override an edge its parent defines.
graph = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))
probe = json.loads(json.dumps(graph))
probe["tiers"]["FIX"] = {"extends": "FEATURE", "PLAN->CODE": {"gates": ["only-mine"]}}
edges = m._effective_edges(probe, "FIX")
assert edges["PLAN->CODE"]["gates"] == ["only-mine"], \
    "the chain is walked so the parent wins — a tier cannot override what it extends"

# 4. The linter's dangling-reference check, over the prose it actually ships.
work = tempfile.mkdtemp(dir=os.environ["WORK"])
subprocess.run(["cp", "-r", src, os.path.join(work, "repo")], check=True)
repo = os.path.join(work, "repo")
victim = os.path.join(repo, "skills", "ddw-status", "SKILL.md")
open(victim, "a", encoding="utf-8").write('\n\nSkill(skill="ddw-does-not-exist")\n')
r = subprocess.run([sys.executable, os.path.join(repo, "scripts/lint_method.py")],
                   capture_output=True, text=True, cwd=repo)
assert r.returncode != 0 and "ddw-does-not-exist" in (r.stdout + r.stderr), \
    "a skill named in a SKILL.md that does not exist went uncaught: " + (r.stdout + r.stderr)[-300:]
PYFOUR

# The catalog's Quantitative Summary said 69 FAIL rules and 84 total where its
# tables define 65 and 80, and `ddw/rules/README.md` repeated the 84. Nobody
# mis-typed it: rules were merged and removed over three rounds and the summary
# was never recounted. The number the method is FOR was the one number nothing
# checked.
python3 - "$SELF" <<'PYRULECOUNT' && ok "the catalog's summary is counted against the rules the catalog defines, and so is the README line that restates it" || bad "the rule catalog can go back to summarising a count of rules it does not contain"
import json, os, re, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
subprocess.run(["cp", "-r", src, os.path.join(work, "repo")], check=True)
repo = os.path.join(work, "repo")

def lint():
    r = subprocess.run([sys.executable, os.path.join(repo, "scripts/lint_method.py")],
                       capture_output=True, text=True, cwd=repo)
    return r.returncode, r.stdout + r.stderr

def rewrite(rel, old, new):
    path = os.path.join(repo, rel)
    text = open(path, encoding="utf-8").read()
    assert old in text, "%s no longer contains %r" % (rel, old)
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

code, out = lint()
assert code == 0, "the shipped tree does not lint clean, so nothing below means anything: " + out[-300:]

# One area row overstated by one, exactly the shape the drift took.
rewrite("ddw/rules/validation-rules.instructions.md", "| PRD | 12 | 6 | 18 |", "| PRD | 13 | 6 | 19 |")
code, out = lint()
assert code != 0 and "PRD" in out and "12" in out, \
    "an area row that overcounts its own rules passed: " + out[-300:]
rewrite("ddw/rules/validation-rules.instructions.md", "| PRD | 13 | 6 | 19 |", "| PRD | 12 | 6 | 18 |")

# The total alone, with every row correct — the arithmetic nobody redid.
rewrite("ddw/rules/validation-rules.instructions.md",
        "| **Total** | **73** | **18** | **91** |", "| **Total** | **77** | **18** | **95** |")
code, out = lint()
assert code != 0 and "73" in out, "a summary whose total contradicts its own rows passed: " + out[-300:]
rewrite("ddw/rules/validation-rules.instructions.md",
        "| **Total** | **77** | **18** | **95** |", "| **Total** | **73** | **18** | **91** |")

# Two more of the linter's checks, driven the same way. Both were added with a
# mutation and no check: deleting the CALL left the repository linting clean,
# because a clean repository is what a deleted check reports. What proves a
# check runs is a planted violation it has to name.

# The 🔒 mark: a phase that blocks source and does not say the hook is what
# refuses it reads like the rules nothing enforces.
orch = os.path.join(repo, "ddw/orchestrator.md")
text = open(orch, encoding="utf-8").read()
# The line has to be one the check judges: a phase that blocks source, and not
# one of the phases where source is allowed and there is nothing to mark.
def _unmark(m):
    line = m.group(0)
    return line.replace("🔒", "") if "source" in line.lower() else line
stripped, n = re.subn(r"^- \*\*Blocked:\*\*.*🔒.*$", _unmark, text, flags=re.M)
assert n and stripped != text, "no Blocked line marks a source refusal, so the case cannot be planted"
open(orch, "w", encoding="utf-8").write(stripped)
code, out = lint()
assert code != 0 and "mark" in out.lower(), \
    "a phase that blocks source without marking it as the hook's passed: " + out[-300:]
open(orch, "w", encoding="utf-8").write(text)

# The context template: a section it ships that `ddw-context-check` never looks
# for means a repository missing that section is reported as complete.
tpl = os.path.join(repo, "ddw/AGENTS.template.md")
text = open(tpl, encoding="utf-8").read()
open(tpl, "a", encoding="utf-8").write("\n## Deployment topology\n\nWhere this runs.\n")
code, out = lint()
assert code != 0 and "Deployment topology" in out, \
    "the template shipped a section nothing looks for and linted clean: " + out[-300:]
open(tpl, "w", encoding="utf-8").write(text)

# The heading the skills order CITED has to be in the template the installer
# writes. The two skills that ask for a coverage floor cite
# `AGENTS.md, "Testing"` in the document they teach, and the linter's sweep
# only looked at `ddw/**`: the template's section could be deleted and the lint
# stayed green. It is what 87ae703 fixed, and nothing was holding it up.
tpl2 = os.path.join(repo, "ddw/AGENTS.template.md")
text = open(tpl2, encoding="utf-8").read()
cut = re.sub(r"^## Testing.*?(?=^## )", "", text, flags=re.M | re.S)
assert cut != text, "the template no longer carries `## Testing`, so there is no case to plant"
open(tpl2, "w", encoding="utf-8").write(cut)
code, out = lint()
assert code != 0 and "Testing" in out and "installer" in out, \
    "the template lost a section the skills order cited and the lint passed: " + out[-300:]
open(tpl2, "w", encoding="utf-8").write(text)

# A tier that asks for NO gate has to be explained where a person reads. The
# others announce themselves: something is asked for, something is refused. In
# that one nothing is asked, so if `docs/METHOD.md` does not name it, the
# product has an enforcement-free mode that only whoever reads the graph finds
# out about. It is the half of 4c41f3e no check was holding up —
# `check_tiers_documented` looks at the two files the MODEL reads, and none a
# person reads.
method = os.path.join(repo, "docs/METHOD.md")
text = open(method, encoding="utf-8").read()
graph = json.load(open(os.path.join(repo, "ddw/rules/transition-graph.json"), encoding="utf-8"))
def _asks(tier):
    """What a tier asks for, with the `extends` chain resolved: reading only its
    own keys, every inheriting tier looks like it asks for nothing — and then
    this probe picked any one, and deleting it from METHOD.md changed nothing."""
    out, seen, cur = set(), set(), tier
    while cur and cur not in seen:
        seen.add(cur)
        spec = (graph.get("tiers") or {}).get(cur) or {}
        for key, edge in spec.items():
            if key.startswith("_") or key == "extends" or not isinstance(edge, dict):
                continue
            out |= set(edge.get("gates") or [])
        cur = spec.get("extends")
    return out


free = [t for t in (graph.get("tiers") or {}) if not _asks(t)]
assert free, "the graph no longer defines any gateless tier, so there is no case to plant"
open(method, "w", encoding="utf-8").write(text.replace(free[0], "REDACTED"))
code, out = lint()
assert code != 0 and free[0] in out, \
    "the only enforcement-free tier was deleted from METHOD.md and the lint passed: " + out[-300:]
open(method, "w", encoding="utf-8").write(text)

code, out = lint()
assert code == 0, "the tree was not put back the way it was found: " + out[-300:]

# And the restatement outside the catalog, which is the line a reader of
# `ddw/rules/` meets first.
rewrite("ddw/rules/README.md", "The 91 validation rules", "The 94 validation rules")
code, out = lint()
assert code != 0 and "91" in out, "the README's rule count drifted from the catalog unchecked: " + out[-300:]
rewrite("ddw/rules/README.md", "The 94 validation rules", "The 91 validation rules")

code, out = lint()
assert code == 0, "the probe was not restored: " + out[-300:]
PYRULECOUNT

# A tier is one line in the graph and four places in the method: the rules that
# say when to choose it, the schema of the file it is written into, the router
# that says what to load in the phase carrying its name, and the docs a person
# reads. FREE was added and the first three were missed on the first pass — the
# pipeline worked and the method described a product with one fewer tier than it
# had. The graph is the authority for what exists; this is what makes the prose
# follow it.
python3 - "$SELF" <<'PYTIERDOC' && ok "every tier the graph defines is explained where the model and the reader look for it" || bad "a tier can be added to the graph and named nowhere — the model cannot choose on purpose what nobody described"
import json, os, re, shutil, subprocess, sys, tempfile
src = sys.argv[1]
graph = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))
tiers = sorted(graph.get("tiers", {}))
assert len(tiers) >= 2, "the graph defines fewer than two tiers; this check has nothing to compare"

probe = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
shutil.copytree(src, probe, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))


def lint():
    r = subprocess.run([sys.executable, os.path.join(probe, "scripts/lint_method.py")],
                       capture_output=True, text=True, cwd=probe)
    return r.returncode, r.stdout + r.stderr


code, out = lint()
assert code == 0, "the shipped tree does not lint clean, so nothing below means anything: " + out[-300:]

# Take one tier out of the rules that say when to choose it, and the linter has
# to notice. Done for EVERY tier rather than one, so a check that happens to
# name the tier that was there when it was written keeps working.
rules = os.path.join(probe, "ddw/rules/classify.instructions.md")
original = open(rules, encoding="utf-8").read()
for tier in tiers:
    open(rules, "w", encoding="utf-8").write(original.replace(tier, "REDACTED-TIER"))
    code, out = lint()
    open(rules, "w", encoding="utf-8").write(original)
    assert code != 0 and tier in out, \
        "the classification rules can stop naming %s and nothing says so: %s" % (tier, out[-300:])

code, out = lint()
assert code == 0, "the probe was not restored: " + out[-300:]
PYTIERDOC

# `\s` includes the newline, so `^\s*` under `re.MULTILINE` can swallow the rest
# of the file from every line start and give it back one character at a time.
# Twenty patterns across the six validators were written that way, and the one
# in `validate_tests.py` — asked once per field, and there are ten — turned a
# report of blank lines into more than a minute of CPU. Fifty thousand blank
# lines is what a mis-piped `printf` leaves behind, and the failure mode was the
# worst one available: not a refusal, a hang. A hook that hangs is not a hook
# that refused.
#
# Driven with a clock, because that is the only thing that tells the two apart.
python3 - "$SELF" <<'PYSLOWRE' && ok "a document made of blank lines is judged in seconds, not left to backtrack — and every validator is held to it" || bad "a validator can be hung by whitespace, which is a refusal nobody receives"
import glob, os, re, subprocess, sys, tempfile, time
src = sys.argv[1]
d = tempfile.mkdtemp(dir=os.environ["WORK"])
report = os.path.join(d, "blank.md")
open(report, "w", encoding="utf-8").write("\n" * 20000)

for v in sorted(glob.glob(os.path.join(src, "ddw/scripts/validate_*.py"))):
    began = time.time()
    try:
        r = subprocess.run([sys.executable, v, report, "--tier", "FEATURE"],
                           capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise AssertionError("%s did not answer in twenty seconds about a file of blank lines"
                             % os.path.basename(v))
    took = time.time() - began
    assert took < 10, "%s took %.1fs on twenty thousand blank lines" % (os.path.basename(v), took)
    assert "Traceback" not in (r.stdout + r.stderr), \
        "%s crashed on a file of blank lines: %s" % (os.path.basename(v), (r.stdout + r.stderr)[-200:])

# …and the shape that caused it does not come back. `^\s*` at the start of a
# pattern is the tell: under MULTILINE it is an invitation to scan the file from
# every line, and what it always means is the indentation of one line.
offenders = []
for path in sorted(glob.glob(os.path.join(src, "ddw/scripts/*.py"))):
    body = open(path, encoding="utf-8").read()
    for m in re.finditer(r"""r f?["']\^\\s\*""".replace(" ", ""), body):
        offenders.append("%s:%d" % (os.path.basename(path), body[:m.start()].count("\n") + 1))
assert not offenders, ("these patterns anchor with `^\\s*` under MULTILINE, which is the shape "
                       "that hung: " + ", ".join(offenders))
PYSLOWRE

# `clock-time`, the second of the three findings that lost their verdict with the
# disk. The timestamp's SHAPE was checked and its VALUE was not, so an entry
# could be dated six years before the one above it and land without a word. The
# history is the one artefact this method promises will still make sense in six
# months, and a record that cannot be read in the order it happened is not one.
python3 - "$SELF" <<'PYCLOCK' && ok "the history cannot go backwards in time, and two transitions in the same second still can" || bad "an entry dated before the one above it lands, so the audit record cannot be read in order"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)
graph = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))
FIRST = {"timestamp": "2026-08-06T10:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a",
         "tier": "FEATURE", "ticket": "T-1"}


def land(ts):
    nxt = {"timestamp": ts, "from": "CLASSIFY", "to": "DEFINE", "action": "b",
           "tier": "FEATURE", "ticket": "T-1"}
    old = {"phase": "CLASSIFY", "ticket": "T-1", "tier": "FEATURE", "gates": {}, "history": [FIRST]}
    # The title is the fixture's, not the subject: this edge leaves CLASSIFY, so
    # without one the refusal that comes back is about the name and the check
    # reads a verdict it did not ask for.
    new = {"phase": "DEFINE", "ticket": "T-1", "tier": "FEATURE", "title": "the fixture ticket",
           "gates": {}, "history": [FIRST, nxt]}
    try:
        vt.validate(old, new, graph)
        return None
    except vt.Block as exc:
        return str(exc)


why = land("2020-01-01T00:00:00Z")
assert why, "an entry dated six years before the one above it was accepted"
assert "backwards" in why and "clock" in why, \
    "the refusal does not say what is wrong or what to do about it: " + why

# Equal is not backwards: two transitions inside one second are ordinary, and a
# clock with one-second resolution is not evidence of anything.
assert land("2026-08-06T10:00:00Z") is None, \
    "two entries stamped in the same second are refused — that is an ordinary run"
assert land("2026-08-06T10:00:01Z") is None, "an entry one second later is refused"
PYCLOCK

# `adapters-parity`: the suite asserts what reaches the gate for Cursor, for
# OpenCode and for Copilot (whose hook has no matcher at all, which is why the
# gate does the filtering). Codex and Gemini had none — and they are the two
# whose matchers a reviewer already had to reason about once, because a proposed
# "fix" to Codex's would have deleted the only shell matcher that tool
# recognises. What nothing asserted, nothing was holding.
#
# The shape is the same question in both: does a WRITE reach the pre hook, and
# does a SHELL reach the post one. The pre hook is what refuses; the post hook is
# what catches a state rewritten behind it, which is the documented limit of
# every pre matcher there is.
python3 - "$SELF" <<'PYPARITY' && ok "Codex and Gemini declare a write matcher on the gate and a shell matcher on the net, like the adapters that were already asserted" || bad "an adapter's matcher lets a write past the gate or a shell past the net, and no check was looking"
import json, os, sys
src = sys.argv[1]


def hooks_of(rel):
    """The hook table, whichever level the file keeps it at."""
    d = json.load(open(os.path.join(src, rel), encoding="utf-8"))
    return d.get("hooks", d)


# developers.openai.com/codex/hooks: shell commands match as `Bash`; edits made
# through apply_patch match `apply_patch`, `Edit` or `Write`. There is no tool
# called `shell`, which is what makes the Bash matcher the right one.
codex = hooks_of("adapters/codex/hooks.json")
pre = codex["PreToolUse"][0].get("matcher", "")
post = codex["PostToolUse"][0].get("matcher", "")
assert "apply_patch" in pre and "Write" in pre, \
    "codex PreToolUse matcher %r does not cover the ways that tool writes a file" % pre
assert "Bash" in post, \
    "codex PostToolUse matcher %r has no Bash: a state rewritten by a shell is what the net is for" % post
assert "Bash" not in pre, \
    "codex PreToolUse now matches Bash — the gate judges paths, and a shell command has none"

# gemini-cli docs: the write tools are `write_file` and `replace`; the shell is
# `run_shell_command`.
gemini = hooks_of("adapters/gemini/settings.json")
before = gemini["BeforeTool"][0].get("matcher", "")
after = gemini["AfterTool"][0].get("matcher", "")
assert "write_file" in before and "replace" in before, \
    "gemini BeforeTool matcher %r does not cover both of that tool's write verbs" % before
assert "run_shell_command" in after, \
    "gemini AfterTool matcher %r has no run_shell_command: nothing catches a state written by a shell" % after

# And both boot: a session that never loads the orchestrator enforces the parts
# that live in prose, which is none of them.
for name, h in (("codex", codex), ("gemini", gemini)):
    assert any(k.lower().startswith("session") for k in h), \
        "%s wires no session-start hook, so the pipeline never reaches the model" % name
PYPARITY

# `suite-inert`: a rule asserted in one direction only. Both warnings were
# checked for NOT firing — the lint result under its own heading, the block whose
# FR is in the coverage table — because both had been false positives once. That
# is half a check: delete the rule from the validator and both stay green, which
# is the same shape as an assertion over a list literal, one file further in.
python3 - "$SELF" <<'PYWARNPOS' && ok "the two warnings fire when they should, not only stay quiet when they should" || bad "a warning rule can be deleted outright and the suite goes green — it was only ever checked for silence"
import os, subprocess, sys, tempfile
src = sys.argv[1]
d = tempfile.mkdtemp(dir=os.environ["WORK"])
os.makedirs(os.path.join(d, "docs/ddw/reports"))
os.makedirs(os.path.join(d, "docs/ddw/specs"))
os.makedirs(os.path.join(d, "docs/ddw/prd"))


def run(script, doc, *extra):
    r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts", script), doc,
                        "--tier", "FEATURE", *extra], capture_output=True, text=True, cwd=d)
    return r.stdout + r.stderr


# W-TEST-01: a complete report that says nothing about a linter has to say so.
report = os.path.join(d, "docs/ddw/reports/tests-T-1.md")
open(report, "w", encoding="utf-8").write(
    "# Test run T-1\n\n| Field | Value |\n|---|---|\n| Runner | pytest 8.2 |\n"
    "| Command | `pytest -q` |\n| Total | 12 |\n| Passed | 12 |\n| Failed | 0 |\n"
    "| Skipped | 0 |\n| Line coverage | 91% |\n| Branch coverage | 88% |\n"
    "| Function coverage | 93% |\n| Coverage floor | 80% (AGENTS.md) |\n\n"
    "## Failures\nNone.\n")
out = run("validate_tests.py", report)
assert "W-TEST-01" in out, \
    "a report with no lint or type-check result did not raise W-TEST-01, so the rule is only " \
    "ever checked for staying quiet:\n" + out[-400:]

# W-SPEC-01: a block that traces to no FR, with no coverage row carrying it.
prd = os.path.join(d, "docs/ddw/prd/prd-T-2.md")
open(prd, "w", encoding="utf-8").write(
    "# PRD T-2\n\n## Functional Requirements\n- FR-01: the form\n\n"
    "## Acceptance Criteria\n- AC-01 (FR-01): WHEN a visitor opens it, THE system SHALL render it.\n")
spec = os.path.join(d, "docs/ddw/specs/spec-T-2.md")
open(spec, "w", encoding="utf-8").write(
    "# Spec T-2\n\n| Field | Value |\n|---|---|\n| Ticket | T-2 |\n\n"
    "## Block 1 — something nobody traced\n\n**Files**\n- `src/app.py`\n\n"
    "**Required tests**\n- [ ] test_it_renders — validates AC-01\n\n"
    "**Error handling**\n- the form is empty — 400 with the field named\n\n"
    "**Completion criterion**\nIt renders.\n")
out = run("validate_spec.py", spec, "--prd", prd)
assert "W-SPEC-01" in out, \
    "a block tracing to no FR did not raise W-SPEC-01:\n" + out[-400:]
PYWARNPOS

# `lifecycle-install`: the installer run against repositories built into the
# states nobody builds by hand. Eight of them; one bit. `.claude` as a FILE —
# a stray note, a redirect that went to the wrong name — reached `os.makedirs`
# halfway through and came out as a NotADirectoryError with the method already
# copied, no manifest and no hooks: a repository that looks installed, is not,
# and whose drift detector is off for good. The settings merge and the context
# file were both fixed for that shape; this was the third door into it.
#
# The refusal is asked BEFORE anything lands, and that is not tidiness either:
# the first version of this check ran after the method was copied and said
# "nothing was written", which was false as it printed.
python3 - "$SELF" <<'PYLIFECYCLE' && ok "an install refuses a path it needs and cannot have, before writing anything, and says which one" || bad "the installer crashes on a repo shaped oddly, or leaves a half-install behind while claiming it did not"
import glob, json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])


def repo(name):
    p = os.path.join(work, name)
    os.makedirs(p)
    subprocess.run(["git", "-C", p, "init", "-q"], check=True)
    return p


def install(p):
    return subprocess.run(["bash", os.path.join(src, "install.sh"), p, "--target", "claude"],
                          capture_output=True, text=True, timeout=180)


# The wiring directory, occupied by a file.
p = repo("claude-is-a-file")
open(os.path.join(p, ".claude"), "w", encoding="utf-8").write("not a directory\n")
before = sorted(os.listdir(p))
r = install(p)
out = r.stdout + r.stderr
assert "Traceback" not in out, "the installer answered a file named `.claude` with a stack:\n" + out[-400:]
assert r.returncode != 0, "the installer reported success on a repo it could not install into"
assert ".claude" in out and "directory" in out, \
    "the refusal does not name the path it needs: " + out[-300:]
assert sorted(os.listdir(p)) == before, (
    "the refusal says nothing has been written and something was: %s appeared"
    % sorted(set(os.listdir(p)) - set(before)))

# The LEAF of each wiring, occupied, with the ancestor healthy. Above,
# `.claude` gets occupied, which is the common ancestor of the four paths the
# preflight gathers for claude: breaking a single one changes nothing there, so
# the verification passed with the preflight looking at any subset. And
# `commands` was read in the singular where the installer writes it in the
# plural, so the directory of OpenCode's seventeen commands was never looked
# at. With that one occupied, the refusal that promises "nothing has been
# written" arrived after writing `.ddw/` and `AGENTS.md`, and with no manifest
# — that is, with the drift detector off forever.
for _rec in sorted(glob.glob(os.path.join(src, "adapters/*/adapter.json"))):
    _tool = os.path.basename(os.path.dirname(_rec))
    _r = json.load(open(_rec, encoding="utf-8")) or {}
    _leaves = [w.get("to") for w in (_r.get("wiring") or [])]
    _leaves += [(_r.get(_k) or {}).get("dir") for _k in ("skills", "agents", "commands")]
    for _leaf in sorted({l.strip("/") for l in _leaves if l}):
        _p = repo("leaf-%s-%s" % (_tool, _leaf.replace("/", "-")))
        os.makedirs(os.path.join(_p, os.path.dirname(_leaf)), exist_ok=True) \
            if os.path.dirname(_leaf) else None
        open(os.path.join(_p, _leaf), "w", encoding="utf-8").write("mío, no un directorio\n")
        _before = set()
        for _dp, _dn, _fn in os.walk(_p):
            if ".git" in _dp.split(os.sep):
                continue
            _before |= {os.path.relpath(os.path.join(_dp, f), _p) for f in _fn}
        _ir = subprocess.run(["bash", os.path.join(src, "install.sh"), _p, "--target", _tool],
                             capture_output=True, text=True, timeout=180)
        _out = _ir.stdout + _ir.stderr
        assert "Traceback" not in _out, \
            "%s: `%s` occupied answered with a stack:\n%s" % (_tool, _leaf, _out[-400:])
        assert _ir.returncode != 0, \
            "%s: the installation said it went fine with `%s` occupied by a file" % (_tool, _leaf)
        _after = set()
        for _dp, _dn, _fn in os.walk(_p):
            if ".git" in _dp.split(os.sep):
                continue
            _after |= {os.path.relpath(os.path.join(_dp, f), _p) for f in _fn}
        assert _after == _before, \
            ("%s: the refusal over `%s` says nothing was written and %s was — "
             "a half-done installation, and with no manifest nothing detects it afterwards"
             % (_tool, _leaf, sorted(_after - _before)[:5]))

# …and the ordinary repo still installs, or the guard has eaten the product.
ok_repo = repo("ordinary")
r = install(ok_repo)
assert r.returncode == 0, "a clean repo no longer installs: " + (r.stdout + r.stderr)[-300:]
assert os.path.isdir(os.path.join(ok_repo, ".claude", "skills")), "the wiring did not land"

# Two more shapes a real project arrives in, neither of which may end in a stack.
for name, build in (("gitignore-is-a-dir", lambda p: os.makedirs(os.path.join(p, ".gitignore"))),
                    ("manifest-is-a-list",
                     lambda p: open(os.path.join(p, ".ddw-installed.json"), "w").write("[1,2]"))):
    p = repo(name)
    build(p)
    out = install(p)
    assert "Traceback" not in (out.stdout + out.stderr), \
        "%s ends in a stack:\n%s" % (name, (out.stdout + out.stderr)[-300:])
PYLIFECYCLE

# `check_rule_ranges` demanded whitespace straight after `-01`, and every rule ID
# in this method's prose is written as code — so the one shape the files
# actually use was the one shape it could not see. It ran green over ranges that
# were all correct while `code.instructions.md` asked for F-TEST-01 to -06 with
# 07 and 08 implemented and never applied.
python3 - "$SELF" <<'PYRANGE' && ok "a rule range is read the way the method writes it — in backticks, in a skill as well as a rule file" || bad "a stale rule range written as code goes unseen, and the rules past its end are never applied"
import os, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
subprocess.run(["cp", "-r", src, os.path.join(work, "repo")], check=True)
repo = os.path.join(work, "repo")

def lint():
    r = subprocess.run([sys.executable, os.path.join(repo, "scripts/lint_method.py")],
                       capture_output=True, text=True, cwd=repo)
    return r.returncode, r.stdout + r.stderr

for rel in ("ddw/rules/code.instructions.md", "skills/ddw-test/SKILL.md"):
    path = os.path.join(repo, rel)
    text = open(path, encoding="utf-8").read()
    open(path, "a", encoding="utf-8").write("\n\nApply `F-VER-01` to `F-VER-04`.\n")
    code, out = lint()
    open(path, "w", encoding="utf-8").write(text)
    assert code != 0 and "F-VER" in out, \
        "a backticked range stopping short of the catalog passed in %s: %s" % (rel, out[-300:])

code, out = lint()
assert code == 0, "the probe was not restored: " + out[-300:]
PYRANGE

# ── The phase has to route to the skill, or the skill's trigger is unreachable ─
#
# `ddw-create-adr` said "the agent MUST create an ADR when it detects…" and the
# phase that would detect it never named the skill — so the condition lived
# inside a file the model reads only after deciding to invoke it, behind the
# decision it was meant to cause. Measured on a live run: the design chose a
# rate limit over a CAPTCHA, argued it well, and wrote nothing.
python3 - "$SELF" <<'PYADRROUTE' && ok "the phases that make decisions route to the ADR skill, so its trigger is reachable" || bad "a phase stopped naming ddw-create-adr, and the skill's own trigger is behind the decision it exists to catch"
import os, sys
src = sys.argv[1]
for rel in ("ddw/rules/plan.instructions.md", "ddw/rules/code.instructions.md"):
    text = open(os.path.join(src, rel), encoding="utf-8").read()
    assert "ddw-create-adr" in text, (
        "%s never names the ADR skill: nothing in the phase asks whether this decision needs "
        "one, and the skill's automatic trigger is written where only its own invocation "
        "reaches it" % rel)
PYADRROUTE

# ── The same question in six tools ────────────────────────────────────────────
#
# All six have something that turns a question into options the user picks from,
# and DDW named none of them. Measured: two models asked the same thing on the
# same repo, one offered a picker and the other prose, and neither was breaking
# a rule — the user got two different products.
python3 - "$SELF" <<'PYCHOICE' && ok "the rule that a choice is offered as a choice is written once, and every adapter names its own picker" || bad "an adapter stopped declaring how its tool asks, or the rule moved out of the orchestrator"
import glob, json, os, sys
src = sys.argv[1]
orch = open(os.path.join(src, "ddw/orchestrator.md"), encoding="utf-8").read()
assert "choice_prompt" in orch, (
    "the orchestrator no longer sends the model to the adapter for its tool's picker, so the "
    "rule is a name six recipes carry and nothing reads")
missing = []
for path in sorted(glob.glob(os.path.join(src, "adapters/*/adapter.json"))):
    d = json.load(open(path, encoding="utf-8"))
    cp = d.get("choice_prompt")
    if not isinstance(cp, dict) or not cp.get("tool"):
        missing.append(d.get("id") or os.path.basename(os.path.dirname(path)))
assert not missing, (
    "these adapters do not say how their tool asks a question with options, so the model has "
    "nothing to reach for and falls back to prose: " + ", ".join(missing))
PYCHOICE

# ── The turn that waits says so, and the picker cannot approve a gated act ────
#
# Measured on the first manual run: the moment the pipeline needed the user was
# marked with an arrow character among forty lines of summary, and the user
# asked for something they could not miss. And the obvious "make every
# confirmation a picker" is a trap: no hook receives a picker answer, so the
# turn counter holding the commit gate would never move and the gate would
# refuse the act the user just approved.
grep -q '^## Your turn' "$SELF/ddw/orchestrator.md" \
  && grep -q '🙋 YOUR TURN' "$SELF/ddw/orchestrator.md" \
  && ok "a response that ends waiting on the user ends in the banner that says so" \
  || bad "the orchestrator no longer tells the model how to mark the turn that waits, and the ask goes back to an arrow in the noise"
grep -q 'answered with a message, never with the picker' "$SELF/ddw/orchestrator.md" \
  && ok "the approvals the hooks measure are kept out of the picker no hook can see" \
  || bad "nothing stops a gated approval from moving into the picker, whose answer fires no event any hook receives"

# ── The arrow into CLASSIFY is taken by the request, not owed to the ok ───────
#
# Measured on two consecutive manual runs: the model classified while the state
# still said IDLE, so the user's single ok owed two transitions, the hook
# (correctly) landed one, and the second sat waiting for an ok that decided
# nothing — with the banner promising an arrow the enforcement could not let it
# deliver.
grep -q '^## Step 0: Enter the phase first' "$SELF/ddw/rules/classify.instructions.md" \
  && grep -q -- '--to CLASSIFY' "$SELF/ddw/rules/classify.instructions.md" \
  && ok "CLASSIFY is entered before the classification work, in the response that answers the request" \
  || bad "nothing tells the model when IDLE→CLASSIFY is written, so it defers the arrow and the user's ok owes two transitions"
grep -q 'in this same response, before the' "$SELF/ddw/orchestrator.md" \
  && ok "the orchestrator's IDLE section takes the arrow the user's request already approved" \
  || bad "the orchestrator went back to a timeless 'transition to CLASSIFY', and the extra ok that decides nothing returns"

# ── The banner promises one arrow, and a split child skips the rubber stamp ───
#
# Measured on the fourth manual run: one banner promised "commit + close the
# run + open in DEFINE", the hook (correctly) landed one arrow, and the user
# paid two extra oks. And the child's trip through CLASSIFY re-decided nothing:
# tier, ticket and autonomy all existed before it — the split that named the
# child was approved by the user, in a box, once.
grep -q 'promises at most ONE arrow' "$SELF/ddw/orchestrator.md" \
  && ok "the banner's promise is bounded to one arrow, said where every banner is defined" \
  || bad "nothing stops a banner from promising a chain the hook will refuse, and the user pays the difference in oks"
grep -q 'directly in the phase the split paused from' "$SELF/ddw/rules/define.instructions.md" \
  && grep -q -- '--action "split: abrir' "$SELF/ddw/rules/define.instructions.md" \
  && grep -q '_split_open_allowed' "$SELF/ddw/scripts/validate-transition.py" \
  && ok "the split child opens where the split paused, and the edge the prose orders is one the gate proves" \
  || bad "the Split Protocol and the validator disagree about how a child opens — prose ordering an edge the gate refuses is this repo's oldest defect"

# ── The merge keeps its confirmation, and now something holds it ──────────────
#
# Measured on the first end-to-end run: the user chose "merge" in a picker —
# which no hook receives — and `gh pr merge` ran mid-turn, ungated, while the
# local revertible commit had a byte-sealed gate. The prose had said "in both
# modes" since `minimal` existed; this is the pair that makes it true.
grep -q '_IS_PR_MERGE' "$SELF/ddw/scripts/hook-gate.py" \
  && grep -q 'confirms \*\*with a message\*\*' "$SELF/ddw/rules/closeout.instructions.md" \
  && ok "the merge is held by the same seal the commit is, and the closeout says so where the merge is chosen" \
  || bad "gh pr merge runs with no hook watching, or the closeout stopped saying the execution waits for a message"

# ── The PR is born answerable, and the closeout finishes what it started ──────
#
# Round 5 closed a ticket whose PR was a draft nobody could approve, whose body
# went through a shell heredoc no hook saw, whose integration box never plainly
# asked the one thing the user cared about — feedback, or merge? — and whose
# final index commit stayed stranded on the machine, one commit ahead of the
# PR it had just presented.
grep -Fq 'ready for review — NOT a draft' "$SELF/skills/ddw-create-pr/SKILL.md" \
  && ! grep -Fq 'ALWAYS create the PR as a **draft**' "$SELF/skills/ddw-create-pr/SKILL.md" \
  && grep -Fq -- '--body-file .ddw-work/pr-body.md' "$SELF/skills/ddw-create-pr/SKILL.md" \
  && grep -Fq 'never a shell heredoc' "$SELF/skills/ddw-create-pr/SKILL.md" \
  && ok "the PR is created ready for review, its body written with the Write tool and passed by file" \
  || bad "the PR is born a draft nobody can approve, or its body goes through a shell heredoc no hook sees"
grep -Fq 'Are you waiting for feedback on' "$SELF/ddw/rules/closeout.instructions.md" \
  && grep -Fq 'ready for review, not a draft' "$SELF/ddw/rules/closeout.instructions.md" \
  && ok "the integration step asks the user's actual question — waiting for feedback, or merge it now" \
  || bad "the integration box went back to jargon, and the feedback-or-merge decision hides behind option numbers"
grep -Fq 'Then push the branch.' "$SELF/ddw/rules/closeout.instructions.md" \
  && ok "the closeout pushes the index commit it makes after the PR, so the PR shows the whole ticket" \
  || bad "the closeout's own last commit strands on the machine again, and the PR reviews a branch already one commit stale"
grep -Fq 'And aim for balance.' "$SELF/ddw/rules/define.instructions.md" \
  && ok "the scope check aims for a balanced cut, and an over-ceiling part is approved knowingly or not at all" \
  || bad "an 11/6/2 cut sails through the scope check with nobody told the big part never shrank"

# ── The installation offers to commit itself, or says why it should have ─────
#
# Left uncommitted, the framework surfaces at the first closeout — whose commit
# gate demands a clean tree — and that ticket's PR carries all of it. Measured:
# 68 files of DDW inside a pull request about a web form. With a terminal the
# installer asks; without one it warns; a repo without git hears nothing.
grep -q 'Commit the installation now?' "$SELF/install.sh" \
  && grep -q 'this repo is git-tracked and the installation is not committed' "$SELF/install.sh" \
  && grep -q 'offers to commit the installation' "$SELF/docs/INSTALL.md" \
  && ok "the installer offers to commit exactly what it wrote, and warns when it cannot ask" \
  || bad "the installation is left uncommitted in silence again, and the first ticket's PR will carry the framework"
grep -Fq 'Where should the $DDW_LANDS land?' "$SELF/install.sh" \
  && grep -q 'ddw-setup-' "$SELF/install.sh" \
  && grep -q 'DDW_GIT_FLOW' "$SELF/install.sh" \
  && ok "a fresh install asks where it lands — setup branch, current branch, or files only — before writing" \
  || bad "the installer stopped asking where the installation lands, and it goes back to landing on whatever branch the user happened to be on"
# And the same question RUN rather than grepped. `grep -q 'ddw-setup-'` proves
# somebody typed the string; it does not reach the line that builds the name —
# and no check in this file ever had. Every install here ran against a bare
# `git init`, so `rev-parse --verify HEAD` failed and the whole git-flow block
# was skipped. The line underneath was `tr -dc 'a-f0-9' < /dev/urandom | head`,
# which hangs forever on macOS: the installer stopped dead in any repository
# with a commit in it, on the platform this suite has run on since the
# beginning, and the run said nothing because a hung job reports "cancelled".
#
# Driven through python for the timeout: `timeout(1)` is GNU, and this check
# exists precisely for the platform that does not have it. A hang has to come
# back as a sentence, not as a dead runner.
python3 - "$SELF" <<'PYSETUPBRANCH' && ok "an install into a repository that has commits lands on a fresh ddw-setup-<hex> branch, finishes, and names a different branch every time" || bad "the installer hangs, fails, or cannot name the setup branch it stops to offer — on a repo with a commit, which is every repo anyone installs into"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
seen = set()
for _ in range(2):
    d = tempfile.mkdtemp(dir=os.environ["WORK"])
    repo, home = os.path.join(d, "repo"), os.path.join(d, "home")
    os.makedirs(repo); os.makedirs(home)
    git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    git("init", "-q")
    for k, v in (("user.email", "e@example.com"), ("user.name", "e"), ("commit.gpgsign", "false")):
        git("config", k, v)
    open(os.path.join(repo, "README.md"), "w", encoding="utf-8").write("# fixture\n")
    git("add", "-A"); git("commit", "-qm", "init")
    env = dict(os.environ, HOME=home, DDW_GIT_FLOW="setup")
    env.pop("CLAUDE_PROJECT_DIR", None)
    try:
        r = subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                           capture_output=True, text=True, env=env, timeout=180)
    except subprocess.TimeoutExpired:
        raise AssertionError(
            "install.sh never finished on a git repository with a commit. The setup branch is "
            "named BEFORE the question it is named for, so this hangs ahead of any prompt and "
            "the user sees the installer stop with nothing said.")
    assert r.returncode == 0, "the install failed: " + (r.stdout + r.stderr)[-400:]
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert re.fullmatch(r"ddw-setup-[0-9a-f]{6}", branch), \
        "the install did not land on a setup branch of the shape it offers: %r" % branch
    seen.add(branch)
# Random, not a constant with a hexadecimal look: two installs on the same day
# must not collide on the branch they create.
assert len(seen) == 2, "two installs produced the same setup branch name: %s" % sorted(seen)
PYSETUPBRANCH

# ── An UPDATE is asked the same question, and reported the same way ──────────
#
# Reported from real use, and true: the question above was gated on
# `[ -z "$INSTALLED" ]`, so a refresh never asked it and committed onto whatever
# branch you were standing on. Run mid-ticket, the whole framework landed on
# that ticket's branch — the exact failure the question exists to prevent, and
# one that already cost a pull request 66 framework files. The reasoning for
# skipping it ("a new branch per refresh would be noise") holds while you are on
# the branch DDW lives on and nowhere else.
#
# Both halves are driven, because the cure has its own failure: a refresh that
# writes nothing must not leave you standing on a branch made for a commit that
# never happened.
python3 - "$SELF" <<'PYUPDATEFLOW' && ok "an update asks where it lands like a first install does, commits under its own name, and a refresh that changes nothing puts you back where you were with no empty branch left behind" || bad "an update commits onto the branch you were working on, calls itself an install in the log, or strands you on a setup branch it made for a commit it never wrote"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
d = tempfile.mkdtemp(dir=os.environ["WORK"])
repo, home = os.path.join(d, "repo"), os.path.join(d, "home")
os.makedirs(repo); os.makedirs(home)
git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
git("init", "-q")
for k, v in (("user.email", "e@example.com"), ("user.name", "e"), ("commit.gpgsign", "false")):
    git("config", k, v)
open(os.path.join(repo, "README.md"), "w", encoding="utf-8").write("# fixture\n")
git("add", "-A"); git("commit", "-qm", "init")


def install(flow):
    env = dict(os.environ, HOME=home, DDW_GIT_FLOW=flow)
    env.pop("CLAUDE_PROJECT_DIR", None)
    r = subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                       capture_output=True, text=True, env=env, timeout=240)
    assert r.returncode == 0, "the install failed: " + (r.stdout + r.stderr)[-400:]
    return r


branch = lambda: git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

install("current")
# Standing on a ticket's branch, which is where the defect bites.
git("checkout", "-q", "-b", "feat/T-1")
open(os.path.join(repo, "src.py"), "w", encoding="utf-8").write("x = 1\n")
git("add", "-A"); git("commit", "-qm", "the ticket's own work")
# Something for the update to actually rewrite.
open(os.path.join(repo, ".ddw", "orchestrator.md"), "a", encoding="utf-8").write("\n<!-- drift -->\n")
git("add", "-A"); git("commit", "-qm", "drift")

install("setup")
landed = branch()
assert re.fullmatch(r"ddw-setup-[0-9a-f]{6}", landed), \
    "the update landed on %r — the ticket's own branch — instead of a setup branch of its own" % landed
message = git("log", "-1", "--format=%s").stdout.strip()
assert message.startswith("\U0001F527 chore(ddw): update DDW to"), \
    "the update's commit calls itself an install: %r" % message

# And the same run again, with nothing left to write.
here = branch()
before = set(git("branch", "--format=%(refname:short)").stdout.split())
out = install("setup").stdout
assert branch() == here, \
    "a refresh that wrote nothing moved you to %r and left you there" % branch()
left = set(git("branch", "--format=%(refname:short)").stdout.split()) - before
assert not left, "a refresh that wrote nothing left an empty setup branch behind: %s" % sorted(left)
assert "Nothing changed" in out, \
    "it went back silently, so the branch that appeared and vanished has no explanation:\n" + out[-400:]
PYUPDATEFLOW

# The one commit path this file cannot drive — the standing offer, which reads
# the answer from /dev/tty and is reached only by a git repo with no commit in
# it — read structurally rather than run. It was the only one of the three that
# printed a bare sha: it never said WHICH branch took the commit and never said
# the remote did not have it, while both others did.
python3 - "$SELF" <<'PYSTANDINGOFFER' && ok "the standing commit offer names the branch it committed on and warns the commit is not on the remote, like the two paths beside it" || bad "the standing offer commits and says only a sha — no branch, no warning that the first ticket's PR will drag it along"
import os, re, sys
src = open(os.path.join(sys.argv[1], "install.sh"), encoding="utf-8").read()
start = src.index("Commit the installation now?")
# Its own `case`, and no further: the paths beside it must not be what answers.
end = src.index("      esac", start)
offer = src[start:end]
assert "ddw_warn_unpushed" in offer, \
    "the standing offer commits without warning that the commit is not on the remote"
assert "--abbrev-ref HEAD" in offer, \
    "the standing offer does not name the branch its commit landed on"
PYSTANDINGOFFER
# Round 5's expensive lesson: the commit landed — on the LOCAL default branch —
# and nobody pushed it. The ticket branched off that base, and its PR showed 66
# framework files to the feature's reviewer. Committing was never the whole
# job; reaching the remote is.
grep -Fq 'THIS COMMIT IS NOT ON YOUR REMOTE' "$SELF/install.sh" \
  && grep -Fq 'Push %s to origin now?' "$SELF/install.sh" \
  && ok "an installation committed on the current branch offers the push, and declined, warns that the commit must reach the remote before the first ticket" \
  || bad "the installer went quiet about a commit the remote never got — that silence already cost a PR 66 framework files"
grep -Fq 'Two questions come BEFORE the branch exists' "$SELF/ddw/rules/branches.instructions.md" \
  && grep -Fq 'git rev-list --count origin/{base}..{base}' "$SELF/ddw/rules/branches.instructions.md" \
  && ok "creating the ticket branch asks about a non-default base and stops on local-only commits the PR would drag along" \
  || bad "the branch gets created from whatever base happens to be checked out, and local-only commits ride into the ticket's PR unannounced"

# Reconstructing the state from an Edit whose old_string appears more than once
# means guessing which occurrence was meant — and the guess decides what gets
# validated. Nothing exercised the refusal.
python3 - "$SELF" <<'PYAMBIG' && ok "an Edit to the state with an ambiguous old_string is refused unless it says replace_all" || bad "the state is reconstructed from a guess about which occurrence the model meant"
import importlib.util, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
OLD = '{"phase": "CODE", "a": "x", "b": "x"}'
try:
    m._reconstruct_new_text("Edit", {"old_string": '"x"', "new_string": '"y"'}, OLD)
    raise AssertionError("an ambiguous Edit was reconstructed by picking an occurrence")
except m.Block as exc:
    assert "replace_all" in str(exc), "the refusal does not name what resolves it: %s" % exc
# …and it is allowed once the write says which it meant.
out = m._reconstruct_new_text("Edit", {"old_string": '"x"', "new_string": '"y"',
                                       "replace_all": True}, OLD)
assert out.count('"y"') == 2, "replace_all did not replace both occurrences: %r" % out
# An unambiguous one still works, and an absent old_string cannot be replayed.
one = m._reconstruct_new_text("Edit", {"old_string": '"CODE"', "new_string": '"VERIFY"'}, OLD)
assert '"VERIFY"' in one, "an unambiguous Edit was refused"
try:
    m._reconstruct_new_text("Edit", {"old_string": "nowhere", "new_string": "z"}, OLD)
    raise AssertionError("an Edit whose old_string is absent produced a state anyway")
except m.Block:
    pass
PYAMBIG

# Reinstalling on top must be as clean as the first time.
bash "$SELF/install.sh" "$UN" --target claude >/dev/null 2>&1
[ -d "$UN/.ddw" ] && [ -f "$UN/CLAUDE.md" ] && grep -q "MY OWN HOOK" "$UN/.claude/settings.json" \
  && ok "and installing again afterwards works, still without touching what is yours" \
  || bad "a repo cannot be reinstalled cleanly after an uninstall"

# What a SECOND version does, which nothing here had ever driven: the same repo,
# upgraded by a DDW that ships something the first one did not. Two defects
# lived in that gap, and the second one leaves a repo nobody can leave.
python3 - "$SELF" <<'PYSECONDVERSION' && ok "an upgrade leaves a file of yours alone at a path DDW starts shipping, rewires a renamed hook instead of stacking it, and the uninstall after it leaves nothing pointing at a deleted script" || bad "a second version of DDW overwrites a file of yours, or leaves the repo wired to a hook script that no longer exists"
import json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
# A copy of DDW to play the part of the NEXT release: the shipped tree is what
# every other check reads, and this one has to change what is shipped.
nxt = os.path.join(work, "ddw-next")
shutil.copytree(src, nxt, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))


def install(repo, root=src):
    return subprocess.run(["bash", os.path.join(root, "install.sh"), repo, "--target", "claude"],
                          capture_output=True, text=True)


def blocks(repo, event="PreToolUse"):
    path = os.path.join(repo, ".claude", "settings.json")
    if not os.path.exists(path):
        return None
    return (json.load(open(path, encoding="utf-8")).get("hooks") or {}).get(event) or []


# 1. A file of yours at a path this version does not ship and the next one does.
repo = os.path.join(work, "yours")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
install(repo)
mine = os.path.join(repo, ".claude", "hooks", "audit.sh")
open(mine, "w", encoding="utf-8").write("MY OWN AUDIT HOOK\n")
open(os.path.join(nxt, "adapters", "claude", "hooks", "audit.sh"), "w",
     encoding="utf-8").write("#!/usr/bin/env bash\n# DDW's own audit hook\n")
r = install(repo, nxt)
assert "MY OWN AUDIT HOOK" in open(mine, encoding="utf-8").read(), (
    "the upgrade overwrote a file the user had at a path the new version starts shipping — "
    "`ours_if_unknown` asked whether the TOOL had been installed, and the answer stays yes "
    "forever:\n" + r.stdout[-300:])
assert "audit.sh" in r.stdout, "the file was kept and the run never said so: " + r.stdout[-300:]
os.remove(os.path.join(nxt, "adapters", "claude", "hooks", "audit.sh"))

# 2. A hook script the next version renames. The block naming the old one is
#    DDW's, whichever version wired it — so the upgrade takes it out instead of
#    stacking a second one beside it.
repo = os.path.join(work, "renamed")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
install(repo)
before = len(blocks(repo))
assert before >= 2, "the fixture repo has no PreToolUse blocks to renumber"
settings = os.path.join(nxt, "adapters", "claude", "settings.json")
text = open(settings, encoding="utf-8").read().replace("enforce.sh", "housekeeping.sh")
with open(settings, "w", encoding="utf-8") as fh:
    fh.write(text)
shutil.move(os.path.join(nxt, "adapters", "claude", "hooks", "enforce.sh"),
            os.path.join(nxt, "adapters", "claude", "hooks", "housekeeping.sh"))
r = install(repo, nxt)
after = blocks(repo)
assert len(after) == before, (
    "the upgrade stacked the renamed hook beside the old one (%d → %d): the repo now runs a "
    "block naming a script the next uninstall deletes" % (before, len(after)))
assert not any("enforce.sh" in json.dumps(b) for b in after), \
    "the block naming the script this version no longer ships is still wired: " + json.dumps(after)[:200]

# 3. …and the uninstall after that upgrade leaves nothing behind. Byte-for-byte
#    against what the CURRENT version ships answers "is this block ours?" only
#    for the version asking, so a block from before survived while the script it
#    names was deleted — every write failing on a command not found, with DDW
#    gone and nothing left to explain it.
subprocess.run(["bash", os.path.join(nxt, "uninstall.sh"), repo, "--yes"],
               capture_output=True, text=True)
left = blocks(repo)
assert not left, (
    "the uninstall left %d hook block(s) behind: %s" % (len(left or []), json.dumps(left)[:200]))
for name in ("enforce.sh", "housekeeping.sh"):
    assert not os.path.exists(os.path.join(repo, ".claude", "hooks", name)), \
        "%s survived the uninstall" % name
PYSECONDVERSION

# ── Stale bases and branches that land nowhere ────────────────────────────────
#
# These assert that an instruction is present in the file the model loads for
# that phase. That is the whole of what is testable about a rule made of prose —
# and it is not nothing: every one of these was absent once, and its absence is
# what let a branch be cut from a stale base, or a ticket close leaving its work
# stranded on a branch nobody would ever merge.
section "The pipeline never builds on a stale base, and never strands a branch"

BR="$SELF/ddw/rules/branches.instructions.md"
REL="$SELF/ddw/rules/closeout.instructions.md"
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
# The drop-in row specifically, and only the five observation columns in it. The
# row grew a `mode` column and a sixth observation; matching the whole line for
# `| — |` then read "minimal not driven yet" as "check 4 not driven yet" and
# called the README a liar. A check that reads a table by pattern instead of by
# column breaks the first time the table earns a column — which it will, because
# the ritual grows every time it finds something.
python3 - "$SELF" <<'PYCLAUDE' && ok "the README claims for Claude exactly what the record holds" || bad "README status vs the Claude drop-in row — see above"
import os, re, sys
root = sys.argv[1]
acc = open(os.path.join(root, "scripts/acceptance.md"), encoding="utf-8").read()
readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in acc.splitlines() if ln.strip().startswith("|")]
header = next((r for r in rows if r and r[0] == "Tool"), None)
assert header, "acceptance.md has no record table"
first = next(i for i, h in enumerate(header) if h.startswith("1."))
# EVERY numbered column, not the first five. The ritual grew a sixth check and
# this bound stayed at `[1-5]`, so the row the README summarises was read one
# column short: the record said five ✅ and one —, the guard called that
# complete, and the README's "all five" agreed with a count nobody was taking
# any more. A range hardcoded next to the thing it measures ages the moment the
# thing grows.
numbered = [i for i, h in enumerate(header) if re.match(r"^\d+\.", h)]
last = max(numbered)
row = next((r for r in rows if r[0] == "Claude Code" and r[1] == "drop-in"), None)
assert row, "no Claude Code drop-in row in the record"
verdicts = row[first:last + 1]
passed = sum("✅" in v for v in verdicts)
complete = passed == len(verdicts)
# The claim has to name the number the record holds, whatever that number is.
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
claims_all = "all %s acceptance checks pass" % WORDS.get(len(verdicts), len(verdicts)) in readme
assert complete == claims_all, (
    f"the record has {passed}/{len(verdicts)} for Claude drop-in and the README "
    f"{'claims' if claims_all else 'does not claim'} all {WORDS.get(len(verdicts))}")
if not complete:
    claimed = re.search(r"\*\*(\w+) of the (\w+) acceptance checks pass", readme)
    assert claimed, (
        f"{passed} of {len(verdicts)} acceptance checks pass for Claude drop-in and the README "
        "does not say so in those words — a status section that rounds up is the one place a "
        "reader cannot check for themselves")
    assert WORDS.get(passed) == claimed.group(1) and WORDS.get(len(verdicts)) == claimed.group(2), \
        (f"the README says {claimed.group(1)} of {claimed.group(2)} and the record says "
         f"{WORDS.get(passed)} of {WORDS.get(len(verdicts))}")
PYCLAUDE

# A step that dies at its first command never ran, and a step that only runs on
# pull requests dies unwatched in a repository whose work lands on main. Both
# pull-request-only steps carried `git fetch --depth=0` — not "no limit" but
# `fatal: depth 0 is not a positive number` — so the version rule and the
# attribution rule had never once been applied to a pull request. It surfaced on
# the first one this repository ever opened, which is the whole argument for
# opening one.
python3 - "$SELF" <<'PYFETCH' && ok "CI's pull-request fetch is a command git will actually run" || bad "a fetch in verify.yml cannot execute, so the step that needs it has never run"
import os, re, sys
y = open(os.path.join(sys.argv[1], ".github/workflows/verify.yml"), encoding="utf-8").read()
bad = re.findall(r"git fetch[^\n]*--depth=0[^\n]*", y)
assert not bad, ("`--depth=0` is an error, not a depth: " + "; ".join(bad))
fetches = re.findall(r"git fetch[^\n]*", y)
assert fetches, "no fetch at all: the ranged checks have nothing to diff against"
for f in fetches:
    assert "--depth" not in f or re.search(r"--depth=[1-9]", f), f"unusable depth in: {f}"
PYFETCH

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
  && ok "CLOSEOUT asks where the branch lands before it closes the ticket" \
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

# Its own directory. `$WORK/upgrade` is also where the earlier section left a
# repo with DDW installed and a user-edited skill in it, so the "first install"
# below was this fixture's THIRD — and every assertion about what a first run
# says was being made about an update.
UPG="$WORK/upgrade-messages"; mkdir -p "$UPG"; git -C "$UPG" init -q .
FIRST="$(bash "$SELF/install.sh" "$UPG" --target claude 2>&1)"
# Both directions. Only one was asserted, so an installer that called EVERY run
# an update — a one-character edit away — passed the suite: the re-run below
# said "updating:" because every run did.
case "$FIRST" in
  *"updating:"*) bad "a first install into a virgin repo reports itself as an update" ;;
  *"installing into"*) ok "a first install says it is installing, in a repo that had nothing" ;;
  *) bad "a first install says neither that it is installing nor that it is updating" ;;
esac

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

# ── The line somebody pastes has to BE the installer ─────────────────────────
#
# `install.sh` copies `ddw/`, `adapters/`, `scripts/` and the manifest out of its
# own tree, so pasted from a URL it has none of the four. It used to die on
# `${BASH_SOURCE[0]}` — unset under `bash -s`, and under `set -u` that is an
# "unbound variable" with not one word about what happened. The plugin path was
# already one line; the drop-in path, which is the only door three of the six
# tools have, asked you to clone first.
#
# Offline on purpose: the tarball is built from this tree and served over
# `file://`. A check that reaches the network measures GitHub's morning.
python3 - "$SELF" <<'PYBOOT' && ok "install.sh run with no tree around it fetches the method and installs from it" || bad "the installer pasted from a URL cannot install — the drop-in path still requires cloning first"
import os, shutil, subprocess, sys, tarfile, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
tar = os.path.join(work, "ddw.tar.gz")
with tarfile.open(tar, "w:gz") as t:
    t.add(src, arcname="dilux-development-workflow-main",
          filter=lambda ti: None if "/.git/" in ti.name + "/" else ti)
alone = os.path.join(work, "alone")
os.makedirs(alone)
shutil.copy(os.path.join(src, "install.sh"), os.path.join(alone, "install.sh"))
repo = os.path.join(work, "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
env = dict(os.environ, DDW_TARBALL="file://" + tar, DDW_GIT_FLOW="none")
r = subprocess.run(["bash", os.path.join(alone, "install.sh"), repo, "--target", "claude",
                    "--mode", "dropin"], capture_output=True, text=True, env=env, timeout=300)
assert r.returncode == 0, "the pasted installer failed: " + (r.stdout + r.stderr)[-400:]
assert os.path.isdir(os.path.join(repo, ".ddw")), \
    "it reported success and the method is not there: " + r.stdout[-300:]
# And it does not leave the tree it downloaded behind.
assert not [d for d in os.listdir(work) if d.startswith("tmp")], \
    "the bootstrap left its download in place: %s" % os.listdir(work)
PYBOOT

# ── Whether to ASK is not a question about stdin ─────────────────────────────
#
# Every read in the installer reads `/dev/tty`, and that is right: under
# `curl | bash`, stdin is the script itself. But the three decisions of WHETHER
# to ask tested `[ -t 0 ]`, which is stdin — so with the installer arriving down
# a pipe, with the terminal right there, it went non-interactive in silence: it
# picked a mode without saying so and skipped the whole question of where the
# installation lands. The probe is the real shape: stdin is a pipe, a
# controlling terminal exists, and the answer travels over the terminal.
python3 - "$SELF" <<'PYTTY' && ok "the installer asks when a terminal exists, even though stdin is the pipe it arrived down" || bad "piped in, the installer decides the mode and the git flow by itself and never says it did"
import fcntl, os, pty, signal, subprocess, sys, tarfile, tempfile, termios, threading, time
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
tar = os.path.join(work, "ddw.tar.gz")
with tarfile.open(tar, "w:gz") as t:
    t.add(src, arcname="dilux-development-workflow-main",
          filter=lambda ti: None if "/.git/" in ti.name + "/" else ti)
repo = os.path.join(work, "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
script = open(os.path.join(src, "install.sh"), encoding="utf-8").read()

master, slave = pty.openpty()
name = os.ttyname(slave)


def preexec():
    os.setsid()
    # Without O_NOCTTY, and then the ioctl: Linux takes it on the open, the
    # BSDs (macOS is one) demand TIOCSCTTY and without it `/dev/tty` does not
    # open. It cost an entire CI run to discover, because the probe hung for
    # five minutes and did not say what it had seen.
    fd = os.open(name, os.O_RDWR)
    try:
        fcntl.ioctl(fd, termios.TIOCSCTTY, 0)
    except OSError:
        pass
    os.close(fd)


env = dict(os.environ, DDW_TARBALL="file://" + tar, DDW_GIT_FLOW="none")
p = subprocess.Popen(["bash", "-s", "--", repo, "--target", "claude"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, preexec_fn=preexec, env=env)
seen = []
# Read RAW, not by lines, and that is the correction that cost two macOS runs:
# a prompt does not end in a newline (`printf "… [y/N] "`), so iterating lines
# the question never shows up — and the only thing visible is a child that does
# not advance, without saying what it is waiting for. A check about questions
# that cannot see a question mid-line is looking the other way.
_fd = p.stdout.fileno()


def drain():
    while True:
        try:
            chunk = os.read(_fd, 4096)
        except OSError:
            return
        if not chunk:
            return
        seen.append(chunk.decode("utf-8", "replace"))


threading.Thread(target=drain, daemon=True).start()


def feed():
    try:
        p.stdin.write(script)
        p.stdin.flush()
        p.stdin.close()
    except (BrokenPipeError, ValueError):
        pass


threading.Thread(target=feed, daemon=True).start()

# Answer when the question appears; and if at twenty seconds it has not,
# answer anyway. What this verification asserts is NOT "I saw the question in
# time" — that is a race against a pipe's buffer, and losing it hung for five
# minutes — but "the question is in what it printed". Asserted at the end,
# over everything captured.
QUESTION = "How do you want DDW installed?"

# What this verification asserts is that it ASKS, and that it uses the answer.
# Neither needs the process to finish — and waiting for it is what cost four
# macOS runs, where `poll()` said alive and `getpgid` of the same pid answered
# "no such process": that accuses the harness, not the product, and is not
# what this check is looking at. So the screen is looked at and the disk is
# looked at, which are the two halves of the assertion, and then it is killed.
sent = False
landed = False
nudged = 0.0
deadline = time.time() + 90
while time.time() < deadline:
    now = time.time()
    if not sent and QUESTION in "".join(seen):
        os.write(master, b"2\n")
        sent = True
        nudged = now
    elif sent and now - nudged > 2:
        # The default to whatever comes after: the installer offers to commit
        # and offers to push, and both wait on `/dev/tty`.
        os.write(master, b"\n")
        nudged = now
    if sent and os.path.isdir(os.path.join(repo, ".ddw")):
        landed = True
        break
    time.sleep(0.2)
out = "".join(seen)

# Best-effort, and by group: the child is a session leader — that is what
# gives it the controlling terminal — and it started a second bash for the
# bootstrap. Killing the pid leaves the grandchild alive with the pipe open.
# None of this may throw away the diagnosis, which is already assembled.
try:
    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
except OSError:
    try:
        p.kill()
    except OSError:
        pass
try:
    p.wait(timeout=30)
except Exception:                                 # noqa: BLE001 — es la limpieza
    pass
for _fd in (master, slave):
    try:
        os.close(_fd)
    except OSError:
        pass

assert QUESTION in out, \
    ("it never asked which way in, and answered for the user. What it printed:\n"
     + (out[-1200:] or "nothing at all"))
assert landed, ("it asked, and the answer given over the terminal was not the one it used: "
                "no .ddw after ninety seconds. What it printed:\n" + out[-1200:])
PYTTY

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
python3 - "$SELF" "$VP" <<'PYDEMAND' && ok "and every validator PRINTS the demand under the table it produced, where the model is already looking" || bad "a validator's table goes out with nothing telling anyone to show it — see above"
import os, subprocess, sys
src, repo = sys.argv[1], sys.argv[2]
DEMAND = "Show the user this table IN FULL"
cases = [("validate_prd.py", "docs/ddw/prd/prd-FEAT-001.md"),
         ("validate_spec.py", "docs/ddw/specs/spec-FEAT-001.md"),
         ("validate_threat.py", "docs/ddw/security/threat-FEAT-001.md"),
         ("validate_verify.py", "docs/ddw/reports/verify-FEAT-001.md"),
         ("validate_sast.py", "docs/ddw/security/sast-FEAT-001.md"),
         ("validate_tests.py", "docs/ddw/reports/tests-FEAT-001.md")]
missing, examined, skipped = [], [], []
for script, artifact in cases:
    path = os.path.join(repo, artifact)
    if not os.path.exists(path):
        skipped.append(artifact)      # fixture not built in this section
        continue
    examined.append(script)
    out = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts", script), path,
                          "--tier", "FEATURE"], capture_output=True, text=True)
    if DEMAND not in out.stdout:
        missing.append(script)
# `assert cases` was the guard here, over a list literal three lines up: it can
# only ever be true. Every fixture could be absent, every validator skipped, and
# the check went green having run none of them — which is the shape of a suite
# that measures nothing while reporting a pass. What has to be true is that the
# validators were actually asked.
assert not skipped, ("these fixtures are not on disk, so their validator was never asked whether "
                     "it prints the demand: " + ", ".join(skipped))
assert len(examined) == len(cases), "expected %d validators, examined %d" % (len(cases), len(examined))
assert not missing, ("these validators printed a checklist and nothing telling the user it has to "
                     "be shown: " + ", ".join(missing))
PYDEMAND

# In the catalog AND in each skill: the skill is what the model loads and
# executes. The one that collapsed the table had read the skill, not the catalog.
VRMISS=""
# Derived, not typed: the six skills that own a receipt gate are the six the
# validators write for, and a list maintained by hand named four of them.
for S in $(python3 - "$SELF" <<'PYVRLIST'
import os, re, sys
vt = open(os.path.join(sys.argv[1], "ddw/scripts/validate-transition.py"), encoding="utf-8").read()
GATE_SKILL = {"define": "ddw-validate-prd", "spec": "ddw-validate-spec",
              "threat": "ddw-threat-modeling", "verify": "ddw-verify-module",
              "tests": "ddw-test", "sast": "ddw-security-sast"}
# dict.fromkeys, not a set: a gate may have more than one call site (the
# `define` gate resolves three documents, one per tier) and the answer is the
# six GATES, in a stable order.
print(" ".join(GATE_SKILL[g] for g in
                dict.fromkeys(re.findall(r'_receipt_missing\(root, state, "(\w+)"', vt))))
PYVRLIST
); do
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
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "CLOSEOUT", "to": "IDLE",
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
markers = os.path.join(repo, ".ddw-sessions", "live")
os.makedirs(markers, exist_ok=True)
# One `..` only reaches `.ddw-sessions/` now that the markers have a namespace of
# their own, and asking whether the STATE survived stopped being the question:
# the id has to stay inside the markers' directory, whatever it is shaped like.
# Two levels up is where the state lives, and that is the id the old fixture was
# one directory short of.
for evil in ("../.ddw-state.json", "../../.ddw-state.json", "../../../etc/passwd",
             "a/b/c", "..", "."):
    json.dump(live, open(state, "w"))
    before = sorted(p for p in os.listdir(os.path.join(repo, ".ddw-sessions")) if p != "live")
    subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", evil],
                   capture_output=True, text=True)
    back = json.load(open(state))
    assert back.get("ticket") == "FEAT-001", f"session id {evil!r} clobbered the state"
    assert sorted(p for p in os.listdir(os.path.join(repo, ".ddw-sessions"))
                  if p != "live") == before, \
        f"session id {evil!r} wrote outside .ddw-sessions/live/"
    for name in os.listdir(markers):
        assert os.path.realpath(os.path.join(markers, name)).startswith(
            os.path.realpath(markers) + os.sep), \
            f"session id {evil!r} left a marker that points out of its own directory"
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

# The classify edge's context check — a different gate than the lock under
# test, satisfied so the legal-move assertions below measure the lock alone.
os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
open(os.path.join(repo, ".ddw-work", "context-check.md"), "w", encoding="utf-8").write(
    "Nothing to report.\n")

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

mid = {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {"define": True},
       "history": [h("IDLE", "CLASSIFY"), h("CLASSIFY", "DEFINE", "FEATURE")]}

# A write that appends no history entry can still change the tier, and that was
# the whole exploit: flip to QUICK-FIX, then take its shortcut and reach CLOSEOUT
# without PLAN, VERIFY, spec, threat or verify. Post mode replays against the
# FINAL tier, under which the path is legal, so it never noticed.
hop = dict(mid); hop["tier"] = "QUICK-FIX"
assert rc(mid, hop) == 2, "a FEATURE hopped tier mid-run and can walk QUICK-FIX's shortcut"

# Falsy-but-not-null poison: it resolved to the previous tier (so every check
# passed) while landing on disk and making the lock's own truthiness test false.
for poison in ("", [], 0, False):
    bad_tier = dict(mid); bad_tier["tier"] = poison
    assert rc(mid, bad_tier) == 2, f"tier={poison!r} was accepted and disarms the lock"

# `null` is the same poison wearing the one costume the check let past: it is
# the value a caller may legitimately send to mean "unchanged", so it resolved
# to the old tier, every comparison passed — and it LANDED. Two writes, neither
# appending history, neither saying anything, both exit 0, and a FEATURE in
# DEFINE is a QUICK-FIX that skips PLAN and VERIFY. Driven as the two writes it
# actually takes, because each one alone looks like nothing. Omitting the key
# is the same state by another spelling, so it is asked the same way.
#
# The second write is what makes the first one worth refusing, and it is asked
# about here so the reason this closes is on the record: from a tier-less state
# the lock has nothing to compare and accepts anything. That write is NOT
# refused by shape — a tier legitimately reappears from nothing when a paused
# ticket resumes out of IDLE, and refusing it there would strand every pause —
# so what has to hold is that no write can produce the state it starts from.
for drop in (lambda s: dict(s, tier=None), lambda s: {k: v for k, v in s.items() if k != "tier"}):
    dropped = drop(mid)
    assert rc(mid, dropped) == 2, \
        "a write dropped the tier mid-ticket: the next write then sets any tier, unchecked"
    assert rc(dropped, dict(dropped, tier="QUICK-FIX")) == 0, \
        "this is the write the one above exists to keep unreachable; if it now fails on its " \
        "own, say so here rather than leaving the refusal above resting on a stale reason"

# An idle state carries no ticket — every time it is written, not only on the
# edge that lands there. Otherwise the next write re-plants a full set of gates.
idle = {"tier": None, "phase": "IDLE", "gates": {},
        "history": [h("IDLE", "CLASSIFY"), h("CLASSIFY", "IDLE")]}
plant = dict(idle)
plant["ticket"] = "T-1"
plant["tier"] = "FEATURE"
plant["gates"] = {"define": True, "spec": True, "threat": True,
                  "tests": True, "sast": True, "verify": True}
assert rc(idle, plant) == 2, "a tier and six gates were planted onto an idle state"
only_gates = dict(idle, ticket="T-1"); only_gates["gates"] = {"spec": True}
assert rc(idle, only_gates) == 2, "gates were planted onto an idle state"

# ...and none of that may cost the legal moves.
# Marking a gate this phase OWNS. The fixture used to add `spec` from DEFINE,
# which under FEATURE is earned in PLAN — so the check demonstrating that
# in-phase marking is legal was itself the claim-from-anywhere hole, asserted as
# correct behaviour.
ungated = dict(mid); ungated["gates"] = {}
mark = dict(ungated); mark["gates"] = {"define": True}
assert rc(ungated, mark) == 0, "marking a gate the phase owns is legal and was refused"
early = dict(mid); early["gates"] = {"define": True, "spec": True}
assert rc(mid, early) == 2, \
    "`spec` was claimed from DEFINE: under FEATURE it is earned in PLAN, and a gate claimed " \
    "from another phase records work that has not happened"
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

python3 - "$SELF" "$ALL" <<'PYCOMPACT' && ok "every adapter answers its tool's compaction event, in the envelope that tool reads" || bad "a tool compacts and DDW says nothing — see above"
import json, os, subprocess, sys, tempfile
root, target = sys.argv[1], sys.argv[2]
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
}
# Copilot is not in that table and cannot be: its manifest is not a file in this
# repo. It is wired once per machine by the adapter's own script, so the way to
# read it is to run that script — which is also the only way to notice the day
# it stops wiring preCompact at all.
_cph = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"], prefix="ddw-precompact-home-"), "home")
os.makedirs(_cph, exist_ok=True)
subprocess.run([sys.executable, os.path.join(root, "adapters/copilot/wire-user-hooks.py"), ""],
               env=dict(os.environ, HOME=_cph), check=True, capture_output=True)
WIRING["copilot"] = (os.path.join(_cph, ".copilot/hooks/ddw.json"), "preCompact")
for tool, (rel, event) in sorted(WIRING.items()):
    blob = json.load(open(rel if os.path.isabs(rel) else os.path.join(root, rel), encoding="utf-8"))
    assert event in blob["hooks"], f"{tool}: {rel} does not wire {event}"
    assert "pre-compact.sh" in json.dumps(blob["hooks"][event]), \
        f"{tool}: {event} is wired to something other than the compaction hook"

# Which EVENT each tool wires was checked here and which ENVELOPE it answers in
# was not — and the envelope is where the silence lives: a nudge in the wrong
# shape is computed, formatted and dropped, and the pipeline simply never starts
# after a compaction. Codex passed `--format text` while two documents said it
# reads `hookSpecificOutput.additionalContext`, and nothing could see the
# disagreement because one side is prose and the other is a shell argument.
ENVELOPE = {
    "claude":  lambda out: not out.lstrip().startswith("{"),
    "codex":   lambda out: "additionalContext" in json.loads(out).get("hookSpecificOutput", {}),
    "cursor":  lambda out: "additional_context" in json.loads(out),
    "gemini":  lambda out: "additionalContext" in json.loads(out).get("hookSpecificOutput", {}),
    "copilot": lambda out: "additionalContext" in json.loads(out),
}
HOOK = {
    "claude":  ".claude/hooks/pre-compact.sh",
    "codex":   ".codex/hooks/ddw/pre-compact.sh",
    "cursor":  ".cursor/hooks/ddw/pre-compact.sh",
    "gemini":  ".gemini/hooks/ddw/pre-compact.sh",
    "copilot": ".github/hooks/ddw/pre-compact.sh",
}
for tool, hook_rel in sorted(HOOK.items()):
    hook = os.path.join(target, hook_rel)
    if not os.path.exists(hook):
        raise AssertionError(f"{tool}: no compaction hook was installed at {hook_rel}")
    r = subprocess.run(["bash", hook], input="{}", capture_output=True, text=True,
                       cwd=target, env=dict(os.environ, CLAUDE_PROJECT_DIR=target))
    out = r.stdout.strip()
    assert out, f"{tool}: the compaction hook said nothing at all"
    try:
        shaped = ENVELOPE[tool](out)
    except ValueError:
        shaped = False
    assert shaped, (f"{tool}: the compaction nudge came out in an envelope this tool does not "
                    f"read, so it is dropped in silence: {out[:160]}")

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
# Counted, because the loop's body is the check: delete `trust_note` from every
# recipe and a loop with no guard iterates zero times and reports success.
checked = 0
for recipe_path in glob.glob(os.path.join(src, "adapters", "*", "adapter.json")):
    recipe = json.load(open(recipe_path, encoding="utf-8"))
    note = recipe.get("trust_note")
    if not note:
        continue
    checked += 1
    repo = os.path.join(work, "trust-" + recipe["id"])
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "-C", repo, "init", "-q", "."], check=True)
    out = subprocess.run(["bash", os.path.join(src, "install.sh"), repo,
                          "--target", recipe["id"]],
                         capture_output=True, text=True).stdout
    head = " ".join(note.split()[:6])
    assert head in " ".join(out.split()), f"{recipe['id']}: the install never mentioned its trust_note"
assert checked >= 2, ("no adapter declares a trust_note, so this check measured nothing — "
                      "Codex and Gemini cannot enforce writes and the install has to say so")
PYEOF

# /ddw-self-check is what a user runs when they suspect DDW is not working. It
# reported TWO inconsistencies on every correct install of all six tools — one
# `grep` handed three filenames when one exists exits 2 for the missing operand
# even after a match, and one `ls` over six globs fails when any of them is
# empty, which five of six always are. A diagnostic that cries wolf on a healthy
# repo is worse than none: it is what people learn to ignore before the real one.
python3 - "$SELF" <<'PYSELFCHK' && ok "/ddw-self-check is silent on a correct install of every tool, and still speaks when something really is missing" || bad "the self-check reports a healthy install as broken, or has stopped noticing a broken one"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
skill = open(os.path.join(src, "skills/ddw-self-check/SKILL.md"), encoding="utf-8").read()
fence = re.search(r"```bash\n(.*?)```", skill, re.S)
assert fence, "the self-check skill no longer carries a runnable block"
snippet = fence.group(1)
assert "INCONSISTENCY" in snippet, "the block no longer reports anything"
work = tempfile.mkdtemp(dir=os.environ["WORK"])
for target in ("claude", "codex", "copilot", "cursor", "gemini", "opencode"):
    repo = os.path.join(work, target)
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", target],
                   capture_output=True, text=True)

    def say():
        return subprocess.run(["bash", "-c", snippet], cwd=repo, capture_output=True, text=True,
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=repo)).stdout

    out = say()
    assert "INCONSISTENCY" not in out, \
        f"{target}: a correct install is reported as broken:\n{out.strip()[:300]}"
    # …and it has to still speak. A snippet that says nothing on a healthy repo
    # and nothing on a gutted one is not a check, it is a comment.
    os.remove(os.path.join(repo, ".ddw", "orchestrator.md"))
    assert "INCONSISTENCY" in say(), f"{target}: a missing orchestrator went unreported"
PYSELFCHK

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
CORRUPT = {"phase": "CLOSEOUT", "tier": "FEATURE", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                        "to": "CLOSEOUT", "action": "forged"}]}


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

# A session marker expires after two hours, and only the Claude adapter had a
# second PreToolUse shim to refresh it from. In the other five tools it was
# written once at session start and swept — so a session long enough to collide
# with someone stopped being counted, and the concurrency warning went quiet
# for exactly the sessions worth warning about. The gate every tool runs says
# "still here" now, which is the one place all six share.
python3 - "$SELF" <<'PYLIVE' && ok "the write gate keeps this session's liveness marker fresh, so the concurrency guard survives a session longer than two hours" || bad "a session's marker still expires under every tool but one, and the guard goes quiet for long sessions"
import importlib.util, json, os, subprocess, sys, tempfile, time
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")
spec = importlib.util.spec_from_file_location("sb", os.path.join(src, "ddw/scripts/session-boot.py"))
sb = importlib.util.module_from_spec(spec); spec.loader.exec_module(sb)

repo = tempfile.mkdtemp(dir=os.environ["WORK"])
subprocess.run(["git", "init", "-q", repo], check=True)
state = os.path.join(repo, ".ddw-state.json")
json.dump({"phase": "CODE", "ticket": "T-1", "tier": "FEATURE",
           "gates": {"define": True, "spec": True, "threat": True}, "history": []},
          open(state, "w", encoding="utf-8"))
marker = os.path.join(repo, ".ddw-sessions", "live", "sess-A")
os.makedirs(os.path.dirname(marker))
open(marker, "w", encoding="utf-8").write("0")
aged = time.time() - (sb.STALE_SECONDS + 600)
os.utime(marker, (aged, aged))
# Before: this session is old enough that the next sweep deletes it.
assert time.time() - os.stat(marker).st_mtime > sb.STALE_SECONDS, "the fixture is not aged"

ev = json.dumps({"session_id": "sess-A", "tool_name": "Write",
                 "tool_input": {"file_path": os.path.join(repo, "src.py"), "content": "x = 1\n"}})
r = subprocess.run([sys.executable, gate, "--dialect", "standard", "--mode", "pre",
                    "--state", state, "--graph", graph, "--repo", repo],
                   input=ev, capture_output=True, text=True)
assert r.returncode == 0, "the fixture write was refused, so nothing here was driven: " + r.stderr[-200:]
assert time.time() - os.stat(marker).st_mtime < sb.STALE_SECONDS, \
    "the gate ran and the marker is still stale — every session over two hours vanishes from the count"

# …and the count sees it: a second session finds one other, not zero.
others, _ = sb.other_live_sessions(repo, "sess-B")
assert others == 1, "the refreshed session is not counted as live: %r" % others

# No id in the envelope, no marker invented: a pid is not a session, and one
# marker per write is how the guard came to warn about twelve people in a
# directory holding one.
before = set(os.listdir(os.path.dirname(marker)))
r = subprocess.run([sys.executable, gate, "--dialect", "standard", "--mode", "pre",
                    "--state", state, "--graph", graph, "--repo", repo],
                   input=json.dumps({"tool_name": "Write",
                                     "tool_input": {"file_path": os.path.join(repo, "src.py"),
                                                    "content": "x = 2\n"}}),
                   capture_output=True, text=True)
assert r.returncode == 0, "the second fixture write was refused: " + r.stderr[-200:]
assert set(os.listdir(os.path.dirname(marker))) == before, \
    "a write with no session id in the envelope invented a marker anyway"
PYLIVE

python3 - "$SELF" <<'PYEOF' && ok "and nothing inside the repository got easier while that door opened" || bad "the outside-the-repo exit softened the corrupt-state rule for the repo itself"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")
CORRUPT = {"phase": "CLOSEOUT", "tier": "FEATURE", "gates": {},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE",
                        "to": "CLOSEOUT", "action": "forged"}]}


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

    # The third disguise, and the one that fell between the two checks above:
    # zero bytes. Not absent, so the deletion net does not fire; not garbage, so
    # the parse guard does not either — and a blank state is read as a fresh
    # IDLE, because a fresh install genuinely leaves one behind. `: >
    # .ddw-state.json` therefore put the repository at IDLE with no ticket and
    # no history, and the write to product source that DEFINE had just refused
    # went through.
    open(state, "w", encoding="utf-8").close()
    rc, out = post(repo)
    assert rc == 2, "a state truncated to zero bytes read as a fresh IDLE — the run was erased " \
                    "by emptying the file rather than deleting it"
    assert "history" in out.lower(), \
        "the refusal does not say what was lost, which is what tells the user to restore: %r" % out
PYEOF

# …and a blank state with NOTHING recorded is not an erasure: it is a repository
# where the run has not started. A guard that cannot tell "nobody has begun"
# from "somebody erased this" refuses the first write in every new repository,
# which is how a guard gets deleted rather than fixed. Both spellings of "not
# started" are asked about — no file at all, which is what install leaves, and
# an empty one, which is what a `touch` or an editor leaves.
python3 - "$SELF" <<'PYEMPTYFRESH' && ok "and a blank state with nothing in the journal is a run that has not started, not one that was erased" || bad "the first write in a freshly installed repository is refused as an erased run"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
state = os.path.join(repo, ".ddw-state.json")
ddw = os.path.join(repo, ".ddw")
assert not os.path.exists(os.path.join(repo, ".ddw-journal.jsonl")), \
    "a fresh install now has a journal, which changes what 'nothing recorded' means here"
# A document, not product source. This check is about the ERASED-STATE guard —
# whether an empty state reads as "somebody wiped this" or "nobody has begun" —
# and it used `src/app.ts` as its example of a first write. Product source at
# IDLE is refused now, by a different rule and on purpose, so the example had to
# stop carrying an argument it was never making. The source rule is driven
# separately, below.
event = json.dumps({"tool_name": "Write",
                    "tool_input": {"file_path": os.path.join(repo, "docs", "notes.md"),
                                   "content": "x"}})


def first_write():
    return subprocess.run([sys.executable, os.path.join(ddw, "scripts", "hook-gate.py"),
                           "--mode", "pre", "--state", state, "--repo", repo, "--method", ddw,
                           "--graph", os.path.join(ddw, "rules", "transition-graph.json")],
                          input=event, capture_output=True, text=True)


assert not os.path.exists(state), \
    "install now writes a state file, so the case below is no longer the one it ships"
r = first_write()
assert r.returncode == 0, \
    "the first write in a freshly installed repository is refused: " + (r.stdout + r.stderr)[:200]

open(state, "w", encoding="utf-8").close()
r = first_write()
assert r.returncode == 0, \
    "an empty state file with an empty journal is refused as an erased run — that is a repo " \
    "nobody has started: " + (r.stdout + r.stderr)[:200]
PYEMPTYFRESH

# The hole every other one of these took a trick to reach, and this one took
# nothing: at IDLE the source guard was not applied, so an agent that never
# classifies wrote product code with both hooks green, no ticket, and no record
# that it had happened. Measured in a real session — asked plainly the model
# classified and refused to code; told "no ticket, just write it", it wrote the
# file. The prose held against forgetting and not against deciding, which is the
# difference between a guarantee and a convention.
#
# The answer is not to make it impossible — a tool that cannot be opted out of
# gets uninstalled — but to make opting out a DECISION: tier FREE, entered
# through CLASSIFY like any other, recorded at both ends, and announced at every
# session start for as long as it lasts.
python3 - "$SELF" <<'PYFREE' && ok "product source is refused at IDLE, allowed in FREE, and FREE is reachable only by classifying into it — never out of a ticket in flight" || bad "code can be written with no ticket and no record, or FREE is a way to walk out of the gates a ticket already owes"
import importlib.util, json, os, subprocess, sys, tempfile
src = sys.argv[1]
spec = importlib.util.spec_from_file_location("vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)
graph = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))
repo = tempfile.mkdtemp(dir=os.environ["WORK"])
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)


def denied(rel, phase):
    return vt.source_write_denied(os.path.join(repo, rel), repo, phase)


# 0. And the method ASKS it to write code with the write tool, not with the
#    shell. It cannot be enforced — DDW sees a shell command and cannot tell
#    the agent's from yours in another terminal, which is decision 12 — so the
#    only thing left is to ask for it, and the only thing that holds up a
#    request is that it is written down. Measured: facing a refused `Write`, a
#    live model went to the shell in most runs. Not by cheating: because
#    nothing had told it not to.
_orch = open(os.path.join(src, "ddw/orchestrator.md"), encoding="utf-8").read()
assert "never with a shell command" in _orch and "bypasses PreToolUse" in _orch, \
    ("the method no longer asks the model to write source with the write tool. That request is "
     "the only thing standing between a refused `Write` and the same file written with `cat >`, "
     "because the shell path cannot be refused — only reported.")

# 1. No ticket, no product source — and the refusal names the sanctioned way
#    out and NOT the recipe for going around itself.
why = denied("src/app.py", "IDLE")
assert why, "product source is writable at IDLE: no ticket, no gates, no record"
assert "CLASSIFY" in why, \
    "the refusal at IDLE does not name the sanctioned way out: " + why
assert "--tier FREE" not in why and "--to FREE" not in why, \
    ("the refusal hands the model the recipe for the tier with no enforcement. Measured with a "
     "live model over OpenCode: it read this refusal, took `--to CLASSIFY --tier FREE` and then "
     "`--to FREE` on its own, and wrote the file. It did not cheat — it did what the message "
     "said it could do. Working with no pipeline is the USER's call; offered here it becomes "
     "the model's, and a pipeline that teaches how to step around it is not enforcing "
     "anything: " + why)

# 2. …and what a repo at rest legitimately needs is still writable, or the guard
#    stops the install, the eject and every document.
for rel in ("docs/ddw/prd/prd-T-1.md", "AGENTS.md", "CHANGELOG.md", ".claude/settings.json"):
    assert not denied(rel, "IDLE"), "%s is refused at IDLE, and a repo at rest needs it" % rel

# 3. FREE is the phase where none of this is asked. That IS the escape hatch.
assert not denied("src/app.py", "FREE"), \
    "FREE refuses product source, so the sanctioned way to work without a pipeline is a wall"

# 4. But FREE is reachable only by classifying into it, and leads only back to
#    IDLE. A ticket in flight cannot become FREE — otherwise the gates it has
#    already been asked for are one transition away from being forgotten.
edges = vt._effective_edges(graph, "FREE")
assert "CLASSIFY->FREE" in edges and "FREE->IDLE" in edges, \
    "the FREE tier no longer has its two edges: %s" % sorted(edges)
assert not [e for e in edges if e.endswith("->FREE") and not e.startswith("CLASSIFY")], \
    "something other than CLASSIFY leads into FREE: %s" % sorted(edges)
for tier in ("FEATURE", "QUICK-FIX", "FIX", "DISCOVERY"):
    assert not [e for e in vt._effective_edges(graph, tier) if e.endswith("->FREE")], \
        "tier %s has an edge into FREE — a ticket can walk out of its gates" % tier
assert not vt._gate_owners(graph, "FREE"), \
    "FREE asks for a gate, which is not what the user asked for when they asked for no pipeline"

# 5. And FREE is not a licence to disarm DDW itself.
assert vt.enforcement_write_denied(os.path.join(repo, ".ddw/rules/code.instructions.md"), repo), \
    "the method is writable in FREE — turning the pipeline off must not hand over what turns it off for good"
PYFREE

# The other half of FREE, and the half that keeps it honest: the announcement.
# A mode nobody is reminded of is a mode people stay in by accident, and this one
# has no other guard — nothing is gated, so the warning IS the guard. Driven
# through `session-boot.py`, the program every tool's session-start hook runs,
# in both directions: it says it in FREE, and it does not say it anywhere else.
python3 - "$SELF" <<'PYFREEWARN' && ok "a session in FREE opens by saying there is no workflow, and a session anywhere else does not" || bad "the repo can sit in FREE with nothing announcing it, which is the only thing FREE has instead of gates"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
state = os.path.join(repo, ".ddw-state.json")
H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "FREE",
      "action": "sin pipeline, a pedido", "tier": "FREE", "ticket": "F-1"}]


def boot(phase, tier):
    json.dump({"phase": phase, "tier": tier, "ticket": "F-1", "gates": {}, "history": H},
              open(state, "w", encoding="utf-8"))
    r = subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/session-boot.py"),
                        "--repo", repo, "--session-id", "s-" + phase],
                       capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


said = boot("FREE", "FREE")
assert "SIN WORKFLOW" in said, \
    "a session opened in FREE and never said the pipeline is off:\n" + said[-400:]
assert "exit free:" in said, \
    "the warning does not carry the way out, so leaving takes reading the rules:\n" + said[-400:]

# …and it is not printed for a repo that IS running a pipeline, or the line
# becomes noise and the next reader learns to skip it.
quiet = boot("CODE", "FEATURE")
assert "SIN WORKFLOW" not in quiet, \
    "a session in CODE is told it has no workflow:\n" + quiet[-400:]
PYFREEWARN

# The arrow into FREE, judged by what it will and will not accept. The check
# above proves the requirement exists; this one proves it DISCRIMINATES, which
# is a different question and the one three surviving mutations asked. A rule
# that refuses everything but a magic word is a rule that refuses nothing the
# day the word is easy to type — and the word `free` is the easiest one here.
python3 - "$SELF" <<'PYFREEWORDS' && ok "the arrow into FREE takes the user's words quoted and opening the action, and refuses a bare declaration, a buried one, and a quote too short to be a sentence — and a run already in FREE is not re-judged on replay" || bad "FREE is entered on a paraphrase, on a declaration hidden inside another sentence, or every ticket that entered FREE before the rule existed is refused on every tool call"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)
graph = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))

INTO = {"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "clasificar"}
OLD = {"phase": "CLASSIFY", "tier": None, "ticket": None, "title": None, "gates": {},
       "history": [INTO]}


def verdict(action, **kw):
    """None if the arrow is allowed, the refusal otherwise."""
    new = {"phase": "FREE", "tier": "FREE", "ticket": None, "title": None, "gates": {},
           "history": [INTO, {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY",
                              "to": "FREE", "action": action, "tier": "FREE"}]}
    try:
        vt.validate(OLD, new, graph, **kw)
        return None
    except vt.Block as exc:
        return str(exc)


# The shape the rules teach, and the only one that gets in.
assert verdict('free: "no me armes workflow, quiero probar algo"') is None, \
    "the action the CLASSIFY rules teach is refused by the gate those rules feed"

# A declaration with nothing quoted. This is the paraphrase: the model saying
# the user asked, instead of showing what they said.
assert verdict("free: el usuario lo pidio"), \
    "FREE was entered on a declaration carrying none of the user's words — a paraphrase counts " \
    "as the user asking"

# Quoted, well-formed, and riding along inside a sentence about something else.
# The declaration is what the action OPENS with, or an action about anything at
# all can carry FREE into the state.
assert verdict('le expliqué el pipeline y me dijo free: "dale sin pipeline"'), \
    "the FREE declaration was accepted from the middle of an action about something else"

# Two characters between quotes is punctuation, not a sentence somebody said.
assert verdict('free: "ok"'), "a two-character quote was accepted as the user's own words"

# And the requirement governs the next arrow, never the ones already taken.
# Post mode re-walks the whole run as one batch (`max_appended=None`); without
# the replay guard, every ticket that entered FREE before this release is
# refused on every tool call, with no way out short of editing the state by hand.
assert verdict("free: el usuario lo pidio", max_appended=None) is None, \
    "post mode's replay re-judges an arrow taken before the rule existed, stranding the run"
PYFREEWORDS

# The ticket's name, asked as a name rather than as a field that exists. `title`
# defaults to `None` in the state schema, so a check that reads `is None` reads
# the DEFAULT and not the requirement: `""` is a field somebody filled in with
# nothing, and every status line, report header and PR title downstream is the
# same reconstruction from context that the null was.
python3 - "$SELF" <<'PYTITLESHAPE' && ok "the name a ticket leaves CLASSIFY with has to be a name: absent, blank and whitespace are all refused, and a non-string is not a name either" || bad "a ticket leaves CLASSIFY with an empty title — the same nothing the null was, now with a type"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)
graph = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))

INTO = {"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "clasificar"}
OLD = {"phase": "CLASSIFY", "tier": None, "ticket": None, "title": None, "gates": {},
       "history": [INTO]}


def verdict(title):
    new = {"phase": "DEFINE", "tier": "FEATURE", "ticket": "T-1", "title": title, "gates": {},
           "history": [INTO, {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY",
                              "to": "DEFINE", "action": "clasificado", "tier": "FEATURE",
                              "ticket": "T-1"}]}
    try:
        vt.validate(OLD, new, graph, max_appended=1)
        return None
    except vt.Block as exc:
        return str(exc)


assert verdict("Tetris LatinoNet") is None, "a ticket with a name was refused"
for empty, what in ((None, "absent"), ("", "empty"), ("   ", "whitespace"),
                    ("\t\n", "a tab and a newline"), (7, "a number"), ([], "a list")):
    why = verdict(empty)
    assert why, "a title that is %s left CLASSIFY unrefused" % what
    assert "title" in why, "the refusal for a title that is %s names something else: %s" % (what, why)
PYTITLESHAPE

# Under a plugin install, the method is sealed and the FILES THE TOOL EXECUTES
# were not. `$PLUGIN/ddw` is the rules and the validators; the hook that runs the
# gate is `$PLUGIN/adapters/<tool>/hooks/*.sh`, wired by `plugin-hooks.json` and
# declared in `.claude-plugin/plugin.json` — one level up, outside the method and
# outside the repo, so every guard answered "not ours". Overwriting that one
# shell script with `exit 0` takes a single Write, allowed in any phase, and DDW
# stops holding in every repository using that plugin.
python3 - "$SELF" <<'PYPLUGINROOT' && ok "a plugin install seals what the tool executes, not only the method it reads — and a drop-in still leaves the repository writable" || bad "the hook that runs the gate can be overwritten from inside a ticket, which turns DDW off everywhere it is installed"
import json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
plug = os.path.join(work, "plugin")
os.makedirs(plug)
for item in ("ddw", "adapters", ".claude-plugin"):
    if os.path.exists(os.path.join(src, item)):
        shutil.copytree(os.path.join(src, item), os.path.join(plug, item), symlinks=True)
repo = os.path.join(work, "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
state = os.path.join(repo, ".ddw-state.json")
json.dump({"phase": "CODE", "ticket": "T-1", "tier": "FEATURE",
           "gates": {"define": True, "spec": True, "threat": True},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "a"},
                       {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
                        "action": "b", "tier": "FEATURE", "ticket": "T-1"}]},
          open(state, "w", encoding="utf-8"))


def write(path):
    ev = json.dumps({"tool_name": "Write", "tool_input": {"file_path": path, "content": "exit 0\n"}})
    return subprocess.run([sys.executable, os.path.join(plug, "ddw/scripts/hook-gate.py"),
                           "--dialect", "standard", "--mode", "pre", "--state", state,
                           "--graph", os.path.join(plug, "ddw/rules/transition-graph.json"),
                           "--repo", repo, "--method", os.path.join(plug, "ddw")],
                          input=ev, capture_output=True, text=True).returncode


for rel in ("ddw/rules/transition-graph.json",
            "adapters/claude/hooks/validate-state-transition.sh",
            "adapters/claude/plugin-hooks.json",
            ".claude-plugin/plugin.json",
            "adapters/cursor/hooks/pre-tool-use.sh"):
    path = os.path.join(plug, rel)
    if not os.path.exists(path):
        continue
    assert write(path) == 2, (
        "`%s` is writable from inside a ticket under a plugin install. It is what the tool runs, "
        "or what tells the tool to run it — one Write and the pipeline is off in every repository "
        "sharing this plugin." % rel)

# The repository is still the user's: CODE writes its own source.
assert write(os.path.join(repo, "src", "app.py")) == 0, \
    "sealing the plugin root also sealed the repository — CODE cannot write source"

# And a DROP-IN install must not seal the project: there the method is
# `<repo>/.ddw`, whose parent is the repo itself.
drop = os.path.join(work, "dropin")
os.makedirs(drop)
subprocess.run(["git", "-C", drop, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), drop, "--target", "claude"],
               capture_output=True, text=True)
json.dump({"phase": "CODE", "ticket": "T-1", "tier": "FEATURE",
           "gates": {"define": True, "spec": True, "threat": True},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                        "action": "a"},
                       {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE",
                        "action": "b", "tier": "FEATURE", "ticket": "T-1"}]},
          open(os.path.join(drop, ".ddw-state.json"), "w", encoding="utf-8"))
ev = json.dumps({"tool_name": "Write",
                 "tool_input": {"file_path": os.path.join(drop, "src", "app.py"), "content": "x"}})
r = subprocess.run([sys.executable, os.path.join(drop, ".ddw/scripts/hook-gate.py"),
                    "--dialect", "standard", "--mode", "pre",
                    "--state", os.path.join(drop, ".ddw-state.json"),
                    "--graph", os.path.join(drop, ".ddw/rules/transition-graph.json"),
                    "--repo", drop, "--method", os.path.join(drop, ".ddw")],
                   input=ev, capture_output=True, text=True)
assert r.returncode == 0, \
    "a drop-in install now seals the repository itself: " + (r.stdout + r.stderr)[-200:]
PYPLUGINROOT

# The resume is the one edge in the machine that skips the graph AND the gates —
# coming back to a paused ticket owes nothing, because pausing owed nothing. So
# what it rests on has to be something the forger does not also write, and until
# now it rested on the history: which lives in the state file, which is exactly
# what a shell rewrites.
#
# Measured end to end: one shell write of a state whose history holds a single
# `pause:` entry from CODE, then the SANCTIONED helper resuming into CODE. No
# ticket, no tier, no receipt, `gates: {}` — and product source writable on the
# next call, with both hooks green. Every gate in the pipeline skipped by
# inventing a pause that never happened.
python3 - "$SELF" <<'PYFAKEPAUSE' && ok "a resume has to point at a pause the journal recorded, and a real one still resumes" || bad "inventing a `pause:` entry in the state file is a key to any phase, with no gates and no ticket"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]


def repo_with(history, journal):
    repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                   capture_output=True, text=True)
    json.dump({"tier": None, "phase": "IDLE", "ticket": None, "gates": {}, "history": history},
              open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8"))
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "w", encoding="utf-8") as fh:
        for line in journal:
            fh.write(json.dumps(line) + "\n")
    return repo


def resume(repo):
    return subprocess.run(
        [sys.executable, os.path.join(repo, ".ddw/scripts/transition.py"),
         "--state", os.path.join(repo, ".ddw-state.json"),
         "--graph", os.path.join(repo, ".ddw/rules/transition-graph.json"),
         "--write", "--to", "CODE", "--action", "resume: back to it"],
        capture_output=True, text=True, cwd=repo)


HISTORY = [{"timestamp": "2026-08-06T09:00:00Z", "from": "IDLE", "to": "CLASSIFY",
            "action": "classify", "tier": "FEATURE", "ticket": "T-1"},
           {"timestamp": "2026-08-06T10:00:00Z", "from": "CODE", "to": "IDLE",
            "action": "pause: waiting", "ticket": "T-1"}]
REAL = [{"from": "IDLE", "to": "CLASSIFY", "action": "classify"},
        {"from": "CODE", "to": "IDLE", "action": "pause: waiting"}]
FORGED = [{"from": "IDLE", "to": "CLASSIFY", "action": "classify"},
          {"from": "CLASSIFY", "to": "DEFINE", "action": "define"}]

# The pause the journal saw: resuming is legal, as it has always been.
r = resume(repo_with(HISTORY, REAL))
assert r.returncode == 0, "a resume onto a pause the journal recorded was refused: " + r.stderr[-300:]

# The same history, with a journal that never saw that pause.
r = resume(repo_with(HISTORY, FORGED))
assert r.returncode != 0, \
    "a `pause:` entry written into the state file is enough to resume into any phase, with no " \
    "gates and no ticket — the one edge that skips both"
assert "journal" in r.stderr, \
    "the refusal does not say which record is missing, so it reads as a bug: " + r.stderr[-300:]

# A repository with no journal at all is not a forgery: it is one installed
# before the journal existed, or one whose first transition has not landed.
r = resume(repo_with(HISTORY, []))
assert r.returncode == 0, \
    "a repo with no journal cannot resume at all, which strands every ticket that predates it"
PYFAKEPAUSE

# Every receipt gate resolves its document through the ticket, and a missing
# ticket read as a missing CLAIM — so the switch that turns the entire evidence
# layer on was held by whoever wrote the history. Leave `ticket` off the entries
# and post mode asks for nothing.
#
# Measured: a FEATURE forged in one shell write, seven transitions from IDLE to
# IDLE, `tier` stamped so the tier-less hatch would not catch it and `ticket`
# left off. Post mode returned 0 and the journal recorded all seven as blessed —
# no PRD, no spec, no threat model, no test report, no SAST report, no verdict,
# and afterwards indistinguishable from a run that earned them.
python3 - "$SELF" <<'PYNOTICKET' && ok "a run that owes evidence and names no ticket is refused, because a run nobody can check is not one that passed" || bad "leaving `ticket` off the entries turns the whole evidence layer off — the forger holds the switch"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
state = os.path.join(repo, ".ddw-state.json")
EDGES = [("IDLE", "CLASSIFY", "classify"), ("CLASSIFY", "DEFINE", "prd"),
         ("DEFINE", "PLAN", "spec"), ("PLAN", "CODE", "code"), ("CODE", "VERIFY", "verify"),
         ("VERIFY", "CLOSEOUT", "closeout"), ("CLOSEOUT", "IDLE", "done")]


def post(with_ticket):
    hist = [{"timestamp": "2026-08-06T1%d:00:00Z" % i, "from": a, "to": b, "action": c,
             "tier": "FEATURE", **({"ticket": "T-9"} if with_ticket else {})}
            for i, (a, b, c) in enumerate(EDGES)]
    json.dump({"tier": None, "phase": "IDLE", "ticket": None, "gates": {}, "history": hist},
              open(state, "w", encoding="utf-8"))
    return subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/hook-gate.py"),
                           "--dialect", "standard", "--mode", "post", "--state", state,
                           "--repo", repo, "--method", os.path.join(repo, ".ddw"),
                           "--graph", os.path.join(repo, ".ddw/rules/transition-graph.json")],
                          input="{}", capture_output=True, text=True)


r = post(with_ticket=False)
assert r.returncode == 2, (
    "a whole FEATURE forged in one write, with no ticket on any entry, was blessed by post mode: "
    "every receipt gate resolves its document through the ticket, so leaving it off asked for "
    "nothing at all")
assert "ticket" in (r.stdout + r.stderr), \
    "the refusal does not say what is missing: " + (r.stdout + r.stderr)[-250:]

# The control: the same forgery WITH a ticket is refused too, and for the older
# reason — the documents it names are not on disk. Both roads have to be shut,
# or the fix above is just a longer forgery.
r = post(with_ticket=True)
assert r.returncode == 2, "the same run with a ticket stamped was blessed with no artifacts at all"

# …and the journal recorded none of it. A refused run that leaves its edges in
# the append-only record is a forgery the next replay treats as history.
journal = os.path.join(repo, ".ddw-journal.jsonl")
if os.path.exists(journal):
    lines = [json.loads(l) for l in open(journal, encoding="utf-8") if l.strip()]
    assert not [l for l in lines if l.get("from") == "VERIFY"], \
        "post mode refused the run and still journalled its transitions"
PYNOTICKET

# The fast layer, kept honest by the slow one.
#
# `tests/` asks the enforcement core directly — dictionaries in, verdict out —
# and answers in a tenth of a second where this suite takes eighty-five. It is
# NOT a substitute and the numbers say why: measured over the 114 faults injected
# into `validate-transition.py`, thirty-six tests catch sixteen. What it buys is
# the loop you use while WRITING a rule, not the measurement you publish.
#
# Run here so it cannot rot: a test file nobody runs is a file that stops
# compiling and nobody finds out.
# Read the summary rather than the exit status. `cmd && ok || bad` reports
# success for anything that exits 0, including a command that ran nothing —
# replace the invocation with `true` and this line still printed that the layer
# "passes". The count is the evidence that tests were collected and run.
# `CLAUDE_PROJECT_DIR` is exported three times further up and never cleaned,
# and the helper reads it BEFORE the cwd: inherited, everything that runs after
# works on some other section's repo. Measured — a test that passed twenty
# times in a row on its own failed in here, with a message about gates that had
# nothing to do with what it measured. The two layers below stand up their own repos.
unset CLAUDE_PROJECT_DIR

# ── The instruction layer ─────────────────────────────────────────────────────
#
# Everything above measures the HOOKS: given an event, does the gate answer
# correctly? This measures the INSTRUCTIONS: does an obedient reader of the
# rules as written end up where the hooks allow? No check goes red when a
# skill orders a write the enforcement refuses — the model simply obeys and
# crashes into it.
#
# It runs here, and with the CONTROL, for the same reason as everything else in
# this file: a layer nobody executes reports green for not having looked. The
# control applies to each scenario the historical broken version of its
# instruction and DEMANDS that the scenario go red; if it passes, the scenario
# cannot detect the regression it came from and is measuring nothing.
if command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" 2>/dev/null; then
  EV_OUT="$(python3 "$SELF/evals/runner.py" --repo "$SELF" --offline 2>&1)"
  EV_RC=$?
  # The CONTROL needs the history: each scenario declares the commit of the
  # regression it comes from, and without `.git` there is nowhere to get it.
  # The copies `mutate.py` makes do not carry it, so there the control cannot
  # be asked — and ever since an inapplicable control FAILS instead of
  # counting as red, asking anyway put every copy in red and the runner
  # refused to inject anything. Skip, which is counted apart and does not add
  # up to a green.
  if git -C "$SELF" rev-parse --git-dir >/dev/null 2>&1; then
    EV_CTL="$(python3 "$SELF/evals/runner.py" --repo "$SELF" --offline --control 2>&1)"
    EV_CRC=$?
  else
    EV_CTL="(no git history: the control cannot be asked here)"
    EV_CRC=0
  fi
  if [ "$EV_RC" = 0 ] && [ "$EV_CRC" = 0 ]; then
    ok "the instruction evals pass, and each one still goes red against the regression it came from"
  else
    bad "an instruction eval fails, or one of them cannot go red — a scenario that cannot fail is not a test"
    printf '%s\n' "$EV_OUT" | tail -8 | sed 's/^/      /'
    printf '%s\n' "$EV_CTL" | tail -8 | sed 's/^/      /'
  fi
else
  skip "pyyaml is not installed, so the instruction evals were not run"
fi

if command -v python3 >/dev/null 2>&1 && python3 -c "import pytest" 2>/dev/null; then
  PYTEST_OUT="$(python3 -m pytest "$SELF/tests" -q 2>&1)"
  # Both halves of the summary. Counting only the passes reproduces the defect
  # this check was written against: `1 failed, 38 passed` still reports 38, and
  # a red layer went green because enough of it was green. Measured — two faults
  # survived exactly here.
  PYTEST_PASSED="$(printf '%s\n' "$PYTEST_OUT" | grep -oE '[0-9]+ passed' | head -1 | cut -d' ' -f1)"
  PYTEST_BAD="$(printf '%s\n' "$PYTEST_OUT" | grep -coE '[0-9]+ (failed|error)')"
  if [ -n "${PYTEST_PASSED:-}" ] && [ "$PYTEST_PASSED" -ge 30 ] 2>/dev/null && [ "$PYTEST_BAD" -eq 0 ]; then
    ok "the fast layer over the enforcement core passes, and still compiles ($PYTEST_PASSED tests)"
  else
    bad "tests/ fails, collects nothing, or no longer runs — the loop used while writing a rule is broken"
    printf '%s\n' "$PYTEST_OUT" | tail -12 | sed 's/^/      /'
  fi
else
  skip "pytest is not installed, so the fast layer was not run (the suite above is the measurement)"
fi

python3 - "$SELF" <<'PYEOF' && ok "and it says the whole finding once, not on every tool call" || bad "the same corrupt state is re-reported in full forever — see above"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
gate = os.path.join(src, "ddw", "scripts", "hook-gate.py")
graph = os.path.join(src, "ddw", "rules", "transition-graph.json")

with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["git", "init", "-q", repo], check=True)
    state = os.path.join(repo, ".ddw-state.json")
    json.dump({"tier": "FEATURE", "phase": "CLOSEOUT", "gates": {},
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

FORGED_STATE='{"tier":"FEATURE","phase":"CLOSEOUT","ticket":"T-1","gates":{"define":true,"spec":true,"threat":true,"tests":true,"sast":true,"verify":true,"commit":true,"pr":true},"history":[{"timestamp":"2026-07-27T10:00:00Z","from":"IDLE","to":"CLOSEOUT","action":"forged with sed","tier":"FEATURE"}]}'

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

# Those five cleared the journal on purpose, once per adapter, so that each is
# judged on the whole finding rather than on the short line the second one would
# get. Everything below this line is an ordinary run again, and an ordinary run
# has the journal its validators wrote: without it every receipt in this fixture
# is one no validator is recorded as having written, and the gates that rest on
# them would be refused for a reason no check here is about.
for _t in T-1 FEAT-001 EVIL-1 Q-1; do
  for _g in define spec threat tests sast verify; do ddw_earn "$ALL" "$_g" "$_t"; done
done

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

# …and when the marker cannot be written, the guard runs in one direction only:
# this session sees the others, the others will never see this one. The flag that
# says so was computed and then discarded by `return others if registered else
# others` — the same expression twice. Counting a session that does not exist
# would be the worse repair: the number has to stay honest and the sentence has
# to be said out loud.
# The guard's other failure mode, and the one a real user actually hits: not
# missing a session, but inventing eleven. The pre-write hook runs on every edit
# and identified itself by its own pid, so each write left a new "live session"
# on disk and the next session-start warned about a crowd nobody else could see.
python3 - "$SELF" <<'PYPIDMARKERS' && ok "a dozen edits in one session leave one marker, not a dozen — the guard counts sessions, not writes" || bad "every write registers a session of its own, so the concurrency warning fires against a directory with one person in it"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
env = dict(os.environ, CLAUDE_PROJECT_DIR=repo)
event = json.dumps({"session_id": "the-one-session", "tool_name": "Write",
                    "tool_input": {"file_path": os.path.join(repo, "f.txt"), "content": "x"}})
start = json.dumps({"session_id": "the-one-session"})
subprocess.run(["bash", os.path.join(repo, ".claude/hooks/session-start.sh")],
               input=start, capture_output=True, text=True, env=env, cwd=repo)
for _ in range(12):
    subprocess.run(["bash", os.path.join(repo, ".claude/hooks/enforce.sh")],
                   input=event, capture_output=True, text=True, env=env, cwd=repo)
live = os.path.join(repo, ".ddw-sessions", "live")
markers = sorted(os.listdir(live)) if os.path.isdir(live) else []
assert markers == ["the-one-session"], \
    "twelve edits in one session left %d marker(s): %s" % (len(markers), markers[:6])
out = subprocess.run(["bash", os.path.join(repo, ".claude/hooks/session-start.sh")],
                     input=start, capture_output=True, text=True, env=env, cwd=repo).stdout
assert "other session" not in out, "the session was warned about itself: " + out[:200]
# An event with no session id in it claims no identity at all, rather than one
# per process.
subprocess.run(["bash", os.path.join(repo, ".claude/hooks/enforce.sh")],
               input=json.dumps({"tool_name": "Write"}), capture_output=True, text=True,
               env=env, cwd=repo)
assert sorted(os.listdir(live)) == ["the-one-session"], \
    "a write whose event names no session still registered one: %s" % sorted(os.listdir(live))
PYPIDMARKERS

python3 - "$SB2" <<'PYONESIDED' && ok "a session that cannot announce itself says the guard is one-sided, and does not invent a session to say it" || bad "a boot that could not register stays silent about it, or pads the count with a session nobody is running"
import os, re, shutil, subprocess, sys, tempfile
work = tempfile.mkdtemp(dir=os.environ["WORK"])
repo = os.path.join(work, "repo")
shutil.copytree(sys.argv[1], repo, symlinks=True)
boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")


def run(session_id):
    return subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", session_id],
                          capture_output=True, text=True).stdout


live = os.path.join(repo, ".ddw-sessions", "live")
shutil.rmtree(live, ignore_errors=True)
os.makedirs(os.path.dirname(live), exist_ok=True)
run("sess-A")
out = run("sess-B")
assert "could not write its marker" not in out, "a session that DID register is told it did not"

# The case where the count is right and the announcement is not: this session's
# own marker name is taken by a directory, so writing it fails while listing the
# others still works. Both facts have to reach the reader — one session IS here,
# and this one is invisible to whoever opens the next terminal.
mine = os.path.join(live, "sess-C")
os.makedirs(mine, exist_ok=True)
out = run("sess-C")
seen = [int(n) for n in re.findall(r"DDW: (\d+) other session", out)]
assert seen and seen[0] >= 1, \
    f"the session that could not register also stopped counting the ones that could: {out[:200]}"
assert "could not write its marker" in out, \
    f"a boot that could not register reported a guard that runs both ways: {out[:200]}"

# And when the whole namespace cannot even be listed, the count is zero — not
# padded with a session nobody is running, which would be the tempting repair.
shutil.rmtree(live, ignore_errors=True)
open(live, "w", encoding="utf-8").write("not a directory\n")
out = run("sess-D")
assert "could not write its marker" in out, f"a boot that could not register says nothing: {out[:200]}"
counts = [int(n) for n in re.findall(r"DDW: (\d+) other session", out)]
assert not counts, f"a boot that saw nobody still reported {counts[0]} other session(s)"

# The id comes from the harness and is used as a FILENAME. Written through, one
# shaped like a path leaves the sessions directory: `--session-id
# ../.ddw-state.json` replaces the pipeline state with a marker and reports a
# clean boot. Whatever the harness calls a session, on disk it is one flat name.
# The case above left a FILE where the directory goes, and `rmtree` on a file
# does nothing when it is told to ignore errors.
if os.path.isdir(live):
    shutil.rmtree(live, ignore_errors=True)
elif os.path.exists(live):
    os.remove(live)
os.makedirs(live, exist_ok=True)
state = os.path.join(repo, ".ddw-state.json")
before = open(state, "rb").read() if os.path.exists(state) else None
assert before is not None, "this repository has no state file, so the case cannot be planted"
run("../../.ddw-state.json")
assert open(state, "rb").read() == before, \
    "a session id shaped like a path walked out of the sessions directory and overwrote the state"
escaped = [n for n in os.listdir(os.path.dirname(live)) if n not in ("live",)]
assert not any(n.startswith("..") for n in escaped), \
    f"the id was written as a name that climbs: {escaped[:4]}"
assert os.listdir(live), "the boot registered nothing at all, so nothing above was exercised"
assert all(os.sep not in n and n not in ("..", ".") for n in os.listdir(live)), \
    f"a session marker is not one flat name: {os.listdir(live)[:4]}"

# And the count is made against those same flat names. Sanitised on the way to
# disk and compared unsanitised, a session whose id carries one character the
# filename cannot hold stops recognising its own marker and reports ITSELF as
# somebody else — the concurrency warning fires at a person working alone, which
# is the fastest way to teach them to ignore it.
if os.path.isdir(live):
    shutil.rmtree(live, ignore_errors=True)
os.makedirs(live, exist_ok=True)
out = run("sess/A")
counts = [int(n) for n in re.findall(r"DDW: (\d+) other session", out)]
assert not counts, \
    f"a session alone in the repository was told about {counts[0]} other session(s) — it counted " \
    f"its own marker, because the id is written to disk sanitised and compared raw"
PYONESIDED

# ── The guard cannot exempt its own rulebook ──────────────────────────────────
section "What a blocked phase still cannot touch"

# In CODE, and that is the point. Run in PLAN — where it was — the source-code
# guard refuses these four paths on its own, so breaking the entire SEAL
# changed no verdict: the check reported green for a reason that was not its
# own, and no one-line edit over the seal could be seen from here. In CODE
# writing code is allowed, so the only thing that can deny these paths is the
# seal, which is what this check claims to measure.
printf '%s' "$IN_CODE" > "$GST"
# The graph and the gate ARE the enforcement. Allowing a phase to write there let
# an agent that could not write code rewrite the rules that stopped it: add an
# edge from PLAN and a FEATURE closes with no spec, no threat model, no tests and
# no verification, with both hooks green.
for TARGET in .ddw/rules/transition-graph.json .ddw/scripts/hook-gate.py \
              .ddw/scripts/validate-transition.py .ddw/orchestrator.md; do
  ddw_event_path snake "$ALL/$TARGET"
  [ "$(gate_pre standard < "$EVENT")" = "2" ] \
    && ok "not even CODE can rewrite $TARGET" \
    || bad "the phase that writes source rewrote $TARGET — the guard exempts its own rulebook"
done

# ...while the runtime the protocol needs stays writable. Pause is advertised as
# available from any phase, and step one is saving the state to .ddw-paused/.
ddw_event_path snake "$ALL/.ddw-paused/TICKET-1.ddw-state.json"
[ "$(gate_pre standard < "$EVENT")" = "0" ] \
  && ok "and pausing from a blocked phase still works" \
  || bad "the pause protocol is unusable from the phases that most need it"

# And the same refusal has to hold in CODE and CLOSEOUT, which is where it did
# NOT. The guard above lived inside the phase rule, and that rule returns early
# for the two phases where writing is allowed — so the protection covered
# exactly the phases where the agent cannot write anything anyway and stood down
# in the one where it works. Measured end to end on a real install: in CODE the
# agent rewrote the transition graph, added an edge, and closed a FEATURE that
# never claimed tests, sast, verify, commit or pr, with both hooks green. It
# could also write its own receipt into .ddw-sessions/ and open six gates with a
# touch, or replace the tool's hook script with `exit 0`.
python3 - "$SELF" <<'PYENF' && ok "DDW's own machinery — the method, the receipts, the wiring, the manifest — is unwritable in EVERY phase, and the repo stays writable" || bad "the pipeline can edit the rules that stop it: see which path and which phase, above"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
vt = os.path.join(repo, ".ddw", "scripts", "validate-transition.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
EDGES = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN"), ("PLAN", "CODE"),
         ("CODE", "VERIFY"), ("VERIFY", "CLOSEOUT")]
UPTO = {"CLASSIFY": 1, "DEFINE": 2, "PLAN": 3, "CODE": 4, "VERIFY": 5, "CLOSEOUT": 6}


def ask(phase, rel):
    hist = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
             "tier": "FEATURE", "ticket": "T-1"}
            for i, (f, t) in enumerate(EDGES[:UPTO[phase]])]
    json.dump({"tier": "FEATURE", "phase": phase, "ticket": "T-1", "title": None,
               "tracker": None, "autonomy": None, "gates": {}, "block": None,
               "discovery": None, "history": hist}, open(state, "w", encoding="utf-8"))
    ev = json.dumps({"tool_name": "Write",
                     "tool_input": {"file_path": os.path.join(repo, rel), "content": "x"}})
    return subprocess.run([sys.executable, vt, "--mode", "pre", "--state", state,
                           "--graph", graph, "--repo", repo],
                          input=ev, capture_output=True, text=True).returncode


SEALED = [".ddw/rules/transition-graph.json", ".ddw/scripts/validate-transition.py",
          ".ddw/scripts/hook-gate.py", ".ddw/orchestrator.md",
          ".ddw-sessions/prd-validated-deadbeef1234",   # writing your own receipt
          ".ddw-journal.jsonl", ".ddw-installed.json",
          ".claude/hooks/enforce.sh",                   # from the install manifest
          ".claude/settings.json"]                      # what wires the hook to the tool
# CODE and CLOSEOUT are the point: those are the phases the old guard skipped.
for phase in ("CODE", "CLOSEOUT", "PLAN"):
    for rel in SEALED:
        assert ask(phase, rel) == 2, f"{phase} can write {rel}"
# …and none of that may cost the writes a ticket is made of.
for phase, rel in (("CODE", "src/app.py"), ("CODE", "docs/ddw/prd/prd-T-1.md"),
                   ("PLAN", ".ddw-paused/T-1.ddw-state.json"),
                   ("PLAN", "docs/ddw/specs/spec-T-1.md"), ("CODE", ".claude/agents/mine.md")):
    assert ask(phase, rel) == 0, f"{phase} was refused {rel}, which is legitimate work"
PYENF

# The other half, for the writes no hook can see. `printf > .ddw/...` is not a
# tool call with a path in it (docs/RATIONALE.md decision 11), so the manifest
# carries a hash per installed file — and nothing had ever read it back.
python3 - "$SELF" <<'PYDRIFT' && ok "a tampered install is reported at boot, and a correct one says nothing — for all six tools" || bad "the enforcement can be replaced through a shell and the next session is never told"
import os, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
MARK = "not what was installed"
for target in ("claude", "codex", "copilot", "cursor", "gemini", "opencode"):
    repo = os.path.join(work, target)
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", target],
                   capture_output=True, text=True)
    boot = os.path.join(repo, ".ddw", "scripts", "session-boot.py")

    def say():
        return subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", "s"],
                              capture_output=True, text=True).stdout

    # A correct install is silent. A drift report that cries on every clean repo
    # is one nobody reads by the third session.
    assert MARK not in say(), f"{target}: a clean install is reported as tampered"
    manifest = os.path.join(repo, ".ddw-installed.json")
    import json
    recorded = json.load(open(manifest, encoding="utf-8"))
    assert recorded, f"{target}: nothing was recorded"
    # Every entry has to resolve to something on disk, or the check is comparing
    # against paths that do not exist — which is what it did: 22 of 28 entries
    # named the SOURCE layout, so nothing could be verified at all.
    for key in recorded:
        rel = key.split(":", 1)[1] if ":" in key else key
        assert os.path.exists(os.path.join(repo, rel)), f"{target}: manifest names {rel}, absent"
    victim = sorted(k.split(":", 1)[-1] for k in recorded)[0]
    path = os.path.join(repo, victim)
    if os.path.isdir(path):
        import shutil
        shutil.rmtree(path)
        expect = "MISSING"
    else:
        open(path, "a", encoding="utf-8").write("\n# tampered\n")
        expect = "CHANGED"
    out = say()
    assert MARK in out and expect in out and victim in out, \
        f"{target}: tampering with {victim} was not reported: {out[:200]}"

    # …and the three files the detection actually exists for, by name. The
    # victim above is `sorted(...)[0]`, which on every tool is the first thing
    # under `.claude/` or its equivalent — so this check could never reach the
    # method, and the method was not in the manifest at all: a clean install
    # recorded 28 entries and none of them under `.ddw/`. Tampering with the
    # graph, the validator and the gate reported NOTHING, while the same byte in
    # a hook script reported CHANGED. The graph decides which gates exist; it was
    # the least watched file in the repository.
    for rel in (".ddw/rules/transition-graph.json",
                ".ddw/scripts/validate-transition.py",
                ".ddw/scripts/hook-gate.py"):
        assert "method:" + rel in recorded, \
            f"{target}: {rel} is not in the manifest, so no shell edit to it is ever reported"
        with open(os.path.join(repo, rel), "a", encoding="utf-8") as fh:
            fh.write("\n# tampered\n")
        out = say()
        assert MARK in out and "CHANGED" in out and rel in out, \
            f"{target}: a shell rewriting {rel} is not reported at boot: {out[:200]}"
PYDRIFT

# The gates' own worst case, and the easiest state in the world to be in: the
# document simply does not exist. `_receipt_missing` returned None there — "no
# artifact on disk means no claim to check" — and that sentence is false at every
# call site, because the function is only reached for a gate BEING CLAIMED.
# Measured on a real install: a FEATURE walked IDLE→CLOSEOUT with no PRD, no
# spec, no threat model, no test report, no SAST report and no verdict, six gates
# true, both hooks green, nothing on disk at all.
python3 - "$SELF" <<'PYNOART' && ok "a gate claimed for a document that does not exist is refused, and so is one nothing can read" || bad "six of the eight gates open when the artifact is simply absent — the whole pipeline walks with no artifacts at all"
import hashlib, json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
tr = os.path.join(repo, ".ddw", "scripts", "transition.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")

# The classify edge's context check — a different gate than the receipts under
# test, satisfied so every refusal below is about the missing artifact alone.
os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
open(os.path.join(repo, ".ddw-work", "context-check-T-1.md"), "w", encoding="utf-8").write(
    "Nothing to report.\n")


def step(*args):
    return subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                           *args], capture_output=True, text=True)


assert step("--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE",
            "--ticket", "T-1").returncode == 0
assert step("--to", "DEFINE", "--action", "d", "--title", "the fixture ticket").returncode == 0
# No PRD anywhere. This walked straight through before.
r = step("--to", "PLAN", "--action", "p", "--gate", "define")
assert r.returncode != 0, "the define gate opened with no PRD on disk"
assert "no PRD" in r.stderr and "prd-T-1.md" in r.stderr, \
    "the refusal does not say what is missing or where it goes: " + r.stderr[:200]
# A document nothing can decode is a document no receipt can name — same answer.
prd = os.path.join(repo, "docs", "ddw", "prd")
os.makedirs(prd, exist_ok=True)
open(os.path.join(prd, "prd-T-1.md"), "wb").write(b"# PRD\n\xff\xfe not utf-8\n")
r = step("--to", "PLAN", "--action", "p", "--gate", "define")
assert r.returncode != 0, "one non-UTF-8 byte turned the refusal into a pass"
# And the legitimate path still works, or this rule is just a wall.
open(os.path.join(prd, "prd-T-1.md"), "w", encoding="utf-8").write("# PRD\n")
digest = hashlib.sha256(open(os.path.join(prd, "prd-T-1.md"), encoding="utf-8").read()
                        .encode("utf-8")).hexdigest()[:12]
sess = os.path.join(repo, ".ddw-sessions")
os.makedirs(sess, exist_ok=True)
open(os.path.join(sess, "prd-validated-%s" % digest), "w").write("prd-T-1.md")
with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"record": "receipt", "name": "prd-validated-%s" % digest,
                         "file": "prd-T-1.md"}, sort_keys=True) + "\n")
assert step("--to", "PLAN", "--action", "p", "--gate", "define").returncode == 0, \
    "a PRD that exists and has its receipt is still refused"
# A gate with two candidate names — `spec` also accepts `fix` — must not have its
# search ended by something that is not a document. A DIRECTORY called
# spec-T-1.md, next to a real validated fix-T-1.md, refused legitimate work when
# the search asked whether the path existed instead of whether it was a file.
specs = os.path.join(repo, "docs", "ddw", "specs")
os.makedirs(os.path.join(specs, "spec-T-1.md"), exist_ok=True)
fix = os.path.join(specs, "fix-T-1.md")
open(fix, "w", encoding="utf-8").write("# fix plan\n")
d2 = hashlib.sha256(open(fix, encoding="utf-8").read().encode("utf-8")).hexdigest()[:12]
open(os.path.join(sess, "spec-validated-%s" % d2), "w").write("fix-T-1.md")
with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"record": "receipt", "name": "spec-validated-%s" % d2,
                         "file": "fix-T-1.md"}, sort_keys=True) + "\n")
threat = os.path.join(repo, "docs", "ddw", "security")
os.makedirs(threat, exist_ok=True)
tp = os.path.join(threat, "threat-T-1.md")
open(tp, "w", encoding="utf-8").write("# threat model\n")
d3 = hashlib.sha256(open(tp, encoding="utf-8").read().encode("utf-8")).hexdigest()[:12]
open(os.path.join(sess, "threat-validated-%s" % d3), "w").write("threat-T-1.md")
with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"record": "receipt", "name": "threat-validated-%s" % d3,
                         "file": "threat-T-1.md"}, sort_keys=True) + "\n")
r = step("--to", "CODE", "--action", "co", "--gate", "spec", "--gate", "threat")
assert r.returncode == 0, \
    "a directory named like one candidate ended the search and refused a validated fix plan: " + r.stderr[:200]
PYNOART

# A receipt is a file, and a file can be written by anything that writes files.
# The pre-write hook refuses the tool path in every phase; a shell is not a tool
# call with a path in it. So the validators record in the journal that they wrote
# each receipt, and the gate asks for both.
python3 - "$SELF" <<'PYWITNESS' && ok "a receipt no validator is recorded as having written does not open its gate" || bad "a receipt written by hand still opens its gate — the shell path is unguarded and unreported"
import hashlib, importlib.util, json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
tr = os.path.join(repo, ".ddw", "scripts", "transition.py")
vt = os.path.join(repo, ".ddw", "scripts", "validate-transition.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
prd_dir = os.path.join(repo, "docs", "ddw", "prd")
os.makedirs(prd_dir)
prd = os.path.join(prd_dir, "prd-T-1.md")
open(prd, "w", encoding="utf-8").write("# PRD\n")
# The classify edge's context check — not the witness rule under test.
os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
open(os.path.join(repo, ".ddw-work", "context-check-T-1.md"), "w", encoding="utf-8").write(
    "Nothing to report.\n")


def step(*args):
    return subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                           *args], capture_output=True, text=True)


assert step("--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE",
            "--ticket", "T-1").returncode == 0
assert step("--to", "DEFINE", "--action", "d", "--title", "the fixture ticket").returncode == 0
subprocess.run([sys.executable, vt, "--mode", "post", "--state", state, "--graph", graph],
               capture_output=True, text=True)
journal = os.path.join(repo, ".ddw-journal.jsonl")
assert os.path.exists(journal), "no journal, so the witness rule has nothing to read"

digest = hashlib.sha256(open(prd, encoding="utf-8").read().encode("utf-8")).hexdigest()[:12]
sess = os.path.join(repo, ".ddw-sessions")
os.makedirs(sess, exist_ok=True)
forged = os.path.join(sess, "prd-validated-%s" % digest)
open(forged, "w", encoding="utf-8").write("prd-T-1.md\n")
r = step("--to", "PLAN", "--action", "p", "--gate", "define")
assert r.returncode == 2 and "no validator is recorded" in r.stderr, \
    "a hand-written receipt opened the define gate: %s" % (r.stderr[:220] or "(it was accepted)")

# …and the same receipt, written the way a validator writes it, is accepted. The
# rule has to discriminate, not merely refuse.
os.remove(forged)
rspec = importlib.util.spec_from_file_location(
    "ddw_receipt", os.path.join(repo, ".ddw", "scripts", "ddw_receipt.py"))
rmod = importlib.util.module_from_spec(rspec); rspec.loader.exec_module(rmod)
rmod.write(prd, "prd", open(prd, encoding="utf-8").read())
r = step("--to", "PLAN", "--action", "p", "--gate", "define")
assert r.returncode == 0, "a receipt written by the validator's own writer was refused: %s" % r.stderr[:220]
assert any(json.loads(l).get("record") == "receipt"
           for l in open(journal, encoding="utf-8") if l.strip()), \
    "writing a receipt recorded nothing in the journal"
PYWITNESS

# Six more the mutation run found uncovered, each a rule that exists and that
# nothing had ever broken on purpose.
python3 - "$SELF" <<'PYSIX' && ok "the helper fails closed, install.sh reads either manifest, uninstall takes the .gitignore it created, the hooks' comments match their code, the release step really runs, and every rule ID shown is catalogued" || bad "one of the six: a traceback instead of a verdict, an upgrade that re-asks, a leftover file, a comment that lies, a release step that is a comment, or a rule ID in no catalog"
import glob, json, os, re, shutil, subprocess, sys, tempfile
src = sys.argv[1]

# 1. The helper answers an unexpected fault with a sentence and exit 2. Exit 1 is
#    what a shell reads as an ordinary error and a caller may continue past.
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "r1")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
bad_graph = os.path.join(repo, "weird.json")
open(bad_graph, "w", encoding="utf-8").write('{"common": "not a mapping", "tiers": {}}')
r = subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/transition.py"),
                    "--state", os.path.join(repo, ".ddw-state.json"), "--graph", bad_graph,
                    "--to", "CLASSIFY", "--action", "x"], capture_output=True, text=True)
assert r.returncode == 2, "an unexpected fault exited %d, not 2 — exit 1 reads as 'carry on'" % r.returncode
assert "Traceback" not in r.stderr and "could not reach a verdict" in r.stderr, \
    "the helper answered with a stack instead of a sentence: " + r.stderr[-200:]

# 2. install.sh finds the manifest wherever a previous version left it. It moved
#    out of .ddw/ once; reading only the new place makes an upgrade look like a
#    first install and re-ask the question the manifest exists to answer.
legacy = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "r2")
os.makedirs(legacy)
subprocess.run(["git", "-C", legacy, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), legacy, "--target", "claude"],
               capture_output=True, text=True)
os.makedirs(os.path.join(legacy, ".ddw"), exist_ok=True)
os.rename(os.path.join(legacy, ".ddw-installed.json"),
          os.path.join(legacy, ".ddw", ".installed.json"))
out = subprocess.run(["bash", os.path.join(src, "install.sh"), legacy, "--target", "claude"],
                     capture_output=True, text=True).stdout
# Anchored on the headline, not on line 0: the installer opens with a banner
# now, and "the first line says updating" was a fact about the old layout rather
# than about the thing being checked. Both directions are asserted, so a run
# that called every install an update still fails — that is what the pair of
# checks further up is for, and this one no longer depends on where in the
# output the sentence lands.
assert (any("is updating:" in l for l in out.splitlines())
        and "installing into" not in out), \
    ("an upgrade from a pre-move install announced itself as a first install — it did not find "
     "the manifest, which is what tells DDW's wiring from yours:\n" + out[:200])

# 3. The .gitignore: created by the install only when it writes into it, and
#    removed by the uninstall when nothing of yours is left in it.
gi = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "r3")
os.makedirs(gi)
subprocess.run(["git", "-C", gi, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), gi, "--target", "claude"],
               capture_output=True, text=True)
subprocess.run(["bash", os.path.join(src, "uninstall.sh"), gi, "--yes"],
               capture_output=True, text=True)
assert not os.path.exists(os.path.join(gi, ".gitignore")), \
    "the uninstall left behind the empty .gitignore the install created"
# …and a .gitignore that was yours keeps its rules and loses only the block.
gi2 = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "r4")
os.makedirs(gi2)
subprocess.run(["git", "-C", gi2, "init", "-q"], check=True)
open(os.path.join(gi2, ".gitignore"), "w", encoding="utf-8").write("node_modules/\n")
subprocess.run(["bash", os.path.join(src, "install.sh"), gi2, "--target", "claude"],
               capture_output=True, text=True)
subprocess.run(["bash", os.path.join(src, "uninstall.sh"), gi2, "--yes"],
               capture_output=True, text=True)
kept = open(os.path.join(gi2, ".gitignore"), encoding="utf-8").read()
assert "node_modules/" in kept and "BEGIN DDW" not in kept, \
    "a .gitignore of the user's was destroyed or left with DDW's block: %r" % kept

# 4b. And BEFORE that: that the hook actually refuses, executed without
#     python3. The block below reads text and skips the file that lacks it
#     ('if "command -v python3" not in text: continue'), meaning deleting the
#     whole block passes — and it globs `adapters/*/hooks/**`, where Copilot's
#     do not live: theirs are in `adapters/copilot/scripts/`. Copilot's two
#     write-deciding hooks exited 127 ("python3: not found") where the other
#     five exit 2, and any exit other than 2 is a NON-BLOCKING error: the
#     write went in with nothing judging it. Measured, not read.
#
#     Over the INSTALLED hooks, not the source tree's: run from here they
#     consider themselves not installed and exit 0 rightly, and that 0 reads
#     identical to the one this check exists to forbid.
_bin = tempfile.mkdtemp(dir=os.environ["WORK"])
for _tool in ("bash", "sh", "git", "env", "cat", "grep", "sed", "dirname", "basename", "mkdir"):
    _found = shutil.which(_tool)
    if _found:
        os.symlink(_found, os.path.join(_bin, _tool))
# The ones that JUDGE a write. `enforce.sh` runs in the same PreToolUse and is
# not one: it does housekeeping (creates the state, refreshes the session
# marker) and exiting 0 without python3 is correct there — it had nothing to
# say about the write. `session-start.sh` and `pre-compact.sh` inform. The
# difference is what this check measures: whoever decides, decides or refuses;
# whoever does not, stays silent.
_DECIDERS = ("pre-tool-use.sh", "post-write.sh",
             "validate-state-transition.sh", "validate-state-postwrite.sh")
_open, _seen = [], 0
for _target in ("claude", "codex", "copilot", "cursor", "gemini"):
    _r6 = tempfile.mkdtemp(dir=os.environ["WORK"])
    subprocess.run(["git", "-C", _r6, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), _r6, "--target", _target],
                   capture_output=True, text=True)
    # `os.walk`, not `glob`: `**` does not enter hidden directories, and ALL
    # the hooks live in one — `.claude/`, `.github/`, `.cursor/`. The glob
    # returned zero files and the check would have passed for finding nothing
    # to judge.
    _found_hooks = []
    for _dirpath, _dirnames, _files in os.walk(_r6):
        if ".git" in _dirpath.split(os.sep):
            continue
        _found_hooks += [os.path.join(_dirpath, _f) for _f in _files if _f in _DECIDERS]
    for _h in _found_hooks:
        _seen += 1
        _r = subprocess.run(["bash", _h],
                            input='{"tool_name":"Write","tool_input":{"file_path":"'
                                  + os.path.join(_r6, "src/a.py") + '"}}',
                            capture_output=True, text=True, cwd=_r6,
                            # Claude resolves the repo via `CLAUDE_PROJECT_DIR`
                            # and stays silent if it is missing: without this its
                            # three hooks exit 0 for not knowing where they are,
                            # and that 0 reads like the one this check forbids.
                            env={"PATH": _bin, "HOME": os.environ.get("HOME", "/tmp"),
                                 "CLAUDE_PROJECT_DIR": _r6},
                            timeout=30)
        if _r.returncode != 2:
            _open.append("%s/%s → exit %d" % (_target, os.path.basename(_h), _r.returncode))
assert _seen >= 8, \
    ("only %d installed write-deciding hooks were found across the five adapters; the "
     "sweep stopped seeing one, and an empty sweep passes this check judging nothing" % _seen)
assert not _open, \
    ("without python3 on the PATH these installed hooks do not refuse the write, and any exit "
     "other than 2 is a non-blocking error — the write goes in with nothing having judged it: "
     + "; ".join(_open))

# 4. A comment that says the opposite of the four lines under it is worse than no
#    comment: whoever is checking whether the guard is safe reads the sentence.
for hook in glob.glob(os.path.join(src, "adapters/*/hooks/**/*.sh"), recursive=True):
    text = open(hook, encoding="utf-8").read()
    if "command -v python3" not in text:
        continue
    tail = text[text.index("command -v python3"):][:400]
    exits_2 = "exit 2" in tail
    claims_open = re.search(r"fail[- ]open", text[:text.index("command -v python3")][-400:], re.I)
    assert not (exits_2 and claims_open), \
        "%s exits 2 without python3 and its comment calls that fail-open" % os.path.basename(hook)

# 5. The release step has to RUN the suite, not mention it. A commented-out line
#    contains the same string.
import yaml
rel = yaml.safe_load(open(os.path.join(src, ".github/workflows/release.yml"), encoding="utf-8"))
rsteps = [str(st.get("run", "")) for job in rel["jobs"].values() for st in job.get("steps", [])]
def runs(needle):
    """Present in a line that is not commented out. `true # scripts/...` still
    contains the string, and a workflow that mentions the suite does not run it."""
    for block in rsteps:
        for line in block.splitlines():
            code = line.split("#", 1)[0]
            if needle in code:
                return True
    return False
assert runs("scripts/verify_install.sh"), \
    "the release workflow does not RUN the suite — it would publish unvalidated"

# 6. Every rule ID a validator SHOWS the user is defined in the catalog. The
#    catalog's own linter matched only numeric suffixes, so F-SAST-COVERAGE and
#    its siblings were excused by the pattern rather than by being catalogued.
catalog = open(os.path.join(src, "ddw/rules/validation-rules.instructions.md"),
               encoding="utf-8").read()
defined = set(re.findall(r"\b([FW]-[A-Z]+-[A-Z0-9]{2,})\b", catalog))
shown = set()
for v in glob.glob(os.path.join(src, "ddw/scripts/validate_*.py")):
    shown |= set(re.findall(r'"([FW]-[A-Z]+-[A-Z0-9]{2,})"', open(v, encoding="utf-8").read()))
missing = sorted(shown - defined)
assert not missing, "these rule IDs are printed to users and defined in no catalog: %s" % missing
# …asked THROUGH the linter, which is what runs in CI. Computing the answer here
# left the linter free to stop asking: its pattern demanded a numeric suffix, so
# F-SAST-COVERAGE and its siblings were excused by the regex rather than by
# being catalogued.
probe = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
subprocess.run(["cp", "-r", src, probe], check=True)
victim = os.path.join(probe, "ddw/rules/plan.instructions.md")
open(victim, "a", encoding="utf-8").write("\n\nSee F-MADEUP-RULE for the details.\n")
r = subprocess.run([sys.executable, os.path.join(probe, "scripts/lint_method.py")],
                   capture_output=True, text=True, cwd=probe)
assert r.returncode != 0 and "F-MADEUP-RULE" in (r.stdout + r.stderr), \
    ("the linter no longer notices a rule ID the catalog does not define — a word-suffixed ID "
     "is excused by its pattern again, which is how F-SAST-COVERAGE went uncatalogued: "
     + (r.stdout + r.stderr)[-200:])
PYSIX

# ── Two hooks at once, and a ticket that outlives lunch ──────────────────────
#
# The model is encouraged to batch independent tool calls, and the post matcher
# fires on every one of them — so two post hooks in one turn is the ordinary
# case, not a corner. They both read "how many entries does the journal have"
# and both appended the same one, after which the erase check read a duplicated
# line as a deleted entry and refused EVERY write in the repo, forever, blaming
# the state file. Measured at five repos in twelve before the fix.
python3 - "$SELF" <<'PYRACE' && ok "parallel post hooks do not wedge the repo, a duplicated journal line is not read as a deletion, and a receipt outlives a two-hour ticket" || bad "the journal races itself into a permanent refusal, or the session sweep deletes the evidence the gates rest on"
import json, os, subprocess, sys, tempfile, time
src = sys.argv[1]


def fresh():
    repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                   capture_output=True, text=True)
    return repo


TRIALS = 8
wedged = 0
for _ in range(TRIALS):
    repo = fresh()
    tr = os.path.join(repo, ".ddw/scripts/transition.py")
    gate = os.path.join(repo, ".ddw/scripts/hook-gate.py")
    graph = os.path.join(repo, ".ddw/rules/transition-graph.json")
    state = os.path.join(repo, ".ddw-state.json")

    def post():
        return subprocess.Popen([sys.executable, gate, "--mode", "post", "--state", state,
                                 "--graph", graph, "--repo", repo],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                    "--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE", "--ticket", "T-1"],
                   capture_output=True)
    post().wait()
    # The classify edge's context check — without it the DEFINE below fails
    # silently and the race is measured over one transition instead of two.
    os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
    open(os.path.join(repo, ".ddw-work", "context-check-T-1.md"), "w", encoding="utf-8").write(
        "Nothing to report.\n")
    subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                    "--to", "DEFINE", "--action", "d", "--title", "the fixture ticket"], capture_output=True)
    a, b = post(), post()
    a.wait(); b.wait()
    if post().wait() != 0:
        wedged += 1
assert wedged == 0, \
    "%d of %d repos were permanently wedged by two post hooks in one turn" % (wedged, TRIALS)
# The repo surviving is the outcome that matters; the journal not growing a
# duplicate is the mechanism. Both are checked, because the content comparison
# below makes a duplicate harmless — and a harmless duplicate is still a record
# that says a transition happened twice when it happened once.
dupes = 0
for _ in range(TRIALS):
    repo = fresh()
    tr = os.path.join(repo, ".ddw/scripts/transition.py")
    gate = os.path.join(repo, ".ddw/scripts/hook-gate.py")
    graph = os.path.join(repo, ".ddw/rules/transition-graph.json")
    state = os.path.join(repo, ".ddw-state.json")
    subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                    "--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE", "--ticket", "T-1"],
                   capture_output=True)
    procs = [subprocess.Popen([sys.executable, gate, "--mode", "post", "--state", state,
                               "--graph", graph, "--repo", repo],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for _ in range(3)]
    for pr in procs:
        pr.wait()
    lines = [l for l in open(os.path.join(repo, ".ddw-journal.jsonl"), encoding="utf-8")
             if l.strip()]
    if len(lines) != len(set(lines)):
        dupes += 1
assert dupes == 0, \
    "%d of %d journals grew a duplicate line: the read and the append are not one " \
    "critical section" % (dupes, TRIALS)

# And the same refusal reached by hand: a journal line written twice is a
# duplicate, not a deletion. The lock above is advisory and a filesystem may not
# have one, so the comparison has to survive it landing anyway.
import importlib.util
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp(dir=os.environ["WORK"])
st = os.path.join(d, ".ddw-state.json")
H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "c"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "d"}]
json.dump({"phase": "DEFINE", "history": H}, open(st, "w", encoding="utf-8"))
jp = os.path.join(d, ".ddw-journal.jsonl")
open(jp, "w", encoding="utf-8").write(
    "\n".join(json.dumps(e, sort_keys=True) for e in H + [H[1]]) + "\n")
m._check_state_not_erased(st)                       # raises if a duplicate reads as a deletion
# …and in the shape the race actually writes. Two hooks appending at once do not
# produce neighbours: each writes the whole tail it believes is missing, so the
# lines interleave (classify, define, classify, define) and a fold that only
# looks at the previous line walks straight past every one of them. This is the
# journal a wedged repo really had.
open(jp, "w", encoding="utf-8").write(
    "\n".join(json.dumps(e, sort_keys=True) for e in H + H) + "\n")
m._check_state_not_erased(st)
# And deleting the journal outright does not turn the witness check off. `rm
# .ddw-journal.jsonl` was one command, and it took a hand-written receipt from
# "no validator is recorded as having written this" to "nothing to compare
# against" — which read as permission. A repo where DDW has never run still has
# to be told apart from one whose record was removed, and the state's own
# history is what tells them apart.
os.unlink(jp)
assert m._receipt_witnesses(d) == set(), \
    "a run with a history and no journal is read as a repo DDW has never touched, so every " \
    "receipt on disk is taken on faith"
json.dump({"phase": "IDLE", "history": []}, open(st, "w", encoding="utf-8"))
assert m._receipt_witnesses(d) is None, \
    "a repo where DDW has never run is treated as one whose journal was deleted"
json.dump({"phase": "DEFINE", "history": H}, open(st, "w", encoding="utf-8"))
open(jp, "w", encoding="utf-8").write(
    "\n".join(json.dumps(e, sort_keys=True) for e in H + H) + "\n")
assert len(m._journal_entries(st)) == len(H), \
    "a journal line written twice counts as another transition, so the index that finds what " \
    "just landed slides past it and post mode owes evidence for nothing"
# …and a genuinely dropped entry is still refused.
open(jp, "w", encoding="utf-8").write("\n".join(json.dumps(e, sort_keys=True) for e in H + [
    {"timestamp": "2026-01-01T00:02:00Z", "from": "DEFINE", "to": "PLAN", "action": "p"}]) + "\n")
try:
    m._check_state_not_erased(st)
    raise AssertionError("an entry that really was dropped is no longer noticed")
except m.Block:
    pass

# The sweep that expires dead sessions must not touch the evidence. Receipts and
# liveness markers used to share one directory, and every ticket longer than two
# hours had its gates deleted by the bookkeeping.
repo = fresh()
boot = os.path.join(repo, ".ddw/scripts/session-boot.py")
sess = os.path.join(repo, ".ddw-sessions")
os.makedirs(sess, exist_ok=True)
receipt = os.path.join(sess, "prd-validated-deadbeef1234")
open(receipt, "w", encoding="utf-8").write("prd-T-1.md\n")
old = time.time() - 3 * 60 * 60
os.utime(receipt, (old, old))
out = subprocess.run([sys.executable, boot, "--repo", repo, "--session-id", "s1"],
                     capture_output=True, text=True).stdout
assert os.path.exists(receipt), \
    "the session sweep deleted a validation receipt three hours old — every FEATURE loses its gates"
# …and a receipt is not another session, either.
assert "other session" not in out, \
    "a receipt on disk was counted as a session working in the directory:\n" + out[:300]
PYRACE

# ── The three tiers that are not FEATURE ─────────────────────────────────────
#
# The `define` gate looked for `prd-<ticket>.md` and nothing else, which was
# invisible while a missing document counted as no claim — and became a wall the
# moment that stopped being true. QUICK-FIX writes a fix brief and FIX writes an
# RCA; neither could leave DEFINE at all.
python3 - "$SELF" <<'PYTIERS' && ok "every tier can leave DEFINE with the document its own phase writes, and the QUICK-FIX guard reads a capitalised path" || bad "a tier cannot walk its own pipeline, or the sensitive-path guard misses the conventions half the ecosystems use"
import hashlib, importlib.util, json, os, subprocess, sys, tempfile
src = sys.argv[1]

WRITES = {"FEATURE": ("prd", "prd", "prd"),
          "QUICK-FIX": ("prd", "fix", "prd"),
          "FIX": ("specs", "rca", "prd")}
for tier, (subdir, stem, receipt) in WRITES.items():
    repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                   capture_output=True, text=True)
    tr = os.path.join(repo, ".ddw/scripts/transition.py")
    graph = os.path.join(repo, ".ddw/rules/transition-graph.json")
    state = os.path.join(repo, ".ddw-state.json")
    d = os.path.join(repo, "docs", "ddw", subdir)
    os.makedirs(d, exist_ok=True)
    doc = os.path.join(d, "%s-T-1.md" % stem)
    open(doc, "w", encoding="utf-8").write("# the document this tier's DEFINE writes\n")
    rspec = importlib.util.spec_from_file_location(
        "ddw_receipt", os.path.join(repo, ".ddw/scripts/ddw_receipt.py"))
    rmod = importlib.util.module_from_spec(rspec); rspec.loader.exec_module(rmod)
    rmod.write(doc, receipt, open(doc, encoding="utf-8").read())
    # The classify edge's context check — a different gate than the one under test.
    os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
    open(os.path.join(repo, ".ddw-work", "context-check-T-1.md"), "w", encoding="utf-8").write(
        "Nothing to report.\n")

    def step(*args):
        return subprocess.run([sys.executable, tr, "--state", state, "--graph", graph,
                               "--write", *args], capture_output=True, text=True)

    assert step("--to", "CLASSIFY", "--action", "c", "--tier", tier,
                "--ticket", "T-1").returncode == 0, tier
    assert step("--to", "DEFINE", "--action", "d", "--title", "the fixture ticket").returncode == 0, tier
    nxt = "CODE" if tier == "QUICK-FIX" else "PLAN"
    r = step("--to", nxt, "--action", "next", "--gate", "define")
    assert r.returncode == 0, \
        "%s cannot leave DEFINE with the document its own phase writes (docs/ddw/%s/%s-T-1.md): %s" % (
            tier, subdir, stem, r.stderr[:220])

# The QUICK-FIX sensitive-path guard, in the capitalisation half the ecosystems
# use. The list calls itself deliberately wide and was case-sensitive, so it was
# widest exactly where it was least likely to bite.
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = os.path.realpath(tempfile.mkdtemp(dir=os.environ["WORK"]))
qf = {"tier": "QUICK-FIX"}
for rel in ("app/Http/Middleware/Authenticate.php", "src/API/keys.py",
            "db/Migrations/001.sql", "schema.SQL", "config/.ENV"):
    assert m.quickfix_scope_denied(os.path.realpath(os.path.join(root, rel)), root, qf), \
        "a QUICK-FIX may touch %s — the guard is case-sensitive and the path is not lowercase" % rel
for rel in ("src/ui/button.py", "docs/ddw/prd/prd-T-1.md"):
    assert not m.quickfix_scope_denied(os.path.realpath(os.path.join(root, rel)), root, qf), \
        "%s was refused, and a guard that stops ordinary work gets routed around" % rel
PYTIERS

# The closing edge is the write that SPENDS `commit` and `pr` rather than
# claiming them, and evidence used to be owed only where a gate is claimed — so
# the two gates that ask the world outside this repository were never asked on
# the write that cashes them. Between the claim and the spend a commit can be
# amended away and a pull request closed.
python3 - "$SELF" <<'PYSPEND' && ok "the write that spends commit and pr is asked for their evidence, not only the write that claimed them" || bad "the closing edge owes evidence to nobody: the gates are asked when turned on and never when cashed"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
for k, v in (("user.email", "ddw@test"), ("user.name", "ddw"), ("commit.gpgsign", "false")):
    subprocess.run(["git", "-C", repo, "config", k, v], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
open(os.path.join(repo, "f.txt"), "w", encoding="utf-8").write("x\n")
subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
subprocess.run(["git", "-C", repo, "commit", "-qm", "base"], capture_output=True)
state = os.path.join(repo, ".ddw-state.json")
E = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN"), ("PLAN", "CODE"),
     ("CODE", "VERIFY"), ("VERIFY", "CLOSEOUT")]
H = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
      "tier": "FEATURE", "ticket": "T-1"} for i, (f, t) in enumerate(E)]
G = {k: True for k in ("define", "spec", "threat", "tests", "sast", "verify", "commit", "pr")}
cur = {"tier": "FEATURE", "phase": "CLOSEOUT", "ticket": "T-1", "title": None, "tracker": None,
       "autonomy": None, "gates": G, "block": None, "discovery": None, "history": H}
json.dump(cur, open(state, "w", encoding="utf-8"))
nxt = dict(cur)
nxt.update({"tier": None, "phase": "IDLE", "ticket": None, "gates": {},
            "history": H + [{"timestamp": "2026-01-01T02:00:00Z", "from": "CLOSEOUT",
                             "to": "IDLE", "action": "done", "tier": "FEATURE",
                             "ticket": "T-1"}]})
ev = json.dumps({"tool_name": "Write",
                 "tool_input": {"file_path": state, "content": json.dumps(nxt)}})


def close():
    return subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/validate-transition.py"),
                           "--mode", "pre", "--state", state, "--graph",
                           os.path.join(repo, ".ddw/rules/transition-graph.json"), "--repo", repo],
                          input=ev, capture_output=True, text=True)


# A clean tree closes.
_r = close()
assert _r.returncode == 0, "a legitimate closeout was refused: " + (_r.stdout + _r.stderr)[:220]
# …and the same closeout, with the work no longer committed, does not.
open(os.path.join(repo, "f.txt"), "a", encoding="utf-8").write("changed after the claim\n")
r = close()
said = r.stdout + r.stderr
assert r.returncode == 2 and "commit gate" in said, \
    "the closing edge accepted a state whose commit gate no longer holds: " + (said[:220] or "(allowed)")
PYSPEND

# …and asked of the SANCTIONED HELPER too, which is the path the method actually
# tells the model to take. The hook learned this first and `transition.py` had
# not: it asked `gate_evidence_missing` only about the gates named in `--gate`,
# and `--gate` is refused on `--to IDLE` — so the closing run named nothing, was
# asked nothing, and closed the ticket over uncommitted work with exit 0 while
# every hook stayed green.
python3 - "$SELF" <<'PYHELPERCLOSE' && ok "the helper asks the closing edge for the evidence it spends, and not only the hook" || bad "a ticket closes through the sanctioned helper over work that only exists on your disk"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
for k, v in (("user.email", "ddw@test"), ("user.name", "ddw"), ("commit.gpgsign", "false")):
    subprocess.run(["git", "-C", repo, "config", k, v], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
open(os.path.join(repo, "f.txt"), "w", encoding="utf-8").write("x\n")
subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
subprocess.run(["git", "-C", repo, "commit", "-qm", "base"], capture_output=True)
state = os.path.join(repo, ".ddw-state.json")
E = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "PLAN"), ("PLAN", "CODE"),
     ("CODE", "VERIFY"), ("VERIFY", "CLOSEOUT")]
H = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "x",
      "tier": "FEATURE", "ticket": "T-1"} for i, (f, t) in enumerate(E)]
G = {k: True for k in ("define", "spec", "threat", "tests", "sast", "verify", "commit", "pr")}
cur = {"tier": "FEATURE", "phase": "CLOSEOUT", "ticket": "T-1", "title": None, "tracker": None,
       "autonomy": None, "gates": G, "block": None, "discovery": None, "history": H}


def closeout():
    json.dump(cur, open(state, "w", encoding="utf-8"))
    return subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/transition.py"),
                           "--to", "IDLE", "--action", "closeout", "--state", state,
                           "--graph", os.path.join(repo, ".ddw/rules/transition-graph.json"),
                           "--write"], capture_output=True, text=True, cwd=repo)


r = closeout()
assert r.returncode == 0, "a legitimate closeout was refused by the helper: " + (r.stdout + r.stderr)[:220]
assert json.load(open(state, encoding="utf-8"))["phase"] == "IDLE", "the helper did not land the closeout"
open(os.path.join(repo, "f.txt"), "a", encoding="utf-8").write("changed after the claim\n")
r = closeout()
said = r.stdout + r.stderr
assert r.returncode == 2 and "commit gate" in said, \
    "the helper closed a ticket over uncommitted tracked work: " + (said[:220] or "(allowed)")
assert json.load(open(state, encoding="utf-8"))["phase"] == "CLOSEOUT", \
    "the helper refused the closeout and wrote it anyway"
PYHELPERCLOSE

# Two runs of the helper in one turn is the ordinary case — the model is
# encouraged to issue parallel tool calls — and read and write were not one
# critical section: both read the same phase, both validated against it, both
# wrote, and the second `os.replace` dropped the first one's edge while both
# exited 0. A transition that reports success and is not on disk afterwards is
# the one outcome this helper exists to prevent.
python3 - "$SELF" <<'PYRACEWRITE' && ok "two helper runs racing on one state never both report success for one landed edge" || bad "a concurrent transition is lost: the helper exits 0 on an edge that is not there afterwards"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
graph = os.path.join(src, "ddw/rules/transition-graph.json")
helper = os.path.join(src, "ddw/scripts/transition.py")
TRIALS = 8
lost = []
for trial in range(TRIALS):
    repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    state = os.path.join(repo, ".ddw-state.json")
    seed = {"tier": None, "phase": "CLASSIFY", "ticket": None, "title": None, "tracker": None,
            "autonomy": None, "gates": {}, "block": None, "discovery": None,
            "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                         "action": "start"}]}
    json.dump(seed, open(state, "w", encoding="utf-8"))
    procs = [subprocess.Popen([sys.executable, helper, "--to", "DEFINE", "--tier", "FEATURE", "--title", "the fixture ticket",
                               "--ticket", "T-%d" % n, "--action", "racer %d" % n,
                               "--state", state, "--graph", graph, "--write"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=repo)
             for n in (1, 2)]
    winners = sum(1 for p in procs if p.wait() == 0)
    for p in procs:
        p.stdout.close()
        p.stderr.close()
    landed = len(json.load(open(state, encoding="utf-8"))["history"]) - 1
    if winners != landed:
        lost.append("trial %d: %d run(s) exited 0, %d edge(s) on disk" % (trial, winners, landed))
assert not lost, "; ".join(lost[:3])

# And the guarantee underneath it, asked where no lock can answer for it. The
# lock serialises two runs that both have one to take; a filesystem without
# flock — an NFS mount, a container bind — gets a no-op, and then the only thing
# between a stale read and a lost edge is the write refusing to land over a file
# that moved. Driven directly, because a race cannot prove which of the two
# stopped it.
import importlib.util
spec = importlib.util.spec_from_file_location("ddw_transition_probe", helper)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
probe = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), ".ddw-state.json")
open(probe, "w", encoding="utf-8").write('{"phase": "CLASSIFY"}\n')


class _Args(object):
    write = True
    state = probe


try:
    mod._emit(_Args(), {"phase": "DEFINE"}, seen='{"phase": "WHAT THIS RUN READ"}')
    raise AssertionError("a state that changed since it was read was overwritten anyway")
except SystemExit as exc:
    assert exc.code == 2, "refusing to overwrite a moved state exited %r, not 2" % (exc.code,)
assert json.load(open(probe, encoding="utf-8"))["phase"] == "CLASSIFY", \
    "the refusal printed and the write landed regardless"
PYRACEWRITE

# The closing write is the one write that erases the gates, and post mode was
# reading that erasure as nothing left to ask about: a forged run refused at
# CLOSEOUT was blessed in full by ONE more shell write to IDLE, and every finding
# outstanding against it went with it. Closing a ticket is not a way of answering
# the question — the edges the journal has not blessed still owe their evidence,
# and the entries still carry the ticket the header just dropped.
python3 - "$SELF" <<'PYCLOSEWIPE' && ok "a run refused by post mode is not blessed by closing it: the closing write owes what the run never paid" || bad "one more write to IDLE erases every post-mode finding — a forged ticket closes itself clean"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
state = os.path.join(repo, ".ddw-state.json")
graph = os.path.join(repo, ".ddw/rules/transition-graph.json")
E = [("IDLE", "CLASSIFY"), ("CLASSIFY", "DEFINE"), ("DEFINE", "CODE"), ("CODE", "CLOSEOUT")]
H = [{"timestamp": "2026-01-01T00:0%d:00Z" % i, "from": f, "to": t, "action": "forged",
      "tier": "QUICK-FIX", "ticket": "QF-9"} for i, (f, t) in enumerate(E)]
# A whole ticket written by a shell: no PRD, no test report, no SAST report, and
# no receipt for any of the three gates it claims.
forged = {"tier": "QUICK-FIX", "phase": "CLOSEOUT", "ticket": "QF-9", "title": None,
          "tracker": None, "autonomy": None,
          "gates": {"define": True, "tests": True, "sast": True},
          "block": None, "discovery": None, "history": H}


def post():
    return subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/validate-transition.py"),
                           "--mode", "post", "--state", state, "--graph", graph, "--repo", repo],
                          capture_output=True, text=True)


json.dump(forged, open(state, "w", encoding="utf-8"))
first = post()
assert first.returncode == 2, \
    "the forged run was not refused in the first place, so this check proves nothing"
closed = dict(forged)
closed.update({"tier": None, "phase": "IDLE", "ticket": None, "gates": {},
               "history": H + [{"timestamp": "2026-01-01T01:00:00Z", "from": "CLOSEOUT",
                                "to": "IDLE", "action": "done", "tier": "QUICK-FIX",
                                "ticket": "QF-9"}]})
json.dump(closed, open(state, "w", encoding="utf-8"))
second = post()
said = second.stdout + second.stderr
assert second.returncode == 2, "closing the ticket erased the refusal: " + (said[:200] or "(allowed)")
assert not os.path.exists(os.path.join(repo, ".ddw-journal.jsonl")), \
    "the run that was refused was recorded in the journal as blessed"

# …and the legitimate closeout of a run the journal DID bless still closes.
ok_state = dict(forged)
with open(os.path.join(repo, ".ddw-journal.jsonl"), "w", encoding="utf-8") as fh:
    for entry in H:
        fh.write(json.dumps(entry) + "\n")
json.dump(closed, open(state, "w", encoding="utf-8"))
third = post()
assert third.returncode == 0, \
    "a closeout whose whole run the journal already blessed was refused: " + (third.stdout + third.stderr)[:200]
PYCLOSEWIPE

# ── Nothing DDW runs may answer with a stack ─────────────────────────────────
#
# Every entry point is on a path where a traceback is worse than a refusal: the
# hooks decide whether a write happens, the boot is the session's first line, and
# the installer runs half-way. Each of these crashed on input a real repo can
# hold.
python3 - "$SELF" <<'PYCRASH' && ok "the boot, the installer, the uninstaller and the seven validators refuse odd input instead of crashing on it" || bad "an entry point answers with a traceback: a half-install, a session that starts blind, or a validator that exits 1 where its contract says 3"
import glob, json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]


def repo_with_ddw(context=None, install=True):
    repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
    os.makedirs(repo)
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    if context is not None:
        open(os.path.join(repo, "AGENTS.md"), "w", encoding="utf-8").write(context)
    if not install:
        return repo, None      # the caller is about to make the install itself the subject
    r = subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                       capture_output=True, text=True)
    return repo, r


# 1. A context file that merely MENTIONS the marker in prose. A project
#    documenting its own setup writes exactly this, and it used to raise
#    ValueError mid-install, leaving the repo half-wired.
repo, r = repo_with_ddw("# Notes\n\nWe use a BEGIN DDW block; see the docs.\n")
assert r.returncode == 0 and "Traceback" not in r.stderr, \
    "the installer crashed on a context file that mentions the marker in prose:\n" + r.stderr[-300:]
assert os.path.isdir(os.path.join(repo, ".ddw")), "the install did not finish"

# 1b. The settings file DDW merges into is the user's, and it arrives in shapes
#     the merge was not written for: a mapping where the tool's own schema says
#     list, a null, a string, a top-level array. Every one of them reached
#     `cur.append(blk)` and came back an AttributeError mid-install — `.claude/`
#     and `.ddw/` on disk, no manifest, no hooks wired, and a traceback as the
#     entire user-facing report. And the same for a context file that is not
#     UTF-8, which is what a Spanish AGENTS.md saved as cp1252 is.
for shape in ('{"hooks":{"PreToolUse":{"matcher":"Edit","hooks":[]}}}', '{"hooks":null}',
              '{"hooks":"x"}', '{"hooks":{"PreToolUse":null}}', '[]', '"x"', '5', 'null'):
    repo, _ = repo_with_ddw(install=False)
    os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
    open(os.path.join(repo, ".claude", "settings.json"), "w", encoding="utf-8").write(shape)
    r = subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                       capture_output=True, text=True)
    said = r.stdout + r.stderr
    assert "Traceback" not in said, \
        "a settings.json shaped %s crashed the installer:\n%s" % (shape[:28], said[-300:])
    assert os.path.exists(os.path.join(repo, ".ddw-installed.json")), \
        "the install stopped before the manifest on a settings.json shaped %s — the drift " \
        "detector is off in a repo that looks installed" % shape[:28]
    assert "ddw-settings.json" in said, \
        "a settings.json DDW could not merge into was passed over in silence: %s" % said[-200:]

repo, _ = repo_with_ddw(install=False)
open(os.path.join(repo, "AGENTS.md"), "wb").write("# Reglas\n\nfunci\xf3n\n".encode("cp1252"))
r = subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
                   capture_output=True, text=True)
said = r.stdout + r.stderr
assert "Traceback" not in said, "a context file that is not UTF-8 crashed the installer:\n" + said[-300:]
assert os.path.exists(os.path.join(repo, ".ddw-installed.json")), \
    "the install stopped before the manifest on a context file it could not read"
assert open(os.path.join(repo, "AGENTS.md"), "rb").read() == "# Reglas\n\nfunci\xf3n\n".encode("cp1252"), \
    "the installer rewrote a file it could not decode, so the user's bytes are gone"

# 2. A state so deeply nested that the parser gives up. The boot has a designed
#    answer for a state it cannot read, and it was reaching the user as exit 1
#    with a stack.
#    Deep enough that the PARSER gives up, which is the whole point: 300 levels
#    parses fine and comes back a list, so the check was measuring the
#    "not an object" branch and never the RecursionError it was written for —
#    and the fault it was guarding stayed invisible with the check green.
repo, _ = repo_with_ddw()
open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8").write(
    "[" * 100000 + "]" * 100000)
r = subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/session-boot.py"),
                    "--repo", repo, "--session-id", "s"], capture_output=True, text=True)
assert r.returncode == 0 and "Traceback" not in r.stderr, \
    "the session boot answered with a stack: " + (r.stderr[-300:] or "exit %d" % r.returncode)
assert "cannot be read" in r.stdout or "could not run" in r.stdout, \
    "the boot said nothing about a state it could not read: " + r.stdout[-200:]
#    And the same fault reached through a file the state is not: the manifest is
#    read by the drift detector, whose own catch is narrower than the fault.
repo, _ = repo_with_ddw()
open(os.path.join(repo, ".ddw-installed.json"), "w", encoding="utf-8").write(
    "[" * 100000 + "]" * 100000)
r = subprocess.run([sys.executable, os.path.join(repo, ".ddw/scripts/session-boot.py"),
                    "--repo", repo, "--session-id", "s"], capture_output=True, text=True)
assert r.returncode == 0 and "Traceback" not in r.stderr, \
    "a manifest the parser gives up on takes the whole boot down: " + \
    (r.stderr[-300:] or "exit %d" % r.returncode)

# 3. A manifest whose shape nobody expected. The uninstaller is what you reach
#    for when DDW is in a state you do not want; it has to run.
repo, _ = repo_with_ddw()
open(os.path.join(repo, ".ddw-installed.json"), "w", encoding="utf-8").write('["not","a","mapping"]')
r = subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes"],
                   capture_output=True, text=True)
assert r.returncode == 0 and "Traceback" not in r.stderr, \
    "the uninstaller could not run against a manifest it did not expect:\n" + r.stderr[-300:]

# 3b. …and every other shape the same file can arrive in, plus the settings file
#     it un-merges from. One of these did not crash — it exited 0, printed
#     "Done." and rewrote `"PreToolUse": "oops"` as one list element per
#     CHARACTER. A tool that corrupts what it was asked to clean and reports
#     success is worse than one that refuses.
POISON = [
    (".claude/settings.json", "[1,2]"),
    (".claude/settings.json", '"x"'),
    (".claude/settings.json", '{"hooks":"x"}'),
    (".claude/settings.json", '{"hooks":{"PreToolUse":"oops"}}'),
    (".ddw-installed.json", "[" * 100000 + "]" * 100000),
]
for rel, payload in POISON:
    repo, _ = repo_with_ddw()
    target = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    open(target, "w", encoding="utf-8").write(payload)
    r = subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes"],
                       capture_output=True, text=True)
    said = r.stdout + r.stderr
    assert r.returncode == 0 and "Traceback" not in said, \
        "the uninstaller crashed on %s = %s:\n%s" % (rel, payload[:24], said[-300:])
    assert not os.path.isdir(os.path.join(repo, ".ddw")), \
        "the uninstall stopped at %s = %s and left the method behind" % (rel, payload[:24])
    if rel.endswith("settings.json") and os.path.exists(target):
        after = open(target, encoding="utf-8").read()
        assert after.strip() == payload.strip(), \
            "the uninstaller rewrote a settings file it could not read as hooks:\n" + after[:200]

# The corruption needs DDW's own blocks to still be there: the un-merge only
# writes the file back when it removed something, so a settings.json whose every
# event is odd is left alone and proves nothing. One event of the user's shaped
# differently, next to the event DDW installed into, is the real shape.
repo, _ = repo_with_ddw()
spath = os.path.join(repo, ".claude", "settings.json")
settings = json.load(open(spath, encoding="utf-8"))
assert settings.get("hooks", {}).get("PreToolUse"), "the install wired no PreToolUse to remove"
settings["hooks"]["SessionEnd"] = "mine, and not a list"
json.dump(settings, open(spath, "w", encoding="utf-8"), indent=2)
r = subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes"],
                   capture_output=True, text=True)
assert "Traceback" not in (r.stdout + r.stderr), \
    "an event of the user's that is not a list crashed the uninstall:\n" + (r.stdout + r.stderr)[-300:]
if os.path.exists(spath):
    after = json.load(open(spath, encoding="utf-8"))
    assert after.get("hooks", {}).get("SessionEnd") == "mine, and not a list", \
        ("the uninstaller rewrote an event it could not read as hooks, one list element per "
         "character: %r" % (after.get("hooks", {}).get("SessionEnd"),))

repo, _ = repo_with_ddw()
odd = "# Notas\n\nfunci\xf3n\n".encode("cp1252")
open(os.path.join(repo, "CLAUDE.md"), "wb").write(odd)
r = subprocess.run(["bash", os.path.join(src, "uninstall.sh"), repo, "--yes"],
                   capture_output=True, text=True)
assert r.returncode == 0 and "Traceback" not in (r.stdout + r.stderr), \
    "a context file that is not UTF-8 stopped the uninstall:\n" + (r.stdout + r.stderr)[-300:]
assert open(os.path.join(repo, "CLAUDE.md"), "rb").read() == odd, \
    "the uninstaller rewrote a context file it could not decode"

# 4. A document that is not UTF-8. The validators' own contract says exit 3 for
#    "cannot read"; all six exited 1 with a stack.
d = tempfile.mkdtemp(dir=os.environ["WORK"])
bad = os.path.join(d, "not-utf8.md")
open(bad, "wb").write(b"# report\n\xff\xfe\n")
for v in sorted(glob.glob(os.path.join(src, "ddw/scripts/validate_*.py"))):
    r = subprocess.run([sys.executable, v, bad, "--tier", "FEATURE"],
                       capture_output=True, text=True)
    assert r.returncode == 3 and "Traceback" not in r.stderr, \
        "%s exited %d on a non-UTF-8 document; its own contract says 3" % (
            os.path.basename(v), r.returncode)

# 4b. …and the COMPANION artifact, which is the one a Spanish PRD saved as
#     cp1252 actually is. The primary document is the one a user passes; the
#     counterpart is the one the validator finds by itself, with no flag
#     involved — and those four reads kept a bare `except OSError`, so the
#     everyday case exited 1 with a stack from a validator whose contract has an
#     exit code for exactly this.
repo, _ = repo_with_ddw()
for sub, stem in (("prd", "prd"), ("specs", "spec")):
    os.makedirs(os.path.join(repo, "docs", "ddw", sub), exist_ok=True)
open(os.path.join(repo, "docs/ddw/prd/prd-T-1.md"), "wb").write(
    "# PRD T-1\n\n- FR-01: la funci\xf3n\n".encode("cp1252"))
open(os.path.join(repo, "docs/ddw/specs/spec-T-1.md"), "w", encoding="utf-8").write(
    "# Spec T-1\n\n| Field | Value |\n|---|---|\n| Ticket | T-1 |\n\n## Block 1 — algo\n")
for v, doc in (("validate_spec.py", "docs/ddw/specs/spec-T-1.md"),
               ("validate_verify.py", "docs/ddw/reports/verify-T-1.md"),
               ("validate_threat.py", "docs/ddw/security/threat-T-1.md")):
    target = os.path.join(repo, doc)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not os.path.exists(target):
        open(target, "w", encoding="utf-8").write(
            "# %s\n\n| Field | Value |\n|---|---|\n| Ticket | T-1 |\n" % os.path.basename(doc))
    r = subprocess.run([sys.executable, os.path.join(src, "ddw/scripts", v), target,
                        "--tier", "FEATURE"], capture_output=True, text=True, cwd=repo)
    assert "Traceback" not in r.stderr, \
        "%s crashed on a counterpart document that is not UTF-8:\n%s" % (v, r.stderr[-300:])
    assert r.returncode in (0, 2, 3), \
        "%s exited %d on a counterpart it could not read — 0 passes, 2 fails, 3 cannot read, and " \
        "1 is the code nothing here is allowed to answer with" % (v, r.returncode)

# 4c. The method linter is on the same list. One rule file in the wrong encoding
#     took it down with a stack and exit 1 — the exit code that means "a claim
#     did not check out", from a run where no claim was ever read.
probe = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "method")
shutil.copytree(src, probe, symlinks=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__"))
open(os.path.join(probe, "ddw/rules/odd-encoding.instructions.md"), "wb").write(b"texto\xf3\n")
r = subprocess.run([sys.executable, os.path.join(probe, "scripts/lint_method.py")],
                   capture_output=True, text=True, cwd=probe)
assert "Traceback" not in r.stderr, \
    "lint_method.py answered a file it could not decode with a stack:\n" + r.stderr[-300:]
assert "could not be read as UTF-8" in (r.stdout + r.stderr), \
    "lint_method.py passed over a file it could not read in silence"
PYCRASH

# ── One write cannot skip the phase that classifies the work ────────────────
#
# A leniency about where an appended run STARTS was also a leniency about what it
# skipped: a state at IDLE plus a history beginning at CLASSIFY landed in DEFINE
# having never been classified — and carrying whatever `autonomy` it liked, since
# any edge touching CLASSIFY may set that field.
python3 - "$SELF" <<'PYSKIP2' && ok "a run cannot begin somewhere the state is not, so nothing skips CLASSIFY or the mode chosen there" || bad "one Write skips the phase that classifies the work and grants itself a mode nobody chose"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
g = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))
idle = {"tier": None, "phase": "IDLE", "ticket": None, "title": None, "tracker": None,
        "autonomy": None, "gates": {}, "block": None, "discovery": None, "history": []}
# `title` filled, and the refusal read rather than merely counted. The fixture
# left it null, and the edge it builds leaves CLASSIFY carrying a ticket — so
# the Block that came back was the one about the ticket's NAME, and this block
# went on passing with the leniency it exists to catch restored. Two defences
# over one hole hide each other unless the check says which one answered.
jump = dict(idle, tier="FEATURE", phase="DEFINE", ticket="T-1", title="the fixture ticket",
            autonomy="minimal",
            history=[{"timestamp": "2026-01-01T00:00:00Z", "from": "CLASSIFY", "to": "DEFINE",
                      "action": "skipped the classification", "tier": "FEATURE",
                      "ticket": "T-1"}])
try:
    m.validate(idle, jump, g, max_appended=1)
    raise AssertionError("a run beginning at CLASSIFY landed in DEFINE from IDLE, unclassified")
except m.Block as exc:
    assert "starts at CLASSIFY" in str(exc), \
        "the write was refused, but for something other than where the run begins: %s" % exc
# …and the ordinary first step is untouched.
first = dict(idle, tier="FEATURE", phase="CLASSIFY", ticket="T-1", autonomy="minimal",
             history=[{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY",
                       "action": "classify", "tier": "FEATURE", "ticket": "T-1"}])
m.validate(idle, first, g, max_appended=1)
PYSKIP2

# An edge the journal already blessed was legal when it landed. Upgrading DDW
# mid-ticket changed the graph under an open run, the new graph was applied to
# the whole history, and post mode then refused every tool call over a step taken
# days earlier — with no message naming a way out.
python3 - "$SELF" <<'PYUPGRADE' && ok "a graph change under an open ticket does not condemn the steps already taken, and a new illegal step is still refused" || bad "upgrading DDW mid-ticket strands the ticket permanently, or the window that allows it lets anything through"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
tr = os.path.join(repo, ".ddw/scripts/transition.py")
vt = os.path.join(repo, ".ddw/scripts/validate-transition.py")
graph = os.path.join(repo, ".ddw/rules/transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")


def post():
    return subprocess.run([sys.executable, vt, "--mode", "post", "--state", state,
                           "--graph", graph], capture_output=True, text=True)


def step(*args):
    subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write", *args],
                   capture_output=True, text=True)
    return post()


assert step("--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE",
            "--ticket", "T-1").returncode == 0
# The classify edge's context check — a different gate than the replay window
# under test. Without it the DEFINE step below fails SILENTLY (step() reads
# post's exit, not the helper's), the graph-change scenario never gets built,
# and the fault this check exists to catch survives on a fixture that broke.
# Measured: exactly that, on the first CI run after the gate shipped.
os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
open(os.path.join(repo, ".ddw-work", "context-check-T-1.md"), "w", encoding="utf-8").write(
    "Nothing to report.\n")
assert step("--to", "DEFINE", "--action", "d", "--title", "the fixture ticket").returncode == 0
# …and the edge has to have LANDED, or everything after this line measures a
# repo standing somewhere else than the scenario says.
assert json.load(open(state, encoding="utf-8"))["phase"] == "DEFINE", \
    "the fixture's DEFINE step did not land, so the graph change would move under nothing"
# The graph moves under the open ticket, exactly as an upgrade does.
g = json.load(open(graph, encoding="utf-8"))
g["tiers"]["FEATURE"].pop("CLASSIFY->DEFINE", None)
json.dump(g, open(graph, "w", encoding="utf-8"), indent=2)
r = post()
assert r.returncode == 0, \
    "an open ticket was stranded by a graph change under it: " + (r.stdout + r.stderr)[:220]
# …and the window is exactly the blessed edges: a NEW step that the graph does
# not have is still refused.
d = json.load(open(state, encoding="utf-8"))
d["history"].append({"timestamp": "2026-01-01T09:00:00Z", "from": "DEFINE", "to": "CLOSEOUT",
                     "action": "jump", "tier": "FEATURE", "ticket": "T-1"})
d["phase"] = "CLOSEOUT"
json.dump(d, open(state, "w", encoding="utf-8"))
assert post().returncode == 2, "the compatibility window accepted a brand-new illegal edge"
PYUPGRADE

# The instrument, checked by the instrument. Three rules of this file's own —
# the trust_note loop's non-empty guard, the derived list of validation skills,
# and mutate.py's coverage arithmetic — can each be weakened without any check
# going red, because weakening a CHECK does not make the suite fail. Read as
# source, which is the only place the question can be asked.
python3 - "$SELF" <<'PYMETA' && ok "the suite's own guards against measuring nothing are still in place, and --cover still refuses a job that cannot fail" || bad "a check that measures nothing, or a coverage number that counts a job which never runs"
import importlib.util, os, re, shutil, signal, subprocess, sys, tempfile
src = sys.argv[1]
suite = open(os.path.join(src, "scripts/verify_install.sh"), encoding="utf-8").read()

# A loop over recipes with no non-empty guard reports success when the field it
# reads has been deleted from every recipe.
assert re.search(r"^assert checked >= 2,", suite, re.M), \
    "the trust_note check lost the guard that stops it iterating zero times"
# The same shape one section down, and it was live: the check that every
# validator prints the demand skipped any fixture not on disk and then guarded
# itself with `assert cases` — a list literal three lines above it, true by
# construction. Every fixture could be missing, every validator unasked, and the
# check went green having run none of them.
assert re.search(r"^assert not skipped, \(", suite, re.M), \
    "the demand check lost the guard that stops it passing without asking a single validator"
# The probe that drives an empty selection has to kill a process GROUP. Killing
# the process is what `subprocess.run(timeout=)` does, and it leaves everything
# that process started running — which for this probe means the run it launched,
# the suite that run launched, and the probe that suite reached: a recursion
# outliving every one of its ancestors. Found still spawning hours later, inside
# temporary trees from a version of the list that no longer existed.
# Built in pieces, like the other one: written whole, this assert finds itself
# and the verification passes even when the code has lost it. It already
# happened to me with `EXPECT_CHECKS` forty lines further up, in this same block.
_group_kill = "start_new_" + "session=True"
assert suite.count(_group_kill) >= 1 and "killpg" in suite, \
    ("the empty-selection probe no longer kills the process group; a timeout that kills one "
     "process leaves the tree it started alive, and this is the one probe whose child starts "
     "another")
# The pinned totals are constants of this file, not knobs. Read as source
# because the run cannot see the difference: `EXPECT_CHECKS=${EXPECT_CHECKS:-N}`
# behaves identically until someone sets it, and then a run of 43 of 523 checks
# exits 0 while printing a green total. Both documents that tell contributors
# never to soften this variable were describing a variable anyone could soften
# from outside the file.
# Every temporary directory this file makes has to be anchored to `$WORK`, the
# one the trap deletes. `tempfile.mkdtemp()` registers no finaliser and removes
# nothing — fifty-five of them ran per pass and every one was left behind. Alone
# that is fifty stale directories nobody notices; under `mutate.py` it is this
# file once per fault across ten shards, which put 38 GB and 36,000 entries into
# /tmp in two hours and took the disk with it. The leak was never in the runner.
#
# Read as source, because a run cannot see its own litter: the directories
# outlive the process that made them, which is the whole defect.
assert re.search(r"^export WORK=", suite, re.M), \
    "WORK is not exported, so the Python blocks cannot anchor to it and `os.environ[\"WORK\"]` " \
    "raises KeyError in every one of them"
# Comment lines are skipped: this rule is about calls, and the paragraph above
# names the broken form in prose. A checker that reads its own explanation as a
# violation is one somebody deletes.
loose = [i + 1 for i, ln in enumerate(suite.splitlines())
         if re.search(r"tempfile\.mkdtemp\((?!dir=)", ln) and not ln.lstrip().startswith("#")]
assert not loose, (
    "%d temporary-directory call(s) do not pass `dir=` (line %s), so they land in /tmp and "
    "nothing ever removes them: the trap on WORK is the only cleanup this file has, and a "
    "directory outside it is outside that" % (len(loose), ", ".join(map(str, loose[:6]))))
# …and TemporaryDirectory is fine as it is: it cleans up on its own. Named here
# so the next reader does not "fix" the seven that are already correct.
assert "TemporaryDirectory" in suite, \
    "the self-cleaning form is gone from the file, which makes the rule above the only one left"

for pin in ("EXPECT_CHECKS", "EXPECT_MUTATIONS"):
    m = re.search(r"^%s=(.+)$" % pin, suite, re.M)
    assert m, "%s is no longer pinned at the top of the suite" % pin
    assert re.fullmatch(r"[1-9][0-9]*", m.group(1).strip()), \
        "%s is not a plain number (%s): a total the environment can set is not a pinned total" % (
            pin, m.group(1).strip())
# The six validation skills are DERIVED from the gate table; a hand-typed list
# named four of them for months. Asked by RUNNING the derivation, not by looking
# for its shape: a check that greps for its own assertion text is satisfied by
# itself, which is how this very line first passed under the mutation it exists
# to catch.
block = re.search(r"<<'PYVRLIST'\n(.*?)\nPYVRLIST", suite, re.S)
assert block, "the derivation of the validation skills is gone"
derived = subprocess.run([sys.executable, "-c", block.group(1), src],
                         capture_output=True, text=True).stdout.split()
assert len(derived) == 6 and len(set(derived)) == 6, \
    "the re-validation rule is checked for %d skills, and six gates rest on a receipt: %s" % (
        len(set(derived)), derived)
for name in derived:
    assert os.path.isdir(os.path.join(src, "skills", name)), \
        "the derivation named %r, which is not a skill" % name

# A mutation that leaves the file unparseable measures the file not compiling.
# Every check dies on the import, the run records a kill, and the defect the
# entry names was never in the tree — so it reads as covered for as long as it
# exists. One shipped, and lived through two audits. Driven by handing
# --check-anchors a copy carrying exactly that shape.
probe = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "method")
shutil.copytree(src, probe, symlinks=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__"))
mut = os.path.join(probe, "scripts/mutate.py")
text = open(mut, encoding="utf-8").read()
anchor = "MUTATIONS = [\n"
assert anchor in text, "the mutation list no longer starts where this check looks"
text = text.replace(anchor, anchor + '    ("a mutation that only stops the file parsing",\n'
                                     '     edit("ddw/scripts/session-boot.py", "def safe_id(",\n'
                                     '          "def safe_id_UNUSED(\\n    pass\\n\\n\\ndef safe_id(")),\n', 1)
open(mut, "w", encoding="utf-8").write(text)
r = subprocess.run([sys.executable, mut, "--check-anchors"], capture_output=True, text=True)
assert r.returncode != 0 and "unparseable" in r.stdout, \
    "--check-anchors accepted a mutation that leaves the file it edits unable to parse: " + \
    (r.stdout + r.stderr)[-200:]

# And a mutation duplicated in the list is one fault counted twice: two entries
# injecting the same edit move the denominator and try nothing new. A pair
# shipped that way, and neither run could see it — both were killed by the same
# check, which is how a duplicate hides.
dup = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "method")
shutil.copytree(src, dup, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
mut = os.path.join(dup, "scripts/mutate.py")
text = open(mut, encoding="utf-8").read()
anchor = "MUTATIONS = [\n"
assert anchor in text, "the mutation list no longer starts where this check looks"
twin = ('    ("one fault, written down twice",\n'
        '     edit("ddw/scripts/session-boot.py", "def safe_id(", "def safe_id_RENAMED(")),\n')
open(mut, "w", encoding="utf-8").write(text.replace(anchor, anchor + twin + twin, 1))
r = subprocess.run([sys.executable, mut, "--check-anchors"], capture_output=True, text=True)
assert r.returncode != 0 and "twice" in r.stdout, \
    "--check-anchors accepted the same edit listed as two mutations: " + (r.stdout + r.stderr)[-200:]
# …and the `exists` constructors that legitimately share a file are not reported
# as duplicates: six groups in the shipped list name one file and change
# different things inside it.
#
# Asked of the LIST, in memory, and never by running `--check-anchors` here.
# That was the first version of this line and it fabricated the measurement it
# was meant to protect: inside a mutation run, `src` is the MUTATED copy, where
# the fault under test has just replaced its own anchor — so `--check-anchors`
# failed, the suite went red, and the mutation was recorded as caught without a
# single check having noticed the defect. 372 of 437 faults destroy their own
# anchor by construction, so 372 of them were scoring the instrument's own
# footprint. `mutate.py` carries this exact warning about the same check having
# lived in this file for one afternoon and fabricated 180 kills; it is the same
# mistake, made again, four hundred lines away from the comment describing it.
_dupe_spec = importlib.util.spec_from_file_location("ddw_mut_dupes",
                                                    os.path.join(src, "scripts/mutate.py"))
_dupe_mut = importlib.util.module_from_spec(_dupe_spec)
_dupe_spec.loader.exec_module(_dupe_mut)
_probes = [getattr(fn, "probe", None) for _, fn in _dupe_mut.MUTATIONS]
_text_probes = [p for p in _probes if p and p[0] == "text"]
assert len(_text_probes) == len(set(_text_probes)), \
    "two text mutations inject the same edit — one fault counted twice in the list this file pins"

# The same fabricated measurement one layer down: `run_one` reads a non-zero
# exit as "the suite caught the fault", and a suite that was ALREADY red — a
# tool the preflight refuses over, a signing config this machine cannot satisfy,
# a half-applied edit — makes every fault report as caught without one check
# having examined it. The run then prints 100%. Driven by handing the runner a
# copy whose suite cannot pass: it has to refuse before injecting anything, and
# say which of the two it was.
# The suite is made to FAIL without being made to disappear, and the copy is
# given a mutation list of ONE entry whose anchor is certainly present.
#
# Both halves are load-bearing, and the second one was missing. `src` here is
# whatever tree this suite is running in — and inside a mutation run that is the
# MUTATED copy, where the fault under test has already replaced its own anchor.
# So `--check-anchors`, which `mutate.py` asks before anything else, failed for
# a reason that has nothing to do with the guard being driven: the assertion
# below went red, the suite went red, and the fault was recorded as caught
# without a single check having noticed the defect. 372 of the 437 faults
# destroy their own anchor by construction, so that is how many were scoring the
# instrument's own footprint rather than the product's behaviour.
#
# `mutate.py` carries a comment about this exact check having lived in that file
# for one afternoon and fabricated 180 kills. This is the same mistake in the
# other direction: not the anchors check inside the copy, but a probe that
# depends on it passing there.
red = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "method")
shutil.copytree(src, red, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
_redmut = os.path.join(red, "scripts/mutate.py")
_mtext = open(_redmut, encoding="utf-8").read()
_start = _mtext.index("MUTATIONS = [")
_end = _mtext.index("\n]\n", _start)
open(_redmut, "w", encoding="utf-8").write(
    _mtext[:_start]
    + 'MUTATIONS = [\n    ("a fault whose anchor this copy is certain to have",\n'
    + '     edit("scripts/mutate.py", "def baseline():", "def baseline_():")),'
    + _mtext[_end:])
redsuite = os.path.join(red, "scripts/verify_install.sh")
redtext = open(redsuite, encoding="utf-8").read()
open(redsuite, "w", encoding="utf-8").write(
    "echo 'a check that has nothing to do with any mutation'\nexit 1\n" + redtext)
r = subprocess.run([sys.executable, os.path.join(red, "scripts/mutate.py"), "--only", "1"],
                   capture_output=True, text=True)
assert r.returncode != 0 and "UNMUTATED" in r.stdout, \
    "a run over an already-red suite reported its faults as caught: " + (r.stdout + r.stderr)[-200:]
assert "Injecting" not in r.stdout, \
    "the runner injected a fault into a tree whose suite was already failing: " + r.stdout[-200:]

# --cover has to refuse a workflow whose mutation job cannot fail, and one that
# injects the same mutation twice. Driven against doctored copies of the real
# workflow, because that is what the number is about.
work = tempfile.mkdtemp(dir=os.environ["WORK"])
real = open(os.path.join(src, ".github/workflows/mutations.yml"), encoding="utf-8").read()


def cover(text, name):
    path = os.path.join(work, name)
    open(path, "w", encoding="utf-8").write(text)
    return subprocess.run([sys.executable, os.path.join(src, "scripts/mutate.py"),
                           "--cover", path], capture_output=True, text=True)


assert cover(real, "ok.yml").returncode == 0, "the real workflow no longer covers its own list"
skipped = real.replace("    strategy:", "    if: false\n    strategy:", 1)
r = cover(skipped, "skipped.yml")
assert r.returncode != 0 and "conditional" in r.stdout, \
    "a mutation job that never runs was counted as full coverage: " + r.stdout[-200:]
# The shard step's own shape, whatever it is: the anchor used to be the single
# `- run:` line that carried the command, and when the step grew a body the
# replacement quietly matched nothing — the probe built an identical file, the
# cover check passed it, and this assertion was asking about a workflow that was
# never modified. Anchored on the job instead, which is what the question is
# about.
_at = real.index("  mutations:")
_run = real.index("      - run:", _at)
swallowed = real[:_run] + "      - continue-on-error: true\n" + real[_run:]
assert "continue-on-error" in swallowed, "the shard step no longer has a run step to swallow"
r = cover(swallowed, "swallowed.yml")
assert r.returncode != 0 and "continue-on-error" in r.stdout, \
    "a shard whose failure is swallowed was counted as coverage: " + r.stdout[-200:]

# Two mutations injected twice is not "each exactly once", and the phrase was
# printed without ever being measured. Two jobs sharding the same list is the
# everyday way to get there.
doubled = real.replace("jobs:\n", "jobs:\n  second:\n    runs-on: ubuntu-latest\n    strategy:\n"
                       "      matrix:\n        shard: [1]\n    steps:\n"
                       "      - run: python3 scripts/mutate.py --shard ${{ matrix.shard }}/1\n", 1)
r = cover(doubled, "doubled.yml")
assert r.returncode != 0 and "more than once" in r.stdout, \
    "the same mutations injected by two jobs still read as each exactly once: " + r.stdout[-200:]

# And a selection that names nothing has to be an error, not "0/0 (0%)". Three
# ways to name nothing, and they are caught by three different guards — the one
# that matters most is the LAST, where the arguments are individually valid and
# the intersection is still empty.
#
# The empty shard is DERIVED, and that is not neatness. It was written as
# `400/400` when the list held 393, and the day the list passed four hundred
# that shard stopped naming nothing: this check ran a real mutation, the
# mutation ran the suite, the suite reached this line again — a recursion that
# forks until the machine gives up, from a check whose whole subject is a
# selection that matches no mutation. Past the end of the list is a fact about
# the list.
_mspec = importlib.util.spec_from_file_location("ddw_mut", os.path.join(src, "scripts/mutate.py"))
_mut = importlib.util.module_from_spec(_mspec); _mspec.loader.exec_module(_mut)
_past_end = "%d/%d" % (len(_mut.MUTATIONS) + 1, len(_mut.MUTATIONS) + 1)

# A shard has to FIT in its timeout, and that is arithmetic nobody was doing.
# One fault is one full run of the suite, so the slice count is what keeps a
# shard under the ceiling — and both sides of it grew. Three consecutive runs
# of the mutation job died at exactly 45:00 and reported "cancelled", which is
# the shape this repository already named as not an answer: the coverage number
# CI publishes was unobtainable, on the pull request that carried the growth,
# and every check on the branch was green. The budget below is measured, not
# guessed: a suite run costs about ninety seconds on a GitHub runner, and two
# minutes is that with room. A shard also pays for one unmutated baseline.
import math
import yaml
_wf = yaml.safe_load(open(os.path.join(src, ".github/workflows/mutations.yml"), encoding="utf-8"))
# Of EVERY job that shards the list, not of one named by hand. The arithmetic
# was asked of `mutations` and of nothing else, so `kill-map` — which pays the
# whole suite per fault instead of asking tests/ first — sat at twenty-eight
# runs against a ceiling of forty-five for as long as it existed, and the check
# written to catch exactly that was looking one job over. Measured before the
# ceiling moved: the slowest shard took thirty-eight of its forty-five minutes.
_sharded = {name: job for name, job in _wf["jobs"].items()
            if "shard" in job.get("strategy", {}).get("matrix", {})}
assert len(_sharded) > 1, (
    "only %d job shards the list; this check was written because asking it of one job by name "
    "is how the other one went unmeasured" % len(_sharded))
for _name, _job in sorted(_sharded.items()):
    _shards = len(_job["strategy"]["matrix"]["shard"])
    _ceiling = int(_job["timeout-minutes"])
    _per_shard = math.ceil(len(_mut.MUTATIONS) / _shards) + 1
    assert _per_shard * 2 < _ceiling, (
        "in `%s`, a shard runs %d suite runs (%d faults over %d shards, plus the baseline), "
        "which is about %d minutes against a timeout of %d. It will be killed and reported as "
        "cancelled. Add shards — never fewer faults." % (_name, _per_shard, len(_mut.MUTATIONS),
                                                         _shards, _per_shard * 2, _ceiling))

# And no job that measures the list may be conditional. `--cover` already refuses
# a conditional `mutations` job — a job that does not run is not coverage — and
# the two jobs that produce and compare `docs/CHECKS-THAT-CANNOT-FAIL.md` carried
# `if: github.event_name == 'workflow_dispatch'` for seventeen pull requests
# under the argument that the suite does not change on every push. It changes on
# almost every push here: a new `bad` and a new fault are half of what lands. The
# book went untouched from PR #7 to PR #25, and the only job that could have said
# so was the one switched off.
for _name in ("kill-map", "kill-map-ledger"):
    _cond = _wf["jobs"][_name].get("if")
    assert _cond is None, (
        "`%s` runs only when `%s`. The book it produces is an expectation the CI compares, and a "
        "comparison that happens on request is one nobody makes: it is how the file aged eighteen "
        "pull requests without a single red." % (_name, _cond))
for argv in (["--only", "999999"], ["--only"], ["--shard", _past_end]):
    # With a timeout, and it is load-bearing. Each of these is supposed to be
    # refused in milliseconds, from the arguments alone. Take the guard away and
    # the run reaches its baseline, the baseline runs the whole suite, the suite
    # reaches this line and starts the same run again: a recursion with no
    # bottom. The check that was meant to catch the missing guard never got to
    # assert anything, the job sat until the runner killed it at its ceiling,
    # and a killed job reports as cancelled — the shape this repository already
    # named as not an answer, arriving this time through its own instrument.
    # Measured: shard 17 of 24, 1h15m, on the commit that reshaped the shards.
    # In its own process group, and killed as a group. `subprocess.run(timeout=)`
    # kills the process it started and nothing that process started — so when
    # this probe timed out, the run it had launched went on, reached the suite,
    # reached THIS line again and launched another. A recursion that outlives
    # every one of its ancestors: found hours later, still spawning, inside
    # temporary trees from a version of the list that no longer existed, with
    # four gigabytes of /tmp behind it. The timeout was real and it was killing
    # the wrong thing.
    proc = subprocess.Popen([sys.executable, os.path.join(src, "scripts/mutate.py"), *argv],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=180)
        r = subprocess.CompletedProcess(argv, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.communicate()
        raise AssertionError(
            "%s did not answer in three minutes. A selection that names nothing is refused from "
            "the arguments; anything that reaches the baseline from here runs the suite, which "
            "runs this again. A hung measurement is not a measurement — and the whole process "
            "group is killed, because the run this started has started others." % " ".join(argv))
    assert r.returncode != 0, \
        "%s injected nothing and reported success — 0/0 is not a measurement" % " ".join(argv)
PYMETA

# The path a gate reads is hardcoded in validate-transition.py. The path the
# model is TOLD to write to lives in the skill. Nothing joined the two — so a
# copy-edit to a SKILL, or a renamed docs subdirectory, silently disarms a
# blocking gate: the document lands somewhere the gate does not look, the gate
# finds nothing, and (before today) opened. Derived from the source on both
# sides, so it cannot be satisfied by restating the table in a third place.
# The helper reads the same file the hook does, and refuses where it refuses.
# `_load_disk_state` answers an unparseable state with a fresh IDLE — right for
# the hook, which has another check for that; catastrophic for `--write`, which
# then lands that fresh IDLE ON TOP of the file. The one thing the product exists
# to protect, destroyed by the tool the method says to reach for first, in
# exactly the situation where the orchestrator says STOP and report.
python3 - "$SELF" <<'PYCORRUPT' && ok "the helper refuses a state it cannot read instead of overwriting it with a fresh IDLE" || bad "transition.py --write destroys a corrupt state's history — the file the whole product exists to protect"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
tr = os.path.join(repo, ".ddw", "scripts", "transition.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                "--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE", "--ticket", "T-1"],
               capture_output=True, text=True)
for broken in ('{ "phase": "CLAS', "not json at all", '{"phase": "CODE", "history": '):
    open(state, "w", encoding="utf-8").write(broken)
    # The destination is one the run could legitimately reach, so a refusal here
    # is about the unreadable file and not about the graph.
    r = subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write",
                        "--to", "CLASSIFY", "--action", "c", "--tier", "FEATURE",
                        "--ticket", "T-1"], capture_output=True, text=True)
    assert r.returncode == 2, f"a state of {broken!r} was accepted and written over"
    assert open(state, encoding="utf-8").read() == broken, \
        f"the helper overwrote a state it could not read ({broken!r})"
    assert "cannot be read" in r.stderr, f"the refusal does not say why: {r.stderr[:160]}"
PYCORRUPT

# Adding a SECOND tool to a repo that already has DDW. `had_manifest` was asked
# of the whole manifest, so a target that had never been installed was treated as
# an upgrade — and the user's own hooks, under exactly the names a user of that
# agent already has, were overwritten with no backup, no warning and exit 0.
python3 - "$SELF" <<'PYSECOND' && ok "installing a second tool leaves that tool's pre-existing hooks alone and says they are yours" || bad "adding a second tool silently destroys the user's own hook scripts"
import os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
MINE = "#!/bin/sh\n# the user's own hook\necho mine\n"
own = os.path.join(repo, ".codex", "hooks", "ddw")
os.makedirs(own, exist_ok=True)
for name in ("session-start.sh", "enforce.sh"):
    open(os.path.join(own, name), "w", encoding="utf-8").write(MINE)
out = subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "codex"],
                     capture_output=True, text=True).stdout
for name in ("session-start.sh", "enforce.sh"):
    assert open(os.path.join(own, name), encoding="utf-8").read() == MINE, \
        f"the user's {name} was overwritten by installing a second tool"
assert "they are yours" in out or "left alone" in out, \
    "the files were kept and the user was never told: " + out[-300:]
PYSECOND

python3 - "$SELF" <<'PYPATHS' && ok "every gate's document path is the one its skill tells you to write, and its validator the one its skill tells you to run" || bad "a gate reads one path and its skill documents another — the gate is disarmed and nothing said so"
import os, re, sys
src = sys.argv[1]
vt = open(os.path.join(src, "ddw/scripts/validate-transition.py"), encoding="utf-8").read()
calls = re.findall(
    r'_receipt_missing\(root, state, "(\w+)", "(\w+)", "(\w+)", \(([^)]*)\),\s*"([\w.]+)"',
    vt)
# One row per CALL SITE, and a gate may have several — `define` resolves a PRD,
# a fix brief or an RCA depending on the tier. Six distinct gates, and every
# call site checked against the skill that writes that document.
assert len({c[0] for c in calls}) == 6, \
    "expected six receipt gates, parsed %s" % sorted({c[0] for c in calls})
# gate -> everywhere the METHOD tells you where that gate's document goes. A
# skill for most of them; the `define` gate resolves three documents across three
# tiers and the FIX tier's RCA is documented by the phase rule rather than by a
# skill, so the question is asked of the whole method rather than of one file.
SKILL = {"define": "ddw-validate-prd", "spec": "ddw-validate-spec",
         "threat": "ddw-threat-modeling", "verify": "ddw-verify-module",
         "tests": "ddw-test", "sast": "ddw-security-sast"}
EXTRA = {"define": ["skills/ddw-create-prd/SKILL.md",
                    "ddw/rules/define.instructions.md"]}
for gate, receipt, subdir, stems_raw, script in calls:
    stems = re.findall(r'"(\w+)"', stems_raw)
    skill = os.path.join(src, "skills", SKILL[gate], "SKILL.md")
    assert os.path.exists(skill), f"{gate}: {SKILL[gate]} does not exist"
    text = open(skill, encoding="utf-8").read()
    for extra in EXTRA.get(gate, []):
        text += "\n" + open(os.path.join(src, extra), encoding="utf-8").read()
    # The directory the gate looks in has to be the directory the skill names…
    wanted = "docs/ddw/%s/" % subdir
    assert wanted in text, \
        f"the {gate} gate reads {wanted}, and {SKILL[gate]} never names it"
    # …under one of the filenames the gate accepts…
    assert any("%s%s-" % (wanted, stem) in text for stem in stems), \
        f"the {gate} gate accepts {stems} in {wanted}, and {SKILL[gate]} documents neither"
    # …and the script the refusal tells you to run has to be the one the skill
    # tells you to run, and has to exist.
    assert script in text, f"the {gate} refusal names {script}; {SKILL[gate]} names something else"
    assert os.path.exists(os.path.join(src, "ddw/scripts", script)), \
        f"{script} is named by the {gate} gate and is not in ddw/scripts/"
    # …and EVERY path in the skill that carries one of the gate's filenames has
    # to be under the directory the gate reads. "It says the right thing
    # somewhere" is not the property: the model follows whichever line it lands
    # on, and one drifted line sends the document where the gate does not look.
    for said_dir, said_stem in re.findall(r"docs/ddw/(\w+)/(\w+)-", text):
        if said_stem in stems:
            assert said_dir == subdir, \
                (f"the method tells you to write docs/ddw/{said_dir}/{said_stem}-… "
                 f"and the {gate} gate reads docs/ddw/{subdir}/{said_stem}-")
PYPATHS

# Ten of the seventeen skills could have their entire body replaced with "TODO."
# and the suite stayed green. A skill IS its protocol — the file is what the
# model follows — so a skill nothing can falsify has stopped being a rule. One
# narrow, load-bearing claim each, chosen so that gutting the file breaks it.
python3 - "$SELF" <<'PYSKILLS' && ok "every skill's load-bearing claim is asserted, so a gutted protocol cannot pass" || bad "a skill's whole protocol can be deleted and nothing notices — see which claim went missing, above"
import os, re, sys
src = sys.argv[1]
CLAIMS = {
    "ddw-commit":            ["AI-assisted:", "gitmoji", "git status"],
    "ddw-create-adr":        ["docs/adr/", "ADR"],
    "ddw-create-pr":         ["gh pr create", "gates.pr"],
    "ddw-create-prd":        ["docs/ddw/prd/", "PRD loops"],
    "ddw-create-spec":       ["docs/ddw/specs/", "Spec loops"],
    "ddw-context-check":     ["AGENTS.md", "## Stack"],
    "ddw-family-catalog":    ["family_catalog.py", "## Repo family", "--write-members"],
    "ddw-family-impact":     ["family_impact.py", "impact-data-", "--validate", "Sin impacto"],
    "ddw-family-status":     ["family_next.py", "origin/main", "update-row", "Never improvise"],
    "ddw-eject":             [".ddw/", "The repo wins", "CLAUDE_PLUGIN_ROOT"],
    "ddw-help":              ["/ddw-status", "/ddw-self-check"],
    "ddw-security-sast":     ["validate_sast.py", "docs/ddw/security/sast-"],
    "ddw-self-check":        ["INCONSISTENCY", "```bash"],
    "ddw-status":            [".ddw-state.json"],
    "ddw-test":              ["validate_tests.py", "docs/ddw/reports/tests-"],
    "ddw-threat-modeling":   ["validate_threat.py", "docs/ddw/security/threat-"],
    "ddw-validate-arch":     ["architecture", "AGENTS.md"],
    "ddw-validate-prd":      ["validate_prd.py", "docs/ddw/prd/prd-"],
    "ddw-validate-spec":     ["validate_spec.py", "docs/ddw/specs/"],
    "ddw-verify-module":     ["validate_verify.py", "docs/ddw/reports/verify-"],
}
present = {d for d in os.listdir(os.path.join(src, "skills"))
           if os.path.isdir(os.path.join(src, "skills", d))}
# The table keeps up with the skills in BOTH directions: a skill added with no
# claim here is a skill back to having no coverage at all.
assert present == set(CLAIMS), \
    "skills and claims disagree: only in skills=%s, only in the table=%s" % (
        sorted(present - set(CLAIMS)), sorted(set(CLAIMS) - present))
for skill, claims in sorted(CLAIMS.items()):
    text = open(os.path.join(src, "skills", skill, "SKILL.md"), encoding="utf-8").read()
    # Below the frontmatter: the description in the header is not the protocol,
    # and a check the frontmatter alone satisfies survives a gutted body.
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    for claim in claims:
        assert claim in body, f"{skill}/SKILL.md no longer says {claim!r}"
PYSKILLS

# /ddw-eject rests on one rule — the repo's `.ddw/` wins, the plugin is the
# fallback — asserted in four documents and executed by one shell function.
# Swapping the two branches left the suite green.
python3 - "$SELF" <<'PYEJECT' && ok "the method resolves to the repo's copy when there is one, and to the plugin only when there is not" || bad "the repo/plugin precedence /ddw-eject depends on can be inverted with nothing noticing"
import os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
guard = os.path.join(src, "adapters/claude/hooks/lib/guard.sh")
work = tempfile.mkdtemp(dir=os.environ["WORK"])
repo, plugin = os.path.join(work, "repo"), os.path.join(work, "plugin")
for d, name in ((os.path.join(repo, ".ddw"), "repo"), (os.path.join(plugin, "ddw"), "plugin")):
    os.makedirs(os.path.join(d, "scripts"))
    open(os.path.join(d, "orchestrator.md"), "w", encoding="utf-8").write(name)
    # An install is the method's SCRIPTS being there. The fixture used to be a
    # directory with one markdown file in it, which is exactly the shape the
    # check below now exists to refuse.
    open(os.path.join(d, "scripts", "hook-gate.py"), "w", encoding="utf-8").write("#\n")


def resolved():
    out = subprocess.run(["bash", "-c", "source %s; ddw_method" % guard],
                         capture_output=True, text=True,
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=repo,
                                  CLAUDE_PLUGIN_ROOT=plugin))
    return out.stdout.strip()


assert resolved() == os.path.join(repo, ".ddw"), \
    "with both present the plugin won: %r — /ddw-eject's whole promise is the other way" % resolved()
shutil.rmtree(os.path.join(repo, ".ddw"))
assert resolved() == os.path.join(plugin, "ddw"), \
    "with no repo copy it did not fall back to the plugin: %r" % resolved()

# A directory is not an install. Chosen by directory, `mkdir .ddw` resolved the
# method to an empty folder, and every hook then bowed out at its
# `[ -f "$DDW/scripts/hook-gate.py" ] || exit 0` — so one command with no
# privileges and no content turned enforcement off for the repo.
os.makedirs(os.path.join(repo, ".ddw"))
assert resolved() == os.path.join(plugin, "ddw"), \
    "an empty .ddw won the method: `mkdir .ddw` resolves DDW to a folder with no gate in it, " \
    "and every hook exits 0 rather than falling back to the copy that does: %r" % resolved()
PYEJECT

# …and the same question asked of the hooks themselves, because resolving a path
# correctly is not the thing that has to hold — refusing the write is. Under a
# plugin install the fallback an empty `.ddw` skips is the only copy of the
# method there is, so the hook that refused a write exits 0 for the same write
# once the directory exists. Driven through the shipped hook scripts, both
# modes, with the plugin as the only place the method lives.
python3 - "$SELF" <<'PYEMPTYDDW' && ok "an empty .ddw does not disarm the hooks: enforcement falls back to the plugin, not open" || bad "\`mkdir .ddw\` turns every Claude hook off — one command, no privileges, and the refusal becomes exit 0"
import json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
repo, plugin = os.path.join(work, "repo"), os.path.join(work, "plugin")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
shutil.copytree(os.path.join(src, "ddw"), os.path.join(plugin, "ddw"),
                ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(os.path.join(src, "adapters/claude/hooks"), os.path.join(plugin, "hooks"))

H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "tier": "FEATURE", "ticket": "T-1"}]
open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8").write(json.dumps(
    {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {}, "history": H}))
event = json.dumps({"tool_name": "Write",
                    "tool_input": {"file_path": os.path.join(repo, "src", "app.ts"),
                                   "content": "x"}})


def hook(name):
    return subprocess.run(["bash", os.path.join(plugin, "hooks", name)],
                          input=event, capture_output=True, text=True,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=repo,
                                   CLAUDE_PLUGIN_ROOT=plugin)).returncode


before = hook("validate-state-transition.sh")
assert before == 2, \
    "the fixture does not refuse this write to begin with (rc %s), so it cannot show anything " \
    "being turned off" % before
os.makedirs(os.path.join(repo, ".ddw"))
after = hook("validate-state-transition.sh")
assert after == 2, \
    "`mkdir .ddw` turned a refused write (exit 2) into an allowed one (exit %s): the method " \
    "resolved to the empty directory and the hook bowed out instead of using the plugin" % after
PYEMPTYDDW

# ── The method is protected where the method actually is ─────────────────────
#
# Every guard on DDW's own files asked "is this path under the repo root?",
# which is the whole story for a drop-in install and none of it for a plugin
# one: there the method sits in a plugin root SHARED BY EVERY PROJECT, so a
# write to it was outside the repo, therefore "not ours", therefore allowed. One
# write to the graph — `"PLAN->CLOSEOUT": {"gates": []}` — and a FEATURE reaches
# CLOSEOUT with no spec, threat, tests, sast or verify, in every repository that
# installs DDW as a plugin.
python3 - "$SELF" <<'PYPLUGINSEAL' && ok "under a plugin install the method itself is sealed, and the out-of-repo recovery path still is not" || bad "the plugin's graph, gate and validator are writable from inside a ticket — one write disarms DDW in every repo using it"
import json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
repo, plugin = os.path.join(work, "repo"), os.path.join(work, "plugin")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
shutil.copytree(os.path.join(src, "ddw"), os.path.join(plugin, "ddw"),
                ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree(os.path.join(src, "adapters/claude/hooks"), os.path.join(plugin, "hooks"))
H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "tier": "FEATURE", "ticket": "T-1"}]
open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8").write(json.dumps(
    {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {}, "history": H}))


def write_to(path):
    event = json.dumps({"tool_name": "Write",
                        "tool_input": {"file_path": path, "content": "x"}})
    return subprocess.run(["bash", os.path.join(plugin, "hooks",
                                                "validate-state-transition.sh")],
                          input=event, capture_output=True, text=True,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=repo,
                                   CLAUDE_PLUGIN_ROOT=plugin))


# The three that matter: the rules, the gate, and the code that judges.
for rel in ("ddw/rules/transition-graph.json", "ddw/scripts/hook-gate.py",
            "ddw/scripts/validate-transition.py"):
    r = write_to(os.path.join(plugin, rel))
    assert r.returncode == 2, \
        "a write to the plugin's %s was allowed (rc %s) — the method is shared, so this " \
        "disarms DDW for every repository using it, not just this one" % (rel, r.returncode)

# The control: the same event shape, inside the repo, still refused for its own
# reason. Without it a gate that refused everything would pass this check.
assert write_to(os.path.join(repo, "src", "app.ts")).returncode == 2, \
    "the control write is no longer refused, so the assertions above prove nothing"

# And the one door that has to stay open: the corrupt-state recovery this
# product prescribes tells the model to write the corrected state to a scratch
# path outside the repo. That path is not under the method root, and sealing the
# method must not turn that instruction into a painted door a second time.
out = os.path.join(work, "ddw-recovery-state.json")
r = write_to(out)
assert r.returncode == 0, \
    "the out-of-repo scratch path the corrupt-state refusal tells the model to use is now " \
    "refused too: the recovery it prescribes cannot be carried out: " + (r.stdout + r.stderr)[:200]
PYPLUGINSEAL

# ── Input that stops the hook rather than being refused by it ────────────────
#
# Two shapes the journal can take that no handler covered. A single non-UTF-8
# byte raised `UnicodeDecodeError` from the file ITERATION, not from
# `json.loads`, so it escaped both `except` clauses and came out of the hook as
# a traceback — every write in the repository refused, permanently, with the
# refusal naming `.ddw-state.json`, a file with nothing wrong in it. And
# `mkfifo .ddw-journal.jsonl` makes `open()` itself block until a writer that
# never comes: every hook hangs, with no output and no exit code. A hung hook is
# not a refusal — nothing tells the user anything at all.
#
# Driven with a timeout, because the second one reproduces by NOT returning:
# checking an exit code cannot detect it.
python3 - "$SELF" <<'PYHOSTILEJOURNAL' && ok "a journal that cannot be decoded, or is not a file at all, is a refusal that names it — not a stack and not a hang" || bad "one odd byte in the journal bricks the repo blaming the wrong file, or a FIFO there hangs every hook forever"
import importlib.util, os, subprocess, sys, tempfile
src = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)

STATE = '{"phase":"IDLE","tier":null,"gates":{},"history":[]}'


def fresh():
    repo = tempfile.mkdtemp(dir=os.environ["WORK"])
    open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8").write(STATE)
    return repo, os.path.join(repo, ".ddw-state.json")


# One byte that is not UTF-8, on its own line.
repo, state = fresh()
with open(os.path.join(repo, ".ddw-journal.jsonl"), "wb") as fh:
    fh.write(b'{"from":"IDLE","to":"CLASSIFY"}\n\xff\xfe\n')
try:
    vt._check_state_not_erased(state)
    raise AssertionError("an undecodable journal line was ignored, so the record it is the "
                         "evidence for can be short by one transition and nothing says so")
except vt.Block as exc:
    why = str(exc)
assert ".ddw-journal.jsonl" in why, \
    "the refusal does not name the journal — it used to name .ddw-state.json, which is the file " \
    "the reader then goes and inspects for nothing: %s" % why
# The lines that ARE readable still parse: one bad byte is not the whole file.
assert vt._journal_lines(state) == [{"from": "IDLE", "to": "CLASSIFY"}], \
    "a single undecodable line took the readable ones with it"

# …and the shape that reproduces by hanging. Run in a child with a timeout,
# because if this regresses the assertion is never reached at all.
probe = """
import importlib.util, os, sys, tempfile
spec = importlib.util.spec_from_file_location("vt", sys.argv[1])
vt = importlib.util.module_from_spec(spec); spec.loader.exec_module(vt)
victim, state_text = sys.argv[2], sys.argv[3]
repo = tempfile.mkdtemp(dir=os.environ["WORK"])
state = os.path.join(repo, ".ddw-state.json")
# The FIFO goes where the victim says; whatever is NOT the fifo is a real file,
# so the only unusual thing in the repo is the one under test.
if victim != ".ddw-state.json":
    open(state, "w", encoding="utf-8").write(state_text)
os.mkfifo(os.path.join(repo, victim))
try:
    vt._read_state_or_refuse(state)
    print("ALLOWED")
except vt.Block as exc:
    print("BLOCK " + str(exc))
"""
for victim in (".ddw-journal.jsonl", ".ddw-state.json"):
    try:
        out = subprocess.run([sys.executable, "-c", probe,
                              os.path.join(src, "ddw/scripts/validate-transition.py"),
                              victim, STATE],
                             capture_output=True, text=True, timeout=20).stdout
    except subprocess.TimeoutExpired:
        raise AssertionError(
            "a FIFO at %s hung the hook: `open()` blocks for a writer that never comes, so the "
            "session stops with no output and no exit code" % victim)
    assert out.startswith("BLOCK") and victim in out, \
        "a FIFO at %s was not refused by name: %s" % (victim, out[:150])

# The everyday journal is untouched by any of this.
repo, state = fresh()
open(os.path.join(repo, ".ddw-journal.jsonl"), "w", encoding="utf-8").write(
    '{"from":"IDLE","to":"CLASSIFY"}\n')
open(state, "w", encoding="utf-8").write(
    '{"phase":"CLASSIFY","tier":null,"gates":{},"history":'
    '[{"timestamp":"t","from":"IDLE","to":"CLASSIFY","action":"a"}]}')
vt._check_state_not_erased(state)
PYHOSTILEJOURNAL

# ── The corrective loop costs what it gave back ──────────────────────────────
#
# `clears` was a boolean operation and nothing outlived the write that performed
# it. For define, spec, threat and verify that is enough: the artifact IS what
# changed, so its hash moves and the old receipt stops matching. For tests and
# sast it is not — the artifact is a report ABOUT code that is about to change,
# and its bytes are identical after the fix. So VERIFY->CODE and back
# re-presented the same receipts and cost nothing, which is the loop the method
# documents as its recovery path.
python3 - "$SELF" <<'PYSPENT' && ok "a gate the corrective loop cleared cannot be re-claimed with the receipt from before it" || bad "tests and sast are re-claimed for free after a corrective loop — the report's bytes did not change, and neither did anything else"
import hashlib, json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
for sub in ("prd", "specs", "security", "reports"):
    os.makedirs(os.path.join(repo, "docs", "ddw", sub), exist_ok=True)
os.makedirs(os.path.join(repo, ".ddw-sessions"), exist_ok=True)
tr = os.path.join(repo, ".ddw", "scripts", "transition.py")
vt = os.path.join(repo, ".ddw", "scripts", "validate-transition.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")


def receipt(prefix, rel):
    """What a PASSED validation leaves: the marker AND the journal line."""
    path = os.path.join(repo, rel)
    open(path, "w", encoding="utf-8").write("# %s\n" % rel)
    digest = hashlib.sha256(open(path, encoding="utf-8").read().encode("utf-8")).hexdigest()[:12]
    name = "%s-validated-%s" % (prefix, digest)
    open(os.path.join(repo, ".ddw-sessions", name), "w", encoding="utf-8").write(
        os.path.basename(path))
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": "receipt", "name": name,
                             "file": os.path.basename(path)}, sort_keys=True) + "\n")


def step(*args):
    r = subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write", *args],
                       capture_output=True, text=True)
    if r.returncode == 0:
        subprocess.run([sys.executable, vt, "--mode", "post", "--state", state, "--graph", graph],
                       capture_output=True, text=True)
    return r.returncode, (r.stderr or "").strip()


receipt("prd", "docs/ddw/prd/prd-T-9.md")
receipt("spec", "docs/ddw/specs/spec-T-9.md")
receipt("threat", "docs/ddw/security/threat-T-9.md")
# The classify edge's context check and CODE's decisions record — other gates
# than the spent-receipt rule under test.
os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
open(os.path.join(repo, ".ddw-work", "context-check-T-9.md"), "w", encoding="utf-8").write(
    "Nothing to report.\n")
open(os.path.join(repo, "docs", "ddw", "specs", "decisions-T-9.md"), "w", encoding="utf-8").write(
    "No decisions were approved outside the spec during this ticket.\n")
for args in (("--to", "CLASSIFY", "--action", "classify: a feature",
              "--tier", "FEATURE", "--ticket", "T-9"),
             ("--to", "DEFINE", "--action", "write the PRD", "--title", "the fixture ticket"),
             ("--to", "PLAN", "--action", "plan it", "--gate", "define"),
             ("--to", "CODE", "--action", "implement", "--gate", "spec", "--gate", "threat")):
    rc, why = step(*args)
    assert rc == 0, "the walk to CODE was refused: %s" % why

receipt("tests", "docs/ddw/reports/tests-T-9.md")
receipt("sast", "docs/ddw/security/sast-T-9.md")
rc, why = step("--to", "VERIFY", "--action", "verify it", "--gate", "tests", "--gate", "sast")
assert rc == 0, "the first VERIFY was refused: %s" % why

rc, why = step("--to", "CODE", "--action", "fix what verification found")
assert rc == 0, "the corrective loop was refused: %s" % why

# The move: forward again on the receipts from before the fix. The reports are
# untouched, so their hashes are exactly what they were.
rc, why = step("--to", "VERIFY", "--action", "verify again", "--gate", "tests", "--gate", "sast")
assert rc != 0, \
    "the gates the corrective loop cleared were re-claimed with the receipts written before it: " \
    "the reports never changed, so nothing asked whether they had been re-run"
assert "corrective loop" in why or "cleared" in why, \
    "the refusal does not say why the receipt is stale: %s" % why

# …and re-running the validators is what pays for it. Same bytes, same digest,
# same marker name — a new journal line, which is the only thing that can record
# that a report was produced again.
receipt("tests", "docs/ddw/reports/tests-T-9.md")
receipt("sast", "docs/ddw/security/sast-T-9.md")
rc, why = step("--to", "VERIFY", "--action", "verify again", "--gate", "tests", "--gate", "sast")
assert rc == 0, \
    "re-running the validators does not re-open the gate, so the corrective loop is a dead end: %s" % why
PYSPENT

# ── The sealed names are sealed as NAMES ─────────────────────────────────────
#
# Paths are resolved through symlinks before being judged, and they have to be:
# that is what stops a guarded file being written under an unguarded name. But
# the sealed lists are about names, so resolving first answers the question
# about a different one. With `.ddw` made a symlink to a directory outside the
# repository, `.ddw/rules/transition-graph.json` and `.ddw/scripts/hook-gate.py`
# resolved outside it, and the guard said "nothing here is DDW's to judge" about
# DDW's own graph — while `src/app.ts`, in the same phase and the same event
# shape, was refused.
#
# `install.sh` never builds that topology, and `.ddw-sessions/` and
# `.ddw-installed.json` were never affected. Both halves are asserted, so the
# refusal rests on what is true rather than on the wider claim it was reported
# with.
python3 - "$SELF" <<'PYSYMSEAL' && ok "a .ddw symlinked out of the repository is still sealed, under the name it was written as" || bad "moving .ddw behind a symlink makes DDW's own graph and gate writable from inside a ticket"
import json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
work = tempfile.mkdtemp(dir=os.environ["WORK"])
repo, outside = os.path.join(work, "repo"), os.path.join(work, "elsewhere")
os.makedirs(repo)
os.makedirs(outside)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
shutil.move(os.path.join(repo, ".ddw"), os.path.join(outside, "ddw"))
os.symlink(os.path.join(outside, "ddw"), os.path.join(repo, ".ddw"))

H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "tier": "FEATURE", "ticket": "T-1"}]
state = os.path.join(repo, ".ddw-state.json")
open(state, "w", encoding="utf-8").write(json.dumps(
    {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {}, "history": H}))
ddw = os.path.join(repo, ".ddw")


def write_to(path):
    # Deliberately WITHOUT --method: that flag seals the method wherever it
    # lives, and it would mask whether the name-based seal still holds. This is
    # the guard underneath it.
    event = json.dumps({"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}})
    return subprocess.run([sys.executable, os.path.join(ddw, "scripts", "hook-gate.py"),
                           "--mode", "pre", "--state", state, "--repo", repo,
                           "--graph", os.path.join(ddw, "rules", "transition-graph.json")],
                          input=event, capture_output=True, text=True).returncode


for rel in (".ddw/rules/transition-graph.json", ".ddw/scripts/hook-gate.py",
            ".ddw/scripts/validate-transition.py"):
    assert write_to(os.path.join(repo, rel)) == 2, \
        "`%s` was writable once .ddw pointed outside the repo: the seal is on the name, and " \
        "the name is still `.ddw/`" % rel

# The two the finding also claimed and that were never affected — asserted so
# the record says what is true rather than what was reported.
for rel in (".ddw-sessions/forged", ".ddw-installed.json"):
    assert write_to(os.path.join(repo, rel)) == 2, "%s stopped being sealed" % rel
assert write_to(os.path.join(repo, "src", "app.ts")) == 2, \
    "the control write is no longer refused, so the assertions above prove nothing"

# And the scratch path outside the repo that the corrupt-state refusal tells the
# model to use has to stay reachable: judging the written name must not turn
# every out-of-repo path into a refusal.
assert write_to(os.path.join(work, "ddw-recovery-state.json")) == 0, \
    "the out-of-repo recovery path the refusal prescribes is now refused as well"
PYSYMSEAL

# …and the same question with the REPOSITORY reached through a symlink, which is
# not exotic: `/var` is `/private/var` on every macOS, so a checkout under the
# system temporary directory is behind one by default. The name-based seal
# anchored its comparison on a resolved root and judged the path as written, so
# every path written through the unresolved spelling read as "outside the
# repository" for its whole length and nothing under it was sealed at all. It
# held on Linux and not on macOS — same source, same commit, and the suite could
# not see the difference because it never built the shape.
python3 - "$SELF" <<'PYSYMROOT' && ok "the seal still holds when the repository itself is reached through a symlink, which is the ordinary case on macOS" || bad "a repo behind a symlinked path leaves DDW's own graph and gate writable from inside a ticket"
import json, os, shutil, subprocess, sys, tempfile
src = sys.argv[1]
real = tempfile.mkdtemp(dir=os.environ["WORK"])
work = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "link")
os.symlink(real, work)                    # every path below is written through it
repo, outside = os.path.join(work, "repo"), os.path.join(work, "elsewhere")
os.makedirs(repo)
os.makedirs(outside)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
shutil.move(os.path.join(repo, ".ddw"), os.path.join(outside, "ddw"))
os.symlink(os.path.join(outside, "ddw"), os.path.join(repo, ".ddw"))

H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "tier": "FEATURE", "ticket": "T-1"}]
state = os.path.join(repo, ".ddw-state.json")
open(state, "w", encoding="utf-8").write(json.dumps(
    {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {}, "history": H}))
ddw = os.path.join(repo, ".ddw")


def write_to(path):
    event = json.dumps({"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}})
    return subprocess.run([sys.executable, os.path.join(ddw, "scripts", "hook-gate.py"),
                           "--mode", "pre", "--state", state, "--repo", repo,
                           "--graph", os.path.join(ddw, "rules", "transition-graph.json")],
                          input=event, capture_output=True, text=True).returncode


for rel in (".ddw/rules/transition-graph.json", ".ddw/scripts/hook-gate.py",
            ".ddw-sessions/forged", ".ddw-installed.json"):
    assert write_to(os.path.join(repo, rel)) == 2, \
        ("`%s` is writable when the repo is reached through a symlink: the seal compared a path "
         "written one way against a root resolved another, and everything under it read as "
         "outside the repository" % rel)
assert write_to(os.path.join(repo, "src", "app.ts")) == 2, \
    "the control write is no longer refused, so the assertions above prove nothing"
assert write_to(os.path.join(work, "ddw-recovery-state.json")) == 0, \
    "the out-of-repo recovery path the refusal prescribes is refused under a symlinked root"
PYSYMROOT

# ── A gate is earned in the phase that does its work ─────────────────────────
#
# `--claim` checked that the name is a known gate and that its evidence exists,
# and never read the phase; a raw Write that appends no history returns early in
# `validate`, so nothing covered that path either. Under QUICK-FIX the closing
# edge CODE->CLOSEOUT costs define, tests and sast — three booleans that could
# all be set while sitting in DEFINE, before a line of the fix existed.
# `transition.py --claim` states the contract in its own help text ("in the
# phase that owns it") and nothing held it.
#
# The owners are derived from the graph, not listed here: an edge `A->B` asking
# for `g` is the statement that `g` is what leaving A costs.
python3 - "$SELF" <<'PYGATEOWNER' && ok "a gate cannot be claimed from a phase the graph does not say earns it" || bad "the gates of a later phase can be claimed from an earlier one — the order that IS the guarantee is optional"
import importlib.util, json, os, sys
src = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "vt", os.path.join(src, "ddw/scripts/validate-transition.py"))
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)
graph = json.load(open(os.path.join(src, "ddw/rules/transition-graph.json"), encoding="utf-8"))

owners = vt._gate_owners(graph, "QUICK-FIX")
assert owners.get("tests") == {"CODE"} and owners.get("sast") == {"CODE"}, \
    "QUICK-FIX no longer earns tests/sast in CODE; this check is asserting a graph that changed"
# Several owners is normal and must stay allowed: QUICK-FIX asks `define` on
# both DEFINE->CODE and CODE->CLOSEOUT.
assert owners.get("define") == {"DEFINE", "CODE"}, \
    "a gate asked for by two edges no longer has two owners: %r" % (owners.get("define"),)


def h(f, t, tier="QUICK-FIX"):
    return {"timestamp": "2026-01-01T00:00:00Z", "from": f, "to": t, "action": "a",
            "tier": tier, "ticket": "T-1"}


HIST = [h("IDLE", "CLASSIFY"), h("CLASSIFY", "DEFINE")]
at_define = {"tier": "QUICK-FIX", "phase": "DEFINE", "ticket": "T-1", "gates": {},
             "history": HIST}


def claim(state, gates, phase=None):
    new = json.loads(json.dumps(state))
    new["gates"] = dict(new.get("gates") or {}, **gates)
    if phase:
        new["phase"] = phase
    try:
        vt.validate(state, new, graph)
        return None
    except vt.Block as exc:
        return str(exc)


# The three the closing edge costs, claimed from DEFINE.
for gate in ("tests", "sast"):
    why = claim(at_define, {gate: True})
    assert why, "`%s` was claimed from DEFINE, where the fix has not been written yet" % gate
    assert "CODE" in why, "the refusal does not say where it IS earned: %s" % why

# …and the same claim from the phase that owns it is untouched.
at_code = {"tier": "QUICK-FIX", "phase": "CODE", "ticket": "T-1",
           "gates": {"define": True},
           "history": HIST + [h("DEFINE", "CODE")]}
for gate in ("tests", "sast"):
    assert claim(at_code, {gate: True}) is None, \
        "`%s` cannot be claimed in CODE, which is the only phase that earns it" % gate

# A gate no edge asks for has no owner and fails closed — a gate nothing spends
# is not one anything earns.
assert claim(at_define, {"verify": True}), \
    "`verify` was claimed under QUICK-FIX, a tier whose graph never asks for it"

# And under FEATURE, `define` is DEFINE's alone: claiming it from PLAN is the
# same move one phase later.
feat = {"tier": "FEATURE", "phase": "PLAN", "ticket": "T-1", "gates": {},
        "history": [h("IDLE", "CLASSIFY", "FEATURE"), h("CLASSIFY", "DEFINE", "FEATURE"),
                    h("DEFINE", "PLAN", "FEATURE")]}
assert claim(feat, {"spec": True}) is None, "`spec` is earned in PLAN and was refused there"
assert claim(feat, {"define": True}), "`define` was claimed from PLAN under FEATURE"
PYGATEOWNER

# ── Deleting the manifest is not an uninstall ────────────────────────────────
#
# `_manifest_paths` returns an empty set when it cannot read
# `.ddw-installed.json`, and every hook script was protected by nothing else. So
# `rm .ddw-installed.json` — one file whose name reads like a build artifact —
# turned a refused write to the gate script into exit 0, and turned drift
# detection off permanently, which is the worse half: the write leaves evidence,
# and this removes what would have reported it.
python3 - "$SELF" <<'PYNOMANIFEST' && ok "deleting the install manifest neither unseals the hooks nor silences the drift report" || bad "\`rm .ddw-installed.json\` unseals every hook script and leaves a tampered repo reading like a clean one"
import json, os, subprocess, sys, tempfile
src = sys.argv[1]
repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "repo")
os.makedirs(repo)
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
subprocess.run(["bash", os.path.join(src, "install.sh"), repo, "--target", "claude"],
               capture_output=True, text=True)
H = [{"timestamp": "2026-01-01T00:00:00Z", "from": "IDLE", "to": "CLASSIFY", "action": "a"},
     {"timestamp": "2026-01-01T00:01:00Z", "from": "CLASSIFY", "to": "DEFINE", "action": "b",
      "tier": "FEATURE", "ticket": "T-1"}]
state_p = os.path.join(repo, ".ddw-state.json")
open(state_p, "w", encoding="utf-8").write(json.dumps(
    {"tier": "FEATURE", "phase": "DEFINE", "ticket": "T-1", "gates": {}, "history": H}))
ddw = os.path.join(repo, ".ddw")


def write_to(rel):
    event = json.dumps({"tool_name": "Write",
                        "tool_input": {"file_path": os.path.join(repo, rel), "content": "x"}})
    return subprocess.run([sys.executable, os.path.join(ddw, "scripts", "hook-gate.py"),
                           "--mode", "pre", "--state", state_p, "--repo", repo,
                           "--method", ddw,
                           "--graph", os.path.join(ddw, "rules", "transition-graph.json")],
                          input=event, capture_output=True, text=True).returncode


SEALED = (".claude/hooks/validate-state-transition.sh", ".claude/hooks/enforce.sh",
          ".claude/settings.json", ".ddw/rules/transition-graph.json")
for rel in SEALED:
    assert write_to(rel) == 2, "%s is not sealed even WITH the manifest present" % rel

os.remove(os.path.join(repo, ".ddw-installed.json"))
for rel in SEALED:
    assert write_to(rel) == 2, \
        "with the manifest deleted, `%s` became writable: the only thing protecting the hook " \
        "scripts was a file anyone can remove" % rel

# And the boot has to say so. Silence here is the permanent half: nothing in the
# repository can be compared against anything again, and every later session
# reads a tampered install as a clean one.
sb = os.path.join(ddw, "scripts", "session-boot.py")
out = subprocess.run([sys.executable, sb, "--repo", repo, "--session-id", "s"],
                     capture_output=True, text=True).stdout
assert ".ddw-installed.json" in out, \
    "the boot says nothing about a missing manifest in a repo that plainly has `.ddw/` in it: " \
    + out[:200]

# …and it must stay quiet where the manifest is legitimately absent. A plugin
# install writes nothing into the repository, so there is no `.ddw/` and no
# manifest, and warning there would train the reader to ignore this.
plugin_repo = os.path.join(tempfile.mkdtemp(dir=os.environ["WORK"]), "plain")
os.makedirs(plugin_repo)
subprocess.run(["git", "-C", plugin_repo, "init", "-q"], check=True)
quiet = subprocess.run([sys.executable, sb, "--repo", plugin_repo, "--session-id", "s"],
                       capture_output=True, text=True).stdout
assert ".ddw-installed.json" not in quiet, \
    "a repo DDW was never installed into is reported as having lost its manifest: " + quiet[:200]
PYNOMANIFEST

# The sealed wiring directories are a closed literal in the shipped validator,
# because it cannot read `adapters/`. This is what stops that literal drifting
# from what the adapters actually declare — an adapter whose destination is not
# sealed is one `rm` away from being unprotected again.
python3 - "$SELF" <<'PYWIRINGSEAL' && ok "every adapter's hook destination is in the validator's sealed set" || bad "an adapter installs its hooks somewhere the validator does not seal"
import json, glob, os, re, sys
src = sys.argv[1]
vt = open(os.path.join(src, "ddw/scripts/validate-transition.py"), encoding="utf-8").read()
m = re.search(r"PROTECTED_WIRING_DIRS = \(([^)]*)\)", vt, re.S)
assert m, "the validator no longer carries a sealed set of wiring directories"
sealed = tuple(s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip())
assert sealed, "the sealed set is empty"

declared = []
for path in sorted(glob.glob(os.path.join(src, "adapters/*/adapter.json"))):
    recipe = json.load(open(path, encoding="utf-8"))
    wiring = recipe.get("wiring") or []
    if isinstance(wiring, dict):
        wiring = [wiring]
    for w in wiring:
        to = w.get("to") if isinstance(w, dict) else None
        if to:
            declared.append((os.path.basename(os.path.dirname(path)), to.rstrip("/") + "/"))
assert len(declared) >= 6, "found %d wiring destinations, fewer than there are adapters" % len(declared)

for adapter, dest in declared:
    assert any(dest == s or dest.startswith(s) for s in sealed), \
        "the %s adapter installs its hooks into `%s`, which no entry of PROTECTED_WIRING_DIRS " \
        "covers: deleting the manifest leaves them writable" % (adapter, dest)
PYWIRINGSEAL

# Sealing it depends on each adapter HANDING the gate the method root it already
# resolved to find the gate. Asked of every adapter, derived from the files, so
# the next one added is asked too rather than being the one nobody listed.
python3 - "$SELF" <<'PYMETHODARG' && ok "every adapter's pre-write hook hands the gate the method root it resolved" || bad "an adapter invokes the gate without --method, so under a plugin install the method is unprotected there"
import os, re, sys
src = sys.argv[1]
adapters = os.path.join(src, "adapters")

# Both spellings of a gate invocation run across several lines — the shell ones
# with `\` continuations, the JS one as an argv array — so this reads whole
# invocations. Judging line by line called two correct adapters broken, which is
# the failure mode that gets a check deleted rather than fixed.
pre = []
for dirpath, _dirs, files in os.walk(adapters):
    for name in sorted(files):
        if not name.endswith((".sh", ".js")):
            continue
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, src)
        text = open(path, encoding="utf-8").read()
        if name.endswith(".sh"):
            joined = re.sub(r"\\\n\s*", " ", text)
            for line in joined.splitlines():
                # Matched on the INVOCATION, not on the gate's filename: four of
                # the six adapters run it through a `$GATE` variable, and a
                # matcher looking for `hook-gate.py` saw two of them.
                if "--mode pre" in line and "python3" in line and not line.lstrip().startswith("#"):
                    pre.append((rel, " ".join(line.split())))
        else:
            m = re.search(r"const runGate[\s\S]{0,500}?\n\s*\}\)", text)
            if m and "gate" in m.group(0):
                # This one is called for both modes with `mode` as a variable,
                # so it has to carry --method for the pre call to be covered.
                pre.append((rel, " ".join(m.group(0).split())))

assert len(pre) >= 6, \
    "found %d gate invocations across the adapters, which is fewer than there are adapters — " \
    "this check is not reading them: %s" % (len(pre), [r for r, _ in pre])
for rel, call in pre:
    assert "--method" in call, \
        "%s runs the gate in pre mode without --method: under a plugin install the method " \
        "root is outside the repo, and every guard on DDW's own files answers 'not ours'" % rel
PYMETHODARG

# /ddw-commit's template against the rule this repo enforces on itself. The
# template could be changed to emit the trailer `check_commits.py` refuses, and
# nothing joined the two — so the skill would teach every user to write a commit
# DDW's own checker rejects.
python3 - "$SELF" <<'PYTRAILER' && ok "the commit template writes the attribution the repo's own checker demands" || bad "the commit skill's template and the attribution rule disagree — the skill teaches a commit DDW rejects"
import os, re, subprocess, sys, tempfile
src = sys.argv[1]
skill = open(os.path.join(src, "skills/ddw-commit/SKILL.md"), encoding="utf-8").read()
assert "Co-Authored-By" not in skill, \
    "the template teaches a Co-Authored-By trailer, which scripts/check_commits.py refuses"
m = re.search(r"^AI-assisted:.*$", skill, re.M)
assert m, "the template no longer carries the attribution trailer at all"
# Through the checker, not against a string: a commit written the way the skill
# says has to pass the script that guards this repo's own history.
repo = tempfile.mkdtemp(dir=os.environ["WORK"])
subprocess.run(["git", "-C", repo, "init", "-q", "-b", "main"], check=True)
for k, v in (("user.email", "ddw@test"), ("user.name", "ddw"), ("commit.gpgsign", "false")):
    subprocess.run(["git", "-C", repo, "config", k, v], check=True)
subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
base = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-F", "-"],
               input="✨ feat(x): a thing the skill would write\n\n%s\n" % m.group(0),
               text=True, check=True)
r = subprocess.run([sys.executable, os.path.join(src, "scripts/check_commits.py"),
                    "--repo", repo, "--since", base], capture_output=True, text=True)
assert r.returncode == 0, \
    "a commit written from the skill's own template is refused:\n" + (r.stdout + r.stderr)[-300:]
PYTRAILER

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
forged = {"tier": "FEATURE", "phase": "CLOSEOUT", "ticket": "EVIL-1",
          "gates": {"commit": True, "pr": True},
          "history": [h("IDLE", "CLOSEOUT", "resume: EVIL-1")]}
assert rc(virgin, forged) == 2, "a resume with no pause behind it walked the whole pipeline"

paused = [h("IDLE", "CLASSIFY", tier=None), h("CLASSIFY", "DEFINE"), h("DEFINE", "PLAN"),
          h("PLAN", "IDLE", "pause: waiting on product")]
idle = {"tier": None, "phase": "IDLE", "gates": {}, "history": paused}

good = {"tier": "FEATURE", "phase": "PLAN", "ticket": "FEAT-001", "gates": {"define": True},
        "history": paused + [h("IDLE", "PLAN", "resume: FEAT-001")]}
assert rc(idle, good) == 0, "a legitimate resume was refused"

elsewhere = {"tier": "FEATURE", "phase": "CODE", "ticket": "FEAT-001", "gates": {"define": True},
             "history": paused + [h("IDLE", "CODE", "resume: FEAT-001")]}
assert rc(idle, elsewhere) == 2, "a resume landed in a phase the ticket was never paused at"

dropped = paused[:-1] + [h("PLAN", "IDLE", "abandon: not worth it")]
assert rc({"tier": None, "phase": "IDLE", "gates": {}, "history": dropped},
          {"tier": "FEATURE", "phase": "PLAN", "ticket": "FEAT-001", "gates": {"define": True},
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
json.dump({"tier": None, "phase": "CODE", "ticket": "FEAT-001",
           "gates": {k: True for k in ("define", "spec", "threat", "tests", "sast", "verify")},
           "history": [{"timestamp": "2026-01-01T00:00:00Z", "from": "CLOSEOUT",
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

base = {"tier": "FEATURE", "phase": "PLAN", "ticket": "T-1", "gates": {"define": True},
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
    # whole point — CODE reaches IDLE through VERIFY and CLOSEOUT, so any check
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
python3 "$RUN/.ddw/scripts/transition.py" --to CLASSIFY --action start --ticket T-1 --state "$RST" \
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
rstep --to CLOSEOUT --action verify  --gate verify
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
    {"timestamp": "2026-07-27T11:01:00Z", "from": "CLASSIFY", "to": "CLOSEOUT",
     "action": "teleport", "tier": "FEATURE"},
    {"timestamp": "2026-07-27T11:02:00Z", "from": "CLOSEOUT", "to": "IDLE",
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
        ("PLAN","CODE"),("CODE","VERIFY"),("VERIFY","CLOSEOUT"))]
earned = {k: True for k in ("define","spec","threat","tests","sast","verify")}   # no commit, no pr
def attempt(action, src="CLOSEOUT", tier="FEATURE", gates=None, hist=None):
    h = hist if hist is not None else run
    entry = {"timestamp": T, "from": src, "to": "IDLE", "action": action}
    return ({"phase": src, "tier": tier, "gates": gates if gates is not None else earned, "history": h},
            {"phase": "IDLE", "tier": None, "gates": {}, "history": h + [entry]})
def blocked(*a, **k):
    try:
        m.validate(*attempt(*a, **k), graph=g, max_appended=1); return False
    except m.Block:
        return True
assert blocked("abandon"),                  "abandon walked out of CLOSEOUT without commit+pr"
assert blocked("pause: later"),             "pause walked out of CLOSEOUT without commit+pr"
assert blocked("abandonware cleanup"),      "an unanchored prefix match counted as an abandon"
# …and the same question where walking away is ALLOWED, which is the only
# place it discriminates: at CLOSEOUT an abandon is refused whatever the word
# matched, so the assertion above holds for a reason that is not the rule.
MID = {"define": True, "spec": True, "threat": True}
assert blocked("abandonware cleanup", src="CODE", gates=MID, hist=run[:4]), \
    "from CODE, a word that merely STARTS with abandon walked out as a declared abandon"
assert blocked("pause-the-build until Friday", src="CODE", gates=MID, hist=run[:4]), \
    "from CODE, `pause-the-build` walked out as a declared pause"
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
        ("PLAN","CODE"),("CODE","VERIFY"),("VERIFY","CLOSEOUT"))]
full = {k: True for k in ("define","spec","threat","tests","sast","verify")}
def blocked(old, new, **kw):
    try:
        m.validate(old, new, g, **kw); return False
    except m.Block:
        return True
# the whole pipeline asserted in a single write
assert blocked({"phase":"IDLE","tier":None,"gates":{},"history":[]},
               {"phase":"CLOSEOUT","tier":"FEATURE","gates":full,"history":run},
               max_appended=1), "a single write declared six transitions"
# closing out while keeping the tier / the gates
closed = run + [{"timestamp": T, "from":"CLOSEOUT","to":"IDLE","action":"done"}]
paid = dict(full, commit=True, pr=True)
assert blocked({"phase":"CLOSEOUT","tier":"FEATURE","gates":paid,"history":run},
               {"phase":"IDLE","tier":"FEATURE","gates":{},"history":closed},
               max_appended=1), "the tier survived the closeout"
assert blocked({"phase":"CLOSEOUT","tier":"FEATURE","gates":paid,"history":run},
               {"phase":"IDLE","tier":None,"gates":paid,"history":closed},
               max_appended=1), "the gates survived the closeout"
# hopping tier mid-run to reach an edge the real tier gates
mid = run[:5]
assert blocked({"phase":"VERIFY","tier":"FEATURE",
                "gates":{"define":True,"spec":True,"threat":True,"tests":True,"sast":True},
                "history":mid},
               {"phase":"CLOSEOUT","tier":"QUICK-FIX",
                "gates":{"define":True,"tests":True,"sast":True},
                "history":mid+[{"timestamp":T,"from":"VERIFY","to":"CLOSEOUT"}]},
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
python3 "$TRL" --to CLASSIFY --action r --ticket T-1 --state "$LOOP/.ddw-state.json" --graph "$G" > "$LOOP/.ddw-state.json"
# The gates, EARNED. Without `ddw_earn` every step fails silently — `lstep`
# redirects stderr and only copies the state if the helper exited 0 — and the
# fixture stayed in DEFINE: the two checks below asked about a DEFINE→VERIFY
# edge that is not in the graph, so one reported green for a reason that had
# nothing to do with the corrective loop, and the other measured the same
# thing as its neighbor. It is the only one of this section's three fixtures
# that did not earn them.
# Claiming and MOVING are two calls: `--claim` marks gates in the current
# phase and takes no edge. In a single one, the helper refuses both things.
lstep --to DEFINE --action c --tier FEATURE --title "the fixture ticket"
ddw_earn "$LOOP" define T-1;  lstep --claim define
lstep --to PLAN   --action p
ddw_earn "$LOOP" spec T-1; ddw_earn "$LOOP" threat T-1;  lstep --claim spec --claim threat
lstep --to CODE   --action x
ddw_earn "$LOOP" tests T-1; ddw_earn "$LOOP" sast T-1;  lstep --claim tests --claim sast
lstep --to VERIFY --action x
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

# ── One ticket, walked the way a user walks it ───────────────────────────────
#
# Every check above drives a function or a hook with a state built to reach it.
# This one runs the SANCTIONED PATH end to end — `transition.py --write` for each
# step, then the post hook after each one, exactly as a session does — and it is
# how three defects surfaced that nothing else could see: choosing an autonomy
# mode made the post hook refuse every later call (the replay's first edge comes
# from IDLE, so the CLASSIFY exemption never matched); the helper had no way to
# name a ticket, so its own output claimed gates against a null one; and pausing
# to work on something else could not be resumed. Each rule passed on its own.
section "A whole ticket, through the helper and both hooks"
E2E="$WORK/e2e"; mkdir -p "$E2E"
git -C "$E2E" init -q .
bash "$SELF/install.sh" "$E2E" --target claude >/dev/null 2>&1
python3 - "$E2E" <<'PYE2E' && ok "a full ticket — classify, define, plan, code, pause, another ticket, resume, corrective loop, closeout — walks the sanctioned path with both hooks green" || bad "the pipeline cannot be walked end to end through its own helper: see which step, above"
import hashlib, json, os, subprocess, sys
repo = sys.argv[1]
tr = os.path.join(repo, ".ddw", "scripts", "transition.py")
vt = os.path.join(repo, ".ddw", "scripts", "validate-transition.py")
graph = os.path.join(repo, ".ddw", "rules", "transition-graph.json")
state = os.path.join(repo, ".ddw-state.json")
for sub in ("docs/ddw/prd", "docs/ddw/specs", "docs/ddw/security", "docs/ddw/reports",
            ".ddw-sessions"):
    os.makedirs(os.path.join(repo, sub), exist_ok=True)


def receipt(prefix, rel):
    """What a PASSED validation leaves behind, written the way the validators
    write it — content-hashed, naming the file it was earned for."""
    path = os.path.join(repo, rel)
    open(path, "w", encoding="utf-8").write("# %s\n" % rel)
    digest = hashlib.sha256(open(path, encoding="utf-8").read().encode("utf-8")).hexdigest()[:12]
    name = "%s-validated-%s" % (prefix, digest)
    open(os.path.join(repo, ".ddw-sessions", name), "w").write(os.path.basename(path))
    # The journal line a real validator leaves. Without it this fixture is
    # minting the forgery the gate now refuses.
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": "receipt", "name": name,
                             "file": os.path.basename(path)}, sort_keys=True) + "\n")


def step(label, *args):
    r = subprocess.run([sys.executable, tr, "--state", state, "--graph", graph, "--write", *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, "%s refused by the helper: %s" % (label, (r.stderr or "").strip()[:200])
    p = subprocess.run([sys.executable, vt, "--mode", "post", "--state", state, "--graph", graph],
                       capture_output=True, text=True)
    assert p.returncode == 0, "%s refused by the post hook: %s" % (label, (p.stdout + p.stderr).strip()[:220])


receipt("prd", "docs/ddw/prd/prd-T-1.md")
receipt("spec", "docs/ddw/specs/spec-T-1.md")
receipt("threat", "docs/ddw/security/threat-T-1.md")
# What CLASSIFY and CODE leave behind on a real run — the context check and the
# decisions record — created where a real run creates them, so the walk is the
# walk a compliant ticket takes.
os.makedirs(os.path.join(repo, ".ddw-work"), exist_ok=True)
open(os.path.join(repo, ".ddw-work", "context-check-T-1.md"), "w", encoding="utf-8").write(
    "Nothing to report.\n")
open(os.path.join(repo, "docs", "ddw", "specs", "decisions-T-1.md"), "w", encoding="utf-8").write(
    "No decisions were approved outside the spec during this ticket.\n")
step("classify", "--to", "CLASSIFY", "--action", "classify: a feature",
     "--tier", "FEATURE", "--ticket", "T-1", "--autonomy", "minimal")
step("define", "--to", "DEFINE", "--action", "write the PRD", "--title", "the fixture ticket")
step("plan", "--to", "PLAN", "--action", "plan it", "--gate", "define")
step("code", "--to", "CODE", "--action", "implement", "--gate", "spec", "--gate", "threat")
# Set aside, run something else start to finish, come back.
step("pause", "--to", "IDLE", "--action", "pause: waiting on product")
step("other ticket", "--to", "CLASSIFY", "--action", "classify: unrelated",
     "--tier", "QUICK-FIX", "--ticket", "T-2")
step("drop it", "--to", "IDLE", "--action", "abandon: not worth it")
step("resume", "--to", "CODE", "--action", "resume: back to T-1", "--tier", "FEATURE",
     "--ticket", "T-1", "--autonomy", "minimal",
     "--gate", "define", "--gate", "spec", "--gate", "threat")
receipt("tests", "docs/ddw/reports/tests-T-1.md")
receipt("sast", "docs/ddw/security/sast-T-1.md")
step("verify", "--to", "VERIFY", "--action", "verify it", "--gate", "tests", "--gate", "sast")
# The corrective loop: back to CODE, giving up what VERIFY granted, then forward
# again re-earning it. The pipeline's own documented recovery path.
step("corrective loop", "--to", "CODE", "--action", "fix what verification found")
# …and re-earning them means RUNNING them again. The reports' bytes are
# identical before and after the fix — they are reports about the code, not the
# code — so the content hash cannot tell the two runs apart, and reusing the old
# receipts used to cost nothing. What distinguishes them is the journal line a
# validator leaves when it passes, which is what these two calls model.
receipt("tests", "docs/ddw/reports/tests-T-1.md")
receipt("sast", "docs/ddw/security/sast-T-1.md")
step("re-verify", "--to", "VERIFY", "--action", "verify again", "--gate", "tests", "--gate", "sast")
receipt("verify", "docs/ddw/reports/verify-T-1.md")
step("closeout", "--to", "CLOSEOUT", "--action", "close it out", "--gate", "verify")
d = json.load(open(state, encoding="utf-8"))
assert d["ticket"] == "T-1" and d["phase"] == "CLOSEOUT", d
assert all(e.get("ticket") for e in d["history"]), "an entry came out unattributable"
# The mode is stamped on the edges taken under it, which is the only place it can
# live: the header resets when the ticket closes.
walked = [e for e in d["history"][:5] if e.get("autonomy") == "minimal"]
assert len(walked) == 5, "the run under `minimal` reads identically to one somebody watched"
# A pause does not carry the mode across on its own — reaching IDLE clears it —
# and the resume above answered the question the pause protocol makes the
# assistant ask. So it is set here because somebody said so, and the edges after
# it are stamped with it.
assert d["autonomy"] == "minimal", \
    "the answer given when resuming did not take: %r" % d["autonomy"]
assert all(e.get("autonomy") == "minimal" for e in d["history"][7:]), \
    "the edges walked after the resume do not record the mode they were walked under"
PYE2E

# ── What the installer promises about a plugin, against what it does ─────────
# The banner said "Nothing of DDW is written into your repo" and thirty lines
# below the same run printed "scope: project". Both cannot be true: a
# project-scope install records the activation in the repo's own settings file.
# This is not a check for a sentence — it compares two facts inside the file, so
# rewording the promise keeps it honest and reverting the behaviour trips it.
python3 - "$SELF" <<'PYCHK' && ok "the plugin banner tells the truth about its scope — user-wide, with the per-repo off switch named" || bad "the plugin's scope and its banner disagree, or the user-wide install hides its reach"
import sys
src = open(f"{sys.argv[1]}/install.sh", encoding="utf-8").read()
start = src.index('MODE" = "plugin"')
banner = src[start:start + 2200]
if "--scope user" in src:
    # A user-scope install reaches every repo the user opens. A banner that
    # does not say so is the measured defect inverted: one repo of a family
    # got project scope, the sibling ran naked, and nothing warned. Whole
    # profile, said out loud, and the way to switch one repo off named.
    assert "YOUR profile" in banner and "plugin disable" in banner, (
        "install.sh installs at --scope user but its banner does not say the "
        "install covers the whole profile, or does not name the per-repo off "
        "switch — reach that is not disclosed reads as a repo-local install")
elif "--scope project" in src:
    assert ".claude/settings.json" in banner, (
        "install.sh installs at --scope project but its plugin banner never names "
        ".claude/settings.json, so the user is told nothing lands in the repo")
PYCHK

# ── The two writers of .gitignore write the same list ──────────────────
# `install.sh` writes the block on an install; `session-boot.py` writes it at
# every boot, and under a plugin install it is the ONLY writer — nothing there
# ever runs the installer. They drifted: `.ddw-work/` was in one and not the
# other, so the runtime that never saw an installer offered the drafted commit
# message and PR body to the next `git add -A`.
python3 - "$SELF" <<'PYCHK' && ok "both writers of the .gitignore block agree on what is runtime" || bad "install.sh and session-boot.py disagree about which paths are runtime"
import ast, re, sys
root = sys.argv[1]
sh = open(f"{root}/install.sh", encoding="utf-8").read()
py = open(f"{root}/ddw/scripts/session-boot.py", encoding="utf-8").read()
m = re.search(r"GITIGNORE_ENTRIES\s*=\s*(\([^)]*\))", py, re.S)
assert m, "GITIGNORE_ENTRIES not found in session-boot.py"
runtime = set(ast.literal_eval(m.group(1)))
start = sh.index("'# BEGIN DDW")
end = sh.index("'# END DDW", start)
shipped = set(re.findall(r"^\s*'(\.[^']+)'\s*\\?$", sh[start:end], re.M))
assert shipped, "the installer's .gitignore block has no entries to compare"
assert shipped == runtime, (
    "the installer ignores %s and the runtime ignores %s; the difference is %s"
    % (sorted(shipped), sorted(runtime), sorted(shipped ^ runtime)))
PYCHK

# ── This repository obeys the block it writes into everybody else's ──────────
# DDW is developed with DDW, so its own runtime lands here too. It ignored three
# of the six paths, by hand, without the markers — and `.ddw-journal.jsonl` was
# committed, seventeen transitions of one machine's local history.
python3 - "$SELF" <<'PYCHK' && ok "this repo ignores its own runtime, and tracks none of it" || bad "DDW does not obey the .gitignore block it writes into other repos"
import ast, re, subprocess, sys
root = sys.argv[1]
py = open(f"{root}/ddw/scripts/session-boot.py", encoding="utf-8").read()
runtime = set(ast.literal_eval(re.search(r"GITIGNORE_ENTRIES\s*=\s*(\([^)]*\))", py, re.S).group(1)))
own = open(f"{root}/.gitignore", encoding="utf-8").read()
assert "# BEGIN DDW" in own and "# END DDW" in own, "no DDW block in this repo's own .gitignore"
# RULES, not text. The block documents each path in a comment above the rules,
# so a substring search found `.ddw-journal.jsonl` in its own explanation and
# passed while the rule beneath it was gone — the file describing what it
# ignores answering for the ignoring.
rules = {l.strip() for l in own.splitlines() if l.strip() and not l.lstrip().startswith("#")}
missing = [e for e in runtime if e not in rules]
assert not missing, "this repo's .gitignore is missing %s" % missing
tracked = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True).stdout.split()
leaked = [f for f in tracked
          if any(f == e or f.startswith(e) for e in runtime if not e.startswith(".ddw/"))]
assert not leaked, "runtime files are committed in this repository: %s" % leaked
PYCHK

# ── Plugin capability is the adapter's answer, not a list typed in the script ──
# `PLUGIN_CAPABLE=" claude copilot opencode "` lived in install.sh while that
# file's own header promises the target list is discovered from adapters/. A
# name typed into a script is a second source of truth nothing compares against
# the first — the shape this repository already paid for once, when a check
# named one job by hand and left the other unmeasured for as long as it existed.
python3 - "$SELF" <<'PYCHK' && ok "every adapter declares whether it has a plugin install, and the installer reads it" || bad "plugin capability is hardcoded, or an adapter does not declare it"
import glob, json, os, re, sys
root = sys.argv[1]
recipes = sorted(glob.glob(f"{root}/adapters/*/adapter.json"))
assert recipes, "no adapters found"
for r in recipes:
    d = json.load(open(r, encoding="utf-8"))
    tid = os.path.basename(os.path.dirname(r))
    assert isinstance(d.get("plugin_install"), bool), (
        "adapters/%s/adapter.json does not declare plugin_install" % tid)
src = open(f"{root}/install.sh", encoding="utf-8").read()
m = re.search(r"^PLUGIN_CAPABLE=(.*)$", src, re.M)
assert m, "PLUGIN_CAPABLE is not assigned in install.sh"
assert not re.search(r"[A-Za-z]", m.group(1)), (
    "PLUGIN_CAPABLE is assigned a literal list of tool names: %s" % m.group(1).strip())
assert "plugin_install_of" in src, "install.sh never reads plugin_install out of a recipe"
PYCHK

# ── The pull request the installer offers is the one it opens ────────────
# It asked "open a draft PR?" and `gh pr create` passes no --draft — correctly,
# because the next line it prints is that you have to merge that PR before the
# first ticket, and a draft is one nobody can approve or merge. The word was
# also in docs/INSTALL.md, so a reader could learn the wrong thing twice.
python3 - "$SELF" <<'PYCHK' && ok "the installer does not offer a draft PR it never opens" || bad "the installer says draft while opening a normal pull request"
import re, sys
root = sys.argv[1]
# Comment lines are dropped BEFORE looking. The first version of this check
# read the raw file, and the comment written next to the fix — the one saying
# "passes no --draft" — was the first hit for both needles, so the check
# answered about itself and reported the defect it had just fixed.
src = open(f"{root}/install.sh", encoding="utf-8").read()
code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
create = code.index("gh pr create")
opens_draft = "--draft" in code[create:create + 400]
prompt = re.search(r'printf "  Push %s and open a[^"]*"', src)
assert prompt, "the push/PR prompt was not found"
says_draft = "draft" in prompt.group(0).lower()
assert opens_draft == says_draft, (
    "the prompt says draft=%s but gh pr create passes --draft=%s" % (says_draft, opens_draft))
doc = open(f"{root}/docs/INSTALL.md", encoding="utf-8").read()
setup = doc.index("A new setup branch")
assert opens_draft or "draft PR" not in doc[setup:setup + 700], (
    "docs/INSTALL.md still promises a draft PR for the setup branch")
PYCHK
# ── Did the whole suite actually run? ─────────────────────────────────────────
# The single highest-leverage line in this file. Everything above can be made to
# pass by not running: an absent tool, an unsupported `find`, a loop over an
# empty list. Each of those printed a green N/N with a smaller N, and nobody can
# eyeball a total they never memorised. So the run declares up front how many
# checks it owes, and this is where it settles the account.
section "The suite ran in full"

# A skip used to be summed into the total and then printed as "N/N passed", in
# the file whose own line 40 says a check that did not run is not a check that
# passed. Two plugin manifests had therefore never been validated against the
# real schema in CI, and the run said green. Asked of this file's own source,
# because the alternative is a suite that has to skip something to test it.
python3 - "${BASH_SOURCE[0]}" <<'PYSKIP' && ok "a check that did not run is counted apart and the run does not go green with one" || bad "a skip is summed into the passing total again — the surest way to a green run is to run less"
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
body = re.search(r"^skip\(\)\s*\{(.*)$", src, re.M)
assert body, "the skip helper is gone"
assert "SKIPS=$((SKIPS+1))" in body.group(1), "skip() no longer counts itself as a skip"
verdict = src[src.index("# ── Verdict"):]
assert "SKIPS" in verdict, "the verdict never mentions the checks that did not run"
assert re.search(r"exit \$\(\(.*SKIPS.*\)\)", verdict), \
    "the exit code ignores the skips, so a run that skipped everything exits 0"
PYSKIP
if [ "$EXPECT_CHECKS" -le 0 ]; then
  # Not a pass. An unpinned total is the absence of this check, and printing it
  # green is how a run of 43 of 523 exited 0.
  bad "the check total is not pinned (EXPECT_CHECKS=$EXPECT_CHECKS) — set it to $((CHECKS + 1)) at the top of this file"
elif [ "$CHECKS" -eq "$((EXPECT_CHECKS - 1))" ]; then
  ok "all $EXPECT_CHECKS checks ran"
else
  bad "only $((CHECKS + 1)) of $EXPECT_CHECKS checks ran — something skipped itself and a smaller green total hid it"
fi

# ── Verdict ───────────────────────────────────────────────────────────────────
printf '\n\033[1m%s\033[0m\n' "──────────────────────────────────────────"
if [ "$SKIPS" -gt 0 ]; then
  printf '\033[33m%d of %d checks did not run.\033[0m\n' "$SKIPS" "$CHECKS"
fi
if [ "$FAILS" -eq 0 ] && [ "$SKIPS" -eq 0 ]; then
  printf '\033[32m%d/%d checks passed.\033[0m\n' "$CHECKS" "$CHECKS"
elif [ "$FAILS" -eq 0 ]; then
  printf '\033[31m%d checks passed but %d never ran — that is not a green run.\033[0m\n' \
    "$((CHECKS - SKIPS))" "$SKIPS"
else
  printf '\033[31m%d of %d checks FAILED.\033[0m\n' "$FAILS" "$CHECKS"
fi
exit $(( FAILS > 0 || SKIPS > 0 ))
