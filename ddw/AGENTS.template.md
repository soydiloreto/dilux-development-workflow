# AGENTS.md — project context

> **DDW template.** Fill in the `[...]` with what is true of YOUR project and delete what does not
> apply. This file describes **the project**; **the process** is DDW's job (phases, gates, when to
> test, when to commit). Do not mix the two: process rules written here compete with the pipeline's.
>
> It is **tool-agnostic on purpose**: Claude Code reads it through the import in `CLAUDE.md`, Codex
> CLI, Copilot CLI, Cursor and OpenCode read it directly, and Gemini CLI gets it through
> `GEMINI.md`. The same file serves whichever tool you open the repo with — which is the point:
> porting the pipeline to another tool must not mean rewriting what your project is.

---

## Language

**Always respond in the language the user writes in.** Write every artifact you produce — PRDs,
specs, ADRs, reports, commit messages, status lines — in that same language, regardless of the
language these instructions are written in.

If this project has a fixed working language, state it here and use it instead:

> Working language: `[e.g. Spanish — write all artifacts in Spanish]`

---

## What this project is

[One or two sentences: what the app does and who for. Take it from the PRD, do not reinvent it.]

**Reference PRD:** `docs/ddw/prd/[your-prd].md`

---

## Stack

**This is the only place the stack lives.** DDW reads it from here and generates no derived file.
Fill it in even if the repo is empty: without a stack there is nothing to plan or implement against.

If the repo already has code and this section is empty, DDW will detect the stack from your config
files and **propose the text for you to paste here**. You always confirm it.

| Field | Value |
|-------|-------|
| Language | [e.g. TypeScript 5.x] |
| Runtime | [e.g. Node 20] |
| Framework | [e.g. Next.js 15 · or N/A] |
| Database | [e.g. PostgreSQL + Prisma · or N/A] |
| Test runner | [e.g. Vitest] |
| Linter / formatter | [e.g. ESLint + Prettier] |
| Package manager | [e.g. pnpm] |

---

## Testing

**The coverage floor lives here, and nowhere else.** `ddw-test` and
`ddw-verify-module` both require a report to state the floor **and where it came from**, and both
show it sourced as `AGENTS.md, "Testing"` — a section this template did not have, so every project
was told to cite something the installer never created. A floor a report chooses for itself is a
floor that passes itself; it belongs to the project.

| Field | Value |
|-------|-------|
| Coverage floor — line | [e.g. 80%] |
| Coverage floor — branch | [e.g. 70%] |
| Coverage floor — function | [e.g. 80%] |
| How the suite is run | [e.g. `pnpm test`] |
| What a skipped test owes | [e.g. a reason on the same line] |

If a number here is not the one your CI enforces, say which one wins. Two floors that disagree is
the same as no floor.

---

## Architecture conventions

**DDW validates your code against this section** during the CODE phase, via `ddw-validate-arch`.
Leave it empty and that validation has nothing to compare against, so it stops being worth running.

- **Folder structure:** [e.g. `src/features/<feature>/` with `ui`, `domain`, `data`]
- **Layer separation:** [e.g. the UI never talks to the database; always through a service]
- **Error handling:** [e.g. typed errors; never a silent catch]
- **Naming:** [e.g. files in kebab-case, components in PascalCase]
- **Dependencies:** [e.g. no new libraries without justifying them in the spec]

---

## Code conventions

- [e.g. No `any`. If it is unavoidable, it comes with a comment explaining why.]
- [e.g. Pure functions wherever possible; side effects at the edges.]
- [e.g. Comments only when the *why* is not obvious from the code.]

---

## What NOT to do in this project

This section is worth its weight in gold: it is where the scars go, the things that already went
wrong once.

- [e.g. Do not touch `config/` without asking.]
- [e.g. Never call the payments API in tests — there is a mock.]
- [e.g. No destructive migrations.]

---

## Domain glossary

The terms specific to your product, so the agent uses them correctly instead of inventing synonyms.

- **[Term]:** [what it means exactly, here]
- **[Term]:** [what it means exactly, here]

---

> ℹ️ **What does NOT belong in this file, because DDW provides it:** the order work happens in, when
> the spec gets written, when tests run, when to commit, what it takes to move between phases. All
> of that lives in `.ddw/` and applies on its own.
