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

    python3 family_catalog.py --sweep --org ACME [--facts-out FILE]
        # the MECHANICAL sweep, the deterministic half of the derived store:
        # every repo's tree read from its TARBALL (never a clone), and the
        # facts a row of prose may lean on recorded with THE PATH each one
        # came from and the SHA the repo was read at. No model runs here and
        # no prose is written: this is what the prose is later held to.

    python3 family_catalog.py --admit STORE_DIR [--facts FILE]
        # the ADMISSION gate over the prose half: renglones.md and fichas/
        # judged against the sweep's facts. Coverage (every swept repo has a
        # row), no invention (no row names a repo nobody read), and every
        # claim citing a file the sweep FOUND, at the SHA it was read. It does
        # not check that a claim is true — a file that exists is not a claim
        # that holds — and the run says so out loud.

    python3 family_catalog.py --stale STORE_DIR [--org ACME]
        # the REFRESH question, and the reason this is affordable at a
        # thousand repos: not "did this repo move" (almost always yes, and
        # worthless) but "did it move where a row LEANS". Adds/deletes, a
        # cited file, or a structural path make a row stale; anything else
        # leaves it true. It names which rows to re-sweep, and why each one.

Exit: 0 = fresh / regenerated / swept / admitted / nothing stale · 2 = cannot
run (no workspace section, no gh) · 3 = --check found it stale, --admit refused
the store, or --stale found rows to re-read.
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


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


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
    listed, err = _org_repos(owner)
    if listed is None:
        # The paginated listing failed; the flat call is better than nothing,
        # but its 200-repo page is a known cap — say so where it happens.
        raw = _gh("repo", "list", owner, "--limit", "200", "--json", "name",
                  "--jq", ".[].name")
        if raw:
            page = [n.strip() for n in raw.splitlines() if n.strip()]
            names.update(page)
            if len(page) >= 200:
                print("  ⚠ la lista plana de %s tocó su tope de 200 — puede "
                      "faltar gente; reintentá cuando el forge conteste la "
                      "paginada." % owner)
    else:
        names.update(listed)
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
            # And WHOLE-WORD header match: the key `consume` must never be
            # satisfied by the `consumed by` column — a substring match read
            # Consumes from the wrong cell whenever Consumed-by came first.
            for k in keys:
                for h in headers:
                    if h == k or re.search(r"(?:^|\s)%s(?:$|\s)" % re.escape(k), h):
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


# ── The mechanical sweep: what a SCRIPT can know about a repo ────────────────
#
# The renglón and the ficha are prose, and prose is the model's half. This is
# the other half, and it comes first: every fact the prose is allowed to lean
# on, gathered by grep-and-walk over the repo's own files, each one carrying
# THE PATH it came from. The path is not decoration — it is what makes the
# later admission gate possible ("a claim whose citation does not resolve does
# not enter the store") and what makes the refresh cheap ("re-read this repo
# only when one of the paths its row cites has moved").
#
# Read from a TARBALL, never a clone: looking at a repository needs its files,
# not its history, and at organisation scale the history is the whole cost.

STRUCTURAL = (
    "openapi", "swagger", ".proto", "/routes/", "/controllers/", "/handlers/",
    "/api/", "/events/", "/migrations/", "/schemas/", "schema.", "Dockerfile",
    "docker-compose", ".github/workflows/", "serverless.yml", "terraform",
)

MANIFESTS = ("package.json", "pyproject.toml", "go.mod", "pom.xml",
             "Cargo.toml", "composer.json", "build.gradle")

_STRUCTURAL_CAP = 200


def _gh_bytes(*args, timeout=300):
    """gh, for an answer that is not text. None when it could not answer."""
    try:
        out = subprocess.run(["gh", *args], capture_output=True,
                             timeout=timeout, stdin=subprocess.DEVNULL)
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def _tarball_tree(slug, dest):
    """Extract the repo's default branch under `dest`. (root, None) or (None, why).

    Guarded on the way in: a member of the archive whose path escapes `dest`
    is refused and the whole extraction fails. A sweep that can be made to
    write outside its scratch directory by the repository it is reading is not
    a sweep, it is a delivery mechanism.
    """
    blob = _gh_bytes("api", "repos/%s/tarball" % slug)
    if not blob:
        return None, "the forge did not send a tarball"
    import io
    import tarfile
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            root = os.path.realpath(dest)
            for m in tf.getmembers():
                target = os.path.realpath(os.path.join(dest, m.name))
                if target != root and not target.startswith(root + os.sep):
                    return None, "the tarball tried to write outside the sweep"
                if m.issym() or m.islnk():
                    continue
            tf.extractall(dest)
    except Exception as exc:                                  # noqa: BLE001
        return None, "unreadable tarball: %s" % str(exc)[:120]
    tops = [d for d in os.listdir(dest) if os.path.isdir(os.path.join(dest, d))]
    if len(tops) != 1:
        return None, "the tarball did not unpack into one directory"
    return os.path.join(dest, tops[0]), None


def _read_head(path, limit=400):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(4000)
    except OSError:
        return None
    body = "\n".join(ln for ln in text.splitlines() if ln.strip())
    return body[:limit] or None


def sweep_tree(root):
    """The facts, from the extracted tree. Every one of them names its path."""
    files, structural, manifests = 0, [], {}
    readme = None
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules",
                                                "__pycache__", ".venv", "vendor")]
        for n in names:
            files += 1
            full = os.path.join(base, n)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            probe = "/" + rel
            if any(frag.lower() in probe.lower() for frag in STRUCTURAL):
                if len(structural) < _STRUCTURAL_CAP:
                    structural.append(rel)
            if n in MANIFESTS and len(manifests) < 40:
                manifests[rel] = _read_head(full, 300)
            if readme is None and n.lower() in ("readme.md", "readme.rst",
                                                "readme.txt"):
                readme = {"path": rel, "head": _read_head(full)}
    tops = sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d)) and not d.startswith("."))
    return {"files": files, "top_dirs": tops[:40],
            "structural_paths": sorted(structural),
            "structural_truncated": len(structural) >= _STRUCTURAL_CAP,
            "manifests": manifests, "readme": readme}


def sweep_repo(slug):
    """One repo's facts, read at its default branch from the forge.

    The SHA is recorded beside the facts and is the whole point of the refresh:
    a row read at a commit can be compared with the commit the repo is on now,
    so "this row is 200 commits behind" is a fact the gate can state instead of
    a freshness nobody ever checks.
    """
    import shutil
    import tempfile
    meta = _gh("api", "repos/%s" % slug,
               "--jq", "{default_branch, language, description}")
    head = _gh("api", "repos/%s/commits?per_page=1" % slug, "--jq", ".[0].sha")
    facts = {"slug": slug, "name": slug.rsplit("/", 1)[-1],
             "sha": (head or "").strip()[:7] or None,
             "default_branch": None, "language": None, "description": None,
             "read_at": _now_iso(), "unreadable": None}
    if meta:
        try:
            facts.update({k: v for k, v in json.loads(meta).items()
                          if k in ("default_branch", "language", "description")})
        except Exception:                                     # noqa: BLE001
            pass
    if not facts["sha"]:
        facts["unreadable"] = "the forge did not name a head commit"
        return facts
    tmp = tempfile.mkdtemp(prefix="ddw-sweep-")
    try:
        root, why = _tarball_tree(slug, tmp)
        if root is None:
            facts["unreadable"] = why
            return facts
        facts.update(sweep_tree(root))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return facts


def sweep(org, repos, out_path):
    """The organisation's facts in one pass — the deterministic half of the
    store, written where the prose half will be built from it.

    Every repo lands in the file, readable or not: a sweep that silently drops
    what it could not read reports a smaller organisation in green, which is
    the failure this method spends most of its checks preventing.
    """
    if repos:
        names = [r.strip() for r in repos.split(",") if r.strip()]
    else:
        names, why = _org_repos(org)
        if names is None:
            print("family_catalog: %s" % why, file=sys.stderr)
            return 2
    owner = org or (names[0].split("/", 1)[0] if names and "/" in names[0] else None)
    report = {"owner": owner, "generated_at": _now_iso(), "repos": []}
    for name in names:
        slug = name if "/" in name else "%s/%s" % (owner, name)
        report["repos"].append(sweep_repo(slug))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    ok = [r for r in report["repos"] if not r["unreadable"]]
    print("family_catalog: swept %d repo(s) of %s · %d read, %d unreadable · %s"
          % (len(report["repos"]), owner or "?", len(ok),
             len(report["repos"]) - len(ok), out_path))
    for r in report["repos"]:
        if r["unreadable"]:
            print("  ⚠ %s: %s" % (r["name"], r["unreadable"]))
        else:
            print("  · %s @ %s — %d file(s), %d structural path(s)"
                  % (r["name"], r["sha"], r["files"], len(r["structural_paths"])))
    print("These are FACTS, not a catalog: every row of prose written from this "
          "file has to cite one of the paths in it.")
    return 0


# ── The prose half, and the gate it has to pass ──────────────────────────────
#
# The sweep above gathers facts. The RENGLÓN (one line per repo, so a question
# can pick which repos matter) and the FICHA (half a page for a repo that was
# picked) are prose, and prose is the model's half. This is the admission gate
# it has to pass to enter the store, and it checks exactly three things — the
# three a script CAN check:
#
#   1. COVERAGE — every repo the sweep read has a row. A store that quietly
#      omits repos answers "who do I hit?" over a smaller organisation, in
#      green, which is the failure mode the whole method is built against.
#   2. NO INVENTION — no row names a repo the sweep never saw.
#   3. CITATIONS RESOLVE — every claim in a ficha names a file, and that file
#      is one the sweep actually found in that repo at that SHA.
#
# What it does NOT check, said plainly because the receipt says it too: that a
# claim is TRUE. A file that exists is not a claim that holds. What the gate
# buys is that every claim points at something real in a real commit, that the
# whole organisation is accounted for, and that a ficha written against an
# older commit cannot pass as current. The truth of the sentence stays a human
# reading, and the store says which commit to read it against.

ROWS_BEGIN = "<!-- BEGIN DDW ROWS -->"
ROWS_END = "<!-- END DDW ROWS -->"
FICHA_BEGIN = "<!-- BEGIN DDW FICHA -->"
FICHA_END = "<!-- END DDW FICHA -->"

_FICHA_STAMP = re.compile(r"<!--\s*repo:\s*(?P<repo>[^\s·]+)\s*·\s*"
                          r"sha:\s*(?P<sha>[0-9a-f]+)\s*-->")


def _managed(text, begin, end):
    """The lines inside a managed block, or None when there is no block."""
    if begin not in text or end not in text:
        return None
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return [ln.strip() for ln in body.splitlines() if ln.strip()]


def _table_rows(lines):
    """The DATA rows of a markdown table.

    A header is whatever sits immediately above the `---` rule, so it is
    dropped when the rule is met, not by guessing at its words. Guessing was
    the first version and it let `| Repo | SHA |` through as a repository
    named "Repo" — a gate that invents a finding is as useless as one that
    misses a real one.
    """
    out = []
    for ln in lines:
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if cells and set("".join(cells)) <= set("-: ") and "-" in "".join(cells):
            if out:
                out.pop()
            continue
        out.append(cells)
    return out


def known_paths(facts_repo):
    """Every path the sweep actually saw in this repo — what a citation may name.

    Top-level directories count: "the work lives under `src/api/`" is a claim
    about a place, and refusing it would push the prose towards vaguer
    sentences that cite nothing, which is the opposite of the point.
    """
    paths = set(facts_repo.get("structural_paths") or [])
    paths |= set((facts_repo.get("manifests") or {}).keys())
    readme = facts_repo.get("readme") or {}
    if readme.get("path"):
        paths.add(readme["path"])
    for d in facts_repo.get("top_dirs") or []:
        paths.add(d)
        paths.add(d + "/")
    return paths


def _cited(path, paths):
    """A citation resolves when the sweep saw that exact file, or saw the
    directory it names. Nothing fuzzier: a citation that matches by prefix
    would let `src/` stand in for a file nobody looked at."""
    p = path.strip().strip("`").lstrip("./")
    if p in paths:
        return True
    if p.endswith("/") and p.rstrip("/") in paths:
        return True
    return False


def admit(facts_path, store_dir):
    """The gate: coverage, no invention, and every citation resolving.

    Exit 0 admits the store as written. Exit 3 refuses it and NAMES every
    reason — a gate that stops at the first problem makes the author walk it
    once per defect, and a gate people walk many times is a gate people route
    around.
    """
    try:
        with open(facts_path, encoding="utf-8") as fh:
            facts = json.load(fh)
    except (OSError, ValueError) as exc:
        print("family_catalog: cannot read the facts at %s (%s) — run --sweep "
              "first; the gate judges prose AGAINST facts, never alone."
              % (facts_path, exc), file=sys.stderr)
        return 2

    by_name = {r["name"]: r for r in facts.get("repos", [])}
    readable = {n: r for n, r in by_name.items() if not r.get("unreadable")}
    problems, checked = [], 0

    rows_path = os.path.join(store_dir, "renglones.md")
    try:
        rows_text = open(rows_path, encoding="utf-8").read()
    except OSError:
        print("family_catalog: no renglones.md under %s — the store's index is "
              "the one file the gate cannot do without." % store_dir,
              file=sys.stderr)
        return 3
    lines = _managed(rows_text, ROWS_BEGIN, ROWS_END)
    if lines is None:
        problems.append("renglones.md has no managed block (%s / %s)"
                        % (ROWS_BEGIN, ROWS_END))
        rows = []
    else:
        rows = _table_rows(lines)

    seen = {}
    for cells in rows:
        name = cells[0].strip().rsplit("/", 1)[-1]
        seen[name] = cells
        if name not in by_name:
            problems.append("renglones.md names `%s`, which the sweep never "
                            "saw — invented rows are the failure this gate "
                            "exists for" % name)
        elif len(cells) > 1 and cells[1].strip():
            claimed, real = cells[1].strip(), (by_name[name].get("sha") or "")
            if real and claimed != real:
                problems.append("renglones.md has `%s` at %s, the sweep read it "
                                "at %s — a row written against another commit "
                                "is not this repo's row"
                                % (name, claimed, real))
    for name in sorted(readable):
        if name not in seen:
            problems.append("`%s` was swept and has no row — a store that omits "
                            "repos answers over a smaller organisation" % name)
        else:
            checked += 1

    fichas_dir = os.path.join(store_dir, "fichas")
    for fname in sorted(os.listdir(fichas_dir)) if os.path.isdir(fichas_dir) else []:
        if not fname.endswith(".md"):
            continue
        text = open(os.path.join(fichas_dir, fname), encoding="utf-8").read()
        stamp = _FICHA_STAMP.search(text)
        if not stamp:
            problems.append("fichas/%s carries no `repo:` / `sha:` stamp — a "
                            "ficha that does not say what it describes, and at "
                            "which commit, cannot be judged at all" % fname)
            continue
        name = stamp.group("repo").rsplit("/", 1)[-1]
        if name not in by_name:
            problems.append("fichas/%s describes `%s`, which the sweep never saw"
                            % (fname, name))
            continue
        real = by_name[name].get("sha") or ""
        if real and stamp.group("sha") != real:
            problems.append("fichas/%s is written at %s, the sweep read `%s` at "
                            "%s" % (fname, stamp.group("sha"), name, real))
            continue
        body = _managed(text, FICHA_BEGIN, FICHA_END)
        if body is None:
            problems.append("fichas/%s has no managed block — claims outside "
                            "one are prose nothing holds" % fname)
            continue
        claims = _table_rows(body)
        if not claims:
            problems.append("fichas/%s states no claim with a file beside it — "
                            "an uncitable ficha is a summary, and the store "
                            "does not take summaries" % fname)
            continue
        paths = known_paths(by_name[name])
        for cells in claims:
            if len(cells) < 2 or not cells[1].strip():
                problems.append("fichas/%s: the claim %r cites no file"
                                % (fname, cells[0][:60]))
                continue
            if not _cited(cells[1], paths):
                problems.append("fichas/%s cites `%s`, which the sweep did not "
                                "find in `%s` at %s" % (fname, cells[1].strip(),
                                                        name, real or "?"))
            else:
                checked += 1

    if problems:
        print("family_catalog: the store is REFUSED — %d problem(s):"
              % len(problems), file=sys.stderr)
        for p in problems:
            print("  ✗ %s" % p, file=sys.stderr)
        return 3
    print("family_catalog: the store is admitted — %d repo(s) swept, every one "
          "with a row, no invented row, %d citation(s) resolved at the SHA they "
          "were read." % (len(by_name), checked))
    print("What this proves: every claim points at a real file in a real "
          "commit, and the whole sweep is accounted for. NOT that a claim is "
          "true — that stays a reading, and the SHA says which one.")
    return 0


# ── The refresh: which rows are actually stale ───────────────────────────────
#
# At organisation scale the sweep is affordable once and unaffordable on a
# schedule: a thousand repositories move every week, and re-reading all of them
# because their SHA changed is the same cost as never having indexed anything.
#
# The SHA answers "did this repo move", which is almost always yes and is
# therefore worthless on its own. The question that matters is "did it move
# somewhere this row DEPENDS on", and the citations make it answerable: a row
# is stale when the diff since it was read touches a file that row cites, adds
# or deletes any file, or lands on a structural path. A commit inside a
# function nobody cited leaves the row true, and the row is left alone.
#
# The three filters are not a proof, and the report says which one fired. What
# closes the remaining gap is the full re-sweep, run cold, and the fact that
# every row carries the commit it was read at — so "this row is behind" is
# always answerable, even when the filters missed.

_ADD_DELETE = ("added", "removed", "renamed")


def _forge_head_sha(slug):
    raw = _gh("api", "repos/%s/commits?per_page=1" % slug, "--jq", ".[0].sha",
              timeout=30)
    return (raw or "").strip() or None


def _diff_files(slug, base, head):
    """(files, why). files is [(path, status)]; why is set when the comparison
    could not be trusted — and an untrusted comparison is treated as stale, not
    as clean: the failure of a freshness check must never read as fresh."""
    raw = _gh("api", "repos/%s/compare/%s...%s" % (slug, base, head),
              "--jq", "{n: .files | length, total: .total_commits, "
                      "f: [.files[] | {p: .filename, s: .status}]}", timeout=60)
    if raw is None:
        return [], "the forge could not compare %s...%s" % (base, head)
    try:
        data = json.loads(raw)
    except ValueError:
        return [], "the forge's comparison was unreadable"
    files = [(e["p"], e["s"]) for e in data.get("f") or []]
    if len(files) >= 300:
        return files, "the comparison hit the forge's file limit"
    return files, None


def ficha_citations(store_dir, name):
    """The paths a repo's ficha leans on — the rows of its claims table."""
    path = os.path.join(store_dir, "fichas", name + ".md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return set()
    body = _managed(text, FICHA_BEGIN, FICHA_END)
    if body is None:
        return set()
    return {cells[1].strip().strip("`").lstrip("./")
            for cells in _table_rows(body) if len(cells) > 1 and cells[1].strip()}


def stale(store_dir, owner=None):
    """Which rows the store has to re-read, and WHY each one.

    Exit 0 when nothing is stale, 3 when something is — the `--check` shape,
    so a routine can run it and act on the code without parsing prose.
    """
    rows_path = os.path.join(store_dir, "renglones.md")
    try:
        rows_text = open(rows_path, encoding="utf-8").read()
    except OSError:
        print("family_catalog: no renglones.md under %s — nothing to refresh."
              % store_dir, file=sys.stderr)
        return 2
    lines = _managed(rows_text, ROWS_BEGIN, ROWS_END)
    rows = _table_rows(lines) if lines else []
    if not rows:
        print("family_catalog: renglones.md has no rows — run --sweep and write "
              "the store first.", file=sys.stderr)
        return 2

    verdicts = []
    for cells in rows:
        name = cells[0].strip().rsplit("/", 1)[-1]
        slug = cells[0].strip() if "/" in cells[0] else "%s/%s" % (owner or "?", name)
        was = cells[1].strip() if len(cells) > 1 else ""
        head = _forge_head_sha(slug)
        if not head:
            verdicts.append((name, "stale", "the forge did not answer — an "
                                            "unanswered freshness check is not "
                                            "freshness"))
            continue
        if was and head.startswith(was):
            verdicts.append((name, "fresh", "unmoved since %s" % was))
            continue
        files, why = _diff_files(slug, was, head)
        if why:
            verdicts.append((name, "stale", why))
            continue
        moved = {p for p, _ in files}
        added = sorted(p for p, st in files if st in _ADD_DELETE)
        cited = sorted(moved & ficha_citations(store_dir, name))
        structural = sorted(p for p in moved
                            if any(f.lower() in ("/" + p).lower()
                                   for f in STRUCTURAL))
        if added:
            verdicts.append((name, "stale", "files added or removed: %s"
                             % ", ".join(added[:3])))
        elif cited:
            verdicts.append((name, "stale", "a cited file moved: %s"
                             % ", ".join(cited[:3])))
        elif structural:
            verdicts.append((name, "stale", "a structural path moved: %s"
                             % ", ".join(structural[:3])))
        else:
            verdicts.append((name, "fresh", "%d file(s) moved, none cited or "
                                            "structural" % len(files)))

    dirty = [v for v in verdicts if v[1] == "stale"]
    print("family_catalog: %d row(s) checked · %d stale · %d fresh"
          % (len(verdicts), len(dirty), len(verdicts) - len(dirty)))
    for name, verdict, why in verdicts:
        print("  %s %s — %s" % ("✗" if verdict == "stale" else "·", name, why))
    if dirty:
        print("Re-sweep only these: --sweep --repos %s"
              % ",".join(n for n, _, _ in dirty))
        return 3
    print("Nothing to re-read. A repo that moved where no row leans is a repo "
          "whose row is still true.")
    return 0


MAP_BEGIN = "<!-- BEGIN DDW FAMILY MAP -->"
MAP_END = "<!-- END DDW FAMILY MAP -->"


def _seed_map(family, ws_slug, members):
    """A ddw-family.md born from the declarations — a SEED for the owner to
    grow (descriptions, decisions), with the member table in a managed block."""
    lines = ["# Familia %s" % family,
             "",
             "Mapa de la familia, nacido del bootstrap. Editalo libremente — "
             "el barrido (`family_catalog.py --org`) REPORTA la deriva contra "
             "lo declarado, nunca lo reescribe.",
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
            # "The repo has no AGENTS.md" and "the forge fell over" must
            # never read the same: one is a standalone, the other a retry.
            if _gh("api", "repos/%s/%s" % (org, name), "--jq", ".name") is not None:
                standalone.append(name)
            else:
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
        ws_short = ws.rsplit("/", 1)[-1]
        if existing:
            have = {r2["name"] for r2 in (familia_map(tmp) or [])}
            # The workspace declares itself, but authored maps list the
            # CHILDREN — counting the center as a member made every healthy
            # family read as drifted forever.
            declared = {m["name"] for m in members} - {ws_short}
            have -= {ws_short}
            missing, extra = sorted(declared - have), sorted(have - declared)
            if missing or extra:
                print("  ⚠ %s ya tiene %s — DERIVA (no lo reescribo): faltan %s · "
                      "sobran %s" % (ws, existing, missing or "-", extra or "-"))
            else:
                print("  ✓ %s: %s al día." % (ws, existing))
            continue
        path = os.path.join(tmp, "ddw-family.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_seed_map(members[0]["family"], ws,
                               [m for m in members if m["name"] != ws_short]))
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
                  "merge --pr %s --repo %s" % (ws, m2.group(1) if m2 else "?",
                                               m2.group(1) if m2 else "?", ws))
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
    ap.add_argument("--sweep", action="store_true",
                    help="the MECHANICAL sweep: read every repo's tree from its "
                         "tarball (never a clone) and record the facts a row of "
                         "prose is allowed to lean on, each one with the path it "
                         "came from and the SHA it was read at")
    ap.add_argument("--facts-out", default=".ddw-work/org-facts.json",
                    help="where --sweep writes its facts (default: "
                         ".ddw-work/org-facts.json)")
    ap.add_argument("--admit", default=None, metavar="STORE_DIR",
                    help="the ADMISSION gate: judge the store's prose "
                         "(renglones.md and fichas/) against the facts — every "
                         "swept repo has a row, no row invents a repo, and "
                         "every claim cites a file the sweep found at that SHA. "
                         "exit 0 admits, 3 refuses and names every reason")
    ap.add_argument("--facts", default=".ddw-work/org-facts.json",
                    help="with --admit: the facts to judge against")
    ap.add_argument("--stale", default=None, metavar="STORE_DIR",
                    help="the REFRESH question: which rows have to be re-read. "
                         "A row is stale when the diff since it was read adds or "
                         "removes a file, touches a file its ficha cites, or "
                         "lands on a structural path — a commit where no row "
                         "leans leaves the row true. exit 0 nothing stale, "
                         "3 something is")
    args = ap.parse_args()

    if args.stale:
        sys.exit(stale(args.stale, owner=args.org or args.owner))

    if args.admit:
        sys.exit(admit(args.facts, args.admit))

    if args.sweep:
        if not args.org and not args.repos:
            ap.error("--sweep needs --org ACME or --repos a,b,c: the list of "
                     "what to read is not something this script may invent")
        sys.exit(sweep(args.org, args.repos, args.facts_out))

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
        # The stamp AND the departure annotations: an annotated removal
        # carries its date and reappears in no later derivation, so leaving
        # it in the comparison made --check cry STALE right after a regen.
        t = re.sub(r"generated-at: [^ ]+", "generated-at: *", t)
        return re.sub(r"^\| ~~.*$", "", t, flags=re.MULTILINE)

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
