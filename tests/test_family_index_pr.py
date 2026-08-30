"""The one-approve index: the leash, and `done` that no word can write.

family_index_pr.py collapses the index ceremony to one approval per
direction. What these tests pin is not the convenience — it is the two
safety properties that make the convenience acceptable:

  * the LEASH: `merge` refuses any PR touching a file outside index
    territory (docs/ddw/** and .gitignore), so the worst a runaway
    "aprobado" can do is land a document;
  * the LAW: `update-row --status done` refuses without a MERGED child PR
    at the forge — the same rule the family write gate enforces in hooked
    sessions, enforced here because the throwaway clone has no hooks.

The forge is a PATH shim: a fake `gh` that answers from canned JSON and
logs every call, so the tests assert both what was answered AND what was
never asked.
"""
import json
import os
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "ddw/scripts/family_index_pr.py")


def _fake_gh(tmp_path, view_files, merged_children=None, index_b64=None):
    """A `gh` that answers `pr view --json files,...` with `view_files`,
    `pr list --state merged` with `merged_children`, and logs every argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "gh-calls.log"
    answers = {
        "view": {"state": "OPEN", "baseRefName": "main",
                 "files": [{"path": p} for p in view_files]},
        "merged": merged_children or [],
        "index_b64": index_b64,
    }
    (tmp_path / "gh-answers.json").write_text(json.dumps(answers), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(f"""#!/usr/bin/env python3
import json, sys
log = open({str(log)!r}, "a"); log.write(json.dumps(sys.argv[1:]) + "\\n"); log.close()
answers = json.load(open({str(tmp_path / 'gh-answers.json')!r}))
args = sys.argv[1:]
if args[:1] == ["api"] and "/contents/" in args[1]:
    if answers.get("index_b64"):
        print(answers["index_b64"]); sys.exit(0)
    sys.exit(1)
if args[:2] == ["pr", "view"]:
    print(json.dumps(answers["view"])); sys.exit(0)
if args[:2] == ["pr", "list"]:
    print(json.dumps(answers["merged"])); sys.exit(0)
if args[:2] == ["pr", "merge"]:
    print("merged ok"); sys.exit(0)
print("{{}}"); sys.exit(0)
""", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return str(bin_dir), str(log)


def _ws_repo(tmp_path):
    """A minimal workspace clone: ddw-family.md + a git remote pointing at acme/ws."""
    repo = tmp_path / "ws"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "https://github.com/acme/ws.git"], check=True)
    (repo / "ddw-family.md").write_text("# familia\n", encoding="utf-8")
    return str(repo)


def _run(args, tmp_path, view_files, merged=None, cwd=None, index_b64=None):
    bin_dir, log = _fake_gh(tmp_path, view_files, merged, index_b64)
    r = subprocess.run([sys.executable, SCRIPT, *args],
                       capture_output=True, text=True, cwd=cwd,
                       env=dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"]))
    calls = []
    if os.path.exists(log):
        calls = [json.loads(ln) for ln in open(log, encoding="utf-8")]
    return r, calls


def test_la_correa_rechaza_un_pr_que_toca_codigo(tmp_path):
    ws = _ws_repo(tmp_path)
    r, calls = _run(["merge", "--pr", "7", "--root", ws], tmp_path,
                    view_files=["docs/ddw/prd/prd-T-1.md", "app/main.py"])
    assert r.returncode == 2, "a PR with code in it was merged by the leash: " + r.stdout
    assert "app/main.py" in r.stderr and "human merge" in r.stderr, r.stderr[:300]
    assert not any(c[:2] == ["pr", "merge"] for c in calls), \
        "the refusal came AFTER asking the forge to merge — the leash bit too late"


def test_la_correa_deja_pasar_un_pr_de_solo_documentos(tmp_path):
    ws = _ws_repo(tmp_path)
    r, calls = _run(["merge", "--pr", "7", "--root", ws], tmp_path,
                    view_files=["docs/ddw/prd/prd-T-1.md", ".gitignore"])
    assert r.returncode == 0, "the documents-only PR was refused: " + r.stderr[:300]
    assert any(c[:2] == ["pr", "merge"] for c in calls), "merge was never asked of the forge"


def test_done_no_se_escribe_sin_pr_mergeado_del_hijo(tmp_path):
    ws = _ws_repo(tmp_path)
    r, calls = _run(["update-row", "--ticket", "T-1", "--repo-row", "acme/child",
                     "--status", "done", "--root", ws],
                    tmp_path, view_files=[], merged=[])
    assert r.returncode == 2, "`done` landed on nobody's word being checked: " + r.stdout
    assert "MERGED" in r.stderr and "unverified" in r.stderr, r.stderr[:300]
    assert not any(c[:2] == ["repo", "clone"] for c in calls), \
        "the clone happened before the forge said yes — work before the law"


def test_el_vocabulario_declarado_pasa_sin_forge(tmp_path):
    # `dropped: <why>` is a DECLARED out — it needs no forge answer, and it
    # must not even ask (the clone attempt is the first forge touch).
    ws = _ws_repo(tmp_path)
    r, calls = _run(["update-row", "--ticket", "T-1", "--repo-row", "acme/child",
                     "--status", "gibberish", "--root", ws],
                    tmp_path, view_files=[])
    assert r.returncode == 2 and "fixed vocabulary" in r.stderr, r.stderr[:300]
    assert calls == [], "a refused status still reached the forge"


def test_la_ley_del_done_no_se_paga_con_un_ticket_parecido(tmp_path):
    # T-11's merged PR must NOT satisfy T-1's done — a substring match let a
    # prefix ticket close on its neighbour's merge; and the index machinery's
    # own chore/<T>-row-* branches are nobody's child work.
    ws = _ws_repo(tmp_path)
    near_miss = [{"number": 44, "headRefName": "feat/T-11-otra-cosa"},
                 {"number": 45, "headRefName": "chore/T-1-row-api"}]
    r, calls = _run(["update-row", "--ticket", "T-1", "--repo-row", "acme/child",
                     "--status", "done", "--root", ws],
                    tmp_path, view_files=[], merged=near_miss)
    assert r.returncode == 2 and "MERGED" in r.stderr, \
        "a near-miss branch (or the index's own row PR) satisfied the done-law: " + r.stdout


def test_el_ticket_exacto_si_satisface_la_ley(tmp_path):
    ws = _ws_repo(tmp_path)
    r, calls = _run(["update-row", "--ticket", "T-1", "--repo-row", "acme/child",
                     "--status", "done", "--root", ws],
                    tmp_path, view_files=[],
                    merged=[{"number": 7, "headRefName": "feat/T-1-lo-real"}])
    # The forge check passes (its confirmation is printed) even though the
    # run then dies at the shim's clone — that failure is a different door.
    assert "forge confirms" in r.stdout and "#7" in r.stdout, \
        "the exact ticket's merged PR was not accepted: " + r.stderr[:300]


def test_el_row_edit_no_agarra_una_fila_que_solo_contiene_el_nombre():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fip", SCRIPT)
    fip = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fip)
    text = ("| Repo | Ticket | Scope | Depends on | Status |\n"
            "|---|---|---|---|---|\n"
            "| acme/tienda-api | T-1 | parte grande | none | active |\n"
            "| `acme/api` | T-1 | parte chica | none | pending |\n")
    m = fip._row_pattern("api").search(text)
    assert m and "tienda-api" not in m.group(1), \
        "updating `api` grabbed `tienda-api`'s row: %r" % (m and m.group(1))
    m2 = fip._row_pattern("tienda-api").search(text)
    assert m2 and "tienda-api" in m2.group(1)


def test_el_slug_sobrevive_los_puntos_del_nombre():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fip2", SCRIPT)
    fip = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fip)
    # Dotted repo names are legal; a regex that stopped at the first dot sent
    # forge questions to a DIFFERENT repository (acme/my for acme/my.repo).
    assert fip._slug_from_url("https://github.com/acme/my.repo.git") == "acme/my.repo"
    assert fip._slug_from_url("git@github.com:acme/next.js.git") == "acme/next.js"
    assert fip._slug_from_url("https://github.com/acme/plain") == "acme/plain"
    assert fip._slug_from_url("git@gitlab.com:acme/x.git") is None


def test_la_pregunta_al_forge_lleva_el_ticket_de_la_fila(tmp_path):
    # A sub-ticket row (T-1a) merges under a branch naming T-1a; asking the
    # forge for the INITIATIVE's id (T-1) refused a genuinely merged child
    # forever. The index is read at the forge (API, not a clone) for the
    # row's own ticket.
    import base64
    ws = _ws_repo(tmp_path)
    index = ("| Repo | Ticket | Scope | Depends on | Status |\n"
             "|---|---|---|---|---|\n"
             "| acme/child | T-1a | la parte | none | active |\n")
    r, calls = _run(["update-row", "--ticket", "T-1", "--repo-row", "acme/child",
                     "--status", "done", "--root", ws],
                    tmp_path, view_files=[],
                    merged=[{"number": 9, "headRefName": "feat/T-1a-cosa"}],
                    index_b64=base64.b64encode(index.encode()).decode())
    assert "forge confirms" in r.stdout and "#9" in r.stdout, \
        "the row's own ticket was not what the forge was asked: " + r.stderr[:300]


def test_un_pipe_en_el_status_no_rompe_la_tabla(tmp_path):
    ws = _ws_repo(tmp_path)
    r, calls = _run(["update-row", "--ticket", "T-1", "--repo-row", "acme/child",
                     "--status", "dropped: a | b", "--root", ws],
                    tmp_path, view_files=[])
    assert r.returncode == 2 and "table cell" in r.stderr, r.stderr[:200]
