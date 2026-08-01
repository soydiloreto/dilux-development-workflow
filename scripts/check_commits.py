#!/usr/bin/env python3
"""Hold this repository's commits to the attribution rule it publishes.

`ddw/rules/commits.instructions.md` requires one of two trailers on any commit
produced with AI assistance, and forbids `Co-Authored-By` by name. The
distinction is the point, not the spelling:

**`Co-Authored-By: <a model>` claims co-authorship.** Authorship is where
responsibility sits, so a trailer naming the tool as an author spreads it onto
something that cannot hold it — and "the AI wrote it" is exactly the answer
`docs/AI-POLICY.md` opens by refusing to accept.

**`AI-assisted: yes` records assistance.** It says a model helped and a human
read, understood and approved the result. One author, who signed; a disclosure
of how the work was done. `AI-full: yes` is the same disclosure for a change
generated end to end — still owned by whoever committed it.

That rule applied to every repository DDW is installed in and to nothing here,
and a framework exempting itself from its own commit convention is an argument
against itself, made in public, in its own history.

    python3 scripts/check_commits.py --since origin/main [--repo .]

Only the range is checked: history before the rule cannot be rewritten without
breaking every clone, and rewriting it is not what makes the next commit right.

Exit 0 = every commit in the range is attributed. Exit 1 = at least one is not.
"""
import argparse
import os
import re
import subprocess
import sys

TRAILER = re.compile(r"^(?:AI-assisted|AI-full):\s*yes\s*$", re.M | re.I)
COAUTHOR = re.compile(r"^Co-Authored-By:", re.M | re.I)

# ASCII record/unit separators: a commit body can contain any text a person can
# type, so the delimiters have to be characters they cannot. NUL would be the
# conventional choice and cannot be passed in an argv string at all.
SEP = "\x1e"
UNIT = "\x1f"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), ".."))
    ap.add_argument("--since", required=True,
                    help="a git ref; every commit in <since>..HEAD is checked")
    args = ap.parse_args()
    root = os.path.abspath(args.repo)

    out = subprocess.run(["git", "-C", root, "log", f"--format=%H%x1f%B{SEP}",
                          f"{args.since}..HEAD"], capture_output=True, text=True)
    if out.returncode != 0:
        # Saying so is the point: a range that cannot be read is not a range
        # that passed, and this is the failure a shallow clone produces.
        print(f"check_commits: cannot read {args.since}..HEAD — the check did NOT run\n"
              f"  {out.stderr.strip()}")
        return 1

    problems = []
    checked = 0
    for chunk in out.stdout.split(SEP):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, _, body = chunk.partition(UNIT)
        checked += 1
        subject = body.strip().splitlines()[0] if body.strip() else "(no subject)"
        where = f"{sha[:9]} {subject[:60]}"
        if COAUTHOR.search(body):
            problems.append((where, "carries a Co-Authored-By trailer, which names the tool as "
                                    "an author. Use `AI-assisted: yes` — it discloses the help "
                                    "without moving the authorship, and the responsibility, off "
                                    "the person who signed"))
        elif not TRAILER.search(body):
            problems.append((where, "has no `AI-assisted: yes` or `AI-full: yes` trailer. Every "
                                    "commit made with AI assistance carries one; this repository "
                                    "is not exempt from the rule it ships"))

    if not problems:
        print(f"check_commits: {checked} commit(s) in {args.since}..HEAD, every one attributed.")
        return 0
    print(f"check_commits: {len(problems)} of {checked} commit(s) break the attribution rule\n")
    for where, msg in problems:
        print(f"  {where}\n      {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
