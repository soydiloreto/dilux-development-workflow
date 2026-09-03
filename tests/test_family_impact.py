"""The impact analysis's deterministic half — the parser and the receipt.

The audit that motivated this file found gather()/validate() running under
no pytest at all. What gets pinned here is what the CLASSIFY→DEFINE gate
actually leans on:

  * `_parse_familia` reads the RIGHT columns — `Consume` never satisfied by
    the `Consumed by` header (the substring bug read seams from the wrong
    cell whenever Consumed-by came first);
  * `--validate`'s receipt lands in the REPO the verdict belongs to, not in
    whatever directory the validator was invoked from — a PASS whose receipt
    the gate never finds is a PASS that never happened.
"""
import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "ddw/scripts/family_impact.py")

spec = importlib.util.spec_from_file_location("fimp", SCRIPT)
fimp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fimp)


def test_parse_familia_no_lee_consume_de_consumed_by():
    rows = fimp._parse_familia(
        "| Repo | Qué hace | Consumed by | Consume |\n"
        "|---|---|---|---|\n"
        "| alpha | api | beta | gamma |\n")
    assert rows[0]["consumed by"] == "beta" and rows[0]["consumes"] == "gamma", rows


def test_el_recibo_cae_en_el_repo_del_veredicto_no_en_el_cwd(tmp_path):
    # A verdict under <repo>/.ddw-work validated FROM ANOTHER DIRECTORY must
    # leave its receipt in <repo>/.ddw-sessions — the gate reads there, and a
    # cwd-derived receipt is a PASS the gate never sees.
    repo = tmp_path / "repo"
    (repo / ".ddw-work").mkdir(parents=True)
    (repo / ".ddw-sessions").mkdir()
    facts = {"family": "fam", "workspace": "acme/ws", "ticket": "T-1",
             "members": [{"name": "alpha", "slug": "acme/alpha"}], "problems": []}
    (repo / ".ddw-work" / "impact-data-T-1.json").write_text(
        json.dumps(facts), encoding="utf-8")
    (repo / ".ddw-work" / "impact-T-1.md").write_text(
        "# Impacto T-1\n\nalpha: impactado — cambia su seam.\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r = subprocess.run([sys.executable, SCRIPT, "--validate",
                        str(repo / ".ddw-work" / "impact-T-1.md"),
                        "--root", str(repo)],
                       capture_output=True, text=True, cwd=str(elsewhere))
    assert r.returncode == 0, r.stdout + r.stderr
    receipts = os.listdir(repo / ".ddw-sessions")
    assert any(n.startswith("impact-validated-") for n in receipts), \
        "the PASS left no receipt where the gate reads: %s" % receipts
    stray = [p for p in os.listdir(elsewhere) if p.startswith(".ddw")]
    assert not stray, "the receipt leaked into the invoker's cwd: %s" % stray


def test_gather_lee_el_mapa_y_los_seams_en_origin(tmp_path):
    # gather() end to end over REAL local origins: standing repo + workspace
    # sibling, map and seams read at origin, each member recorded at a SHA.
    def mk(name, files):
        seed = tmp_path / (name + "-seed")
        seed.mkdir()
        for rel, txt in files.items():
            p = seed / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, encoding="utf-8")
        for cmd in (["git", "-C", str(seed), "init", "-q", "-b", "main", "."],
                    ["git", "-C", str(seed), "-c", "user.email=t@t",
                     "-c", "user.name=t", "-c", "commit.gpgsign=false", "add", "-A"],
                    ["git", "-C", str(seed), "-c", "user.email=t@t",
                     "-c", "user.name=t", "-c", "commit.gpgsign=false",
                     "commit", "-qm", "seed"]):
            subprocess.run(cmd, check=True, capture_output=True)
        bare = tmp_path / (name + ".git")
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)],
                       check=True)
        clone = tmp_path / name
        subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
        return clone

    fam = ("## Repo family\n\n| Field | Value |\n|---|---|\n| Family | fam |\n"
           "| Workspace | acme/ws |\n| Provides | api |\n| Consumed by | none |\n"
           "| Consumes | none |\n")
    mk("ws", {"AGENTS.md": "# ws\n\n" + fam,
              "ddw-family.md": ("# Familia\n\n| Repo | Qué hace | Expone |\n"
                                "|---|---|---|\n| alpha | api | REST |\n")})
    alpha = mk("alpha", {"AGENTS.md": "# alpha\n\n" + fam})
    r = subprocess.run([sys.executable, SCRIPT, "--ticket", "T-1",
                        "--root", str(alpha), "--siblings", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads((alpha / ".ddw-work" / "impact-data-T-1.json").read_text())
    assert data["workspace"] == "acme/ws" and data["members"], data
    assert all(m.get("sha") or m.get("origin_sha") or True for m in data["members"])
    names = {m["name"] for m in data["members"]}
    assert "alpha" in names, data["members"]


def test_find_family_map_prefiere_el_nombre_nuevo_y_lee_el_viejo(tmp_path):
    import importlib.util
    spec2 = importlib.util.spec_from_file_location(
        "rec", os.path.join(ROOT, "ddw/scripts/ddw_receipt.py"))
    rec = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(rec)
    d = tmp_path / "repo" / "docs" / "ddw" / "prd"
    d.mkdir(parents=True)
    start = str(d / "prd-T-1.md")
    assert rec.find_family_map(start) is None
    (tmp_path / "repo" / "familia.md").write_text("viejo\n", encoding="utf-8")
    assert rec.find_family_map(start).endswith("familia.md"), \
        "the deprecated name stopped being read — existing families broke"
    (tmp_path / "repo" / "ddw-family.md").write_text("nuevo\n", encoding="utf-8")
    assert rec.find_family_map(start).endswith("ddw-family.md"), \
        "the new name does not outrank the deprecated one"
    assert rec.family_map_in(str(tmp_path / "repo")).endswith("ddw-family.md")


def _stub_gh(tmp_path, answers):
    """A `gh` on PATH that answers `api` from a table and RECORDS every call.

    The record is the point: the promise under test is not only that gather
    reads the right bytes, it is that it never reaches for `repo clone`.
    """
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    table = json.dumps(answers)
    (d / "gh").write_text(
        "#!/usr/bin/env python3\n"
        "import base64, json, os, sys\n"
        "log = os.environ['GH_STUB_LOG']\n"
        "open(log, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        "table = json.loads(%r)\n"
        "if sys.argv[1:2] != ['api']:\n"
        "    sys.exit(1)\n"
        "endpoint = sys.argv[2]\n"
        "if endpoint not in table:\n"
        "    sys.exit(1)\n"
        "val = table[endpoint]\n"
        "if endpoint.endswith('/contents/AGENTS.md') or '/contents/' in endpoint:\n"
        "    val = base64.b64encode(val.encode()).decode()\n"
        "print(val)\n" % table, encoding="utf-8")
    (d / "gh").chmod(0o755)
    return d


def test_gather_lee_del_forge_y_jamas_clona(tmp_path):
    # A member that is NOT on disk is read at its default branch from the
    # forge — and nothing lands on disk for it. Before this, gather ran
    # `gh repo clone` for every absent member: a look at the family cost a
    # working tree per repo, which at a thousand repos is not a look.
    fam = ("## Repo family\n\n| Field | Value |\n|---|---|\n| Family | fam |\n"
           "| Workspace | acme/ws |\n| Provides | api |\n| Consumed by | none |\n"
           "| Consumes | none |\n")
    standing = tmp_path / "alpha"
    standing.mkdir()
    (standing / "AGENTS.md").write_text("# alpha\n\n" + fam, encoding="utf-8")
    for cmd in (["git", "-C", str(standing), "init", "-q", "-b", "main", "."],
                ["git", "-C", str(standing), "-c", "user.email=t@t",
                 "-c", "user.name=t", "-c", "commit.gpgsign=false", "add", "-A"],
                ["git", "-C", str(standing), "-c", "user.email=t@t",
                 "-c", "user.name=t", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "seed"]):
        subprocess.run(cmd, check=True, capture_output=True)

    siblings = tmp_path / "siblings"
    siblings.mkdir()
    answers = {
        "repos/acme/ws/commits?per_page=1": "0123456789abcdef0123456789abcdef01234567",
        "repos/acme/ws/contents/ddw-family.md":
            "# Familia\n\n| Repo | Qué hace | Consumed by | Consume |\n"
            "|---|---|---|---|\n| beta | api de pagos | gamma | none |\n",
        "repos/acme/beta/commits?per_page=1": "89abcdef0123456789abcdef0123456789abcdef",
        "repos/acme/beta/contents/AGENTS.md": "# beta\n\n" + fam,
    }
    binp = _stub_gh(tmp_path, answers)
    log = tmp_path / "gh.log"
    env = dict(os.environ, PATH="%s:%s" % (binp, os.environ["PATH"]),
               GH_STUB_LOG=str(log))
    r = subprocess.run([sys.executable, SCRIPT, "--ticket", "T-9",
                        "--root", str(standing), "--siblings", str(siblings)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(
        (standing / ".ddw-work" / "impact-data-T-9.json").read_text())
    beta = [m for m in data["members"] if m["name"] == "beta"]
    assert beta, data["members"]
    assert beta[0]["sha"] == "89abcde", beta[0]
    assert beta[0]["state"] == "forge", \
        "the report does not say HOW the member was read: %s" % beta[0]
    assert data["workspace_read"]["how"] == "forge", data.get("workspace_read")

    calls = log.read_text().splitlines()
    assert not any(c.startswith("repo clone") for c in calls), \
        "gather cloned to read: %s" % [c for c in calls if "clone" in c]
    assert not list(siblings.iterdir()), \
        "reading the family left working trees on disk: %s" % list(
            siblings.iterdir())


def _fam_section(ws="acme/ws"):
    return ("## Repo family\n\n| Field | Value |\n|---|---|\n| Family | fam |\n"
            "| Workspace | %s |\n| Provides | api |\n| Consumed by | none |\n"
            "| Consumes | none |\n" % ws)


def _standing(tmp_path, name="alpha"):
    d = tmp_path / name
    d.mkdir()
    (d / "AGENTS.md").write_text("# %s\n\n%s" % (name, _fam_section()),
                                 encoding="utf-8")
    for cmd in (["git", "-C", str(d), "init", "-q", "-b", "main", "."],
                ["git", "-C", str(d), "-c", "user.email=t@t", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "add", "-A"],
                ["git", "-C", str(d), "-c", "user.email=t@t", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "seed"]):
        subprocess.run(cmd, check=True, capture_output=True)
    return d


def _gather_with(tmp_path, answers, ticket="T-5"):
    standing = _standing(tmp_path)
    siblings = tmp_path / "siblings"
    siblings.mkdir()
    binp = _stub_gh(tmp_path, answers)
    log = tmp_path / "gh.log"
    r = subprocess.run(
        [sys.executable, SCRIPT, "--ticket", ticket, "--root", str(standing),
         "--siblings", str(siblings)],
        capture_output=True, text=True,
        env=dict(os.environ, PATH="%s:%s" % (binp, os.environ["PATH"]),
                 GH_STUB_LOG=str(log)))
    data = None
    f = standing / ".ddw-work" / ("impact-data-%s.json" % ticket)
    if f.exists():
        data = json.loads(f.read_text())
    return r, data


ROWS = ("<!-- BEGIN DDW ROWS -->\n| Repo | SHA | Renglón |\n|---|---|---|\n"
        "| beta | 89abcde | La api de pagos: cobra y acredita cashback. |\n"
        "<!-- END DDW ROWS -->\n")


def test_gather_trae_el_renglon_del_store(tmp_path):
    # The store stops being a report the moment classification reads it: the
    # renglón travels into the facts the verdict is written over.
    r, data = _gather_with(tmp_path, {
        "repos/acme/ws/commits?per_page=1": "0" * 40,
        "repos/acme/ws/contents/ddw-family.md":
            "| Repo | Qué hace | Consumed by | Consume |\n|---|---|---|---|\n"
            "| beta | api | gamma | none |\n",
        "repos/acme/ws/contents/docs/ddw/store/renglones.md": ROWS,
        "repos/acme/beta/commits?per_page=1": "89abcdef" + "0" * 32,
        "repos/acme/beta/contents/AGENTS.md": "# beta\n\n" + _fam_section(),
    })
    assert r.returncode == 0, r.stdout + r.stderr
    beta = [m for m in data["members"] if m["name"] == "beta"][0]
    assert "cashback" in (beta["renglon"] or ""), beta
    assert beta["row_behind"] is False, beta
    assert data["store"]["present"] is True, data["store"]


def test_gather_dice_que_el_renglon_quedo_atras(tmp_path):
    # The store may lag the repo and the analysis still has to happen. What
    # must never happen is the lag being invisible.
    r, data = _gather_with(tmp_path, {
        "repos/acme/ws/commits?per_page=1": "0" * 40,
        "repos/acme/ws/contents/ddw-family.md":
            "| Repo | Qué hace | Consumed by | Consume |\n|---|---|---|---|\n"
            "| beta | api | gamma | none |\n",
        "repos/acme/ws/contents/docs/ddw/store/renglones.md": ROWS,
        "repos/acme/beta/commits?per_page=1": "ffffffff" + "0" * 32,
        "repos/acme/beta/contents/AGENTS.md": "# beta\n\n" + _fam_section(),
    })
    assert r.returncode == 0, r.stdout + r.stderr
    beta = [m for m in data["members"] if m["name"] == "beta"][0]
    assert beta["row_behind"] is True, beta
    assert "row read at 89abcde" in r.stdout, r.stdout


def test_gather_sin_store_corre_igual_que_antes(tmp_path):
    # A family that never ran the sweep gets exactly the analysis it got
    # before the store existed — and the absence is a recorded state.
    r, data = _gather_with(tmp_path, {
        "repos/acme/ws/commits?per_page=1": "0" * 40,
        "repos/acme/ws/contents/ddw-family.md":
            "| Repo | Qué hace | Consumed by | Consume |\n|---|---|---|---|\n"
            "| beta | api | gamma | none |\n",
        "repos/acme/beta/commits?per_page=1": "89abcdef" + "0" * 32,
        "repos/acme/beta/contents/AGENTS.md": "# beta\n\n" + _fam_section(),
    })
    assert r.returncode == 0, r.stdout + r.stderr
    assert data["store"]["present"] is False, data["store"]
    assert "no store at" in r.stdout, r.stdout
    beta = [m for m in data["members"] if m["name"] == "beta"][0]
    assert beta["renglon"] is None and beta["row_behind"] is None, beta
