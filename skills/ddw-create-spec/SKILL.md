---
name: ddw-create-spec
description: >
  Creates a new spec or fix-plan from an approved PRD or a fix diagnosis.
  Trigger: /ddw-create-spec, during DDW's PLAN phase.
---

# Skill: /ddw-create-spec

## Description
Creates a new spec or fix-plan from an approved PRD or a fix diagnosis, or updates an existing one.

### What a spec is, and what it is not

**A spec says how the thing in the PRD gets built, and everything in it traces back to something
the PRD asked for.** Components, files, data structures, endpoints, the order of the work, split
into blocks that can each be verified on their own. Where the PRD is technology-free on purpose,
this is where the technology is chosen and the reasons are written down.

**It does not introduce requirements.** If building the design reveals something the product has to
do that the PRD never said — a rule, a limit, a behaviour — that is not a line to add here. It is a
corrective loop back to DEFINE, and the loop exists precisely so that requirements keep coming from
one place. A requirement smuggled into a spec is a requirement no acceptance criterion covers, and
VERIFY checks the criteria.

It is binding, unlike an ADR: what it says is what CODE implements, and the blocks it declares are
what the implementation is judged against.

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
6. Increment `Spec loops` in the header — and `Loops since last human decision` too, unless this
   round is applying an answer a human just gave, in which case that one resets to 0 and their
   answer is recorded in the spec.

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
| Loops since last human decision | 0 |

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

**Data model** *(only if it creates/modifies a schema — or reuses one)*
- Entity, fields with types, constraints (nullable, unique, FK, default), indexes.
- A block that only REUSES a schema an earlier block declared still fills this section, restating
  the constraints by name: *"Reuses `ticket` from Block 2 — no schema change; constraints as
  declared there: NOT NULL, default, index on estado."* The validator reads each block alone, so
  "same table as above" names no constraint and fails F-SPEC-08. Measured three times, by two
  different models, in the same place: this sentence is the shape that passes.

**Input validation** *(only if it accepts input)*
- Type, maximum length, format, allowed values.

**Error handling**
- [Which errors can occur, and how each is handled.]
- [If this block has none of its own, say exactly that in ONE bullet — "Sin condiciones de error
  propias: …" / "None — …" — and nothing else. Do not borrow an error from another block to fill
  the section. A block that takes input or touches a schema may not declare this: data that
  arrives can arrive wrong.]

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

### The spec, in the shape the validator reads

The template above is a skeleton, and a skeleton cannot be validated: every bracketed row is a
placeholder the validator drops on purpose, so an unfilled document fails and should. This is the
same document filled in — one block, complete — and it is what `validate_spec.py --tier FEATURE`
is run against. It exists because the first live FEATURE run wrote a spec from the skeleton alone
and was refused by F-SPEC-07, F-SPEC-09 and F-SPEC-16, and the model's way out was reading the
validator's source to learn the shape — knowledge that belongs here. Three couplings are
load-bearing:

- **F-SPEC-07** looks inside `API contract` for all five items — method+path, request, response,
  error codes, auth. An endpoint block missing any one of them is refused by name.
- **F-SPEC-09**: a block whose surface takes input (a form, a payload, params) MUST carry
  `Input validation` — and may not declare "no error conditions of its own", because data that
  arrives can arrive wrong.
- **F-SPEC-16** COUNTS, per block: at least as many sad-path tests as `Error handling` bullets. A
  test counts as sad-path when its line names the failure — invalid/inválido, missing/faltante,
  rejected/rechazado, duplicate/duplicado, unauthorized/no autorizado, forbidden, timeout,
  conflict, error — in either language. Two error bullets with one sad-path test is a refusal,
  however good that test is.

```markdown
# Spec {ticket}: Alta pública de tickets

| Field | Value |
|-------|-------|
| Ticket | {ticket} |
| PRD | docs/ddw/prd/prd-{ticket}.md |
| Tier | FEATURE |
| Date | 2026-08-24 |
| Spec loops | 0 |
| Loops since last human decision | 0 |

## Summary
Un endpoint público recibe el alta de un ticket, la valida y la persiste. Un solo bloque: el
formulario y su ruta.

## Coverage: PRD → blocks
| Requirement | Covered by |
|---|---|
| FR-01 | Block 1 |
| NFR-01 | Strategy: render server-side sin bundle JS, p95 medido bajo 3 s |

## Dependencies between blocks
None — Block 1 stands alone.

## Block 1 — Formulario público de alta

**Files**
- `app/routes/public.py` (new) — las rutas del formulario

**Logic**
Implements FR-01: the anonymous form posts a ticket and receives its id.

**API contract**
- Method + path: `POST /tickets`
- Request: titulo (str), email (str)
- Response: id (int), estado (str)
- Error codes: 400, 422
- Auth: public, no authentication

**Data model**
- Entity ticket: id (PK), titulo (not null), estado (default "Pendiente"), index on estado.

**Input validation**
- titulo: str, max 200, required.
- email: valid address format, max 254, required.

**Error handling**
- titulo ausente — 400 naming the field; nothing persisted.
- email malformado — 422; nothing persisted.

**Required tests**
- [ ] test_alta_devuelve_id — validates AC-01
- [ ] test_titulo_faltante_400 — the missing field is refused (sad path)
- [ ] test_email_invalido_422 — the malformed email is refused (sad path)

**Completion criterion**
The three tests pass and `POST /tickets` returns 201 with the created id.

## Block 3 — [a block that reuses Block 2's schema]
**Files**
- `app/routes/listing.py` (new) — el listado protegido

**Logic**
Implements FR-02: the listing reads the tickets Block 2 persists.

**Data model**
- Reuses `ticket` from Block 2 — no schema change; constraints as declared there: NOT NULL,
  default "Pendiente", index on estado.

**Input validation**
- estado (query): one of the fixed states, optional.

**Error handling**
- estado desconocido — 422; the list is not computed.

**Required tests**
- [ ] test_listado_por_estado — validates AC-02
- [ ] test_estado_invalido_422 — the unknown state is refused (sad path)

**Completion criterion**
Both tests pass and the listing filters by estado.

## Final verification
`validate_spec.py --tier FEATURE` passes on this document and the endpoint answers as contracted.
```

Name every sad-path test with the failure word its error bullet uses — `faltante`, `inválido`,
`rechazado` (or `missing`, `invalid`, `rejected`) — because F-SPEC-16 pairs errors to tests by
those words, and a test called `test_post_sin_email` names none of them. Block 3 above is not
decoration: the block that reuses an earlier schema is where two different models failed
F-SPEC-08 three times, and its Data model sentence is the accepted shape, verbatim.

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
| Loops since last human decision | 0 |

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
- [error condition] — [the code, the message, and what the caller does about it]

## Tests
- [ ] **Regression test** — reproduces the original bug: fails BEFORE the fix, passes AFTER.
- [ ] [one test per error condition above, naming it — F-SPEC-16 counts them]

## Regression risk
[Low/Medium/High + what could break.]

## Rollback plan *(mandatory)*
- Steps: [how to revert] — or "trivial: revert the commit", stated explicitly
- Indicators: [what tells you to apply it]
```

> The `FR-`/`NFR-`/`AC-` identifiers and these section names are what `ddw-validate-spec` matches on
> (rules F-SPEC-01 to F-SPEC-16). Write the *content* in the user's language, but keep the
> identifiers and the structure as written here.

### The fix-plan, in the shape the validator reads

The template above is a skeleton, and a skeleton cannot be validated: every bracketed row is a
placeholder the validator drops on purpose, so an unfilled document fails and should. This is the
same document filled in, and it is what `validate_spec.py --tier FIX` is run against — errors as a
list because F-SPEC-16 counts them against the tests that name them, and prose in the error section
counts as none.

```markdown
# Fix-plan {ticket}: The config loader eats the trailing newline

| Field | Value |
|-------|-------|
| Ticket | {ticket} |
| Tier | FIX |
| RCA | docs/ddw/specs/rca-{ticket}.md |
| Date | 2026-08-05 |
| Spec loops | 0 |
| Loops since last human decision | 0 |

## Problem
`loadConfig()` returns the file without its final newline, so every rewrite of the config produces a
whole-file diff and three reviewers have now asked why.

## Root cause
`readText().rstrip()` was written to strip a BOM and takes the trailing newline with it.

## Solution — steps
1. `src/config/loader.ts:41` — strip the BOM only, with `replace(/^﻿/, "")`.
2. `src/config/loader.ts:58` — write back the text that was read, unmodified.

## Dependencies between steps
None; the two steps are independent.

## Error handling
- The file cannot be read — `ConfigUnreadable` naming the path; the caller falls back to defaults
  and logs once.
- The file is not valid UTF-8 — the same error, with the byte offset; the fallback is the same.

## Tests
- [ ] **Regression test** — a config with a BOM keeps its trailing newline: fails BEFORE the fix,
      passes AFTER.
- [ ] An unreadable file surfaces the `ConfigUnreadable` error, and the defaults are used.
- [ ] A file with an invalid UTF-8 byte reports the offset and falls back the same way.

## Regression risk
Low — the only caller is the config writer, and its output is asserted byte for byte.

## Rollback plan *(mandatory)*
- Steps: trivial: revert the commit
- Indicators: config rewrites start showing whole-file diffs again
```

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
│  Spec loops: [N] (since last human decision: [N])        │
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
