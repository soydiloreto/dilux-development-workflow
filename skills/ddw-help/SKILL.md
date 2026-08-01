---
name: ddw-help
description: >
  Getting-started guide for DDW. Use it when the user asks "how do I use DDW", "how do I start /
  install DDW", "what is DDW", or "what commands does DDW have".
  Trigger: /ddw-help.
---

# Skill: /ddw-help — How to use DDW

Show this guide when the user asks how to use, start with, or install DDW; what it is; or what
commands it has. Match the level of detail to the question — there is no need to dump all of it
every time.

## What DDW is

DDW (Dilux Development Workflow) is a phased development pipeline, driven by an orchestrator agent
(a state machine), that takes over on its own as soon as you ask for a code change:

```
CLASSIFY → DEFINE → PLAN → CODE → VERIFY → RELEASE
```

The method lives in `.ddw/` and is the same for every tool. What changes per tool is the wiring —
where its skills, its subagents and its hooks go.

## 1. Install

From the DDW repo:

```bash
bash install.sh /path/to/target-repo --target claude|codex|copilot|cursor|gemini|opencode|all
```

Without `--target` it asks. Without a path it uses the current directory. It is idempotent, and it
never overwrites a skill or agent you already have.

The installer:
- copies the method to `.ddw/`,
- writes the skills and subagents into the location your tool looks in,
- wires that tool's hooks,
- adds the activation block to its context file (`CLAUDE.md`, `AGENTS.md` or `GEMINI.md`),
- adds the pipeline state to `.gitignore`.

**Installing is activating**: once it is in, the pipeline is live in that repo.

Then fill in the "Stack" section of `AGENTS.md`. Without it, DDW has nothing to plan or implement
against, and it will stop and ask.

## 2. Use it

Open your agent in the repo and ask for a code change: the pipeline starts by itself. You never
invoke phases by hand. Day-to-day commands:

- `/ddw-status` — which phase the pipeline is in for this repo.
- `/ddw-self-check` — check the installation and the state are sound.

Each phase's skills (`ddw-create-prd`, `ddw-create-spec`, `ddw-test`, `ddw-commit`, `ddw-create-pr`,
and so on) are orchestrated by the state machine; you rarely invoke them yourself.

Not every request pays the full price: CLASSIFY assigns a **tier** and the tier picks the pipeline.
A question is answered directly, a typo takes a short lane, a feature runs the whole thing.

## 3. Work on two things at once

The state is one per directory. For real parallelism use a worktree — each gets its own state:

```bash
git worktree add ../myapp-FEAT-002 -b feat/FEAT-002
```

## 4. Uninstall

DDW touches none of your code: everything lives in `.ddw/`, the `BEGIN DDW` block of the context
file, your tool's hooks, and `.ddw-state.json` (gitignored). Remove those pieces and it is gone.

## More information

- **Full usage:** the DDW repo's `README.md`.
- **Internals** (orchestrator, hooks, FSM, helpers): `docs/DEVELOPMENT.md`.

## What this skill does NOT do

- It is **read-only**: it installs and modifies nothing. It only explains. To install, tell the user
  to run `install.sh`.

## Language

Answer in the language the user is writing in.
