# Lint checks that cannot fail

Generated against `scripts/lint_method.py` by `scripts/lint_kill_map.py`, and
**compared** by CI rather than trusted.

The suite has one check for the whole prose linter, so in
[CHECKS-THAT-CANNOT-FAIL.md](CHECKS-THAT-CANNOT-FAIL.md) every check inside it
collapses into a single line: while any fault keeps the linter red, a check of
the linter that stopped finding what it was written for still reports green.
This file is that question asked one level down.

Every line is a `fail(…)` of `lint_method.py` that **no fault in
`scripts/mutate.py` provokes**. Either write a fault that makes it fire, or say
here why there is not one.

<!-- 56 site(s), 234 fault(s) measured -->

- [ ] `check_boot_reads_every_state_field[0]`
      **Shape guard, and the shape is a whole table.** It fires when
      `ddw/rules/state.instructions.md` exists and NOT ONE field can be read
      out of it — the table stopped having the `| \`field\` | …` shape — and
      that is all of its rows at once, not one line. A one-edit fault cannot
      express it, and one that rewrites the whole table measures the fault,
      not the check. The neighbouring case — the file outright missing — does
      have a fault and exits through another branch.
- [ ] `check_rationale[1]`
      **Shape guard, same story.** It demands `docs/RATIONALE.md` exists with
      NO numbered decision at all: today that is twenty `## N.` headings, so
      the fault would have to delete every one. The file being missing is
      covered by the previous site, which does have a fault.
- [ ] `check_autonomy_prose_matches_the_hook[0]`
      **Defensive branch about the instrument, not the product.** It fires if
      `ddw/scripts/validate-transition.py` cannot be imported, which is the
      condition under which no linter check measures anything and the whole
      suite is already red for a hundred other reasons. A fault provoking it
      measures the fault.
- [ ] `check_autonomy_prose_matches_the_hook[1]`
      **It asks for a fault in a `.py`, and the map skips those by
      construction** (`SKIP_EXT = (".py",)` in `scripts/lint_kill_map.py`:
      this check is the linter's first that reads code and not prose). What
      the site asserts — that the guard refuses the second arrow under
      `assisted` — IS measured, one layer down, by
      `test_dos_flechas_en_un_turno_son_rechazadas`. What is left without a
      fault is the linter's WARNING, not the behaviour.
- [ ] `check_autonomy_prose_matches_the_hook[2]`
      **Shape guard.** It fires when `ddw/orchestrator.md` has no
      `## Autonomy` section at all — deleting the whole section, not one line.
      A one-edit fault cannot express it, and one that deletes it measures the
      fault.
- [ ] `check_autonomy_prose_matches_the_hook[4]`
      **The same ceiling as `[1]`**: the reverse direction of the same pair
      (the prose says the hook exempts `minimal` and the guard refuses anyway)
      also needs to touch the `.py` the map skips. The behaviour is measured
      by `test_en_minimal_las_flechas_no_esperan`.
- [ ] `check_minimal_exemption_reaches_the_phase_rules[0]`
      **Shape guard, and the shape is six routers at once.** It fires when
      NO orchestrator exit declares itself exempt under `minimal`, which is
      six edits in one fault. The one that matters — a phase that IS exempt
      whose rules file does not say so — is the neighbouring site, and that
      one has its fault.
