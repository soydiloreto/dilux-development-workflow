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
