#!/usr/bin/env python3
"""Which check of `lint_method.py` does each fault provoke — the kill map, one
level down.

`scripts/verify_install.sh` has ONE check for the whole prose linter ("the
method's prose claims something the repo does not support"). So in
`docs/CHECKS-THAT-CANNOT-FAIL.md` the linter's thirty-odd `fail()` sites collapse
into a single line: as long as any fault keeps `lint_method.py` red, a check
inside it that stopped finding what it was written for goes on reporting green,
and the ledger says the check is covered. That is the exact defect the ledger
exists to catch, one layer below where it can see.

So this asks the same question the kill map asks, about the linter itself:

    apply each fault to a copy → run the linter → record WHICH message came out

What never comes out is a check of the linter that no fault provokes. That does
not prove it cannot fail — it proves nothing measures whether it can. Either
write a fault that makes it fire, or write here why there is not one. Same
contract as the other ledger, same reason.

    python3 scripts/lint_kill_map.py --repo .            # measure and compare
    python3 scripts/lint_kill_map.py --repo . --write    # regenerate the ledger

Exit 0 = every site either fires or carries a written reason. Exit 1 = a site
fires nothing and nobody has said why, or the ledger excuses a site that now
fires. Exit 2 = the instrument could not measure.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

# The only thing skipped: faults on a `.py`. The linter reads no code — it
# reads prose, the graph, the compaction hooks and the FILESYSTEM — and running
# the five-hundred-odd of them triples how long this takes.
#
# The first version instead listed the extensions the linter DOES read
# (`.md`, `.json`, `.sh`), and that ate every fault that deletes a DIRECTORY:
# `delete("skills/ddw-test")` ends in none of the three. The two guards that
# fault exists to light up kept coming out as "nothing provokes them" right
# after their fault was written, and for twenty minutes the hole looked like
# the product's. An allowlist filter hides what it did not foresee; a
# blocklist lets too much through, which here costs seconds.
SKIP_EXT = (".py",)

LEDGER_HEADER = """# Lint checks that cannot fail

Generated against `scripts/lint_method.py` by `scripts/lint_kill_map.py`, and
**compared** by CI rather than trusted.

The suite has one check for the whole prose linter, so in
[CHECKS-THAT-CANNOT-FAIL.md](CHECKS-THAT-CANNOT-FAIL.md) every check inside it
collapses into a single line: while any fault keeps the linter red, a check of
the linter that stopped finding what it was written for still reports green.
This file is that question asked one level down.

Every line is a `fail(…)` of `lint_method.py` that **no fault in
`scripts/mutate.py` provokes**. Either write a fault that makes it fire, or say
here why there is not one.
"""


def sites_of(path):
    """Every `fail(...)` of every `check_*`, by LINE.

    The first version recognised each site by a literal piece of its message,
    and it had two measured holes:

      · A `fail()` with `%s` inside does NOT print `%s`, it prints the value.
        Taking the whole format string as the literal, that site can never
        match and comes out as "no mutation provokes it" with the mutation
        existing — it happened to the boot check, which has had its own since
        b605648. The same measurement error the kill map committed five times.
      · Splitting on the placeholders, TEN sites were left with no long
        literal stretch at all: messages that are almost pure interpolation.
        Demanding a ledger excuse for them would have recorded an instrument's
        ceiling as a product hole.

    So no recognition by text: `fail` is instrumented and the line it was
    called from is what gets recorded. A new site joins the count the day it
    is written, whatever its message says.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    by_line = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("check_"):
            continue
        calls = sorted((n for n in ast.walk(node)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == "fail"), key=lambda n: n.lineno)
        for i, call in enumerate(calls):
            by_line[call.lineno] = f"{node.name}[{i}]"
    return by_line


def load(root, name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(root, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def fault_target(apply_fn):
    """The file the fault touches, read from its own probe."""
    probe = getattr(apply_fn, "probe", None)
    if probe and len(probe) > 1:
        return probe[1]
    return None


def lint_lines(tree, n):
    """Runs the linter over `tree` and returns the LINES of the `fail()`s that
    came out.

    The linter is imported, not launched as a subprocess: that way `fail` can
    be wrapped and the calling line recorded, which is the only thing that
    identifies a site without depending on how its message is written. As a
    bonus, five hundred runs stop paying for five hundred interpreters.
    """
    mod = load(tree, f"ddw_lint_{n}", "scripts/lint_method.py")
    hit = set()
    real = mod.fail

    def spy(where, msg):
        hit.add(sys._getframe(1).f_lineno)
        return real(where, msg)

    mod.fail = spy
    mod.FINDINGS.clear()
    argv = sys.argv
    sys.argv = ["lint_method.py", "--repo", tree]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            mod.main()
    finally:
        sys.argv = argv
        sys.modules.pop(f"ddw_lint_{n}", None)
    return hit


def measure(root, sites):
    mut = load(root, "ddw_mutate", "scripts/mutate.py")
    work = tempfile.mkdtemp(prefix="lintmap-")
    tree = os.path.join(work, "tree")
    shutil.copytree(root, tree,
                    ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__",
                                                  ".pytest_cache", ".ddw-sessions"))
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=e@x", "-c", "user.name=e",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "base"]):
        subprocess.run(cmd, cwd=tree, check=True, capture_output=True)

    if lint_lines(tree, 0):
        # A dirty base tree measures its own dirt: every site already firing
        # counts as provoked by the first fault that gets applied.
        print("FATAL: lint_method is not green on this tree, so nothing below would "
              "measure the faults.", file=sys.stderr)
        shutil.rmtree(work, ignore_errors=True)
        return None, 0, 0

    fired, ran, skipped = {}, 0, 0
    for n, (desc, apply_fn) in enumerate(mut.MUTATIONS, 1):
        target = fault_target(apply_fn) or ""
        if target.endswith(SKIP_EXT):
            skipped += 1
            continue
        problem = apply_fn(tree)
        if not problem:
            ran += 1
            for line in lint_lines(tree, n):
                name = sites.get(line)
                if name:
                    fired.setdefault(name, []).append(desc)
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=tree, check=True)
        subprocess.run(["git", "clean", "-qfd"], cwd=tree, check=True)
    shutil.rmtree(work, ignore_errors=True)
    return fired, ran, skipped


_LEDGER_LINE = re.compile(r"^- \[ \] `([^`]+)`", re.M)


def existing_reason(old, name):
    """The written reason for a site, WHOLE.

    This used to capture a single line (`( +.*)$`, and `.` does not cross the
    newline), so regenerating the ledger cut every explanation to its first
    line — the reasons run five or six. One regeneration would have left
    forty-four excuses truncated mid-sentence, each still excusing its site:
    the file would stay green and no longer say why. A record that loses the
    one thing it records is worse than none, because nobody looks at it again.

    The whole indented block after the name is taken, up to the next item or
    the end.
    """
    m = re.search(r"^- \[ \] `%s`\n((?:[ \t]+.*(?:\n|$))*)" % re.escape(name), old, re.M)
    return m.group(1).rstrip("\n") if m else ""


def read_ledger(path):
    if not os.path.exists(path):
        return set()
    return set(_LEDGER_LINE.findall(open(path, encoding="utf-8").read()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), ".."))
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--write", action="store_true",
                    help="regenerate the ledger instead of comparing against it")
    args = ap.parse_args()
    root = os.path.abspath(args.repo)
    ledger_path = args.ledger or os.path.join(root, "docs/LINT-CHECKS-THAT-CANNOT-FAIL.md")

    sites = sites_of(os.path.join(root, "scripts/lint_method.py"))
    if not sites:
        print("FATAL: no fail() site could be read out of lint_method.py — a run that "
              "examined nothing is not a pass.", file=sys.stderr)
        return 2
    names = set(sites.values())

    fired, ran, skipped = measure(root, sites)
    if fired is None:
        return 2
    if ran == 0:
        print("FATAL: no fault touched a file the linter reads; nothing was measured.",
              file=sys.stderr)
        return 2

    naked = sorted(names - set(fired))
    print(f"lint_kill_map: {len(fired)} of {len(names)} fail() site(s) are provoked by some "
          f"fault ({ran} fault(s) run, {skipped} skipped for touching a file the linter "
          f"never reads)")

    if args.write:
        body = [LEDGER_HEADER, f"<!-- {len(names)} site(s), {ran} fault(s) measured -->\n"]
        old = open(ledger_path, encoding="utf-8").read() if os.path.exists(ledger_path) else ""
        for name in naked:
            reason = existing_reason(old, name)
            body.append(f"- [ ] `{name}`\n{reason or '      **No written reason yet.**'}")
        open(ledger_path, "w", encoding="utf-8").write("\n".join(body) + "\n")
        print(f"  wrote {ledger_path} — {len(naked)} site(s) with no fault")
        return 0

    excused = read_ledger(ledger_path)
    unexcused = [n for n in naked if n not in excused]
    stale = sorted(excused - set(naked))
    for name in unexcused:
        print(f"  ✗ {name}\n      nothing provokes it and the ledger does not say why")
    for name in stale:
        print(f"  ✗ {name}\n      the ledger excuses it, but a fault provokes it now — "
              "delete the entry, or the excuse outlives the reason")
    if unexcused or stale:
        return 1
    print(f"  every site either fires or carries a written reason ({len(naked)} excused)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
