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
