---
applyTo: '**'
version: 2.6.0
---

# CLASSIFY Phase (Recognition and Classification)

**Goal:** understand the codebase, classify the user's request, and prepare the state for the
pipeline.

---

## Step 0: Enter the phase first

Write `IDLE → CLASSIFY` **before any classification work**, in the same response that answers the
user's request:

```bash
.ddw/scripts/transition.py --to CLASSIFY --action "clasificar: <the request, in a few words>"
```

Nothing here waits, in either autonomy mode: the user just spoke, and this arrow is what their
message asked for. What waits under `assisted` is the NEXT one — the ok that closes this phase pays
`CLASSIFY → DEFINE` and nothing else, which is also all the closing banner may promise. Classifying
while the state still says IDLE looks harmless and costs the user a turn: their ok then owes two
transitions, the hook (correctly) lands only one, and the second sits until an ok that decides
nothing. Measured on two consecutive manual runs, with the banner promising an arrow the
enforcement could not let it deliver.

---

## Step 1: Project stack

The stack lives in **`AGENTS.md`**, section "Stack". **That is the only place.** No derived file is
generated: duplicating the stack across two files guarantees that at some point they will say
different things.

**Protocol:**

1. **Read the "Stack" section of `AGENTS.md`.**
2. **If it is complete** → use it and skip to Step 2. There is nothing else to do.
3. **If `AGENTS.md` does not exist at all** — which is the ordinary state of a **plugin** install,
   where nothing was ever written into the repo — say so and offer to create it:

   ```
   This repo has no AGENTS.md. DDW reads the stack from there, and under a plugin install
   nothing has written one. Shall I create it with the headings the method reads —
   Stack, Commands, Conventions, Testing — filled in from what I can detect here?
   ```

   With the user's confirmation, create it with **the project's own content and nothing of DDW's**:
   no activation block, no phase references, no template boilerplate. `AGENTS.md` is the project's
   file whether or not DDW is what asked for it, and a plugin that leaves DDW content in a repo is
   the thing the plugin install exists to avoid. Then continue at point 3 below with what you wrote.

   If the user declines, **STOP** — the same stop as an empty stack. You cannot plan blind.
4. **If it is empty or still has unfilled placeholders:**
   - **If the repo has configuration files** (`package.json`, `pyproject.toml`, `go.mod`,
     `build.gradle`, `Gemfile`, etc.): scan them, detect language, framework, test runner, linter,
     ORM/DB and package manager, and **hand the user the finished text to paste into `AGENTS.md`**:

     ```
     Your AGENTS.md does not declare the stack. Here is what I detected in the repo:

     | Field | Value |
     |-------|-------|
     | Language | [detected] |
     | ...      | ...       |

     Shall I add this to the "Stack" section of your AGENTS.md?
     ```

     With the user's confirmation, write it **into `AGENTS.md`** and continue.
   - **If the repo has NO configuration files** (a new project, no code yet): **STOP**. There is
     nothing to detect, and you cannot plan or implement blind.

     ```
     I need the stack to work, and your AGENTS.md does not have it yet.
     Fill in the "Stack" section of AGENTS.md and we start over.
     ```

**Hard rule:** the stack is **written once, in `AGENTS.md`**, and the user always confirms it. DDW
can detect it and propose it — never assume it, never store it somewhere else.

### Step 1.1: Does the stack cover what this repo actually does?

A declared stack can be complete and still leave DDW running the wrong commands: the repo has a
linter DDW was never told about, or a CI job that runs something no gate will.

Invoke `Skill(skill="ddw-context-check")`. Once per ticket, here, because this is the last moment
before the pipeline starts spending time on the wrong commands.

**It does not block.** It reports what the repo declares and the context file does not, with the
evidence and the line to add. The user accepts, declines, or ignores it, and the answer is recorded
so it is not asked again for this ticket. If there is nothing to report it says one line and gets out
of the way. Do not turn its findings into gates, and do not treat a decline as a reason to stop:
whether a project should run a linter is not DDW's call.

---

## Step 2: Tier Classification

Analyze the user's request:

### QUERY (Stateless)
The user asks something informational, without requesting code changes.
- Examples: "how does X work?", "where is the file that does Y?", "explain this function to me"
- **Action:** answer directly. Do not touch `.ddw-state.json`. Do not change phase. Done.

> **Anything that is not about the repo's code is not classified at all.** Drafting an email,
> putting a deck together, summarizing a sprint: do it and move on, with no tier, no state and no
> tool restrictions. DDW governs what happens to the code, not everything you are asked for.

### QUICK-FIX (cross-cutting modifier)

**Evaluate FIRST, before FIX/FEATURE.** A mechanical heuristic over the expected diff
(estimated from the user's description and the likely paths):

1. ≤ 10 LOC modified.
2. 1 code file, or several only if they are docs/comments.
3. Does NOT touch: schemas, migrations, HTTP endpoints, authentication, authorization, input
   validation, or paths marked as security-sensitive in `AGENTS.md` ("Stack" section).
4. Does NOT add new files.
5. Does NOT introduce dependencies.

If **ALL** hold → `tier="QUICK-FIX"`. If **any** fails → continue with the normal classification
(FIX / FEATURE).

- Valid examples: fixing a typo in a log message, adjusting a comment, changing a non-sensitive
  constant's value.
- Short pipeline: `CLASSIFY → DEFINE → CODE → CLOSEOUT` (skips PLAN and VERIFY). Only artifact: a
  4-line fix-brief. Only security validation: SAST.
- Safeguard: if during CODE something tries to write a sensitive path or the diff exceeds 10 LOC,
  the shared gate blocks and asks you to abandon the ticket and reclassify
  it as a FIX (escalating means a new ticket, a new branch and an RCA — it is not a step backwards
  inside the same flow).

### FIX
Meets ALL of these criteria:
- Fixes a bug or defect in existing behavior
- Does NOT change behavior visible to the end user
- Does NOT modify public interfaces (APIs, schemas, exported types)
- Does NOT change architecture
- Examples: a typo in logic, a query correction, a config adjustment, fixing broken validation,
  a live production bug

A FIX always gets a **root cause analysis** in DEFINE (`docs/ddw/specs/rca-{ticket}.md`) and a
**rollback plan** in its fix-plan. That is what separates it from QUICK-FIX: a QUICK-FIX is too
small to have a root cause worth writing down or a revert worth planning.

### FEATURE
Meets ANY of these criteria:
- Adds new user-visible functionality
- Modifies a public API or a data schema
- Changes navigation flows or UX
- Introduces a new architectural dependency
- Requires a data migration
- Examples: a new endpoint, a new page, a module refactor, integrating an external service

### DISCOVERY
Meets ANY of these criteria:
- The user wants to explore an idea without implementing code yet
- The PM or user wants functionality defined at a high level
- PRDs need to be created for a new project or product
- The request is vague/broad and needs refining before it becomes executable tickets
- The goal is to plan how to split a large project into implementable features
- Examples: "I want to build a marketplace", "I need to define the features of a CRM", "I have this
  idea and want to turn it into PRDs", "the PM wants the requirements for X documented"

**Difference from FEATURE:** FEATURE will implement code. DISCOVERY only produces documentation
(concept + PRDs). DISCOVERY's PRDs can later be executed as individual FEATURE tickets.

### FREE

**Only when the user asks for it, in as many words.** Never propose it, never route to it because
the request is small, and never offer it as a way out of a refusal you just gave.

- The user says they want to work without the pipeline: "sin ticket", "no me armes workflow",
  "quiero probar algo", "es una prueba".
- What it means: no gates, no artifacts, no validations. Code can be written from the first turn.
- What it does NOT mean: DDW's own files stay sealed, the journal stays append-only, and the state
  is still the state.
- What it costs: nothing about that work is recorded except that it happened without a pipeline —
  no PRD, no spec, no threat model, no test report, no verdict.

Entering is a transition like any other (`CLASSIFY→FREE`), so the history says when it started and
why. Leaving is `FREE→IDLE`. A ticket already in flight cannot become FREE: there is no edge into
it from any working phase, and the tier cannot change outside CLASSIFY — otherwise FREE would be a
way to walk out of the gates a ticket has already been asked for.

### When in doubt
Ask the user: "Does this change what the user sees or how they interact with the system? Is it
urgent because of production impact? Does it change the architecture? Or are you exploring an idea
and want to define it before implementing?"

---

## Step 2.1: Stop for stateless classifications

If the classification is **QUERY**:
- Answer per the rule defined above.
- **Do NOT continue to Steps 3 through 6.** Those steps only apply to the stateful tiers
  (QUICK-FIX, FIX, FEATURE, DISCOVERY, FREE).
- Do not touch `.ddw-state.json`. Do not change phase. Done.

---

## Step 3: Ticket

### First: is this continuing a split PRD?

Before asking anything, list `docs/ddw/prd/`. A file named `prd-{TICKET}{letter}.md` whose ticket has
no closeout in `history` is work that was already defined and never run — and if the user just said
something like *"continue with the PRD"* or *"the next one"*, that is almost certainly what they
mean.

When there is one, **propose it instead of running the intake from scratch**:

```
This looks like FEAT-001b — "[title from its PRD]", the next sub-ticket of FEAT-001.
Its PRD is already written. Continue with it?
```

On confirmation: `ticket` = the sub-ticket ID, `title` from its PRD, `tracker` inherited from the
parent, and **the tier is the parent's** — a split does not reclassify the work, it divides it.
Then carry on with step 4.

Two things not to do. Do not invent a fresh `FEAT-NNN` for work that already has a PRD: you end up
with two tickets for one deliverable and the parent index pointing at neither. And do not skip
DEFINE — the PRD gets re-validated there, always, for the reasons that phase gives.

If the user is clearly asking for something else, say what is pending in one line and get on with
what they asked. This is a proposal, not a redirection.

### Then, for new work

If the tier is stateful (QUICK-FIX, FIX, FEATURE, DISCOVERY or FREE):

1. Ask: "Is there an associated tracker ticket? If so, which one?"
2. **If the user provides a tracker ticket** (e.g. `PROJ-123`):
   - `ticket` = the tracker ID (e.g. `"PROJ-123"`)
   - `title` = the tracker ticket's title
   - `tracker` = the tracker ID (same value as `ticket`)
   - Every artifact, path and status line will use this ID.
3. **If there is no tracker ticket:**
   - Ask: "Do you want me to propose a tracker ticket for this?"
     - If yes → propose one per `.ddw/rules/tracker.instructions.md`. If it gets created, apply
       rule 2.
     - If no → generate a sequential internal ID (`FIX-NNN`, `FEAT-NNN` or `DISC-NNN`).
       `tracker` = `null`.

---

## Step 4: Presenting to the User

```
┌─────────────────────────────────────────────────────────┐
│  CLASSIFY — Classification                               │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Classification: [TIER]                                  │
│  Reason: [one line explaining why]                       │
│  Mode: [full pipeline / short lane / free ideation]      │
│  Ticket: [PROJ-XXX with a tracker / FIX-NNN without]     │
│  Source: [tracker / internal]                            │
│  Title: [tracker ticket title, or generated]             │
│  Stack: [reference to AGENTS.md ("Stack" section)]       │
│                                                          │
│  Do you confirm this classification?                     │
└─────────────────────────────────────────────────────────┘
```

Wait for explicit confirmation **of this specific classification**. Generic phrases like "go ahead",
"next one", "continue" said in the context of ANOTHER ticket do NOT constitute approval of this
classification. The user has to answer THIS table.
> **Under `autonomy: "minimal"` this arrow does not wait.** The mode was chosen
> in this very phase, one question earlier, so the answer that set it is the
> last one owed here: the table is still SHOWN and the classification still
> lands in the history, what goes away is the pause. Its four sibling phases
> already said this and this one did not — the only exit of the six that read
> as waiting in every mode. Three things stop the run anyway, in either mode: a
> decision nobody wrote down, a corrective loop at its ceiling, and a corrupt
> state. See `.ddw/orchestrator.md` § Autonomy.

If the user objects:
1. Briefly explain your reasoning.
2. If they insist → accept the reclassification.

---

## Step 5: Create the Working Branch

Only after the user confirms, **BEFORE updating the state:**

1. Create the branch per `.ddw/rules/branches.instructions.md` — including its
   two out-loud questions BEFORE the branch exists: a current branch that is
   not the base gets asked about, and local-only commits on the base
   (`git rev-list --count origin/{base}..{base}` ≠ 0) stop the creation until
   the user pushes them or owns carrying them into the ticket's PR.
   - FEATURE → `feat/<ticket>-<short-name>`
   - FIX and QUICK-FIX → `fix/<ticket>-<short-name>`
   - DISCOVERY → `discovery/<ticket>-<short-name>`
2. Confirm to the user: "Branch created: `[name]` from `[base]`"

**Reason:** starting in DEFINE, artifacts are written to disk (PRDs, RCAs). Everything must live on
the ticket's branch, never on `main`.

---

## Step 5b: How much of this runs without being asked

Along with the tier, the classification records **`autonomy`**, and the CLASSIFY box shows it so the
user sees what they are agreeing to before anything is written.

**Showing the value is not telling them there is a choice.** A line reading `autonomy: assisted`
means nothing to somebody who does not already know the other mode exists — and one run that did
exactly that was following this section to the letter. So when the box goes up, offer both, the
way § *Asking* in the orchestrator says: the default, the alternative, and one sentence on what the
alternative costs. Once, here, before they agree. **Never infer `minimal` from impatience**, and
never let it be chosen by someone who was not told what it removes.

- **`assisted`** — the default, and what DDW has always done: every arrow waits for the user. Use
  this unless the user asked otherwise, in those words or plainly equivalent ones ("no me preguntes
  en cada paso", "corré solo", "minimal intervention"). **Never infer it from impatience.**
- **`minimal`** — the arrows stop waiting. Nothing else changes: the same eight gates, the same
  receipts, refused by the same hook over the same bytes. What goes away is the confirmation on a
  transition whose evidence is already on disk.

**Say what it costs, once, here, before they agree:** in `minimal` nobody reads the tables. The
receipts still refuse an incomplete PRD, an unvalidated spec, a SAST report that never judged SSRF
or a test run whose numbers do not add up — but *complete* is not *true*, and the person who would
have noticed the difference is the one who just stepped out of the loop.

Three things still stop the run, in either mode, and they are not configurable: a decision nobody
wrote down (asking is the only correct move — inventing a requirement to clear a check is a worse
defect than the one it silences), a corrective loop that hit its ceiling, and a corrupt state.

Every transition taken without a human carries `"autonomy": "minimal"` in its history entry, because
six months later the record has to distinguish a run somebody watched from one that did not have
anyone to watch it.

---

## Step 6: Transition

1. Update `.ddw-state.json`:
   - `tier` → the confirmed tier (`"QUICK-FIX"`, `"FIX"`, `"FEATURE"`, `"DISCOVERY"` or
     `"FREE"`)
   - `autonomy` → `"assisted"` unless the user asked for the other one (see below)
   - `phase`:
     - For `QUICK-FIX`, `FIX`, `FEATURE` → `"DEFINE"`
     - For `DISCOVERY` → `"DISCOVERY"`
     - For `FREE` → `"FREE"`
   - `ticket` → the tracker ID if there is one (e.g. `"PROJ-123"`), or a sequential internal ID
     (e.g. `"FIX-001"`, `"DISC-001"`)
   - `title` → the tracker ticket's title if there is one, or the generated title
   - `tracker` → the tracker ID, or `null` when the ID is internal
   - Append a `history` entry for the transition CLASSIFY → DEFINE (or → DISCOVERY, or → FREE), **stamped
     with `ticket` and `tier`** (see `.ddw/rules/state.instructions.md`). This is the first entry
     that can carry a ticket — the one before it left IDLE, where there was none yet.

2. **Build that write with the helper**, do not hand-assemble it:

   ```bash
   .ddw/scripts/transition.py --to DEFINE --tier <TIER> --ticket <ID> --action "<why this tier>"
   ```

   It prints the complete next state and self-validates against the graph first, so an illegal
   transition fails here rather than being refused by the hook afterwards. Paste its output in a
   single write, filling in `title` and `tracker` in that same write — the helper takes the
   ticket as `--ticket` because an ID is not free text, and leaves those two to the write
   because free text through shell arguments is how quoting bugs get in.
