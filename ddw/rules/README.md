# DDW — The Method

## What DDW is

DDW is a **structured development pipeline for AI agents** (Claude Code, Codex CLI, Copilot CLI,
Cursor, Gemini CLI, OpenCode). It defines a
state machine that walks the agent step by step through a complete development cycle: from
understanding what has to be done, to shipping the code with a commit, a PR and a closed ticket.

### The problem it solves

AI agents have three recurring problems when working on code:

1. **They skip steps** — straight to writing code, without understanding requirements or planning.
2. **They lose context** — in long sessions they forget earlier decisions or the state of the work.
3. **They get overloaded** — give them every rule at once and they follow some and ignore the rest.

### The solution

DDW implements three mechanisms:

- **A state machine**: the agent can only be in one phase at a time, with explicit allowed and
  blocked actions.
- **Lazy loading**: each phase loads only the relevant instructions, avoiding context overload.
- **Blocking gates**: you cannot advance a phase without meeting verifiable conditions (tests
  passing, clean SAST, the user's approval).

---

## Work Classification

When the user makes a request, CLASSIFY sorts it into one of two families:

**Stateless** — `QUERY` (an informational question, read-only). It is resolved inside IDLE: it
does **not** modify `.ddw-state.json`, does not start a phase, and is not recorded in the `tier`
field. A request that has nothing to do with the repo's code is not classified at all: DDW governs
what happens to the code, not everything you are asked for.

**Stateful** — `QUICK-FIX`, `FIX`, `FEATURE`, `DISCOVERY`. They record a `tier` in
the state and advance through phases. FIX/FEATURE walk the full pipeline; QUICK-FIX takes
a short subset (`CLASSIFY → DEFINE → CODE → CLOSEOUT`, skipping PLAN and VERIFY); DISCOVERY has its
own ideation flow (`CLASSIFY → DISCOVERY`).

### Tiers (canonical table)

| Tier | What it is | Pipeline | Notes |
|---|---|---|---|
| `QUERY` | An informational question | none (stateless) | Read-only. Does not touch the state. |
| `QUICK-FIX` | A ≤ 10 LOC change with no attack surface | `CLASSIFY → DEFINE → CODE → CLOSEOUT` | Artifact: a 4-line fix-brief. SAST still blocks. Guarded by the shared gate, on every tool. |
| `FIX` | A defect in existing behavior, including a live production bug | the full pipeline | Fix-plan instead of a spec with blocks. Requires an RCA, a regression test and a rollback plan. |
| `FEATURE` | New functionality | the full pipeline | PRD + spec with blocks + scope control. |
| `DISCOVERY` | Ideation, no implementation | `CLASSIFY → DISCOVERY` | Produces a concept + validated PRDs. No code. |

QUICK-FIX is evaluated FIRST, using a mechanical 5-criteria heuristic (≤ 10 LOC, 1 code file, no
sensitive paths, no new files, no new dependencies). If any criterion fails, classification
continues normally. See `classify.instructions.md`.

> ℹ️ Tier names are written to the state as **enum identifiers** — they are what the FSM and
> `transition-graph.json` validate against, not display text.

---

## Pipeline

```
CLASSIFY → DEFINE → PLAN → CODE → VERIFY → CLOSEOUT → IDLE
```

Every `→` transition requires the user's explicit approval. **Unless the ticket was classified `autonomy: "minimal"`**, where the arrows stop waiting and nothing else changes — see `.ddw/orchestrator.md` § Autonomy.

Six phases. CLASSIFY is not numbered in the status line, so the numbering the agent shows you
runs over the other five: DEFINE(1) → PLAN(2) → CODE(3) → VERIFY(4) → CLOSEOUT(5).

| Phase | What it does | Exit gate |
|-------|--------------|-----------|
| **CLASSIFY** | Classifies the tier, reads the stack, assigns a ticket and creates the branch | The user confirms the classification |
| **DEFINE** | Writes/reviews the PRD, controls scope | The user approves the PRD |
| **PLAN** | Designs the technical solution, writes the spec/fix-plan to disk | Spec approved + threat model |
| **CODE** | Implements block by block, writes tests | Tests pass + clean SAST |
| **VERIFY** | Cross-verification against the PRD and the spec, written to a report | verify-module passes |
| **CLOSEOUT** | Commit, PR, tracker update | The user confirms the closeout |

### Behavior by tier in each phase

| Phase | FEATURE | FIX |
|-------|---------|-----|
| **CLASSIFY** | Classifies, assigns FEAT-NNN | Classifies, assigns FIX-NNN |
| **DEFINE** | Full PRD + scope control | Root cause analysis + reviews PRDs, gate if there is a gap |
| **PLAN** | Spec with blocks + threat modeling | Fix-plan + rollback plan + threat modeling |
| **CODE** | Block by block from the spec | Steps from the fix-plan, stability first |
| **VERIFY** | verify-module | verify-module |
| **CLOSEOUT** | Commit + PR + tracker | Commit + PR + tracker |

> **QUICK-FIX** and **DISCOVERY** are not in this table (which compares FEATURE and FIX):
> QUICK-FIX uses the short pipeline (DEFINE = fix-brief, CODE = tests + SAST, no PLAN and no
> VERIFY), and DISCOVERY does not walk the pipeline at all. See the tier table above.

---

## Control Mechanisms

### 1. Lazy loading
The router (the "Phase Router" section of `orchestrator.md`) defines which instruction files load in
each phase. The agent **never** loads instructions from a phase other than the current one.

### 2. Blocking gates
- **SAST** (CODE phase): `ddw-security-sast` must pass before advancing to VERIFY.
- **Tests**: the full suite must pass before leaving CODE.
- **User approval**: every phase transition is confirmed by the user. Under `minimal`, only the acts that leave the repository are (a merge, a tracker ticket).

### 3. Multi-session persistence
The state is stored in `.ddw-state.json`. If a session is interrupted, the next one picks up where
it left off. Block-by-block progress is tracked in the state's `block` field.

### 4. Self-check
The agent verifies its own state before every write action. If it detects an inconsistency between
what it is doing and the current phase, it stops and reports.

---

## File Layout

```
.ddw/                        ← THE METHOD (tool-agnostic)
  orchestrator.md                   The state machine and the phase router
  rules/
    classify.instructions.md          Phase: classifying the request
    define.instructions.md            Phase: requirements and PRD
    plan.instructions.md              Phase: technical planning and specs
    code.instructions.md              Phase: implementation
    verify.instructions.md            Phase: verification
    closeout.instructions.md          Phase: commit, PR and the closeout itself
    discovery.instructions.md         Tier: ideation and product definition
    state.instructions.md             The state schema (always loaded)
    validation-rules.instructions.md  The central catalog of validation rules
    testing.instructions.md           Convention: testing and coverage
    commits.instructions.md           Convention: Gitmoji + Conventional Commits
    security.instructions.md          Convention: security and SAST
    tracker.instructions.md           Convention: tracker integration
    branches.instructions.md          Convention: branching and naming
    transition-graph.json             Legal transitions + required gates
  scripts/
    transition.py                     Builds the next state (the sanctioned write)
    validate-transition.py            The FSM: what a transition may do, and the source guard
    hook-gate.py                      The one entry point every tool's hook calls
    session-boot.py                   Materialises the state, warns about concurrent sessions
    validate_prd.py                   Writes the receipt the `define` gate asks for
    validate_spec.py                  Writes the receipt the `spec` gate asks for
    validate_threat.py                Writes the receipt the `threat` gate asks for
    validate_tests.py                 Writes the receipt the `tests` gate asks for
    validate_sast.py                  Writes the receipt the `sast` gate asks for
    validate_verify.py                Writes the receipt the `verify` gate asks for

.claude/                     ← THE WIRING (one of these per tool)
  settings.json                     Which hooks run and when
  skills/*/                         17 pipeline skills (invoked as `ddw-<name>`)
  agents/*.md                       5 specialized agents (spawned as `ddw-<name>`)
  hooks/                            The enforcement scripts

AGENTS.md                    ← The project's context — you fill this in
.ddw-state.json              ← The pipeline's state, at the repo root (gitignored)

docs/
  ddw/                              Everything the pipeline produces, namespaced
    prd/                            Generated PRDs and fix-briefs
    specs/                          Specs, fix-plans, RCAs
    discovery/                      Discovery concepts
    security/                       Threat models and SAST reports
    reports/                        Verification reports
  adr/                              Architecture Decision Records — deliberately
                                    OUTSIDE docs/ddw/: the decision belongs to
                                    the project, not to the tool that recorded it
```

---

## Version

The method does not carry a number of its own. There is **one** product version —
`CHANGELOG.md` states it and every manifest repeats it — and each rule file
carries its own in its frontmatter, bumped when that file changes.

A third number here said `2.2.0` while the product said `1.0.0`, and nothing
compared them, so it drifted for as long as it existed. `CONTRIBUTING.md` has the
rule and `scripts/check_versions.py` enforces it.

## Rule files — Phases

- [classify.instructions.md](classify.instructions.md) — Classifying the request
- [define.instructions.md](define.instructions.md) — Requirements definition and the PRD
- [plan.instructions.md](plan.instructions.md) — Technical planning and specs
- [code.instructions.md](code.instructions.md) — Implementation
- [verify.instructions.md](verify.instructions.md) — Verification
- [closeout.instructions.md](closeout.instructions.md) — Commit, PR, tracker and closeout
- [discovery.instructions.md](discovery.instructions.md) — The DISCOVERY tier

## Rule files — Conventions

- **Architecture conventions** — defined in the target project's `AGENTS.md` (not a DDW file; the
  user fills it in)
- [state.instructions.md](state.instructions.md) — The `.ddw-state.json` schema and how to write it
- [validation-rules.instructions.md](validation-rules.instructions.md) — The 84 validation rules
- [testing.instructions.md](testing.instructions.md) — Testing and coverage conventions
- [commits.instructions.md](commits.instructions.md) — Gitmoji + Conventional Commits and PRs
- [security.instructions.md](security.instructions.md) — Security practices and SAST
- [tracker.instructions.md](tracker.instructions.md) — Tracker integration
- [branches.instructions.md](branches.instructions.md) — Branching conventions

## Examples

- [before-after-1.md](examples/before-after-1.md) — A complete FIX flow
- [before-after-2.md](examples/before-after-2.md) — A FEATURE flow with scope control
