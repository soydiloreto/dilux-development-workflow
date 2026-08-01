## What this changes, and why

<!-- The problem first. If it fixes a defect, say what the defect let through. -->

## What proves it

Every behaviour change here ships with something that fails without it. That is
not ceremony: prose is most of this product, so a rule nothing checks is a rule
that rots quietly — and `docs/RATIONALE.md` §10 explains why the mutation matters
as much as the check.

- [ ] A check in `scripts/verify_install.sh`, and `EXPECT_CHECKS` bumped on purpose
- [ ] A mutation in `scripts/mutate.py` that this change kills — **and that survives without it**
- [ ] `python3 scripts/mutate.py` is still 100%

<!-- Which check, which mutation. If neither applies (docs, typo), say so. -->

## Ran

- [ ] `bash scripts/verify_install.sh`
- [ ] `python3 scripts/lint_method.py`
- [ ] `python3 scripts/check_versions.py`
- [ ] A rule file changed → its `version:` bumped (CI enforces this)

## Two traps worth re-reading before you tick the boxes

- **A check can pass for the wrong reason.** Build the fixture so exactly one
  reason is available to it, then confirm it goes red when you remove the fix.
- **A mutation that cannot fail proves nothing.** If it survives, the hole is a
  missing check, not a mutation to soften.
