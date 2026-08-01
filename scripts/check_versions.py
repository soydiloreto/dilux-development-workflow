#!/usr/bin/env python3
"""Keep every fact this repo states twice honest.

Mostly that means versions, of which there are three kinds, and conflating them
is how they rot:

**The product's.** One number, in `.claude-plugin/plugin.json` and at the top of
the CHANGELOG. It is what someone installs and what the changelog talks about.

**A format's.** `transition-graph.json` carries `format_version` because a
program reads that file and may be handed an old one. The validator refuses a
major it does not know, which is what separates a version from a decoration.

**A rule's.** Each `ddw/rules/*.instructions.md` carries its own. These are the
ones people argue about, and the argument is settled by whether anything checks
them: a number nobody verifies drifts, and this repo shipped `tracker` at 2.0.0
while the product said 1.0.0 — a lie sitting in a file the model reads.

So with `--since <ref>`: a rule file whose content changed and whose version did
not is an error. That is the deal that makes the number mean something, and it
costs a bump on every edit. Without the check the field is worse than absent,
because absent tells you nothing and stale tells you something false.

The licence is the same shape of problem without being a version: one grant in
LICENSE, restated in every manifest, and the restatement is what a registry and
an installer read. So it is checked here, against the file that grants it.

    python3 scripts/check_versions.py [--repo .] [--since origin/main]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
FM_VERSION = re.compile(r"^version:\s*(\S+)\s*$", re.M)

# Every file that states the product's version. The first is the one the
# CHANGELOG is compared against; the rest have to agree with it.
PRODUCT_MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
                     ".cursor-plugin/plugin.json", "gemini-extension.json", "package.json")

# What a user installs. A change under any of these reaches somebody's machine,
# so it owes a version — otherwise two different products answer to one number,
# and the tools that cache by version go on serving the old one.
#
# Deliberately NOT here: scripts/ (the suite and the linters), docs/, README,
# CHANGELOG, .github/. Editing a test does not change what anyone installs, and
# demanding a release for it teaches people that the number means nothing.
SHIPPED = ("ddw/", "adapters/", "skills/", "agents/", "install.sh", "uninstall.sh",
           ".claude-plugin/", ".codex-plugin/", ".cursor-plugin/", "gemini-extension.json",
           "package.json")

FAILURES = []


def bad(where, msg):
    FAILURES.append((where, msg))


def rule_version(path):
    head = open(path, encoding="utf-8").read().split("---", 2)
    if len(head) < 3:
        return None
    m = FM_VERSION.search(head[1])
    return m.group(1) if m else None


def changelog_version(root):
    text = open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8").read()
    m = re.search(r"^##\s*\[([^\]]+)\]", text, re.M)
    return m.group(1) if m else None


def git(root, *args):
    out = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), ".."))
    ap.add_argument("--since", default=None,
                    help="a git ref: also require a version bump on every rule file "
                         "whose content changed since it")
    args = ap.parse_args()
    root = os.path.abspath(args.repo)

    # 1. The product's version — ONE number, in every file that states it.
    #
    # Six wirings, one product: `ddw/` is byte-identical in all of them, so a
    # manifest saying 1.0.5 while another says 1.0.2 would not be describing two
    # versions of anything. It would mean a bug report no longer maps to a commit,
    # and a user on two tools having no way to tell they are running the same
    # thing. Checking only Claude's manifest let the other five drift unwatched.
    plugin = json.load(open(os.path.join(root, ".claude-plugin/plugin.json"), encoding="utf-8"))
    pv, cv = plugin.get("version"), changelog_version(root)
    if not SEMVER.match(pv or ""):
        bad(".claude-plugin/plugin.json", f"version {pv!r} is not semver")
    if pv != cv:
        bad(".claude-plugin/plugin.json",
            f"declares {pv!r} while the CHANGELOG's latest entry is {cv!r} — "
            "one of them is what people will quote back at you")
    for rel in PRODUCT_MANIFESTS[1:]:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        other = json.load(open(path, encoding="utf-8")).get("version")
        if other != pv:
            bad(rel, f"declares version {other!r} while the product is {pv!r} — one product "
                     "shipped six ways is one number, or nobody can say what they are running")

    # 2. The graph's format version, and that the validator knows that major.
    gpath = os.path.join(root, "ddw/rules/transition-graph.json")
    graph = json.load(open(gpath, encoding="utf-8"))
    fv = graph.get("format_version")
    if not fv or not re.match(r"^\d+\.\d+$", str(fv)):
        bad("ddw/rules/transition-graph.json",
            f"format_version {fv!r} is missing or not MAJOR.MINOR")
    else:
        src = open(os.path.join(root, "ddw/scripts/validate-transition.py"),
                   encoding="utf-8").read()
        m = re.search(r"^GRAPH_FORMAT_MAJOR\s*=\s*(\d+)", src, re.M)
        if not m:
            bad("ddw/scripts/validate-transition.py",
                "no GRAPH_FORMAT_MAJOR — nothing refuses a graph of an unknown format")
        elif int(m.group(1)) != int(str(fv).split(".")[0]):
            bad("ddw/rules/transition-graph.json",
                f"format {fv} but the validator reads major {m.group(1)} — it would refuse "
                "the graph shipped beside it")

    # 3. Every rule carries a semver.
    rules = sorted(glob.glob(os.path.join(root, "ddw/rules/*.instructions.md")))
    for path in rules:
        v = rule_version(path)
        rel = os.path.relpath(path, root)
        if v is None:
            bad(rel, "has no `version:` in its frontmatter")
        elif not SEMVER.match(v):
            bad(rel, f"version {v!r} is not semver")

    # 4. Changed rules bumped it. This is the half that makes the rest true.
    if args.since:
        changed = git(root, "diff", "--name-only", f"{args.since}...HEAD")
        if changed is None:
            bad("git", f"cannot diff against {args.since!r} — the bump check did not run")
        else:
            # 4a. A change to what people install owes a version.
            #
            # Without this the number is decoration: a fix ships, the manifests
            # still say 1.0.0, and every tool that caches by version keeps
            # serving the file that had the bug. Measured on a live install —
            # the plugin cache still held a file that had been deleted upstream,
            # because nothing had told the tool anything was different.
            touched = sorted(f for f in changed.split() if f.startswith(SHIPPED))
            if touched:
                before = git(root, "show", f"{args.since}:.claude-plugin/plugin.json")
                old_pv = json.loads(before).get("version") if before else None
                if old_pv is not None and old_pv == pv:
                    bad("the product version",
                        f"{len(touched)} shipped file(s) changed since {args.since} and the "
                        f"version is still {pv} — first: {touched[0]}. Bump it in all "
                        f"{len(PRODUCT_MANIFESTS)} manifests and open the CHANGELOG entry, "
                        "or this ships as a version that already means something else")

            for rel in changed.split():
                if not re.match(r"^ddw/rules/.*\.instructions\.md$", rel):
                    continue
                before = git(root, "show", f"{args.since}:{rel}")
                if before is None:
                    continue                     # new file: nothing to bump from
                m = FM_VERSION.search(before.split("---", 2)[1] if "---" in before else "")
                now = rule_version(os.path.join(root, rel))
                if m and m.group(1) == now:
                    bad(rel, f"changed since {args.since} and its version is still {now} — "
                             "bump it, or the number stops describing the file")

    # 5. The licence, wherever it is restated.
    #
    # LICENSE is the grant; every other mention is a copy, and a copy that
    # disagrees is the one a machine reads. package.json is what a registry
    # publishes and what OpenCode installs through, so "UNLICENSED" there says
    # the opposite of the file beside it to the only reader that parses either.
    # Read the heading, not the file: Apache's own boilerplate names the licence
    # a dozen times further down, so a substring search over the whole text still
    # matches a LICENSE whose grant was replaced.
    licence_head = "\n".join(
        open(os.path.join(root, "LICENSE"), encoding="utf-8").read().strip().splitlines()[:5])
    if "Apache License" in licence_head and "Version 2.0" in licence_head:
        expected = "Apache-2.0"
    else:
        expected = None
        bad("LICENSE", "is not a licence this check recognises — it cannot verify the copies "
                       "against it, and unverified copies are how they drift")
    if expected:
        for rel in ("package.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
                    ".cursor-plugin/plugin.json", "gemini-extension.json"):
            path = os.path.join(root, rel)
            if not os.path.isfile(path):
                continue
            declared = json.load(open(path, encoding="utf-8")).get("license")
            if declared is None:
                continue                     # silent is not a contradiction
            if declared != expected:
                bad(rel, f"declares license {declared!r} while LICENSE grants {expected} — "
                         "the manifest is what a registry and an installer read")
        readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
        if "Apache" not in readme.split("\n## ")[0]:
            bad("README.md", f"its header no longer names {expected}, which LICENSE grants")

    if not FAILURES:
        print("check_versions: the product, the graph format, every rule and the licence agree.")
        return 0
    print(f"check_versions: {len(FAILURES)} problem(s)\n")
    for where, msg in FAILURES:
        print(f"  {where}\n      {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
