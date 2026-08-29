---
applyTo: '**'
version: 2.14.0
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

**The helper PRINTS the next state; it does not write it.** Copy its stdout into a `Write` of
`.ddw-state.json` — that `Write` is the transition, and it is what PreToolUse judges. Running the
command and moving on leaves the phase where it was: measured live, a model read back a state
saying `"phase": "CLASSIFY"`, announced the pipeline had advanced, and on disk the phase was still
IDLE with an empty history. The helper now says so on stderr; this line is here because the phase
rule is what gets loaded, and a warning only reaches whoever runs the command.

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

**What IS gated is that it ran.** Land what the skill found — or the line
`Nothing to report: the context file matches the repo.` — in
`.ddw-work/context-check-<ID>.md`, where `<ID>` is the ticket this classification names. The
`CLASSIFY → DEFINE` edge refuses to open without that file (DISCOVERY and FREE are exempt — neither
runs stack commands, so there is nothing for the comparison to protect): this step was skipped, silently, on two
measured general runs, and a step only prose orders is a step the least obedient model decides
about. The file does not prove the comparison was good — it makes skipping it a deliberate act
that leaves no file where the record demands one.

### Step 1.2: Is this repo part of a family?

Read the **`## Repo family`** section of `AGENTS.md`. No section → the repo is standalone: skip
this step entirely, ask nothing, change nothing. That absence IS the mono/multi switch, and it is
the user's file that flips it — never the installation.

When the section exists, **the impact analysis is classification's first duty — from ANY repo of
the family, this one included**. It is a gate, not a suggestion: CLASSIFY→DEFINE refuses without
the validated verdict's receipt. The step (`/ddw-family-impact` is the full protocol):

1. **Gather the facts by script**: `python3 .ddw/scripts/family_impact.py --ticket <TICKET>`. It
   finds the workspace and every member as sibling clones — **cloning the missing ones via
   `gh`** — fetches them all, and reads the map and every seam at `origin/<default>`: freshness
   by construction, each repo recorded at the SHA it was read. The standing repo is
   fast-forwarded only when clean and on its default branch; a diverged tree is reported, never
   merged over.
2. **Write the verdict** to `.ddw-work/impact-<TICKET>.md`: EVERY member, impacted (with what
   part hits it) or `Sin impacto: <reason>` — the reason names the contract that stays intact.
   Walk `Consumed by` of everything the work touches: a consumer of a changing seam missing from
   the impacted list is the analysis failing at its one job.
3. **Validate it**: `family_impact.py --validate .ddw-work/impact-<TICKET>.md` — every member
   accounted for, no invented repos. The PASS writes the content-hashed receipt the edge
   demands; editing the verdict afterwards kills the receipt.
4. **Classify with the verdict in hand:**
   - **Only this repo impacted** → an ordinary local ticket: classify normally, pipeline
     unchanged. Belonging to a family is not a toll on local work.
   - **Several repos impacted, and this repo is NOT the workspace** → the initiative's parent is
     a committed document and it lives in the workspace — this session cannot write it (nothing
     writes outside its own repo, ever). Name the move and stop: `cd <workspace clone>` and open
     the initiative there — the verdict travels with you (paste it; the workspace re-earns its
     own receipt).
   - **This repo IS the workspace** → classify the initiative as a FEATURE whose DEFINE writes
     the **multirepo index** (`define.instructions.md` § Multirepo split): one row per impacted
     repo, the order from the dependency chain, the children run in their own repositories —
     and the index must agree with the verdict: same impacted set, the excluded members carried
     with their reasons.

A child ticket opened FROM a parent initiative (the request names it, or the PRD parent's row does)
reads the parent index from the workspace clone or the forge — **read-only** — and, when its row
depends on another repo, asks the forge whether that repo's child PR merged before entering CODE.
Building on a dependency that is not on main yet is a fact to put in front of the user, not a
detail to discover in integration.

**The walk continues from the session you are in.** When a child's closeout ends (its PR open or
merged), offer the initiative's next step instead of parking the user at a table: run
`python3 .ddw/scripts/family_next.py --ticket <TICKET>` and put its one verdict on screen — the
stale row to correct, the next repo to walk to, the blockers by name, or all-done. With the
user's ok, MOVE to the next child's sibling clone and open its run THERE: each repository's own
state, hooks and gates rule in its own directory, and the session carries nothing across but the
initiative's id. The pilgrimage was the design's cost, not its point — the conductor is how one
session walks the whole family without ever writing outside the repo it stands in.

### Step 1.3: What does the organization already know?

Before classifying a request that **crosses family seams or names an initiative** (and only then —
a typo fix consults nothing), gather what the organization already knows about it: what each repo
does, what was decided before, what is open. Two channels, in order, degrading gracefully:

1. **The declared memory.** If `AGENTS.md` carries an `## Organizational memory` section naming an
   MCP server (any second brain — the section names the tool, the method never does), query it:
   prior decisions on these seams, the repos involved, open initiatives.
2. **The committed record, with no memory declared or the memory unreachable.** The family
   catalog, the workspace's initiative indexes, the sibling repos' `decisions-*.md` and ADRs.
   Slower than semantic search, same truth — the truth always lived in git; a memory service is
   the accelerator, never the source.

**Whatever the channel: cite the source of every finding** ("the back decided idempotent-by-key —
`decisions-TIENDA-88.md`" / "note *Webhook idempotente*, workspace tienda-demo"). A finding with
no source is not memory, it is a hunch, and it is not used. Surface what was found in the
classification box; found nothing → say "no relevant prior record" and classify anyway. **Never a
gate**: an absent section, an unreachable server or an empty answer change nothing about the
pipeline — this step informs the classification, it does not permit it.

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
why — and it carries **the user's own words**:

```bash
.ddw/scripts/transition.py --to FREE --tier FREE --action 'free: "<the sentence in which they asked for it>"'
```

The gate refuses the arrow without them. That is not bookkeeping: this tier buys the absence of
every guarantee DDW makes, so the one thing that must survive it is the record of who asked. It
cannot tell a faithful quote from an invented one — nothing can — but it turns proposing FREE into
a sentence you had to write down and attribute. Measured live: a model read this very section and
then offered FREE, with "(Recomendado)" beside it, as the way to get past a refusal it had just
been given. Leaving is `FREE→IDLE`. A ticket already in flight cannot become FREE: there is no edge into
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

**Before the box, look up its dependencies — the answer is already on file.** The sub-PRD names
the siblings it depends on, and the parent index's status column carries what CLOSEOUT recorded
for each one that closed ("done — PR #N pending review", "merged"). Read that, verify it against
git and the forge (`gh pr view`), and put the result in the box's `Depends on` line. This check
used to live only at branch creation (`branches.instructions.md` § Sub-tickets with dependencies),
three steps after the user had already confirmed — measured live: the classification box proposed
starting a sub-ticket whose dependency sat in an unmerged PR, the user had to interrupt to ask,
and the answer had been written in the index by the previous closeout all along. Where a
dependency is not merged, the box is where the user decides to wait or to branch from the
dependency's branch — not a surprise at step 5.

Two things not to do. Do not invent a fresh `FEAT-NNN` for work that already has a PRD: you end up
with two tickets for one deliverable and the parent index pointing at neither. And do not skip
DEFINE — the PRD gets re-validated there, always, for the reasons that phase gives.

If the user is clearly asking for something else, say what is pending in one line and get on with
what they asked. This is a proposal, not a redirection.

### Then, for new work

If the tier is stateful (QUICK-FIX, FIX, FEATURE, DISCOVERY or FREE), the ticket is resolved in
ONE stop — inside the Step 4 box — never in a chain of questions before it. Measured on a live
run: "is there a ticket?", then "do you want me to propose one?", then "shall we use FEAT-001?"
were three separate interruptions before the box asked a fourth, and every answer after the first
was derivable from it.

1. Generate the next sequential internal ID (`FIX-NNN`, `FEAT-NNN` or `DISC-NNN`) and a title
   yourself, and put them in the Step 4 box as the proposal.
2. The box carries the alternative in the same stop: **if the user answers with a tracker ID**
   (e.g. `PROJ-123`), then `ticket` = that ID, `title` = the tracker ticket's title, `tracker` =
   the same value, and every artifact, path and status line uses it.
3. If they confirm the proposal as it stands → `tracker` = `null` and the internal ID is the
   ticket. A ticket text they can file in their own tracker is
   `.ddw/rules/tracker.instructions.md`'s format — hand it over at CLOSEOUT's tracker update or
   whenever they ask; it is never a second question here.

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
│  Depends on: [sub-tickets only — each dependency and its │
│    verified state, e.g. "FEAT-001a — merged"; omit the   │
│    line when there are none]                             │
│                                                          │
│  Do you confirm this classification? If this work has a  │
│  ticket in your tracker, answer with its ID and I will   │
│  use that instead of [internal ID].                      │
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
   .ddw/scripts/transition.py --to DEFINE --tier <TIER> --ticket <ID> \
       --title "<the ticket's name, one line>" --action "<why this tier>"
   ```

   It prints the complete next state and self-validates against the graph first, so an illegal
   transition fails here rather than being refused by the hook afterwards. Paste its output in a
   single write.

   `--title` is not optional here and the FSM refuses this edge without it: the name is decided
   in CLASSIFY and nowhere else, and a state that names no work makes every status line, report
   header and PR title afterwards a reconstruction from context. It used to be left to the write
   — "fill in `title` and `tracker` in that same write" — from a time when the write was
   hand-assembled; once the helper became the way the state lands, that instruction had nowhere
   to land, and a FEATURE reached DEFINE with `"title": null`. `--tracker` joins it for the same
   reason, and stays optional because plenty of tickets have no tracker.

   For FREE, and only for FREE, the action carries the user's own words:

   ```bash
   .ddw/scripts/transition.py --to FREE --tier FREE --ticket <ID> \
       --title "<the ticket's name, one line>" --action 'free: "<what the user actually said>"'
   ```

   You do not get to paraphrase that into existence. FREE is the tier the user has to ask for,
   and quoting them is what the edge costs.
