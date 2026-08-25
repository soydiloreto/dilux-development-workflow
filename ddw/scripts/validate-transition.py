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
import datetime
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

# …and the ones that spell it in no word at all. The list above is matched as
# SUBSTRINGS, which covers `read_file`, `file_search`, `grep_search` and every
# other compound — and misses a name that is an abbreviation. Copilot CLI calls
# ripgrep `rg`, and `rg` contains none of the words above, so the search that
# reads a file was judged a write to it.
#
# Measured live, one release after reads were let through: `view` of
# `.ddw/orchestrator.md` passed and `rg` over the same file came back "DDW
# blocked this write". The agent recovered through `bash grep`, which is the
# part worth reading twice — the refusal did not stop the read, it moved it to
# the one door PreToolUse cannot see through.
#
# Matched WHOLE, not as a substring: two letters inside somebody's `purge` or
# `merge_files` would turn a write into a read, which is the failure this list
# must never have.
READ_TOOLS = ("rg",)

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

    # `extends` is not an edge, and neither is a comment. The graph carries prose
    # at the top level (`_note`, `_resume_note`, `_backward_note`) and a tier is
    # the obvious place to write the next one — at which point `_note` became an
    # edge named `_note` whose "gates" are a string, and the first function to
    # ask a tier what it owes died on it. A key that starts with `_` is for the
    # reader.
    edges = {k: v for k, v in graph.get("common", {}).items() if not k.startswith("_")}
    for name in reversed(chain):          # ancestors first, so the tier wins
        edges.update({k: v for k, v in tiers[name].items()
                      if k != "extends" and not k.startswith("_")})
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


def _paused_at(history, upto, ticket=None):
    """The phase the last UNRESUMED pause left, or None if there is none.

    It used to read `history[-1]` alone — the entry immediately before the
    resume — which assumed the pause was the last thing that ever happened. That
    is the one thing a pause is for NOT being: you set a ticket aside precisely
    because you are going to work on something else. Pause A, run B end to end,
    come back for A, and the entry before the resume is B's closeout, so the
    resume was refused as having no paused ticket — the feature failed at exactly
    the workflow it was built for.

    So: search backwards, skipping the tickets that came and went in between, and
    pair each resume already in the history with the pause it consumed. A pause
    that was resumed once cannot be resumed again — otherwise `resume` re-enters
    a phase whose ticket is long closed, carrying whatever gates it likes.
    """
    prior = [e for e in history[:upto] if isinstance(e, dict)]
    if ticket:
        # Only this ticket's own pauses. Without it, resuming A could be paired
        # with B's pause and land in B's phase, carrying whatever gates the write
        # cares to declare.
        #
        # The fallback is for histories written before entries carried a ticket,
        # and it is conditioned on the history actually being one of those — not
        # on "I found none of mine". Falling back whenever the filter came up
        # empty meant a run whose entries all name someone else took the
        # unfiltered path, which is precisely the case it must not take.
        if any(e.get("ticket") for e in prior):
            prior = [e for e in prior if e.get("ticket") == ticket]
    pending_resumes = 0
    for entry in reversed(prior):
        if _is_resume(entry):
            pending_resumes += 1
            continue
        if entry.get("to") != IDLE or not _is_pause(entry):
            continue
        if pending_resumes:
            pending_resumes -= 1           # this pause was already picked back up
            continue
        return entry.get("from")
    return None


def _resume_allowed(entry, history, upto):
    """Is this a real resume, or the word `resume` used as a skeleton key?

    Listing the destination in `resume_edges` is necessary and nowhere near
    sufficient. Without proof that a pause happened, and from this very phase,
    `resume:` was an edge from IDLE to any phase at all, carrying whatever gates
    the same write cared to declare — the entire pipeline in one write, which is
    the exact hole every other check here exists to close.
    """
    dst = entry.get("to")
    paused_at = _paused_at(history, upto, entry.get("ticket"))
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


def _is_split_open(entry):
    """Does this entry declare itself as opening a sub-ticket of a split?"""
    action = entry.get("action")
    if not isinstance(action, str):
        return False
    return action.strip().lower().split(":", 1)[0].strip() == "split"


def _split_parent(ticket):
    """`FEAT-001a` → `FEAT-001`, or None when the name derives from no parent."""
    if (isinstance(ticket, str) and len(ticket) > 1
            and ticket[-1].isalpha() and ticket[-1].islower()):
        return ticket[:-1]
    return None


def _split_pause_of(history, upto, parent):
    """The parent's newest entry, IF it is the split's own pause; else None.

    Deliberately not consumed by being used: every child of one split rests on
    the same pause, and closing child `a` — a whole run of its own, ending at
    IDLE under the child's ticket — does not spend the parent's proof. What DOES
    end the claim is the parent doing anything newer: its newest entry must BE
    the split-pause, or the split is not the parent's standing last word.
    """
    for entry in reversed(list(history)[:upto]):
        if not isinstance(entry, dict) or entry.get("ticket") != parent:
            continue
        if (entry.get("to") == IDLE and _is_pause(entry)
                and "split" in (entry.get("action") or "").lower()):
            return entry
        return None
    return None


def _split_open_allowed(entry, history, upto):
    """Is this a real split-child opening, or `split:` used as a skeleton key?

    Same bargain as `_resume_allowed`: this edge skips the graph, so every part
    of it has to be proven by the record. CLASSIFY exists to produce tier,
    ticket and autonomy — and for a split child all three already exist: the
    parent's run produced them and the user approved the split that named this
    child. Sending the child through CLASSIFY re-decided nothing and cost the
    user a turn that decided nothing — the rubber stamp the method itself
    argues against. So the child opens directly in the phase its parent paused
    from, and the proof is the pause: the child's name derives from the
    parent's, the parent's newest entry is the split's own pause, the
    destination is the phase that pause left, and the tier is the pause's.
    """
    child = entry.get("ticket")
    parent = _split_parent(child)
    if not parent:
        raise Block(
            f"`split:` opens a sub-ticket of a split, and {child!r} names no parent: a "
            "sub-ticket is its parent's ID plus one lowercase letter (FEAT-001a). Anything "
            "else is not a split child and starts at CLASSIFY like every ticket."
        )
    pause = _split_pause_of(history, upto, parent)
    if pause is None:
        raise Block(
            f"this history has no standing split-pause for {parent}: `split:` rests on the "
            'parent\'s own `pause: split into …` entry being its newest word, and it is not. '
            "A split that did not happen cannot be opened into; classify the work instead."
        )
    dst = entry.get("to")
    if pause.get("from") != dst:
        raise Block(
            f"the split paused {parent} at {pause.get('from')}, so its children open there — "
            f"not at {dst}. The phase is part of the proof, exactly as it is for a resume."
        )
    if pause.get("tier") and entry.get("tier") != pause.get("tier"):
        raise Block(
            f"the split was taken under tier {pause.get('tier')} and this entry says "
            f"{entry.get('tier')!r}. A split does not reclassify the work: the child rides "
            "the parent's tier or it is not its child."
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


def _is_pause(entry):
    """A pause specifically, as opposed to an abandon. The two are the same edge
    and mean opposite things: one comes back, the other never does."""
    action = entry.get("action")
    if not isinstance(action, str):
        return False
    return action.strip().lower().split(":", 1)[0].strip() in ("pause", "paused")


def _walkaway_blocked(graph, phase):
    """Phases you are not allowed to walk away from. There is exactly one so far
    — CLOSEOUT, where nothing is left to decide, only steps to finish — and it
    lives in the graph rather than in this file so a project can say otherwise."""
    return phase in set(graph.get("no_walkaway", []))


# Phases this method has had, and what they are called now. A state written by an
# older DDW is not a forgery, and telling its owner they "probably wrote it with
# Bash/jq/sed" is both wrong and accusatory — it sends them to fix a state they
# never touched, with the one explanation that cannot be true.
RENAMED_PHASES = {"RELEASE": "CLOSEOUT"}


def _renamed_phase_in(state):
    """The old phase name this state still carries, or None."""
    names = {state.get("phase")}
    for entry in (state.get("history") or []):
        if isinstance(entry, dict):
            names.add(entry.get("from"))
            names.add(entry.get("to"))
    for old, new in RENAMED_PHASES.items():
        if old in names:
            return old, new
    return None


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


# The six gates whose evidence is a receipt naming an artifact, and the artifact's
# path is derived from the ticket. `commit` and `pr` ask git and the forge instead,
# so they do not need one.
RECEIPT_GATES = ("define", "spec", "threat", "tests", "sast", "verify")


def _check_ticket_shape(new_state):
    """`ticket` is a string, or null at IDLE. It was the only header field with
    no shape check while `tier`, `autonomy`, `gates` and `history` all have one —
    so a ticket of the wrong STRING was refused and a ticket of the wrong TYPE
    was accepted, after which every isinstance guard downstream carried weight it
    was not written to carry."""
    ticket = new_state.get("ticket")
    if ticket is None:
        return
    if not isinstance(ticket, str) or not ticket.strip():
        raise Block(
            f"`ticket` must be a non-empty string or null, got {ticket!r}. Everything the run "
            "records is attributed through it, and a receipt resolves its document by it."
        )


def _check_gates_have_a_ticket(new_state):
    """A claimed receipt gate has to name the ticket it was earned for.

    Every receipt gate resolves its artifact through the ticket —
    `docs/ddw/prd/prd-<ticket>.md` and its siblings. With `ticket` null there is
    no path to resolve, so each of those checks found no artifact and read that
    as "no claim to check": clearing the ticket opened all six at once, and it
    was one `jq` away. The absent-artifact hatch is for a state that claims
    nothing; a state that claims six gates is exactly what it is not for.
    """
    ticket = new_state.get("ticket")
    if ticket:
        return
    gates = new_state.get("gates") or {}
    if not isinstance(gates, dict):
        return
    claimed = sorted(g for g in RECEIPT_GATES if gates.get(g) is True)
    if claimed:
        raise Block(
            "`ticket` is null but these gates are claimed: %s. A gate is earned for a ticket — "
            "its receipt names that ticket's document. Restore the ticket, or drop the gates and "
            "earn them again under the one this run is actually about." % ", ".join(claimed)
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
    # ANY appended edge touching CLASSIFY, not just the first one. On the pre
    # path a write carries a single edge, so first-or-any is the same question —
    # but post mode replays the whole run as one batch against a synthetic IDLE
    # prior, and there `appended[0]` is IDLE→CLASSIFY while the change being
    # judged happened on it. Every real ticket that chose a mode and walked past
    # DEFINE was refused by the post hook from then on: the field the feature
    # exists for made the pipeline unusable, and no check drove it end to end.
    touches_classify = any(e.get("from") == CLASSIFY or e.get("to") == CLASSIFY
                           for e in appended if isinstance(e, dict))
    reaching_idle = new_state.get("phase", IDLE) == IDLE
    # Resuming is the one other moment the mode is chosen, and it has to be, or
    # the setting is simply lost across a pause: reaching IDLE clears it, and the
    # only way back would be abandoning the ticket and classifying it again.
    #
    # Narrow because a resume cannot be manufactured. `_resume_allowed` demands a
    # real, unresumed pause of THIS ticket, from the exact phase being re-entered
    # — so getting here means a ticket was genuinely set aside and picked back
    # up, which is a user-visible act with two history entries behind it. The
    # value chosen is stamped on the resume edge, so the record says a mode was
    # decided there rather than inherited.
    #
    # What this cannot see is whether the user was actually asked. That stop is
    # the method's (`ddw/orchestrator.md`, Pause Protocol), like the loop ceiling
    # — a hook can prove a pause happened; it cannot prove a question was put.
    # From IDLE, which is the only place a resume comes from. Matching the word
    # alone was a skeleton key the first time it was written: `_resume_allowed`
    # only runs on the edges out of IDLE, so an ordinary PLAN→CODE labelled
    # "resume: …" was never checked as a resume at all and granted the mode for
    # free. Caught by the check written alongside this, before it shipped.
    resuming = any(_is_resume(e) and e.get("from") == IDLE
                   for e in appended if isinstance(e, dict))
    # Opening a split child is that child's CLASSIFY-moment: the edge replaces
    # the CLASSIFY the child never passes through, so the mode is chosen here or
    # it cannot be chosen at all. Narrow for the resume's reason: `from` must be
    # IDLE, because `_split_open_allowed` only ever judges the edges out of
    # IDLE, and the word alone on any other edge is the same skeleton key.
    split_opening = any(_is_split_open(e) and e.get("from") == IDLE
                        for e in appended if isinstance(e, dict))
    if (in_classify or entering_classify or touches_classify or reaching_idle
            or resuming or split_opening):
        return
    raise Block(
        f"`autonomy` changed {old_auto!r}→{raw_new!r} outside CLASSIFY. How much of this run "
        "waits for a human is decided when the request is classified, with the user looking at "
        "the box, and again when a paused ticket is resumed — and nowhere else. To change it "
        'now, walk away from this ticket (action "abandon: …") and reclassify.'
    )


# FREE is the only tier the user has to ASK for, and the rule saying so was
# prose. Measured live, on 0.32.2: asked to create a file at IDLE, the model read
# `classify.instructions.md` — the file that says *never propose it, never offer
# it as a way out of a refusal you just gave* — and then offered exactly that,
# with "(Recomendado)" next to it. The refusal text had already been cleaned of
# the recipe; the model learned FREE from the rule that forbids proposing it.
#
# A rule the model reads and steps over is a rule the pipeline does not have. So
# the arrow into FREE now costs something only the user can supply: their own
# words, quoted, in the action. It cannot tell a faithful quote from a fabricated
# one — nothing here can — but it turns a slip into a sentence somebody had to
# write down, and it puts what was said on the record where a person can read it
# back. Every other tier stays free of this: FREE is the one that buys the
# absence of every other guarantee.
# The action is stripped before it is matched, so this pattern needs no
# leading `\s*` — the shape one file over bans for hanging on long input.
_FREE_ACTION = re.compile(r"""free\s*:\s*.*["“'«][^"”'»]{4,}["”'»]""", re.IGNORECASE | re.DOTALL)


def _check_the_ticket_has_a_name(new_state, appended, replaying=False):
    """Leaving CLASSIFY, the ticket carries a title. Measured live: it did not.

    The rules say `title` and `tracker` are filled in the SAME write as the
    classifying edge — and that write was a hand-composed `Write`, so when the
    helper grew `--write` and became the way the state actually lands, the two
    fields had no way in. A FEATURE reached DEFINE with `"title": null`, and from
    there every status line, every report header and the PR title were the model
    re-inventing the name from context, turn after turn, while the state — the
    thing that survives the session — named nothing.

    Only on the edge out of CLASSIFY, which is the one moment the name is
    decided. A resume cannot restore what no history entry carries, and refusing
    there would strand a paused ticket.
    """
    # NOT on a replay. Post mode re-walks the whole run as one batch, so without
    # this the requirement reaches backwards: every ticket already open with
    # `"title": null` — which is every ticket opened before this release, the
    # defect being fixed — would be refused on every tool call from here on,
    # with nothing the user could do about it short of hand-editing the state.
    # A new rule governs the next edge, never the ones already taken. Post mode
    # is the only caller that passes no cap, and the hook path always passes 1,
    # so this cannot be reached for by a write.
    if replaying:
        return
    classifying = [e for e in appended if e.get("from") == CLASSIFY and e.get("to") != IDLE]
    if not classifying or not new_state.get("ticket"):
        return
    title = new_state.get("title")
    if not (isinstance(title, str) and title.strip()):
        raise Block(
            "this edge leaves CLASSIFY with a ticket and no `title`. The name is decided here "
            "and nowhere else: pass `--title \"<one line>\"` on the same run that sets "
            "`--ticket`, or put both in the same Write. A state that names no work makes every "
            "line the user reads afterwards a reconstruction from context."
        )


def _check_free_is_the_users_word(old_state, new_state, appended, replaying=False):
    # Same reason as the check above: a run that entered FREE before this
    # release recorded no quote, and re-judging it on replay would strand it.
    if replaying:
        return
    entering = [e for e in appended if e.get("to") == "FREE"]
    turning_free = (new_state.get("tier") == "FREE" and old_state.get("tier") != "FREE")
    if not entering and not turning_free:
        return
    actions = [e.get("action") or "" for e in (entering or appended)]
    if not actions:
        raise Block(
            "this write turns the tier to FREE and appends no history entry, so nothing says "
            "who asked for it. FREE is the one tier the user has to ask for: the arrow that "
            "enters it carries their words."
        )
    # `match` on the stripped action, not `search`: the declaration is what the
    # action OPENS with. Searching anywhere in it would let `free: "…"` ride along
    # inside a sentence about something else entirely.
    if not any(_FREE_ACTION.match(a.strip()) for a in actions):
        raise Block(
            'FREE needs the user\'s own words on the record. Write the action as '
            '`free: "<what they said>"` — quoting the sentence in which they asked to work '
            "without the pipeline. This tier buys the absence of every guarantee DDW makes, "
            "and it is not yours to choose: never propose it, and never offer it as a way out "
            "of a refusal you just gave. If they have not asked for it, the answer is to "
            "classify the work — the tier decides what it owes, not whether there is a record."
        )


def _check_tier(old_state, new_state, appended):
    """The tier is chosen in CLASSIFY and holds for the whole ticket.

    Two holes lived here, and both were about WHEN this ran rather than what it
    checked. It ran after the early return for writes that append no history
    entry, so a write changing only `tier` skipped it entirely — and that is all
    it takes: flip a FEATURE to QUICK-FIX in one silent write, then walk
    DEFINE→CODE→CLOSEOUT, skipping PLAN and VERIFY and never earning `spec`,
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
    # Being IN classify counts, not only leaving it. The check looked at the
    # first appended edge, so an in-phase correction while still in CLASSIFY was
    # refused with "the tier changed outside CLASSIFY" — while in CLASSIFY.
    in_classify = old_state.get("phase") == CLASSIFY
    leaving_classify = bool(appended) and appended[0].get("from") == CLASSIFY
    reaching_idle = new_state.get("phase", IDLE) == IDLE
    # The third hole, and it is the one the check above was written for without
    # covering: `null` reads as "unchanged" everywhere it is consulted, exactly
    # like the `""` and `0` refused a few lines up — but it arrives as the value
    # a caller is ALLOWED to send to mean "leave it alone", so it was let
    # through. Being let through, it LANDS: the next write finds no old tier and
    # `not old_tier` returns before anything is compared. FEATURE → null →
    # QUICK-FIX, two writes, both exit 0, neither saying anything, and the
    # ticket now walks a graph with no PLAN and no VERIFY. Only IDLE clears a
    # tier — `_check_idle_invariant` requires it to be null there — and CLASSIFY
    # may still change it outright, so neither of those is what this refuses.
    if old_tier and raw_new is None and not reaching_idle and not in_classify:
        raise Block(
            f"this write drops `tier` (it is {old_tier!r} on disk) while the ticket is still at "
            f"{old_state.get('phase', IDLE)}. A null tier reads as 'unchanged' everywhere it is "
            "consulted, so landing it here lets the NEXT write set any tier it likes without "
            "this check having anything to compare against. Keep the tier as it is; to change "
            'it, walk away from this ticket (action "abandon: …") and reclassify.'
        )
    # The other half of the same two-write move — planting any tier onto a state
    # that records none — is deliberately NOT refused here. A tier legitimately
    # reappears from nothing on more than one edge: entering CLASSIFY, and
    # resuming a paused ticket out of IDLE, where the tier is restored rather
    # than assigned. Refusing it by shape breaks both. What closes the exploit
    # is the check above: the tier-less state is now unreachable through a
    # write, so nothing arrives at this line by dropping one.
    new_tier = raw_new if raw_new is not None else old_tier
    if not old_tier or old_tier == new_tier:
        return
    # Only CLASSIFY assigns a tier, so the only legal change is the one that
    # leaves CLASSIFY — or a reset to IDLE, which clears it.
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
    (CLOSEOUT→DEFINE, or its equivalent) is not in the graph. A model told to fix
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


def _gate_owners(graph, tier):
    """gate → the phases that may claim it, derived from the graph.

    A gate is EARNED in the phase whose work produces its evidence, and the
    graph already says which phase that is: an edge `A->B` demanding gate `g` is
    the statement that `g` is what leaving A costs. So the phases that own `g`
    are the sources of the edges that ask for it.

    Nothing enforced that. `transition.py --claim` checked only that the name is
    a known gate and that its evidence exists, and never read the phase; a raw
    Write that appends no history returns early in `validate`, so it was not
    covered either. Under QUICK-FIX, `CODE->CLOSEOUT` costs define, tests and
    sast — three booleans that could all be set while sitting in DEFINE, before
    a line of the fix existed. `transition.py` states the contract ("in the
    phase that owns it") in its own `--claim` help text, and nothing held it.

    Several owners is normal: QUICK-FIX asks `define` on both `DEFINE->CODE` and
    `CODE->CLOSEOUT`, so both phases may claim it. A gate no edge asks for has no
    owner, and it fails closed — a gate nothing spends is not one anything earns.
    """
    owners = {}
    for name, spec in _effective_edges(graph, tier).items():
        src = name.split("->", 1)[0]
        for gate in (spec or {}).get("gates") or []:
            owners.setdefault(gate, set()).add(src)
    return owners


def _check_gate_owner(old_state, new_state, graph, appended):
    """A gate may only be set true in a phase the graph says earns it.

    Judged against the phase the work was done IN, which for a write that also
    takes an edge is the phase being LEFT, not the one being entered:
    `--to PLAN --gate define` is the ordinary shape of finishing DEFINE, and
    reading the destination there refuses the whole happy path.
    """
    if len(appended) > 1:
        # A replay of a whole run (post mode), not a claim. Each edge is judged
        # on its own terms there; there is no single phase this is "in".
        return
    if appended and _is_resume(appended[0]):
        # Resuming a paused ticket RESTORES the gates it had already earned.
        # Reaching IDLE wipes them, so every one of them looks newly claimed
        # here, and the edge comes from IDLE, which owns nothing — so judging a
        # resume by this rule refuses every pause, which is the exit the method
        # advertises as costing nothing. What those gates are worth on the way
        # back is the resume check's question, not this one's.
        return
    tier = new_state.get("tier") or old_state.get("tier")
    if not tier:
        return                          # no tier, no pipeline to own anything yet
    old_gates = old_state.get("gates") or {}
    new_gates = new_state.get("gates") or {}
    if not isinstance(new_gates, dict):
        return                          # shape is another check's business
    claimed = sorted(g for g, v in new_gates.items() if v and not old_gates.get(g))
    if not claimed:
        return
    try:
        owners = _gate_owners(graph, tier)
    except Block:
        return                          # a graph that will not resolve is reported elsewhere
    phase = appended[0].get("from") if appended else new_state.get("phase", IDLE)
    for gate in claimed:
        allowed = owners.get(gate, set())
        if phase in allowed:
            continue
        where = (", ".join(sorted(allowed)) if allowed else None)
        raise Block(
            f"`{gate}` cannot be claimed in {phase}: " + (
                f"under tier {tier} it is earned in {where}."
                if where else
                f"no edge in tier {tier} asks for it, so nothing spends it and nothing earns it."
            ) + " A gate is the evidence that a phase's work was done, so claiming it from "
            "another phase records work that has not happened yet. Take the transitions in "
            "order and claim it where it is earned."
        )


def validate(old_state, new_state, graph, tool_name=None, max_appended=1,
             gates_scope="all", skip_edges=0, state_path=None):
    old_h, new_h = _check_append_only(old_state, new_state)
    appended = new_h[len(old_h):]

    # Before any early return: a write that appends nothing can still change the
    # tier, and that was enough to walk another tier's shortcut.
    _check_tier(old_state, new_state, appended)
    # `max_appended is None` is post mode's replay and nothing else: the hook
    # path and the helper both pass a cap. The two newest rules read it so they
    # judge the edge being taken now, not the run already taken.
    _replaying = max_appended is None
    _check_free_is_the_users_word(old_state, new_state, appended, replaying=_replaying)
    _check_the_ticket_has_a_name(new_state, appended, replaying=_replaying)
    _check_autonomy(old_state, new_state, appended)
    _check_ticket_continuity(old_state, new_state)
    _check_entry_ticket(old_state, new_state, appended)
    _check_idle_invariant(new_state)
    _check_ticket_shape(new_state)
    # Also before the early return: an in-phase write is exactly how a gate is
    # claimed, so the phase it is claimed from has to be judged here or nowhere.
    _check_gate_owner(old_state, new_state, graph, appended)
    _check_gates_have_a_ticket(new_state)

    old_phase = old_state.get("phase", IDLE)
    new_phase = new_state.get("phase", IDLE)

    # A single write declares a single transition. Without this, one Write could
    # append the entire pipeline — IDLE through CLOSEOUT, every gate asserted at
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

    # Time moves forward, or the record cannot be read in the order it happened.
    #
    # The shape was validated and the VALUE was not, so a new entry could be
    # dated six years before the one above it and land without a word. Two ways
    # that happens for real: a machine whose clock is wrong — a container, a VM
    # resumed from a snapshot — and somebody editing the file by hand. Both
    # produce the same thing, which is the one artefact this method promises will
    # still make sense in six months: a history that says a ticket was defined
    # before it was classified.
    #
    # Compared as strings on purpose. The format is already pinned to
    # `YYYY-MM-DDThh:mm:ssZ` by the check above, and in that format lexical order
    # IS chronological order — no parsing, no timezone arithmetic, nothing that
    # can raise on the way to a verdict. Equal timestamps are allowed: two
    # transitions inside the same second are ordinary, and a clock with
    # one-second resolution is not evidence of anything.
    _prev = [e for e in old_h if isinstance(e, dict) and isinstance(e.get("timestamp"), str)]
    _last = _prev[-1]["timestamp"] if _prev else ""
    for entry in appended:
        if _last and entry["timestamp"] < _last:
            raise Block(
                "history goes backwards in time: this entry is stamped %s and the one before it "
                "%s. The history is the record somebody reads six months from now; one that "
                "cannot be read in order is not one. If this machine's clock is wrong, fix the "
                "clock — the entry cannot be written as if it were not."
                % (entry["timestamp"], _last)
            )
        _last = entry["timestamp"]

    # Internal contiguity.
    for a, b in zip(appended, appended[1:]):
        if a["to"] != b["from"]:
            raise Block(
                f"history is not contiguous: {a['from']}→{a['to']} followed by "
                f"{b['from']}→{b['to']}"
            )

    # Connection to the previous state (with IDLE↔CLASSIFY leniency).
    # The appended run has to start where the state actually is. There used to be
    # a hatch for `IDLE → (a run beginning at CLASSIFY)`, and it let ONE write
    # skip CLASSIFY entirely: a state at IDLE, a history whose first appended
    # entry says it came from CLASSIFY, and the write lands in DEFINE having
    # never been classified — carrying whatever `autonomy` it liked, since
    # `_check_autonomy` allows the field on any edge touching CLASSIFY. A
    # leniency about where a run STARTS cannot also be a leniency about what it
    # skipped.
    first_from = appended[0]["from"]
    if first_from != old_phase:
        raise Block(
            f"the first transition starts at {first_from} but the previous state "
            f"is at {old_phase}. History is appended to what is ON DISK: re-read "
            ".ddw-state.json and append from the phase it actually holds. If the run really "
            f"is at {first_from}, the edge that got there has to be written and validated "
            "first — one write, one transition."
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
        # An edge the journal already blessed was legal when it landed, and a
        # graph that changed afterwards — an upgrade mid-ticket — does not make
        # it illegal now. `skip_edges` is that window, and it is only ever
        # non-zero in post mode's replay.
        if src == dst:
            raise Block(
                f"a transition must go somewhere: {key}. An in-phase change — claiming a gate, "
                "filling in the title — carries NO history entry: write the new state without "
                "appending one, or use `.ddw/scripts/transition.py --claim <gate>`, which builds "
                "exactly that write.")
        if src == IDLE and dst != CLASSIFY and _is_resume(entry):
            # Coming back to a ticket that was paused. It owes no gates — pausing
            # owed none either, and the gates it had earned come back with it.
            # But it has to BE a resume: proven by a pause, from this phase.
            _resume_allowed(entry, old_h + appended, len(old_h) + idx)
            # …and proven by a pause the JOURNAL saw, not merely one the file
            # claims. This branch skips the graph and skips the gates — it is the
            # one edge in the machine that does — so what it rests on has to be
            # something the forger does not also write. The history is the state
            # file, and the state file is exactly what a shell rewrites.
            #
            # Measured: one shell write of a history containing a single
            # `pause:` entry from CODE, then the SANCTIONED helper resuming into
            # CODE — no ticket, no tier, no receipt, gates `{}`, both hooks
            # green, and product source writable on the next call. Every gate in
            # the pipeline skipped by inventing a pause that never happened.
            #
            # The journal is append-only, written by post mode when a transition
            # actually lands, and already carries every edge. A pause it never
            # recorded is a pause that never happened.
            if state_path:
                _resume_needs_a_recorded_pause(state_path, entry, dst)
            # Except the two that describe the world outside this repository.
            # A pause at CLOSEOUT is a pause waiting on a person, and days pass:
            # the pull request can be closed, the branch can be force-pushed,
            # the commit can be gone. `commit` and `pr` come back false and get
            # asked again — one question to git, one to the forge, both instant.
            # Without this the closeout is satisfied by a gate earned before the
            # wait, because a gate already true is never re-asked.
            if dst == "CLOSEOUT":
                stale = [g for g in ("commit", "pr") if gates.get(g) is True]
                if stale:
                    raise Block(
                        "resuming at CLOSEOUT has to ask again about what happened while you were "
                        f"away: {', '.join(stale)} came back true. Days passed — the pull request "
                        "may have been closed and the branch may have moved. Drop them and earn "
                        "them again; both are instant."
                    )
            continue
        if src == IDLE and dst != CLASSIFY and _is_split_open(entry):
            # Opening a sub-ticket of an approved split, directly in the phase
            # its parent paused from. Skips the graph the way a resume does, and
            # rests on the same kind of proof — see `_split_open_allowed`.
            _split_open_allowed(entry, old_h + appended, len(old_h) + idx)
            if state_path:
                _split_needs_a_recorded_pause(state_path, entry, dst)
            # A resume RESTORES gates already earned; a split child has earned
            # nothing — its run starts on this edge. Gates riding in on it were
            # written, not earned.
            if idx == len(appended) - 1 and any(v is True for v in gates.values()):
                raise Block(
                    "a split child opens with no gates: its run starts on this edge, and "
                    f"{', '.join(sorted(g for g, v in gates.items() if v is True))} rode in "
                    "already true. Whatever the parent earned closed with the parent; the "
                    "child earns its own."
                )
            continue
        if dst == IDLE and _is_walkaway(entry):
            # Walking away — abandon or pause. Always allowed, from anywhere the
            # graph does not forbid it, gated by nothing: the work is not going
            # to ship, so there is nothing to demand of it. It must SAY so, since
            # a closeout takes the same edge and does owe its gates.
            if _walkaway_blocked(graph, src):
                # One exception, and it is narrow on purpose: a PAUSE at CLOSEOUT
                # whose `commit` and `pr` are already paid for.
                #
                # The rule exists because "abandon" would otherwise be a skeleton
                # key — relabel the exit and ship with no commit and no PR. That
                # reasoning does not cover the case it was catching in practice:
                # the work IS committed, the pull request IS open, and what you
                # are waiting for is another person. Refusing there does not
                # protect anything; it just means the ticket sits in CLOSEOUT for
                # two days while you cannot start anything else, because there is
                # one state per directory.
                #
                # An abandon is still refused here, which is what the skeleton
                # key was about. And both gates are read from the state BEFORE
                # this write, so the same write cannot grant them and spend them.
                # `check_gates` for the same reason as `clears` above: post mode
                # replays from a synthetic prior whose gates are {}, so `paid`
                # read false for EVERY legitimate pause and condemned it — the
                # feature that exists so you can walk away for two days locked
                # the directory for exactly those two days.
                paid = (all(gates_before.get(g) is True for g in ("commit", "pr"))
                        if check_gates else True)
                if not (_is_pause(entry) and paid):
                    missing = [g for g in ("commit", "pr") if gates_before.get(g) is not True]
                    detail = ("an abandon" if not _is_pause(entry)
                              else "a pause with " + ", ".join(missing) + " unpaid")
                    raise Block(
                        f"you cannot walk away from {src} with {detail}: at this point nothing is "
                        "left to decide, only steps to finish. A pause is allowed here ONLY once "
                        "`commit` and `pr` are true — the work is committed, the pull request is "
                        "open, and what you are waiting for is a person. Anything else is a "
                        "closeout that owes its gates."
                    )
            continue
        if key not in edges and idx >= skip_edges:
            hint = ""
            if dst == IDLE and not _walkaway_blocked(graph, src):
                hint = (
                    ' To leave this ticket without closing it out, set the entry\'s "action" to '
                    '"abandon: <reason>" (dropped for good) or "pause: <reason>" (set aside).'
                )
            raise Block(f"transition {key} is not in the graph for tier {tier!r}.{hint}")
        edge_cfg = edges.get(key)
        if edge_cfg is None:
            # Inside the blessed window and no longer in the graph: the edge was
            # legal when it landed and the graph moved under it. Nothing left to
            # check about a step already taken.
            continue
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
                    # The MOVE, not only the fact. This is the most-read
                    # refusal in the product, and it named a state of the world
                    # ("is not true") with nothing about how to make it true —
                    # so the model's next act was to edit the state by hand,
                    # which the hook then refused for a different reason.
                    earn = _EARNED_BY.get(gate)
                    how = (" Earn it first: run %s over the document that phase writes, then "
                           "`.ddw/scripts/transition.py --claim %s` (one run, no phase change), "
                           "and take this edge after that." % (earn, gate)) if earn else (
                          " `commit` is git's answer and `pr` is the forge's: commit the work, or "
                          "open the pull request, and this edge stops asking.")
                    raise Block(f"gate {gate!r} required for {key} is not true.{how}")

        # Going back takes away what going forward granted, and the rule lives
        # HERE — in the function the hook calls — not in the helper.
        #
        # Clearing them in the helper alone is the shape of defect this file has
        # been bitten by twice: a hand-written state stepped back, kept the
        # gates, rewrote the artifact and stepped forward again, and nothing
        # asked for a receipt, because evidence is owed only when a gate is
        # claimed for the FIRST time. That is a rewritten PRD laundered through
        # the pipeline's own recovery path. Measured on the version before this.
        cleared = edge_cfg.get("clears", [])
        if not isinstance(cleared, list):
            raise Block(f"malformed graph: the `clears` of {key!r} is not a list")
        # Only against the state this write is actually producing — never against
        # a replay. `gates` in post mode is the CURRENT snapshot, not the one
        # that edge was taken under, so the moment a backward step's gate was
        # re-earned the replay saw the old edge holding it and condemned the
        # whole run. The post matcher fires on every Bash, Edit and Write, and
        # history is append-only: the repository was bricked, permanently, by
        # completing the corrective loop the pipeline documents. Measured through
        # the sanctioned helper, with nothing hand-written.
        still_held = [g for g in cleared if gates.get(g) is True] if check_gates else []
        if still_held:
            raise Block(
                f"{key} goes back a phase, so it must give up what that phase granted: "
                f"{', '.join(sorted(still_held))} is still true. Going back is always allowed "
                "and always costs — the work from here on has to be earned again, against the "
                "artifacts as they now are. Use `.ddw/scripts/transition.py`, which drops them "
                "for you."
            )

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
# Phases whose rules forbid touching product source. CLOSEOUT is not here: it
# writes the CHANGELOG and its own gates already close it. FREE is not here
# either, and that is the whole point of FREE.
#
# IDLE IS here now, and its absence was the hole the paragraph above predicts,
# one phase further out. "An agent that never bothers to transition can write
# code from PLAN" — and an agent that never CLASSIFIES writes it from where
# every session already starts, which needs no transition at all. Measured in a
# real session: asked plainly, the model classified and refused to code; told
# "no ticket, just write it", it wrote the file, both hooks green, the state
# still IDLE and no record anywhere that a line of product code had been
# written. Every other hole this repository has closed took a trick — a symlink,
# a placeholder, a backdated clock. This one took nothing.
#
# The point is not that the code was written. It is that it was written with
# nobody having decided to. Which is why the way out is not a loophole but a
# tier: `--tier FREE` is a transition, in the history, with a timestamp and a
# reason, and the session says ESTÁS TRABAJANDO SIN WORKFLOW for as long as it
# lasts. A user who wants no pipeline gets exactly that, on the record.
#
# What stays writable at IDLE is what a repo at rest legitimately needs: the
# context files and the CHANGELOG, each tool's wiring, and everything under
# `docs/` — so installing, ejecting, reading and writing documents need no
# ticket.
NO_SOURCE_PHASES = frozenset({"IDLE", "CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY"})

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
    # CLOSEOUT.
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


def lexical_in_repo(path, root):
    """The path as WRITTEN, anchored to the repo, with no symlink resolved.

    `resolve_in_repo` follows symlinks, and it has to: that is what stops a
    guarded file being written under an unguarded name. But the sealed lists are
    about NAMES — `.ddw/`, `.ddw-sessions/`, `.claude/settings.json` — and
    resolving first answers the question about a different name. With `.ddw`
    made a symlink to a directory outside the repository, writes to
    `.ddw/rules/transition-graph.json` and `.ddw/scripts/hook-gate.py` resolved
    outside, so `enforcement_write_denied` said "not ours" and returned 0, while
    `src/app.ts` in the same phase returned 2.
    (`.ddw-sessions/`, `.ddw-installed.json` and `.claude/settings.json` were
    NOT affected — measured — because nothing had moved those.)

    So both readings are judged: the resolved one catches a guarded file reached
    under another name, and this one catches another file reached under a
    guarded name. Neither subsumes the other.

    One thing IS resolved here, and only one: the repository root itself. `root`
    arrives already resolved, and a root can perfectly well be written through a
    symlink of its own — `/var` is `/private/var` on every macOS, which is where
    a temporary checkout lives, and a repo behind a symlinked path is ordinary
    anywhere. Compared as written, such a path sits "outside the repository" for
    the whole of its length, so every sealed name under it went unjudged and
    this reading protected nothing on that platform. Measured: the seal held on
    Linux and not on macOS, in CI, from the same source.

    The prefix that resolves TO the root is replaced by the root; the components
    below it stay exactly as written, because those are the names this reading
    exists to judge.
    """
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    path = os.path.normpath(path)
    if path == root or path.startswith(root + os.sep):
        return path
    parts = path.split(os.sep)
    for i in range(len(parts), 0, -1):
        prefix = os.sep.join(parts[:i]) or os.sep
        try:
            if os.path.realpath(prefix) == root:
                rest = parts[i:]
                return os.path.join(root, *rest) if rest else root
        except OSError:
            continue                      # unreadable ancestor: keep it as written
    return path


def _outside_repo(target, root):
    """Is this resolved path outside the repository DDW is guarding?

    Written once because three callers were asking it, each with its own copy of
    the same `os.pardir` comparison — and the fourth caller, the one that needed
    it most, did not ask at all.
    """
    rel = os.path.relpath(target, root)
    return rel == os.pardir or rel.startswith(os.pardir + os.sep)


# DDW's own enforcement, which no phase may write. Not a matter of what a phase
# is for — a matter of what the pipeline IS.
#
#   .ddw/             the method: the graph, the rules, the validator, the gate
#   .ddw-sessions/    the receipts six of the eight gates read
#   .ddw-journal.jsonl the append-only record the erase check compares against
#
# `.ddw-state.json` and `.ddw-paused/` are deliberately NOT here: writing the
# state is how the pipeline advances, and that write is what every other rule in
# this file judges.
PROTECTED_PREFIXES = (".ddw/", ".ddw-sessions/")
# The files that WIRE the gates to each tool. DDW merges one key into these
# rather than owning them — your own settings live in the same file — so they
# carry no manifest hash, and without naming them here the whole protection was
# one `Write` away from being switched off at the source: delete DDW's `hooks`
# key from `.claude/settings.json` and nothing runs again.
#
# A closed set, because these are DDW's own adapters (`adapters/*/adapter.json`,
# `settings_merge.to`) rather than a guess about your project.
PROTECTED_FILES = frozenset({
    ".ddw-journal.jsonl",
    ".claude/settings.json", ".codex/hooks.json",
    ".cursor/hooks.json", ".gemini/settings.json",
})
# And the directories those adapters install their hook scripts INTO — the
# `wiring.to` of each `adapters/*/adapter.json`.
#
# Every one of these paths was protected only by `_manifest_paths`, which reads
# `.ddw-installed.json` and returns an empty set when it cannot. So `rm
# .ddw-installed.json` — one innocuous-looking JSON file, nothing else — turned
# a refused write to `.claude/hooks/validate-state-transition.sh` into exit 0.
# Measured: `.claude/settings.json` and `.ddw/` stayed sealed, because they are
# named above; every hook script fell open, because none of them was.
#
# What this actually buys is narrower than it looks, and saying so is the point:
# whoever can delete the manifest has a shell, and a shell could already write
# the hook without any of this seeing it (decision 11). It closes the case where
# the manifest is absent for an ordinary reason — a clone that never committed
# it — and leaves a repository in that state as protected as one that did.
#
# A closed set for the same reason as above: these are DDW's own adapters, not a
# guess about your project. `scripts/verify_install.sh` holds it to what the
# adapters actually declare.
PROTECTED_WIRING_DIRS = (
    ".claude/hooks/", ".codex/hooks/ddw/", ".cursor/hooks/ddw/",
    ".gemini/hooks/ddw/", ".github/hooks/", ".opencode/plugins/",
)
INSTALL_MANIFEST = ".ddw-installed.json"


def _manifest_paths(root):
    """Every file the installer put in this repo, from `.ddw-installed.json`.

    The manifest was written at install time, listed each file with its sha256,
    and nothing at runtime had ever opened it. It is the only thing that knows
    which of `.claude/hooks/*.sh` is DDW's gate and which is the user's own hook,
    so it is what makes the refusal below precise instead of a blanket ban on a
    directory the user also lives in.
    """
    out = set()
    try:
        with open(os.path.join(root, INSTALL_MANIFEST), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    for key in data:
        # "claude:.claude/hooks/enforce.sh" — the tool, then the path.
        rel = key.split(":", 1)[1] if ":" in key else key
        if isinstance(rel, str) and rel:
            out.add(rel.replace(os.sep, "/"))
    return out


def enforcement_write_denied(target, root):
    """A write to the machinery that does the enforcing. Refused in EVERY phase.

    This existed only inside `source_write_denied`, which returns early for CODE
    and CLOSEOUT — so the protection covered exactly the phases where the agent
    cannot write anything anyway, and stood down in the one where it works. In
    CODE the agent could rewrite `.ddw/rules/transition-graph.json` to add an
    edge, rewrite `validate-transition.py` itself, replace the tool's hook script
    with `exit 0`, or simply write its own receipt into `.ddw-sessions/` and open
    all six receipt gates with a touch. Measured, end to end, on a real install:
    a FEATURE closed having never claimed tests, sast, verify, commit or pr, with
    both hooks green.

    What this does NOT reach is the shell (`docs/RATIONALE.md` decision 11): a
    `printf > .ddw/...` is not a tool call with a path in it. That is why the
    manifest also carries a hash, and why the boot reports drift — prevention
    where a path is visible, detection where it is not. Said plainly rather than
    implied, because a guard whose scope is unstated gets read as total.
    """
    if _outside_repo(target, root):
        return None
    rel = os.path.relpath(target, root).replace(os.sep, "/")
    what = None
    if rel == INSTALL_MANIFEST:
        what = "the record of what DDW installed"
    elif any(rel.startswith(p) for p in PROTECTED_PREFIXES):
        what = "part of DDW itself"
    elif rel in PROTECTED_FILES:
        what = "what wires DDW's gates into this tool"
    elif any(rel.startswith(p) for p in PROTECTED_WIRING_DIRS):
        what = "where DDW's hooks are installed for this tool"
    elif rel in _manifest_paths(root):
        what = "a file DDW installed, and the wiring that makes the gates run"
    if what is None:
        return None
    return (
        f"`{rel}` is {what}, and no phase writes it. A pipeline that can edit the rules that "
        "stop it is not enforcing anything — this is the one refusal that holds in CODE too. "
        "To change how DDW is installed here, run `install.sh` (or `uninstall`) yourself, "
        "outside the ticket; to change your own settings in that file, do it between tickets."
    )


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

    if phase == IDLE:
        # From IDLE there is no phase to finish and no ticket to finish it for,
        # so the two real answers are: start one, or say out loud that you are
        # not going to.
        # Without the recipe for the unenforced tier.
        #
        # This message used to carry it: `--to CLASSIFY --tier FREE` and then
        # `--to FREE`. Measured with a live model — it read the refusal, took
        # those two steps on its own, and wrote the file. It obeyed both
        # halves of the same message: the block and the way around it.
        #
        # Working without the pipeline is the USER's decision, and that was
        # FREE's premise from the day it was added. Offering it to the model
        # inside the refusal turns it into the model's decision, which is the
        # opposite. The tier still exists, `classify.instructions.md` still
        # teaches when it applies, and the path stays open — for whoever asks.
        unlock = ("Nothing is open here: classify the work with `--to CLASSIFY`, and the tier "
                  "decides what it owes before CODE. If the user does not want a pipeline for "
                  "this at all, that is theirs to say — ASK them, and classify with the tier "
                  "they name. It is not a step you take on your own to get past this. ")
    else:
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

    # Lowercased on both sides. The patterns are written lowercase and the list
    # calls itself deliberately wide, but `fnmatch` is case-sensitive on Linux —
    # so `app/Http/Middleware/`, `src/API/`, `db/Migrations/` and `.SQL` walked
    # straight past a guard whose whole design is to stop them. The convention
    # that capitalises directories is the norm in several ecosystems, which is
    # to say the guard was widest exactly where it was least likely to bite.
    probe = "/" + rel.lower()
    for pattern in QUICKFIX_SENSITIVE:
        if fnmatch.fnmatch(probe, pattern):
            return (f"`{rel}` is security-sensitive, and QUICK-FIX is the lane that skips both "
                    f"the threat model and verification. {QUICKFIX_ESCALATE}")

    loc = _branch_insertions(root)
    if loc is not None and loc > QUICKFIX_LOC_LIMIT:
        return (f"this branch has grown to {loc} added lines of code, over the QUICK-FIX limit "
                f"of {QUICKFIX_LOC_LIMIT}. {QUICKFIX_ESCALATE}")
    return None


# The artifacts a standing gate rests on, and the phase that owns each. The
# graph already clears these gates on the way back — `CODE->PLAN` clears `spec`
# and `threat` — so the seal and the release are the same fact read twice.
SEALED_BY_GATE = (
    ("spec", "PLAN", "docs/ddw/specs/spec-{ticket}.md"),
    ("threat", "PLAN", "docs/ddw/security/threat-{ticket}.md"),
)


def sealed_artifact_denied(target, root, state):
    """Is this a write to an artifact whose gate is already standing?

    `target` and `root` must already be realpath-resolved. Returns the reason to
    refuse, or None to allow.

    A gate is a claim about a document a human approved. Round 6 measured what
    happens while the document stays writable underneath it: CODE found a real
    error in the spec, said it would "leave it recorded in VERIFY" — a place
    that does not exist — and moved on. The gap survived to the end of the
    ticket. Editing it in place would have been worse: the spec would have
    changed shape under a `spec` gate nobody re-earned, which is the laundering
    the graph's `clears` was written to stop, arriving by another door.
    Correcting the spec is not forbidden; correcting it HERE is. The way is the
    edge that already exists, and it costs the approval it should cost.
    """
    ticket = (state.get("ticket") or "").strip()
    if not ticket:
        return None                                  # no ticket, no artifact of its own
    if _outside_repo(target, root):
        return None
    gates = state.get("gates") or {}
    rel = os.path.relpath(target, root).replace(os.sep, "/")
    phase = state.get("phase", IDLE)
    for gate, owner, template in SEALED_BY_GATE:
        if not gates.get(gate):
            continue                                 # not earned yet — this is where it is written
        if rel.lower() != template.format(ticket=ticket).lower():
            continue
        return (f"`{rel}` is what the `{gate}` gate was earned on, and that gate is standing. "
                f"{phase} does not rewrite an approved artifact — a document that changes shape "
                f"under a gate nobody re-earned is exactly what the pipeline promises cannot "
                f"happen. If it is wrong, it is wrong for everyone downstream: go back to "
                f"{owner} (the {phase}→{owner} edge is in the graph and clears `{gate}`), fix it "
                f"there, re-validate, and re-earn the gate. Say out loud that you are going back "
                f"and why, so the approval that follows is read as the re-approval it is.")


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
# All eight gates have an answer, and they are not the same answer — which is the
# distinction this comment used to get wrong. It said five, and named `tests`,
# `sast` and `pr` as claims nothing could confirm, sixty lines above the handlers
# that confirm them.
#
#   six of them  resolve a content-hashed receipt over the document the phase
#                produced, so what is attested is that the DOCUMENT is complete —
#                never that the work it describes was done. DDW does not run your
#                suite and does not scan your code.
#   `commit`     asks git.
#   `pr`         asks the forge, through `gh`.
#
# That split is a decision rather than an unfinished job, and `docs/RATIONALE.md`
# decision 16 has the table.


def _receipt_witnesses(state_path_root):
    """The receipts the journal records a validator as having written.

    Returns None when there is no journal AND no run — "unknown", never "empty".
    Without a journal there is nothing to have recorded anything, and refusing on
    that basis would refuse a repo where DDW has simply never run.

    A repo whose STATE already holds transitions is not that repo. There, a
    missing journal is a journal that was removed, and `rm .ddw-journal.jsonl`
    was the whole bypass: with the witness unknown, a receipt written by hand
    opened its gate, in one command, on a run that was already under way. The
    docstring of `read_gates_snapshot` promises that removing the journal makes
    post mode STRICTER; this is that promise reaching the receipts. The cost is
    re-running the validators that earned them, which is the same cost the
    upgrade path already pays, and the refusal says so.

    Where there IS a journal, the answer is the set, even when it is empty. A
    repo upgrading mid-run therefore has to re-run its validators, and the
    refusal says so; that is a minute of work, and the alternative is a hatch
    that stays open forever because somebody might once have needed it.
    """
    if not os.path.exists(journal_path(os.path.join(state_path_root, ".ddw-state.json"))):
        try:
            with open(os.path.join(state_path_root, ".ddw-state.json"), encoding="utf-8") as fh:
                started = bool((json.load(fh) or {}).get("history"))
        except (OSError, ValueError, AttributeError):
            return None
        return set() if started else None
    entries = _journal_lines(os.path.join(state_path_root, ".ddw-state.json"))
    names = {e.get("name") for e in entries
             if isinstance(e, dict) and e.get("record") == "receipt"}
    names.discard(None)
    return names


def _receipt_unwitnessed(root, marker_name):
    """A receipt on disk that no validator is recorded as having written.

    The pre-write hook refuses a Write to `.ddw-sessions/`, in every phase. A
    shell is not a tool call with a path in it, so `printf > .ddw-sessions/
    prd-validated-abc123` still reaches the disk — and a receipt is just a file,
    indistinguishable from an earned one by looking at it. What distinguishes
    them is that an earned one was written by `validate_*.py`, which now says so
    in the journal.

    This does not make forgery impossible: the same shell can write both files.
    It makes it two coordinated writes instead of one, and leaves the second in a
    record that outlives deleting the state. `docs/RATIONALE.md` decision 11 is
    the honest version of what a local guard can and cannot promise.
    """
    witnessed = _receipt_witnesses(root)
    if witnessed is None or marker_name in witnessed:
        return None
    return ("`.ddw-sessions/%s` is on disk and no validator is recorded as having written it. "
            "A receipt is written by `validate_*.py` when it PASSES, and writing one by hand "
            "attests to a validation that did not happen. Run the validator for this document. "
            "(If DDW was upgraded mid-ticket, receipts earned before the upgrade carry no record "
            "either — re-running the validator is the whole fix.)" % marker_name)


def _receipt_spent(root, gate, marker_name, ticket=None):
    """Was this receipt earned BEFORE the corrective loop took the gate back?

    The journal is ordered, so the question is a comparison of positions: the
    last line recording `gate` as spent, against the line recording this receipt
    as written. A receipt that predates the spending attests to work done before
    the code changed.

    Returns None when there is no journal to read — the same "unknown, never
    empty" rule the witness check uses, for the same reason.
    """
    entries = _journal_lines(os.path.join(root, ".ddw-state.json"))
    if not entries:
        return None
    spent_at = written_at = None
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if entry.get("record") == "spent" and gate in (entry.get("gates") or []):
            # The spending names its ticket, and the comparison has to too: the
            # last `spent` used to be read globally, so a CLOSED ticket's receipts
            # started reading as spent the moment a LATER ticket's corrective
            # loop touched the same gate (measured: FEAT-001a's spec receipt,
            # under FEAT-001b's loop). A record without a ticket stays binding —
            # unknown is never an exemption.
            if ticket is None or entry.get("ticket") in (None, ticket):
                spent_at = i
        elif entry.get("record") == "receipt" and entry.get("name") == marker_name:
            written_at = i
    if spent_at is None:
        return None
    if written_at is not None and written_at > spent_at:
        return None
    return ("the %s gate was cleared by a corrective loop after this receipt was written, so the "
            "receipt attests to a run from before the code changed. A test or SAST report is a "
            "report ABOUT the code, and its own bytes do not change when the code does — which is "
            "why re-running it is the only thing that can say the fix holds. Run the validator "
            "again and claim the gate with the new receipt." % gate)


def _receipt_missing(root, state, gate, receipt, subdir, stems, script, artifact):
    """One gate, one artifact, one receipt naming that artifact's CURRENT bytes.

    Content-hashed on purpose. A receipt keyed on the filename would go on
    attesting to a document that has since been rewritten — which is the same
    claim-without-evidence in a file, and harder to notice.

    **A missing artifact is a refusal, not a pass.** It used to return None here
    — "no artifact on disk means no claim to check" — and that sentence is false
    at every call site: this function is reached ONLY for gates being claimed
    (`decide_pre` passes `_gates_newly_claimed`, `decide_post` passes what the
    landed edges require, `transition.py` passes `--gate`). The claim has already
    been made by the time we look. Measured on a real install: a FEATURE walked
    IDLE→CLOSEOUT with **no PRD, no spec, no threat model, no test report, no
    SAST report and no verdict**, six gates true, both hooks green, nothing on
    disk at all. Six of the eight gates were decoration whenever the document
    simply did not exist — which is the easiest state in the world to be in.

    Unreadable is a refusal too, for the same reason: one stray non-UTF-8 byte in
    the document turned the refusal into a pass.

    This is the table decision 16 promised — adding a gate is a row here plus a
    validator that writes the receipt, not new machinery.
    """
    ticket = state.get("ticket")
    if not ticket:
        return None
    tried = ["docs/ddw/%s/%s-%s.md" % (subdir, stem, ticket) for stem in stems]
    path = None
    for stem, rel in zip(stems, tried):
        cand = os.path.join(root, "docs", "ddw", subdir, "%s-%s.md" % (stem, ticket))
        if os.path.isfile(cand):
            path = cand
            break
    if path is None:
        where = tried[0] if len(tried) == 1 else " or ".join("`%s`" % t for t in tried)
        return ("the %s gate is being claimed for ticket %s and there is no %s to claim it for. "
                "Expected %s. Write it, then run `python3 .ddw/scripts/%s <file> --tier <tier>` — "
                "a PASSED run writes the receipt this gate reads."
                % (gate, ticket, artifact, where if len(tried) > 1 else "`%s`" % where, script))
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
    except (OSError, UnicodeDecodeError) as exc:
        # Also a refusal. A document nothing can read is a document no receipt
        # can name, and returning None here meant one stray non-UTF-8 byte
        # converted the gate from enforced to decorative.
        return ("the %s gate needs to read %s and could not (%s). A receipt names the bytes of a "
                "document; a document that cannot be decoded as UTF-8 has none this can check. "
                "Fix the file's encoding and validate it again."
                % (gate, os.path.relpath(path, root), type(exc).__name__))
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
                lines = fh.read().splitlines()
        except OSError:
            lines = []
        named = lines[0].strip() if lines else ""
        # …and it has to be a receipt earned under the rules THIS ticket is
        # being held to. The tier selects which rules a validator runs, and no
        # validator recorded which one it was asked for: the same bytes that
        # FAILED as a FEATURE PASSED as a QUICK-FIX and wrote a receipt this
        # gate could not tell apart. The state's tier is the authority — the
        # receipt's prefix is not, because the define gate reads an `rca-`
        # document for tier FIX, so prefix and tier legitimately differ.
        #
        # A receipt with no tier line was written before validators recorded it.
        # Refusing those would strand every ticket mid-flight on upgrade, for a
        # document that really was validated, so they are accepted as they were.
        stamped = next((ln.split(":", 1)[1].strip() for ln in lines[1:]
                        if ln.split(":", 1)[0].strip().lower() == "tier" and ":" in ln), "")
        if stamped and state.get("tier") and stamped != state.get("tier"):
            return ("the %s gate has a receipt for %s, but it was validated under `--tier %s` "
                    "while this ticket is tier %s. The tier decides which rules run, so that "
                    "receipt does not say this document passes the rules this ticket is held "
                    "to. Run `python3 .ddw/scripts/%s %s --tier %s`."
                    % (gate, os.path.relpath(path, root), stamped, state.get("tier"),
                       script, os.path.relpath(path, root), state.get("tier")))
        # …and under the clock this ticket is actually running on. `--today` is
        # the caller's to choose, and it decides whether a suppression has
        # expired: the same SAST report passed with suppressions six months
        # lapsed by naming a day they were fresh, and wrote a receipt no gate
        # could tell from one earned this morning. So the day is on the receipt,
        # and a receipt earned against some other day is refused — re-running
        # the validator costs seconds and answers the question honestly.
        #
        # Only SAST records one, and a receipt without the line is one written
        # before this existed: accepted, for the same reason the tier line is.
        asof = next((ln.split(":", 1)[1].strip() for ln in lines[1:]
                     if ln.split(":", 1)[0].strip().lower() == "asof" and ":" in ln), "")
        today = datetime.date.today().isoformat()
        if asof and asof != today:
            return ("the %s gate has a receipt for %s, but it was earned against the date %s and "
                    "today is %s. That date decides which suppressions have expired, so the "
                    "receipt does not say this report passes as of today. Run `python3 "
                    ".ddw/scripts/%s %s --tier %s`."
                    % (gate, os.path.relpath(path, root), asof, today, script,
                       os.path.relpath(path, root), state.get("tier") or "<tier>"))
        if not named or named == os.path.basename(path):
            unwitnessed = _receipt_unwitnessed(root, os.path.basename(marker))
            if unwitnessed:
                return unwitnessed
            return _receipt_spent(root, gate, os.path.basename(marker),
                                  ticket=state.get("ticket"))
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
    # Three names, because DEFINE produces three documents depending on the tier
    # and the gate has to look for the one that phase actually writes:
    #   FEATURE  docs/ddw/prd/prd-<ticket>.md    the PRD
    #   QUICK-FIX docs/ddw/prd/fix-<ticket>.md   the four-section fix brief
    #   FIX      docs/ddw/specs/rca-<ticket>.md  the root cause analysis
    # It looked only for `prd-`, which was invisible while a missing document
    # counted as no claim — and became a wall the moment that stopped being true:
    # neither QUICK-FIX nor FIX could leave DEFINE at all. Measured on a clean
    # install, following the skills' own instructions to the letter.
    if (state.get("tier") or "") == "FIX":
        return _receipt_missing(root, state, "define", "prd", "specs", ("rca",),
                                "validate_prd.py", "root cause analysis")
    return _receipt_missing(root, state, "define", "prd", "prd", ("prd", "fix"),
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
    # A receipt from the moment the gate was earned makes this check independent
    # of where the repository is standing NOW. Without it, the check resolved
    # the PR through the CURRENT branch — and the closeout's own happy path
    # destroys that branch: the user merges, the forge deletes it, the repo sits
    # on main, and the final transition finds "no PR" for work whose PR it is
    # LOOKING AT. Measured: the model un-stuck itself by recreating the deleted
    # branch, satisfying the check, and deleting it again — a gate that teaches
    # the model to route around it. The receipt names the PR by NUMBER, and the
    # forge — never the receipt — still says what state that PR is in.
    ticket = (state or {}).get("ticket") if isinstance(state, dict) else None
    if ticket:
        try:
            with open(_pr_receipt_path(root, ticket), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            rec = None
        if isinstance(rec, dict) and rec.get("number"):
            verdict = _pr_by_number_missing(root, ticket, rec)
            if verdict is not _NO_VERDICT:
                return verdict                        # None (pass) or the refusal
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
        # Earned: remember WHICH pull request, so every later re-check — the
        # closeout edge, a resume — asks the forge about this PR by number
        # instead of about whatever branch the repo happens to be on then.
        if ticket:
            try:
                path = _pr_receipt_path(root, ticket)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump({"number": live[0].get("number"), "head": branch}, fh)
            except OSError:
                pass                     # never fail a claim over bookkeeping
        return None
    closed = " (there is a CLOSED one, which is not the same thing)" if prs else ""
    return ("the pr gate says a pull request was opened for `%s`, and the forge has none%s. "
            "Open it, or close this ticket without claiming the gate — a PR that only exists "
            "in the report is the one thing this gate is for." % (branch, closed))


_NO_VERDICT = object()


def _pr_receipt_path(root, ticket):
    # `.ddw-sessions/` because only hooks and the helper write there: a receipt
    # the model could write itself would be the model vouching for the model.
    return os.path.join(root, ".ddw-sessions", "pr-%s.json" % ticket)


def _pr_by_number_missing(root, ticket, rec):
    """The receipt's PR, asked about at the forge. Returns None (pass), a
    refusal, or _NO_VERDICT when gh cannot answer — the same three states the
    branch-based check distinguishes, for the same reason.

    The forge stays the authority: the receipt only says WHERE to ask. A forged
    receipt naming somebody else's pull request dies on the head check — the
    branch a PR was opened from names the ticket it was opened for, and that is
    the naming convention every branch in this method carries.
    """
    try:
        out = subprocess.run(["gh", "pr", "view", str(rec.get("number")),
                              "--json", "state,headRefName"],
                             cwd=root, capture_output=True, text=True, timeout=15,
                             stdin=subprocess.DEVNULL)
    except Exception:
        return _NO_VERDICT
    if out.returncode != 0:
        return _NO_VERDICT
    try:
        pr = json.loads(out.stdout or "{}")
    except ValueError:
        return _NO_VERDICT
    if not isinstance(pr, dict) or not pr.get("state") or not pr.get("headRefName"):
        return _NO_VERDICT               # not the shape `gh pr view` answers with
    head = str(pr.get("headRefName") or "")
    if ticket.lower() not in head.lower():
        return ("the pr gate's receipt points at PR #%s, whose branch `%s` does not name "
                "ticket %s. A receipt for another ticket's pull request is not evidence for "
                "this one; open this ticket's PR and earn the gate against it."
                % (rec.get("number"), head, ticket))
    if str(pr.get("state", "")).upper() in ("OPEN", "MERGED"):
        return None
    return ("the pr gate was earned against PR #%s and the forge now says it is %s. A closed, "
            "unmerged pull request is not the one this ticket shipped on; open it again or "
            "close the ticket without claiming the gate."
            % (rec.get("number"), pr.get("state")))


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


# Which validator earns which gate. The refusal above names it, because "gate
# 'spec' is not true" tells a reader what is wrong and not one thing about what
# to do — and the thing to do is never "edit the state".
_EARNED_BY = {"define": "`.ddw/scripts/validate_prd.py`", "spec": "`.ddw/scripts/validate_spec.py`",
              "threat": "`.ddw/scripts/validate_threat.py`", "tests": "`.ddw/scripts/validate_tests.py`",
              "sast": "`.ddw/scripts/validate_sast.py`", "verify": "`.ddw/scripts/validate_verify.py`"}

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


def _journal_lines(state_path):
    """Every well-formed object in the journal, transitions and gate snapshots
    alike. The two are told apart by shape and never by position.
    """
    out = []
    if _not_a_regular_file(journal_path(state_path)):
        return out              # named by _check_state_not_erased, which refuses
    try:
        with open(journal_path(state_path), "rb") as fh:
            raw = fh.read()
    except OSError:
        return out
    # Read as BYTES and decoded a line at a time. `encoding="utf-8"` on the file
    # raises `UnicodeDecodeError` from the ITERATION, not from `json.loads`, so
    # it escaped both handlers here — one stray byte anywhere in the journal came
    # out of the hook as a traceback, and every write in the repository was
    # refused for it, permanently, with the refusal naming `.ddw-state.json`: a
    # file with nothing wrong in it. `_journal_undecodable` is what turns that
    # into something a person can act on.
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
    return out


def _not_a_regular_file(path):
    """Is something at this path that is not a file we can finish reading?

    Asked BEFORE opening, because that is the whole point: `mkfifo
    .ddw-journal.jsonl` makes `open()` itself block until a writer appears, and
    no writer ever does — so every hook in the repository hangs, forever, with
    no output and no exit code. A hung hook is not a refusal: the tool is left
    waiting, and nothing tells the user why. A timeout would only convert it
    into a slow one. What is true is simpler: DDW's records are regular files,
    and anything else at those paths did not get there by accident.

    Returns the reason, or None. `os.path.isfile` follows symlinks, so a symlink
    to a real file stays fine.
    """
    if not os.path.exists(path) or os.path.isfile(path):
        return None
    return (
        "`%s` is not a regular file. DDW's records are files; a FIFO, socket or device at that "
        "path makes every hook block on opening it, which stops the session without saying "
        "anything. Remove it and restore the real file." % os.path.basename(path)
    )


def _journal_undecodable(state_path):
    """How many journal lines cannot be read as text at all.

    Counted rather than skipped in silence: the journal is what the erase check
    compares the state against, so quietly dropping lines makes a damaged record
    look like a shorter run — which is the exact reading the erase check exists
    to refuse. A line that cannot be decoded is a line whose transition cannot be
    ruled out.
    """
    if _not_a_regular_file(journal_path(state_path)):
        return 0                # a different problem, named separately below
    try:
        with open(journal_path(state_path), "rb") as fh:
            raw = fh.read()
    except OSError:
        return 0
    bad = 0
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        try:
            line.decode("utf-8")
        except UnicodeDecodeError:
            bad += 1
    return bad


def _resume_needs_a_recorded_pause(state_path, entry, dst):
    """The pause a resume points at has to be one the journal recorded.

    `_resume_allowed` reads the history — which lives in the state file, which is
    what a shell rewrites. This asks the other record, the one written only when
    a transition really landed.

    A journal that does not exist yet is not evidence of forgery: it is a
    repository installed before this file existed, or one whose first transition
    has not landed. In that case there is nothing to compare against and the
    older check is all there is — the same bargain the tier line on a receipt
    makes. What is refused is a journal that EXISTS and has no such pause.
    """
    recorded = _journal_entries(state_path)
    if not recorded:
        return
    for line in recorded:
        if line.get("to") != IDLE or line.get("from") != dst:
            continue
        action = line.get("action")
        if isinstance(action, str) and action.strip().lower().split(":", 1)[0].strip() == "pause":
            return
    raise Block(
        "this resume points at a pause the journal never recorded. The history says this ticket "
        f"was paused in {dst}; the append-only record of what actually landed does not. A resume "
        "is the one edge that owes no gates, so it rests on a pause that happened — and a pause "
        "that happened is in both records. If the journal was lost, restore it or start the work "
        "again from CLASSIFY; it cannot be resumed on the strength of the file the resume is "
        "asking about."
    )


def _split_needs_a_recorded_pause(state_path, entry, dst):
    """The split-pause a child opening rests on has to be one the journal saw.

    Same bargain as `_resume_needs_a_recorded_pause`, for the same reason: the
    history lives in the state file, which is what a shell rewrites, and this
    edge skips the graph — so the proof has to come from the record only landed
    transitions write. A missing journal is not evidence of forgery; a journal
    that EXISTS and never saw the parent's split-pause is.
    """
    parent = _split_parent(entry.get("ticket"))
    recorded = _journal_entries(state_path)
    if not recorded:
        return
    for line in recorded:
        if line.get("to") != IDLE or line.get("from") != dst:
            continue
        if line.get("ticket") != parent:
            continue
        action = line.get("action")
        if (isinstance(action, str)
                and action.strip().lower().split(":", 1)[0].strip() in ("pause", "paused")
                and "split" in action.lower()):
            return
    raise Block(
        f"this `split:` opening points at a split-pause of {parent} the journal never recorded. "
        "The append-only record of what actually landed has no such pause, and this is the one "
        "other edge that skips the graph — it rests on a split that happened, and a split that "
        "happened is in both records. If the journal was lost, restore it or open the child "
        "through CLASSIFY like any ticket."
    )


def _journal_entries(state_path):
    """The transitions the journal recorded, in order.

    A transition is an object naming where it came from and where it went. The
    gate snapshots share the file and are filtered out here — `known` indexes
    into the state's history, so a snapshot line counted as a transition would
    slide that index and hide the entry that just landed.

    DISTINCT transitions, and that is the same rule for the same reason. A line
    written twice — two hooks racing on a filesystem with no flock, a journal
    restored from a backup — slid that index exactly as a snapshot line did:
    `history[known:]` came back empty, so post mode owed evidence for nothing on
    the write that had just landed. Read as a count of transitions it also made
    the state look SHORTER than the record and bricked the repo. One filter, so
    the two readings cannot disagree.
    """
    entries, out = [e for e in _journal_lines(state_path)
                    if isinstance(e, dict) and "from" in e and "to" in e], []
    for entry in entries:
        # Not just consecutive duplicates: the race interleaves them
        # (classify, define, classify, define), which a neighbours-only fold
        # walks straight past.
        if any(_same_entry(prev, entry) for prev in out):
            continue
        out.append(entry)
    return out


def read_gates_snapshot(state_path):
    """The gates as they stood the last time post mode blessed them, or None.

    The journal records TRANSITIONS, and that is the hole this closes: a write
    that appends no history entry — `jq '.gates.tests = true'` — landed with
    nothing for the replay to owe evidence against, because the only gates post
    mode asked about were the ones the landed EDGES declared, and no edge landed.
    The pre path does not catch it either: it owes evidence on what a write newly
    claims, and by the time it runs the forged `true` is already the prior.

    A snapshot, not a re-check of everything true. Re-checking every gate on
    every write means editing the PRD two phases later brings the pipeline down
    (see `_gates_newly_claimed`); this asks only what changed since the last
    blessing, which is the same question asked where the answer is known.

    It lives in the journal rather than beside it so that removing it costs the
    transitions too — and a journal that comes back empty makes post mode
    STRICTER, not weaker: with nothing recorded, every entry counts as landed and
    every gate its edges declare is owed again.

    None means "unknown", never "empty": a repo that upgrades mid-run has no
    snapshot yet, and reading that as `{}` would call every gate it already
    earned newly claimed and refuse the next write.
    """
    snaps = [e.get("gates") for e in _journal_lines(state_path)
             if isinstance(e, dict) and e.get("record") == "gates"]
    for gates in reversed(snaps):
        if isinstance(gates, dict):
            return gates
    return None


def _lock(fh):
    """An exclusive lock on the journal, where the platform has one.

    Advisory and best-effort: on a filesystem or OS without flock this is a
    no-op, and the content comparison in `_check_state_not_erased` is what
    survives that. Both exist because ONE of them is not enough — the lock stops
    the duplicate being written, the comparison stops a duplicate that was
    written anyway from reading as a deletion.
    """
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except Exception:
        pass


def _journal_append(state_path, lines):
    """Best effort by design: a journal that cannot be written must not block a
    legal pipeline, it only costs the extra guarantee.
    """
    if not lines:
        return
    try:
        with open(journal_path(state_path), "a", encoding="utf-8") as fh:
            _lock(fh)
            for line in lines:
                fh.write(json.dumps(line, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def record_journal(state_path):
    """Append whatever the state's history has that the journal does not, plus
    the gates that history left it in.

    Called from post mode — after the write landed, so the journal records what
    IS rather than what was about to be.
    """
    try:
        if not os.path.exists(state_path):
            return
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh) or {}
        history = state.get("history") or []
    except (OSError, ValueError, AttributeError):
        return
    # Read-what-is-there and append-what-is-missing under ONE lock. They used to
    # be two unsynchronised steps, and two hooks in that window both read the
    # same `known` and both appended the same entry — after which
    # `_check_state_not_erased` saw more journal lines than history entries and
    # refused every write in the repo, forever, blaming the state file. Measured
    # at five repos in twelve, from parallel tool calls in ONE session: the model
    # is encouraged to batch independent calls, and the post matcher fires on all
    # of them.
    gates = state.get("gates") or {}
    if not isinstance(gates, dict):
        gates = {}
    held = {g: True for g, v in gates.items() if v is True}
    try:
        with open(journal_path(state_path), "a+", encoding="utf-8") as fh:
            _lock(fh)
            fh.seek(0)
            recorded = []
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        recorded.append(json.loads(line))
                    except ValueError:
                        continue
            known = len([e for e in recorded
                         if isinstance(e, dict) and "from" in e and "to" in e])
            snaps = [e.get("gates") for e in recorded
                     if isinstance(e, dict) and e.get("record") == "gates"]
            last = next((g for g in reversed(snaps) if isinstance(g, dict)), None)
            lines = list(history[known:])
            phase_now = state.get("phase", IDLE)
            # `block` used to leave no trace at all: an in-phase update the
            # graph rightly allows, recorded nowhere — so the journal could not
            # tell "advanced by the sanctioned helper" from "never touched",
            # and an audit of a finished ticket found zero occurrences of the
            # field the phase rules order updated once per block. One snapshot
            # per change, same shape as the gates record.
            bsnaps = [e for e in recorded
                      if isinstance(e, dict) and e.get("record") == "block"]
            last_block = bsnaps[-1].get("block") if bsnaps else None
            block_now = state.get("block")
            if block_now != last_block:
                lines.append({"record": "block", "block": block_now,
                              "ticket": state.get("ticket"), "phase": phase_now})
            if last != held:
                # A gate that WAS held and is not any more was spent: the
                # corrective loop took it back. Recorded by name, because a
                # receipt is content-hashed and that is not enough for two of
                # them. For define, spec, threat and verify the artifact IS
                # what changed, so re-earning costs a real re-validation — the
                # hash moved. For tests and sast the artifact is a report ABOUT
                # code that is about to change: the report's bytes are the same
                # after the fix as before it, so the old receipt went on opening
                # the gate and QUICK-FIX CLOSEOUT->CODE (or FEATURE VERIFY->CODE)
                # cost nothing at all. `clears` was a boolean operation and
                # nothing outlived the write that performed it.
                #
                # Not on the way to IDLE: reaching IDLE wipes every gate as part
                # of parking or closing the ticket, and a paused ticket restores
                # them on resume without re-validating anything. Recording that
                # as spending would refuse every resumed ticket.
                dropped = sorted(g for g in (last or {}) if g not in held)
                if dropped and phase_now != IDLE:
                    lines.append({"record": "spent", "gates": dropped,
                                  "ticket": state.get("ticket"), "phase": phase_now})
                lines.append({"record": "gates", "gates": held,
                              "ticket": state.get("ticket"),
                              "phase": phase_now})
            for line in lines:
                fh.write(json.dumps(line, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def _same_entry(a, b):
    """Two records of the same transition. Compared on what identifies it — where
    it went, why, and when — rather than on the whole object, so a field added by
    a later version does not make an old line look like a different one."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    return all(a.get(k) == b.get(k) for k in ("timestamp", "from", "to", "action"))


def _check_state_not_erased(state_path):
    """A state that vanished, or came back shorter than what was recorded.

    `rm` used to be the one move that always worked. Now the journal outlives
    the file, so the history cannot be dropped by deleting what holds it — the
    next write is refused until a human says what happened.
    """
    for _path in (journal_path(state_path), state_path):
        _odd = _not_a_regular_file(_path)
        if _odd:
            raise Block(_odd)
    damaged = _journal_undecodable(state_path)
    if damaged:
        raise Block(
            f"{damaged} line(s) of `.ddw-journal.jsonl` cannot be read as text. That file is the "
            "record the history is checked against, so a line nobody can read is a transition "
            "nobody can rule out — and this refusal is about the JOURNAL, not about "
            "`.ddw-state.json`, which may be perfectly fine. Restore the journal from a backup, "
            "or if you accept losing the tamper-evidence for this run, remove the unreadable "
            "lines yourself and tell the user you did."
        )
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
            text = fh.read()
    except OSError:
        return
    if not text.strip():
        # Zero bytes is not garbage and it is not absence, and it fell between
        # the two: this check bailed to "unreadable is the other check's
        # business", and that check reads a blank file as a fresh IDLE, because
        # a fresh install genuinely leaves an empty state file behind. So
        # truncating the state — `: > .ddw-state.json`, or any editor saving an
        # empty buffer — produced a repository at IDLE with no ticket and no
        # history, and a write to product source that DEFINE had just refused
        # went through.
        #
        # Which of the two it is, is not a guess: an empty state with nothing in
        # the journal is the install; an empty state with transitions recorded
        # is a history that was destroyed. Counted as the zero entries it now
        # holds, so the comparison below says exactly that.
        history = []
    else:
        try:
            history = (json.loads(text) or {}).get("history") or []
        except (ValueError, AttributeError):
            return                   # unreadable is the other check's business
    # `recorded` is already DISTINCT transitions — `_journal_entries` folds a line
    # written twice, wherever in the file it landed. The comparison used to be
    # against raw lines, which reads a journal line written TWICE as a history
    # entry deleted once, and two hooks racing to append is how that happened.
    # The lock stops the duplicate being written; the fold stops one that was
    # written anyway from bricking the repo with a message pointing at the wrong
    # file.
    seen = recorded
    if len(history) < len(seen):
        raise Block(
            f".ddw-state.json holds {len(history)} history entries but {len(seen)} distinct "
            "transitions were recorded for this repo. History is append-only: a shorter one "
            "means entries were dropped, not that the run got simpler. Restore the state and "
            "tell the user."
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


def _method_write_denied(target, method, repo=None):
    """A write to the method itself, wherever the method actually lives.

    `enforcement_write_denied` asks whether a path is under `.ddw/` *in the
    repo*, which is the whole story for a drop-in install and none of it for a
    plugin one: there the method sits in a plugin root shared by every project,
    and every guard on DDW's own files answered "outside the repo, not ours".
    Measured: writes to the plugin's `transition-graph.json`, `hook-gate.py` and
    `validate-transition.py` all returned 0 while a write to `src/app.ts` in the
    same event returned 2 — and with `"PLAN->CLOSEOUT": {"gates": []}` injected
    into that graph, a FEATURE walked PLAN→CLOSEOUT with no spec, threat, tests,
    sast or verify. One write, and DDW stops holding in every repository that
    installs it as a plugin.

    Kept separate from the repo guard because the answer is different: this one
    holds no matter which side of the repo boundary the path falls on.

    **And it covers the plugin ROOT, not only the method inside it.** The first
    version sealed `$PLUGIN/ddw` — the rules, the graph, the validators — while
    the files the tool actually EXECUTES sit one level up:
    `$PLUGIN/adapters/claude/hooks/validate-state-transition.sh`, the
    `plugin-hooks.json` that wires it, `.claude-plugin/plugin.json`. None of
    those are under the method and none are in the repo, so every guard answered
    "not ours". Measured: overwriting that one `.sh` with `exit 0` took a single
    `Write`, allowed in any phase including IDLE, after which a write to
    `src/x.py` that had just been refused came back at exit 0 — DDW off, in
    every repository using that plugin, from inside a ticket.

    Only when the method is OUTSIDE the repo. In a drop-in install the method is
    `<repo>/.ddw`, whose parent is the repository itself: sealing that would seal
    the user's project, which is the opposite of the deal.
    """
    if not method:
        return None
    root = os.path.realpath(method)
    if repo:
        repo_root = os.path.realpath(repo)
        outside = root != repo_root and not root.startswith(repo_root + os.sep)
        if outside:
            # The plugin root: what the tool loads, hooks and manifest included.
            root = os.path.dirname(root) or root
    if target != root and not target.startswith(root + os.sep):
        return None
    return (
        f"`{os.path.relpath(target, root)}` is part of DDW itself — the method this repository "
        "is being held to, which under a plugin install lives outside the repository and is "
        "shared by every project using it. No phase writes it, and a write here would change "
        "the rules for all of them. To change how DDW is installed, run `install.sh` (or "
        "`uninstall`) yourself, outside the ticket."
    )


def decide_pre(state_path, graph_path, tool_name, tool_input, paths, repo=None, raw_tool=None,
               method=None):
    """PreToolUse: judge a pending write. `paths` is every path the event names.

    Every candidate is judged, not just the first one found: an envelope
    carrying a harmless `file_path` next to the real `path` bought a free write
    while the gate looked at the decoy.
    """
    root = os.path.realpath(repo) if repo else os.path.dirname(os.path.realpath(state_path))
    state_real = os.path.realpath(state_path)

    named = [pth for pth in paths if isinstance(pth, str) and pth]
    targets = [resolve_in_repo(pth, root) for pth in named]
    # The same paths unresolved: the sealed lists are about names, and following
    # a symlink first answers the question about a different name.
    lexicals = [lexical_in_repo(pth, root) for pth in named]
    if not targets:
        return None                                   # no path to judge

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
    reading = _verb in READ_TOOLS or any(r in _verb for r in READ_VERBS)
    writing = payload_writes or not reading

    # Asked BEFORE the early return below, because that return is exactly what
    # let this through: under a plugin install the method is outside the repo,
    # so "nothing here is in the repository" was true of a write to DDW's own
    # graph. The scratch path the corrupt-state recovery prescribes is not under
    # the method root, so that door stays open.
    #
    # And asked only of a WRITE, which is why the question above had to move up
    # here. This guard was hoisted to the top of the function to close the
    # plugin hole and left ahead of it, so on Copilot — whose preToolUse carries
    # no matcher — it refused every READ of a path under the method. Measured
    # live: the sessionStart hook injects "read `.ddw/orchestrator.md` now and
    # run its Boot Sequence", and the very next tool call came back "DDW blocked
    # this write: orchestrator.md is part of DDW itself". The agent could not
    # load the state machine it was being held to, so nothing enforced a phase
    # and the run looked like DDW was not installed at all — while the refusals
    # printed DDW's own words. Sealing the method against writes is the rule;
    # sealing it against reads is the method refusing to be read.
    if writing:
        for target in targets:
            denied = _method_write_denied(target, method, repo)
            if denied:
                return denied

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
    #
    # Judged on BOTH readings of each path. A `.ddw` symlinked to a directory
    # outside the repository made every write to the method resolve outside it,
    # so this returned "none of it is DDW's to judge" about DDW's own graph —
    # while `src/app.ts` in the same phase was refused. A path that is in the
    # repo under either reading is one this has to look at.
    if (all(_outside_repo(t, root) for t in targets)
            and all(_outside_repo(lex, root) for lex in lexicals)):
        return None

    # Judge the source guard on every target that is NOT the state file, always.
    # Returning early once the state was recognised meant an envelope naming the
    # state alongside the real target bought a write that nothing looked at —
    # the mirror image of the decoy this function was written to close.
    _, disk = _read_state_or_refuse(state_path)
    phase = disk.get("phase", IDLE)
    for target, lexical in zip(targets, lexicals):
        if target == state_real:
            continue
        if not writing:
            continue                      # a read cannot violate a write rule
        # Asked FIRST, and separately from the phase rule, because it does not
        # depend on the phase: DDW's own machinery is not writable from inside
        # the pipeline, in CODE and CLOSEOUT as much as anywhere else.
        reason = enforcement_write_denied(target, root)
        if reason:
            return reason
        # …and under the name it was written as, which is a different question
        # whenever a symlink stands between the two.
        if lexical != target:
            reason = enforcement_write_denied(lexical, root)
            if reason:
                return reason
        reason = source_write_denied(target, root, phase)
        if reason:
            return reason
        reason = quickfix_scope_denied(target, root, disk)
        if reason:
            return reason
        reason = sealed_artifact_denied(target, root, disk)
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
        validate(old_state, new_state, graph, tool_name=tool_name, max_appended=1,
                 state_path=state_path)
        # The claim is legal. Is it backed?
        #
        # This used to be asked by transition.py alone — the helper the model is
        # asked to use — so the one gate that rests on evidence rested on the
        # model choosing the cooperative path. A plain Write of the same state,
        # judged right here, was allowed: exit 2 through the helper, exit 0
        # through the hook. A guarantee with a polite way around it is a
        # promise, which is the distinction this whole repository is about.
        # Newly claimed, PLUS what the edge being taken requires. The closing
        # edge is the case that made the difference matter: `CLOSEOUT->IDLE`
        # demands `commit` and `pr`, and the write that takes it claims nothing
        # — the gates were turned on earlier and are being SPENT here. So the two
        # gates that ask the world outside the repo were asked only on the write
        # that turned them on, and never on the write that cashed them. Between
        # those two writes the commit can be amended away and the pull request
        # closed, and the closeout would still pass.
        owed = list(_gates_newly_claimed(old_state, new_state))
        _oh, _nh = (old_state.get("history") or []), (new_state.get("history") or [])
        if len(_nh) > len(_oh):
            _edges = _effective_edges(graph,
                                      new_state.get("tier") or old_state.get("tier"))
            _cfg = _edges.get("%s->%s" % (old_state.get("phase", IDLE),
                                          new_state.get("phase", IDLE)))
            if isinstance(_cfg, dict):
                owed.extend(_cfg.get("gates") or [])
        reason = gate_evidence_missing(root, new_state, sorted(set(owed)))
        if reason:
            return reason
        if len(_nh) > len(_oh):
            reason = second_arrow_in_one_turn(root, old_state, new_state)
            if reason:
                return reason
            reason = goback_gate(root, old_state, new_state, graph)
            if reason:
                return reason
            _record_arrow(root)
    return None


# ── One arrow per turn ───────────────────────────────────────────────────────
#
# "NEVER run more than one phase transition in a single response. Finish the
# current phase, show the closing summary, wait for EXPLICIT confirmation."
# The orchestrator states it as hard, and said how it was enforced: "the state
# is written once per arrow either way, and the hook refuses a write that
# appends two."
#
# That covers one of the two ways to break it. Measured on a live run: three
# separate writes, one entry each, thirty-seven seconds apart, on a single
# "avanti" — the split closed, the sub-ticket opened, and DEFINE entered, with
# the user having approved only the first. Each write was legal on its own and
# nothing compares writes across a response.
#
# The turn counter the commit gate needed is the signal that was missing. Under
# `minimal` this does not apply: there the arrows are supposed to run without
# anyone between them, which is what that mode was opted into.
def _turn_file(root):
    return os.path.join(root or ".", ".ddw-sessions", "turn")


def _turn_now(root):
    try:
        with open(_turn_file(root), encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _record_arrow(root):
    turn = _turn_now(root)
    if turn is None:
        return
    try:
        path = os.path.join(root, ".ddw-sessions", "last-arrow")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(turn))
    except OSError:
        pass                            # bookkeeping never decides a write


def second_arrow_in_one_turn(root, old_state, new_state):
    """The reason to refuse a second transition in one response, or None."""
    autonomy = new_state.get("autonomy") or old_state.get("autonomy") or "assisted"
    if autonomy == "minimal":
        return None
    turn = _turn_now(root)
    if turn is None:
        # No turn signal from this tool. Silence rather than a refusal: a guard
        # that fires because a counter is missing refuses every write on every
        # harness that does not write one.
        return None
    try:
        with open(os.path.join(root, ".ddw-sessions", "last-arrow"), encoding="utf-8") as fh:
            last = int(fh.read().strip())
    except (OSError, ValueError):
        return None
    if last != turn:
        return None
    return (
        "a transition already landed in this turn (%s → %s), and `assisted` means every arrow "
        "waits for the user.\n"
        "Show the closing summary for the arrow you just took, END YOUR TURN, and take the next "
        "one once they have answered. Do NOT batch the rest of the pipeline into this response: "
        "approving one step is not approving the ones after it, and a run that crosses three "
        "phases on one \"go ahead\" was approved once and recorded as three decisions.\n"
        "If the user wants the arrows to stop waiting, that is `autonomy: minimal`, decided in "
        "CLASSIFY with the cost stated." % (old_state.get("phase", IDLE),
                                            new_state.get("phase", IDLE)))


def goback_gate(root, old_state, new_state, graph):
    """A backward edge under `assisted` carries its reason on disk — and, when
    that reason is a question, the user's turn.

    § Going back (state.instructions.md) has two lanes: a CORRECTION — a
    validator or review named a defect, nothing is the user's to decide —
    announces the move and takes it; a QUESTION is asked BEFORE the edge and
    taken with the answer in hand. Both lanes lived only in prose, and the fix
    that introduced the second one touched only `.md` files — so a live run
    took PLAN's return edge first and asked after, exactly the shape the prose
    forbids, and nothing could refuse it: the one-arrow-per-turn counter only
    ever compares a SECOND arrow, and the first arrow of any turn lands free.

    So the reason gets the commit gate's treatment. The model writes it to
    `.ddw-work/goback-proposal.txt` (the runtime that IS writable), naming the
    edge and opening with its lane — `correction:` or `ask:`. A correction
    passes with the file as its record. A question passes only when the seal
    the turn hook stamps (`.ddw-sessions/goback-seen`, where the model cannot
    write) matches the proposal's bytes — which can only be true if that exact
    question was on screen before the user answered.

    Where no turn hook is wired (`.ddw-sessions/turn` absent — a tool with no
    UserPromptSubmit equivalent), this returns None: a guard that fires because
    a counter is missing refuses every backward edge on every harness that does
    not write one. That gap is declared, not smoothed over — the same sentence
    POST_CANNOT_BLOCK gets.
    """
    old_h = old_state.get("history") or []
    new_h = new_state.get("history") or []
    if len(new_h) != len(old_h) + 1:
        return None                     # not a single fresh edge; validate() owns the rest
    entry = new_h[-1] if isinstance(new_h[-1], dict) else {}
    frm, to = entry.get("from"), entry.get("to")
    tier = new_state.get("tier") or old_state.get("tier")
    if not (frm and to and tier):
        return None
    try:
        edges = _effective_edges(graph, tier)
    except Block:
        return None                     # a malformed graph is validate()'s finding
    cfg = edges.get("%s->%s" % (frm, to))
    if not (isinstance(cfg, dict) and cfg.get("clears")):
        return None                     # forward edges have their own approvals
    autonomy = new_state.get("autonomy") or old_state.get("autonomy") or "assisted"
    if autonomy == "minimal":
        return None                     # opted into with the cost stated out loud
    if _turn_now(root) is None:
        return None                     # no turn signal from this tool: declared above
    proposal = os.path.join(root, ".ddw-work", "goback-proposal.txt")
    try:
        with open(proposal, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return (
            "%s->%s goes back a phase under `assisted`, and nothing on disk shows the user was "
            "told. Write the reason to .ddw-work/goback-proposal.txt first, naming the edge "
            "('%s -> %s') and opening with its lane: 'correction: <the defect a validator or "
            "review named>' when nothing is the user's to decide — announce it and go — or "
            "'ask: <the question>' when something is, which ends your turn and takes the edge "
            "WITH their answer in hand (state.instructions § Going back)." % (frm, to, frm, to))
    if ("%s -> %s" % (frm, to)) not in text and ("%s->%s" % (frm, to)) not in text:
        return (
            "the go-back proposal on disk does not name this edge (%s -> %s), so it is not this "
            "move's reason. Rewrite .ddw-work/goback-proposal.txt for the edge being taken — a "
            "reason that fits any edge explains none." % (frm, to))
    lane = text.strip().split(":", 1)[0].strip().lower()
    if lane == "correction":
        return None
    if lane == "ask":
        seen = os.path.join(root, ".ddw-sessions", "goback-seen")
        try:
            with open(seen, encoding="utf-8") as fh:
                sealed = fh.read().strip()
        except OSError:
            sealed = None
        if sealed == hashlib.sha256(text.strip().encode("utf-8")).hexdigest():
            return None
        return (
            "this go-back proposal is a question ('ask:'), and the question has not been in "
            "front of the user yet — or changed after it was. Show it, END YOUR TURN, and take "
            "%s -> %s with their answer in hand; the seal is written when they speak. Executing "
            "the loop first and asking after is the exact shape this gate exists to stop "
            "(measured live)." % (frm, to))
    return (
        "the go-back proposal's first word decides its lane, and %r is neither 'correction' nor "
        "'ask'. A correction is a defect a validator or review named (announce and go); a "
        "question is the user's (show it and wait). Pick the one that is true — a mislabelled "
        "question stays on disk, in a file the audit reads." % lane)


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
    # it is what erased them: `CLOSEOUT->IDLE` demands `commit` and `pr`, and the
    # same write that takes that edge resets `gates` to {}. Replaying it against
    # the empty snapshot declared every finished ticket illegal — and since the
    # post matcher fires on every Bash and Edit, the session stayed wedged from
    # then on. So on a closed run this checks the PATH, which is what a Bash/jq
    # forgery fakes; the gates were already enforced pre-write, when they existed.
    scope = "none" if (run and run[-1].get("to") == IDLE) else "last"
    # …and the graph is consulted only for the edges the journal has NOT yet
    # blessed. An edge validated when it landed does not become illegal because
    # the graph changed afterwards — but that is exactly what happened on an
    # upgrade mid-ticket: the new graph was applied to the whole run, an edge
    # that was legal under the old one was condemned, and post mode then refused
    # every tool call with no way back that any message named.
    blessed = len(_journal_entries(state_path))
    # gates_scope="last" and no cap: this replays a whole run that was already
    # validated edge by edge. Checking every edge against today's gate snapshot
    # does not re-check history, it invents a verdict — and it rejected the
    # corrective loop, the pipeline's own documented recovery path.
    validate(prior, disk_state, graph, gates_scope=scope, max_appended=None,
             state_path=state_path,
             skip_edges=max(0, blessed - start))

    # The same question the pre path asks, for the writes it never sees: a
    # `jq`/`sed`/heredoc that sets a gate reaches the disk without passing a
    # write tool. What is new here is exactly what the journal has not recorded
    # yet — the journal is written below, after the verdict — so this asks about
    # the edge that just landed and never re-litigates the ones before it.
    # Asked on the closing edge too. `scope == "none"` was gating this arm as
    # well, and the closing write is the one write that clears the gates — so a
    # forged run refused at CLOSEOUT was blessed in full by one more shell write
    # to IDLE, and every outstanding finding went with it. What the hatch exists
    # for is not re-litigating a CLOSED ticket's gates against an empty snapshot;
    # the edges that have not been journalled yet are a different question, and
    # `commit` and `pr` — the two the closing edge spends — can still be asked of
    # git and the forge after the header is wiped.
    owed = []
    known = len(_journal_entries(state_path))
    landed = [e for e in history[known:] if isinstance(e, dict)]
    edges = _effective_edges(graph, tier)
    for entry in landed:
        cfg = edges.get("%s->%s" % (entry.get("from"), entry.get("to")))
        if isinstance(cfg, dict):
            owed.extend(cfg.get("gates") or [])
    # The header's ticket is null at IDLE by definition, and a receipt resolves
    # its document by the ticket. The entries carry it — that is what stamping
    # them was for — so the run being closed is still identifiable after the
    # write that erased its name.
    if owed and not disk_state.get("ticket"):
        run_ticket = next((e.get("ticket") for e in reversed(landed) if e.get("ticket")), None)
        if run_ticket:
            disk_state = {**disk_state, "ticket": run_ticket,
                          "tier": disk_state.get("tier") or tier}
        else:
            # And if NOTHING names a ticket, that is not "nothing to check" — it
            # is a run that cannot be checked, which is the same thing wearing a
            # different face. Every receipt gate resolves its document through
            # the ticket, and `_receipt_missing` reads a missing one as a missing
            # CLAIM: so the switch that turns the whole evidence layer on was
            # held by whoever wrote the history.
            #
            # Measured: a FEATURE forged in one shell write —
            # IDLE→CLASSIFY→DEFINE→PLAN→CODE→VERIFY→CLOSEOUT→IDLE, seven
            # transitions, `tier` stamped so the tier-less hatch would not catch
            # it, and `ticket` left off every entry. Post mode returned 0, and
            # the journal recorded all seven as blessed: a run with no PRD, no
            # spec, no threat model, no test report, no SAST report and no
            # verdict, indistinguishable afterwards from one that earned them.
            raise Block(
                "this run takes %d transition(s) that owe evidence (%s) and no entry names a "
                "ticket, so there is no document any of them can be checked against. The ticket "
                "is stamped on the entry that classifies the work and carried by every entry "
                "after it — a run without one cannot be judged, and a run that cannot be judged "
                "is not one this gate lets past. If this history is real, the entries lost their "
                "`ticket` field; restore it from the journal rather than writing the state again."
                % (len(landed), ", ".join(sorted(set(owed))))
            )

    # And the gates this write turned on WITHOUT declaring a transition, which is
    # the case the edges above cannot see: a `jq`/`sed` that flips `tests` to true
    # appends no history, so it owed nothing, and the pre path then reads that
    # `true` as the prior and finds nothing newly claimed either. Asked here
    # against the last blessed snapshot, and only about what changed since it.
    snapshot = read_gates_snapshot(state_path)
    if snapshot is not None:
        owed.extend(_gates_newly_claimed({"gates": snapshot}, disk_state))
    if owed:
        reason = gate_evidence_missing(os.path.dirname(os.path.abspath(state_path)),
                                       disk_state, sorted(set(owed)))
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
        # Read the state again, only to explain the refusal better. A state
        # written by an older DDW is not a forgery and its owner should not be
        # told they wrote it with `sed`.
        try:
            with open(args.state, encoding="utf-8") as _fh:
                _disk = json.load(_fh)
        except Exception:
            _disk = None
        renamed = _renamed_phase_in(_disk) if isinstance(_disk, dict) else None
        if renamed:
            old_name, new_name = renamed
            print(
                f"DDW: this .ddw-state.json was written by an older DDW — it names the `{old_name}` "
                f"phase, which is now `{new_name}`. Nothing is wrong with your work and nothing was "
                "forged: the phase was renamed because it never released anything (it commits, "
                "opens the pull request and closes the ticket out).\n"
                f"Rename it in the state and in every history entry — `{old_name}` → `{new_name}` — "
                "and carry on. The artifacts, the branch and the pull request are untouched.",
                file=sys.stderr,
            )
            sys.exit(2)
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
