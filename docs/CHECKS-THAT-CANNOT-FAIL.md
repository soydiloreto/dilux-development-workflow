# Checks that cannot fail

Generated against the suite by `scripts/kill_map_ledger.py`, and **compared** by
CI rather than trusted: this file is what somebody has already looked at, not a
report nobody regenerates.

Every line is a `bad "…"` of `scripts/verify_install.sh` that **no fault in
`scripts/mutate.py` provokes**. That does not prove it cannot fail — it proves
nothing measures whether it can. Either write a fault that makes it fire, or say
here why there is not one.

A check that cannot fail reports green because it has no other thing to say.

One of the lines below — `the method's prose claims something the repo does not
support` — is the whole of `scripts/lint_method.py` seen from here, and its
thirty-odd checks collapse into it. The same question, asked one level down, is
in [LINT-CHECKS-THAT-CANNOT-FAIL.md](LINT-CHECKS-THAT-CANNOT-FAIL.md).

<!-- 719 fault(s) across 24 shard(s) -->
- [ ] `$TOOL is missing — the checks that need it would skip, and a skip reads as a pass`
      **Environment.** It only fails when the tool is missing from the machine, and no mutation of the tree can provoke that. Its value lives in CI, which installs the tool on purpose — and there a skip is counted apart and never adds to a green.
- [ ] `node is missing — ${f#$SELF/} was NOT parsed; that is a gap, not a pass`
      **Environment.** It only fails when the tool is missing from the machine, and no mutation of the tree can provoke that. Its value lives in CI, which installs the tool on purpose — and there a skip is counted apart and never adds to a green.
- [ ] `python < 3.11 — the Codex TOML checks would skip in silence`
      **Environment.** It depends on the interpreter version, which no mutation changes.
- [ ] `pyyaml is missing — frontmatter is the contract every tool reads; it must be validated`
      **Environment.** It only fails when the tool is missing from the machine, and no mutation of the tree can provoke that. Its value lives in CI, which installs the tool on purpose — and there a skip is counted apart and never adds to a green.
- [ ] `the commit-gate fixture never committed: the three checks below measure the fixture, not the gate`
      **Fixture guard.** The two conditions that make it fail — `commit.gpgsign` and the git identity — are neutralised by the fixture itself two lines earlier, and nothing in this repo installs git hooks. No product path can light it.
- [ ] `fixture: IDLE->CLASSIFY failed and the three checks below measure nothing`
      **Fixture guard.** It fires only when the prose-gates fixture cannot take the one edge the graph always allows (IDLE→CLASSIFY, no gates, no receipts) — a broken helper, not a weakened gate. Every fault that breaks the helper that broadly is already killed by the FSM section's own checks before this line runs, so no fault reaches it with anything left to say.
- [ ] `the review gate refuses the marker even with both verdicts on disk`
      **Inverse guard.** It fails only if `block_review_missing` starts refusing a review file that carries both a `verifier:` and an `arch:` line — over-refusal, the direction no fault in the list pushes: every mutation of that gate removes a refusal rather than inventing one. Its value is catching a future edit that tightens the parse (a stricter regex, a case-sensitivity slip) and quietly turns the mandatory advance into a wall people route around.
- [ ] `a row said done with no MERGED child PR at the forge`
      **Companion-success guard.** It fires only if `update-row --status done` EXITS ZERO without the forge confirming the child's merge. The "a row says done on anyone's word" fault cannot reach it: with the check silenced the fixture's run still fails downstream (the shim's clone holds no index), and the refusal-shape assert above fires first. Its value is catching a future edit that makes the whole done-path succeed in silence.
- [ ] `a DIRTY worktree was closed — uncommitted work removed with the forge's blessing`
      **Companion-success guard.** It fires only if `close` EXITS ZERO on a dirty worktree. The "a dirty worktree is removed anyway, work and all" fault cannot reach it: git itself refuses to remove a tree with modified or untracked files unless forced, and nothing in the script says `--force` — under that fault the run still dies at git's own door, and what that fault provably fires is the sibling check (a refusal that no longer names the uncommitted file). Its value is catching a future edit that forces the removal.
- [ ] `ticket_worktree open failed on a plain repo: $(tail -1`
      **Fixture guard.** This arm reports the fixture's own scaffolding failing — git worktree support missing, the seed clone broken — not a product refusal: `open` has no refusal path on a healthy plain repo. Every product behavior of `open` is asserted in the ok-arm beside it, and the fault that bends `open` (the worktree born at the standing tree instead of origin) fires that arm's check, never this one.
- [ ] `list failed on a healthy pair of trees: $(echo`
      **Fixture guard.** This arm reports `list` itself dying on a healthy fixture — scaffolding, not product: every product behavior of `list` (each tree named, with the ticket and phase its own state declares) is asserted in the ok-arm beside it, and the "the list stops reading each tree's own state" fault fires that arm's check, never this one.
