#!/usr/bin/env python3
"""DDW's sanctioned FSM transition primitive.

Prints the COMPLETE JSON of the next .ddw-state.json for ONE phase transition to
stdout, ready to paste into a `Write` tool call. Read-only: it does NOT write the
state. The actual write is done by the model with `Write`, which the PreToolUse
hook validates.

It builds the transition deterministically (reads the state from disk, appends
{timestamp, from, to, action} at the END of history, sets phase + gates) and
SELF-VALIDATES with the same validate() the hook uses before printing: if the
transition is illegal (an edge outside the graph, a missing gate, etc.) it exits
2 with the reason on stderr — the model sees the problem BEFORE writing, and no
JSON is emitted.

`from` = the phase read from disk (pre-mutation); `to` = --to. Run it ONCE per
edge: IDLE→CLASSIFY and CLASSIFY→DEFINE are separate runs (a direct IDLE→DEFINE
is not in the graph and gets rejected).

The only metadata the helper sets is `--tier` and `--autonomy` (both enums —
shell-safe, and the two things chosen once in CLASSIFY that the rest of the run
is routed by). The other fields
(ticket/title/tracker, and the discovery object) are NOT handled here:
the model fills them in in the SAME Write where it pastes this output. Passing
free text (e.g. a title with spaces) through shell args broke the quoting, so
`--set` was removed.
"""
import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/.ddw/scripts
_DDW  = os.path.dirname(_HERE)                       # <repo>/.ddw   (the method)
_REPO = os.path.dirname(_DDW)                        # <repo>        (the root)
_VALIDATOR = os.path.join(_HERE, "validate-transition.py")
_DEFAULT_GRAPH = os.path.join(_DDW, "rules", "transition-graph.json")

_TIERS = ("QUICK-FIX", "FIX", "FEATURE", "DISCOVERY")


def _default_state():
    """Resolve the path of `.ddw-state.json`.

    The state is **runtime of the target repo**, never of the method. That holds
    whether DDW is vendored into the repo (drop-in) or comes from a plugin
    installed elsewhere: in both cases the state goes at the root of the repo you
    are working in.

    Resolution order:
      1. $CLAUDE_PROJECT_DIR — exported by the harness. The normal path.
      2. Walk up from the cwd looking for `.ddw/` or `.git/`.
      3. Error. We do NOT guess: in plugin mode, deriving the root from this
         script's location would write the state inside the plugin and
         contaminate every repo that uses it.
    """
    base = os.environ.get("CLAUDE_PROJECT_DIR")
    if base:
        return os.path.join(base, ".ddw-state.json")

    cur = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(cur, ".ddw")) or os.path.isdir(os.path.join(cur, ".git")):
            return os.path.join(cur, ".ddw-state.json")
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    raise SystemExit(
        "Could not determine the repo root. Run the helper from inside the "
        "repository, or pass --state <path>/.ddw-state.json explicitly."
    )


def _load_validator():
    """Import the hook's validator (its filename has a dash) — single source of truth."""
    spec = importlib.util.spec_from_file_location("ddw_validate_transition", _VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now_iso():
    # Explicit Z suffix: datetime.isoformat() would give +00:00.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_next_state(old_state, to_phase, action, gates, tier, clear_gates=(),
                     autonomy=None, edge_clears=(), ticket=None):
    """The complete state for the next step. Read-only over old_state (deep copy)."""
    new_state = json.loads(json.dumps(old_state))  # deep copy
    from_phase = old_state.get("phase", "IDLE")

    if to_phase == "IDLE":
        # Reset: clean metadata, gates {}, history preserved (--gate/--tier ignored).
        new_state["tier"] = None
        # `autonomy` resets with the ticket, for the reason tier and gates do:
        # otherwise the next request inherits a decision to stop asking that
        # nobody made for it. The hook refuses an IDLE state that keeps it.
        for key in ("ticket", "title", "tracker", "block", "discovery", "autonomy"):
            new_state[key] = None
        new_state["gates"] = {}
    else:
        if tier is not None:
            new_state["tier"] = tier
        if autonomy is not None:
            new_state["autonomy"] = autonomy
        # The ticket a gate is earned for. `--write` lands the state on disk with
        # nothing after it, so without a flag the only way to name the ticket was
        # a separate hand-written edit — and until it happened the gates were
        # claimed against a null ticket, which is the name every receipt is
        # resolved through. The hook now refuses that state; this is how the
        # sanctioned helper satisfies it.
        if ticket is not None:
            new_state["ticket"] = ticket
        merged = dict(new_state.get("gates") or {})
        # What the graph says this edge gives up. Going back a phase takes away
        # what that phase granted: the work from here on has to be earned again
        # against the artifacts as they now are. The validator REFUSES a backward
        # write that still holds them, so this is convenience, not enforcement —
        # the rule lives where the hook can see it.
        for gate in edge_clears:
            merged.pop(gate, None)
        for gate in clear_gates:
            merged.pop(gate, None)
        for gate in gates:
            merged[gate] = True
        new_state["gates"] = merged
        # Stepping back out of CODE means you are not implementing a block any
        # more, and a stale block name outlives the thing it named.
        if from_phase == "CODE" and to_phase != "CODE" and edge_clears:
            new_state["block"] = None

    new_state["phase"] = to_phase
    history = list(new_state.get("history") or [])
    entry = {"timestamp": _now_iso(), "from": from_phase, "to": to_phase, "action": action}
    # The tier the edge was taken under, stamped on the edge itself.
    #
    # Reaching IDLE wipes `tier` — that is what closing a ticket means. But the
    # post-write check replays the run that just closed, and with the tier gone
    # it could only look up edges in the empty `null` graph, so it declared EVERY
    # legitimate closeout an illegal state and then fired on every subsequent
    # tool call. The history is the audit trail; the tier is part of what
    # happened, so it belongs in the record rather than only in the header that
    # the closeout resets.
    run_tier = old_state.get("tier") or new_state.get("tier")
    if run_tier:
        entry["tier"] = run_tier
    # And the ticket, for the same reason: the entry is what answers "what
    # happened to which ticket", and the session boot reads it to work out which
    # sub-tickets of a split still have no closeout. The header's ticket is wiped
    # by the closeout, so an unstamped entry is unattributable forever after.
    run_ticket = new_state.get("ticket") or old_state.get("ticket")
    if run_ticket:
        entry["ticket"] = run_ticket
    # And the mode the edge was taken under, stamped on the edge itself, when it
    # was taken without anyone being asked. A history that reads identically for
    # a run somebody watched and one that had nobody to watch it is a record that
    # lies by omission — and this is the only place that distinction can live,
    # because the header resets when the ticket closes.
    run_auto = new_state.get("autonomy") or old_state.get("autonomy")
    if run_auto == "minimal":
        entry["autonomy"] = "minimal"
    history.append(entry)
    new_state["history"] = history
    return new_state


def main():
    ap = argparse.ArgumentParser(description="Emit the next .ddw-state.json for an FSM transition.")
    ap.add_argument("--to", required=True, help="Destination phase (CLASSIFY, DEFINE, PLAN, CODE, VERIFY, CLOSEOUT, IDLE, DISCOVERY).")
    ap.add_argument("--action", required=True, help="Description of the transition, for the history entry.")
    ap.add_argument("--gate", action="append", default=[], help="Gate to set to true (repeatable).")
    ap.add_argument("--clear-gate", dest="clear_gates", action="append", default=[],
                    help="Gate to drop (repeatable). The corrective loop VERIFY->CODE clears "
                         "tests and sast: the fix has to re-earn them.")
    ap.add_argument("--tier", choices=_TIERS, default=None,
                    help="Tier of the work (enum). The only metadata the FSM needs to route the graph.")
    ap.add_argument("--ticket", default=None,
                    help="The ticket this run belongs to. Set it on the edge that classifies the "
                         "request; a gate cannot be claimed without one, because the ticket is "
                         "how every receipt finds its document.")
    ap.add_argument("--autonomy", choices=("assisted", "minimal"), default=None,
                    help="How much of the run waits for the user. Set in CLASSIFY, with the user "
                         "looking at the box; the hook refuses a change anywhere else. Absent "
                         "leaves whatever the state carries, and absent there means assisted.")
    # --set was removed (free text through shell args broke the quoting). It is
    # kept registered and hidden only so we can return an actionable message.
    ap.add_argument("--set", dest="sets", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--state", default=None, help="Path of .ddw-state.json (autodetected if omitted).")
    ap.add_argument("--graph", default=_DEFAULT_GRAPH, help="Path of transition-graph.json.")
    ap.add_argument("--write", action="store_true",
                    help="Write the validated state to --state atomically (temp file + rename) "
                         "instead of only printing it. Shell redirection onto the state file "
                         "truncates it BEFORE this script can read it — measured live — so "
                         "never `> .ddw-state.json`; use this flag.")
    args = ap.parse_args()
    if args.state is None:
        args.state = _default_state()

    if args.sets:
        print(
            "ddw-transition: --set was removed (free text through shell args broke the "
            "quoting). Use --tier <TIER> for the tier and --ticket <ID> for the ticket; "
            "fill in title/tracker in the SAME Write where you paste the helper's output.",
            file=sys.stderr,
        )
        sys.exit(2)

    vt = _load_validator()
    _, old_state = vt._load_disk_state(args.state)
    graph = vt._load_graph(args.graph)  # exits 2 with a message if the graph will not load
    # The edge decides what it gives up, and the graph is where that is written.
    _edges = vt._effective_edges(graph, args.tier or old_state.get("tier"))
    _cfg = _edges.get("%s->%s" % (old_state.get("phase", "IDLE"), args.to)) or {}
    _clears = _cfg.get("clears", []) if isinstance(_cfg, dict) else []
    new_state = build_next_state(old_state, args.to, args.action, args.gate, args.tier,
                                 args.clear_gates, autonomy=args.autonomy, edge_clears=_clears,
                                 ticket=args.ticket)

    # A gate that rests on evidence is asked for it here too — the same function
    # the hook calls, never a second copy. This helper used to hold the only
    # implementation, which is how the hook came to allow what the helper
    # refused; two implementations of one rule drift, and the one that drifts is
    # always the one nobody is watching.
    #
    # Asking here as well is not redundancy: the model that runs this gets the
    # reason before it composes a write, instead of a refusal afterwards.
    reason = vt.gate_evidence_missing(
        os.path.dirname(os.path.abspath(args.state)),
        {**new_state, "ticket": new_state.get("ticket") or old_state.get("ticket")},
        args.gate or [])
    if reason:
        print("ddw-transition: " + reason, file=sys.stderr)
        sys.exit(2)

    try:
        vt.validate(old_state, new_state, graph)
    except vt.Block as exc:
        # validate()'s message is the truth (single source of truth — we do not
        # duplicate the graph's logic), but we add an actionable hint from the
        # context the helper ALREADY knows (phase on disk, --to, --tier). The
        # cryptic "is not in the graph" alone does not tell the model what to do.
        disk_phase = old_state.get("phase", "IDLE")
        if disk_phase == "IDLE" and args.to != "CLASSIFY":
            hint = (
                "From IDLE the only transition is --to CLASSIFY. Run that first, then "
                "--to <phase> (one run per edge; a direct IDLE→DEFINE does not exist)."
            )
        elif new_state.get("tier") is None and args.tier is None:
            hint = (
                "The tier is missing: pass --tier <" + "|".join(_TIERS) + "> (it is set on the "
                "CLASSIFY→DEFINE/DISCOVERY transition)."
            )
        else:
            hint = (
                "Transitions are one per edge; check the graph in "
                ".ddw/rules/transition-graph.json."
            )
        print(f"ddw-transition: illegal transition, nothing emitted: {exc} {hint}", file=sys.stderr)
        sys.exit(2)

    emitted = json.dumps(new_state, indent=2, ensure_ascii=False)
    if args.write:
        # Atomic on purpose: the state is read by hooks between any two shell
        # commands, and a half-written file reads as corruption.
        tmp = args.state + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(emitted + "\n")
        os.replace(tmp, args.state)
    print(emitted)


if __name__ == "__main__":
    main()
