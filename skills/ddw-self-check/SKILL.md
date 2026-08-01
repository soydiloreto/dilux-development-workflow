---
name: ddw-self-check
description: >
  Full coherence validation of the internal state. Checks that the DDW installation in the repo is
  sound and that the pipeline state is consistent with the artifacts on disk. Read-only.
  Trigger: /ddw-self-check, available in any DDW phase.
---

# Skill: /ddw-self-check

## Description

Full coherence validation of the internal state. Checks that DDW's installation in the repo is
sound, and that the pipeline state matches the artifacts on disk. It is read-only — it modifies no
file.

## Inputs

- `.ddw/orchestrator.md` (the method installed into the repo)
- The context file for the tool in use (`CLAUDE.md`, `AGENTS.md` or `GEMINI.md`), carrying the
  `BEGIN DDW` block
- That tool's hook wiring (`.claude/settings.json`, `.codex/hooks.json`, `.cursor/hooks.json`,
  `.gemini/settings.json`, `.github/hooks/`, `.opencode/plugins/`)
- `.ddw-state.json` (the pipeline state, at the repo root)
- The artifacts derived from the ticket (PRD, spec, branch)

## Execution Protocol

### 0. Validate DDW's installation in the repo

```bash
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# The method must be present.
[ -f "$ROOT/.ddw/orchestrator.md" ] || \
  echo "INCONSISTENCY: .ddw/orchestrator.md is missing. Reinstall with install.sh."

# Some context file must carry the activation block. Which one depends on the
# tool, and a repo may legitimately have several.
grep -lqF "BEGIN DDW" "$ROOT"/CLAUDE.md "$ROOT"/AGENTS.md "$ROOT"/GEMINI.md 2>/dev/null || \
  echo "INCONSISTENCY: no context file carries the DDW block. Reinstall with install.sh."

# At least one tool's enforcement must be wired, or the gates are decoration.
ls "$ROOT"/.claude/hooks/*.sh "$ROOT"/.codex/hooks/ddw/*.sh "$ROOT"/.cursor/hooks/ddw/*.sh \
   "$ROOT"/.gemini/hooks/ddw/*.sh "$ROOT"/.github/hooks/ddw/*.sh \
   "$ROOT"/.opencode/plugins/ddw.js >/dev/null 2>&1 || \
  echo "INCONSISTENCY: no enforcement is wired for any tool. Reinstall with install.sh --target <tool>."
```

### 1. Validate the `.ddw-state.json` schema

- The file exists (if it does not, ASSUMING IDLE is valid — it is created on the first write by the
  `enforce.sh` hook).
- If it exists, the **9** mandatory fields are present: `tier`, `phase`, `ticket`, `title`,
  `tracker`, `gates`, `block`, `discovery`, `history`.
- `phase` is a valid value (`IDLE`, `CLASSIFY`, `DEFINE`, `PLAN`, `CODE`, `VERIFY`, `RELEASE`,
  `DISCOVERY`).
- `tier` is `null` (in IDLE/CLASSIFY) or a valid value (`QUICK-FIX`, `FIX`, `FEATURE`,
  `DISCOVERY`).
- If `phase` is neither IDLE nor CLASSIFY, `tier` should not be `null`.
- `gates` is an object and `history` is a list.

### 2. Validate the state against what is on disk

A state that claims a gate no artifact backs is the failure this skill exists to catch.

- The branch derived from `ticket` and `tier` is the one checked out (`git branch --show-current`).
- `gates.define` → `docs/ddw/prd/prd-{ticket}.md` exists (or `fix-{ticket}.md` for QUICK-FIX).
- `gates.spec` → `docs/ddw/specs/spec-{ticket}.md` or `fix-{ticket}.md` exists.
- `gates.threat` → `docs/ddw/security/threat-{ticket}.md` exists.
- `gates.sast` → `docs/ddw/security/sast-{ticket}.md` exists.
- On a FIX: `docs/ddw/specs/rca-{ticket}.md` exists once DEFINE has closed.

### 3. Validate the history

- `history` is non-empty whenever `phase` is not IDLE.
- Its last entry's `to` equals `phase`.
- Every entry has `timestamp`, `from`, `to` and `action`, and the timestamps do not go backwards.
- Each entry's `from` matches the previous entry's `to` (no gaps).

## Output Format

```
┌─────────────────────────────────────────────────────────┐
│  SELF-CHECK — DDW coherence                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Installation:  [✅/❌] method · context file · wiring   │
│  State schema:  [✅/❌] 9 fields, valid values           │
│  Artifacts:     [✅/❌] every earned gate has its file   │
│  History:       [✅/❌] contiguous, ends at {phase}      │
│                                                          │
│  [one ❌ line per inconsistency, with what to do]        │
│                                                          │
│  Result: [SOUND | INCONSISTENCIES (N)]                   │
└─────────────────────────────────────────────────────────┘
```

## PASS/FAIL criteria

- **SOUND:** zero inconsistencies.
- **INCONSISTENCIES (N):** report every one of them, with the fix, and STOP.

## Updating `.ddw-state.json`

**None. This skill is strictly read-only.** It never repairs what it finds — a state machine that
quietly fixes its own state is a state machine you cannot trust the next time it says it is fine.
Report, and let the user decide.

## Language

Answer in the language the user is writing in.
