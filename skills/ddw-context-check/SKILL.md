---
name: ddw-context-check
description: >
  Compares what the repository already declares about how it is built — linters, type checkers, CI,
  pre-commit, runtime versions — against what the tool's context file tells DDW. Reports the
  commands DDW would otherwise run wrong. Never blocks.
  Trigger: /ddw-context-check, and once per ticket in CLASSIFY.
---

# Skill: /ddw-context-check

## Description

DDW runs commands: the test suite, the linter, the type checker. It learns them from the context
file (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) — and when that file does not mention one, DDW does not
run it. The result is code that passes every gate and then fails your CI, or commits that your
`pre-commit` hook rejects for reasons the agent has no way to explain.

This skill compares the two: **what the repo already says about how it is built**, against **what
the context file told DDW**. It reports the difference and proposes a one-line fix for each.

It is **read-only until you say otherwise**, it **never blocks**, and it writes to exactly one file
— the context file — and only with your approval.

## What it must NOT report

This restriction is the skill, not a caveat on it.

**It reports only knowledge the agent cannot discover on its own** — the commands DDW is about to
run. It never proposes prose, conventions, architecture, style guidance, or anything the agent can
find by reading a file at the moment it needs it.

The reason is evidence, not taste. A study across 138 real repositories found that repository
context files produced **no improvement in agent task success rate while adding over 20% to
inference cost**, with LLM-generated ones actively hurting; the authors' conclusion was that these
files should be minimal rather than comprehensive. A skill that grows the context file is therefore
not a neutral act — without this restriction, this one becomes the problem that study describes.

> Recorded, with its sources, as decision 8 in `docs/RATIONALE.md`.

## Inputs

- The context file in use (`AGENTS.md`, `CLAUDE.md` or `GEMINI.md`) — its "Stack" and commands.
- The repository root and its configuration files (read-only).

## Execution Protocol

1. Read the context file. Note every command it declares and every `ddw:declined` marker.
2. Look for each piece of evidence below. **Evidence means a file that exists** — never an
   assumption about what this project ought to use.
3. Report only the gaps, and only ones not already declined for this ticket.

| Evidence in the repo | Gap, if the context file does not declare it | Why it costs something |
|---|---|---|
| `.pre-commit-config.yaml` | no pre-commit step | Your hook rejects the agent's commits and it cannot say why |
| A CI workflow (`.github/workflows/*.yml`, `.gitlab-ci.yml`, …) | a command CI runs that DDW does not | CI is the repo's real contract. Anything it runs that DDW does not, the PR discovers |
| Linter config (`[tool.ruff]`, `.eslintrc*`, `.golangci.yml`, …) | no lint command | Code that passes the gates and fails style |
| Type checker (`[tool.mypy]`, `tsconfig.json` with `strict`, …) | no typecheck command | Type errors no test catches |
| Test runner config / a `tests/` directory | no test command, or a different one | `ddw-test` runs the wrong thing, or nothing |
| A coverage threshold configured in the repo | it differs from the 80% in `.ddw/rules/testing.instructions.md` | Two thresholds, and the stricter one is a surprise |
| `.nvmrc`, `.python-version`, `.tool-versions` | no runtime version | Runs against the wrong version |
| A lockfile (`package-lock.json`, `poetry.lock`, `uv.lock`, …) | no install command | The agent guesses the package manager |

## Also: the sections the method reads

The context file is not only commands. The method reads it by **heading**, and a heading that is not
there is a lookup that silently finds nothing:

| Heading | Read by |
|---|---|
| `## Stack` | CLASSIFY, CODE, `ddw-test`, `ddw-security-sast`, `ddw-threat-modeling`, `ddw-create-prd`, `ddw-create-adr`, `ddw-help`, `ddw-sec-auditor` |
| `## Architecture conventions` | PLAN, CODE, `ddw-validate-arch`, `ddw-arch-auditor` |
| `## Code conventions` | `ddw-arch-auditor` |
| `## What NOT to do in this project` | `ddw-arch-auditor` |
| `## Domain glossary` | DEFINE, PLAN |

`AGENTS.md` is copied from DDW's template **once**, when the installer finds none. Three situations
leave it without these, and all three are ordinary:

- **The repo already had its own `AGENTS.md`.** The template is never applied — correctly, it is
  their file — so none of these headings exist and nobody was told.
- **A later version of DDW added one.** The template grew; the installed file did not, because
  nothing outside the `BEGIN DDW` block is managed.
- **There is no `AGENTS.md` at all**, which is the ordinary state of a **plugin** install: the
  installer never ran, so nothing was copied. Report the FILE, not each heading in turn — a list of
  six missing headings for a file that does not exist reads as six problems instead of one — and
  point at CLASSIFY Step 1, which offers to create it with the project's own content. Never write
  DDW's own material into it: under a plugin the repo is meant to come away with nothing of DDW's
  in it.

So report a missing heading like any other gap, with **the heading and one line saying what reads
it**. Propose the heading, empty, and nothing else: what goes underneath is the user's to write, and
writing it for them is the bloat this skill exists to avoid. For `## Stack` specifically, CLASSIFY
already knows how to detect a stack from the repo's config files and offer the text — point at that
rather than duplicating it.

## Output Format

```
┌─────────────────────────────────────────────────────────┐
│  /ddw-context-check — [N] gap(s)                         │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  1. Lint is configured but DDW does not run it           │
│     Evidence: pyproject.toml:41 — [tool.ruff]            │
│     Add to AGENTS.md → Stack:                            │
│       Lint: ruff check .                                 │
│                                                          │
│  2. CI runs a command DDW does not know                  │
│     Evidence: .github/workflows/ci.yml:22 — mypy app/    │
│     Add to AGENTS.md → Stack:                            │
│       Typecheck: mypy app/                               │
│                                                          │
│  Add them? (all / by number / none)                      │
└─────────────────────────────────────────────────────────┘
```

Every finding carries **the evidence with its `file:line`, and the exact line to add**. A finding
the user has to go and investigate is a finding they will skip.

**If there are no gaps, say so in one line and stop.** A panel that appears every ticket with
nothing in it is how people learn not to read the panel.

## Updating the context file

Only after approval, and only the context file:

- **Accepted** → the declared command is added to its Stack section. Nothing else is written: no
  prose, no explanation, no heading the file did not already have.
- **Declined** → a marker is written so the full panel does not interrogate you again:

  ```
  <!-- ddw:declined FEAT-001 lint typecheck -->
  ```

**A decline is per ticket, not forever.** The next session mentions it in one line —
*"2 recommendations declined — `/ddw-context-check` to see them"* — and nothing more. A "never
again" that silently disappears is worse than a question: the day the gap actually costs you
something, nothing will be there to say it was known. And re-asking in full every session is how a
useful check gets turned off.

Never write to `pyproject.toml`, `.pre-commit-config.yaml`, CI workflows or any other configuration.
This skill teaches DDW what your repo already says; it does not change what your repo says.

## PASS/FAIL criteria

- N/A. This skill has findings, not a verdict. **It never sets a gate and never blocks a
  transition.** DDW cannot know that your project ought to run a linter — only that it has one
  configured and DDW was not told. Reporting a fact is useful; blocking on an inference is not.

## Updating .ddw-state.json

- NONE.

## Language

Write the findings in the language the user is working in. Keep commands, file paths and the
`ddw:declined` marker verbatim.
