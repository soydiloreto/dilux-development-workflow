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
    (tmp_path / "ws" / "familia.md").write_text(
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
