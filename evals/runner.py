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

def copilot_home(workdir: Path, repo: Path) -> Path:
    """A HOME of this run's own, still logged in.

    `~/.copilot/config.json` is where Copilot keeps `copilotTokens` and
    `loggedInUsers`, so it is the one file that has to come across; everything
    else — settings, hooks, the session store — starts empty, which is the
    point. `trustedFolders` gets the fixture appended so the run is never asked
    a question it has no terminal to answer.
    """
    home = workdir / "home"
    (home / ".copilot").mkdir(parents=True, exist_ok=True)
    src = Path(os.path.expanduser("~/.copilot/config.json"))
    cfg = {}
    if src.exists():
        # JSONC: the file opens with two `//` lines. Strict JSON raises on them,
        # and the credentials would be silently dropped — a run that then fails
        # on authentication and reports it as the product's behaviour.
        try:
            cfg = json.loads(re.sub(r"^\s*//.*$", "", src.read_text(encoding="utf-8"), flags=re.M))
        except ValueError:
            cfg = {}
    if not cfg.get("copilotTokens") and not cfg.get("loggedInUsers"):
        raise RuntimeError("no Copilot credentials in ~/.copilot/config.json — a run from here "
                           "would fail on authentication and read as a product verdict")
    trusted = cfg.get("trustedFolders")
    cfg["trustedFolders"] = (trusted if isinstance(trusted, list) else []) + [str(repo)]
    (home / ".copilot" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return home


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

    env = None
    if target == "copilot":
        # Copilot's gates are wired at USER level — the only level `copilot -p`
        # reads — so installing for Copilot writes outside the fixture, into
        # `$HOME`. Two things follow, and both are the harness's problem:
        #
        #   the run must not touch the operator's own ~/.copilot — one eval
        #   would rewire every Copilot session on the machine, and two evals in
        #   parallel would rewire each other;
        #   and it must not simply be blanked either, because a HOME with no
        #   `.copilot/config.json` has no credentials, and an unauthenticated
        #   Copilot fails in a way that reads as a product verdict.
        #
        # So: a HOME per run, carrying the credentials forward and nothing else.
        env = dict(os.environ, HOME=str(copilot_home(workdir, repo)))
    r = sh(["bash", str(ddw_root / "install.sh"), str(repo), "--target", target],
           cwd=repo, env=env, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"install.sh failed ({r.returncode}): {r.stderr[-600:]}")
    if target == "copilot" and not (workdir / "home" / ".copilot" / "hooks" / "ddw.json").exists():
        raise RuntimeError("install.sh exited 0 and wired no user-level Copilot hooks — "
                           "nothing would gate this run, and it would report as a clean pass")
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


# --------------------------------------------------------------------------- #
# the tap — Copilot CLI
#
# Same shell tap as Claude's, on the scripts the repo carries in
# `.github/hooks/ddw/`. What differs is who calls them: Copilot's wiring lives
# at USER level, and runs the repo's script by relative path. So wrapping the
# repo's copy is enough — and it is also the only thing that works, because
# there is no repo-level manifest to rewrite.
#
# `pre-compact.sh` is left alone: it is not a verdict, it is a nudge, and a tap
# that recorded it as exit 0 would put an "allowed" in the log for a write that
# never happened.
# --------------------------------------------------------------------------- #


def _tap_copilot(repo: Path) -> int:
    hooks = repo / ".github" / "hooks" / "ddw"
    if not hooks.is_dir():
        return 0
    tapped = 0
    for name in ("pre-tool-use.sh", "post-write.sh"):
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
        reseal_manifest(repo, {f".github/hooks/ddw/{name}"})
        tapped += 1
    return tapped


def install_verdict_tap(repo: Path) -> int:
    """Wrap whichever adapter this repo was installed with. Never judges."""
    tapped = _tap_claude(repo) + _tap_opencode(repo) + _tap_copilot(repo)
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
    "copilot": {
        # `-p` is the headless entry point; `--allow-all` is required for it
        # (GitHub's own words) and is Copilot's spelling of bypassPermissions.
        # `--stream off` and `--no-color` are here so the footer this runner
        # reads the session id out of arrives as plain text.
        "argv": ["copilot"],
        "flags": ["--allow-all", "--no-color", "--stream", "off"],
        "model": ["--model", "{model}"],
        "resume": ["--resume={session}"],
        # `-C` is Copilot's change-directory flag. Named for the same reason
        # OpenCode's `--dir` is: a run pointed at the wrong repo measures
        # nothing and writes into the tree it was pointed at.
        "dir": ["-C", "{repo}"],
        # The HOME made by `copilot_home` — where this run's credentials and,
        # crucially, its user-level hooks are. Without it the agent reads the
        # operator's own wiring and the fixture is gated by whatever that says.
        "env": {"HOME": "{home}"},
        "prompt": ["-p", "{turn}"],
    },
}


def agent_profile(agent_cmd) -> tuple[str, dict]:
    name = Path(agent_cmd[0]).name
    if name not in AGENT_CLIS:
        raise RuntimeError(f"no headless profile for agent {name!r}; add one to AGENT_CLIS")
    return name, AGENT_CLIS[name]


def agent_turn_cmd(agent_cmd, model, session, turn, repo=None, home=None):
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
    if prof.get("env"):
        fields = {"repo": str(repo or ""), "home": str(home or "")}
        # A profile that asks for a value the caller did not supply is a run
        # measuring something other than what it says. Copilot's HOME is where
        # its gates live: pointed at the operator's own, the fixture is judged
        # by whatever that machine happens to be wired for, and the scenario
        # reports it as the product.
        missing = [k for k, v in prof["env"].items()
                   if any(f"{{{f}}}" in v and not fields[f] for f in fields)]
        if missing:
            raise RuntimeError(f"{name}: {', '.join(missing)} cannot be set — this run would "
                               "read wiring that is not the fixture's")
        env = dict(os.environ)
        env.update({k: v.format(**fields) for k, v in prof["env"].items()})
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

    if name == "copilot":
        # Copilot has no JSON output mode. What it does print, at the end of a
        # `-p` run, is the line that resumes the session:
        #
        #     Resume     copilot --resume=48ac578f-15de-4b10-b255-c2d4518af86c
        #
        # That id is REQUIRED, not best-effort. Without it every turn of a
        # multi-turn scenario opens a fresh session, the model never sees what
        # it just did, and the scenario measures a sequence of first turns while
        # reporting a conversation.
        m = re.search(r"--resume=([0-9a-fA-F-]{8,})", stdout)
        if not m:
            return None, None, ("the run printed no resume id, so a second turn would start a "
                                "new session and the scenario would measure first turns only")
        return stdout, m.group(1), None

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
    """The scenario's state. `null` keeps the one the installation left.

    A string is written AS IS, without going through JSON: there is an entire
    family of regressions that only exists with the state CORRUPT — the
    recovery message is what gets read once everything has already gone wrong —
    and there was no way to express it. A scenario that wanted corrupt state
    ended up with healthy state, passed in both directions, and its control
    said it could not detect its own regression. That it said so is the only
    reason this was found.
    """
    if state is None:
        return
    if isinstance(state, str):
        (repo / ".ddw-state.json").write_text(state, encoding="utf-8")
        return
    (repo / ".ddw-state.json").write_text(json.dumps(state, indent=2))


def seed_files(repo: Path, files, commit=True) -> int:
    """The files the scenario needs to ALREADY exist.

    `given.state` knows how to write exactly one, `.ddw-state.json`, and there
    is an entire family of scenarios that cannot be expressed with only that: a
    product source a phase must not touch, a half-written artifact its gate has
    to refuse, a PRD already in place when the phase goes to write it. All of
    them started from the fixture's empty repo — that is, measuring something
    other than what they say they measure.

    They are written THROUGH THE FILESYSTEM, not through the tools: they are
    the `given`, not something the model does, and sending them through the
    gate would make it impossible to seed exactly what the gate refuses.

    They are COMMITTED unless the scenario says otherwise. A seeded, uncommitted
    source leaves the tree dirty before the first turn, and what the scenario
    measures after that is a rule about uncommitted work nobody asked for.
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
            # Without this, a `../..` in a scenario writes into the checkout of
            # whoever runs it. It already happened once by another route — a
            # control that rewrote the user's tree — and cost twenty minutes of
            # believing the product had a bug.
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
        # Only what was seeded. A `git add -A` here drags in the installed
        # method and the scenario's state, which the fixture keeps out of the
        # index on purpose.
        #
        # `-f` because the installation leaves a block in `.gitignore`, and
        # what it ignores — `.ddw-paused/`, `.ddw-sessions/`, the journal — is
        # exactly part of what a scenario needs to seed. Without `-f`,
        # `git add` refuses those paths, the commit finds nothing to commit,
        # and the fixture ends up different from what the scenario says it is
        # without anyone noticing.
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
# The real destinations come templated — `docs/ddw/prd/prd-{ticket}.md` is the
# form the method writes them in. Rejecting them for carrying braces left the
# sweep at ONE order across thirty-two files, which is not sweeping. They get
# substituted; what still carries brackets after substitution IS an example.
TEMPLATED = re.compile(r"[<{\[](ticket|TICKET|id|ID|slug|name)[>}\]]")
PLACEHOLDER = re.compile(r"[<{\[]|path/to|your-|example|FIXME|TODO|\.\.\.")


# Between the verb and the path: if one of these appears, the path is a
# REFERENCE, not the object of the write. "Write the summary following
# `ddw/rules/x.md`" does not order writing that rule. Without this, the sweep
# accused every file a skill cites of being a painted door — six of six
# offenders were citations.
REFERENCE = re.compile(
    r"(?i)\b(in|per|from|see|read|following|according to|documented in|described in|"
    r"defined in|listed in|under|against|as in|like|of|by|via|using|with)\s*$")


def _ordered_writes(text):
    """(line, path) for every write the document ORDERS to be done.

    Conservative on purpose: over a corpus of twenty instruction files, a
    generous heuristic produces noise faster than it produces findings, and a
    sweep that cries wolf is a sweep that gets turned off.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not re.match(r"^(?:[-*+]|\d+\.)\s", line):
            continue                       # prose: not a step
        verb = re.search(r"(?i)\b%s\b" % WRITE_VERB, line)
        if not verb:
            continue
        if NOT_AN_ORDER.search(line):
            continue                       # talks about a write, does not order it
        rest = line[verb.end():]
        for m in re.finditer(r"`([^`\s]+)`", rest):
            path = m.group(1)
            # A slash-command (`/ddw-create-prd`) is not a path, and the verb
            # that let it in was the "create" of its own name. And a path with
            # no extension and no inner slash does not name a file.
            path = TEMPLATED.sub("T-1", path)
            if PLACEHOLDER.search(path):
                continue
            if path.startswith("/") and "/" not in path[1:]:
                continue
            if path.endswith("/"):
                # A DIRECTORY is a legitimate destination, and it was the one
                # of the painted door that started all this: "**Copy** the
                # method to `.ddw/`". Requiring an inner slash rejected it, so
                # the sweep did not find the one regression it did know how to
                # reproduce — and the control said so. The gate is asked about
                # a file inside, which is what a copy writes.
                path = path + "probe.txt"
            elif not (re.search(r"[^/]/[^/]", path) and re.search(r"\.\w{1,6}$", path)):
                continue
            if path.startswith(("http", "-", "python3", "bash", "git")):
                continue
            if ":" in path:
                continue                   # `src/x.ts:58` is a citation, not a destination
            if REFERENCE.search(rest[:m.start()]):
                continue                   # the path is where to LOOK, not where to write
            # `lstrip("./")` eats the leading dot and turns `.ddw-paused/x`
            # into `ddw-paused/x`, which is ANOTHER path: the first is written
            # by the pause in any phase, the second is product source. The
            # sweep accused the orchestrator of a painted door that does not exist.
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
    # Who says the refusal: the HOOK, with a tool event, or the HELPER, with an
    # invocation that exits non-zero. The two most expensive hints this repo
    # fixed — "run `--claim commit --claim pr` first" and "the only transition
    # from IDLE is `--to CLASSIFY`" — live only in `transition.py`'s `main()`,
    # and without being able to assert against its stderr there was no way to
    # write those scenarios: the control came out green because the only thing
    # that changed was the hint's text.
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
               # `transition.py` does not accept `--repo`: it resolves the repo
               # via `CLAUDE_PROJECT_DIR` and then the cwd. Passing it, argparse
               # exits 2 and the scenario reports "the prescribed step is itself
               # refused" — that is, no `router-reachability` scenario could
               # ever come out green. Since there is none in the tree yet, the
               # bug was invisible: a kind dead at birth.
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
# `scripts/lint_method.py` compares what the prose CLAIMS against the graph,
# the rule catalog and the tree. It runs in the suite, but there the only
# question asked is whether it is green TODAY — nobody measures whether it
# still knows how to go red. Each of its twenty-odd checks is a regression that
# already happened, and a prose linter breaks silently: you rename a section,
# the check stops finding what it looked at, and it keeps reporting green for
# having nothing else to say. It is exactly the [[CHECKS-THAT-CANNOT-FAIL]]
# family.
#
# Here the linter is the VERDICT: in normal mode it has to come out clean, and
# with the control applied — a prose claim broken on purpose — it has to name
# it. Hence `control.finding_matches`: a linter that goes red over something
# else has not proven it can hunt this one, and that is the same mistake this
# repository already made with the controls that failed on a TypeError.
# --------------------------------------------------------------------------- #

def run_method_lint(sc, ddw_root, repo, control=False):
    r = sh([sys.executable, str(ddw_root / "scripts" / "lint_method.py"),
            "--repo", str(ddw_root)], cwd=ddw_root, timeout=300)
    out = (r.stdout + r.stderr).strip()
    if not re.search(r"^lint_method: ", out, re.M):
        # Neither the green nor the red: it crashed before judging. A stack is
        # not a verdict, and counting it as red in control mode gives the
        # control away.
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
        # `make_repo` puts the run's HOME beside the fixture. Derived rather
        # than threaded through every signature: the two are made together and
        # a Copilot run without it is refused above, not silently mismeasured.
        name, cmd, env = agent_turn_cmd(agent_cmd, model, session, turn, repo,
                                        home=(repo.parent / "home"))
        # The per-turn ceiling. 300s was enough for Opus; a free model went
        # past 420 in a single turn, and a timeout is ERROR — meaning the
        # scenario cannot be judged and the run stays red, which is correct
        # but says nothing about the product. The scenario can raise it, and
        # the stability measurement is what decides whether a model gets in.
        r = sh(cmd, cwd=repo, env=env, timeout=sc["when"].get("timeout", 900))
        if r.returncode != 0:
            # BOTH outputs, and the last line with text.
            #
            # Measured: ten cloud runs died at eight seconds with this message
            # and an empty `stderr` — meaning the harness knew the agent had
            # failed and could not say why, which is the half that matters. A
            # CLI that reports over stdout leaves the diagnosis out if only
            # stderr is read, and without a diagnosis the explanation is
            # supplied by whoever is looking: "must be rate limit", and that
            # cannot be called a measurement.
            said = [l.strip() for l in ((r.stderr or "") + "\n" + (r.stdout or "")).splitlines()
                    if l.strip()]
            # And the line that TALKS about the error first. With the plain
            # last three, the boot notice DDW injects into every turn ate the
            # character budget and the event that says what happened came out
            # truncated — no diagnosis again, this time because of the trim.
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

    # The phase the state ended up in. It is what distinguishes "the model ate
    # the refusal and used the shell" — decision 12, documented — from "the
    # model fabricated itself a pipeline in order to write", which is what this
    # scenario exists to catch.
    if "state_phase" in exp:
        sp = repo / ".ddw-state.json"
        try:
            got = json.loads(sp.read_text()).get("phase")
        except Exception:  # noqa: BLE001 — an unreadable state is NOT a pass
            got = "<unreadable>"
        if got != exp["state_phase"]:
            problems.append(f"the state ended in {got!r}, not {exp['state_phase']!r}")

    for rel in exp.get("files_absent", []):
        if (repo / rel).exists():
            problems.append(f"{rel} exists and must not")
    for rel in exp.get("files_present", []):
        if not (repo / rel).exists():
            problems.append(f"{rel} is missing")

    # The CONTENT of an artifact, not its existence.
    #
    # `files_present` does not distinguish the document that answers the
    # question from the one that makes it up: both exist, and `state_phase`
    # only separates them if the model also crossed the arrow. The defect
    # `acceptance.md` names — "inventing a requirement, a criterion or a
    # threshold so a check passes" — is seen inside the file or not at all.
    #
    # A `matches` that does not compile, or a clause that asserts nothing,
    # RAISES: an assertion that cannot judge is the same as not writing it,
    # and here that reads as green.
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
                    # No `re.I`: a case-insensitive `matches` is a looser
                    # `matches`, and what is asserted here is the only thing
                    # separating the document that answered from the one that
                    # invented the answer. A scenario that needs it writes
                    # `(?i)`, and that shows.
                    hit = re.search(pat, body, re.S | re.M) is not None
                except re.error as exc:
                    raise RuntimeError(
                        f"file_matches on {rel!r} carries a regex that does not compile "
                        f"({pat!r}): {exc}") from None
                if key == "matches" and not hit:
                    problems.append(f"{rel} does not contain anything matching {pat!r}")
                elif key == "absent" and hit:
                    problems.append(f"{rel} contains {pat!r} and must not")

    # What the model SAID, not what it left in the repo. The status line and
    # the 🙋 banner are the method's two most frequent format demands — one per
    # response — and until here nothing measured them: verify_install greps
    # that the text exists in the METHOD, not that the agent emits it, and a
    # live run omitted them entirely with one model and honored them always
    # with another. The serialized transcript is the only surface where that
    # shows.
    for spec in exp.get("transcript_matches", []):
        clauses = [(k, spec[k]) for k in ("matches", "absent") if k in spec]
        if not clauses:
            raise RuntimeError(
                "transcript_matches declares neither `matches` nor `absent` — "
                "a clause that asserts nothing passes for the wrong reason")
        body = json.dumps(transcript, ensure_ascii=False)
        for key, pats in clauses:
            for pat in (pats if isinstance(pats, list) else [pats]):
                try:
                    hit = re.search(pat, body, re.S) is not None
                except re.error as exc:
                    raise RuntimeError(
                        f"transcript_matches carries a regex that does not compile "
                        f"({pat!r}): {exc}") from None
                if key == "matches" and not hit:
                    problems.append(f"the transcript never says anything matching {pat!r}")
                elif key == "absent" and hit:
                    problems.append(f"the transcript says {pat!r} and must not")

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
    # "some hook refused something", with no path. OpenCode's post verdicts on
    # `bash` carry no path, so requiring a concrete one cannot be asserted —
    # and `hook_ran` is satisfied by any read, which is not the same thing.
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
    """The control, applied.

    `git_root` is where history is READ from and `ddw_root` where it is
    WRITTEN: the working copy carries no `.git`, so `git show` run there fails,
    and with the failure now counting as a broken control, all six failed.
    It went unnoticed before because nobody called this function for this type.
    """
    ctl = sc.get("control")
    if not ctl:
        raise RuntimeError("scenario declares no control; it cannot be trusted")
    kind = ctl["type"]
    if kind == "restore_from_commit":
        # `path` or `paths`. Some regressions cannot be restored one file at a
        # time: the corrupt-state painted door lives in
        # `validate-transition.py`, and that version has a different signature
        # than HEAD's `hook-gate.py` — restoring only one, the control goes red
        # on a TypeError and not on the regression, meaning it discriminates
        # nothing. A control that goes red for the wrong reason is as useless
        # as one that does not go red.
        paths = ctl.get("paths") or [ctl["path"]]
        for rel_path in paths:
            gr = git_root or ddw_root
            r = sh(["git", "show", f"{ctl['commit']}:{rel_path}"], cwd=gr)
            if r.returncode != 0:
                # The commit may not be reachable from here: it lives on
                # another branch, or the clone is shallow. Locally the clone
                # has every branch and it works; on a CI runner the PR's branch
                # is checked out and the other one's history does not come —
                # and ever since a control that could not be applied FAILS
                # instead of counting as red, that put the whole CI in red for
                # a reason that is not the scenario's. An attempt to fetch it
                # by sha, which is what GitHub allows.
                base = ctl["commit"].rstrip("^~0123456789")
                sh(["git", "fetch", "--quiet", "--depth=2", "origin", base], cwd=gr)
                r = sh(["git", "show", f"{ctl['commit']}:{rel_path}"], cwd=gr)
            if r.returncode != 0:
                raise RuntimeError(
                    f"cannot read {rel_path} at {ctl['commit']} — the commit is not reachable "
                    "from this checkout and could not be fetched from the remote. A control "
                    "that cannot be applied proves nothing; consider moving this scenario to "
                    "`type: substitute`, which reinjects the defect over HEAD and does not "
                    "depend on the history.")
            # patch BOTH the source tree copy the scenario reads and the installed copy
            installed = (ctl.get("installed_paths", {}).get(rel_path)
                         or ctl.get("installed_path")
                         or rel_path)
            for dest in (ddw_root / rel_path, repo / installed):
                if dest.parent.exists():
                    dest.write_text(r.stdout, encoding="utf-8")
        return
    if kind == "substitute" and ctl.get("edits"):
        # Several files, one single control.
        #
        # DDW repeats some rules ON PURPOSE: the corrupt-state one lives in the
        # hook's message and twice in `ddw/orchestrator.md`, because the model
        # has to find it whichever way it comes in. Reinjecting the defect into
        # a single file leaves the other copies standing, and the control comes
        # out red or green depending on which of the three the model read that
        # time. Measured: 1 of 3. An intermittent control proves nothing — it
        # is the same coin toss this mode exists to not throw.
        for spec in ctl["edits"]:
            # The copy the MODEL reads has to actually exist.
            #
            # This branch silently skips the destination that is not there, and
            # for a behavioral scenario that is the entire control turned into
            # nothing: the model reads `.ddw/…` and `.claude/skills/…` from the
            # installed repo, not the source tree. With a misspelled
            # `installed_path` the control applied "fine", the scenario passed,
            # and the verdict accused the scenario of being unable to detect
            # its regression. A typo shaped like a finding.
            if sc.get("kind") == "behavioral":
                installed = repo / spec.get("installed_path", spec["path"])
                if not installed.exists():
                    raise RuntimeError(
                        f"the control patches {spec['path']} but its installed copy "
                        f"({spec.get('installed_path', spec['path'])}) is not in the fixture — "
                        "the model reads the installed tree, so this edit would change nothing")
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
        # An exact replacement over HEAD, not a historical restoration.
        #
        # Restoring the file from before the fix is the most faithful, and for
        # some regressions it is impossible: the old version of
        # `validate-transition.py` does not accept the `--method` that
        # `hook-gate.py` passes it today, so the control goes red with
        # `unrecognized arguments` — a crash, not the regression. It is the
        # idiom `scripts/mutate.py` already uses, and for the same reason: it
        # expresses the defect without dragging the rest of the tree into the past.
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
    # A control that CANNOT discriminate, said by the scenario and with its
    # reason written down.
    #
    # It exists because it was measured: the control of
    # `forged-state-stops-and-reports` PASSES with a capable model, and not
    # because the scenario is badly written — because its three edits are PROSE
    # and the hook keeps refusing the state write regardless. The rule is
    # defended twice on purpose, so the repo ends up identical with the prose
    # broken, and the only model that could make it end up different is one
    # that goes to the shell.
    #
    # The two easy ways out were bad: leaving it red forever trains people to
    # ignore red, and deleting the control leaves the scenario claiming to
    # measure something it does not. So it is said, counted APART, and a run
    # with nothing but skips does not come out green — the same rule the suite
    # applies to its own skips, for the same reason.
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
            # For ANY control, not just `restore_from_commit`. With the
            # condition tied to a type, the `substitute` added later landed
            # with `scratch_root` == the user's checkout and rewrote their
            # `validate-transition.py` — and it stayed that way. I found it
            # because the tree started refusing a write it should allow and
            # believed for twenty minutes that I had found a product bug.
            # The rule was not "this type copies", it was "no control touches
            # the tree of whoever runs it", and it was written right above.
            scratch_root = workdir / "src"
            sh(["git", "worktree", "list"], cwd=ddw_root)
            shutil.copytree(ddw_root, scratch_root,
                            ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
            sh(["git", "init", "-q"], cwd=scratch_root)

        # The installed adapter follows the agent when the scenario says
        # nothing else: running `opencode` against a repo wired for claude
        # installs an enforcement that agent never invokes, and the scenario
        # comes out green without anything having judged it.
        # The installed adapter has to be the one the agent invokes. Running
        # `opencode` against a repo wired for claude installs an enforcement
        # that agent never calls: nothing judges, the model writes whatever it
        # wants, and the scenario reports it as the PRODUCT's failure.
        # Measured — that is how the first attempt came out, and the verdict
        # accused DDW of something that had never been installed for the agent
        # that ran.
        ADAPTERS = ("claude", "codex", "copilot", "cursor", "gemini", "opencode")
        _agent_name = Path((sc["given"].get("agent") or args.agent).split()[0]).name
        _install = sc["given"].get("install")
        if _install and _agent_name in ADAPTERS and _install != _agent_name:
            if sc.get("kind") == "behavioral":
                return Result(sc["id"], sc["kind"], ERROR,
                              f"the scenario installs `{_install}` and the agent is `{_agent_name}`: "
                              "nobody invokes that enforcement, so there is nothing to judge")
        elif not _install:
            _install = _agent_name if _agent_name in ADAPTERS else "claude"
        repo = make_repo(scratch_root, _install, workdir)
        # The ticket's branch, when the scenario says work is in progress.
        #
        # The fixture was born on `master` with a state that says DEFINE, and
        # that is NOT a possible world: the boot orders checking the branch
        # before resuming — `ddw/orchestrator.md`, "if we are on a generic
        # branch … the state says work is in progress, but we are on [branch]" —
        # so an obedient agent stops to ask about that inconsistency. Measured
        # with Claude Code: the ENTIRE first turn went into that question, and
        # the scenario measured what it meant to measure only on the second.
        # It was not failing; it was running out of turns over a contradiction
        # the harness put there.
        branch = sc["given"].get("branch")
        if branch:
            r = sh(["git", "checkout", "-q", "-b", branch], cwd=repo)
            if r.returncode != 0:
                raise RuntimeError(f"the fixture could not be put on `{branch}`: "
                                   + (r.stderr or r.stdout).strip()[:150])
        write_state(repo, sc["given"].get("state"))
        seed_files(repo, sc["given"].get("files"),
                   commit=sc["given"].get("commit_files", True))

        if control:
            # ONE implementation. `apply_control` had `paths` support and this
            # branch resolved it inline with `ctl['path']`, so the capability
            # existed in a function nobody called — and a scenario declaring
            # `paths` died with a `KeyError`, came out ERROR, and in control
            # mode an ERROR counted as "went red". A control green for the
            # wrong reason, which is worse than a red one.
            try:
                apply_control(sc, scratch_root, repo, workdir, git_root=ddw_root)
            except Exception as exc:  # noqa: BLE001
                return Result(sc["id"], sc["kind"], ERROR, f"control unavailable: {exc}")

        kind = sc["kind"]
        if kind == "painted-door-sweep":
            # `scratch_root`, not `ddw_root`: it is the copy where the control
            # applies the broken instruction. Reading the real tree, the
            # control would see nothing and the sweep would pass the control
            # without being able to go red.
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
            # The agent and the model come from the scenario if it declares
            # them, and from the command line if not. Without this the same
            # scenario cannot be run against two adapters, which is half the
            # point: DDW ships six and the behavioral layer tested one.
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
            # An ERROR SHAPED LIKE AN EXCEPTION is the harness broken, not the
            # regression. `KeyError: 'when'` counted as "went red as it must"
            # in a run where the scenario could not even be assembled —
            # measured, and it is the same defect the line below closes for
            # "control unavailable". It generalizes: if what broke is the
            # instrument, the control proved nothing.
            #
            # `control off-target` is the third case and arrived with
            # `method-lint`: the control was applied, the instrument went red,
            # and it did so over a claim this scenario did not break. That does
            # not prove it can hunt its own — it is the same defect as the
            # control that failed with a `TypeError`, better disguised.
            #
            # And the fourth: "the agent did not complete a turn". Measured in
            # the cloud — a control counted as red because the CLI exited 1
            # without getting to answer, meaning the regression was never put
            # in front of anyone. It does not start with `…Error`, so the rule
            # above did not see it: a turn that did not run proves nothing, and
            # in control mode that GIVES the control AWAY — the one instrument
            # whose entire job is to distrust a green.
            _harness = re.match(r"^(\w*Error|\w*Exception|TimeoutExpired)\b", r.detail or "")
            _no_turn = (r.detail or "").startswith((
                "the agent did not complete a turn",
                "the agent produced no JSON events",
                "the agent returned output this runner cannot parse",
                "the agent reported an error"))
            if r.verdict == SKIP:
                pass                        # said, with its reason, and counted apart
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
        # A skip is counted apart and does not add up to a green: if EVERYTHING
        # there was to measure got skipped, the run measured nothing, and
        # saying "green" there is the same lie as a `bad` that cannot fail.
        print("  FATAL: every scenario was skipped — a run that measured nothing is not a pass.")
        return 2
    print("  green\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
