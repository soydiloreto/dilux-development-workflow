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

### ADR format

```
# ADR-NNN: [Title]

| Field | Value |
|-------|-------|
| Date | [timestamp] |
| Ticket | [ticket or "N/A"] |
| Status | Accepted |

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

## Updating .ddw-state.json
- None. This skill does not modify the pipeline's state.

## Language

Write the ADR's content in the language the user is working in, keeping the section names above.
