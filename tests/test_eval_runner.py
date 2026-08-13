"""El arnés de los evals, preguntado directamente.

`evals/runner.py` es el instrumento con el que se mide la capa de
instrucciones, y un instrumento que nadie mide informa lo que sea. Los
escenarios lo ejercitan de punta a punta —cada uno levanta un repo, instala el
método y corre el veredicto—, así que cuestan minutos: acá van las capacidades
del arnés en sí, que se preguntan en milisegundos y son justamente las que, si
se rompen callado, hacen que un escenario pase por la razón equivocada.

Las tres que se prueban acá llegaron juntas y por la misma razón: sin ellas,
una familia entera de escenarios se podía escribir pero no juzgar.

  · `given.files` — sembrar el árbol. Antes sólo se podía escribir
    `.ddw-state.json`, así que todo escenario sobre un fuente que ya existe
    arrancaba con el repo vacío del fixture, o sea midiendo otra cosa.
  · `expect.file_matches` — afirmar sobre el CONTENIDO. `files_present` no
    distingue el documento que contesta la pregunta del que se la inventa: los
    dos existen.
  · `kind: method-lint` — `lint_method.py` como veredicto, con su control.
"""
import importlib.util
import json
import os
import subprocess

import pytest

pytest.importorskip("yaml")  # el runner sale con exit(2) si falta; no colgar la colección

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load("ddw_eval_runner", "evals/runner.py")


@pytest.fixture()
def repo(tmp_path):
    """Un repo git de mentira, con la forma que deja `make_repo`."""
    r = tmp_path / "repo"
    r.mkdir()
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "eval@example.com"],
                ["git", "config", "user.name", "eval"],
                ["git", "config", "commit.gpgsign", "false"]):
        subprocess.run(cmd, cwd=r, check=True, capture_output=True)
    (r / "README.md").write_text("# fixture\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=r, check=True, capture_output=True)
    return r


# ── given.files: sembrar el árbol ────────────────────────────────────────────

def test_seed_files_writes_and_commits(repo):
    n = runner.seed_files(repo, {"src/account.py": "def delete(): ...\n",
                                 "docs/ddw/prd/prd-T-1.md": "# PRD\n"})
    assert n == 2
    assert (repo / "src" / "account.py").read_text() == "def delete(): ...\n"
    tracked = subprocess.run(["git", "ls-files"], cwd=repo,
                             capture_output=True, text=True).stdout.split()
    assert "src/account.py" in tracked and "docs/ddw/prd/prd-T-1.md" in tracked
    # Y el árbol queda limpio: un fuente sembrado y sin commitear es trabajo sin
    # commitear que el escenario no pidió, y hay reglas que se miden sobre eso.
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    assert dirty == ""


def test_seed_files_can_leave_them_uncommitted(repo):
    runner.seed_files(repo, {"src/a.py": "x\n"}, commit=False)
    # `-uall`: con el default git colapsa el directorio nuevo en `?? src/` y la
    # aserción sobre la ruta completa no dice nada.
    dirty = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=repo,
                           capture_output=True, text=True).stdout
    assert "?? src/a.py" in dirty


def test_seed_files_commits_what_the_install_ignores(repo):
    # La instalación deja un bloque en `.gitignore`, y lo que ignora —los
    # tickets pausados, los marcadores de sesión, el journal— es parte de lo que
    # un escenario necesita sembrar. Sin `-f` el commit no encuentra nada, y el
    # fixture queda distinto de lo que el escenario dice sin avisar.
    (repo / ".gitignore").write_text(".ddw-paused/\n")
    runner.seed_files(repo, {".ddw-paused/T-2.json": '{"ticket": "T-2"}\n'})
    tracked = subprocess.run(["git", "ls-files"], cwd=repo,
                             capture_output=True, text=True).stdout.split()
    assert ".ddw-paused/T-2.json" in tracked


def test_seed_files_does_not_write_outside_the_fixture(repo):
    # El control que reescribió el checkout de quien lo corría costó veinte
    # minutos de creer que el producto tenía un bug. Por acá no se entra otra vez.
    with pytest.raises(RuntimeError, match="outside the fixture"):
        runner.seed_files(repo, {"../escaped.py": "x"})
    with pytest.raises(RuntimeError, match="absolute path"):
        runner.seed_files(repo, {"/etc/passwd": "x"})
    assert not (repo.parent / "escaped.py").exists()


def test_seed_files_refuses_the_state_file(repo):
    with pytest.raises(RuntimeError, match="given.state"):
        runner.seed_files(repo, {".ddw-state.json": "{}"})


# ── expect.file_matches: el contenido, no la existencia ──────────────────────

def _judge(repo, expect):
    return runner.judge_repo_state({"expect": expect}, repo, [])


def test_file_matches_reads_the_artifact(repo):
    (repo / "prd.md").write_text("NFR: el endpoint responde en menos de 5 segundos (p95)\n")
    v, _ = _judge(repo, {"file_matches": [{"path": "prd.md", "matches": r"p95"}]})
    assert v == runner.PASS

    v, d = _judge(repo, {"file_matches": [
        {"path": "prd.md", "absent": r"\d+\s*segundos"}]})
    assert v == runner.FAIL and "must not" in d


def test_file_matches_accepts_a_list_and_reports_each_miss(repo):
    (repo / "prd.md").write_text("# PRD\n")
    v, d = _judge(repo, {"file_matches": [
        {"path": "prd.md", "matches": ["NFR", "criterio de aceptación"]}]})
    assert v == runner.FAIL
    assert d.count("does not contain") == 2


def test_file_matches_is_case_sensitive_unless_the_scenario_says_otherwise(repo):
    (repo / "prd.md").write_text("Menos de 5 Segundos\n")
    v, _ = _judge(repo, {"file_matches": [{"path": "prd.md", "absent": r"\d+ segundos"}]})
    assert v == runner.PASS
    v, _ = _judge(repo, {"file_matches": [{"path": "prd.md", "absent": r"(?i)\d+ segundos"}]})
    assert v == runner.FAIL


def test_file_matches_on_a_missing_file_is_a_problem_not_a_pass(repo):
    v, d = _judge(repo, {"file_matches": [{"path": "gone.md", "absent": "cualquier cosa"}]})
    assert v == runner.FAIL and "does not exist" in d


def test_a_clause_that_asserts_nothing_raises(repo):
    # Una aserción que no puede juzgar es lo mismo que no escribirla, y acá eso
    # se lee como verde. Levanta: `run_one` lo convierte en ERROR, que es rojo.
    (repo / "prd.md").write_text("x")
    with pytest.raises(RuntimeError, match="asserts nothing"):
        _judge(repo, {"file_matches": [{"path": "prd.md"}]})


def test_a_regex_that_does_not_compile_raises(repo):
    (repo / "prd.md").write_text("x")
    with pytest.raises(RuntimeError, match="does not compile"):
        _judge(repo, {"file_matches": [{"path": "prd.md", "matches": "("}]})


def test_file_matches_works_inside_any_of(repo):
    # `any_of` juzga cada rama con esta misma función; una capacidad que no
    # llegue ahí adentro deja media familia de escenarios sin poder escribirse.
    (repo / "prd.md").write_text("pendiente de plataforma\n")
    v, _ = _judge(repo, {"any_of": [[
        {"file_matches": [{"path": "prd.md", "matches": "pendiente"}]},
        {"files_absent": ["prd.md"]},
    ]]})
    assert v == runner.PASS


# ── kind: method-lint ────────────────────────────────────────────────────────

def _fake_method(tmp_path, body):
    root = tmp_path / "method"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "lint_method.py").write_text(body)
    return root


def test_method_lint_that_never_judged_is_error_not_red(tmp_path, repo):
    # Un linter que se cae antes de imprimir su veredicto no salió ni verde ni
    # rojo. Contarlo como rojo regala el modo control entero.
    root = _fake_method(tmp_path, "import sys\nsys.stderr.write('Traceback…\\n')\nsys.exit(1)\n")
    v, d = runner.run_method_lint({}, root, repo)
    assert v == runner.ERROR and "nothing was judged" in d


def test_method_lint_control_off_target(tmp_path, repo):
    root = _fake_method(tmp_path, "print('lint_method: 1 claim(s)')\nprint('  otra cosa')\n"
                                  "raise SystemExit(1)\n")
    sc = {"control": {"finding_matches": "el hueco que este escenario rompió"}}
    v, d = runner.run_method_lint(sc, root, repo, control=True)
    assert v == runner.ERROR and d.startswith("control off-target")


def test_method_lint_control_that_stays_green_is_a_failed_control(tmp_path, repo):
    root = _fake_method(tmp_path, "print('lint_method: every claim checks out')\n")
    sc = {"control": {"finding_matches": "lo que sea"}}
    v, d = runner.run_method_lint(sc, root, repo, control=True)
    assert v == runner.FAIL and "stayed green" in d


def test_method_lint_green_tree_passes(tmp_path, repo):
    root = _fake_method(tmp_path, "print('lint_method: every claim checks out')\n")
    v, _ = runner.run_method_lint({}, root, repo)
    assert v == runner.PASS


# ── un control que no puede discriminar, dicho y contado aparte ──────────────

def test_a_control_that_cannot_discriminate_is_skipped_with_its_reason():
    # Medido: el control de `forged` PASA con un modelo capaz, porque sus tres
    # ediciones son prosa y el hook rechaza la escritura igual. Dejarlo rojo
    # para siempre entrena a ignorar el rojo; borrarlo deja al escenario
    # afirmando que mide algo que no mide.
    import types
    sc = {"id": "x", "kind": "behavioral",
          "control": {"cannot_discriminate": "the rule is defended twice"}}
    args = types.SimpleNamespace(keep=False, agent="claude", model=None)
    r = runner.run_one(sc, os.path.join(ROOT), args, control=True)
    assert r.verdict == runner.SKIP
    assert "defended twice" in r.detail


def test_the_excuse_does_nothing_in_a_normal_run():
    # Sólo el modo control lo mira: en normal el escenario tiene que correr como
    # cualquier otro, o una excusa sobre el control apagaría la medición entera.
    import inspect
    src = inspect.getsource(runner.run_one)
    head = src[:src.index("workdir = Path(")]
    assert "if control:" in head and "cannot_discriminate" in head


# ── el modo control no acepta un rojo del arnés ──────────────────────────────

@pytest.mark.parametrize("detail", [
    "KeyError: 'when'",
    "TimeoutExpired: …",
    "control unavailable: the anchor is gone",
    "control off-target: lint_method went red on another claim",
    # Medido en la nube: un control se contó como rojo porque el CLI salió 1 sin
    # llegar a contestar. La regresión nunca se puso delante de nadie.
    "the agent did not complete a turn (exit 1): ",
    "the agent produced no JSON events — the turn did not run",
])
def test_a_red_that_is_the_harness_does_not_pass_the_control(detail):
    import inspect
    src = inspect.getsource(runner.main)
    block = src[src.index("if args.control:"):src.index("results.append(r)")]
    # Las cuatro familias tienen que estar nombradas en la rama que convierte un
    # ERROR del arnés en un control FALLADO, no en un rojo legítimo.
    needles = ("_harness", "_no_turn", "control unavailable", "control off-target",
               "the agent did not complete a turn", "the agent produced no JSON events")
    assert all(n in block or n in src for n in needles)
    assert "the control proved nothing" in block


# ── un control atado a una rama tiene fecha de vencimiento ───────────────────

def test_every_restored_commit_is_reachable_from_the_main_line():
    """Un `restore_from_commit` que apunta a un commit de una rama muere con ella.

    Medido: el squash-merge del PR #7 se llevó puesta la historia de
    `feat/docs-audit`, y el control de `painted-door-install-doc-eject` —que
    restauraba `docs/INSTALL.md` en `4c41f3e^`— pasó a fallar desde `main` por
    no poder aplicarse. Un control que no se puede aplicar no prueba nada, y el
    escenario sale rojo por una razón que no es la suya.
    """
    import glob
    import yaml
    # Esta pregunta es sobre el REPOSITORIO, no sobre el árbol: sin `.git` no
    # hay línea principal contra la cual medir, y `git merge-base` falla por no
    # poder correr — que es indistinguible de un control inaplicable.
    #
    # El sandbox de `scripts/mutate.py` copia el árbol con
    # `ignore_patterns(".git", …)`, así que acá esto fallaba en TODA copia sin
    # mutar. La guarda de baseline rojo del runner lo agarraba y se negaba a
    # inyectar — o sea que la corrida de mutaciones no podía arrancar, ni local
    # ni en CI, y el motivo era este test preguntando algo que en una copia no
    # tiene respuesta.
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        pytest.skip("sin historia git: la pregunta no se puede hacer sobre una copia del árbol")
    offenders = []
    for path in sorted(glob.glob(os.path.join(ROOT, "evals/scenarios/*.yaml"))):
        sc = yaml.safe_load(open(path, encoding="utf-8"))
        ctl = sc.get("control") or {}
        if ctl.get("type") != "restore_from_commit":
            continue
        commit = ctl["commit"]
        # ¿Está en la línea principal de ESTE checkout? `HEAD` alcanza porque
        # toda rama de trabajo sale de `main`; lo que se descarta es el commit
        # que sólo vive en otra rama.
        r = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                           cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            offenders.append(f"{os.path.basename(path)} restores at {commit}")
    assert not offenders, (
        "these controls hang off history the main line does not carry, so they stop being "
        "applicable the day that branch is deleted — use `type: substitute`: " + "; ".join(offenders))


def test_a_scenario_with_work_in_progress_says_which_branch_it_is_on():
    """Un estado que dice trabajo en curso, en `master`, es un mundo imposible.

    El boot manda comprobar la branch antes de resumir: en una genérica —`main`,
    `master`, `develop`…— el agente FRENA y pregunta por la inconsistencia. Es
    lo correcto, y si la puso el arnés el escenario gasta un turno en algo que
    no mide. Medido con Claude Code: el primer turno entero se iba en eso.
    """
    import glob
    import yaml
    GENERIC = {None, "IDLE"}
    offenders = []
    for path in sorted(glob.glob(os.path.join(ROOT, "evals/scenarios/*.yaml"))):
        sc = yaml.safe_load(open(path, encoding="utf-8"))
        if sc.get("kind") != "behavioral":
            continue
        state = (sc.get("given") or {}).get("state")
        if not isinstance(state, dict) or state.get("phase") in GENERIC:
            continue
        if not (sc.get("given") or {}).get("branch"):
            offenders.append(f"{os.path.basename(path)} is in {state.get('phase')}")
    assert not offenders, (
        "these scenarios start with work in progress on a generic branch, so the boot's own "
        "consistency check fires and the turn goes to a contradiction the harness invented: "
        + "; ".join(offenders))


# ── el escenario real, leído como dato ───────────────────────────────────────

def test_the_method_lint_scenario_declares_a_control_with_a_target(tmp_path):
    import yaml
    p = os.path.join(ROOT, "evals/scenarios/method-lint-still-knows-how-to-go-red.yaml")
    sc = yaml.safe_load(open(p, encoding="utf-8"))
    assert sc["kind"] == "method-lint"
    # Sin `finding_matches` el control se conforma con cualquier rojo, que es
    # justamente lo que este kind existe para no aceptar.
    assert sc["control"]["finding_matches"]
    assert sc["kind"] in runner.OFFLINE_KINDS, "el CI corre `--offline`; afuera no se corre"
    # Y el ancla del control tiene que seguir existiendo en el árbol, o el
    # control no se puede aplicar y no prueba nada.
    for edit in sc["control"]["edits"]:
        text = open(os.path.join(ROOT, edit["path"]), encoding="utf-8").read()
        assert edit["old"] in text, f"el ancla del control ya no está en {edit['path']}"


def test_json_import_is_used_by_seed_files(repo):
    # Un `given.files` con un valor que no es texto se escribe como JSON: es la
    # forma en que un escenario siembra un manifiesto o un estado de otro
    # archivo sin tener que escaparlo a mano en el YAML.
    runner.seed_files(repo, {"pkg.json": {"name": "x"}})
    assert json.loads((repo / "pkg.json").read_text())["name"] == "x"
