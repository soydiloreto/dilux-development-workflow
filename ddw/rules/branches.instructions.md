---
applyTo: '**'
version: 1.3.0
---

# Branch Conventions

---

## When to Create the Branch

The working branch is created at the **end of the CLASSIFY phase**, after the user confirms the
classification and before updating the state.

**Reason:** starting in DEFINE, files get created (PRDs, RCAs), and in PLAN, specs/fix-plans. Every
artifact for the ticket must live on the branch from the very first moment. Nothing should be
written on `main`.

### Sequence:
1. The user confirms the classification in CLASSIFY.
2. Create the branch immediately, following the naming convention.
3. Update the state and transition to DEFINE (already on the branch).
4. All artifacts (PRD, spec, code, tests) are written on this branch.
5. The branch is pushed and the PR is opened in the RELEASE phase.

---

## Naming

### Format

```
<prefix>/<ticket>-<short-name>
```

- **prefix**: indicates the type of work (see table).
- **ticket**: the ticket ID (from the tracker if there is one, e.g. `PROJ-123`; or internal, e.g.
  `FIX-001`).
- **short-name**: 2–4 words in kebab-case describing the change.

### Prefixes by Tier

| Tier | Prefix | What it groups | Example |
|------|--------|----------------|---------|
| FEATURE | `feat/` | Features and functional changes | `feat/PROJ-108-product-catalog` |
| QUICK-FIX | `fix/` | Sub-10-LOC fixes with no attack surface | `fix/FIX-002-typo-log-message` |
| FIX | `fix/` | Bug fixes | `fix/PROJ-42-cors-header` |
| DISCOVERY | `discovery/` | Ideation and product definition | `discovery/DISC-001-marketplace` |

**What does the `/` in the prefix do?** In git, `/` creates visual grouping. In GitHub, GitLab and
most GUIs, branches are displayed organized by folder: all the `feat/` ones together, all the `fix/`
ones together. It is visual organization — it does not change git's behavior.

### Examples with and without a tracker

```
feat/PROJ-108-product-catalog          ← tracker ticket as the primary ID
fix/FIX-001-typo-email-validation      ← internal ID (no tracker)
discovery/DISC-001-marketplace         ← internal Discovery ID
feat/FEAT-002a-db-migration            ← sub-ticket (always with a letter suffix)
feat/FEAT-002b-bot-integration         ← sibling sub-ticket
```

### Sub-tickets (split tickets)

When a PRD is split in DEFINE (scope check), each sub-ticket uses the same prefix as the parent
ticket with a lowercase letter suffix:
- `feat/{TICKET}a-short-name`, `feat/{TICKET}b-short-name`, etc.
- The first is ALWAYS `a`. **NEVER without a letter suffix.**

---

## Base Branch

| Situation | Base branch |
|-----------|-------------|
| Normal development | `main` or `develop` (depending on the project) |

*(Adapt to the project's branching model: gitflow, trunk-based, GitHub flow, etc.)*

---

## Staying current — three checkpoints

A branch built on a stale base is a merge conflict that has not happened yet, and every day it stays
behind makes it bigger. The research behind trunk-based development puts the useful lifetime of a
branch at **under a day**, and GitHub encodes the same idea as a merge requirement ("require
branches to be up to date before merging") or a merge queue. DDW cannot merge for you, so it does
the part it can: it never starts you from a stale base, and it never lets you find out late.

**These are checks, not gates.** Whether to rebase, merge or ignore the drift is the project's
convention and the user's call. DDW reports the distance and asks; it never rewrites history on its
own.

### 1. Creating the branch (CLASSIFY)

```bash
git fetch origin
git switch -c feat/{ticket}-short-name origin/{base}
```

**Fetch and branch from `origin/{base}` — do not `git pull`.** Pulling requires standing on the base
branch and can trigger a merge nobody asked for, on a working tree that may not be clean. Branching
from the fetched ref does exactly one thing, and does it the same way every time.

If there is no remote: `git switch -c … {base}`, and say so out loud — a local-only repo has nothing
to be stale against, and pretending otherwise is worse than the silence.

### 2. Resuming a branch that already exists (DEFINE's branch check, and session boot)

The branch may have been created days ago. Measure the drift before working on it:

```bash
git fetch origin
git rev-list --count HEAD..origin/{base}      # commits the base gained since
```

If it is 0, say nothing. If it is not:

```
⚠️  The base branch moved {N} commits since this branch started.

  1. Update this branch from origin/{base} (the project's convention decides
     rebase or merge — say which)
  2. Continue as is (the drift will surface at merge time)
```

**Wait for the answer.** Never rebase or merge on your own: rewriting history the user did not ask
for is not a convenience, and a conflict resolved by an agent nobody was watching is worse than a
conflict.

### 3. Before opening the PR (RELEASE)

The same measurement, in the phase where the drift actually costs something: a PR built against a
base that moved 40 commits ago merges code that was never tested against what is there now. This is
precisely the condition GitHub's branch protection enforces, applied one step earlier — where it is
still cheap to act on.

### Sub-tickets with dependencies

When a sub-ticket depends on other sub-tickets (e.g. `FEAT-002c` depends on `FEAT-002a` and
`FEAT-002b`), check whether those dependencies are merged into the base branch BEFORE creating the
branch. **RELEASE's integration step recorded the answer** for each one that already closed — read
it there instead of guessing, and verify it against git:

- **If the dependencies are merged into `main`/`develop`** → create the branch from the base branch
  as usual.
- **If the dependencies are NOT merged** → WARN the user:
  ```
  ⚠️ This sub-ticket's dependencies are not merged into [base branch]:
    - FEAT-002a: branch feat/FEAT-002a-... (PR pending / not opened)
    - FEAT-002b: branch feat/FEAT-002b-... (PR pending / not opened)

  Options:
    1. Create the branch from the last completed sub-ticket (feat/FEAT-002b-...)
    2. Wait for the pending PRs to be merged
    3. Create from [base branch] (the dependencies' code will not be available)
  ```
- **Wait for the user's answer before creating the branch.**

---

## Rules

- **One branch per ticket.** Every ticket in the pipeline gets its own branch.
- **Do not reuse branches.** When a ticket closes (RELEASE phase), the branch is merged and not
  reused.
- **Do not work on `main` directly.** Always create a branch, even for small fixes.
- **Lowercase names.** No spaces, no special characters except `-` and `/`.
- **~60 characters max** for the full branch name (to avoid trouble in some tools).

---

## Artifact Path Convention (derived, not stored)

Paths are derived from the ticket; they are not saved in the state:

| Artifact | Path |
|---|---|
| PRD | `docs/ddw/prd/prd-{ticket}.md` |
| Parent PRD (split) | `docs/ddw/prd/prd-{ticket}.md` (becomes an index) |
| Sub-ticket PRD | `docs/ddw/prd/prd-{ticket}a.md`, `prd-{ticket}b.md`, etc. |
| PRD (DISCOVERY) | `docs/ddw/prd/prd-{ticket}-{NN}.md` (e.g. `prd-DISC-001-01.md`) |
| Concept (DISCOVERY) | `docs/ddw/discovery/concept-{ticket}.md` |
| Fix-brief (QUICK-FIX) | `docs/ddw/prd/fix-{ticket}.md` (a lightweight PRD substitute; not to be confused with the Fix-plan in `docs/ddw/specs/`) |
| Spec / Fix-plan | `docs/ddw/specs/spec-{ticket}.md` or `docs/ddw/specs/fix-{ticket}.md` |
| RCA (FIX only) | `docs/ddw/specs/rca-{ticket}.md` |
| Threat model | `docs/ddw/security/threat-{ticket}.md` |
| SAST report | `docs/ddw/security/sast-{ticket}.md` |
| ADR | `docs/adr/adr-NNN-title.md` — **outside `docs/ddw/`, deliberately** |
| Branch | `feat/{ticket}`, `fix/{ticket}`, or `discovery/{ticket}` |

**This table is the single definition of where every artifact lives**, and every path in the method
derives from it — nothing is stored in the state, and no phase decides for itself. That is what makes
the layout relocatable: a fork that wants its artifacts somewhere else changes them here.

Everything DDW produces lives under **`docs/ddw/`**, namespaced so it never collides with the
project's own `docs/`. Two consequences worth the nesting: a repo that already has a `docs/specs/`
does not end up with its specs and DDW's mixed together, and "what did this process generate" is one
directory you can read, review or grep.

The ADR is the exception, and on purpose: an architecture decision record is a decision **of the
project**, not an artifact of the tool that helped write it. `docs/adr/` is an established
convention with tooling that expects it there, and the decision outlives whoever used DDW to record
it.

---

## Notes for the Agent

- Create the branch at the end of the CLASSIFY phase, after the user confirms.
- The branch name is derived from the ticket and tier by convention (it is not stored in the state).
- **Fetch and branch from `origin/{base}`** — see "Staying current" above. Never `git pull` to
  freshen the base.
- If the branch already exists (resuming a session), check it out instead of creating a new one —
  **and measure the drift**, checkpoint 2 above.
- In the RELEASE phase, the `ddw-create-pr` skill derives the branch name from the ticket.
