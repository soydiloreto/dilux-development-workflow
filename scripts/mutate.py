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

Splitting a measurement is how a measurement goes quietly missing — a matrix
that loses an entry leaves faults nobody injects, and every job that did run is
still green. `--cover` reads the workflow and adds the slices back up, so the
workflow has to prove it ran the whole list rather than assert it.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SELF = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SELF)


def edit(rel, old, new):
    """A mutation that swaps one exact string in one file."""
    def apply(repo):
        p = os.path.join(repo, rel)
        s = open(p, encoding="utf-8").read()
        if old not in s:
            return f"the anchor is gone from {rel} — update this mutation"
        open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
        return None
    return apply


def delete(rel):
    def apply(repo):
        p = os.path.join(repo, rel)
        if not os.path.exists(p):
            return f"{rel} does not exist — update this mutation"
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        return None
    return apply


def json_edit(rel, fn):
    def apply(repo):
        p = os.path.join(repo, rel)
        d = json.load(open(p, encoding="utf-8"))
        fn(d)
        json.dump(d, open(p, "w", encoding="utf-8"), indent=2)
        return None
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
    return apply


def _drop_gate(d):
    d["tiers"]["FEATURE"]["VERIFY->RELEASE"]["gates"] = []


def _drop_quickfix_close(d):
    d["tiers"]["QUICK-FIX"].pop("CODE->RELEASE", None)


def _cursor_open(d):
    d["hooks"]["preToolUse"][0]["failClosed"] = False


MUTATIONS = [
    # ── The gate the six tools run ───────────────────────────────────────────
    ("the shared gate stops capping transitions per write",
     edit("ddw/scripts/hook-gate.py", "vt.decide_pre(", "vt.decide_pre_UNCAPPED(")),
    # Targets the CALL, not the default. The default is unreachable — both
    # callers pass the value explicitly — so mutating it cannot change
    # behaviour, and a mutation that cannot fail is not evidence of anything.
    ("the pre path stops capping transitions per write",
     edit("ddw/scripts/validate-transition.py",
          "        validate(old_state, new_state, graph, tool_name=tool_name, max_appended=1)",
          "        validate(old_state, new_state, graph, tool_name=tool_name, max_appended=None)")),
    ("the gate's fail-closed wrapper becomes fail-open",
     edit("ddw/scripts/hook-gate.py",
          'deny(_d, f"DDW could not reach a verdict', 'allow(_d) or deny(_d, f"DDW could not reach a verdict')),
    ("paths are resolved lexically again (symlinks bypass both guards)",
     edit("ddw/scripts/validate-transition.py",
          "    return os.path.realpath(path)", "    return os.path.abspath(path)")),
    ("the source guard forgets every phase but PLAN",
     edit("ddw/scripts/validate-transition.py",
          'NO_SOURCE_PHASES = frozenset({"CLASSIFY", "DEFINE", "PLAN", "VERIFY", "DISCOVERY"})',
          'NO_SOURCE_PHASES = frozenset({"PLAN"})')),
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
          "    targets = [resolve_in_repo(pth, root) for pth in paths if isinstance(pth, str) and pth]",
          "    targets = [resolve_in_repo(pth, root) for pth in paths[:1] if isinstance(pth, str) and pth]")),

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
          '        with open(os.path.join(sess, f"prd-validated-{digest}"), "w", encoding="utf-8") as fh:\n'
          '            fh.write(os.path.basename(prd_abs) + "\\n")\n',
          '        pass\n')),
    ("the helper stops asking for the evidence the hook asks for",
     edit("ddw/scripts/transition.py",
          "    reason = vt.gate_evidence_missing(\n",
          "    reason = None or (lambda *a: None)(\n")),
    ("the spec, threat and verify gates go back to trusting the boolean",
     edit("ddw/scripts/validate-transition.py",
          'GATE_EVIDENCE = {"define": _prd_receipt_missing, "spec": _spec_receipt_missing,\n'
          '                 "threat": _threat_receipt_missing, "verify": _verify_receipt_missing,\n'
          '                 "commit": _commit_evidence_missing}',
          'GATE_EVIDENCE = {"define": _prd_receipt_missing, "commit": _commit_evidence_missing}')),
    ("the spec validator stops counting a block's errors against its tests",
     edit("ddw/scripts/validate_spec.py",
          "        if errors and len(sad) < len(errors):\n",
          "        if False:\n")),
    ("a component analysed against five STRIDE categories passes as six",
     edit("ddw/scripts/validate_threat.py",
          "            missing = [cat for cat in STRIDE\n"
          "                       if not re.search(STRIDE_ALIASES[cat], body, re.IGNORECASE)]\n",
          "            missing = []\n")),
    ("the verify validator stops holding coverage to the floor",
     edit("ddw/scripts/validate_verify.py",
          "        below = [f\"{k} {v:.0f}%\" for k, v in cov.items() if v < MINIMUM]\n",
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
    ("Copilot's raw-text apply_patch is unjudged again (the M4 hole)",
     edit("ddw/scripts/hook-gate.py",
          '    if not paths and raw_args and "*** Begin Patch" in raw_args:\n'
          '        paths = _paths_from_patch(raw_args)\n',
          '')),
    ("the post net stops closing the gitignore window a plugin-born state opens",
     edit("ddw/scripts/validate-transition.py",
          "    _ensure_runtime_ignored(state_path)\n",
          "")),
    ("the Copilot installer sends hooks back to config.json (the gateless window)",
     edit(".github/INSTALL.md",
          "into **`~/.copilot/settings.json`** (NOT",
          "into **`~/.copilot/config.json`** (NOT")),
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
          "    paused_at = _paused_at(history, upto)",
          "    paused_at = entry.get('to')  # noqa")),
    ("`resume` stops requiring the phase it was paused at",
     edit("ddw/scripts/validate-transition.py",
          "    if paused_at != dst:", "    if False:")),
    ("post mode's compatibility hatch stops checking the phase",
     edit("ddw/scripts/validate-transition.py",
          '            and disk_state.get("phase", IDLE) == IDLE):', "            ):")),
    ("the source guard exempts the method's own directory again",
     edit("ddw/scripts/validate-transition.py",
          '    ".claude", ".codex", ".cursor", ".gemini", ".opencode",',
          '    ".ddw", ".claude", ".codex", ".cursor", ".gemini", ".opencode",')),
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
          "    session_id = safe_id(args.session_id or f\"pid-{os.getpid()}\")",
          "    session_id = args.session_id or f\"pid-{os.getpid()}\"")),
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
    ("RELEASE stops asking where the branch lands",
     edit("ddw/rules/release.instructions.md",
          "## Step 4: Integration — where does this branch land? (MANDATORY)",
          "## Step 4: Notes")),
    ("the closeout drops the Integration line, so the step can be skipped quietly",
     edit("ddw/rules/release.instructions.md",
          "│  Integration: [merged into X | on the PR | next ticket   │",
          "│                                                          │")),

    # ── Unfinished sub-tickets ───────────────────────────────────────────────
    ("the boot stops looking for sub-tickets nobody ran",
     edit("ddw/scripts/session-boot.py",
          "    if phase == \"IDLE\":\n        pending = pending_subtickets(repo)",
          "    if False:\n        pending = pending_subtickets(repo)")),
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
     edit("install.sh", 'INSTALLED="$(python3 - "$TARGET" <<\'PY\' 2>/dev/null || true',
          'INSTALLED=""; true "$(python3 - "$TARGET" <<\'PY\' 2>/dev/null || true')),
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
          "(or → DISCOVERY), **stamped\n     with `ticket` and `tier`** "
          "(see `.ddw/rules/state.instructions.md`). This is the first entry\n"
          "     that can carry a ticket — the one before it left IDLE, where there was none yet.",
          "(or → DISCOVERY).")),
    ("a phase appends to history without being told what to stamp on the entry",
     edit("ddw/rules/verify.instructions.md",
          "transition VERIFY \u2192 RELEASE, **stamped with `ticket` and `tier`** "
          "(see `.ddw/rules/state.instructions.md`)",
          "transition VERIFY \u2192 RELEASE")),

    # ── What a gate rests on ─────────────────────────────────────────────────
    ("the receipt is asked for by the helper again, and not by the hook",
     edit("ddw/scripts/validate-transition.py",
          "        reason = gate_evidence_missing(root, new_state,\n"
          "                                       _gates_newly_claimed(old_state, new_state))\n"
          "        if reason:\n"
          "            return reason",
          "        reason = None")),
    ("the shell can still set a gate that owes evidence",
     edit("ddw/scripts/validate-transition.py",
          "            reason = gate_evidence_missing(os.path.dirname(os.path.abspath(state_path)),\n"
          "                                           disk_state, owed)\n"
          "            if reason:\n"
          "                raise Block(reason)",
          "            pass")),
    ("the receipt stops naming the PRD's current bytes, and attests to a rewrite",
     edit("ddw/scripts/validate-transition.py",
          '    if os.path.exists(os.path.join(root, ".ddw-sessions", "%s-validated-%s" % (receipt, digest))):',
          '    if glob.glob(os.path.join(root, ".ddw-sessions", "%s-validated-*" % receipt)):')),
    ("the commit gate goes back to taking the model's word",
     edit("ddw/scripts/validate-transition.py",
          '                 "commit": _commit_evidence_missing}',
          '                 }')),
    ("an untracked build directory starts blocking the closeout",
     edit("ddw/scripts/validate-transition.py",
          'dirty = _git(root, "status", "--porcelain", "--untracked-files=no")',
          'dirty = _git(root, "status", "--porcelain")')),
    ("the README claims a tool passed acceptance that the record does not",
     edit("scripts/acceptance.md",
          "| Claude Code | drop-in | 2.1.220 | 2026-07-28 | \u2705 | \u2705 | \u2705 | \u2705 |",
          "| Claude Code | drop-in | 2.1.220 | 2026-07-28 | \u2705 | \u2705 | \u2705 | \u2014 |")),
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
          '                    print(f"DDW notices: {note}", file=sys.stderr)',
          "                    deny(args.dialect, note)")),
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
    ("a rule's version stops being semver",
     edit("ddw/rules/code.instructions.md", "version: 1.5.0", "version: latest")),
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
          ' --format text --method "$DDW"', ' --format text')),

    # ── Reads judged as writes ───────────────────────────────────────────────
    ("every tool is judged as a write again, so the agent cannot read",
     edit("ddw/scripts/validate-transition.py",
          "        if not writing:\n            continue                      # a read cannot violate a write rule\n",
          "")),
    ("the raw tool name stops reaching the decision, so every read is an edit again",
     edit("ddw/scripts/hook-gate.py",
          "                               repo=args.repo, raw_tool=raw_name)",
          "                               repo=args.repo)")),
    # The one that shipped: asking "is this a write?" and letting an unrecognised
    # tool through as a read.
    ("unknown tools go back to being read as reads, and walk past the guard",
     edit("ddw/scripts/validate-transition.py",
          "    writing = payload_writes or not any(r in _verb for r in READ_VERBS)",
          "    writing = payload_writes or any(r in _verb for r in READ_VERBS)")),
    ("a viewer stops being recognised, so the agent cannot read",
     edit("ddw/scripts/validate-transition.py",
          'READ_VERBS = ("read", "view", "list", "ls", "cat", "search", "grep", "glob",',
          'READ_VERBS = ("nothing_matches",  # was: "read", "view", "list", "ls", "cat",')),
    ("the payload stops overruling a read-sounding name",
     edit("ddw/scripts/validate-transition.py",
          "    writing = payload_writes or not any(r in _verb for r in READ_VERBS)",
          "    writing = not any(r in _verb for r in READ_VERBS)")),

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
          "    if len(history) < len(recorded):", "    if False:")),
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
          'echo "The pipeline starts on its own. See the \\"try:\\" line above for how to call it."',
          'echo "The pipeline starts on its own. Commands: /ddw-status, /ddw-help."')),

    # ── The payload ──────────────────────────────────────────────────────────
    ("a skill disappears", delete("skills/ddw-commit")),
    ("an agent disappears", delete("agents/ddw-sec-auditor.md")),
    ("a rule file disappears", delete("ddw/rules/code.instructions.md")),
    ("an adapter recipe points at a directory that is not there",
     json_edit("adapters/claude/adapter.json",
               lambda d: d["skills"].update({"dir": ".claude/nope"}))),
]


def run_one(index, label, mutate):
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "ddw")
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        problem = mutate(repo)
        if problem:
            return None, problem
        r = subprocess.run(["bash", os.path.join(repo, "scripts", "verify_install.sh")],
                           capture_output=True, text=True, cwd=repo)
        return r.returncode != 0, None


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
    found = [(name, m) for name, s in steps
             for m in [re.search(r"--shard\s+\$\{\{\s*matrix\.(\w+)\s*\}\}/(\d+)",
                                 str(s.get("run", "")))] if m]
    if not found:
        print(f"cover: no step in {path} runs a sharded mutation job — nothing to check")
        return 1

    covered, problems = set(), []
    for job_name, m in found:
        key, n = m.group(1), int(m.group(2))
        entries = jobs[job_name].get("strategy", {}).get("matrix", {}).get(key)
        if not entries:
            problems.append(f"{job_name}: --shard reads matrix.{key}, and the matrix has no {key}")
            continue
        if sorted(entries) != list(range(1, n + 1)):
            problems.append(f"{job_name}: shards run are {sorted(entries)}, "
                            f"but each one is told it is 1 of {n}")
            continue
        for i in entries:
            covered |= set(slice_of(f"{i}/{n}", count))

    missing = sorted(set(range(1, count + 1)) - covered)
    if missing:
        problems.append(f"{len(missing)} mutations are in no shard: "
                        + ", ".join(str(i) for i in missing[:12])
                        + (" …" if len(missing) > 12 else ""))
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
    args = ap.parse_args()

    if args.list:
        for i, (label, _) in enumerate(MUTATIONS, 1):
            print(f"  {i:2d}. {label}")
        return 0

    if args.cover:
        return cover(args.cover, len(MUTATIONS))

    if args.only and args.shard:
        raise SystemExit("--only and --shard both pick what runs; use one")

    wanted = set(slice_of(args.shard, len(MUTATIONS))) if args.shard else None
    chosen = [(i, m) for i, m in enumerate(MUTATIONS, 1)
              if (not args.only or i in args.only)
              and (wanted is None or i in wanted)]
    killed, survived, broken = 0, [], []
    # Name the slice in the output. A shard's log is a full green run to anyone
    # skimming it, and "193/193" is the only number worth reporting.
    of_all = f" — shard {args.shard} of the {len(MUTATIONS)}" if args.shard else ""
    print(f"Injecting {len(chosen)} faults, one at a time{of_all}.\n")
    for i, (label, mutate) in chosen:
        verdict, problem = run_one(i, label, mutate)
        if problem:
            broken.append((i, label, problem))
            print(f"  \033[33m?\033[0m  {i:2d}. {label}\n         {problem}")
        elif verdict:
            killed += 1
            print(f"  \033[32m✓\033[0m  {i:2d}. {label}")
        else:
            survived.append((i, label))
            print(f"  \033[31m✗\033[0m  {i:2d}. {label}  ← SURVIVED")

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
    return 1 if (survived or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
