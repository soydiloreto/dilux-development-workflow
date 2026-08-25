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


def state(phase="IDLE", tier=None, ticket=None, gates=None, history=None, title=None):
    # A ticket carries a name from the arc that classifies it, and the
    # validator demands it there. The fixtures did not set it — the field did
    # not exist in this helper — so twelve tests were building the state the
    # product no longer accepts and measuring the wrong rule. It fills itself
    # in, unless the test deliberately says otherwise.
    return {"phase": phase, "tier": tier, "ticket": ticket,
            "title": title if title is not None else (f"ticket {ticket}" if ticket else None),
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


def test_the_refusal_at_idle_does_not_hand_over_the_way_around_itself(repo):
    """The refusal names the sanctioned path and NOT the recipe around it.

    It used to carry both: `--to CLASSIFY` and, right beside it, `--to
    CLASSIFY --tier FREE` with its second step. Measured with a live model on
    OpenCode: it read the refusal, took the two steps of the unenforced tier,
    and wrote the file. It did not cheat — it did what the message said it
    could do.

    Working without the pipeline is the user's decision. Put in the refusal,
    it becomes the model's decision, and a pipeline that teaches how to skip
    itself is enforcing nothing. The tier stays; what goes is the recipe.
    """
    why = vt.source_write_denied(os.path.join(repo, "src/app.py"), repo, "IDLE")
    assert "CLASSIFY" in why, "the refusal does not name the sanctioned path"
    assert "--tier FREE" not in why and "--to FREE" not in why, \
        "the refusal still hands over the recipe for skipping the pipeline: " + why
    assert "ask" in why.lower() or "user" in why.lower(), \
        "the refusal does not say whose decision it is: " + why


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


# ── FREE is the one tier the user has to ask for ─────────────────────────────
#
# Measured live on 0.32.2: asked to create a file in IDLE, the model read
# `classify.instructions.md` — the file that says *never propose it, never
# offer it as the way out of a refusal you just gave* — and offered exactly
# that, with "(Recomendado)" beside it. The write refusal no longer hands over
# the recipe; the model learned it from the rule that forbids it. A rule the
# model reads and steps over is a rule the pipeline does not have.

_INTO_CLASSIFY = entry("IDLE", "CLASSIFY", tier=None, ticket=None)


def _free_arrow(action):
    return state("FREE", "FREE", None, {},
                 [_INTO_CLASSIFY,
                  dict(entry("CLASSIFY", "FREE", tier="FREE", ticket=None), action=action)])


def test_free_needs_the_users_own_words():
    old = state("CLASSIFY", None, None, {}, [_INTO_CLASSIFY])
    with pytest.raises(vt.Block) as exc:
        vt.validate(old, _free_arrow("sin workflow para esta prueba"), GRAPH)
    assert "own words" in str(exc.value), str(exc.value)

    # With the user's own sentence quoted, it passes.
    vt.validate(old, _free_arrow('free: "no me armes workflow, quiero probar algo"'), GRAPH)


def test_el_ticket_sale_de_classify_con_nombre():
    """Measured live: a FEATURE reached DEFINE with `"title": null`.

    The rules say `title` and `tracker` get filled in the SAME write as the
    arrow that classifies — and that write used to be a hand-made `Write`.
    When the helper gained `--write` and became the door the state actually
    lands through, both fields were left with no way in. From then on every
    status line, every report header and the PR title were the model
    reconstructing the name from context, while the state — the thing that
    survives the session — named nothing.
    """
    old = state("CLASSIFY", None, None, {}, [entry("IDLE", "CLASSIFY")])
    sin_nombre = {**state("DEFINE", "FEATURE", "F-1", {},
                          [entry("IDLE", "CLASSIFY"),
                           entry("CLASSIFY", "DEFINE", tier="FEATURE", ticket="F-1")]),
                  "title": None}
    with pytest.raises(vt.Block) as exc:
        vt.validate(old, sin_nombre, GRAPH)
    assert "title" in str(exc.value)

    con_nombre = dict(sin_nombre, title="Tetris LatinoNet")
    vt.validate(old, con_nombre, GRAPH)


def test_the_tier_cannot_turn_free_in_a_silent_write():
    """Without a new entry there is nowhere to put the words — and without them, no FREE."""
    old = state("CLASSIFY", None, None, {}, [_INTO_CLASSIFY])
    silent = state("CLASSIFY", "FREE", None, {}, [_INTO_CLASSIFY])
    with pytest.raises(vt.Block):
        vt.validate(old, silent, GRAPH)


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


def test_the_agent_may_read_the_method_it_is_held_to(tmp_path):
    """The test above measures a PRODUCT path, and that is why this defect lived.

    `decide_pre` has two guards and a single "is this a write?" question. The
    method guard was hoisted to the top of the function to close the plugin
    hole and landed IN FRONT of that question, so any tool naming a path under
    `.ddw/` — a `view` included — got refused. In Claude it does not show: the
    hook's matcher sends only Edit|Write. In Copilot preToolUse has no matcher
    and receives them all.

    Measured live: the sessionStart hook injects "read `.ddw/orchestrator.md`
    now and run its Boot Sequence" and the next tool came back with "DDW
    blocked this write: orchestrator.md is part of DDW itself". The agent
    could not load the state machine it was being held to, and the whole run
    looked like DDW not installed — with the refusals written in DDW's words.
    """
    repo = _repo_at(tmp_path, phase="IDLE", gates={})
    method = os.path.join(repo, ".ddw")
    os.makedirs(method, exist_ok=True)
    orch = os.path.join(method, "orchestrator.md")
    with open(orch, "w", encoding="utf-8") as fh:
        fh.write("# el orquestador\n")
    graph = os.path.join(ROOT, "ddw/rules/transition-graph.json")
    state_path = os.path.join(repo, ".ddw-state.json")

    leer = vt.decide_pre(state_path, graph, "Edit", {"path": orch}, [orch],
                         repo=repo, raw_tool="view", method=method)
    assert leer is None, \
        "the agent cannot READ the orchestrator the hook orders it to read: " + str(leer)

    # `rg` says neither "read" nor "grep" in any of its letters: the list
    # above is matched by substring and an abbreviation matches nothing.
    # Copilot calls ripgrep that way, and measured live one release after the
    # reads were let through: `view` of the orchestrator passed and `rg` on
    # the same file came back "DDW blocked this write". The agent recovered
    # via `bash grep`, which is the part to read twice — the refusal did not
    # stop the read, it moved it to the one door PreToolUse cannot see.
    assert vt.decide_pre(state_path, graph, "Edit", {"path": orch}, [orch],
                         repo=repo, raw_tool="rg", method=method) is None, \
        "`rg` over the method is judged as a write"
    # And the abbreviation matches WHOLE: two letters inside another name
    # cannot turn a write into a read.
    assert vt.decide_pre(state_path, graph, "Edit", {"path": orch}, [orch],
                         repo=repo, raw_tool="purge", method=method), \
        "a name that merely CONTAINS `rg` passed as a read"

    # …and the rule the guard does impose still stands: writing it is refused.
    escribir = vt.decide_pre(state_path, graph, "Write",
                             {"path": orch, "content": "otras reglas"}, [orch],
                             repo=repo, raw_tool="create", method=method)
    assert escribir, "the method ended up writable from inside the pipeline"


# ── The artifact that holds up an earned gate ────────────────────────────────
#
# Measured in round 6: CODE found a real error in the spec, announced it would
# be "registrado en VERIFY" — a place that does not exist — and moved on.
# Fixing it right there would have been worse: the document changing shape
# under a gate nobody re-earned, which is exactly the laundering the graph's
# `clears` exists to prevent, coming in through another door.

def test_la_spec_no_se_reescribe_con_su_compuerta_en_pie(tmp_path):
    repo = _repo_at(tmp_path, phase="CODE", ticket="T-1",
                    gates={"define": True, "spec": True, "threat": True})
    why = _pre(repo, os.path.join(repo, "docs/ddw/specs/spec-T-1.md"), "corregida a mano")
    assert why and "PLAN" in why, \
        "the approved spec was rewritten from CODE without re-earning the gate: %r" % why


def test_el_modelo_de_amenazas_tambien_esta_sellado(tmp_path):
    """`CODE->PLAN` clears `spec` AND `threat`: both are PLAN's artifacts, and
    sealing only one leaves the other rewritable under its own gate."""
    repo = _repo_at(tmp_path, phase="CODE", ticket="T-1",
                    gates={"define": True, "spec": True, "threat": True})
    why = _pre(repo, os.path.join(repo, "docs/ddw/security/threat-T-1.md"), "x")
    assert why, "the approved threat model was rewritten from CODE"


def test_en_PLAN_la_spec_se_escribe_porque_su_compuerta_no_esta_ganada(tmp_path):
    """The other half, and the one that keeps the seal from being a padlock:
    PLAN is where the spec gets written, and the way back from CODE clears the
    gate precisely so it can be corrected. A seal that also bites here fixes
    nothing — it leaves the ticket dead."""
    repo = _repo_at(tmp_path, phase="PLAN", ticket="T-1", gates={"define": True})
    assert _pre(repo, os.path.join(repo, "docs/ddw/specs/spec-T-1.md"), "x") is None, \
        "the spec cannot be written in the phase that writes it"


def test_la_spec_de_otro_ticket_no_es_este_sello(tmp_path):
    """The seal is on THIS ticket's artifact. A split parent's index and the
    sibling's spec are other documents; sealing them for looking alike breaks
    the split's closeout, which edits the parent's index."""
    repo = _repo_at(tmp_path, phase="CODE", ticket="T-1",
                    gates={"define": True, "spec": True, "threat": True})
    assert _pre(repo, os.path.join(repo, "docs/ddw/specs/spec-T-2.md"), "x") is None, \
        "the active ticket's seal reached another ticket's document"


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


# ── Three guards the suite executes zero times ───────────────────────────────
#
# These did not come from reading the code for what is missing: they came from
# running the suite under `coverage` with `COVERAGE_PROCESS_START`, which also
# measures subprocesses — the validators and the hooks are subprocesses, and
# without it none gets measured — and looking at which lines of this file it
# never executes once. All three are enforcement rules, not error branches.

def _journal(repo, records):
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def test_a_receipt_from_before_the_corrective_loop_does_not_reopen_the_gate(tmp_path):
    """The whole case for `_receipt_spent`, and the suite never touched it.

    A corrective loop hands the gate back: the code changed, so whatever the
    previous report said no longer says anything about THIS code. A receipt
    written before that hand-back witnesses an old run — and since a report's
    bytes do not change when the code does, it is exactly the receipt that
    reopens the door without anyone having measured again.
    """
    repo = _repo_at(tmp_path)
    marker = "tests-validated-abc123"
    _journal(repo, [{"record": "receipt", "name": marker, "file": "x.md"},
                    {"record": "spent", "gates": ["tests"]}])
    why = vt._receipt_spent(repo, "tests", marker)
    assert why, "a receipt from before the corrective loop reopened the gate"
    assert "again" in why.lower() or "re-run" in why.lower(), \
        f"the refusal does not say what to do: {why[:160]}"

    # And the order is the only thing that decides: the same receipt, written
    # AFTER the gate was handed back, is the good receipt.
    _journal(repo, [{"record": "spent", "gates": ["tests"]},
                    {"record": "receipt", "name": marker, "file": "x.md"}])
    assert vt._receipt_spent(repo, "tests", marker) is None, \
        "a receipt written after the corrective loop was refused anyway"


def test_a_repo_upgraded_mid_ticket_has_to_re_earn_its_receipts(tmp_path):
    """No journal but with history: the answer is the EMPTY set, not "don't
    know". Read as "don't know", a repo whose journal was deleted ends up more
    permissive than one that has it — the reverse of what the rest of the file
    promises. The cost is re-running the validators, a minute."""
    repo = _repo_at(tmp_path)
    os.remove(os.path.join(repo, ".ddw-journal.jsonl")) if os.path.exists(
        os.path.join(repo, ".ddw-journal.jsonl")) else None
    assert vt._receipt_witnesses(repo) == set(), \
        "a repo with history and no journal takes whatever receipts it finds on disk as good"

    # A repo that has not started anything is the other case, and there it IS
    # "don't know": there is nothing to re-earn and refusing would refuse a
    # fresh install.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with open(fresh / ".ddw-state.json", "w", encoding="utf-8") as fh:
        json.dump(state("IDLE"), fh)
    assert vt._receipt_witnesses(str(fresh)) is None, \
        "a freshly installed repo has to re-earn receipts it never earned"


@pytest.mark.parametrize("tool,needle", [("Edit", "not an Edit"), ("Write", "history")])
def test_the_refusal_for_a_phase_without_its_entry_names_the_tool_that_can_fix_it(
        tmp_path, tool, needle):
    """An Edit CANNOT change the header (above) and append to `history`
    (below) in one operation. Telling whoever used Edit "rewrite the file
    adding the entry" sends them to repeat what just failed, and measured
    live the model loops. The refusal is the same; what changes is whether it
    can be acted on."""
    repo = _repo_at(tmp_path, phase="PLAN")
    target = os.path.join(repo, ".ddw-state.json")
    graph = os.path.join(ROOT, "ddw/rules/transition-graph.json")
    if tool == "Edit":
        # A real Edit: only the header, which is all an Edit reaches.
        payload = {"file_path": target, "old_string": '"phase": "PLAN"',
                   "new_string": '"phase": "CODE"'}
    else:
        payload = {"file_path": target, "content": json.dumps(
            state("CODE", "FEATURE", "T-1",
                  {"define": True, "spec": True, "threat": True},
                  [entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1"),
                   entry("CLASSIFY", "DEFINE", tier="FEATURE", ticket="T-1")]))}
    try:
        why = vt.decide_pre(target, graph, tool, payload, [target], repo=repo)
    except vt.Block as exc:
        why = str(exc)
    assert why, "a phase that changed without its history entry passed"
    low = why.lower()
    assert "history" in low, f"the refusal does not name what is missing: {why[:200]}"
    if tool == "Edit":
        assert "edit cannot" in low or "use a write" in low, \
            f"whoever used Edit is not told that Edit cannot do it: {why[:240]}"


# ── Four holes the entire suite cannot see ───────────────────────────────────
#
# From an audit aimed at the core: correct guards in the code and nothing
# measuring them. All four faults survived the 553 checks.

def test_a_notebook_write_carries_a_path_the_guards_can_see(tmp_path):
    """`NotebookEdit` is in all six adapters' matchers and carries the path in
    `notebook_path`, not `file_path`. If that key is not in the list that
    knows where each tool hides the path, the event reaches the gate with NO
    path to judge — and a guard that receives no paths refuses nothing:
    product source written in any phase, with both hooks green."""
    repo = _repo_at(tmp_path, phase="PLAN")
    nb = os.path.join(repo, "src/model.ipynb")
    payload = {"notebook_path": nb, "new_source": "x = 1"}
    # The paths are pulled out of the event WITH `PATH_KEYS`, which is what is
    # being tested: passing the list by hand here skips exactly the line that
    # decides. The hook does precisely this, in `main`.
    paths = [payload.get(k) for k in vt.PATH_KEYS]
    why = None
    try:
        why = vt.decide_pre(os.path.join(repo, ".ddw-state.json"),
                            os.path.join(ROOT, "ddw/rules/transition-graph.json"),
                            "NotebookEdit", payload, paths, repo=repo)
    except vt.Block as exc:
        why = str(exc)
    assert why, "a NotebookEdit wrote product source in PLAN without any guard seeing the path"
    assert "source" in why.lower(), f"the refusal does not say what was refused: {why[:160]}"


@pytest.mark.parametrize("rel", ["src/docs/app.py", "lib/docs/ddw/helper.py"])
def test_the_artefact_allowlist_is_a_prefix_and_not_a_substring(tmp_path, rel):
    """`docs/` opens the phases to the artifacts the method orders written.
    Read as a substring instead of a prefix, any path carrying `docs/` in the
    middle becomes writable in every phase — and `src/docs/` is an ordinary
    directory name, not a contrived one."""
    repo = _repo_at(tmp_path, phase="PLAN")
    assert vt.source_write_denied(os.path.join(repo, rel), repo, "PLAN"), \
        f"{rel} could be written in PLAN: the allowlist is no longer anchored at the start"
    # …and what the allowlist exists to allow stays allowed.
    assert vt.source_write_denied(
        os.path.join(repo, "docs/ddw/prd/prd-T-1.md"), repo, "PLAN") is None, \
        "the guard swallowed the artifact the phase has to write"


def test_a_forged_history_cannot_skip_whole_phases(tmp_path):
    """In post mode — the only route that sees a `jq` or a `sed` — this is the
    only thing preventing skipped phases: each loose edge IS in the graph, and
    what is not is the jump between one and the next. Without comparing one's
    `to` against the next one's `from`, IDLE→CLASSIFY followed by PLAN→CODE
    passes."""
    repo = _repo_at(tmp_path)
    h = [entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1"),
         entry("PLAN", "CODE", tier="FEATURE", ticket="T-1")]
    with open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8") as fh:
        json.dump(state("CODE", "FEATURE", "T-1",
                        {"define": True, "spec": True, "threat": True}, h), fh)
    why = None
    try:
        why = vt.decide_post(os.path.join(repo, ".ddw-state.json"),
                             os.path.join(ROOT, "ddw/rules/transition-graph.json"))
    except vt.Block as exc:
        why = str(exc)
    assert why, "a history that jumps from CLASSIFY to PLAN without DEFINE passed the post gate"
    assert "contiguous" in why.lower() or "CLASSIFY" in why, \
        f"the refusal does not say where the chain breaks: {why[:200]}"


def test_a_receipt_earned_for_another_document_does_not_open_this_gate(tmp_path):
    """The receipt is named by a digest of the CONTENT alone, on purpose: one
    keyed on the file name would keep witnessing a document that was later
    rewritten. The price is that two tickets with byte-identical documents
    share a receipt name, and the file's first line — which document it was
    earned for — is the only thing that tells them apart.

    The attack needs nothing exotic: `docs/` is writable in every phase, so
    it is a `cp`."""
    repo = _repo_at(tmp_path, phase="DEFINE", gates={})
    prd_dir = os.path.join(repo, "docs/ddw/prd")
    os.makedirs(prd_dir)
    body = "# PRD T-1\n\n| Field | Value |\n|---|---|\n| Ticket | T-1 |\n"
    for stem in ("prd-T-1.md", "prd-T-2.md"):
        with open(os.path.join(prd_dir, stem), "w", encoding="utf-8") as fh:
            fh.write(body)

    sys.path.insert(0, os.path.join(ROOT, "ddw/scripts"))
    receipt = _load("ddw_receipt", "ddw/scripts/ddw_receipt.py")
    name = "prd-validated-" + receipt.digest_of(body)
    os.makedirs(os.path.join(repo, ".ddw-sessions"), exist_ok=True)
    with open(os.path.join(repo, ".ddw-sessions", name), "w", encoding="utf-8") as fh:
        fh.write("prd-T-1.md\n")          # earned for T-1, and only for T-1
    with open(os.path.join(repo, ".ddw-journal.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": "receipt", "name": name, "file": "prd-T-1.md"}) + "\n")

    st = state("DEFINE", "FEATURE", "T-1", {}, [entry("IDLE", "CLASSIFY", tier="FEATURE",
                                                      ticket="T-1")])
    assert vt._prd_receipt_missing(repo, st) is None, \
        "the ticket that DID earn the receipt was shut out, so the check below proves nothing"
    st2 = dict(st, ticket="T-2")
    why = vt._prd_receipt_missing(repo, st2)
    assert why, ("a receipt earned for prd-T-1.md opened prd-T-2.md's gate — a `cp` of a "
                 "document every phase can write counts as a validation")
    assert "T-2" in why, f"the refusal does not name the document left to validate: {why[:200]}"


def test_the_helper_never_stamps_an_entry_before_the_one_it_follows(tmp_path):
    """The wall clock goes backwards, and the pipeline used to stop with no way out.

    Measured on the machine this is written on — WSL2, which resyncs with the
    host — six one-second backward jumps in 33,465 samples over 75 seconds
    under load. A jump between two steps leaves the new entry stamped before
    the previous one, and the monotonicity guard refuses a legal transition
    the helper just built. No way out: the only thing that would fix it is
    editing the history, which the hook also refuses.

    The guard stays untouched — it protects against a hand-reordered history,
    which is what it was written for. What cannot happen is the sanctioned
    path producing the case.
    """
    # From CLASSIFY, not from IDLE: the edge that SETS the tier has rules of
    # its own, and the first version of this test stepped on them — it failed
    # with a message about the tier, not the clock, and only sometimes. A test
    # that falls over for something other than what it measures is noise,
    # which is exactly what this whole file is trying to get out of the
    # instrument.
    repo = _repo_at(tmp_path, phase="CLASSIFY")
    ahead = "2099-01-01T00:00:00Z"          # the last stamp, in the future
    with open(os.path.join(repo, ".ddw-state.json"), "w", encoding="utf-8") as fh:
        json.dump(state("CLASSIFY", "FEATURE", "T-1", {},
                        [dict(entry("IDLE", "CLASSIFY", tier="FEATURE", ticket="T-1"),
                              timestamp=ahead)]), fh)
    # An explicit `CLAUDE_PROJECT_DIR`: the helper resolves the repo through
    # that variable BEFORE the cwd, and the suite exports it and does not
    # clean it up. Inherited, this subprocess worked on another section's
    # repo: the test passed alone and failed inside the suite, with a message
    # about gates that had nothing to do with what it measures.
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "ddw/scripts/transition.py"),
         "--to", "DEFINE", "--action", "x", "--write"],
        capture_output=True, text=True, cwd=repo,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=repo))
    assert r.returncode == 0, \
        ("a legal transition was refused because the clock went backwards, and there is "
         "nothing the user can do: " + (r.stderr or r.stdout)[-200:])
    history = json.load(open(os.path.join(repo, ".ddw-state.json"), encoding="utf-8"))["history"]
    stamps = [e["timestamp"] for e in history]
    assert stamps == sorted(stamps), f"the history ended up out of order anyway: {stamps}"
    assert stamps[-1] >= ahead, \
        "the new stamp landed before the previous one, which is what the guard refuses"


# ── The helper and its own gate ──────────────────────────────────────────────
#
# Two defects measured in one real run, an arrow apart. The helper resolved a
# value for the history entry and left the header without it; post mode reads
# the tier and the ticket from the entries, so it condemned the very bytes the
# helper had just written with exit 0. And the refusal, which is correct, says
# do not repair: one missing flag stopped the run and only a hand-made `cp`
# brought it back.

# Paths, not the already-loaded graph: `GRAPH` in this module is the parsed
# JSON and half a dozen tests use it as a dict.
_TRANSITION_PY = os.path.join(ROOT, "ddw/scripts/transition.py")
_GRAPH_PATH = os.path.join(ROOT, "ddw/rules/transition-graph.json")


def test_el_helper_sin_write_dice_que_no_escribio(tmp_path):
    """An output indistinguishable from a success is a false success.

    The helper PRINTS on purpose: the state has to land through a `Write`,
    which is the door PreToolUse watches. What it did not do was say so, and
    its stdout is a complete, valid state file.

    Measured live on Copilot: the model ran the documented command, read a
    state that said `"phase": "CLASSIFY"`, told the user the pipeline had
    advanced and went on classifying. On disk the phase was still IDLE,
    `history` was empty and no journal line existed. Exit 0, DDW's JSON, and
    a transition that never happened.
    """
    p = str(tmp_path / ".ddw-state.json")
    open(p, "w", encoding="utf-8").write(json.dumps(state()))
    r = subprocess.run([sys.executable, _TRANSITION_PY, "--state", p, "--graph", _GRAPH_PATH,
                        "--to", "CLASSIFY", "--action", "clasificar: probar"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-300:]
    assert json.loads(r.stdout)["phase"] == "CLASSIFY", \
        "the helper stopped emitting the next state, which is what it exists for"
    on_disk = json.load(open(p, encoding="utf-8"))
    assert on_disk["phase"] == "IDLE" and on_disk["history"] == [], \
        "without --write the helper wrote anyway, skipping the door PreToolUse watches"
    aviso = r.stderr.lower()
    assert "nothing was written" in aviso or "not been written" in aviso, \
        ("the helper prints a state that looks landed and does not say it did not land: "
         + repr(r.stderr))
    assert "write" in aviso, "the notice does not say which step is missing: " + repr(r.stderr)


def _step(state_path, *args):
    # `--title` fills itself in when the step names a ticket and the test said
    # nothing else: the classifying arc demands it, and none of these steps
    # measures that — they measure the tier, the clock, the turn or the pause.
    # A test that falls over on a field it is not measuring stops measuring
    # its own thing.
    args = list(args)
    if "--ticket" in args and "--title" not in args:
        args += ["--title", "un ticket de prueba"]
    return subprocess.run([sys.executable, _TRANSITION_PY, "--state", state_path,
                           "--graph", _GRAPH_PATH, *args, "--write"],
                          capture_output=True, text=True,
                          cwd=os.path.dirname(state_path))


def _split_upto_pause(tmp_path):
    """CLASSIFY → DEFINE → IDLE(pause), which is how every split ends."""
    p = str(tmp_path / ".ddw-state.json")
    open(p, "w", encoding="utf-8").write(json.dumps(state()))
    assert _step(p, "--to", "CLASSIFY", "--tier", "FEATURE", "--ticket", "F-1",
                 "--action", "clasificar").returncode == 0
    assert _step(p, "--to", "DEFINE", "--tier", "FEATURE", "--ticket", "F-1",
                 "--action", "definir").returncode == 0
    assert _step(p, "--to", "IDLE", "--action", "pause: split into F-1a/F-1b").returncode == 0
    return p


def test_el_header_lleva_el_tier_que_lleva_la_entrada(tmp_path):
    """Leaving IDLE after a pause, the helper recovers the paused tier and
    stamps it on the entry. If it does not put it in the header too, the
    state contradicts its own newest arrow and post mode condemns it."""
    p = _split_upto_pause(tmp_path)
    r = _step(p, "--to", "CLASSIFY", "--ticket", "F-1a", "--action", "abrir sub-ticket")
    assert r.returncode == 0, r.stderr[-300:]
    d = json.load(open(p, encoding="utf-8"))
    assert d["tier"] == "FEATURE", (
        "the header was left without a tier while its last entry says %r — the state the "
        "post-write calls corrupt" % d["history"][-1].get("tier"))
    assert d["history"][-1].get("tier") == "FEATURE"


def test_el_header_lleva_el_ticket_que_lleva_la_entrada_al_retomar(tmp_path):
    """A `resume:` does inherit the paused ticket — and has to restore it in
    the header for the same reason."""
    p = _split_upto_pause(tmp_path)
    r = _step(p, "--to", "DEFINE", "--action", "resume: seguimos con lo pausado")
    assert r.returncode == 0, r.stderr[-300:]
    d = json.load(open(p, encoding="utf-8"))
    assert d["ticket"] == "F-1" == d["history"][-1].get("ticket")


def test_saliendo_de_idle_tras_un_pause_el_helper_no_adivina_el_ticket(tmp_path):
    """For a split's sub-ticket — the normal way a pause ends — inheriting the
    paused ticket stamps the parent's ID on a run that belongs to the child,
    and post mode finds one run naming two tickets."""
    p = _split_upto_pause(tmp_path)
    r = _step(p, "--to", "CLASSIFY", "--action", "abrir sub-ticket del split")
    assert r.returncode == 2, "the helper guessed instead of asking for --ticket"
    assert "--ticket" in r.stderr, r.stderr[-300:]
    assert json.load(open(p, encoding="utf-8"))["phase"] == "IDLE", "it wrote anyway"


# ── One arrow per turn ───────────────────────────────────────────────────────
#
# The orchestrator says it hard — "NEVER run more than one transition in a
# single response" — and used to say how it was enforced: "the hook refuses a
# write that appends two". That covers one of the two ways to break it.
# Measured: three separate writes, one entry each, 37 seconds apart, on a
# single "avanti". Each one legal on its own.

def _turn_passes(repo_dir):
    subprocess.run([sys.executable, os.path.join(ROOT, "ddw/scripts/hook-gate.py"),
                    "--mode", "turn", "--state", os.path.join(repo_dir, ".ddw-state.json"),
                    "--graph", _GRAPH_PATH, "--repo", repo_dir],
                   input="{}", capture_output=True, text=True)


def _arrow(repo_dir, *args):
    """The arrow via the sanctioned path, with the pre-write guard watching."""
    p = os.path.join(repo_dir, ".ddw-state.json")
    args = list(args)
    if "--ticket" in args and "--title" not in args:
        args += ["--title", "un ticket de prueba"]   # see `_step`
    emitted = subprocess.run([sys.executable, _TRANSITION_PY, "--state", p,
                              "--graph", _GRAPH_PATH, *args],
                             capture_output=True, text=True, cwd=repo_dir)
    assert emitted.returncode == 0, emitted.stderr[-300:]
    vt = _load("vt", "ddw/scripts/validate-transition.py")
    old = json.load(open(p, encoding="utf-8"))
    new = json.loads(emitted.stdout)
    reason = vt.second_arrow_in_one_turn(repo_dir, old, new)
    if reason is None:
        open(p, "w", encoding="utf-8").write(emitted.stdout)
        vt._record_arrow(repo_dir)
    return reason


def _repo_con_estado(tmp_path, autonomy="assisted"):
    d = str(tmp_path)
    os.makedirs(os.path.join(d, ".ddw-sessions"), exist_ok=True)
    open(os.path.join(d, ".ddw-state.json"), "w", encoding="utf-8").write(
        json.dumps(state(autonomy=autonomy) if False else
                   {"phase": "IDLE", "tier": None, "ticket": None, "autonomy": autonomy,
                    "gates": {}, "history": []}))
    return d


def test_dos_flechas_en_un_turno_son_rechazadas(tmp_path):
    d = _repo_con_estado(tmp_path)
    _turn_passes(d)
    assert _arrow(d, "--to", "CLASSIFY", "--tier", "FEATURE", "--ticket", "F-1",
                  "--autonomy", "assisted", "--action", "clasificar") is None
    reason = _arrow(d, "--to", "DEFINE", "--tier", "FEATURE", "--ticket", "F-1",
                    "--action", "definir")
    assert reason and "already landed in this turn" in reason, \
        "the second transition of the same turn passed: %r" % reason


def test_despues_de_que_hable_el_usuario_la_siguiente_flecha_pasa(tmp_path):
    d = _repo_con_estado(tmp_path)
    _turn_passes(d)
    _arrow(d, "--to", "CLASSIFY", "--tier", "FEATURE", "--ticket", "F-1",
           "--autonomy", "assisted", "--action", "clasificar")
    _turn_passes(d)
    assert _arrow(d, "--to", "DEFINE", "--tier", "FEATURE", "--ticket", "F-1",
                  "--action", "definir") is None, "the approved arrow was refused anyway"


def test_en_minimal_las_flechas_no_esperan(tmp_path):
    """What that mode removes is the confirmation, and it is opted into with
    the cost said out loud."""
    d = _repo_con_estado(tmp_path, autonomy="minimal")
    _turn_passes(d)
    _arrow(d, "--to", "CLASSIFY", "--tier", "FEATURE", "--ticket", "F-1",
           "--autonomy", "minimal", "--action", "clasificar")
    assert _arrow(d, "--to", "DEFINE", "--tier", "FEATURE", "--ticket", "F-1",
                  "--action", "definir") is None, "minimal got caught by the rule"


def test_sin_señal_de_turno_no_se_refusa_nada(tmp_path):
    """A guard that fires because a counter is missing refuses every write in
    every tool that does not write one."""
    d = _repo_con_estado(tmp_path)
    assert _arrow(d, "--to", "CLASSIFY", "--tier", "FEATURE", "--ticket", "F-1",
                  "--autonomy", "assisted", "--action", "c") is None
    assert _arrow(d, "--to", "DEFINE", "--tier", "FEATURE", "--ticket", "F-1",
                  "--action", "d") is None


def test_el_guard_de_pre_write_es_el_que_refusa_la_segunda_flecha(tmp_path):
    """Via the path that actually runs. The test above calls the function; if
    `decide_pre` stops consulting it, that test stays green and the hole comes back."""
    d = _repo_con_estado(tmp_path)
    _turn_passes(d)
    p = os.path.join(d, ".ddw-state.json")

    def write(*args):
        args = list(args)
        if "--ticket" in args and "--title" not in args:
            args += ["--title", "un ticket de prueba"]   # see `_step`
        emitted = subprocess.run([sys.executable, _TRANSITION_PY, "--state", p,
                                  "--graph", _GRAPH_PATH, *args],
                                 capture_output=True, text=True, cwd=d)
        assert emitted.returncode == 0, emitted.stderr[-300:]
        reason = vt.decide_pre(p, _GRAPH_PATH, "Write",
                               {"file_path": p, "content": emitted.stdout}, [p], repo=d)
        if reason is None:
            open(p, "w", encoding="utf-8").write(emitted.stdout)
        return reason

    assert write("--to", "CLASSIFY", "--tier", "FEATURE", "--ticket", "F-1",
                 "--autonomy", "assisted", "--action", "c") is None
    reason = write("--to", "DEFINE", "--tier", "FEATURE", "--ticket", "F-1", "--action", "d")
    assert reason and "already landed in this turn" in reason, \
        "the guard let the turn's second arrow through: %r" % reason


# ── A split's child opens directly in the phase the split paused ─────────────
#
# CLASSIFY exists to produce tier, ticket and autonomy — and for a split's
# child all three already exist: the parent's run produced them and the user
# approved the split that named the child. Sending it through CLASSIFY
# re-decided nothing and charged a turn that decided nothing. The `split:`
# arrow jumps the graph like a resume does, so every part of the proof has to
# be on the record.

def _split_history():
    return [
        entry("IDLE", "CLASSIFY", "clasificar"),
        entry("CLASSIFY", "DEFINE", "clasificado FEATURE", tier="FEATURE", ticket="F-1"),
        entry("DEFINE", "IDLE", "pause: split into F-1a/b", tier="FEATURE", ticket="F-1"),
    ]


def _open_child(dst="DEFINE", ticket="F-1a", tier="FEATURE", gates=None):
    hist = _split_history()
    old = state(history=list(hist))
    new = state(phase=dst, tier=tier, ticket=ticket, gates=gates,
                history=hist + [entry("IDLE", dst, "split: abrir %s" % ticket,
                                      tier=tier, ticket=ticket)])
    return old, new


def test_el_hijo_de_un_split_abre_directo_donde_el_split_pauso():
    old, new = _open_child()
    assert refusal(old, new) is None


def test_split_sin_pause_de_split_es_una_llave_maestra_refusada():
    old = state()
    new = state(phase="DEFINE", tier="FEATURE", ticket="F-1a",
                history=[entry("IDLE", "DEFINE", "split: abrir F-1a",
                               tier="FEATURE", ticket="F-1a")])
    assert refusal(old, new), "split: with no parent pause opened DEFINE out of nowhere"


def test_el_hijo_abre_en_la_fase_del_pause_y_en_ninguna_otra():
    old, new = _open_child(dst="PLAN")
    assert refusal(old, new), "the child chose a phase: it opened in PLAN a split paused in DEFINE"


def test_un_ticket_que_no_deriva_del_padre_no_es_hijo():
    old, new = _open_child(ticket="OTRA-9")
    assert refusal(old, new), "an unrelated ticket passed as the split's child"


def test_el_hijo_no_hereda_gates():
    # Two layers catch it — `_check_gate_owner` first (IDLE earns nothing) and
    # the split branch after. The test pins the VERDICT, not which layer speaks.
    old, new = _open_child(gates={"define": True})
    why = refusal(old, new)
    assert why and "gate" in why.lower(), \
        "the child opened with gates it never earned: %r" % why


def test_el_tier_del_hijo_es_el_del_pause():
    old, new = _open_child(tier="FIX")
    assert refusal(old, new), "a split re-classified the work while opening the child"


def test_un_split_que_el_journal_nunca_vio_es_refusado(tmp_path):
    old, new = _open_child()
    sp = tmp_path / ".ddw-state.json"
    sp.write_text("{}", encoding="utf-8")
    (tmp_path / ".ddw-journal.jsonl").write_text(
        json.dumps(entry("IDLE", "CLASSIFY", "c")) + "\n", encoding="utf-8")
    why = refusal(old, new, state_path=str(sp))
    assert why and "journal" in why.lower(), \
        "a shell-forged pause vouched for the opening: %r" % why


def test_el_journal_que_vio_el_split_lo_avala(tmp_path):
    old, new = _open_child()
    sp = tmp_path / ".ddw-state.json"
    sp.write_text("{}", encoding="utf-8")
    (tmp_path / ".ddw-journal.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _split_history()) + "\n", encoding="utf-8")
    assert refusal(old, new, state_path=str(sp)) is None


def test_un_pause_comun_del_padre_no_autoriza_un_split():
    """The proof is THE SPLIT'S pause, not any pause: a parent paused for
    another reason has no children to open."""
    hist = [
        entry("IDLE", "CLASSIFY", "clasificar"),
        entry("CLASSIFY", "DEFINE", "clasificado FEATURE", tier="FEATURE", ticket="F-1"),
        entry("DEFINE", "IDLE", "pause: lo retomo mañana", tier="FEATURE", ticket="F-1"),
    ]
    old = state(history=list(hist))
    new = state(phase="DEFINE", tier="FEATURE", ticket="F-1a",
                history=hist + [entry("IDLE", "DEFINE", "split: abrir F-1a",
                                      tier="FEATURE", ticket="F-1a")])
    assert refusal(old, new), "an ordinary pause of the parent vouched for opening a split child"


# ── The pr gate resolves by receipt, not by the branch of the moment ─────────
#
# The closeout's happy path DESTROYS the branch (merge + delete), and the
# check used to resolve the PR by the current branch: run 4 ended with the
# model recreating the deleted branch to satisfy the gate — a gate that
# teaches how to go around it. The receipt names the PR by number; the forge
# is still the one that says what state it is in.

def _gh_stub(tmp_path):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    gh = b / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *view*) out="${GH_VIEW_OUT}"; [ -z "$out" ] && out="{}"\n'
        '          echo "$out"; exit "${GH_VIEW_RC:-0}";;\n'
        '  *)      echo "${GH_LIST_OUT:-[]}"; exit "${GH_LIST_RC:-0}";;\n'
        "esac\n", encoding="utf-8")
    gh.chmod(0o755)
    return str(b)


def _pr_repo(tmp_path):
    r = str(tmp_path / "prrepo")
    os.makedirs(r)
    subprocess.run(["git", "-C", r, "init", "-q"], check=True)
    subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                    "-c", "commit.gpgsign=false", "commit", "-q",
                    "--allow-empty", "-m", "base"], check=True)
    subprocess.run(["git", "-C", r, "remote", "add", "origin",
                    "https://github.com/example/example.git"], check=True)
    subprocess.run(["git", "-C", r, "checkout", "-q", "-b", "feat/T-1-x"], check=True)
    return r


def _ask_pr(repo, binpath, **stub_env):
    old = os.environ.copy()
    os.environ["PATH"] = binpath + os.pathsep + os.environ["PATH"]
    for k, v in stub_env.items():
        os.environ[k] = v
    try:
        return vt._pr_evidence_missing(repo, {"ticket": "T-1"})
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_el_gate_pr_sobrevive_al_merge_que_borra_la_rama(tmp_path):
    repo, binpath = _pr_repo(tmp_path), _gh_stub(tmp_path)
    # It is earned on the ticket's branch: the receipt gets written.
    assert _ask_pr(repo, binpath, GH_LIST_OUT='[{"number":7,"state":"OPEN"}]') is None
    assert os.path.exists(os.path.join(repo, ".ddw-sessions", "pr-T-1.json"))
    # The closeout's happy path: merge, branch deleted, standing on the base.
    subprocess.run(["git", "-C", repo, "checkout", "-q", "-b", "landing"], check=True)
    subprocess.run(["git", "-C", repo, "branch", "-q", "-D", "feat/T-1-x"], check=True)
    why = _ask_pr(repo, binpath, GH_LIST_OUT="[]",
                  GH_VIEW_OUT='{"state":"MERGED","headRefName":"feat/T-1-x"}')
    assert why is None, "the gate went blind after the merge again: %r" % why


def test_un_receipt_que_nombra_el_pr_de_otro_ticket_es_refusado(tmp_path):
    repo, binpath = _pr_repo(tmp_path), _gh_stub(tmp_path)
    os.makedirs(os.path.join(repo, ".ddw-sessions"), exist_ok=True)
    with open(os.path.join(repo, ".ddw-sessions", "pr-T-1.json"), "w") as fh:
        json.dump({"number": 99, "head": "feat/OTRO-9-x"}, fh)
    why = _ask_pr(repo, binpath,
                  GH_VIEW_OUT='{"state":"MERGED","headRefName":"feat/OTRO-9-x"}')
    assert why and "T-1" in why, "another ticket's PR passed as evidence: %r" % why


def test_un_pr_cerrado_sin_mergear_no_sostiene_el_gate(tmp_path):
    repo, binpath = _pr_repo(tmp_path), _gh_stub(tmp_path)
    os.makedirs(os.path.join(repo, ".ddw-sessions"), exist_ok=True)
    with open(os.path.join(repo, ".ddw-sessions", "pr-T-1.json"), "w") as fh:
        json.dump({"number": 7, "head": "feat/T-1-x"}, fh)
    why = _ask_pr(repo, binpath,
                  GH_VIEW_OUT='{"state":"CLOSED","headRefName":"feat/T-1-x"}')
    assert why and "CLOSED" in why


def test_un_gh_roto_con_receipt_sigue_sin_ser_un_veredicto(tmp_path):
    repo, binpath = _pr_repo(tmp_path), _gh_stub(tmp_path)
    os.makedirs(os.path.join(repo, ".ddw-sessions"), exist_ok=True)
    with open(os.path.join(repo, ".ddw-sessions", "pr-T-1.json"), "w") as fh:
        json.dump({"number": 7, "head": "feat/T-1-x"}, fh)
    assert _ask_pr(repo, binpath, GH_VIEW_RC="1", GH_LIST_RC="1") is None, \
        "a fallen-over gh was read as a verdict"
