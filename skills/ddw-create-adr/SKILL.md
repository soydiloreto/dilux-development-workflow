---
name: ddw-create-adr
description: >
  Records an architecture or design decision as an ADR (Architecture Decision Record). Captures the
  context, the options considered, the decision taken and its consequences.
  Trigger: /ddw-create-adr, during DDW's PLAN or CODE phase.
---

# Skill: /ddw-create-adr

## Description
Records an architecture or design decision as an ADR (Architecture Decision Record). Captures the
context, the options considered, the decision taken and its consequences.

### What an ADR is, and what it is not

**An ADR explains a decision that has already been taken. It does not impose anything.** Its reader
is whoever, months from now, asks "why is it built like this?" and would otherwise reopen a
settled argument or undo something for a reason that was already weighed.

Requirements live in the PRD. Design that must be built lives in the spec. Both are validated by a
script and both are binding. An ADR is neither: nobody has to obey it, because it describes what was
obeyed and why. That is the whole distinction, and it is written here because every other artifact
in DDW has a validator pinning its genre and this one has none — nothing catches an ADR that reads
like a requirement, so it has to be said rather than checked.

In practice: write it in the past, describing. If a sentence of yours says **must**, **shall** or
**should**, it is not an ADR sentence — it belongs in the spec, and leaving it here creates a second
document telling the implementation what to do, one that no gate reads and no validator judges.

An ADR is also not a status report, not a summary of the phase, and not a place to restate the PRD.

## Inputs
- The decision's context (detected automatically, or provided by the user)
- The relevant source code
- The project's architecture conventions (`AGENTS.md`)
- The project's stack: the "Stack" section of `AGENTS.md`

## Execution Protocol

### Automatic trigger
The agent MUST create an ADR when it detects:
- Renaming entities, tables or modules
- Changing a data structure or a schema
- Choosing between two or more valid technical approaches
- Including or excluding something from scope for technical reasons
- Changing an established pattern in the project
- Adding a significant new dependency
- Deviating from a documented convention

### Manual trigger
The user invokes `/ddw-create-adr <title>`.

### Process
1. Identify the decision's context.
2. Document at least 2 options considered, with pros and cons.
3. Record the decision taken, with concrete reasons.
4. Document the consequences (what changes, which files are affected, what limitations).
5. Save it to `docs/adr/adr-NNN-title-in-kebab.md`.
6. **Validate it:** `python3 .ddw/scripts/validate_adr.py docs/adr/adr-NNN-title-in-kebab.md`, and
   fix what it finds before showing the ADR. No gate reads this — an ADR is written only when a
   decision warrants one, and a gate would demand one per ticket — so the loop is yours to close.
   The rules are §7 of `.ddw/rules/validation-rules.instructions.md`.

### ADR format

```
# ADR-NNN: [Title]

| Field | Value |
|-------|-------|
| Date | [timestamp] |
| Ticket | [ticket or "N/A"] |
| Status | Accepted · or "Superseded by ADR-NNN" once another one replaces it |

## Context
[The problem that led to the decision]

## Options considered

### Option 1: [name]
- **Pros:** [list]
- **Cons:** [list]

### Option 2: [name]
- **Pros:** [list]
- **Cons:** [list]

## Decision
[The option chosen, and the concrete reasons]

## Consequences
- [What changes]
- [Which files are affected]
- [Limitations or trade-offs accepted]
```

## Output Format

```
┌─────────────────────────────────────────────────────────┐
│  /ddw-create-adr — Recorded                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  File: docs/adr/adr-NNN-title.md                         │
│  Decision: [one-line summary]                            │
│  Options considered: [N]                                 │
│  Consequences: [N]                                       │
│                                                          │
│  Next: continue with the current flow                    │
└─────────────────────────────────────────────────────────┘
```

## Rules
- Concise: at most ~30 lines of useful content.
- Do not duplicate PRDs or specs — reference them.
- Enough context that someone from outside understands the *why*.
- Always evaluate at least 2 options. One option is not a decision, it is a preference.
- The NNN numbering is sequential within `docs/adr/`.
- **An ADR is never edited to change its decision, and never deleted.** It records what was decided
  when it was decided; rewriting it destroys the only reason it exists. To change course, write a
  new ADR that names the one it replaces, and set the old one's `Status` to
  `Superseded by ADR-NNN`. Correcting a typo is fine; correcting the past is not.

## Updating .ddw-state.json
- None. This skill does not modify the pipeline's state.

## Language

Write the ADR's content in the language the user is working in, keeping the section names above.
