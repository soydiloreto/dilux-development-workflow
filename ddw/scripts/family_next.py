#!/usr/bin/env python3
"""DDW — the walk's conductor: what is the initiative's next step, per the forge.

The launch plan told the developer to walk the family by hand — cd, prompt,
wait, cd again — and the walk stalled at every handoff, because "what now?"
had to be reconstructed from a table and a set of pull requests. This script
IS that reconstruction, deterministic and fresh: it reads the index at the
workspace's origin, asks the forge which children actually merged, and hands
back exactly one verdict:

  next     — the first row whose every dependency is MERGED at the forge and
             whose own work is not: the repo to walk to, with the command.
  waiting  — no row is unblocked: each pending row named with the dependency
             it waits on and that dependency's forge state.
  update   — a row's child PR IS merged but the index still says otherwise:
             the truthful next step is the row update, and it is named first
             (an index behind the forge misleads every later question).
  all-done — every row done or declared out: the initiative is ready to close.

The decision is a pure function over (rows, forge answers) — tested and
mutated as such. The forge is asked, never trusted from the index: a row's
`Status` says what somebody recorded; a MERGED pull request says what
happened. Where the two disagree, the forge wins and the index is the bug.

Usage:
  python3 family_next.py --ticket <TICKET> [--root .]
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


def _load(name, filename):
    spec = _ilu.spec_from_file_location(name, os.path.join(_here, filename))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_vt = _load("ddw_vt", "validate-transition.py")
_fip = _load("ddw_fip", "family_index_pr.py")


def decide(rows, merged):
    """The verdict, as a pure function.

    `rows`: parse_family_rows output, in index order. `merged`: {short_name:
    pr_number_or_None} — the forge's answer per row's repo. Returns a dict
    with `kind` in (next | update | waiting | all-done) and its payload.

    Order of questions, and why:
      1. An index row behind the forge (child merged, row not done) is
         answered FIRST — every other verdict computed over a stale index
         inherits its lie.
      2. Then the first not-done row whose dependencies are all MERGED at
         the forge — dependencies are satisfied by MERGES, never by another
         row's recorded status.
      3. Nothing unblocked → waiting, each blocker named.
      4. Nothing pending at all → all-done.
    """
    def short(name):
        return name.rsplit("/", 1)[-1]

    def out_of_play(r):
        return r["done"] or r["status"].startswith(("dropped", "descartado"))

    stale = [r for r in rows if not out_of_play(r) and merged.get(short(r["repo"]))]
    if stale:
        r = stale[0]
        return {"kind": "update", "repo": r["repo"], "ticket": r["ticket"],
                "pr": merged[short(r["repo"])]}

    pending = [r for r in rows if not out_of_play(r)]
    if not pending:
        return {"kind": "all-done"}

    for r in pending:
        blockers = [d for d in r["deps"] if not merged.get(short(d))]
        if not blockers:
            return {"kind": "next", "repo": r["repo"], "ticket": r["ticket"],
                    "scope": r["scope"]}
    waits = [{"repo": r["repo"],
              "on": [d for d in r["deps"] if not merged.get(short(d))]}
             for r in pending]
    return {"kind": "waiting", "waits": waits}


def ready(rows, merged):
    """The PARALLEL set: every row that may run right now, in index order.

    A row is ready when it is still in play, its own child has not merged
    (a merged child is a stale row — decide() answers that first), and every
    dependency is MERGED at the forge. Two ready rows are independent by
    construction — each child runs standing in its OWN clone, so the only
    thing they could ever share is the workspace index, and every write to
    that travels through the forge. Ready-ness is the forge's word, never
    the index's: same law as decide(), stated twice because this set is what
    a parallel launch trusts."""
    out = []
    for r in rows:
        if r["done"] or r["status"].startswith(("dropped", "descartado")):
            continue
        if merged.get(r["repo"].rsplit("/", 1)[-1]):
            continue
        deps_short = [d.rsplit("/", 1)[-1] for d in r["deps"]]
        if all(merged.get(d2) for d2 in deps_short):
            out.append(r)
    return out


def _dup_shorts(rows):
    """Short names two rows share — the collision that would cross their
    forge answers, refused before any verdict is computed over it."""
    shorts = [r["repo"].rsplit("/", 1)[-1] for r in rows]
    return sorted({s for s in shorts if shorts.count(s) > 1})


def _read_index(root, ticket):
    """The index at the workspace's origin — fetched, then read from the ref."""
    slug = _fip._ws_slug(root)
    if not slug:
        return None, None, "cannot resolve the workspace repository from here"
    name = slug.rsplit("/", 1)[-1]
    siblings = os.path.dirname(os.path.abspath(root))
    ws = root if _fip._ws_map(root) else os.path.join(siblings, name)
    if not os.path.isdir(os.path.join(ws, ".git")):
        return None, None, ("the workspace clone %s is not there — "
                            "family_impact.py clones it" % ws)
    subprocess.run(["git", "-C", ws, "fetch", "--quiet", "origin"],
                   capture_output=True, timeout=120)
    # The workspace's OWN default branch — a master-default workspace made
    # a hardcoded origin/main fail every read with a misleading error.
    hb = subprocess.run(["git", "-C", ws, "symbolic-ref", "--quiet", "--short",
                         "refs/remotes/origin/HEAD"],
                        capture_output=True, text=True)
    default = hb.stdout.strip().rsplit("/", 1)[-1] if hb.returncode == 0 else "main"
    r = subprocess.run(["git", "-C", ws, "show",
                        "origin/%s:docs/ddw/prd/prd-%s.md" % (default, ticket)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None, None, ("no docs/ddw/prd/prd-%s.md at %s's origin/%s — is "
                            "%s the initiative's id, and is its index merged?"
                            % (ticket, slug, default, ticket))
    return slug, r.stdout, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticket", required=True)
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    slug, text, err = _read_index(root, args.ticket)
    if err:
        print("family_next: " + err, file=sys.stderr)
        return 2
    rows = _vt.parse_family_rows(text)
    if not rows:
        print("family_next: the index carries no readable rows.", file=sys.stderr)
        return 2

    dup = _dup_shorts(rows)
    if dup:
        print("family_next: two rows share the short name %s — the walk keys "
              "the forge's answers by short name, and a collision crosses "
              "their merges. Make the rows distinct." % ", ".join(dup),
              file=sys.stderr)
        return 2

    # The forge's silence is not a "no merge": offline, every child reads as
    # unmerged and the conductor speaks confident, wrong verdicts. One probe;
    # if the forge cannot answer, neither can this tool.
    probe, _, perr = _fip._run(["gh", "pr", "list", "--repo", slug,
                                "--limit", "1", "--json", "number"])
    if probe != 0:
        print("family_next: el forge no contesta (%s) — sin su palabra no hay "
              "veredicto." % (perr[:120] or "gh falló"), file=sys.stderr)
        return 2

    owner = slug.split("/", 1)[0]
    merged = {}
    for r in rows:
        short = r["repo"].rsplit("/", 1)[-1]
        child = r["repo"] if "/" in r["repo"] else "%s/%s" % (owner, short)
        merged[short] = _fip._merged_child_pr(child, r["ticket"] or args.ticket)

    print("Iniciativa %s — %d parte(s), según el forge:" % (args.ticket, len(rows)))
    for r in rows:
        short = r["repo"].rsplit("/", 1)[-1]
        forge = ("PR #%s MERGEADO" % merged[short]) if merged[short] else "sin merge"
        print("  · %-28s índice: %-24s forge: %s" % (short, r["status"], forge))

    verdict = decide(rows, merged)
    siblings = os.path.dirname(os.path.abspath(root))
    if verdict["kind"] == "update":
        short = verdict["repo"].rsplit("/", 1)[-1]
        print("\n➡ PRIMERO la verdad del índice: `%s` ya mergeó (PR #%s) y su fila "
              "no lo dice." % (short, verdict["pr"]))
        print("  python3 .ddw/scripts/family_index_pr.py update-row --ticket %s "
              "--repo-row %s --status done" % (args.ticket, short))
    elif verdict["kind"] == "next":
        short = verdict["repo"].rsplit("/", 1)[-1]
        print("\n➡ SIGUIENTE: `%s` — %s (dependencias mergeadas)."
              % (short, verdict["scope"]))
        print("  cd %s   →   Implementá mi parte de %s"
              % (os.path.join(siblings, short), verdict["ticket"] or args.ticket))
        listos = ready(rows, merged)
        if len(listos) > 1:
            print("\n∥ EN PARALELO — %d partes tienen todas sus dependencias "
                  "mergeadas y pueden correr a la vez, cada una PARADA en su "
                  "propio clon:" % len(listos))
            for r in listos:
                s = r["repo"].rsplit("/", 1)[-1]
                print("  · cd %s   →   Implementá mi parte de %s"
                      % (os.path.join(siblings, s), r["ticket"] or args.ticket))
            print("  (en paralelo solo si tu herramienta orquesta subprocesos; "
                  "si no, en este orden — el conductor re-consultado tras cada "
                  "merge da lo mismo)")
    elif verdict["kind"] == "waiting":
        print("\n⏳ Nada desbloqueado:")
        for w in verdict["waits"]:
            print("  · %s espera el merge de %s"
                  % (w["repo"].rsplit("/", 1)[-1], ", ".join(w["on"])))
    else:
        print("\n✅ Todas las partes cerradas o declaradas — la iniciativa está "
              "lista para cerrarse en el workspace.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
