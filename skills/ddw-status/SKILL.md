---
name: ddw-status
description: >
  Reads .ddw-state.json and prints a formatted summary of where the pipeline is. Read-only — it
  modifies no file.
  Trigger: /ddw-status, available in any DDW phase.
---

# Skill: /ddw-status

## Description
Reads `.ddw-state.json` and prints a formatted summary of the current state. Read-only — it modifies
no file.

## Inputs
- `.ddw-state.json`
- `docs/ddw/prd/` — the directory listing only, to work out what is still unfinished

## Execution Protocol

1. Read `.ddw-state.json` in full.
2. Derive the artifact paths from the ticket (they are not stored in the state).
3. **Work out the unfinished sub-tickets.** List `docs/ddw/prd/`: a file named `prd-{TICKET}{letter}.md`
   is a sub-ticket of a split PRD. It is finished if `history` holds an entry with that `ticket`
   reaching `IDLE` by anything other than a pause. Everything else is still owed. Derived on the
   spot from two things already on disk — nothing about this is stored, and nothing needs to be.
4. Format and print the summary.

## Output Format

```
┌─────────────────────────────────────────────────────────┐
│  /ddw-status — Current State                             │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Phase: [phase]                                          │
│  Tier: [tier or "—"]                                     │
│  Ticket: [ticket] — [title]                              │
│  Tracker: [tracker or "—"]                               │
│  Block: [block or "—"]  (FEATURE, during CODE)           │
│  Autonomy: [assisted | minimal]                          │
│                                                          │
│  Gates:                                                  │
│    [✅/⬜] define                                        │
│    [✅/⬜] spec                                          │
│    [✅/⬜] threat                                        │
│    [✅/⬜] tests                                         │
│    [✅/⬜] sast                                          │
│    [✅/⬜] verify                                        │
│    [✅/⬜] commit                                        │
│    [✅/⬜] pr                                            │
│                                                          │
│  (every gate rests on a receipt, git, or the forge —     │
│   `/ddw-help` or RATIONALE 16 for which is which)        │
│                                                          │
│  Artifacts (derived from the ticket):                    │
│    PRD:   docs/ddw/prd/prd-{ticket}.md                   │
│    Spec:  docs/ddw/specs/spec-{ticket}.md                │
│    RCA:   docs/ddw/specs/rca-{ticket}.md    (FIX)        │
│    Branch: feat|fix|discovery/{ticket}-name              │
│                                                          │
│  History: [N] transitions recorded                       │
│                                                          │
│  Unfinished sub-tickets of [PARENT]:  (only if any)      │
│    ✅ [TICKET]a — closed                                 │
│    ▶️ [TICKET]b — in progress                            │
│    ⬜ [TICKET]c — PRD written, never run                 │
└─────────────────────────────────────────────────────────┘
```

**Omit that last section entirely when there is no split PRD.** A panel that shows an empty block
every time teaches the reader to skip the place where the answer will eventually be.

Show only the gates that apply to the current tier. The names are the ones in
`transition-graph.json` — `define`, `spec`, `threat`, `tests`, `sast`, `verify`, `commit`, `pr` —
and nothing else is ever written to `gates`: a status panel that prints a gate no edge asks for
stays empty forever and teaches you to ignore the panel. QUICK-FIX has `define`, `tests`, `sast`,
`commit` and `pr`; DISCOVERY has only `commit` and `pr` (report the concept and the PRDs instead).

## PASS/FAIL criteria
- N/A — this skill is informational; it has no verdict.

## Updating .ddw-state.json
- NONE. This skill is strictly read-only.

## Language

Write the summary in the language the user is working in.
