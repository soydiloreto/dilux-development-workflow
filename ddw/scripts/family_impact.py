#!/usr/bin/env python3
"""DDW — the impact analysis's deterministic half.

Standing in ANY repo of a family, classification's first duty is the impact
question: which members does this work hit, and which does it provably not.
The MODEL owns the verdict; this script owns everything a script can own —
so the verdict is written over fresh, complete, recorded facts instead of
memory and goodwill:

  gather (default)   Resolve the family from this repo's `## Repo family`,
                     find the workspace and every member as sibling clones —
                     CLONING the missing ones via `gh` — fetch them all, and
                     read the map (familia.md) and each member's seams from
                     `origin/<default>`: freshness by construction, no
                     working tree is ever touched. The facts land in
                     `.ddw-work/impact-data-<ticket>.json`, each repo with
                     the SHA it was read at.

  --validate FILE    Judge the model-written verdict at FILE against the
                     gathered facts: EVERY member must appear — impacted, or
                     under "Sin impacto" with a non-empty reason — and no
                     invented repo may appear as impacted. On PASS, write the
                     content-hashed receipt the CLASSIFY→DEFINE gate demands.

The receipt's honest bargain (ddw_receipt.py says it plainly): it does not
prove the judgment is right — it proves the judgment was made over the whole
family, freshly read, and that skipping the step is a deliberate act that
leaves no file where the record demands one.

Usage:
  python3 family_impact.py [--root .] [--ticket T-1] [--siblings DIR]
  python3 family_impact.py --validate .ddw-work/impact-T-1.md [--root .]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ddw_receipt                                            # noqa: E402
import importlib.util as _ilu                                 # noqa: E402

_spec = _ilu.spec_from_file_location(
    "ddw_family_catalog",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "family_catalog.py"))
_catalog = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_catalog)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(cwd, *args, ok_codes=(0,)):
    """Run git in `cwd`; return (code, stdout). Never raises on git failure —
    an unreachable remote is a FACT to record, not a crash."""
    try:
        r = subprocess.run(["git", "-C", cwd, *args],
                           capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout or "").strip() or (r.stderr or "").strip()
    except Exception as exc:                                  # noqa: BLE001
        return 1, str(exc)


def _default_branch(clone):
    """The remote's default branch, from origin/HEAD; 'main' as the guess of
    last resort (a fresh `gh repo clone` always sets origin/HEAD)."""
    code, out = _git(clone, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if code == 0 and out.startswith("refs/remotes/origin/"):
        return out.rsplit("/", 1)[-1]
    return "main"


def _read_at_origin(clone, branch, path):
    """A file's content at origin/<branch> — the fetched truth, not whatever
    the working tree holds mid-edit. None if the file is not there."""
    code, out = _git(clone, "show", "origin/%s:%s" % (branch, path))
    return out if code == 0 else None


def _sha_at_origin(clone, branch):
    code, out = _git(clone, "rev-parse", "--short", "origin/%s" % branch)
    return out if code == 0 else None


def _clone_missing(slug, dest):
    """`gh repo clone` for a member that is not on disk. Returns an error
    string, or None on success."""
    try:
        r = subprocess.run(["gh", "repo", "clone", slug, dest],
                           capture_output=True, text=True, timeout=300)
        return None if r.returncode == 0 else (r.stderr or r.stdout).strip()[:200]
    except Exception as exc:                                  # noqa: BLE001
        return str(exc)


def _standing_repo_freshness(root):
    """The one working tree the ticket will actually change: fetch always;
    fast-forward the default branch only when it is checked out and clean.
    A diverged or dirty tree is REPORTED, never merged over — an automatic
    merge mid-run is a box of surprises nobody ordered."""
    _git(root, "fetch", "--quiet", "origin")
    branch = _default_branch(root)
    code, current = _git(root, "branch", "--show-current")
    _, dirty = _git(root, "status", "--porcelain")
    if current != branch:
        return "fetched; on `%s`, not `%s` — left as-is" % (current or "?", branch)
    if dirty:
        return "fetched; working tree has local changes — left as-is"
    code, out = _git(root, "merge", "--ff-only", "origin/%s" % branch)
    if code == 0:
        return "fetched and fast-forwarded to origin/%s" % branch
    return ("fetched; local %s DIVERGED from origin — resolve it before "
            "branching (no automatic merge)" % branch)


def gather(root, ticket, siblings=None):
    """The facts: family, members, seams, freshness — everything deterministic."""
    try:
        agents = open(os.path.join(root, "AGENTS.md"), encoding="utf-8").read()
    except OSError:
        agents = ""
    section = _catalog.family_section(agents)
    if not section:
        print("family_impact: this repo declares no `## Repo family` — single-repo "
              "flow, nothing to gather.", file=sys.stderr)
        return 3

    ws_slug = re.sub(r"\s*\(.*\)$", "", section.get("workspace", "")).strip()
    if "/" not in ws_slug:
        print("family_impact: the Workspace field (%r) is not owner/name — fix "
              "AGENTS.md § Repo family first." % ws_slug, file=sys.stderr)
        return 2
    family = section.get("family", "").strip() or "?"
    siblings = os.path.abspath(siblings or os.path.dirname(os.path.abspath(root)))
    report = {"family": family, "workspace": ws_slug, "ticket": ticket,
              "generated_at": _now_iso(), "standing_repo": None,
              "members": [], "problems": []}

    report["standing_repo"] = {
        "path": os.path.abspath(root),
        "freshness": _standing_repo_freshness(root),
    }

    def ensure_clone(slug):
        name = slug.rsplit("/", 1)[-1]
        dest = os.path.join(siblings, name)
        if not os.path.isdir(os.path.join(dest, ".git")):
            err = _clone_missing(slug, dest)
            if err:
                return None, "clone failed: %s" % err
            return dest, "cloned now"
        _git(dest, "fetch", "--quiet", "origin")
        return dest, "fetched"

    ws_dir, ws_state = ensure_clone(ws_slug)
    if ws_dir is None:
        print("family_impact: cannot reach the workspace %s (%s) — without the "
              "map there is no family to analyse." % (ws_slug, ws_state),
              file=sys.stderr)
        return 2
    ws_branch = _default_branch(ws_dir)
    familia_text = _read_at_origin(ws_dir, ws_branch, "familia.md")
    if not familia_text:
        print("family_impact: %s has no familia.md at origin/%s — the map is "
              "the workspace's one job." % (ws_slug, ws_branch), file=sys.stderr)
        return 2
    rows = _parse_familia(familia_text)
    if not rows:
        print("family_impact: familia.md at origin/%s has no member table." % ws_branch,
              file=sys.stderr)
        return 2

    owner = ws_slug.split("/", 1)[0]
    for row in rows:
        name = row["name"].rsplit("/", 1)[-1]
        slug = row["name"] if "/" in row["name"] else "%s/%s" % (owner, name)
        member = {"name": name, "slug": slug,
                  "provides": row.get("provides", "none"),
                  "consumed_by": row.get("consumed by", "none"),
                  "consumes": row.get("consumes", "none"),
                  "state": None, "sha": None}
        clone, state = ensure_clone(slug)
        member["state"] = state
        if clone is None:
            report["problems"].append("%s: %s" % (name, state))
        else:
            branch = _default_branch(clone)
            member["sha"] = _sha_at_origin(clone, branch)
            fresh_agents = _read_at_origin(clone, branch, "AGENTS.md") or ""
            fresh = _catalog.family_section(fresh_agents)
            if fresh:
                # The member's own declaration wins over the map's copy — the
                # catalog doctrine, applied here too.
                member["provides"] = fresh.get("provides", member["provides"])
                member["consumed_by"] = fresh.get("consumed by", member["consumed_by"])
                member["consumes"] = fresh.get("consumes", member["consumes"])
        report["members"].append(member)

    os.makedirs(os.path.join(root, ".ddw-work"), exist_ok=True)
    out_path = os.path.join(root, ".ddw-work",
                            "impact-data-%s.json" % (ticket or "unticketed"))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print("family_impact: family `%s` · %d member(s) read at origin · data: %s"
          % (family, len(report["members"]), os.path.relpath(out_path, root)))
    print("  standing repo: %s" % report["standing_repo"]["freshness"])
    for m in report["members"]:
        print("  · %s @ %s — provides: %s · consumed by: %s"
              % (m["name"], m["sha"] or "?", m["provides"], m["consumed_by"]))
    for p in report["problems"]:
        print("  ⚠ %s" % p)
    print("Now write the verdict to .ddw-work/impact-%s.md — every member above, "
          "impacted or `Sin impacto` with its reason — and validate it with "
          "--validate." % (ticket or "unticketed"))
    return 0


def _parse_familia(text):
    """familia.md's member table, standalone (same tolerance as familia_map)."""
    rows, headers = [], None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        low = [c.lower() for c in cells]
        if headers is None:
            if any("repo" in c for c in low):
                headers = low
            continue
        if set(c.strip("-: ") for c in low) <= {""}:
            continue
        row = dict(zip(headers, cells))
        name = re.sub(r"[`*]", "", row.get(next((h for h in headers if "repo" in h), ""), "")).strip()
        if not name:
            continue

        def col(*keys):
            for k in keys:
                for h in headers:
                    if k in h:
                        return re.sub(r"[`*]", "", row.get(h, "")).strip() or "none"
            return "none"
        rows.append({"name": name,
                     "provides": col("expone", "provides", "hace", "what"),
                     "consumed by": col("consumed by", "consumen", "consumido"),
                     "consumes": col("consume")})
    return rows


def validate(root, verdict_path):
    """Judge the verdict against the gathered facts; receipt on PASS."""
    try:
        verdict = open(verdict_path, encoding="utf-8").read()
    except OSError as exc:
        print("family_impact: cannot read %s: %s" % (verdict_path, exc), file=sys.stderr)
        return 2
    m = re.search(r"impact-(.+?)\.md$", os.path.basename(verdict_path))
    ticket = m.group(1) if m else None
    data_path = os.path.join(root, ".ddw-work",
                             "impact-data-%s.json" % (ticket or "unticketed"))
    try:
        data = json.load(open(data_path, encoding="utf-8"))
    except OSError:
        print("family_impact: no gathered facts at %s — run the gather step first; "
              "a verdict with no fresh facts under it is an opinion." % data_path,
              file=sys.stderr)
        return 1

    problems = []
    members = [m["name"] for m in data.get("members", [])]
    if not members:
        problems.append("the data file lists no members — regather")
    body = verdict
    # "Sin impacto" block: lines mentioning a member need a reason after a dash.
    for name in members:
        pattern = re.compile(r"^.*\b%s\b.*$" % re.escape(name), re.MULTILINE)
        hit = pattern.search(body)
        if not hit:
            problems.append("member `%s` appears nowhere — impacted or not, every "
                            "member gets a line" % name)
            continue
        line = hit.group(0)
        sin = re.search(r"sin impacto\s*[:—–-]?\s*(.*)$", line, re.IGNORECASE)
        if sin and len(sin.group(1).strip()) < 8:
            problems.append("member `%s` is 'Sin impacto' with no real reason — "
                            "an unexplained exclusion is a member nobody analysed"
                            % name)
    impacted = []
    for ln in body.splitlines():
        if not re.search(r"impact", ln, re.IGNORECASE):
            continue
        m2 = re.match(r"[ \t|*`-]{0,8}([A-Za-z0-9._\-]+)`?[ \t]*(?:\||—|:)", ln)
        if m2:
            impacted.append(m2.group(1))
    known = set(members)
    for cand in impacted:
        if cand not in known and re.match(r"^[a-z0-9][a-z0-9._\-]+$", cand) \
                and cand.count("-") >= 1 and cand not in ("sin-impacto",):
            problems.append("`%s` is named as impacted and is not in the family — "
                            "the split cannot schedule a repo the map does not know"
                            % cand)
    if not re.search(r"sin impacto", body, re.IGNORECASE) and len(members) > 1:
        # Not an error by itself — an initiative CAN hit everyone — but the
        # verdict must say so in words, not by omission.
        if not re.search(r"impacta.*tod|all members|toda la familia", body, re.IGNORECASE):
            hit_all = all(
                re.search(r"^.*\b%s\b.*$" % re.escape(n), body, re.MULTILINE)
                for n in members)
            if not hit_all:
                problems.append("no `Sin impacto` section and not every member is "
                                "listed as impacted — the family does not add up")

    if problems:
        print("family_impact --validate: FAILED")
        for p in problems:
            print("  ❌ " + p)
        return 1
    name = ddw_receipt.write(verdict_path, "impact", verdict)
    print("family_impact --validate: PASSED — every member of `%s` accounted for."
          % data.get("family", "?"))
    print("Receipt: %s" % name)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--ticket", default=None)
    ap.add_argument("--siblings", default=None,
                    help="where the family's clones live (default: the parent dir)")
    ap.add_argument("--validate", default=None, metavar="IMPACT_MD")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if args.validate:
        sys.exit(validate(root, args.validate))
    sys.exit(gather(root, args.ticket, args.siblings))


if __name__ == "__main__":
    main()
