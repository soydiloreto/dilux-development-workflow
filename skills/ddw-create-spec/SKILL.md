---
name: ddw-create-spec
description: >
  Creates a new spec or fix-plan from an approved PRD or a fix diagnosis.
  Trigger: /ddw-create-spec, during DDW's PLAN phase.
---

# Skill: /ddw-create-spec

## Description
Creates a new spec or fix-plan from an approved PRD or a fix diagnosis, or updates an existing one.

## Inputs
- The PRD at `docs/ddw/prd/prd-{ticket}.md` (for FEATURE, if `gates.define` is true)
- The ticket info in `.ddw-state.json` (for FIX)
- The `tier` from `.ddw-state.json`
- The project's architecture conventions (`AGENTS.md`)

## Execution Protocol

### Creation mode — FEATURE (full spec)
1. Read the complete PRD.
2. Read the architecture conventions.
3. Extract tasks by category: schema/model, business logic, endpoints/API, views/UI, testing,
   scaffolding.
4. Produce the document: header, summary, numbered blocks with atomic tasks, execution order, final
   verification.
5. Every block carries: files to create/modify, logic, required tests, completion criterion.

### Creation mode — FIX (lightweight fix-plan)
1. Read the diagnosis of the problem.
2. Identify the root cause and the affected files.
3. Produce the document: problem, root cause, solution with steps, tests, regression risk.

The **Rollback plan** is mandatory for FIX (F-SPEC-15), and the fix-plan references the RCA that
DEFINE produced (`docs/ddw/specs/rca-{ticket}.md`) — the reference is a convention of the tier, not
an F-SPEC rule. If
reverting really is trivial, the section still has to exist and say so — QUICK-FIX is the tier for
changes too small to deserve one, and it has no PLAN phase at all.

### Update mode (existing spec)
1. Read the existing spec and the PRD.
2. Identify already-completed tasks (`[x]`).
3. Identify new requirements not yet covered.
4. Append new blocks at the end with sequential numbering.
5. Preserve completed blocks — never modify them.
6. Increment `Spec loops` in the header.

## Spec Template (FEATURE) — canonical

```markdown
# Spec {ticket}: [Title]

| Field | Value |
|-------|-------|
| Ticket | [ticket] |
| PRD | docs/ddw/prd/prd-{ticket}.md |
| Tier | FEATURE |
| Date | [timestamp] |
| Spec loops | 0 |

## Summary
[The technical approach in 3–5 lines: what gets built and how.]

## Coverage: PRD → blocks
| Requirement | Covered by |
|---|---|
| FR-01 | Block 1 |
| FR-02 | Block 2, Block 3 |
| NFR-01 | Strategy: [how it is met] |

## Dependencies between blocks
[Which block depends on which, and the execution order. "None" if they are independent.]

## Block 1 — [name]

**Files**
- `path/to/file.ts` (new) — [what it does]
- `path/to/other.ts` (modified) — [what changes]

**Logic**
[What this block implements.]

**API contract** *(only if it creates/modifies an endpoint)*
- Method + path: `POST /api/...`
- Request: fields with types
- Response: fields with types
- Error codes: [list]
- Auth: [which authentication/authorization applies]

**Data model** *(only if it creates/modifies a schema)*
- Entity, fields with types, constraints (nullable, unique, FK, default), indexes.

**Input validation** *(only if it accepts input)*
- Type, maximum length, format, allowed values.

**Error handling**
- [Which errors can occur, and how each is handled.]

**Required tests**
- [ ] [test name] — validates AC-xx
- [ ] [sad path test] — invalid input

**Completion criterion**
[Verifiable, e.g. "tests X and Y pass and the endpoint returns 201 with the created id".]

## Block 2 — [name]
[Same structure.]

## Final verification
[What has to hold once every block is done.]
```

## Fix-Plan Template (FIX) — canonical

```markdown
# Fix-plan {ticket}: [Title]

| Field | Value |
|-------|-------|
| Ticket | [ticket] |
| Tier | FIX |
| RCA | docs/ddw/specs/rca-{ticket}.md [FIX only] |
| Date | [timestamp] |
| Spec loops | 0 |

## Problem
[What is failing, and how it manifests.]

## Root cause
[The technical cause, not the symptom.]

## Solution — steps
1. `path/to/file.ts:NN` — [what changes]
2. ...

## Dependencies between steps
[Order, if it matters. "None" if the steps are independent.]

## Error handling
[Which errors can occur with this change, and how they are handled.]

## Tests
- [ ] **Regression test** — reproduces the original bug: fails BEFORE the fix, passes AFTER.
- [ ] [other tests]

## Regression risk
[Low/Medium/High + what could break.]

## Rollback plan *(mandatory)*
- Steps: [how to revert] — or "trivial: revert the commit", stated explicitly
- Indicators: [what tells you to apply it]
```

> The `FR-`/`NFR-`/`AC-` identifiers and these section names are what `ddw-validate-spec` matches on
> (rules F-SPEC-01 to F-SPEC-16). Write the *content* in the user's language, but keep the
> identifiers and the structure as written here.

## Granularity Rules
- At most ~200 lines of code per task.
- 2+ concrete, verifiable checkboxes per task.
- List EVERY file that gets created/modified.
- Explicit dependencies between tasks and blocks.

## Output Format
```
┌─────────────────────────────────────────────────────────┐
│  /ddw-create-spec — [Created | Updated]                  │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  File: [path]                                            │
│  Type: [spec | fix-plan]                                 │
│  Blocks: [N] (N new)                                     │
│  Tasks: [N]                                              │
│  Checkboxes: [N]                                         │
│  Spec loops: [N]                                         │
│                                                          │
│  Next: review and confirm to move on                     │
└─────────────────────────────────────────────────────────┘
```

## Updating .ddw-state.json
- `gates.spec` → `true` once the user approves the spec. The path is derived from the ticket:
  `docs/ddw/specs/spec-{ticket}.md` or `docs/ddw/specs/fix-{ticket}.md`.
- `block` → `"1/N"` where N is the number of blocks (FEATURE only, indicating the current block).
  `null` for a fix-plan (FIX have no blocks).

## Language

Write the spec's content in the language the user is working in, keeping the identifiers and section
names above.
