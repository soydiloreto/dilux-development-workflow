---
applyTo: '**'
version: 1.4.0
---

# Phase 5: RELEASE (Commit, PR and Closeout)

**Goal:** close out what the earlier phases already committed — the CHANGELOG, the PR, the tracker
and the ticket itself.

> Each phase commits its own artifacts as it closes them (the PRD in DEFINE, the spec and the threat
> model in PLAN, code and tests in CODE). By the time you get here, the branch already holds the
> whole trail; RELEASE commits what is left.

Read `.ddw-state.json.tier` to determine your behavior.

---

## Mandatory Sequence — RELEASE Gates

**EVERY step is blocking. Resetting to IDLE without completing ALL the gates is FORBIDDEN.**

| # | Step | Gate | Mandatory |
|---|------|------|-----------|
| 1 | CHANGELOG | — | Yes |
| 2 | `ddw-commit` | `commit` | Yes |
| 3 | `ddw-create-pr` | `pr` | Yes |
| 4 | Integration — where does this branch land? | — | Yes. A mandatory step, not a gate: whether anyone merges depends on people and pipelines outside this repo |
| 5 | Tracker update | — | If there is a tracker ticket. A mandatory step, not a gate: it depends on a system outside the repo, and the graph carries no `tracker` condition |
| 6 | Closeout + IDLE | — | Yes |

**Non-negotiable rule:** you cannot run step N+1 without having completed step N. You cannot reset
to IDLE without going through step 6 — and that is enforced by the FSM, not just written here:
`RELEASE → IDLE` is a declared edge requiring the `commit` and `pr` gates. Abandoning a ticket from
an earlier phase is always allowed; abandoning from RELEASE is not, because at this point there is
nothing left to decide, only steps to finish.

**The PR is mandatory for every tier** — but "mandatory" means *the step gets resolved in front of
the user*, not *a PR always exists*. If the repo has no remote, no `gh`, or is not on GitHub,
`ddw-create-pr` says so, offers the options, and records the outcome. What it must never do is skip
the step in silence.

---

## Step 1: Update the CHANGELOG

1. Check whether `CHANGELOG.md` exists at the project root.
2. If it exists → add an entry under the current version or "Unreleased":
   - Format: `- [ticket] [short description of the change]`
   - Group by type: Added, Changed, Fixed, Removed (following Keep a Changelog).
3. If it does not exist → propose creating it to the user.

---

## Step 2: Commit

1. Run `ddw-commit` following the conventions in `.ddw/rules/commits.instructions.md`.
   - The message includes the `ticket` and the gitmoji for its type.
   - If tier == FIX → the fix prefix.
   - If tier == FEATURE → `feat:`, `refactor:` or whichever applies.
   - Include the CHANGELOG changes in the same commit.
   - **If the working tree is clean** — everything was already committed by the earlier phases —
     the `commit` gate is satisfied by the commits already on the branch. Verify them with
     `git log main..HEAD --oneline` and show them to the user. **Never create an empty commit just
     to tick the gate:** the gate asks for the work to be on the record, not for one more commit.
2. Ask the user to confirm before running the commit.
3. If the user asks for changes to the message → adjust and ask for confirmation again.

---

## Step 3: Pull Request (MANDATORY)

1. Run `ddw-create-pr`. **It checks first whether this repo can host a PR** (remote, `gh`,
   authentication). If it cannot, it reports why and offers the options — it does not fail silently
   and does not leave the ticket stranded in RELEASE.
   - The title includes the `ticket`.
   - The body includes:
     - A link to the spec/fix-plan (derived path: `docs/ddw/specs/spec-{ticket}.md` or
       `docs/ddw/specs/fix-{ticket}.md`).
     - A link to the PRD if there is one (derived path: `docs/ddw/prd/prd-{ticket}.md`).
     - A summary of the changes.
     - For FIX: the root cause, from `docs/ddw/specs/rca-{ticket}.md`.
   - The PR is always created as a **draft**. Marking it "Ready for Review" is a later manual
     action, once the branch is ready to merge.
2. Ask the user to confirm before creating the PR.
3. Add the `pr` gate to `.ddw-state.json.gates`.

---

## Step 4: Integration — where does this branch land? (MANDATORY)

A closed ticket whose branch never reaches the base branch is work that exists and that nobody can
build on. It shows up one ticket later: the next sub-ticket branches off a base that does not have
its predecessor's code, and someone has to work that out by hand.

**Before deciding, measure the drift** (checkpoint 3 of "Staying current" in
`.ddw/rules/branches.instructions.md`): `git fetch origin` and
`git rev-list --count HEAD..origin/{base}`. A branch that is far behind should be updated before it
merges, not after.

Then resolve, out loud:

```
┌─────────────────────────────────────────────────────────┐
│  RELEASE — Integration                                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Branch: [branch]                                        │
│  Base:   [base] — [N commits ahead of this branch]       │
│  PR:     [url or "none"]                                 │
│                                                          │
│  Where does this land?                                   │
│    1. It merges when the PR merges — nothing to do now   │
│    2. Merge it into [base] now (--no-ff)                 │
│    3. Leave the branch; the next ticket branches off it  │
│    4. Leave it — you will handle the integration         │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

- **Option 2** → merge only after the user confirms, and never force. If it conflicts, stop and hand
  it back: a conflict resolved by an agent nobody is watching is worse than a conflict.
- **Option 3** → this is the honest answer for a chain of sub-tickets in a repo with no PR flow. Say
  it plainly, because the next ticket's branch check reads it as its base.

**The answer is recorded in the closeout summary and — for a sub-ticket — in the parent PRD's
index.** Recording it is the whole point: no gate can verify that a human merged something, but
nobody should have to guess afterwards whether anyone did.

---

## Step 5: Tracker Update

If there is an associated tracker ticket (check `.ddw-state.json.tracker`):

1. Propose a transition for the ticket in the tracker per `.ddw/rules/tracker.instructions.md`:
   - FIX → propose transitioning to "Done" or "Resolved".
   - FEATURE → propose transitioning to "Done" or "In Review".
2. Propose a closing comment with:
   - A reference to the commit/PR.
   - A reference to the spec/fix-plan.
   - A summary of what was implemented.
3. Ask the user to confirm before taking any action in the tracker.
4. If there is no direct tracker integration → show the proposed text so the user can paste it
   manually.

If there is no tracker ticket:
- Report: "No tracker ticket associated. Continuing to closeout."

---

## Step 6: Closeout

**Precondition:** verify that ALL the mandatory RELEASE gates are present in
`.ddw-state.json.gates`: `commit` and `pr`. If any is missing → STOP and complete the corresponding step.

**And the `Integration` line below must not be blank.** It is not a gate — the FSM cannot see
whether anyone merged anything — so what keeps it honest is that the closeout does not get presented
without it. If you cannot fill it in, step 4 did not happen; go back and do it.

Present the final summary:

```
┌─────────────────────────────────────────────────────────┐
│  RELEASE — Closeout                                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Ticket: [ticket] — [title]                              │
│  Tier: [tier]                                            │
│  Commit: [short hash]                                    │
│  PR: [url or "not created"]                              │
│  Integration: [merged into X | on the PR | next ticket   │
│                branches off this one | left to you]      │
│  Tracker: [updated status or "no ticket"]                │
│                                                          │
│  Do you confirm closing this ticket?                     │
└─────────────────────────────────────────────────────────┘
```

> **Under `autonomy: "minimal"` this arrow does not wait.** The state is still
> written, the gates are still owed and still refused by the hook, and the
> closing box is still shown — what goes away is the pause for a confirmation of
> something a receipt already attests. Three things stop the run anyway, in
> either mode: a decision nobody wrote down, a corrective loop at its ceiling,
> and a corrupt state. See `.ddw/orchestrator.md` § Autonomy.

Only after the user confirms:

1. **If this was a sub-ticket of a split PRD** (`docs/ddw/prd/prd-{PARENT}.md` exists and indexes
   it): update that index — this sub-ticket's row to `done`, with the integration answer from step 4
   beside it, and the next one in the order to `active`. Commit it with the CHANGELOG. The index is
   the human-readable half of "what is left"; the machine derives the same thing from the history,
   and the two should not be allowed to disagree.
2. Add an entry to `history`: transition RELEASE → IDLE, **stamped with this `ticket` and `tier`**
   (see `.ddw/rules/state.instructions.md`). The reset on the next line wipes `ticket`, so this
   entry is where the finished ticket's name survives — and what stops the session boot from
   offering work that is already done.
3. Reset `.ddw-state.json` to the IDLE state (see the template in
   `.ddw/rules/state.instructions.md`). **`history` is NOT reset** — it is preserved as an audit
   log.
4. Report: "Ticket completed. System back to IDLE." If sub-tickets remain, name them.

---

**FORBIDDEN in this phase:**
- Writing new code
- Modifying the PRD
- Modifying the spec/fix-plan
- Running tests
- Merging PRs without the user's approval
- Closing tracker tickets without the user's approval
