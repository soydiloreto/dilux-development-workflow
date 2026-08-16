# Installing DDW

Two ways in, and the difference is **where the method lives**.

| | Plugin | Drop-in |
|---|---|---|
| The method sits | outside your repo, in the tool | inside your repo, in `.ddw/` |
| Your repo gets | your `AGENTS.md`, the artifacts, the state file | that, plus `.ddw/` and a wiring directory |
| Upgrading | the tool's plugin update | re-run `install.sh` |
| Editing the method | not until you eject | open the file and change it |
| Your teammates | install the plugin too | get it on clone |

**Start with the plugin.** Drop-in is the right answer once you want to change how the method
works — and `/ddw-eject` walks you through it when that day comes, after which plugin updates stop
reaching that repo. That is the trade.

The eject itself is a command **you** run, not something the agent does for you:

```bash
bash "<plugin root>/install.sh" . --method-only
```

Not a limitation of the skill — a consequence of the rule underneath it. Every write into `.ddw/` is
refused in every phase, because that seal is what stops a pipeline editing the rules that stop it,
and it cannot tell installing the method apart from disarming it: a fresh `.ddw/` with weaker rules
is the same write. So ejecting is what installing and uninstalling already are — something done from
outside the ticket, with the hooks looking on. `--method-only` copies the method, records it in the
manifest so the drift check can see it change afterwards, and touches no wiring.

---

## As a plugin

### Let the installer do it

```
bash install.sh . --mode plugin --target claude,copilot,opencode
```

It calls each tool's own plugin CLI rather than writing that tool's cache layout
itself, and for Copilot it also wires the user-level hooks that the plugin
manifest cannot carry — the step that, skipped, leaves an install looking alive
and enforcing nothing. The marketplace it registers is the working copy you ran
it from, so what lands is what is in front of you.

Nothing here needs administrator rights on any platform: every path written is
under `$HOME` or inside the repo you named. Run it before you open the tool and
there is nothing to restart; OpenCode's first launch is slower because that is
when it clones the plugin.

Without `--mode` the installer always asks which of the two you want, whether or
not you named a tool: those are different questions, and the answers leave very
different repositories behind.

`--mode plugin` covers Claude Code, Copilot CLI and OpenCode. For Codex, Cursor
and Gemini it says so and stops — a manifest exists for them in this repository,
but no install procedure for one has been written or driven, and running
something plausible would be worse than saying nothing.

The manual equivalents are below, and are what the installer runs.

### Claude Code

```
/plugin marketplace add soydiloreto/dilux-development-workflow
/plugin install ddw@dilux --scope project
```

`--scope project` records the plugin in the repo's `.claude/settings.json`, so a teammate who clones
gets the pipeline from one line of config. `--scope local` is you alone in this repo; `--scope user`
is every repo you open.

### Copilot CLI and OpenCode

Both need steps of their own, and the reason is worth knowing before you start. Copilot reads the
plugin manifest for its skills and **ignores the hooks in it**, so the gates ride user-level hooks
instead — install the skills and stop, and it looks alive while enforcing nothing. OpenCode
registers the plugin in `opencode.json` and needs a permission for the directory the method lives in.

Both are written out as steps to hand to your agent:
[`.github/INSTALL.md`](../.github/INSTALL.md) · [`.opencode/INSTALL.md`](../.opencode/INSTALL.md)

### Codex CLI and Cursor

Both ship a plugin manifest in this repository and the test suite installs and drives them in that
mode. Nobody has run a full session against either one yet, which is what the README's status
section means by *verified at the boundary*.

### What a plugin install does not do

**Nothing is written to your repo until a pipeline actually starts.** Clone something to read for
five minutes and you get no state file and no edited `.gitignore`.

**The repo always wins.** Every hook looks for `.ddw/` in the project first and the plugin second, so
a repo that wants its own version just has one.

**No `AGENTS.md` is created either**, and that file is where DDW reads your stack. Under a drop-in
install the installer copies a template when it finds none; under a plugin nothing is copied,
because nothing is written to your repo at all. The first CLASSIFY offers to create it, from what it
can detect in the repo and with none of DDW's own content in it — or you write it yourself first.
Either way the file is yours: DDW never puts its blocks, phases or boilerplate in it under a plugin.

---

## Or into your repository

```bash
git clone https://github.com/soydiloreto/dilux-development-workflow.git

cd /path/to/your/project
bash /path/to/dilux-development-workflow/install.sh . --target claude
```

Drop `--target` and it asks. Valid values: `claude`, `codex`, `copilot`, `cursor`, `gemini`,
`opencode`, several separated by commas, or `all`.

Installing **is** activating — there is no separate enable step.

### What lands in your repo

```
.ddw/                      THE METHOD — identical for every tool
├── orchestrator.md          the state machine and the phase router
├── rules/                   per-phase instructions + transition-graph.json
└── scripts/                 the transition validator and the shared hook gate

.claude/  .codex/  …       THE WIRING — one per tool you install
├── skills/                  the actions: create-spec, test, security-sast, commit…
├── agents/                  the auditors: architecture, security, verification
└── hooks/                   the enforcement scripts

AGENTS.md                  your project's context — you fill this in
docs/ddw/                  everything the pipeline produces, committed
.ddw-state.json            the pipeline's memory (gitignored: it is yours)
```

That split is the point. **`.ddw/` is byte-identical across tools.** Supporting a new one means
writing a recipe that says where that tool looks for things — never translating the framework. See
[`adapters/adapter.schema.md`](../adapters/adapter.schema.md).

### Upgrading

Pull, re-run the same command. The installer is idempotent, replaces DDW's own files, and **never
overwrites something you made yours**: if one of your skills shares a name with one of DDW's, it says
so and leaves yours alone. Your state, your artifacts under `docs/ddw/` and your stack are untouched.

Two things decide what "yours" means:

- **The activation block.** DDW writes a block delimited by `<!-- BEGIN DDW -->` / `<!-- END DDW -->`
  into your tool's context file and refreshes it on every upgrade — that block is what loads the
  orchestrator, so a stale one would quietly run an old method. **Only what is between the markers is
  touched.** Anything you wrote outside it is not read, moved or reformatted.
- **It is always `AGENTS.md`.** DDW's instructions live in that one file whatever tool you installed,
  so it holds both your stack and a managed block. Claude and Gemini read `CLAUDE.md`/`GEMINI.md`
  instead, so those get a four-line pointer and nothing else. Nothing is duplicated, so nothing can
  drift.

### Taking it out

```bash
bash /path/to/dilux-development-workflow/uninstall.sh .        # shows the plan, then asks
bash /path/to/dilux-development-workflow/uninstall.sh . --plan # just the plan, changes nothing
```

It removes the method, the runtime, each installed tool's wiring, the activation block and the
`.gitignore` rules — **and nothing else**. What is DDW's is read from the manifest, not guessed from
directory names: `.claude/` is Claude Code's directory and your own skills live there too, so they
stay. Your hooks in `settings.json` stay while DDW's are unwired, which matters more than tidiness —
hooks left pointing at deleted scripts fail on every session afterwards.

**`docs/` is never removed.** The PRDs, specs, threat models and verification reports are the record
of what was decided and why. Uninstalling the tool is not a reason to lose them.

A DDW file you have edited since installing is kept and reported; `--force` removes those too.

---

## The file you have to write

`AGENTS.md` is the one part of the install you own — your stack, your architecture conventions, your
domain glossary. **Read [`AGENTS-MD.md`](AGENTS-MD.md) before you edit it.** DDW manages exactly one
block inside that file, and a heading the method looks up and does not find fails **quietly**: the
pipeline runs on, knowing nothing about your project.

## Requirements

- **Python 3** on your PATH — the transition validator and the hook gate.
- **Git.** The pipeline assumes a real repository.
- One of the six supported tools.

> **Codex and Gemini quarantine project hooks.** Both fingerprint what a repo brings and refuse to
> run it until you approve it. Run `/hooks` in either after installing, or the gates are decoration.

## Working in parallel

State is **one per directory**, so two sessions on the same folder will step on each other whichever
tools they are running. Every adapter registers its session and warns you when it sees another one
alive. For real parallelism, give each ticket a worktree — each gets its own state:

```bash
git worktree add ../myapp-FEAT-002 -b feat/FEAT-002
```
