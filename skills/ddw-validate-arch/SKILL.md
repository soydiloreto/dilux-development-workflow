---
name: ddw-validate-arch
description: >
  Validates that the code follows the project's architecture decisions and conventions. An advisory
  check, not a gate: the graph carries no `arch` condition, so it reports and the orchestrator
  decides. Produces disambiguation questions when a finding needs the user's context.
  Trigger: /ddw-validate-arch, during DDW's CODE phase.
---

# Skill: /ddw-validate-arch

## Description
Validates that the code follows the project's architecture decisions and conventions. It is an
**advisory check, not a gate**: `transition-graph.json` carries no `arch` condition on any edge, so
nothing here refuses a transition — it reports, and the orchestrator decides what to do. Naming it
a gate would be the exact failure this pipeline exists to avoid: calling something a lock when it
is a sign. Produces disambiguation questions when a finding needs the user's context.

## Inputs
- The modified files (default) or the whole project (if specified)
- The project's architecture conventions (`AGENTS.md`)

> **This skill has no rules of its own.** Its criteria come from the "Architecture conventions"
> section of the target project's `AGENTS.md`. If that section is empty, say so and report PASSED
> with a warning: there is nothing to validate against, and inventing conventions the project never
> declared is worse than validating nothing. The patterns below are a *starting* checklist to adapt,
> not a fixed catalog. (This is why `validate-arch` has no F-/W- IDs in
> `.ddw/rules/validation-rules.instructions.md` — it is an operational gate, not an artifact
> validator.)

## Execution Protocol

1. Identify which files to analyze:
   - First run in the phase: the whole relevant codebase.
   - Post-block: only the files the block modified.
2. For each file, check:
   - **Module structure:** every file in its correct layer.
   - **Separation of responsibilities:** no business logic in the transport layer.
   - **Language conventions:** typing, imports, naming, formatting.
   - **Correct use of the framework/ORM.**
   - **Data fetching:** server-side pagination, no in-memory filtering.
   - **Basic security:** no hardcoded secrets, no debug logging left in production paths.
3. Classify findings against the explicit criteria (below).
4. **For every FAIL that needs the user's decision, produce a disambiguation question.**

## Search patterns *(adapt to the stack)*

| Category | Look for | Level |
|----------|----------|-------|
| Circular dependencies | Mutual imports between modules | FAIL |
| Logic in transport | Queries or transformations in routes/controllers | FAIL |
| Hardcoded secrets | Strings that look like API keys, passwords, tokens | FAIL |
| In-memory filtering | Full lists filtered client-side with no pagination | FAIL |
| SQL injection | Queries built by string concatenation, unparameterized | FAIL |
| Weak typing | `any`, `Object`, `dynamic` with no justification | WARN |
| Debug logging in production | `console.log`, `print()` outside tests | WARN |
| Unjustified raw SQL | Queries outside the ORM with no comment | WARN |
| Unused import | Imports declared but never referenced | WARN |

## Output Format

```
┌─────────────────────────────────────────────────────────────┐
│  /ddw-validate-arch [scope] — [PASSED | BLOCKED (N quest.)]  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [Category]:                                                 │
│    ✅/❌/⚠️ file:line — [description]                          │
│                                                              │
│  Disambiguation questions:      (only if there are FAILs)    │
│                                                              │
│    Q1: file:line — [concrete question]                       │
│        Options: a) ... b) ... c) ...                         │
│                                                              │
│  ────────────────────────────────────────────────────────────│
│  Total: X passed, Y failed, Z warnings                       │
│  Next: [recommended action] (attempt N/3)                    │
└─────────────────────────────────────────────────────────────┘
```

## FAIL criteria (blocking)

A check is ❌ FAIL when it is a **safe architecture or security violation**:

- Circular dependencies between modules
- Business logic in the transport layer (queries, transformations in routes/controllers)
- Hardcoded secrets (API keys, passwords, tokens, connection strings)
- In-memory filtering with no server-side pagination for potentially large collections
- SQL injection (string concatenation in unparameterized queries)
- A violation of layer separation as defined by the project's architecture
- Files in the wrong layer (e.g. a service inside the routes folder)

## WARN criteria (non-blocking)

A check is ⚠️ WARN when it **needs context and may be valid**:

- Weak typing (`any`, `Object`, `dynamic`) — may be intentional in a catch or in generics
- Debug logging outside tests — may be intentional logging
- Raw SQL outside the ORM — may be justified by performance
- Unused import — may be a side-effect import
- Unconventional naming — may be dictated by an external API

## Disambiguation questions

Produce a question when:
- A FAIL has an obvious fix → a confirmation question: "Shall I move the query in controller.ts:23
  to the service layer?"
- A FAIL has several possible fixes → a question with options: "In-memory filtering in routes.ts:45.
  a) Move it into a SQL query with pagination b) Add limit/offset to the endpoint c) It is
  intentional (the collection is always small)"
- A WARN looks suspicious → an exploratory question: "Is the `any` in service.ts:30 intentional?"

## Result Rules

- **PASSED:** 0 FAILs. It may have WARNs.
- **BLOCKED (N questions):** 1+ FAILs. Each FAIL may produce a question if the fix is not obvious.
- Max 3 correction attempts before escalating to the user.
- The answers guide the automatic correction, or justify the pattern.

## Updating .ddw-state.json
- Does not modify flags directly. The result determines whether work can advance.

## Language

Write the report in the language the user is working in.
