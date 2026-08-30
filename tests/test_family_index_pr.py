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


def _fake_gh(tmp_path, view_files, merged_children=None):
    """A `gh` that answers `pr view --json files,...` with `view_files`,
    `pr list --state merged` with `merged_children`, and logs every argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "gh-calls.log"
    answers = {
        "view": {"state": "OPEN", "baseRefName": "main",
                 "files": [{"path": p} for p in view_files]},
        "merged": merged_children or [],
    }
    (tmp_path / "gh-answers.json").write_text(json.dumps(answers), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(f"""#!/usr/bin/env python3
import json, sys
log = open({str(log)!r}, "a"); log.write(json.dumps(sys.argv[1:]) + "\\n"); log.close()
answers = json.load(open({str(tmp_path / 'gh-answers.json')!r}))
args = sys.argv[1:]
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


def _run(args, tmp_path, view_files, merged=None, cwd=None):
    bin_dir, log = _fake_gh(tmp_path, view_files, merged)
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
