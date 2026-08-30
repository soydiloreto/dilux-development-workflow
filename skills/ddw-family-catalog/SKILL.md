---
name: ddw-family-catalog
description: >
  Regenerates the workspace's family catalog from each member repo's own
  `## Repo family` declaration — derived, never hand-edited, so it cannot rot.
  Trigger: /ddw-family-catalog, standing in a family's workspace repo.
---

# Skill: /ddw-family-catalog

## What it is

The consolidated answer to "what does each repo of this family do", built the
only way a catalog survives: **derived from the declarations that travel with
each repo's own code**, on demand, with every row recording exactly which
version of which file it came from. Hand-maintained catalogs rot the week
after they are written; a derived one cannot drift further than one re-run.

Membership is self-declared: a repo is in the catalog if and only if its
`AGENTS.md` carries a `## Repo family` section whose `Workspace` names this
repo. Joining is adding the section; leaving is removing it — and a departure
is annotated in the block on the next run, never silent.

## Execution

Standing in the workspace repo:

```bash
python3 .ddw/scripts/family_catalog.py            # derive and write
python3 .ddw/scripts/family_catalog.py --check    # fresh? exit 0/3, writes nothing
```

(Under a plugin install the script lives in the plugin's method tree; resolve
it the way every DDW script is resolved — the repo's `.ddw/` first, the plugin
root second.)

- Enumeration: the workspace owner's repos via the **user's own `gh`** (no
  credential is ever stored by DDW), or `--repos a,b,c` explicit, or
  `--local <dir>` to read sibling clones offline.
- Output: the managed block in `docs/ddw/family-catalog.md`
  (`BEGIN/END DDW CATALOG`). Outside the markers the file is the user's;
  inside, no hand writes — the header says so.
- A member whose `AGENTS.md` cannot be fetched is kept and marked
  `(unreachable: …)`: "the forge fell over" and "no longer a member" must
  never read the same.

**Print the script's output VERBATIM.** A run without the script's own lines
catalogued nothing, whatever the prose around it says.

## After a run that changed the file

Show the diff and offer the ordinary commit (`ddw-commit` conventions). The
catalog is a derived document: committing it is bookkeeping, and a `--pr`
detour is only worth it where branch protection demands one.

## The other direction: propagating the map

```bash
python3 .ddw/scripts/family_catalog.py --write-members --local ~/repos [--push]
```

The owner's decision (2026-08-26): the family's map is AUTHORED once,
centrally, in the workspace's `ddw-family.md`, and the routine PROPAGATES it —
creating or updating each member clone's `## Repo family` section and
committing IN that clone under the user's own git identity. This is the user
administering their own repositories with their own credentials — the
installer's class of act; what stays forbidden is a pipeline SESSION writing
across repos. Only the section is touched (the rest of each `AGENTS.md` is
its repo's own), an unchanged map writes nothing, and pushes are listed
rather than taken unless `--push`.

## What it never does

- Never feeds a gate: the catalog is a report. Enforcement stays where it
  lives — the multirepo index's rows, held to the forge.
- Never stores a credential, never runs on a schedule by itself. Scheduling
  the command is the user's cron/CI to set up, if they want it.
