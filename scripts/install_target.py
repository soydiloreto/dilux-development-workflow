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
    had_manifest = bool(manifest)
    print(f"  ── wiring: {recipe.get('label', args.id)}")

    # 1. Skills — ONE source (skills), copied into this tool's own location.
    if "skills" in recipe:
        src = os.path.join(args.self, "skills")
        dst = os.path.join(args.target, recipe["skills"]["dir"])
        landed = copy_tree_no_clobber(src, dst, recipe["skills"]["dir"], collisions,
                                      manifest, f"{args.id}:skills")
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
            rel = f"{args.id}:agents/{out_name}"
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
            rel = f"{args.id}:commands/{out_name}"
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
        dst = {}
        if os.path.exists(dst_path):
            try:
                dst = json.load(open(dst_path, encoding="utf-8"))
            except ValueError:
                side = os.path.join(os.path.dirname(dst_path), "ddw-settings.json")
                json.dump(src, open(side, "w", encoding="utf-8"), indent=2)
                print(f"  ! {sm['to']} is not valid JSON; wrote ddw-settings.json alongside it")
                dst = None
        if dst is not None:
            for k, v in (sm.get("base") or {}).items():
                dst.setdefault(k, v)
            key = sm["merge_key"]
            dst.setdefault(key, {})
            for event, blocks in src[key].items():
                cur = dst[key].setdefault(event, [])
                seen = [json.dumps(b, sort_keys=True) for b in cur]
                for blk in blocks:
                    if json.dumps(blk, sort_keys=True) not in seen:
                        cur.append(blk)
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
        existing = open(ctx, encoding="utf-8").read() if os.path.exists(ctx) else ""
        if "BEGIN DDW" in existing:
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
