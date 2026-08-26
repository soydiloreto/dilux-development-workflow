# AGENTS.md — the one file DDW needs you to write

Everything DDW does, it does inside your repository. It brings its own method, its own gates and its
own wiring. The one thing it cannot bring is **what your project is** — and that is what `AGENTS.md`
holds.

Get this file wrong and nothing crashes. The pipeline runs, the gates pass, and the agent builds
against a project it never learned anything about. That is why this page exists.

---

## Why this file and not your tool's

`AGENTS.md` is an [open standard](https://agents.md/) — a plain Markdown file at the repo root
holding the operational context an AI coding agent needs. It was formalised in 2025 with OpenAI,
Google, Cursor and Factory, and donated to the Linux Foundation's Agentic AI Foundation in December
2025. Codex, Copilot, Cursor and OpenCode read it natively.

DDW keeps your context there, and not in `CLAUDE.md`, for one reason: **it is the same file for every
tool**. Port the pipeline from Claude to Copilot and your stack, conventions and glossary come along
untouched. That is the same reason `.ddw/` is byte-identical across the six adapters.

---

## Who writes what

`AGENTS.md` has two kinds of content, and they belong to different owners.

| | Owner | What happens on an upgrade |
|---|---|---|
| Everything outside the markers | **You** | Never read, never moved, never rewritten |
| The `<!-- BEGIN DDW -->` … `<!-- END DDW -->` block | **DDW** | Replaced with the current version |

**Do not edit inside the block.** Its first line says so. On the next `install.sh` it is replaced,
and your edit is gone — and unlike most losses, this one is silent.

Everything else in the file is yours, forever. DDW never touches it.

---

## Which file gets the block

It depends on what your tool reads. This is worth knowing, because it is the difference between the
pipeline having your context and not having it.

**DDW's instructions live in `AGENTS.md`, always** — whatever tool you installed, and however many.
One file, one answer to "where are DDW's instructions?", and nothing to move when you port the
pipeline to another agent.

| Tool | Reads | What it gets |
|---|---|---|
| Codex CLI · Copilot CLI · Cursor · OpenCode | `AGENTS.md` natively | nothing else — the block is already in the file they read |
| Claude Code | `CLAUDE.md` | a four-line pointer |
| Gemini CLI | `GEMINI.md` | the same four-line pointer |

The pointer is the whole file:

```markdown
<!-- BEGIN DDW (managed by DDW — do not edit by hand) -->
@AGENTS.md
@.ddw/orchestrator.md
<!-- END DDW -->
```

No prose, no duplicated instructions, nothing to keep in step. Claude and Gemini do not read
`AGENTS.md` on their own, so the first import is what brings your context in; without it the pipeline
runs knowing nothing about your project.

> **Why is `@.ddw/orchestrator.md` there and not inside `AGENTS.md` with the rest?** Because it would
> then be reached through a *nested* import — `CLAUDE.md → AGENTS.md → orchestrator`. Claude
> documents nested imports (five deep) and would manage it. Gemini documents `@file.md` and says
> nothing about nesting. Loading the state machine is not the place to rely on undocumented
> behaviour: it would boot on one tool and silently not on the other. One hop from the root works
> everywhere, and costs one line.

---

## The headings the method looks up by name

DDW does not read `AGENTS.md` as one blob. Specific phases look up specific headings:

Two of them are cited by name in the method's own instructions, so a phase goes looking for them.
The other three are read by whoever is doing the work — they are in the template, and
`/ddw-context-check` reports them missing, but no phase resolves them. The distinction is here
rather than implied, because a table that lists five and enforces two teaches you to expect more
than you get.

| Heading | Who reads it | Looked up by name? | What breaks without it |
|---|---|---|---|
| `## Stack` | CLASSIFY, CODE, `ddw-test`, `ddw-security-sast`, `ddw-threat-modeling`, `ddw-create-prd`, `ddw-create-adr`, `ddw-sec-auditor` | **yes** | The pipeline does not know your language, test runner or linter. It guesses, or runs nothing |
| `## Architecture conventions` | PLAN, CODE, `ddw-validate-arch`, `ddw-arch-auditor` | **yes** | The architecture audit has no standard to audit against, so it passes |
| `## Code conventions` | whoever is reviewing | no | Same, one level down — but nothing goes looking for it |
| `## What NOT to do in this project` | whoever is reviewing (`/ddw-context-check` lists it) | no | Your hard-won "never do X here" is unknown, and X gets done |
| `## Domain glossary` | whoever is writing the PRD or the spec | no | The PRD and the spec invent names for things you already named |
| `## Repo family` | CLASSIFY (Step 1.2) | **yes** | The repo is treated as standalone: no multi-repo scope question, no seam warnings, no family initiative — which is also exactly what its ABSENCE means on purpose. This heading IS the mono/multi switch |

**The `## Repo family` section**, for a repo that is part of one, carries four facts and nothing
else — the family's name, the workspace repo (`owner/repo`, cloned as a sibling), what this repo
provides, and who consumes it / what it consumes:

```markdown
## Repo family

| Field | Value |
|---|---|
| Family | tienda-demo |
| Workspace | acme/tienda-workspace |
| Provides | REST API /api/v1 (facturación) |
| Consumed by | tienda-bff |
| Consumes | none |
```

Keep it to the seams other repos actually touch. It is a declaration, not a contract: it feeds the
scope question in CLASSIFY, and nothing verifies it — which is why it stays one small table instead
of a system map that would rot.

**A missing heading fails quietly.** The lookup finds nothing and the phase carries on. Nothing goes
red. That is the whole hazard of this file, and it is why the installer and `/ddw-context-check` both
report the ones that are absent.

---

## The two situations that leave you without them

`AGENTS.md` is created from DDW's template **once** — only when the installer finds no `AGENTS.md` at
all. After that it is yours and DDW never restructures it. So:

**1. You already had your own `AGENTS.md`.** The template is not applied — correctly, it is your
file. You get the DDW block appended at the end and none of the headings. The installer says so:

```
✓ AGENTS.md   already exists (your content kept as it is)
⚠ AGENTS.md   is missing headings the method reads:
                ## Stack
                ## Architecture conventions
                ## Domain glossary
```

**2. A later version of DDW started reading a new heading.** Your file was written before it existed.
Nothing outside the block is managed, so it will not appear on its own.

In both cases the fix is the same, and it is thirty seconds of work.

---

## What to do when a heading is missing

**Add the heading. Empty is fine** — the heading is what the lookup matches on; what goes under it is
yours to write, when you have something to say.

```markdown
## Stack

## Architecture conventions

## Domain glossary
```

For `## Stack` specifically you do not have to fill it in by hand. Add the empty heading, then start
a ticket: **CLASSIFY detects your stack from the repo's own config files** — `package.json`,
`pyproject.toml`, `go.mod` and friends — and hands you the finished table to approve. It will not
write it without asking.

Or run **`/ddw-context-check`** any time. It reports every missing heading with what reads it, and
every command your repo has configured that DDW was never told about — your linter, your
`pre-commit`, the commands your CI runs. It proposes; you decide; it writes nothing you did not
approve.

> **A word on filling this in.** More is not better. A study across 138 real repositories found that
> repository context files gave **no improvement in agent success rate while costing over 20% more in
> inference**, with generated ones making things actively worse. Write what the agent cannot work out
> for itself — your commands, your conventions, the things you would tell a new hire on day one — and
> stop. `docs/RATIONALE.md` §8 has the sources.

---

## A worked example

```markdown
# AGENTS.md — project context

## Stack
- Language: Python 3.12
- Framework: FastAPI
- Tests: pytest -q
- Lint: ruff check .
- Typecheck: mypy app/
- Package manager: uv

## Architecture conventions
- Routes in `app/api/`, business logic in `app/services/`, persistence in `app/repos/`.
- A route never touches the database directly. It calls a service.
- Every external call goes through `app/clients/`, with a timeout.

## Code conventions
- Type hints on every public function.
- Errors: raise a domain exception; the handler in `app/api/errors.py` maps it to HTTP.

## What NOT to do in this project
- No ORM lazy loading. It caused the incident of 2026-03; queries are explicit.
- Do not add a new dependency without an ADR.

## Domain glossary
- **Ticket**: a support request from a student. Not a tracker issue.
- **Triage**: assigning category + priority. Always reviewed by a human before sending.

<!-- BEGIN DDW (managed by DDW — do not edit by hand) -->
…
<!-- END DDW -->
```

---

## The short version

- **`AGENTS.md` is yours.** DDW manages exactly one block in it and nothing else.
- **Never edit inside `<!-- BEGIN DDW -->`.** It is replaced on every upgrade, without warning.
- **The headings matter more than the prose.** A missing heading fails silently; that is the one
  failure mode of this file.
- **When in doubt, run `/ddw-context-check`.** It tells you what is missing and what reads it.
