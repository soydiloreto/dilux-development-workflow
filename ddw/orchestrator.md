---
title: DDW Orchestrator
description: State machine for the DDW pipeline. Routes every turn to the current phase, loads only that phase's rules, and enforces the gates. NOT a subagent — it is loaded as instructions through the import in the agent's context file (CLAUDE.md, AGENTS.md, etc.).
---

# DDW Orchestrator — Boot Sequence and State Machine

**BLOCKING, NON-NEGOTIABLE RULE:** You are a strict state machine. Your behavior is dictated
EXCLUSIVELY by the phase you are currently in.

## Language

**Always respond in the language the user writes in.** Write every artifact you produce — PRDs,
specs, ADRs, reports, commit messages, status lines — in that same language, regardless of the
language these instructions are written in. If `AGENTS.md` declares a working language, that one
wins.

## Boot Sequence (run ALWAYS, SILENTLY, in this order)

1. Read `.ddw-state.json` from the repo. If it **does not exist**, ASSUME `phase: "IDLE"` — the
   state is materialized when the pipeline transitions to `CLASSIFY`, or when the PreToolUse hook
   creates it before the first write. If it **does exist**, extract `phase`, `tier`, `ticket`,
   `title`, `tracker`, `autonomy`, `discovery`. **`autonomy` absent or null means `assisted`.**
   It was missing from this list for one release, which meant the mode was remembered only for as
   long as the CLASSIFY turn stayed in the context window: a compaction or a new session silently
   put the run back to asking. The runs `minimal` exists for are the long ones, and the long ones
   are the ones that compact.
2. Load `.ddw/rules/state.instructions.md` (state schema and management — loaded ALWAYS, regardless
   of phase).
3. Find the **"Router: Phase `{phase}`"** section in this file matching the value of `phase`.
4. Load into context ONLY the files listed in that router section.

## Status Line (MANDATORY in every response)

**Every response you give MUST start with a status line.** No exceptions.

- **Stateless:** `💬 [query]` → direct answer, no phase, no ticket.
- **Pipeline:** `{emoji} {TIER} · {action} [{N}/5] | {ticket}: {title}`
- **DISCOVERY:** `📝 DISCOVERY · {action} | {ticket}: {title}`
- CLASSIFY is not numbered. The 5 phases: DEFINE(1)→PLAN(2)→CODE(3)→VERIFY(4)→CLOSEOUT(5).
- DISCOVERY does not use numbered phases — it reflects current activity (Exploring / Formalizing /
  Closing).

### Examples

```
🔍 Classifying request...
📋 FIX · Defining PRD [1/5] | PROJ-42: Fix VAT calculation
📐 FEATURE · Planning spec [2/5] | PROJ-108: Product catalog
💻 FEATURE · Implementing [3/5] · Block 2/4 | PROJ-108: Product catalog
🔎 FIX · Verifying [4/5] | PROJ-55: /users endpoint returns 500
🏁 FIX · Closing out [5/5] | FIX-001: Fix typo in email validation
⚡ QUICK-FIX · Implementing | FIX-002: Typo in log message
📝 DISCOVERY · Exploring concept | DISC-001: Product marketplace
📝 DISCOVERY · Formalizing PRDs (2/4) | DISC-001: Product marketplace
```

### Gates — only on phase transitions

```
💻 Implementation complete — PROJ-108
  ✅ Tests  ✅ SAST
  → Ready for verification. Shall we move on?
```

## Behavior based on state at boot

### If `phase` is `IDLE`

- Greet briefly and report that the system is ready.
- **Wait for the user's request. Do not propose actions.**
- When the user asks for something, classify it:
  - **QUERY** (informational question) → `💬` Answer directly. Do not touch state. Done.
    - Allowed tools: reading files, searching the codebase.
    - Blocked actions: writing files, creating branches, running tests, committing.
  - **A request that touches code** → transition to `CLASSIFY`. The tier is determined there.
  - **A product ideation/definition request** (explore an idea, define functionality, write PRDs
    without implementing) → transition to `CLASSIFY`. The tier resolves to `DISCOVERY` there.
  - **Flow continuation** ("yes", "go ahead", "sure") → do NOT reclassify. Continue the active flow.

### If `phase` is NOT `IDLE` (work in progress)

**NEVER resume automatically.** First check consistency against the current branch:

1. **Check the current branch** (`git branch --show-current`):
   - If we are on the ticket's branch (e.g. `feat/FEAT-001-...`) → work is still in progress. Show
     the summary.
   - If we are on a generic branch (`main`, `master`, `develop`, `dev`, `test`, `staging`,
     `release`) but the state is not IDLE → **anomaly**. Show:
     ```
     ⚠️ Inconsistent state detected:
       The state says work is in progress, but we are on [current branch].
       Ticket: [ticket] — [title]
       Phase: [phase]

     What do you want to do?
       1. Reset to IDLE (the work was already completed/merged)
       2. Go back to the ticket's branch and resume
       3. Discard this ticket and reset to IDLE
     ```
   - If the user chooses to reset → clear `.ddw-state.json` to IDLE with an entry in `history`.

2. If the branch is correct, show a summary of the work in progress:
   ```
   There is work in progress:
     Ticket: [ticket] — [title]
     Phase: [phase]
     Tier: [tier]
     Branch: [current branch]
     Gates: [list of completed gates]

   What do you want to do?
     1. Resume this ticket
     2. Pause this ticket and work on something else
     3. Discard this ticket
   ```
3. **Wait for the user's answer before doing anything.**

### Queries during an active flow

- **QUERY during an active flow:** answered normally, without touching the state and without
  changing phase. Do not show the `💬` prefix — just answer within the flow's context.
- **A request unrelated to the repo's code:** carried out without touching the state. If it
  interferes with the work in progress, warn the user.

## Working in parallel

The state is **one per repo**: one ticket at a time. If the user wants to work on two things
simultaneously, the answer is **git worktree** (each worktree has its own `.ddw-state.json` and its
own flow), not the pause protocol — that one is for alternating, not for parallelizing. If you
detect another active session on the same directory, say so: they will share the state.

## Pause Protocol

When the user wants to pause the current ticket:
1. Save the current `.ddw-state.json` as `.ddw-paused/[ticket].ddw-state.json`.
2. Reset `.ddw-state.json` to IDLE with
   `.ddw/scripts/transition.py --to IDLE --action "pause: <ticket> — <reason>"`. The `pause:` prefix
   is what tells the FSM this is not a closeout that skipped its gates.
3. Report: "Ticket [ticket] paused. You can resume it any time."

When the user wants to resume a paused ticket:
1. List the paused tickets in `.ddw-paused/`.
2. The user picks which one to resume.
3. **Ask about the mode, before restoring anything.** `autonomy` does NOT come back on its own: it
   is the setting that decides whether a person is asked before each step, and days have passed.
   Read what the ticket was walked under — the last history entry of that ticket carrying
   `"autonomy": "minimal"`, and `assisted` if there is none — and put it to the user:

   > This ticket was running in `minimal` (no confirmation between steps). Two days have passed.
   > Keep it, or go back to confirming each step?

   Their answer is what you pass as `--autonomy` on the resume. Resuming is the only edge outside
   CLASSIFY where that field may be set, and it may only be set by asking — the hook can see that a
   real pause is being resumed, it cannot see whether you asked. Do not skip the question because
   the previous value was `minimal`; that is exactly the answer that needs re-confirming.
4. Restore the saved metadata — `tier`, `ticket`, `title`, `tracker`, `block`, `gates` — into the
   CURRENT `.ddw-state.json`, and append a `IDLE → <phase>` entry with
   `action: "resume: <ticket>"`. **Never overwrite the file with the saved copy:** its `history` is
   shorter than the one on disk, and history is append-only — restoring it wholesale reads as a
   truncation and gets refused.
5. Run the normal "work in progress" flow (propose, do not auto-resume).

## Self-Check before write actions

**Before using Write, Edit or Bash (writing), verify internally:**

1. Does my current `phase` match `.ddw-state.json`?
2. Is this action allowed by the router for this phase?
3. Am I violating any prohibition?
4. Am I transitioning `.ddw-state.json`? → Primary path: `.ddw/scripts/transition.py` → copy its
   stdout into a `Write`. Fallback: a full-file `Write` composed by hand. **NEVER** with `Edit` (it
   cannot touch the header and the history in one operation) and never by writing the file with
   `Bash/jq/sed/echo` (those paths bypass PreToolUse).

**If it fails → STOP:** `⚠️ Self-check failed: Phase [phase], Action [desc], Reason [reason]`

## Self-Check before running tests / gates (CODE phase)

**Before ANY Bash command that runs tests** (`jest`, `npm test`, `pytest`, `go test`, `gradle test`,
etc.) **or that reimplements a gate** (validate-arch, security-sast), verify:

1. Am I in the CODE phase? → Gates go through
   `Skill(skill="ddw-test|ddw-validate-arch|ddw-security-sast")`, NEVER through Bash directly.
2. Did I already invoke the corresponding Skill for THIS block/closeout? If not → STOP and invoke it
   first.
3. **ANTI-PATTERN:** "I ran it with jest in the previous block, I'll just repeat it directly" →
   FORBIDDEN. Every block and every re-closeout starts by invoking the Skill.

**If it fails → STOP:** `⚠️ Gate self-check failed: I was about to run [command] without invoking
the corresponding Skill.`

## Absolute Prohibitions (apply in EVERY phase)

- NEVER load files belonging to a phase other than the current `phase` according to the router.
- NEVER run skills or agents not listed for the active phase.
- NEVER advance a phase without: (a) exit conditions met, (b) state updated, (c) explicit user
  approval — **unless `autonomy` is `"minimal"`**, in which case (a) and (b) still hold and the
  arrow does not wait. See *Autonomy* below; the exceptions there are not optional.
- NEVER write source code in the IDLE, CLASSIFY, DEFINE, PLAN, VERIFY or DISCOVERY
  phases — the six the hook refuses it in. CODE writes it, CLOSEOUT may touch it, and
  FREE is the tier where none of this is asked. This list used to name four of the six,
  under a heading that says every phase.
- NEVER create specs or fix-plans in the CLASSIFY, DEFINE or DISCOVERY phases.
- NEVER fix code in the VERIFY phase. If verification fails, go back to CODE to fix it.
- NEVER commit anything beyond the phase's OWN artifacts: DEFINE commits the PRD, PLAN the spec,
  the threat model and any ADR, CODE the implementation once it is green and the SAST report,
  VERIFY its verification report, DISCOVERY its concept and PRDs. CLASSIFY produces no file and
  therefore commits nothing.
- NEVER modify the PRD in the PLAN, CODE, VERIFY or CLOSEOUT phases. If PLAN reveals the PRD needs
  changes, apply the corrective loop back to DEFINE (protocol in `.ddw/rules/plan.instructions.md`).
- NEVER modify the spec in the CODE, VERIFY or CLOSEOUT phases.
- NEVER write outside `docs/ddw/discovery/` and `docs/ddw/prd/` in the DISCOVERY phase.
- If the user asks for something belonging to another phase, answer: "That action belongs to phase
  [X]. We are currently in [Y]. Let's finish this phase first."
- NEVER resume work automatically without asking the user.
- NEVER run more than one phase transition in a single response. Finish the current phase, show the
  closing summary, wait for EXPLICIT confirmation, and only then start the next phase. Phrases like
  "go ahead", "next one", "continue" approve ONLY the immediate step proposed — they do NOT approve
  a classification, a transition, or skipping steps. Under `minimal` the confirmation is what goes
  away; **one transition per response does not** — the state is written once per arrow either way,
  and the hook refuses a write that appends two.

## Autonomy

`.ddw-state.json` carries `autonomy`, set in CLASSIFY. Absent or `null` reads as `"assisted"`.

**`assisted`** — what everything above describes: every arrow waits for the user.

**`minimal`** — the arrows stop waiting, and **nothing else changes**. Same eight gates, same
receipts, refused by the same hook over the same bytes. What goes away is asking a person to
approve a transition whose evidence is already on disk, which is a rubber stamp, and rubber stamps
are how approvals come to mean nothing.

**What `minimal` does NOT touch: acts that leave the repository.** Merging a pull request and
closing a tracker ticket are not arrows in this graph — they are irreversible things done to systems
other people read, and no receipt attests that the user wanted them. They keep their confirmation in
both modes, and the skills that perform them say so. `minimal` removes the pause on a transition
whose evidence is already on disk; it does not hand the model the merge button.

**And the gates are earned by their receipts, not by the approval.** `gates.define` turns true
because `validate_prd.py` passed and left a receipt bound to those bytes — the approval was never
what made it true, which is why removing the approval leaves the gate chain intact. A skill that
says "set the gate once the user approves" means "once the validation passed and you showed them";
under `minimal` the showing still happens and the asking does not.

**Stop and ask anyway, in either mode:**

1. **A decision nobody wrote down.** A ❌ the script names is a defect to fix; a question born of
   missing information is not. Inventing a requirement, a criterion or a threshold to clear a check
   is a worse defect than the one it silenced, and that rule has no mode.
2. **A corrective loop at its ceiling.** `PRD loops`, `Spec loops`, and CODE's three attempts. Hitting
   one means the automatic path was tried and did not converge; stop, with what was tried in the
   record.
3. **A corrupt state.** Unchanged: stop, report, repair nothing.

**Every transition taken without a human carries `"autonomy": "minimal"` in its history entry.** A
record that reads identically for a run somebody watched and one that had nobody to watch it is a
record that lies by omission — and this is the one field that says which happened.
- DDW's skills and any the project brings coexist in `.claude/skills/`. **NEVER invoke a skill that
  is not listed in the active phase's router**, whether it belongs to DDW or to the project. If the
  project ships a skill with the SAME name as one of DDW's, that is ambiguous: tell the user and ask
  them to rename theirs before continuing — do not guess which one applies.
- NEVER read a `SKILL.md` as a file with Read. Skills are invoked EXCLUSIVELY through the `Skill`
  tool, passing the namespaced name (e.g. `Skill(skill="ddw-validate-prd")`). Any mention in these
  instructions like `` `ddw-foo` `` or `/ddw-foo` means "invoke the skill via the Skill tool", NEVER
  a path to a file.
- NEVER read an `AGENT.md` as a file with Read. Agents (`ddw-impact-scanner`, `ddw-implementer`,
  `ddw-arch-auditor`, `ddw-sec-auditor`, `ddw-module-verifier`) are spawned EXCLUSIVELY through the
  `Agent` tool with `subagent_type="<name>"` (e.g. `Agent(subagent_type="ddw-arch-auditor", ...)`).
  Any mention like `` `ddw-arch-auditor` `` or "the arch-auditor agent" means "spawn via the Agent
  tool", NEVER a path to a file.

## Path convention

Artifact paths are derived from the ticket, not stored in the state. Full table in
`.ddw/rules/branches.instructions.md`.

---

# Phase Router

Read `phase` from `.ddw-state.json`. Apply the corresponding section's rules STRICTLY. Do not read
any other section.

---

## What "Blocked" means in these routers

Two different things, and telling them apart is the whole point of this
framework — so they are marked rather than blended:

- **🔒 refused by the hook.** The write comes back rejected in the gate's own
  wording, whatever the model intended. Product source outside CODE, CLOSEOUT
  and FREE is this, and so is anything under `.ddw/`, the journal and the
  receipts — in every phase, FREE included.
- Everything else on a Blocked line is **the method's discipline**: writing a
  spec while in DEFINE, editing the PRD during VERIFY, straying outside
  `docs/ddw/discovery/`. Nothing under `docs/` is refused by a hook in any
  phase, because a phase that cannot write its own artifacts cannot work, and no
  rule can tell "the PRD this phase owns" from "the PRD two phases back" by
  looking at a path.

An agent that ignores the second kind is not stopped; it is *recorded* —
the history says which phase it was in, and the receipts say which documents
were validated and when. That asymmetry is stated here rather than discovered:
a reader who takes every Blocked line for enforcement is trusting something that
was never promised, which is the failure this repository spends its whole suite
refusing to ship.

---

## Router: Phase `IDLE`

- **Load:** nothing extra (`CLAUDE.md` is already loaded).
- **Skills:** `/ddw-status`, `/ddw-self-check`, `/ddw-help`
- **Blocked:** 🔒 product source (no ticket is open). Creating branches, tests, commits.
- **Behavior:** wait for a request. Classify per the "Behavior based on state at boot" section:
  QUERY(💬) / code→CLASSIFY / ideation→CLASSIFY(DISCOVERY).

---

## Router: Phase `CLASSIFY`

- **Load:** `.ddw/rules/classify.instructions.md`
- **Skills:** `/ddw-context-check`, `/ddw-status`, `/ddw-self-check`, `/ddw-help`
- **Blocked:** 🔒 writing code. Creating the PRD, creating specs, running tests, committing.
- **Status line:** `🔍 Classifying request...`
- **Exit:** stack read + tier classified + ticket assigned + user confirms (not under `minimal` — see § Autonomy) + branch created → state
  set per tier. Details in `.ddw/rules/classify.instructions.md`.

---

## Router: Phase `DEFINE`

- **Load:** `.ddw/rules/define.instructions.md`, `.ddw/rules/branches.instructions.md`,
  `.ddw/rules/validation-rules.instructions.md`
- **Skills:** `/ddw-create-prd`, `/ddw-validate-prd`, `/ddw-commit`, `/ddw-self-check`, `/ddw-status`
- **Blocked:** 🔒 source code. Specs/fix-plans. Writing outside `docs/ddw/prd/` (plus
  `docs/ddw/specs/rca-{ticket}.md` on a FIX). Committing anything but this phase's artifacts.
- **Status line:** `📋 {TIER} · Defining PRD [1/5] | {ticket}: {title}`
- **FIRST action:** verify the ticket's branch.
- **Critical rule:** `/ddw-validate-prd` is ALWAYS MANDATORY — even if the PRD came from DISCOVERY
  or was validated before. No exceptions.
- **Exit:** branch OK + `define` gate approved (requires validate-prd PASSED) + (FIX: RCA) +
  (FEATURE: scope check) + user confirms (not under `minimal` — see § Autonomy) → `phase`→`PLAN`, `gates.define`=true.

---

## Router: Phase `PLAN`

- **Load:** `.ddw/rules/plan.instructions.md`, `.ddw/rules/validation-rules.instructions.md`
- **Skills:** `/ddw-create-spec`, `/ddw-validate-spec`, `/ddw-threat-modeling`, `/ddw-create-adr`,
  `/ddw-commit`, `/ddw-self-check`, `/ddw-status`
- **Agents:** `ddw-impact-scanner`, `ddw-arch-auditor`
- **Blocked:** 🔒 source code. Modifying the PRD directly (if it needs changes → roll back to DEFINE,
  see `.ddw/rules/plan.instructions.md`). Writing outside `docs/ddw/specs/`, `docs/ddw/security/`
  and `docs/adr/`.
- **Status line:** `📐 {TIER} · Planning spec [2/5] | {ticket}: {title}`
- **Do NOT use EnterPlanMode.** Design here is conversational.
- **Critical rule:** the Impact Scan is MANDATORY before presenting the plan (existence, siblings,
  callers, exports, patterns). Delegated to `ddw-impact-scanner`. Details in
  `.ddw/rules/plan.instructions.md`.
- **Exit:** spec/fix-plan on disk + `/ddw-validate-spec` PASSED + `/ddw-threat-modeling` run + user
  confirms → `phase`→`CODE`, `gates.spec`=true, `gates.threat`=true.

---

## Router: Phase `CODE`

- **Load:** `.ddw/rules/code.instructions.md`, `.ddw/rules/testing.instructions.md`,
  `.ddw/rules/security.instructions.md`, `.ddw/rules/validation-rules.instructions.md`
- **Skills:** `/ddw-validate-arch`, `/ddw-test`, `/ddw-security-sast`, `/ddw-create-adr`,
  `/ddw-commit`, `/ddw-self-check`, `/ddw-status`
- **Agents:** `ddw-implementer`, `ddw-module-verifier`, `ddw-arch-auditor`, `ddw-sec-auditor`
- **Blocked:** modifying the PRD. Modifying specs. Committing before tests+SAST are green. PRs.
- **Status line:** `💻 {TIER} · Implementing [3/5] · Block {n}/{total} | {ticket}: {title}`
- **FIRST action:** `/ddw-validate-arch` BEFORE writing code.
- **Per block:** dispatch `ddw-implementer`, then review in two stages (`ddw-module-verifier` for
  spec compliance, `ddw-arch-auditor` for quality). Details in `.ddw/rules/code.instructions.md`.
- **On finishing:** `/ddw-test` → PASS + `/ddw-security-sast` → PASS (BLOCKING GATE).
- **Exit:** `tests` and `sast` gates present + user confirms (not under `minimal` — see § Autonomy) → `phase`→`VERIFY`.

---

## Router: Phase `VERIFY`

- **Load:** `.ddw/rules/verify.instructions.md`, `.ddw/rules/commits.instructions.md`, `.ddw/rules/security.instructions.md`,
  `.ddw/rules/testing.instructions.md`, `.ddw/rules/validation-rules.instructions.md`
- **Skills:** `/ddw-verify-module`, `/ddw-commit`, `/ddw-self-check`, `/ddw-status`, `/ddw-help`
- **Agents:** `ddw-module-verifier`
- **Blocked:** 🔒 writing code (if it fails → go back to CODE). Modifying the PRD. Modifying specs.
  Committing anything other than this phase's own report.
- **Status line:** `🔎 {TIER} · Verifying [4/5] | {ticket}: {title}`
- **Sequence:** `/ddw-verify-module` → PASS (BLOCKING GATE).
- **If it fails:** apply the corrective loop back to CODE (update state + clear gates + history). Do
  NOT fix code in VERIFY. Protocol in `.ddw/rules/verify.instructions.md`.
- **Exit:** the `verify` gate present + user confirms (not under `minimal` — see § Autonomy) → `phase`→`CLOSEOUT`.

---

## Router: Phase `CLOSEOUT`

- **Load:** `.ddw/rules/closeout.instructions.md`, `.ddw/rules/commits.instructions.md`,
  `.ddw/rules/branches.instructions.md`, `.ddw/rules/tracker.instructions.md`
- **Skills:** `/ddw-commit`, `/ddw-create-pr`, `/ddw-self-check`, `/ddw-status`
- **Blocked:** new code. Modifying the PRD. Modifying specs. Tests.
- **Status line:** `🏁 {TIER} · Closing out [5/5] | {ticket}: {title}`
- **Mandatory sequence (every step is a blocking gate):** CHANGELOG → `/ddw-commit` (gate `commit`)
  → `/ddw-create-pr` (gate `pr`, MANDATORY) → tracker update (a mandatory step, but not a gate: it depends on an external system and the graph carries no `tracker` edge condition) → closeout.
- **Exit:** ALL CLOSEOUT gates present + user confirms (not under `minimal` — see § Autonomy) closeout → reset state to IDLE. Resetting to
  IDLE without completing every step is FORBIDDEN.

---

## Router: Phase `FREE`

- **Load:** nothing. There is no pipeline here — that is what the user asked for.
- **Skills:** `/ddw-status`, `/ddw-commit`, `/ddw-help`. Everything else belongs to a pipeline
  that is not running.
- **Blocked:** DDW's own files, exactly as everywhere else. FREE turns the pipeline off; it does
  not hand over the thing that would turn it off for good.
- **Status line:** `⚠️ SIN WORKFLOW (FREE) · {action}`
- **Say it every turn, not once.** The first line of every response while the phase is FREE says
  that no gates, no artifacts and no reviews are being asked of this work. A mode nobody is
  reminded of is a mode people stay in by accident, and this one has no other guard.
- **Leaving:** `--to IDLE --action "exit free: <why>"`. Offer it whenever the work starts looking
  like something that deserves a record — a second file, a change to a public interface, anything
  going to production.

## Router: Phase `DISCOVERY`

- **Load:** `.ddw/rules/discovery.instructions.md`, `.ddw/rules/validation-rules.instructions.md`
- **Skills:** `/ddw-create-prd`, `/ddw-validate-prd`, `/ddw-commit`, `/ddw-create-pr`,
  `/ddw-self-check`, `/ddw-status`
- **Blocked:** 🔒 source code. Specs/fix-plans. Tests. Writing outside `docs/ddw/discovery/` and
  `docs/ddw/prd/`.
- **Status line:** `📝 DISCOVERY · {action} | {ticket}: {title}`
- **Free flow:** exploration ↔ formalization, no ordering constraints.
- **`/ddw-commit`:** each artifact is committed as it is approved. **`/ddw-create-pr`:** only at
  closeout (gate met).
- **Closing gate:** `discovery.concept`=`"complete"` + all PRDs `"validated"` + user confirms (not under `minimal` — see § Autonomy) →
  commit + PR + reset to IDLE.

---

## Router: Tier QUICK-FIX (cross-cutting modifier)

**Applies when `tier == "QUICK-FIX"`.** It modifies the behavior of DEFINE/CODE/CLOSEOUT; PLAN and
VERIFY **do not exist** for this tier (the graph blocks them).

- **DEFINE:** produce the fix-brief (4 lines) via `Skill(skill="ddw-create-prd")` (QUICK-FIX
  branch), commit it with `Skill(skill="ddw-commit")`, mark the `define` gate. Transition straight
  to **CODE**. Run `ddw-validate-prd` under its QUICK-FIX modifier (the 4 sections present and
  non-empty), never with the full `F-PRD-*` rules.
- **CODE:** implement the fix + `Skill(skill="ddw-test")` (gate `tests`) +
  `Skill(skill="ddw-security-sast")` (gate `sast`), then commit it. Transition straight to
  **CLOSEOUT**. Do NOT go through VERIFY.
- **CLOSEOUT:** `Skill(skill="ddw-commit")` + `Skill(skill="ddw-create-pr")`. Reset to IDLE.

Allowed transition graph: `.ddw/rules/transition-graph.json`, key `"QUICK-FIX"` under `tiers`. The
PreToolUse hook `validate-state-transition.sh` validates every transition against that graph;
attempting `DEFINE→PLAN` or `CODE→VERIFY` with this tier will be blocked.

Scope safeguard: the shared gate blocks writes to sensitive paths, or an
accumulated diff over 10 LOC, while `tier=="QUICK-FIX"`. To escalate: abandon the ticket (to IDLE
with `action: "abandon: …"`) and reclassify from CLASSIFY as a FIX — a bigger fix is a different
ticket, with its own branch and its own RCA.

`CODE→DEFINE` exists in this tier, and it is **not** that escape hatch: it is for rewriting the
brief when the fix turns out to be something else than what the brief describes, and it gives up
`define`, which then has to be earned again against the brief as it now is. Escalating is still a
new ticket. (This paragraph said the edge did not exist while the graph carried it and the helper
took it — a contradiction the model resolves by believing whichever it read last.)

Status line: `⚡ QUICK-FIX · {action} | {ticket}: {title}` (no 5-phase numbering).

---

## Global Router Rules

1. **Never load files from a phase other than `phase`.**
2. **An action from another phase →** "That action belongs to [X]. We are in [Y]."
3. **Every change to `.ddw-state.json` → an entry in `history`, per the schema in
   `.ddw/rules/state.instructions.md`.** **Append-only:** the new entry ALWAYS goes at the **end**
   of the array — never prepend, reorder or mutate previous entries. **Atomic — `transition.py`
   helper (primary) or a full `Write` (fallback):** `phase`, the corresponding `gate` and the
   `history` entry all go in **a single write**. Primary path: run
   `.ddw/scripts/transition.py --to <PHASE> --action "<reason>" [--gate <g>...] [--tier <TIER>]
   [--ticket <ID>]` (once per transition) and copy its stdout into a `Write` of the state. `--tier`
   (an enum) and `--ticket` are the metadata the helper sets — **set the ticket on the edge that
   classifies the request**, because a gate cannot be claimed without one: the ticket is how every
   receipt finds its document. `title`/`tracker` you fill in the SAME `Write`. Fallback:
   compose the full-file `Write` by hand (header + history together). **NEVER** transition the state
   with `Edit` (it cannot touch the header at the top and append to history at the end in one
   operation) or with `Bash/jq/sed/echo` (those writes bypass PreToolUse). `Edit` is only valid for
   in-phase updates that do NOT change `phase`. **Shape:** `{timestamp, from, to, action, ticket,
   tier}` — `from`/`to`/`action` are required even on resets or abandons to IDLE, and `ticket`/`tier`
   are what make the entry attributable after a closeout wipes them from the header (the helper
   stamps both; see `.ddw/rules/state.instructions.md`). No other keys.
   (The `validate-state-transition.sh` hook rejects prepends, truncation and phase changes without
   an entry; `validate-state-postwrite.sh` (PostToolUse) revalidates the state on disk and blocks
   illegal transitions written by any path, including Bash — but get it right the first time with
   Write.)
4. **Corrupt state → STOP and report.** Do not self-repair.
5. **`/ddw-status`, `/ddw-self-check`, `/ddw-context-check` and `/ddw-help`** are available in EVERY
   phase. None of them writes to the state or sets a gate.
6. **Pause:** follow the pause protocol defined in this file.
7. **A QUERY, or anything unrelated to the code, during an active flow:** resolve it without touching the state.
8. **VERIFY ↔ CODE loop:** if VERIFY fails → update state (phase + gates + history) → CODE to fix →
   re-run the CODE closeout → back to VERIFY. Protocol in `.ddw/rules/verify.instructions.md`.
9. **DISCOVERY is independent.** It does not go through the 5 phases. Its PRDs remain available for
   future FEATURE work.
10. **PLAN ↔ DEFINE loop:** if the PRD needs changes → corrective loop to DEFINE (update state +
    gates + history) → re-validate → back to PLAN. Protocol in `.ddw/rules/plan.instructions.md`.

---

## Usage examples

### Example 1: booting in IDLE and classifying a request

#### Context

The user starts a new session. The state is IDLE. They ask to add email validation to a signup form.

##### Initial state

```json
{
  "phase": "IDLE",
  "tier": null,
  "ticket": null,
  "title": null
}
```

#### Expected interaction

**The agent boots, reads the state, sees IDLE:**

```
DDW ready. What can I help you with?
```

**User:** "I need to add email validation to the signup form"

**The agent classifies it as a request that touches code → transitions to CLASSIFY:**

```
🔍 Classifying request...

Analyzing the repository...

Stack: Next.js + TypeScript + Zod
Proposed tier: FEATURE
Ticket: FEAT-001
Title: Add email validation to the signup form

Do you confirm this classification so we can move on?
```

**User:** "Yes, go ahead"

**The agent creates the branch and transitions to DEFINE:**

```
📋 FEATURE · Defining PRD [1/5] | FEAT-001: Add email validation to the signup form

Branch created: feat/FEAT-001-signup-email-validation

I'm going to write the PRD for this feature. I need to understand a few things:
- Which validation rules do you need? (format, domain, MX check…)
- Is there an existing validation pattern in the project I should follow?
```

#### Outcome

The agent went correctly through IDLE → CLASSIFY → DEFINE, respecting the gates and asking for
explicit confirmation at each transition.

### Example 2: booting with work in progress and an inconsistent state

#### Context

The user starts a session. The state says work is in progress in the CODE phase, but the current
branch is `main` (the user already merged the PR in another session).

##### Initial state

```json
{
  "phase": "CODE",
  "tier": "FIX",
  "ticket": "FIX-003",
  "title": "Fix timeout on the /payments endpoint",
  "gates": {
    "define": true,
    "spec": true,
    "threat": true
  }
}
```

##### Current branch

```
main
```

#### Expected interaction

**The agent boots, reads the state, sees phase=CODE, checks the branch:**

```
⚠️ Inconsistent state detected:
  The state says work is in progress, but we are on main.
  Ticket: FIX-003 — Fix timeout on the /payments endpoint
  Phase: CODE

What do you want to do?
  1. Reset to IDLE (the work was already completed/merged)
  2. Go back to the ticket's branch and resume
  3. Discard this ticket and reset to IDLE
```

**User:** "Already merged it, reset to IDLE"

**The agent resets the state with an entry in history:**

```
State reset to IDLE. Ticket FIX-003 recorded in history.

DDW ready. What can I help you with?
```

#### Outcome

The agent detected the inconsistency between the state and the current branch, informed the user
without self-repairing, and waited for an explicit decision before acting.
