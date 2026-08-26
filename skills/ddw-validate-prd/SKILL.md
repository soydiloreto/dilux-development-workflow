---
name: ddw-validate-prd
description: >
  Validates a PRD against the catalog's PRD rules and the project's architecture. Produces a
  disambiguation question for every FAIL, so gaps get resolved before approval.
  Trigger: /ddw-validate-prd, during DDW's DEFINE phase.
---

# Skill: /ddw-validate-prd

> **Sequencing — invoke this AFTER the PRD file exists on disk, never
> alongside `ddw-create-prd`.** The validator reads the file; against a file
> that is not written yet it can only fail or, worse, look like it ran.

## Description
Validates a PRD against the rules in section 1 of `.ddw/rules/validation-rules.instructions.md`, and
against the project's architecture. Produces a concrete disambiguation question for every FAIL, so
gaps get resolved before the PRD is approved.

## Inputs
- The path to the PRD (an argument, or the last PRD created/modified)
- `.ddw/rules/validation-rules.instructions.md` (the rule catalog)
- The project's conventions (`AGENTS.md`), if available

## The rules live in the catalog, not here

**`.ddw/rules/validation-rules.instructions.md` §1 is the single source of truth**: F-PRD-01 to
F-PRD-11 (FAIL) and W-PRD-01 to W-PRD-06 (WARNING). Do not re-derive criteria from memory and do not
duplicate them in this file — read the catalog and evaluate its rules mechanically, citing each
rule's ID in the report.

Summary of what each ID covers, so you know what you are looking for:

| ID | Fails when |
|---|---|
| F-PRD-01 | An FR has no AC validating it |
| F-PRD-02 | An AC is not binary (unmeasurable adjectives, no verifiable outcome) |
| F-PRD-03 | An NFR has no quantitative value |
| F-PRD-04 | "Out of Scope" is missing or empty (FEATURE) |
| F-PRD-05 | Duplicate or missing FR/NFR/AC IDs |
| F-PRD-06 | A requirement uses "should"/"could"/"ideally" instead of "must" |
| F-PRD-07 | A cross-reference is not declared under "Dependencies" |
| F-PRD-08 | A mandatory structural section is missing |
| F-PRD-09 | An AC matches none of the five EARS patterns (not DISCOVERY, not QUICK-FIX) |

**Tier modifier:** if `tier == "QUICK-FIX"`, none of `F-PRD-*` applies. Require only the
fix-brief's 4 sections (Bug, Change, Regression test, Risk) present and non-empty → PASS.

## Execution Protocol

1. **Run the validator — do not re-derive its rules yourself:**
   `python3 .ddw/scripts/validate_prd.py <prd-path> --tier <tier>`
   (under a plugin install, resolve `.ddw/scripts/` at the plugin's method path).
   **Paste its output VERBATIM** as the body of your report. A run of this
   skill that shows no script output did not validate anything: the script is
   the validation, and a PASSED run writes the content-hashed receipt that the
   `define` gate demands — without it, the DEFINE→PLAN transition refuses.
2. The script marks F-PRD-02 (binary ACs) and F-PRD-07 (undeclared
   cross-references) as MANUAL: judge those two yourself, against the PRD and
   `AGENTS.md`, and state each verdict explicitly under the pasted output.
3. **Fix and re-run, before asking anything.** Every ❌ is a mandatory loop:
   correct the PRD, run the script again, repeat until zero FAILs. Attempt the
   ⚠️ too. Fix only what the rule names — inventing a requirement or a criterion
   to clear a check is a worse defect than the one it silences, and editing the
   catalog or the script to make a check pass is never a correction.
4. **Then, for whatever survived the loop because it needs a human decision,
   produce a concrete disambiguation question** with 2–4 options and what
   choosing each one means, in the user's language and not the repo's.
5. Show the whole table, the totals, the verdict and **the link to the full
   report** the script wrote next to the PRD, and ask for approval. **Every
   run, including a re-validation of a PRD that has not changed** — the receipt
   matching says the bytes are the same, not that anyone read what was checked.
6. If the PRD is edited after validating, run the script again: the receipt is
   bound to the content, and a stale one does not open the gate.

## Output Format

```
┌─────────────────────────────────────────────────────────────┐
│  /ddw-validate-prd [name] — [PASSED | FAILED (N questions)]  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Structure:                                                  │
│    ✅/❌ [ID]: [what was checked]                            │
│                                                              │
│  Requirement quality:                                        │
│    ✅/❌/⚠️ [ID]: [what was checked]                          │
│       → [what is missing and how to fix it]                  │
│                                                              │
│  Traceability and dependencies:                              │
│    ✅/❌/⚠️ [ID]: [what was checked]                          │
│                                                              │
│  Disambiguation questions:      (only if there are FAILs)    │
│                                                              │
│    Q1: [concrete question derived from the FAIL]             │
│        Options: a) ... b) ... c) ...                         │
│                                                              │
│    Q2: [concrete question derived from the FAIL]             │
│        Options: a) ... b) ... c) ...                         │
│                                                              │
│  ────────────────────────────────────────────────────────────│
│  Total: X passed, Y failed, Z warnings                       │
│  Result: [PASSED if Y == 0 | FAILED if Y > 0]                │
│  Full report: docs/ddw/prd/prd-[ticket].validation.md        │
│  Next: [recommended action]                                  │
└─────────────────────────────────────────────────────────────┘
```

The **Full report** row is the path the script printed, always, so the user can
read the complete checklist instead of asking for it again.

## Result Rules

- **The order is fixed: create → validate → THEN ask the user for approval,
  presenting the script's output.** Asking for approval before the validation
  ran puts the user's signature on an unvalidated document; a live run did
  exactly that. The gate backs this: DEFINE cannot be left without the receipt
  a PASSED run writes.
- **PASSED:** 0 FAILs. It may have WARNINGs.
- **FAILED (N questions):** 1+ FAILs. Each FAIL produces a disambiguation question.
- Questions must be concrete, with options where possible (a/b/c).
- The user answers → the answers are folded into the PRD (via `ddw-create-prd` in update mode) →
  re-validate.
- A PRD in the FAILED state cannot be approved.

## Updating .ddw-state.json
- Does not modify flags directly (the user's approval is what sets `gates.define`).

## Language

Write the report in the language the user is working in, citing the rule IDs verbatim.
