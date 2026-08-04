---
name: ddw-test
description: >
  Runs the project's tests, generating missing ones when needed. A blocking gate.
  Trigger: /ddw-test, during DDW's CODE phase.
---

# Skill: /ddw-test

## Description
Runs the project's tests. Generates missing tests where needed. A blocking gate.

## Inputs
- Scope: an explicit argument, the modified files (`git diff`), or the full suite.
- `.ddw/rules/testing.instructions.md` for the conventions.
- The spec/fix-plan, to know which tests are expected.
- The project's test runner: the "Stack" section of `AGENTS.md`.

## Execution Protocol

1. **Detect the scope:**
   - With an argument → run that module's/file's tests.
   - Post-block in CODE → run the block's tests.
   - In the closeout sequence → run the full suite.

2. **Check that the tests exist:**
   - For each modified logic file, check whether a corresponding test exists.
   - If it does not → generate one following `.ddw/rules/testing.instructions.md`.
   - **Rule #0 applies to any test you generate:** a test that modifies data creates its own data in
     setup, only operates on what it created, and cleans up in teardown. Never destructive
     operations against existing environment data.

3. **Run the tests:**
   - Use the test runner command declared in `AGENTS.md` ("Stack" section).
   - Capture the full output.

4. **Analyze the results:**
   - On failure: work out whether the bug is in the test or in the code.
   - Fix and re-run. Max 3 attempts before reporting to the user.

## Output Format

```
┌─────────────────────────────────────────────────────────────┐
│  /ddw-test [scope] — [PASSED | BLOCKED]                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [file.test.ext]:                                            │
│    ✅/❌ [test name]                                         │
│                                                              │
│  Tests generated: [N]                                        │
│                                                              │
│  ────────────────────────────────────────────────────────────│
│  Total: X passed, Y failed                                   │
│  Coverage: XX% lines, XX% branches (if available)            │
│  Next: [recommended action] (attempt N/3)                    │
└─────────────────────────────────────────────────────────────┘
```

## PASS/FAIL criteria
- **PASSED:** 0 failing tests → `gates.tests` = `true`.
- **BLOCKED:** 1+ failing tests → fix and re-run.

> **The run leaves a report, and the report is validated.** Write
> `docs/ddw/reports/tests-{ticket}.md` — runner, exact command, total/passed/failed/skipped,
> line/branch/function coverage, the floor and where it comes from, every failure by test ID, every
> skip with a reason, the lint result — then run
> `python3 .ddw/scripts/validate_tests.py docs/ddw/reports/tests-{ticket}.md --tier <tier>` and
> **paste its output VERBATIM**, every rule ID, on every run including a re-validation of something
> unchanged. A PASSED run writes the receipt the `tests` gate demands; without it, CODE→VERIFY
> refuses.
>
> **DDW does not run your suite, and that receipt does not say it did.** It says the account of the
> run is complete: reproducible, arithmetically possible, named where it failed, measured against a
> floor the project set rather than one the report chose. The numbers stay yours. What they can no
> longer be is absent.

### The report, in the shape the validator reads

Everything above was prose, and a report has to be parsed. Three plausible renderings of the same
run were refused for their layout rather than their content — a coverage table whose rows are
labelled `Line`, a lint result under its own heading, a hyphenated `sad-path`. The parser accepts
all three now, and this is the shape it was written for:

```markdown
# Test run {ticket}

| Field | Value |
|---|---|
| Runner | pytest 8.2.0 |
| Command | `pytest -q --cov=app --cov-report=term` |
| Total | 42 |
| Passed | 42 |
| Failed | 0 |
| Skipped | 0 |
| Line coverage | 91% |
| Branch coverage | 84% |
| Function coverage | 88% |
| Coverage floor | 80% (AGENTS.md, "Testing") |
| Lint | `ruff check .` — clean, 0 findings |

## Failures
(none)

## Skips
(none)
```

When the run is red, every failure goes under that `## Failures` heading, one per line, **by test
name** — `test_email_invalido_devuelve_422 — expected 422, got 500 (app/routes/public.py:41)`. That
is the list the fix loop works from, and a count with no names is refused by F-TEST-03. A red run
does not earn the gate either way (F-TEST-08): the report is complete, the suite is not green, and
those are two different sentences.

Counts that add up, a command someone else can run, every failure by test ID, every skip with a
reason, and the floor quoted from the project rather than chosen here. A report missing any of those
is refused by a rule that names it.

> This skill is a **runner**, not an artifact validator: it reports pass/fail. Test *quality*
> (coverage thresholds, AC traceability, sad paths) is evaluated in the VERIFY phase by
> `ddw-verify-module`, against §5 of the rule catalog. A green suite here does not mean the tests
> are good enough — it means they pass.

## Updating .ddw-state.json
- `gates.tests` → `true` on PASS in the closeout sequence.

## Language

Write the report in the language the user is working in.
