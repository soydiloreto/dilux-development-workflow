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


def refresh_marker(repo, session_id):
    """Say that this session is still here. Returns True if it could.

    Split out of `other_live_sessions` for one reason: the marker goes stale
    after STALE_SECONDS and only the Claude adapter had somewhere to refresh it
    from — an extra PreToolUse shim that runs on every write. In the other five
    tools the marker was written once at session start and swept two hours
    later, so every session long enough to matter vanished from the count and
    the concurrency warning stopped firing for exactly the sessions it exists
    for. The refresh is the method's, like everything else the hooks share, so
    it is one function here rather than five shims out there.
    """
    if not session_id:
        return False                  # no id, no marker (see the note in main)
    try:
        sess_dir = os.path.join(repo, ".ddw-sessions", "live")
        os.makedirs(sess_dir, exist_ok=True)
        with open(os.path.join(sess_dir, safe_id(session_id)), "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
        return True
    except OSError:
        return False


def other_live_sessions(repo, session_id):
    """Count sessions other than this one that are still alive on this directory.

    Registers FIRST, then counts. The other order is a race the guard loses
    against the exact scenario it exists for — two terminals opened on one repo
    at the same time — and in that window neither session was warned.

    Returns `(others, announced)`. The count is what it is whether or not this
    session managed to write its own marker; `announced` says whether the guard
    runs in both directions, and the caller says so out loud when it does not.
    """
    # A namespace of its own, and this is not tidiness. The markers used to live
    # directly in `.ddw-sessions/`, which is also where the six gates' RECEIPTS
    # live — and the sweep below unlinks anything older than STALE_SECONDS
    # without asking what it is. Every ticket longer than two hours, which is
    # every FEATURE, had its evidence deleted by the bookkeeping that thinks it
    # is expiring dead sessions; the gate then blamed the document ("if the PRD
    # changed after validating, validate again") for a change nobody made.
    # Measured. Liveness markers and evidence do not share a directory.
    sess_dir = os.path.join(repo, ".ddw-sessions", "live")
    now = time.time()
    # Registers FIRST, then counts, through the same function the write path
    # calls — one definition of what a marker is and where it lives.
    registered = refresh_marker(repo, session_id)

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
        return others, registered
    except OSError:
        return 0, registered


def _no_manifest(why):
    """`.ddw/` is here and the record of what was installed is not.

    Reported as loudly as a CHANGED file, because it is strictly worse: a
    changed file is one thing this can name, and a missing manifest is every
    file at once — nothing in the repository can be compared against anything
    again, and the state is permanent. It is also the cheapest thing in the
    world to reach, being a `rm` of a file whose name reads like a build
    artifact.
    """
    return [
        "⚠️ DDW: the record of what was installed here is gone.",
        f"   MISSING  .ddw-installed.json ({why})",
        "   `.ddw/` is in this repository, so DDW was installed into it — which means this "
        "file existed. Without it nothing can be checked against what was installed, and a "
        "tampered repository reads exactly like a clean one. Say so to the user before doing "
        "anything else; re-running `install.sh` writes it again.",
    ]


def enforcement_drift(repo):
    """Files DDW installed whose bytes no longer match what it installed.

    The pre-write hook refuses a WRITE to any of them, in every phase. What it
    cannot see is a shell: `printf > .ddw/rules/transition-graph.json` is not a
    tool call with a path in it, and `docs/RATIONALE.md` decision 11 is honest
    that the shell is detected rather than prevented. This is that detection —
    the manifest recorded a sha256 for every installed file at install time and
    nothing had ever read it back.

    It reports; it does not repair. A file that changed may be a tampered gate or
    may be a deliberate local edit, and DDW does not get to decide which by
    overwriting your work.
    """
    manifest = os.path.join(repo, ".ddw-installed.json")
    # A missing manifest read as "plugin mode, or never installed" and said
    # nothing. But those two cases have no `.ddw/` in the repository, and a
    # drop-in install does — so the one state this could not be is the one it was
    # treated as. Deleting the manifest therefore turned drift detection off
    # permanently and left a tampered repository indistinguishable from a clean
    # one, which is worse than the write it also unsealed: that write leaves
    # evidence, and this removes the thing that would have reported it.
    installed_here = os.path.isdir(os.path.join(repo, ".ddw"))
    try:
        with open(manifest, encoding="utf-8") as fh:
            recorded = json.load(fh)
    except (OSError, ValueError) as exc:
        if not installed_here:
            return []                  # plugin mode, or never installed
        return _no_manifest(type(exc).__name__)
    if not isinstance(recorded, dict) or not recorded:
        return _no_manifest("it is empty or not an object") if installed_here else []
    import hashlib

    def fingerprint(path):
        """The installer's own hash, for files and for whole directories — a
        skill is a directory, and hashing it as a file reported every correct
        install as missing. One definition, two readers: scripts/install_target.py
        `_fingerprint`."""
        h = hashlib.sha256()
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                h.update(fh.read())
            return h.hexdigest()
        if not os.path.isdir(path):
            return None
        for base, dirs, files in os.walk(path):
            dirs.sort()
            for f in sorted(files):
                p = os.path.join(base, f)
                h.update(os.path.relpath(p, path).encode())
                with open(p, "rb") as fh:
                    h.update(fh.read())
        return h.hexdigest()

    changed, gone = [], []
    for key, digest in recorded.items():
        if not isinstance(key, str) or not isinstance(digest, str):
            continue
        rel = key.split(":", 1)[1] if ":" in key else key
        try:
            actual = fingerprint(os.path.join(repo, rel))
        except OSError:
            actual = None
        if actual is None:
            gone.append(rel)
        elif actual != digest:
            changed.append(rel)
    if not changed and not gone:
        return []
    lines = ["⚠️ DDW: what enforces the pipeline is not what was installed."]
    for rel in sorted(gone)[:6]:
        lines.append(f"   MISSING  {rel}")
    for rel in sorted(changed)[:6]:
        lines.append(f"   CHANGED  {rel}")
    extra = len(gone) + len(changed) - min(len(gone), 6) - min(len(changed), 6)
    if extra > 0:
        lines.append(f"   … and {extra} more.")
    lines.append("   The hooks refuse to write these, so a change here came from a shell or from "
                 "outside the session. Say so to the user before doing anything else; re-running "
                 "`install.sh` restores them.")
    return lines


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
    CANNOT = "🔕 DDW: could not check your open pull requests — "
    SHOWN = 8
    try:
        remote = subprocess.run(["git", "-C", repo, "remote"], capture_output=True,
                                text=True, timeout=timeout)
    except Exception:
        remote = None
    if remote is None or remote.returncode != 0:
        # "git failed" and "there is no remote" are different answers, and only
        # one of them is silence. A directory that is not a repository at all is
        # not a failure worth a line — DDW is simply not the thing to say it.
        # `exists`, not `isdir`: in a worktree `.git` is a file, and a worktree
        # is a repository whose git failures are worth the same line.
        if os.path.exists(os.path.join(repo, ".git")):
            return [CANNOT + "git could not read this repo's remotes."]
        return []
    if not remote.stdout.strip():
        return []                      # no remote: no pull requests to have, and no noise
    try:
        out = subprocess.run(["gh", "pr", "list", "--author", "@me", "--state", "open",
                              # Explicit, because gh's default page size is its
                              # business and not ours. The count below is what
                              # the user acts on, so it has to be a count of the
                              # same thing every time.
                              "--limit", "30",
                              "--json", "number,title,headRefName,reviewDecision,updatedAt"],
                             cwd=repo, capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return [CANNOT + "`gh` is not installed."]
    except subprocess.TimeoutExpired:
        return [CANNOT + f"the forge did not answer in {timeout}s."]
    except Exception as exc:
        # Anything else — a locale that cannot decode gh's output, a permission
        # error on the executable — used to be reported as a timeout, which is a
        # statement about the network that nobody established.
        return [CANNOT + f"{type(exc).__name__} while running gh."]
    if out.returncode != 0:
        why = (out.stderr or "").strip().splitlines()
        detail = why[0][:120] if why else f"gh exited {out.returncode}"
        return [CANNOT + detail]
    try:
        prs = json.loads(out.stdout or "[]")
    except ValueError:
        return [CANNOT + "gh returned something unparseable."]
    # Shape-checked, not trusted. `gh` returning an object, or a list of strings,
    # crashed the boot on `pr.get` — and a session boot that raises takes the
    # phase announcement down with it, which is the one line that must survive.
    if not isinstance(prs, list):
        return [CANNOT + "gh returned something that is not a list of pull requests."]
    prs = [p for p in prs if isinstance(p, dict)]
    if not prs:
        return []
    lines = [f"🔎 DDW: {len(prs)} open pull request(s) of yours in this repo:"]
    for pr in prs[:SHOWN]:
        decision = str(pr.get("reviewDecision") or "").upper()
        note = {"CHANGES_REQUESTED": "  ← changes requested",
                "APPROVED": "  ← approved, ready to merge"}.get(decision, "")
        lines.append(f"   #{pr.get('number')} {str(pr.get('headRefName'))[:44]}{note}")
    if len(prs) > SHOWN:
        # Never a silent truncation: a list that stops without saying so reads as
        # the whole list, and the ones it dropped are the oldest — the ones most
        # likely to be the forgotten review this exists to surface.
        lines.append(f"   … and {len(prs) - SHOWN} more (showing the first {SHOWN}).")
    lines.append("   A ticket paused at CLOSEOUT resumes there; what a reviewer asks for is a step "
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

    # No id, no marker. A pid is not a session: the pre-write hook runs on EVERY
    # edit, and each run had a pid of its own, so a repo with one person working
    # in it grew one "live session" per write and then warned about twelve of
    # them. An identity nobody supplied is better left unclaimed than invented —
    # the count stays right, and the caller that has a real session id (every
    # session-start hook does) still refreshes the one marker that means it.
    session_id = safe_id(args.session_id) if args.session_id else ""
    others, announced = other_live_sessions(repo, session_id) if started else (0, True)

    lines = []
    # First, above everything: if the enforcement itself was changed, nothing
    # below it means what it says.
    lines += enforcement_drift(repo)
    if others:
        lines += [
            f"⚠️ DDW: {others} other session(s) are working in THIS SAME directory.",
            "   They share one .ddw-state.json and will clobber each other — one changes phase and",
            "   the other finds out when a hook stops it. To work in parallel, give each one its own",
            "   worktree: git worktree add ../<repo>-<TICKET> -b feat/<TICKET>",
        ]
    if not announced:
        # Half a guard, named as half a guard. This session can see the others;
        # the others cannot see this one, and a warning nobody receives reads
        # exactly like a directory nobody else is working in.
        lines += [
            "⚠️ DDW: this session could not write its marker under .ddw-sessions/live, so the",
            "   next session opened on this directory will NOT be warned about this one. The",
            "   count above is one-sided rather than wrong.",
        ]
    if phase == "IDLE":
        # `started` and `--quiet` both gate the network call, not just its
        # output. Without them the boot reached out to the forge in a repo that
        # has never run DDW, and again on a quiet run whose whole point is to
        # print nothing — paying a round trip on every session start for a line
        # that was going to be discarded.
        if started and not args.quiet:
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
    # Fail SOFT and always say something. This is the session's first line, and a
    # traceback here means the model starts with no idea what phase it is in —
    # which is worse than any message this could have printed. A state so deeply
    # nested that json raises RecursionError is not a state; it is the case the
    # UNREADABLE line was written for, and it was reaching the user as exit 1.
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:                  # noqa: BLE001 — breadth is the point
        print("⚠️ DDW: the session boot could not run (%s: %s). This is NOT an idle "
              "pipeline — a ticket may be mid-flight. Read .ddw-state.json yourself before "
              "starting anything, and tell the user." % (type(exc).__name__, exc))
        sys.exit(0)
