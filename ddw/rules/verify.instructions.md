---
applyTo: '**'
version: 1.5.0
---

# Phase 4: VERIFY

**Goal:** verify that the complete implementation does what the spec said it would.

Read `.ddw-state.json.tier` to determine your behavior.

---

## Step 1: Module Verification

1. Run `ddw-verify-module`, applying **every rule in section 5 of
   `.ddw/rules/validation-rules.instructions.md`** (F-VER-01 to F-VER-06, W-VER-01 to W-VER-03).
   This skill verifies:
   - Every AC in the PRD has a passing test (F-VER-01 — FAIL if missing).
   - Every task in the spec/fix-plan is implemented (F-VER-02 — FAIL if missing).
   - Test coverage ≥ 80% lines, ≥ 80% branches and ≥ 80% functions over new/modified code
     (F-VER-03 — FAIL if any of the three is below).
   - Every endpoint/function taking input has at least one sad-path test (F-VER-04 — FAIL if only
     happy path).
   - Lint/type checker passes with no errors (F-VER-05 — FAIL on errors).
   - Every test listed in the spec exists and passes (F-VER-06 — FAIL if any is missing).
   - Dead code, unused imports (W-VER-01 — WARNING).
   - Business-logic coverage between 80–90% (W-VER-02 — WARNING, recommend raising to 90%+).
   - Fragile tests: order dependencies, global state, hardcoded values (W-VER-03 — WARNING).
2. If it FAILS:
   - Show the report with the failing items.
   - **Go back to the CODE phase:** update `.ddw-state.json` with `phase` → `"CODE"`. Clear the
     invalidated gates with
     `.ddw/scripts/transition.py --to CODE --action "corrective loop: <reason>" --clear-gate tests
     --clear-gate sast --clear-gate verify` — the fix has to re-earn them. Tell the user:
     "Verification found problems. Going back to CODE to fix them."
   - After fixing in CODE and passing its gates (tests + SAST), transition back to VERIFY.
3. If it PASSES → `gates.verify` = `true`.

Spawn an agent via the Agent tool with `subagent_type="ddw-module-verifier"` for detailed
cross-verification (do NOT read AGENT.md as a file).

---

## Step 2: Write the Report

Write the verdict to `docs/ddw/reports/verify-{ticket}.md`: every rule that was checked with its
result, the coverage numbers, the cross-verification's findings, and every WARNING — including the
ones that did not block. If this is a return trip after a corrective loop, append the new run rather
than overwriting the old one; how many rounds verification took is part of what happened.

Then run `.ddw/scripts/validate_verify.py` over it. A PASSED run writes
`.ddw-sessions/verify-validated-<hash>` and **the `verify` gate asks for it**, so VERIFY→RELEASE no
longer rests on the boolean alone. What that receipt attests is that the verdict is **complete** —
no acceptance criterion missing, no block unaccounted for, the three coverage numbers stated and
above the floor, lint and the sad paths answered. It does not attest that the tests pass: DDW does
not run your suite (`docs/RATIONALE.md` decisions 2 and 16), and the numbers stay your report of
what you ran. Say that to the user rather than letting the receipt imply more.

A gate whose only trace is `true` in the state cannot be read six months later. This is the
phase whose verdict is worth the most in writing, because it is the one that says whether what
shipped is what was asked for.

---

## Step 3: Summary and Approval

Present to the user:

```
┌─────────────────────────────────────────────────────────┐
│  VERIFY — Verification Summary                           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Ticket: [ticket] — [title]                              │
│  Tier: [tier]                                            │
│  PRD: [prd_path or N/A]                                  │
│  Spec: [spec_path]                                       │
│  Report: docs/ddw/reports/verify-[ticket].md             │
│  Full checklist: verify-[ticket].validation.md           │
│                                                          │
│  Results:                                                │
│    ✅ /ddw-verify-module: PASSED                         │
│    ✅ Tests: [X passed, Y total]                         │
│    ✅ SAST (CODE phase): PASSED                          │
│                                                          │
│  Files modified:                                         │
│    - [file list]                                         │
│                                                          │
│  Do you approve moving to the release phase?             │
└─────────────────────────────────────────────────────────┘
```

Wait for the user's explicit approval.
> **Under `autonomy: "minimal"` this arrow does not wait.** The state is still
> written, the gates are still owed and still refused by the hook, and the
> closing box is still shown — what goes away is the pause for a confirmation of
> something a receipt already attests. Three things stop the run anyway, in
> either mode: a decision nobody wrote down, a corrective loop at its ceiling,
> and a corrupt state. See `.ddw/orchestrator.md` § Autonomy.

---

## Transition

Only after the user approves:

1. **Commit this phase's artifact** with `Skill(skill="ddw-commit")`: the verification report.
   Documentation commit — `📝 docs`, no source code. What was verified goes on the record before
   the closeout, not as part of it.
2. Update `.ddw-state.json`:
   - `phase` → `"RELEASE"`
   - Add an entry to `history`: transition VERIFY → RELEASE, **stamped with `ticket` and `tier`** (see `.ddw/rules/state.instructions.md`)

Report: "Moving on to the RELEASE phase."

---

**FORBIDDEN in this phase:**
- Writing code (if fixes are needed, go back to the CODE phase)
- Modifying the PRD
- Modifying the spec/fix-plan
- Committing anything other than this phase's own report (never source code)
- Creating PRs
- Skipping the verification gate (`/ddw-verify-module`)
