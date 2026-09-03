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

## The mechanical sweep — the half a script owns

```bash
python3 .ddw/scripts/family_catalog.py --sweep --org ACME    # facts, no prose
python3 .ddw/scripts/family_catalog.py --sweep --repos a,b,c [--facts-out FILE]
```

The catalog above reads what each repo DECLARES about itself. The sweep reads
the repo itself: every tree pulled from its **tarball**, never a clone —
looking at a repository needs its files, not its history, and at organisation
scale the history is the whole cost.

It writes facts, not prose: the top-level layout, the manifests, the README's
head, and every path that matches a structural pattern (routes, controllers,
events, migrations, schemas, API descriptions, workflows) — **each fact
carrying the path it came from**, and each repo carrying the SHA it was read
at. No model runs here.

The path is not decoration. It is what a later row of prose must CITE, and it
is what makes the refresh cheap: a repo is re-read when one of the paths its
row cites has moved, not on every commit.

Every repo lands in the file, readable or not: one that could not be read is a
row with a reason. A sweep that drops what it could not read reports a smaller
organisation in green, which is the one outcome this method spends its checks
preventing.
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

## The prose half, and the gate it must pass

The sweep gathers facts. The **renglón** (one line per repo, so a question can
pick which repos matter) and the **ficha** (half a page, for a repo that was
picked) are prose, and prose is the model's half. Write them against the facts
file, never against memory, and then submit them:

```bash
python3 .ddw/scripts/family_catalog.py --admit docs/ddw/store [--facts FILE]
```

**The store's shape** — two files, both managed blocks:

`renglones.md`

```
<!-- BEGIN DDW ROWS -->
| Repo | SHA | Renglón |
|---|---|---|
| rewards-api | 89abcde | Motor de promociones legacy; resuelve el tope por usuario en el camino de pago. |
<!-- END DDW ROWS -->
```

`fichas/<repo>.md`

```
<!-- BEGIN DDW FICHA --><!-- repo: acme/rewards-api · sha: 89abcde -->
| Afirmación | Archivo |
|---|---|
| Publica cashback.start | events/publisher.js |
<!-- END DDW FICHA -->
```

**Every claim names the file it comes from.** That is the rule the gate
enforces and the reason the ficha is worth anything: a sentence with a file
beside it can be checked by the next reader, and a repo can be re-read when
that file moves rather than on every commit.

**What the gate checks** — the three things a script can:

1. **Coverage.** Every repo the sweep read has a row. A store that omits
   repos answers "who do I hit?" over a smaller organisation, in green.
2. **No invention.** No row names a repo the sweep never saw.
3. **Citations resolve.** Every claim's file is one the sweep actually found
   in that repo, and the ficha's stamped SHA is the one it was read at.

**What it does NOT check, and says so on every run: that a claim is TRUE.** A
file that exists is not a claim that holds. What the gate buys is that every
claim points at something real in a real commit, that the whole sweep is
accounted for, and that a ficha written against an older commit cannot pass as
current. The truth of the sentence stays a human reading — and the store says
which commit to read it against.

Exit 3 refuses the store and **names every problem**, not the first: a gate
people walk once per defect is a gate people route around.

## The refresh — which rows actually have to be re-read

```bash
python3 .ddw/scripts/family_catalog.py --stale docs/ddw/store [--org ACME]
```

At organisation scale the sweep is affordable once and unaffordable on a
schedule: a thousand repositories move every week, and re-reading all of them
because their SHA changed costs what never having indexed anything costs.

So the SHA is not the question. "Did this repo move" is almost always yes and
is worthless on its own; **"did it move where a row leans"** is the question,
and the citations make it answerable. A row is stale when the diff since it was
read:

- **adds or removes a file** — a new file is cited by nobody, precisely because
  it did not exist when the row was written, so this is the filter that catches
  a seam added after the sweep;
- **touches a file its ficha cites**;
- **lands on a structural path** (routes, controllers, events, migrations,
  schemas, API descriptions).

Anything else leaves the row true and the repo is not re-read. A comparison the
forge could not make counts as **stale**, never as fresh: the failure of a
freshness check must not read as freshness.

Exit 3 when something is stale, and the run prints the exact re-sweep to run —
only the repos that need it. What closes the gap the three filters leave is the
full re-sweep run cold now and then, plus the fact that every row carries the
commit it was read at, so "this row is behind" is always answerable.

## What it never does

- Never feeds a gate: the catalog is a report. Enforcement stays where it
  lives — the multirepo index's rows, held to the forge.
- Never stores a credential, never runs on a schedule by itself. Scheduling
  the command is the user's cron/CI to set up, if they want it.
