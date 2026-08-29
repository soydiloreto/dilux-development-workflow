#!/usr/bin/env python3
"""Break DDW on purpose, one fault at a time, and see whether the suite notices.

A test suite that always passes and a test suite that cannot fail look exactly
alike from the outside. The only way to tell them apart is to introduce a defect
you know is real and check that something goes red. That is all this is.

Each mutation below describes a defect class this design is built to prevent —
not a hypothetical, but a way these guards are known to fail. If a mutation survives, the suite has a blind spot at
exactly that spot — and the fix is a new check, not a smaller mutation list.

    python3 scripts/mutate.py            # run them all, print the kill rate
    python3 scripts/mutate.py --list     # just show what would run
    python3 scripts/mutate.py --only 3 7 # run a subset while iterating

Exit 0 when every mutation is killed. Exit 1 when any survives: a surviving
mutation is a hole, and the number is the project's real coverage figure.

Running the whole suite once per fault takes hours in one process, and a CI job
that cannot finish inside its timeout is a measurement nobody ever reads. So the
run splits:

    python3 scripts/mutate.py --shard 3/10           # one slice, in its own job
    python3 scripts/mutate.py --cover <workflow.yml> # do the slices cover it all?
    python3 scripts/mutate.py --check-anchors        # do they all still apply?

Splitting a measurement is how a measurement goes quietly missing — a matrix
that loses an entry leaves faults nobody injects, and every job that did run is
still green. `--cover` reads the workflow and adds the slices back up, so the
workflow has to prove it ran the whole list rather than assert it.
"""
import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SELF = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SELF)


def edit(rel, old, new, last=False, may_not_parse=False):
    """A mutation that swaps one exact string in one file.

    `last=True` swaps the LAST occurrence instead of the first, and it exists for
    one case: a mutation that targets THIS file. The anchor is a literal in the
    list above, so it appears before the code it names — `replace(..., 1)` edited
    the mutation's own entry, the product went unchanged, and the fault was
    reported as surviving (or, worse, as killed, when editing the list broke this
    file's syntax and the suite went red for that instead). Every function this
    file mutates in itself lives below the list, so the last occurrence is the
    real one.
    """
    def apply(repo):
        p = os.path.join(repo, rel)
        s = open(p, encoding="utf-8").read()
        if old not in s:
            return f"the anchor is gone from {rel} — update this mutation"
        if last:
            head, _, tail = s.rpartition(old)
            s = head + new + tail
        else:
            s = s.replace(old, new, 1)
        open(p, "w", encoding="utf-8").write(s)
        return None
    # What this mutation needs to still be true of the tree, cheap enough to ask
    # about without running anything. See `--check-anchors`.
    apply.probe = ("text", rel, old, new, last, may_not_parse)
    return apply


def edit_re(rel, pattern, repl, what):
    """Like `edit`, but the anchor is an EXPRESSION, not a literal.

    It exists for a single class of fault: the ones that have to touch a line
    carrying a number that changes on its own. `EXPECT_CHECKS=553` as a literal
    anchor means that adding a check breaks the fault that verifies the total
    is pinned — and what breaks is precisely the verification that nobody
    deleted checks. It happened three times in one night, with
    `EXPECT_MUTATIONS` and with `EXPECT_CHECKS` twice.

    `what` describes what is expected to be found, so that `--check-anchors`
    says something actionable when it is gone.
    """
    rx = re.compile(pattern, re.M)

    def apply(repo):
        path = os.path.join(repo, rel)
        text = open(path, encoding="utf-8").read()
        out, n = rx.subn(repl, text, count=1)
        if not n:
            return f"{what} is gone from {rel} — update this mutation"
        if out == text:
            return f"{what} in {rel}: the substitution changed nothing"
        open(path, "w", encoding="utf-8").write(out)
        return None

    apply.probe = ("regex", rel, pattern, repl, what)
    return apply


def multi(*parts):
    """Several edits as ONE fault.

    It exists because some defects do not live on one line. The corrective loop
    returns gates in two places — the state on disk and the list of edges that
    return them — and breaking just one is covered by the other: the fault
    survives and the check looks like it cannot fail, when what cannot fail is
    a single edit. The kill map asked for this, which is where it was seen.

    The probe is the FIRST piece's: `--check-anchors` asks whether the fault
    still finds something to break, and if the first piece moved the rest do
    not matter. The others still report their own problem when injected.
    """
    def apply(repo):
        for part in parts:
            problem = part(repo)
            if problem:
                return problem
        return None
    apply.probe = getattr(parts[0], "probe", None)
    return apply


def delete(rel):
    def apply(repo):
        p = os.path.join(repo, rel)
        if not os.path.exists(p):
            return f"{rel} does not exist — update this mutation"
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        return None
    apply.probe = ("exists", rel, None)
    return apply


def json_edit(rel, fn):
    def apply(repo):
        p = os.path.join(repo, rel)
        d = json.load(open(p, encoding="utf-8"))
        fn(d)
        json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
        return None
    apply.probe = ("exists", rel, None)
    return apply


def copy_to(src, dest):
    """A mutation that puts a file back somewhere it must not be.

    Not every regression is an edit. This one is a file reappearing at a path
    another tool scans on sight, which is how a plugin that installs correctly
    comes to report an error on every session.
    """
    def apply(repo):
        s, d = os.path.join(repo, src), os.path.join(repo, dest)
        if not os.path.exists(s):
            return f"{src} does not exist — update this mutation"
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(s, d)
        return None
    apply.probe = ("exists", src, None)
    return apply


def _drop_gate(d):
    d["tiers"]["FEATURE"]["VERIFY->CLOSEOUT"]["gates"] = []


def _drop_quickfix_close(d):
    d["tiers"]["QUICK-FIX"].pop("CODE->CLOSEOUT", None)


def _cursor_open(d):
    d["hooks"]["preToolUse"][0]["failClosed"] = False


MUTATIONS = [
    # ── The defects a real ticket found, one arrow at a time ────────────────
    #
    # Each of these was live, measured on a run, and each reinjection is the
    # only thing standing between the fix and the next refactor.
    ("the helper stops carrying the resumed tier into the header, so the state contradicts its own newest edge",
     edit("ddw/scripts/transition.py",
          '        if to_phase != "IDLE" and new_state.get("tier") is None:\n'
          '            new_state["tier"] = run_tier',
          '        if False:\n'
          '            new_state["tier"] = run_tier')),
    ("the helper goes back to guessing which ticket an edge out of IDLE is about",
     edit("ddw/scripts/transition.py",
          '            and args.ticket is None and _verb not in ("resume", "resumed")):',
          '            and args.ticket is None and _verb in ("never", "happens")):')),
    ("a resume out of IDLE stops restoring the ticket to the header",
     edit("ddw/scripts/transition.py",
          '        if to_phase != "IDLE" and new_state.get("ticket") is None:\n'
          '            new_state["ticket"] = run_ticket',
          '        if False:\n'
          '            new_state["ticket"] = run_ticket')),
    ("a commit no longer has to have been shown to the user",
     edit("ddw/scripts/hook-gate.py",
          "        reason = commit_verdict(args.repo, command)",
          "        reason = None")),
    ("a commit shown once opens every commit after it",
     edit("ddw/scripts/hook-gate.py",
          "    for path in (proposal, seal):    # spent: the next commit is proposed afresh",
          "    for path in ():                 # spent: the next commit is proposed afresh")),
    ("the commit gate stops comparing what was shown with what is being committed",
     edit("ddw/scripts/hook-gate.py",
          "    if require_seal and sealed != digest:",
          "    if False:")),
    ("the spent proposal is consumed on the gate's word again, not the commit's",
     # The measured defect: git fails after the allow and the approval is no
     # longer there. Here the consumption stops checking whether HEAD carries
     # the approved bytes.
     edit("ddw/scripts/hook-gate.py",
          '    if head.returncode != 0:\n'
          '        return\n'
          '    if hashlib.sha256(head.stdout.strip().encode("utf-8")).hexdigest() != digest:\n'
          '        return',
          '    if head.returncode != 0:\n'
          '        return')),
    ("the post hook stops asking whether an approved commit has landed",
     edit("ddw/scripts/hook-gate.py",
          "        consume_spent_proposal(args.repo)",
          "        pass")),
    ("the turn that waits goes back to an arrow in the noise",
     edit("ddw/orchestrator.md",
          "## Your turn",
          "## Ending a phase")),
    ("a gated approval can arrive through the picker no hook can see",
     edit("ddw/orchestrator.md",
          "**The approvals the hooks measure are answered with a message, never with the picker.**",
          "**Any approval may be taken from the picker like any other answer.**")),
    ("classification happens in IDLE again, and the ok goes back to owing two arrows",
     edit("ddw/rules/classify.instructions.md",
          "## Step 0: Enter the phase first",
          "## Step 0: Classify, then enter the phase")),
    ("the orchestrator stops saying when the arrow into CLASSIFY is written",
     edit("ddw/orchestrator.md",
          "write `IDLE→CLASSIFY` **in this same response, before the\n    classification work**",
          "transition to `CLASSIFY` once the user has confirmed the classification")),
    ("any pause of the parent authorizes opening a split child",
     edit("ddw/scripts/validate-transition.py",
          '        if (entry.get("to") == IDLE and _is_pause(entry)\n'
          '                and "split" in (entry.get("action") or "").lower()):\n'
          '            return entry',
          '        if entry.get("to") == IDLE and _is_pause(entry):\n'
          '            return entry')),
    ("a split child opening stops asking the journal whether the split landed",
     edit("ddw/scripts/validate-transition.py",
          "            _split_open_allowed(entry, old_h + appended, len(old_h) + idx)\n"
          "            if state_path:\n"
          "                _split_needs_a_recorded_pause(state_path, entry, dst)",
          "            _split_open_allowed(entry, old_h + appended, len(old_h) + idx)\n"
          "            if False:\n"
          "                _split_needs_a_recorded_pause(state_path, entry, dst)")),
    ("a split child opens in whatever phase the write cares to name",
     edit("ddw/scripts/validate-transition.py",
          '    if pause.get("from") != dst:',
          "    if False:")),
    ("a split reclassifies the work on the way into the child",
     edit("ddw/scripts/validate-transition.py",
          '    if pause.get("tier") and entry.get("tier") != pause.get("tier"):',
          "    if False:")),
    ("the banner goes back to promising the chain the hook will refuse",
     edit("ddw/orchestrator.md",
          "**And under `assisted` it promises at most ONE arrow.**",
          "**And under `assisted` it may promise the whole of what follows.**")),
    ("the split child is sent back through the CLASSIFY that decides nothing",
     edit("ddw/rules/define.instructions.md",
          "2. **Open the sub-ticket, directly in the phase the split paused from.**",
          "2. **Open the sub-ticket through CLASSIFY, like every ticket.**")),
    # The round-4 family: rules that measured zero and vouched anyway.
    ("the backticked test names go back to being invisible to F-VER-06",
     edit("ddw/scripts/validate_verify.py",
          '            name = raw.strip("`").rsplit("::", 1)[-1].strip("`")',
          '            name = raw.rsplit("::", 1)[-1]')),
    ("a spec whose promised tests cannot be read goes back to vouching anyway",
     edit("ddw/scripts/validate_verify.py",
          "        promised = _promised_tests(spec_text)\n        if not promised:",
          "        promised = _promised_tests(spec_text)\n        if False:")),
    ("a PRD parsing to zero IDs clears the whole battery again",
     edit("ddw/scripts/validate_prd.py",
          '        empty = [p for p, items in (("FR", frs), ("NFR", nfrs), ("AC", acs)) if not items]',
          "        empty = []")),
    ("spec coverage is declared against a PRD that parsed to nothing again",
     edit("ddw/scripts/validate_spec.py",
          "        if not frs or not acs:",
          "        if False:")),
    # The pr gate and its receipt (round 4: the merge deletes the branch and the check went blind).
    ("the pr gate goes back to resolving through whatever branch the repo is on",
     edit("ddw/scripts/validate-transition.py",
          "        if isinstance(rec, dict) and rec.get(\"number\"):",
          "        if False:")),
    ("the pr receipt is never written when the gate is earned",
     edit("ddw/scripts/validate-transition.py",
          "        if ticket:\n            try:\n                path = _pr_receipt_path(root, ticket)",
          "        if False:\n            try:\n                path = _pr_receipt_path(root, ticket)")),
    ("a receipt naming another ticket's pull request passes as evidence",
     edit("ddw/scripts/validate-transition.py",
          "    if ticket.lower() not in head.lower():",
          "    if False:")),
    ("a pull request closed without merging satisfies the receipt check",
     edit("ddw/scripts/validate-transition.py",
          '    if str(pr.get("state", "")).upper() in ("OPEN", "MERGED"):',
          '    if str(pr.get("state", "")).upper() in ("OPEN", "MERGED", "CLOSED"):')),
    # The merge gate (round 4: the irreversible act ran with no hook watching it).
    ("gh pr merge goes back to running with no hook watching",
     edit("ddw/scripts/hook-gate.py",
          "        if _IS_PR_MERGE.search(command):",
          "        if False:")),
    ("a merge proposal written in the same turn passes as seen",
     edit("ddw/scripts/hook-gate.py",
          '    if require_seal and sealed != digest:\n'
          '        return (\n'
          '            "DDW: this merge proposal has not been in front of the user yet — it was written "',
          '    if False:\n'
          '        return (\n'
          '            "DDW: this merge proposal has not been in front of the user yet — it was written "')),
    ("the merge approval is consumed whether or not the forge says MERGED",
     edit("ddw/scripts/hook-gate.py",
          '    if str(state).upper() != "MERGED":\n        return',
          '    if False:\n        return')),
    ("the post hook stops asking whether an approved merge has landed",
     edit("ddw/scripts/hook-gate.py",
          "        consume_spent_merge(args.repo)",
          "        pass")),
    ("the closeout lets a picker answer execute the merge again",
     edit("ddw/rules/closeout.instructions.md",
          "merge only after the user confirms **with a message**, and never force",
          "merge as soon as the user picks it, and never force")),
    ("the installer dies silently on a target that is not a git repository",
     edit("install.sh",
          "2>/dev/null | awk '{print $2}' || true)\"",
          "2>/dev/null | awk '{print $2}')\"")),
    ("a directory with no git gets DDW installed and not one word about it",
     edit("install.sh",
          '  echo "  ⚠ This directory is not a git repository. DDW\'s pipeline branches, commits"',
          '  :')),
    ("the installer leaves the installation uncommitted in silence again",
     multi(
         edit("install.sh",
              '      printf "  Commit the installation now? [Y/n] "',
              '      printf "  Files written. [enter] "'),
         edit("install.sh",
              '  echo "  Note: this repo is git-tracked and the installation is not committed."',
              '  echo "  Done."'))),
    ("the installer stops asking where the installation lands",
     edit("install.sh",
          '        echo "  Where should the $DDW_LANDS land?"',
          '        :')),
    ("choosing the setup branch lands the installation on the current branch anyway",
     edit("install.sh",
          '         if git -C "$TARGET" checkout -q -b "$DDW_SETUP_BRANCH" 2>/dev/null; then',
          '         if false; then')),
    # Round 5: the committed installation never reached the remote, the ticket
    # branched off the local base, and the PR showed 66 framework files to the
    # feature's reviewer. Four faults guard the road from that commit to a PR
    # a reviewer can actually read.
    ("the installation is committed on the current branch and the remote hears nothing",
     edit("install.sh",
          '  echo "  ⚠ THIS COMMIT IS NOT ON YOUR REMOTE. YOU MUST GET IT ONTO YOUR DEFAULT"',
          '  :')),
    ("the current-branch push offer says yes and pushes nothing",
     edit("install.sh",
          '          if git -C "$TARGET" push -q origin "$DDW_CURB" 2>/dev/null; then',
          '          if false; then')),
    ("the branch gets created from whatever base happens to be checked out, no questions asked",
     edit("ddw/rules/branches.instructions.md",
          "Two questions come BEFORE the branch exists, both out loud:",
          "Create the branch:")),
    ("the closeout's own index commit strands on the machine again",
     edit("ddw/rules/closeout.instructions.md",
          "**Then push the branch.**",
          "**Then rest.**")),
    # The same round watched a spec swap "rechazado" for "error" to please a
    # stem the regex could never match, a wrapped bullet hide its sad-path word
    # on line two, a PR born a draft nobody could approve, and a split proposed
    # as 11/6/2 with the big part still over the ceiling that caused it.
    ("the sad-path vocabulary goes back to stems no written word can match",
     edit("ddw/scripts/validate_spec.py",
          r"reject\w*|rechaz\w*|",
          "reject|rechaz|")),
    ("a wrapped bullet loses its second line again",
     edit("ddw/scripts/validate_spec.py",
          "            if cont and out:",
          "            if cont and False:")),
    ("the pull request is born a draft nobody can approve or merge",
     edit("skills/ddw-create-pr/SKILL.md",
          "Create the PR **ready for review — NOT a draft**.",
          "ALWAYS create the PR as a **draft** (`--draft`).")),
    ("the integration box stops asking feedback-or-merge in words",
     edit("ddw/rules/closeout.instructions.md",
          "│  Every gate is green. Are you waiting for feedback on    │",
          "│  Where does this land?                                   │")),
    ("an 11/6/2 cut sails through the scope check again",
     edit("ddw/rules/define.instructions.md",
          "**And aim for balance.**",
          "**And that is enough.**")),
    # Measured on a workflow-only dependency bump: --changed named 3 mutations,
    # and 21 of 24 shards died red for holding none of them — the guard against
    # measuring nothing refused shards whose empty slice WAS the answer.
    ("a shard whose slice holds none of the diff's mutations dies red instead of answering empty",
     edit("scripts/mutate.py",
          "    if not chosen and touched and wanted is not None:",
          "    if False:",
          last=True)),
    ("an ADR can order the implementation around again",
     edit("ddw/scripts/validate_adr.py", "    if offenders:", "    if False:")),
    ("one option is a decision again",
     edit("ddw/scripts/validate_adr.py", "    if len(names) >= 2:", "    if len(names) >= 0:")),
    # The WHOLE block, which is how the repo actually was: `plan.instructions.md`
    # named the skill nowhere in its process. Trimming only the first sentence
    # left the rest of the paragraph naming it, and the control — which asks
    # whether the phase routes to the skill — kept passing over a real defect.
    ("PLAN stops asking what it decided that nobody could reconstruct",
     edit_re("ddw/rules/plan.instructions.md",
             r"(?s)   \*\*Then ask what step 3 decided.*?(?=\n5\. \*\*Impact check)",
             "",
             "the step that orders writing an ADR disappears from PLAN")),
    ("a split can drop an acceptance criterion and nothing counts",
     edit("ddw/scripts/validate_prd.py",
          "            if problems:", "            if False:")),
    ("a split index no longer owes the count of what it replaced",
     edit("ddw/scripts/validate_prd.py",
          "        if not total:", "        if False:")),
    ("a run takes three arrows on one \"go ahead\" again",
     edit("ddw/scripts/validate-transition.py",
          "        if len(_nh) > len(_oh):\n"
          "            reason = second_arrow_in_one_turn(root, old_state, new_state)",
          "        if False:\n"
          "            reason = second_arrow_in_one_turn(root, old_state, new_state)")),
    ("minimal gets caught by the rule it opted out of",
     edit("ddw/scripts/validate-transition.py",
          '    if autonomy == "minimal":\n        return None\n    turn = _turn_now(root)',
          '    if autonomy == "never-happens":\n        return None\n    turn = _turn_now(root)')),
    # Both halves together: without a counter, `_turn_now` returns 0 instead of
    # None and `_record_arrow` writes anyway, so the first arrow leaves a mark
    # and the second is refused — in every tool that does not write turns.
    # Mutating only one of the two changes nothing, and a mutation that cannot
    # fail is not evidence of anything.
    ("a missing turn counter refuses every write instead of staying quiet",
     multi(edit("ddw/scripts/validate-transition.py",
                "    except (OSError, ValueError):\n        return None\n\n\ndef _record_arrow(root):",
                "    except (OSError, ValueError):\n        return 0\n\n\ndef _record_arrow(root):"),
           edit("ddw/scripts/validate-transition.py",
                "    turn = _turn_now(root)\n    if turn is None:\n        return\n    try:\n"
                "        path = os.path.join(root, \".ddw-sessions\", \"last-arrow\")",
                "    turn = _turn_now(root)\n    if turn is None:\n        turn = 0\n    try:\n"
                "        path = os.path.join(root, \".ddw-sessions\", \"last-arrow\")"))),
    ("a tool stops declaring how it asks, so the question comes out as prose",
     json_edit("adapters/opencode/adapter.json", lambda d: d.pop("choice_prompt", None))),
    ("the orchestrator stops sending anyone to the adapter for its picker",
     edit("ddw/orchestrator.md",
          "its name is in that tool's `adapter.json` under `choice_prompt`",
          "ask however you like")),
    ("a sub-ticket bigger than the whole stops being reported",
     edit("ddw/scripts/validate_prd.py",
          '        if args.tier == "FEATURE" and len(acs) > 7:',
          '        if args.tier == "FEATURE" and len(acs) > 99999:')),
    # ── The gate the six tools run ───────────────────────────────────────────
    ("the shared gate stops capping transitions per write",
     edit("ddw/scripts/hook-gate.py", "vt.decide_pre(", "vt.decide_pre_UNCAPPED(")),
    # Targets the CALL, not the default. The default is unreachable — both
    # callers pass the value explicitly — so mutating it cannot change
    # behaviour, and a mutation that cannot fail is not evidence of anything.
    ("the pre path stops capping transitions per write",
     edit("ddw/scripts/validate-transition.py",
          "        validate(old_state, new_state, graph, tool_name=tool_name, max_appended=1,",
          "        validate(old_state, new_state, graph, tool_name=tool_name, max_appended=None,")),
    ("the gate's fail-closed wrapper becomes fail-open",
     edit("ddw/scripts/hook-gate.py",
          'deny(_d, f"DDW could not reach a verdict', 'allow(_d) or deny(_d, f"DDW could not reach a verdict')),
    ("paths are resolved lexically again (symlinks bypass both guards)",
     edit("ddw/scripts/validate-transition.py",
          "    return os.path.realpath(path)", "    return os.path.abspath(path)")),
    ("the source guard forgets every phase but PLAN",
     edit("ddw/scripts/validate-transition.py",
          'NO_SOURCE_PHASES = frozenset({"IDLE", "CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY"})',
          'NO_SOURCE_PHASES = frozenset({"PLAN"})')),
    ("IDLE goes back to writing product source with no ticket and no record",
     edit("ddw/scripts/validate-transition.py",
          'NO_SOURCE_PHASES = frozenset({"IDLE", "CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY"})',
          'NO_SOURCE_PHASES = frozenset({"CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY"})')),
    ("FREE stops being a phase where code can be written, so the escape hatch is a wall",
     edit("ddw/scripts/validate-transition.py",
          'NO_SOURCE_PHASES = frozenset({"IDLE", "CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY"})',
          'NO_SOURCE_PHASES = frozenset({"IDLE", "CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY", "FREE"})')),
    ("the session stops saying that this repo is running without a workflow",
     edit("ddw/scripts/session-boot.py",
          '    if phase == "FREE":\n        lines += [\n'
          '            "⚠️ ESTÁS TRABAJANDO SIN WORKFLOW (tier FREE): no gates, no artifacts, nothing is",',
          '    if False:\n        lines += [\n'
          '            "⚠️ ESTÁS TRABAJANDO SIN WORKFLOW (tier FREE): no gates, no artifacts, nothing is",')),
    ("the tiers go back to being typed in the helper instead of read from the graph",
     edit("ddw/scripts/transition.py",
          '    return tuple(sorted(graph.get("tiers", {})))',
          '    return ("QUICK-FIX", "FIX", "FEATURE", "DISCOVERY")')),
    ("the source guard allows anything again",
     edit("ddw/scripts/validate-transition.py",
          "    if phase not in NO_SOURCE_PHASES:\n        return None",
          "    if True:\n        return None")),
    ("an unreadable state reads as a fresh IDLE",
     edit("ddw/scripts/validate-transition.py",
          '        raise Block(\n            f".ddw-state.json exists but cannot be read',
          '        return "", _idle_template()  # noqa\n        raise Block(\n            f".ddw-state.json exists but cannot be read')),
    ("only the first path in an event is judged",
     edit("ddw/scripts/validate-transition.py",
          "    named = [pth for pth in paths if isinstance(pth, str) and pth]",
          "    named = [pth for pth in paths[:1] if isinstance(pth, str) and pth]")),

    ("the replay judges stamped entries against the empty set again (M1 false positive)",
     edit("ddw/scripts/validate-transition.py",
          "        if allowed and stamped not in allowed:",
          "        if stamped not in allowed:")),
    ("a replayed run may mix tickets freely",
     edit("ddw/scripts/validate-transition.py",
          "    if not allowed and len(stamped_run) > 1:",
          "    if False:")),
    ("Copilot's user-level hook goes back to drop-in-only resolution",
     edit("adapters/copilot/scripts/pre-tool-use.sh",
          '  if [ -n "${DDW_PLUGIN_ROOT:-}" ] && [ -f "$DDW_PLUGIN_ROOT/ddw/scripts/hook-gate.py" ]; then\n'
          '    DDW="$DDW_PLUGIN_ROOT/ddw"\n'
          '  else                      # DDW is not reachable from here\n',
          '  if false; then\n'
          '    DDW="$DDW_PLUGIN_ROOT/ddw"\n'
          '  else                      # DDW is not reachable from here\n')),
    ("the DEFINE rules go back to 'create-prd automatically validates'",
     edit("ddw/rules/define.instructions.md",
          "   never in parallel with `ddw-create-prd` — invoke `ddw-validate-prd`, which\n",
          "   automatically at the end of `ddw-create-prd` via `ddw-validate-prd`, which\n")),
    ("a PASSED validation stops leaving its receipt",
     edit("ddw/scripts/validate_prd.py",
          '        print("Receipt: .ddw-sessions/" + ddw_receipt.write(args.prd, "prd", text, args.tier))',
          "        pass")),
    ("the helper stops asking for the evidence the hook asks for",
     edit("ddw/scripts/transition.py",
          "    reason = vt.gate_evidence_missing(\n",
          "    reason = None or (lambda *a: None)(\n")),
    ("the spec, threat and verify gates go back to trusting the boolean",
     edit("ddw/scripts/validate-transition.py",
          # Anchored on the first line of the table only: the table grows every
          # time a gate earns a receipt, and pinning all of it meant raising a
          # gate broke the mutation that guards the others.
          '''GATE_EVIDENCE = {"define": _prd_receipt_missing, "spec": _spec_receipt_missing,''',
          '''GATE_EVIDENCE = {"define": _prd_receipt_missing, "_spec": _spec_receipt_missing,''')),
    ("the spec validator stops counting a block's errors against its tests",
     edit("ddw/scripts/validate_spec.py",
          "        if errors and len(sad) < len(errors):\n",
          "        if False:\n")),
    ("a component analysed against five STRIDE categories passes as six",
     edit("ddw/scripts/validate_threat.py",
          "                if entry is None:\n                    missing.append(cat)\n",
          "                if False:\n                    missing.append(cat)\n")),
    ("the verify validator stops holding coverage to the floor",
     edit("ddw/scripts/validate_verify.py",
          "        below = [f\"{k} {v:.0f}%\" for k, v in cov.items() if v < minimum]\n",
          "        below = []\n")),
    ("an Add File patch loses its content again and legal state writes bounce to the shell",
     edit("ddw/scripts/hook-gate.py",
          "    if patch_add_content is not None and not isinstance(out.get(\"content\"), str):\n"
          "        out[\"content\"] = patch_add_content\n",
          "")),
    ("--write stops writing and the redirect footgun is the only path",
     edit("ddw/scripts/transition.py",
          "        os.replace(tmp, args.state)",
          "        pass")),
    ("FREE stops needing the user's words and the model can hand it to itself",
     edit("ddw/scripts/validate-transition.py",
          "    _check_free_is_the_users_word(old_state, new_state, appended, replaying=_replaying)\n",
          "")),
    ("the arrow into FREE accepts any wording, so a paraphrase of the user counts as the user asking",
     edit("ddw/scripts/validate-transition.py",
          '_FREE_ACTION = re.compile(r"""free\\s*:\\s*.*["“\'«][^"”\'»]{4,}["”\'»]""", re.IGNORECASE | re.DOTALL)',
          '_FREE_ACTION = re.compile(r"""free""", re.IGNORECASE | re.DOTALL)')),
    ("the FREE declaration may hide anywhere inside the action instead of opening it",
     edit("ddw/scripts/validate-transition.py",
          "    if not any(_FREE_ACTION.match(a.strip()) for a in actions):",
          "    if not any(_FREE_ACTION.search(a) for a in actions):")),
    ("a ticket leaves CLASSIFY with no name, and every line the user reads afterwards is a reconstruction",
     edit("ddw/scripts/validate-transition.py",
          "    _check_the_ticket_has_a_name(new_state, appended, replaying=_replaying)\n",
          "")),
    ("the ticket's name may be blank as long as the field exists, which is the same nothing with a type",
     edit("ddw/scripts/validate-transition.py",
          "    if not (isinstance(title, str) and title.strip()):",
          "    if title is None:")),
    ("the name requirement reaches backwards through post mode's replay, and every ticket already "
     "open is refused on every tool call",
     edit("ddw/scripts/validate-transition.py",
          "    _check_the_ticket_has_a_name(new_state, appended, replaying=_replaying)",
          "    _check_the_ticket_has_a_name(new_state, appended)")),
    ("FREE's quote requirement reaches backwards through the replay, stranding a run that entered "
     "FREE before the rule existed",
     edit("ddw/scripts/validate-transition.py",
          "    _check_free_is_the_users_word(old_state, new_state, appended, replaying=_replaying)",
          "    _check_free_is_the_users_word(old_state, new_state, appended)")),
    ("the commit gate stops reading the trailers, and DDW signs its own commits the way its method forbids",
     edit("ddw/scripts/hook-gate.py",
          '    bad = [m.group(0) for m in re.finditer(\n'
          '        r"^[ \\t]*(Co-Authored-By|Signed-off-by-AI|🤖 Generated with[^\\n]*)\\s*:?[^\\n]*$",\n'
          '        body, re.IGNORECASE | re.MULTILINE)]',
          '    bad = []')),
    ("the trailer check goes case-sensitive, and `Co-authored-by` — the spelling the tool actually writes — sails through",
     edit("ddw/scripts/hook-gate.py",
          '        body, re.IGNORECASE | re.MULTILINE)]',
          '        body, re.MULTILINE)]')),
    ("ripgrep is a write again: `rg` over the method comes back refused",
     edit("ddw/scripts/validate-transition.py",
          'READ_TOOLS = ("rg",)',
          'READ_TOOLS = ()')),
    ("the method guard judges reads again and the agent cannot load the orchestrator",
     edit("ddw/scripts/validate-transition.py",
          "    if writing:\n"
          "        for target in targets:\n"
          "            denied = _method_write_denied(target, method, repo)\n"
          "            if denied:\n"
          "                return denied\n",
          "    for target in targets:\n"
          "        denied = _method_write_denied(target, method, repo)\n"
          "        if denied:\n"
          "            return denied\n")),
    ("the helper goes back to printing a state that looks like it landed",
     edit("ddw/scripts/transition.py",
          "    if not args.write:",
          "    if False:")),
    ("Copilot's raw-text apply_patch is unjudged again (the M4 hole)",
     edit("ddw/scripts/hook-gate.py",
          '    if not paths and raw_args and "*** Begin Patch" in raw_args:',
          '    if False and not paths and raw_args and "*** Begin Patch" in raw_args:')),
    ("the post net stops closing the gitignore window a plugin-born state opens",
     edit("ddw/scripts/validate-transition.py",
          "    _ensure_runtime_ignored(state_path)\n",
          "")),
    ("the Copilot installer stops saying that repository hooks need a trusted folder, "
     "and the next person wires the gates where an untrusted clone never runs them",
     edit(".github/INSTALL.md",
          "**Repository hooks load only in a folder the",
          "**Repository hooks load in any folder the")),
    ("the plugin boot stops saying classify-first (the M4 omission)",
     edit("ddw/scripts/session-boot.py",
          '            "Work that changes this repo starts by CLASSIFYING it into a ticket and walking the "\n'
          '            "phases — NEVER by writing code first. IDLE does not mean free to code; it means no "\n'
          '            "ticket has been started yet. A hand-written state file that skips the transitions is "\n'
          '            "not a started ticket."\n',
          '            ""\n')),
    ("the plugin boot forgets both prohibitions",
     edit("ddw/scripts/session-boot.py",
          "    if not dropped_in:",
          "    if False:")),
    ("the plugin stops registering its skills with OpenCode's discovery",
     edit("adapters/opencode/plugin/ddw.js",
          "      if (!config.skills.paths.includes(skills)) config.skills.paths.push(skills)\n",
          "")),
    ("the bootstrap stops forbidding the self-install that broke the plugin promise",
     edit("adapters/opencode/plugin/ddw.js",
          '      "The method STAYS with the plugin: do NOT install DDW into this repo — no install.sh, no copying .ddw/ or .opencode/. " +\n'
          '      "Where the method\'s documents say `.ddw/...`, resolve them under the path above. " +\n'
          '      "Only .ddw-state.json, the context file and the phase artifacts (docs/) belong in the repo.",\n',
          '')),
    ("the bootstrap lets DDW content leak into the project's context file",
     edit("adapters/opencode/plugin/ddw.js",
          '      "The context file (AGENTS.md) is the PROJECT\'s, not DDW\'s: if it is missing, gather the stack and conventions " +\n'
          '      "from the user and write it as a plain project file. Never put DDW content in it — no DDW blocks, no DDW " +\n'
          '      "template boilerplate, no references to DDW or its phases. A reader without the plugin must see an ordinary repo.",\n',
          '')),
    ("the bootstrap never reaches the first user message",
     edit("adapters/opencode/plugin/ddw.js",
          "      firstUser.parts.unshift({ ...ref, type: \"text\", text })",
          "      return")),
    ("the plugin forgets the global method and only ever looks in the repo",
     edit("adapters/opencode/plugin/ddw.js",
          '    join(here, "..", "ddw"),            // global install: ~/.config/opencode/plugins/ → ~/.config/opencode/ddw\n',
          '')),
    ("the recovery advice points at git for a file git never had",
     edit("ddw/scripts/hook-gate.py",
          "The user's recovery is restoring their own backup",
          "The user's recovery is `git checkout -- .ddw-state.json`, or restoring their own backup")),

    # ── Dialects ─────────────────────────────────────────────────────────────
    # Reaching the generic envelope spec because nothing matched looks exactly
    # like reaching it on purpose, and the flag is the other way in.
    ("a dialect two hooks pass stops being declared at all",
     edit("ddw/scripts/hook-gate.py", '    "cursor": {"name": "tool_name", "args": "tool_input"},\n', "")),
    ("the gate takes any dialect string again, generic envelope and all",
     edit("ddw/scripts/hook-gate.py",
          'ap.add_argument("--dialect", choices=tuple(DIALECTS), default="standard")',
          'ap.add_argument("--dialect", default="standard")')),
    ("Copilot stops parsing its double-encoded toolArgs",
     edit("ddw/scripts/hook-gate.py",
          '    if spec.get("args_is_json_string") and isinstance(args, str):',
          '    if False and isinstance(args, str):')),
    ("Codex stops reading paths out of apply_patch",
     edit("ddw/scripts/hook-gate.py",
          '    if spec.get("apply_patch") and not paths:',
          '    if False and not paths:')),
    ("Copilot's refusal goes back to the wrong keys",
     edit("ddw/scripts/hook-gate.py",
          '        print(json.dumps({"permissionDecision": "deny",',
          '        print(json.dumps({"decision": "block",')),
    ("OpenCode registers its boot under a key that is never called",
     edit("adapters/opencode/plugin/ddw.js", "    event: async ({ event }) => {",
          '    "session.created": async ({ event }) => {')),
    ("OpenCode stops gating apply_patch",
     edit("adapters/opencode/plugin/ddw.js",
          'const WRITE_TOOLS = new Set(["write", "edit", "apply_patch"])',
          'const WRITE_TOOLS = new Set(["write", "edit"])')),
    ("Cursor's post net moves back to an event that cannot block",
     json_edit("adapters/cursor/hooks.json",
               lambda d: d["hooks"].update({"afterFileEdit": d["hooks"].pop("postToolUse")}))),
    ("Cursor stops failing closed",
     json_edit("adapters/cursor/hooks.json", _cursor_open)),
    ("Cursor's sessionStart is unwired again",
     json_edit("adapters/cursor/hooks.json", lambda d: d["hooks"].pop("sessionStart"))),
    ("the session nudge is emitted in one shape for every tool",
     edit("ddw/scripts/session-boot.py", '    if fmt == "cursor":',
          '    if False:')),

    # ── The state machine ────────────────────────────────────────────────────
    ("the tier lock runs after the early return again",
     edit("ddw/scripts/validate-transition.py",
          "    _check_tier(old_state, new_state, appended)", "    pass")),
    ("the idle invariant is checked only on the edge that lands there",
     edit("ddw/scripts/validate-transition.py",
          "    _check_idle_invariant(new_state)", "    pass")),
    ("the tier type check accepts falsy poison values",
     edit("ddw/scripts/validate-transition.py",
          "    if raw_new is not None and not (isinstance(raw_new, str) and raw_new):",
          "    if False:")),
    ("history stops being append-only",
     edit("ddw/scripts/validate-transition.py", "    if new_h[: len(old_h)] != old_h:",
          "    if False:")),
    ("timestamps stop being validated",
     edit("ddw/scripts/validate-transition.py",
          "    if not isinstance(ts, str) or not _ISO8601.match(ts):", "    if False:")),
    ("a closed ticket is no longer replayed",
     edit("ddw/scripts/validate-transition.py",
          "    if resets[-1] == len(history) - 1:", "    if False:")),
    ("a gated edge stops requiring its gate",
     json_edit("ddw/rules/transition-graph.json", _drop_gate)),
    ("QUICK-FIX loses the edge that lets it finish",
     json_edit("ddw/rules/transition-graph.json", _drop_quickfix_close)),

    # ── Regressions introduced by the fix for something else ─────────────────
    # Every one of these was created by a change that closed a different hole.
    # That is the failure mode this list exists for now: not the original bug,
    # but the one its repair invents.
    ("`resume` stops requiring that a pause happened",
     edit("ddw/scripts/validate-transition.py",
          "    paused_at = _paused_at(history, upto, entry.get(\"ticket\"))",
          "    paused_at = entry.get('to')  # noqa")),
    ("`resume` stops requiring the phase it was paused at",
     edit("ddw/scripts/validate-transition.py",
          "    if paused_at != dst:", "    if False:")),
    ("post mode's compatibility hatch stops checking the phase",
     edit("ddw/scripts/validate-transition.py",
          '            and disk_state.get("phase", IDLE) == IDLE):', "            ):")),
    # (Removed: putting `.ddw` back in ALLOWED_WIRING_DIRS no longer changes
    # anything — `enforcement_write_denied` refuses the method before that list
    # is consulted, in every phase. A mutation that cannot fail measures nothing,
    # and the list IS the coverage figure. What it used to test is covered by
    # "the method itself stops being sealed" and "the pipeline can edit the rules
    # that stop it again".)
    ("the pause protocol's own directory is no longer writable",
     edit("ddw/scripts/validate-transition.py",
          '    ".ddw-paused", ".ddw-sessions", ".ddw-work",',
          '    ".ddw-sessions", ".ddw-work",')),

    # ── The installer ────────────────────────────────────────────────────────
    ("the wiring is copied without claiming it",
     edit("scripts/install_target.py",
          "                if claim(key, sp, dp, manifest, collisions, w[\"to\"],\n"
          "                         ours_if_unknown=had_manifest):",
          "                if True:")),
    ("directory comparison goes back to one-directional",
     edit("scripts/install_target.py", "    if _relfiles(a) != _relfiles(b):", "    if False:")),
    ("the session id is used as a filename unsanitised",
     edit("ddw/scripts/session-boot.py",
          '    session_id = safe_id(args.session_id) if args.session_id else ""',
          '    session_id = args.session_id or ""')),
    ("the gitignore check matches comments again",
     edit("ddw/scripts/session-boot.py",
          "        rules = {ln.strip() for ln in existing.splitlines()\n"
          "                 if ln.strip() and not ln.lstrip().startswith(\"#\")}",
          "        rules = set(existing.split())")),
    ("the manifest is never written",
     edit("scripts/install_target.py", "        with open(os.path.join(repo, MANIFEST), \"w\", encoding=\"utf-8\") as fh:",
          "        return\n        with open(os.path.join(repo, MANIFEST), \"w\", encoding=\"utf-8\") as fh:")),
    ("agent frontmatter is emitted unquoted again",
     edit("scripts/install_target.py", "    return json.dumps(str(v), ensure_ascii=False)",
          "    return str(v)")),

    # ── The wiring that nothing ever executed ────────────────────────────────
    # check_adapter drives each tool's PRE hook. Nothing drove the post hooks,
    # session-start, enforce or pre-compact — they were syntax-checked and never
    # run, so any of them could be neutralised in silence.
    ("Claude's post-write net is neutralised",
     edit("adapters/claude/hooks/validate-state-postwrite.sh",
          'exec python3 "$DDW/scripts/hook-gate.py" --mode post',
          'exit 0\nexec python3 "$DDW/scripts/hook-gate.py" --mode post')),
    ("Codex's post-write net is neutralised",
     edit("adapters/codex/hooks/post-write.sh",
          'exec python3 "$GATE" --dialect codex --mode post',
          'exit 0\nexec python3 "$GATE" --dialect codex --mode post')),
    ("Claude's session boot never runs",
     edit("adapters/claude/hooks/session-start.sh",
          'exec python3 "$BOOT"', 'exit 0\nexec python3 "$BOOT"')),
    ("apply_patch stops recognising a modified file",
     edit("ddw/scripts/hook-gate.py", '"*** Update File: "', '"*** NEVER MATCHES: "')),
    ("an edit's replacement text is read as the whole file",
     edit("ddw/scripts/hook-gate.py",
          'CONTENT_KEYS = ("content", "contents", "text", "patchText")',
          'CONTENT_KEYS = ("content", "contents", "text", "newString", "patchText")')),
    ("the camelCase edit pair stops being understood",
     edit("ddw/scripts/hook-gate.py",
          '    if "old_string" not in out and isinstance(args.get("oldString"), str):',
          "    if False:")),
    ("Cursor's refusal loses the field Cursor reads",
     edit("ddw/scripts/hook-gate.py", '        print(json.dumps({"permission": "deny",',
          '        print(json.dumps({"denied": True,')),
    ("Gemini's refusal loses the field Gemini reads",
     edit("ddw/scripts/hook-gate.py", '        print(json.dumps({"decision": "deny", "reason": reason}))',
          '        print(json.dumps({"verdict": "deny", "reason": reason}))')),
    ("Codex's refusal loses its permissionDecision",
     edit("ddw/scripts/hook-gate.py", '            "permissionDecision": "deny",',
          '            "permission": "deny",')),
    ("Cursor stops being told a write is allowed",
     edit("ddw/scripts/hook-gate.py", '        print(json.dumps({"permission": "allow"}))',
          "        pass")),
    ("QUICK-FIX stops guarding security-sensitive paths",
     edit("ddw/scripts/validate-transition.py",
          "QUICKFIX_SENSITIVE = (", "QUICKFIX_SENSITIVE = ()\nUNUSED_SENSITIVE = (")),
    ("the QUICK-FIX ceiling stops being a ceiling",
     edit("ddw/scripts/validate-transition.py",
          "QUICKFIX_LOC_LIMIT = 10", "QUICKFIX_LOC_LIMIT = 10_000")),
    # The guard can also stop mattering without being edited at all: nothing has
    # to call it. That is how it held for one tool and for nobody else.
    ("nothing asks the shared gate about the QUICK-FIX scope any more",
     edit("ddw/scripts/validate-transition.py",
          "        reason = quickfix_scope_denied(target, root, disk)\n        if reason:\n            return reason",
          "        pass")),
    ("the concurrent-session warning can never fire",
     edit("ddw/scripts/session-boot.py", "STALE_SECONDS", "UNUSED_STALE")),

    # ── The prose contradicting itself ───────────────────────────────────────
    ("CODE goes back to one commit for the whole implementation",
     edit("ddw/rules/code.instructions.md",
          "one commit per block, plus whatever the",
          "one commit for the whole implementation, not one per block, plus whatever the")),
    ("the block loop stops committing the block it just closed",
     edit("ddw/rules/code.instructions.md",
          '7. **Commit the block** with `Skill(skill="ddw-commit")`',
          "7. **Leave the block for the closeout to commit**")),

    # ── Stale bases, stranded branches ───────────────────────────────────────
    ("branches are cut from the local base again, not the fetched one",
     edit("ddw/rules/branches.instructions.md",
          "git switch -c feat/{ticket}-short-name origin/{base}",
          "git switch -c feat/{ticket}-short-name {base}")),
    ("nothing measures how far the base moved while the branch sat there",
     edit("ddw/rules/branches.instructions.md",
          "git rev-list --count HEAD..origin/{base}      # commits the base gained since",
          "# (skip the drift check)")),
    ("CLOSEOUT stops asking where the branch lands",
     edit("ddw/rules/closeout.instructions.md",
          "## Step 4: Integration — where does this branch land? (MANDATORY)",
          "## Step 4: Notes")),
    ("the closeout drops the Integration line, so the step can be skipped quietly",
     edit("ddw/rules/closeout.instructions.md",
          "│  Integration: [merged into X | on the PR | next ticket   │",
          "│                                                          │")),

    # ── Unfinished sub-tickets ───────────────────────────────────────────────
    ("the boot stops looking for sub-tickets nobody ran",
     edit("ddw/scripts/session-boot.py",
          # Anchored on the call, not on the `if` above it: that line now carries
          # the pull-request notice too, and pinning both meant adding a second
          # thing to the same branch broke the mutation guarding the first.
          "        pending = pending_subtickets(repo)",
          "        pending = []")),
    ("a closed sub-ticket keeps being offered (the history's ticket is ignored)",
     edit("ddw/scripts/session-boot.py",
          "        if ticket in left or ticket == active:",
          "        if ticket == active:")),
    ("the sub-ticket pattern widens and swallows DISCOVERY's numbered PRDs",
     edit("ddw/scripts/session-boot.py",
          r'r"^prd-(.+[0-9])([a-z])\.md$"',
          r'r"^prd-(.+?)-?([a-z0-9]+)\.md$"')),
    ("a history entry may name any ticket it likes",
     edit("ddw/scripts/validate-transition.py",
          "    _check_entry_ticket(old_state, new_state, appended)\n", "")),

    # ── Error paths ──────────────────────────────────────────────────────────
    ("a documented error no longer has to be tested (the gap that reached VERIFY)",
     edit("ddw/rules/validation-rules.instructions.md",
          "| F-SPEC-16 | Documented error with no test |",
          "| W-SPEC-16 | Documented error with no test |")),
    ("F-SPEC-16 drops out of the spec validator's FAIL table",
     edit("skills/ddw-validate-spec/SKILL.md",
          "| F-SPEC-16 | A block documents an error that appears in no test of that block | all tiers |\n",
          "")),
    ("F-SPEC-16 is listed but the spec validator's FIX path cannot evaluate it",
     edit("ddw/scripts/validate_spec.py",
          '        units = [("Fix-plan", text)]', "        pass")),
    ("ACs go back to free prose, where a missing failure case is invisible",
     edit("ddw/rules/validation-rules.instructions.md",
          "| F-PRD-09 | AC not in EARS form |", "| W-PRD-09 | AC not in EARS form |")),
    ("the rule catalog grows a rule that no range asks for",
     edit("ddw/rules/validation-rules.instructions.md",
          "| F-SPEC-16 | Documented error with no test |",
          "| F-SPEC-17 | Documented error with no test |")),

    # ── The reasoning behind the method ──────────────────────────────────────
    ("a decision is documented with only its upside",
     edit("docs/RATIONALE.md",
          "**The cost.** A whole class of vulnerability",
          "**Also worth knowing.** A whole class of vulnerability")),
    ("RATIONALE.md disappears while the README still points at it",
     delete("docs/RATIONALE.md")),

    # ── The repo's own tooling ───────────────────────────────────────────────
    ("nothing invokes ddw-context-check, so it never runs",
     edit("ddw/rules/classify.instructions.md",
          'Invoke `Skill(skill="ddw-context-check")`', "Consider the stack sufficient")),
    ("the skill loses the restriction that keeps it from bloating the context file",
     edit("skills/ddw-context-check/SKILL.md",
          "never proposes prose, conventions, architecture",
          "may also propose prose, conventions, architecture")),
    ("a declined recommendation stops being mentioned at boot",
     edit("ddw/scripts/session-boot.py",
          "    declined = declined_recommendations(repo)", "    declined = []")),

    # ── Upgrading an existing install ────────────────────────────────────────
    ("a stale activation block is called current and left to rot",
     edit("scripts/install_target.py",
          "            elif existing[start:end + len(end_marker)].strip() == snippet.strip():",
          "            elif True:")),
    ("the block upgrade swallows whatever came after it in the user's file",
     edit("scripts/install_target.py",
          "                             + existing[end + len(end_marker):])",
          "                             + existing[len(existing):])")),

    # Was "AGENTS.md never gets the block". After the refactor that put the
    # instructions in AGENTS.md always, that defect is what mutation 78 injects —
    # keeping both would inflate the count while measuring one thing twice. So
    # this one moved to the mirror: the tool's own file never gets its pointer,
    # which leaves Claude and Gemini importing nothing at all.
    ("Claude and Gemini stop getting the pointer that imports the method",
     edit("scripts/install_target.py",
          '    if recipe.get("context_file", "AGENTS.md") != "AGENTS.md":',
          "    if False:")),

    ("the installer stops noticing that this repo already has DDW",
     edit("install.sh", 'INSTALLED="$(python3 - "$TARGET" "$SELF" <<\'PY\' 2>/dev/null || true',
          'INSTALLED=""; true "$(python3 - "$TARGET" "$SELF" <<\'PY\' 2>/dev/null || true')),
    ("an installed tool left out of the run is passed over in silence",
     edit("install.sh", 'case " $TARGETS " in *" $inst "*) ;; *) SKIPPED="$SKIPPED $inst" ;; esac',
          'case " $TARGETS " in *) ;; esac')),

    ("a pre-existing AGENTS.md with no ## Stack is congratulated instead of reported",
     edit("install.sh",
          '    grep -qF "$h" "$TARGET/AGENTS.md" || MISSING="$MISSING|$h"',
          '    grep -qF "$h" "$TARGET/AGENTS.md" || true')),
    # Renaming the section heading was the first attempt and proved nothing: the
    # table stayed, so the skill still knew every heading. The defect is the
    # skill losing one — a section the method reads that nothing checks for.
    ("the skill forgets a heading the method reads",
     edit("skills/ddw-context-check/SKILL.md",
          "| `## Architecture conventions` |", "| `## Arquitectura` |")),

    ("Gemini goes back to a block that never names AGENTS.md",
     json_edit("adapters/gemini/adapter.json", lambda d: d.pop("snippet", None))),
    ("the AGENTS.md guide disappears while the README sends people to it",
     delete("docs/AGENTS-MD.md")),

    ("the instructions go back to living in each tool's own file",
     edit("scripts/install_target.py",
          '    blocks = [(os.path.join(args.self, "ddw", "activation.snippet.md"), "AGENTS.md")]',
          "    blocks = []")),
    ("Claude's pointer loses the import that brings the project context in",
     edit("adapters/claude/CLAUDE.snippet.md", "@AGENTS.md\n", "")),
    ("Gemini's orchestrator import moves behind a nested hop its docs never promised",
     edit("adapters/gemini/GEMINI.snippet.md", "@.ddw/orchestrator.md\n", "")),

    # ── The uninstaller ──────────────────────────────────────────────────────
    ("the uninstaller reads skill paths as repo paths and silently skips them all",
     edit("scripts/uninstall_repo.py",
          '        rel = resolve(key, os.path.abspath(args.self))',
          '        rel = key.split(":", 1)[1] if ":" in key else key')),
    ("it removes a whole tool directory instead of the files it installed",
     edit("scripts/uninstall_repo.py", 'METHOD = (".ddw",)',
          'METHOD = (".ddw", ".claude", ".gemini")')),
    ("it takes docs/ with it",
     edit("scripts/uninstall_repo.py", 'RUNTIME = (".ddw-state.json"',
          'RUNTIME = ("docs", ".ddw-state.json"')),
    ("DDW's hooks stay wired to scripts it just deleted",
     edit("scripts/uninstall_repo.py",
          "        for event in list(dst.get(key, {})):", "        for event in []:")),
    ("--plan starts deleting things before you have approved it",
     edit("scripts/uninstall_repo.py", "    act = not args.plan", "    act = True")),

    ("impatience can be read as PRD approval again",
     edit("ddw/rules/define.instructions.md",
          "> **Impatience is not approval.**", "> **A note on pace.**")),

    # First attempt turned "**stamped" into "**not stamped", which the check
    # happily matched — "not stamped with" contains "stamped with". The defect
    # that actually shipped was the instruction being ABSENT, so that is what
    # this injects.
    ("CLASSIFY appends its entry without being told to stamp the ticket",
     edit("ddw/rules/classify.instructions.md",
          "(or → DISCOVERY, or → FREE), **stamped\n     with `ticket` and `tier`** "
          "(see `.ddw/rules/state.instructions.md`). This is the first entry\n"
          "     that can carry a ticket — the one before it left IDLE, where there was none yet.",
          "(or → DISCOVERY, or → FREE).")),
    ("a phase appends to history without being told what to stamp on the entry",
     edit("ddw/rules/verify.instructions.md",
          "transition VERIFY \u2192 CLOSEOUT, **stamped with `ticket` and `tier`** "
          "(see `.ddw/rules/state.instructions.md`)",
          "transition VERIFY \u2192 CLOSEOUT")),

    # ── What a gate rests on ─────────────────────────────────────────────────
    ("the receipt is asked for by the helper again, and not by the hook",
     edit("ddw/scripts/validate-transition.py",
          "        reason = gate_evidence_missing(root, new_state, sorted(set(owed)))\n"
          "        if reason:\n"
          "            return reason",
          "        reason = None")),
    ("the shell can still set a gate that owes evidence",
     edit("ddw/scripts/validate-transition.py",
          "        reason = gate_evidence_missing(os.path.dirname(os.path.abspath(state_path)),\n"
          "                                       disk_state, sorted(set(owed)))\n"
          "        if reason:\n"
          "            raise Block(reason)",
          "        pass")),
    ("the receipt stops naming the PRD's current bytes, and attests to a rewrite",
     edit("ddw/scripts/validate-transition.py",
          'marker = os.path.join(root, ".ddw-sessions", "%s-validated-%s" % (receipt, digest))',
          'sess = os.path.join(root, ".ddw-sessions")\n'
          '    marker = next((os.path.join(sess, f) for f in\n'
          '                   (sorted(os.listdir(sess)) if os.path.isdir(sess) else [])\n'
          '                   if f.startswith(receipt + "-validated-")), "")')),
    ("the commit gate goes back to taking the model's word",
     # One key, never its neighbours: this table grows every time a gate earns
     # evidence, and an anchor that includes the next entry breaks on the growth
     # it is supposed to be indifferent to.
     edit("ddw/scripts/validate-transition.py",
          '"commit": _commit_evidence_missing,',
          '"_commit": _commit_evidence_missing,')),
    ("an untracked build directory starts blocking the closeout",
     edit("ddw/scripts/validate-transition.py",
          'dirty = _git(root, "status", "--porcelain", "--untracked-files=no")',
          'dirty = _git(root, "status", "--porcelain")')),
    # Anchored on the row's identity \u2014 the tool and the install path \u2014 and not on
    # its date or its verdicts. Pinning the whole row meant recording a run broke
    # the mutation that guards the record, which is a mutation that goes stale
    # every time the thing it protects is used as intended.
    ("the README claims a tool passed acceptance that the record does not",
     edit("scripts/acceptance.md",
          "| Claude Code | drop-in |",
          "| Claude Code | drop-in | \u2014 | \u2014 | \u2014 | \u2014 | \u2014 | \u2014 | \u2014 |\n"
          "| Claude Code (shadowed by the mutation) | drop-in |")),
    ("a tool the record has driven live is still called unverified in the wild",
     edit("README.md",
          "- **Codex CLI, Cursor, Gemini CLI** \u2014 each adapter is driven through its own",
          "- **Codex CLI, Cursor, Gemini CLI, OpenCode** \u2014 each adapter is driven through its own")),
    ("a tool nobody has ever driven stops being named as one",
     edit("README.md",
          "- **Codex CLI, Cursor, Gemini CLI** \u2014 each adapter is driven through its own",
          "- **Codex CLI, Gemini CLI** \u2014 each adapter is driven through its own")),

    # ── The shell bypass ─────────────────────────────────────────────────────
    ("nothing notices source written through a shell in a no-source phase",
     edit("ddw/scripts/hook-gate.py",
          "                note = vt.source_changed_in_no_source_phase(args.repo, phase)",
          "                note = None")),
    ("the report becomes a refusal, blocking your own editing in another terminal",
     edit("ddw/scripts/hook-gate.py",
          '                    notice_post(args.dialect, f"DDW notices: {note}")',
          "                    deny(args.dialect, note)")),
    ("--block starts riding edges, hiding a state change inside a transition",
     edit("ddw/scripts/transition.py",
          "    if block_given and args.to:",
          "    if block_given and args.to and False:")),
    ("any floor passes as the method default, 90 included",
     edit("ddw/scripts/validate_tests.py",
          "        if floor == 80.0:",
          "        if True:")),
    ("the method default's honest wording starts being refused",
     edit("ddw/scripts/validate_tests.py",
          "        if floor == 80.0:",
          "        if floor == 81.0:")),
    ("copilot's partial commit gate disappears and -m commits sail through again",
     edit("ddw/scripts/hook-gate.py",
          '    if args.mode == "pre" and args.dialect == "copilot":',
          '    if False and args.dialect == "copilot":')),
    ("a copilot merge stops waiting for its proposal on disk",
     edit("ddw/scripts/hook-gate.py",
          "                reason = merge_verdict(args.repo, _cmd, require_seal=False)",
          "                reason = None")),
    ("copilot's model omission stops being a decision on file",
     json_edit("adapters/copilot/adapter.json", lambda d: d["agents"].pop("_model_note"))),
    ("claude's agent model becomes a literal the source cannot correct",
     edit("adapters/claude/adapter.json",
          '"model": "{model}"',
          '"model": "inherit"')),
    ("the go-back gate disappears from the sanctioned helper",
     edit("ddw/scripts/transition.py",
          "        _reason = vt.goback_gate(_root, old_state, new_state, graph)",
          "        _reason = None")),
    ("the classify edge stops asking for its context check",
     edit("ddw/scripts/validate-transition.py",
          '    if entry.get("from") != "CLASSIFY" or entry.get("to") != "DEFINE":',
          "    if True:")),
    ("the context-check gate disappears from the sanctioned helper",
     edit("ddw/scripts/transition.py",
          "        _reason = (vt.context_check_missing(_root, old_state, new_state)\n"
          "                   or vt.impact_receipt_missing(_root, old_state, new_state)\n"
          "                   or vt.decisions_record_missing(_root, old_state, new_state)\n"
          "                   or vt.family_split_pause_missing(_root, old_state, new_state))",
          "        _reason = (vt.impact_receipt_missing(_root, old_state, new_state)\n"
          "                   or vt.decisions_record_missing(_root, old_state, new_state)\n"
          "                   or vt.family_split_pause_missing(_root, old_state, new_state))")),
    ("the context-check gate disappears from the hook's pre path",
     edit("ddw/scripts/validate-transition.py",
          "            reason = context_check_missing(root, old_state, new_state)",
          "            reason = None")),
    ("CODE closes without its decisions record again",
     edit("ddw/scripts/validate-transition.py",
          '    if entry.get("from") != "CODE" or entry.get("to") not in ("VERIFY", "CLOSEOUT"):',
          "    if True:")),
    ("the decisions gate disappears from the sanctioned helper",
     edit("ddw/scripts/transition.py",
          "        _reason = (vt.context_check_missing(_root, old_state, new_state)\n"
          "                   or vt.impact_receipt_missing(_root, old_state, new_state)\n"
          "                   or vt.decisions_record_missing(_root, old_state, new_state)\n"
          "                   or vt.family_split_pause_missing(_root, old_state, new_state))",
          "        _reason = (vt.context_check_missing(_root, old_state, new_state)\n"
          "                   or vt.impact_receipt_missing(_root, old_state, new_state)\n"
          "                   or vt.family_split_pause_missing(_root, old_state, new_state))")),
    ("the decisions gate disappears from the hook's pre path",
     edit("ddw/scripts/validate-transition.py",
          "            reason = decisions_record_missing(root, old_state, new_state)",
          "            reason = None")),
    ("the block marker stops spending its reviews",
     edit("ddw/scripts/validate-transition.py",
          "    if new_block == old_block:\n        return None",
          "    if True:\n        return None")),
    ("the review gate disappears from the helper's --block path",
     edit("ddw/scripts/transition.py",
          "            _reason = vt.block_review_missing(\n"
          "                os.path.dirname(os.path.abspath(args.state)),\n"
          "                old_state.get(\"block\"), block_val)",
          "            _reason = None")),
    ("the review gate disappears from the hook's pre path",
     edit("ddw/scripts/validate-transition.py",
          '            reason = block_review_missing(root, old_state.get("block"),\n'
          '                                          new_state.get("block"))',
          "            reason = None")),
    ("the shell-write notice stops being journalled",
     edit("ddw/scripts/hook-gate.py",
          "                    vt.record_notice(args.state, note)",
          "                    pass")),
    ("the notice record itself goes nowhere",
     edit("ddw/scripts/validate-transition.py",
          '        _journal_append(state_path, [{"record": "notice", "note": note}])',
          "        pass")),
    ("an unchanged finding floods the journal again",
     edit("ddw/scripts/validate-transition.py",
          '                if entry.get("note") == note:\n                    return',
          "                if False:\n                    return")),
    ("the landed write goes back to landing silently",
     edit("ddw/scripts/transition.py",
          "        print(_status_box(state, vt, graph), file=sys.stderr)",
          "        pass")),
    ("a sub-PRD renumbering its index's criteria stops being refused",
     edit("ddw/scripts/validate_prd.py",
          "            if renumbered:",
          "            if False:")),
    ("the family index gets its gate taken away",
     edit("ddw/scripts/validate-transition.py",
          '    rel = os.path.relpath(target, root).replace(os.sep, "/")\n'
          '    if not (rel.startswith("docs/ddw/prd/") and rel.endswith(".md")):\n'
          "        return None",
          '    rel = os.path.relpath(target, root).replace(os.sep, "/")\n'
          "    if True:\n"
          "        return None")),
    ("the family gate disappears from the hook's pre path",
     edit("ddw/scripts/validate-transition.py",
          "        reason = family_index_write_denied(target, root, tool_name, tool_input)",
          "        reason = None")),
    ("a claim event stops owing its receipt",
     edit("ddw/scripts/validate-transition.py",
          "    if not blessed and state_path:",
          "    if False:")),
    ("a dropped row stops needing its reason",
     edit("ddw/scripts/validate-transition.py",
          '        status_ok = bool(drop or unver\n'
          '                         or status in ("active", "pending", "done"))',
          '        status_ok = bool(drop or unver\n'
          '                         or status in ("active", "pending", "done", "dropped"))')),
    ("the impact gate vanishes from the family's classify edge",
     edit("ddw/scripts/validate-transition.py",
          '    if not re.search(r"^##\\s+Repo family\\s*$", agents, re.MULTILINE | re.IGNORECASE):',
          "    if True:")),
    ("an impact verdict edited after validation keeps its dead receipt",
     edit("ddw/scripts/validate-transition.py",
          '    if not os.path.exists(receipt):',
          "    if False:")),
    ("dependencies become satisfied by the index's word",
     edit("ddw/scripts/family_next.py",
          '        blockers = [d for d in r["deps"] if not merged.get(short(d))]',
          "        blockers = []")),
    ("the stale index stops outranking the walk",
     edit("ddw/scripts/family_next.py",
          "    if stale:",
          "    if False:")),
    ("a blocked child rides the parallel set",
     edit("ddw/scripts/family_next.py",
          "        if all(merged.get(d2) for d2 in deps_short):",
          "        if True:")),
    ("a merged child is launched again by the parallel set",
     edit("ddw/scripts/family_next.py",
          '        if merged.get(r["repo"].rsplit("/", 1)[-1]):',
          "        if False:")),
    ("the leash stops reading the diff",
     edit("ddw/scripts/family_index_pr.py",
          "    outside = sorted(p for p in files if not ALLOWED.match(p))",
          "    outside = []")),
    ("the leash's refusal stops naming the offender",
     edit("ddw/scripts/family_index_pr.py",
          '                "human merge, always." % (pr, ", ".join(outside)))',
          '                "human merge, always." % (pr, ""))')),
    ("a row says done on anyone's word",
     edit("ddw/scripts/family_index_pr.py",
          '    if status.strip().lower() == "done":',
          "    if False:")),
    ("a dirty worktree is removed anyway, work and all",
     edit("ddw/scripts/ticket_worktree.py",
          "    if code != 0 or out:",
          "    if False:")),
    ("a worktree closes on anyone's word",
     edit("ddw/scripts/ticket_worktree.py",
          "        if pr is None:",
          "        if False:")),
    ("the close refusal stops teaching the law",
     edit("ddw/scripts/ticket_worktree.py",
          '            return _fail("no MERGED pull request names %s at the forge — a worktree "\n'
          '                         "does not close on anyone\'s word. If the work is being "\n'
          '                         "abandoned, say so: `close --ticket %s --drop \\"<why>\\"`."\n'
          '                         % (ticket, ticket))',
          '            return _fail("refused (%s %s)" % (ticket, ticket))')),
    ("the removal is announced but never performed",
     edit("ddw/scripts/ticket_worktree.py",
          '    code, _, err = _run(["git", "-C", top, "worktree", "remove", path], timeout=120)',
          '    code, _, err = 0, "", ""')),
    ("the new worktree starts where the standing tree stands",
     edit("ddw/scripts/ticket_worktree.py",
          '    code, _, err = _run(["git", "-C", top, "worktree", "add", "--detach", path, ref],',
          '    code, _, err = _run(["git", "-C", top, "worktree", "add", "--detach", path],')),
    ("the index stops checking the map",
     edit("ddw/scripts/validate_prd.py",
          '        mapa_path = ddw_receipt.find_upward(args.prd, "familia.md")',
          "        mapa_path = None")),
    ("a dependency on a repo outside the table stops being an error",
     edit("ddw/scripts/validate_prd.py",
          "                if dep not in listed:",
          "                if False:")),
    ("the multirepo index stops being judged as one",
     edit("ddw/scripts/validate_prd.py",
          '    if re.search(r"^\\|\\s*Status\\s*\\|\\s*Multirepo", text, re.MULTILINE | re.IGNORECASE):',
          "    if False:")),
    ("a departure vanishes from the catalog silently",
     edit("ddw/scripts/family_catalog.py",
          '                gone.append((name, "no longer declares this family"))',
          "                pass")),
    ("the regenerated catalog eats the prose outside its markers",
     edit("ddw/scripts/family_catalog.py",
          "    if BEGIN in current:\n"
          "        head = current.split(BEGIN, 1)[0]\n"
          '        tail = current.split(END, 1)[1] if END in current else "\\n"\n'
          "        new_text = head + block + tail",
          "    if BEGIN in current:\n"
          '        new_text = block + "\\n"')),
    ("an unchanged family rewrites the catalog anyway",
     edit("ddw/scripts/family_catalog.py",
          "    if strip_stamp(current) == strip_stamp(new_text):\n"
          '        print("family_catalog: no changes — %d repo(s), catalog already current." % len(rows))',
          "    if False:\n"
          '        print("family_catalog: no changes — %d repo(s), catalog already current." % len(rows))')),
    ("--check calls a stale catalog fresh",
     edit("ddw/scripts/family_catalog.py",
          "        if strip_stamp(current) == strip_stamp(new_text):\n"
          '            print("family_catalog: fresh — every row matches its repo\'s AGENTS.md.")',
          "        if True:\n"
          '            print("family_catalog: fresh — every row matches its repo\'s AGENTS.md.")')),
    ("the sync lands on a ticket branch again",
     edit("ddw/scripts/family_catalog.py",
          '        if head not in ("", default) or mid_ticket:',
          "        if False:")),
    ("the member sync eats the rest of the AGENTS.md",
     edit("ddw/scripts/family_catalog.py",
          "            new_text = text[:m.start()] + section + chr(10) + text[end:].lstrip(chr(10))",
          "            new_text = section")),
    ("a status outside the vocabulary lands unjudged",
     edit("ddw/scripts/validate-transition.py",
          '        status_ok = bool(drop or unver\n'
          '                         or status in ("active", "pending", "done"))',
          "        status_ok = True")),
    ("F-PRD-12 stops judging the status vocabulary",
     edit("ddw/scripts/validate_prd.py",
          '            if not r.get("status_ok", True):',
          "            if False:")),
    ("a vanished row goes back to vanishing silently",
     edit("ddw/scripts/validate-transition.py",
          '            if old_row["repo"] not in new_names:',
          "            if False:")),
    ("dismissing the judge works again",
     edit("ddw/scripts/validate-transition.py",
          "    if not FAMILY_MARKER.search(content):\n        if was_index:",
          "    if not FAMILY_MARKER.search(content):\n        if False:")),
    ("the multirepo pause stops spending the receipt",
     edit("ddw/scripts/validate-transition.py",
          '    if (entry.get("from") != "DEFINE" or entry.get("to") != IDLE\n'
          '            or not action.startswith("pause") or "multirepo" not in action):\n'
          "        return None",
          "    if True:\n        return None")),
    ("the pause gate disappears from the sanctioned helper",
     edit("ddw/scripts/transition.py",
          "        _reason = (vt.context_check_missing(_root, old_state, new_state)\n"
          "                   or vt.impact_receipt_missing(_root, old_state, new_state)\n"
          "                   or vt.decisions_record_missing(_root, old_state, new_state)\n"
          "                   or vt.family_split_pause_missing(_root, old_state, new_state))",
          "        _reason = (vt.context_check_missing(_root, old_state, new_state)\n"
          "                   or vt.impact_receipt_missing(_root, old_state, new_state)\n"
          "                   or vt.decisions_record_missing(_root, old_state, new_state))")),
    ("the pause gate disappears from the hook's pre path",
     edit("ddw/scripts/validate-transition.py",
          "            reason = family_split_pause_missing(root, old_state, new_state)",
          "            reason = None")),
    ("an unaskable forge reads as merged",
     edit("ddw/scripts/validate-transition.py",
          '        return ("the family index marks `%s` as done and the forge could not be asked "\n'
          '                "(gh unreachable or unauthenticated). The count never degrades to \\"trust "\n'
          '                "me\\" in silence: retry when the forge answers, or assert it on the record "\n'
          '                "as `done (unverified: <why>)` — a human\'s name on the assertion is the "\n'
          '                "declared way out." % row["repo"])',
          "        continue")),
    ("the state's refusal becomes a puzzle again",
     edit("ddw/scripts/validate-transition.py",
          '            raise Block("Edit to the state with no old_string/new_string." + _HELPER)',
          '            raise Block("Edit to the state with no old_string/new_string.")')),
    ("the go-back gate disappears from the hook's pre path",
     edit("ddw/scripts/validate-transition.py",
          "            reason = goback_gate(root, old_state, new_state, graph)",
          "            reason = None")),
    ("a question goes back without the user's turn again",
     edit("ddw/scripts/validate-transition.py",
          '        if sealed == hashlib.sha256(text.strip().encode("utf-8")).hexdigest():\n'
          "            return None",
          "        if True:\n"
          "            return None")),
    ("the spec skill teaches a schema-reuse phrasing its own validator rejects",
     edit("skills/ddw-create-spec/SKILL.md",
          '- Reuses `ticket` from Block 2 — no schema change; constraints as declared there: NOT NULL,\n'
          '  default "Pendiente", index on estado.',
          "- Same table as Block 2.")),
    ("the commit skill's minimal carve-out disappears and every commit waits again",
     edit("skills/ddw-commit/SKILL.md",
          "   Under `assisted`, **end your turn**: the file is the message, it is what will be committed, so\n"
          "   what they read and what lands are the same bytes, and the gate holds the commit until that\n"
          "   exact text was on screen before their answer. Under `minimal`, the showing still happens and\n"
          "   the asking does not (`.ddw/orchestrator.md` § Autonomy — a commit is local and reversible, not\n"
          "   one of the acts that keep their confirmation in both modes): present the message and continue\n"
          "   to step 8 in the same response. This step used to read as unconditional, and a live `minimal`\n"
          "   run stopped at every one of its commits waiting for an \"ok\" the mode had already given —\n"
          "   `assisted` with different words, in the exact place the orchestrator's exemption was not.",
          "   **end your turn.** The file is the message: it is what will be committed, so what they\n"
          "   read and what lands are the same bytes.")),
    ("--block stops reaching the state and the marker silently stays stale",
     edit("ddw/scripts/transition.py",
          '        updated["block"] = block_val',
          '        updated["block"] = old_state.get("block")')),
    ("a block change leaves no journal trace again",
     edit("ddw/scripts/validate-transition.py",
          "            if block_now != last_block:",
          "            if False and block_now != last_block:")),
    ("an identical re-validation duplicates its journal line again",
     edit("ddw/scripts/ddw_receipt.py",
          "            if tail.strip() != line:",
          "            if True:")),
    ("a spent gate stops naming its ticket and spends every ticket's receipts",
     edit("ddw/scripts/validate-transition.py",
          "            if ticket is None or entry.get(\"ticket\") in (None, ticket):",
          "            if True:")),
    ("a floor attributed to AGENTS.md stops being read back against it",
     edit("ddw/scripts/validate_tests.py",
          '        agents = ddw_receipt.find_upward(args.report, "AGENTS.md")',
          "        agents = None")),
    ("the verify floor stops being the project's and goes back to a constant",
     edit("ddw/scripts/validate_verify.py",
          '    agents = ddw_receipt.find_upward(report_path, "AGENTS.md")',
          "    return 80.0")),
    ("the notice falls back to stderr, where no tool listens",
     edit("ddw/scripts/hook-gate.py",
          '    if dialect == "copilot":\n'
          '        print(json.dumps({"additionalContext": reason}))\n'
          '    elif dialect == "standard":\n'
          '        print(json.dumps({"hookSpecificOutput": {\n'
          '            "hookEventName": "PostToolUse",\n'
          '            "additionalContext": reason}}))\n'
          "    print(reason, file=sys.stderr)\n"
          "    sys.exit(0)",
          "    print(reason, file=sys.stderr)\n"
          "    sys.exit(0)")),
    ("DDW's own untracked files are reported as product source on every fresh install",
     edit("ddw/scripts/validate-transition.py",
          '_NOT_PRODUCT = frozenset({".ddw", ".ddw-installed.json", ".git",',
          "_NOT_PRODUCT = frozenset()\n_UNUSED_NOT_PRODUCT = frozenset({")),
    ("an untracked artifact directory reads as product source again",
     edit("ddw/scripts/validate-transition.py",
          '        target = resolve_in_repo(probe.rstrip("/") + ("/x" if path.endswith("/") else ""), root)',
          "        target = resolve_in_repo(probe.rstrip(\"/\"), root)")),

    # ── Compaction ───────────────────────────────────────────────────────────
    # The pipeline's quietest ending: the model keeps answering, from a summary
    # of the state machine rather than the state machine.
    ("a tool stops being told the pipeline survived its compaction",
     json_edit("adapters/gemini/settings.json", lambda d: d["hooks"].pop("PreCompress"))),
    ("the compaction event is wired to the wrong script",
     edit("adapters/cursor/hooks.json",
          '"command": ".cursor/hooks/ddw/pre-compact.sh"',
          '"command": ".cursor/hooks/ddw/session-start.sh"')),
    ("OpenCode stops hearing the compaction it cannot print about anyway",
     edit("adapters/opencode/plugin/ddw.js", 'event?.type === "session.compacted"',
          'event?.type === "session.never-happens"')),
    # Not the opening line — the DEMAND. A reminder that fires and then lets the
    # model answer from the summary is the same outcome as no reminder, reached
    # expensively.
    ("the reminder stops forbidding an answer before the boot is redone",
     edit("ddw/scripts/session-boot.py",
          '        "\\nDo NOT answer without completing these 4 steps. The state machine is re-read from "\n'
          '        "disk, never inferred from a post-compaction summary."\n',
          '        ""\n')),

    # The corrupt-state refusal orders a scratch file outside the repo. Take the
    # exit away and the order stands with nowhere to carry it out — the shape of
    # painted door this section exists to keep closed.
    ("the corrupt-state refusal orders a write it also forbids",
     edit("ddw/scripts/validate-transition.py",
          "    if (all(_outside_repo(t, root) for t in targets)\n            and all(_outside_repo(lex, root) for lex in lexicals)):\n        return None\n",
          "")),
    # And the other direction: one outside path in an envelope that also names
    # the state would wave the whole event through.
    ("one path outside the repo excuses every other path in the same event",
     edit("ddw/scripts/validate-transition.py",
          "    if (all(_outside_repo(t, root) for t in targets)",
          "    if (any(_outside_repo(t, root) for t in targets)")),

    ("the record's row width goes back to being pinned, and every row stops matching",
     edit("scripts/verify_install.sh", "    if len(cells) != width:", "    if len(cells) != 8:")),

    # Breaks an anchor rather than the check that reads it: a mutation that
    # merely disabled the check would leave the suite green and survive, which
    # is a mutation measuring nothing — the thing this whole file is about.
    # The preflight runs against the tree as it is, before anything is injected —
    # the only place it can run without scoring its own side effect as a kill.
    # That also puts it out of reach of a mutation: breaking an anchor inside the
    # copy is invisible now, because the copy no longer checks. So what gets
    # mutated is the CALL, and the suite asserts the call is there and is first.
    ("mutate.py stops verifying its anchors before it starts injecting",
     edit("scripts/mutate.py", "    if check_anchors() != 0:\n        return 1",
          "    if False:\n        return 1", last=True)),
    # The ceiling was a number in four documents and a comparison in none of
    # them, so one of the three stops that hold under `minimal` was unreachable.
    # ── Going back, and what going back costs ────────────────────────────────
    ("the status line goes back to calling the phase by the name it lost",
     edit("ddw/orchestrator.md", "🏁 {TIER} · Closing out [5/5]", "🚀 {TIER} · Releasing [5/5]")),
    ("an upgraded state is accused of being forged instead of being explained",
     edit("ddw/scripts/validate-transition.py",
          "        if renamed:", "        if False:")),
    ("a backward transition may keep the gates it is supposed to give up",
     edit("ddw/scripts/validate-transition.py",
          "        still_held = [g for g in cleared if gates.get(g) is True]",
          "        still_held = []")),
    ("the graph stops saying what stepping back gives up",
     edit("ddw/rules/transition-graph.json",
          '"clears": [\n          "define"\n        ]', '"clears": []')),
    ("CLOSEOUT takes an abandon again, and the closeout's gates are dodgeable",
     edit("ddw/scripts/validate-transition.py",
          "                if not (_is_pause(entry) and paid):",
          "                if False:")),
    ("a pause at CLOSEOUT stops needing the work committed and the PR open",
     edit("ddw/scripts/validate-transition.py",
          '                paid = (all(gates_before.get(g) is True for g in ("commit", "pr"))',
          "                paid = (True or all(gates_before.get(g) is True for g in ('commit', 'pr'))")),
    ("resuming at CLOSEOUT keeps the commit and the PR earned before the wait",
     edit("ddw/scripts/validate-transition.py",
          '            if dst == "CLOSEOUT":\n                stale = [g for g in ("commit", "pr") if gates.get(g) is True]',
          '            if False:\n                stale = [g for g in ("commit", "pr") if gates.get(g) is True]')),
    ("the corrective loop's ceiling goes back to being a number nothing compares",
     edit("ddw/scripts/validate_prd.py", "    if loops >= LOOP_CEILING:", "    if False:")),
    ("the sast gate goes back to turning true on the model's say-so",
     edit("ddw/scripts/validate-transition.py",
          '"sast": _sast_receipt_missing,',
          '"_sast": _sast_receipt_missing,')),
    ("a warning marker exempts a Critical from every other rule again",
     edit("ddw/scripts/validate_sast.py",
          "    downgraded = [r for r, ls in lines.items()", "    downgraded = [] or [r for r, ls in lines.items()"[:0] + "    downgraded = []\n    _unused = [r for r, ls in lines.items()")),
    ("a Critical becomes suppressible again",
     edit("ddw/scripts/validate_sast.py", "    if unsuppressible:", "    if False:")),
    ("a red test run earns the tests gate again",
     edit("ddw/scripts/validate_tests.py", "    elif failed > 0:", "    elif False:")),
    ("two runs in one report stop being two runs",
     edit("ddw/scripts/validate_tests.py", "    if dupes:", "    if False:")),
    ("a PASSED SAST validation stops leaving its receipt",
     edit("ddw/scripts/validate_sast.py",
          '        print("Receipt: .ddw-sessions/"\n'
          '              + ddw_receipt.write(args.report, "sast", text, args.tier, asof=today.isoformat()))',
          "        pass")),
    ("a receipt is written and nothing records that a validator wrote it",
     edit("ddw/scripts/ddw_receipt.py",
          '            if tail.strip() != line:\n                fh.write(line + "\\n")',
          "            pass")),
    ("a receipt nobody's validator wrote opens its gate again",
     edit("ddw/scripts/validate-transition.py",
          "            unwitnessed = _receipt_unwitnessed(root, os.path.basename(marker))\n"
          "            if unwitnessed:\n                return unwitnessed",
          "            unwitnessed = None\n            if unwitnessed:\n                return unwitnessed")),
    ("a receipt from before the corrective loop opens the gate it cleared",
     edit("ddw/scripts/validate-transition.py",
          "            return _receipt_spent(root, gate, os.path.basename(marker),\n"
          "                                  ticket=state.get(\"ticket\"))",
          "            return None")),
    ("a category nobody judged stops being noticed",
     edit("ddw/scripts/validate_sast.py",
          "    missing = [r for r in CATEGORIES if r not in lines]",
          "    missing = []")),
    ("a Critical finding above a PASSED verdict stops being a contradiction",
     edit("ddw/scripts/validate_sast.py",
          "    if blocking and (says_passed or not says_blocked):",
          "    if False:")),
    ("a suppression stops ageing, and six months means nothing",
     edit("ddw/scripts/validate_sast.py",
          "        if due < today:",
          "        if False:")),

    # ── The test run, which used to be one word ──────────────────────────────
    ("the tests gate goes back to turning true on a sentence",
     edit("ddw/scripts/validate-transition.py",
          '"tests": _tests_receipt_missing,',
          '"_tests": _tests_receipt_missing,')),
    ("a run report stops needing the command that produced it",
     edit("ddw/scripts/validate_tests.py",
          "    if runner and command:",
          "    if True:")),
    ("counts that do not add up stop being a contradiction",
     edit("ddw/scripts/validate_tests.py",
          "    elif abs((passed + failed + skipped) - total) > 0.5:",
          "    elif False:")),
    ("coverage under the floor stops blocking",
     edit("ddw/scripts/validate_tests.py",
          "        under = [f\"{n} {v:.0f}%\" for n, v in have if v < floor]",
          "        under = []")),
    ("the pr gate stops asking the forge and takes the model's word again",
     edit("ddw/scripts/validate-transition.py",
          '"pr": _pr_evidence_missing}',
          '}')),
    # The field itself: absent has to read as assisted, or every repo that
    # upgrades is reported broken by its own self-check.
    ("the state schema forgets the autonomy field",
     edit("ddw/scripts/session-boot.py", '    "autonomy": None,\n', "")),

    # ── What the user actually reads ─────────────────────────────────────────
    # Three defects found by installing it and using it, not by any of the above.
    ("the refusal doubles its prefix and reads DDW blocked this write: DDW:",
     edit("ddw/scripts/validate-transition.py",
          'return ("the %s gate needs a validation receipt for %s and there is none for its "',
          'return ("DDW: the %s gate needs a validation receipt for %s and there is none for its "')),
    ("the method's own bytecode stops being gitignored, and the drop-in commits it",
     edit("install.sh", "      '.ddw/**/__pycache__/' \\\n", "")),
    # The rule that reached the model twice and worked neither time lived in a
    # file the model had not opened. Take it out of the output and it goes back
    # to depending on which files were loaded that turn.
    ("the validator stops telling the model to show the table it just printed",
     # Not `print("" or "Show…")`, which is what this said first: that evaluates
     # to the same string and prints the same line, so nothing could kill it and
     # the run reported it surviving for two releases. An equivalent mutant is a
     # line in a list.
     edit("ddw/scripts/validate_prd.py",
          '    print("Show the user this table IN FULL',
          '    _ = ("Show the user this table IN FULL')),

    ("the protocol stops saying a re-validation prints the table",
     edit("ddw/rules/validation-rules.instructions.md",
          "**A re-validation is a validation, and it shows the whole table too.**",
          "A re-validation is whatever the model feels like.")),
    ("a validation skill drops it where the protocol is executed",
     edit("skills/ddw-validate-prd/SKILL.md",
          "**Every\n   run, including a re-validation of a PRD that has not changed**",
          "**Every run**")),

    # ── Attribution ──────────────────────────────────────────────────────────
    # The rule DDW ships to every repo it is installed in, applied here. Each of
    # these is a way the checker keeps returning success while checking nothing.
    ("Co-Authored-By stops being refused, and the tool is credited as an author",
     edit("scripts/check_commits.py", 'COAUTHOR = re.compile(r"^Co-Authored-By:", re.M | re.I)',
          'COAUTHOR = re.compile(r"^Co-Authored-By-NEVER-MATCHES:", re.M | re.I)')),
    ("a commit with no attribution at all stops being noticed",
     edit("scripts/check_commits.py", "        elif not TRAILER.search(body):",
          "        elif False:")),
    # The exemption exists so the weekly dependency PR is not red on arrival.
    # Losing it is not loud: nothing breaks until Monday, in a pull request
    # nobody is watching, and the rule people learn is "the check is always red".
    ("the bot exemption goes, and every dependency PR lands red",
     edit("scripts/check_commits.py", "        if is_bot(name, email):",
          "        if False:")),
    # And the other direction: an exemption that stops naming who it exempted is
    # a check that stopped running, wearing the same green.
    ("a skipped commit stops being named and is only subtracted",
     edit("scripts/check_commits.py",
          '            skipped.append(f"{sha[:9]} {name}")',
          "            pass")),
    ("the pull request's own merge commit is held to the attribution rule again",
     edit("scripts/check_commits.py", '"log", "--no-merges",', '"log",')),

    ("a range git cannot read reports success instead of saying it did not run",
     edit("scripts/check_commits.py",
          '        print(f"check_commits: cannot read {args.since}..HEAD — the check did NOT run\\n"\n'
          '              f"  {out.stderr.strip()}")\n'
          "        return 1",
          "        return 0")),
    ("CI stops asking the question on the pull requests that carry the commits",
     edit(".github/workflows/verify.yml",
          "          python3 scripts/check_commits.py --since \"origin/${{ github.base_ref }}\"",
          "          true")),

    # ── Versions ─────────────────────────────────────────────────────────────
    ("the product ships two different version numbers",
     json_edit(".claude-plugin/plugin.json", lambda d: d.update({"version": "2.2.0"}))),
    # Anchored on the frontmatter, not the number: a rule file's version moves
    # every time the rule does, and pinning it meant that editing a rule broke
    # the mutation that guards every rule's version.
    ("a rule's version stops being semver",
     edit("ddw/rules/code.instructions.md", "\nversion: ", "\nversion: latest-")),
    ("the validator reads a graph of any format it is handed",
     edit("ddw/scripts/validate-transition.py",
          "        if major != GRAPH_FORMAT_MAJOR:", "        if False:")),
    ("the graph loses the format version a program needs to detect an old one",
     json_edit("ddw/rules/transition-graph.json", lambda d: d.pop("format_version", None))),
    # The licence is stated in a file humans read and in manifests machines
    # read, and only the second kind reaches a registry or an installer. Three
    # ways they can stop agreeing: the manifest, the prose, and the grant that
    # both of them are supposed to be copying.
    ("a manifest tells the registry the work is unlicensed",
     json_edit("package.json", lambda d: d.update({"license": "UNLICENSED"}))),
    ("the README stops naming the licence the repository grants",
     edit("README.md",
          "[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)",
          "[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)")),
    # The heading, which is the one occurrence that says what the grant IS. The
    # boilerplate below names Apache throughout, so a check reading the whole
    # file agrees with a LICENSE that was replaced.
    ("LICENSE is swapped for a grant nothing else in the repo mentions",
     edit("LICENSE", "                                 Apache License",
          "                              Mozilla Public License")),

    ("an issue form is malformed, so GitHub silently stops showing it",
     edit(".github/ISSUE_TEMPLATE/bug.yml", "name: 🐛 Bug", "name: [🐛 Bug")),
    ("nothing routes a vulnerability away from the public issue tracker",
     edit(".github/ISSUE_TEMPLATE/config.yml", "security/advisories/new", "issues/new")),
    ("the code of conduct disappears",
     delete("CODE_OF_CONDUCT.md")),
    ("the AI policy disappears from a repo whose prose becomes other people's prompts",
     delete("docs/AI-POLICY.md")),
    # The defect that actually shipped: the manifest NAMING the agents. It
    # validates, it reads right, and it loads zero components — while the same
    # files load fine when the manifest says nothing and the default scan finds
    # them.
    ("the manifest declares agents again, and they silently stop loading",
     json_edit(".claude-plugin/plugin.json",
               lambda d: d.update({"agents": ["./agents/ddw-arch-auditor.md"]}))),
    ("the agents move out of the directory the tool scans",
     delete("agents")),
    ("a foreign dialect lands in Claude's hooks file, which discards it whole",
     json_edit("adapters/claude/plugin-hooks.json",
               lambda d: d["hooks"].update({"BeforeTool": d["hooks"]["PreToolUse"]}))),
    ("a hook command points at a variable Claude never expands",
     edit("adapters/claude/plugin-hooks.json",
          "${CLAUDE_PLUGIN_ROOT}/adapters/claude/hooks/session-start.sh",
          "${extensionPath}/adapters/claude/hooks/session-start.sh")),
    ("the plugin stops naming its hook file and trusts a default it shares",
     json_edit(".claude-plugin/plugin.json", lambda d: d.pop("hooks", None))),
    ("Gemini's hooks stop resolving from its own extension path",
     edit("adapters/gemini/extension-hooks.json", "${extensionPath}/adapters/gemini/hooks/session-start.sh",
          "./adapters/gemini/hooks/session-start.sh")),
    # ── One product, one number ──────────────────────────────────────────────
    ("a shipped change can go out on the version that came before it",
     edit("scripts/check_versions.py",
          "            touched = sorted(f for f in changed.split() if f.startswith(SHIPPED))",
          "            touched = []")),
    ("five manifests can say one version and the sixth another",
     edit("scripts/check_versions.py",
          "    for rel in PRODUCT_MANIFESTS[1:]:",
          "    for rel in []:")),
    # The failure that hid for the whole life of the repository: a step whose
    # first command cannot run, on the only event that reaches it.
    ("CI's pull-request fetch goes back to a depth git refuses",
     edit(".github/workflows/verify.yml",
          'git fetch --no-tags origin "+refs/heads/${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"',
          'git fetch --no-tags --depth=0 origin "${{ github.base_ref }}"')),

    ("the version rule goes back to applying on pull requests alone",
     edit(".github/workflows/verify.yml",
          "          elif git rev-parse --verify -q HEAD~1 >/dev/null; then\n"
          "            python3 scripts/check_versions.py --since HEAD~1\n",
          "")),
    ("another tool's hook file comes back to the path Claude scans on sight",
     copy_to("adapters/gemini/extension-hooks.json", "hooks/hooks.json")),
    ("the marketplace that makes the plugin installable disappears",
     delete(".claude-plugin/marketplace.json")),
    # Cursor and Codex find components by the same default scan Claude uses, so
    # what breaks them is a path that is not there — never a missing key.
    ("a non-Claude plugin manifest names a component path this repo does not have",
     json_edit(".cursor-plugin/plugin.json", lambda d: d.update({"skills": "./cursor-skills/"}))),
    # The schema is what a seventh tool's recipe gets written from. A field it
    # does not name is a capability that exists and cannot be found.
    ("the schema stops documenting a field the installer honours",
     edit("adapters/adapter.schema.md", "| `skills_are_slash` | no |",
          "| `skills_are_slash_UNDOCUMENTED` | no |")),
    ("a recipe grows a field the schema was never told about",
     json_edit("adapters/claude/adapter.json",
               lambda d: d.update({"post_install_note": "anything"}))),
    # Written for a human comparing install routes, read by the agent already
    # running the plugin — which then runs install.sh in the user's repo.
    ("a plugin's own description sends its reader off to run the installer",
     json_edit(".claude-plugin/plugin.json",
               lambda d: d.update({"description": d["description"] +
                                   " Plugin packaging is still in progress — install with install.sh for now."}))),
    ("the marketplace entry picks up the same redirect",
     json_edit(".claude-plugin/marketplace.json",
               lambda d: d["plugins"][0].update({"description": d["plugins"][0]["description"] +
                                                 " Use the installer instead."}))),

    # ── The method, found from wherever it lives ─────────────────────────────
    ("session-start goes back to looking for the method only in the repo",
     edit("adapters/claude/hooks/session-start.sh",
          'DDW="$(ddw_method)" || exit 0', 'DDW="${CLAUDE_PROJECT_DIR}/.ddw"')),
    ("the boot nudge names a relative .ddw/ that a plugin install does not have",
     edit("ddw/scripts/session-boot.py",
          "    orch = os.path.join(method, \"orchestrator.md\")",
          "    orch = \".ddw/orchestrator.md\"")),
    ("merely opening a repo under a plugin starts writing files into it",
     edit("ddw/scripts/session-boot.py",
          "    started = dropped_in or os.path.exists(os.path.join(repo, \".ddw-state.json\"))",
          "    started = True")),
    ("a drop-in stops materialising its state, regressing every existing install",
     edit("ddw/scripts/session-boot.py",
          "    started = dropped_in or os.path.exists(os.path.join(repo, \".ddw-state.json\"))",
          "    started = False")),
    # A plugin manifest is data the tool resolves elsewhere, so a wrong path is
    # never an error anyone sees — the hook is simply never run. These four each
    # break one link of the plugin chain: the path, the two ways a hook can find
    # the method, and the pointer that tells the model where the method is.
    ("a plugin manifest points back at the drop-in's directory layout",
     edit("adapters/codex/plugin-hooks.json",
          "/adapters/codex/hooks/session-start.sh",
          "/adapters/codex/hooks/ddw/session-start.sh")),
    ("a hook that runs through a shell stops reading the root its manifest exports",
     edit("adapters/gemini/hooks/pre-tool-use.sh",
          'PLUGIN_ROOT="${DDW_PLUGIN_ROOT:-}"', 'PLUGIN_ROOT=""')),
    ("a hook the tool executes directly stops reading the tool's own root",
     edit("adapters/cursor/hooks/pre-tool-use.sh",
          'PLUGIN_ROOT="${DDW_PLUGIN_ROOT:-${CURSOR_PLUGIN_ROOT:-}}"', 'PLUGIN_ROOT=""')),
    ("a plugin boot goes back to naming an orchestrator the repo does not have",
     edit("adapters/codex/hooks/session-start.sh",
          ' --format nested --method "$DDW"', ' --format nested')),

    # ── Reads judged as writes ───────────────────────────────────────────────
    ("every tool is judged as a write again, so the agent cannot read",
     edit("ddw/scripts/validate-transition.py",
          "        if not writing:\n            continue                      # a read cannot violate a write rule\n",
          "")),
    ("the raw tool name stops reaching the decision, so every read is an edit again",
     edit("ddw/scripts/hook-gate.py",
          "                               repo=args.repo, raw_tool=raw_name, method=args.method)",
          "                               repo=args.repo, method=args.method)")),
    # The one that shipped: asking "is this a write?" and letting an unrecognised
    # tool through as a read.
    ("unknown tools go back to being read as reads, and walk past the guard",
     edit("ddw/scripts/validate-transition.py",
          "    writing = payload_writes or not reading",
          "    writing = payload_writes and not reading")),
    ("a viewer stops being recognised, so the agent cannot read",
     edit("ddw/scripts/validate-transition.py",
          'READ_VERBS = ("read", "view", "list", "ls", "cat", "search", "grep", "glob",',
          'READ_VERBS = ("nothing_matches",  # was: "read", "view", "list", "ls", "cat",')),
    ("the payload stops overruling a read-sounding name",
     edit("ddw/scripts/validate-transition.py",
          "    writing = payload_writes or not reading",
          "    writing = not reading")),

    # ── The post net's channel ───────────────────────────────────────────────
    ("Copilot is sent a refusal its post hook ignores",
     edit("ddw/scripts/hook-gate.py", 'POST_CANNOT_BLOCK = {"copilot"}',
          "POST_CANNOT_BLOCK = set()")),
    ("the report drops the instruction to stop, so the model reads it and carries on",
     edit("ddw/scripts/hook-gate.py",
          '"\\n\\nSTOP. Do not continue the pipeline, do not repair the state, and do not delete it. "',
          '"\\n\\nNoted. Carry on. "')),

    # ── A corrupt state is an incident, not a chore ──────────────────────────
    ("pre stops enforcing the ticket, so post condemns what pre let in",
     edit("ddw/scripts/validate-transition.py",
          "    _check_ticket_continuity(old_state, new_state)\n", "")),
    ("the ticket may change mid-run as long as it is not IDLE",
     edit("ddw/scripts/validate-transition.py",
          "    if new_t is None or new_state.get(\"phase\", IDLE) == IDLE:\n        return",
          "    return")),
    ("the state stops being journalled, so deleting it works again",
     edit("ddw/scripts/validate-transition.py",
          "    record_journal(state_path)\n", "")),
    ("a deleted state reads as a clean start again",
     edit("ddw/scripts/validate-transition.py",
          "    _check_state_not_erased(state_path)\n    if not os.path.exists(state_path):\n"
          "        return \"\", _idle_template()",
          "    if not os.path.exists(state_path):\n        return \"\", _idle_template()")),
    ("a shorter history passes as a simpler run",
     edit("ddw/scripts/validate-transition.py",
          "    if len(history) < len(seen):", "    if False:")),
    ("the refusal goes back to ordering a repair the graph forbids",
     edit("ddw/scripts/hook-gate.py",
          '"\\n\\nSTOP. Do not continue the pipeline, do not repair the state, and do not delete it. "',
          '"\\n\\nFix the state and redo the transition with the write tool. "')),
    ("the finding is repeated in full on every tool call",
     edit("ddw/scripts/hook-gate.py",
          "            if already_reported(args.state, reason):", "            if False:")),
    ("the split protocol goes back to retargeting the header",
     edit("ddw/rules/define.instructions.md",
          "**4. Close the parent run, then open sub-ticket `a` as its own run:**",
          "**4. Update `.ddw-state.json`: `ticket` -> `{TICKET}a`:**")),

    # ── The entry point ──────────────────────────────────────────────────────
    ("OpenCode stops generating commands while the installer still promises them",
     json_edit("adapters/opencode/adapter.json", lambda d: d.pop("commands"))),
    ("the commands land in the singular directory the docs do not use",
     json_edit("adapters/opencode/adapter.json",
               lambda d: d["commands"].update({"dir": ".opencode/command"}))),
    ("a generated command carries the skill's body instead of pointing at it",
     edit("scripts/install_target.py",
          'body = render(cmd["body"], {"name": name, "description": description})',
          'body = open(skill_md, encoding="utf-8").read()')),
    ("the installer goes back to promising /ddw-status to every tool",
     edit("install.sh",
          'echo "  The \\"try:\\" line above shows how to call DDW by hand in your tool."',
          'echo "  Commands: /ddw-status, /ddw-help."')),

    # ── The ticket a gate is earned for ──────────────────────────────────────
    ("clearing the ticket opens the six receipt gates again",
     edit("ddw/scripts/validate-transition.py",
          "    if claimed:\n        raise Block(", "    if False:\n        raise Block(")),
    ("the rule stops knowing which gates rest on a receipt",
     edit("ddw/scripts/validate-transition.py",
          'RECEIPT_GATES = ("define", "spec", "threat", "tests", "sast", "verify")',
          "RECEIPT_GATES = ()")),
    ("the invariant is written and never called",
     edit("ddw/scripts/validate-transition.py",
          "    _check_gates_have_a_ticket(new_state)\n", "")),
    ("the helper cannot name the ticket it is earning gates for",
     edit("ddw/scripts/transition.py",
          "        if ticket is not None:\n            new_state[\"ticket\"] = ticket",
          "        if False:\n            new_state[\"ticket\"] = ticket")),
    ("history entries go back to being unattributable",
     edit("ddw/scripts/transition.py",
          '    if run_ticket:\n        entry["ticket"] = run_ticket',
          '    if False:\n        entry["ticket"] = run_ticket')),

    # ── The gate turned on with no transition to declare it ──────────────────
    ("a gate flipped on disk stops being compared to the last blessed snapshot",
     edit("ddw/scripts/validate-transition.py",
          "    if snapshot is not None:\n        owed.extend(_gates_newly_claimed({\"gates\": snapshot}, disk_state))",
          "    if False:\n        owed.extend(_gates_newly_claimed({\"gates\": snapshot}, disk_state))")),
    ("the snapshot is never recorded, so there is nothing to compare against",
     edit("ddw/scripts/validate-transition.py",
          "            if last != held:", "            if False:")),
    ("snapshot lines are counted as transitions, sliding the index that finds what landed",
     edit("ddw/scripts/validate-transition.py",
          '    entries, out = [e for e in _journal_lines(state_path)\n'
          '                    if isinstance(e, dict) and "from" in e and "to" in e], []',
          "    entries, out = _journal_lines(state_path), []")),
    ("post mode judges the autonomy change against the first edge of the replay again",
     edit("ddw/scripts/validate-transition.py",
          '    touches_classify = any(e.get("from") == CLASSIFY or e.get("to") == CLASSIFY\n'
          "                           for e in appended if isinstance(e, dict))",
          '    touches_classify = bool(appended) and appended[0].get("from") == CLASSIFY')),

    ("resuming stops being a moment the mode can be chosen, so a pause loses it",
     edit("ddw/scripts/validate-transition.py",
          "    resuming = any(_is_resume(e) and e.get(\"from\") == IDLE",
          "    resuming = False and any(_is_resume(e) and e.get(\"from\") == IDLE")),
    ("the word resume on any edge grants the mode, not only on the one out of IDLE",
     edit("ddw/scripts/validate-transition.py",
          '    resuming = any(_is_resume(e) and e.get("from") == IDLE\n'
          "                   for e in appended if isinstance(e, dict))",
          "    resuming = any(_is_resume(e) for e in appended if isinstance(e, dict))")),
    ("the pause protocol stops asking which mode to come back in",
     edit("ddw/orchestrator.md",
          "3. **Ask about the mode, before restoring anything.**",
          "3. **Restore the mode silently.**")),

    # ── Pause, work on something else, come back ─────────────────────────────
    ("a pause only resumes if it was the very last thing that happened",
     edit("ddw/scripts/validate-transition.py",
          "    prior = [e for e in history[:upto] if isinstance(e, dict)]",
          "    prior = [e for e in history[:upto] if isinstance(e, dict)]\n"
          "    return prior[-1].get('from') if prior and _is_pause(prior[-1]) else None")),
    ("one pause can be resumed over and over",
     edit("ddw/scripts/validate-transition.py",
          "        if pending_resumes:\n            pending_resumes -= 1",
          "        if False:\n            pending_resumes -= 1")),
    ("another ticket's pause becomes this ticket's way back in",
     edit("ddw/scripts/validate-transition.py",
          '        if any(e.get("ticket") for e in prior):\n            prior = [e for e in prior if e.get("ticket") == ticket]',
          '        if False:\n            prior = [e for e in prior if e.get("ticket") == ticket]')),

    # ── The notice about pull requests waiting on a reviewer ─────────────────
    ("the pending-PR notice goes back to crashing on a shape it did not expect",
     edit("ddw/scripts/session-boot.py",
          "    prs = [p for p in prs if isinstance(p, dict)]\n", "")),
    ("a list gh did not return is rendered as pull requests anyway",
     edit("ddw/scripts/session-boot.py",
          "    if not isinstance(prs, list):", "    if False:")),
    ("pull requests are dropped without a word again",
     edit("ddw/scripts/session-boot.py", "    if len(prs) > SHOWN:", "    if False:")),
    ("every way gh can fail is reported as a timeout again",
     edit("ddw/scripts/session-boot.py",
          "    except subprocess.TimeoutExpired:\n        return [CANNOT + f\"the forge did not answer in {timeout}s.\"]\n"
          "    except Exception as exc:\n",
          "    except Exception as exc:\n")),
    ("git failing to read the remotes becomes silence again",
     edit("ddw/scripts/session-boot.py",
          '        if os.path.exists(os.path.join(repo, ".git")):\n            return [CANNOT + "git could not read this repo\'s remotes."]',
          "        if False:\n            return [CANNOT]")),
    ("the notice about waiting pull requests disappears from the boot",
     edit("ddw/scripts/session-boot.py",
          "            lines += awaiting_review(repo)", "            pass")),
    ("the notice goes back to calling the forge on every boot, quiet or not",
     edit("ddw/scripts/session-boot.py",
          "        if started and not args.quiet:", "        if True:")),

    # ── What the audit found still alive ─────────────────────────────────────
    # Each of these is a mutation the list did not have, on code the checks do
    # cover — which is the quieter half of a coverage figure: not a rule nobody
    # tests, but a way of breaking it nobody had written down.
    ("QUICK-FIX's step back from CLOSEOUT keeps everything it is supposed to give up",
     edit("ddw/rules/transition-graph.json",
          '      "CLOSEOUT->CODE": {\n        "gates": [],\n        "clears": [\n'
          '          "tests",\n          "sast",\n          "commit",\n          "pr"\n        ]\n      }',
          '      "CLOSEOUT->CODE": {\n        "gates": [],\n        "clears": []\n      }')),
    ("a pause is matched by bare prefix again, so `pause-the-build` is a pause",
     edit("ddw/scripts/validate-transition.py",
          '    return action.strip().lower().split(":", 1)[0].strip() in ("pause", "paused")',
          '    return action.strip().lower().startswith("pause")')),
    ("the clears rule runs against the replay's synthetic prior and bricks the repo",
     edit("ddw/scripts/validate-transition.py",
          "        still_held = [g for g in cleared if gates.get(g) is True] if check_gates else []",
          "        still_held = [g for g in cleared if gates.get(g) is True]")),
    ("the pause exception is judged against the replay's synthetic prior too",
     edit("ddw/scripts/validate-transition.py",
          '                paid = (all(gates_before.get(g) is True for g in ("commit", "pr"))\n'
          "                        if check_gates else True)",
          '                paid = all(gates_before.get(g) is True for g in ("commit", "pr"))')),

    # ── The two loop counters ────────────────────────────────────────────────
    ("the PRD template stops emitting the counter the ceiling reads",
     edit("skills/ddw-create-prd/SKILL.md",
          "| Loops since last human decision | 0 |\n", "")),
    ("the spec template stops emitting it too",
     edit("skills/ddw-create-spec/SKILL.md",
          "| Loops since last human decision | 0 |\n", "")),
    ("the two counters may disagree in the direction that loops forever",
     edit("ddw/scripts/validate_prd.py",
          "    if since is not None and since > total_loops:", "    if False:")),

    # ── DDW's own machinery, which no phase writes ───────────────────────────
    ("the pipeline can edit the rules that stop it again",
     edit("ddw/scripts/validate-transition.py",
          "        reason = enforcement_write_denied(target, root)\n        if reason:\n            return reason\n",
          "")),
    ("the method itself stops being sealed",
     edit("ddw/scripts/validate-transition.py",
          'PROTECTED_PREFIXES = (".ddw/", ".ddw-sessions/")',
          "PROTECTED_PREFIXES = ()")),
    ("the agent can write its own receipts again",
     edit("ddw/scripts/validate-transition.py",
          'PROTECTED_PREFIXES = (".ddw/", ".ddw-sessions/")',
          'PROTECTED_PREFIXES = (".ddw/",)')),
    ("what wires the gates into the tool becomes writable",
     edit("ddw/scripts/validate-transition.py",
          '    ".claude/settings.json", ".codex/hooks.json",\n'
          '    ".cursor/hooks.json", ".gemini/settings.json",\n',
          "")),
    ("the installed hook scripts stop being protected",
     edit("ddw/scripts/validate-transition.py",
          "    elif rel in _manifest_paths(root):", "    elif False:")),
    ("the manifest goes back to naming files that are not there",
     edit("scripts/install_target.py",
          "            rel = f\"{args.id}:{spec['dir']}/{out_name}\"",
          '            rel = f"{args.id}:agents/{out_name}"')),
    ("a tampered install stops being reported at boot",
     edit("ddw/scripts/session-boot.py",
          "    lines += enforcement_drift(repo)\n", "")),
    ("the drift report stops noticing a file that changed",
     edit("ddw/scripts/session-boot.py",
          "        elif actual != digest:\n            changed.append(rel)",
          "        elif False:\n            changed.append(rel)")),
    ("the drift report stops noticing a file that is gone",
     edit("ddw/scripts/session-boot.py",
          "        if actual is None:\n            gone.append(rel)",
          "        if False:\n            gone.append(rel)")),

    # ── A gate claimed for a document that is not there ──────────────────────
    ("a missing artifact goes back to meaning there is nothing to check",
     edit("ddw/scripts/validate-transition.py",
          '        where = tried[0] if len(tried) == 1 else " or ".join("`%s`" % t for t in tried)',
          "        return None\n        where = tried[0] if len(tried) == 1 else \" or \".join(\"`%s`\" % t for t in tried)")),
    ("a document nothing can decode opens its gate again",
     edit("ddw/scripts/validate-transition.py",
          "    except (OSError, UnicodeDecodeError) as exc:",
          "    except (OSError, UnicodeDecodeError) as exc:\n        return None")),
    ("a directory named like the document ends the search for it",
     edit("ddw/scripts/validate-transition.py",
          "        if os.path.isfile(cand):", "        if os.path.exists(cand):")),

    # ── What the pre-merge audit found ──────────────────────────────────────
    ("the helper reads a corrupt state as a fresh IDLE and writes over it",
     edit("ddw/scripts/transition.py",
          "        old_text, old_state = vt._read_state_or_refuse(args.state)",
          "        old_text, old_state = vt._load_disk_state(args.state)")),
    ("installing a second tool treats the user's own hooks as DDW's to replace",
     edit("scripts/install_target.py",
          "    had_manifest = (any(isinstance(k, str) and k.startswith(args.id + \":\") for k in manifest)\n"
          "                    and not recorded_wiring)",
          "    had_manifest = bool(manifest) and not recorded_wiring")),
    ("a check that did not run is summed into the green total again",
     edit("scripts/verify_install.sh",
          "skip() { CHECKS=$((CHECKS+1)); SKIPS=$((SKIPS+1));",
          "skip() { CHECKS=$((CHECKS+1));")),
    ("CI stops running the suite, and every required context stays green",
     edit(".github/workflows/verify.yml",
          "      - name: The suite\n        run: bash scripts/verify_install.sh",
          "      - name: The suite\n        run: echo skipped")),
    ("CI swallows the linter's failure",
     edit(".github/workflows/verify.yml",
          "      - name: The prose agrees with the machine\n        run: python3 scripts/lint_method.py",
          "      - name: The prose agrees with the machine\n        run: python3 scripts/lint_method.py || true")),
    ("CI stops installing the CLI the manifest checks need, so they skip",
     edit(".github/workflows/verify.yml",
          "          npm install -g @anthropic-ai/claude-code",
          "          true")),
    ("a mutation shard's failure stops failing the workflow",
     edit(".github/workflows/mutations.yml",
          '      - run: |\n        if [ "${{ github.event_name }}" = "pull_request" ]; then'.replace(
              "        if", "          if"),
          '      - continue-on-error: true\n        run: |\n'
          '          if [ "${{ github.event_name }}" = "pull_request" ]; then')),
    ("a gate reads one document path and its skill documents another",
     edit("skills/ddw-security-sast/SKILL.md",
          "docs/ddw/security/sast-", "docs/ddw/sast/sast-")),
    ("a skill points at a validator that is not the one the gate runs",
     edit("skills/ddw-test/SKILL.md", "validate_tests.py", "validate_test.py")),

    # ── Catalogued rules nothing had ever broken on purpose ─────────────────
    ("an FR that no acceptance criterion validates stops being noticed",
     edit("ddw/scripts/validate_prd.py",
          "        orphans = [i for i, _ in frs if i not in ac_text]", "        orphans = []")),
    ("an NFR with no number passes as a measured requirement",
     edit("ddw/scripts/validate_prd.py",
          '        unmetered = [i for i, t in nfrs if not re.search(r"\\d", _after_id(i, t))]',
          "        unmetered = []")),
    ("the rule that wants a number goes back to finding it in the label",
     edit("ddw/scripts/validate_prd.py", "_after_id(i, t))]", "t)]")),
    ("an acceptance criterion in free prose stops needing EARS",
     edit("ddw/scripts/validate_prd.py",
          "        non_ears = [i for i, t in acs if not EARS.search(t)]", "        non_ears = []")),
    ("an FR the spec covers nowhere stops being noticed",
     edit("ddw/scripts/validate_spec.py",
          '        uncovered = [i for i in frs if not re.search(r"\\b%s\\b" % i, text)]',
          "        uncovered = []")),
    ("an acceptance criterion named by no test stops being noticed",
     edit("ddw/scripts/validate_spec.py",
          '        untested = [i for i in acs if not re.search(r"\\b%s\\b" % i, tests_text)]',
          "        untested = []")),
    ("a threat with neither mitigation nor accepted risk passes",
     edit("ddw/scripts/validate_threat.py",
          "        untreated = [r[0] for r in risks", "        untreated = [] or [r[0] for r in []")),
    ("an acceptance criterion the verdict never mentions passes verification",
     edit("ddw/scripts/validate_verify.py",
          "    unmentioned = [a for a in acs", "    unmentioned = [] or [a for a in []")),

    # ── The validator's own internals ───────────────────────────────────────
    # There was a second "the session id is not sanitised" entry here. It
    # injected `def safe_id_UNUSED(` with no body, so the file stopped parsing:
    # every check died on the import, the run recorded a kill, and the defect it
    # named was never in the tree. The class is covered by the entry above, which
    # removes the sanitising and leaves the file compiling. `--check-anchors` now
    # refuses this shape outright, which is how both of them were found.
    ("walking away is matched by bare prefix again",
     edit("ddw/scripts/validate-transition.py",
          '    first = action.strip().lower().split(":", 1)[0].strip()\n'
          '    return first in ("abandon", "abandoned", "pause", "paused")',
          '    return action.strip().lower().startswith(("abandon", "pause"))')),
    ("an Edit that matches many places stops needing replace_all",
     edit("ddw/scripts/validate-transition.py",
          '        if n > 1 and not bool(tool_input.get("replace_all", False)):',
          "        if False:")),
    ("a tool nobody mapped writes the state unexamined",
     edit("ddw/scripts/validate-transition.py",
          '    raise Block(f"tool {tool_name!r} is not supported',
          '    return old_text\n    raise Block(f"tool {tool_name!r} is not supported')),
    ("the pr gate goes back to `gh pr view`, where a branch named 123 is PR #123",
     edit("ddw/scripts/validate-transition.py",
          '        out = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "all",\n'
          '                              "--json", "number,state"],',
          '        out = subprocess.run(["gh", "pr", "view", branch,\n'
          '                              "--json", "number,state"],')),
    ("the tier chain is walked the wrong way, so a child cannot override its parent",
     edit("ddw/scripts/validate-transition.py",
          "    for name in reversed(chain):", "    for name in chain:")),

    # ── The linter that runs in CI and had no mutation at all ───────────────
    ("a skill referenced by name that does not exist stops being caught",
     edit("scripts/lint_method.py", "            if m.group(1) not in skills:", "            if False:")),

    # ── What the pre-merge audit found, second batch ────────────────────────
    ("the self-check reports a healthy install as broken again",
     edit("skills/ddw-self-check/SKILL.md",
          'for f in CLAUDE.md AGENTS.md GEMINI.md; do\n  [ -f "$ROOT/$f" ] && grep -qF "BEGIN DDW" "$ROOT/$f" && found=1\ndone',
          'grep -lqF "BEGIN DDW" "$ROOT"/CLAUDE.md "$ROOT"/AGENTS.md "$ROOT"/GEMINI.md 2>/dev/null || found=0')),
    ("uninstall goes back to leaving every generated slash command behind",
     edit("scripts/uninstall_repo.py",
          'if kind not in ("skills", "agents", "commands") or not name:',
          'if kind not in ("skills", "agents") or not name:')),
    ("uninstall deletes the manifest that --force needs to find your files",
     edit("scripts/uninstall_repo.py",
          "    if os.path.exists(mpath) and not kept:", "    if os.path.exists(mpath):")),
    ("a file you edited is removed without --force",
     edit("scripts/uninstall_repo.py",
          "        if fingerprint(path) != recorded and not args.force:",
          "        if False:")),
    ("the linter stops reading the skills and agents that name skills and agents",
     edit("scripts/lint_method.py",
          '    return (sorted(glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True))\n'
          '            + sorted(glob.glob(os.path.join(root, "skills/*/SKILL.md")))\n'
          '            + sorted(glob.glob(os.path.join(root, "agents/*.md"))))',
          '    return sorted(glob.glob(os.path.join(root, "ddw/**/*.md"), recursive=True))')),
    ("a rule ID whose suffix is a word stops having to be catalogued",
     edit("scripts/lint_method.py",
          'pattern = re.compile(r"\\b([FW]-[A-Z]+-[A-Z0-9]{2,})\\b")',
          'pattern = re.compile(r"\\b([FW]-[A-Z]+-\\d{2,})\\b")')),
    ("the trust_note check goes back to a loop that can iterate zero times",
     edit("scripts/verify_install.sh",
          "assert checked >= 2,", "assert True or checked >= 2,")),
    ("a mutation job that never runs still reports full coverage",
     edit("scripts/mutate.py",
          '        if cond is not None and str(cond).strip().lower() not in ("true", "${{ true }}"):',
          "        if False:", last=True)),
    ("injecting the same mutation twice still reads as each exactly once",
     edit("scripts/mutate.py",
          "    twice = sorted(i for i, c in counted.items() if c > 1)", "    twice = []",
          last=True)),

    ("the helper cannot claim a gate in the phase that owns it",
     edit("ddw/scripts/transition.py", "    if args.claim:", "    if False:")),
    ("--gate on the closing edge is silently dropped again",
     edit("ddw/scripts/transition.py",
          '    if args.to == "IDLE" and args.gate:', "    if False:")),
    ("the refusal on the closing edge blames the tier again",
     edit("ddw/scripts/transition.py", '        elif args.to == "IDLE":', "        elif False:")),
    ("the helper answers an unexpected fault with a traceback and exit 1",
     edit("ddw/scripts/transition.py",
          '    except Exception as exc:                      # noqa: BLE001 — the point is breadth',
          "    except Exception as exc:\n        raise\n    except BaseException as exc:")),

    # ── The last batch the audit named ──────────────────────────────────────
    ("a selection that matches no mutation reports success again",
     edit("scripts/mutate.py",
          '        raise SystemExit("the selection matched no mutation — nothing was injected, and a run "',
          '        pass\n    if False:\n        raise SystemExit("the selection matched no mutation — nothing was injected, and a run "',
          last=True)),
    ("install.sh looks for the manifest in one place again, so upgrades re-ask",
     edit("install.sh",
          'for rel in (".ddw-installed.json", os.path.join(".ddw", ".installed.json")):',
          'for rel in (".ddw-installed.json",):')),
    ("uninstall leaves behind the empty .gitignore the install created",
     edit("scripts/uninstall_repo.py",
          "            if not out.strip():\n                removed.append(\".gitignore\")",
          "            if False:\n                removed.append(\".gitignore\")")),
    ("the hooks claim to fail open where they fail closed",
     edit("adapters/claude/hooks/validate-state-transition.sh",
          "# Without python3 there is nothing to validate with, so this fails CLOSED (exit 2):",
          "# Without python3 there is nothing to validate with. Explicit fail-open (exit 0).")),
    ("the release workflow stops running the suite before it publishes",
     edit(".github/workflows/release.yml", "scripts/verify_install.sh", "true # scripts/verify_install.sh")),
    ("a skill's whole protocol is replaced by a placeholder",
     edit("skills/ddw-help/SKILL.md", "/ddw-self-check", "/ddw-selfcheck")),
    ("the commit template teaches the trailer this repo refuses",
     edit("skills/ddw-commit/SKILL.md", "AI-assisted: yes",
          "Co-Authored-By: Claude <noreply@anthropic.com>")),
    ("the method resolves to the plugin even when the repo has its own copy",
     edit("adapters/claude/hooks/lib/guard.sh", "ddw_method() {",
          'ddw_method() {\n  [ -n "$CLAUDE_PLUGIN_ROOT" ] && [ -d "$CLAUDE_PLUGIN_ROOT/ddw" ] && { printf %s "$CLAUDE_PLUGIN_ROOT/ddw"; return 0; }')),
    ("the re-validation rule is checked for a hand-typed subset of the gates again",
     edit("scripts/verify_install.sh",
          "print(\" \".join(GATE_SKILL[g] for g in\n                dict.fromkeys(",
          'print("ddw-validate-prd ddw-validate-spec ddw-threat-modeling ddw-verify-module") or (lambda *a: None)(')),

    ("the validation skills are checked from a hand-typed list again",
     edit("scripts/verify_install.sh",
          "print(\" \".join(GATE_SKILL[g] for g in",
          'print("ddw-validate-prd ddw-validate-spec") or (lambda *a: None)(')),

    # ── Two hooks at once, and a ticket that outlives lunch ─────────────────
    # The lock itself has no mutation any more, and that is a statement rather
    # than an omission: with the fold below reading DISTINCT transitions, a
    # duplicate line costs bytes and nothing else, so removing `_lock` is an
    # equivalent mutant — it cannot change an answer the suite can ask for. What
    # the lock still buys is the duplicate never being written; what the fold
    # buys is that one written anyway changes nothing. The second is the one a
    # check can hold, so the second is the one measured.
    ("the pre-write hook identifies the session by its own pid again",
     edit("adapters/claude/hooks/enforce.sh",
          '--session-id "$SID" --quiet', '--session-id "pid-$$" --quiet')),
    ("a session id nobody supplied is invented from the process id",
     edit("ddw/scripts/session-boot.py",
          '    session_id = safe_id(args.session_id) if args.session_id else ""',
          '    session_id = safe_id(args.session_id or f"pid-{os.getpid()}")')),
    ("the gate refusal goes back to naming the fact and not the move",
     edit("ddw/scripts/validate-transition.py",
          "is not true.{how}", "is not true")),
    ("a malformed self-edge stops naming the one entry the history accepts",
     edit("ddw/scripts/validate-transition.py",
          "The one in-phase entry the history ", "")),
    ("the phase mismatch names two phases and no way back",
     edit("ddw/scripts/validate-transition.py",
          "History is appended to what is ON DISK: re-read ", "")),
    ("every install calls itself an update, in a repo that never had DDW",
     edit("install.sh", 'if [ -n "$INSTALLED" ]; then', "if true; then")),
    ("the coverage rule reads only the long metric names, so a coverage table is 'missing'",
     edit("ddw/scripts/validate_tests.py",
          '"Cobertura de l[i\u00ed]neas", "Lines", "Line")',
          '"Cobertura de l[i\u00ed]neas", "Lines")')),
    ("the lint result is only seen on one line, never under its own heading",
     edit("ddw/scripts/validate_tests.py",
          '        m = re.search(r"^#{1,6}',
          '        m = None or re.search(r"^NEVERMATCHES#{1,6}')),
    ("CLASSIFY loses the branch for a repo that has no context file at all",
     edit("ddw/rules/classify.instructions.md",
          "3. **If `AGENTS.md` does not exist at all**", "3. **If AGENTS.md is somewhere else**")),
    ("the codex compaction nudge goes back to an envelope codex does not read",
     edit("adapters/codex/hooks/pre-compact.sh",
          "  --format nested --event PreCompact", "  --format text --event PreCompact")),
    ("the root walk asks whether .git is a directory again, so a worktree has no root",
     edit("ddw/scripts/transition.py",
          'or os.path.exists(os.path.join(cur, ".git")):',
          'or os.path.isdir(os.path.join(cur, ".git")):')),
    ("a validator crashes on the counterpart document it finds by itself",
     edit("ddw/scripts/validate_spec.py",
          "            prd_text = open(prd_path, encoding=\"utf-8\").read()\n        except (OSError, UnicodeDecodeError):",
          "            prd_text = open(prd_path, encoding=\"utf-8\").read()\n        except OSError:")),
    ("the method linter answers a file it cannot decode with a stack",
     edit("scripts/lint_method.py",
          "    except (OSError, UnicodeDecodeError) as exc:\n        fail(path, \"could not be read as UTF-8",
          "    except OSError as exc:\n        fail(path, \"could not be read as UTF-8")),
    ("the uninstaller trusts the shape of the settings file it un-merges from",
     edit("scripts/uninstall_repo.py",
          "        if not isinstance(dst.get(key), dict):\n            continue\n", "")),
    ("the uninstaller rewrites a hooks event that is not a list, one character per element",
     edit("scripts/uninstall_repo.py",
          "            if not isinstance(dst[key][event], list):\n                continue\n", "")),
    ("the uninstaller rewrites a context file it could not decode",
     edit("scripts/uninstall_repo.py",
          "        except (OSError, UnicodeDecodeError):", "        except OSError:")),
    ("the installer merges into a settings.json of any shape and crashes on the odd ones",
     edit("scripts/install_target.py",
          "                if not isinstance(dst, dict):", "                if False:")),
    ("the installer trusts that a settings event holds a list",
     edit("scripts/install_target.py",
          "                if not isinstance(cur, list):", "                if False:")),
    ("the installer reads a context file it cannot decode and rewrites it anyway",
     edit("scripts/install_target.py",
          "        except (OSError, UnicodeDecodeError) as exc:", "        except OSError as exc:")),
    ("deleting the journal turns the receipt-witness check off again",
     edit("ddw/scripts/validate-transition.py",
          "        return set() if started else None", "        return None")),
    ("a journal line written twice reads as a history entry deleted once",
     edit("ddw/scripts/validate-transition.py",
          "        if any(_same_entry(prev, entry) for prev in out):\n            continue",
          "        if False:\n            continue")),
    ("only NEIGHBOURING duplicate journal lines are folded, which is not the shape a race makes",
     edit("ddw/scripts/validate-transition.py",
          "        if any(_same_entry(prev, entry) for prev in out):",
          "        if out and _same_entry(out[-1], entry):")),
    ("the session sweep shares a directory with the evidence again",
     edit("ddw/scripts/session-boot.py",
          'sess_dir = os.path.join(repo, ".ddw-sessions", "live")',
          'sess_dir = os.path.join(repo, ".ddw-sessions")')),

    # ── The tiers that are not FEATURE ──────────────────────────────────────
    ("the define gate looks only for a PRD, so QUICK-FIX cannot leave DEFINE",
     edit("ddw/scripts/validate-transition.py",
          '    return _receipt_missing(root, state, "define", "prd", "prd", ("prd", "fix"),',
          '    return _receipt_missing(root, state, "define", "prd", "prd", ("prd",),')),
    ("the define gate forgets the FIX tier's root cause analysis",
     edit("ddw/scripts/validate-transition.py",
          '    if (state.get("tier") or "") == "FIX":', "    if False:")),
    ("the PRD template stops naming the FR each criterion validates",
     edit("skills/ddw-create-prd/SKILL.md",
          "- AC-01 (FR-01): WHEN [trigger], THE [system] SHALL [response].",
          "- AC-01: WHEN [trigger], THE [system] SHALL [response].")),

    # ── The guards that were widest where they were least likely to bite ────
    ("the QUICK-FIX sensitive-path guard is case-sensitive again",
     edit("ddw/scripts/validate-transition.py",
          '    probe = "/" + rel.lower()', '    probe = "/" + rel')),
    ("the closing edge stops owing the evidence it spends",
     edit("ddw/scripts/validate-transition.py",
          "        if len(_nh) > len(_oh):", "        if False:")),
    ("uninstall follows a manifest entry out of the repository",
     edit("scripts/uninstall_repo.py",
          "                or os.path.commonpath([real, repo_real]) != repo_real\n", "")),

    ("an update stops being asked where it lands, and commits the framework onto the branch of "
     "whatever ticket was open",
     edit("install.sh",
          'if git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1 \\\n   && { [ -n "${DDW_GIT_FLOW:-}" ] || have_tty; }; then',
          'if [ -z "$INSTALLED" ] && git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1 \\\n   && { [ -n "${DDW_GIT_FLOW:-}" ] || have_tty; }; then')),
    ("an update's commit calls itself an install, and the log says the wrong thing about every "
     "refresh",
     edit("install.sh",
          '  [ -n "$INSTALLED" ] && DDW_COMMIT_MSG="🔧 chore(ddw): update DDW to v${VERSION:-?} (drop-in)"\n',
          "")),
    ("a refresh that writes nothing strands you on the empty setup branch it made for the commit "
     "it never wrote",
     edit("install.sh",
          '    if git -C "$TARGET" checkout -q "$CURBRANCH" 2>/dev/null; then',
          "    if false; then")),
    ("the standing commit offer goes back to a bare sha: no branch named, no word that the remote "
     "does not have it",
     edit("install.sh",
          '            echo "  ✓ Committed on $(git -C "$TARGET" rev-parse --abbrev-ref HEAD 2>/dev/null || echo \'?\'): $N_PATHS path(s) ($(git -C "$TARGET" rev-parse --short HEAD))"\n            ddw_warn_unpushed',
          '            echo "  ✓ Installation committed: $(git -C "$TARGET" rev-parse --short HEAD)"')),
    ("the setup branch stops being six hex characters, so the name the installer offers is not the "
     "name it makes",
     edit("install.sh",
          "import secrets; print(secrets.token_hex(3))",
          "import secrets; print(secrets.token_hex(8))")),
    ("the setup branch goes back to a constant that merely looks random, and the second install "
     "collides with the first",
     edit("install.sh",
          "import secrets; print(secrets.token_hex(3))",
          "print('abc123')")),
    ("the installer crashes on a context file that mentions the marker in prose",
     edit("scripts/install_target.py",
          '        if "<!-- BEGIN DDW" in existing:', '        if "BEGIN DDW" in existing:')),
    ("the session boot answers an unexpected fault with a stack",
     edit("ddw/scripts/session-boot.py",
          "    except BaseException as exc:                  # noqa: BLE001 — breadth is the point",
          "    except OSError as exc:")),
    ("the uninstaller cannot run against a manifest shaped unexpectedly",
     edit("scripts/uninstall_repo.py",
          "        if not isinstance(manifest, dict):\n            manifest = {}",
          "        if False:\n            manifest = {}")),
    ("a validator exits 1 with a stack on a document that is not UTF-8",
     edit("ddw/scripts/validate_prd.py",
          "    except (OSError, UnicodeDecodeError) as exc:", "    except OSError as exc:")),
    ("one write skips the phase that classifies the work",
     edit("ddw/scripts/validate-transition.py",
          "    if first_from != old_phase:",
          "    if first_from != old_phase and not (old_phase == IDLE and first_from == CLASSIFY):")),
    ("an upgrade mid-ticket strands the open ticket again",
     edit("ddw/scripts/validate-transition.py",
          "        if key not in edges and idx >= skip_edges:", "        if key not in edges:")),
    ("the blessed window is widened to the whole run",
     edit("ddw/scripts/validate-transition.py",
          "             skip_edges=max(0, blessed - start))", "             skip_edges=10**9)")),

    # ── The payload ──────────────────────────────────────────────────────────
    ("a skill disappears", delete("skills/ddw-commit")),
    ("an agent disappears", delete("agents/ddw-sec-auditor.md")),
    ("a rule file disappears", delete("ddw/rules/code.instructions.md")),
    ("an adapter recipe points at a directory that is not there",
     json_edit("adapters/claude/adapter.json",
               lambda d: d["skills"].update({"dir": ".claude/nope"}))),
    ("the ticket is the one header field whose type nothing checks again",
     edit("ddw/scripts/validate-transition.py",
          "    _check_ticket_shape(new_state)\n", "")),
    ("the SAST skill sends every tier to VERIFY again",
     edit("skills/ddw-security-sast/SKILL.md",
          "the `sast` receipt is what lets a ticket leave CODE, in every tier.",
          "you cannot advance to VERIFY with open vulnerabilities.")),
    ("the CLASSIFY rules drop the ticket from the helper's command again",
     edit("ddw/rules/classify.instructions.md",
          "--to DEFINE --tier <TIER> --ticket <ID> \\", "--to DEFINE --tier <TIER> \\")),
    ("the CLASSIFY rules stop teaching --title, so the template the model copies is the one its own gate refuses",
     edit("ddw/rules/classify.instructions.md",
          '       --title "<the ticket\'s name, one line>" --action "<why this tier>"',
          '       --action "<why this tier>"')),
    ("the CLASSIFY rules open the ticket question chain again — three interruptions before the box",
     edit("ddw/rules/classify.instructions.md",
          "never in a chain of questions before it",
          'opening with the question "Do you want me to propose a tracker ticket for this?"')),
    ("the tracker convention re-grows its second question, against the one-stop rule it now shares",
     edit("ddw/rules/tracker.instructions.md",
          "**One stop, not a chain.**",
          '**Ask first:** "Do you want me to propose one so you can file it later?" Then,')),
    ("a backward edge under assisted is taken first and explained after again",
     edit("ddw/rules/state.instructions.md",
          "**Under `assisted`, the question comes BEFORE the edge.**",
          "**And taking one is not a question.**")),
    ("the PLAN corrective loop stops asking before it transitions",
     edit("ddw/rules/plan.instructions.md",
          "**Announce it, and put the motivating question FIRST.**",
          "**Announce it — this is not a question.**")),
    ("W-PRD-06 becomes a warning the model may wave through on the user's behalf again",
     edit("ddw/rules/define.instructions.md",
          "A ⚠️ W-PRD-06 in the report you just showed IS this",
          "A ⚠️ W-PRD-06 in the report is informational; note it and move on. This")),
    ("the worked FEATURE spec disappears, so the validator's shape lives only in its parser again",
     edit("skills/ddw-create-spec/SKILL.md",
          "### The spec, in the shape the validator reads",
          "### Notes on the spec's shape")),
    ("W-SPEC-01 goes back to contradicting F-SPEC-01 in the same output",
     edit("ddw/scripts/validate_spec.py",
          "        if not is_fix and not re.search(r\"\\bFR-\\d+\\b\", body) and not covered_here:",
          "        if not is_fix and not re.search(r\"\\bFR-\\d+\\b\", body):")),
    ("closing a ticket erases what post mode was about to refuse",
     edit("ddw/scripts/validate-transition.py",
          "    owed = []\n    known = len(_journal_entries(state_path))",
          "    owed = []\n    known = len(_journal_entries(state_path)) if scope != \"none\" else 10**9")),
    ("the boot's one-sided-guard warning is dropped on the path that can still count",
     edit("ddw/scripts/session-boot.py", "        return others, registered", "        return others, True")),
    ("the boot's one-sided-guard warning is dropped on the path that cannot list at all",
     edit("ddw/scripts/session-boot.py", "        return 0, registered", "        return 0, True")),
    ("a write lands over a state that changed since the helper read it",
     edit("ddw/scripts/transition.py", "        if seen is not None:", "        if False:")),
    ("the helper stops asking the closing edge for the evidence it spends",
     edit("ddw/scripts/transition.py",
          "    _owed = sorted(set(list(args.gate or []) + list(_cfg.get(\"gates\") or [])))",
          "    _owed = list(args.gate or [])")),
    ("the uninstaller follows a manifest entry to the repository root",
     edit("scripts/uninstall_repo.py",
          "        if (real == repo_real\n", "        if (False\n")),
    ("the uninstaller follows a manifest entry into .git",
     edit("scripts/uninstall_repo.py",
          "                or real == git_dir\n                or real.startswith(git_dir + os.sep)",
          "                or False")),
    ("W-SAST-01 warns again about the Low findings a report says it does not have",
     edit("ddw/scripts/validate_sast.py",
          "    lows = [m for m in re.finditer(r\"\\b(?:low|informational|informativ\\w*)\\b\",",
          "    lows = [m for m in re.finditer(r\"\\b(?:low|informational|informativ\\w*|clean)\\b\",")),
    ("the run stops asking whether the suite passes before anything is injected",
     edit("scripts/mutate.py", "    if baseline() != 0:", "    if False:", last=True)),
    ("the mutation job goes back to running the suite on a machine its preflight refuses",
     edit(".github/workflows/mutations.yml",
          "          npm install -g @anthropic-ai/claude-code\n", "")),
    ("the release job goes back to running the suite on a machine its preflight refuses",
     edit(".github/workflows/release.yml",
          "          npm install -g @anthropic-ai/claude-code\n", "")),
    ("the suite goes back to leaving a temporary directory behind on every block",
     edit("scripts/verify_install.sh",
          'repo = tempfile.mkdtemp(dir=os.environ["WORK"])', "repo = tempfile.mkdtemp()")),
    ("WORK stops being exported, so nothing can anchor to the one cleanup there is",
     edit("scripts/verify_install.sh", 'export WORK="$(mktemp -d)"', 'WORK="$(mktemp -d)"')),
    # Two earlier wordings of this fault picked at redundant code and nothing
    # killed them: `UnicodeDecodeError` is a subclass of `ValueError`, and the
    # byte-level read is covered by the guard that runs earlier on ALL paths.
    # The guard is the living defense — without it the broken line is discarded
    # silently and the journal ends up shorter than the history it verifies.
    # The next three came from running the suite under `coverage`, measuring
    # the subprocesses too: they are enforcement lines the suite was not
    # executing even once. Nobody found them by reading the code.
    ("a receipt written before the corrective loop took the gate back reopens it again",
     edit("ddw/scripts/validate-transition.py",
          "    if written_at is not None and written_at > spent_at:\n        return None",
          "    if True:\n        return None")),
    ("the refusal for a phase without its entry tells an Edit to do what an Edit cannot",
     edit("ddw/scripts/validate-transition.py",
          '            if tool_name == "Edit":',
          '            if False:')),
    ("the drift warning stops naming what is missing, so a repo with no enforcement looks governed",
     edit("ddw/scripts/session-boot.py",
          "    if not changed and not gone:\n        return []",
          "    if True:\n        return []")),
    ("a security suppression goes back to being aged by a date it writes about itself",
     edit("ddw/scripts/validate_sast.py",
          "                if (today - made).days > 190:",
          "                if False:")),
    # These four came out of an audit aimed at the installation and the six
    # adapters. All four survived the entire suite when they were proposed.
    ("a write-deciding hook stops refusing when there is no python3 to judge with",
     edit("adapters/copilot/scripts/pre-tool-use.sh",
          'command -v python3 >/dev/null 2>&1 || {\n'
          '  echo "DDW cannot enforce anything without python3 on PATH. Refusing the write." >&2\n'
          '  exit 2\n'
          '}\n',
          "")),
    ("the preflight stops looking at where the wiring goes, so `nothing was written` stops being true",
     edit("scripts/install_target.py",
          '              + [w.get("to") for w in recipe.get("wiring", [])]',
          "              + []")),
    ("the uninstall leaves Gemini importing a method that is no longer there",
     edit("scripts/uninstall_repo.py",
          'CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")',
          'CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md")')),
    ("the plan you approve stops being the removal that runs",
     edit("uninstall.sh",
          'python3 "$SELF/scripts/uninstall_repo.py" --repo "$TARGET" --self "$SELF" --plan $FORCE',
          'python3 "$SELF/scripts/uninstall_repo.py" --repo "$TARGET" --self "$SELF" --plan')),
    # Eight from an audit aimed at the enforcement core. Four survived the
    # entire suite when they were proposed; the other four already died, and
    # they are added because the list is the coverage: a check with nothing
    # measuring it is a check nobody knows can fail.
    ("a NotebookEdit writes product source with no path for any guard to see",
     edit("ddw/scripts/validate-transition.py",
          'PATH_KEYS = ("file_path", "notebook_path", "path", "filePath", "file", "absolute_path")',
          'PATH_KEYS = ("file_path", "path", "filePath", "file", "absolute_path")')),
    ("a receipt earned for another document opens this gate",
     edit("ddw/scripts/validate-transition.py",
          "        if not named or named == os.path.basename(path):",
          "        if True:")),
    ("a forged history can skip whole phases: nobody compares a.to with b.from",
     edit("ddw/scripts/validate-transition.py",
          '        if a["to"] != b["from"]:', "        if False:")),
    ("the artefact allowlist stops being anchored at the start of the path",
     edit("ddw/scripts/validate-transition.py",
          "    if any(rel.startswith(pre) for pre in ALLOWED_DIR_PREFIXES):",
          "    if any(pre in rel for pre in ALLOWED_DIR_PREFIXES):")),
    ("deleting .ddw-state.json starts a clean run again",
     edit("ddw/scripts/validate-transition.py",
          '        raise Block(\n            f".ddw-state.json is gone, but ',
          '        return  # noqa\n        raise Block(\n            f".ddw-state.json is gone, but ')),
    ("the header can declare a phase no transition ever reached",
     edit("ddw/scripts/validate-transition.py",
          '    if appended[-1]["to"] != new_phase:', "    if False:")),
    ("the field that takes the human out of the loop stops being checked at all",
     edit("ddw/scripts/validate-transition.py",
          "    _check_autonomy(old_state, new_state, appended)", "    pass")),
    ("a write can move the phase without declaring the transition",
     edit("ddw/scripts/validate-transition.py",
          "    if not appended:\n        if new_phase != old_phase:",
          "    if not appended:\n        if False:")),
    # Ten from an audit aimed at the artifact validators. Eight survived the
    # 553 checks: these are the rules that decide whether an empty document,
    # or one that approves itself, earns a gate.
    ("a threat model that names nothing from its own design earns the gate",
     edit("ddw/scripts/validate_threat.py",
          "        if anchors and not cited:", "        if False:")),
    ("a design handling sensitive data passes with nothing classified",
     edit("ddw/scripts/validate_threat.py",
          "    elif SENSITIVE.search(text):", "    elif False:")),
    ("a threat model written in Spanish is told it skipped a STRIDE category",
     edit("ddw/scripts/validate_threat.py",
          '    "Elevation of Privilege": (r"elevation of privilege|elevaci[oó]n de privilegios?|escalada"),',
          '    "Elevation of Privilege": (r"elevation of privilege"),')),
    ("a test report picks a coverage floor it can clear and grades itself against it",
     edit("ddw/scripts/validate_tests.py",
          "        floor = args.floor\n", "        pass\n")),
    ("a report that states no floor is graded against one DDW invented for it",
     edit("ddw/scripts/validate_tests.py",
          "    floor = float(floor_m.group(1)) if floor_m else None",
          "    floor = float(floor_m.group(1)) if floor_m else args.floor")),
    ("a skipped test stops owing a reason — the cheapest way to green a suite",
     edit("ddw/scripts/validate_tests.py",
          "    if skipped and reasons < skipped:", "    if False:")),
    ("a real run of 1,204 tests is refused for its own punctuation",
     edit("ddw/scripts/validate_tests.py",
          '    raw = re.sub(r"(\\d),(\\d{3})\\b", r"\\1\\2", raw)\n', "\n")),
    ("a spec block stops owing what can go wrong with it",
     edit("ddw/scripts/validate_spec.py",
          "        elif not errors:\n            no_errors.append(label)",
          "        elif False:\n            no_errors.append(label)")),
    ("a spec stops owing the order its blocks run in",
     edit("ddw/scripts/validate_spec.py", "    if deps:", "    if True:")),
    ("the PRD template earns its own gate with one field filled in",
     edit("ddw/scripts/validate_prd.py",
          "        unwritten = [pretty for pretty, names in SECTIONS\n"
          "                     if pretty not in missing and _unfilled(_section_body(text, names))]",
          "        unwritten = []")),
    ("the method tells every project to quote a heading its own installer never writes",
     edit("scripts/lint_method.py",
          '        if shipped and f"## {name}" not in shipped:',
          "        if False:")),
    ("a clock that steps backwards stops the pipeline with a refusal nobody can act on",
     edit("ddw/scripts/transition.py",
          "    if _last and _stamp < _last:\n        _stamp = _last",
          "    if False:\n        _stamp = _last")),
    ("a tier with no enforcement stops being explained to the person using it",
     edit("scripts/lint_method.py",
          "        if not asks and tier not in text:", "        if False:")),
    ("a spec block stops owing a criterion for when it is done",
     edit("ddw/scripts/validate_spec.py",
          "        if not criterion and not is_fix:", "        if False:")),
    ("an endpoint stops owing error codes and authentication in its contract",
     edit("ddw/scripts/validate_spec.py",
          "            if missing:\n                bad_api.append",
          "            if False:\n                bad_api.append")),
    ("the refusal goes back to handing the model the way around itself",
     edit("ddw/scripts/validate-transition.py",
          '"this at all, that is theirs to say — ASK them, and classify with the tier "',
          '"this at all, take `--to CLASSIFY --tier FREE` and then `--to FREE`. Or ask "')),
    # Four of FORM, not content: they delete an entire file.
    #
    # The kill map asked for them. The four pinned counts — skills, agents,
    # rules, adapters — were checks no fault ever triggered, and not because
    # they could not fail but because the list had no mutation capable of
    # deleting a file. A count nothing can contradict is a count that reports
    # green for lack of anything else to say.
    # The receipt, which is the only thing separating "the validator said it
    # passes" from "there is an open gate". Four checks asserted it — spec,
    # tests, threat, verify: "rejects a healthy document or writes no receipt" —
    # and no fault triggered them: the whole receipt could stop being written
    # and all four stayed green. It is the half of each of those messages that
    # nobody measured.
    ("a validator that passes stops leaving the receipt its gate looks for",
     edit("ddw/scripts/ddw_receipt.py",
          '    with open(os.path.join(sess, name), "w", encoding="utf-8") as fh:\n'
          "        fh.write(filename + \"\\n\")",
          '    with open(os.path.join(sess, \"x-\" + name), "w", encoding="utf-8") as fh:\n'
          "        fh.write(filename + \"\\n\")")),
    ("an agent disappears from the tree and the pinned count says nothing",
     delete("agents/ddw-arch-auditor.md")),
    ("a skill disappears from the tree and the pinned count says nothing",
     delete("skills/ddw-commit")),
    ("a rule file disappears from the tree and the pinned count says nothing",
     delete("ddw/rules/branches.instructions.md")),
    ("an adapter disappears from the tree and the pinned count says nothing",
     delete("adapters/cursor")),
    # ── From the kill map, list A ───────────────────────────────────────────
    # The stand-down came back into existence. It used to be a condition bug;
    # now the fault is the whole block, because there is no repo manifest that
    # relieves anyone: standing down here is gating nowhere.
    ("Copilot's user-level hook stands down for a repo hook again, and `copilot -p` gates nothing",
         edit("adapters/copilot/scripts/post-write.sh",
              "cat > /dev/null            # drain the event; post mode reads the disk, not stdin\n",
              "cat > /dev/null            # drain the event; post mode reads the disk, not stdin\n"
              "if [ -n \"${DDW_PLUGIN_ROOT:-}\" ] && [ -f \"$REPO/.github/hooks/ddw/post-write.sh\" ]; then\n"
              "  echo '{}'\n"
              "  exit 0\n"
              "fi\n")),
    # The `bad` of `check_post_hook`'s `report` mode was triggered by no
    # fault: the stand-down above sits behind `DDW_PLUGIN_ROOT`, and that
    # check runs the hook without that variable. A check nothing can make
    # fail reports green for lack of anything else to say. This one makes it fail.
    ("Copilot's post net answers every write with a bare {} — the one tool whose post hook cannot "
     "refuse stops speaking too, and a forged state reaches the model as nothing",
         edit("adapters/copilot/scripts/post-write.sh",
              'exec python3 "$GATE" --dialect copilot --mode post --state "$STATE" --graph "$GRAPH" --repo "$REPO"',
              "echo '{}'")),
    ("Copilot's pre-write gate stands down for a repo hook again, and every headless write lands",
         edit("adapters/copilot/scripts/pre-tool-use.sh",
              "DDW=\"$REPO/.ddw\"\n",
              "if [ -n \"${DDW_PLUGIN_ROOT:-}\" ] && [ -f \"$REPO/.github/hooks/ddw/pre-tool-use.sh\" ]; then\n"
              "  echo '{}'\n"
              "  exit 0\n"
              "fi\n"
              "DDW=\"$REPO/.ddw\"\n")),
    ("the Copilot recipe wires its hooks manifest into the repo again, where `-p` never reads it",
         json_edit("adapters/copilot/adapter.json",
                   lambda d: d["wiring"].insert(0, {"from": "hooks", "to": ".github/hooks"}))),
    ("the user-level wrapper goes back to `&&`/`||`, turning every Copilot refusal into permission",
         edit("adapters/copilot/wire-user-hooks.py",
              'bash = "if [ -f %s ]; then exec bash %s; fi; echo \'{}\'" % (target, target)',
              'bash = "[ -f %s ] && bash %s || echo \'{}\'" % (target, target)')),
    ("the drop-in stops wiring Copilot at user level, so headless sessions run with no gates",
         edit("install.sh",
              '  if [ "$t" = "copilot" ]; then\n    copilot_hooks\n',
              '  if [ "$t" = "copilot" ]; then\n    :\n')),
    ("the Copilot wiring drops preCompact, and the pipeline ends at the first summary",
         edit("adapters/copilot/wire-user-hooks.py",
              '        "preCompact": entry("pre-compact.sh", 10),\n',
              "")),
    ("the uninstall reports the block removed and writes the file back unchanged",
         edit("scripts/uninstall_repo.py",
              "                open(path, \"w\", encoding=\"utf-8\").write(out)",
              "                open(path, \"w\", encoding=\"utf-8\").write(text)")),
    ("Copilot's hook grows a matcher, so the gate stops being the only filter",
         edit("adapters/copilot/wire-user-hooks.py",
              'return [{"type": "command", "bash": bash, "timeoutSec": timeout}]',
              'return [{"matcher": "write", "type": "command", "bash": bash, "timeoutSec": timeout}]')),
    ("DISCOVERY closes with no commit and no pull request",
         json_edit("ddw/rules/transition-graph.json",
                   lambda d: d["tiers"]["DISCOVERY"]["DISCOVERY->IDLE"].update(gates=[]))),
    ("the installer stops recognising the block it already wrote and appends a second one",
         edit("scripts/install_target.py",
              "        if \"<!-- BEGIN DDW\" in existing:",
              "        if False:")),
    ("QUICK-FIX grows a PLAN phase, so the tier for a one-line fix costs a spec",
         json_edit("ddw/rules/transition-graph.json",
                   lambda d: d["tiers"]["QUICK-FIX"].update({"DEFINE->PLAN": {"gates": []}}))),
    ("the wiring directory of the tool that runs the gate stops being sealed by name",
         edit("ddw/scripts/validate-transition.py",
              "PROTECTED_WIRING_DIRS = (\n"
              "    \".claude/hooks/\", \".codex/hooks/ddw/\", \".cursor/hooks/ddw/\",",
              "PROTECTED_WIRING_DIRS = (\n"
              "    \".codex/hooks/ddw/\", \".cursor/hooks/ddw/\",")),
    ("every event is judged as a read, so no write is judged at all",
         edit("ddw/scripts/validate-transition.py",
              "        if not writing:\n"
              "            continue                      # a read cannot violate a write rule",
              "        if True:\n"
              "            continue                      # a read cannot violate a write rule")),
    ("the gate reads its own Block — the corrupt-state refusal — as nothing to object to",
         edit("ddw/scripts/hook-gate.py",
              "    except vt.Block as exc:\n"
              "        deny(args.dialect, f\"DDW FSM blocked the write to the state: {exc}\")",
              "    except vt.Block as exc:\n"
              "        allow(args.dialect)")),
    ("the lint result under its own heading stops counting, and a complete report is warned at",
         edit("ddw/scripts/validate_tests.py",
              "        lint = m.group(1).strip() if m else \"\"",
              "        lint = \"\"")),
    ("a path key that is not a string empties the check instead of refusing the write",
         edit("ddw/scripts/hook-gate.py",
              "    typed_but_wrong = any(\n"
              "        k in args and args[k] is not None and not isinstance(args[k], str)\n"
              "        for k in vt.PATH_KEYS\n"
              "    )",
              "    typed_but_wrong = False")),
    ("F-PRD-06 stops looking, so 'deberia' passes as a requirement",
         edit("ddw/scripts/validate_prd.py",
              "        loose = [i for i, t in frs + nfrs + acs if AMBIGUOUS.search(t)]",
              "        loose = []")),
    ("CODE->VERIFY stops asking for tests and sast, so the corrective loop is free",
         json_edit("ddw/rules/transition-graph.json",
                   lambda d: d["tiers"]["FEATURE"]["CODE->VERIFY"].update(gates=[]))),
    ("a graph written before the version field existed is read as an unknown format",
         edit("ddw/scripts/validate-transition.py",
              "    declared = graph.get(\"format_version\")",
              "    declared = graph.get(\"format_version\", \"0\")")),
    ("a run that names no ticket anywhere is waved through instead of refused",
         edit("ddw/scripts/validate-transition.py",
              "        else:\n"
              "            # And if NOTHING names a ticket, that is not \"nothing to check\" — it",
              "        elif False:\n"
              "            # And if NOTHING names a ticket, that is not \"nothing to check\" — it")),
    ("the shared resolver leaves lib/guard.sh under another name, and every hook bows out silently",
         edit("adapters/claude/hooks/lib/guard.sh",
              "ddw_method() {\n  if [ -f",
              "ddw_resolve() {\n  if [ -f")),
    ("any action reads as a declared walkaway, so an undeclared exit to IDLE is free",
         edit("ddw/scripts/validate-transition.py",
              "    return first in (\"abandon\", \"abandoned\", \"pause\", \"paused\")",
              "    return True")),
    ("a script under scripts/ stops parsing, and nothing runs it until CI does",
         edit("scripts/lint_method.py",
              "        print(f\"  {where}\\n      {msg}\")",
              "        print(f\"  {where}\\n      {msg}\"", may_not_parse=True)),
    ("the boot cannot tell a drop-in from a plugin, and tells everyone not to install",
         edit("ddw/scripts/session-boot.py",
              "    if not dropped_in:",
              "    if True:")),
    ("the install manifest moves back inside the method",
         edit("scripts/install_target.py",
              "MANIFEST = \".ddw-installed.json\"\n"
              "LEGACY_MANIFEST = os.path.join(\".ddw\", \".installed.json\")",
              "MANIFEST = os.path.join(\".ddw\", \".installed.json\")\n"
              "LEGACY_MANIFEST = \".ddw-installed.json\"")),
    ("a gh that fails is read as 'the forge has none', which is a fact the guard never established",
         edit("ddw/scripts/validate-transition.py",
              "    if out.returncode != 0:\n"
              "        # An error is not an answer. Offline, rate-limited, unauthenticated, a",
              "    if False:\n"
              "        # An error is not an answer. Offline, rate-limited, unauthenticated, a")),
    # It used to be: "stops standing down, and every write is judged twice".
    # That fault died with the stand-down, and its place is taken by the one
    # that does exist — the hook resolves the method from the repo and, failing
    # that, from the plugin. Removing the second half leaves the plugin with
    # nothing to execute.
    ("the Copilot hook stops falling back to the plugin's method, so a plugin-only install gates nothing",
         edit("adapters/copilot/scripts/pre-tool-use.sh",
              "  if [ -n \"${DDW_PLUGIN_ROOT:-}\" ] && [ -f \"$DDW_PLUGIN_ROOT/ddw/scripts/hook-gate.py\" ]; then\n"
              "    DDW=\"$DDW_PLUGIN_ROOT/ddw\"\n",
              "  if false; then\n"
              "    DDW=\"$DDW_PLUGIN_ROOT/ddw\"\n")),
    # ── From the kill map, list B ───────────────────────────────────────────
    ("Claude's recipe places the skills inside .ddw/, and the method goes back to "
     "carrying one tool's payload",
     edit("adapters/claude/adapter.json",
          '"dir": ".claude/skills",',
          '"dir": ".ddw/skills",')),
    ("Claude's snippet stops being a pointer and copies the instructions: two copies "
     "to keep in step",
     edit("adapters/claude/CLAUDE.snippet.md",
          "@AGENTS.md\n@.ddw/orchestrator.md\n",
          "@AGENTS.md\n@.ddw/orchestrator.md\n\n"
          "Before answering, read `.ddw/orchestrator.md` and run its Boot Sequence. It is a strict state\n"
          "machine: it decides what you are allowed to do based on the phase recorded in `.ddw-state.json`.\n")),
    ("OpenCode's plugin stops judging writes before they happen",
     edit("adapters/opencode/plugin/ddw.js",
          '      if (!WRITE_TOOLS.has(input?.tool)) return\n'
          '      if (!installed()) return\n'
          '      try {\n'
          '        runGate("pre",',
          '      if (true) return\n'
          '      if (!installed()) return\n'
          '      try {\n'
          '        runGate("pre",')),
    ("W-SAST-01 stops counting the word 'low' and only looks at 'informational'",
     edit("ddw/scripts/validate_sast.py",
          '    lows = [m for m in re.finditer(r"\\b(?:low|informational|informativ\\w*)\\b",',
          '    lows = [m for m in re.finditer(r"\\b(?:informational|informativ\\w*)\\b",')),
    ("F-SPEC-15 approves a fix-plan with no rollback plan: the section stops being mandatory",
     edit("ddw/scripts/validate_spec.py",
          '        rb = _section_body(text, ("rollback", "plan de rollback", "reversa"))\n'
          '        if rb:\n',
          '        rb = _section_body(text, ("rollback", "plan de rollback", "reversa"))\n'
          '        if True:\n')),
    ("DEFINE stops measuring the drift when resuming a branch that already existed",
     edit("ddw/rules/define.instructions.md",
          '**Then measure the drift** (checkpoint 2 of "Staying current" in `.ddw/rules/branches.instructions.md`):\n'
          '`git fetch origin` and `git rev-list --count HEAD..origin/{base}`. Silent if it is 0; if the base\n'
          'moved, report how far and offer to update. Do not rebase or merge without the user saying so.',
          'Do not rebase or merge without the user saying so.')),
    ("the installer stops saying whether it is installing or updating",
     edit("install.sh",
          '  echo "  DDW is updating: $TARGET"',
          '  echo "  DDW: $TARGET"')),
    ("a rule file can change without moving its own version",
     edit("scripts/check_versions.py",
          "                if m and m.group(1) == now:",
          "                if False:")),
    ("a recipe is left without a label, and the installer loses that tool's block",
     edit("adapters/opencode/adapter.json",
          '"label": "OpenCode",',
          '"label": "",')),
    ("closing a FEATURE ticket stops requiring commit and PR",
     edit("ddw/rules/transition-graph.json",
          '      "CLOSEOUT->IDLE": {\n'
          '        "gates": [\n'
          '          "commit",\n'
          '          "pr"\n'
          '        ]\n'
          '      },',
          '      "CLOSEOUT->IDLE": {\n'
          '        "gates": []\n'
          '      },')),
    ("the tests validator goes back to demanding the long label: a `| Line | 88% |` "
     "table reads as absent coverage",
     edit("ddw/scripts/validate_tests.py",
          '    line = _number(text, "Line coverage", "Cobertura de l[ií]neas", "Lines", "Line")',
          '    line = _number(text, "Line coverage", "Cobertura de l[ií]neas", "Lines")')),
    ("the installer goes back to flattening the AGENTS.md that was already there with the template",
     edit("install.sh",
          'if [ -f "$TARGET/AGENTS.md" ]; then',
          'if false; then')),
    ("the marketplace declares the owner under another field name and the schema rejects it",
     edit(".claude-plugin/marketplace.json",
          '  "owner": {',
          '  "author": {')),
    ("the installer stops recognising its own files: every second run reports them "
     "as the user's collision",
     edit("scripts/install_target.py",
          "    if _same(src_path, dst_path):\n"
          "        manifest[rel] = _fingerprint(dst_path)\n"
          "        return False                      # already current; nothing to do\n"
          "    if manifest.get(rel) == _fingerprint(dst_path):\n"
          "        return True                       # ours, untouched, superseded\n",
          "")),
    ("Copilot's uninstall procedure stops saying which user-level file has to be "
     "deleted",
     edit(".github/INSTALL.md",
          "Then delete `~/.copilot/hooks/ddw.json`",
          "Then delete `~/.copilot/ddw/`")),
    ("Copilot's install doc goes back to dictating the JSON instead of running the "
     "script that writes it, and the level gets retyped wrong",
     edit(".github/INSTALL.md",
          "python3 ROOT/adapters/copilot/wire-user-hooks.py ROOT",
          "cat ~/.copilot/hooks/ddw.json")),
    ("the installer warns over a heading its own template never writes, so the "
     "warning comes out on every run",
     edit("install.sh",
          '  for h in "## Stack" "## Architecture conventions" "## Domain glossary"; do',
          '  for h in "## Stack" "## Architecture conventions" "## Domain glossary" "## Deployment"; do')),
    ("the uninstaller never deletes the manifest: the repo keeps saying DDW is installed",
     edit("scripts/uninstall_repo.py",
          "    if os.path.exists(mpath) and not kept:",
          "    if False:")),
    ("the closeout leaves the autonomy mode set, and the next ticket inherits the "
     "permission not to ask",
     edit("ddw/scripts/transition.py",
          '        for key in ("ticket", "title", "tracker", "block", "discovery", "autonomy"):',
          '        for key in ("ticket", "title", "tracker", "block", "discovery"):')),
    ("validate_spec.py stops refuting QUICK-FIX and mints a receipt for a phase that "
     "tier does not have",
     edit("ddw/scripts/validate_spec.py",
          '    if args.tier == "QUICK-FIX":',
          '    if False:')),
    # ── From the kill map, list C ───────────────────────────────────────────
    ("the uninstaller searches .gitignore for the context file's markers",
         edit("scripts/uninstall_repo.py",
              "        out, found = strip_block(text, GI_BEGIN, GI_END)",
              "        out, found = strip_block(text, BEGIN, END)")),
    ("the empty-shell exception widens from AGENTS.md to every context file",
         edit("scripts/uninstall_repo.py",
              '        if not out.strip() and name != "AGENTS.md":',
              "        if not out.strip() and name not in CONTEXT_FILES:")),
    ("FEATURE gains a DEFINE->CODE shortcut and PLAN stops being mandatory",
         json_edit("ddw/rules/transition-graph.json",
                   lambda d: d["tiers"]["FEATURE"].update({"DEFINE->CODE": {"gates": []}}))),
    ("the graph lets IDLE go straight to DEFINE, unclassified and with no ticket",
         json_edit("ddw/rules/transition-graph.json",
                   lambda d: d["common"].update({"IDLE->DEFINE": {"gates": []}}))),
    ("QUICK-FIX's edge into CODE stops asking for the fix-brief",
         json_edit("ddw/rules/transition-graph.json",
                   lambda d: d["tiers"]["QUICK-FIX"]["DEFINE->CODE"].update({"gates": []}))),
    ("F-SPEC-06 stays in the catalog and no longer looks at anything: it always says yes",
         edit("ddw/scripts/validate_spec.py",
              '    verdict("F-SPEC-06", no_tests, "every block lists at least one required test",\n'
              '            "block with no tests")',
              '    ok("F-SPEC-06", "every block lists at least one required test")')),
    ("the threat validator is left with five STRIDE categories",
         edit("ddw/scripts/validate_threat.py",
              'STRIDE = ("Spoofing", "Tampering", "Repudiation", "Information Disclosure",',
              'STRIDE = ("Spoofing", "Tampering", "Information Disclosure",')),
    ("Claude's PreCompact hook goes back to carrying its own copy of the reminder",
         edit("adapters/claude/hooks/pre-compact.sh",
              "command -v python3 >/dev/null 2>&1 || exit 0",
              'echo "DDW POST-COMPACTION: re-read the orchestrator and .ddw-state.json before answering."\n'
              "command -v python3 >/dev/null 2>&1 || exit 0")),
    ("the state file is recognised by the name it was written under, not by what it resolves to",
         edit("ddw/scripts/validate-transition.py",
              "    if state_real in targets and writing:",
              "    if state_real in lexicals and writing:")),
    ("the sealed set loses Gemini's hooks directory",
         edit("ddw/scripts/validate-transition.py",
              '    ".gemini/hooks/ddw/", ".github/hooks/", ".opencode/plugins/",',
              '    ".github/hooks/", ".opencode/plugins/",')),
    ("package.json points at a ddw.js that moved",
         edit("package.json",
              '"main": "adapters/opencode/plugin/ddw.js"',
              '"main": "adapters/opencode/ddw.js"')),
    ("a skill is left with its frontmatter `name` different from its directory",
         edit("skills/ddw-create-adr/SKILL.md",
              "name: ddw-create-adr", "name: create-adr")),
    ("the attribution trailer is only searched for at the start of the message, not line by line",
         edit("scripts/check_commits.py",
              'TRAILER = re.compile(r"^(?:AI-assisted|AI-full):\\s*yes\\s*$", re.M | re.I)',
              'TRAILER = re.compile(r"^(?:AI-assisted|AI-full):\\s*yes\\s*$", re.I)')),
    ("the corrective loop returns to VERIFY with the gates it had invalidated",
         multi(  # ← a primitive that does not exist in mutate.py today
           json_edit("ddw/rules/transition-graph.json",
                     lambda d: d["tiers"]["FEATURE"]["VERIFY->CODE"].pop("clears", None)),
           edit("ddw/scripts/transition.py",
                "        for gate in clear_gates:\n            merged.pop(gate, None)\n",
                ""))),
    ("the missing-headings notice prints the user's AGENTS.md into the installer's output",
         edit("install.sh",
              '    echo "  ⚠ AGENTS.md              is missing headings the method reads:"',
              '    echo "  ⚠ AGENTS.md              is missing headings the method reads; it has:"\n'
              "    grep '^##' \"$TARGET/AGENTS.md\" || true")),
    ("the boot line goes back to naming a relative .ddw/orchestrator.md",
         edit("ddw/scripts/session-boot.py",
              '\n    orch = os.path.join(method, "orchestrator.md")',
              '\n    orch = ".ddw/orchestrator.md"')),
    ("the AGENTS.md template stops applying exactly once: -f turns into -d and every AGENTS.md is flattened",
         edit("install.sh",
              'if [ -f "$TARGET/AGENTS.md" ]; then',
              'if [ -d "$TARGET/AGENTS.md" ]; then')),
    ("the seal over DDW's own machinery stops refusing, in the one phase where nothing else does",
     edit("ddw/scripts/validate-transition.py",
          "    if rel == INSTALL_MANIFEST:", "    if False:")),
    # The four the ledger still owed.
    ("the PRD validator skill stops naming the rule it is the only one that applies",
     # The header now names a range (F-PRD-01 to F-PRD-10), so the literal
     # F-PRD-09 lives only in the catalog row.
     edit("skills/ddw-validate-prd/SKILL.md",
          "| F-PRD-09 | An AC matches none of the five EARS patterns",
          "| F-PRD-XX | An AC matches none of the five EARS patterns")),
    ("the PRD template goes back to acceptance criteria in prose the validator cannot match",
     # All FOUR occurrences: the check asks whether the word is in the file,
     # and three examples plus a note about the language keep it alive even
     # when the template stops emitting the form. Another defense by repetition.
     multi(
         edit("skills/ddw-create-prd/SKILL.md",
              "- AC-01 (FR-01): WHEN [trigger], THE [system] SHALL [response].",
              "- AC-01 (FR-01): when [trigger] the [system] does [response]."),
         edit("skills/ddw-create-prd/SKILL.md",
              "- AC-02 (FR-01): IF [failure or misuse], THEN THE [system] SHALL [response].",
              "- AC-02 (FR-01): if [failure or misuse] the [system] does [response]."),
         edit("skills/ddw-create-prd/SKILL.md",
              "- AC-03 (FR-02): WHILE [state], THE [system] SHALL [response].",
              "- AC-03 (FR-02): while [state] the [system] does [response]."),
         edit("skills/ddw-create-prd/SKILL.md",
              "`IF … THEN`, `SHALL`)", "`IF … THEN`)"))),
    ("the context check goes back to being able to block over somebody else's stack",
     multi(
         # Two sentences satisfy the same `grep`, so a single edit is covered
         # by the other one: the class of defect `multi` exists for.
         edit("skills/ddw-context-check/SKILL.md",
              "commands DDW would otherwise run wrong. Never blocks.",
              "commands DDW would otherwise run wrong."),
         edit("skills/ddw-context-check/SKILL.md",
              "it **never blocks**", "it reports"),
         edit("skills/ddw-context-check/SKILL.md",
              "**It never sets a gate and never blocks a",
              "**It reports what it finds. It may set a gate and block a"))),
    ("the context check stops being a skill, so nobody reads a repo's own commands",
     delete("skills/ddw-context-check")),
    ("nothing tells the model to write source with the write tool rather than the shell",
     edit("ddw/orchestrator.md",
          "5. Am I writing product source? → **With `Write` or `Edit`, never with a shell command.**",
          "5. Am I writing product source? → however is convenient.")),
    ("the file the router loads every turn stops saying what a history entry carries",
     multi(
         # It says it twice — the declared shape and the sentence that follows
         # it — so a single edit is covered by the other one.
         edit("ddw/orchestrator.md",
              "**Shape:** `{timestamp, from, to, action, ticket,\n   tier}`",
              "**Shape:** `{timestamp, from, to, action}`"),
         edit("ddw/orchestrator.md", "and `ticket`/`tier`", "and the rest"))),
    ("a state field stops being recovered at boot, so a compaction forgets it",
     edit("ddw/orchestrator.md",
          "`title`, `tracker`, `autonomy`, `block`, `discovery`",
          "`title`, `tracker`, `discovery`")),

    # ── The prose linter's checks, one by one ─────────────────────────────────
    #
    # The suite has ONE check for all of `lint_method.py` ("the method's prose
    # claims something the repo does not support"), so in the kill map its
    # thirty-four `fail()` sites collapse into one: as long as any fault keeps
    # it red, a linter check that stopped finding its target keeps reporting
    # green. Measured by applying each mutation to a copy and reading WHICH
    # message came out: of 34 sites, 16 were triggered by some mutation and 18
    # by none. What follows closes fourteen of those eighteen; the four that
    # remain are in `docs/CHECKS-THAT-CANNOT-FAIL.md` with their reason.
    ("the 🔒 marks vanish from the router, so every Blocked line reads as enforcement",
     multi(*[edit("ddw/orchestrator.md", "🔒 ", "") for _ in range(7)])),
    ("the legend that explains 🔒 goes away and the mark becomes decoration",
     edit("ddw/orchestrator.md", "**🔒 refused by the hook.**", "**🔒 blocked.**")),
    ("DEFINE blocks source code without marking it as the hook's",
     edit("ddw/orchestrator.md",
          "- **Blocked:** 🔒 source code. Specs/fix-plans. Writing outside `docs/ddw/prd/`",
          "- **Blocked:** source code. Specs/fix-plans. Writing outside `docs/ddw/prd/`")),
    ("the Boot Sequence stops naming the file a new turn recovers from",
     edit("ddw/orchestrator.md",
          "1. Read `.ddw-state.json` from the repo.",
          "1. Load the pipeline state from the repo.")),
    ("the template stops shipping a heading the method tells every repo to quote",
     edit("ddw/AGENTS.template.md", "## Testing", "## Tests")),
    ("the tier that asks for no gate stops being explained to people",
     multi(edit("docs/METHOD.md", "So there is a tier for deciding to: **`FREE`**.",
                "So there is a tier for deciding to: **`OPEN`**."),
           edit("docs/METHOD.md", "the state are as sealed in `FREE` as anywhere else.",
                "the state are as sealed in `OPEN` as anywhere else."))),
    ("an artifact is written outside the docs/ddw/ namespace and the citation follows it",
     edit("ddw/rules/define.instructions.md",
          "The skill generates `docs/ddw/prd/prd-{ticket}.md`",
          "The skill generates `docs/prd/prd-{ticket}.md`")),
    ("a router routes a phase that appears in no edge of the graph",
     edit("ddw/orchestrator.md", "## Router: Phase `PLAN`", "## Router: Phase `REVIEW`")),
    ("the catalog's summary loses its heading and the recount goes quiet",
     edit("ddw/rules/validation-rules.instructions.md",
          "## Quantitative Summary", "## Rule Totals")),
    ("a rule family stops being totalled by the summary that counts them",
     edit("ddw/rules/validation-rules.instructions.md",
          "| Threat Model | 7 | 2 | 9 |\n", "")),
    ("a summary row is renamed to an area nothing knows how to count",
     edit("ddw/rules/validation-rules.instructions.md",
          "| SAST | 19 | 1 | 20 |", "| Static Analysis | 19 | 1 | 20 |")),
    ("the rules README restates a total the catalog does not define",
     edit("ddw/rules/README.md", "The 91 validation rules", "The 93 validation rules")),
    ("a phase cites a validation rule the catalog does not define",
     edit("ddw/rules/define.instructions.md", "(F-PRD-02, F-PRD-07)", "(F-PRD-02, F-PRD-77)")),
    ("a tier stops being documented in the schema of the file it is written into",
     multi(edit("ddw/rules/state.instructions.md", '`"QUICK-FIX"`, ', ""),
           edit("ddw/rules/state.instructions.md", "Under QUICK-FIX the two edges",
                "Under the smallest tier the two edges"))),
    ("codex's pre-compact passes an event the compaction table does not name",
     edit("adapters/codex/hooks/pre-compact.sh",
          "--format nested --event PreCompact", "--format nested --event preCompact")),
    # The four below do not break a claim: they make the source it is checked
    # against DISAPPEAR. They are the linter's guards — "the catalog looks
    # empty", "the skill does not exist" — and they are what keeps it from
    # reporting green for having read nothing. Without a fault to light them
    # up, a linter that stopped finding its files says the same thing as one
    # that read them all.
    # `ddw-test`, and not just any skill: the check looks at invocations of the
    # form `Skill(skill="…")`, and that is the one CODE invokes that way half a
    # dozen times. Deleting one the prose names only as a slash-command, the
    # fault triggers nothing — measured.
    ("the skill a rule invokes disappears and the prose goes on invoking it",
     delete("skills/ddw-test")),
    ("the skill that reports a context file's missing sections disappears",
     delete("skills/ddw-context-check")),
    ("the rule catalog disappears, so every cited rule ID has nothing to check against",
     delete("ddw/rules/validation-rules.instructions.md")),
    ("an adapter recipe stops being readable JSON, so nothing bridges its context file",
     edit("adapters/claude/adapter.json", '{\n', '{\n  "broken",\n')),
    ("the graph stops defining tiers at all",
     json_edit("ddw/rules/transition-graph.json", lambda d: d.pop("tiers", None))),

    ("the compaction table stops being readable, and nothing else documents the envelopes",
     multi(edit("docs/DEVELOPMENT.md",
                "| Claude Code | `PreCompact` | stdout (the runtime rejects a JSON verdict here) |",
                "| Claude Code | `PreCompact` | the tool's own transcript |"),
           edit("docs/DEVELOPMENT.md",
                "| Cursor | `preCompact` | `additional_context` |",
                "| Cursor | `preCompact` | its own field |"),
           # Three rows, not two. OpenCode's makes it into the table for saying
           # `stdout` in passing — "its plugin's stdout reaches the terminal" —
           # so breaking two still left FOUR and the check never reached its
           # threshold. Measured: the mutation went through triggering nothing,
           # which is exactly the fault that looks like coverage and is not.
           edit("docs/DEVELOPMENT.md",
                "its plugin's stdout reaches the terminal",
                "its plugin's output reaches the terminal"))),
    ("a journal line nobody can decode is dropped in silence again",
     edit("ddw/scripts/validate-transition.py",
          "    damaged = _journal_undecodable(state_path)",
          "    damaged = 0")),
    ("a FIFO where a record belongs hangs every hook again",
     edit("ddw/scripts/validate-transition.py",
          "    for _path in (journal_path(state_path), state_path):\n"
          "        _odd = _not_a_regular_file(_path)\n        if _odd:\n            raise Block(_odd)\n",
          "")),
    ("the mutation count goes back to being pinned nowhere",
     # Anchored to the COMPARISON, not the number: anchored to the number,
     # adding a fault breaks this fault, and what breaks is precisely the
     # verification that no faults were deleted. The only line that has to be
     # touched when adding one is `EXPECT_MUTATIONS`, and no other.
     # With `edit_re`, over the PIN. Re-anchoring it to the comparison was a
     # mistake and the run said so: making the comparison trivially true turns
     # the check OFF, and a check turned off puts nothing in red — the fault
     # survived. What has to break is the number, so the check speaks.
     edit_re("scripts/verify_install.sh", r"^EXPECT_MUTATIONS=\d+$", "EXPECT_MUTATIONS=0",
             "the line that pins the total of mutations")),
    ("the check total goes back to being unpinned, which used to print as a pass",
     edit_re("scripts/verify_install.sh", r"^EXPECT_CHECKS=\d+$", "EXPECT_CHECKS=0",
             "the line that pins the total of checks")),
    ("the check total becomes a knob the environment can turn again",
     edit_re("scripts/verify_install.sh", r"^EXPECT_CHECKS=(\d+)$",
             r"EXPECT_CHECKS=${EXPECT_CHECKS:-\1}",
             "the line that pins the total of checks")),
    ("the sealed names are judged only after symlinks are followed again",
     edit("ddw/scripts/validate-transition.py",
          "        if lexical != target:\n            reason = enforcement_write_denied(lexical, root)\n"
          "            if reason:\n                return reason\n", "")),
    ("a PRD with no acceptance criteria passes as all zero of them again",
     edit("ddw/scripts/validate_verify.py", "    elif not acs:", "    elif False:")),
    ("a verdict can be checked against another ticket's documents again",
     edit("ddw/scripts/validate_verify.py",
          '    _ticket = re.match(r"verify-(.+)\\.md$", os.path.basename(args.report))',
          "    _ticket = None")),
    ("a gate can be claimed from any phase again, in any order",
     edit("ddw/scripts/validate-transition.py",
          "    _check_gate_owner(old_state, new_state, graph, appended)\n", "")),
    ("a state truncated to zero bytes reads as a fresh IDLE again",
     edit("ddw/scripts/validate-transition.py",
          "    if not text.strip():\n        # Zero bytes is not garbage and it is not absence",
          "    if False:\n        # Zero bytes is not garbage and it is not absence")),
    ("deleting the manifest unseals every hook script again",
     edit("ddw/scripts/validate-transition.py",
          "    elif any(rel.startswith(p) for p in PROTECTED_WIRING_DIRS):\n"
          '        what = "where DDW\'s hooks are installed for this tool"\n', "")),
    ("a missing manifest goes back to reading as a repo DDW was never installed into",
     edit("ddw/scripts/session-boot.py",
          '        return _no_manifest(type(exc).__name__)', "        return []")),
    ("the method tree drops out of the manifest, and no shell edit to it is ever reported",
     edit("scripts/install_target.py",
          "\n    record_method(args.target, manifest)\n", "\n")),
    ("the method root stops reaching the gate, so a plugin install seals nothing",
     edit("adapters/claude/hooks/validate-state-transition.sh",
          '  --repo "${CLAUDE_PROJECT_DIR}" \\\n  --method "$DDW"',
          '  --repo "${CLAUDE_PROJECT_DIR}"')),
    ("a write to the method itself is judged only when the method is inside the repo",
     edit("ddw/scripts/validate-transition.py",
          "        denied = _method_write_denied(target, method, repo)", "        denied = None")),
    ("`mkdir .ddw` picks the method again, and every Claude hook bows out",
     edit("adapters/claude/hooks/lib/guard.sh",
          '  if [ -f "${CLAUDE_PROJECT_DIR:-}/.ddw/scripts/hook-gate.py" ]; then',
          '  if [ -d "${CLAUDE_PROJECT_DIR:-}/.ddw" ]; then')),
    ("--tier goes back to accepting any string at all",
     edit("ddw/scripts/validate_prd.py",
          'ap.add_argument("--tier", default="FEATURE", choices=ddw_receipt.TIERS)',
          'ap.add_argument("--tier", default="FEATURE")')),
    ("the receipt stops recording which rules earned it",
     edit("ddw/scripts/ddw_receipt.py",
          '        if tier:\n            fh.write("tier: %s\\n" % tier)', "        pass")),
    ("the gate stops asking whether the receipt's tier is the ticket's tier",
     edit("ddw/scripts/validate-transition.py",
          '        if stamped and state.get("tier") and stamped != state.get("tier"):',
          "        if False:")),
    ("a write may drop the tier again, and the next one sets whatever it likes",
     edit("ddw/scripts/validate-transition.py",
          "    if old_tier and raw_new is None and not reaching_idle and not in_classify:",
          "    if False:")),
    ("the ❌ every verify report is told to write goes back to being unmatchable",
     edit("ddw/scripts/validate_verify.py",
          "FAILING = re.compile(r\"(?:\\b(?:fail|failed|falla|fallo|fallido|error)\\b|❌|✗|✘)\", re.IGNORECASE)",
          "FAILING = re.compile(r\"\\b(fail|failed|falla|fallo|fallido|error|❌)\\b\", re.IGNORECASE)")),
    ("an upgrade goes back to calling every unknown wiring file DDW's own",
     edit("scripts/install_target.py",
          "    had_manifest = (any(isinstance(k, str) and k.startswith(args.id + \":\") for k in manifest)\n"
          "                    and not recorded_wiring)",
          "    had_manifest = any(isinstance(k, str) and k.startswith(args.id + \":\") for k in manifest)")),
    ("an upgrade goes back to stacking the renamed hook beside the block it replaces",
     edit("scripts/install_target.py",
          "                for b in stale:\n                    cur.remove(b)\n", "")),
    ("the uninstall goes back to leaving an older version's block wired to a deleted script",
     edit("scripts/uninstall_repo.py",
          "                    and not _names_installed_file(b, manifest, target)", "")),
    ("the QUICK-FIX gate goes back to counting the four labels as a fix-brief",
     edit("ddw/scripts/validate_prd.py",
          "        unwritten = [s for s in FIX_BRIEF_SECTIONS\n"
          "                     if s not in missing and _unfilled(_after_label(text, s))]",
          "        unwritten = []")),
    ("the PRD template goes back to teaching prose where the rule counts items",
     edit("skills/ddw-create-prd/SKILL.md",
          "- [what is explicitly NOT included, one item per line]",
          "[What is explicitly NOT included]")),
    ("the PRD template goes back to an acceptance criterion the validator refuses",
     edit("skills/ddw-create-prd/SKILL.md",
          "- AC-03 (FR-02): WHILE [state], THE [system] SHALL [response].",
          "- AC-03 (FR-02): ...")),
    ("the eject skill goes back to ordering a write its own enforcement refuses",
     edit("skills/ddw-eject/SKILL.md",
          '   bash "${CLAUDE_PLUGIN_ROOT}/install.sh" . --method-only',
          "   (copy the method into .ddw/ yourself)")),
    ("the ejected method stops being recorded, so no drift check can see it change",
     edit("scripts/install_target.py",
          "        record_method(args.target, manifest)\n        save_manifest(args.target, manifest)\n"
          '        print("  ✓ .ddw/                  recorded in the manifest")',
          '        print("  ✓ .ddw/                  recorded in the manifest")')),
    ("an agent spawned to judge is handed a tool that edits what it judges",
     edit("agents/ddw-sec-auditor.md", "tools: Read, Grep, Glob, Bash",
          "tools: Read, Write, Grep, Glob, Bash")),
    ("the runner stops asking the suite to stop early, and pays a full pass per fault",
     edit("scripts/mutate.py",
          '        if not want_all_failures:\n'
          '            env["DDW_STOP_ON_FIRST_FAILURE"] = "1"\n',
          '        if False:\n            pass\n', last=True)),
    ("a diff touching the suite itself narrows the mutation run instead of running it whole",
     edit("scripts/mutate.py",
          '    if files & {"scripts/verify_install.sh", "scripts/mutate.py"}:\n'
          "        return set(range(1, len(MUTATIONS) + 1))\n", "", last=True)),
    ("a diff that names no fault reports it as a run instead of saying it injected nothing",
     edit("scripts/mutate.py",
          '        print("Nothing in this diff is named by a mutation, so this run injects nothing. "',
          '        (lambda *a: None)("Nothing in this diff is named by a mutation, so this run injects nothing. "',
          last=True)),
    ("the empty-selection probe goes back to killing one process and orphaning its tree",
     edit("scripts/verify_install.sh", "                            start_new_session=True)", "                            )")),
    ("a router stops marking which half of its Blocked line the hook actually refuses",
     edit("scripts/lint_method.py", "    check_blocked_marks_enforcement(root)\n", "")),
    ("the context template ships a section the check for missing sections never looks for",
     edit("scripts/lint_method.py", "    check_template_sections_known(root)\n", "")),
    ("the coverage floor goes back to being sourced from a section the template does not ship",
     edit("ddw/AGENTS.template.md", "## Testing\n", "## Testing (unused)\n")),
    ("the install stops asking whether the paths it needs are free, and crashes halfway in",
     edit("install.sh",
          '  python3 "$SELF/scripts/install_target.py" --self "$SELF" --target "$TARGET" --id "$t" --preflight || exit 1\n',
          "")),
    ("the untraced-block warning is deleted outright and nothing goes red",
     edit("ddw/scripts/validate_spec.py",
          '        warn("W-SPEC-01", f"block referencing no FR — enabler or gold-plating?: {\', \'.join(no_fr)}")',
          "        pass")),
    ("the missing-lint warning is deleted outright and nothing goes red",
     edit("ddw/scripts/validate_tests.py",
          '        warn("W-TEST-01", "no lint or type-check result reported; VERIFY will ask for it (F-VER-05)")',
          "        pass")),
    ("codex stops watching the shell, so a state rewritten behind the gate is never caught",
     edit("adapters/codex/hooks.json", '"matcher": "apply_patch|Edit|Write|Bash"',
          '"matcher": "apply_patch|Edit|Write"')),
    ("gemini stops matching one of its two write verbs",
     edit("adapters/gemini/settings.json", '"matcher": "write_file|replace"',
          '"matcher": "write_file"')),
    ("the history goes back to accepting an entry dated before the one above it",
     edit("ddw/scripts/validate-transition.py",
          '        if _last and entry["timestamp"] < _last:',
          "        if False:")),
    ("the field extractor goes back to a pattern whitespace can hang", 
     edit("ddw/scripts/validate_tests.py",
          r'rf"^[ \t]*(?:[-*][ \t]*)?\|?[ \t]*\*{{0,2}}{name}\*{{0,2}}[ \t]*[:|][ \t]*(.+?)[ \t]*\|?[ \t]*$"',
          r'rf"^\s*(?:[-*]\s*)?\|?\s*\*{{0,2}}{name}\*{{0,2}}\s*[:|]\s*(.+?)\s*\|?\s*$"')),
    ("the fast layer over the enforcement core stops being run, so it rots unnoticed",
     edit("scripts/verify_install.sh",
          '  PYTEST_OUT="$(python3 -m pytest "$SELF/tests" -q 2>&1)"',
          '  PYTEST_OUT="$(true)"')),
    ("a run that owes evidence and names no ticket is read as owing nothing again",
     edit("ddw/scripts/validate-transition.py",
          '            raise Block(\n                "this run takes %d transition(s) that owe evidence',
          '            pass\n        if False:\n            raise Block(\n                "this run takes %d transition(s) that owe evidence')),
    ("a pause invented in the state file is enough to resume into any phase again",
     edit("ddw/scripts/validate-transition.py",
          "            if state_path:\n                _resume_needs_a_recorded_pause(state_path, entry, dst)",
          "            if False:\n                _resume_needs_a_recorded_pause(state_path, entry, dst)")),
    ("the plugin seal shrinks back to the method, leaving the hook that runs the gate writable",
     edit("ddw/scripts/validate-transition.py",
          "        if outside:\n            # The plugin root:",
          "        if False:\n            # The plugin root:")),
    ("a tier can be added to the graph and explained nowhere",
     edit("scripts/lint_method.py", "    check_tiers_documented(root, graph)\n", "")),
    ("the shard timeout goes back under what a shard actually takes",
     edit(".github/workflows/mutations.yml", "    timeout-minutes: 75", "    timeout-minutes: 30")),
    # It used to be `\bdos\b` against `dos\b`, and nothing kills it:
    # `_entry_after` already requires the match to BE the label, so the boundary
    # became redundant when the position guard arrived. A fault no check can see
    # does not measure a defense — it measures that there were two. This is the
    # one left alive, and it covers all six categories, not just the one ending
    # in `dos`.
    ("a category word inside somebody else's sentence answers for the category again",
     edit("ddw/scripts/validate_threat.py",
          '        if m and re.fullmatch(r"[\\s*_`\\-\u2014\u2013|>]*", ln[:m.start()]):',
          '        if m:')),
    ("the threat validator goes back to counting a bracketed placeholder as an answer",
     edit("ddw/scripts/validate_threat.py",
          '    return not re.search(r"[0-9A-Za-z\u00c0-\u00ff]", re.sub(r"\\[[^\\[\\]]*\\]", "", v))',
          "    return False")),
    ("the encryption rule goes back to reading two sections and believing a denial",
     edit("ddw/scripts/validate_threat.py",
          "            elif not _states_control(text, pat):",
          "            elif not pat.search(data_body + risk_body):")),
    ("the lexical reading stops anchoring on a root written through a symlink of its own",
     edit("ddw/scripts/validate-transition.py",
          "    if path == root or path.startswith(root + os.sep):\n        return path\n    parts = path.split(os.sep)",
          "    return path\n    parts = path.split(os.sep)")),
    ("nothing counts the catalog's rules against the summary that claims to total them",
     edit("scripts/lint_method.py", "    check_rule_counts(root)\n", "")),
    ("a rule range in backticks — the only shape the method uses — goes unread again",
     edit("scripts/lint_method.py",
          r'for m in re.finditer(r"\b([FW]-[A-Z]+)-0*1`?\s+to\s+`?\1-(\d+)\b", body):',
          r'for m in re.finditer(r"\b([FW]-[A-Z]+)-0*1\s+to\s+\1-(\d+)\b", body):')),
    ("the SAST receipt stops recording the clock its suppressions were aged against",
     edit("ddw/scripts/validate_sast.py",
          "              + ddw_receipt.write(args.report, \"sast\", text, args.tier, asof=today.isoformat()))",
          "              + ddw_receipt.write(args.report, \"sast\", text, args.tier))")),
    ("the gate stops asking which day the receipt was earned against",
     edit("ddw/scripts/validate-transition.py",
          "        if asof and asof != today:", "        if False:")),
    ("the write gate stops refreshing the marker, so a long session expires under five of six tools",
     edit("ddw/scripts/hook-gate.py",
          '    _touch_marker(args.repo, event.get("session_id") or event.get("sessionId"))\n', "")),
    ("the demand check goes back to guarding itself with a list literal that is always true",
     edit("scripts/verify_install.sh", "assert not skipped, (", "assert True or not skipped, (")),
    ("two entries injecting one edit stop being reported, and the denominator grows for free",
     edit("scripts/mutate.py", "        if probe in first:", "        if False:", last=True)),
    ("the fix-plan template goes back to teaching prose where the validator counts a list",
     edit("skills/ddw-create-spec/SKILL.md",
          "- [error condition] — [the code, the message, and what the caller does about it]",
          "[Which errors can occur with this change, and how they are handled.]")),
    ("the worked fix-plan documents its errors in prose, which reads to the validator as none",
     edit("skills/ddw-create-spec/SKILL.md",
          "- The file cannot be read — `ConfigUnreadable` naming the path; the caller falls back to defaults\n"
          "  and logs once.\n- The file is not valid UTF-8 — the same error, with the byte offset; the fallback is the same.",
          "The file cannot be read (`ConfigUnreadable` naming the path) or is not valid UTF-8 (the same\n"
          "error, with the byte offset); either way the caller falls back to defaults and logs once.")),
    ("the refusal on an edge to IDLE goes back to prescribing gates the edge never asks for",
     edit("ddw/scripts/transition.py", '            owed = list(_cfg.get("gates") or [])',
          '            owed = ["commit", "pr"]')),
    ("a paused ticket at IDLE is told again that reclassifying is its only way out",
     edit("ddw/scripts/transition.py",
          '            paused_at = vt._paused_at(history, len(history), old_state.get("ticket"))',
          "            paused_at = None")),
    ("rule ranges go back to being read in the rule files and not in the skills that run them",
     edit("scripts/lint_method.py",
          "    for path in method_prose(root):\n        body = read(path)\n"
          "        # Only ranges that START at 01.",
          "    for path in sorted(glob.glob(os.path.join(root, \"ddw/**/*.md\"), recursive=True)):\n"
          "        body = read(path)\n        # Only ranges that START at 01.")),
    # ── Ronda 6 ─────────────────────────────────────────────────────────────
    ("a block with no error conditions of its own has nowhere to say so again",
     edit("ddw/scripts/validate_spec.py",
          "        if len(errors) == 1 and NO_ERRORS.search(errors[0]):",
          "        if False:")),
    ("the declaration of absence becomes a magic word any block can claim",
     edit("ddw/scripts/validate_spec.py",
          "            if INPUT_SURFACE.search(surface) or SCHEMA.search(surface):\n"
          "                no_errors.append(f\"{label} (declares no error conditions, yet it takes input \"",
          "            if False:\n"
          "                no_errors.append(f\"{label} (declares no error conditions, yet it takes input \"")),
    ("the promised tests go back to being read from the whole spec, paths and all",
     edit("ddw/scripts/validate_verify.py",
          "    for body in _required_tests_parts(spec_text):",
          "    for body in [spec_text]:")),
    ("the approved spec stays writable from the phase that implements it",
     edit("ddw/scripts/validate-transition.py",
          "        reason = sealed_artifact_denied(target, root, disk)\n"
          "        if reason:\n            return reason\n", "")),
    ("the seal stops asking whether the gate is standing, and locks the phase that writes it",
     edit("ddw/scripts/validate-transition.py",
          "        if not gates.get(gate):\n"
          "            continue                                 # not earned yet",
          "        if False:\n"
          "            continue                                 # not earned yet")),
    ("the per-response arrow limit goes back to being stated as universal",
     edit("ddw/orchestrator.md",
          "**One arrow\n  per RESPONSE** is `assisted` only.",
          "**One arrow\n  per RESPONSE** holds either way.")),
    ("the autonomy section stops naming the guard that exempts `minimal`",
     edit("ddw/orchestrator.md",
          "hook agrees — `second_arrow_in_one_turn` exempts this mode",
          "hook agrees — the enforcement exempts this mode")),
    ("CLASSIFY goes back to reading as an exit that waits in every mode",
     edit("ddw/rules/classify.instructions.md",
          '> **Under `autonomy: "minimal"` this arrow does not wait.** The mode was chosen\n',
          "")),
    ("the banner's arrow limit goes back to naming no autonomy mode at all",
     edit("ddw/orchestrator.md",
          "**And under `assisted` it promises at most ONE arrow.** There the hook lands",
          "**And it promises at most ONE arrow.** The hook lands")),
    ("regenerating the ledger goes back to keeping one line of each written reason",
     edit("scripts/lint_kill_map.py",
          r'    m = re.search(r"^- \[ \] `%s`\n((?:[ \t]+.*(?:\n|$))*)" % re.escape(name), old, re.M)'
          "\n"
          r'    return m.group(1).rstrip("\n") if m else ""',
          r'    m = re.search(r"^- \[ \] `%s`\n( +.*)$" % re.escape(name), old, re.M)'
          "\n"
          r'    return m.group(1) if m else ""')),
    ("the split index goes back to handing out criteria its own count never declared",
     edit("ddw/scripts/validate_prd.py",
          "            extra = sorted(set(taken) - want)",
          "            extra = []")),
    ("the split receipt goes back to vouching for where the criteria came from",
     edit("ddw/scripts/validate_prd.py",
          'f"the {len(taken)} acceptance criteria the index puts up are "',
          'f"the {len(taken)} acceptance criteria of the original are "')),
    ("the loop back to DEFINE goes back to asking permission to correct a known defect",
     edit("ddw/rules/plan.instructions.md",
          "   │  The PRD is DEFINE's to change, so that is where this    │",
          "   │  Do we proceed with the corrective loop?                 │")),
    ("going back a phase stops being described as the mandatory move it is",
     edit("ddw/rules/state.instructions.md",
          '**Under `assisted`, the question comes BEFORE the edge.** A backward edge exists because something\nalready approved turned out to be wrong — and what there is to ask is never permission to correct\na known defect (that is a rubber stamp; the corrective loop is mandatory everywhere the catalog\ndescribes one, `validation-rules.instructions.md` §2) but the decision that MOTIVATES the\ncorrection: which of two contradicting stacks stands, whether the too-big scope splits, the answer\nnobody wrote down. Measured on a live run: the helper took `PLAN→DEFINE` first and asked which\nstack should prevail after, so a user answering "neither — drop the ticket" would have answered\ninto a phase already re-entered and a gate already spent. Where such a decision exists, announce\nthe reason, put the question to the user, and take the edge WITH their answer in hand. Where\nnothing is theirs to decide before the fix — CODE finding a block that names the wrong file has no\nquestion in it, only a correction (`code.instructions.md` § When the spec is the thing that is\nwrong) — announce with the flag up and go; inventing a question there is the rubber stamp again.\nUnder `minimal` the pause goes away like every other arrow\'s, and the move is announced with its\nreason.\n\n**The lane is enforced, not promised — through a file.** Before taking a backward edge under\n`assisted`, write its reason to `.ddw-work/goback-proposal.txt`, naming the edge and opening with\nthe lane: `correction: <the defect a validator or review named>`, or `ask: <the question>`. A\n`correction:` announces and goes, with the file as its durable record. An `ask:` is held by the\nhook until the sealed copy of that exact question matches — which can only be true if it was on\nscreen before the user answered — so executing the loop first and asking after now bounces instead\nof landing (this paragraph alone did not stop it; the fix that introduced it touched only prose,\nand a later run took the edge first anyway). Where no turn hook is wired, the gate stands down and\nsays so here rather than reading as coverage. In both modes what waits at the far end is unchanged:\nthe corrected artifact re-earning the gate the edge just cleared, from a banner that says where it\ncame back from — an approval\nthat does not know it is a re-approval is the same rubber stamp one document later.\n\n',
          "")),
    # The twin of the fault above, which only touched the update message: the
    # suite's `case` has three arms and the third — the one that says the run
    # announced itself in neither of the two ways — was triggered by nothing.
    # The book of checks asked for it, out loud, the first time its job ran
    # outside a manual dispatch.
    ("the installer stops saying that it is installing, on the first run",
     edit("install.sh",
          '  echo "  DDW is installing into: $TARGET"',
          '  echo "  DDW: $TARGET"')),
    ("the kill map goes back to running only when somebody asks for it",
     edit(".github/workflows/mutations.yml",
          "    name: which checks can never fail? (shard ${{ matrix.shard }}/24)\n"
          "    needs: anchors",
          "    name: which checks can never fail? (shard ${{ matrix.shard }}/24)\n"
          "    if: github.event_name == 'workflow_dispatch'\n"
          "    needs: anchors")),
    ("the kill map's shard goes back to a ceiling it does not fit under",
     edit(".github/workflows/mutations.yml",
          "    # job and of no other. The slowest shard took 38.\n"
          "    timeout-minutes: 75",
          "    # job and of no other. The slowest shard took 38.\n"
          "    timeout-minutes: 45")),
    ("the installer pasted from a URL goes back to not finding itself",
     edit("install.sh",
          'if ! { [ -f "$SELF/.claude-plugin/plugin.json" ]',
          'if false && { [ -f "$SELF/.claude-plugin/plugin.json" ]')),
    ("preguntar vuelve a depender de stdin y no de la terminal",
     edit("install.sh",
          'have_tty() { { : < /dev/tty; } 2>/dev/null; }',
          'have_tty() { [ -t 0 ]; }')),

    # ── The five the installer's own prose was hiding ───────────────────────
    #
    # Four of them were found by reading the code against what it printed, and
    # one by running it: a plugin install at project scope leaves a file in the
    # repo the banner swore was untouched.
    ("the plugin banner stops saying the install covers the whole profile",
     edit("install.sh",
          '  echo "  plugin store, installed to YOUR profile: every repo you open gets the"',
          '  echo "  plugin store, for the repos where you activate it, one at a time, and"')),
    ("the runtime's gitignore list drops the scratch directory again, so a plugin-only install leaks the drafted commit message",
     edit("ddw/scripts/session-boot.py",
          '                     ".ddw-work/", ".ddw-journal.jsonl", ".ddw/**/__pycache__/")',
          '                     ".ddw-journal.jsonl", ".ddw/**/__pycache__/")')),
    ("this repository stops ignoring one of the runtime paths it tells every other repo to ignore",
     edit(".gitignore", "\n.ddw-journal.jsonl\n", "\n")),
    ("plugin capability goes back to a list of tool names typed into the installer",
     edit("install.sh",
          'PLUGIN_CAPABLE=" "\nfor _a in "${AVAILABLE[@]}"; do\n'
          '  [ "$(plugin_install_of "$_a")" = "true" ] && PLUGIN_CAPABLE="${PLUGIN_CAPABLE}${_a} "\ndone\nunset _a',
          'PLUGIN_CAPABLE=" claude copilot opencode "')),
    ("the installer offers a draft pull request again, and opens one nobody can merge",
     edit("install.sh",
          'printf "  Push %s and open a PR? [y/N] "',
          'printf "  Push %s and open a draft PR? [y/N] "')),
    # ── Copilot, medido de punta a punta por primera vez ────────────────────
    ("the eval runner loses its Copilot profile, and the one adapter never measured stays unmeasured",
     edit("evals/runner.py",
          '    "copilot": {\n        # `-p` is the headless entry point',
          '    "_copilot": {\n        # `-p` is the headless entry point')),
    ("a Copilot eval runs against the operator's own hooks, so the fixture is judged by another machine's wiring",
     edit("evals/runner.py",
          '        missing = [k for k, v in prof["env"].items()\n'
          '                   if any(f"{{{f}}}" in v and not fields[f] for f in fields)]',
          '        missing = []')),
    ("a Copilot turn with no resume id is accepted, and a conversation is measured as a run of first turns",
     edit("evals/runner.py",
          '        if not m:\n            return None, None, ("the run printed no resume id',
          '        if False:\n            return None, None, ("the run printed no resume id')),
    ("the verdict tap stops wrapping Copilot's hooks, so its evals judge blind",
     edit("evals/runner.py",
          "_tap_claude(repo) + _tap_opencode(repo) + _tap_copilot(repo)",
          "_tap_claude(repo) + _tap_opencode(repo)")),
    ("the Copilot eval HOME stops carrying credentials, and an authentication failure reads as a product verdict",
     edit("evals/runner.py",
          '    if not cfg.get("copilotTokens") and not cfg.get("loggedInUsers"):',
          "    if False:")),
    ("a Copilot install that wired no user-level hooks is accepted, and the run reports a clean pass over no gates",
     edit("evals/runner.py",
          '    if target == "copilot" and not (workdir / "home" / ".copilot" / "hooks" / "ddw.json").exists():',
          "    if False:")),
    ("the Copilot eval writes its wiring into the operator's real HOME, rewiring every session on the machine",
     edit("evals/runner.py",
          '        env = dict(os.environ, HOME=str(copilot_home(workdir, repo)))',
          "        env = None")),
]


# Is there a fast layer? Asked once: without pytest installed the runner does
# not use it, and the baseline must not refuse over the absence of something it
# was never going to use. The notice comes out once, up top, so nobody reads a
# slower run as a different run.
HAVE_PYTEST = subprocess.run([sys.executable, "-c", "import pytest"],
                             capture_output=True).returncode == 0


def baseline():
    """Does the suite pass on a copy nobody mutated?

    `run_one` reads a non-zero exit as "the suite caught the fault", and it has
    no way to tell that verdict apart from a suite that exits non-zero for a
    reason no mutation put there: a missing tool the preflight refuses over, a
    `commit.gpgsign` this machine cannot satisfy, a half-applied edit. Any one of
    those makes every fault in the list report as caught without a single check
    having examined it, and the run prints 100%.

    That is the same fabricated measurement `check_anchors` exists to prevent,
    one layer down, and it costs one run of the suite to refuse: ask the
    unmutated tree first, and say which it was.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "ddw")
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        # NOT stopped at the first failure, and that is the difference between
        # the two questions. This one has to be able to say "the suite passes",
        # which is a statement about every check — and the run that answers it
        # yes costs the same either way, because a passing run never reaches the
        # branch that stops.
        # The fast layer is asked here too, because `run_one` takes a kill from
        # it: red on an unmutated copy and every fault reports as caught without
        # being examined — the fabricated hundred percent, one layer further down
        # than the one this function was written for.
        #
        # …but only when there IS one. Without pytest installed the runner never
        # asks it, so a baseline that refuses over its absence refuses a run that
        # was never going to use it. Measured in CI, which installs pyyaml and
        # not pytest: twenty-four shards refused to inject anything.
        fast = (subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                               capture_output=True, text=True, cwd=repo)
                if HAVE_PYTEST else None)
        if fast is not None and fast.returncode != 0:
            print("`tests/` does not pass on an UNMUTATED copy of this tree, and the runner "
                  "takes a kill\nfrom it. Nothing was injected. pytest said:\n")
            for ln in [l for l in (fast.stdout + fast.stderr).splitlines() if l.strip()][-15:]:
                print("  " + ln)
            return 1
        r = subprocess.run(["bash", os.path.join(repo, "scripts", "verify_install.sh")],
                           capture_output=True, text=True, cwd=repo)
        if r.returncode == 0:
            return 0
        print("The suite does not pass on an UNMUTATED copy of this tree, so every fault "
              "below would\nbe recorded as caught without being examined. Nothing was "
              "injected. The suite said:\n")
        # The ✗ lines FIRST, and then the tail. The baseline does not stop at
        # the first failure — it has to be able to say "the suite passes",
        # which is a statement about every check — so what failed can sit four
        # hundred lines from the end, and the tail alone says "something
        # failed" without saying what. That is exactly what this whole file is
        # trying to prevent.
        out = r.stdout + r.stderr
        marks = [re.sub(r"\x1b\[[0-9;]*m", "", ln).strip()
                 for ln in r.stdout.splitlines()
                 if re.sub(r"\x1b\[[0-9;]*m", "", ln).lstrip().startswith("✗")]
        for ln in marks:
            print("  " + ln)
        if marks:
            print()
        tail = [ln for ln in out.splitlines() if ln.strip()][-25:]
        for ln in tail:
            print("  " + ln)
        return 1


def run_one(index, label, mutate, skip_fast=False, want_all_failures=False):
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "ddw")
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        problem = mutate(repo)
        if problem:
            return None, problem
        # Stop at the first ✗. The question here is "did the suite go red", not
        # "how many checks pass", and most faults die early in a pass that then
        # runs to the end proving something nobody asked — four hundred times.
        # It cannot change a verdict: the variable is read from `bad` and
        # nowhere else, so a run with nothing to report never sees it, and a run
        # that does exits non-zero either way.
        # The fast layer first, and it is not a shortcut: the suite RUNS pytest
        # and refuses to go green with a single failure or error in it, so a
        # fault that reddens pytest is a fault the suite would catch — the same
        # verdict, reached in a third of a second instead of eighty-five.
        #
        # Only a KILL is taken from here. pytest passing says nothing at all
        # about the fault (it sees a fraction of the enforcement core and no
        # hook, no install, no adapter), so that case falls through to the suite
        # exactly as before. The measurement can only get faster, never looser.
        #
        # The baseline pays the same question on an unmutated copy, for the same
        # reason it pays the suite: a pytest that is already red would report
        # every fault as caught without examining one.
        # …and the kill map does NOT use it, even when `--no-fast` was not
        # asked for. `run_one` cuts off here if pytest goes red, so the suite
        # check that would also have caught that fault never gets recorded —
        # and it shows up as "no fault triggers it" when one does. Part of the
        # 83 was that. The shortcut is correct for the verdict and false for
        # the map: two different questions about the same run.
        if not skip_fast and not want_all_failures and HAVE_PYTEST:
            fast = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-x", "-q"],
                                  capture_output=True, text=True, cwd=repo)
            if fast.returncode != 0:
                return True, None, ["tests/ (fast layer)"]
        # Stopping at the first ✗ answers "did it go red?", which is the
        # verdict's question. It is NOT the kill map's question: there what
        # matters is WHICH checks can fail, and with the early stop only the
        # first one for each fault gets recorded. The map's first run said
        # "352 of 402 never fire", which read that way is false — they are 352
        # that were never FIRST. A number that sounds like a finding and
        # measures something else.
        env = dict(os.environ)
        if not want_all_failures:
            env["DDW_STOP_ON_FIRST_FAILURE"] = "1"
        r = subprocess.run(["bash", os.path.join(repo, "scripts", "verify_install.sh")],
                           capture_output=True, text=True, cwd=repo, env=env)
        # WHICH check killed it, not just that it died. With the stop at the
        # first ✗ that is the first one to appear. It serves the question
        # nothing else answers: which `bad` of the suite NEVER fires — a check
        # that cannot fail reports green for lack of anything else to say.
        killers = []
        if r.returncode != 0:
            for ln in r.stdout.splitlines():
                clean = re.sub(r"\x1b\[[0-9;]*m", "", ln)
                if clean.lstrip().startswith("✗"):
                    killers.append(clean.strip().lstrip("✗").strip())
                    if not want_all_failures:
                        break
        return r.returncode != 0, None, killers


def flake_check(rounds, jobs):
    """The instrument's noise, measured before believing it.

    A spurious red does not get lost: it turns into a KILL. `run_one` reads a
    non-zero exit as "the suite caught the fault", and has no way to tell it
    apart from "the suite failed on its own". Under the concurrency of a full
    run that fabricates coverage, which is the same defect `baseline` and
    `--check-anchors` exist to prevent, one layer further down.

    So the suite is run UNMUTATED, as many times as asked and at the same
    concurrency as the real run, and every check that fails is named. A check
    that fails here cannot kill anything: whatever it reports about a fault is
    about itself.

    Observed twice and not reproduced in forty targeted runs. This does not
    explain it — it makes it visible, which is what can be promised.
    """
    print(f"Midiendo el ruido: {rounds} corridas de la suite sin mutar, {jobs} a la vez.\n")

    def once(n):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "ddw")
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            r = subprocess.run(["bash", os.path.join(repo, "scripts", "verify_install.sh")],
                               capture_output=True, text=True, cwd=repo)
            # The ✗ as a MARKER, not anywhere in the line: there is a check
            # whose own message carries a ✗ ("…can stop the suite at the first
            # ✗…"), and searching for it at any position reported that green
            # check as noise in 24 of 24 runs. The very defect this mode exists
            # to measure, committed by the mode.
            bad_lines = []
            for ln in r.stdout.splitlines():
                clean = re.sub(r"\x1b\[[0-9;]*m", "", ln)
                if clean.lstrip().startswith("✗"):
                    bad_lines.append(clean.strip().lstrip("✗").strip())
            # Kept, not discarded: the check's name says WHICH one failed and
            # not why, and the tree is deleted on leaving the `with`. Without
            # this, every red has to be hunted down again.
            if r.returncode != 0:
                keep = os.path.join(tempfile.gettempdir(), "ddw-flake-%d.log" % n)
                with open(keep, "w", encoding="utf-8") as fh:
                    fh.write(r.stdout + "\n----- stderr -----\n" + r.stderr)
            return n, r.returncode, bad_lines

    seen = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(once, n)
                                                    for n in range(1, rounds + 1)]):
            n, rc, bad_lines = fut.result()
            mark = "\033[32m✓\033[0m" if rc == 0 else "\033[31m✗\033[0m"
            print(f"  {mark} corrida {n}", file=sys.stderr, flush=True)
            for ln in bad_lines:
                seen.setdefault(ln, []).append(n)

    print(f"\n{'─' * 60}")
    if not seen:
        print(f"{rounds}/{rounds} green runs. No check failed on its own at this "
              f"concurrency — which does not prove it cannot, only that it did not here.")
        return 0
    print(f"{len(seen)} check(s) failed on an UNMUTATED tree. Whatever they report about a "
          f"fault is about themselves:")
    for ln, rounds_hit in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        print(f"  · {len(rounds_hit)}/{rounds}  {ln[:96]}")
    print(f"\nThe full output of every red run was kept at "
          f"{os.path.join(tempfile.gettempdir(), 'ddw-flake-<n>.log')}")
    return 1


def slice_of(spec, count):
    """The mutation numbers `--shard I/N` is responsible for.

    Round-robin rather than contiguous blocks: every fault costs one full run of
    the suite, so the slices only stay the same size if they interleave.
    """
    try:
        i, n = (int(x) for x in spec.split("/"))
    except ValueError:
        raise SystemExit(f"--shard {spec}: expected I/N, as in 3/10")
    if not 1 <= i <= n:
        raise SystemExit(f"--shard {spec}: I has to be between 1 and N")
    return [k for k in range(1, count + 1) if (k - 1) % n == i - 1]


def changed_mutations(base):
    """The mutations whose file this diff touches, as a set of 1-based indexes.

    A pull request asks a narrower question than main does: not "can the suite
    fail anywhere", which is four hundred full runs of it, but "can it still
    fail where this diff went". Running the whole list on every push made the
    honest measurement so expensive that the temptation is always to delete
    faults from it, and deleting faults deletes the measurement rather than the
    cost. So the list stays whole, and the PULL REQUEST runs the part of it that
    can say anything about this change.

    Every probe names its file, which is what makes this possible without a
    second source of truth. A mutation whose constructor carries no probe is
    included: unknown is not the same as unaffected, and this must not be the
    thing that quietly drops a fault.
    """
    r = subprocess.run(["git", "diff", "--name-only", "%s...HEAD" % base],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit("--changed %s: git could not diff against it (%s). Fetch the base "
                         "branch first: a shallow clone has no merge base to compare to."
                         % (base, (r.stderr or "").strip()[:120]))
    files = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    # The suite and the runner are load-bearing for every fault: touch either and
    # the answer for all of them may have changed.
    if files & {"scripts/verify_install.sh", "scripts/mutate.py"}:
        return set(range(1, len(MUTATIONS) + 1))
    out = set()
    for i, (_label, mutate) in enumerate(MUTATIONS, 1):
        probe = getattr(mutate, "probe", None)
        if probe is None or probe[1] in files:
            out.add(i)
    return out


def check_anchors():
    """Does every mutation still find the thing it is supposed to break?

    A mutation whose anchor moved is not a mutation: it is a line in a list, and
    the run reports it apart from the kill rate so it cannot be read as a pass.
    But it reports it after injecting the other two hundred, which is thirty
    minutes in CI and hours in one process — for a question that is a substring
    search. Asked here, the answer arrives before the run.

    Whoever edits a file this list quotes finds out from the suite that runs in
    two minutes, instead of from the job that runs last.
    """
    cache, stale = {}, []
    for i, (label, mutate) in enumerate(MUTATIONS, 1):
        probe = getattr(mutate, "probe", None)
        if probe is None:
            stale.append((i, label, "carries no probe — this constructor cannot be checked cheaply"))
            continue
        kind, rel, needle = probe[0], probe[1], probe[2]
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            stale.append((i, label, f"{rel} does not exist"))
            continue
        if kind == "regex":
            if rel not in cache:
                cache[rel] = open(path, encoding="utf-8").read()
            _rx = re.compile(probe[2], re.M)
            _out, _n = _rx.subn(probe[3], cache[rel], count=1)
            if not _n:
                stale.append((i, label, "%s is gone from %s" % (probe[4], rel)))
                continue
            if _out == cache[rel]:
                stale.append((i, label, "%s: the substitution changes nothing in %s" % (probe[4], rel)))
                continue
            if rel.endswith(".py"):
                try:
                    compile(_out, rel, "exec")
                except SyntaxError as exc:
                    stale.append((i, label, "leaves %s uncompilable (%s, line %s)"
                                  % (rel, exc.msg, exc.lineno)))
                    continue
            continue

        if kind == "text":
            if rel not in cache:
                cache[rel] = open(path, encoding="utf-8").read()
            if needle not in cache[rel]:
                stale.append((i, label, f"the anchor is gone from {rel}"))
                continue
            # …and the mutated file still has to be the same LANGUAGE. A
            # "mutation" that leaves Python unparseable does not inject the
            # defect it names — every check dies on the import, the run records
            # a kill, and the fault it claimed to measure was never in the tree.
            # One of these shipped, and it read as covered for as long as it
            # existed. Compiled in memory: the answer is a parse, not a copy.
            # …except when NOT parsing IS the defect. There is a check that
            # asserts a script in `scripts/` stops parsing and nobody runs it
            # until CI; the only fault that can trigger it is one that breaks
            # the syntax. The guard exists for the accidental case, not this one.
            if rel.endswith(".py") and not (len(probe) > 5 and probe[5]):
                text, new, last = cache[rel], probe[3], probe[4]
                if last:
                    head, _, tail = text.rpartition(needle)
                    mutated = head + new + tail
                else:
                    mutated = text.replace(needle, new, 1)
                try:
                    compile(mutated, rel, "exec")
                except SyntaxError as exc:
                    stale.append((i, label, "leaves %s unparseable (%s at line %s), so it measures "
                                            "the file not compiling, not the defect it names"
                                            % (rel, exc.msg, exc.lineno)))
    # Two entries that inject the SAME edit are one fault counted twice: the
    # denominator grows, the percentage moves, and nothing new was ever tried.
    # A pair shipped that way and neither run could see it — both were killed by
    # the same check, which is exactly how a duplicate hides.
    #
    # `text` probes only. The `exists` constructors legitimately collide — six
    # groups of `delete`/`json_edit` mutations name one file and change
    # different things inside it, and treating those as duplicates would report
    # correct entries as defects.
    first = {}
    for i, (label, mutate) in enumerate(MUTATIONS, 1):
        probe = getattr(mutate, "probe", None)
        if not probe or probe[0] != "text":
            continue
        if probe in first:
            stale.append((i, label, "injects exactly what mutation %d injects — one fault counted "
                                    "twice, and the kill rate is a percentage of the list"
                                    % first[probe]))
        else:
            first[probe] = i

    if stale:
        print(f"check-anchors: {len(stale)} of {len(MUTATIONS)} mutations no longer apply.\n"
              "A mutation that cannot be injected proves nothing, and the list is the "
              "coverage figure:")
        for i, label, why in stale:
            print(f"  {i:3d}. {label}\n       {why}")
        return 1
    print(f"check-anchors: all {len(MUTATIONS)} mutations still find what they break.")
    return 0


def cover(path, count):
    """Do the shards in this workflow add up to every mutation, or only look it?

    A matrix entry deleted, or an N that stopped matching the list it is paired
    with, leaves faults that no job injects — and every job that did run is
    green, so the workflow reports success for a measurement it never took. This
    reads the file GitHub reads and adds the slices back up.
    """
    import yaml
    wf = yaml.safe_load(open(path, encoding="utf-8"))
    jobs = wf.get("jobs", {})
    steps = [(name, s) for name, job in jobs.items() for s in job.get("steps", [])]
    # `--kill-map` is ANOTHER measurement, sharded the same way and on demand:
    # it does not answer "was every fault injected?" but "which check catches
    # each one?". It is excluded here and only here, so that the rule below —
    # a job with `if:` covers nothing — keeps holding in full for the job that
    # IS the coverage.
    found = [(name, m) for name, s in steps
             if "--kill-map" not in str(s.get("run", ""))
             for m in [re.search(r"--shard\s+\$\{\{\s*matrix\.(\w+)\s*\}\}/(\d+)",
                                 str(s.get("run", "")))] if m]
    if not found:
        print(f"cover: no step in {path} runs a sharded mutation job — nothing to check")
        return 1

    counted, problems = {}, []
    for job_name, m in found:
        key, n = m.group(1), int(m.group(2))
        job = jobs[job_name]
        # A job that does not run covers nothing, and a job whose failure is
        # swallowed measures nothing. Both were counted as full coverage: the
        # arithmetic added up while the workflow was reporting on a run that
        # either never happened or could not go red.
        cond = job.get("if")
        if cond is not None and str(cond).strip().lower() not in ("true", "${{ true }}"):
            problems.append(f"{job_name}: the job is conditional (`if: {cond}`), so its shards "
                            "may cover nothing on a given run")
            continue
        for label, obj in ((job_name, job), *((f"{job_name} step", s) for _, s in
                                              [(job_name, st) for st in job.get("steps", [])])):
            if obj.get("continue-on-error"):
                problems.append(f"{label}: continue-on-error, so a surviving mutation is green")
        entries = job.get("strategy", {}).get("matrix", {}).get(key)
        if not entries:
            problems.append(f"{job_name}: --shard reads matrix.{key}, and the matrix has no {key}")
            continue
        if sorted(entries) != list(range(1, n + 1)):
            problems.append(f"{job_name}: shards run are {sorted(entries)}, "
                            f"but each one is told it is 1 of {n}")
            continue
        for i in entries:
            for idx in slice_of(f"{i}/{n}", count):
                counted[idx] = counted.get(idx, 0) + 1

    missing = sorted(set(range(1, count + 1)) - set(counted))
    if missing:
        problems.append(f"{len(missing)} mutations are in no shard: "
                        + ", ".join(str(i) for i in missing[:12])
                        + (" …" if len(missing) > 12 else ""))
    # "Each exactly once" was printed and never measured. Two workflows sharding
    # the same list, or one job's matrix overlapping another's, doubles the cost
    # and hides that some other slice is empty.
    twice = sorted(i for i, c in counted.items() if c > 1)
    if twice:
        problems.append(f"{len(twice)} mutations are injected more than once: "
                        + ", ".join(str(i) for i in twice[:12])
                        + (" …" if len(twice) > 12 else ""))
    if problems:
        print(f"cover: the sharded run does NOT cover all {count} mutations")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"cover: the shards in {os.path.basename(path)} run all {count} mutations, "
          f"each exactly once.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", nargs="*", type=int)
    ap.add_argument("--shard", metavar="I/N",
                    help="run slice I of N; the slices together are the whole list")
    ap.add_argument("--cover", metavar="WORKFLOW",
                    help="check that workflow's shards cover every mutation, then exit")
    ap.add_argument("--check-anchors", action="store_true",
                    help="check every mutation still finds what it breaks, then exit")
    ap.add_argument("--jobs", type=int, default=None,
                    help="how many faults to inject at once (default: half the cores, capped at "
                         "4 — the bound is disk, not CPU)")
    ap.add_argument("--flake-check", metavar="N", type=int,
                    help="run the suite UNMUTATED N times at the concurrency of --jobs and "
                         "name every check that fails: a spurious red does not get lost, it "
                         "turns into a kill")
    ap.add_argument("--no-fast", action="store_true",
                    help="do not ask tests/ first: every fault pays for the entire suite. "
                         "Needed for the kill map, which asks WHICH check kills each one "
                         "— a kill from the fast layer hides the check that would also "
                         "have failed.")
    ap.add_argument("--kill-map", metavar="FILE",
                    help="write which check killed each fault, and list the suite's `bad` "
                         "that fire with none of them")
    ap.add_argument("--changed", metavar="BASE",
                    help="only the mutations whose file the diff against BASE touches "
                         "(a pull request's question); the whole list still runs on main")
    args = ap.parse_args()

    if args.list:
        for i, (label, _) in enumerate(MUTATIONS, 1):
            print(f"  {i:2d}. {label}")
        return 0

    if args.check_anchors:
        return check_anchors()

    if args.cover:
        return cover(args.cover, len(MUTATIONS))

    if args.flake_check:
        return flake_check(args.flake_check,
                           args.jobs or max(1, min(8, (os.cpu_count() or 2) // 2)))

    if args.only and args.shard:
        raise SystemExit("--only and --shard both pick what runs; use one")

    touched = None
    if args.changed:
        touched = changed_mutations(args.changed)

    # What was asked for is settled FIRST, before any tree is copied or any suite
    # is run. Both checks below cost a full run of the suite each, and spending
    # them to then answer "there is no mutation 999999" is backwards twice over:
    # it is minutes of work for a question answerable from the argument, and the
    # two guards run this file recursively, so a suite that drives the empty
    # selections would sit in that recursion instead of failing in a second.
    if args.only is not None:
        # A selection that names nothing runs nothing and then prints
        # "0/0 faults caught (0%)" and exits 0 — a green run for a measurement
        # that never happened, in the file whose whole job is to say when that is
        # what happened.
        if not args.only:
            raise SystemExit("--only needs at least one mutation number")
        out_of_range = sorted(i for i in args.only if not 1 <= i <= len(MUTATIONS))
        if out_of_range:
            raise SystemExit("no such mutation(s): %s (there are %d)"
                             % (", ".join(str(i) for i in out_of_range), len(MUTATIONS)))
    wanted = set(slice_of(args.shard, len(MUTATIONS))) if args.shard else None
    chosen = [(i, m) for i, m in enumerate(MUTATIONS, 1)
              if (not args.only or i in args.only)
              and (wanted is None or i in wanted)
              and (touched is None or i in touched)]
    # A narrowed run says so, in the same breath as its percentage. A number
    # that is a fraction of a subset, printed the way a number over the whole
    # list is printed, is the kind of quiet cap this file exists to refuse.
    if touched is not None:
        print("--changed %s: %d of %d mutations touch what this diff changed. This is the "
              "pull request's question.\nThe whole list runs on main and on the weekly "
              "schedule, and that run is the coverage figure.\n"
              % (args.changed, len(touched), len(MUTATIONS)))
    if not chosen and touched is not None and not touched:
        # Nothing this diff touches has a fault in the list, which is an
        # ordinary answer for a docs-only change and not the empty selection the
        # guard below refuses. It is still worth saying out loud.
        print("Nothing in this diff is named by a mutation, so this run injects nothing. "
              "The list is unchanged and main still measures it whole.")
        return 0
    if not chosen and touched and wanted is not None:
        # The diff DOES name mutations — just none in this shard's slice. For a
        # sharded PR run that is an ordinary answer, not a refused measurement:
        # the shards holding them answer the PR's question. Measured on a
        # workflow-only dependency bump: 3 touched mutations, and 21 of 24
        # shards died red for holding none of them.
        print("This shard's slice holds none of the %d mutation(s) this diff touches; "
              "nothing to inject here. The shard(s) holding them answer the PR's question."
              % len(touched))
        return 0
    if not chosen:
        raise SystemExit("the selection matched no mutation — nothing was injected, and a run "
                         "that injects nothing has measured nothing")

    # Anchors are verified HERE, before anything is injected, against the tree as
    # it is on disk. This check lived inside `verify_install.sh` for one
    # afternoon and it was worse than not having it: the suite runs inside the
    # MUTATED copy, where the mutation being tested has just removed its own
    # anchor, so the check failed, the suite exited non-zero, and this file
    # recorded the mutation as KILLED — whether or not a single real check had
    # noticed the defect. Two mutations were caught surviving that way (the `pr`
    # gate and the `autonomy` field); both had been reported killed.
    #
    # A measurement whose instrument reports success for its own side effect is
    # not a weak measurement, it is a fabricated one — and this file exists to
    # say so about everything else.
    if check_anchors() != 0:
        return 1

    # …and the same question about the instrument itself, before the first
    # injection: a suite that is already red measures nothing below.
    if baseline() != 0:
        return 1

    killed, survived, broken = 0, [], []
    # Name the slice in the output. A shard's log is a full green run to anyone
    # skimming it, and "193/193" is the only number worth reporting.
    of_all = f" — shard {args.shard} of the {len(MUTATIONS)}" if args.shard else ""
    # In parallel, and the only thing that changes is the wall clock. Each fault
    # still gets a private copy of the tree and a full run of the suite over it:
    # `run_one` allocates its own TemporaryDirectory and the suite anchors every
    # scratch path to a `mktemp -d` of its own, so two faults share nothing —
    # measured before writing this, along with the fact that nothing here writes
    # `$HOME` or `git config --global`.
    #
    # The default is deliberately below the core count. The bound here is not
    # CPU, it is the disk: every worker copies the tree and the suite makes
    # dozens of temporary repositories inside its run, and this measurement once
    # put 38 GB into /tmp.
    # Was capped at 4 when a worker meant one full suite each. Most faults are
    # now answered by the fast layer in under a second, so the cap was costing
    # wall clock for a disk pressure that only the minority still create. Held
    # to half the cores, which is what /tmp survived at 6 on a 12-core machine.
    jobs = args.jobs or max(1, min(8, (os.cpu_count() or 2) // 2))
    print(f"Injecting {len(chosen)} faults, {jobs} at a time{of_all}.")
    if not HAVE_PYTEST:
        print("pytest is not installed, so every fault pays the whole suite: the fast layer "
              "answers a third of them in under a second and it is not here.")
    print()

    kills = {}

    def report(i, label, verdict, problem):
        nonlocal killed
        if problem:
            broken.append((i, label, problem))
            print(f"  \033[33m?\033[0m  {i:2d}. {label}\n         {problem}")
        elif verdict:
            killed += 1
            print(f"  \033[32m✓\033[0m  {i:2d}. {label}")
        else:
            survived.append((i, label))
            print(f"  \033[31m✗\033[0m  {i:2d}. {label}  ← SURVIVED")

    if jobs == 1:
        for i, (label, mutate) in chosen:
            verdict, problem, killer = run_one(i, label, mutate, args.no_fast,
                                               bool(args.kill_map))
            if killer:
                kills[i] = killer
            report(i, label, verdict, problem)
    else:
        # Printed in list order even though they finish out of order: a log whose
        # lines arrive by luck is a log nobody can diff against the last one.
        # Threads, not processes. Every worker spends its life waiting on
        # `bash verify_install.sh`, so the GIL is released the whole time and
        # there is nothing to gain from separate interpreters — and something to
        # lose: the mutations are closures over their arguments, which do not
        # pickle. Measured: the process pool refused all four faults of a smoke
        # test with "Can't pickle local object", and reported them as anchors
        # that had moved. It failed honestly, which is the only reason that was
        # a five-minute detour and not a fabricated hundred percent.
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(run_one, i, label, mutate, args.no_fast,
                                   bool(args.kill_map)): (i, label)
                       for i, (label, mutate) in chosen}
            done = {}
            # A line per fault as it closes, to stderr, so the run says something
            # while it runs. It cannot go to stdout: that is the log, and a log
            # whose lines arrive by luck is one nobody can diff against the last
            # one. An hour of silence is what made people reach for `--only`,
            # which is the measurement getting smaller to fit the wait.
            for n, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                i, label = futures[fut]
                try:
                    verdict, problem, killer = fut.result()
                    done[i] = (label, verdict, problem)
                    if killer:
                        kills[i] = killer
                except Exception as exc:                          # noqa: BLE001
                    done[i] = (label, None, f"the worker died: {exc.__class__.__name__}: {exc}")
                mark = "?" if done[i][2] else ("✓" if done[i][1] else "✗")
                left = len(chosen) - n
                print(f"  [{n}/{len(chosen)}] {mark} {i}. {label[:58]}"
                      + (f"   ({left} left)" if left else ""),
                      file=sys.stderr, flush=True)
            for i, _ in chosen:
                label, verdict, problem = done[i]
                report(i, label, verdict, problem)

    total = len(chosen) - len(broken)
    rate = (killed / total * 100) if total else 0
    print(f"\n{'─' * 60}")
    print(f"{killed}/{total} faults caught  ({rate:.0f}%){of_all}")
    if survived:
        print("\nThe suite cannot see these. Each one is a check that does not exist yet:")
        for i, label in survived:
            print(f"  {i:2d}. {label}")
    if broken:
        print("\nThese mutations no longer apply — their anchor moved. Update them:")
        for i, label, why in broken:
            print(f"  {i:2d}. {label}: {why}")

    if args.kill_map:
        # Every `bad` the suite knows how to say, against the ones it ever
        # said. A `bad` no fault triggers is a check that, as far as this list
        # knows, cannot fail — and a check that cannot fail reports green
        # because it cannot say anything else, not because it looked at something.
        suite = open(os.path.join(ROOT, "scripts/verify_install.sh"), encoding="utf-8").read()
        declared = set()
        for m in re.finditer(r'\bbad\s+"((?:[^"\\]|\\.)*)"', suite):
            declared.add(m.group(1).strip())
        fired = {k for ks in kills.values() for k in ks}
        # The text `bad` prints can carry interpolation; they are compared by
        # stable prefix so one that DID fire is not called "never fired".
        def seen(msg):
            head = msg.split("$")[0].strip()[:40]
            return any(head and head in f for f in fired)
        never = sorted(d for d in declared if not seen(d))
        with open(args.kill_map, "w", encoding="utf-8") as fh:
            json.dump({"kills": kills, "never_fired": never,
                       "declared": len(declared), "fired": len(fired)}, fh, indent=2)
        print(f"\n{'─' * 60}")
        print(f"Kill map: {len(fired)} distinct checks killed something; "
              f"{len(never)} of {len(declared)} `bad` fire with no fault at all.")
        for d in never[:40]:
            print(f"  · {d[:100]}")
        if len(never) > 40:
            print(f"  … and {len(never) - 40} more (the full list in {args.kill_map})")
    return 1 if (survived or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
