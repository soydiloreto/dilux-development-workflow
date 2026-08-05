#!/usr/bin/env python3
"""Install DDW's wiring for one target, from that target's adapter recipe.

This engine knows nothing about Claude, OpenCode or Copilot. It reads
`adapters/<id>/adapter.json` and applies it. Supporting a new tool means adding
a directory with a recipe (and whatever hook scripts that tool needs) — no
change to this file.

What a recipe declares:

  skills.dir        where the tool looks for skills. The skills themselves live
                    once in skills/ and are copied there.
  agents.dir        where the tool looks for subagents.
  agents.filename   the tool's filename convention, e.g. "{name}.agent.md".
  agents.frontmatter  the tool's frontmatter dialect. Values are templates over
                    the neutral fields declared in agents/*.md
                    ({name}, {description}, {tools}).
  agents.when_readonly  extra frontmatter merged in for agents with writes:false
                    (tools that express permissions rather than a tool list).
  agents.format     "yaml" (default) or "toml" — Codex defines subagents as TOML
                    files, not markdown with frontmatter.
  commands.dir      where the tool looks for slash commands, for tools that do
                    NOT expose skills as `/name` on their own. One thin command
                    is generated per skill so the entry point is the same
                    sentence on every tool.
  skills_are_slash  true when the tool already exposes each skill as `/name`
                    (Claude Code does). Declaring neither means DDW's skills
                    exist but there is no `/ddw-status` — which the installer
                    now says out loud instead of printing one closing line that
                    promised slash commands everywhere.
  wiring[]          directories to copy verbatim: that tool's hook scripts.
  settings_merge    a JSON file to merge a key into, instead of overwrite.
  settings_merge.base  top-level keys to seed when creating that file (Cursor's
                    hooks.json carries a schema "version" beside the hooks).
  context_file      the file the activation snippet is appended to.

Never overwrites a skill or agent the user already has: on a name collision with
different content it reports and leaves theirs alone.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys

NEUTRAL_FIELDS = ("name", "description", "tools")
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")


def _wrap(text, width):
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def die(msg):
    print(f"DDW install: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_agent(path):
    """Split a agents/*.md into (neutral fields dict, body)."""
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        die(f"{path} has no frontmatter")
    fm, body = m.group(1), text[m.end():]
    fields = {}
    for line in fm.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            # Unwrap a quoted scalar. The source frontmatter has to be valid YAML,
            # so a description containing ": " is quoted there — and keeping the
            # quotes meant the emitter quoted them again, and the model read a
            # description that begins and ends with a literal quote character.
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                try:
                    v = json.loads(v) if v[0] == '"' else v[1:-1]
                except ValueError:
                    v = v[1:-1]
            fields[k.strip()] = v
    missing = [f for f in NEUTRAL_FIELDS if f not in fields]
    if missing:
        die(f"{path} is missing neutral field(s): {', '.join(missing)}")
    # Whether the agent may write is derived from its tool list, not declared
    # separately. That keeps this file valid Claude frontmatter as it stands, so
    # plugin mode can point straight at agents/ with no build step.
    fields["writes"] = any(t in fields["tools"] for t in WRITE_TOOLS)
    return fields, body


def parse_skill(path):
    """Read (name, description) out of a skills/*/SKILL.md.

    Deliberately narrow: it handles `key: value` and YAML's folded `key: >`
    block, which is every form the skills actually use. A skill that grows a
    frontmatter shape this cannot read raises rather than yielding a command
    with an empty description — a `/ddw-status` the TUI lists with no text
    beside it is worse than the missing command it replaced.
    """
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        die(f"{path} has no frontmatter")
    fields, key = {}, None
    for line in m.group(1).splitlines():
        if re.match(r"^\S", line) and ":" in line:
            key, v = line.split(":", 1)
            key, v = key.strip(), v.strip()
            fields[key] = "" if v in (">", "|", ">-", "|-") else v
        elif key and line.strip():
            fields[key] = (fields[key] + " " + line.strip()).strip()
    for f in ("name", "description"):
        if not fields.get(f):
            die(f"{path} has no usable '{f}' in its frontmatter")
    return fields["name"], fields["description"]


def command_description(description, limit=140):
    """The one line a TUI shows beside the command name.

    The skills' descriptions are written for a model deciding whether to load
    one, so they carry a trailing `Trigger: …` clause that means nothing to a
    human reading a command list. It is dropped, and what is left is cut at a
    sentence boundary rather than mid-word.
    """
    text = re.split(r"\bTrigger:", description)[0].strip().rstrip(".")
    if len(text) > limit:
        cut = text[:limit]
        text = cut[:cut.rfind(" ")] if " " in cut else cut
        text = text.rstrip(",;:") + "…"
    return text


def render(template, fields):
    """Substitute {name}/{description}/{tools} in a recipe template value."""
    out = template
    for k in ("name", "description", "tools"):
        out = out.replace("{" + k + "}", fields.get(k, ""))
    return out


TOML_FENCE = '"' * 3


def toml_agent(fm, body):
    """Codex wants one TOML file per subagent, not markdown with frontmatter.

    The prompt goes into `developer_instructions` as a multi-line basic string.
    Escaping matters: a stray triple quote inside a prompt would close the
    literal early and leave a file that parses as something else entirely.
    """
    lines = []
    for k, v in fm.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"')
    safe = body.replace("\\", "\\\\").replace(TOML_FENCE, '\\"\\"\\"')
    lines.append("developer_instructions = " + TOML_FENCE)
    lines.append(safe.rstrip())
    lines.append(TOML_FENCE)
    return "\n".join(lines) + "\n"


def _yaml_scalar(v):
    """Quote a value so the result is always parseable YAML.

    Emitting values raw was fine until a description contained ": " — a plain
    YAML scalar cannot, so the frontmatter stopped parsing and the tool dropped
    the agent. It failed in every dialect at once, because they all come through
    here. JSON's string syntax is a subset of YAML's double-quoted style, so
    json.dumps produces something both parsers agree on.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def _public(mapping):
    """Recipe keys starting with `_` are notes for whoever reads the recipe.
    They are not frontmatter, and they were being emitted into every agent."""
    return {k: v for k, v in mapping.items() if not str(k).startswith("_")}


def yaml_block(mapping, indent=0):
    """Emit the recipe's frontmatter mapping as YAML. Values are scalars, lists,
    or one level of nesting, which is all any adapter dialect needs so far."""
    pad = " " * indent
    lines = []
    for k, v in _public(mapping).items():
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.extend(yaml_block(v, indent + 2))
        else:
            lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
    return lines


def _fingerprint(path):
    """A stable hash of a file, or of a directory's whole content."""
    h = hashlib.sha256()
    if os.path.isfile(path):
        h.update(open(path, "rb").read())
        return h.hexdigest()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            h.update(os.path.relpath(p, path).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


# The record of what was installed here, and what it looked like. It belongs at
# the repo root, NOT under .ddw/: `.ddw/` is the method, and the method is
# byte-identical in every repo and for every tool. This file is the opposite —
# it lists the wiring of the tools THIS repo happens to install, so keeping it
# inside .ddw/ made that directory differ between two installs of the same
# version. It is committed (unlike .ddw-state.json): a teammate who clones needs
# it, or their first upgrade reads every DDW file as one of their own.
MANIFEST = ".ddw-installed.json"
LEGACY_MANIFEST = os.path.join(".ddw", ".installed.json")


def load_manifest(repo):
    """What DDW installed here last time, and what it looked like.

    Without this the installer could not tell "DDW's own file, from an older
    version" from "a file of yours that happens to share a name" — so it treated
    every difference as yours, refused to touch it, and an upgrade silently left
    the repo running a mix of two versions while reporting a collision that was
    never the user's doing.
    """
    for rel in (MANIFEST, LEGACY_MANIFEST):
        try:
            with open(os.path.join(repo, rel), encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            continue
    return {}


METHOD_DIR = ".ddw"


def record_method(repo, manifest):
    """Fingerprint the method tree into the manifest, file by file.

    A clean install wrote 28 entries and not one of them was under `.ddw/` — so
    the drift check, which is the whole detection half of "prevention where a
    path is visible, detection where it is not", could not see a shell rewriting
    `transition-graph.json`, `validate-transition.py` or `hook-gate.py`.
    Measured: tampering with all three reported nothing, while the same byte in
    `.claude/hooks/enforce.sh` reported CHANGED. The graph is the file that
    decides which gates exist; it was the least watched thing in the repository.

    Three separate comments — `session-boot.py`, `validate-transition.py`,
    `verify_install.sh` — named exactly this shell vector as the one the manifest
    covers. It did not.

    Recorded per FILE rather than as one directory hash: importing the validator
    creates `.ddw/scripts/__pycache__`, and a directory fingerprint would take
    that in and report drift on every install that had ever run. The `method:`
    prefix keeps these apart from a tool's wiring, and `enforcement_drift`
    already splits any `prefix:path` key, so nothing downstream changes.
    """
    root = os.path.join(repo, METHOD_DIR)
    if not os.path.isdir(root):
        return
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, repo).replace(os.sep, "/")
            manifest["method:" + rel] = _fingerprint(path)


def save_manifest(repo, manifest):
    try:
        with open(os.path.join(repo, MANIFEST), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError:
        return
    # Installs made before the move left one inside .ddw/. Drop it once it has
    # been read, or `.ddw/` keeps differing between repos forever.
    try:
        os.remove(os.path.join(repo, LEGACY_MANIFEST))
    except OSError:
        pass


WIRING_PREFIXES = ("hooks", "plugin", "scripts")


def claim(rel, src_path, dst_path, manifest, collisions, label, ours_if_unknown=False):
    """Decide what to do with one file DDW wants to install.

    Returns True when the caller should write it. Three cases, and the middle
    one is the whole reason this exists:

      - nothing there                      → write it
      - there, and it is DDW's own older copy → write it (this is an upgrade)
      - there, and it is not ours          → leave it alone and report
    """
    if not os.path.exists(dst_path):
        return True
    if _same(src_path, dst_path):
        manifest[rel] = _fingerprint(dst_path)
        return False                      # already current; nothing to do
    if manifest.get(rel) == _fingerprint(dst_path):
        return True                       # ours, untouched, superseded
    if ours_if_unknown:
        # Only when DDW was already installed here. Versions before the wiring
        # went through claim() copied it without recording anything, so on the
        # first upgrade every hook looked like a file of the user's: left alone,
        # reported as theirs, and the repo ran a new method against old
        # enforcement scripts.
        #
        # The condition matters as much as the rule. On a FIRST install there is
        # no manifest, and a file already sitting where DDW wants to write is
        # the user's — that is how a pre-existing session-start.sh survives.
        # Applied unconditionally, this would eat it.
        return True
    collisions.append(f"{label}/{os.path.basename(rel)}")
    return False


def _names_installed_file(block, manifest, tool):
    """Does this settings block run a file the manifest says DDW installed?

    The question both the installer and the uninstaller need, and neither had:
    "is this block ours?" was answered by comparing it against what the CURRENT
    version ships, so a block wired by an older one belonged to nobody. It was
    left behind on upgrade and left behind on uninstall, still naming a script
    that had been removed.

    The manifest is the record of what DDW put on disk, so a block naming one of
    those paths is DDW's. A block of the user's that happens to sit in the same
    file names a script of theirs, which is not in the manifest.
    """
    text = json.dumps(block, sort_keys=True)
    for k in manifest:
        if not isinstance(k, str) or not k.startswith(tool + ":"):
            continue
        rel = k.split(":", 1)[1]
        if rel and rel in text:
            return True
    return False


def copy_tree_no_clobber(src, dst, label, collisions, manifest, key):
    """Copy each entry of src into dst, upgrading DDW's own files and never
    touching one the user has made theirs."""
    if not os.path.isdir(src):
        return 0
    os.makedirs(dst, exist_ok=True)
    landed = 0
    for name in sorted(os.listdir(src)):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        rel = f"{key}/{name}"
        if claim(rel, s, d, manifest, collisions, label):
            if os.path.exists(d):
                shutil.rmtree(d) if os.path.isdir(d) else os.remove(d)
            (shutil.copytree if os.path.isdir(s) else shutil.copy2)(s, d)
            manifest[rel] = _fingerprint(d)
            landed += 1
        elif os.path.exists(d) and _same(s, d):
            landed += 1
    return landed


def _relfiles(root):
    out = set()
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            out.add(os.path.relpath(os.path.join(dirpath, f), root))
    return out


def _same(a, b):
    """Byte-identical, in BOTH directions.

    Walking a -> b only leaves a file that exists solely on the b side
    invisible: a skill directory the user has dropped a note into reads as
    "already current", gets fingerprinted into the manifest with their file
    counted as ours, and the next upgrade removes the directory whole.
    """
    if os.path.isdir(a) != os.path.isdir(b):
        return False
    if os.path.isfile(a):
        return open(a, "rb").read() == open(b, "rb").read()
    if _relfiles(a) != _relfiles(b):
        return False
    for rel in _relfiles(a):
        pa, pb = os.path.join(a, rel), os.path.join(b, rel)
        if open(pa, "rb").read() != open(pb, "rb").read():
            return False
    return True


def chmod_x(path):
    for root, _, files in os.walk(path):
        for f in files:
            if f.endswith(".sh"):
                p = os.path.join(root, f)
                os.chmod(p, os.stat(p).st_mode | 0o111)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self", required=True, help="the DDW repo root")
    ap.add_argument("--target", required=True, help="the repo being installed into")
    ap.add_argument("--id", required=True, help="the adapter id (a directory under adapters/)")
    args = ap.parse_args()

    adapter_dir = os.path.join(args.self, "adapters", args.id)
    recipe_path = os.path.join(adapter_dir, "adapter.json")
    if not os.path.isfile(recipe_path):
        die(f"unknown target '{args.id}' — no adapters/{args.id}/adapter.json")
    recipe = json.load(open(recipe_path, encoding="utf-8"))

    collisions = []
    manifest = load_manifest(args.target)
    # Whether DDW had ever been installed here, decided before this run
    # starts adding to it. It is what separates an upgrade from a first
    # install, and therefore DDW's own older file from one of the user's.
    # …for THIS tool. Asked of the whole manifest, installing a second tool into
    # a repo that already had DDW answered "upgrade" for a target that had never
    # been installed — so `ours_if_unknown` fired on files DDW had never written,
    # and the user's own `.codex/hooks/session-start.sh`, `enforce.sh`,
    # `pre-compact.sh` (exactly the names a user of that agent already has) were
    # overwritten with no backup, no warning and exit 0. The installer's central
    # promise is that it never overwrites a file it did not put there.
    #
    # And it is asked about the WIRING, not about the tool. `ours_if_unknown`
    # exists for one situation and one only: manifests written before the wiring
    # went through `claim()`, which recorded skills and agents and nothing else,
    # so on the first upgrade every hook looked like a file of the user's. That
    # is a manifest with entries for this tool and NONE of them wiring. Asked as
    # "has this tool ever been installed", it stayed true forever — so the day a
    # new version starts shipping a file at a path the user already has one at,
    # the upgrade overwrote it with no backup, no ⚠ and exit 0. Measured: a
    # `.claude/hooks/audit.sh` of the user's, replaced by DDW's on the second
    # run. A file DDW never recorded is the user's, on every run after the
    # first as much as on it.
    wiring_dirs = [w["to"].rstrip("/") + "/" for w in recipe.get("wiring", [])]
    recorded_wiring = any(
        isinstance(k, str) and k.startswith(args.id + ":")
        and any(k.split(":", 1)[1].startswith(d) for d in wiring_dirs)
        for k in manifest)
    had_manifest = (any(isinstance(k, str) and k.startswith(args.id + ":") for k in manifest)
                    and not recorded_wiring)
    print(f"  ── wiring: {recipe.get('label', args.id)}")

    # 1. Skills — ONE source (skills), copied into this tool's own location.
    if "skills" in recipe:
        src = os.path.join(args.self, "skills")
        dst = os.path.join(args.target, recipe["skills"]["dir"])
        landed = copy_tree_no_clobber(src, dst, recipe["skills"]["dir"], collisions,
                                      manifest, f"{args.id}:{recipe['skills']['dir']}")
        # Report what LANDED, not what was on offer: printing the source count on
        # a run that skipped one is how a half-installed method looks complete.
        print(f"  ✓ {recipe['skills']['dir']:<22} {landed} skills")

    # 2. Agents — ONE source (agents), transpiled into this tool's dialect.
    if "agents" in recipe:
        spec = recipe["agents"]
        dst_dir = os.path.join(args.target, spec["dir"])
        os.makedirs(dst_dir, exist_ok=True)
        src_dir = os.path.join(args.self, "agents")
        count = 0
        for fname in sorted(os.listdir(src_dir)):
            if not fname.endswith(".md"):
                continue
            fields, body = parse_agent(os.path.join(src_dir, fname))
            fm = {k: render(v, fields) if isinstance(v, str) else v
                  for k, v in spec["frontmatter"].items()}
            if not fields["writes"] and "when_readonly" in spec:
                fm.update(spec["when_readonly"])
            out_name = spec.get("filename", "{name}.md").replace("{name}", fields["name"])
            out_path = os.path.join(dst_dir, out_name)
            if spec.get("format") == "toml":
                rendered = toml_agent(fm, body)
            else:
                rendered = "---\n" + "\n".join(yaml_block(fm)) + "\n---\n" + body
            rel = f"{args.id}:{spec['dir']}/{out_name}"
            if os.path.exists(out_path):
                current = open(out_path, encoding="utf-8").read()
                if current == rendered:
                    manifest[rel] = hashlib.sha256(current.encode()).hexdigest()
                    count += 1
                    continue
                if manifest.get(rel) != hashlib.sha256(current.encode()).hexdigest():
                    collisions.append(f"{spec['dir']}/{out_name}")
                    continue
            open(out_path, "w", encoding="utf-8").write(rendered)
            manifest[rel] = hashlib.sha256(rendered.encode()).hexdigest()
            count += 1
        print(f"  ✓ {spec['dir']:<22} {count} agents (transpiled)")

    # 3. Commands — a `/name` for each skill, on the tools that need one.
    #
    #    Claude Code exposes every skill as a slash command by itself, so DDW
    #    never had to think about this — and the installer's closing line said
    #    "Commands: /ddw-status, /ddw-self-check, /ddw-help" to all six targets.
    #    On OpenCode that line is false: skills are discovered and loaded by the
    #    model, but `/ddw-status` is a different feature living in a different
    #    directory, and typing it returns "command not found". The first user to
    #    follow DDW's own last line of output on OpenCode hit exactly that.
    #
    #    So the entry point is made to exist rather than the promise withdrawn:
    #    one generated command per skill, whose whole body is "use this skill".
    #    The skill stays the single source of the behaviour; the command is an
    #    entry point to it, which is precisely what Claude's is too.
    cmd = recipe.get("commands")
    if cmd:
        dst_dir = os.path.join(args.target, cmd["dir"])
        os.makedirs(dst_dir, exist_ok=True)
        src_dir = os.path.join(args.self, "skills")
        made, names = 0, []
        for sname in sorted(os.listdir(src_dir)):
            skill_md = os.path.join(src_dir, sname, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue
            name, description = parse_skill(skill_md)
            fm = {k: render(v, {"name": name,
                                "description": command_description(description)})
                  for k, v in cmd.get("frontmatter", {}).items()}
            body = render(cmd["body"], {"name": name, "description": description})
            rendered = "---\n" + "\n".join(yaml_block(fm)) + "\n---\n" + body.rstrip() + "\n"
            out_name = cmd.get("filename", "{name}.md").replace("{name}", name)
            out_path = os.path.join(dst_dir, out_name)
            rel = f"{args.id}:{cmd['dir']}/{out_name}"
            if os.path.exists(out_path):
                current = open(out_path, encoding="utf-8").read()
                if current == rendered:
                    manifest[rel] = hashlib.sha256(current.encode()).hexdigest()
                    made += 1
                    names.append(name)
                    continue
                if manifest.get(rel) != hashlib.sha256(current.encode()).hexdigest():
                    collisions.append(f"{cmd['dir']}/{out_name}")
                    continue
            open(out_path, "w", encoding="utf-8").write(rendered)
            manifest[rel] = hashlib.sha256(rendered.encode()).hexdigest()
            made += 1
            names.append(name)
        print(f"  ✓ {cmd['dir']:<22} {made} commands (/{', /'.join(names[:3])}, …)")

    # 3. Wiring — this tool's hook scripts, copied verbatim.
    for w in recipe.get("wiring", []):
        src = os.path.join(adapter_dir, w["from"])
        dst = os.path.join(args.target, w["to"])
        if not os.path.isdir(src):
            die(f"adapters/{args.id}/{w['from']} does not exist (declared in the recipe)")
        os.makedirs(dst, exist_ok=True)
        # Skills and agents got the whole protection machinery; the wiring got a
        # bare copy2. So a first install silently destroyed a pre-existing
        # session-start.sh, enforce.sh or lib/guard.sh — exactly the names a
        # Claude Code user already has — while the same run printed a ⚠ saying
        # it had respected a skill of theirs. No backup, no report, exit 0.
        for wroot, _wdirs, wfiles in os.walk(src):
            for name in sorted(wfiles):
                sp = os.path.join(wroot, name)
                rel_in = os.path.relpath(sp, src)
                dp = os.path.join(dst, rel_in)
                key = f"{args.id}:{w['to']}/{rel_in}"
                os.makedirs(os.path.dirname(dp), exist_ok=True)
                if claim(key, sp, dp, manifest, collisions, w["to"],
                         ours_if_unknown=had_manifest):
                    shutil.copy2(sp, dp)
                    manifest[key] = _fingerprint(dp)
        if w.get("chmod") == "+x":
            chmod_x(dst)
        print(f"  ✓ {w['to']:<22} enforcement")

    # 4. settings_merge — merge one key instead of overwriting the user's file.
    sm = recipe.get("settings_merge")
    if sm:
        src = json.load(open(os.path.join(adapter_dir, sm["from"]), encoding="utf-8"))
        dst_path = os.path.join(args.target, sm["to"])

        def _sidecar(reason):
            """The file is the user's, and it is not one we can merge into.

            The same answer the unparseable case already had, for every other way
            a settings file can be shaped unexpectedly: `{"hooks": null}`,
            `{"hooks": {"PreToolUse": {…}}}` (a mapping where the tool's own
            schema says list), a top-level array. Each of those reached
            `cur.append(blk)` and came out as an AttributeError mid-install —
            with `.claude/` and `.ddw/` already on disk, no manifest written, and
            no hooks wired. A half-install that says "Traceback" is the one
            outcome an installer owes the user a sentence for instead.
            """
            side = os.path.join(os.path.dirname(dst_path), "ddw-settings.json")
            os.makedirs(os.path.dirname(side), exist_ok=True)
            with open(side, "w", encoding="utf-8") as fh:
                json.dump(src, fh, indent=2)
            print(f"  ! {sm['to']} {reason}; wrote ddw-settings.json alongside it. Merge its "
                  "hooks into your file by hand, or move yours aside and re-run — DDW's hooks "
                  "are NOT wired until you do.")

        dst = {}
        if os.path.exists(dst_path):
            try:
                with open(dst_path, encoding="utf-8") as fh:
                    dst = json.load(fh)
            except (OSError, ValueError, RecursionError) as exc:
                _sidecar("could not be read (%s)" % exc.__class__.__name__)
                dst = None
            else:
                if not isinstance(dst, dict):
                    _sidecar("holds a %s where an object was expected" % type(dst).__name__)
                    dst = None
        if dst is not None:
            for k, v in (sm.get("base") or {}).items():
                dst.setdefault(k, v)
            key = sm["merge_key"]
            dst.setdefault(key, {})
            if not isinstance(dst.get(key), dict):
                _sidecar("has a `%s` that is a %s, not an object" % (key, type(dst[key]).__name__))
                dst = None
        if dst is not None:
            for event, blocks in src[key].items():
                cur = dst[key].setdefault(event, [])
                if not isinstance(cur, list):
                    # One event of theirs is shaped differently. Refusing the
                    # whole file over it would be worse than saying which one.
                    _sidecar("has a `%s.%s` that is a %s, not a list"
                             % (key, event, type(cur).__name__))
                    dst = None
                    break
                # A block DDW wired once and no longer ships is DDW's to take
                # out. The merge was add-only in both directions: rename a hook
                # script between versions and the upgrade left the old block
                # wired beside the new one — two hooks, one of them pointing at
                # a script that is about to stop existing — and the uninstall
                # after it took out only what the CURRENT adapter defines, so
                # the repo came away configured to run a command that had just
                # been deleted. A block is DDW's when it names a file this
                # manifest records as DDW's; anything else is the user's and is
                # left exactly where it is.
                shipped = [json.dumps(b, sort_keys=True) for b in blocks]
                stale = [b for b in cur
                         if json.dumps(b, sort_keys=True) not in shipped
                         and _names_installed_file(b, manifest, args.id)]
                for b in stale:
                    cur.remove(b)
                seen = [json.dumps(b, sort_keys=True) for b in cur]
                for blk in blocks:
                    if json.dumps(blk, sort_keys=True) not in seen:
                        cur.append(blk)
        if dst is not None:
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            with open(dst_path, "w", encoding="utf-8") as fh:
                json.dump(dst, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            print(f"  ✓ {sm['to']:<22} hooks wired")

    # 5. The activation block.
    #
    #    It lives in AGENTS.md, always, whatever tool you installed. That is the
    #    one file every adapter shares, so "where are DDW's instructions?" has
    #    one answer instead of six, and porting the pipeline moves nothing.
    #
    #    Claude and Gemini read CLAUDE.md / GEMINI.md rather than AGENTS.md, so
    #    those get a pointer — two imports, no prose. Claude resolves nested
    #    imports (documented, five deep) and could reach the orchestrator through
    #    AGENTS.md alone; Gemini documents `@file.md` but says nothing about
    #    nesting. So `@.ddw/orchestrator.md` stays in the tool's own file, one
    #    hop from the root, where no tool has to nest to find it. Betting the
    #    orchestrator on undocumented behaviour is how you get a pipeline that
    #    boots on one tool and silently does not on another.
    blocks = [(os.path.join(args.self, "ddw", "activation.snippet.md"), "AGENTS.md")]
    if recipe.get("context_file", "AGENTS.md") != "AGENTS.md":
        blocks.append((os.path.join(adapter_dir, recipe["snippet"]), recipe["context_file"]))

    for snippet_path, ctx_name in blocks:
        ctx = os.path.join(args.target, ctx_name)
        snippet = open(snippet_path, encoding="utf-8").read()
        try:
            existing = open(ctx, encoding="utf-8").read() if os.path.exists(ctx) else ""
        except (OSError, UnicodeDecodeError) as exc:
            # A context file DDW cannot read is a context file DDW must not
            # rewrite: appending to it would mean writing back whatever the
            # replacement characters decoded to, and losing the user's bytes. A
            # Spanish AGENTS.md saved as cp1252 crashed here mid-install, hooks
            # already wired and no manifest written — so the drift detector was
            # off for good in a repo that looked installed.
            print(f"  ! {ctx_name:<22} could not be read as UTF-8 ({exc.__class__.__name__}); "
                  "left untouched. Add the activation block by hand, or save it as UTF-8 and "
                  "re-run the installer.")
            continue
        # The MARKER, not the words. A context file that merely mentions
        # "BEGIN DDW" in prose — a README explaining the block, which is exactly
        # what a project documenting its own setup writes — took this branch and
        # then raised ValueError on the `index` below, mid-install, leaving the
        # repo half-wired.
        if "<!-- BEGIN DDW" in existing:
            # Upgrade it in place. Finding the block and leaving it was silent
            # data rot: the block is what loads the orchestrator, so a version
            # that changes it — a new import, a different entry point — would
            # never reach any repo that already had DDW, and the installer
            # would print a green tick over an install that no longer matched
            # the method it just copied in.
            #
            # Only the span between the markers is replaced. The block says
            # "managed by DDW" on its first line; everything outside it is the
            # user's file and is not read, not moved and not reformatted.
            start = existing.index("<!-- BEGIN DDW")
            end_marker = "<!-- END DDW -->"
            end = existing.find(end_marker)
            if end == -1:
                print(f"  ⚠ {ctx_name:<22} has an unterminated DDW block "
                      "(no END DDW marker) — left alone, fix it by hand")
            elif existing[start:end + len(end_marker)].strip() == snippet.strip():
                print(f"  ✓ {ctx_name:<22} DDW block already current")
            else:
                with open(ctx, "w", encoding="utf-8") as fh:
                    fh.write(existing[:start] + snippet.strip()
                             + existing[end + len(end_marker):])
                print(f"  ✓ {ctx_name:<22} DDW block updated "
                      "(the rest of the file untouched)")
        else:
            with open(ctx, "a", encoding="utf-8") as fh:
                if existing.strip():
                    fh.write("\n")
                fh.write(snippet)
            print(f"  ✓ {ctx_name:<22} activation block appended")

    record_method(args.target, manifest)
    save_manifest(args.target, manifest)

    if collisions:
        print("COLLISIONS:" + ",".join(collisions))

    # The recipe declares what the user still has to do by hand, and until now
    # nothing printed it: the schema's own words are that a recipe silent about
    # this "ships a pipeline that looks installed and enforces nothing". Codex
    # and Gemini quarantine project hooks until you approve them, so on those two
    # the install is complete and the enforcement is not.
    note = recipe.get("trust_note")
    if note:
        print(f"  ⚠ ACTION REQUIRED — {recipe['label']}")
        for line in _wrap(note, 74):
            print(f"      {line}")

    # How you actually invoke DDW on THIS tool, said by the recipe that knows.
    # It replaces install.sh's single closing line, which named `/ddw-status` to
    # every target and was true of exactly one of them.
    if cmd or recipe.get("skills_are_slash"):
        print("  → try: /ddw-status, /ddw-help, /ddw-self-check")
    else:
        print("  → this tool has no /ddw-* commands yet — ask for the skill by "
              'name ("run the ddw-status skill").')


if __name__ == "__main__":
    main()
