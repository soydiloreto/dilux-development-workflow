---
applyTo: '**'
version: 1.1.0
---

# Testing Conventions

*(Adapt to the specific stack detected in the CLASSIFY phase)*

---

## Rule #-1 — Test first, always

**The test is written before the code it tests. Every tier, every block, no exceptions.** This is
not conditional on the project's conventions: it is how this pipeline works.

The test must be **seen to fail** before the implementation exists. A test that passes before you
write anything is asserting something that was already true — it documents the status quo, not the
change. The implementer records that failure (which tests, which assertion) in its report, and
`ddw-module-verifier` fails the block if the evidence is missing.

What "the test" means depends on the tier:

| Tier | The test that has to fail first |
|---|---|
| FEATURE | the tests the block's spec lists |
| FIX | the regression test that reproduces the bug |
| QUICK-FIX | the regression test named in the fix-brief |

Why it is enforced by evidence rather than by trust: a green suite looks exactly the same whether
the tests came before the code or after. The failure you observed is the only thing that
distinguishes them.

---

## Rule #0 — Never Operate on Real Data

**NON-NEGOTIABLE RULE.** Every test that modifies data MUST:

1. **Create its own data** in setup (beforeAll/beforeEach/setUp).
2. **Only operate on data the test created** — NEVER use existing environment data for destructive
   operations.
3. **Clean up afterwards** in teardown (afterAll/afterEach/tearDown).

If the test cannot create its data (external service unavailable), destructive operations MUST be
skipped with a log: "SKIP: no own data was created — nothing modified."

Read-only tests (GETs/queries) MAY use existing data as a fallback.

## Framework and Runner *(adapt)*

| Field | Value |
|-------|-------|
| Testing framework | *(detected in CLASSIFY)* |
| Run command | *(detected in CLASSIFY)* |
| Configuration | *(detected in CLASSIFY)* |

## Test Structure *(adapt)*

- Unit tests: next to the source file (co-located) or in `__tests__/`
- Integration tests: in `tests/integration/`
- E2E tests: in `tests/e2e/`

## Naming Convention

- File: `[source-name].test.[ext]` or `[source-name].spec.[ext]`
- Describe blocks: the module/function name
- It blocks: "should [expected behavior]"

## Structure of Each Test

```
describe('<module>/<function>')
  beforeEach: reset state (mocks, data)

  describe('happy path')
    it('should <expected action>')
      // Arrange — Act — Assert

  describe('input validation')
    it('should reject <invalid input>')

  describe('edge cases')
    it('should handle <edge case>')
```

## Testing Pyramid (in priority order)

1. **Smoke tests** — do the routes/endpoints exist and respond?
2. **Unit tests** — pure business-logic functions.
3. **Validation tests** — valid and invalid inputs against schemas.
4. **Integration tests** — endpoints with a simulated request.
5. **Isolation tests** — verify one user/tenant cannot see another's data.
6. **Error tests** — error scenarios documented in the PRD.

## Minimum Coverage

| Metric | Minimum |
|--------|---------|
| Line coverage | 80% |
| Branch coverage | 80% |
| Function coverage | 80% |

- Business logic should aim for 90%+.
- NEVER lower coverage with a new change.

## Mocking

- Mock the I/O layer (DB, HTTP, filesystem) in unit tests.
- Minimal mocking: only what the test needs.
- NEVER mock the unit under test.
- Prefer dependency injection over monkey-patching.

## General Rules

| Rule | Reason |
|------|--------|
| One assert (or related group) per test | Makes it obvious what failed |
| Descriptive names | "should create a user with valid data", not "test1" |
| Test behavior, not implementation | A refactor should not break the test |
| Tests do not depend on each other | Each test can run alone, in any order |
| Do not test third-party code | Test your own integration with it |
| Every fix needs a regression test | The test must reproduce the bug BEFORE the fix |

## Test Traceability

- **Every AC in the PRD must have at least one test validating it** (F-VER-01 in
  `.ddw/rules/validation-rules.instructions.md`). Checked in the VERIFY phase.
- **Every test listed in the spec must exist and pass** (F-VER-06 in
  `.ddw/rules/validation-rules.instructions.md`). Tests in the spec are approved commitments.
- **Every endpoint/function that accepts input must have at least one sad-path test** (F-VER-04 in
  `.ddw/rules/validation-rules.instructions.md`). Happy-path-only tests are not enough.

## Notes for the Agent

- Every block in the spec must have at least one test.
- Every fix must have a regression test (F-SPEC-14 in
  `.ddw/rules/validation-rules.instructions.md`).
- Run `ddw-test` after each block, not only at the end.
- If a test fails, work out whether it is a bug in the test or in the code before fixing.
- Coverage and test-completeness validation rules are centralized in
  `.ddw/rules/validation-rules.instructions.md` (sections 2 and 5).
