#!/usr/bin/env python3
"""DDW FSM transition validation.

Two modes (same graph, same `validate()`):

- `--mode pre` (PreToolUse, default): reads the event from stdin; if the target
  is .ddw-state.json, validates disk→new (reconstructed from tool_input) BEFORE
  the write lands. Covers Edit|Write|NotebookEdit (the hook's matcher).
- `--mode post` (PostToolUse): ignores the event; revalidates the state ON DISK
  as a complete chain from IDLE (the `history` IS the chain, no external
  reference needed) after any tool — including Bash/jq, which the PreToolUse
  matcher never sees. Illegal → exit 2 (does not undo, it stops). Tool-agnostic,
  path-agnostic, stateless.

exit 0 = allow, exit 2 = block (with the reason on stderr). Validation is
anchored on the history entries that were APPENDED, not on the phase on disk:
the model does not always persist an intermediate CLASSIFY.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

# Verbs that mean a tool is writing. Matched as substrings because every tool
# spells it differently — `Write`, `write_file`, `create_file`, `apply_patch`,
# `str_replace_editor`, `NotebookEdit`. A tool whose name says none of these and
# whose payload carries no content is reading, and a read is judged by nobody.
READ_VERBS = ("read", "view", "list", "ls", "cat", "search", "grep", "glob",
              "find", "show", "open", "get", "fetch", "head", "tail", "stat")

# The only phase constants in code (everything else comes from the graph):
IDLE = "IDLE"
# Where the path of the file being written hides, across every tool's envelope.
PATH_KEYS = ("file_path", "notebook_path", "path", "filePath", "file", "absolute_path")
CLASSIFY = "CLASSIFY"

_ISO8601 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


class Block(Exception):
    """FSM violation → exit 2 with this message."""


def _idle_template():
    return {"tier": None, "phase": IDLE, "autonomy": None, "gates": {}, "history": []}


def _load_disk_state(path):
    """Previous state from disk. Missing or unreadable → IDLE template."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        state = json.loads(text)
    except (OSError, ValueError):
        return "", _idle_template()
    if not isinstance(state, dict):
        return "", _idle_template()
    return text, state


def _reconstruct_new_text(tool_name, tool_input, old_text):
    """The full state text the tool is trying to write.

    Write → content. Edit → apply old_string→new_string over old_text.
    Any other tool (NotebookEdit, etc.) against the state → fail closed.
    """
    if tool_name == "Write":
        content = tool_input.get("content")
        if not isinstance(content, str):
            raise Block(
                "Write to the state with no reconstructable content — this tool's envelope does "
                "not carry the final file. Do not fall back to the shell: run "
                "`.ddw/scripts/transition.py --to <phase> --action \"…\" --write`, which "
                "validates and writes the state atomically itself."
            )
        return content
    if tool_name == "Edit":
        old_s = tool_input.get("old_string")
        new_s = tool_input.get("new_string")
        if old_s is None or new_s is None:
            raise Block("Edit to the state with no old_string/new_string")
        n = old_text.count(old_s)
        if n == 0:
            raise Block("Edit to the state: old_string not found (cannot reconstruct)")
        if n > 1 and not bool(tool_input.get("replace_all", False)):
            raise Block("Edit to the state: ambiguous old_string (multiple matches) without replace_all")
        if bool(tool_input.get("replace_all", False)):
            return old_text.replace(old_s, new_s)
        return old_text.replace(old_s, new_s, 1)
    raise Block(f"tool {tool_name!r} is not supported for the state file; use Write")


def _parse_new_state(new_text):
    try:
        state = json.loads(new_text)
    except ValueError as exc:
        raise Block(f"the new state does not parse as JSON: {exc}")
    if not isinstance(state, dict):
        raise Block("the new state is not a JSON object")
    return state


def _check_append_only(old_state, new_state):
    old_h = old_state.get("history", []) or []
    new_h = new_state.get("history", []) or []
    if not isinstance(old_h, list) or not isinstance(new_h, list):
        raise Block("history must be a list")
    if len(new_h) < len(old_h):
        raise Block(
            "history is not append-only: it was truncated (previous entries "
            f"cannot be deleted; old={len(old_h)} entries, new={len(new_h)})"
        )
    if new_h[: len(old_h)] != old_h:
        raise Block(
            f"history is not append-only: the prefix of the first {len(old_h)} "
            "entries does not match the previous state. Did you prepend, or "
            "reorder/mutate an entry? New entries ALWAYS go at the END, leaving "
            "the previous ones untouched."
        )
    return old_h, new_h


def _effective_edges(graph, tier):
    """The edges that apply to `tier`: the common ones, plus its own, plus any
    it inherits through `extends`.

    `extends` exists so two tiers with the same pipeline shape are declared
    once. Without it, FIX and FEATURE were seven identical edges copy-pasted,
    and editing one while forgetting the other made them diverge silently.
    A tier's own edges override whatever it inherits.
    """
    tiers = graph.get("tiers", {})
    chain, seen, cur = [], set(), tier
    while cur is not None and cur in tiers and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = tiers[cur].get("extends")
    if cur is not None and cur not in tiers and cur is not tier:
        raise Block(f"the graph's tier {chain[-1]!r} extends {cur!r}, which does not exist")

    edges = dict(graph.get("common", {}))
    for name in reversed(chain):          # ancestors first, so the tier wins
        edges.update({k: v for k, v in tiers[name].items() if k != "extends"})
    return edges


def _is_resume(entry):
    """Does this entry declare itself as resuming a paused ticket?

    Pause is advertised as a first-class exit — walk away from any phase, owing
    nothing. It was a one-way door: the graph's only edge out of IDLE is
    IDLE->CLASSIFY, so the ticket was written to .ddw-paused/ and then
    unreachable through any sanctioned path. Same anchored match as the
    walkaway markers, for the same reason.
    """
    action = entry.get("action")
    if not isinstance(action, str):
        return False
    return action.strip().lower().split(":", 1)[0].strip() == "resume"


def _paused_at(history, upto):
    """The phase the last pause left, or None if the ticket was not paused.

    Looks at the entry immediately before this run: pausing is the last thing
    that happened to the previous ticket, and the phase it paused FROM is the
    only phase a resume may re-enter.
    """
    prior = [e for e in history[:upto] if isinstance(e, dict)]
    if not prior:
        return None
    last = prior[-1]
    if last.get("to") != IDLE or not _is_walkaway(last):
        return None
    action = last.get("action", "")
    if not isinstance(action, str):
        return None
    if action.strip().lower().split(":", 1)[0].strip() not in ("pause", "paused"):
        return None                       # abandoned, not paused: no way back
    return last.get("from")


def _resume_allowed(entry, history, upto):
    """Is this a real resume, or the word `resume` used as a skeleton key?

    Listing the destination in `resume_edges` is necessary and nowhere near
    sufficient. Without proof that a pause happened, and from this very phase,
    `resume:` was an edge from IDLE to any phase at all, carrying whatever gates
    the same write cared to declare — the entire pipeline in one write, which is
    the exact hole every other check here exists to close.
    """
    dst = entry.get("to")
    paused_at = _paused_at(history, upto)
    if paused_at is None:
        raise Block(
            "this history has no paused ticket to resume: the entry before it does not declare "
            'a pause (action "pause: <reason>") ending at IDLE. `resume` returns to work that '
            "was set aside; it does not start work in the middle."
        )
    if paused_at != dst:
        raise Block(
            f"the ticket was paused at {paused_at}, so it resumes at {paused_at} — not at {dst}. "
            "Resuming is picking the work back up where it was left, not choosing a phase."
        )
    return True


def _is_walkaway(entry):
    """Does this entry declare itself as leaving the ticket, rather than closing it?

    Two ways out of a ticket, and they owe different things. A **closeout** ships
    the work and owes its gates — a commit, a PR. **Walking away** owes nothing,
    because the whole point is that this work is not going to ship: an abandon
    (the classification was wrong, the idea did not survive contact) or a pause
    (set it aside, come back later).

    It has to be DECLARED, and the match is anchored: bare `startswith` let
    "abandonware cleanup" read as an abandon. The word is the marker, followed by
    nothing or by a colon and the reason.
    """
    action = entry.get("action")
    if not isinstance(action, str):
        return False
    first = action.strip().lower().split(":", 1)[0].strip()
    return first in ("abandon", "abandoned", "pause", "paused")


def _walkaway_blocked(graph, phase):
    """Phases you are not allowed to walk away from. There is exactly one so far
    — RELEASE, where nothing is left to decide, only steps to finish — and it
    lives in the graph rather than in this file so a project can say otherwise."""
    return phase in set(graph.get("no_walkaway", []))


def _check_entry_shape(entry):
    if not isinstance(entry, dict) or "from" not in entry or "to" not in entry:
        raise Block("history entry with no from/to")
    ts = entry.get("timestamp", "")
    if not isinstance(ts, str) or not _ISO8601.match(ts):
        raise Block(f"non-ISO-8601 timestamp in history: {ts!r}")


def _check_idle_invariant(new_state):
    """An idle state carries no ticket. This is a property of the STATE.

    It used to be checked only on the edge that landed on IDLE, so the very next
    write — one that appends no history entry and therefore returned early —
    could re-plant a tier and a full set of gates onto the idle state. The
    following ticket then walked the whole pipeline having earned none of them.
    An invariant about what IDLE means has to hold every time IDLE is written,
    not only on the way in.
    """
    if new_state.get("phase", IDLE) != IDLE:
        return
    if new_state.get("tier") is not None:
        raise Block(
            f"at IDLE `tier` must be null (it is {new_state.get('tier')!r}). Reaching IDLE ends "
            "the ticket; otherwise the next one inherits this one's tier."
        )
    gates = new_state.get("gates") or {}
    if isinstance(gates, dict) and gates:
        raise Block(
            "at IDLE `gates` must be empty (it still has: "
            f"{', '.join(sorted(gates))}). Reaching IDLE ends the ticket; otherwise the next "
            "one starts with gates it never earned."
        )
    if new_state.get("autonomy") is not None:
        raise Block(
            f"at IDLE `autonomy` must be null (it is {new_state.get('autonomy')!r}). It is chosen "
            "when a request is classified and it ends with the ticket — otherwise the next one "
            "inherits a decision to stop asking that nobody made for it."
        )


AUTONOMY_VALUES = ("assisted", "minimal")


def _check_autonomy(old_state, new_state, appended):
    """`autonomy` is chosen in CLASSIFY, with the user watching, and holds.

    This is the field that decides whether a person is asked before each arrow,
    so it is the one field a model has an incentive to set for itself — and it
    shipped with none of the protection `tier` has. Measured on the version that
    introduced it: a write flipping `assisted` to `minimal` mid-run was accepted,
    `"banana"` was accepted, and `minimal` survived the reset to IDLE into the
    next ticket. A gate the model can open by writing a word is not a gate, and
    "nobody has to approve this any more" is the last word it should be able to
    write about itself.

    Absent or null reads as `assisted`: a state written before the field existed
    did not opt into anything, and refusing it would break every repository that
    upgrades.
    """
    raw_new = new_state.get("autonomy")
    if raw_new is not None and raw_new not in AUTONOMY_VALUES:
        raise Block(
            f"`autonomy` must be null, \"assisted\" or \"minimal\", got {raw_new!r}. An "
            "unrecognised value is read as 'not assisted' by anything that tests for the string, "
            "which is the failure mode of every unvalidated enum."
        )
    old_auto = old_state.get("autonomy")
    if old_auto == raw_new:
        return
    # ENTERING classify counts too, and that is the one this check first got
    # wrong: the mode is chosen while the request is being classified, and the
    # write that materialises the classification is IDLE→CLASSIFY — where the
    # old phase is still IDLE and the appended edge comes `from` IDLE. Refusing
    # it made the field unsettable by the only path that sets it. Found by
    # driving the helper end to end, not by the three adversarial cases, which
    # all passed.
    in_classify = old_state.get("phase") == CLASSIFY
    entering_classify = new_state.get("phase") == CLASSIFY
    leaving_classify = bool(appended) and appended[0].get("from") == CLASSIFY
    reaching_idle = new_state.get("phase", IDLE) == IDLE
    if in_classify or entering_classify or leaving_classify or reaching_idle:
        return
    raise Block(
        f"`autonomy` changed {old_auto!r}→{raw_new!r} outside CLASSIFY. How much of this run "
        "waits for a human is decided once, when the request is classified and the user is "
        "looking at the box. To change it, walk away from this ticket "
        '(action "abandon: …") and reclassify.'
    )


def _check_tier(old_state, new_state, appended):
    """The tier is chosen in CLASSIFY and holds for the whole ticket.

    Two holes lived here, and both were about WHEN this ran rather than what it
    checked. It ran after the early return for writes that append no history
    entry, so a write changing only `tier` skipped it entirely — and that is all
    it takes: flip a FEATURE to QUICK-FIX in one silent write, then walk
    DEFINE→CODE→RELEASE, skipping PLAN and VERIFY and never earning `spec`,
    `threat` or `verify`. Post mode does not notice, because it replays the run
    against the FINAL tier, under which that path is perfectly legal.

    And the type check ran on the RESOLVED tier — `new or old` — so a falsy but
    non-null value (`""`, `[]`, `0`) passed by falling back to the previous
    tier, landed on disk, and made `old_tier` falsy for the next write, which
    disarmed the immutability check itself.
    """
    raw_new = new_state.get("tier")
    if raw_new is not None and not (isinstance(raw_new, str) and raw_new):
        raise Block(
            f"`tier` must be a non-empty string or null, got {raw_new!r}. A falsy tier reads "
            "as 'unchanged' everywhere it is consulted, which is indistinguishable from an "
            "attempt to disable the check."
        )
    old_tier = old_state.get("tier")
    new_tier = raw_new if raw_new is not None else old_tier
    if not old_tier or old_tier == new_tier:
        return
    # Only CLASSIFY assigns a tier, so the only legal change is the one that
    # leaves CLASSIFY — or a reset to IDLE, which clears it.
    # Being IN classify counts, not only leaving it. The check looked at the
    # first appended edge, so an in-phase correction while still in CLASSIFY was
    # refused with "the tier changed outside CLASSIFY" — while in CLASSIFY.
    in_classify = old_state.get("phase") == CLASSIFY
    leaving_classify = bool(appended) and appended[0].get("from") == CLASSIFY
    reaching_idle = new_state.get("phase", IDLE) == IDLE
    if in_classify or leaving_classify or reaching_idle:
        return
    raise Block(
        f"the tier changed {old_tier!r}→{new_tier!r} outside CLASSIFY. The tier is set when the "
        "request is classified and holds for the whole ticket: to change it, walk away from this "
        'one (action "abandon: …") and reclassify. Letting it change mid-run turns the graph '
        "into a menu — every tier's shortcut becomes available to every ticket."
    )


def _check_ticket_continuity(old_state, new_state):
    """One run belongs to one ticket. Changing it mid-run is a new run.

    This is the rule post mode has always enforced — it replays a run against
    the header it ends with, so an entry stamped with a ticket the header no
    longer names is condemned. Pre mode did not enforce it: it judges one write,
    and at that moment the old header still carried the parent, so a write that
    moved `ticket` from FEAT-001 to FEAT-001a passed.

    The two disagreeing is worse than either rule alone. The write landed —
    exit 0, no warning — and post then declared the file on disk illegal, on
    every subsequent tool call, forever. Nothing could clear it: the header
    could not go back without a history entry, and the entry it needed
    (RELEASE→DEFINE, or its equivalent) is not in the graph. A model told to fix
    it tried eight times, and the only thing that ever worked was deleting the
    file — which took the history with it.

    So the refusal moves to where it can still be acted on. A split does have a
    sanctioned path, and it is the one the graph already has: walk away from the
    parent (`pause: …` → IDLE), then start the sub-ticket through
    IDLE → CLASSIFY. Both edges exist; nothing has to be invented.
    """
    old_t, new_t = old_state.get("ticket"), new_state.get("ticket")
    if not (isinstance(old_t, str) and old_t) or old_t == new_t:
        return
    # Letting go of the ticket is how a run ends, and the IDLE invariant already
    # says what that write has to look like.
    if new_t is None or new_state.get("phase", IDLE) == IDLE:
        return
    raise Block(
        f"the ticket changed {old_t!r}→{new_t!r} while the run is still open (phase "
        f"{new_state.get('phase', IDLE)}). A run belongs to one ticket: its history entries are "
        f"stamped {old_t!r}, and a header naming {new_t!r} makes every one of them unattributable "
        "— which post mode then refuses on every later write, with no way back.\n"
        f"To start {new_t!r}: first leave {old_t!r} with a history entry whose action is "
        f'"pause: split into sub-tickets" (or "abandon: …") ending at IDLE, then take '
        "IDLE→CLASSIFY for the new ticket. Both edges are in the graph."
    )


def _check_entry_ticket(old_state, new_state, appended):
    """A history entry that names a ticket must name THIS one.

    `ticket` on the entry is what makes the history answer "what happened to
    which ticket" — and, downstream, what lets the session boot work out which
    sub-tickets of a split PRD still have no closeout. Derived facts are only
    worth as much as the record they come from: an entry free to claim any
    ticket would let a closeout be attributed to work that never ran, and the
    boot would stop mentioning it.

    A closeout resets `ticket` to null, so the entry belongs to the ticket as it
    was BEFORE the write. Either side is accepted; anything else is not.
    Entries with no `ticket` are legal — histories written before this existed
    stay valid, and the boot treats what it cannot attribute as still pending.

    When BOTH sides name no ticket, this is post mode replaying a paused or
    closed run: the prior it rebuilds is IDLE and the header the run ends with
    is IDLE too. The entries in between legitimately carry the run's ticket —
    that is what makes the history attributable at all — so the rule there is
    consistency, not membership: one run, one ticket. Judging membership
    against the empty set condemned every stamped entry of every paused split,
    live, the first time a drop-in walked one: the pre-write gate accepted the
    pause (rightly, on the old side) and every later tool call was refused.
    """
    allowed = {t for t in (old_state.get("ticket"), new_state.get("ticket"))
               if isinstance(t, str) and t}
    stamped_run = set()
    for entry in appended:
        if not isinstance(entry, dict) or "ticket" not in entry:
            continue
        stamped = entry.get("ticket")
        if stamped is None:
            continue
        if not isinstance(stamped, str) or not stamped:
            raise Block(
                f"a history entry stamps `ticket` as {stamped!r}. It must be the ticket string, "
                "or absent — a ticket nothing can match makes the entry unattributable."
            )
        stamped_run.add(stamped)
        if allowed and stamped not in allowed:
            raise Block(
                f"a history entry stamps ticket {stamped!r}, but this write concerns "
                f"{sorted(allowed)}. The entry records what happened to the ticket "
                "in hand; letting it name another one lets a closeout be credited to work that "
                "never ran."
            )
    if not allowed and len(stamped_run) > 1:
        raise Block(
            f"history entries within one run stamp different tickets {sorted(stamped_run)}. A run "
            "belongs to one ticket; entries free to disagree let a closeout be credited to work "
            "that never ran."
        )


def validate(old_state, new_state, graph, tool_name=None, max_appended=1,
             gates_scope="all"):
    old_h, new_h = _check_append_only(old_state, new_state)
    appended = new_h[len(old_h):]

    # Before any early return: a write that appends nothing can still change the
    # tier, and that was enough to walk another tier's shortcut.
    _check_tier(old_state, new_state, appended)
    _check_autonomy(old_state, new_state, appended)
    _check_ticket_continuity(old_state, new_state)
    _check_entry_ticket(old_state, new_state, appended)
    _check_idle_invariant(new_state)

    old_phase = old_state.get("phase", IDLE)
    new_phase = new_state.get("phase", IDLE)

    # A single write declares a single transition. Without this, one Write could
    # append the entire pipeline — IDLE through RELEASE, every gate asserted at
    # the end — and pass: each gate is present, so nothing is "missing", and the
    # sequencing that is the entire point of the machine evaporates. The
    # sanctioned helper never emits more than one edge; post mode replays a whole
    # run and passes no cap.
    if max_appended is not None and len(appended) > max_appended:
        raise Block(
            f"a single write may declare at most {max_appended} transition(s); this one appends "
            f"{len(appended)}. Move one edge at a time — the order is the guarantee."
        )

    # No transition: an in-phase update. Only valid if the phase did not change.
    if not appended:
        if new_phase != old_phase:
            core = (
                f"the phase changed {old_phase}→{new_phase} but you did not add the matching "
                "history entry. In the SAME write that changes `phase`, append a "
                "{timestamp, from, to, action} entry at the END of the `history` array."
            )
            if tool_name == "Edit":
                hint = (
                    " An Edit cannot change the header (at the top) and append to history "
                    "(at the end) in a single operation: use a Write of the whole file "
                    "(header + history together), not an Edit."
                )
            elif tool_name == "Write":
                hint = (
                    " Your Write changed `phase` but the `history` array is missing the new "
                    "entry — add it at the end and rewrite the file. (The helper "
                    ".ddw/scripts/transition.py builds the correct JSON for you.)"
                )
            else:
                hint = ""
            raise Block(core + hint)
        return  # in-phase update (gates, block, discovery): allowed

    # With a transition: validate the chain of appended entries.
    for entry in appended:
        _check_entry_shape(entry)

    # Internal contiguity.
    for a, b in zip(appended, appended[1:]):
        if a["to"] != b["from"]:
            raise Block(
                f"history is not contiguous: {a['from']}→{a['to']} followed by "
                f"{b['from']}→{b['to']}"
            )

    # Connection to the previous state (with IDLE↔CLASSIFY leniency).
    first_from = appended[0]["from"]
    if first_from != old_phase and not (old_phase == IDLE and first_from == CLASSIFY) \
            and not (old_phase == IDLE and first_from == IDLE):
        raise Block(
            f"the first transition starts at {first_from} but the previous state "
            f"is at {old_phase}"
        )

    # Phase head: the last transition must end at new.phase.
    if appended[-1]["to"] != new_phase:
        raise Block(
            f"the last transition ends at {appended[-1]['to']} but phase={new_phase}"
        )

    # Every edge: graph + gates.
    #
    # A transition to IDLE wipes `tier` and `gates` — that is what closing a
    # ticket means. So for those edges we have to look at the state as it was
    # BEFORE the reset, or the closeout edge could never be found and its gates
    # would read as empty. The fallback is deliberately narrow: it applies only
    # when the destination is IDLE. Anywhere else, a gate cleared by a
    # corrective loop (VERIFY→CODE drops tests/sast) must NOT count as met.
    tier = new_state.get("tier") or old_state.get("tier")
    if not isinstance(tier, (str, type(None))):
        raise Block(f"`tier` must be a string or null, got {type(tier).__name__}")
    gates = new_state.get("gates", {}) or {}
    gates_before = old_state.get("gates", {}) or {}
    for label, val in (("gates", gates), ("the previous gates", gates_before)):
        if not isinstance(val, dict):
            raise Block(f"{label} must be an object, got {type(val).__name__}")
    edges = _effective_edges(graph, tier)

    # (The tier lock itself ran here once. It moved to _check_tier(), above every
    # early return, because a write that appends no history entry can change the
    # tier too — and that was the whole exploit.)

    for idx, entry in enumerate(appended):
        src, dst = entry["from"], entry["to"]
        key = f"{src}->{dst}"
        # "none" validates the PATH only. It exists for one case: replaying a
        # ticket that already closed, whose gates the closeout itself erased.
        check_gates = gates_scope == "all" or (
            gates_scope == "last" and idx == len(appended) - 1)
        if src == dst:
            raise Block(f"a transition must go somewhere: {key}")
        if src == IDLE and dst != CLASSIFY and _is_resume(entry):
            # Coming back to a ticket that was paused. It owes no gates — pausing
            # owed none either, and the gates it had earned come back with it.
            # But it has to BE a resume: proven by a pause, from this phase.
            _resume_allowed(entry, old_h + appended, len(old_h) + idx)
            continue
        if dst == IDLE and _is_walkaway(entry):
            # Walking away — abandon or pause. Always allowed, from anywhere the
            # graph does not forbid it, gated by nothing: the work is not going
            # to ship, so there is nothing to demand of it. It must SAY so, since
            # a closeout takes the same edge and does owe its gates.
            if _walkaway_blocked(graph, src):
                raise Block(
                    f"you cannot walk away from {src}: at this point nothing is left to decide, "
                    "only steps to finish. Complete the closeout."
                )
            continue
        if key not in edges:
            hint = ""
            if dst == IDLE and not _walkaway_blocked(graph, src):
                hint = (
                    ' To leave this ticket without closing it out, set the entry\'s "action" to '
                    '"abandon: <reason>" (dropped for good) or "pause: <reason>" (set aside).'
                )
            raise Block(f"transition {key} is not in the graph for tier {tier!r}.{hint}")
        edge_cfg = edges[key]
        if not isinstance(edge_cfg, dict):
            raise Block(f"malformed graph: the value of {key!r} is not an object")
        gates_required = edge_cfg.get("gates", [])
        if not isinstance(gates_required, list):
            raise Block(f"malformed graph: the gates of {key!r} are not a list")
        if check_gates:
            available = dict(gates_before) if dst == IDLE else {}
            available.update(gates)
            for gate in gates_required:
                if available.get(gate) is not True:
                    raise Block(f"gate {gate!r} required for {key} is not true")

    # Landing on IDLE means the ticket is over: the tier and the gates go with
    # it. Not enforcing this let one ticket's earned gates survive into the next
    # one — a second ticket could then walk the entire pipeline and close out on
    # gates the FIRST ticket paid for. `history` is the exception: it is the
    # audit trail, and it is append-only forever.


# ── The source-code guard ─────────────────────────────────────────────────────
#
# The FSM stops you ENTERING the phase where code gets written without the gates.
# On its own that is not enough: an agent that never bothers to transition can
# write code from PLAN, and "no approved spec, no code" — the one rule this
# pipeline exists to guarantee — collapses into a line in a prompt.
#
# Phases whose rules forbid touching product source. RELEASE is not here: it
# writes the CHANGELOG and its own gates already close it.
NO_SOURCE_PHASES = frozenset({"CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY"})

# What those phases MAY still write. An allowlist, not a blocklist: a blocklist
# of source extensions is a guess about someone else's stack, and every guess it
# gets wrong fails open.
ALLOWED_DIR_PREFIXES = ("docs/",)
ALLOWED_WIRING_DIRS = frozenset({
    # Each tool's wiring, plus the pipeline's own runtime. Product source lives
    # in none of these.
    #
    # Two entries are conspicuously absent, and both for the same reason.
    # `.github/workflows/` is CI: code that runs on push. And `.ddw/` is the
    # METHOD — the transition graph and the gate itself. Allowing a phase to
    # write there let an agent that could not write code rewrite the rules that
    # stopped it: add an edge to the graph from PLAN and a FEATURE closes with
    # no spec, no threat model, no tests and no verification, with both hooks
    # green. A guard that exempts its own rulebook is not a guard.
    ".claude", ".codex", ".cursor", ".gemini", ".opencode",
    ".agents", ".vscode",
    # The runtime the pipeline keeps for itself. `.ddw-paused/` matters: saving
    # the state there is step one of the pause protocol, and leaving it out made
    # pause — advertised as available from any phase — work only from CODE and
    # RELEASE.
    ".ddw-paused", ".ddw-sessions", ".ddw-work",
})
ALLOWED_ROOT_FILES = frozenset({
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "CHANGELOG.md", ".gitignore",
})


def resolve_in_repo(path, root):
    """Absolute, symlink-resolved, and relative paths anchored to the REPO.

    Two separate holes lived here. `abspath` is lexical, so `/proc/self/cwd/x`,
    a symlinked repo root, and `docs/passthru.py -> ../src/app.py` all named a
    guarded file under an unguarded name. And a relative path was resolved
    against the hook's cwd, which is not necessarily the repo — from /tmp, every
    relative path escaped both guards.
    """
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    return os.path.realpath(path)


def _outside_repo(target, root):
    """Is this resolved path outside the repository DDW is guarding?

    Written once because three callers were asking it, each with its own copy of
    the same `os.pardir` comparison — and the fourth caller, the one that needed
    it most, did not ask at all.
    """
    rel = os.path.relpath(target, root)
    return rel == os.pardir or rel.startswith(os.pardir + os.sep)


def source_write_denied(target, root, phase):
    """Is this write product source, in a phase that forbids it?

    `target` and `root` must already be realpath-resolved. Returns the reason to
    refuse, or None to allow.
    """
    if phase not in NO_SOURCE_PHASES:
        return None

    if _outside_repo(target, root):
        return None                                  # outside the repo, not ours
    rel = os.path.relpath(target, root).replace(os.sep, "/")

    head = rel.split("/", 1)[0]
    if head in ALLOWED_WIRING_DIRS:
        return None
    if rel in ALLOWED_ROOT_FILES:
        return None
    if any(rel.startswith(pre) for pre in ALLOWED_DIR_PREFIXES):
        return None

    unlock = ("Finish this phase and take the transition — its gates are what unlock CODE, "
              "which is the phase that writes source. " if phase != "CODE" else "")
    return (
        f"the {phase} phase does not write product source, and `{rel}` is not one of its "
        f"artifacts. This is the pipeline's core promise being kept: no approved spec, no code. "
        f"{unlock}If this file IS an artifact of this phase, it belongs under docs/."
    )


# ── What keeps the short lane short ───────────────────────────────────────────
#
# QUICK-FIX is the tier that skips PLAN and VERIFY: nothing threat-models it and
# nothing verifies it afterwards. That is only honest while the change stays
# small, so the tier carries a ceiling — and the ceiling is the METHOD's. The
# tier is a field in the state and the limit is a line in the rules; neither is a
# fact about any tool. Decided in one adapter's hook it held for that adapter
# alone, and the same ticket was refused or waved through depending on which
# agent happened to be open.
QUICKFIX_LOC_LIMIT = 10

# Deliberately wide. A QUICK-FIX is ten lines, so the cost of stopping one that
# did not need stopping is reclassifying it as a FIX; the cost of missing one is
# an unreviewed change to the code that decides who gets in.
QUICKFIX_SENSITIVE = (
    "*auth*", "*guard*", "*middleware*", "*/api/*", "*payments*", "*secret*",
    "*credential*", "*.env", "*.env.*", "*/routes/*", "*/migrations/*",
    "*schema*", "*.sql",
)

QUICKFIX_ESCALATE = (
    'This is no longer a QUICK-FIX: close the ticket with an abandon (a history entry to IDLE '
    'with action="abandon: escalated to FIX") and reclassify it from CLASSIFY as a FIX. '
    "Escalating means a new ticket, a new branch and a root cause analysis — it is not a step "
    "backwards inside the same flow."
)


def _git(root, *args):
    """git, or None when it could not answer. A guard is not a place to raise."""
    try:
        out = subprocess.run(["git", "-C", root, *args],
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _branch_insertions(root):
    """Lines this branch adds over its base, or None when git cannot say.

    The base is DETECTED, never assumed: hardcoding `main` made the whole ceiling
    fail open on every repo whose trunk is named something else — git errored,
    the count read zero, and a diff of any size passed. `docs/ddw/` is excluded
    because each phase commits its own artifacts, so the fix-brief lands on the
    branch before the code does, and counting it spends the budget on paperwork.
    """
    branch = _git(root, "branch", "--show-current")
    if not branch:
        return None                              # detached head: nothing to compare
    base = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    base = base.split("/", 1)[-1] if base else None
    if not base:
        for cand in ("main", "master", "trunk"):
            if _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{cand}") is not None:
                base = cand
                break
    if not base or base == branch:
        return None
    stat = _git(root, "diff", f"{base}...{branch}", "--shortstat",
                "--", ".", ":(exclude)docs/ddw/")
    if stat is None:
        return None
    m = re.search(r"(\d+) insertion", stat)
    return int(m.group(1)) if m else 0


def quickfix_scope_denied(target, root, state):
    """Is this write outside what a QUICK-FIX is allowed to be?

    `target` and `root` must already be realpath-resolved. Returns the reason to
    refuse, or None to allow. Only bites on the QUICK-FIX tier.
    """
    if (state.get("tier") or "") != "QUICK-FIX":
        return None

    if _outside_repo(target, root):
        return None                                  # outside the repo, not ours
    rel = os.path.relpath(target, root).replace(os.sep, "/")
    if rel.startswith("docs/"):
        return None                                  # artifacts, not the code being changed

    probe = "/" + rel
    for pattern in QUICKFIX_SENSITIVE:
        if fnmatch.fnmatch(probe, pattern):
            return (f"`{rel}` is security-sensitive, and QUICK-FIX is the lane that skips both "
                    f"the threat model and verification. {QUICKFIX_ESCALATE}")

    loc = _branch_insertions(root)
    if loc is not None and loc > QUICKFIX_LOC_LIMIT:
        return (f"this branch has grown to {loc} added lines of code, over the QUICK-FIX limit "
                f"of {QUICKFIX_LOC_LIMIT}. {QUICKFIX_ESCALATE}")
    return None


# ── The two decisions, in one place each ──────────────────────────────────────
#
# Everything above is machinery; these two functions are the policy. They exist
# so that the CLI below and ddw/scripts/hook-gate.py — which is what the six
# tools actually run — cannot drift apart. They did: the caller had to opt into
# `max_appended`, and hook-gate did not, so one Write could declare the whole
# pipeline on every tool while this file's own CLI refused it.
#
# Both return None to allow, or a human-readable reason to refuse.

# ── What a gate rests on ─────────────────────────────────────────────────────
#
# `validate()` asks whether a gate is claimed. That is a question about the state
# and nothing else, which is why it stays a pure function the suite can drive
# with synthetic runs. This asks the other question — whether anything outside
# the model backs the claim — and it needs the repository, so it lives out here
# where the root is known.
#
# Five gates have an answer. `tests`, `sast` and `pr` are claims the machine
# sequences and records but cannot confirm, and that asymmetry is a decision
# rather than an unfinished job: docs/RATIONALE.md decision 16 says which are
# which and why.


def _receipt_missing(root, state, gate, receipt, subdir, stems, script, artifact):
    """One gate, one artifact, one receipt naming that artifact's CURRENT bytes.

    Content-hashed on purpose. A receipt keyed on the filename would go on
    attesting to a document that has since been rewritten — which is the same
    claim-without-evidence in a file, and harder to notice.

    No artifact on disk means no claim to check: synthetic runs (the suite's)
    and tiers whose phase artifact is something else are not what this is about.
    This is the table decision 16 promised — adding a gate is a row here plus a
    validator that writes the receipt, not new machinery.
    """
    ticket = state.get("ticket")
    if not ticket:
        return None
    path = None
    for stem in stems:
        cand = os.path.join(root, "docs", "ddw", subdir, "%s-%s.md" % (stem, ticket))
        if os.path.exists(cand):
            path = cand
            break
    if path is None:
        return None
    try:
        # TEXT mode, exactly as every validator reads it before hashing. Reading
        # the raw bytes here and text there disagrees on one thing and only one:
        # `\r\n`. A report authored on Windows — routine under WSL — hashed one
        # way for the validator and another for this gate, so a PASSED run wrote
        # a receipt under a digest the gate never looks for and the refusal said
        # "validate it again". There is no way out of that loop by validating
        # again, which makes it the worst shape a refusal can have.
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    except (OSError, UnicodeDecodeError):
        return None
    marker = os.path.join(root, ".ddw-sessions", "%s-validated-%s" % (receipt, digest))
    if os.path.exists(marker):
        # And it has to be a receipt for THIS artifact. The digest is of the
        # content alone, so two tickets whose documents are byte-identical —
        # a template filled in the same way twice, which is what a split
        # produces — shared one receipt: validate `a`, copy it to `b`, and
        # `b`'s gate opened having never been validated. The receipt records
        # the filename it was written for; nothing had ever read it back.
        try:
            with open(marker, encoding="utf-8") as fh:
                named = fh.read().strip()
        except OSError:
            named = ""
        if not named or named == os.path.basename(path):
            return None
    rel = os.path.relpath(path, root)
    # No "DDW: " here. Every caller prefixes this reason with its own wording —
    # `DDW blocked this write:`, `ddw-transition:`, `DDW:` — and a prefix baked
    # into the reason arrives doubled at whichever caller did not know to strip
    # it. One did, one did not, and the user read `DDW blocked this write: DDW:`.
    return ("the %s gate needs a validation receipt for %s and there is none for its "
            "current content. Run `python3 .ddw/scripts/%s %s --tier <tier>` — a "
            "PASSED run writes the receipt. If the %s changed after validating, validate again."
            % (gate, rel, script, rel, artifact))


def _prd_receipt_missing(root, state):
    """The define gate. The receipt file is `prd-validated-…` and not
    `define-validated-…` because it shipped first: renaming it would invalidate
    every receipt already on disk in every repository running DDW."""
    return _receipt_missing(root, state, "define", "prd", "prd", ("prd",),
                            "validate_prd.py", "PRD")


def _spec_receipt_missing(root, state):
    """The spec gate. `spec-` for FEATURE, `fix-` for FIX — the two names the
    PLAN phase emits. The tier is not consulted, so a mislabelled state cannot
    aim the check at the file that happens to be absent."""
    return _receipt_missing(root, state, "spec", "spec", "specs", ("spec", "fix"),
                            "validate_spec.py", "spec")


def _threat_receipt_missing(root, state):
    """The threat gate. The threat model is a document whose structure the
    catalog names rule by rule, so it can carry the same evidence the PRD does.
    That is not the same as proving the analysis is right — the report says
    which rules a parser answered and which the model judged."""
    return _receipt_missing(root, state, "threat", "threat", "security", ("threat",),
                            "validate_threat.py", "threat model")


def _verify_receipt_missing(root, state):
    """The verify gate. VERIFY's artifact is the verdict it wrote, and a verdict
    that no longer matches its own bytes is a verdict about a different run."""
    return _receipt_missing(root, state, "verify", "verify", "reports", ("verify",),
                            "validate_verify.py", "verification report")


def _commit_evidence_missing(root, state):
    """The commit gate: git is asked, rather than the model.

    Tracked modifications only. Untracked files are the build output, the
    scratch file and the dependency directory of every real repository, and a
    closeout that refuses until the working directory is pristine is a gate
    nobody can satisfy honestly — which is the one thing worse than no gate.
    """
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    if not dirty:
        return None                # clean, or git could not answer: never raise here
    # `XY PATH`, and _git already stripped the leading space off the first line —
    # a fixed offset ate a character of the first filename and named a file that
    # does not exist. Slice past the status columns, then strip what is left.
    names = [ln[2:].strip() for ln in dirty.splitlines() if ln[2:].strip()][:3]
    more = "" if len(dirty.splitlines()) <= 3 else " (and others)"
    return ("the commit gate says this work is committed, and git reports tracked changes "
            "still in the working tree: %s%s. Commit them, or this ticket closes over work that "
            "only exists on your disk." % (", ".join(names), more))


def _tests_receipt_missing(root, state):
    """The tests gate.

    DDW does not run your suite and this receipt does not claim it did. What it
    attests is the REPORT of the run: the runner and the exact command named, the
    counts adding up, every failure identified, three coverage numbers against a
    floor quoted from the project rather than chosen by the report, every skip
    explained. `docs/RATIONALE.md` decision 16 refused a receipt that would mean
    DDW running the suite — it still refuses that, because it is still true.

    What the refusal covered for was the sentence underneath: `tests: true`, on a
    run nobody could reproduce, with no numbers and no names. That is what this
    replaces.
    """
    return _receipt_missing(root, state, "tests", "tests", "reports", ("tests",),
                            "validate_tests.py", "test report")


def _pr_evidence_missing(root, state):
    """The pr gate: the forge is asked, rather than the model.

    The only gate whose evidence lives outside the repository, and the only one
    the model cannot produce by writing a file — which makes it the strongest of
    the eight when it can be checked at all, and the one that has to be most
    careful about the difference between *no* and *I could not find out*.

    Three states, distinguished rather than blurred:

    - **No remote, or a detached HEAD.** There is no pull request to have.
    - **`gh` answers about this branch.** Open or merged is the claim; anything
      else is not.
    - **Anything else** — `gh` missing, unauthenticated, offline, rate-limited,
      no default remote in a fork, authenticated to an account without access —
      is NOT a verdict, and this falls back to the model's record. A guard that
      says "the forge has none" because the network was down asserts a fact it
      never established, and that is the failure this whole file is about.
    """
    if not _git(root, "remote"):
        return None                                   # nothing to open a PR against
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        return None                                   # detached: not a branch that has a PR
    # `gh pr list --head`, never `gh pr view <branch>`. `view` takes a number, a
    # URL *or* a branch, so a branch named after a ticket number — `123`, which
    # is how plenty of teams name them — resolved to whatever PR #123 happens to
    # be, in any state, on any topic, and opened the gate.
    try:
        out = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "all",
                              "--json", "number,state"],
                             cwd=root, capture_output=True, text=True, timeout=15,
                             stdin=subprocess.DEVNULL)
    except Exception:
        return None                                   # gh absent or unusable: not a verdict
    if out.returncode != 0:
        # An error is not an answer. Offline, rate-limited, unauthenticated, a
        # fork with no default remote — every one of those used to be read as
        # "the branch has no pull request", because the code tested the exit
        # code instead of what it said.
        return None
    try:
        prs = json.loads(out.stdout or "[]")
    except ValueError:
        return None
    # A pull request that was closed without merging is not a pull request that
    # was opened for this work in any sense the closeout means. `state` was
    # already being requested from the API and then thrown away.
    live = [p for p in prs if str(p.get("state", "")).upper() in ("OPEN", "MERGED")]
    if live:
        return None
    closed = " (there is a CLOSED one, which is not the same thing)" if prs else ""
    return ("the pr gate says a pull request was opened for `%s`, and the forge has none%s. "
            "Open it, or close this ticket without claiming the gate — a PR that only exists "
            "in the report is the one thing this gate is for." % (branch, closed))


def _sast_receipt_missing(root, state):
    """The sast gate.

    What the receipt attests is the REPORT, never the code: every catalogued
    category judged, every finding carrying a file and a line, the stated result
    consistent with the severities listed, suppressions documented and in date.
    Whether a finding is right stays the model's judgement and the script says so
    on every run — the same split `validate_verify.py` makes for the verdict.

    `docs/RATIONALE.md` decision 16 refused a receipt here, and the refusal was
    aimed at a different object: a receipt claiming the code is safe. That one is
    still refused, because nothing can write it. What was left unguarded in the
    meantime was the report itself — nineteen rules catalogued, none executed,
    and a `sast` gate that turned true because the model said the reading went
    well.
    """
    return _receipt_missing(root, state, "sast", "sast", "security", ("sast",),
                            "validate_sast.py", "SAST report")


GATE_EVIDENCE = {"define": _prd_receipt_missing, "spec": _spec_receipt_missing,
                 "threat": _threat_receipt_missing, "verify": _verify_receipt_missing,
                 "sast": _sast_receipt_missing, "tests": _tests_receipt_missing,
                 "commit": _commit_evidence_missing,
                 "pr": _pr_evidence_missing}


def gate_evidence_missing(root, state, gates):
    """The first gate among `gates` whose evidence is not there, as a message."""
    for gate in gates:
        check = GATE_EVIDENCE.get(gate)
        if check is not None:
            reason = check(root, state)
            if reason:
                return reason
    return None


def _gates_newly_claimed(old_state, new_state):
    """Gates this write turns on. Evidence is owed when the claim is MADE.

    Not "every gate currently true": re-checking an old claim on every write
    means editing the PRD two phases later makes the pipeline unusable, and a
    gate that fires on legal work is how a team learns to route around gates.
    """
    was = (old_state.get("gates") or {}) if isinstance(old_state, dict) else {}
    now = (new_state.get("gates") or {}) if isinstance(new_state, dict) else {}
    return [g for g, v in now.items() if v is True and was.get(g) is not True]


def journal_path(state_path):
    """The append-only record of transitions that actually landed.

    It exists because the state file was the only record, and deleting it was
    therefore a complete escape: with nothing on disk to validate against, the
    next write starts from a blank IDLE and every rule that compares old to new
    has nothing to compare. That is not hypothetical — it is how a model, told
    to repair a state it could not legally repair, got out: `rm -f
    .ddw-state.json`, then a fresh history of its own. The run's real history
    was gone, and no check anywhere noticed.

    Written by the hook, never by the model, and only ever appended to.
    """
    return os.path.join(os.path.dirname(os.path.abspath(state_path)), ".ddw-journal.jsonl")


def _journal_entries(state_path):
    out = []
    try:
        with open(journal_path(state_path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return out


def record_journal(state_path):
    """Append whatever the state's history has that the journal does not.

    Called from post mode — after the write landed, so the journal records what
    IS rather than what was about to be. Best effort by design: a journal that
    cannot be written must not block a legal pipeline, it only costs the extra
    guarantee below.
    """
    try:
        if not os.path.exists(state_path):
            return
        with open(state_path, encoding="utf-8") as fh:
            history = (json.load(fh) or {}).get("history") or []
    except (OSError, ValueError, AttributeError):
        return
    known = len(_journal_entries(state_path))
    if len(history) <= known:
        return
    try:
        with open(journal_path(state_path), "a", encoding="utf-8") as fh:
            for entry in history[known:]:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass


def _check_state_not_erased(state_path):
    """A state that vanished, or came back shorter than what was recorded.

    `rm` used to be the one move that always worked. Now the journal outlives
    the file, so the history cannot be dropped by deleting what holds it — the
    next write is refused until a human says what happened.
    """
    recorded = _journal_entries(state_path)
    if not recorded:
        return
    if not os.path.exists(state_path):
        raise Block(
            f".ddw-state.json is gone, but {len(recorded)} transition(s) were recorded for this "
            "repo. Deleting the state does not start a clean run, it destroys the history of the "
            "one in progress — restore it (a backup, or rebuild it from .ddw-journal.jsonl; "
            "`git checkout` cannot restore a gitignored file) and tell the user what happened."
        )
    try:
        with open(state_path, encoding="utf-8") as fh:
            history = (json.load(fh) or {}).get("history") or []
    except (OSError, ValueError, AttributeError):
        return                       # unreadable is the other check's business
    if len(history) < len(recorded):
        raise Block(
            f".ddw-state.json holds {len(history)} history entries but {len(recorded)} were "
            "recorded for this repo. History is append-only: a shorter one means entries were "
            "dropped, not that the run got simpler. Restore the state and tell the user."
        )


def _read_state_or_refuse(state_path):
    """(old_text, old_state) — or raise Block if the file exists and is garbage.

    Treating an unreadable state as a fresh IDLE handed anyone a way around the
    append-only rule: corrupt the file, then write any history you like over the
    "empty" one.
    """
    _check_state_not_erased(state_path)
    if not os.path.exists(state_path):
        return "", _idle_template()
    try:
        with open(state_path, encoding="utf-8") as fh:
            text = fh.read()
        parsed = json.loads(text) if text.strip() else _idle_template()
        if not isinstance(parsed, dict):
            raise ValueError("the state is not a JSON object")
    except (OSError, ValueError) as exc:
        raise Block(
            f".ddw-state.json exists but cannot be read ({exc}). Restore it from the last "
            "good version and redo the transition with the write tool."
        )
    return text, parsed


def decide_pre(state_path, graph_path, tool_name, tool_input, paths, repo=None, raw_tool=None):
    """PreToolUse: judge a pending write. `paths` is every path the event names.

    Every candidate is judged, not just the first one found: an envelope
    carrying a harmless `file_path` next to the real `path` bought a free write
    while the gate looked at the decoy.
    """
    root = os.path.realpath(repo) if repo else os.path.dirname(os.path.realpath(state_path))
    state_real = os.path.realpath(state_path)

    targets = [resolve_in_repo(pth, root) for pth in paths if isinstance(pth, str) and pth]
    if not targets:
        return None                                   # no path to judge

    # Nothing this event names is in the repository, so none of it is DDW's to
    # judge. The per-target guards below already say that — but they run after
    # the state is read, and a corrupt state refuses before any target is looked
    # at. That turned the one recovery this product prescribes into a painted
    # door: the refusal tells the model to write the corrected state to a scratch
    # path OUTSIDE the repo and hand the user a copy command, and then the same
    # guard refuses that write too. Measured live — the model tried exactly what
    # it had just been told to do, and was stopped.
    #
    # This does not soften the corrupt-state rule. Every path inside the repo,
    # the state file first, stays refused until a human restores it.
    if all(_outside_repo(t, root) for t in targets):
        return None

    # Is this event a WRITE at all?
    #
    # It has to be asked, because not every tool a hook sees is one. Claude's
    # matcher filters to Edit|Write|NotebookEdit before the gate is ever called,
    # so the question never came up; Copilot's preToolUse carries no matcher and
    # hands over EVERY tool. Reads and directory listings arrived here with a
    # path, were judged as writes, and were refused — including the agent trying
    # to read `.ddw/rules/classify.instructions.md`, the very file that tells it
    # what CLASSIFY may do.
    #
    # An agent that cannot read is not a guarded agent, it is a broken one. And
    # this failed in the direction that looks like working: the refusals were
    # real, the wording was DDW's, and the pipeline appeared to be enforcing
    # something.
    # `raw_tool` is what the harness actually called. `tool_name` may be the
    # canonical verb hook-gate rewrote it to, which says "Edit" for anything it
    # did not recognise — judging on that made every read a write.
    _verb = (raw_tool if raw_tool is not None else tool_name or "").lower()
    payload_writes = (tool_input.get("content") is not None
                      or "old_string" in tool_input or "new_string" in tool_input)
    writing = payload_writes or not any(r in _verb for r in READ_VERBS)

    # Judge the source guard on every target that is NOT the state file, always.
    # Returning early once the state was recognised meant an envelope naming the
    # state alongside the real target bought a write that nothing looked at —
    # the mirror image of the decoy this function was written to close.
    _, disk = _read_state_or_refuse(state_path)
    phase = disk.get("phase", IDLE)
    for target in targets:
        if target == state_real:
            continue
        if not writing:
            continue                      # a read cannot violate a write rule
        reason = source_write_denied(target, root, phase)
        if reason:
            return reason
        reason = quickfix_scope_denied(target, root, disk)
        if reason:
            return reason

    # The state file keeps failing closed on an unknown verb: reconstructing it
    # is what decides, and `_reconstruct_new_text` refuses anything it cannot
    # replay. A READ of the state is harmless and is not reconstructed.
    if state_real in targets and writing:
        old_text, old_state = _read_state_or_refuse(state_path)
        graph = _load_graph(graph_path)
        new_text = _reconstruct_new_text(tool_name, tool_input, old_text)
        new_state = _parse_new_state(new_text)
        validate(old_state, new_state, graph, tool_name=tool_name, max_appended=1)
        # The claim is legal. Is it backed?
        #
        # This used to be asked by transition.py alone — the helper the model is
        # asked to use — so the one gate that rests on evidence rested on the
        # model choosing the cooperative path. A plain Write of the same state,
        # judged right here, was allowed: exit 2 through the helper, exit 0
        # through the hook. A guarantee with a polite way around it is a
        # promise, which is the distinction this whole repository is about.
        reason = gate_evidence_missing(root, new_state,
                                       _gates_newly_claimed(old_state, new_state))
        if reason:
            return reason
    return None


# DDW's own footprint, which is not product source and is not the agent going
# around the guard. `.ddw/` is absent from ALLOWED_WIRING_DIRS on purpose — an
# agent that cannot write code must not be able to rewrite the graph that stops
# it — but that is a rule about WRITES, and this function asks a different
# question. A freshly installed repo has `.ddw/` untracked until someone commits
# it, and warning about that on every shell command would train the reader to
# ignore the one warning that matters.
_NOT_PRODUCT = frozenset({".ddw", ".ddw-installed.json", ".git",
                          # DDW's own runtime. The journal is written BY the post hook,
                          # so leaving it out made the net report its own bookkeeping as
                          # unapproved source on every single transition.
                          ".ddw-state.json", ".ddw-journal.jsonl", ".ddw-sessions",
                          ".ddw-paused"})


def source_changed_in_no_source_phase(repo, phase):
    """Did product source change while the pipeline sat in a phase that forbids it?

    **This detects; it does not prevent.** The pre-write guard refuses a Write
    or an Edit, which is where the "no approved spec, no code" promise is kept.
    It cannot see a shell command: `bash -c 'cat > app/x.py'` reaches the disk
    through a tool whose PreToolUse matcher never names it, and adding one means
    parsing shell — `cat >`, `tee`, `sed -i`, a heredoc, `python -c` — which is
    guessing at someone else's syntax, and every guess it gets wrong fails open.
    A guard that covers most spellings and reads as covering all of them is
    worse than an honest gap.

    So this closes the loop the other way: the post-write net already runs on
    every Bash, and git already knows what changed. It returns a sentence, and
    the caller reports it.

    **It never blocks, and that is not timidity.** DDW cannot tell the agent's
    shell from yours. Editing your own code in another terminal while a ticket
    sits in PLAN is an ordinary thing to do, and being refused for it would be a
    defect. Reporting a fact is useful; blocking on an inference about who typed
    it is not.
    """
    if phase not in NO_SOURCE_PHASES:
        return None
    try:
        out = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None                      # no git, or it is not answering: not ours to guess
    if out.returncode != 0:
        return None

    root = os.path.realpath(repo)
    hits = []
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:               # a rename: the destination is what exists now
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if not path or path.rstrip("/").split("/", 1)[0] in _NOT_PRODUCT:
            continue
        # git reports an untracked DIRECTORY as `docs/`, with the slash. Resolved
        # to a path it becomes `docs`, which does not start with `docs/` — so the
        # allowlist missed it and every artifact directory read as product source.
        # Probing the directory itself keeps the prefix intact.
        probe = path if path.endswith("/") else path
        target = resolve_in_repo(probe.rstrip("/") + ("/x" if path.endswith("/") else ""), root)
        if target and source_write_denied(target, root, phase):
            hits.append(path)
        if len(hits) > 5:
            break

    if not hits:
        return None
    shown = ", ".join(sorted(hits)[:5])
    more = " and others" if len(hits) > 5 else ""
    return (
        f"product source has changed while the pipeline is in {phase}, which does not write "
        f"source: {shown}{more}. The pre-write guard refuses this through the write tools; a shell "
        "command goes around it, so this is a report rather than a refusal — and it cannot tell "
        "your own editing from the agent's. If the agent wrote these, they were written with no "
        "approved spec: review them before they reach CODE."
    )


def decide_post(state_path, graph_path):
    """PostToolUse: revalidate the current run of the state ON DISK.

    Tool- and path-agnostic: it reads the file exactly as the write left it,
    including a Bash/jq the PreToolUse matcher never sees.
    """
    if not os.path.exists(state_path):
        # Not "nothing to check": the journal knows whether there was.
        _check_state_not_erased(state_path)
        return None
    _, disk_state = _read_state_or_refuse(state_path)
    # IDLE with no history: nothing to validate. Avoids noise — the post matcher
    # fires on EVERY Bash, and most of them do not touch the state.
    if disk_state.get("phase", IDLE) == IDLE and not (disk_state.get("history") or []):
        return None

    graph = _load_graph(graph_path)
    history = disk_state.get("history") or []
    start = _last_idle_reset_index(history)
    run = [e for e in history[start:] if isinstance(e, dict)]

    # Recover the tier the run was walked under. After a closeout the header's
    # `tier` is null by design, so without this the replay looks the run's edges
    # up in the empty `null` graph and calls every finished ticket illegal.
    run_tier = next((e.get("tier") for e in reversed(run) if e.get("tier")), None)
    tier = run_tier or disk_state.get("tier")
    if (tier is None and run and run[-1].get("to") == IDLE
            and disk_state.get("phase", IDLE) == IDLE):
        # A ticket that closed before edges carried their tier. Its EDGES cannot
        # be looked up — the tier they were walked under is gone — so judging
        # the graph would invent a verdict, and refusing would brick every
        # session that upgraded mid-ticket.
        #
        # The condition on `phase` is what keeps this from being a skeleton key.
        # Returning early skips append-only, the IDLE invariant and the
        # phase/history agreement as well, so without it a single untiered entry
        # ending at IDLE disabled post mode entirely: a state forged with `sed`
        # saying `phase: CODE` with every gate set walked straight through. A
        # closed ticket is at IDLE by definition; anything else is not the case
        # this hatch is for.
        return None

    prior = {"phase": IDLE, "tier": tier, "gates": {}, "history": history[:start]}

    # A closed ticket's gates are unverifiable after the fact, because closing
    # it is what erased them: `RELEASE->IDLE` demands `commit` and `pr`, and the
    # same write that takes that edge resets `gates` to {}. Replaying it against
    # the empty snapshot declared every finished ticket illegal — and since the
    # post matcher fires on every Bash and Edit, the session stayed wedged from
    # then on. So on a closed run this checks the PATH, which is what a Bash/jq
    # forgery fakes; the gates were already enforced pre-write, when they existed.
    scope = "none" if (run and run[-1].get("to") == IDLE) else "last"
    # gates_scope="last" and no cap: this replays a whole run that was already
    # validated edge by edge. Checking every edge against today's gate snapshot
    # does not re-check history, it invents a verdict — and it rejected the
    # corrective loop, the pipeline's own documented recovery path.
    validate(prior, disk_state, graph, gates_scope=scope, max_appended=None)

    # The same question the pre path asks, for the writes it never sees: a
    # `jq`/`sed`/heredoc that sets a gate reaches the disk without passing a
    # write tool. What is new here is exactly what the journal has not recorded
    # yet — the journal is written below, after the verdict — so this asks about
    # the edge that just landed and never re-litigates the ones before it.
    if scope != "none":
        known = len(_journal_entries(state_path))
        landed = [e for e in history[known:] if isinstance(e, dict)]
        if landed:
            edges = _effective_edges(graph, tier)
            owed = []
            for entry in landed:
                cfg = edges.get("%s->%s" % (entry.get("from"), entry.get("to")))
                if isinstance(cfg, dict):
                    owed.extend(cfg.get("gates") or [])
            reason = gate_evidence_missing(os.path.dirname(os.path.abspath(state_path)),
                                           disk_state, owed)
            if reason:
                raise Block(reason)

    # Only a state that just passed gets recorded. Journalling before the verdict
    # would enshrine the forgery it is meant to survive.
    record_journal(state_path)
    _ensure_runtime_ignored(state_path)
    return None


def _ensure_runtime_ignored(state_path):
    """Under a plugin the state is born mid-session, and the session boot — the
    only other writer of the .gitignore block — has already run by then. Until
    the next boot every commit could take the runtime with it, so the net that
    just blessed the state closes that window itself. Delegates to the boot's
    own ensure_gitignore: one block, one writer of its content.
    """
    try:
        import importlib.util
        boot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session-boot.py")
        spec = importlib.util.spec_from_file_location("ddw_session_boot", boot_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ensure_gitignore(os.path.dirname(os.path.abspath(state_path)))
    except Exception:
        pass                     # a missing convenience net must not block the verdict


# The graph's FORMAT version, not the product's. It moves when the shape of the
# file changes — a new key, a renamed one, a different meaning for `gates`.
#
# Checked rather than decorative, which is the whole reason it exists. A repo
# that installed DDW a year ago has its own `.ddw/rules/transition-graph.json`
# committed; upgrade the scripts and not the graph, or the other way round, and
# without this the validator would read a shape it does not understand and reach
# a verdict anyway. Refusing beats guessing when the thing being guessed at is
# what may write source code.
GRAPH_FORMAT_MAJOR = 1


def _load_graph(path):
    try:
        with open(path, encoding="utf-8") as fh:
            graph = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"DDW FSM: could not load the graph: {exc}", file=sys.stderr)
        sys.exit(2)

    declared = graph.get("format_version")
    # Absent means a graph written before the field existed. Those are format 1
    # by definition, so they keep working: refusing them would break every repo
    # that installed DDW earlier, to enforce a field they could not have had.
    if declared is not None:
        try:
            major = int(str(declared).split(".", 1)[0])
        except ValueError:
            major = None
        if major != GRAPH_FORMAT_MAJOR:
            print(
                f"DDW FSM: this transition graph declares format {declared!r} and these scripts "
                f"read format {GRAPH_FORMAT_MAJOR}.x. Upgrading `.ddw/` in halves leaves the "
                "validator reading a shape it does not understand — re-run install.sh so the "
                "graph and the scripts come from the same version.",
                file=sys.stderr)
            sys.exit(2)
    return graph


def _run_pre(args):
    """PreToolUse mode, standard dialect. The decision itself is decide_pre()."""
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except ValueError:
        sys.exit(0)  # unreadable envelope: not our business, do not block
    if not isinstance(event, dict):
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        sys.exit(0)  # malformed envelope: not a tool_input we can route
    paths = [tool_input.get(k) for k in PATH_KEYS]

    try:
        reason = decide_pre(args.state, args.graph, tool_name, tool_input, paths,
                            repo=args.repo)
    except Block as exc:
        print(f"DDW FSM blocked the write to the state: {exc}", file=sys.stderr)
        sys.exit(2)
    if reason:
        print(f"DDW blocked this write: {reason}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def _last_idle_reset_index(history):
    """Index of the FIRST element of the current run: whatever follows the last reset.

    `history` is an append-only log for the whole life of the repo and spans
    several tickets, each with its own tier (separated by a `to==IDLE` entry).
    The "current run" starts after the last reset to IDLE. If there was never a
    reset, the current run is the whole history (index 0).

    One subtlety, and it used to be a hole: when the LAST entry is itself a reset
    to IDLE, "after the last reset" is the empty tail — so the ticket that just
    closed fell entirely into the already-validated prefix and was never checked.
    Every illegal closeout became invisible the moment it completed. When the
    history ends on a reset, the current run is the ticket that reset closed.
    """
    resets = [i for i, e in enumerate(history) if isinstance(e, dict) and e.get("to") == IDLE]
    if not resets:
        return 0
    if resets[-1] == len(history) - 1:
        return resets[-2] + 1 if len(resets) >= 2 else 0
    return resets[-1] + 1


def _run_post(args):
    """PostToolUse mode. The decision itself is decide_post()."""
    try:
        reason = decide_post(args.state, args.graph)
    except Block as exc:
        print(
            "DDW FSM found an ILLEGAL .ddw-state.json on disk: "
            f"{exc}. You probably wrote it with Bash/jq/sed (which bypass the "
            "PreToolUse hook). Fix the state and redo the transition with the Write "
            "tool (whole file: header + history), NEVER with Bash.",
            file=sys.stderr,
        )
        sys.exit(2)
    if reason:
        print(f"DDW: {reason}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--graph", required=True)
    ap.add_argument("--mode", choices=("pre", "post"), default="pre")
    ap.add_argument("--repo", default=None,
                    help="repo root; relative paths in the event resolve against it")
    args = ap.parse_args()

    # Fail CLOSED on anything unexpected. An uncaught exception exits 1, and 1 is
    # not a refusal — every harness reads it as "the hook errored" and lets the
    # write through. A `tier` written as a list was enough: TypeError, exit 1,
    # illegal state on disk. If this validator cannot reach a verdict, the answer
    # is no.
    try:
        if args.mode == "post":
            _run_post(args)
        else:
            _run_pre(args)
    except SystemExit:
        raise
    except Exception as exc:                                  # noqa: BLE001
        print(
            f"DDW FSM: the validator could not reach a verdict ({type(exc).__name__}: {exc}). "
            "Refusing the write — a state it cannot read is a state it cannot vouch for.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
