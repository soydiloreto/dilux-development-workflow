#!/usr/bin/env python3
"""DDW — parallel tickets without shared state: one worktree per ticket.

A DDW run's whole state lives in its working tree — `.ddw-state.json` is
gitignored, receipts live beside it — so two tickets in one directory would
fight over one state file, and the second would clobber the first. Git
worktrees are the answer the tool already ships: each ticket gets its own
working tree, its own state born fresh, its own branch, and the SAME hooks
and gates (the checkout carries `.ddw/` and the tool's wiring, because they
are committed; the state is not, because it is per-tree by design).

  open --ticket T   A sibling worktree `<repo>--wt-<t>`, detached at the
                    freshly fetched origin/<default> — never at the standing
                    tree's branch, whose half-done work is exactly what the
                    new ticket must not inherit. No state file travels: the
                    new tree classifies from IDLE, and its own CLASSIFY
                    names its branch, as always. Idempotent: already open
                    means "here is the path", not an error.

  list              Every worktree of this repo, with the ticket and phase
                    its own state file declares. Read-only.

  close --ticket T  THE SAME LAW AS EVERY CLOSE: the forge must show a
                    MERGED pull request naming the ticket, or the removal
                    is refused — a worktree is not done on anyone's word.
                    The declared out is `--drop "<why>"`. A DIRTY worktree
                    is never removed, not even dropped: uncommitted work is
                    named file by file and left standing.

Consolidation is not this script's job and needs no machinery: parallel
worktrees consolidate as pull requests landing IN ORDER against main — the
first merge is invisible to the second PR's review once it rebases, and the
forge already owns that story.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util as _ilu                                 # noqa: E402

_here = os.path.dirname(os.path.abspath(__file__))
_spec = _ilu.spec_from_file_location(
    "ddw_fip", os.path.join(_here, "family_index_pr.py"))
_fip = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_fip)


def _run(cmd, cwd=None, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _fail(msg):
    print("ticket_worktree: " + msg, file=sys.stderr)
    return 2


def _toplevel(root):
    code, out, _ = _run(["git", "-C", root, "rev-parse", "--show-toplevel"])
    return out if code == 0 else None


def _wt_path(top, ticket):
    name = os.path.basename(top)
    return os.path.join(os.path.dirname(top), "%s--wt-%s" % (name, ticket.lower()))


def _worktrees(top):
    """[(path, head, branch_or_None)] for every worktree of this repo."""
    code, out, _ = _run(["git", "-C", top, "worktree", "list", "--porcelain"])
    if code != 0:
        return []
    trees, cur = [], {}
    for ln in out.splitlines() + [""]:
        if not ln.strip():
            if cur.get("worktree"):
                trees.append((cur["worktree"], cur.get("HEAD", ""),
                              cur.get("branch")))
            cur = {}
        elif " " in ln:
            k, v = ln.split(" ", 1)
            cur[k] = v
        else:
            cur[ln] = True
    return trees


def _default_ref(top):
    code, out, _ = _run(["git", "-C", top, "symbolic-ref", "--quiet",
                         "refs/remotes/origin/HEAD"])
    if code == 0 and out:
        return out.replace("refs/remotes/", "", 1)
    for cand in ("origin/main", "origin/master"):
        if _run(["git", "-C", top, "rev-parse", "--verify", "--quiet", cand])[0] == 0:
            return cand
    return None


def open_wt(root, ticket):
    top = _toplevel(root)
    if not top:
        return _fail("not inside a git repository.")
    path = _wt_path(top, ticket)
    if any(os.path.realpath(p) == os.path.realpath(path) for p, _, _ in _worktrees(top)):
        print("ticket_worktree: %s ya está abierto en %s — seguí ahí." % (ticket, path))
        return 0
    # Freshness by construction: the new tree starts at the fetched origin
    # default, never at this tree's branch with its half-done work.
    _run(["git", "-C", top, "fetch", "--quiet", "origin"], timeout=300)
    ref = _default_ref(top)
    if not ref:
        return _fail("cannot resolve origin's default branch — is there an origin?")
    code, _, err = _run(["git", "-C", top, "worktree", "add", "--detach", path, ref],
                        timeout=300)
    if code != 0:
        return _fail("git worktree add failed: " + err[:300])
    code, sha, _ = _run(["git", "-C", path, "rev-parse", "--short", "HEAD"])
    print("ticket_worktree: worktree para %s en %s (detached en %s @ %s)."
          % (ticket, path, ref, sha))
    print("Sin estado heredado: el run arranca en IDLE y su propio CLASSIFY "
          "nombra la rama.")
    print("  cd %s   →   trabajá %s ahí" % (path, ticket))
    return 0


def list_wt(root):
    top = _toplevel(root)
    if not top:
        return _fail("not inside a git repository.")
    trees = _worktrees(top)
    print("Worktrees de %s:" % os.path.basename(top))
    for path, head, branch in trees:
        ticket, phase = "—", "—"
        try:
            st = json.load(open(os.path.join(path, ".ddw-state.json"), encoding="utf-8"))
            ticket = st.get("ticket") or "—"
            phase = st.get("phase") or st.get("state") or "—"
        except (OSError, ValueError):
            pass
        where = (branch or "detached").replace("refs/heads/", "")
        print("  · %-40s %-18s ticket: %-12s fase: %s"
              % (path, where, ticket, phase))
    return 0


def close_wt(root, ticket, drop):
    top = _toplevel(root)
    if not top:
        return _fail("not inside a git repository.")
    path = _wt_path(top, ticket)
    if not any(os.path.realpath(p) == os.path.realpath(path) for p, _, _ in _worktrees(top)):
        return _fail("no worktree for %s at %s — `list` shows what is open." % (ticket, path))

    # A dirty worktree is NEVER removed — not even dropped. Uncommitted work
    # has no other copy anywhere; naming it is the whole safety.
    code, out, _ = _run(["git", "-C", path, "status", "--porcelain"])
    if code != 0 or out:
        return _fail("the worktree holds uncommitted work — commit it or clean it "
                     "by hand first:\n" + (out or "(status failed)"))

    if drop:
        print("ticket_worktree: %s descartado — %s" % (ticket, drop))
    else:
        # Same law as every close: done is the forge's word, not anyone's.
        slug = None
        code, url, _ = _run(["git", "-C", path, "remote", "get-url", "origin"])
        if code == 0:
            m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
            slug = m.group(1) if m else None
        pr = _fip._merged_child_pr(slug, ticket) if slug else None
        if pr is None:
            return _fail("no MERGED pull request names %s at the forge — a worktree "
                         "does not close on anyone's word. If the work is being "
                         "abandoned, say so: `close --ticket %s --drop \"<why>\"`."
                         % (ticket, ticket))
        print("ticket_worktree: forge confirms PR #%s merged for %s." % (pr, ticket))

    code, _, err = _run(["git", "-C", top, "worktree", "remove", path], timeout=120)
    if code != 0:
        return _fail("git worktree remove failed: " + err[:300])
    _run(["git", "-C", top, "worktree", "prune"])
    print("ticket_worktree: %s cerrado y el worktree removido. Las ramas locales "
          "quedan como están — borralas cuando quieras." % ticket)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    p1 = sub.add_parser("open")
    p1.add_argument("--ticket", required=True)
    p2 = sub.add_parser("list")
    p3 = sub.add_parser("close")
    p3.add_argument("--ticket", required=True)
    p3.add_argument("--drop", default=None, help="declared out: abandon with a reason")
    for sp in (p1, p2, p3):
        sp.add_argument("--root", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if args.mode == "open":
        sys.exit(open_wt(root, args.ticket))
    if args.mode == "list":
        sys.exit(list_wt(root))
    if args.mode == "close":
        sys.exit(close_wt(root, args.ticket, args.drop))


if __name__ == "__main__":
    main()
