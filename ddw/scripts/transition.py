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

def _tiers(graph=None):
    """The tiers that exist, read from the graph that defines them.

    Typed here once, as a tuple, while `ddw_receipt` derived the same list from
    the graph — two sources of truth for the same fact, and the day a tier was
    added to the graph the validators accepted it and this helper refused it
    with "invalid choice", from the sanctioned path, naming the four it knew.
    The graph is the authority for which tiers exist, as it is for every edge
    between them.
    """
    if graph is None:
        try:
            with open(_DEFAULT_GRAPH, encoding="utf-8") as fh:
                graph = json.load(fh)
        except (OSError, ValueError):
            return ("QUICK-FIX", "FIX", "FEATURE", "DISCOVERY", "FREE")
    return tuple(sorted(graph.get("tiers", {})))


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
        # `.git` EXISTS, rather than `.git` is a directory. In a worktree it is a
        # file holding a gitdir pointer, and `isdir` walked straight past it: a
        # sibling worktree (the layout the boot itself tells you to create) could
        # not resolve a root at all, and a worktree nested inside another repo
        # resolved to the ENCLOSING one — the ticket's state landing in a
        # different checkout than the ticket.
        if os.path.isdir(os.path.join(cur, ".ddw")) or os.path.exists(os.path.join(cur, ".git")):
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


def _resumed_from(old_state, field):
    """What the PAUSED run was carrying, for the edge that picks it back up.

    A resume starts at IDLE, where the header's `tier` and `ticket` are null by
    definition — so the entry that re-enters the work came out stamped with
    neither, and `ddw/rules/state.instructions.md` says every entry carries both.
    An unattributable entry is the one thing the history cannot afford: the
    closeout wipes the header, so nothing later can supply what this entry left
    out. Read from the pause the resume is answering, and only there: at
    IDLE→CLASSIFY for a NEW ticket, inheriting the previous one's stamp would be
    a lie of exactly the same kind.
    """
    if old_state.get("phase", "IDLE") != "IDLE":
        return None
    for entry in reversed(old_state.get("history") or []):
        if not isinstance(entry, dict):
            continue
        action = entry.get("action")
        if isinstance(action, str) and action.strip().lower().split(":", 1)[0].strip() in (
                "pause", "paused") and entry.get("to") == "IDLE":
            return entry.get(field)
        if entry.get("to") == "IDLE":
            return None                 # the run before this one closed or was abandoned
    return None


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
    # El sello, y nunca ANTERIOR al de la entrada previa.
    #
    # El reloj de pared retrocede. Medido en esta máquina —WSL2, que resincroniza
    # con el host— seis saltos de un segundo hacia atrás en 33.465 muestras
    # tomadas a lo largo de 75 segundos bajo carga. Un salto entre dos pasos del
    # pipeline deja la entrada nueva sellada antes que la anterior, y la guarda
    # de monotonía —que existe para que una historia editada a mano no pueda
    # reordenarse— refusa una transición legal que el helper acaba de construir.
    #
    # Sin salida, además: el rechazo dice que la historia va hacia atrás, y lo
    # único que la corregiría es editar la historia, que el hook también
    # rechaza. Un rechazo sobre el que no se puede actuar es el peor que hay.
    #
    # La guarda se queda como está: protege contra una historia reordenada, que
    # es lo que fue escrita para atrapar. Lo que cambia es que el camino
    # sancionado no puede producir el caso. Igual está permitido — dos
    # transiciones en el mismo segundo son corrientes — así que sujetar al
    # último sello no inventa orden, sólo se niega a perderlo.
    _stamp = _now_iso()
    _last = next((e.get("timestamp") for e in reversed(history)
                  if isinstance(e, dict) and isinstance(e.get("timestamp"), str)), None)
    if _last and _stamp < _last:
        _stamp = _last
    entry = {"timestamp": _stamp, "from": from_phase, "to": to_phase, "action": action}
    # The tier the edge was taken under, stamped on the edge itself.
    #
    # Reaching IDLE wipes `tier` — that is what closing a ticket means. But the
    # post-write check replays the run that just closed, and with the tier gone
    # it could only look up edges in the empty `null` graph, so it declared EVERY
    # legitimate closeout an illegal state and then fired on every subsequent
    # tool call. The history is the audit trail; the tier is part of what
    # happened, so it belongs in the record rather than only in the header that
    # the closeout resets.
    run_tier = old_state.get("tier") or new_state.get("tier") or _resumed_from(old_state, "tier")
    if run_tier:
        entry["tier"] = run_tier
        # …and in the header too, when the header carries none. Resuming out of
        # IDLE is the only edge where the two can differ: `_resumed_from`
        # recovers the paused run's tier for the entry, and leaving the header
        # null emitted a state that contradicted its own newest edge. Post mode
        # reads a run's tier off the entries, so it saw FEATURE against a null
        # header and condemned as corrupt the exact bytes this helper had just
        # written with exit 0 — and the refusal it prints forbids repairing, so
        # one missing --tier bricked the pipeline and only the user could undo
        # it. Only IDLE clears a tier, and that branch cleared it above.
        if to_phase != "IDLE" and new_state.get("tier") is None:
            new_state["tier"] = run_tier
    # And the ticket, for the same reason: the entry is what answers "what
    # happened to which ticket", and the session boot reads it to work out which
    # sub-tickets of a split still have no closeout. The header's ticket is wiped
    # by the closeout, so an unstamped entry is unattributable forever after.
    # The fallback to the paused ticket now reaches only a `resume:`, which is
    # the edge it was written for: `main` refuses every other way out of IDLE
    # that does not name its ticket, instead of guessing. It used to guess, and a
    # sub-ticket of a split came out stamped with its parent's ID — two writes
    # later post mode found one run naming two tickets and condemned the state.
    run_ticket = (new_state.get("ticket") or old_state.get("ticket")
                  or _resumed_from(old_state, "ticket"))
    if run_ticket:
        entry["ticket"] = run_ticket
        # And in the header, for the reason the tier is: a resume restores the
        # run it is picking back up, and a header that names no ticket while its
        # newest edge names one is the same self-contradiction post mode reads as
        # corruption.
        if to_phase != "IDLE" and new_state.get("ticket") is None:
            new_state["ticket"] = run_ticket
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


_LOCK_FH = None      # held for the life of the process; released when it exits


def _take_state_lock(state_path, vt):
    """Hold the state across read → validate → write, so two runs cannot interleave.

    The model is actively encouraged to issue parallel tool calls, and two
    `transition.py --write` runs in one turn is the ordinary case, not the
    exotic one. Read and write were not one critical section: both runs read the
    same phase, both validated against it, both wrote — and the second `replace`
    dropped the first one's edge on the floor while both reported success. A
    transition that exits 0 and is not there afterwards is the one failure this
    file exists to make impossible.

    The lock lives under `.ddw-sessions/`, which git already ignores and the
    uninstaller already removes; a sidecar next to `.ddw-state.json` would be an
    untracked file in every repo instead. It is advisory and best-effort — a
    filesystem without flock gets a no-op, which is why `_emit` also refuses to
    write over a state that changed since it was read.
    """
    global _LOCK_FH
    try:
        sess = os.path.join(os.path.dirname(os.path.abspath(state_path)), ".ddw-sessions")
        os.makedirs(sess, exist_ok=True)
        _LOCK_FH = open(os.path.join(sess, "state.lock"), "a+", encoding="utf-8")
        vt._lock(_LOCK_FH)
    except OSError:
        _LOCK_FH = None


def _emit(args, state, seen=None):
    """Print the state, and land it when asked. One writer, so `--claim` and a
    transition cannot drift on atomicity."""
    emitted = json.dumps(state, indent=2, ensure_ascii=False)
    if args.write:
        # Compare-and-write. The lock above serialises the ordinary case; this
        # answers the case where there is no lock to take — an NFS mount, a
        # filesystem without flock — by refusing rather than by overwriting work
        # that landed while this run was thinking. `seen` is the exact text the
        # state was read from.
        if seen is not None:
            try:
                with open(args.state, encoding="utf-8") as fh:
                    current = fh.read()
            except OSError:
                current = ""
            if current.strip() != (seen or "").strip():
                print("ddw-transition: the state changed on disk while this transition was being "
                      "built, so writing it would drop whatever landed in between. Nothing was "
                      "written. Re-read .ddw-state.json and run the helper again.", file=sys.stderr)
                sys.exit(2)
        # Atomic on purpose: the state is read by hooks between any two shell
        # commands, and a half-written file reads as corruption. The temp name
        # carries the pid because two writers sharing one `.tmp` can splice their
        # halves into a single file that parses and says something neither wrote.
        tmp = "%s.%d.tmp" % (args.state, os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(emitted + "\n")
            os.replace(tmp, args.state)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    print(emitted)
    if not args.write:
        # The helper PRINTS by design: the state has to land through a `Write`,
        # because that is the door PreToolUse guards. What it did not do was say
        # so, and its stdout is a complete, valid state file — indistinguishable
        # from one that landed.
        #
        # Measured live on Copilot: the model ran the documented command, read
        # back a state saying `"phase": "CLASSIFY"`, told the user the pipeline
        # had advanced, and went on classifying. On disk the phase was still
        # IDLE, `history` was empty and no journal line existed. Exit 0, DDW's
        # own JSON, and a transition that never happened — the failure that
        # looks exactly like success.
        #
        # On stderr so nothing that parses stdout has to change, and next to the
        # output it governs, which is the only place a rule is certain to be
        # read.
        print("ddw-transition: PREVIEW — nothing was written. The JSON above is the state to "
              "write; the write itself goes through a `Write` of .ddw-state.json on purpose, "
              "because that is the door PreToolUse guards. It has NOT been written yet: copy "
              "the JSON into that Write. A shell redirect (`>`, tee, sed -i) bypasses the guard "
              "and is refused.", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Emit the next .ddw-state.json for an FSM transition.")
    ap.add_argument("--to", default=None, help="Destination phase (CLASSIFY, DEFINE, PLAN, CODE, VERIFY, CLOSEOUT, IDLE, DISCOVERY). Omit only with --claim.")
    ap.add_argument("--action", default=None, help="Description of the transition, for the history entry.")
    ap.add_argument("--claim", action="append", default=[],
                    help="Mark a gate true WITHOUT moving phase (repeatable). This is how a gate is "
                         "earned: in the phase that owns it, before the edge that demands it. Without "
                         "it the helper could not close a ticket in ANY tier — CLOSEOUT->IDLE wants "
                         "`commit` and `pr`, reaching IDLE wipes the gates, so --gate on that edge was "
                         "silently discarded and the only way through was a hand-written Write."),
    ap.add_argument("--gate", action="append", default=[], help="Gate to set to true (repeatable).")
    ap.add_argument("--clear-gate", dest="clear_gates", action="append", default=[],
                    help="Gate to drop (repeatable). The corrective loop VERIFY->CODE clears "
                         "tests and sast: the fix has to re-earn them.")
    ap.add_argument("--tier", choices=_tiers(), default=None,
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
    # The SAME reader the hook uses, and refusing where it refuses. `_load_disk_state`
    # answers a truncated or unparseable file with a fresh IDLE — which is exactly
    # right for the hook (it has another check for that) and catastrophic here,
    # because `--write` then lands that fresh IDLE ON TOP of the file. The one
    # thing the whole product exists to protect, destroyed by the tool the method
    # tells the model to reach for first, in precisely the situation where the
    # orchestrator says STOP and report (rule 4). Two readers of one file with
    # opposite failure modes is the shape this project keeps finding.
    _take_state_lock(args.state, vt)
    try:
        old_text, old_state = vt._read_state_or_refuse(args.state)
    except vt.Block as exc:
        print("ddw-transition: %s" % exc, file=sys.stderr)
        sys.exit(2)
    graph = vt._load_graph(args.graph)  # exits 2 with a message if the graph will not load

    if args.claim:
        if args.to or args.action:
            print("ddw-transition: --claim marks gates in the CURRENT phase and takes no edge, so "
                  "it does not go with --to/--action. Claim first, then transition.", file=sys.stderr)
            sys.exit(2)
        bad = [g for g in args.claim if g not in vt.GATE_EVIDENCE]
        if bad:
            print("ddw-transition: unknown gate(s) %s. Known: %s"
                  % (", ".join(bad), ", ".join(sorted(vt.GATE_EVIDENCE))), file=sys.stderr)
            sys.exit(2)
        claimed = json.loads(json.dumps(old_state))
        gates = dict(claimed.get("gates") or {})
        gates.update({g: True for g in args.claim})
        claimed["gates"] = gates
        reason = vt.gate_evidence_missing(os.path.dirname(os.path.abspath(args.state)),
                                          claimed, args.claim)
        if reason:
            print("ddw-transition: " + reason, file=sys.stderr)
            sys.exit(2)
        try:
            vt.validate(old_state, claimed, graph, state_path=args.state)
        except vt.Block as exc:
            print("ddw-transition: %s" % exc, file=sys.stderr)
            sys.exit(2)
        _emit(args, claimed, seen=old_text)
        return

    if not args.to or not args.action:
        print("ddw-transition: --to and --action are required (or use --claim to mark a gate "
              "without moving phase).", file=sys.stderr)
        sys.exit(2)

    if args.to == "IDLE" and args.gate:
        # Silently dropping it is how the sanctioned helper came to be unable to
        # close a ticket in any tier: the flag was accepted, ignored, and the
        # refusal that followed blamed the tier.
        print("ddw-transition: --gate is not read on --to IDLE — reaching IDLE clears the "
              "gates, so a gate claimed there would be erased by the same write. Claim it "
              "first, in the phase that owns it: --claim %s" % " --claim ".join(args.gate),
              file=sys.stderr)
        sys.exit(2)
    # Leaving IDLE with a pause behind it is the one edge whose ticket cannot be
    # inferred: it is either resuming the paused ticket or opening a new one —
    # a sub-ticket of a split is the ordinary case — and the two want opposite
    # stamps. The helper used to guess, and inherited the paused ticket onto an
    # edge that was about a different one; two writes later post mode found a run
    # naming two tickets and condemned the state, which is how a split lost a
    # pipeline to a flag nobody knew was needed. A guess that lands in the audit
    # trail is worse than a question: the record has to say which ticket the work
    # was for, and only the caller knows.
    #
    # A `resume:` is exempt, and is the reason this is not a blanket rule: that
    # word says which ticket is meant — the paused one — so there is nothing to
    # guess and the entry inherits it correctly. Every other action leaving IDLE
    # is about a ticket only the caller can name.
    _verb = (args.action or "").strip().lower().split(":", 1)[0].strip()
    if (args.to != "IDLE" and old_state.get("phase", "IDLE") == "IDLE"
            and args.ticket is None and _verb not in ("resume", "resumed")):
        paused = _resumed_from(old_state, "ticket")
        if paused:
            print("ddw-transition: this edge needs --ticket. The history has a paused %s, so "
                  "leaving IDLE is either resuming it or opening a different ticket (a "
                  "sub-ticket of a split, say) — and the helper cannot tell, while the entry it "
                  "writes claims one of them forever. Pass --ticket %s to resume it, or "
                  "--ticket <ID> for the new one."
                  % (paused, paused), file=sys.stderr)
            sys.exit(2)

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
    #
    # Asked for what this EDGE requires, not only for what this run happens to
    # name on the command line. The closing edge is the one write in a ticket
    # that claims nothing — CLOSEOUT→IDLE spends `commit` and `pr` and wipes the
    # gates in the same write — so a helper that only asked about `--gate` asked
    # about nothing exactly where the evidence matters most, and a ticket closed
    # over uncommitted work with exit 0. The hook's `decide_pre` learned this
    # first; the helper the method actually tells the model to run had not.
    _owed = sorted(set(list(args.gate or []) + list(_cfg.get("gates") or [])))
    reason = vt.gate_evidence_missing(
        os.path.dirname(os.path.abspath(args.state)),
        {**new_state, "ticket": new_state.get("ticket") or old_state.get("ticket")},
        _owed)
    if reason:
        print("ddw-transition: " + reason, file=sys.stderr)
        sys.exit(2)

    try:
        vt.validate(old_state, new_state, graph, state_path=args.state)
    except vt.Block as exc:
        # validate()'s message is the truth (single source of truth — we do not
        # duplicate the graph's logic), but we add an actionable hint from the
        # context the helper ALREADY knows (phase on disk, --to, --tier). The
        # cryptic "is not in the graph" alone does not tell the model what to do.
        disk_phase = old_state.get("phase", "IDLE")
        history = old_state.get("history") or []
        action_kind = (args.action or "").strip().lower().split(":", 1)[0].strip()
        if disk_phase == "IDLE" and args.to != "CLASSIFY":
            # "The only transition out of IDLE is CLASSIFY" is false, and the
            # suite's own happy path is the counterexample: a paused ticket
            # re-enters the phase it was paused in, and `--to DEFINE --action
            # "resume: …"` exits 0 over the very state this hint was printed
            # for. A reader who believed it would abandon a ticket that was one
            # flag away from continuing — which is the advice the pause exists
            # to make unnecessary.
            paused_at = vt._paused_at(history, len(history), old_state.get("ticket"))
            if paused_at == args.to and action_kind != "resume":
                hint = (
                    "This ticket was paused in %s, so the edge you want exists — as a resume, "
                    "and only the action says so: --action \"resume: <why now>\"." % paused_at
                )
            elif paused_at:
                hint = (
                    "Out of IDLE there are two edges, and %s is neither: --to CLASSIFY starts a "
                    "ticket, and the paused ticket in this history goes back to where it stopped "
                    "(--to %s --action \"resume: <why now>\")." % (args.to, paused_at)
                )
            else:
                hint = (
                    "From IDLE the only transition is --to CLASSIFY: a resume is proven by the "
                    "pause it picks up, and nothing in this history is paused. Run CLASSIFY "
                    "first, then --to <phase> (one run per edge)."
                )
        elif args.to == "IDLE":
            # Closing the ticket wipes the gates, so `new_state["tier"]` is
            # ALWAYS None here and the tier hint below fired on every refused
            # closeout — sending the reader to a flag this edge ignores. What is
            # actually missing is a gate, and it is claimed before the edge, not
            # on it.
            #
            # But "run --claim commit --claim pr first" was pasted onto EVERY
            # refused edge to IDLE, including the ones where no such edge
            # exists. From CODE both claims succeed, exit 0, and the retry
            # prints this same refusal word for word: a fixed point, and the
            # only conclusion left to the reader is that the tool is broken. The
            # gates are the answer where the graph asks for them, and the graph
            # is where that is written.
            owed = list(_cfg.get("gates") or [])
            if action_kind in ("pause", "abandon"):
                # A pause and an abandon reach IDLE without an edge, and every
                # way they are refused — `no_walkaway`, a pause with nothing
                # committed — is refused by a message that already names its own
                # way out.
                hint = ""
            elif owed:
                hint = (
                    "Gates are earned in the phase that owns them, not on the edge out of it: "
                    "`--gate` is not read on --to IDLE, because reaching IDLE clears the gates. "
                    "Run `--claim %s` first (one run, no phase change), then take this edge."
                    % " --claim ".join(owed)
                )
            else:
                froms = sorted({p.split("->", 1)[0] for p in _edges if p.endswith("->IDLE")})
                closes = ", ".join(froms) if froms else "no phase in this tier"
                # The tier comes from the flag or from disk, never from
                # `new_state`: reaching IDLE clears it, so the state being built
                # here has none by construction.
                tier = args.tier or old_state.get("tier")
                hint = (
                    "There is no %s→IDLE edge%s — the closeout is taken from %s. Claiming gates "
                    "here changes nothing: it is the edge that is missing, not the evidence."
                    % (disk_phase, " in tier %s" % tier if tier else "", closes)
                )
        elif new_state.get("tier") is None and args.tier is None:
            hint = (
                "The tier is missing: pass --tier <" + "|".join(_tiers(graph)) + "> (it is set on the "
                "CLASSIFY→DEFINE/DISCOVERY transition)."
            )
        elif str(exc).startswith("gate "):
            # The validator's own message already names the gate, the validator
            # that earns it and the command that claims it. Appending "check the
            # graph" here sent the reader to a file with nothing wrong in it —
            # the graph is right, the evidence is missing.
            hint = ""
        else:
            hint = (
                "Transitions are one per edge; check the graph in "
                ".ddw/rules/transition-graph.json."
            )
        # A space between two sentences and no full stop read as one sentence
        # that ran on: "…is not true Transitions are one per edge".
        joined = f"{exc} {hint}".strip() if hint else str(exc)
        print(f"ddw-transition: illegal transition, nothing emitted: {joined}", file=sys.stderr)
        sys.exit(2)

    _emit(args, new_state, seen=old_text)


if __name__ == "__main__":
    # Fail closed, and with a sentence rather than a stack. The module's own
    # contract says "exits 2 with the reason on stderr", and anything main() did
    # not anticipate — a graph whose `common` is a string, a state whose `gates`
    # is a list — came out as a traceback and exit 1. Exit 1 is what a shell
    # reads as an ordinary error and a caller may well continue past; 2 is the
    # verdict this tool speaks in.
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:                      # noqa: BLE001 — the point is breadth
        print("ddw-transition: could not reach a verdict (%s: %s). Nothing was emitted and "
              "nothing was written." % (type(exc).__name__, exc), file=sys.stderr)
        sys.exit(2)
