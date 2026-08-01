# Example: a FIX flow

## Scenario
An endpoint returns 200 instead of 404 when the resource does not exist.

## Without DDW (before)
The developer tells the agent "fix this bug" and the agent:
1. Writes the fix straight away, with no root cause analysis
2. Does not check existing PRDs
3. Writes no regression tests
4. Commits without conventions
5. Runs no SAST

## With DDW (after)
1. **CLASSIFY**: classifies it as FIX, assigns FIX-001
2. **DEFINE**: reviews the PRDs, finds no gap, writes the RCA (the branch `fix/FIX-001-404-missing`
   was created back in CLASSIFY, before anything was written to disk)
3. **PLAN**: produces a lightweight fix-plan with steps and a regression test
4. **CODE**: implements the fix, writes the regression test, passes SAST
5. **VERIFY**: verify-module passes
6. **RELEASE**: commit with gitmoji, PR with AI attribution

## Rules applied
- `.ddw/rules/classify.instructions.md` — tier classification
- `.ddw/rules/branches.instructions.md` — branch naming
- `.ddw/rules/testing.instructions.md` — mandatory regression test
- `.ddw/rules/commits.instructions.md` — Gitmoji + Conventional Commits format
- `.ddw/rules/security.instructions.md` — the SAST gate
