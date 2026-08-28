#!/usr/bin/env python3
"""DDW — the one-approve index: publish, merge-on-a-leash, and the row's way back.

The multirepo index is a DOCUMENT, and its ceremony was priced like code:
draft PR, ready, merge, pull — four stops for a table. The owner walked that
ceremony twice on live initiatives and named it what it was. This script
collapses it to ONE human word per direction, without touching the line that
matters: code PRs keep their human merge at the forge, always.

  publish       From the workspace, on the ticket branch with the index
                committed: push the branch and open the PR. Prints the PR
                number and stops — the merge is a second, deliberate call.

  merge --pr N  THE LEASH. Merges the PR only if every file it touches is
                index territory (docs/ddw/** or .gitignore) and it targets
                this workspace. A PR with one line of code in it is refused —
                so the worst a runaway "aprobado" can do is land a document,
                which the next session can read, and revert with another PR.
                The approval itself is conversational (the user's word in the
                session); the leash is what bounds its blast radius, and the
                leash is code.

  update-row    The way back. From ANY repo of the family: verifies against
                the forge that the child's PR is MERGED (`done` is not yours
                to write — same law as the write gate, enforced here because
                this path edits a throwaway clone no hook watches), edits
                exactly one row, and publishes the update PR the same
                one-approve way. Declared outs (`dropped: <why>`,
                `done (unverified: <why>)`) are accepted with their reason.

Nothing here pushes to a main directly, ever: every write to the workspace
travels as a branch and lands as a squash-merged PR — the audit trail is the
forge's, same as everything else in this method.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util as _ilu                                 # noqa: E402

_spec = _ilu.spec_from_file_location(
    "ddw_family_catalog",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "family_catalog.py"))
_catalog = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_catalog)

ALLOWED = re.compile(r"^(docs/ddw/.*|\.gitignore)$")
STATUS_OK = re.compile(
    r"^(active|pending|done|dropped:\s*\S.*|done \(unverified:\s*\S.*\))$",
    re.IGNORECASE)


def _run(cmd, cwd=None, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _fail(msg):
    print("family_index_pr: " + msg, file=sys.stderr)
    return 2


def _ws_slug(root):
    """The workspace this repo belongs to — its own remote when the repo IS
    the workspace (familia.md on disk), the family section's slug otherwise."""
    if os.path.exists(os.path.join(root, "familia.md")):
        code, out, _ = _run(["git", "-C", root, "remote", "get-url", "origin"])
        if code == 0:
            m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", out)
            if m:
                return m.group(1)
    try:
        agents = open(os.path.join(root, "AGENTS.md"), encoding="utf-8").read()
    except OSError:
        agents = ""
    section = _catalog.family_section(agents)
    if section:
        slug = re.sub(r"\s*\(.*\)$", "", section.get("workspace", "")).strip()
        if "/" in slug:
            return slug
    return None


def publish(root, ticket):
    """Push the current branch and open the index PR. One stop, not four."""
    code, branch, _ = _run(["git", "-C", root, "branch", "--show-current"])
    if code != 0 or not branch or branch in ("main", "master"):
        return _fail("publish runs on the ticket branch, not on %r — the index "
                     "travels as a branch and lands as a PR, like everything." % branch)
    code, _, err = _run(["git", "-C", root, "push", "-u", "origin", branch], timeout=300)
    if code != 0:
        return _fail("push failed: " + err[:300])
    title = "\U0001F4DD %s: multirepo index" % (ticket or branch)
    code, out, err = _run(["gh", "pr", "create", "--fill", "--title", title,
                           "--body", "Multirepo index for %s. Documents only — "
                           "mergeable by the one-approve leash "
                           "(family_index_pr.py merge)." % (ticket or branch)],
                          cwd=root, timeout=300)
    if code != 0 and "already exists" not in err:
        return _fail("gh pr create failed: " + (err or out)[:300])
    m = re.search(r"/pull/(\d+)", out + err)
    pr = m.group(1) if m else "?"
    print("family_index_pr: PR #%s abierto para la rama %s." % (pr, branch))
    print("Con el 'aprobado' del usuario EN PANTALLA, mergear con: "
          "family_index_pr.py merge --pr %s" % pr)
    return 0


def _leash(slug, pr):
    """Every file the PR touches must be index territory. Returns error or None."""
    code, out, err = _run(["gh", "pr", "view", str(pr), "--repo", slug,
                           "--json", "files,state,baseRefName"])
    if code != 0:
        return "gh pr view failed: " + err[:300]
    data = json.loads(out or "{}")
    if data.get("state") not in ("OPEN",):
        return "PR #%s is %s — only an open PR can be merged" % (pr, data.get("state"))
    files = [f.get("path", "") for f in data.get("files", [])]
    if not files:
        return "PR #%s touches no files — nothing to approve" % pr
    outside = sorted(p for p in files if not ALLOWED.match(p))
    if outside:
        return ("PR #%s touches %s — the one-approve leash merges INDEX DOCUMENTS "
                "only (docs/ddw/** and .gitignore). Code goes to the forge for a "
                "human merge, always." % (pr, ", ".join(outside)))
    return None


def merge(root, pr, slug=None):
    slug = slug or _ws_slug(root)
    if not slug:
        return _fail("cannot resolve the workspace repository (no familia.md here "
                     "and no `## Repo family` section).")
    reason = _leash(slug, pr)
    if reason:
        return _fail(reason)
    code, out, err = _run(["gh", "pr", "merge", str(pr), "--repo", slug,
                           "--squash", "--delete-branch"], timeout=300)
    if code != 0:
        return _fail("gh pr merge failed: " + (err or out)[:300])
    print("family_index_pr: PR #%s mergeado (squash) en %s." % (pr, slug))
    if os.path.exists(os.path.join(root, "familia.md")):
        _run(["git", "-C", root, "checkout", "main"])
        _run(["git", "-C", root, "pull", "--ff-only", "origin", "main"], timeout=300)
        print("El clon local del workspace quedó en main, actualizado.")
    return 0


def _merged_child_pr(child_slug, ticket):
    """The forge's answer: a MERGED PR in the child whose branch names the
    ticket. Returns its number, or None."""
    code, out, _ = _run(["gh", "pr", "list", "--repo", child_slug, "--state", "merged",
                         "--json", "number,headRefName", "--limit", "50"])
    if code != 0:
        return None
    for row in json.loads(out or "[]"):
        if ticket.lower() in (row.get("headRefName") or "").lower():
            return row.get("number")
    return None


def update_row(root, ticket, row_repo, status):
    """Edit ONE row of the index in a throwaway clone, and publish the PR."""
    if not STATUS_OK.match(status.strip()):
        return _fail("status %r is not the fixed vocabulary (`active`, `pending`, "
                     "`done`, `dropped: <why>`, `done (unverified: <why>)`)." % status)
    slug = _ws_slug(root)
    if not slug:
        return _fail("cannot resolve the workspace repository from here.")
    owner = slug.split("/", 1)[0]
    short = row_repo.rsplit("/", 1)[-1]

    # `done` is not yours to write — same law as the family write gate,
    # enforced HERE because a throwaway clone has no hooks watching it.
    if status.strip().lower() == "done":
        child_slug = row_repo if "/" in row_repo else "%s/%s" % (owner, short)
        pr = _merged_child_pr(child_slug, ticket)
        if pr is None:
            return _fail("no MERGED pull request in %s names ticket %s — a row does "
                         "not say `done` on anyone's word. If the merge truly cannot "
                         "be confirmed, the declared out is "
                         "`done (unverified: <why>)`." % (child_slug, ticket))
        print("family_index_pr: forge confirms %s PR #%s merged." % (child_slug, pr))

    tmp = tempfile.mkdtemp(prefix="ddw-index-")
    code, _, err = _run(["gh", "repo", "clone", slug, tmp, "--", "--depth", "5"],
                        timeout=300)
    if code != 0:
        return _fail("clone of %s failed: %s" % (slug, err[:200]))
    index = os.path.join(tmp, "docs", "ddw", "prd", "prd-%s.md" % ticket)
    try:
        text = open(index, encoding="utf-8").read()
    except OSError:
        return _fail("the workspace has no docs/ddw/prd/prd-%s.md — is %s the "
                     "initiative's id?" % (ticket, ticket))
    pattern = re.compile(
        r"^(\|\s*\S*%s\s*\|[^\n]*\|)\s*[^|\n]*\|\s*$" % re.escape(short), re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return _fail("no row for `%s` in the index — rows: run `--validate` on the "
                     "index to see them." % short)
    new_text = text[:m.start()] + m.group(1) + " %s |" % status.strip() + text[m.end():]
    if new_text == text:
        print("family_index_pr: the row already says %r — nothing to publish." % status)
        return 0
    with open(index, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    branch = "chore/%s-row-%s" % (ticket, short)
    for cmd in (["git", "-C", tmp, "checkout", "-b", branch],
                ["git", "-C", tmp, "add", "-A"],
                ["git", "-C", tmp, "commit", "-m",
                 "docs(index): %s -> %s (%s)" % (short, status.strip(), ticket)],
                ["git", "-C", tmp, "push", "-u", "origin", branch]):
        code, _, err = _run(cmd, timeout=300)
        if code != 0:
            return _fail("%s failed: %s" % (" ".join(cmd[3:5]), err[:200]))
    code, out, err = _run(["gh", "pr", "create", "--repo", slug, "--head", branch,
                           "--title", "\U0001F4C7 %s: %s → %s" %
                           (ticket, short, status.strip()),
                           "--body", "Index row update. Documents only — mergeable "
                           "by the one-approve leash."],
                          cwd=tmp, timeout=300)
    m2 = re.search(r"/pull/(\d+)", out + err)
    pr_n = m2.group(1) if m2 else "?"
    print("family_index_pr: PR #%s abierto en %s (%s → %s)."
          % (pr_n, slug, short, status.strip()))
    print("Con el 'aprobado' del usuario EN PANTALLA: "
          "family_index_pr.py merge --pr %s" % pr_n)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    p1 = sub.add_parser("publish")
    p1.add_argument("--ticket", default=None)
    p2 = sub.add_parser("merge")
    p2.add_argument("--pr", required=True)
    p2.add_argument("--repo", default=None, help="workspace slug (resolved if omitted)")
    p3 = sub.add_parser("update-row")
    p3.add_argument("--ticket", required=True)
    p3.add_argument("--repo-row", required=True, help="the row's repo (short name or slug)")
    p3.add_argument("--status", required=True)
    for sp in (p1, p2, p3):
        sp.add_argument("--root", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if args.mode == "publish":
        sys.exit(publish(root, args.ticket))
    if args.mode == "merge":
        sys.exit(merge(root, args.pr, args.repo))
    if args.mode == "update-row":
        sys.exit(update_row(root, args.ticket, args.repo_row, args.status))


if __name__ == "__main__":
    main()
