---
applyTo: '**'
version: 1.3.0
---

# Commit and PR Conventions

---

## Commit Format (Gitmoji + Conventional Commits)

```
<gitmoji> <type>(<scope>): <short description> (<ticket>)

<optional body>

Refs: <ticket>
AI-assisted: yes
```

**One commit = one atomic change.** Commits should be as small as possible. One block of the spec =
one commit. One fix = one commit. If a block is large, split it into logical commits.

## Gitmoji — Reference Table

| Emoji | Code | CC type | When to use |
|-------|------|---------|-------------|
| ✨ | `:sparkles:` | `feat` | New functionality |
| 🐛 | `:bug:` | `fix` | Bug fix |
| 🚑 | `:ambulance:` | `fix` | Urgent fix — a bug already hurting users |
| ♻️ | `:recycle:` | `refactor` | Code refactor |
| 🎨 | `:art:` | `style` | Improve code structure / formatting |
| ⚡ | `:zap:` | `perf` | Performance improvement |
| 🔒 | `:lock:` | `security` | Security fix |
| ✅ | `:white_check_mark:` | `test` | Add or update tests |
| 📝 | `:memo:` | `docs` | Documentation |
| 🔧 | `:wrench:` | `chore` | Configuration changes |
| 🏗️ | `:building_construction:` | `chore` | Architectural changes |
| ➕ | `:heavy_plus_sign:` | `chore` | Add a dependency |
| ➖ | `:heavy_minus_sign:` | `chore` | Remove a dependency |
| ⬆️ | `:arrow_up:` | `chore` | Update a dependency |
| 🔥 | `:fire:` | `chore` | Delete code or files |
| 🚀 | `:rocket:` | `chore` | Deploy / release |
| 🗃️ | `:card_file_box:` | `chore` | Database changes / migrations |
| 🚧 | `:construction:` | `wip` | Work in progress (do NOT use in final commits) |

*(Adapt this table to the project. Add or remove emojis according to the team's needs.)*

**The table is a palette, not a per-tier restriction.** Any emoji in it is available in any tier —
pick the one that describes the change. A FIX that is urgent takes 🚑 and one that is not takes 🐛;
a QUICK-FIX that deletes dead code takes 🔥. The mapping below is just the sensible default when
nothing more specific fits.

## Tier → Gitmoji Mapping

| Tier | Default gitmoji | CC type |
|------|-----------------|---------|
| QUICK-FIX | 🐛 `:bug:` | `fix` |
| FIX | 🐛 `:bug:` — 🚑 `:ambulance:` if it is urgent | `fix` |
| FIX (security) | 🔒 `:lock:` | `security` |
| FEATURE (feature) | ✨ `:sparkles:` | `feat` |
| FEATURE (refactor) | ♻️ `:recycle:` | `refactor` |

## Tracker Ticket in the Commit

If there is an associated tracker ticket, include it in parentheses at the end of the first line:

```
✨ feat(auth): add login endpoint (PROJ-123)
```

If there is no tracker ticket, do not add the parentheses:

```
🐛 fix(payments): correct VAT calculation
```

**One commit = one tracker ticket at most.** Do not mix work from multiple tickets in one commit.

## One commit per phase, as each phase closes

A phase that produced something commits it before handing over. Not one commit at the end with
everything in it:

| Phase | What it commits | Default gitmoji |
|---|---|---|
| DEFINE | The PRD (and the RCA, on a FIX) | 📝 `docs` |
| PLAN | The spec/fix-plan, the threat model, any ADR | 📝 `docs` |
| CODE | **One commit per block** — code + tests — as each block passes its reviews and its tests. Plus whatever the closeout changed | The tier's gitmoji |
| RELEASE | The CHANGELOG and whatever is left | The tier's gitmoji |

**CODE is the phase that commits more than once, and that is the same rule, not an exception to
it.** Its unit of work is the block, so the block is what gets committed — exactly as the line at
the top of this file says. FIX and QUICK-FIX have no blocks, so their implementation is one commit.

Two reasons this beats a single commit at the end. **A ticket that gets abandoned still leaves its
thinking behind** — the PRD and the spec are already on the branch, and the reasoning survives the
decision not to build it, which is exactly when it is most worth reading. And **the history says
what happened in what order**: the design landed before the code, and that is visible instead of
being asserted.

If a phase produced nothing new to commit, it commits nothing. An empty commit to tick a gate is
noise, and the gate does not ask for a commit — it asks for the work to be on the record.

> **Only the commit that a closeout edge depends on touches `gates.commit`** — RELEASE for every tier, and the DISCOVERY closeout, which has no RELEASE phase and would otherwise be unable to close at all. The earlier phases commit without setting it. Were any of
> them to set it, the closeout gate would read `true` from the first phase on and would stop
> guarding anything.

## Commit Rules

- Description in the imperative, lowercase, no trailing period.
- First line at most 72 characters (including gitmoji, type and ticket).
- Scope = the module or area affected. *(Define the valid scopes for the project.)*
- ALWAYS include `Refs:` with the `ticket` from `.ddw-state.json`.
- Keep commits as small as possible. Each commit must be atomic and coherent.
- Do not commit files containing secrets (.env, credentials, API keys).
- NEVER include `.ddw-state.json` in `git add`. That file is local, it is in `.gitignore`, and it
  must not be committed.
- Do not commit while there are unresolved blocking gates.

## AI Attribution — Mandatory Trailer

Every commit produced with AI assistance MUST include a trailer:

| Level | Meaning | When to use |
|-------|---------|-------------|
| `AI-assisted: yes` | AI helped, a human reviewed and approved | The human gave instructions and reviewed the result |
| `AI-full: yes` | AI generated the whole change with no intervention | Automatic gate fixes, automatic generation |

**The trailer goes as the last line of the commit message**, separated from the body by a blank
line.

**NEVER create a commit without one of these trailers.**

**NEVER use `Co-Authored-By` as a trailer.** The DDW framework uses exclusively `AI-assisted: yes`
or `AI-full: yes`. A `Co-Authored-By: Claude ...` trailer is a tool default that does NOT apply when
DDW is active. Always ignore it.

## Full Examples

```
✨ feat(auth): add JWT login endpoint (PROJ-123)

Implements POST /api/auth/login with credential validation
and JWT generation with a configurable expiry.

Refs: FEAT-001
AI-assisted: yes
```

```
🐛 fix(payments): correct VAT calculation in billing (PROJ-456)

The VAT percentage was applied to the discounted total instead of
the subtotal. Root cause: wrong order of operations in
calculateTotal().

Refs: FIX-003
AI-assisted: yes
```

## PR Format

Defined by the `ddw-create-pr` skill, and **not repeated here.** Two copies of a template are two
templates: the day someone adds a field, one of them silently becomes wrong, and the reader has no
way to tell which.

**One PR = one ticket.** PRs should also be as small as possible. If the spec has many blocks,
consider one PR per coherent group of blocks (but always within the same ticket).

## GitHub Labels for PRs

| Label | Color | When to apply |
|-------|-------|---------------|
| `AI-assisted` | `#1D76DB` (blue) | PR created with AI assistance |
| `AI-full` | `#7057FF` (purple) | PR created 100% by AI |

**NEVER create a PR without an AI attribution label.**

**NEVER use `🤖 Generated with Claude Code` or similar footers in the PR body.** Attribution is done
exclusively through the `## Attribution` section in the body and the GitHub label (`AI-assisted` or
`AI-full`). Any tool-generated footer must be omitted.

## Notes for the Agent

- Use the `ddw-commit` skill, not `git commit` directly.
- Check there are no unintended staged files.
- Do not include generated files (build/, dist/, node_modules/).
- Always ask the user to confirm before committing.
- Always ask for confirmation before pushing or creating a PR.
- For branch naming, see `.ddw/rules/branches.instructions.md`.
