---
name: ddw-eject
description: >
  Copies the method out of the plugin and into this repository, so it can be read, edited and
  versioned with the project. After this, the repo's copy is the one that runs.
  Trigger: /ddw-eject, available in any DDW phase.
---

# Skill: /ddw-eject

## Description

Installed as a plugin, the method lives outside your repository — nothing of DDW's is in your tree,
which is what you want most of the time. **This copies it in.**

That matters the moment you want to change something. A pipeline you cannot edit is a pipeline you
have to accept whole, and the whole argument of this framework is that you should be deciding which
parts of it earn their cost in *your* project. Editing the plugin would change every project you
have; editing `.ddw/` in your repo changes this one.

**The repo wins.** Every hook resolves the method as `.ddw/` first, the plugin second, so the moment
this skill finishes there is nothing else to switch on. Your copy is the one that runs.

## When it is worth doing

- You want to **remove a phase or a gate** your project does not need.
- You want to **add a rule of your own**, or edit the wording of one that does not fit your domain.
- You want the pipeline **versioned with the project**, so a change to it lands in a commit and
  shows up in review like any other decision.
- Your team wants a teammate who clones the repo to get **exactly your pipeline**, not the current
  upstream default.

If none of those apply, do not do this. The plugin updating itself is a real benefit, and you give
it up here — see the trade below.

## Inputs

- The plugin's method directory (`${CLAUDE_PLUGIN_ROOT}/ddw`, or the equivalent for your tool).
- The repository root.

## Execution Protocol

1. **Check there is something to eject.** If `.ddw/` already exists in the repo, stop and say so:
   the method is already here, and the plugin is already being overridden. Offer `/ddw-self-check`
   instead if they suspect it is stale.
2. **Say what will change, and wait.** This adds a directory to their repository — a small thing, but
   theirs, and they get to say no:

   ```
   ┌─────────────────────────────────────────────────────────┐
   │  /ddw-eject — copy the method into this repo             │
   ├─────────────────────────────────────────────────────────┤
   │                                                          │
   │  From: [plugin root]/ddw                                 │
   │  To:   .ddw/            ([N] files)                      │
   │                                                          │
   │  After this:                                             │
   │    · This repo runs ITS copy. The plugin is ignored here │
   │    · You can edit any of it. It commits with your code   │
   │    · Plugin updates NO LONGER reach this repo            │
   │                                                          │
   │  Go ahead?                                               │
   └─────────────────────────────────────────────────────────┘
   ```
3. **Copy** the method to `.ddw/`. Nothing else moves: the wiring stays with the plugin, and the
   context file is untouched.
4. **Commit it** with `Skill(skill="ddw-commit")` as a `🔧 chore`. A method sitting uncommitted is
   the one thing worse than not having ejected — the next `git checkout` takes it and nobody knows
   why the pipeline changed.
5. **Report** where it landed and what to read first: `.ddw/rules/` for the phases,
   `.ddw/rules/transition-graph.json` for what movements are legal.

## The trade, said plainly

| | Plugin | Ejected into the repo |
|---|---|---|
| Updates | `/plugin update`, once, everywhere | **Yours now.** Re-run the installer or merge by hand |
| Editing | Changes every project you have | Changes this one |
| A teammate who clones | Needs the plugin installed | **Gets your exact pipeline** |
| Your repo | Nothing of DDW's in it | `.ddw/`, committed |

Neither is the right answer in general. The plugin is right while the default fits; ejecting is right
once it does not.

## PASS/FAIL criteria

- N/A. This is an action, not a validation.

## Updating .ddw-state.json

- NONE. Where the method is read from is not part of the pipeline's state — it is resolved on every
  hook, from the filesystem.

## Language

Write the panel and the report in the language the user is working in.
