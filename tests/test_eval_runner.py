"""The eval harness, asked directly.

`evals/runner.py` is the instrument the instruction layer is measured with,
and an instrument nobody measures reports whatever. The scenarios exercise it
end to end — each one stands up a repo, installs the method and runs the
verdict — so they cost minutes: here go the capabilities of the harness
itself, which can be asked in milliseconds and are precisely the ones that,
broken silently, make a scenario pass for the wrong reason.

The three tested here arrived together and for the same reason: without them,
a whole family of scenarios could be written but not judged.

  · `given.files` — seeding the tree. Before, only `.ddw-state.json` could be
    written, so every scenario about a source file that already exists started
    from the fixture's empty repo — that is, measuring something else.
  · `expect.file_matches` — asserting on the CONTENT. `files_present` cannot
    tell the document that answers the question from the one that makes it
    up: both exist.
  · `kind: method-lint` — `lint_method.py` as a verdict, with its control.
"""
import importlib.util
import json
import os
import pathlib
import subprocess

import pytest

pytest.importorskip("yaml")  # the runner exits with exit(2) without it; do not hang collection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load("ddw_eval_runner", "evals/runner.py")


@pytest.fixture()
def repo(tmp_path):
    """A pretend git repo, shaped the way `make_repo` leaves one."""
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


# ── given.files: seeding the tree ────────────────────────────────────────────

def test_seed_files_writes_and_commits(repo):
    n = runner.seed_files(repo, {"src/account.py": "def delete(): ...\n",
                                 "docs/ddw/prd/prd-T-1.md": "# PRD\n"})
    assert n == 2
    assert (repo / "src" / "account.py").read_text() == "def delete(): ...\n"
    tracked = subprocess.run(["git", "ls-files"], cwd=repo,
                             capture_output=True, text=True).stdout.split()
    assert "src/account.py" in tracked and "docs/ddw/prd/prd-T-1.md" in tracked
    # And the tree ends up clean: a seeded, uncommitted source file is
    # uncommitted work the scenario did not ask for, and rules get measured on that.
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    assert dirty == ""


def test_seed_files_can_leave_them_uncommitted(repo):
    runner.seed_files(repo, {"src/a.py": "x\n"}, commit=False)
    # `-uall`: with the default, git collapses the new directory into `?? src/`
    # and the assertion on the full path says nothing.
    dirty = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=repo,
                           capture_output=True, text=True).stdout
    assert "?? src/a.py" in dirty


def test_seed_files_commits_what_the_install_ignores(repo):
    # The install leaves a block in `.gitignore`, and what it ignores — the
    # paused tickets, the session markers, the journal — is part of what a
    # scenario needs to seed. Without `-f` the commit finds nothing, and the
    # fixture silently ends up different from what the scenario says.
    (repo / ".gitignore").write_text(".ddw-paused/\n")
    runner.seed_files(repo, {".ddw-paused/T-2.json": '{"ticket": "T-2"}\n'})
    tracked = subprocess.run(["git", "ls-files"], cwd=repo,
                             capture_output=True, text=True).stdout.split()
    assert ".ddw-paused/T-2.json" in tracked


def test_seed_files_does_not_write_outside_the_fixture(repo):
    # The control that rewrote the checkout of whoever ran it cost twenty
    # minutes of believing the product had a bug. Nobody comes in this way again.
    with pytest.raises(RuntimeError, match="outside the fixture"):
        runner.seed_files(repo, {"../escaped.py": "x"})
    with pytest.raises(RuntimeError, match="absolute path"):
        runner.seed_files(repo, {"/etc/passwd": "x"})
    assert not (repo.parent / "escaped.py").exists()


def test_seed_files_refuses_the_state_file(repo):
    with pytest.raises(RuntimeError, match="given.state"):
        runner.seed_files(repo, {".ddw-state.json": "{}"})


# ── expect.file_matches: the content, not the existence ──────────────────────

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
    # An assertion that cannot judge is the same as not writing it, and here
    # that reads as green. It raises: `run_one` turns it into ERROR, which is red.
    (repo / "prd.md").write_text("x")
    with pytest.raises(RuntimeError, match="asserts nothing"):
        _judge(repo, {"file_matches": [{"path": "prd.md"}]})


def test_a_regex_that_does_not_compile_raises(repo):
    (repo / "prd.md").write_text("x")
    with pytest.raises(RuntimeError, match="does not compile"):
        _judge(repo, {"file_matches": [{"path": "prd.md", "matches": "("}]})


def test_file_matches_works_inside_any_of(repo):
    # `any_of` judges each branch with this same function; a capability that
    # does not reach inside it leaves half a family of scenarios unwritable.
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
    # A linter that falls over before printing its verdict came out neither
    # green nor red. Counting it as red gives away the whole control mode.
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


# ── a control that cannot discriminate, said and counted separately ──────────

def test_a_control_that_cannot_discriminate_is_skipped_with_its_reason():
    # Measured: the `forged` control PASSES with a capable model, because its
    # three edits are prose and the hook rejects the write anyway. Leaving it
    # red forever trains everyone to ignore red; deleting it leaves the
    # scenario claiming to measure something it does not.
    import types
    sc = {"id": "x", "kind": "behavioral",
          "control": {"cannot_discriminate": "the rule is defended twice"}}
    args = types.SimpleNamespace(keep=False, agent="claude", model=None)
    r = runner.run_one(sc, os.path.join(ROOT), args, control=True)
    assert r.verdict == runner.SKIP
    assert "defended twice" in r.detail


def test_the_excuse_does_nothing_in_a_normal_run():
    # Only control mode looks at it: in normal mode the scenario has to run
    # like any other, or an excuse about the control would switch off the whole measurement.
    import inspect
    src = inspect.getsource(runner.run_one)
    head = src[:src.index("workdir = Path(")]
    assert "if control:" in head and "cannot_discriminate" in head


# ── control mode does not accept a red that belongs to the harness ───────────

@pytest.mark.parametrize("detail", [
    "KeyError: 'when'",
    "TimeoutExpired: …",
    "control unavailable: the anchor is gone",
    "control off-target: lint_method went red on another claim",
    # Measured in the cloud: a control got counted as red because the CLI
    # exited 1 without ever answering. The regression was never put in front of anyone.
    "the agent did not complete a turn (exit 1): ",
    "the agent produced no JSON events — the turn did not run",
])
def test_a_red_that_is_the_harness_does_not_pass_the_control(detail):
    import inspect
    src = inspect.getsource(runner.main)
    block = src[src.index("if args.control:"):src.index("results.append(r)")]
    # All four families have to be named in the branch that turns a harness
    # ERROR into a FAILED control, not into a legitimate red.
    needles = ("_harness", "_no_turn", "control unavailable", "control off-target",
               "the agent did not complete a turn", "the agent produced no JSON events")
    assert all(n in block or n in src for n in needles)
    assert "the control proved nothing" in block


# ── a control tied to a branch has an expiry date ────────────────────────────

def test_every_restored_commit_is_reachable_from_the_main_line():
    """A `restore_from_commit` pointing at a branch's commit dies with the branch.

    Measured: the squash-merge of PR #7 took the history of `feat/docs-audit`
    with it, and the control of `painted-door-install-doc-eject` — which
    restored `docs/INSTALL.md` at `4c41f3e^` — started failing from `main` for
    not being applicable. A control that cannot be applied proves nothing, and
    the scenario goes red for a reason that is not its own.
    """
    import glob
    import yaml
    # This question is about the REPOSITORY, not the tree: without `.git`
    # there is no main line to measure against, and `git merge-base` fails for
    # not being able to run — which is indistinguishable from an inapplicable
    # control.
    #
    # The `scripts/mutate.py` sandbox copies the tree with
    # `ignore_patterns(".git", …)`, so here this failed on EVERY unmutated
    # copy. The runner's red-baseline guard caught it and refused to inject —
    # meaning the mutation run could not start, locally or in CI, and the
    # cause was this test asking something that has no answer on a copy.
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        pytest.skip("no git history: the question cannot be asked of a copy of the tree")
    offenders = []
    for path in sorted(glob.glob(os.path.join(ROOT, "evals/scenarios/*.yaml"))):
        sc = yaml.safe_load(open(path, encoding="utf-8"))
        ctl = sc.get("control") or {}
        if ctl.get("type") != "restore_from_commit":
            continue
        commit = ctl["commit"]
        # Is it on the main line of THIS checkout? `HEAD` is enough because
        # every working branch comes off `main`; what gets ruled out is the
        # commit that lives only on another branch.
        r = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                           cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            offenders.append(f"{os.path.basename(path)} restores at {commit}")
    assert not offenders, (
        "these controls hang off history the main line does not carry, so they stop being "
        "applicable the day that branch is deleted — use `type: substitute`: " + "; ".join(offenders))


def test_a_scenario_with_work_in_progress_says_which_branch_it_is_on():
    """A state that says work in progress, on `master`, is an impossible world.

    The boot orders a branch check before resuming: on a generic one —
    `main`, `master`, `develop`… — the agent STOPS and asks about the
    inconsistency. That is the right behavior, and if the harness put it
    there the scenario spends a turn on something it does not measure.
    Measured with Claude Code: the entire first turn went to that.
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


# ── the real scenario, read as data ──────────────────────────────────────────

def test_the_method_lint_scenario_declares_a_control_with_a_target(tmp_path):
    import yaml
    p = os.path.join(ROOT, "evals/scenarios/method-lint-still-knows-how-to-go-red.yaml")
    sc = yaml.safe_load(open(p, encoding="utf-8"))
    assert sc["kind"] == "method-lint"
    # Without `finding_matches` the control settles for any red, which is
    # exactly what this kind exists to not accept.
    assert sc["control"]["finding_matches"]
    assert sc["kind"] in runner.OFFLINE_KINDS, "CI runs `--offline`; outside it this never runs"
    # And the control's anchor has to still exist in the tree, or the control
    # cannot be applied and proves nothing.
    for edit in sc["control"]["edits"]:
        text = open(os.path.join(ROOT, edit["path"]), encoding="utf-8").read()
        assert edit["old"] in text, f"the control's anchor is no longer in {edit['path']}"


def test_json_import_is_used_by_seed_files(repo):
    # A `given.files` whose value is not text gets written as JSON: it is how
    # a scenario seeds a manifest or another file's state without escaping it
    # by hand in the YAML.
    runner.seed_files(repo, {"pkg.json": {"name": "x"}})
    assert json.loads((repo / "pkg.json").read_text())["name"] == "x"


# ── Copilot: the level of the wiring is what decides whether anything gates ──
#
# Copilot was never measured end to end because it had no headless profile.
# These cases pin what the profile has to get right, and each one corresponds
# to a way of coming out green without having measured anything.


def test_copilot_has_a_headless_profile():
    """Without an entry, `agent_profile` raises and the scenario does not run.
    With a wrong one, it runs and measures something else: which is why the
    flags are asserted too."""
    name, prof = runner.agent_profile(["copilot"])
    assert name == "copilot"
    assert "--allow-all" in prof["flags"], "without --allow-all, -p mode does not even start"
    assert prof["prompt"] == ["-p", "{turn}"], "-p is the headless entry point"
    assert prof["dir"] == ["-C", "{repo}"], "without -C the run can point at another tree"


def test_copilot_turn_refuses_to_run_without_its_own_home():
    """HOME is where Copilot's gates live. Pointed at the operator's, the
    fixture gets judged by that machine's wiring and the scenario reports as
    product what belongs to the harness."""
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
    """A turn without an id is not a detail: the next turn opens another
    session, the model does not see what it just did, and the scenario
    measures first turns while claiming it measured a conversation."""
    payload, session, err = runner.agent_turn_read("copilot", "hecho, saludos")
    assert session is None
    assert err and "new session" in err


def test_the_copilot_tap_wraps_the_repo_hooks(tmp_path):
    """The user-level wiring runs THE REPO'S script by relative path, so
    wrapping the repo's copy is the only thing there is to wrap."""
    hooks = tmp_path / ".github" / "hooks" / "ddw"
    hooks.mkdir(parents=True)
    for name in ("pre-tool-use.sh", "post-write.sh", "pre-compact.sh"):
        (hooks / name).write_text("#!/usr/bin/env bash\nexit 0\n")
    assert runner._tap_copilot(tmp_path) == 2
    for name in ("pre-tool-use.sh", "post-write.sh"):
        assert (hooks / (name[:-3] + ".real.sh")).exists()
        assert "DDW_EVAL_PAYLOAD" in (hooks / name).read_text()
    # pre-compact is not a verdict: wrapping it would put an "allowed" in the
    # log for a write that never existed.
    assert not (hooks / "pre-compact.real.sh").exists()


def test_the_copilot_home_refuses_to_run_unauthenticated(tmp_path, monkeypatch):
    """A blank HOME has no credentials, and Copilot fails in a way that reads
    as a verdict about the product."""
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
    # JSONC: the real file opens with two `//` lines. Parsed as strict JSON it
    # blows up, the credentials get lost in silence, and the run fails at
    # authentication.
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
    # And NOTHING else crosses over: the session, the settings and the hooks start empty.
    assert sorted(p.name for p in (home / ".copilot").iterdir()) == ["config.json"]


# ── What the harness has to get right for a run to mean anything ─────────────
#
# The three below came out of mutations that SURVIVED: the code was right and
# nothing was holding it up. A fault nobody kills is a fault that comes back.


def _fake_install(runner_mod, monkeypatch, calls, wire_hooks=True):
    """Replaces `sh` with something that fakes the install and records how it was called."""
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
    """Installing for Copilot writes OUTSIDE the fixture, in `$HOME`. Without
    a HOME of its own, a single eval run rewires every Copilot session on the
    machine, and two parallel runs rewire each other."""
    _fake_creds(runner, monkeypatch, tmp_path)
    calls = []
    _fake_install(runner, monkeypatch, calls)
    wd = tmp_path / "wd"
    runner.make_repo(tmp_path / "src", "copilot", wd)
    install = [c for c in calls if any("install.sh" in str(x) for x in c["cmd"])][0]
    assert install["env"] is not None, "the Copilot install ran with the operator's HOME"
    assert install["env"]["HOME"] == str(wd / "home")
    assert install["env"]["HOME"] != os.environ.get("HOME")


def test_a_copilot_install_that_wired_no_hooks_is_refused(tmp_path, monkeypatch):
    """Exiting 0 without wiring anything is the exact way this looked healthy:
    the scenario runs, nothing judges, and the result reads as a clean pass."""
    _fake_creds(runner, monkeypatch, tmp_path)
    calls = []
    _fake_install(runner, monkeypatch, calls, wire_hooks=False)
    with pytest.raises(RuntimeError) as e:
        runner.make_repo(tmp_path / "src", "copilot", tmp_path / "wd")
    assert "user-level" in str(e.value)


def test_the_verdict_tap_covers_copilot(tmp_path, monkeypatch):
    """`_tap_copilot` can be perfect and called by nobody."""
    monkeypatch.setattr(runner, "_tap_claude", lambda repo: 0)
    monkeypatch.setattr(runner, "_tap_opencode", lambda repo: 0)
    hooks = tmp_path / ".github" / "hooks" / "ddw"
    hooks.mkdir(parents=True)
    for name in ("pre-tool-use.sh", "post-write.sh"):
        (hooks / name).write_text("#!/usr/bin/env bash\nexit 0\n")
    assert runner.install_verdict_tap(tmp_path) == 2
