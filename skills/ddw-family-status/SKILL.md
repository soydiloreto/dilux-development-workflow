---
name: ddw-family-status
description: >
  The initiative's next step across the family, answered from ANY member repo: reads the index
  at the workspace's origin, asks the forge which children actually merged, and puts exactly one
  verdict on screen — the stale row to correct first, the next repo to walk to with its command,
  the blockers by name, or all-done. Read-only on every repo. Trigger: /ddw-family-status
  [TICKET], in any repo that declares `## Repo family`.
---

# Skill: /ddw-family-status

## Description

Standing anywhere in a family, mid-initiative, the question is always the same: "¿cómo sigo?".
This skill is that answer, deterministic and fresh. Its whole engine is `family_next.py` — the
conductor — and the skill adds only what a script cannot: finding the ticket when the user did
not name it, and walking to the repo the verdict points at.

It writes NOTHING, in this repo or any other. When the verdict is a row update, the way back is
`family_index_pr.py update-row` — every write to the workspace travels through the forge.

## Protocol

1. **Resolve the initiative's ticket.** The user's argument wins. Without one: the standing
   repo's `.ddw-state.json` ticket, or the parent named in its PRD's family row. Two candidates
   → ask, one line.

2. **Ask the conductor** (script, not memory):

   ```bash
   python3 .ddw/scripts/family_next.py --ticket <TICKET>
   ```

   It reads the index from the workspace's **origin/main** (fetched first, never a stale local
   copy) and asks the forge for each row's MERGED child PR — a dependency is satisfied by a
   merge, never by another row's recorded status. Where index and forge disagree, the forge
   wins and the index is the bug.

3. **Put the one verdict on screen**, verbatim in meaning:
   - **update** — the index is behind the forge. Offer the exact `family_index_pr.py update-row
     … --status done` command; with the user's ok, run it and remind them the row lands as a
     workspace PR merged by the one-approve leash.
   - **next** — name the repo and its scope, and offer the move: `cd` to the sibling clone and
     open the child's run THERE (`Implementá mi parte de <TICKET>`). Each repository's own
     state, hooks and gates rule in its own directory. When the conductor also prints the
     `∥ EN PARALELO` block, relay it: those parts may run at the same time, each in its own
     clone — in a tool that cannot orchestrate subprocesses, walk them in the printed order.
   - **waiting** — every blocker by name, and whose merge each part waits on. Nothing to force;
     the answer is a fact.
   - **all-done** — the initiative is ready to close in the workspace.

4. **Never improvise a verdict.** If the script cannot answer (no workspace clone, no index at
   origin/main), its stderr says what is missing and how to get it — relay that, fix that, and
   ask again. A next-step reconstructed from memory is the stall this skill exists to end.

## PASS/FAIL criteria
- N/A — this skill is informational; it has no verdict of its own. The conductor's exit code 2
  means "could not answer", never "the initiative is stuck".

## Updating .ddw-state.json
- NONE. This skill is strictly read-only.

## Language

Write the summary in the language the user is working in.
