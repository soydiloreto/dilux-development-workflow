---
applyTo: '**'
version: 2.0.0
---

# Phase 3: CODE (Implementation)

**Goal:** implement the solution per the approved spec/fix-plan.

Read `.ddw-state.json.tier` to determine your behavior.

---

## NON-NEGOTIABLE RULE — Gates run through the Skill tool

The CODE gates (`ddw-validate-arch`, `ddw-test`, `ddw-security-sast`) run **EXCLUSIVELY by invoking
the Skill tool** with `skill="<name>"`. **Running them by hand with Bash is FORBIDDEN.**

- ❌ NEVER run the test runner directly (`npx jest`, `npm test`, `pytest`, `go test`, `gradle test`,
  `xcodebuild test`, etc.). That skips what `ddw-test` encapsulates: scope detection, generating
  missing tests, the auto-fix loop (max 3 attempts), and updating `gates.tests` in the state.
- ❌ NEVER run linters/architecture analysis by hand instead of `ddw-validate-arch`.
- ❌ NEVER run SAST tools by hand instead of `ddw-security-sast`.
- ✅ ALWAYS `Skill(skill="ddw-test")`, `Skill(skill="ddw-validate-arch")`,
  `Skill(skill="ddw-security-sast")`.

Having Bash available is NOT authorization to reimplement a gate manually. If the skill uses Bash
internally, that is the skill's business — the main agent invokes the skill, not the runner.

**Single exception:** the project's type checker / linter (closeout step #2) IS run with Bash
directly, because no skill encapsulates it. Everything else goes through the Skill tool.

---

## Self-check before running tests (MANDATORY in every block and closeout)

**Before ANY Bash command that runs tests** (`jest`, `npx jest`, `npm test`, `npm run test*`,
`pytest`, `go test`, `gradle test`, `xcodebuild test`, etc.), STOP and verify internally:

1. Am I in the CODE phase? → Yes: tests go through `Skill(skill="ddw-test")`, not through Bash.
2. Have I already invoked `Skill(skill="ddw-test")` for THIS specific block/closeout?
   - **NO** → STOP. Invoke `Skill(skill="ddw-test")` first. The skill handles execution (detects
     scope, generates missing tests, auto-fix loop, updates `gates.tests`).
   - **YES** → is the command I am about to run part of the protocol the skill loaded, or a shortcut
     of my own? If it is a shortcut → STOP.

**If it fails → STOP:** `⚠️ Test self-check failed: I was about to run [command] without invoking
Skill(test) in this block.`

### Known ANTI-PATTERN (do NOT repeat it)

The most common failure mode: invoking `Skill(skill="ddw-test")` in Block 1, then in Blocks 2..N
running `npx jest` / `npm test` directly "because I already did it before". **FORBIDDEN.** Every
block and every closeout (including the re-closeout after a fix) ALWAYS starts by invoking
`Skill(skill="ddw-test")`. There is no "already ran it, skipping". The reflex "tests = jest" is NOT
authorization.

---

## Session Recovery

If this is a new session (the agent just started and `phase` was already `CODE`):
1. Read the spec/fix-plan from `docs/ddw/specs/` (derived from the ticket).
2. Read `block` from the state to know which block we are on (e.g. `"2/5"`).
3. Report the current state to the user before continuing.

---

## Mandatory FIRST Action

**Before writing the first line of code:**
1. Invoke `Skill(skill="ddw-validate-arch")` over the current codebase.
2. If it reports violations:
   - Show the report to the user.
   - **BLOCKED** until the existing violations are resolved, or documented as accepted technical
     debt.
3. If it passes → continue with the implementation.

---

## If tier == FEATURE

### Block-by-block implementation — a subagent per block + two-stage review

**Each block is implemented by a fresh subagent, and you — the orchestrator — review it when it
comes back.** Do not implement the block yourself in the main context.

The reason is twofold. First, **isolation**: the implementer starts clean, with the spec and its
block, dragging in neither the earlier conversation nor the noise of previous blocks — which ties it
to the written contract instead of to what was said in passing. Second, **honest review**: whoever
reviews is not whoever wrote, which is the only way a review is worth anything.

For each block of the spec (starting from the one indicated in the state's `block`, or 1 at the
start):

1. **Announce:** "Implementing Block N of M: [name]".

2. **Dispatch the implementer.** Spawn via the Agent tool with `subagent_type="ddw-implementer"`,
   passing it: the spec, **which block is theirs** (number, name and description), and the
   conventions from `AGENTS.md`. One subagent **per block** — not one for all of them.

3. **Receive its report** and read it. It carries the status, the files touched, the tests, **the
   assumptions it made** and findings outside its scope. If it returned `BLOCKED`, do not push:
   resolve whatever stopped it (this may require a corrective loop back to PLAN) and dispatch again.

4. **Two-stage review** of what it returned. In this order, because they are different questions:
   - **(a) Does it meet the spec?** → `Agent(subagent_type="ddw-module-verifier")` scoped to this
     block. Verifies that what got built is what the block asked for, no more and no less — **and
     that the TDD evidence is there**: the report must show the tests failing before implementation,
     with the assertions that broke. Missing or empty evidence = the block FAILS, however good the
     code looks. A test that never failed proves nothing.
   - **(b) Is it well built?** → `Agent(subagent_type="ddw-arch-auditor")` over the files it
     touched. Verifies conventions and architecture against `AGENTS.md`.

   If (a) fails → dispatch the implementer again with the correction. If (b) fails → same, with the
   violations pointed out. Maximum **3 rounds** per block; if it still fails on the third, stop and
   raise it with the user: the problem is probably in the spec, not in the code.

5. **Mechanical gates for the block:** `Skill(skill="ddw-test")` for the block's tests. **ALWAYS, in
   EVERY block** — do not assume that because you invoked it in the previous one you can run
   `jest`/`npm test` directly. See the self-check before running tests.
   - If it fails → go back to the implementer (max 3 attempts).
   - **Do NOT move to the next block while the tests fail.**

6. **Record the assumptions.** If the implementer declared assumptions, **show them to the user**
   before moving to the next block. An unreviewed assumption is a decision nobody made.

7. **Commit the block** with `Skill(skill="ddw-commit")`: its code and its tests, in one commit, with
   the tier's gitmoji. **One block = one commit** — the same rule
   `.ddw/rules/commits.instructions.md` states for every other unit of work.

   The block has just passed the two reviews and its tests; that is a state worth keeping. Leaving
   three blocks uncommitted so they can share one commit at the end means a session that stops after
   the second one loses both — which is the exact loss the per-phase commit exists to prevent, one
   level down. **The commit goes before the state update**, so an interruption between the two leaves
   work committed and a block to redo, never a block marked done with nothing on disk.

   The `commit` gate stays untouched here: only the closeout edge's commit sets it (see the note in
   `.ddw/rules/commits.instructions.md`).

8. **Update `.ddw-state.json`:** `block` → `"N/M"` (e.g. `"3/5"`, or `null` if it was the last).

9. **Report progress:** "Block N completed (N/M)."

> 🔎 **Why the implementer neither commits nor touches the state.** Its job is to write code inside a
> bounded scope and give an account of it. **The commit belongs to the orchestrator** — which commits
> once per block, at step 7, after the reviews it ran itself came back green — **and so does the
> state**. The invariant is who commits, not how often: if a subagent could move either, the state
> machine would break from the inside.

### Session Rule
The user can say "stop here" or close the session between blocks. Progress is recorded in the
state's `block`. On resume, work continues from the last incomplete block.

---

## If tier == FIX

### Direct Implementation

1. Read the fix-plan from `docs/ddw/specs/fix-{ticket}.md`.
2. Implement all the fix-plan's steps in sequence.
3. Write the specified tests. The **regression test comes first**: it must reproduce the bug and
   fail BEFORE the fix, then pass after it. That is the evidence the fix addresses the real cause.
4. **Verify the rollback plan:** confirm the fix-plan's rollback steps are still valid after the
   implementation.
5. Invoke `Skill(skill="ddw-validate-arch")`.
   - If it fails → fix and re-run (max 3 attempts).
6. Invoke `Skill(skill="ddw-test")`.
   - If it fails → fix and re-run (max 3 attempts).

> **Stability over elegance.** A FIX resolves a defect; it is not the moment to refactor.

---

## Closeout Sequence (MANDATORY, every tier that reaches CODE)

> **Where it goes next depends on the tier.** QUICK-FIX has no VERIFY phase: it
> transitions straight to **CLOSEOUT** (`CODE → CLOSEOUT`, gates `define`, `tests`,
> `sast`). FIX and FEATURE go to **VERIFY** (`CODE → VERIFY`, gates `tests`,
> `sast`). The graph is the authority; taking the other edge is a refused write,
> not a detour.

Once the WHOLE implementation is complete (all blocks or all steps):

### 1. Full test suite
Invoke `Skill(skill="ddw-test")` (the whole suite, not just the new tests).
- If it FAILS → fix. Do not advance. Max 3 attempts.
- If it PASSES → **write the run report** to `docs/ddw/reports/tests-{ticket}.md` and validate it:
  `python3 .ddw/scripts/validate_tests.py docs/ddw/reports/tests-{ticket}.md --tier <tier>`.
  The rules are `F-TEST-01` to `F-TEST-08` and `W-TEST-01` in
  `.ddw/rules/validation-rules.instructions.md` §6: the runner and the exact command, counts that
  add up, every failure named, three coverage numbers against a floor quoted from the project, every
  skip explained, one run per report, and zero failures. A PASSED run writes the receipt the `tests`
  gate demands.
- `gates.tests` = `true` only with that receipt on disk. DDW does not run your suite and the receipt
  does not say it did — it says the report of the run you did is complete enough to be read and
  re-run by someone else.
- **Re-closeout after a fix:** if you corrected something and need to revalidate the suite,
  **invoke `Skill(skill="ddw-test")` again** — do NOT run `npm run test:all`/`npx jest` directly.
  The re-closeout is NOT an exception to the rule.

### 2. Type checker / Lint
Run the project's type checker and linter (if they are configured in `AGENTS.md`, "Stack" section).
- If it FAILS → fix. Max 3 attempts.
- If it PASSES → record the result in the test report (`W-TEST-01` asks for it there, and F-VER-05
  will ask for it again in VERIFY) and continue to SAST.

Report format:
```
┌─────────────────────────────────────────────────────────┐
│  Type checker / Lint — [PASSED | BLOCKED]                │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  [Errors found, with file:line — description]            │
│                                                          │
│  Total: [N] errors                                       │
│  Next: [fix N errors | continue to SAST]                 │
└─────────────────────────────────────────────────────────┘
```

### 3. SAST — Static Security Analysis
Invoke `Skill(skill="ddw-security-sast")`.

**BLOCKING GATE.** If it finds vulnerabilities:
- Show the report to the user.
- Spawn an agent via the Agent tool with `subagent_type="ddw-sec-auditor"` for triage (true positive
  vs false positive). Do NOT read AGENT.md as a file.
- Fix the vulnerabilities confirmed as true positives.
- Re-invoke `Skill(skill="ddw-security-sast")`. Max 3 attempts.
- Only when it PASSES: add `"sast": true` to `gates`.

If it finds no vulnerabilities:
- `gates.sast` = `true`.

### 4. Transition

Only if `gates.tests` AND `gates.sast` are `true`:

Present the summary to the user:
```
┌─────────────────────────────────────────────────────────┐
│  CODE — Implementation complete                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Ticket: [ticket] — [title]                              │
│  Tier: [tier]                                            │
│  Blocks: [completed]/[total] (or N/A for a fix)          │
│                                                          │
│  Results:                                                │
│    ✅ /ddw-validate-arch: PASSED                         │
│    ✅ /ddw-test: PASSED ([X] tests)                      │
│    ✅ /ddw-security-sast: PASSED                         │
│                                                          │
│  Do you approve moving to the verification phase?        │
└─────────────────────────────────────────────────────────┘
```

> **Under `autonomy: "minimal"` this arrow does not wait.** The state is still
> written, the gates are still owed and still refused by the hook, and the
> closing box is still shown — what goes away is the pause for a confirmation of
> something a receipt already attests. Three things stop the run anyway, in
> either mode: a decision nobody wrote down, a corrective loop at its ceiling,
> and a corrupt state. See `.ddw/orchestrator.md` § Autonomy.

After the user approves:
1. **Commit whatever the closeout produced** with `Skill(skill="ddw-commit")`: the fixes the full
   suite, the linter or SAST demanded, with the tier's gitmoji.
   - **FEATURE:** each block was already committed at step 7 of its loop. This commit covers only
     what the closeout itself changed.
   - **FIX / QUICK-FIX:** there are no blocks, so this is the implementation's commit — code +
     tests, committed here because here is where it is green.
   - **If the working tree is clean**, commit nothing. The record is already on the branch; an empty
     commit to mark the phase is noise.
2. Update the state:
   - `phase` → `"VERIFY"`
   - Add an entry to `history`: transition CODE → VERIFY, **stamped with `ticket` and `tier`** (see `.ddw/rules/state.instructions.md`)

---

## Active Conventions

Follow these strictly during implementation:
- The project's architecture conventions ("Architecture conventions" section of `AGENTS.md`) for
  structure and patterns.
- `.ddw/rules/testing.instructions.md` for tests.
- `.ddw/rules/security.instructions.md` for secure coding practices.

---

**FORBIDDEN in this phase:**
- Modifying the spec/fix-plan
- Modifying the PRD
- Committing a block before its two reviews and its tests came back green. **The implementer
  subagent never commits at all** — the orchestrator does, one commit per block, plus whatever the
  closeout changed
- Creating PRs
- Skipping the closeout sequence (tests + SAST)
