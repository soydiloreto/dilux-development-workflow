---
applyTo: '**'
version: 2.7.0
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
   the catalog's mechanical rules (F-PRD-01 to F-PRD-12, W-PRD-01 to W-PRD-06)
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
     answers into the PRD (do NOT write inline; the skill increments `PRD loops`, resets `Loops
     since last human decision` to 0 — the user just decided — and re-runs `ddw-validate-prd`).
   - Repeat until PASSED.
8. **Scope control** (the section below). A ⚠️ W-PRD-06 in the report you just showed IS this
   step's trigger, not a line to gloss: its own text says "legitimate if it was decided", and the
   one who decides is the USER, at the Scope Check box. Measured on a live run: 17 ACs, the
   warning shown verbatim, and the model answered it itself — "does not block" — asking for
   approval as if the report were clean. A warning that names a human decision is not the model's
   to wave through.
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

**Apply the same three to every part you are about to propose, and put each part's numbers in the
box.** The assessment ran once, on the parent, and nothing looked at what the split produced.
Measured across three runs of one source PRD: a split into four left children of 11, 12, 16 and 12
ACs — every one above the threshold that caused the split — and the box said "4 sub-tickets" without
saying that. The user approved a cut that had not made anything smaller, because the number that
would have told them was on nobody's screen. The decision to split, and how, stays theirs; the
numbers are not theirs to lose.

**And aim for balance.** A proposed cut of 11/6/2 has not split the problem, it has renamed it:
the big part is still over the ceiling that triggered the split, and the smallest was never a
ticket. Before proposing, look for the most even cut that keeps every part independently
shippable; a part still over the ceiling goes in the box on its own line — with the reason no
smaller cut ships — so the user approves it knowingly, not by not seeing it.

The first two are signals that something needs looking at. **The third is the one that decides**,
and it is the principle at the top of this section: a part that cannot reach production on its own
is not a part, it is a layer. Splitting a feature into "the models", "the routes" and "the
templates" satisfies both counts and delivers nothing at any point.

**If the scope is too large — and a ⚠️ W-PRD-06 in the validation report means it is, until the
user says otherwise:**

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
│    a. [sub-deliverable] — [ACs it covers] ([N] ACs)      │
│       ships alone: [what a user can do if we stop here]  │
│    b. [sub-deliverable] — [ACs it covers] ([N] ACs)      │
│       ships alone: [...]                                 │
│    c. [sub-deliverable] — [ACs it covers] ([N] ACs)      │
│       ships alone: [...]                                 │
│                                                          │
│  Every AC of the original is taken by exactly one part.  │
│  Parts still over 7 ACs: [none | which, and why]         │
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

- If the user decides to keep it → continue, and document the decision IN THE PRD — so the next
  reader of its W-PRD-06 finds it decided, not pending.
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
| Acceptance criteria to cover | [N] |

## Sub-tickets

| Sub-ticket | Title | PRD | ACs | Dependencies | Status |
|---|---|---|---|---|---|
| {TICKET}a | [title] | prd-{TICKET}a.md | AC-01, AC-02 | none | active |
| {TICKET}b | [title] | prd-{TICKET}b.md | AC-03, AC-04 | depends on a | pending |
| {TICKET}c | [title] | prd-{TICKET}c.md | AC-05 | independent | pending |

> **The `ACs` column and the count above it are what make the split checkable.** This protocol
> REPLACES the parent with this index, so the moment it lands the original list of acceptance
> criteria is gone and "did the parts cover the whole?" can no longer be answered from anything.
> `validate_prd.py` reads these two and refuses an index whose parts leave an AC behind or claim one
> twice (F-PRD-10).
>
> **The count is everything the parts must cover**, which is not always what the source document
> had: DEFINE legitimately adds criteria the user decided on, and those are covered by a part like
> any other. So the two have to agree with each other — an index that declares one number and hands
> out criteria above it is refused (F-PRD-10), because whichever of the two is wrong, reconciling
> them is a sentence somebody has to write. When criteria WERE added, write that sentence under the
> table: which range came from the source and which was decided here, with the date. Measured: an
> index declared 22 where its source had 17, and the receipt vouched for "the 22 of the original".

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

**AC ids are GLOBAL across the split — a sub-PRD carries the ids the index assigns it.** The part
that takes AC-09..AC-17 writes its criteria as AC-09..AC-17; it does NOT restart at AC-01.
Measured on a live split: the index said "b takes AC-09..AC-17", the sub-PRD numbered them
AC-01..AC-09, and every cross-reference between the two documents had two possible answers.
`validate_prd.py` refuses an index whose on-disk parts never name the criteria it assigns them
(F-PRD-11). FR ids stay local to each sub-PRD — nothing cross-references those between documents.

**3. Validate ALL the sub-PRDs:**

Run `ddw-validate-prd` on EACH sub-PRD **and on the index**. They all have to pass BEFORE
continuing. If any fails, iterate until it passes. The index is judged by F-PRD-10 and F-PRD-11
alone — it is not a PRD and is not held to a PRD's sections — and those two are the only thing
standing between a split and an acceptance criterion nobody noticed was dropped or renamed.
Re-validate the index LAST, after the sub-PRDs exist: F-PRD-11 reads the parts off the disk, so an
index validated before its parts has been asked only half the question.

### Multirepo split — an initiative that spans repositories

When CLASSIFY set the scope to **multi-repo** (see `classify.instructions.md` § Repo family), this
repo is the family's **workspace** and the DEFINE artifact is a **multirepo index**, not a PRD with
ACs. The children are not sub-tickets of this repo — they are ordinary tickets each run IN its own
repository, by whoever stands there, with the full pipeline of that repo's tier.

The index (`docs/ddw/prd/prd-{TICKET}.md`):

```markdown
# Parent PRD: [Initiative title]

| Metric | Value |
|--------|-------|
| Ticket | [TICKET] |
| Date | [timestamp] |
| Status | Multirepo split |

## Repos

| Repo | Ticket | Scope | Depends on | Status |
|---|---|---|---|---|
| owner/repo-back | [TICKET] | [what that repo builds] | none | active |
| owner/repo-bff | [TICKET] | [what that repo builds] | repo-back | pending |
| owner/repo-front | [TICKET] | [what that repo builds] | repo-bff | pending |

## Original context
[The problem/opportunity, and where the source PRD came from]
```

- **Every child carries the SAME initiative id** — the branch each repo opens names it, and that
  name is how the forge is asked about that repo's part.
- **`Status` speaks a fixed vocabulary**: `active`, `pending`, `done`, `dropped: <why>`, and
  `done (unverified: <why>)`. The last two are the DECLARED ways out — a part the initiative gave
  up, and a human asserting a merge the forge could not confirm. Free prose in that column is a row
  the gate cannot hold (F-PRD-12).
- **`done` is not yours to write.** The family write gate asks the forge before letting a row say
  `done`: no MERGED pull request whose branch names the child ticket in that repo → the write is
  refused. This is the initiative that cannot lie — its one enforcement point, and the reason the
  index's shape is a FAIL rule rather than a convention.
- **Validate the index** with `ddw-validate-prd` like any DEFINE artifact (it is judged by
  F-PRD-12 alone and writes the ordinary receipt), show it, and on approval **pause the parent**
  (`pause: multirepo split into <repos>`) — the work now happens in the children's repositories.
  This workspace's later sessions update the rows as the forge confirms them.
- **Nothing here writes into the other repositories, ever.** The children read this index
  (read-only, from the sibling clone or the forge); their closeouts cannot update it — the update
  happens here, in a workspace session, against the forge's answer.
- **The pause's closing message prints the launch plan.** The developer walks the family by hand —
  that is the design — so the message that parks the parent hands them the walk, executable: one
  line per repo, in dependency order, with the `cd` to the sibling clone and the prompt to give it
  (`Implementá mi parte de <TICKET>`), marking which child is unblocked NOW and which waits on
  whose merge. Asked for later ("dame el plan de lanzamiento"), any workspace session rebuilds it
  from the index and the forge's current answers. A reparto whose next step the developer has to
  reconstruct from a table is a reparto that stalls at every handoff — the owner asked for this
  after walking the first live initiative.


**4. Close the parent run, then open sub-ticket `a` as its own run:**

The parent ticket is finished as a unit of work — it became an index. So it is **left**, not
edited into something else.

Two writes, and under `assisted` each one is A TURN — one arrow per response is the hook's rule,
so the banner that closes each turn promises exactly the one arrow the next ok will take, never
the chain. Measured before this sentence existed: one banner promised "commit + close + open in
DEFINE", the hook (correctly) landed the first arrow, and the user paid two extra oks for a
promise the enforcement could never let the model keep.

1. **Leave the parent.** One transition to `IDLE` whose entry declares the walk-away:
   `"action": "pause: split into {TICKET}a/b/c"`, stamped `"ticket": "{TICKET}"`. At IDLE, `tier`
   is null and `gates` is `{}` — that is the invariant, and `transition.py` writes it for you.
   The phase commit (the PRDs and their reports) goes in this same turn — a commit is not an
   arrow. End the turn; the banner offers opening `{TICKET}a`.
2. **Open the sub-ticket, directly in the phase the split paused from.** A split child does NOT
   pass through CLASSIFY: that phase exists to produce tier, ticket and autonomy, and all three
   already exist — the parent's run produced them and the user approved the split that named this
   child. Sending it through CLASSIFY re-decides nothing and costs the user a turn that decides
   nothing. One transition, built with the helper:

   ```bash
   .ddw/scripts/transition.py --to DEFINE --tier <TIER> --ticket {TICKET}a \
       --title "<the child's name, one line>" \
       --autonomy <the mode this child runs under> \
       --action "split: abrir {TICKET}a — <title>"
   ```

   The `split:` verb is the declaration the hook verifies: the parent's newest entry must be its
   own `pause: split into …`, the destination must be the phase that pause left, the child's name
   must derive from the parent's (`{TICKET}` + one lowercase letter), the tier must be the
   pause's, and the journal must have seen the pause land. The child opens with `gates: {}` —
   whatever the parent earned closed with the parent.

   **Paste the helper's output VERBATIM**, filling in only `title`/`tracker` in that same write.
   Never touch an existing history entry — editing the pause's stamp to "fit" the child is
   exactly the mutation the append-only check refuses, and it was tried.

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

Sub-tickets b, c, d are independent future pipelines. When they start, they open the same way `a`
did — `split:` directly into the phase the split paused from; the parent's pause is every child's
proof, and closing one child does not spend it. In DEFINE, the PRD already exists — it gets
re-validated (non-negotiable rule) and work continues.

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
