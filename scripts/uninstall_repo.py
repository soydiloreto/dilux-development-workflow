#!/usr/bin/env python3
"""Work out what DDW put in this repo, and take exactly that back out.

The hard part of an uninstaller is not deleting things. It is knowing what is
yours. `.claude/` is not DDW's directory — it is Claude Code's, and your own
skills and hooks live there too. Removing it wholesale would be the same defect
the installer spends its whole life avoiding, run in reverse and with no undo.

So this reads `.ddw-installed.json`, which lists every file DDW wrote and what
it looked like. A file still matching its recorded fingerprint is DDW's and goes.
A file that has changed is one you edited, and it stays unless you say otherwise.
Anything not in the manifest was never DDW's and is not touched.

`docs/` is never removed. The PRDs, specs, threat models and verification
reports are the record of what was decided and why — the whole reason they are
committed instead of living in a chat. Uninstalling the tool is not a reason to
lose them.

    uninstall_repo.py --repo . [--plan] [--force]

`--plan` prints what would happen and writes nothing.
"""
import argparse
import hashlib
import json
import os
import shutil

MANIFEST = ".ddw-installed.json"

# The pipeline's runtime. Not in the manifest — it is created as you work, not
# by the installer — and every one of these is DDW's alone.
RUNTIME = (".ddw-state.json", ".ddw-paused", ".ddw-sessions", ".ddw-work",
           ".ddw-journal.jsonl")

# The method itself. Byte-identical in every repo, entirely DDW's.
METHOD = (".ddw",)

CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
BEGIN, END = "<!-- BEGIN DDW", "<!-- END DDW -->"
GI_BEGIN, GI_END = "# BEGIN DDW", "# END DDW"


def fingerprint(path):
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


def strip_block(text, begin, end):
    """Remove one marked block, leaving everything around it exactly as it was."""
    start = text.find(begin)
    if start == -1:
        return text, False
    stop = text.find(end, start)
    if stop == -1:
        return text, False                # unterminated: not ours to guess at
    out = text[:start] + text[stop + len(end):]
    # The blank line that separated the block from what came before it.
    return out.replace("\n\n\n", "\n\n"), True


def resolve(key, self_dir):
    """Turn a manifest key into a path relative to the repo.

    The manifest speaks two dialects, because the installer writes them from two
    places. Wiring is recorded whole — `claude:.claude/hooks/enforce.sh`. Skills
    and agents are recorded relative to the adapter's own directory —
    `claude:skills/ddw-commit` — because that is what the recipe declares, and
    where it actually lands depends on the recipe's `skills.dir`.

    Reading only the first dialect is not a crash: those paths simply do not
    exist at the repo root, so they are skipped, and an uninstall reports the
    seven hooks it removed while leaving sixteen skills and five agents behind.
    """
    target, _, rel = key.partition(":")
    if not rel:
        return key
    kind, _, name = rel.partition("/")
    # `commands` is the third dialect and was the one left out: every generated
    # slash command stayed behind, and on OpenCode — whose whole surface is
    # commands plus one plugin file — that is most of the install. Manifests
    # written from this version on are already repo-relative, so `kind` is a
    # dotted directory and this translation is skipped; the branch remains for
    # the manifests older installs left on disk.
    if kind not in ("skills", "agents", "commands") or not name:
        return rel
    recipe_path = os.path.join(self_dir, "adapters", target, "adapter.json")
    try:
        recipe = json.load(open(recipe_path, encoding="utf-8"))
        base = recipe[kind]["dir"]
    except (OSError, ValueError, KeyError):
        return rel
    return os.path.join(base, name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--self", required=True,
                    help="the DDW repo, for the adapter recipes the manifest keys refer to")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="also remove DDW files you have edited since installing")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    act = not args.plan

    removed, kept, blocks, outside = [], [], [], []

    manifest = {}
    mpath = os.path.join(repo, MANIFEST)
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError, RecursionError):
            # RecursionError is neither of the other two, and a manifest nested
            # deep enough to raise it is a file that arrives with a clone.
            manifest = {}
        # A manifest arrives with the clone and may be anything. A list where a
        # mapping was expected raised on `.items()` and the uninstaller could not
        # run at all — on a repo whose whole problem is that DDW is in a state
        # nobody wants.
        if not isinstance(manifest, dict):
            manifest = {}

    if not manifest:
        print("  ! No .ddw-installed.json here. Only the method and the runtime can be")
        print("    removed with confidence — each tool's wiring is identified by that file,")
        print("    and without it there is no way to tell DDW's hooks from yours.")

    # 1. The wiring, one entry at a time, verified against what was installed.
    for key, recorded in sorted(manifest.items()):
        rel = resolve(key, os.path.abspath(args.self))
        path = os.path.join(repo, rel)
        # The manifest is COMMITTED, so it arrives with the clone — from whoever
        # wrote it. A key of `../../.ssh` or `/etc` names a path outside this
        # repository, and the loop below removes what the key names. Nothing
        # DDW installs is outside the repo, so anything that resolves outside it
        # is refused and reported rather than acted on.
        #
        # Inside the repo is not enough. `claude:.` resolves to the repository
        # ITSELF, which passed the containment check and was then handed to
        # `shutil.rmtree` — the working tree, `.git` and every file the user has
        # ever written, removed by an uninstaller, from a file that arrives with
        # the clone. `.git` is the same defect one directory down. DDW installs
        # neither, so neither is DDW's to remove.
        real = os.path.realpath(path)
        repo_real = os.path.realpath(repo)
        git_dir = os.path.join(repo_real, ".git")
        if (real == repo_real
                or os.path.commonpath([real, repo_real]) != repo_real
                or real == git_dir
                or real.startswith(git_dir + os.sep)):
            outside.append(rel)
            continue
        if not os.path.exists(path):
            continue
        if fingerprint(path) != recorded and not args.force:
            kept.append(rel)
            continue
        if act:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        removed.append(rel)

    # 2. The method and the runtime.
    for rel in METHOD + RUNTIME:
        path = os.path.join(repo, rel)
        if not os.path.exists(path):
            continue
        if act:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        removed.append(rel)

    # 2b. Un-merge the hooks from each tool's settings file.
    #
    # The installer MERGES into these: they may already be yours, with your own
    # hooks in them, so it appends its blocks rather than owning the file. The
    # reverse has to be just as careful — and skipping it is not a tidiness
    # problem. The settings would go on wiring hook scripts that no longer
    # exist, and every session in the repo would fail on a command not found,
    # with DDW uninstalled and nothing left to explain why.
    #
    # A block is DDW's when it is byte-for-byte one the installer would add,
    # compared the same way the installer compares. Anything else is yours.
    for target in sorted({k.split(":", 1)[0] for k in manifest if ":" in k}):
        recipe_path = os.path.join(os.path.abspath(args.self), "adapters", target,
                                   "adapter.json")
        try:
            recipe = json.load(open(recipe_path, encoding="utf-8"))
            sm = recipe["settings_merge"]
            ours = json.load(open(os.path.join(os.path.dirname(recipe_path), sm["from"]),
                                  encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            continue
        dst_path = os.path.join(repo, sm["to"])
        if not os.path.exists(dst_path):
            continue
        # The user's file, in whatever shape it arrives. A list, a string, a
        # `hooks` that is not a mapping, a nesting deep enough for the parser to
        # give up: every one of those came out as an AttributeError or a
        # TypeError from the loop below, and this is the script you reach for
        # when DDW is in a state you do not want — a traceback here means the
        # repo cannot be uninstalled at all. Nothing of DDW's is in a file shaped
        # like that, so there is nothing here to remove.
        try:
            with open(dst_path, encoding="utf-8") as fh:
                dst = json.load(fh)
        except (OSError, ValueError, RecursionError):
            continue
        if not isinstance(dst, dict):
            continue
        key = sm["merge_key"]
        if not isinstance(dst.get(key), dict):
            continue
        mine = {event: {json.dumps(b, sort_keys=True) for b in blocks}
                for event, blocks in ours.get(key, {}).items()}
        changed = False
        for event in list(dst.get(key, {})):
            # A `PreToolUse` that is a string is not a list of blocks, and
            # iterating it removed nothing while rewriting the user's file as
            # one character per element — an uninstall that exits 0, says
            # "Done." and corrupts the settings it was asked to clean.
            if not isinstance(dst[key][event], list):
                continue
            keep = [b for b in dst[key][event]
                    if json.dumps(b, sort_keys=True) not in mine.get(event, ())]
            if len(keep) != len(dst[key][event]):
                changed = True
            if keep:
                dst[key][event] = keep
            else:
                del dst[key][event]
        if not changed:
            continue
        # Nothing of yours left in it: the base keys a recipe seeds (Cursor's
        # schema `version`) are DDW's doing too, so a file holding only those is
        # a file DDW created.
        leftovers = {k: v for k, v in dst.items()
                     if k != key and k not in (sm.get("base") or {})}
        if not dst.get(key) and not leftovers:
            removed.append(sm["to"])
            if act:
                os.remove(dst_path)
        else:
            blocks.append(sm["to"])
            if act:
                with open(dst_path, "w", encoding="utf-8") as fh:
                    json.dump(dst, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")

    # 3. The activation block, out of whatever carries it. The file itself stays:
    #    everything outside the markers is the user's, always was.
    for name in CONTEXT_FILES:
        path = os.path.join(repo, name)
        if not os.path.exists(path):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            # Not decodable, therefore not rewritable: replacing the bytes we
            # could not read is how a user loses the file we were only supposed
            # to take one block out of. If the marker is in there, it stays, and
            # the summary below is what says so.
            kept.append(name + " (not UTF-8: the DDW block, if any, was left in place)")
            continue
        out, found = strip_block(text, BEGIN, END)
        if not found:
            continue
        # A file left with nothing but whitespace held only DDW's pointer — it
        # did not exist before the install, so leaving an empty husk behind is
        # litter. AGENTS.md is never removed: it is the project's context file
        # whether or not DDW created the first draft of it.
        #
        # Decided the same way in both modes. Working this out only when acting
        # made the plan a different answer from the run — it promised to clear a
        # block from CLAUDE.md and then deleted the file — and a plan you cannot
        # trust is worse than no plan, because you read it and approved.
        if not out.strip() and name != "AGENTS.md":
            removed.append(name)
            if act:
                os.remove(path)
        else:
            blocks.append(name)
            if act:
                open(path, "w", encoding="utf-8").write(out)

    # 4. The .gitignore rules for the runtime.
    gi = os.path.join(repo, ".gitignore")
    if os.path.exists(gi):
        text = open(gi, encoding="utf-8").read()
        out, found = strip_block(text, GI_BEGIN, GI_END)
        if found:
            # The same rule the context files already follow: a file that held
            # nothing but DDW's block is removed rather than left as an empty
            # husk. Installing into a repo with no .gitignore used to create one
            # and uninstalling used to leave it behind, so the repo ended up
            # carrying a file it never had and nobody wrote.
            if not out.strip():
                removed.append(".gitignore")
                if act:
                    os.remove(gi)
            else:
                blocks.append(".gitignore")
                if act:
                    open(gi, "w", encoding="utf-8").write(out)

    # 5. The manifest last: until now it was the record of what to remove.
    #
    # …and NOT AT ALL when files were kept. The manifest is the only thing that
    # can tell DDW's hook from yours, so deleting it while the run is still
    # printing "re-run with --force to remove them" makes that advice
    # unactionable: the second run has nothing left to identify them by, prints
    # "no .ddw-installed.json here", and the files stay forever. Measured.
    if os.path.exists(mpath) and not kept:
        if act:
            os.remove(mpath)
        removed.append(MANIFEST)

    # 6. Directories the wiring left empty. `.claude/` with your own skills still
    #    in it is not empty, and stays.
    if act:
        for rel in sorted({os.path.dirname(r) for r in removed if os.sep in r or "/" in r},
                          key=len, reverse=True):
            d = os.path.join(repo, rel)
            while d.startswith(repo + os.sep) and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)

    verb = "Would remove" if args.plan else "Removed"
    print(f"\n  {verb} {len(removed)} path(s):")
    for r in sorted(removed):
        print(f"      {r}")
    if blocks:
        v = "Would clear" if args.plan else "Cleared"
        print(f"\n  {v} the DDW block from {len(blocks)} file(s), leaving the rest:")
        for b in sorted(blocks):
            print(f"      {b}")
    if outside:
        print(f"\n  ⚠ REFUSED {len(outside)} manifest entr(ies): a path outside this repo, the")
        print("    repository root itself, or something under .git. DDW installs none of the")
        print("    three, so this manifest was not written by an install here. Nothing was")
        print("    removed for them:")
        for o in sorted(outside):
            print(f"      {o}")
    if kept:
        print(f"\n  ⚠ Kept {len(kept)} file(s) that no longer match what DDW installed —")
        print("    you edited them, so they are yours now. Re-run with --force to remove them:")
        for k in sorted(kept):
            print(f"      {k}")
        print(f"    ({MANIFEST} was kept too — it is what identifies those files. "
              "The --force run removes both.)")
    print("\n  docs/ was not touched. The PRDs, specs and reports are the record of what")
    print("  was decided; uninstalling the tool is not a reason to lose them.")


if __name__ == "__main__":
    main()
