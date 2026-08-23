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
import pathlib
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


# ── Copilot: el nivel del cableado es lo que decide si algo gatea ────────────
#
# Copilot no se midió nunca de punta a punta porque no tenía perfil headless.
# Estos casos fijan lo que el perfil tiene que hacer bien, y cada uno
# corresponde a una forma de salir verde sin haber medido nada.


def test_copilot_has_a_headless_profile():
    """Sin entrada, `agent_profile` levanta y el escenario no corre. Con una mal
    puesta, corre y mide otra cosa: por eso los flags también se afirman."""
    name, prof = runner.agent_profile(["copilot"])
    assert name == "copilot"
    assert "--allow-all" in prof["flags"], "sin --allow-all el modo -p ni arranca"
    assert prof["prompt"] == ["-p", "{turn}"], "-p es el punto de entrada headless"
    assert prof["dir"] == ["-C", "{repo}"], "sin -C la corrida puede apuntar a otro árbol"


def test_copilot_turn_refuses_to_run_without_its_own_home():
    """El HOME es donde viven las compuertas de Copilot. Apuntado al del
    operador, el fixture lo juzga el cableado de esa máquina y el escenario
    reporta como producto lo que es del arnés."""
    with pytest.raises(RuntimeError) as e:
        runner.agent_turn_cmd(["copilot"], "gpt-5-mini", None, "hacé algo", repo="/tmp/x")
    assert "HOME" in str(e.value)


def test_copilot_turn_sets_home_and_repo(tmp_path):
    name, cmd, env = runner.agent_turn_cmd(["copilot"], "gpt-5-mini", None, "hacé algo",
                                           repo=tmp_path / "repo", home=tmp_path / "home")
    assert env["HOME"] == str(tmp_path / "home")
    assert "-C" in cmd and str(tmp_path / "repo") in cmd
    assert cmd[-2:] == ["-p", "hacé algo"]


def test_copilot_resumes_the_session_it_was_given(tmp_path):
    _, cmd, _ = runner.agent_turn_cmd(["copilot"], "gpt-5-mini", "abc-123", "seguí",
                                      repo=tmp_path / "repo", home=tmp_path / "home")
    assert "--resume=abc-123" in cmd


def test_copilot_reads_the_session_id_out_of_the_resume_footer():
    out = "hecho\n\nResume     copilot --resume=48ac578f-15de-4b10-b255-c2d4518af86c\n"
    payload, session, err = runner.agent_turn_read("copilot", out)
    assert err is None
    assert session == "48ac578f-15de-4b10-b255-c2d4518af86c"
    assert payload == out


def test_copilot_without_a_resume_id_is_an_error_not_a_pass():
    """Un turno sin id no es un detalle: el turno siguiente abre otra sesión, el
    modelo no ve lo que acaba de hacer, y el escenario mide primeros turnos
    mientras dice que midió una conversación."""
    payload, session, err = runner.agent_turn_read("copilot", "hecho, saludos")
    assert session is None
    assert err and "new session" in err


def test_the_copilot_tap_wraps_the_repo_hooks(tmp_path):
    """El cableado de nivel usuario corre el script DEL REPO por path relativo,
    así que envolver la copia del repo es lo único que hay para envolver."""
    hooks = tmp_path / ".github" / "hooks" / "ddw"
    hooks.mkdir(parents=True)
    for name in ("pre-tool-use.sh", "post-write.sh", "pre-compact.sh"):
        (hooks / name).write_text("#!/usr/bin/env bash\nexit 0\n")
    assert runner._tap_copilot(tmp_path) == 2
    for name in ("pre-tool-use.sh", "post-write.sh"):
        assert (hooks / (name[:-3] + ".real.sh")).exists()
        assert "DDW_EVAL_PAYLOAD" in (hooks / name).read_text()
    # pre-compact no es un veredicto: envolverlo pondría un "permitido" en el
    # log por una escritura que nunca existió.
    assert not (hooks / "pre-compact.real.sh").exists()


def test_the_copilot_home_refuses_to_run_unauthenticated(tmp_path, monkeypatch):
    """Un HOME en blanco no tiene credenciales, y Copilot falla de una forma que
    se lee como veredicto del producto."""
    fake = tmp_path / "fakehome"
    (fake / ".copilot").mkdir(parents=True)
    (fake / ".copilot" / "config.json").write_text("{}")
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(fake)) if p.startswith("~") else p)
    with pytest.raises(RuntimeError) as e:
        runner.copilot_home(tmp_path / "wd", tmp_path / "wd" / "repo")
    assert "credentials" in str(e.value)


def test_the_copilot_home_carries_credentials_and_trusts_the_fixture(tmp_path, monkeypatch):
    fake = tmp_path / "fakehome"
    (fake / ".copilot").mkdir(parents=True)
    # JSONC: el archivo real abre con dos líneas `//`. Parseado como JSON
    # estricto revienta, las credenciales se pierden en silencio, y la corrida
    # falla autenticando.
    (fake / ".copilot" / "config.json").write_text(
        '// managed automatically\n{"copilotTokens": {"t": 1}, "trustedFolders": ["/otro"]}\n')
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(fake)) if p.startswith("~") else p)
    wd = tmp_path / "wd"
    repo = wd / "repo"
    home = runner.copilot_home(wd, repo)
    cfg = json.loads((home / ".copilot" / "config.json").read_text())
    assert cfg["copilotTokens"] == {"t": 1}
    assert str(repo) in cfg["trustedFolders"] and "/otro" in cfg["trustedFolders"]
    # Y NADA más cruza: la sesión, los settings y los hooks arrancan vacíos.
    assert sorted(p.name for p in (home / ".copilot").iterdir()) == ["config.json"]


# ── Lo que el arnés tiene que hacer bien para que una corrida signifique algo ──
#
# Las tres de abajo salieron de mutaciones que SOBREVIVIERON: el código estaba
# bien y no había nada que lo sostuviera. Un fault que nadie mata es un fault
# que vuelve.


def _fake_install(runner_mod, monkeypatch, calls, wire_hooks=True):
    """Reemplaza `sh` por algo que finge la instalación y anota cómo la llamaron."""
    real_sh = runner_mod.sh

    def fake(cmd, cwd=None, env=None, timeout=120, stdin=None):
        calls.append({"cmd": cmd, "env": env})
        if any("install.sh" in str(c) for c in cmd):
            repo = pathlib.Path(cmd[2])
            (repo / ".ddw" / "scripts").mkdir(parents=True, exist_ok=True)
            (repo / ".ddw" / "scripts" / "hook-gate.py").write_text("x")
            if wire_hooks and env and env.get("HOME"):
                d = pathlib.Path(env["HOME"]) / ".copilot" / "hooks"
                d.mkdir(parents=True, exist_ok=True)
                (d / "ddw.json").write_text("{}")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_sh(cmd, cwd=cwd, env=env, timeout=timeout, stdin=stdin)

    monkeypatch.setattr(runner_mod, "sh", fake)


def _fake_creds(runner_mod, monkeypatch, tmp_path):
    fake = tmp_path / "fakehome"
    (fake / ".copilot").mkdir(parents=True, exist_ok=True)
    (fake / ".copilot" / "config.json").write_text('{"copilotTokens": {"t": 1}}')
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: p.replace("~", str(fake)) if p.startswith("~") else p)


def test_a_copilot_install_never_touches_the_operators_own_home(tmp_path, monkeypatch):
    """Instalar para Copilot escribe FUERA del fixture, en `$HOME`. Sin un HOME
    propio, una sola corrida de evals recablea todas las sesiones de Copilot de
    la máquina, y dos corridas en paralelo se recablean entre sí."""
    _fake_creds(runner, monkeypatch, tmp_path)
    calls = []
    _fake_install(runner, monkeypatch, calls)
    wd = tmp_path / "wd"
    runner.make_repo(tmp_path / "src", "copilot", wd)
    install = [c for c in calls if any("install.sh" in str(x) for x in c["cmd"])][0]
    assert install["env"] is not None, "la instalación de Copilot corrió con el HOME del operador"
    assert install["env"]["HOME"] == str(wd / "home")
    assert install["env"]["HOME"] != os.environ.get("HOME")


def test_a_copilot_install_that_wired_no_hooks_is_refused(tmp_path, monkeypatch):
    """Salir 0 sin cablear nada es la forma exacta en que esto se veía sano: el
    escenario corre, nada juzga, y el resultado se lee como un pase limpio."""
    _fake_creds(runner, monkeypatch, tmp_path)
    calls = []
    _fake_install(runner, monkeypatch, calls, wire_hooks=False)
    with pytest.raises(RuntimeError) as e:
        runner.make_repo(tmp_path / "src", "copilot", tmp_path / "wd")
    assert "user-level" in str(e.value)


def test_the_verdict_tap_covers_copilot(tmp_path, monkeypatch):
    """`_tap_copilot` puede estar perfecto y no ser llamado por nadie."""
    monkeypatch.setattr(runner, "_tap_claude", lambda repo: 0)
    monkeypatch.setattr(runner, "_tap_opencode", lambda repo: 0)
    hooks = tmp_path / ".github" / "hooks" / "ddw"
    hooks.mkdir(parents=True)
    for name in ("pre-tool-use.sh", "post-write.sh"):
        (hooks / name).write_text("#!/usr/bin/env bash\nexit 0\n")
    assert runner.install_verdict_tap(tmp_path) == 2
