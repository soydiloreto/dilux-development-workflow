---
applyTo: '**'
version: 2.0.0
---

# Phase 1: DEFINE (Requirements Definition)

**Goal:** make sure the requirements are documented before planning.

Read `.ddw-state.json.tier` to determine your behavior.

---

## Branch Check

The working branch was already created in the CLASSIFY phase. Verify we are on the right one:
- If we are on the ticket's branch → continue.
- If not (resumed session) → check out the ticket's branch. The name is derived from the ticket and
  tier by convention.

**Then measure the drift** (checkpoint 2 of "Staying current" in `.ddw/rules/branches.instructions.md`):
`git fetch origin` and `git rev-list --count HEAD..origin/{base}`. Silent if it is 0; if the base
moved, report how far and offer to update. Do not rebase or merge without the user saying so.

---

## Non-negotiable Validation Rule

**`ddw-validate-prd` is MANDATORY in ALL cases.** No exceptions. It applies when:
- A new PRD is created.
- An existing PRD is updated.
- A pre-existing PRD is reused (e.g. one produced in DISCOVERY).
- The PRD was already validated in another context.

**Reasoning:** a PRD validated in DISCOVERY does not guarantee validity in the pipeline's context.
The codebase may have changed, the PRD may have been edited, and the implementation context may
reveal gaps that ideation did not catch. Validation is cheap; a PRD with gaps reaching CODE is
expensive.

**NEVER rationalize that "it was already validated" to skip this step.**

**QUICK-FIX validates too — against different rules.** That tier's artifact is the 4-line fix-brief,
not a PRD, so `ddw-validate-prd` runs under the tier modifier in
`.ddw/rules/validation-rules.instructions.md`: the four sections (Bug, Change, Regression test,
Risk) present and non-empty → PASS. The `F-PRD-*` rules do not apply. What is never optional is
*running* the validation; what changes per tier is what it demands.

---

## Socratic Protocol (applies to EVERY tier in this phase)

DEFINE is where the requirements get understood, and that only happens by asking. Not by producing a
plausible PRD from what you inferred. **A requirement you assumed is a requirement nobody agreed
to** — and it will surface in CODE, when changing it is expensive.

**The rules, and they are not suggestions:**

1. **One question at a time.** A list of eight questions gets one vague answer to the first and
   silence for the rest. Ask, wait, listen, ask the next one — informed by the answer you just got.
2. **Do not propose a solution before the problem is agreed.** Not the architecture, not the stack,
   not the endpoints. As long as you are still discovering *what* is needed, *how* is out of scope.
   If the user jumps straight to a solution, take it as input, not as a decision: "Got it, you were
   thinking of it as X — before we get there, what happens today when…?"
3. **Do not fill silences with assumptions.** Anything the user did not say and you cannot verify in
   the codebase is a question, not a default. If you genuinely have to assume something to keep
   moving, **say so out loud and mark it in the PRD**.
4. **Ask for the concrete case.** "What should happen if the email is already registered?" beats "do
   you need validations?". Generic questions get generic answers, and a generic answer is not a
   requirement.
5. **Question what does not fit.** If two things the user said contradict each other, or a
   requirement makes no sense against what the code does, say it plainly: "This clashes with X —
   which of the two wins?" Silently picking one is the worst option available.
6. **Stop when it is enough.** Socratic does not mean interrogating. The moment you can write ACs
   that are binary and testable, stop asking and write the PRD.

Two signals that you skipped this protocol: the PRD came out on the first try with no back and
forth, or `ddw-validate-prd` returns FAILs about ambiguity. Both mean you were writing what you
imagined instead of what the user needs.

> **Not in DISCOVERY.** That tier is already free exploration and has its own flow; adding a
> question protocol on top only gets in the way.

---

## If tier == FEATURE

### Full PRD Protocol

1. Check whether a related PRD exists in `docs/ddw/prd/`.
2. If one does: read it and assess whether it covers the new requirement.
   - If it partially covers it → propose an update.
   - If it does not cover it → create a new PRD.
   - **If it comes from DISCOVERY** (`prd-DISC-*`): read it, assess coverage, and propose
     adjustments if the implementation context calls for them. It may need: updating the
     ticket/tracker in the header, adjusting NFRs now that the stack is known, adding technical
     dependencies.
   - **If it is this ticket's own PRD** (`prd-{ticket}.md` exists and the ticket is a sub-ticket of
     a split): it was written and validated when the parent was split, and it is the PRD for the
     work in hand. **Do not rebuild it and do not run the Socratic protocol over it again** — that
     conversation already happened, and repeating it teaches the user that approving a split means
     nothing. Read it, re-validate it (below), and go. Propose changes only if the codebase moved
     underneath it or a sibling sub-ticket that closed since changed what this one has to assume.
3. Disambiguate the requirements with the user, following the **Socratic Protocol** above: one
   question at a time, no solutions before the problem is agreed, no filled-in assumptions. Do not
   use plan mode here — this phase is exploratory and conversational.

### Create or update the PRD

**NON-NEGOTIABLE RULE:** generating or modifying the PRD is done EXCLUSIVELY through the
`ddw-create-prd` skill. **Writing the PRD inline from the agent is forbidden** — the skill
encapsulates the template, naming, file location, `PRD loops` handling and output format.

4. Invoke the skill in the appropriate mode:
   - **New PRD** (does not exist in `docs/ddw/prd/`): invoke the skill via the Skill tool with
     `skill="ddw-create-prd"` in creation mode (do NOT write the PRD inline, do NOT read SKILL.md as
     a file). The skill generates `docs/ddw/prd/prd-{ticket}.md` with the standard template and the data
     from the state (`ticket`, `tracker`, `tier`).
   - **Existing PRD needing changes** (partial coverage, scope adjustment, a PRD inherited from
     DISCOVERY): invoke the skill via the Skill tool with `skill="ddw-create-prd"` in update mode
     (do NOT write the PRD inline, do NOT read SKILL.md as a file). The skill reads the existing
     PRD, applies the changes in place and increments `PRD loops` in the header.
5. **ONLY when the PRD file is written to disk and complete** — never before,
   never in parallel with `ddw-create-prd` — invoke `ddw-validate-prd`, which
   RUNS `.ddw/scripts/validate_prd.py <prd> --tier <tier>`. The script applies
   the catalog's mechanical rules (F-PRD-01 to F-PRD-09, W-PRD-01 to W-PRD-05)
   and writes the receipt the `define` gate demands; the MANUAL rules
   (F-PRD-02, F-PRD-07) you judge yourself and state explicitly. Loading both
   skill files together as reading material is not a sequence: create
   finishes, THEN validate runs, on the file.
6. Show the user the SCRIPT's report — persisted at
   `docs/ddw/prd/prd-{ticket}.validation.md` — verbatim (✅/❌/⚠️), plus your
   two MANUAL verdicts. **If there is at least 1 FAIL → result = FAILED. Gate
   blocked.**
7. **If BLOCKED (there are FAILs with disambiguation questions):**
   - Present the questions to the user.
   - Wait for answers.
   - Re-invoke the skill via the Skill tool with `skill="ddw-create-prd"` in update mode to fold the
     answers into the PRD (do NOT write inline; the skill increments `PRD loops` and re-runs
     `ddw-validate-prd`).
   - Repeat until PASSED.
8. **Scope control** (see the section below).
9. Present the PRD **and its validation report** (name the report file and
   quote its `Result:` line) to the user for explicit approval. An approval
   request that shows no validation result is asking for a blind signature.

> **Impatience is not approval.** "Just start already", "forget the spec", "hurry up" say the user
> wants this to move — not that they read the PRD and agree with it. Reading them as consent is how
> a requirement nobody checked reaches CODE with an approval in the history that never happened.
> Say what is missing and ask for it plainly: *"The PRD is validated and waiting for your OK —
> confirm it and I move to PLAN."* Wanting speed is a good reason to be brief. It is not a reason to
> answer on their behalf.

### PRD Template

The canonical template is defined by the `ddw-create-prd` skill. **It is not duplicated here**, to
avoid drift between sources. The file path is `docs/ddw/prd/prd-{ticket}.md` (defined in
`.ddw/rules/branches.instructions.md`).

---

## If tier == FIX

### Lightweight PRD Review Protocol

1. Search `docs/ddw/prd/` for an existing PRD covering the fix's area.
2. If a related PRD is found → read it in full.
3. Assess: does the fix contradict the PRD, or reveal a gap in it?

**If there is NO gap:**
- Report: "Existing PRD [name] covers this fix. No update required."
- Ask the user to approve moving on.

**If there IS a gap (BLOCKING GATE):**
- Present the discrepancy to the user:
  ```
  ┌─────────────────────────────────────────────────────────┐
  │  DEFINE — Gap detected in the PRD                        │
  ├─────────────────────────────────────────────────────────┤
  │                                                          │
  │  PRD: [PRD name]                                         │
  │  Gap: [description of the gap found]                     │
  │  Impact: [what it means for the fix]                     │
  │                                                          │
  │  Proposal: update the PRD adding [description].          │
  │  Do you approve updating the PRD?                        │
  └─────────────────────────────────────────────────────────┘
  ```
- **Wait for approval BEFORE modifying the PRD.**
- Only after approval: invoke the skill via the Skill tool with `skill="ddw-create-prd"` in update
  mode to apply the changes (do NOT modify the PRD inline, do NOT read SKILL.md as a file). The
  skill increments `PRD loops` and re-runs `ddw-validate-prd`.
- If validation ends up BLOCKED → present the questions to the user, wait for answers, re-invoke the
  skill via the Skill tool with `skill="ddw-create-prd"` in update mode to fold in the answers, and
  re-validate.

**If no related PRD exists:**
- Report: "No PRD found related to this fix's area."
- Ask the user to approve moving on without a PRD.

---

### Root Cause Analysis (mandatory for FIX)

1. **Root cause analysis is mandatory:**
   - Investigate the code in the defect's area.
   - Identify the technical root cause (not just the symptom).
   - Document the chain of events that led to the defect.

2. **Review existing PRDs:**
   - Search `docs/ddw/prd/` for a PRD covering the affected area.
   - Assess: does the defect reveal a gap in the PRD?

3. **If there IS a gap in the PRD (BLOCKING GATE):**
   - Apply the gap protocol above.
   - Wait for approval before modifying.

4. **Document the root cause:**
   Create the analysis record:
   ```
   ┌─────────────────────────────────────────────────────────┐
   │  DEFINE — Root Cause Analysis                            │
   ├─────────────────────────────────────────────────────────┤
   │                                                          │
   │  Ticket: [ticket] — [title]                              │
   │                                                          │
   │  Root cause: [technical description]                     │
   │  Affected component: [module/service]                    │
   │  Related PRD: [name or "none"]                           │
   │  Gap in the PRD: [yes/no — description if applicable]    │
   │                                                          │
   │  Do you confirm this analysis?                           │
   └─────────────────────────────────────────────────────────┘
   ```

5. Save the root cause analysis as `docs/ddw/specs/rca-{ticket}.md`.

---

## Scope Control (applies to all tiers)

**Principle: every ticket should be as small as possible and independently shippable to
production.**

### For FEATURE — mandatory assessment

After drafting the PRD, assess:

1. **Number of acceptance criteria:** more than 5–7 ACs and it is probably too big.
2. **Modules affected:** if it touches more than 2–3 distinct modules/areas, consider splitting.
3. **Independence:** can each part reach production without the others?

**If the scope is too large:**

```
┌─────────────────────────────────────────────────────────┐
│  DEFINE — Scope Check                                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ⚠️  The PRD looks too big for a single ticket.           │
│                                                          │
│  Acceptance criteria: [N]                                │
│  Modules affected: [list]                                │
│                                                          │
│  Proposed split:                                         │
│    a. [sub-deliverable] — [ACs it covers]                │
│    b. [sub-deliverable] — [ACs it covers]                │
│    c. [sub-deliverable] — [ACs it covers]                │
│                                                          │
│  Dependencies: [b depends on a, c is independent]        │
│  Suggested order: a → b → c                              │
│                                                          │
│  Each sub-deliverable becomes a sub-ticket with its own  │
│  complete pipeline.                                      │
│                                                          │
│  Do you want to split it, or keep it as is?              │
└─────────────────────────────────────────────────────────┘
```

- If the user decides to keep it → continue (document the decision).
- If the user accepts the split → apply the **Split Protocol** (below).

### Split Protocol

**Sub-ticket naming:**
- ALWAYS with a lowercase letter suffix: `{TICKET}a`, `{TICKET}b`, `{TICKET}c`, …
- The first is ALWAYS `a`. **NEVER leave a sub-ticket without a letter suffix.**
- Examples: `FEAT-002a`, `FEAT-002b`, `FEAT-002c`, `PROJ-123a`, `PROJ-123b`

**1. Create the parent PRD (index):**

The original PRD (`prd-{TICKET}.md`) becomes an index document:

```markdown
# Parent PRD: [Original title]

| Metric | Value |
|--------|-------|
| Ticket | [TICKET] |
| Date | [timestamp] |
| Status | Split |

## Sub-tickets

| Sub-ticket | Title | PRD | Dependencies | Status |
|---|---|---|---|---|
| {TICKET}a | [title] | prd-{TICKET}a.md | none | active |
| {TICKET}b | [title] | prd-{TICKET}b.md | depends on a | pending |
| {TICKET}c | [title] | prd-{TICKET}c.md | independent | pending |

## Suggested implementation order
a → b → c

> **The `Status` column is maintained, not decorative.** CLOSEOUT's closeout moves the finished
> sub-ticket to `done` — with where its branch landed — and the next one to `active`. Left
> unmaintained it says every sub-ticket is pending forever, and a reader has no way to tell that
> from the truth.

## Original context
[Summary of the original problem/opportunity that motivated the split]
```

**2. Create ALL the sub-PRDs:**

Create a complete PRD for each sub-ticket: `prd-{TICKET}a.md`, `prd-{TICKET}b.md`, etc. Each follows
the standard PRD template with its own ticket, title, FRs, ACs, and so on.

**3. Validate ALL the sub-PRDs:**

Run `ddw-validate-prd` on EACH sub-PRD. They all have to pass BEFORE continuing. If any fails,
iterate until it passes.

**4. Close the parent run, then open sub-ticket `a` as its own run:**

The parent ticket is finished as a unit of work — it became an index. So it is **left**, not
edited into something else, and `{TICKET}a` starts the way every ticket starts.

Two writes, in this order:

1. **Leave the parent.** One transition to `IDLE` whose entry declares the walk-away:
   `"action": "pause: split into {TICKET}a/b/c"`, stamped `"ticket": "{TICKET}"`. At IDLE, `tier`
   is null and `gates` is `{}` — that is the invariant, and `transition.py` writes it for you.
2. **Open the sub-ticket.** `IDLE → CLASSIFY` with `ticket` = `{TICKET}a` and the sub-ticket's
   title, then `CLASSIFY → DEFINE`. The tier is the parent's — a split does not reclassify the
   work, it divides it.

Then rename the branch to `feat/{TICKET}a-short-name` (or create it and discard the previous).

> **Do NOT change `ticket` in the header of a run that is still open.** A run belongs to one
> ticket: its history entries are stamped with the parent, and a header naming the sub-ticket
> makes every one of them unattributable. The pre-write hook refuses it and names this path.
>
> It used to say "update `.ddw-state.json`: `ticket` → `{TICKET}a`", and that instruction is what
> produced the worst failure this method has had. The write was accepted at the time and condemned
> a moment later by the post-write net, on every subsequent tool call, with no legal way back — the
> header could not return without a history entry, and the entry it needed was not an edge in the
> graph. The model tried eight times and escaped the only way left: deleting the state, and the
> run's history with it.

**5. Continue the pipeline with sub-ticket `a`.**

Sub-tickets b, c, d are independent future pipelines. When they start, they come in through
CLASSIFY → DEFINE as usual. In DEFINE, the PRD already exists — it gets re-validated (non-negotiable
rule) and work continues.

### For FIX

Fixes are naturally bounded. If a fix requires changes across many files or modules, ask: "Is this
still a fix, or is it actually a behavior change?"

---

## Transition

**Where this phase goes depends on the tier**, and the graph is the authority:
QUICK-FIX has no PLAN phase, so for that tier the next phase is **CODE**
(`DEFINE → CODE`, gate `define`). For every other tier it is **PLAN**
(`DEFINE → PLAN`, gate `define`).

Sending a QUICK-FIX to PLAN is not a slower route, it is a refused write: that
edge does not exist in its graph, the hook rejects it, and the model is left
stuck with no explanation.

### Transition summary (MANDATORY before asking for confirmation)

Present to the user:

```
┌─────────────────────────────────────────────────────────┐
│  DEFINE — PRD Approved                                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Ticket: [ticket] — [title]                              │
│  Tier: [tier]                                            │
│                                                          │
│  PRD summary:                                            │
│    Functional requirements: [N]                          │
│    Non-functional requirements: [N]                      │
│    Acceptance criteria: [N]                              │
│    Modules affected: [list]                              │
│    Dependencies: [list or "none"]                        │
│                                                          │
│  Validation: ✅ PASSED ([N] checks, [N] warnings)        │
│                                                          │
│  📄 You can review the full PRD here:                    │
│     docs/ddw/prd/prd-[ticket].md                         │
│                                                          │
│  → Shall we move on to the PLAN phase?                   │
└─────────────────────────────────────────────────────────┘
```

For FIX (no new PRD, or a PRD with no changes):

```
┌─────────────────────────────────────────────────────────┐
│  DEFINE — Ready to plan                                  │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Ticket: [ticket] — [title]                              │
│  Tier: [tier]                                            │
│                                                          │
│  PRD: [unchanged / updated / not applicable]             │
│  Root cause: [FIX only — summary]                        │
│                                                          │
│  📄 Documents produced:                                  │
│     [docs/ddw/prd/prd-{ticket}.md if applicable]         │
│     [docs/ddw/specs/rca-{ticket}.md if FIX]              │
│                                                          │
│  → Shall we move on to the PLAN phase?                   │
└─────────────────────────────────────────────────────────┘
```

Wait for the user's explicit confirmation.
> **Under `autonomy: "minimal"` this arrow does not wait.** The state is still
> written, the gates are still owed and still refused by the hook, and the
> closing box is still shown — what goes away is the pause for a confirmation of
> something a receipt already attests. Three things stop the run anyway, in
> either mode: a decision nobody wrote down, a corrective loop at its ceiling,
> and a corrupt state. See `.ddw/orchestrator.md` § Autonomy.

### On confirmation:

1. **Commit this phase's artifacts** with `Skill(skill="ddw-commit")`: the PRD, and the RCA if the
   tier is FIX. Documentation commit — `📝 docs`, never source code. Thinking that is not committed
   is thinking that gets lost the day the ticket is abandoned or the branch is deleted.
2. Update `.ddw-state.json`:
   - `phase` → `"PLAN"`
   - Add `"define": true` to `gates`
   - Add an entry to `history`: transition DEFINE → PLAN, **stamped with `ticket` and `tier`** (see `.ddw/rules/state.instructions.md`)

Note: the PRD path is derived by convention (`docs/ddw/prd/prd-{ticket}.md`); it is not stored in the
state.

---

**FORBIDDEN in this phase:**
- Writing source code
- Creating specs or fix-plans
- Running tests
- Committing anything other than this phase's own artifacts (never source code)
- Jumping to another phase without approval
- **Skipping `ddw-validate-prd`** — even if the PRD already existed or was validated previously
  (e.g. in DISCOVERY). Validation is ALWAYS mandatory before approving the `define` gate.
