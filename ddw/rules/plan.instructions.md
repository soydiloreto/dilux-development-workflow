---
applyTo: '**'
version: 1.6.0
---

# Phase 2: PLAN (Technical Planning)

**Goal:** design the technical solution and write it to disk as a spec or fix-plan.

**Do NOT use Claude's Plan Mode (EnterPlanMode) in this phase.** Design here is conversational:
read, analyze, present to the user, iterate, and write the spec/fix-plan to disk once they approve.

Read `.ddw-state.json.tier` to determine your behavior.

---

## Rules for this Phase

- "go ahead", "approved", "go", "run it" or any variant of approval means **WRITE THE SPEC/FIX-PLAN
  DOCUMENT TO DISK**. It does not mean writing source code.
- After writing to disk: run `ddw-validate-spec`, present the summary, and **STOP**. Do not write
  code.
- If the user says "run the code" or "implement it": answer "We are in the PLAN phase. First I write
  the spec to disk, then we move to CODE to implement. Shall I save the spec?"
- **NEVER modify the PRD in this phase.** If the design reveals the PRD needs changes, apply the
  corrective loop protocol (see the section below).

---

## Corrective loop back to DEFINE (when the PRD needs changes)

**Trigger:** during technical design you discover the PRD needs modification. This can happen
because:
- A technical decision changes a requirement (e.g. dropping a field, changing an entity).
- The design reveals an FR is incomplete or contradictory.
- The user asks for a change during the conversation that impacts the requirements.

**Protocol:**

1. **Detect and communicate:**
   ```
   ┌─────────────────────────────────────────────────────────┐
   │  PLAN — Corrective loop back to DEFINE required          │
   ├─────────────────────────────────────────────────────────┤
   │                                                          │
   │  Reason: [description of the change impacting the PRD]   │
   │  FRs affected: [list of FR-xx that change]               │
   │  ACs affected: [list of AC-xx that change]               │
   │                                                          │
   │  To modify the PRD we need to go back to the DEFINE      │
   │  phase, apply the changes, re-validate, and return.      │
   │                                                          │
   │  Do we proceed with the corrective loop?                 │
   └─────────────────────────────────────────────────────────┘
   ```

2. **On confirming the corrective loop:**
   - Update `.ddw-state.json`:
     - `phase` → `"DEFINE"`
     - Remove `define` from `gates` (it will be re-validated)
     - Add an entry to `history`: corrective loop PLAN → DEFINE (reason in `action`), **stamped with `ticket` and `tier`** (see `.ddw/rules/state.instructions.md`)
   - **Do not delete the PLAN artifacts** (if there is a partial spec on disk, leave it — it will be
     picked up on return).

3. **In DEFINE (re-entry):**
   - Apply the modifications to the PRD.
   - Increment `PRD loops` in the header, and reset `Loops since last human decision` to 0: coming
     back from PLAN is a decision a person made, which is exactly what the ceiling waits for.
   - Run `ddw-validate-prd` (MANDATORY — no exceptions).
   - The user approves the updated PRD.
   - Transition back to PLAN: `phase` → `"PLAN"`, `gates.define` → `true`.

4. **On returning to PLAN:**
   - Resume designing the spec, taking the PRD changes into account.
   - If there was a partial spec on disk, update it to reflect the changes.
   - Continue the normal PLAN flow.

---

## If tier == FEATURE

### Inputs
- The PRD at `docs/ddw/prd/prd-{ticket}.md` (if `gates.define` is true)
- The project's stack: the "Stack" section of `AGENTS.md`
- The project's architecture conventions ("Architecture conventions" section of `AGENTS.md`)

### Design Process
1. Read the complete PRD.
2. Read the architecture conventions.
3. Design the technical solution:
   - Components affected
   - Schema/API changes
   - New files to create
   - Existing files to modify
   - New dependencies
4. Split it into numbered implementation blocks. Each block must be independently verifiable.
5. **Impact check against the codebase (MANDATORY before presenting).**
6. Present the plan to the user for iteration (include the impact report).
7. Spawn an agent via the Agent tool with `subagent_type="ddw-arch-auditor"` to validate the
   proposed architecture (do NOT read AGENT.md as a file).

### Impact Check (Step 5 — mandatory)

**Before presenting the plan to the user, systematically verify that the plan is complete.** You
cannot present a plan without this step.

**Delegate this check to the `ddw-impact-scanner` subagent** via the Agent tool with
`subagent_type="ddw-impact-scanner"`, passing it the draft plan, the spec and the conventions. Do
not run it inline: these are exhaustive searches across the whole codebase, and its intermediate
work — dozens of files read — would pollute the context right before the part that needs the most
reasoning. The subagent returns only the verdict.

The scanner runs these 5 checks:

1. **File existence:** for every file listed in every block, verify it exists in the codebase (or is
   marked "new"). If a file does not exist → the plan has an error.

2. **Siblings / parallel implementations:** if the plan modifies a concrete implementation (e.g.
   `sqlite.py`), search for ALL the other implementations of the same protocol/interface/abstract
   class (e.g. `rest.py`, `graphql.py`). If there are uncovered siblings → add them to the plan or
   explicitly justify why they are not touched.

3. **Callers / call sites:** for every function or method whose signature the plan changes (adds
   parameters, changes types, etc.), find ALL the call sites in the codebase. If there are callers
   not covered by the plan → add them.

4. **Exports / imports:** if the plan adds new functions or classes to a module, check whether there
   is an `__init__.py` or barrel file that needs updating. If exports are missing → add them to the
   plan.

5. **Similar patterns:** if the plan modifies a pattern in one file (e.g. adding a permission check
   in `routes/users.py`), look for other files with the same pattern that also need the change (e.g.
   `routes/people.py`, `routes/auth.py`). Search with grep/glob, not from memory.

**Format of the report the scanner returns (include it when presenting the plan):**

```
┌─────────────────────────────────────────────────────────┐
│  PLAN — Impact Check                                     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ✅ Existence: [N] files verified                        │
│  ✅ Siblings: [N] parallel implementations reviewed      │
│  ✅ Callers: [N] call sites verified                     │
│  ✅ Exports: [N] modules verified                        │
│  ✅ Patterns: [N] files with a similar pattern reviewed  │
│                                                          │
│  Total files affected: [N]                               │
│  [complete file list]                                    │
│                                                          │
│  Gaps found and corrected: [N]                           │
│  [list of files added to the plan after the check that   │
│   were not in the original design]                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**If gaps are found:** fold them into the plan BEFORE presenting. Do not present a plan with known
gaps.

### Threat Modeling (MANDATORY for FEATURE)

Run `ddw-threat-modeling` on the proposed design, applying **every rule in section 3 of
`.ddw/rules/validation-rules.instructions.md`** (F-TM-01 to F-TM-07, W-TM-01 to W-TM-02):
- STRIDE analysis per component (F-TM-01).
- Trust boundary identification (F-TM-02).
- Every threat with a mitigation or a formally accepted risk (F-TM-03, F-TM-04).
- Sensitive data classification (F-TM-05).
- Reference to the spec's actual architecture, not generic boilerplate (F-TM-06).
- Encryption specified for PII/credentials (F-TM-07).
- If it finds CRITICAL/HIGH risks → fold the mitigations into the spec before writing it.

Result: `gates.threat` = `true`. The report is saved to `docs/ddw/security/threat-{ticket}.md` — in the
template `ddw-threat-modeling` defines, because `validate_threat.py` parses that structure and a
model nothing can parse is a model nothing can check. A PASSED run of that script writes
`.ddw-sessions/threat-validated-<hash>`, and **the `threat` gate asks for it**: the boolean alone no
longer opens PLAN→CODE, and editing the model afterwards costs another run.

### Creating / updating the Spec

**NON-NEGOTIABLE RULE:** generating or modifying the spec is done EXCLUSIVELY through the
`ddw-create-spec` skill. **Writing the spec inline from the agent is forbidden** — the skill
encapsulates the template, naming, location, `Spec loops` handling, update mode (which preserves
completed blocks) and output format.

- **New spec** (`docs/ddw/specs/spec-{ticket}.md` does not exist): invoke the skill via the Skill tool
  with `skill="ddw-create-spec"` in FEATURE creation mode (do NOT write inline, do NOT read SKILL.md
  as a file). The skill generates `docs/ddw/specs/spec-{ticket}.md` with the standard template and the
  data from the state.
- **Existing spec needing changes** (a FAILED loop, a PLAN ↔ DEFINE corrective loop, new
  requirements from the PRD): invoke the skill via the Skill tool with `skill="ddw-create-spec"` in
  update mode (do NOT modify inline, do NOT read SKILL.md as a file). The skill reads the existing
  spec, appends new blocks at the end with sequential numbering, preserves completed blocks (`[x]`),
  and increments `Spec loops`.

### Canonical template
The spec's template is defined by the `ddw-create-spec` skill. **It is not duplicated here**, to
avoid drift between sources. The path is `docs/ddw/specs/spec-{ticket}.md` (defined in
`.ddw/rules/branches.instructions.md`).

### Post-write validation
- The skill automatically runs `ddw-validate-spec` at the end of its execution, applying **every
  rule in section 2 of `.ddw/rules/validation-rules.instructions.md`** (F-SPEC-01 to F-SPEC-16,
  W-SPEC-01 to W-SPEC-03). The rules are evaluated mechanically — no subjective interpretation.
  **100% coverage of the PRD's FRs is mandatory (F-SPEC-01): if an FR is not covered by any block →
  FAIL, not WARNING.**
- **If FAILED (there are FAILs):**
  - Present the FAILs to the user with options: (a) fix the spec to cover what is missing, (b)
    modify the PRD to remove/defer the requirement (requires re-approving the PRD).
  - Wait for the user's decision.
  - If they fix the spec → re-invoke the skill via the Skill tool with `skill="ddw-create-spec"` in
    update mode to fold in the corrections (do NOT modify inline; the skill increments `Spec loops`
    and re-runs `ddw-validate-spec`).
  - If they modify the PRD → corrective loop back to DEFINE (see the protocol).
  - Repeat until PASSED (0 FAILs).
- Count the spec's blocks so you can set `block` in the state on transition.

---

## If tier == FIX

### Inputs
- The fix description from the state's `title`
- The related PRD (if any) at `docs/ddw/prd/prd-{ticket}.md`
- The project's stack: the "Stack" section of `AGENTS.md`

### Design Process
1. Analyze the problem in the code.
2. Identify the root cause.
3. Identify the files affected.
4. Design the correction.
5. **Impact check** (apply the same 5 checks as FEATURE — see the section above). For FIX, the most
   relevant checks are: siblings (other implementations), callers (functions with a modified
   signature), and similar patterns.
6. Run `ddw-threat-modeling` on the proposed design.
7. Present it to the user for approval (include the impact report).

> **Stability over elegance.** A FIX resolves a defect; it is not the moment to refactor. If it is
> a live production bug, prioritize the minimal correction and leave the cleanup for its own ticket.

### Creating / updating the Fix-Plan

**NON-NEGOTIABLE RULE:** generating or modifying the fix-plan is done EXCLUSIVELY through the
`ddw-create-spec` skill. **Writing the fix-plan inline from the agent is forbidden** — the skill
encapsulates the template, naming, location and format.

- **New fix-plan:** invoke the skill via the Skill tool with `skill="ddw-create-spec"` in FIX
  creation mode (do NOT write inline, do NOT read SKILL.md as a file). The skill generates
  `docs/ddw/specs/fix-{ticket}.md` from the fix-plan template, which includes the **Rollback plan**
  section and a reference to the RCA written in DEFINE.
- **Existing fix-plan needing changes** (a FAILED loop, new findings from the analysis): invoke the
  skill via the Skill tool with `skill="ddw-create-spec"` in update mode (do NOT modify inline, do
  NOT read SKILL.md as a file). The skill reads the existing fix-plan and applies the changes.

### Canonical template
The fix-plan's template is defined by the `ddw-create-spec` skill. **It is not duplicated here.** The
path is `docs/ddw/specs/fix-{ticket}.md`.

### Post-write validation
- The skill automatically runs `ddw-validate-spec`, applying the applicable rules from section 2 of
  `.ddw/rules/validation-rules.instructions.md` (F-SPEC-10, F-SPEC-11, F-SPEC-14 and F-SPEC-15 are
  mandatory for fix-plans).
- **If FAILED:** present the FAILs and re-invoke the skill via the Skill tool with
  `skill="ddw-create-spec"` in update mode to fold in the corrections (do NOT modify inline). Repeat
  until PASSED.
- There are no blocks in a fix-plan, so `block` stays `null`.

---

## Transition (applies to all tiers)

Requirements to advance:
1. The spec/fix-plan file exists on disk.
2. `ddw-validate-spec` returned **PASSED** (0 FAILs per rules F-SPEC-01 to F-SPEC-16 of
   `.ddw/rules/validation-rules.instructions.md`), which leaves
   `.ddw-sessions/spec-validated-<hash>` — and the `spec` gate asks for a receipt matching the
   spec's **current** bytes, so an edit after validating means validating again.
3. `ddw-threat-modeling` has run → `gates.threat` == `true`, with its own receipt.
4. The user approved the spec/fix-plan, **having seen the validator's whole checklist** — every rule
   ID with its ✅ / ⚠️ / ❌ — and the link to `<artifact>.validation.md`. An approval given on a
   summary is an approval of the summary.

### Transition summary (MANDATORY before asking for confirmation)

Present to the user:

```
┌─────────────────────────────────────────────────────────┐
│  PLAN — Spec Ready                                       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Ticket: [ticket] — [title]                              │
│  Tier: [tier]                                            │
│                                                          │
│  Spec summary:                                           │
│    Implementation blocks: [N]                            │
│    Files to create: [list]                               │
│    Files to modify: [list]                               │
│    Tests planned: [N]                                    │
│                                                          │
│  Validation: ✅ PASSED ([N] checks, [N] warnings)        │
│  Threat model: ✅ docs/ddw/security/threat-[ticket].md    │
│                                                          │
│  📄 You can review the full spec here:                   │
│     docs/ddw/specs/spec-[ticket].md                      │
│                                                          │
│  → Shall we move on to the CODE phase?                   │
└─────────────────────────────────────────────────────────┘
```

For FIX (no blocks):

```
┌─────────────────────────────────────────────────────────┐
│  PLAN — Fix-Plan Ready                                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Ticket: [ticket] — [title]                              │
│  Tier: [tier]                                            │
│                                                          │
│  Fix-plan summary:                                       │
│    Files to modify: [list]                               │
│    Correction steps: [N]                                 │
│    Tests planned: [N]                                    │
│    Regression risk: [Low/Medium/High]                    │
│                                                          │
│  Validation: ✅ PASSED ([N] checks, [N] warnings)        │
│  Threat model: ✅ docs/ddw/security/threat-[ticket].md    │
│                                                          │
│  📄 You can review the full fix-plan here:               │
│     docs/ddw/specs/fix-[ticket].md                       │
│                                                          │
│  → Shall we move on to the CODE phase?                   │
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

1. **Commit this phase's artifacts** with `Skill(skill="ddw-commit")`: the spec/fix-plan, the threat
   model, and the ADR if one was written. Documentation commit — `📝 docs`, no source code. The
   design is on the record before a single line gets written against it.
2. Update `.ddw-state.json`:
- `phase` → `"CODE"`
- Add `"spec": true` and `"threat": true` to `gates`
- `block` → `"1/{total}"` (for FEATURE with blocks, indicating the current block) or `null` (for
  FIX)
- Add an entry to `history`: transition PLAN → CODE, **stamped with `ticket` and `tier`** (see `.ddw/rules/state.instructions.md`)

---

**FORBIDDEN in this phase:**
- Writing product source code
- Modifying the PRD
- Committing anything other than this phase's own artifacts (never source code)
- Creating PRs
- Running code tests
