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


def is_bot(name, email):
    """A commit no person wrote, and therefore has nothing to disclose about.

    The rule is a disclosure: it asks the human who signed a commit to say
    whether a model helped write it. Dependabot bumping a pinned action has no
    such human and no such model, and demanding the trailer from it would make
    every dependency PR red until someone rewrote the bot's message by hand —
    which is how a rule stops being read and starts being routed around.

    Narrow on purpose: GitHub's own bot identity, both halves of it. This is a
    convention and not a boundary — anyone can set an author locally, exactly as
    anyone can type `AI-assisted: yes` without meaning it. What it must not do
    is exempt anyone quietly, so every skip is named in the output.
    """
    return name.endswith("[bot]") and email.endswith("@users.noreply.github.com")

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

    out = subprocess.run(["git", "-C", root, "log", f"--format=%H%x1f%an%x1f%ae%x1f%B{SEP}",
                          f"{args.since}..HEAD"], capture_output=True, text=True)
    if out.returncode != 0:
        # Saying so is the point: a range that cannot be read is not a range
        # that passed, and this is the failure a shallow clone produces.
        print(f"check_commits: cannot read {args.since}..HEAD — the check did NOT run\n"
              f"  {out.stderr.strip()}")
        return 1

    problems = []
    skipped = []
    checked = 0
    for chunk in out.stdout.split(SEP):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, name, email, body = (chunk.split(UNIT, 3) + ["", "", ""])[:4]
        if is_bot(name, email):
            skipped.append(f"{sha[:9]} {name}")
            continue
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

    # Named, never merely subtracted: a count that quietly went down is how an
    # exemption turns into a hole nobody looks for.
    note = ""
    if skipped:
        note = (f"\n  {len(skipped)} commit(s) skipped — authored by a bot, so there is no "
                f"person whose help there was anything to disclose:\n"
                + "\n".join(f"    {s}" for s in skipped))

    if not problems:
        print(f"check_commits: {checked} commit(s) in {args.since}..HEAD, "
              f"every one attributed.{note}")
        return 0
    print(f"check_commits: {len(problems)} of {checked} commit(s) break the attribution rule{note}\n")
    for where, msg in problems:
        print(f"  {where}\n      {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
