---
applyTo: '**'
version: 1.2.0
---

# DISCOVERY Tier (Ideation and Product Definition)

**Goal:** explore an idea, refine it conversationally, and formalize it into one or more validated
PRDs. This tier does NOT run code — it only produces product documentation.

---

## Principles

1. **Free flow, not linear.** The user can alternate between exploration and formalization as many
   times as they want. There are no rigid internal phases.
2. **Rigor in the output.** Even though the process is free, every PRD must pass `ddw-validate-prd`
   before it counts as ready.
3. **Explicit closeout.** A DISCOVERY session only ends when the user confirms it and all the PRDs
   are validated.

---

## Concept Document

The concept is the central exploration artifact. It is created when DISCOVERY starts and updated
iteratively throughout the conversation.

**Path:** `docs/ddw/discovery/concept-{ticket}.md`

### Template (semi-structured)

```markdown
# Concept: [Title]

| Metric | Value |
|--------|-------|
| Ticket | [DISC-NNN] |
| Date | [timestamp] |
| Status | Exploring / Formalizing / Closed |

## Vision
[What are we trying to achieve, at a high level? One or two sentences capturing the essence.]

## Problem / Opportunity
[What problem does it solve, or what opportunity does it take? Business context.]

## Target Users
[Who uses this? Roles, profiles, needs.]

## Candidate Features
- [Feature 1 — brief description]
- [Feature 2 — brief description]
- [Feature 3 — brief description]

## Constraints and Considerations
[Technical, business, regulatory, time or budget limitations.]

## Decisions Made
[Filled in iteratively during the conversation. Each decision with a date and context.]

- [date]: [decision] — [context/reason]

## Identified PRDs

| # | Title | File | Status |
|---|-------|------|--------|
| 1 | [name] | prd-{ticket}-01.md | identified / created / validated |
| 2 | [name] | prd-{ticket}-02.md | identified / created / validated |
```

### Concept Rules

- The sections are **suggested, not blocking**. They get filled in progressively.
- The concept is updated whenever relevant new information comes out of the conversation.
- The "Identified PRDs" table stays in sync with `.ddw-state.json.discovery.prds`.
- When closing DISCOVERY, every section must have content (it does not need to be perfect, but it
  cannot be empty).

---

## Workflow

### Step 1: Start

On entering DISCOVERY (after CLASSIFY):

1. Create the concept document at `docs/ddw/discovery/concept-{ticket}.md` from the template.
2. Initialize `.ddw-state.json.discovery`:
   ```json
   {
     "concept": "draft",
     "prds": []
   }
   ```
3. Begin the conversational exploration with the user.

### Step 2: Exploration (free)

- Ask questions to understand the idea:
  - What problem does it solve?
  - Who is going to use it?
  - Which features are essential vs. nice-to-have?
  - Are there technical or business constraints?
  - Are there existing systems it interacts with?
- Update the concept iteratively with the answers.
- Use AI capabilities to:
  - Identify implicit features that were not mentioned.
  - Detect dependencies between features.
  - Suggest a logical split into independent PRDs.
  - Point out ambiguities or contradictions.

### Step 3: PRD Identification

Once there is enough clarity (it may be partial):

1. Propose the split into PRDs to the user:
   ```
   ┌─────────────────────────────────────────────────────────┐
   │  DISCOVERY — Identified PRDs                             │
   ├─────────────────────────────────────────────────────────┤
   │                                                          │
   │  Based on what we have explored, I propose splitting     │
   │  this into [N] PRDs:                                     │
   │                                                          │
   │  1. [Title] — [1-line description]                       │
   │  2. [Title] — [1-line description]                       │
   │  3. [Title] — [1-line description]                       │
   │                                                          │
   │  Dependencies between PRDs:                              │
   │    PRD 2 depends on PRD 1 (uses its data model)          │
   │    PRD 3 is independent                                  │
   │                                                          │
   │  Do you approve this split? Anything you want to adjust? │
   └─────────────────────────────────────────────────────────┘
   ```
2. On approval, add the PRDs to the state:
   ```json
   {
     "concept": "draft",
     "prds": [
       {"id": "01", "title": "Product catalog", "status": "identified"},
       {"id": "02", "title": "Shopping cart", "status": "identified"},
       {"id": "03", "title": "Payment gateway", "status": "identified"}
     ]
   }
   ```
3. Update the "Identified PRDs" table in the concept.

**This list is mutable.** The user can add, remove or rename PRDs at any time.

### Step 4: PRD Formalization (free)

For each identified PRD:

1. Invoke the skill via the Skill tool with `skill="ddw-create-prd"` to create the PRD (do NOT write
   it inline, do NOT read SKILL.md as a file; the skill already has the template and handles
   naming).
   - Path: `docs/ddw/prd/prd-{ticket}-{NN}.md` (e.g. `prd-DISC-001-01.md`)
   - The PRD **MUST include the complete header** with `PRD loops: 0` and `Loops since last human
     decision: 0`. Both are incremented every time the PRD is modified (in DISCOVERY and in future
     DEFINE phases alike); the second goes back to 0 whenever a human decides something. Without
     them, later modifications cannot be tracked and the ceiling has nothing to measure.
   - The PRD follows exactly the same template and rules as any PRD in the normal pipeline.
2. Update the PRD's status in the state to `"created"`.
3. Run `ddw-validate-prd` on the PRD.
   - If PASSED → update status to `"validated"`.
   - If BLOCKED → present the disambiguation questions, iterate, re-validate.
4. Update the table in the concept.

**At any moment the user can:**
- Go back to exploring (refine the concept, add features).
- Add new PRDs to the list.
- Remove PRDs from the list (if they decide against them).
- Modify an already-created PRD (re-validate afterwards).
- Ask for a PRD that turned out too big to be split again.

### Step 5: Closeout (blocking gate)

When the user indicates they want to close the DISCOVERY:

1. **Check the closing gate:**

   ```
   ┌─────────────────────────────────────────────────────────┐
   │  DISCOVERY — Closing Gate                                │
   ├─────────────────────────────────────────────────────────┤
   │                                                          │
   │  Concept: [✅ complete / ❌ draft]                       │
   │                                                          │
   │  PRDs:                                                   │
   │    ✅ prd-DISC-001-01.md — Catalog        (validated)    │
   │    ✅ prd-DISC-001-02.md — Cart           (validated)    │
   │    ❌ prd-DISC-001-03.md — Payments       (created)      │
   │    ⚠️  prd-DISC-001-04.md — Seller panel   (identified)  │
   │                                                          │
   │  Result: [CAN CLOSE / CANNOT CLOSE]                      │
   └─────────────────────────────────────────────────────────┘
   ```

2. **Conditions for closing:**
   - `discovery.concept` = `"complete"` (every section of the concept has content).
   - EVERY PRD in `discovery.prds` has `status` = `"validated"`.
   - If any condition fails → report what is missing. The user can:
     - Complete what is missing.
     - Remove PRDs they decided not to do (they come off the list).
     - Force the closeout (not recommended — warn them).

3. **On passing the gate:**
   - Update `discovery.concept` to `"complete"`.
   - Commit anything not yet committed (the concept and each PRD are committed as they are
     approved; here you only close what is left).
   - Create a PR with the discovery artifacts.
   - Reset `.ddw-state.json` to IDLE (`discovery` → `null`).
   - Add an entry to `history`: transition DISCOVERY → IDLE, **stamped with `ticket` and `tier`** (see `.ddw/rules/state.instructions.md`).

### Discovery PR Format

```
## Discovery: [concept title]

### Concept
- docs/ddw/discovery/concept-{ticket}.md

### PRDs produced
- docs/ddw/prd/prd-{ticket}-01.md — [title]
- docs/ddw/prd/prd-{ticket}-02.md — [title]
- docs/ddw/prd/prd-{ticket}-03.md — [title]

### Notes
[Summary of the key decisions made during the exploration]

## Attribution
[AI-assisted | AI-full]: [description of the level of human supervision]
```

**A Discovery PR MUST carry the `AI-assisted` or `AI-full` label.** Follow the same attribution
rules as the rest of the framework (see `.ddw/rules/commits.instructions.md`).

---

## Tracking in .ddw-state.json

Full state schema and the `discovery` sub-schema: see
`.ddw/rules/state.instructions.md`.

---

## Status Line

```
📝 DISCOVERY · Exploring concept | DISC-001: Product marketplace
📝 DISCOVERY · Formalizing PRDs (2/4) | DISC-001: Product marketplace
📝 DISCOVERY · Closing | DISC-001: Product marketplace
```

- "Exploring concept" = working on the concept, brainstorming, questions.
- "Formalizing PRDs (N/M)" = writing/validating PRD N of the M identified.
- "Closing" = evaluating the closing gate.

These are not rigid phases — they reflect the current activity.

---

## Prohibitions

- **Do NOT write source code.**
- **Do NOT create specs or fix-plans.**
- **Do NOT run tests.**
- **Do NOT commit anything outside this phase's artifacts** (the concept and the PRDs).
- **Do NOT modify files outside `docs/ddw/discovery/` and `docs/ddw/prd/`.**
- **Do NOT advance to any pipeline phase** (DISCOVERY does not feed the pipeline directly; the PRDs
  stay available for future FEATURE tickets).

---

## Allowed Skills

| Skill | Use in DISCOVERY |
|-------|------------------|
| `ddw-create-prd` | Create individual PRDs |
| `ddw-validate-prd` | Validate PRDs against the rules |
| `ddw-commit` | Commit each artifact as it is approved |
| `ddw-create-pr` | Only at closeout (discovery PR) |
| `ddw-self-check` | Always available (read-only) |
| `ddw-status` | Always available (read-only) |
