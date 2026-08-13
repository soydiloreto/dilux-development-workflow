#!/usr/bin/env python3
"""The single enforcement entry point every tool's hook calls.

Each tool speaks its own dialect twice over: the shape of the event it hands a
hook, and the way that hook says "deny". Everything in between — is this write
touching the state file, is the transition legal, which gate is missing, may
this phase write source at all — is the same question, and it is answered once,
in `validate-transition.py`, by `decide_pre()` and `decide_post()`.

**This file contains no policy.** It translates an envelope in and a verdict
out. That rule is not tidiness: two copies of the same decision drift, and the
copy that runs is not necessarily the copy that gets reasoned about — or tested.
Anything this file decides for itself is a second implementation of the FSM.

    hook-gate.py --dialect copilot --mode pre --state … --graph … --repo …

`--mode post` ignores the event entirely and revalidates the state on disk,
which is how the Bash/jq bypass gets caught on every tool, not just one.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _touch_marker(repo, session_id):
    """Refresh this session's liveness marker, and never fail over it.

    Best effort in the strongest sense: a hook whose job is to allow or refuse a
    write must not turn a full disk, a read-only checkout or a session id the
    harness declined to send into a verdict. Anything that goes wrong here
    leaves the count stale, which is what it was before.
    """
    if not repo or not session_id:
        return
    try:
        path = os.path.join(_HERE, "session-boot.py")
        spec = importlib.util.spec_from_file_location("ddw_session_boot", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.refresh_marker(repo, str(session_id))
    except Exception:                                         # noqa: BLE001
        pass


def _load_validator():
    path = os.path.join(_HERE, "validate-transition.py")
    spec = importlib.util.spec_from_file_location("ddw_validate_transition", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Dialects ─────────────────────────────────────────────────────────────────
#
# `name`/`args`: where (tool_name, tool_input) hide in that tool's envelope.
# `args_is_json_string`: some tools hand external command hooks the arguments
#   double-encoded — a JSON string, not an object. GitHub documents this for
#   Copilot CLI verbatim ("Because toolArgs is a JSON string, your script must
#   parse it before reading fields"). Read as an object it comes out empty, so
#   there is no path to judge and the write is allowed.
#
# Exit 2 with the reason on stderr is honoured by every tool documented so far;
# the ones that also read a JSON verdict get it, because the JSON carries the
# reason back to the model as a tool error instead of console noise.
DIALECTS = {
    # Claude Code, Codex CLI, Gemini CLI, Cursor: snake_case envelope.
    "standard": {"name": "tool_name", "args": "tool_input"},
    # Codex hides the path inside an apply_patch program, not in a field.
    "codex": {"name": "tool_name", "args": "tool_input", "apply_patch": True},
    # Copilot CLI: camelCase envelope, and toolArgs arrives as a JSON string.
    "copilot": {"name": "toolName", "args": "toolArgs", "args_is_json_string": True},
    # Cursor and Gemini send the same snake_case envelope and differ only in how
    # a refusal is written, which `deny` handles. They are spelled out rather
    # than left to the fallback: reaching the generic spec because nothing
    # matched is indistinguishable from reaching it because someone decided it
    # should, and the day either tool changes its envelope the difference is the
    # whole finding.
    "cursor": {"name": "tool_name", "args": "tool_input"},
    "gemini": {"name": "tool_name", "args": "tool_input"},
}

# The whole file a Write carries. `new_str`/`newString` are deliberately NOT here:
# they are the second half of an EDIT, and treating one as content reconstructs
# the state as just that fragment — which then fails to parse, so every legal
# edit is refused for being unreadable.
CONTENT_KEYS = ("content", "contents", "text", "patchText")

# Codex's `apply_patch` carries the file it touches inside its `command`, in the
# patch program's own header lines. There is no path field to read.
_PATCH_MARKERS = ("*** Add File: ", "*** Update File: ", "*** Delete File: ",
                  "*** Move to: ")


def _paths_from_patch(program):
    out = []
    for line in (program or "").splitlines():
        line = line.strip()
        for marker in _PATCH_MARKERS:
            if line.startswith(marker):
                out.append(line[len(marker):].strip())
    return out


def normalize(event, dialect):
    """Turn any tool's envelope into (tool_name, tool_input, paths)."""
    spec = DIALECTS.get(dialect, DIALECTS["standard"])
    tool_name = event.get(spec["name"]) or event.get("tool_name") or ""
    tool_name = str(tool_name) if tool_name is not None else ""

    args = event.get(spec["args"])
    raw_args = args if isinstance(args, str) else None
    if spec.get("args_is_json_string") and isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = None
    if not isinstance(args, dict):
        fallback = event.get("tool_input")
        args = fallback if isinstance(fallback, dict) else {}

    vt = _VALIDATOR
    paths = [args.get(k) for k in vt.PATH_KEYS]
    paths = [p for p in paths if isinstance(p, str) and p]

    # A path key that is present but not a string is not a permitted path — it
    # is an unreadable one, and unreadable is not permitted.
    typed_but_wrong = any(
        k in args and args[k] is not None and not isinstance(args[k], str)
        for k in vt.PATH_KEYS
    )

    if spec.get("apply_patch") and not paths:
        paths = _paths_from_patch(args.get("command"))

    # Copilot's INTERACTIVE writes arrive as `apply_patch` with toolArgs being
    # the raw patch PROGRAM — not a JSON string. json.loads failed, no path
    # survived, and every interactive write sailed past the gate unjudged while
    # the documented `create`+JSON envelope kept the suite green. Captured live
    # (M4: src/probe3.ts landed in DEFINE). The patch names its own files.
    patch_add_content = None
    if not paths and raw_args and "*** Begin Patch" in raw_args:
        paths = _paths_from_patch(raw_args)
        # A single-file Add patch IS its file: the + lines are the whole
        # content. Without this, a LEGAL state creation through the same
        # envelope was refused for carrying no content, and the refusal pushed
        # the model to a shell heredoc — the one write path that only gets
        # detected. Updates stay unreconstructable (no base to apply onto);
        # for the state, the refusal now names transition.py --write instead.
        if (len(paths) == 1 and "*** Add File: " in raw_args
                and "*** Update File: " not in raw_args):
            body, in_body = [], False
            for ln in raw_args.splitlines():
                if ln.startswith("*** Add File: "):
                    in_body = True
                    continue
                if ln.startswith("*** End Patch"):
                    break
                if in_body and ln.startswith("+"):
                    body.append(ln[1:])
            if body:
                patch_add_content = "\n".join(body) + "\n"

    out = dict(args)
    if "content" not in out:
        for k in CONTENT_KEYS:
            if isinstance(args.get(k), str):
                out["content"] = args[k]
                break
    # OpenCode names the edit pair in camelCase.
    if "old_string" not in out and isinstance(args.get("oldString"), str):
        out["old_string"] = args["oldString"]
    if "new_string" not in out and isinstance(args.get("newString"), str):
        out["new_string"] = args["newString"]
    if paths:
        out["file_path"] = paths[0]
    if patch_add_content is not None and not isinstance(out.get("content"), str):
        out["content"] = patch_add_content

    # A tool the validator cannot reconstruct fails CLOSED on the state file.
    # Normalizing the verb is what keeps that from refusing every legal write:
    # `apply_patch`, `edit`, `str_replace` and friends all mean one of the two
    # things it knows.
    verb = tool_name.lower()
    if out.get("content") is not None:
        canonical = "Write"
    elif "old_string" in out or "new_string" in out:
        canonical = "Edit"
    elif any(w in verb for w in ("write", "create", "apply_patch", "notebook")):
        canonical = "Write"
    else:
        canonical = "Edit"

    # The canonical verb is for RECONSTRUCTING the state file, and it deliberately
    # falls through to "Edit" so an unrecognised tool aimed at the state fails
    # closed. But it also ERASES what the tool was — and `decide_pre` needs that
    # to tell a read from a write. Handed a canonical "Edit", it saw the word
    # "edit" and judged a `Read` as a write: on Copilot, whose hook has no
    # matcher, the agent was refused permission to read DDW's own rules.
    #
    # So the original name travels alongside. Fixing the decision without fixing
    # what reaches it changed nothing, and the check missed it by calling
    # decide_pre directly — testing the layer under the defect.
    return canonical, out, paths, typed_but_wrong, tool_name


# Tools whose POST hook cannot refuse anything. GitHub documents Copilot CLI's
# postToolUse as able to "modify the tool result or inject additional context"
# and nothing more: `permissionDecision` is exclusive to preToolUse, and a
# non-zero exit is "logged and skipped — agent execution continues".
#
# So on Copilot the post-write net cannot stop a turn. Sending it a refusal it
# ignores is worse than useless: the check reads as covered and nothing happens.
# What it CAN do is put the finding in front of the model, which is enough for
# the one thing this net is for — the orchestrator's rule is to STOP and report
# on a corrupt state, and a model that has been told will follow it. That is a
# promise where Claude has a guarantee, and the difference is recorded rather
# than smoothed over.
POST_CANNOT_BLOCK = {"copilot"}


# `git … commit`, not crossing a shell separator — so `git log … | grep commit`
# is not a commit and `git -C sub commit` still is. It over-matches rather than
# under-matches on purpose: an extra prompt costs a keystroke, a missed one is
# the whole defect this gate exists for. `--dry-run` writes nothing, so it is
# the one spelling that is let through.
_IS_COMMIT = re.compile(r"\bgit\b(?![^|&;]*--dry-run)[^|&;]*\bcommit\b")


# What a corrupt state is: an incident to report, never a task to take on.
#
# The two halves of this net used to say opposite things. The reporting path
# (Copilot, which cannot refuse) said stop and do not repair. The BLOCKING path —
# the one that runs on every tool that can refuse, which is most of them — said
# "Fix the state and redo the transition", and blamed Bash/jq/sed for a write the
# model had made with `Write`.
#
# Both halves were wrong in the way that matters. The accusation is a guess
# printed as a fact, so the model looks for a shell command it never ran. And the
# order to repair cannot be carried out: restoring the header without a history
# entry is refused for missing the entry, and adding the entry is refused because
# that edge is not in the graph. Told to fix it, a model tried eight times and
# then found the one thing that does work — `rm .ddw-state.json` — which is
# precisely the outcome this net exists to prevent.
STOP_AND_REPORT = (
    "\n\nSTOP. Do not continue the pipeline, do not repair the state, and do not delete it. "
    "Report this to the user in your next message and wait for them.\n"
    "Repairing it is not yours to do: it erases the evidence of what wrote it, and the graph "
    "may have no edge back from where the file now claims to be — which is how an attempt to "
    "help turns into a loop that ends in deleting the history.\n"
    "The user's recovery is restoring their own backup, or `.ddw/scripts/transition.py` from "
    "the last state the history actually supports. `git checkout` is not a recovery here: the "
    "install gitignores the state, so git has no copy of it.\n"
    "You cannot write the fix yourself — while the state is corrupt the gate refuses YOUR "
    "writes to it, by design, including the correct one. If you can compute the corrected "
    "content, save it to a scratch file outside the repo and give the user one copy command to "
    "run; do not offer to write the state."
)


def corrupt_state_reason(exc):
    """One sentence of finding, one instruction, on every dialect."""
    return ("DDW FSM found an ILLEGAL .ddw-state.json on disk: "
            f"{str(exc).rstrip('.')}. This can come from a Bash/jq/sed write, which bypasses "
            "the pre-write hook, or from a write that was legal when it was made and is not "
            "legal now." + STOP_AND_REPORT)


def already_reported(state_path, reason):
    """Has this exact finding, about this exact file, been said already?

    The post net revalidates the state on EVERY tool call, so one corrupt file
    printed the same eight-line finding on `git status`, on `git log`, on every
    Read. That is not eight findings, it is one — and burying the instruction to
    stop under twenty repetitions of itself is what pushes a model to start
    manoeuvring instead of reporting.

    Keyed on the state's content: the moment the file changes, this is a new
    finding and is said in full again. Failing to record it only costs a repeat,
    so any IO problem here falls back to saying it.
    """
    try:
        with open(state_path, "rb") as fh:
            key = hashlib.sha256(fh.read() + reason.encode()).hexdigest()
        marker = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                              ".ddw-sessions", "corrupt-reported")
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        if os.path.exists(marker):
            with open(marker, encoding="utf-8") as fh:
                if fh.read().strip() == key:
                    return True
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(key)
    except OSError:
        pass
    return False


def report_post(dialect, reason):
    """Say it where a refusal is not available. Exits 0 on purpose."""
    if dialect == "copilot":
        print(json.dumps({"additionalContext": "DDW: " + reason}))
    print(reason, file=sys.stderr)
    sys.exit(0)


def deny(dialect, reason):
    """Refuse the write in the dialect this tool understands."""
    if dialect == "copilot":
        # GitHub's preToolUse schema. `decision`/`reason` belong to agentStop;
        # sending those meant the refusal only landed by virtue of exit 2, and
        # the reason never reached the model through the documented channel.
        print(json.dumps({"permissionDecision": "deny",
                          "permissionDecisionReason": reason}))
    elif dialect == "cursor":
        print(json.dumps({"permission": "deny", "agent_message": reason,
                          "user_message": "DDW blocked this write."}))
    elif dialect == "gemini":
        print(json.dumps({"decision": "deny", "reason": reason}))
    elif dialect == "codex":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    print(reason, file=sys.stderr)
    sys.exit(2)


# Where the message being proposed lives, and the proof that a human saw it.
#
# `ddw-commit` writes the message it is showing to PROPOSAL. The turn hook —
# which runs when the user speaks, and only then — stamps SEAL with a digest of
# whatever PROPOSAL held at that moment. A commit is allowed when the digest of
# the message it is about to write matches the sealed one, which can only be
# true if that exact text was on screen before the user answered.
#
# The first design refused the FIRST attempt and allowed the second, counting
# turns. It enforced the same thing and cost a round trip every time: a model
# that had done exactly the right thing — shown the message, waited, been told
# to go — still had its attempt refused, because it was the first attempt the
# gate had seen. Sealing at proposal time instead of at attempt time removes
# that, and buys something the counter never had: the bytes are compared, so
# showing one message and committing another is no longer possible.
def _paths(repo):
    """The proposal the model writes, and the seal only a hook writes.

    They are deliberately in different places. `.ddw-sessions/` holds the
    receipts six of the eight gates read, so every write into it is refused in
    every phase — a model that could write there could forge a gate. The first
    version of this put the proposal there, and DDW's own painted-door eval
    caught it in one run: a skill ordering a write the guard refuses is the
    defect this repository has spent the most time removing.
    `.ddw-work/` is the runtime that IS writable, in every phase, by design.
    """
    base = repo or "."
    return (os.path.join(base, ".ddw-work", "commit-message.txt"),
            os.path.join(base, ".ddw-sessions", "commit-seen"))


def _digest(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read().strip()).hexdigest()
    except OSError:
        return None


def seal_proposal(repo):
    """The user just spoke: whatever is being proposed, they have now seen it."""
    proposal, seal = _paths(repo)
    digest = _digest(proposal)
    if digest is None:
        return
    try:
        os.makedirs(os.path.dirname(seal), exist_ok=True)
        with open(seal, "w", encoding="utf-8") as fh:
            fh.write(digest)
    except OSError:
        pass                         # never fail a turn over bookkeeping


def commit_verdict(repo, command):
    """None to allow, or the reason to refuse."""
    proposal, seal = _paths(repo)
    rel = os.path.join(".ddw-work", "commit-message.txt")
    howto = (
        "\nHow this works: write the message you are about to show — gitmoji, type, scope, body "
        "and trailers, exactly as it will be committed — to `%s`, show it to the user, and END "
        "YOUR TURN. When they answer, commit it with:\n"
        "    git commit -F %s\n"
        "The file is what gets committed, so what they read and what lands are the same bytes." % (rel, rel))
    # The message has to come from the file, so no comparison of shell-quoted
    # text is needed — and none can be got wrong. `-m` through the shell is the
    # same quoting problem that took `--set` out of the transition helper.
    if not re.search(r"(?:^|\s)(?:-F|--file)[=\s]+\S*\.ddw-work/commit-message\.txt", command):
        return ("DDW (assisted): a commit takes its message from the file the user was shown."
                + howto)
    digest = _digest(proposal)
    if digest is None:
        return ("DDW (assisted): `%s` does not exist, so nothing says the user has seen this "
                "message." % rel) + howto
    try:
        with open(seal, encoding="utf-8") as fh:
            sealed = fh.read().strip()
    except OSError:
        sealed = ""
    if sealed != digest:
        return (
            "DDW (assisted): this message has not been in front of the user yet — it was written "
            "during the turn you are still in.\n"
            "`ddw-commit` step 7 is to present it and step 8 is to commit only after they "
            "approve, and `assisted` means every step waits for a person. Show it, end your turn, "
            "and run the same command once they have answered. Do NOT reach for a different "
            "command: the refusal is the pause, not an obstacle to route around.\n"
            "If the user wants commits to stop waiting, that is `autonomy: minimal`, decided in "
            "CLASSIFY with the cost stated, not something to infer from impatience.")
    for path in (proposal, seal):    # spent: the next commit is proposed afresh
        try:
            os.unlink(path)
        except OSError:
            pass
    return None


def allow(dialect):
    # Tools that read a JSON verdict want a well-formed one; the rest treat any
    # stdout on an allow as noise, so they get silence. Cursor is explicit
    # because an empty object there reads as "no decision", and a hook that
    # declines to decide is not the same as one that approves.
    if dialect == "cursor":
        print(json.dumps({"permission": "allow"}))
    elif dialect in ("copilot", "gemini", "codex"):
        print("{}")
    sys.exit(0)


_VALIDATOR = None


def main():
    global _VALIDATOR
    ap = argparse.ArgumentParser()
    # The choices come off the table itself, so the two cannot disagree: a name
    # the table does not carry is a mistake, not a quiet fall back to generic.
    ap.add_argument("--dialect", choices=tuple(DIALECTS), default="standard")
    ap.add_argument("--mode", choices=("pre", "post", "commit", "turn"), default="pre")
    ap.add_argument("--state", required=True)
    ap.add_argument("--graph", required=True)
    ap.add_argument("--repo", default=None,
                    help="repo root; relative paths in the event resolve against it")
    # Where the method itself lives, which under a plugin install is NOT inside
    # the repo — and every guard on DDW's own files was written as "is this path
    # under the repo root?". So the graph, this file and the validator were all
    # writable, and the plugin root is shared, so one write disarmed DDW in every
    # repository using it. The hooks already resolve this path to find the gate;
    # passing it costs nothing and is the only thing that knows where the method
    # is when it is not in the repo.
    ap.add_argument("--method", default=None,
                    help="the method root (.ddw, or the plugin's copy); no phase writes inside it")
    args = ap.parse_args()

    if args.mode == "turn":
        # The user just spoke. Two things follow from that and nothing else
        # does: whatever was being proposed to them has now been seen, and a
        # turn has passed — which is the only signal a hook has that the run is
        # allowed to take its next arrow. This decides nothing and prints
        # nothing: whatever a hook on this event writes to stdout is prepended
        # to the user's own message.
        seal_proposal(args.repo)
        try:
            counter = os.path.join(args.repo or ".", ".ddw-sessions", "turn")
            os.makedirs(os.path.dirname(counter), exist_ok=True)
            try:
                with open(counter, encoding="utf-8") as fh:
                    n = int(fh.read().strip())
            except (OSError, ValueError):
                n = 0
            with open(counter, "w", encoding="utf-8") as fh:
                fh.write(str(n + 1))
        except OSError:
            pass                     # never fail a turn over bookkeeping
        sys.exit(0)

    _VALIDATOR = vt = _load_validator()

    if args.mode == "post":
        # Not every tool's post hook can refuse. On the ones that cannot, saying
        # it is all there is — and saying it is still worth doing.
        _refuse = report_post if args.dialect in POST_CANNOT_BLOCK else deny

        def refuse(dialect, reason):
            """Still refuses every time; says the whole finding only the first."""
            if already_reported(args.state, reason):
                reason = ("DDW: .ddw-state.json is still the corrupt one reported above. "
                          "STOP and wait for the user — nothing here is yours to repair.")
            _refuse(dialect, reason)

        try:
            reason = vt.decide_post(args.state, args.graph)
        except vt.Block as exc:
            # `{exc}.` doubled the full stop on every reason that already ended
            # in one — which is most of them, and it is the first thing a user
            # sees when the net catches something.
            refuse(args.dialect, corrupt_state_reason(exc))
        if reason:
            refuse(args.dialect, reason + STOP_AND_REPORT)
        # Detection, not prevention, and deliberately not a refusal: the shell
        # bypasses the pre-write guard, and DDW cannot tell the agent's shell
        # from the user's own editing in another terminal. See
        # `source_changed_in_no_source_phase` and decision 12 in RATIONALE.md.
        if args.repo:
            try:
                phase = json.load(open(args.state, encoding="utf-8")).get("phase")
            except (OSError, ValueError, AttributeError):
                phase = None
            if phase:
                note = vt.source_changed_in_no_source_phase(args.repo, phase)
                if note:
                    print(f"DDW notices: {note}", file=sys.stderr)
        allow(args.dialect)

    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except ValueError:
        allow(args.dialect)          # unreadable envelope: not ours to judge
    if not isinstance(event, dict):
        allow(args.dialect)

    # Housekeeping, not policy — the rule at the top of this file is about
    # DECISIONS, and this decides nothing: it says "still here" on behalf of a
    # session that is plainly still here, since it is asking for a verdict. The
    # marker expires after two hours, and only the Claude adapter had a second
    # PreToolUse shim to refresh it from; in the other five tools every session
    # longer than that was swept off disk and the concurrency guard went quiet
    # for exactly the sessions worth warning about. The write itself lives in
    # session-boot.py, so there is still one definition of what a marker is.
    _touch_marker(args.repo, event.get("session_id") or event.get("sessionId"))

    tool_name, tool_input, paths, typed_but_wrong, raw_name = normalize(event, args.dialect)

    if args.mode == "commit":
        # Anything that is not a commit is not this gate's business. The matcher
        # fires on every shell call, so silence on the other 99% is the point.
        command = tool_input.get("command")
        if not isinstance(command, str) or not _IS_COMMIT.search(command):
            allow(args.dialect)
        # `minimal` was opted into with the cost stated out loud, and what it
        # removes is the asking, not the showing. A commit is local and
        # reversible, so it is not one of the acts that keep their confirmation
        # in both modes — those are the ones that leave the repository.
        try:
            with open(args.state, encoding="utf-8") as fh:
                autonomy = (json.load(fh) or {}).get("autonomy")
        except (OSError, ValueError, AttributeError):
            autonomy = None              # unreadable reads as assisted, like absent
        if autonomy == "minimal":
            allow(args.dialect)
        reason = commit_verdict(args.repo, command)
        if reason:
            deny(args.dialect, reason)
        allow(args.dialect)

    if typed_but_wrong:
        deny(args.dialect,
             "the event names a file path that is not a string, so this write cannot be "
             "judged. A path DDW cannot read is not a path it can allow.")

    try:
        reason = vt.decide_pre(args.state, args.graph, tool_name, tool_input, paths,
                               repo=args.repo, raw_tool=raw_name, method=args.method)
    except vt.Block as exc:
        deny(args.dialect, f"DDW FSM blocked the write to the state: {exc}")
    if reason:
        deny(args.dialect, f"DDW blocked this write: {reason}")
    allow(args.dialect)


if __name__ == "__main__":
    # Fail CLOSED on anything unexpected. An uncaught exception exits 1, and 1 is
    # not a refusal — every harness reads it as "the hook errored" and lets the
    # write through.
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:                                  # noqa: BLE001
        _d = "standard"
        if "--dialect" in sys.argv:
            try:
                _d = sys.argv[sys.argv.index("--dialect") + 1]
            except IndexError:
                pass
        deny(_d, f"DDW could not reach a verdict ({type(exc).__name__}: {exc}). Refusing the "
                 "write — a state it cannot read is a state it cannot vouch for.")
