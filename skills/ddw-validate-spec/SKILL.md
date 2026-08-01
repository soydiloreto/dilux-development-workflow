---
name: ddw-validate-spec
description: >
  Validates that a spec/fix-plan is complete, coherent and consistent with its PRD, against the
  catalog's spec rules. Produces a disambiguation question for every FAIL.
  Trigger: /ddw-validate-spec, during DDW's PLAN phase.
---

# Skill: /ddw-validate-spec

## Description
Validates that a spec/fix-plan is complete, coherent and consistent with its PRD, against the rules
in section 2 of `.ddw/rules/validation-rules.instructions.md`. Produces a concrete disambiguation
question for every FAIL.

## Inputs
- The path to the spec/fix-plan (an argument, or derived from the ticket:
  `docs/ddw/specs/spec-{ticket}.md` / `docs/ddw/specs/fix-{ticket}.md`)
- The PRD at `docs/ddw/prd/prd-{ticket}.md` (if `gates.define` is true and the tier is FEATURE)
- The `tier` from `.ddw-state.json`
- `.ddw/rules/validation-rules.instructions.md` (the rule catalog)

## The rules live in the catalog, not here

**`.ddw/rules/validation-rules.instructions.md` §2 is the single source of truth**: F-SPEC-01 to
F-SPEC-16 (FAIL) and W-SPEC-01 to W-SPEC-03 (WARNING). Do not re-derive criteria from memory and do
not duplicate them here — read the catalog and evaluate its rules mechanically, citing each rule's
ID in the report.

Summary of what each ID covers:

| ID | Fails when | Applies to |
|---|---|---|
| F-SPEC-01 | A PRD FR maps to no block | FEATURE |
| F-SPEC-02 | A PRD AC maps to no test in the spec | FEATURE |
| F-SPEC-03 | A PRD NFR has no technical strategy | FEATURE |
| F-SPEC-04 | A block lists no files | FEATURE |
| F-SPEC-05 | A block has no verifiable completion criterion | FEATURE |
| F-SPEC-06 | A block lists no tests | FEATURE |
| F-SPEC-07 | An endpoint has an incomplete contract | any |
| F-SPEC-08 | A schema has no constraints | any |
| F-SPEC-09 | Input with no documented validation | any |
| F-SPEC-10 | No error handling documented | all tiers |
| F-SPEC-11 | Dependencies between blocks/steps not declared | all tiers |
| F-SPEC-16 | A block documents an error that appears in no test of that block | all tiers |
| F-SPEC-12 | The spec contradicts the PRD | FEATURE |
| F-SPEC-13 | Terminology diverges from the PRD | FEATURE |
| F-SPEC-14 | A fix-plan has no regression test | FIX |
| F-SPEC-15 | A fix-plan has no rollback plan | FIX |

**F-SPEC-01 has no exceptions:** an approved FR with no coverage is a FAIL, never a WARNING. If the
requirement was deliberately deferred, it has to come out of the PRD first (with the user's
approval), through a corrective loop back to DEFINE.

**Tier modifier:** if `tier == "QUICK-FIX"`, none of `F-SPEC-*` applies — that tier has no PLAN
phase and no spec.

## Execution Protocol

The four steps are the catalog's — `.ddw/rules/validation-rules.instructions.md`, *How a validation
runs*. What follows is what they mean here.

1. **Run the validator — do not re-derive its rules yourself:**
   `python3 .ddw/scripts/validate_spec.py <spec-path> --tier <tier>`
   (under a plugin install, resolve `.ddw/scripts/` at the plugin's method path). Add
   `--prd <path>` if the spec's header table does not name its PRD.
   **Paste its output VERBATIM** as the body of your report — every row, every rule ID, nothing
   collapsed into a total. A run of this skill that shows no script output did not validate
   anything: the script is the validation, and a PASSED run writes the content-hashed receipt the
   `spec` gate demands — without it, the PLAN→CODE transition refuses.
2. The script marks F-SPEC-12 (contradicts the PRD) and F-SPEC-13 (terminology diverging from the
   PRD) as MANUAL: judge those two yourself, against the PRD, and state each verdict explicitly
   under the pasted output. For FIX, also judge whether the proposed solution addresses the declared
   root cause — a solution that does not is a FAIL.
3. **Fix and re-run, before asking anything.** Every ❌ is a mandatory loop: correct the spec, run
   the script again, repeat until zero FAILs. Attempt the ⚠️ too. Fix only what the rule names —
   inventing a requirement, a test or an endpoint to clear a check is a worse defect than the one it
   silences, and editing the catalog or the script to make a check pass is never a correction.
4. **Then ask about what is genuinely undecided**, with 2–4 concrete options and what each one
   means, in the user's language and not the repo's.
5. Show the whole table, the totals, the verdict and **the link to the full report** the script
   wrote next to the spec, and ask for approval.

If the spec is edited after validating, run the script again: the receipt is bound to the content,
and a stale one does not open the gate.

## Output Format

```
┌─────────────────────────────────────────────────────────────┐
│  /ddw-validate-spec [name] — [PASSED | FAILED (N questions)] │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  PRD coverage: (FEATURE only)                                │
│    ✅/❌ [ID]: FR-xx → [block or "NOT COVERED"]              │
│                                                              │
│  Per-block completeness:                                     │
│    ✅/❌/⚠️ [ID]: [what was checked]                          │
│       → [what is missing and how to fix it]                  │
│                                                              │
│  Consistency with the PRD:                                   │
│    ✅/❌/⚠️ [ID]: [what was checked]                          │
│                                                              │
│  Disambiguation questions:      (only if there are FAILs)    │
│                                                              │
│    Q1: [concrete question derived from the FAIL]             │
│        Options: a) ... b) ... c) ...                         │
│                                                              │
│  ────────────────────────────────────────────────────────────│
│  Total: X passed, Y failed, Z warnings                       │
│  Result: [PASSED if Y == 0 | FAILED if Y > 0]                │
│  Full report: docs/ddw/specs/spec-[ticket].validation.md     │
│  Next: [recommended action]                                  │
└─────────────────────────────────────────────────────────────┘
```

The **Full report** row is the path the script printed, always, so the user can read the complete
checklist instead of asking for it again.

## Result Rules

- **PASSED:** 0 FAILs. It may have WARNINGs.
- **FAILED (N questions):** 1+ FAILs. Each FAIL produces a disambiguation question.
- Questions must be concrete, with options where possible (a/b/c).
- The user answers → the answers are folded into the spec (via `ddw-create-spec` in update mode) →
  re-validate.
- A spec in the FAILED state cannot be approved.

## Updating .ddw-state.json
- Does not modify flags directly (the user's approval is what sets `gates.spec`).

## Language

Write the report in the language the user is working in, citing the rule IDs verbatim.
