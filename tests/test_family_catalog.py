"""The family catalog: derived, annotated, and honest about staleness."""
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "ddw/scripts/family_catalog.py")

spec = importlib.util.spec_from_file_location("fc", SCRIPT)
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


AGENTS = """# un repo

## Stack

| Campo | Valor |
|---|---|
| Lenguaje | Python |

## Repo family

| Field | Value |
|---|---|
| Family | tienda-demo |
| Workspace | acme/tienda-workspace |
| Provides | REST API /api/v1 |
| Consumed by | tienda-bff |
| Consumes | none |

## Otra seccion
"""


def test_el_parser_lee_la_seccion_de_familia():
    f = fc.family_section(AGENTS)
    assert f["workspace"] == "acme/tienda-workspace"
    assert f["provides"] == "REST API /api/v1"
    assert f["consumed by"] == "tienda-bff"


def test_el_ejemplo_del_spec_parsea():
    """The worked example in docs/AGENTS-MD.md must parse — the lesson of the
    template its own gate rejects, one document over."""
    doc = open(os.path.join(ROOT, "docs/AGENTS-MD.md"), encoding="utf-8").read()
    m = re.search(r"## Repo family\n\n\| Field \| Value \|.*?\n\n", doc, re.S)
    assert m, "the spec no longer carries the worked example"
    f = fc.family_section(m.group(0))
    assert f and "workspace" in f, "the spec's own example does not parse"


def test_sin_seccion_devuelve_none():
    assert fc.family_section("# repo\n\n## Stack\n") is None


def _run(workspace, *args):
    return subprocess.run([sys.executable, SCRIPT, "--root", workspace, *args],
                          capture_output=True, text=True)


def _family(tmp_path):
    """A local family: workspace + two members + one outsider."""
    base = tmp_path
    for name, ws, extra in (
            ("ws", "acme/ws (este repo)", "| Provides | coordinación |"),
            ("alpha", "acme/ws", "| Provides | api |\n| Consumed by | beta |"),
            ("beta", "acme/ws", "| Provides | ui |\n| Consumes | alpha |")):
        d = base / name
        d.mkdir(exist_ok=True)
        (d / "AGENTS.md").write_text(
            "# %s\n\n## Repo family\n\n| Field | Value |\n|---|---|\n"
            "| Family | fam |\n| Workspace | %s |\n%s\n" % (name, ws, extra),
            encoding="utf-8")
    (base / "otro").mkdir(exist_ok=True)
    (base / "otro" / "AGENTS.md").write_text("# ajeno\n", encoding="utf-8")
    return str(base / "ws")


def test_deriva_y_es_idempotente(tmp_path):
    ws = _family(tmp_path)
    r = _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta,otro")
    assert r.returncode == 0, r.stderr
    cat = open(os.path.join(ws, "docs/ddw/family-catalog.md"), encoding="utf-8").read()
    assert "| alpha |" in cat and "| beta |" in cat and "| otro |" not in cat, \
        "membership is self-declared: the outsider joined, or a member is missing"
    r2 = _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta,otro")
    assert "no changes" in r2.stdout, "an unchanged family rewrote the file"


def test_check_detecta_un_agents_movido(tmp_path):
    ws = _family(tmp_path)
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta")
    assert _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta",
                "--check").returncode == 0
    a = tmp_path / "alpha" / "AGENTS.md"
    a.write_text(a.read_text().replace("| Provides | api |",
                                       "| Provides | api v2 |"), encoding="utf-8")
    r = _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta", "--check")
    assert r.returncode == 3, "a member's AGENTS.md moved and --check called it fresh"


def test_una_baja_queda_anotada_no_silenciosa(tmp_path):
    ws = _family(tmp_path)
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta")
    b = tmp_path / "beta" / "AGENTS.md"
    b.write_text("# beta se fue de la familia\n", encoding="utf-8")
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta")
    cat = open(os.path.join(ws, "docs/ddw/family-catalog.md"), encoding="utf-8").read()
    assert "~~beta~~" in cat and "no longer declares" in cat, \
        "a departure vanished silently instead of being annotated"


def test_lo_de_afuera_de_los_markers_es_del_usuario(tmp_path):
    ws = _family(tmp_path)
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta")
    p = os.path.join(ws, "docs/ddw/family-catalog.md")
    text = open(p, encoding="utf-8").read()
    open(p, "w", encoding="utf-8").write("MI NOTA ARRIBA\n" + text + "\nMI NOTA ABAJO\n")
    a = tmp_path / "alpha" / "AGENTS.md"
    a.write_text(a.read_text().replace("api", "api v3"), encoding="utf-8")
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta")
    out = open(p, encoding="utf-8").read()
    assert out.startswith("MI NOTA ARRIBA") and out.rstrip().endswith("MI NOTA ABAJO"), \
        "the managed block ate the user's own prose outside the markers"


def _git_family(tmp_path):
    ws = _family(tmp_path)
    (tmp_path / "ws" / "ddw-family.md").write_text(
        "# Familia\n\n| Repo | Qué hace | Expone | Consumed by | Consume |\n"
        "|---|---|---|---|---|\n"
        "| alpha | api | REST /v1 | beta | none |\n"
        "| beta | ui | pantallas | none | alpha |\n", encoding="utf-8")
    for name in ("alpha", "beta"):
        d = str(tmp_path / name)
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
            subprocess.run(["git", "-C", d, "config", k, v], check=True)
        subprocess.run(["git", "-C", d, "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", d, "commit", "-qm", "base"], check=True, capture_output=True)
    return ws


def test_write_members_estampa_y_commitea(tmp_path):
    """The owner's decision (2026-08-26): the map is authored centrally and
    the routine PROPAGATES it — a write into the member CLONES, committed
    under the user's own identity, pushes listed rather than taken."""
    ws = _git_family(tmp_path)
    r = _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta", "--write-members")
    assert r.returncode == 0, r.stderr
    a = (tmp_path / "alpha" / "AGENTS.md").read_text()
    assert "| Provides | REST /v1 |" in a and "| Consumed by | beta |" in a, \
        "the map's row did not land in the member's section: %s" % a
    log = subprocess.run(["git", "-C", str(tmp_path / "alpha"), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "Repo family" in log, "the member write was not committed in the member"
    assert "push" in r.stdout and "git -C" in r.stdout, \
        "the pending push is not named — an invisible bulk edit"


def test_write_members_es_idempotente(tmp_path):
    ws = _git_family(tmp_path)
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta", "--write-members")
    n1 = subprocess.run(["git", "-C", str(tmp_path / "alpha"), "rev-list", "--count", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta", "--write-members")
    n2 = subprocess.run(["git", "-C", str(tmp_path / "alpha"), "rev-list", "--count", "HEAD"],
                        capture_output=True, text=True).stdout.strip()
    assert n1 == n2, "an unchanged map produced a second commit in the member"


def test_write_members_no_toca_el_resto_del_agents(tmp_path):
    ws = _git_family(tmp_path)
    a = tmp_path / "alpha" / "AGENTS.md"
    a.write_text("# alpha\n\nMI PROSA PROPIA\n\n" + a.read_text().split("# alpha\n")[-1],
                 encoding="utf-8")
    _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta", "--write-members")
    out = a.read_text()
    assert "MI PROSA PROPIA" in out, "the sync ate the member's own prose"


def test_write_members_saltea_un_clon_a_mitad_de_ticket(tmp_path):
    """Measured live: the sync committed onto a running child pipeline's
    branch. A member standing off its default branch is skipped, out loud."""
    ws = _git_family(tmp_path)
    subprocess.run(["git", "-C", str(tmp_path / "alpha"), "checkout", "-qb",
                    "feat/T-1-algo"], check=True)
    r = _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta", "--write-members")
    assert "alpha" in r.stdout and "salteado" in r.stdout, r.stdout
    log = subprocess.run(["git", "-C", str(tmp_path / "alpha"), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "Repo family" not in log, "the sync landed on a ticket branch anyway"


def test_write_members_funciona_cuando_git_inicializa_master(tmp_path):
    """Measured in CI: the runner's git inits `master`, the guard's `main`
    guess read every clone as mid-ticket, and the sync silently stamped
    nobody. A single-branch clone is standing on its default by definition."""
    ws = _git_family(tmp_path)
    for name in ("alpha", "beta"):
        d = str(tmp_path / name)
        cur = subprocess.run(["git", "-C", d, "branch", "--show-current"],
                             capture_output=True, text=True).stdout.strip()
        if cur != "master":
            subprocess.run(["git", "-C", d, "branch", "-m", cur, "master"], check=True)
    r = _run(ws, "--local", str(tmp_path), "--repos", "ws,alpha,beta", "--write-members")
    a = (tmp_path / "alpha" / "AGENTS.md").read_text()
    assert "| Provides | REST /v1 |" in a, \
        "a master-default clone was skipped as mid-ticket: %s" % r.stdout


def _org_gh_shim(tmp_path, repos):
    """A fake gh for the org sweep: answers the paginated repo listing and
    each repo's AGENTS.md contents call. `repos` maps name -> AGENTS.md text,
    or None for a repo the forge cannot serve (unreachable)."""
    import base64
    import stat
    bin_dir = tmp_path / "orgbin"
    bin_dir.mkdir(exist_ok=True)
    # value None = the forge cannot serve the repo at all (outage);
    # value "NOFILE" = the repo answers but has no AGENTS.md (standalone).
    data = {"names": sorted(repos),
            "contents": {n: ("NOFILE" if t == "NOFILE"
                             else base64.b64encode(t.encode()).decode() if t is not None
                             else None) for n, t in repos.items()}}
    (tmp_path / "org-answers.json").write_text(json.dumps(data), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(f"""#!/usr/bin/env python3
import json, sys
d = json.load(open({str(tmp_path / 'org-answers.json')!r}))
a = sys.argv[1:]
arg = a[1] if len(a) > 1 else ""
if a[:1] == ["api"] and arg.endswith("/repos"):
    print("\\n".join(d["names"])); sys.exit(0)
if a[:1] == ["api"] and "/contents/AGENTS.md" in arg:
    name = arg.split("repos/")[1].split("/contents")[0].split("/")[-1]
    c = d["contents"].get(name)
    if c is None or c == "NOFILE":
        sys.exit(1)
    print(json.dumps({{"sha": "abc123", "content": c}})); sys.exit(0)
if a[:1] == ["api"] and arg.startswith("repos/"):
    name = arg.split("repos/")[1].split("/")[-1]
    if d["contents"].get(name) is None:
        sys.exit(1)
    print(json.dumps({{"name": name}})); sys.exit(0)
sys.exit(1)
""", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return str(bin_dir)


def _agents_for(family, ws):
    return AGENTS.replace("tienda-demo", family).replace("acme/tienda-workspace", ws)


def _bootstrap(tmp_path, repos, *extra):
    bin_dir = _org_gh_shim(tmp_path, repos)
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"])
    return subprocess.run([sys.executable, SCRIPT, "--org", "acme", *extra],
                          capture_output=True, text=True, env=env)


def test_el_barrido_contabiliza_cada_repo_en_un_balde(tmp_path):
    # 5 repos: 3 declare the family, 1 has no section, 1 the forge cannot
    # serve. The report must account for ALL FIVE — and the unreachable one
    # is NAMED, because "gh fell over" and "no family" must never read alike.
    r = _bootstrap(tmp_path, {
        "ws": _agents_for("tienda", "acme/ws"),
        "api": _agents_for("tienda", "acme/ws"),
        "web": _agents_for("tienda", "acme/ws"),
        "solo": "# solo\n\nsin seccion de familia\n",
        "ghost": None,
    })
    assert r.returncode == 0, r.stderr
    assert "5 repos listados" in r.stdout, r.stdout
    assert "1 sin sección" in r.stdout and "1 inalcanzables" in r.stdout, r.stdout
    assert "ghost" in r.stdout, "the unreachable repo was not NAMED: " + r.stdout


def test_la_membresia_es_lo_declarado_y_nada_mas(tmp_path):
    r = _bootstrap(tmp_path, {
        "ws": _agents_for("tienda", "acme/ws"),
        "api": _agents_for("tienda", "acme/ws"),
        "solo": "# solo\nnada\n",
    })
    fam = r.stdout.split("Familia tienda")[-1]
    assert "· api" in fam and "· solo" not in fam, \
        "a repo with no declared family rode into the family listing: " + r.stdout
    assert "preview" in r.stdout, "without --write this must say it wrote nothing"


def test_dos_familias_no_se_mezclan(tmp_path):
    r = _bootstrap(tmp_path, {
        "ws": _agents_for("tienda", "acme/ws"),
        "api": _agents_for("tienda", "acme/ws"),
        "pagos-ws": _agents_for("pagos", "acme/pagos-ws"),
        "cobros": _agents_for("pagos", "acme/pagos-ws"),
    })
    tienda = r.stdout.split("Familia tienda")[-1].split("Familia")[0] \
        if "Familia tienda" in r.stdout else ""
    assert "api" in tienda and "cobros" not in tienda, \
        "the pagos member leaked into tienda's bucket: " + r.stdout


def test_consume_no_se_lee_de_la_columna_consumed_by(tmp_path):
    # Consumed-by comes BEFORE Consume in the authored table: a substring
    # header match read Consumes from the wrong cell every time.
    (tmp_path / "ddw-family.md").write_text(
        "# Familia\n\n| Repo | Qué hace | Consumed by | Consume |\n"
        "|---|---|---|---|\n"
        "| alpha | api | beta | gamma |\n", encoding="utf-8")
    rows = fc.familia_map(str(tmp_path))
    assert rows[0]["consumed by"] == "beta" and rows[0]["consumes"] == "gamma", rows


def test_sin_agents_md_es_standalone_no_caida(tmp_path):
    # "the repo has no AGENTS.md" (404) and "the forge fell over" must never
    # read the same: one is a standalone, the other a retry.
    r = _bootstrap(tmp_path, {
        "ws": _agents_for("tienda", "acme/ws"),
        "api": _agents_for("tienda", "acme/ws"),
        "vacio": "NOFILE",
        "ghost": None,
    })
    assert r.returncode == 0, r.stderr
    assert "1 sin sección" in r.stdout and "1 inalcanzables" in r.stdout, r.stdout
    assert "ghost" in r.stdout and "✗ vacio" not in r.stdout, \
        "a plain repo without AGENTS.md was named unreachable: " + r.stdout


def test_bootstrap_write_publica_la_semilla_sin_el_workspace(tmp_path):
    # --write end to end against a REAL local bare: the seed ddw-family.md
    # lands on a branch at the workspace's origin, WITHOUT the workspace as
    # its own row, and the PR is asked of the forge.
    import base64
    import stat
    bare = tmp_path / "ws-origin.git"
    seed = tmp_path / "ws-seed"
    seed.mkdir()
    for cmd in (["git", "-C", str(seed), "init", "-q", "-b", "main", "."],
                ["git", "-C", str(seed), "-c", "user.email=t@t", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                 "-m", "seed"]):
        subprocess.run(cmd, check=True, capture_output=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True)

    bin_dir = _org_gh_shim(tmp_path, {
        "ws": _agents_for("tienda", "acme/ws"),
        "api": _agents_for("tienda", "acme/ws"),
        "web": _agents_for("tienda", "acme/ws"),
    })
    gh = tmp_path / "orgbin" / "gh"
    shim = gh.read_text()
    assert shim.rstrip().endswith("sys.exit(1)")
    shim = shim.rstrip()[: -len("sys.exit(1)")] + f"""if a[:2] == ["repo", "clone"]:
    import subprocess as sp
    sp.run(["git", "clone", "-q", {str(bare)!r}, a[3]], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        sp.run(["git", "-C", a[3], "config", k, v])
    sys.exit(0)
if a[:2] == ["pr", "create"]:
    print("https://github.com/acme/ws/pull/3"); sys.exit(0)
sys.exit(1)
"""
    gh.write_text(shim)
    env = dict(os.environ, PATH=str(tmp_path / "orgbin") + os.pathsep + os.environ["PATH"])
    r = subprocess.run([sys.executable, SCRIPT, "--org", "acme", "--write"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PR #3" in r.stdout and "--repo acme/ws" in r.stdout, r.stdout
    show = subprocess.run(["git", "-C", str(bare), "show",
                           "chore/ddw-family-bootstrap:ddw-family.md"],
                          capture_output=True, text=True).stdout
    assert "| api |" in show and "| web |" in show, show
    assert "| ws |" not in show, \
        "the workspace rode its own seed map (perpetual drift): " + show


def _sweep_stub(tmp_path, text_answers, tarballs):
    """A `gh` that answers `api` from a table — and binary for a tarball."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    (d / "gh").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "text = json.loads(%r)\n"
        "tars = json.loads(%r)\n"
        "if sys.argv[1:2] != ['api']:\n"
        "    sys.exit(1)\n"
        "ep = sys.argv[2]\n"
        "if ep in tars:\n"
        "    sys.stdout.buffer.write(open(tars[ep], 'rb').read())\n"
        "    sys.exit(0)\n"
        "if ep not in text:\n"
        "    sys.exit(1)\n"
        "print(text[ep])\n" % (json.dumps(text_answers), json.dumps(tarballs)),
        encoding="utf-8")
    (d / "gh").chmod(0o755)
    return d


def _make_tarball(tmp_path, name, files):
    import io
    import tarfile
    p = tmp_path / (name + ".tar.gz")
    with tarfile.open(p, "w:gz") as tf:
        for rel, body in files.items():
            data = body.encode()
            info = tarfile.TarInfo("%s-abc1234/%s" % (name, rel))
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return str(p)


def test_sweep_registra_los_paths_y_el_sha_de_cada_repo(tmp_path):
    # The mechanical half of the derived store: facts read from the TARBALL,
    # each one carrying the path it came from — without the path there is
    # nothing for a later claim to cite and nothing to compare on a refresh.
    tar = _make_tarball(tmp_path, "alpha", {
        "README.md": "# alpha\n\nLa api de pagos.\n",
        "package.json": '{"name": "alpha", "description": "pagos"}\n',
        "api/routes/users.js": "// routes\n",
        "src/util/logging.js": "// nothing structural here\n",
    })
    binp = _sweep_stub(
        tmp_path,
        {"repos/acme/alpha": json.dumps({"default_branch": "main",
                                         "language": "JavaScript",
                                         "description": "pagos"}),
         "repos/acme/alpha/commits?per_page=1":
             "89abcdef0123456789abcdef0123456789abcdef"},
        {"repos/acme/alpha/tarball": tar})
    out = tmp_path / "facts.json"
    r = subprocess.run(
        [sys.executable, SCRIPT, "--sweep", "--org", "acme",
         "--repos", "alpha", "--facts-out", str(out)],
        capture_output=True, text=True,
        env=dict(os.environ, PATH="%s:%s" % (binp, os.environ["PATH"])))
    assert r.returncode == 0, r.stdout + r.stderr
    facts = json.loads(out.read_text())
    repo = facts["repos"][0]
    assert repo["unreadable"] is None, repo
    assert repo["sha"] == "89abcde", repo
    assert "api/routes/users.js" in repo["structural_paths"], repo
    assert "src/util/logging.js" not in repo["structural_paths"], \
        "the sweep called an ordinary file structural — the refresh filter " \
        "it feeds would then re-read on every commit"
    assert repo["readme"]["path"] == "README.md", repo
    assert "package.json" in repo["manifests"], repo


def test_sweep_deja_en_el_archivo_al_repo_que_no_pudo_leer(tmp_path):
    # A sweep that drops what it could not read reports a smaller organisation
    # in green. Unreadable is a row with a reason, never an absence.
    binp = _sweep_stub(tmp_path, {}, {})
    out = tmp_path / "facts.json"
    r = subprocess.run(
        [sys.executable, SCRIPT, "--sweep", "--org", "acme",
         "--repos", "ghost", "--facts-out", str(out)],
        capture_output=True, text=True,
        env=dict(os.environ, PATH="%s:%s" % (binp, os.environ["PATH"])))
    assert r.returncode == 0, r.stdout + r.stderr
    facts = json.loads(out.read_text())
    assert len(facts["repos"]) == 1, facts
    assert facts["repos"][0]["unreadable"], facts["repos"][0]
    assert "ghost" in r.stdout, r.stdout


def test_sweep_rechaza_un_tarball_que_escribe_fuera(tmp_path):
    # The sweep unpacks archives produced by the repositories it reads. An
    # entry whose path climbs out of the scratch directory makes the sweep a
    # delivery mechanism, so the extraction refuses the whole archive.
    import io
    import tarfile
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tf:
        data = b"owned\n"
        info = tarfile.TarInfo("beta-abc1234/../../escaped.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    binp = _sweep_stub(
        tmp_path,
        {"repos/acme/beta": json.dumps({"default_branch": "main"}),
         "repos/acme/beta/commits?per_page=1": "1111111111111111111111111111111111111111"},
        {"repos/acme/beta/tarball": str(evil)})
    out = tmp_path / "facts.json"
    r = subprocess.run(
        [sys.executable, SCRIPT, "--sweep", "--org", "acme",
         "--repos", "beta", "--facts-out", str(out)],
        capture_output=True, text=True,
        env=dict(os.environ, PATH="%s:%s" % (binp, os.environ["PATH"])))
    assert r.returncode == 0, r.stdout + r.stderr
    repo = json.loads(out.read_text())["repos"][0]
    assert repo["unreadable"] and "outside" in repo["unreadable"], repo


def _store(tmp_path, rows, fichas):
    d = tmp_path / "store"
    (d / "fichas").mkdir(parents=True, exist_ok=True)
    (d / "renglones.md").write_text(
        "# Renglones\n\n<!-- BEGIN DDW ROWS -->\n"
        "| Repo | SHA | Renglón |\n|---|---|---|\n" + "".join(rows) +
        "<!-- END DDW ROWS -->\n", encoding="utf-8")
    for name, body in fichas.items():
        (d / "fichas" / (name + ".md")).write_text(body, encoding="utf-8")
    return str(d)


def _facts(tmp_path, repos):
    f = tmp_path / "facts.json"
    f.write_text(json.dumps({"owner": "acme", "repos": repos}), encoding="utf-8")
    return str(f)


def _ficha(repo, sha, claims):
    return ("# %s\n\n<!-- BEGIN DDW FICHA --><!-- repo: %s · sha: %s -->\n"
            "| Afirmación | Archivo |\n|---|---|\n" % (repo, repo, sha) +
            "".join("| %s | %s |\n" % (c, p) for c, p in claims) +
            "<!-- END DDW FICHA -->\n")


ALPHA = {"name": "alpha", "slug": "acme/alpha", "sha": "89abcde",
         "unreadable": None, "structural_paths": ["api/routes/users.js"],
         "manifests": {"package.json": None},
         "readme": {"path": "README.md", "head": "x"}, "top_dirs": ["src"]}


def _admit(tmp_path, facts, store):
    return subprocess.run(
        [sys.executable, SCRIPT, "--admit", store, "--facts", facts],
        capture_output=True, text=True)


def test_admit_acepta_un_store_con_cobertura_y_citas_que_resuelven(tmp_path):
    facts = _facts(tmp_path, [ALPHA])
    store = _store(tmp_path, ["| alpha | 89abcde | la api de pagos |\n"],
                   {"alpha": _ficha("acme/alpha", "89abcde",
                                    [("Expone rutas de usuarios",
                                      "api/routes/users.js")])})
    r = _admit(tmp_path, facts, store)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "admitted" in r.stdout, r.stdout


def test_admit_rechaza_una_cita_que_el_barrido_no_encontro(tmp_path):
    # The claim names a file nobody read. This is the whole point of the gate:
    # prose that points at nothing must not enter the store.
    facts = _facts(tmp_path, [ALPHA])
    store = _store(tmp_path, ["| alpha | 89abcde | la api de pagos |\n"],
                   {"alpha": _ficha("acme/alpha", "89abcde",
                                    [("Publica cashback.start",
                                      "events/publisher.js")])})
    r = _admit(tmp_path, facts, store)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "events/publisher.js" in r.stderr, r.stderr


def test_admit_rechaza_un_repo_barrido_sin_renglon(tmp_path):
    # Coverage: a store that omits repos answers "who do I hit?" over a
    # smaller organisation, and answers it in green.
    beta = dict(ALPHA, name="beta", slug="acme/beta", sha="1111111")
    facts = _facts(tmp_path, [ALPHA, beta])
    store = _store(tmp_path, ["| alpha | 89abcde | la api de pagos |\n"], {})
    r = _admit(tmp_path, facts, store)
    assert r.returncode == 3, r.stdout
    assert "beta" in r.stderr and "no row" in r.stderr, r.stderr


def test_admit_rechaza_un_renglon_de_un_repo_inventado(tmp_path):
    facts = _facts(tmp_path, [ALPHA])
    store = _store(tmp_path,
                   ["| alpha | 89abcde | la api |\n",
                    "| fantasma | 2222222 | no existe |\n"], {})
    r = _admit(tmp_path, facts, store)
    assert r.returncode == 3, r.stdout
    assert "fantasma" in r.stderr, r.stderr


def test_admit_rechaza_una_ficha_escrita_contra_otro_commit(tmp_path):
    # Freshness is not a feeling: the ficha stamps the SHA it was written at,
    # and a stamp that does not match what the sweep read is refused.
    facts = _facts(tmp_path, [ALPHA])
    store = _store(tmp_path, ["| alpha | 89abcde | la api |\n"],
                   {"alpha": _ficha("acme/alpha", "0000000",
                                    [("x", "api/routes/users.js")])})
    r = _admit(tmp_path, facts, store)
    assert r.returncode == 3, r.stdout
    assert "0000000" in r.stderr, r.stderr


def test_admit_nombra_todos_los_problemas_no_solo_el_primero(tmp_path):
    # A gate that stops at the first defect makes the author walk it once per
    # defect, and a gate people walk many times is a gate people route around.
    beta = dict(ALPHA, name="beta", slug="acme/beta", sha="1111111")
    facts = _facts(tmp_path, [ALPHA, beta])
    store = _store(tmp_path, ["| fantasma | 2222222 | no existe |\n"], {})
    r = _admit(tmp_path, facts, store)
    assert r.returncode == 3, r.stdout
    for expected in ("fantasma", "alpha", "beta"):
        assert expected in r.stderr, (expected, r.stderr)
