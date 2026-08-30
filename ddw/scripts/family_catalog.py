#!/usr/bin/env python3
"""The family catalog, derived — never written by hand.

Every serious service catalog converges on the same two lessons, and this file
is DDW's application of both. First: **the descriptor lives in the repo it
describes; the center only aggregates.** Each repo declares its own
`## Repo family` section in its own `AGENTS.md`; this script reads those
declarations and regenerates the workspace's consolidated view. Second:
**hand-maintained catalogs rot** — day-one enthusiasm, then drift, then "kind
of accurate, in places", then nobody trusts it. A catalog that is derived on
demand from files that travel with the code cannot drift further than one
re-run.

Membership is self-declared: a repo belongs to this workspace's catalog if and
only if its `AGENTS.md` declares `Workspace = <this workspace's slug>`. Joining
is adding the section; leaving is removing it — and a removal is ANNOTATED in
the block on the next run, never silent, the same rule `done (unverified:)`
follows: the count may degrade out loud, with a reason, and no other way.

The output is a managed block in `docs/ddw/family-catalog.md`, delimited by
`<!-- BEGIN DDW CATALOG -->` / `<!-- END DDW CATALOG -->` — the `.gitignore`
block's pattern: outside the markers the file is the user's; inside, no hand
writes. Each row records the blob sha of the `AGENTS.md` it was derived from,
so `--check` is a comparison, not an opinion: shas moved → the catalog is
stale, exit 3, nothing written.

A repo whose `AGENTS.md` cannot be fetched is marked `(unreachable: …)` and
KEPT — the `_family_child_merged` lesson: "gh fell over" and "no section" must
never read the same, because one is retried and the other is the finding.

Credentials: none stored, ever. Every remote read is the user's own `gh`, the
same authority the pr gate already leans on.

`--write-members` is the owner's decision, taken out loud (2026-08-26): the
family's map is AUTHORED once, centrally, in the workspace's `ddw-family.md`, and
this routine PROPAGATES it — creating or updating each member clone's
`## Repo family` section and committing in that clone under the user's own
git identity. This is the user administering their own repositories with
their own credentials, the installer's class of act, not a pipeline session
writing across repos (which stays forbidden). Only the section between the
`## Repo family` heading and the next `##` is touched; the rest of each
AGENTS.md is its repo's own. Pushes are listed, not taken — `--push` takes
them, for terminals where the user's SSH agent is live.

    python3 family_catalog.py                  # derive, write the block, report
    python3 family_catalog.py --check          # is it fresh? exit 0/3, write nothing
    python3 family_catalog.py --write-members --local DIR
        # the other direction: propagate the map in ddw-family.md into each
        # member clone's AGENTS.md `## Repo family` section, and commit there
    python3 family_catalog.py --owner NAME     # who to enumerate (default: the workspace's owner)
    python3 family_catalog.py --repos a,b,c    # explicit list instead of enumeration
    python3 family_catalog.py --local DIR      # read sibling clones under DIR, no forge
    python3 family_catalog.py --org ACME [--write]
        # the ORGANIZATION sweep, from anywhere, no clones: the forge lists
        # every repo, each AGENTS.md is read by API, and the report buckets
        # every single one — families with members, standalones counted,
        # unreachables NAMED. Re-running it is the refresh. --write publishes
        # a seed ddw-family.md as a one-approve PR per family with no map;
        # an existing map is never rewritten — its drift is reported.

Exit: 0 = fresh / regenerated · 2 = cannot run (no workspace section, no gh) ·
3 = --check found it stale.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

BEGIN = "<!-- BEGIN DDW CATALOG -->"
END = "<!-- END DDW CATALOG -->"
CATALOG_REL = os.path.join("docs", "ddw", "family-catalog.md")

_FIELD = re.compile(r"^\|\s*(?P<k>[A-Za-z ]+?)\s*\|\s*(?P<v>.+?)\s*\|\s*$")


def family_section(text):
    """The `## Repo family` section's fields, as a dict — or None without one.

    The Field/Value table is the spec in `docs/AGENTS-MD.md`; prose around the
    table is the user's and is ignored. Keys are lowercased so `Consumed by`
    and `Consumed By` are one key, values kept verbatim.
    """
    m = re.search(r"^##\s+Repo family\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    body = text[m.end():]
    nxt = re.search(r"^##\s+", body, re.MULTILINE)
    if nxt:
        body = body[:nxt.start()]
    fields = {}
    for line in body.splitlines():
        fm = _FIELD.match(line.strip())
        if not fm:
            continue
        key = fm.group("k").strip().lower()
        if key in ("field", "---", ""):
            continue
        fields[key] = fm.group("v").strip()
    return fields or None


def _gh(*args, timeout=30):
    """gh, or None when it could not answer — never an exception to the caller."""
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True,
                             timeout=timeout, stdin=subprocess.DEVNULL)
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def fetch_remote(slug):
    """(text, sha) of a repo's AGENTS.md at its default branch, or (None, why)."""
    raw = _gh("api", f"repos/{slug}/contents/AGENTS.md",
              "--jq", "{sha: .sha, content: .content}")
    if raw is None:
        return None, "gh could not fetch AGENTS.md"
    try:
        data = json.loads(raw)
        import base64
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]
    except Exception:
        return None, "unreadable answer from the forge"


def fetch_local(base, name):
    """(text, pseudo-sha) from a sibling clone, for --local and offline work."""
    path = os.path.join(base, name, "AGENTS.md")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None, "no clone (or no AGENTS.md) under %s" % base
    import hashlib
    return text, "local:" + hashlib.sha1(text.encode()).hexdigest()[:12]


def candidate_repos(owner, explicit, prior_names):
    """Who to look at: explicit list, else prior rows + the owner's repos."""
    if explicit:
        return [r.strip() for r in explicit.split(",") if r.strip()]
    names = set(prior_names)
    raw = _gh("repo", "list", owner, "--limit", "200", "--json", "name",
              "--jq", ".[].name")
    if raw:
        names.update(n.strip() for n in raw.splitlines() if n.strip())
    return sorted(names)


def prior_rows(catalog_text):
    """The names the current block already carries, so a vanished repo is
    annotated rather than silently gone."""
    if BEGIN not in catalog_text:
        return []
    block = catalog_text.split(BEGIN, 1)[1].split(END, 1)[0]
    return [m.group(1) for m in re.finditer(r"^\|\s*`?([\w.-]+)`?\s*\|", block, re.MULTILINE)
            if m.group(1).lower() not in ("repo", "---", ":---")]


def build_block(rows, gone, owner, source):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = [BEGIN,
           "<!-- derived by ddw family_catalog.py — do not edit inside the markers;",
           "     re-run the tool instead. generated-at: %s · owner: %s · source: %s -->" % (
               now, owner, source),
           "",
           "| Repo | Provides | Consumed by | Consumes | Source (AGENTS.md sha) |",
           "|---|---|---|---|---|"]
    for r in rows:
        out.append("| %s | %s | %s | %s | %s |" % (
            r["name"], r["provides"], r["consumed by"], r["consumes"], r["sha"]))
    for name, why in gone:
        out.append("| ~~%s~~ | removed %s: %s | | | |" % (name, now[:10], why))
    out.append(END)
    return "\n".join(out)


def familia_map(root):
    """The authored map: the family map's table, one row per member — read
    from `ddw-family.md`, or the deprecated `familia.md`.

    Loose on headers on purpose — the columns are recognised by name
    (repo / qué hace|what / expone|provides / consume) wherever they sit, so
    the owner's own table survives translation and reordering.
    """
    text = None
    for name in ("ddw-family.md", "familia.md"):
        try:
            text = open(os.path.join(root, name), encoding="utf-8").read()
            break
        except OSError:
            continue
    if text is None:
        return None
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
            # Keys in priority order, so a table carrying both "Expone" and
            # "Qué hace" maps Provides to the seam, not to the description.
            for k in keys:
                for h in headers:
                    if k in h:
                        return re.sub(r"[`*]", "", row.get(h, "")).strip() or "none"
            return "none"
        rows.append({"name": name,
                     "provides": col("expone", "provides", "hace", "what"),
                     "consumed by": col("consumed by", "consumen", "consumido"),
                     "consumes": col("consume")})
    return rows or None


def _section_text(fields, family, ws_slug):
    lines = ["## Repo family", "", "| Field | Value |", "|---|---|",
             "| Family | %s |" % family,
             "| Workspace | %s |" % ws_slug,
             "| Provides | %s |" % fields["provides"],
             "| Consumed by | %s |" % fields["consumed by"],
             "| Consumes | %s |" % fields["consumes"]]
    return "\n".join(lines) + "\n"


def write_members(root, local, ws_slug, push=False):
    """Stamp each member clone's `## Repo family` from the workspace's map.

    Returns how many members changed, or -1 when the map cannot be read. Only
    the section is touched; a clone with no AGENTS.md gets a minimal one whose
    only content is the section — the rest of the file is that repo's to grow.
    Each change is committed IN THAT CLONE under the user's git identity, and
    the push is printed rather than taken unless --push: an unpushed commit is
    visible and reversible, which is what an administrative bulk edit owes.
    """
    rows = familia_map(root)
    if rows is None:
        print("family_catalog: --write-members reads the authored map from ddw-family.md "
              "in the workspace, and there is none (or it has no table).", file=sys.stderr)
        return -1
    own = family_section(open(os.path.join(root, "AGENTS.md"), encoding="utf-8").read())
    family = (own or {}).get("family", "familia")
    ws_name = ws_slug.split("/", 1)[-1]
    changed = 0
    for r in rows:
        if r["name"] == ws_name:
            continue
        clone = os.path.join(local, r["name"])
        agents = os.path.join(clone, "AGENTS.md")
        if not os.path.isdir(clone):
            print("  ⚠ %s: no clone under %s — clone it and re-run" % (r["name"], local))
            continue
        # A clone standing on a ticket branch — or mid-ticket by its DDW state
        # — is somebody's work in flight, and a sync commit landing on THEIR
        # branch rides their pull request as noise. Measured the night this
        # mode was written: the sync committed onto a child pipeline's branch
        # while it was running. Skip and say so; the sync lands on the next
        # run, once that repo is back on its default branch.
        head = subprocess.run(["git", "-C", clone, "branch", "--show-current"],
                              capture_output=True, text=True).stdout.strip()
        default = subprocess.run(
            ["git", "-C", clone, "symbolic-ref", "--quiet", "--short",
             "refs/remotes/origin/HEAD"], capture_output=True, text=True
        ).stdout.strip().split("/")[-1]
        if not default:
            # No origin to ask. `main` as a guess skipped every clone whose
            # git initialises `master` — measured in CI, where the runner's
            # git does exactly that and the sync silently stamped nobody. A
            # repo with ONE branch is standing on its default by definition;
            # only with several is there a work branch to protect.
            branches = [b.strip() for b in subprocess.run(
                ["git", "-C", clone, "branch", "--format=%(refname:short)"],
                capture_output=True, text=True).stdout.splitlines() if b.strip()]
            default = (head if len(branches) <= 1
                       else "main" if "main" in branches
                       else "master" if "master" in branches else head)
        mid_ticket = False
        try:
            st = json.load(open(os.path.join(clone, ".ddw-state.json"), encoding="utf-8"))
            mid_ticket = (st or {}).get("phase", "IDLE") != "IDLE"
        except (OSError, ValueError):
            pass
        if head not in ("", default) or mid_ticket:
            print("  ⏸ %s: mid-ticket (rama %s%s) — salteado; sincroniza cuando "
                  "vuelva a %s" % (r["name"], head or "?",
                                   ", pipeline activo" if mid_ticket else "", default))
            continue
        try:
            text = open(agents, encoding="utf-8").read()
        except OSError:
            text = "# %s" % r["name"] + 2 * chr(10)
        section = _section_text(r, family, ws_slug)
        m = re.search(r"^##\s+Repo family\s*$", text, re.MULTILINE | re.IGNORECASE)
        if m:
            body = text[m.start():]
            nxt = re.search(r"^##\s+", body[3:], re.MULTILINE)
            end = m.start() + 3 + nxt.start() if nxt else len(text)
            new_text = text[:m.start()] + section + chr(10) + text[end:].lstrip(chr(10))
        else:
            new_text = text.rstrip(chr(10)) + 2 * chr(10) + section
        if new_text == text:
            continue
        with open(agents, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        subprocess.run(["git", "-C", clone, "add", "AGENTS.md"], capture_output=True)
        c = subprocess.run(["git", "-C", clone, "commit", "-m",
                            "docs: sección Repo family sincronizada desde %s" % ws_name],
                           capture_output=True, text=True)
        if c.returncode == 0:
            changed += 1
            if push:
                pu = subprocess.run(["git", "-C", clone, "push"], capture_output=True,
                                    text=True, timeout=60)
                print("  ✓ %s: sección escrita, commiteada%s" % (
                    r["name"], " y pusheada" if pu.returncode == 0
                    else " — PUSH FALLÓ, corré: git -C %s push" % clone))
            else:
                print("  ✓ %s: sección escrita y commiteada — push pendiente: "
                      "git -C %s push" % (r["name"], clone))
        else:
            print("  ⚠ %s: no se pudo commitear (%s)" % (r["name"], c.stderr.strip()[:80]))
    print("family_catalog: %d miembro(s) sincronizados desde el mapa de familia." % changed)
    return changed


def _org_repos(org):
    """EVERY repository of `org`, from the forge's own paginated listing.

    The completeness of the whole sweep rests on this list being the forge's,
    not anyone's memory — 200-repo pages walked to the end. Returns (names,
    None) or (None, why)."""
    raw = _gh("api", "orgs/%s/repos" % org, "--paginate", "--jq", ".[].name",
              timeout=300)
    if raw is None:
        raw = _gh("api", "users/%s/repos" % org, "--paginate", "--jq", ".[].name",
                  timeout=300)
    if raw is None:
        return None, "gh could not list %s's repositories" % org
    return sorted({n.strip() for n in raw.splitlines() if n.strip()}), None


MAP_BEGIN = "<!-- BEGIN DDW FAMILY MAP -->"
MAP_END = "<!-- END DDW FAMILY MAP -->"


def _seed_map(family, ws_slug, members):
    """A ddw-family.md born from the declarations — a SEED for the owner to
    grow (descriptions, decisions), with the member table in a managed block."""
    lines = ["# Familia %s" % family,
             "",
             "Mapa de la familia. El bloque entre marcadores se regenera con "
             "`family_catalog.py`; todo lo demás es tuyo.",
             "",
             MAP_BEGIN,
             "| Repo | Provides | Consumed by | Consumes |",
             "|---|---|---|---|"]
    for m in members:
        lines.append("| %s | %s | %s | %s |"
                     % (m["name"], m["provides"], m["consumed by"], m["consumes"]))
    lines += [MAP_END, ""]
    return "\n".join(lines)


def bootstrap(org, write=False):
    """The whole organization in one auditable pass, no clone anywhere.

    The forge lists every repo; each repo's AGENTS.md is read by API (one
    small file, not a checkout); membership is what each repo DECLARES —
    the user's file flips the switch, never this sweep. Every repo lands in
    exactly one bucket and every bucket is printed: members by family,
    standalones counted, unreachables NAMED with their reason — a truncated
    or partial pass must be visible, never a smaller total in green.

    Without --write this is a preview. With it, each family whose workspace
    has no map yet gets a seed `ddw-family.md` published as a one-approve PR
    (index territory — the leash merges it on the user's word); a workspace
    that already has a map is never rewritten: drift is reported for its
    owner to fold in."""
    names, err = _org_repos(org)
    if err:
        print("family_catalog: " + err, file=sys.stderr)
        return 2
    families, standalone, unreachable = {}, [], []
    for name in names:
        text, sha = fetch_remote("%s/%s" % (org, name))
        if text is None:
            unreachable.append((name, sha))
            continue
        fields = family_section(text)
        if not fields or "workspace" not in fields:
            standalone.append(name)
            continue
        ws = re.sub(r"\s*\(.*\)$", "", fields["workspace"]).strip()
        families.setdefault(ws, []).append({
            "name": name,
            "family": fields.get("family", "?"),
            "provides": fields.get("provides", "none"),
            "consumed by": fields.get("consumed by", "none"),
            "consumes": fields.get("consumes", "none")})

    print("family_catalog: %d repos listados por el forge · %d leídos · "
          "%d sin sección de familia (standalone) · %d inalcanzables."
          % (len(names), len(names) - len(unreachable), len(standalone),
             len(unreachable)))
    for name, why in unreachable:
        print("  ✗ %s — inalcanzable: %s (reintentá; no es lo mismo que "
              "'sin familia')" % (name, why))
    for ws in sorted(families):
        members = families[ws]
        fam = members[0]["family"]
        print("\nFamilia %s — workspace %s, %d miembro(s):" % (fam, ws, len(members)))
        for m in members:
            print("  · %-24s provee: %s" % (m["name"], m["provides"]))
        ws_name = ws.rsplit("/", 1)[-1]
        if ws_name not in names:
            print("  ⚠ el workspace %s no es un repo de %s — la familia declara "
                  "un centro que el forge no lista" % (ws, org))
        if len(members) == 1:
            print("  ⚠ familia de un solo miembro — ¿seam real o sección huérfana?")
    if not families:
        print("\nNingún repo declara `## Repo family` — no hay familias que mapear.")

    if not write:
        print("\n(preview — nada escrito. Con --write, cada familia sin mapa "
              "recibe su ddw-family.md como PR de un solo aprobado.)")
        return 0

    import tempfile
    for ws in sorted(families):
        members = families[ws]
        tmp = tempfile.mkdtemp(prefix="ddw-bootstrap-")
        r = subprocess.run(["gh", "repo", "clone", ws, tmp, "--", "--depth", "5"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print("  ✗ %s: clone falló — %s" % (ws, (r.stderr or "")[:150]))
            continue
        existing = next((n for n in ("ddw-family.md", "familia.md")
                         if os.path.isfile(os.path.join(tmp, n))), None)
        if existing:
            have = {r2["name"] for r2 in (familia_map(tmp) or [])}
            declared = {m["name"] for m in members}
            missing, extra = sorted(declared - have), sorted(have - declared)
            if missing or extra:
                print("  ⚠ %s ya tiene %s — DERIVA (no lo reescribo): faltan %s · "
                      "sobran %s" % (ws, existing, missing or "-", extra or "-"))
            else:
                print("  ✓ %s: %s al día." % (ws, existing))
            continue
        path = os.path.join(tmp, "ddw-family.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_seed_map(members[0]["family"], ws, members))
        branch = "chore/ddw-family-bootstrap"
        for cmd in (["git", "-C", tmp, "checkout", "-b", branch],
                    ["git", "-C", tmp, "add", "ddw-family.md"],
                    ["git", "-C", tmp, "commit", "-m",
                     "docs: ddw-family.md — mapa semilla del bootstrap"],
                    ["git", "-C", tmp, "push", "-u", "origin", branch]):
            c = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if c.returncode != 0:
                print("  ✗ %s: %s falló — %s" % (ws, " ".join(cmd[3:4]),
                                                 (c.stderr or "")[:150]))
                break
        else:
            pr = subprocess.run(["gh", "pr", "create", "--repo", ws, "--head", branch,
                                 "--title", "🗺️ ddw-family.md: mapa semilla",
                                 "--body", "Seed map from the org bootstrap. "
                                 "Documents only — mergeable by the one-approve "
                                 "leash (family_index_pr.py merge)."],
                                capture_output=True, text=True, cwd=tmp, timeout=300)
            m2 = re.search(r"/pull/(\d+)", (pr.stdout or "") + (pr.stderr or ""))
            print("  ✓ %s: PR #%s abierto — con tu 'aprobado': family_index_pr.py "
                  "merge --pr %s" % (ws, m2.group(1) if m2 else "?",
                                     m2.group(1) if m2 else "?"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--owner", default=None)
    ap.add_argument("--repos", default=None)
    ap.add_argument("--local", default=None,
                    help="directory holding sibling clones; no forge reads")
    ap.add_argument("--root", default=".", help="the workspace repo root")
    ap.add_argument("--write-members", action="store_true",
                    help="propagate ddw-family.md into each member clone's AGENTS.md "
                         "(requires --local), committing in each clone")
    ap.add_argument("--push", action="store_true",
                    help="with --write-members: also push each member commit")
    ap.add_argument("--org", default=None,
                    help="organization sweep: list EVERY repo at the forge, read "
                         "each AGENTS.md by API (no clones), report families / "
                         "standalones / unreachables — re-run any time; that IS "
                         "the refresh")
    ap.add_argument("--write", action="store_true",
                    help="with --org: publish a seed ddw-family.md as a "
                         "one-approve PR for each family that has no map yet")
    args = ap.parse_args()

    if args.org:
        sys.exit(bootstrap(args.org, write=args.write))

    root = os.path.abspath(args.root)
    try:
        own_agents = open(os.path.join(root, "AGENTS.md"), encoding="utf-8").read()
    except OSError:
        print("family_catalog: no AGENTS.md here. Run this standing in the family's "
              "workspace repo — the one every member's `Workspace` field names.",
              file=sys.stderr)
        sys.exit(2)
    own = family_section(own_agents)
    if not own or "workspace" not in own:
        print("family_catalog: this repo's AGENTS.md has no `## Repo family` section "
              "naming a Workspace, so there is no family to catalog from here.",
              file=sys.stderr)
        sys.exit(2)
    ws_slug = re.sub(r"\s*\(.*\)$", "", own["workspace"]).strip()
    owner = args.owner or (ws_slug.split("/", 1)[0] if "/" in ws_slug else None)
    if not owner and not args.repos and not args.local:
        print("family_catalog: cannot tell whose repos to enumerate — the Workspace "
              "field carries no owner/ slug. Pass --owner, --repos or --local.",
              file=sys.stderr)
        sys.exit(2)

    if args.write_members:
        if not args.local:
            print("family_catalog: --write-members needs --local <dir> — the sections "
                  "are written in the member CLONES, committed under your own git "
                  "identity, and pushed only when you say --push.", file=sys.stderr)
            sys.exit(2)
        n = write_members(root, args.local, ws_slug, push=args.push)
        if n < 0:
            sys.exit(2)

    cat_path = os.path.join(root, CATALOG_REL)
    try:
        current = open(cat_path, encoding="utf-8").read()
    except OSError:
        current = ""

    ws_name = ws_slug.split("/", 1)[-1]
    rows, gone = [], []
    for name in candidate_repos(owner, args.repos, prior_rows(current)):
        if args.local:
            text, sha = fetch_local(args.local, name)
        else:
            text, sha = fetch_remote("%s/%s" % (owner, name))
        if text is None:
            if name in prior_rows(current):
                rows.append({"name": name, "provides": "(unreachable: %s)" % sha,
                             "consumed by": "", "consumes": "", "sha": "?"})
            continue
        fields = family_section(text)
        member = fields and ws_name in re.sub(r"\s*\(.*\)$", "",
                                              fields.get("workspace", ""))
        if not member:
            if name in prior_rows(current) and name != ws_name:
                gone.append((name, "no longer declares this family"))
            continue
        rows.append({"name": name,
                     "provides": fields.get("provides", ""),
                     "consumed by": fields.get("consumed by", "none"),
                     "consumes": fields.get("consumes", "none"),
                     "sha": sha})

    block = build_block(rows, gone, owner or "(explicit list)",
                        "local clones" if args.local else "forge")

    if BEGIN in current:
        head = current.split(BEGIN, 1)[0]
        tail = current.split(END, 1)[1] if END in current else "\n"
        new_text = head + block + tail
    else:
        new_text = ("# Family catalog\n\nDerived from each member repo's "
                    "`## Repo family` section. Everything outside the markers "
                    "is yours; everything inside is regenerated.\n\n" + block + "\n")

    def strip_stamp(t):
        return re.sub(r"generated-at: [^ ]+", "generated-at: *", t)

    if args.check:
        if strip_stamp(current) == strip_stamp(new_text):
            print("family_catalog: fresh — every row matches its repo's AGENTS.md.")
            sys.exit(0)
        print("family_catalog: STALE — a member's AGENTS.md changed since this was "
              "generated (or membership moved). Re-run without --check to regenerate.",
              file=sys.stderr)
        sys.exit(3)

    if strip_stamp(current) == strip_stamp(new_text):
        print("family_catalog: no changes — %d repo(s), catalog already current." % len(rows))
        sys.exit(0)
    os.makedirs(os.path.dirname(cat_path), exist_ok=True)
    with open(cat_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    print("family_catalog: regenerated %s — %d member(s)%s." % (
        CATALOG_REL, len(rows),
        ", %d departure(s) annotated" % len(gone) if gone else ""))
    for r in rows:
        print("  · %s — %s" % (r["name"], r["provides"]))


if __name__ == "__main__":
    main()
