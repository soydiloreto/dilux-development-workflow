#!/usr/bin/env python3
"""What every tool has to do when a session starts, written once.

Three things, none of them tool-specific:

  1. Materialize `.ddw-state.json` if the repo does not have one yet, and keep
     the runtime files out of git.
  2. Warn when another session is already working in this same directory —
     there is ONE state file per directory, so two sessions clobber each other
     whatever tool they run under. The markers are shared across tools on
     purpose: Claude Code in one terminal and OpenCode in another are still two
     sessions on one state file.
  3. Tell the agent to read the orchestrator and run its boot sequence.

This lived three times, once per adapter, with the two-hour cutoff and the
marker protocol re-encoded each time and a different session-id key in each
copy. That is method logic, and method logic does not belong in an adapter.

    session-boot.py --repo /path/to/repo [--session-id X] [--format text|json]

`--format json` emits `{"additionalContext": "…"}` for the harnesses that read a
JSON verdict; the rest get plain text on stdout.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

STALE_SECONDS = 2 * 60 * 60          # a marker not refreshed in 2h is a dead session
GITIGNORE_ENTRIES = (".ddw-state.json", ".ddw-paused/", ".ddw-sessions/",
                     ".ddw-journal.jsonl", ".ddw/**/__pycache__/")

IDLE_STATE = {
    "tier": None,
    "phase": "IDLE",
    "ticket": None,
    "title": None,
    "tracker": None,
    "gates": {},
    "block": None,
    "autonomy": None,
    "discovery": None,
    "history": [],
}


def safe_id(session_id):
    """A session id arrives from the harness and is used as a FILENAME.

    Written straight through, an id shaped like a path escapes the sessions
    directory: `--session-id ../.ddw-state.json` would replace the pipeline
    state with a timestamp and report success. Whatever the harness calls a
    session, on disk it is one flat name.
    """
    clean = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in str(session_id))
    return (clean.strip(".-") or "session")[:120]


def ensure_state(repo):
    """Create the state file if absent. Returns the current phase.

    Everything here fails OPEN except where that would be a lie. A read-only
    checkout is not worth failing over — but a state file that exists and cannot
    be read is not IDLE, it is unknown, and saying "IDLE" clears the agent to
    start fresh work on top of a ticket that may be mid-flight.
    """
    path = os.path.join(repo, ".ddw-state.json")
    if not os.path.exists(path):
        try:
            # Written whole and moved into place: a truncated create leaves a
            # zero-byte file that every later read calls IDLE, forever.
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(IDLE_STATE, fh, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except OSError:
            return "IDLE"
        return "IDLE"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data.get("phase", "IDLE")
    except (OSError, ValueError):
        return "UNREADABLE"


def ensure_gitignore(repo):
    """The runtime is per-developer, never committed. Idempotent."""
    path = os.path.join(repo, ".gitignore")
    try:
        existing = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        # Whole non-comment lines, not whitespace tokens. Splitting the file on
        # whitespace matched DDW's own explanatory comments — `#   .ddw-paused/
        # = paused tickets` contains the token — so once the rules were lost but
        # the comments survived, the check believed everything was in place and
        # the runtime got staged for commit, permanently.
        rules = {ln.strip() for ln in existing.splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#")}
        missing = [e for e in GITIGNORE_ENTRIES if e not in rules]
        if not missing:
            return
        with open(path, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            for entry in missing:
                fh.write(entry + "\n")
    except OSError:
        pass                          # a read-only checkout is not worth failing over


def other_live_sessions(repo, session_id):
    """Count sessions other than this one that are still alive on this directory.

    Registers FIRST, then counts. The other order is a race the guard loses
    against the exact scenario it exists for — two terminals opened on one repo
    at the same time — and in that window neither session was warned.
    """
    sess_dir = os.path.join(repo, ".ddw-sessions")
    now = time.time()
    mine = os.path.join(sess_dir, session_id)
    registered = False
    try:
        os.makedirs(sess_dir, exist_ok=True)
        with open(mine, "w", encoding="utf-8") as fh:
            fh.write(str(int(now)))
        registered = True
    except OSError:
        pass          # cannot register; still worth counting who else is here

    try:
        others = 0
        for name in os.listdir(sess_dir):
            full = os.path.join(sess_dir, name)
            try:
                if now - os.stat(full).st_mtime > STALE_SECONDS:
                    os.unlink(full)
                    continue
            except OSError:
                continue
            # Case-insensitively: on macOS and Windows two ids differing only in
            # case are ONE file, so a session ended up warning about itself
            # forever while being alone on disk.
            if name.lower() != session_id.lower():
                others += 1
        return others if registered else others
    except OSError:
        return 0


def awaiting_review(repo, timeout=5):
    """Your open pull requests in this repo, or why they could not be read.

    Deterministic, and that is the whole design of it: **phase is IDLE and the
    repo has a remote → ask, every time. Anything else → never ask.** No
    heuristics, no "sometimes". Mid-ticket it stays quiet — you know what you are
    doing and a network call on every session start, in every repo DDW is
    installed in, is a cost worth refusing.

    IDLE is the moment the question is worth asking: you have nothing in flight
    and you are about to decide what is next. It also covers the case a local
    file cannot — a fresh clone on another machine, where there is no paused
    ticket to notice, because the pause lives in `.ddw-paused/` and that never
    leaves the machine that wrote it. The forge is the only shared record.

    It never raises and never guesses. When it cannot look, it says so and says
    why: an empty answer and an unanswerable question are different things, and
    printing nothing for both is how a tool teaches people it has nothing to say.
    """
    try:
        remote = subprocess.run(["git", "-C", repo, "remote"], capture_output=True,
                                text=True, timeout=timeout)
    except Exception:
        return []
    if remote.returncode != 0 or not remote.stdout.strip():
        return []                      # no remote: no pull requests to have, and no noise
    try:
        out = subprocess.run(["gh", "pr", "list", "--author", "@me", "--state", "open",
                              "--json", "number,title,headRefName,reviewDecision,updatedAt"],
                             cwd=repo, capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return ["🔕 DDW: could not check your open pull requests — `gh` is not installed."]
    except Exception:
        return ["🔕 DDW: could not check your open pull requests — the forge did not answer in "
                f"{timeout}s."]
    if out.returncode != 0:
        why = (out.stderr or "").strip().splitlines()
        detail = why[0][:120] if why else f"gh exited {out.returncode}"
        return [f"🔕 DDW: could not check your open pull requests — {detail}"]
    try:
        prs = json.loads(out.stdout or "[]")
    except ValueError:
        return ["🔕 DDW: could not check your open pull requests — gh returned something "
                "unparseable."]
    if not prs:
        return []
    lines = [f"🔎 DDW: {len(prs)} open pull request(s) of yours in this repo:"]
    for pr in prs[:8]:
        decision = (pr.get("reviewDecision") or "").upper()
        note = {"CHANGES_REQUESTED": "  ← changes requested",
                "APPROVED": "  ← approved, ready to merge"}.get(decision, "")
        lines.append(f"   #{pr.get('number')} {str(pr.get('headRefName'))[:44]}{note}")
    lines.append("   A ticket paused at RELEASE resumes there; what a reviewer asks for is a step "
                 "back, and each step back gives up the gates that phase granted.")
    return lines


def pending_subtickets(repo):
    """Sub-tickets whose PRD is on disk and whose closeout is not in the history.

    A split PRD produces `prd-FEAT-001a.md`, `…b.md`, `…c.md` and a parent that
    indexes them. The pipeline then runs ONE of them and resets to IDLE — and
    everything about the other three lived in whatever the model happened to say
    at closeout. Close the session and the only record left was the user's
    memory.

    This adds no state. Both halves are already on disk: the sub-PRDs are files,
    and `history` says which tickets reached IDLE. Pending is the difference.

    It over-reports rather than under-reports, on purpose. A history written
    before entries carried `ticket` cannot say what closed, so its sub-tickets
    all read as pending — being told about something already done costs a
    sentence, while missing one loses the work.
    """
    prd_dir = os.path.join(repo, "docs", "ddw", "prd")
    try:
        names = sorted(os.listdir(prd_dir))
    except OSError:
        return []

    subs = []
    for name in names:
        m = re.match(r"^prd-(.+[0-9])([a-z])\.md$", name)
        if m:
            subs.append((m.group(1), m.group(1) + m.group(2)))
    if not subs:
        return []

    try:
        with open(os.path.join(repo, ".ddw-state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(state, dict):
        return []

    # Left the pipeline: reached IDLE by any route except a pause, which is a
    # ticket that is coming back and therefore still pending.
    left = set()
    for entry in state.get("history", []):
        if not isinstance(entry, dict) or entry.get("to") != "IDLE":
            continue
        action = entry.get("action")
        action = action if isinstance(action, str) else ""
        if action.strip().lower().split(":", 1)[0].strip() in ("pause", "paused"):
            continue
        ticket = entry.get("ticket")
        if isinstance(ticket, str) and ticket:
            left.add(ticket)

    active = state.get("ticket")
    out = []
    for parent, ticket in subs:
        if ticket in left or ticket == active:
            continue
        out.append((parent, ticket))
    return out


CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")


def declined_recommendations(repo):
    """Recommendations from ddw-context-check that were turned down.

    Declining has to stop the full panel from asking again, or the check gets
    switched off out of irritation. But a decline that vanishes for good is
    worse than the question: the day the gap costs something — CI red, a
    pre-commit hook rejecting every commit — nothing would be left to say it was
    already known. So it survives as one line, and the panel stays quiet.
    """
    found = []
    for name in CONTEXT_FILES:
        path = os.path.join(repo, name)
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"<!--\s*ddw:declined\s+(\S+)\s+([^>]*?)-->", text):
            items = m.group(2).split()
            if items:
                found.append((name, m.group(1), items))
    return found


def emit(message, fmt, event="SessionStart"):
    """One message, four incompatible envelopes.

    Getting the spelling wrong is silent — the nudge is computed, formatted and
    dropped, and the pipeline simply never starts.
      copilot : {"additionalContext": …}                           (top, camel)
      cursor  : {"additional_context": …}                          (top, snake)
      codex   : {"hookSpecificOutput": {"additionalContext": …}}   (nested)
      gemini  : the same nested shape, carrying hookEventName
    `event` is the adapter's to supply: the tools do not agree on what the
    compaction event is called, and a nested envelope naming the wrong one is
    the same silent drop.
    """
    if fmt == "cursor":
        print(json.dumps({"additional_context": message}))
    elif fmt == "nested":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": event, "additionalContext": message}}))
    elif fmt == "json":
        print(json.dumps({"additionalContext": message}))
    else:
        print(message)


def compaction_nudge(orchestrator):
    """What the model has to redo before it answers again.

    The path is interpolated because it is `.ddw/` in a drop-in and somewhere
    under the plugin root otherwise, and a reminder naming a file the model
    cannot open is worse than no reminder at all.
    """
    return (
        "DDW POST-COMPACTION: the summary you are now working from is not the pipeline. "
        "RE-RUN the orchestrator's boot sequence before answering the user:\n"
        f"\n1. Read `{orchestrator}` (global agent rules + phase router)."
        "\n2. Read the repo's `.ddw-state.json` (phase, tier, ticket, title, gates, autonomy —"
        "\n   absent or null means assisted; this is what a compaction used to lose)."
        f"\n3. In `{orchestrator}`, find the \"Router: Phase `{{phase}}`\" section and load ONLY "
        "the files it lists."
        "\n4. Re-apply the mandatory status line at the start of your response.\n"
        "\nDo NOT answer without completing these 4 steps. The state machine is re-read from "
        "disk, never inferred from a post-compaction summary."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--session-id", default="")
    ap.add_argument("--method", default=None,
                    help="where the method lives. Defaults to <repo>/.ddw — pass it "
                         "when DDW comes from a plugin, because nothing in the repo "
                         "points at the orchestrator then.")
    ap.add_argument("--format", choices=("text", "json", "cursor", "nested"),
                    default="text")
    ap.add_argument("--quiet", action="store_true",
                    help="Do the housekeeping (state, .gitignore, refresh this "
                         "session's marker) and say nothing. For per-write hooks, "
                         "which must not narrate on every edit.")
    ap.add_argument("--event", default="SessionStart",
                    help="the tool's name for the event being answered. Only the "
                         "nested envelope carries it, and only that tool cares.")
    ap.add_argument("--compact", action="store_true",
                    help="Emit the post-compaction reminder instead of the boot "
                         "message. Every tool compacts, so the wording is the "
                         "method's and the event name is the adapter's.")
    args = ap.parse_args()

    repo = args.repo
    # Where the orchestrator is. Drop-in: `.ddw/` in the repo. Plugin: under the
    # plugin root, and the caller has to say where because nothing in the repo
    # points at it. The default keeps every existing caller working.
    method = args.method or os.path.join(repo, ".ddw")
    dropped_in = os.path.isdir(os.path.join(repo, ".ddw"))
    if not os.path.isdir(method):
        return                        # DDW is not reachable from here; say nothing

    # Compaction drops the middle of the conversation, and what it drops is the
    # phase router and the state that were read at boot. The model keeps
    # answering, now from a summary of the pipeline rather than the pipeline —
    # which is the one thing the orchestrator forbids inferring. Every one of the
    # six tools compacts and every one of them names the event differently, so
    # the wording belongs here and only the event name belongs to the adapter.
    if args.compact:
        orch = os.path.join(method, "orchestrator.md")
        emit(compaction_nudge(orch), args.format, args.event)
        return

    # **Nothing is written until the pipeline is actually running.**
    #
    # Drop-in earned its writes by existing: somebody put `.ddw/` in this repo,
    # so materialising the state and adding the gitignore block is finishing an
    # install they asked for. A plugin at user scope is loaded in EVERY repo you
    # open — including one you cloned to read for five minutes — and leaving a
    # state file and a modified .gitignore behind in each of them is not a
    # pipeline, it is litter.
    #
    # So under a plugin DDW stays read-only until a ticket exists. The first
    # transition writes `.ddw-state.json` through the ordinary path, and from
    # then on this repo has a pipeline and is treated like any other.
    started = dropped_in or os.path.exists(os.path.join(repo, ".ddw-state.json"))
    if started:
        phase = ensure_state(repo)
        ensure_gitignore(repo)
    else:
        phase = "IDLE"

    session_id = safe_id(args.session_id or f"pid-{os.getpid()}")
    others = other_live_sessions(repo, session_id) if started else 0

    lines = []
    if others:
        lines += [
            f"⚠️ DDW: {others} other session(s) are working in THIS SAME directory.",
            "   They share one .ddw-state.json and will clobber each other — one changes phase and",
            "   the other finds out when a hook stops it. To work in parallel, give each one its own",
            "   worktree: git worktree add ../<repo>-<TICKET> -b feat/<TICKET>",
        ]
    if phase == "IDLE":
        lines += awaiting_review(repo)
        pending = pending_subtickets(repo)
        if pending:
            listed = ", ".join(t for _, t in pending)
            parents = sorted({p for p, _ in pending})
            lines += [
                f"📌 DDW: {len(pending)} sub-ticket(s) of {', '.join(parents)} still have a PRD "
                f"and no closeout: {listed}.",
                "   Their PRDs are already written and validated. Say which one to continue and it "
                "goes through CLASSIFY → DEFINE, where the existing PRD is re-validated rather than "
                "rewritten.",
            ]

    declined = declined_recommendations(repo)
    if declined:
        total = sum(len(items) for _, _, items in declined)
        lines.append(
            f"🔕 DDW: {total} context recommendation(s) declined "
            f"({', '.join(sorted({i for _, _, items in declined for i in items}))}). "
            "Run /ddw-context-check to see them."
        )

    orch = os.path.join(method, "orchestrator.md")
    if not dropped_in:
        # Under a plugin the method stays with the plugin. The first agent that
        # got a full feature request in this mode reconciled the missing .ddw/
        # by running install.sh into the user's repo — the drop-in the user
        # never chose — and filled the context file from DDW's template. Said
        # here because this boot line is the plugin's one channel to the model.
        lines.append(
            "DDW comes from a plugin here. Do NOT install DDW into this repo — no install.sh, no "
            f"copying .ddw/ — resolve the method's `.ddw/...` references under {method}. The "
            "context file (AGENTS.md) is the PROJECT's: never put DDW content in it — no DDW "
            "blocks, no template boilerplate, no phase references. Only .ddw-state.json, its "
            ".gitignore entry and the phase artifacts (docs/) belong in the repo.\n"
            "Work that changes this repo starts by CLASSIFYING it into a ticket and walking the "
            "phases — NEVER by writing code first. IDLE does not mean free to code; it means no "
            "ticket has been started yet. A hand-written state file that skips the transitions is "
            "not a started ticket."
        )
    lines.append(
        f"DDW is active (phase {phase}). If the DDW orchestrator is not already in your context, "
        f"read {orch} now and run its Boot Sequence, silently, before answering."
        if phase != "UNREADABLE" else
        "⚠️ DDW: .ddw-state.json exists but cannot be read. This is NOT an idle pipeline — a "
        "ticket may be mid-flight. Do not start new work: restore the file from the last good "
        "version, or reset it to an idle state, and say so before continuing."
    )
    message = "\n".join(lines)

    if args.quiet:
        return
    emit(message, args.format, args.event)


if __name__ == "__main__":
    main()
