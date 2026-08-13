---
name: ddw-create-prd
description: >
  Creates a new PRD (Product Requirements Document) or updates an existing one. The PRD defines WHAT
  will be built: functional and non-functional requirements, acceptance criteria, scope and risks.
  Trigger: /ddw-create-prd, during DDW's DEFINE phase.
---

# Skill: /ddw-create-prd

> **Sequencing — this skill runs ALONE.** Do not load or invoke
> `ddw-validate-prd` until the PRD file is WRITTEN TO DISK and complete.
> Loading both as reading material and "validating" from memory is not
> validation — the validator is a script that reads the file, and its receipt
> is a hash of the final content: create first, validate after, always.

## Description
Creates a new PRD (Product Requirements Document) or updates an existing one. The PRD defines WHAT
will be built: functional requirements, non-functional requirements, acceptance criteria, scope and
risks.

### What a PRD is, and what it is not

**A PRD says what the software has to do and why, and never how it is built.** Its sentences are
about behaviour someone can observe from outside: what a person does, what the system answers, what
must still hold when things go wrong. Every requirement carries an acceptance criterion, because a
requirement nobody can test is an opinion with a number on it.

It is not a design. No file names, no libraries, no schemas, no endpoints. If a sentence of yours
names a technology, it belongs in the spec — and putting it here freezes a decision before the
phase that weighs the alternatives has run, which is how a PRD comes to dictate an architecture
nobody chose.

It is not a plan either: no blocks, no order of work, no estimates. Those are the spec's.

The test, when unsure: could this requirement still be true if the whole thing were rebuilt in
another language? If yes it is a requirement. If no it is design.

## Inputs
- The user's request (a description of the feature or change)
- Existing PRDs in `docs/ddw/prd/` (to detect duplicates or to update)
- `.ddw-state.json` (ticket, tier)
- The project's stack: the "Stack" section of `AGENTS.md`

## Execution Protocol

### Branch: tier = QUICK-FIX

If `.ddw-state.json` has `tier == "QUICK-FIX"`, do NOT produce a full PRD. Produce a **4-line
fix-brief** and mark the `define` gate:

- **Path:** `docs/ddw/prd/fix-{ticket}.md` (the same folder as the PRDs; the convention is defined in
  `.ddw/rules/branches.instructions.md`).
- **Template:**

```markdown
# Fix {ticket}: {title}

- **Bug**: {one descriptive line}
- **Change**: {file}:{line} — {description of the modification}
- **Regression test**: {name of the test that reproduces the bug BEFORE and passes AFTER}
- **Risk**: none / {explain it if there is one}
```

- Validation: the 4 sections present and non-empty → verdict **PASS**. Do NOT run the `F-PRD-*`
  rules (see "Tier Modifier: QUICK-FIX" in `.ddw/rules/validation-rules.instructions.md`).
- Set `gates.define = true` on the DEFINE→CODE transition.
- Do NOT invoke `ddw-validate-prd` with FEATURE rules.

### Creation mode (new PRD)

1. Search `docs/ddw/prd/` for an existing PRD covering this functionality.
   - If one exists and covers it partially → switch to update mode.
   - If one exists and covers it fully → tell the user; do not duplicate.
2. Talk with the user to disambiguate requirements. This phase is **exploratory and
   conversational** — do not use plan mode.
3. Produce the PRD from the standard template (below).
4. The filename is derived from the ticket: `prd-{ticket}.md` (e.g. `prd-FEAT-001.md`).
5. Run `ddw-validate-prd` automatically.
6. If there are FAILs → fix them and increment **both** `PRD loops` and `Loops since last
   human decision`. The first is the running total and nobody ever resets it; the second is what
   the ceiling measures, and it goes back to 0 only when a human decides something.
7. Present it to the user for approval.

### Update mode (existing PRD)

1. Read the existing PRD in full.
2. Identify which sections need changes.
3. Update in place — preserve whatever does not change.
4. Increment `PRD loops` in the header — and `Loops since last human decision` too, unless this
   update is applying an answer a human just gave, in which case that one resets to 0 and their
   answer is recorded in the PRD.
5. Run `ddw-validate-prd` automatically.
6. Present the diff to the user for approval.

## PRD Template

```markdown
# PRD {ticket}: [Title]

| Field | Value |
|-------|-------|
| Ticket | [ticket] |
| Tracker | [tracker ticket or "none"] |
| Date | [timestamp] |
| PRD loops | 0 |
| Loops since last human decision | 0 |

## Context and Problem
[Describe the problem being solved]

## Goals
[What we want to achieve]

## Functional Requirements
- FR-01: [atomic requirement]
- FR-02: [atomic requirement]

## Non-Functional Requirements
- NFR-01: [performance, security, etc. — always with a number]

## Acceptance Criteria
*(EARS — see `.ddw/rules/validation-rules.instructions.md` §1 for the five patterns)*

**Every AC names the FR it validates, in parentheses.** `F-PRD-01` looks for the FR's own
identifier inside the criterion, so an AC that validates FR-01 without naming it reads as an FR
nothing validates — and the template used to produce exactly that, which failed the first PRD of
every new install.
- AC-01 (FR-01): WHEN [trigger], THE [system] SHALL [response].
- AC-02 (FR-01): IF [failure or misuse], THEN THE [system] SHALL [response].
- AC-03 (FR-02): WHILE [state], THE [system] SHALL [response].

## Out of Scope
- [what is explicitly NOT included, one item per line]

## Risks and Mitigations
[Identified risks and how to mitigate them]

## Dependencies
[Other modules, services or features this depends on]
```

> The `FR-`/`NFR-`/`AC-` prefixes and the section names are what `ddw-validate-prd` matches on
> (rules F-PRD-01 to F-PRD-09). Write the *content* in the user's language, but keep the identifiers
> and the structure as written here — **including the EARS keywords** (`WHEN`, `WHILE`, `WHERE`,
> `IF … THEN`, `SHALL`), which stay in English in every language, exactly as the section headings do.
> They are the shape the validator matches on; translated, the criterion still reads fine to a human
> and matches nothing.

## PRD Quality Rules

- **Atomic requirements:** each FR must describe a single verifiable action.
- **Acceptance criteria in EARS form.** One of the five patterns, every time (F-PRD-09). And **at
  least one `IF … THEN`** wherever the feature can fail, be misused, or depend on something that
  might not answer — that pattern exists for exactly the cases everyone forgets, and W-PRD-04 counts
  them. What nobody writes here is what nobody tests three phases later.
  *(Exceptions: DISCOVERY, which is exploratory, and QUICK-FIX, whose artifact is the fix-brief.)*
- **No ambiguity:** avoid "fast", "efficient", "easy" without concrete metrics.
- **Explicit Out of Scope:** what is NOT included matters as much as what is.
- **Examples:** include concrete examples for endpoints, validations and user flows.
- **Pagination, errors, validations:** always specify them where APIs are involved.

## Output Format

```
┌─────────────────────────────────────────────────────────┐
│  /ddw-create-prd — [Created | Updated]                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  File: docs/ddw/prd/prd-{ticket}.md                      │
│  Mode: [new | update of prd-XXX]                         │
│  Functional requirements: [N]                            │
│  Non-functional requirements: [N]                        │
│  Acceptance criteria: [N]                                │
│  PRD loops: [N] (since last human decision: [N])         │
│                                                          │
│  Next: review the PRD and confirm to move on             │
└─────────────────────────────────────────────────────────┘
```

## Updating .ddw-state.json
- `gates.define` → `true` once the user approves the PRD. The path is derived from the ticket:
  `docs/ddw/prd/prd-{ticket}.md`.
- `gates.define` → `true` for tier QUICK-FIX, once the 4-section fix-brief is produced and
  validated. The path is derived from the ticket: `docs/ddw/prd/fix-{ticket}.md`.

## Language

Write the PRD's content in the language the user is working in, keeping the identifiers and section
names above.
