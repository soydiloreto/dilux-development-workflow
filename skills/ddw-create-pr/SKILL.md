---
name: ddw-create-pr
description: >
  Opens a Pull Request with a standard format and AI attribution labels, or records why one is not
  possible in this repo.
  Trigger: /ddw-create-pr, during DDW's RELEASE phase.
---

# Skill: /ddw-create-pr

## Description
Opens a Pull Request with a standard format and AI attribution labels. If this repo cannot host a
PR, records why — so the closeout is never blocked by something outside the user's control.

## Inputs
- The current branch and the base branch.
- The branch's commits.
- `.ddw-state.json` for ticket, tier and gates.
- `.ddw/rules/commits.instructions.md` for the format.

## Step 0: Can this repo host a PR? (check FIRST)

Before writing anything, check the preconditions — in this order, stopping at the first that fails:

```bash
git remote                     # is there a remote at all?
git remote get-url origin      # where does it point?
command -v gh                  # is the GitHub CLI installed?
gh auth status                 # is it authenticated?
```

**If they all pass** → continue with the normal protocol.

**If any fails**, do NOT invent an alternative and do NOT fail silently. Report exactly what is
missing and offer the options:

```
┌─────────────────────────────────────────────────────────┐
│  /ddw-create-pr — A PR is not possible here              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Reason: [no remote configured / gh not installed /      │
│           not authenticated / the remote is not GitHub]  │
│                                                          │
│  What do you want to do?                                 │
│    1. Push the branch and open the PR yourself (I will   │
│       print the title and body for you to paste)         │
│    2. Record that a PR does not apply to this repo and   │
│       close the ticket                                   │
│    3. Stop here — I will fix it and you re-run this      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

- **Option 1 or 2** → mark `gates.pr = true` with the reason recorded in the closeout summary. The
  gate means *"the PR step was completed"*, and completing it in a repo that cannot host one means
  recording why, out loud. This is what keeps a local-only repo from getting stuck in RELEASE
  forever.
  **Then RELEASE's step 4 still runs.** No PR means nothing is going to merge this branch on its
  own, which is exactly when "where does this land?" has to be answered rather than assumed.
- **Option 3** → do not set the gate. The ticket stays in RELEASE, which is correct: the user asked
  to stop.

> This is not a loophole. `RELEASE → IDLE` demands the `pr` gate precisely so that nobody closes a
> ticket while quietly skipping the review step. Announcing "there is no remote, so there is no PR"
> in front of the user is a decision they took; silently omitting it is the thing being prevented.

## Execution Protocol

1. Run `git status`, `git diff <base>...HEAD`, `git log <base>...HEAD`.
2. Analyze ALL the branch's commits, not just the last one.
3. Check the GitHub labels exist:
   - `AI-assisted` (color `#1D76DB`)
   - `AI-full` (color `#7057FF`)
   - If they do not exist → create them with `gh label create`.
4. Write the PR title and body.
5. Present them to the user for approval.
6. Only after approval → create it with `gh pr create --draft --label <AI-assisted|AI-full>`.
7. Return the PR's URL.

## PR Format

```
Title: [ticket] <short description> (< 70 characters)

Body:
## Ticket
[ticket]

## Summary
- [bullet 1 with the main changes]
- [bullet 2]

## Changes
[Detailed list grouped by area]

## Tests
- Tests run: X passed, Y total
- Coverage: XX% lines, XX% branches (if available)

## Security
- SAST: PASSED ([date])

## Attribution
[AI-assisted | AI-full]: [description of the level of human supervision]
```

## Rules

- Title ≤ 70 characters.
- ALWAYS create the PR as a **draft** (`--draft`). Moving it to *Ready for Review* is a manual
  action, once the branch is ready to merge.
- ALWAYS include the `AI-assisted` or `AI-full` label with `--label`.
- ALWAYS include the Attribution section in the body.
- NEVER create a PR without the user's confirmation.
- NEVER merge automatically.
- NEVER include `🤖 Generated with Claude Code` or similar footers in the body. Attribution is done
  exclusively through the `## Attribution` section and the GitHub label.

## Output Format

```
┌─────────────────────────────────────────────────────────┐
│  /ddw-create-pr — Created ✓                              │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  PR: #[number]                                           │
│  URL: [url]                                              │
│  Title: [title]                                          │
│  Label: [AI-assisted | AI-full]                          │
│  Status: Draft                                           │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Updating .ddw-state.json
- `gates.pr` → `true` once the PR is created, or once the user chooses option 1 or 2 above. The
  RELEASE closeout requires this gate before it will reset to IDLE.

## Language

Write the PR's title and body in the language the user is working in, keeping the section headings
as specified above.
