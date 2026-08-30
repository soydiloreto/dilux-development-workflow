"""Parallel tickets, one worktree each — and the two guards on `close`.

What these tests pin is not git's worktree machinery — it is the DDW law
wrapped around it:

  * `open` starts the new tree at the FETCHED origin default, detached,
    with no `.ddw-state.json` inherited — the standing tree's half-done
    work never leaks into the new ticket; and opening twice is an answer,
    not an error.
  * `close` removes NOTHING dirty: uncommitted work is named and left
    standing, merged PR or no merged PR.
  * `close` on a clean tree still needs the forge's word — a MERGED PR
    naming the ticket — or an explicit `--drop "<why>"`. Done is not
    anyone's to declare, same law as the family index row.

The forge is a PATH shim (a fake `gh`), as in test_family_index_pr.
"""
import json
import os
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "ddw/scripts/ticket_worktree.py")


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def _repo_with_origin(tmp_path):
    """A clone whose origin is a local bare repo with one commit on main."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main", ".")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / "README.md").write_text("hola\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True)
    clone = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")
    return clone


def _fake_gh(tmp_path, merged_children):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    answers = tmp_path / "gh-answers.json"
    answers.write_text(json.dumps(merged_children), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(f"""#!/usr/bin/env python3
import json, sys
print(open({str(answers)!r}).read()); sys.exit(0)
""", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return str(bin_dir)


def _run(args, cwd, gh_bin=None):
    env = dict(os.environ)
    if gh_bin:
        env["PATH"] = gh_bin + os.pathsep + env["PATH"]
    return subprocess.run([sys.executable, SCRIPT, *args, "--root", str(cwd)],
                         capture_output=True, text=True, env=env)


def test_open_nace_fresco_en_el_origin_y_sin_estado(tmp_path):
    repo = _repo_with_origin(tmp_path)
    # The standing tree has half-done work — a branch and a state file —
    # that must NOT travel into the new worktree.
    _git(repo, "checkout", "-q", "-b", "feat/OLD-1-algo")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "half-done")
    (repo / ".ddw-state.json").write_text('{"ticket": "OLD-1"}', encoding="utf-8")
    r = _run(["open", "--ticket", "NEW-2"], repo)
    assert r.returncode == 0, r.stderr
    wt = tmp_path / "repo--wt-new-2"
    assert wt.is_dir(), "the sibling worktree was not created"
    assert not (wt / ".ddw-state.json").exists(), \
        "the standing tree's state leaked into the new worktree"
    head = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    main = subprocess.run(["git", "-C", str(repo), "rev-parse", "origin/main"],
                          capture_output=True, text=True).stdout.strip()
    assert head == main, "the worktree did not start at origin's default"


def test_open_dos_veces_es_una_respuesta_no_un_error(tmp_path):
    repo = _repo_with_origin(tmp_path)
    assert _run(["open", "--ticket", "T-9"], repo).returncode == 0
    r = _run(["open", "--ticket", "T-9"], repo)
    assert r.returncode == 0 and "abierto" in r.stdout, r.stderr


def test_close_jamas_remueve_trabajo_sin_commitear(tmp_path):
    repo = _repo_with_origin(tmp_path)
    _run(["open", "--ticket", "T-3"], repo)
    wt = tmp_path / "repo--wt-t-3"
    (wt / "avance.py").write_text("x = 1\n", encoding="utf-8")
    # Even WITH the forge swearing the PR merged, dirty stands.
    gh_bin = _fake_gh(tmp_path, [{"number": 7, "headRefName": "feat/T-3-x"}])
    r = _run(["close", "--ticket", "T-3"], repo, gh_bin)
    assert r.returncode == 2, "a dirty worktree was closed: " + r.stdout
    assert "avance.py" in r.stderr, "the refusal does not name the uncommitted file"
    assert wt.is_dir(), "the dirty worktree is gone — work lost"


def test_close_limpio_exige_el_merge_del_forge_o_un_drop_con_motivo(tmp_path):
    repo = _repo_with_origin(tmp_path)
    _run(["open", "--ticket", "T-4"], repo)
    _git(repo, "remote", "set-url", "origin", "https://github.com/acme/child.git")
    wt = tmp_path / "repo--wt-t-4"
    assert wt.is_dir()
    gh_bin = _fake_gh(tmp_path, [])           # the forge knows no merged PR
    r = _run(["close", "--ticket", "T-4"], repo, gh_bin)
    assert r.returncode == 2 and "MERGED" in r.stderr, r.stderr[:300]
    assert wt.is_dir(), "closed on nobody's word"
    r = _run(["close", "--ticket", "T-4", "--drop", "el ticket se descartó"], repo, gh_bin)
    assert r.returncode == 0, r.stderr
    assert not wt.is_dir(), "the declared drop did not remove the worktree"


def test_close_con_pr_mergeado_remueve(tmp_path):
    repo = _repo_with_origin(tmp_path)
    _run(["open", "--ticket", "T-5"], repo)
    _git(repo, "remote", "set-url", "origin", "https://github.com/acme/child.git")
    wt = tmp_path / "repo--wt-t-5"
    gh_bin = _fake_gh(tmp_path, [{"number": 12, "headRefName": "feat/T-5-cosa"}])
    r = _run(["close", "--ticket", "T-5"], repo, gh_bin)
    assert r.returncode == 0 and "#12" in r.stdout, r.stderr
    assert not wt.is_dir()


def test_un_ticket_raro_no_escapa_del_esquema_de_nombres(tmp_path):
    # The ticket becomes a sibling DIRECTORY name: "FEAT/T-7" nests and
    # "../../pwn" creates a worktree wherever the string points (audit repro).
    repo = _repo_with_origin(tmp_path)
    for evil in ("FEAT/T-7", "../../pwn", "..", "a b"):
        r = _run(["open", "--ticket", evil], repo)
        assert r.returncode == 2, "%r was accepted as a worktree name" % evil
    assert not (tmp_path.parent / "pwn").exists()


def test_un_worktree_borrado_a_mano_se_reabre_no_se_promete(tmp_path):
    # "seguí ahí" pointing at a directory somebody rm -rf'd sends the agent
    # into a cd that does not exist — the stale registration is pruned and
    # the worktree reopened fresh.
    repo = _repo_with_origin(tmp_path)
    _run(["open", "--ticket", "T-9"], repo)
    wt = tmp_path / "repo--wt-t-9"
    import shutil
    shutil.rmtree(wt)
    r = _run(["open", "--ticket", "T-9"], repo)
    assert r.returncode == 0, r.stderr
    assert wt.is_dir(), "the stale registration was believed and nothing reopened"


def test_origin_no_github_dice_la_verdad_al_cerrar(tmp_path):
    # On a GitLab origin the old refusal claimed "no MERGED PR at the forge"
    # without ever asking any forge.
    repo = _repo_with_origin(tmp_path)
    _run(["open", "--ticket", "T-4"], repo)
    _git(repo, "remote", "set-url", "origin", "git@gitlab.com:acme/child.git")
    r = _run(["close", "--ticket", "T-4"], repo)
    assert r.returncode == 2 and "not a GitHub URL" in r.stderr, r.stderr[:300]


def test_gh_ausente_habla_no_estalla():
    import importlib.util
    spec = importlib.util.spec_from_file_location("tw", SCRIPT)
    tw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tw)
    code, _, err = tw._run(["ddw-binario-que-no-existe"])
    assert code == 127 and "command not found" in err, (code, err)
