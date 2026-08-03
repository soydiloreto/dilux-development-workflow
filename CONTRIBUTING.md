# Contributing

Three things run before anything is merged. Run them locally; CI runs them too.

```bash
python3 scripts/lint_method.py     # the prose against the graph and the catalog
bash scripts/verify_install.sh     # behaviour, through the hooks each tool runs
python3 scripts/mutate.py          # breaks DDW on purpose; the suite must notice
```

`docs/DEVELOPMENT.md` explains what each of the three catches and why it exists.

## The rule that matters most

**A change to enforcement ships with a check that fails without it, and a
mutation so it cannot come back quietly.**

Not a check that passes with the fix — one that goes *red* when the fix is
removed. Write it first and watch it fail. Half the defects this project has had
were sitting under a green check that passed for a different reason than the one
it claimed.

If a mutation survives, the fix is a new check. Never a smaller mutation list,
never a gentler mutation. The one exception is an *equivalent mutant* — a change
that provably cannot alter behaviour — and that one gets re-aimed, not deleted.

## Adding a tool

Write `adapters/<id>/adapter.json` plus that tool's hook scripts. Nothing else
changes: the installer discovers adapters, and `ddw/` stays byte-identical.

An adapter contains **no logic**. It declares two things — where its tool looks
for skills and agents, and what dialect its hooks speak — and delegates every
decision to `ddw/scripts/hook-gate.py`. An adapter that decides something is not
an adapter; it is a second copy of the method, and the copies drift.

Every claim a recipe makes about its tool needs the documentation that supports
it, cited in the pull request. Assuming an envelope shape and then writing the
test from the same assumption produces an adapter that agrees with its test and
with nothing else — that has happened, more than once.

Then work through `scripts/acceptance.md` against the live tool and report what
you saw. Until that is done the adapter is *verified at the boundary, unverified
in the wild*, and the README will say so by name.

## Field reports

The most useful contribution is not a patch. It is: this tool, this version, on
this date, and which of the six acceptance checks failed. That is what tells us
a tool changed its contract.

## Versions

Two numbers move, and they answer different questions. Both are checked, so
neither can quietly stop being true.

**The product's — one number, every tool.** It lives in `CHANGELOG.md` and in the
five manifests (`.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`,
`gemini-extension.json`, `package.json`), and they must all say the same thing.

That is a decision worth stating, because the tempting alternative is to version
each wiring on its own. DDW is one product shipped six ways: `ddw/` is
byte-identical everywhere and an adapter is a recipe, not software with a life of
its own. If Claude read 1.0.5 and Copilot 1.0.2, nothing would tell you they came
from the same commit, a bug report would stop mapping to a place in the history,
and someone running two tools would have no way to know they are running the same
thing. So they move together, even when a change touched only one of them.

**Each rule file's — its own.** Every `ddw/rules/*.instructions.md` carries a
`version:` in its frontmatter. Change the file, move the number.

### What owes a bump

| You changed | Bump |
|---|---|
| Anything under `ddw/`, `adapters/`, `skills/`, `agents/`, the installers, a manifest | **The product**, in all five files, plus a `CHANGELOG` entry |
| A rule file | **That file's own version**, as well as the product's |
| `scripts/`, `docs/`, `README`, CI | Nothing — editing a test changes nothing anyone installs |

That last row is the boundary, and it is drawn there on purpose: a rule that
demands a release for a typo in a comment teaches people the number means
nothing, and then they stop reading it.

Pick the level the way semver says: **patch** for a fix that leaves the method
alone, **minor** for a new capability, **major** for a breaking change to the
method itself — the phases, the graph format, the gate names, the artifact
layout, the state schema, the adapter recipe schema. `CHANGELOG.md` says which of
those the promise covers.

### Why it is enforced rather than asked for

A version nobody checks is worse than no version, because absent tells you
nothing and stale tells you something false. This repository has been on both
sides of that: it shipped a rule at `2.0.0` while the product said `1.0.0`, and
it carried a third number in `ddw/rules/README.md` that no code ever compared to
anything, so it drifted for as long as it existed.

And the cost is not only tidiness. Claude Code and Copilot CLI **cache a plugin
by its version**: ship a fix without moving the number and the tool has no signal
that anything changed, so it keeps serving the file that had the bug. That was
measured here, on a live install, which is why the rule exists in this shape.

`scripts/check_versions.py` enforces all of it, and CI runs it on pushes as well
as pull requests — a repository whose own work lands on `main` would otherwise be
exempt from the rule it ships to everybody else.

```bash
python3 scripts/check_versions.py                 # the numbers agree with each other
python3 scripts/check_versions.py --since HEAD~1  # …and the change earned them
```

## Style

English, present tense, no first person. Comments explain why a guard exists —
without that, the next reader deletes it as redundant. They do not narrate the
history of the project.

## Using AI to contribute

Assumed, not merely tolerated — this is a tool for driving coding agents, built
with one. What it costs you is spelled out in [`docs/AI-POLICY.md`](docs/AI-POLICY.md),
and two rules there catch almost everyone:

- **Never make a failing check pass by weakening it.** Not `EXPECT_CHECKS`, not a
  deleted mutation, not a softened fixture. A model told to "make CI green" goes
  for exactly this, and it is the one thing this repository cannot tolerate.
- **No prompt-injection vectors, especially in `ddw/`.** That directory is copied
  verbatim into other people's repositories and loaded into their agents. There
  is no sandbox between a line you write there and a stranger's session.
