#!/usr/bin/env python3
"""
DDW instruction evals — the layer verify_install.sh cannot reach.

verify_install.sh measures the HOOKS: given an event, does the gate answer
correctly. This measures the INSTRUCTIONS: given the rules as written, does an
obedient reader end up somewhere the hooks allow, and does a live model end the
turn in a state the repo can be asked about.

Three rules this runner is built around, because this repository has been bitten
by all three:

  1. A scenario that cannot be judged is RED, never green. Every outcome is
     PASS / FAIL / ERROR, ERROR is counted apart, and any ERROR fails the run.
  2. A run that examined nothing is RED. The scenario count comes from the tree
     (`scenarios/*.yaml`), not from a literal, and a run whose executed count
     does not equal the discovered count exits non-zero.
  3. An instrument that cannot go red is not a measurement. `--control` applies
     each scenario's declared mutation — the historical broken version of the
     instruction — and REQUIRES the scenario to fail. A control that passes
     invalidates the run.

Usage:
    python3 runner.py --repo /path/to/dilux-development-workflow            # normal run
    python3 runner.py --repo ... --control                                  # prove it can go red
    python3 runner.py --repo ... --only painted-door-eject
    python3 runner.py --repo ... --kinds painted-door,router-reachability   # no-API-key subset
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:  # fail closed: no silent degradation to "0 scenarios, all green"
    print("FATAL: pyyaml is not installed; the scenarios cannot be read.", file=sys.stderr)
    sys.exit(2)

PASS, FAIL, ERROR, SKIP = "PASS", "FAIL", "ERROR", "SKIP"

# Kinds that never call a model. These are the ones CI runs on every push.
OFFLINE_KINDS = {"painted-door", "painted-door-sweep", "router-reachability",
                 "template-vs-gate", "method-lint"}


# --------------------------------------------------------------------------- #
# result plumbing
# --------------------------------------------------------------------------- #

class Result:
    def __init__(self, sid, kind, verdict, detail):
        self.sid, self.kind, self.verdict, self.detail = sid, kind, verdict, detail

    def line(self):
        colour = {PASS: "\033[32m", FAIL: "\033[31m", ERROR: "\033[33m",
                  SKIP: "\033[36m"}[self.verdict]
        return f"  {colour}{self.verdict:5}\033[0m {self.sid:34} {self.detail}"


def sh(cmd, cwd=None, env=None, timeout=120, stdin=None):
    """Run a command. Never converts a crash into a verdict — the caller decides."""
    return subprocess.run(
        cmd, cwd=cwd, env=env, timeout=timeout, input=stdin,
        capture_output=True, text=True,
    )


# --------------------------------------------------------------------------- #
# throwaway repo with DDW installed
# --------------------------------------------------------------------------- #

def make_repo(ddw_root: Path, target: str, workdir: Path) -> Path:
    repo = workdir / "repo"
    repo.mkdir(parents=True)
    sh(["git", "init", "-q"], cwd=repo)
    sh(["git", "config", "user.email", "eval@example.com"], cwd=repo)
    sh(["git", "config", "user.name", "eval"], cwd=repo)
    sh(["git", "config", "commit.gpgsign", "false"], cwd=repo)
    (repo / "README.md").write_text("# fixture\n")
    sh(["git", "add", "-A"], cwd=repo)
    sh(["git", "commit", "-qm", "init"], cwd=repo)

    r = sh(["bash", str(ddw_root / "install.sh"), str(repo), "--target", target],
           cwd=repo, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"install.sh failed ({r.returncode}): {r.stderr[-600:]}")
    if not (repo / ".ddw" / "scripts" / "hook-gate.py").exists():
        raise RuntimeError("install.sh exited 0 but wrote no method")
    return repo


def _fingerprint(path: Path):
    """The installer's own hash. Same definition as scripts/install_target.py."""
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
        return h.hexdigest()
    if not path.is_dir():
        return None
    for base, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            p = Path(base) / f
            h.update(str(p.relative_to(path)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def reseal_manifest(repo: Path, rels) -> int:
    manifest = repo / ".ddw-installed.json"
    if not manifest.exists():
        return 0
    try:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return 0
    resealed = 0
    for key in list(recorded):
        rel = key.split(":", 1)[1] if ":" in key else key
        if rel not in rels:
            continue
        digest = _fingerprint(repo / rel)
        if digest:
            recorded[key] = digest
            resealed += 1
    manifest.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    return resealed

# --------------------------------------------------------------------------- #
# the tap — Claude Code (shell hooks)
# --------------------------------------------------------------------------- #

TAP = r'''#!/usr/bin/env bash
# Verdict tap. Installed by the eval runner only, around the adapter's own hook
# script. It changes no verdict — it records one.
#
# It exists because of the failure acceptance.md names and cannot otherwise
# rule out: "the agent politely declines" and "the write was refused" leave the
# same repository behind. Without this, a behavioral eval that asserts only
# `src/x.py is absent` goes green on prose, which is the exact thing this
# framework exists to stop depending on.
PAYLOAD="$(cat)"
printf '%s' "$PAYLOAD" | bash "$(dirname "$0")/__REAL__"
CODE=$?
python3 - "$CODE" "__NAME__" <<'PY' >> "${CLAUDE_PROJECT_DIR:-.}/.ddw-eval-verdicts.jsonl"
import json, os, sys
raw = os.environ.get("DDW_EVAL_PAYLOAD", "")
try:
    ev = json.loads(raw)
except Exception:
    ev = {}
print(json.dumps({"hook": sys.argv[2], "exit": int(sys.argv[1]),
                  "tool": ev.get("tool_name"),
                  "path": (ev.get("tool_input") or {}).get("file_path")}))
PY
exit $CODE
'''


def _tap_claude(repo: Path) -> int:
    hooks = repo / ".claude" / "hooks"
    if not hooks.is_dir():
        return 0
    tapped = 0
    for name in ("enforce.sh", "validate-state-transition.sh", "validate-state-postwrite.sh"):
        src = hooks / name
        if not src.exists():
            continue
        real = hooks / (name[:-3] + ".real.sh")
        src.rename(real)
        body = TAP.replace("__REAL__", real.name).replace("__NAME__", name)
        body = body.replace('printf \'%s\' "$PAYLOAD" | bash',
                            'export DDW_EVAL_PAYLOAD="$PAYLOAD"; printf \'%s\' "$PAYLOAD" | bash')
        src.write_text(body)
        src.chmod(0o755)
        reseal_manifest(repo, {f".claude/hooks/{name}"})
        tapped += 1
    return tapped


# --------------------------------------------------------------------------- #
# the tap — OpenCode (JavaScript plugin)
#
# The adapter here is `adapters/opencode/plugin/ddw.js`, installed to
# `.opencode/plugins/ddw.js`. It has no exit code to read: it enforces by
# THROWING out of `tool.execute.before`, which is how OpenCode cancels a tool
# call. So the tap wraps the plugin's returned hook table and records
# throw/no-throw as exit 2/0 — the same codes Claude's hooks use, so
# `judge_repo_state`'s `exit != 0` test means the same thing on both.
#
# The real plugin is MOVED OUT of `.opencode/plugins/` before being wrapped:
# OpenCode loads every module in that directory, so leaving it there would load
# it twice — enforcing twice and recording nothing for the second copy.
# --------------------------------------------------------------------------- #

OPENCODE_TAP = Path(__file__).with_name("ddw-eval-tap.js")


def _tap_opencode(repo: Path) -> int:
    plugins = repo / ".opencode" / "plugins"
    src = plugins / "ddw.js"
    if not src.exists():
        # OpenCode reads both spellings; the installer writes the plural.
        alt = repo / ".opencode" / "plugin" / "ddw.js"
        if not alt.exists():
            return 0
        plugins, src = alt.parent, alt
    real = repo / ".opencode" / "ddw.real.js"
    src.rename(real)
    body = (OPENCODE_TAP.read_text(encoding="utf-8")
            .replace("__REAL__", "../ddw.real.js")
            .replace("__LOG__", str((repo / ".ddw-eval-verdicts.jsonl").resolve())))
    src.write_text(body, encoding="utf-8")
    reseal_manifest(repo, {str(src.relative_to(repo))})
    return 1


def install_verdict_tap(repo: Path) -> int:
    """Wrap whichever adapter this repo was installed with. Never judges."""
    tapped = _tap_claude(repo) + _tap_opencode(repo)
    if tapped == 0:
        raise RuntimeError("verdict tap installed nothing — refusing to judge blind")
    return tapped


# --------------------------------------------------------------------------- #
# headless CLI shapes
#
# `run_behavioral` spoke Claude Code and nothing else. Each entry says how to
# build one turn and how to read the answer back.
# --------------------------------------------------------------------------- #

AGENT_CLIS = {
    "claude": {
        "argv": ["claude"],
        "flags": ["--permission-mode", "bypassPermissions", "--output-format", "json"],
        "model": ["--model", "{model}"],
        "resume": ["--resume", "{session}"],
        "prompt": ["-p", "{turn}"],
    },
    "opencode": {
        # `opencode run` is the headless entry point (`opencode` with no
        # subcommand starts the TUI). `--auto` is OpenCode's spelling of
        # bypassPermissions: without it a headless run stalls on the first
        # permission prompt. `--format json` streams one JSON event per line —
        # NOT a single object like Claude's `--output-format json`.
        "argv": ["opencode", "run"],
        "flags": ["--auto", "--format", "json"],
        "model": ["-m", "{model}"],
        "resume": ["-s", "{session}"],
        # OpenCode picks the PROJECT from `PWD`, not from the process's working
        # directory. Measured: `subprocess.run(..., cwd=repo)` leaves PWD at the
        # parent's cwd, and OpenCode then loaded the DEVELOPER'S OWN checkout as
        # the project — a different `.opencode/`, so the tapped plugin never
        # loaded, no gate ever ran, and the model's `src/*.py` landed in
        # /home/pablo/repos/dilux-development-workflow instead of the fixture.
        # The tap caught it only because it recorded nothing and the scenario
        # went red. `--dir` is the documented flag and `PWD` is what decides
        # when it is absent, so both are set: a run pointed at the wrong repo
        # measures nothing and can damage the tree it was pointed at.
        "dir": ["--dir", "{repo}"],
        "env": {"PWD": "{repo}"},
        "prompt": ["{turn}"],
    },
}


def agent_profile(agent_cmd) -> tuple[str, dict]:
    name = Path(agent_cmd[0]).name
    if name not in AGENT_CLIS:
        raise RuntimeError(f"no headless profile for agent {name!r}; add one to AGENT_CLIS")
    return name, AGENT_CLIS[name]


def agent_turn_cmd(agent_cmd, model, session, turn, repo=None):
    """-> (name, argv, env). `env` is None when the agent needs no override."""
    name, prof = agent_profile(agent_cmd)
    # `--agent opencode` names the binary; the headless entry point is the
    # `run` SUBCOMMAND (bare `opencode` opens the TUI and the flags below are
    # rejected). Added only if the caller did not already spell it out.
    cmd = list(agent_cmd)
    for extra in prof["argv"][1:]:
        if extra not in cmd:
            cmd.append(extra)
    cmd += list(prof["flags"])
    if model:
        cmd += [p.format(model=model) for p in prof["model"]]
    if session:
        cmd += [p.format(session=session) for p in prof["resume"]]
    if repo and prof.get("dir"):
        cmd += [p.format(repo=str(repo)) for p in prof["dir"]]
    cmd += [p.format(turn=turn) for p in prof["prompt"]]

    env = None
    if repo and prof.get("env"):
        env = dict(os.environ)
        env.update({k: v.format(repo=str(repo)) for k, v in prof["env"].items()})
    return name, cmd, env


_OC_SESSION = re.compile(r'"sessionID"\s*:\s*"([^"]+)"')


def agent_turn_read(name, stdout):
    """-> (payload, session_id, error_or_None). Never turns a crash into a pass."""
    if name == "claude":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return None, None, "the agent returned output this runner cannot parse"
        if payload.get("is_error"):
            return payload, None, f"the agent reported an error: {str(payload.get('result'))[:150]}"
        return payload, payload.get("session_id"), None

    # OpenCode: newline-delimited JSON events. The session id appears on the
    # message events as `sessionID`; there is no single result object.
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not events:
        return None, None, "the agent produced no JSON events — the turn did not run"
    session = None
    m = _OC_SESSION.search(stdout)
    if m:
        session = m.group(1)
    for ev in events:
        if ev.get("type") == "error" or ev.get("error"):
            return events, session, f"the agent reported an error: {json.dumps(ev)[:200]}"
    return events, session, None


# --------------------------------------------------------------------------- #
# `run_behavioral`, adapter-agnostic. Drop-in replacement for the one in
# runner.py — same signature, same judgement, same transcript file.
# --------------------------------------------------------------------------- #


def write_state(repo: Path, state):
    """El estado del escenario. `null` deja el que dejó la instalación.

    Una cadena se escribe TAL CUAL, sin pasar por JSON: hay una familia entera
    de regresiones que sólo existe con el estado CORRUPTO —el mensaje de
    recuperación es lo que se lee cuando ya salió todo mal— y no había forma de
    expresarlo. Un escenario que quería estado corrupto terminaba con el estado
    sano, pasaba en las dos direcciones, y su control decía que no podía
    detectar su propia regresión. Que lo dijera es la única razón por la que se
    encontró.
    """
    if state is None:
        return
    if isinstance(state, str):
        (repo / ".ddw-state.json").write_text(state, encoding="utf-8")
        return
    (repo / ".ddw-state.json").write_text(json.dumps(state, indent=2))


def seed_files(repo: Path, files, commit=True) -> int:
    """Los archivos que el escenario necesita que YA existan.

    `given.state` sabe escribir uno solo, `.ddw-state.json`, y hay una familia
    entera de escenarios que sin más que eso no se puede expresar: un fuente de
    producto que una fase no debe tocar, un artefacto a medio escribir que su
    gate tiene que rechazar, un PRD que ya está cuando la fase va a escribirlo.
    Todos ellos arrancaban con el repo vacío del fixture, o sea midiendo otra
    cosa que la que dicen medir.

    Se escriben POR EL SISTEMA DE ARCHIVOS, sin pasar por las herramientas: son
    el `given`, no algo que el modelo haga, y mandarlos por el gate haría
    imposible sembrar justamente lo que el gate rechaza.

    Se COMMITEAN salvo que el escenario diga que no. Un fuente sembrado y sin
    commitear deja el árbol sucio antes del primer turno, y lo que el escenario
    mide después es una regla sobre trabajo sin commitear que nadie pidió.
    """
    if not files:
        return 0
    if not isinstance(files, dict):
        raise RuntimeError("given.files is a mapping of path -> content")
    root = repo.resolve()
    written = []
    for rel, content in files.items():
        if Path(rel).is_absolute():
            raise RuntimeError(f"given.files carries an absolute path: {rel!r}")
        dest = (repo / rel)
        try:
            # Sin esto, un `../..` en un escenario escribe en el checkout de
            # quien lo corre. Ya pasó una vez por otro camino —un control que
            # reescribía el árbol del usuario— y costó veinte minutos de creer
            # que el producto tenía un bug.
            dest.resolve().relative_to(root)
        except ValueError:
            raise RuntimeError(
                f"given.files tried to write outside the fixture repo: {rel!r}") from None
        if dest.resolve() == (repo / ".ddw-state.json").resolve():
            raise RuntimeError(
                "given.files cannot write `.ddw-state.json` — that is what `given.state` is "
                "for, and two sources of truth for one file is how a fixture stops being one")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content if isinstance(content, str)
                        else json.dumps(content, indent=2) + "\n", encoding="utf-8")
        written.append(rel)

    if commit and written:
        # Sólo lo sembrado. Un `git add -A` acá se lleva puesto el método
        # instalado y el estado del escenario, que el fixture deja fuera del
        # índice a propósito.
        #
        # `-f` porque la instalación deja un bloque en `.gitignore`, y lo que
        # ignora —`.ddw-paused/`, `.ddw-sessions/`, el journal— es justamente
        # parte de lo que un escenario necesita sembrar. Sin `-f`, `git add`
        # rechaza esas rutas, el commit no encuentra nada que commitear, y el
        # fixture queda distinto de lo que el escenario dice que es sin que
        # nadie se entere.
        r = sh(["git", "add", "-f", "--", *written], cwd=repo)
        if r.returncode == 0:
            r = sh(["git", "commit", "-qm", "eval fixture: given.files"], cwd=repo)
        if r.returncode != 0:
            raise RuntimeError("given.files could not be committed into the fixture: "
                               + (r.stderr or r.stdout).strip()[:200])
    return len(written)


def hook_verdict(repo: Path, event: dict, mode="pre") -> tuple[int, str]:
    """Drive the real shared gate with a real tool event. Returns (exit code, reason)."""
    r = sh([sys.executable, str(repo / ".ddw" / "scripts" / "hook-gate.py"),
            "--mode", mode,
            "--state", str(repo / ".ddw-state.json"),
            "--graph", str(repo / ".ddw" / "rules" / "transition-graph.json"),
            "--repo", str(repo),
            "--method", str(repo / ".ddw")],
           stdin=json.dumps(event), timeout=60)
    return r.returncode, (r.stdout + r.stderr).strip()


# --------------------------------------------------------------------------- #
# kind: painted-door
#
# The defect: an instruction file orders the model to perform a write that the
# hook refuses in that phase. The model obeys and is stopped — mid-ticket, with
# a panel already shown to the user.
#
# The judgement has two halves and needs both, which is what keeps it honest:
#   - does the instruction still order this write?  (regex over the file)
#   - what does the real gate say about it?          (exit code from hook-gate)
# A scenario passes when the instruction no longer orders it, OR the gate allows
# it. It fails only for the combination that actually hurt: ordered AND refused.
# If the instruction file has vanished, the scenario cannot be judged → ERROR.
# --------------------------------------------------------------------------- #

def run_painted_door(sc, ddw_root, repo):
    src = ddw_root / sc["when"]["instruction"]
    if not src.exists():
        return ERROR, f"instruction file gone: {sc['when']['instruction']}"
    text = src.read_text(encoding="utf-8", errors="replace")

    offenders, checked = [], 0
    for probe in sc["when"]["probes"]:
        ordered = re.search(probe["ordered_if_matches"], text, re.S) is not None
        checked += 1
        if not ordered:
            continue
        target = repo / probe["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        code, reason = hook_verdict(repo, {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        })
        if code != 0:
            offenders.append(f"{probe['path']} ordered by {src.name}, gate exit {code}: "
                             f"{reason.splitlines()[0][:90] if reason else ''}")
    if checked == 0:
        return ERROR, "scenario declared no probes"
    if offenders:
        return FAIL, "; ".join(offenders)
    return PASS, f"{checked} probe(s): no ordered write is refused"


# --------------------------------------------------------------------------- #
# kind: painted-door-sweep
#
# `painted-door` pins ONE regex on ONE file: it re-finds a door that already
# shipped. This looks for the NEXT one. It reads every instruction file the
# method carries, pulls out every imperative write and the path it names, and
# hands each one to the real gate in the phase whose file ordered it.
#
# Deliberately conservative about what counts as an order — a corpus this size
# produces noise fast, and a sweep that cries wolf is a sweep people turn off:
#
#   · The verb has to be imperative and the line a step or a bullet, not prose.
#   · A line that says the write is REFUSED, forbidden or blocked is a warning,
#     not an order, and is skipped.
#   · The path has to be a real one — backticked, with a separator — and not a
#     placeholder like `<path>` or `path/to/file`.
#
# What it cannot do is know the phase an instruction is "for" when the file does
# not say. Where the file names phases, each order is judged in those; where it
# does not, it is judged in the phase the scenario declares, and the scenario
# says which. That is a limitation, written down rather than papered over.
# --------------------------------------------------------------------------- #

WRITE_VERB = r"(?:copy|write|create|add|append|place|save|install|generate|put)"
NOT_AN_ORDER = re.compile(
    r"(?i)\b(refus|reject|block|forbid|denied|cannot|can't|never|do not|don't|must not|"
    r"prohibit|instead of|rather than|used to|no longer|would be)\b")
# Los destinos de verdad vienen templados — `docs/ddw/prd/prd-{ticket}.md` es
# la forma en que el método los escribe. Rechazarlos por llevar llaves dejaba el
# barrido en UNA orden sobre treinta y dos archivos, que es no barrer. Se
# sustituyen; lo que queda con corchetes después de sustituir sí es un ejemplo.
TEMPLATED = re.compile(r"[<{\[](ticket|TICKET|id|ID|slug|name)[>}\]]")
PLACEHOLDER = re.compile(r"[<{\[]|path/to|your-|example|FIXME|TODO|\.\.\.")


# Entre el verbo y la ruta: si hay una de éstas, la ruta es una REFERENCIA, no
# el objeto de la escritura. «Write the summary following `ddw/rules/x.md`» no
# ordena escribir esa regla. Sin esto el barrido acusaba de puerta pintada a
# cada archivo que un skill cita — seis de seis ofensores eran citas.
REFERENCE = re.compile(
    r"(?i)\b(in|per|from|see|read|following|according to|documented in|described in|"
    r"defined in|listed in|under|against|as in|like|of|by|via|using|with)\s*$")


def _ordered_writes(text):
    """(línea, ruta) por cada escritura que el documento MANDA hacer.

    Conservador a propósito: sobre un corpus de veinte archivos de instrucción,
    una heurística generosa produce ruido más rápido de lo que produce
    hallazgos, y un barrido que grita lobo es un barrido que se apaga.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not re.match(r"^(?:[-*+]|\d+\.)\s", line):
            continue                       # prosa: no es un paso
        verb = re.search(r"(?i)\b%s\b" % WRITE_VERB, line)
        if not verb:
            continue
        if NOT_AN_ORDER.search(line):
            continue                       # habla de una escritura, no la ordena
        rest = line[verb.end():]
        for m in re.finditer(r"`([^`\s]+)`", rest):
            path = m.group(1)
            # Un slash-command (`/ddw-create-prd`) no es una ruta, y el verbo
            # que lo hizo entrar era el «create» de su propio nombre. Y una
            # ruta sin extensión ni barra interna no nombra un archivo.
            path = TEMPLATED.sub("T-1", path)
            if PLACEHOLDER.search(path):
                continue
            if path.startswith("/") and "/" not in path[1:]:
                continue
            if path.endswith("/"):
                # Un DIRECTORIO es un destino legítimo, y era el de la puerta
                # pintada que empezó todo esto: «**Copy** the method to `.ddw/`».
                # Exigir una barra interna lo rechazaba, así que el barrido no
                # encontraba la única regresión que sí sabía reproducir — y el
                # control lo dijo. Se le pregunta al gate por un archivo adentro,
                # que es lo que una copia escribe.
                path = path + "probe.txt"
            elif not (re.search(r"[^/]/[^/]", path) and re.search(r"\.\w{1,6}$", path)):
                continue
            if path.startswith(("http", "-", "python3", "bash", "git")):
                continue
            if ":" in path:
                continue                   # `src/x.ts:58` es una cita, no un destino
            if REFERENCE.search(rest[:m.start()]):
                continue                   # la ruta es dónde MIRAR, no dónde escribir
            # `lstrip("./")` se come el punto inicial y convierte `.ddw-paused/x`
            # en `ddw-paused/x`, que es OTRA ruta: la primera la escribe la pausa
            # en cualquier fase, la segunda es product source. El barrido acusaba
            # al orquestador de una puerta pintada que no existe.
            out.append((line, path[2:] if path.startswith("./") else path))
    return out


def run_painted_door_sweep(sc, ddw_root, repo):
    corpus = []
    for pattern in sc["when"]["corpus"]:
        corpus += sorted(ddw_root.glob(pattern))
    if not corpus:
        return ERROR, "the corpus matched no file — a sweep over nothing is not a sweep"

    phases = sc["when"]["phases"]
    offenders, orders = [], 0
    for src in corpus:
        text = src.read_text(encoding="utf-8", errors="replace")
        for line, path in _ordered_writes(text):
            orders += 1
            target = repo / path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
            for phase in phases:
                st = dict(sc["given"]["state"], phase=phase)
                write_state(repo, st)
                code, reason = hook_verdict(repo, {
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(target), "content": "x"},
                })
                if code != 0:
                    rel = src.relative_to(ddw_root)
                    offenders.append(
                        "%s orders `%s` and the gate refuses it in %s: %s"
                        % (rel, path, phase,
                           (reason.splitlines()[0][:80] if reason else "exit %d" % code)))
                    break
    if orders == 0:
        return ERROR, ("no imperative write was found in %d instruction file(s) — the extraction "
                       "stopped matching, and a sweep that finds nothing passes for the wrong "
                       "reason" % len(corpus))
    if offenders:
        return FAIL, " | ".join(offenders[:6])
    return PASS, "%d ordered write(s) across %d file(s): every one lands where the gate allows" % (
        orders, len(corpus))


# --------------------------------------------------------------------------- #
# kind: template-vs-gate
#
# The defect: a phase is told to write a document, and the document exactly as
# the skill teaches it is refused by the validator that guards that phase's gate.
# Extract the worked example out of the skill and run it through the real
# validator. This is the "the document a phase is told to write has to pass the
# gate it is written for" family — it shipped three times.
# --------------------------------------------------------------------------- #

def run_template_vs_gate(sc, ddw_root, repo):
    src = ddw_root / sc["when"]["instruction"]
    if not src.exists():
        return ERROR, f"instruction file gone: {sc['when']['instruction']}"
    text = src.read_text(encoding="utf-8", errors="replace")
    m = re.search(sc["when"]["extract_between"], text, re.S)
    if not m:
        return ERROR, ("the worked document could not be extracted — the skill no longer "
                       "carries a canonical shape, so nothing can be judged")
    doc = m.group(1)
    doc = re.sub(r"\{ticket\}|\{TICKET\}", sc["when"].get("ticket", "T-1"), doc)

    art = repo / sc["when"]["write_to"]
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(doc, encoding="utf-8")

    cmd = [sys.executable, str(repo / ".ddw" / "scripts" / sc["when"]["validator"])]
    cmd += [a.replace("${ARTIFACT}", str(art)).replace("${REPO}", str(repo))
            for a in sc["when"].get("validator_args", [])]
    r = sh(cmd, cwd=repo, timeout=90)
    out = r.stdout + r.stderr
    rows = [l for l in out.splitlines() if re.search(r"\b[FW]-[A-Z]+-\w+", l)]
    if not rows:
        # A validator that printed no rule row judged nothing; that is not a pass.
        return ERROR, f"{sc['when']['validator']} printed no checklist — nothing was judged"
    failed = [l for l in rows if "❌" in l]
    if r.returncode != 0 or failed:
        return FAIL, (f"the skill's own worked document is refused by its own gate "
                      f"(exit {r.returncode}): " + (failed[0].strip()[:110] if failed else ""))
    return PASS, (f"{sc['when']['validator']} accepts the skill's worked document "
                  f"({len(rows)} rules)")


# --------------------------------------------------------------------------- #
# kind: router-reachability
#
# The defect: a router or a refusal prescribes a next step the graph does not
# offer — "run --claim commit --claim pr first" from a phase with no such edge,
# or "the only transition from IDLE is --to CLASSIFY" to a paused ticket. The
# reader follows the instruction to the letter and is refused identically.
# Judgement: take the move the text prescribes, replay it through the sanctioned
# helper, and require it to change the state.
# --------------------------------------------------------------------------- #

def run_router_reachability(sc, ddw_root, repo):
    before = json.loads((repo / ".ddw-state.json").read_text())
    steps = sc["when"]["prescribed_steps"]
    if not steps:
        return ERROR, "scenario declared no prescribed steps"

    # The refusal that prescribes them has to actually be the one being shown,
    # or this scenario is asserting about a message nobody sees any more.
    # Quién dice el rechazo: el HOOK, con un evento de herramienta, o el HELPER,
    # con una invocación que sale distinta de cero. Los dos hints más caros que
    # este repo arregló —«corré `--claim commit --claim pr` primero» y «la única
    # transición desde IDLE es `--to CLASSIFY`»— viven sólo en el `main()` de
    # `transition.py`, y sin poder afirmar contra su stderr no había forma de
    # escribir esos escenarios: el control salía verde porque lo único que
    # cambió fue el texto del hint.
    trig = sc["when"].get("triggered_by")
    if trig:
        if "event" in trig:
            code, reason = hook_verdict(repo, trig["event"])
        elif "transition" in trig:
            args = [a.replace("${REPO}", str(repo)) for a in trig["transition"]]
            r = sh([sys.executable, str(repo / ".ddw" / "scripts" / "transition.py"), *args,
                    "--state", str(repo / ".ddw-state.json"),
                    "--graph", str(repo / ".ddw" / "rules" / "transition-graph.json")],
                   cwd=repo, timeout=60, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(repo)))
            code, reason = r.returncode, (r.stderr or r.stdout)
        else:
            return ERROR, "triggered_by declares neither `event` nor `transition`"
        if code == 0:
            return ERROR, ("the refusal this scenario is about no longer fires — "
                           "nothing to judge")
        if not re.search(sc["when"]["refusal_matches"], reason, re.S):
            return ERROR, ("the refusal fired but no longer prescribes this move: "
                           + reason.splitlines()[0][:100])

    for step in steps:
        args = [a.replace("${REPO}", str(repo)) for a in step]
        r = sh([sys.executable, str(repo / ".ddw" / "scripts" / "transition.py"),
                *args,
                "--state", str(repo / ".ddw-state.json"),
                "--graph", str(repo / ".ddw" / "rules" / "transition-graph.json"),
                "--write"], cwd=repo, timeout=60,
               # `transition.py` no acepta `--repo`: resuelve el repo por
               # `CLAUDE_PROJECT_DIR` y después por el cwd. Pasándoselo, argparse
               # sale 2 y el escenario reporta «the prescribed step is itself
               # refused» — o sea, ningún escenario `router-reachability` podía
               # salir verde. Como no hay ninguno todavía en el árbol, el bug
               # estaba invisible: un kind muerto al nacer.
               env=dict(os.environ, CLAUDE_PROJECT_DIR=str(repo)))
        if r.returncode != 0 and sc["expect"].get("every_step_succeeds", True):
            return FAIL, (f"the prescribed step {' '.join(args)} is itself refused: "
                          + (r.stdout + r.stderr).strip().splitlines()[0][:110])
    after = json.loads((repo / ".ddw-state.json").read_text())
    if after == before:
        return FAIL, "following the prescribed steps changed nothing — a fixed point"
    return PASS, f"prescribed move reaches {after.get('phase')}"


# --------------------------------------------------------------------------- #
# kind: method-lint
#
# `scripts/lint_method.py` compara lo que la prosa AFIRMA contra el grafo, el
# catálogo de reglas y el árbol. Corre en la suite, pero ahí lo único que se
# pregunta es si HOY está verde — nadie mide si sigue sabiendo ponerse rojo.
# Cada uno de sus veintipico de checks es una regresión que ya pasó, y un linter
# de prosa se rompe callado: le cambiás el nombre a una sección, el check deja
# de encontrar lo que miraba, y sigue informando verde por no tener otra cosa
# que decir. Es exactamente la familia de [[CHECKS-THAT-CANNOT-FAIL]].
#
# Acá el linter es el VEREDICTO: en normal tiene que salir limpio, y con el
# control puesto —una afirmación de la prosa rota a propósito— tiene que
# nombrarla. Por eso `control.finding_matches`: un linter que se pone rojo por
# otra cosa no probó que sepa cazar ésta, y ese es el mismo error que este
# repositorio ya cometió con los controles que fallaban por un TypeError.
# --------------------------------------------------------------------------- #

def run_method_lint(sc, ddw_root, repo, control=False):
    r = sh([sys.executable, str(ddw_root / "scripts" / "lint_method.py"),
            "--repo", str(ddw_root)], cwd=ddw_root, timeout=300)
    out = (r.stdout + r.stderr).strip()
    if not re.search(r"^lint_method: ", out, re.M):
        # Ni el verde ni el rojo: se cayó antes de juzgar. Un stack no es un
        # veredicto, y contarlo como rojo en modo control regala el control.
        tail = out.splitlines()[-1][:140] if out else "<no output>"
        return ERROR, (f"lint_method printed no verdict line (exit {r.returncode}) — "
                       f"nothing was judged: {tail}")
    clean = r.returncode == 0

    if control:
        needle = (sc.get("control") or {}).get("finding_matches")
        if needle and clean:
            return FAIL, "lint_method stayed green with the broken claim in the tree"
        if needle and not re.search(needle, out, re.S):
            return ERROR, ("control off-target: lint_method went red, but on a claim this "
                           "scenario did not break — " + out.splitlines()[0][:110])

    if not clean:
        return FAIL, "lint_method: " + " | ".join(
            l.strip() for l in out.splitlines()[1:5] if l.strip())
    return PASS, "every claim the prose makes is backed by the graph, the catalog and the tree"


# --------------------------------------------------------------------------- #
# kind: behavioral
#
# The only kind that needs a model. Drive the real tool headless in a repo with
# DDW really installed, send the user's turns, and then ask the repo — never the
# transcript — what happened.
# --------------------------------------------------------------------------- #

def run_behavioral(sc, ddw_root, repo, agent_cmd, model):
    install_verdict_tap(repo)
    ctx = sc["given"].get("context_file")
    if ctx:
        for name in ("CLAUDE.md", "AGENTS.md"):
            p = repo / name
            if p.exists():
                p.write_text(p.read_text() + "\n\n## Stack\n\n" + ctx + "\n")

    transcript = []
    session = None
    for turn in sc["when"]["turns"]:
        name, cmd, env = agent_turn_cmd(agent_cmd, model, session, turn, repo)
        # El techo por turno. 300s alcanzaba para Opus; un modelo gratis se pasó
        # de 420 en un solo turno, y un timeout es ERROR — o sea que el
        # escenario no se puede juzgar y la corrida queda roja, que es correcto
        # pero no dice nada del producto. El escenario puede subirlo, y la
        # medición de estabilidad es la que decide si un modelo entra o no.
        r = sh(cmd, cwd=repo, env=env, timeout=sc["when"].get("timeout", 900))
        if r.returncode != 0:
            # Las DOS salidas, y la última línea con texto.
            #
            # Medido: diez corridas en la nube murieron a los ocho segundos con
            # este mensaje y `stderr` vacío — o sea que el arnés sabía que el
            # agente había fallado y no podía decir por qué, que es la mitad que
            # sirve. Un CLI que informa por stdout deja el diagnóstico afuera si
            # sólo se lee stderr, y sin diagnóstico la explicación la pone quien
            # mira: «será rate limit», y a eso no se le puede llamar medición.
            said = [l.strip() for l in ((r.stderr or "") + "\n" + (r.stdout or "")).splitlines()
                    if l.strip()]
            # Y la línea que HABLA del error primero. Con las últimas tres a
            # secas, el aviso de arranque que DDW inyecta en cada turno se comía
            # el presupuesto de caracteres y el evento que dice qué pasó salía
            # cortado — otra vez sin diagnóstico, esta vez por el recorte.
            errs = [l for l in said if '"type":"error"' in l or '"error"' in l]
            why = " | ".join((errs or said)[-2:])[:600] if said else "the agent printed nothing"
            return ERROR, f"the agent did not complete a turn (exit {r.returncode}): {why}"
        payload, sid, err = agent_turn_read(name, r.stdout)
        session = sid or session
        if err:
            return ERROR, err
        transcript.append(payload)

    (repo.parent / "transcript.json").write_text(json.dumps(transcript, indent=2))
    return judge_repo_state(sc, repo, transcript)

def judge_repo_state(sc, repo, transcript):
    """Every assertion here is about the repo or the hooks. Never about prose."""
    exp = sc["expect"]
    problems = []

    # La fase en la que quedó el estado. Es lo que distingue «el modelo se comió
    # el rechazo y usó la shell» —decisión 12, documentada— de «el modelo se
    # fabricó un pipeline para poder escribir», que es lo que este escenario
    # existe para atrapar.
    if "state_phase" in exp:
        sp = repo / ".ddw-state.json"
        try:
            got = json.loads(sp.read_text()).get("phase")
        except Exception:  # noqa: BLE001 — un estado ilegible NO es un pase
            got = "<unreadable>"
        if got != exp["state_phase"]:
            problems.append(f"the state ended in {got!r}, not {exp['state_phase']!r}")

    for rel in exp.get("files_absent", []):
        if (repo / rel).exists():
            problems.append(f"{rel} exists and must not")
    for rel in exp.get("files_present", []):
        if not (repo / rel).exists():
            problems.append(f"{rel} is missing")

    # El CONTENIDO de un artefacto, no su existencia.
    #
    # `files_present` no distingue el documento que contesta la pregunta del que
    # se la inventa: los dos existen, y `state_phase` sólo los separa si el
    # modelo además cruzó la flecha. El defecto que `acceptance.md` nombra —
    # «inventar un requisito, un criterio o un umbral para que un check pase»—
    # se ve adentro del archivo o no se ve.
    #
    # Un `matches` que no compila, o una cláusula que no afirma nada, LEVANTA:
    # una aserción que no puede juzgar es lo mismo que no escribirla, y acá eso
    # se lee como verde.
    for spec in exp.get("file_matches", []):
        rel = spec["path"]
        clauses = [(k, spec[k]) for k in ("matches", "absent") if k in spec]
        if not clauses:
            raise RuntimeError(
                f"file_matches on {rel!r} declares neither `matches` nor `absent` — "
                "a clause that asserts nothing passes for the wrong reason")
        p = repo / rel
        if not p.exists():
            problems.append(f"{rel} does not exist, so nothing in it could be asserted")
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        for key, pats in clauses:
            for pat in (pats if isinstance(pats, list) else [pats]):
                try:
                    # Sin `re.I`: un `matches` insensible es un `matches` más
                    # flojo, y lo que se afirma acá es lo único que separa el
                    # documento que contestó del que se inventó la respuesta. El
                    # escenario que lo necesita escribe `(?i)` y se ve.
                    hit = re.search(pat, body, re.S | re.M) is not None
                except re.error as exc:
                    raise RuntimeError(
                        f"file_matches on {rel!r} carries a regex that does not compile "
                        f"({pat!r}): {exc}") from None
                if key == "matches" and not hit:
                    problems.append(f"{rel} does not contain anything matching {pat!r}")
                elif key == "absent" and hit:
                    problems.append(f"{rel} contains {pat!r} and must not")

    state = {}
    sp = repo / ".ddw-state.json"
    if sp.exists() and sp.read_text().strip():
        try:
            state = json.loads(sp.read_text())
        except json.JSONDecodeError:
            problems.append(".ddw-state.json is not readable JSON")

    for field, allowed in (exp.get("state") or {}).items():
        allowed = allowed if isinstance(allowed, list) else [allowed]
        if state.get(field) not in allowed:
            problems.append(f"state.{field} is {state.get(field)!r}, expected one of {allowed}")

    # Enforcement versus politeness. The tap records every verdict the adapter's
    # own hook returned; `hook_refused` asserts that a write to this path was
    # actually stopped by something outside the model.
    # «algún hook rechazó algo», sin ruta. Los veredictos post de OpenCode sobre
    # `bash` no llevan path, así que exigir uno concreto no se puede afirmar —
    # y `hook_ran` lo satisface cualquier lectura, que no es lo mismo.
    if exp.get("hook_refused_any"):
        vp = repo / ".ddw-eval-verdicts.jsonl"
        rows = ([json.loads(l) for l in vp.read_text().splitlines() if l.strip()]
                if vp.exists() else [])
        if not any(r.get("exit") not in (0, None) for r in rows):
            problems.append("no hook refused anything at all — a run where nothing was refused "
                            "is the 'the agent politely declines' false pass")

    if "hook_refused" in exp or "hook_ran" in exp:
        vp = repo / ".ddw-eval-verdicts.jsonl"
        if not vp.exists():
            problems.append("the verdict tap recorded nothing — no hook ran at all")
        else:
            rows = [json.loads(l) for l in vp.read_text().splitlines() if l.strip()]
            if exp.get("hook_ran") and not rows:
                problems.append("no hook verdict was recorded")
            for needle in exp.get("hook_refused", []):
                if not any(r["exit"] != 0 and (r.get("path") or "").endswith(needle)
                           for r in rows):
                    problems.append(f"no hook refused a write to {needle} "
                                    f"(verdicts seen: {[(r['hook'], r['exit']) for r in rows]})")

    if "journal_records" in exp:
        jp = repo / ".ddw-journal.jsonl"
        body = jp.read_text() if jp.exists() else ""
        for needle in exp["journal_records"]:
            if needle not in body:
                problems.append(f"the journal records no {needle!r}")

    # "either the file was refused, or the user chose FREE on the record" —
    # written as a disjunction because both are correct outcomes.
    for alt in exp.get("any_of", []):
        ok = False
        for branch in alt:
            v, _ = judge_repo_state({"expect": branch}, repo, transcript)
            if v == PASS:
                ok = True
                break
        if not ok:
            problems.append("none of the acceptable outcomes held: " + json.dumps(alt))

    if problems:
        return FAIL, "; ".join(problems)
    return PASS, "the repo ended where the rules say it must"


# --------------------------------------------------------------------------- #
# controls — the mutation that must make the scenario go red
# --------------------------------------------------------------------------- #

def apply_control(sc, ddw_root, repo, workdir, git_root=None):
    """El control, aplicado.

    `git_root` es de dónde se LEE la historia y `ddw_root` dónde se ESCRIBE: la
    copia de trabajo no lleva `.git`, así que `git show` corrido ahí falla, y
    con el fallo ahora contando como control roto, fallaban los seis. Antes no
    se notaba porque esta función no la llamaba nadie para este tipo.
    """
    ctl = sc.get("control")
    if not ctl:
        raise RuntimeError("scenario declares no control; it cannot be trusted")
    kind = ctl["type"]
    if kind == "restore_from_commit":
        # `path` o `paths`. Algunas regresiones no se pueden restaurar de a un
        # archivo: la puerta pintada del estado corrupto vive en
        # `validate-transition.py`, y esa versión tiene otra firma que el
        # `hook-gate.py` de HEAD — restaurando una sola, el control se pone rojo
        # por un TypeError y no por la regresión, o sea que no discrimina nada.
        # Un control que se pone rojo por la razón equivocada es tan inútil como
        # uno que no se pone rojo.
        paths = ctl.get("paths") or [ctl["path"]]
        for rel_path in paths:
            gr = git_root or ddw_root
            r = sh(["git", "show", f"{ctl['commit']}:{rel_path}"], cwd=gr)
            if r.returncode != 0:
                # El commit puede no ser alcanzable desde acá: vive en otra rama,
                # o el clon es shallow. Localmente el clon tiene todas las ramas
                # y anda; en un runner de CI se checkoutea la rama del PR y la
                # historia de la otra no viene — y desde que un control que no se
                # pudo aplicar FALLA en vez de contarse como rojo, eso ponía el
                # CI entero en rojo por una razón que no es la del escenario.
                # Un intento de traerlo por sha, que es lo que GitHub permite.
                base = ctl["commit"].rstrip("^~0123456789")
                sh(["git", "fetch", "--quiet", "--depth=2", "origin", base], cwd=gr)
                r = sh(["git", "show", f"{ctl['commit']}:{rel_path}"], cwd=gr)
            if r.returncode != 0:
                raise RuntimeError(
                    f"cannot read {rel_path} at {ctl['commit']} — el commit no es alcanzable "
                    "desde este checkout ni se pudo traer del remoto. Un control que no se "
                    "puede aplicar no prueba nada; considerá pasar este escenario a "
                    "`type: substitute`, que reinyecta el defecto sobre HEAD y no depende "
                    "de la historia.")
            # patch BOTH the source tree copy the scenario reads and the installed copy
            installed = (ctl.get("installed_paths", {}).get(rel_path)
                         or ctl.get("installed_path")
                         or rel_path)
            for dest in (ddw_root / rel_path, repo / installed):
                if dest.parent.exists():
                    dest.write_text(r.stdout, encoding="utf-8")
        return
    if kind == "substitute" and ctl.get("edits"):
        # Varios archivos, un solo control.
        #
        # DDW repite algunas reglas A PROPÓSITO: la del estado corrupto vive en
        # el mensaje del hook y dos veces en `ddw/orchestrator.md`, porque el
        # modelo tiene que encontrarla venga por donde venga. Reinyectar el
        # defecto en un archivo solo deja las otras copias en pie, y el control
        # sale rojo o verde según cuál de las tres leyó el modelo esa vez.
        # Medido: 1 de 3. Un control intermitente no prueba nada — es la misma
        # moneda al aire que este modo existe para no tirar.
        for spec in ctl["edits"]:
            for dest in (ddw_root / spec["path"],
                         repo / spec.get("installed_path", spec["path"])):
                if not dest.exists():
                    continue
                text = dest.read_text(encoding="utf-8")
                if spec["old"] not in text:
                    raise RuntimeError(f"the control's anchor is gone from {spec['path']}")
                dest.write_text(text.replace(spec["old"], spec.get("new", ""), 1),
                                encoding="utf-8")
        return

    if kind == "substitute":
        # Un reemplazo exacto sobre HEAD, no una restauración histórica.
        #
        # Restaurar el archivo de antes del fix es lo más fiel, y para algunas
        # regresiones es imposible: la versión vieja de `validate-transition.py`
        # no acepta el `--method` que `hook-gate.py` le pasa hoy, así que el
        # control se pone rojo con `unrecognized arguments` — un crash, no la
        # regresión. Es el idioma que ya usa `scripts/mutate.py`, y por la misma
        # razón: expresa el defecto sin arrastrar el resto del árbol al pasado.
        for dest in (ddw_root / ctl["path"], repo / ctl.get("installed_path", ctl["path"])):
            if not dest.exists():
                continue
            text = dest.read_text(encoding="utf-8")
            if ctl["old"] not in text:
                raise RuntimeError(f"the control's anchor is gone from {ctl['path']}")
            dest.write_text(text.replace(ctl["old"], ctl.get("new", ""), 1), encoding="utf-8")
        return

    if kind == "patch_installed":
        dest = repo / ctl["path"]
        dest.write_text(ctl["content"], encoding="utf-8")
        return
    raise RuntimeError(f"unknown control type {kind!r}")


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def run_one(sc, ddw_root, args, control: bool):
    # Un control que NO puede discriminar, dicho por el escenario y con su
    # razón escrita.
    #
    # Existe porque se midió: el control de `forged-state-stops-and-reports`
    # PASA con un modelo capaz, y no porque el escenario esté mal escrito —
    # porque sus tres ediciones son PROSA y el hook sigue rechazando la
    # escritura del estado igual. La regla está defendida dos veces a propósito,
    # así que el repo termina idéntico con la prosa rota, y el único modelo que
    # podría hacerlo terminar distinto es uno que se vaya a la shell.
    #
    # Las dos salidas fáciles eran malas: dejarlo rojo para siempre entrena a
    # ignorar el rojo, y borrar el control deja al escenario diciendo que mide
    # algo que no mide. Así que se dice, se cuenta APARTE, y una corrida donde
    # sólo hubo salteados no sale verde — la misma regla que la suite aplica a
    # sus propios skips, por la misma razón.
    if control:
        excuse = (sc.get("control") or {}).get("cannot_discriminate")
        if excuse:
            return Result(sc["id"], sc.get("kind", "?"), SKIP,
                          "control declared non-discriminating: " + " ".join(excuse.split())[:150])

    workdir = Path(tempfile.mkdtemp(prefix=f"ddweval-{sc['id']}-"))
    scratch_root = ddw_root
    try:
        if control and sc.get("control"):
            # Never mutate the user's checkout. Work on a copy of the tree.
            #
            # Para CUALQUIER control, no sólo `restore_from_commit`. Con la
            # condición atada a un tipo, el `substitute` que se agregó después
            # caía con `scratch_root` == el checkout del usuario y le reescribía
            # `validate-transition.py` — y quedaba así. Lo encontré porque el
            # árbol empezó a rechazar una escritura que debía permitir y creí
            # por veinte minutos que había encontrado un bug del producto.
            # La regla no era «este tipo copia», era «ningún control toca el
            # árbol de quien lo corre», y estaba escrita acá arriba.
            scratch_root = workdir / "src"
            sh(["git", "worktree", "list"], cwd=ddw_root)
            shutil.copytree(ddw_root, scratch_root,
                            ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
            sh(["git", "init", "-q"], cwd=scratch_root)

        # El adaptador instalado sigue al agente cuando el escenario no dice
        # otra cosa: correr `opencode` contra un repo cableado para claude
        # instala un enforcement que ese agente no invoca nunca, y el escenario
        # sale verde sin que nada lo haya juzgado.
        # El adaptador instalado tiene que ser el que el agente invoca. Correr
        # `opencode` contra un repo cableado para claude instala un enforcement
        # que ese agente no llama nunca: nada juzga, el modelo escribe lo que
        # quiere, y el escenario reporta el fallo del PRODUCTO. Medido — así
        # salió el primer intento, y el veredicto acusaba a DDW de algo que
        # nunca había sido instalado para el agente que corrió.
        ADAPTERS = ("claude", "codex", "copilot", "cursor", "gemini", "opencode")
        _agent_name = Path((sc["given"].get("agent") or args.agent).split()[0]).name
        _install = sc["given"].get("install")
        if _install and _agent_name in ADAPTERS and _install != _agent_name:
            if sc.get("kind") == "behavioral":
                return Result(sc["id"], sc["kind"], ERROR,
                              f"el escenario instala `{_install}` y el agente es `{_agent_name}`: "
                              "ese enforcement no lo invoca nadie, así que no hay nada que juzgar")
        elif not _install:
            _install = _agent_name if _agent_name in ADAPTERS else "claude"
        repo = make_repo(scratch_root, _install, workdir)
        write_state(repo, sc["given"].get("state"))
        seed_files(repo, sc["given"].get("files"),
                   commit=sc["given"].get("commit_files", True))

        if control:
            # UNA implementación. `apply_control` tenía soporte de `paths` y esta
            # rama lo resolvía inline con `ctl['path']`, así que la capacidad
            # existía en una función que nadie llamaba — y un escenario que
            # declarara `paths` moría con `KeyError`, salía ERROR, y en modo
            # control un ERROR contaba como «se puso rojo». Un control verde por
            # la razón equivocada, que es peor que uno rojo.
            try:
                apply_control(sc, scratch_root, repo, workdir, git_root=ddw_root)
            except Exception as exc:  # noqa: BLE001
                return Result(sc["id"], sc["kind"], ERROR, f"control unavailable: {exc}")

        kind = sc["kind"]
        if kind == "painted-door-sweep":
            # `scratch_root`, no `ddw_root`: es la copia donde el control aplica
            # la instrucción rota. Leyendo el árbol real, el control no vería
            # nada y el barrido pasaría el control sin poder ponerse rojo.
            v, d = run_painted_door_sweep(sc, scratch_root, repo)
        elif kind == "painted-door":
            v, d = run_painted_door(sc, scratch_root, repo)
        elif kind == "template-vs-gate":
            v, d = run_template_vs_gate(sc, scratch_root, repo)
        elif kind == "router-reachability":
            v, d = run_router_reachability(sc, scratch_root, repo)
        elif kind == "method-lint":
            v, d = run_method_lint(sc, scratch_root, repo, control=control)
        elif kind == "behavioral":
            # El agente y el modelo salen del escenario si los declara, y de la
            # línea de comandos si no. Sin esto el mismo escenario no se puede
            # correr contra dos adaptadores, que es la mitad del punto: DDW
            # shippea seis y la capa conductual probaba uno.
            _agent = (sc["given"].get("agent") or args.agent).split()
            _model = sc["given"].get("model") or args.model
            v, d = run_behavioral(sc, scratch_root, repo, _agent, _model)
        else:
            v, d = ERROR, f"unknown kind {kind!r}"
        return Result(sc["id"], kind, v, d)
    except Exception as exc:  # an unjudgeable scenario is red, never green
        return Result(sc["id"], sc.get("kind", "?"), ERROR, f"{type(exc).__name__}: {exc}")
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            print(f"    kept: {workdir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="the DDW checkout under test")
    ap.add_argument("--scenarios", default=str(Path(__file__).parent / "scenarios"))
    ap.add_argument("--only", default=None)
    ap.add_argument("--kinds", default=None, help="comma-separated; default all")
    ap.add_argument("--offline", action="store_true", help="only kinds that need no model")
    ap.add_argument("--control", action="store_true",
                    help="apply each scenario's control and require it to FAIL")
    ap.add_argument("--agent", default="claude")
    ap.add_argument("--model", default=None)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    ddw_root = Path(args.repo).resolve()
    if not (ddw_root / "install.sh").exists():
        print(f"FATAL: {ddw_root} is not a DDW checkout", file=sys.stderr)
        return 2

    files = sorted(Path(args.scenarios).glob("*.yaml"))
    discovered = len(files)
    if discovered == 0:
        print("FATAL: no scenarios found. A run that examined nothing is not a pass.",
              file=sys.stderr)
        return 2

    wanted = set(args.kinds.split(",")) if args.kinds else None
    if args.offline:
        wanted = OFFLINE_KINDS if wanted is None else (wanted & OFFLINE_KINDS)

    scenarios, skipped = [], 0
    for f in files:
        sc = yaml.safe_load(f.read_text())
        sc["_file"] = f.name
        if args.only and sc["id"] != args.only:
            skipped += 1
            continue
        if wanted is not None and sc["kind"] not in wanted:
            skipped += 1
            continue
        scenarios.append(sc)

    mode = "CONTROL (each scenario must go RED)" if args.control else "normal"
    print(f"\nDDW instruction evals — {mode}")
    print(f"discovered {discovered} scenario file(s), running {len(scenarios)}, "
          f"filtered out {skipped}\n")

    results = []
    for sc in scenarios:
        r = run_one(sc, ddw_root, args, control=args.control)
        if args.control:
            # In control mode the expectation inverts: not-green is the healthy
            # answer. ERROR counts — "the skill no longer carries a canonical
            # document, so nothing can be judged" IS the pre-fix state for the
            # template family, and a run that cannot judge is red either way.
            #
            # But NOT when the harness is what failed. `control unavailable:
            # KeyError` is the control never having been applied, and reading
            # that as "went red as it must" makes the whole mode report success
            # for its own breakage — measured: a scenario declaring `paths`,
            # which the driver did not support, passed its control while the
            # regression was never put back. The control is the one instrument
            # here whose entire job is to distrust a green.
            # Un ERROR con FORMA DE EXCEPCIÓN es el arnés roto, no la
            # regresión. `KeyError: 'when'` contó como «se puso rojo como debe»
            # en una corrida donde el escenario ni siquiera se había podido
            # armar — medido, y es el mismo defecto que la línea de abajo cierra
            # para «control unavailable». Se generaliza: si lo que se rompió es
            # el instrumento, el control no probó nada.
            #
            # `control off-target` es el tercer caso y llegó con `method-lint`:
            # el control se aplicó, el instrumento se puso rojo, y lo hizo por
            # una afirmación que este escenario no rompió. Eso no prueba que
            # sepa cazar la suya — es el mismo defecto que el control que
            # fallaba con un `TypeError`, con mejor disfraz.
            #
            # Y el cuarto: «the agent did not complete a turn». Medido en la
            # nube — un control se contó como rojo porque el CLI salió 1 sin
            # llegar a contestar, o sea que la regresión nunca se puso delante
            # de nadie. No empieza con `…Error`, así que la regla de arriba no
            # lo veía: un turno que no corrió no prueba nada, y en modo control
            # eso REGALA el control, que es el instrumento cuyo trabajo entero
            # es desconfiar de un verde.
            _harness = re.match(r"^(\w*Error|\w*Exception|TimeoutExpired)\b", r.detail or "")
            _no_turn = (r.detail or "").startswith((
                "the agent did not complete a turn",
                "the agent produced no JSON events",
                "the agent returned output this runner cannot parse",
                "the agent reported an error"))
            if r.verdict == SKIP:
                pass                        # dicho, con su razón, y contado aparte
            elif r.verdict == ERROR and (_harness or _no_turn or r.detail.startswith(
                    ("control unavailable", "control off-target"))):
                r = Result(r.sid, r.kind, FAIL,
                           "the control proved nothing — the harness is what broke: " + r.detail)
            elif r.verdict in (FAIL, ERROR):
                r = Result(r.sid, r.kind, PASS, "control went red as it must — " + r.detail[:80])
            elif r.verdict == PASS:
                r = Result(r.sid, r.kind, FAIL,
                           "CONTROL PASSED: this scenario cannot detect its own regression")
        results.append(r)
        print(r.line())

    p = sum(1 for r in results if r.verdict == PASS)
    f_ = sum(1 for r in results if r.verdict == FAIL)
    e = sum(1 for r in results if r.verdict == ERROR)
    s = sum(1 for r in results if r.verdict == SKIP)
    print(f"\n  {p} passed, {f_} failed, {e} could not be judged, {s} skipped with a "
          f"written reason (of {len(scenarios)} run / {discovered} on disk)")

    if len(results) != len(scenarios):
        print("  FATAL: fewer results than scenarios — the runner lost one.")
        return 2
    if e or f_:
        return 1
    if not results:
        print("  FATAL: nothing ran.")
        return 2
    if s and s == len(results):
        # Un skip se cuenta aparte y no suma a un verde: si TODO lo que había
        # para medir se salteó, la corrida no midió nada, y decir «green» ahí es
        # la misma mentira que un `bad` que no puede fallar.
        print("  FATAL: every scenario was skipped — a run that measured nothing is not a pass.")
        return 2
    print("  green\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
