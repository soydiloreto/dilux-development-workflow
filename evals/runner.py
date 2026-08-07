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

PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"

# Kinds that never call a model. These are the ones CI runs on every push.
OFFLINE_KINDS = {"painted-door", "painted-door-sweep", "router-reachability",
                 "template-vs-gate"}


# --------------------------------------------------------------------------- #
# result plumbing
# --------------------------------------------------------------------------- #

class Result:
    def __init__(self, sid, kind, verdict, detail):
        self.sid, self.kind, self.verdict, self.detail = sid, kind, verdict, detail

    def line(self):
        colour = {PASS: "\033[32m", FAIL: "\033[31m", ERROR: "\033[33m"}[self.verdict]
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


def install_verdict_tap(repo: Path):
    hooks = repo / ".claude" / "hooks"
    if not hooks.is_dir():
        raise RuntimeError("no adapter hooks to tap; the install did not wire this tool")
    tapped = 0
    for name in ("enforce.sh", "validate-state-transition.sh", "validate-state-postwrite.sh"):
        src = hooks / name
        if not src.exists():
            continue
        real = hooks / (name[:-3] + ".real.sh")
        src.rename(real)
        body = TAP.replace("__REAL__", real.name).replace("__NAME__", name)
        # the payload has to reach the recorder as well as the real hook
        body = body.replace('printf \'%s\' "$PAYLOAD" | bash',
                            'export DDW_EVAL_PAYLOAD="$PAYLOAD"; printf \'%s\' "$PAYLOAD" | bash')
        src.write_text(body)
        src.chmod(0o755)
        tapped += 1
    if tapped == 0:
        raise RuntimeError("verdict tap installed nothing — refusing to judge blind")
    return tapped


def write_state(repo: Path, state: dict | None):
    if state is None:
        return
    (repo / ".ddw-state.json").write_text(json.dumps(state, indent=2))


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
    trig = sc["when"].get("triggered_by")
    if trig:
        code, reason = hook_verdict(repo, trig["event"])
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
        cmd = list(agent_cmd) + ["--permission-mode", "bypassPermissions",
                                 "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        if session:
            cmd += ["--resume", session]
        cmd += ["-p", turn]
        r = sh(cmd, cwd=repo, timeout=sc["when"].get("timeout", 300))
        if r.returncode != 0:
            return ERROR, f"the agent did not complete a turn (exit {r.returncode}): {r.stderr[-200:]}"
        try:
            payload = json.loads(r.stdout)
        except json.JSONDecodeError:
            return ERROR, "the agent returned output this runner cannot parse"
        if payload.get("is_error"):
            return ERROR, f"the agent reported an error: {str(payload.get('result'))[:150]}"
        session = payload.get("session_id") or session
        transcript.append(payload)

    (repo.parent / "transcript.json").write_text(json.dumps(transcript, indent=2))
    return judge_repo_state(sc, repo, transcript)


def judge_repo_state(sc, repo, transcript):
    """Every assertion here is about the repo or the hooks. Never about prose."""
    exp = sc["expect"]
    problems = []

    for rel in exp.get("files_absent", []):
        if (repo / rel).exists():
            problems.append(f"{rel} exists and must not")
    for rel in exp.get("files_present", []):
        if not (repo / rel).exists():
            problems.append(f"{rel} is missing")

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

def apply_control(sc, ddw_root, repo, workdir):
    ctl = sc.get("control")
    if not ctl:
        raise RuntimeError("scenario declares no control; it cannot be trusted")
    kind = ctl["type"]
    if kind == "restore_from_commit":
        r = sh(["git", "show", f"{ctl['commit']}:{ctl['path']}"], cwd=ddw_root)
        if r.returncode != 0:
            raise RuntimeError(f"cannot read {ctl['path']} at {ctl['commit']}")
        # patch BOTH the source tree copy the scenario reads and the installed copy
        for dest in (ddw_root / ctl["path"], repo / ctl.get("installed_path", ctl["path"])):
            if dest.parent.exists():
                dest.write_text(r.stdout, encoding="utf-8")
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
    workdir = Path(tempfile.mkdtemp(prefix=f"ddweval-{sc['id']}-"))
    scratch_root = ddw_root
    try:
        if control and sc.get("control", {}).get("type") == "restore_from_commit":
            # Never mutate the user's checkout. Work on a copy of the tree.
            scratch_root = workdir / "src"
            sh(["git", "worktree", "list"], cwd=ddw_root)
            shutil.copytree(ddw_root, scratch_root,
                            ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
            sh(["git", "init", "-q"], cwd=scratch_root)

        repo = make_repo(scratch_root, sc["given"].get("install", "claude"), workdir)
        write_state(repo, sc["given"].get("state"))

        if control:
            ctl = sc["control"]
            if ctl["type"] == "restore_from_commit":
                blob = sh(["git", "show", f"{ctl['commit']}:{ctl['path']}"], cwd=ddw_root)
                if blob.returncode != 0:
                    return Result(sc["id"], sc["kind"], ERROR,
                                  f"control unavailable: {ctl['path']}@{ctl['commit']}")
                (scratch_root / ctl["path"]).write_text(blob.stdout, encoding="utf-8")
                ip = repo / ctl.get("installed_path", "")
                if ctl.get("installed_path") and ip.parent.exists():
                    ip.write_text(blob.stdout, encoding="utf-8")
            else:
                apply_control(sc, scratch_root, repo, workdir)

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
        elif kind == "behavioral":
            v, d = run_behavioral(sc, scratch_root, repo, args.agent.split(), args.model)
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
            if r.verdict in (FAIL, ERROR):
                r = Result(r.sid, r.kind, PASS, "control went red as it must — " + r.detail[:80])
            elif r.verdict == PASS:
                r = Result(r.sid, r.kind, FAIL,
                           "CONTROL PASSED: this scenario cannot detect its own regression")
        results.append(r)
        print(r.line())

    p = sum(1 for r in results if r.verdict == PASS)
    f_ = sum(1 for r in results if r.verdict == FAIL)
    e = sum(1 for r in results if r.verdict == ERROR)
    print(f"\n  {p} passed, {f_} failed, {e} could not be judged "
          f"(of {len(scenarios)} run / {discovered} on disk)")

    if len(results) != len(scenarios):
        print("  FATAL: fewer results than scenarios — the runner lost one.")
        return 2
    if e or f_:
        return 1
    if not results:
        print("  FATAL: nothing ran.")
        return 2
    print("  green\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
