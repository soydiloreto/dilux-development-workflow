# Adapter recipe — adding support for a new tool

DDW keeps **one copy of everything**. The orchestrator, the rules, the 17 skills and the 5 agents
live once, under `ddw/`, written in no tool's dialect. An adapter is not a copy of the framework —
it is a **recipe** that says where this particular tool looks for things and what frontmatter it
speaks. The installer transpiles at install time.

Supporting a new tool means adding one directory. No code changes: `install.sh` discovers targets by
globbing `adapters/*/adapter.json`, and `scripts/install_target.py` is a generic engine that knows
nothing about any specific tool.

```
adapters/<id>/
├── adapter.json          the recipe (this document)
└── <whatever wiring>/    only that tool's hook scripts / plugin
```

## Before writing the recipe

Answer four questions from the tool's own documentation. Do not guess — a wrong path means the tool
silently ignores half the framework:

1. **Where does it look for skills — its OWN location?** Several tools also search `.claude/skills`
   as a compatibility path. Do not use that. DDW never makes one tool depend on another tool's
   directory: OpenCode gets `.opencode/skills`, Copilot gets `.github/skills`. Installing for
   several tools writes the payload into each of their directories, which is what generation *is* —
   the single source stays `skills/`.
2. **Where does it look for subagents, and what filename convention?**
3. **What frontmatter does a subagent need?** Some want a tool allowlist, others express permissions.
4. **How does it run hooks, and which file wires them?**

## Fields

| Field | Required | What it does |
|---|---|---|
| `$schema` | no | Relative pointer to this document, so an editor can offer it while the recipe is written. |
| `id` | yes | Must equal the directory name. This is what `--target` takes. |
| `label` | yes | Human name, shown in the installer's menu. |
| `docs` | no | Link to the documentation the recipe was derived from. Put it in — it is what the next person checks when the tool changes. |
| `skills.dir` | no | This tool's **own** skills directory, repo-relative. Omit the whole `skills` block if the tool has no skill mechanism. |
| `skills.note` | no | Why that directory. Worth writing down. |
| `skills_are_slash` | no | `true` when the tool already exposes every skill as `/name` by itself. It suppresses the generated commands below — without it Claude Code ships each skill twice, once as a skill and once as a command that only says to use the skill. |
| `commands` | no | `{dir, filename, frontmatter, body, note}` — for a tool that discovers skills but does not surface them as `/name`. The installer writes one thin command per skill whose body points at the skill. OpenCode needs it: the installer's own closing line told the user to type `/ddw-status` and the TUI answered that no such command exists. |
| `agents.dir` | no | Repo-relative directory for subagents. Omit the block if the tool has no subagents. |
| `agents.filename` | no | Filename template, default `{name}.md`. E.g. Copilot uses `{name}.agent.md`. |
| `agents.frontmatter` | yes, if `agents` | The tool's dialect. Keys are emitted as YAML; values may be literals or templates over the neutral fields. |
| `agents.format` | no | `yaml` (default) or `toml`. Codex declares subagents as TOML files, prompt and all — not markdown with frontmatter. |
| `agents.when_readonly` | no | Extra frontmatter merged in for agents declaring `writes: false`. For tools that deny by permission instead of by tool list. |
| `wiring[]` | no | `{from, to, chmod}` — copy `adapters/<id>/<from>` to `<repo>/<to>`. `chmod: "+x"` makes `.sh` files executable. |
| `settings_merge` | no | `{from, to, merge_key}` — merge one key into an existing JSON config rather than overwriting the user's file. |
| `settings_merge.base` | no | Top-level keys to seed when the installer is the one creating that file (Cursor's `hooks.json` carries a schema `version` beside the hooks). |
| `trust_note` | no | Anything the user must do by hand before enforcement is live. Codex and Gemini both fingerprint project hooks and quarantine them until approved — a recipe that stays silent about that ships a pipeline that looks installed and enforces nothing. |
| `context_file` | no | The file the activation snippet is appended to (`CLAUDE.md`, `AGENTS.md`, …). |
| `snippet` | no | Only when the tool needs special syntax. Omit it and the shared, tool-neutral `ddw/activation.snippet.md` is used. |

## Template placeholders

Available inside `agents.frontmatter` values, taken from the neutral frontmatter of
`agents/*.md`:

| Placeholder | Source |
|---|---|
| `{name}` | the agent's id, e.g. `ddw-implementer` |
| `{description}` | when the orchestrator should spawn it |
| `{tools}` | the tool list, e.g. `Read, Grep, Glob, Bash` |

`writes: true|false` is not a placeholder and is not declared by hand: the installer derives it from
the agent's tool list (anything holding `Write`/`Edit`/`NotebookEdit` writes). It selects whether
`when_readonly` is merged in.

## Worked example

`agents/ddw-arch-auditor.md` declares, once and for every tool:

```yaml
name: ddw-arch-auditor
description: Read-only architecture auditor. …
tools: Read, Grep, Glob, Bash
writes: false
```

Claude's recipe asks for a tool allowlist:

```json
"agents": {
  "dir": ".claude/agents",
  "frontmatter": { "name": "{name}", "description": "{description}",
                   "model": "inherit", "tools": "{tools}" }
}
```

OpenCode's expresses the same restriction as a permission, because that is its dialect:

```json
"agents": {
  "dir": ".opencode/agents",
  "frontmatter": { "description": "{description}", "mode": "subagent" },
  "when_readonly": { "permission": { "edit": "deny", "write": "deny" } }
}
```

Same body, same guarantee, two dialects — and the auditor's prompt exists once.

## What does NOT belong in an adapter

- **Copies of skills or agents.** If you find yourself pasting one into an adapter, the recipe is
  wrong. Fix the recipe.
- **Method rules.** Phases, gates and the transition graph are `ddw/`'s job and are identical
  everywhere. An adapter that changes the method is not an adapter, it is a fork.
- **A language.** The method is written in English but answers in whatever language the user writes
  in — see the Language directive in `ddw/AGENTS.template.md`.

## Enforcement is the part you have to actually write

The recipe wires files; it cannot invent a deny mechanism. Every tool spells "block this write"
differently — Claude Code uses `exit 2` from a PreToolUse hook, OpenCode throws from a plugin,
Copilot CLI returns a deny-JSON. That script is the real work of a new adapter, and it is the one
piece that must be tested against a live session before you claim the target is supported.

Every adapter calls the same entry point, `.ddw/scripts/hook-gate.py`, which parses that tool's
event shape, asks `validate-transition.py` the one question worth asking, and answers in that tool's
refusal dialect. Nothing about the FSM is reimplemented per tool.

**This is not a style preference.** Two adapters once carried their own copy of that glue, and both
got it wrong the same way: they read the event off stdin before the validator could, so the
validator saw an empty envelope, exited 0, and every illegal write went through. Both tools looked
installed and enforce nothing, while a test suite that exercises the validator directly
and stayed green. A new adapter's enforcement is not "supported" until `verify_install.sh` drives
that tool's own hook, with that tool's own envelope, and sees it refuse.
