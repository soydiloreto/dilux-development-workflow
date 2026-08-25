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

<!-- 541 fault(s) across 25 shard(s) -->
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
