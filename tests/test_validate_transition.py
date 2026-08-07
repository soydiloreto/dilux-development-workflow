"""The enforcement core, asked directly instead of through a repository.

`scripts/verify_install.sh` is the measurement that matters: it installs into a
real repo, sends a real event to a real hook, and reads the verdict the tool
would read. It costs eighty-five seconds, and `scripts/mutate.py` pays that once
per fault — four hundred and forty times.

This file is the other end of that trade. `validate-transition.py` is ~2,700
lines of which most is functions that take dictionaries and return a verdict, and
114 of the 440 faults are injected into it. Asked directly, the same questions
answer in milliseconds.

**It does not replace the suite and must not be read as covering what the suite
covers.** Nothing here proves a hook fires, an envelope is shaped as the tool
sends it, or an installer wrote what it said. What it proves is that the rules
say what they mean, which is the half that costs nothing to ask often.

The assertions are about VERDICTS — refused or allowed, and what the refusal
names — never about how the verdict is reached. A test that pins the internals
is a second implementation to keep in step, and this repository already carries
the scars of having the same rule written twice.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vt = _load("vt", "ddw/scripts/validate-transition.py")
GRAPH = json.load(open(os.path.join(ROOT, "ddw/rules/transition-graph.json"), encoding="utf-8"))


@pytest.fixture()
def repo(tmp_path):
    """A git repository, because several rules ask git about it."""
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    return str(tmp_path)


def state(phase="IDLE", tier=None, ticket=None, gates=None, history=None):
    return {"phase": phase, "tier": tier, "ticket": ticket,
            "gates": gates or {}, "history": history or []}


def entry(src, dst, action="x", **extra):
    return {"timestamp": "2026-08-06T10:00:00Z", "from": src, "to": dst, "action": action, **extra}


def refusal(old, new, **kw):
    """The refusal's text, or None if the write is allowed."""
    try:
        vt.validate(old, new, GRAPH, **kw)
        return None
    except vt.Block as exc:
        return str(exc)


# ── The source guard: which phases may write product code ────────────────────

@pytest.mark.parametrize("phase", sorted(vt.NO_SOURCE_PHASES))
def test_product_source_is_refused_in_every_phase_that_forbids_it(repo, phase):
    why = vt.source_write_denied(os.path.join(repo, "src/app.py"), repo, phase)
    assert why, f"{phase} allows product source"
    assert "source" in why.lower()


@pytest.mark.parametrize("phase", ["CODE", "CLOSEOUT", "FREE"])
def test_the_phases_that_write_code_can_write_code(repo, phase):
    assert vt.source_write_denied(os.path.join(repo, "src/app.py"), repo, phase) is None


@pytest.mark.parametrize("rel", ["docs/ddw/prd/prd-T-1.md", "AGENTS.md", "CHANGELOG.md",
                                 ".claude/settings.json", ".gitignore"])
def test_a_repository_at_rest_still_writes_what_it_needs(repo, rel):
    assert vt.source_write_denied(os.path.join(repo, rel), repo, "IDLE") is None


def test_the_refusal_at_idle_names_both_ways_out(repo):
    why = vt.source_write_denied(os.path.join(repo, "src/app.py"), repo, "IDLE")
    assert "CLASSIFY" in why and "FREE" in why


# ── DDW's own machinery, unwritable in every phase ───────────────────────────

@pytest.mark.parametrize("rel", [".ddw/rules/transition-graph.json",
                                 ".ddw/scripts/validate-transition.py",
                                 ".ddw-sessions/forged",
                                 ".ddw-installed.json"])
def test_the_method_is_sealed(repo, rel):
    assert vt.enforcement_write_denied(os.path.join(repo, rel), repo)


def test_the_plugin_root_is_sealed_not_only_the_method(tmp_path):
    """What the tool EXECUTES lives beside the method, not inside it."""
    plugin = tmp_path / "plugin"
    (plugin / "ddw").mkdir(parents=True)
    (plugin / "adapters" / "claude" / "hooks").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    hook = str(plugin / "adapters/claude/hooks/validate-state-transition.sh")
    assert vt._method_write_denied(hook, str(plugin / "ddw"), str(repo)), \
        "the hook that runs the gate is writable under a plugin install"


def test_a_dropin_install_does_not_seal_the_project(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".ddw").mkdir(parents=True)
    assert vt._method_write_denied(str(repo / "src/app.py"), str(repo / ".ddw"), str(repo)) is None


# ── The graph is the authority ───────────────────────────────────────────────

def test_every_tier_the_graph_defines_can_be_entered_from_classify():
    for tier in GRAPH["tiers"]:
        edges = vt._effective_edges(GRAPH, tier)
        assert [e for e in edges if e.startswith("CLASSIFY->")], \
            f"tier {tier} cannot be entered"


def test_no_working_phase_leads_into_free():
    for tier in GRAPH["tiers"]:
        into_free = [e for e in vt._effective_edges(GRAPH, tier) if e.endswith("->FREE")]
        assert into_free in ([], ["CLASSIFY->FREE"]), \
            f"tier {tier} walks into FREE from {into_free}"


def test_free_asks_for_no_gate():
    assert not vt._gate_owners(GRAPH, "FREE")


def test_a_gate_belongs_to_the_phase_the_graph_says_pays_it():
    owners = vt._gate_owners(GRAPH, "FEATURE")
    assert owners["spec"] == {"PLAN"}
    assert owners["tests"] == {"CODE"}
    assert owners["commit"] == {"CLOSEOUT"}


# ── The history is append-only, contiguous and moves forward ─────────────────

def test_history_cannot_go_backwards_in_time():
    first = entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1")
    late = dict(entry("CLASSIFY", "DEFINE", tier="FEATURE", ticket="T-1"),
                timestamp="2020-01-01T00:00:00Z")
    why = refusal(state("CLASSIFY", "FEATURE", "T-1", history=[first]),
                  state("DEFINE", "FEATURE", "T-1", history=[first, late]))
    assert why and "backwards" in why


def test_two_transitions_in_the_same_second_are_ordinary():
    first = entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1")
    same = entry("CLASSIFY", "DEFINE", tier="FEATURE", ticket="T-1")
    assert refusal(state("CLASSIFY", "FEATURE", "T-1", history=[first]),
                   state("DEFINE", "FEATURE", "T-1", history=[first, same])) is None


def test_a_write_may_declare_one_transition():
    h = [entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1"),
         entry("CLASSIFY", "DEFINE", tier="FEATURE", ticket="T-1")]
    why = refusal(state("IDLE", history=[]), state("DEFINE", "FEATURE", "T-1", history=h))
    assert why and "at most" in why


def test_dropping_history_is_refused():
    h = [entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1")]
    why = refusal(state("CLASSIFY", "FEATURE", "T-1", history=h),
                  state("CLASSIFY", "FEATURE", "T-1", history=[]))
    assert why


# ── The tier is set once, in CLASSIFY ────────────────────────────────────────

def test_the_tier_cannot_change_mid_ticket():
    h = [entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1")]
    why = refusal(state("CODE", "FEATURE", "T-1", history=h),
                  state("CODE", "FREE", "T-1", history=h))
    assert why and "CLASSIFY" in why


def test_a_write_cannot_drop_the_tier():
    h = [entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1")]
    why = refusal(state("CODE", "FEATURE", "T-1", history=h),
                  state("CODE", None, "T-1", history=h))
    assert why


# ── The entry points: paths and events, not dictionaries ─────────────────────
#
# `decide_pre` and `decide_post` are where most of this file's faults live, and
# they take a repository rather than a state. A repository is a temporary
# directory and a JSON file — still milliseconds, still no hook and no install.

def _repo_at(tmp_path, phase="CODE", tier="FEATURE", ticket="T-1", gates=None, history=None):
    repo = tmp_path / "r"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    h = history if history is not None else [
        entry("IDLE", "CLASSIFY", tier=tier, ticket=ticket),
        entry("CLASSIFY", "DEFINE", tier=tier, ticket=ticket)]
    (repo / ".ddw-state.json").write_text(json.dumps(
        state(phase, tier, ticket, gates or {"define": True, "spec": True, "threat": True}, h)))
    return str(repo)


def _pre(repo, path, content="x", tool="Write"):
    """The refusal, however it arrives.

    `decide_pre` has two ways of saying no — a returned reason for the guards,
    a raised `Block` for the state machine — and a caller that only handles one
    reads half the refusals as approvals. The hook handles both; so does this.
    """
    try:
        return vt.decide_pre(os.path.join(repo, ".ddw-state.json"),
                             os.path.join(ROOT, "ddw/rules/transition-graph.json"),
                             tool, {"file_path": path, "content": content}, [path], repo=repo)
    except vt.Block as exc:
        return str(exc)


def test_a_write_to_the_state_is_judged_not_waved_through(tmp_path):
    repo = _repo_at(tmp_path)
    forged = json.dumps(state("CLOSEOUT", "FEATURE", "T-1", {"tests": True, "sast": True}))
    why = _pre(repo, os.path.join(repo, ".ddw-state.json"), forged)
    assert why, "a state rewritten to a later phase was allowed"


def test_every_path_in_an_event_is_judged_not_only_the_first(tmp_path):
    repo = _repo_at(tmp_path, phase="DEFINE")
    decoy = os.path.join(repo, "docs/ddw/prd/prd-T-1.md")
    real = os.path.join(repo, "src/app.py")
    why = vt.decide_pre(os.path.join(repo, ".ddw-state.json"),
                        os.path.join(ROOT, "ddw/rules/transition-graph.json"),
                        "Write", {"file_path": decoy, "content": "x"}, [decoy, real], repo=repo)
    assert why, "a harmless path next to a refused one bought the write"


def test_a_path_reaching_a_sealed_file_through_a_symlink_is_refused(tmp_path):
    repo = _repo_at(tmp_path)
    (tmp_path / "r" / ".ddw").mkdir(exist_ok=True)
    (tmp_path / "r" / ".ddw" / "rules").mkdir(exist_ok=True)
    (tmp_path / "r" / ".ddw" / "rules" / "graph.json").write_text("{}")
    link = tmp_path / "r" / "docs"
    link.mkdir(exist_ok=True)
    (link / "passthru.json").symlink_to(tmp_path / "r" / ".ddw" / "rules" / "graph.json")
    why = _pre(repo, str(link / "passthru.json"))
    assert why, "a sealed file reached under an unsealed name was allowed"


def test_an_unreadable_state_is_not_read_as_a_fresh_idle(tmp_path):
    repo = _repo_at(tmp_path)
    (tmp_path / "r" / ".ddw-state.json").write_text("{ not json")
    why = _pre(repo, os.path.join(repo, "src/app.py"))
    assert why, "a corrupt state was treated as IDLE and the write went through"


def test_a_read_is_not_judged_as_a_write(tmp_path):
    repo = _repo_at(tmp_path, phase="DEFINE")
    target = os.path.join(repo, "src/app.py")
    assert vt.decide_pre(os.path.join(repo, ".ddw-state.json"),
                         os.path.join(ROOT, "ddw/rules/transition-graph.json"),
                         "Read", {"file_path": target}, [target],
                         repo=repo, raw_tool="Read") is None


# ── Three guards nothing else drives ─────────────────────────────────────────
#
# Each of these had a fault in `scripts/mutate.py` and no check anywhere: the
# suite installs, sends an event and reads a verdict, and none of the events it
# sends has the shape that reaches them. Asked here they cost milliseconds.

def test_a_path_outside_the_repo_does_not_excuse_the_ones_inside(tmp_path):
    """The escape hatch is for events wholly outside the repository.

    A corrupt state refuses every write, and the recovery it prescribes is to
    write the corrected state to a scratch path OUTSIDE the repo — so an event
    naming nothing inside is not DDW's to judge. Read as "any path outside", one
    scratch path in the same event buys the write next to it, and the corrupt
    state that must stay refused until a human restores it becomes writable by
    naming `/tmp/anything` alongside it.
    """
    repo = _repo_at(tmp_path)
    (tmp_path / "r" / ".ddw" / "rules").mkdir(parents=True, exist_ok=True)
    (tmp_path / "r" / ".ddw" / "rules" / "graph.json").write_text("{}")
    # Two paths, neither of which NAMES anything in the repository: one genuinely
    # outside, one a scratch name that resolves back inside to the method's own
    # graph. Every name is outside; not every file is. Asked as "is any of this
    # outside?", the first path answers for the second and the write to the
    # graph is never looked at.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "notes.txt").write_text("x")
    (scratch / "passthru.json").symlink_to(tmp_path / "r" / ".ddw" / "rules" / "graph.json")
    paths = [str(scratch / "notes.txt"), str(scratch / "passthru.json")]
    why = None
    try:
        why = vt.decide_pre(os.path.join(repo, ".ddw-state.json"),
                            os.path.join(ROOT, "ddw/rules/transition-graph.json"),
                            "Write", {"file_path": paths[0], "content": "{}"},
                            paths, repo=repo)
    except vt.Block as exc:
        why = str(exc)
    assert why, "a path outside the repo answered for one beside it that reaches the method"


def test_a_file_the_manifest_says_ddw_installed_is_not_writable(tmp_path):
    """The manifest is the only thing that knows which file in a shared
    directory is DDW's. The prefixes and wiring directories above it cover the
    hooks; what is left to this branch is everything else the installer wrote —
    the skills, agents and commands that carry the rules themselves."""
    repo = _repo_at(tmp_path)
    installed = ".claude/skills/ddw-commit/SKILL.md"
    with open(os.path.join(repo, ".ddw-installed.json"), "w", encoding="utf-8") as fh:
        json.dump({"claude:" + installed: "0" * 64}, fh)
    assert vt.enforcement_write_denied(os.path.join(repo, installed), repo), \
        "a file the manifest records as DDW's own was writable"
    assert vt.enforcement_write_denied(
        os.path.join(repo, ".claude/skills/mine/SKILL.md"), repo) is None, \
        "a skill the manifest does not name was refused — the manifest is what makes this precise"


def test_one_undecodable_byte_in_the_journal_is_a_refusal_not_a_traceback(tmp_path):
    """`encoding="utf-8"` raises from the ITERATION, not from `json.loads`, so a
    handler around the parse never sees it: one stray byte anywhere in the
    journal came out of the hook as a traceback, refusing every write in the
    repository, permanently, while naming a state file with nothing wrong in
    it."""
    repo = _repo_at(tmp_path)
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "wb") as fh:
        fh.write(b'{"from": "IDLE", "to": "CLASSIFY"}\n\xff\xfe not utf-8\n')
    why = _pre(repo, os.path.join(repo, "src/app.py"))
    assert why, "a journal with an undecodable byte was read as an empty journal"
    assert "journal" in why.lower(), \
        f"the refusal does not name the journal, so the reader repairs the wrong file: {why[:200]}"

    # And the readers that run BEFORE no guard at all. `decide_post` counts the
    # journal's entries without asking `_journal_undecodable` first, so it is
    # where reading the file as text — rather than as bytes decoded a line at a
    # time — comes back out of the hook as a traceback instead of a sentence.
    try:
        vt.decide_post(os.path.join(repo, ".ddw-state.json"),
                       os.path.join(ROOT, "ddw/rules/transition-graph.json"))
    except vt.Block:
        pass                                  # a refusal is an answer; a traceback is not
    except UnicodeDecodeError as exc:         # noqa: F841 — the failure being asserted against
        raise AssertionError(
            "one undecodable byte in the journal came out of the post-write gate as a "
            "traceback: every write in the repository is refused for it, permanently") from exc
