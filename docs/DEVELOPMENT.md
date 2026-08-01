# DDW — Internals

How DDW works on the inside. To install and use it, see **[README.md](../README.md)**.

DDW separates **the method** from **the wiring**:

- `ddw/` in this repo installs into your project as `.ddw/` — the tool-agnostic method (orchestrator,
  rules, scripts). It never changes between tools.
- `adapters/<tool>/` is the wiring — hooks, skills, agents and settings for one specific harness.
  `install.sh` copies the one you pick.

**Plugin mode.** `.claude-plugin/plugin.json` declares the packaging,
`.claude-plugin/marketplace.json` is what makes it installable at all, and
`adapters/claude/plugin-hooks.json` carries the same six hooks resolved from the
plugin root rather than the project.

Every hook resolves the method through `ddw_method` in `adapters/claude/hooks/lib/guard.sh`:
**the repo's `.ddw/` first, the plugin second.** That sentence used to be here
and was false — two of the six hooks did it, the other four looked only in the
repo, and `session-start.sh` was one of them. Installed as a plugin, DDW loaded
its skills and its agents and enforced nothing, which is the failure
`scripts/acceptance.md` opens by naming. It read as working because the drop-in
path, which is what anyone tested, never exercised the other branch.

Two consequences of the method being outside the repo:

- **The session-start hook is not defence in depth any more, it is the only
  channel.** There is no context file to write an `@.ddw/orchestrator.md` import
  into, so its stdout is the one thing that puts the orchestrator in front of the
  model. It passes `--method` for that reason: a nudge naming a relative `.ddw/`
  points at a file that is not there.
- **Nothing is written until a pipeline exists.** A plugin at user scope loads in
  every repository you open, including one cloned to read for five minutes.
  `session-boot.py` materialises the state and the gitignore block only when the
  repo is a drop-in or already has a `.ddw-state.json`. Otherwise it reports and
  writes nothing.

`/ddw-eject` copies the method into the repo when you want to edit it, after
which the repo's copy is the one that runs — see the skill for the trade.

## Activation flow (drop-in, Claude adapter)

```
1. bash install.sh <repo> --target claude   ← copies ddw/ → .ddw/, adapters/claude/ → .claude/,
                                              wires the hooks, adds the import to CLAUDE.md
2. Open Claude Code in the repo             ← CLAUDE.md imports @AGENTS.md and @.ddw/orchestrator.md
3. The orchestrator enters the context      ← no approval gate (it is an internal import)
4. The state machine boots                  ← reads .ddw-state.json, applies the phase router,
                                              emits the status line (IDLE if there is no state)
```

`--target` also accepts `codex`, `copilot`, `cursor`, `gemini`, `opencode`, several separated by
commas, or `all`. Omit it and the installer asks.

The installer is idempotent and records what it wrote in `.ddw-installed.json`. That record is what
lets it tell its own older copy of a file (→ upgrade it on the next run) from a file you have made
yours (→ leave it alone and report it). Without it, every difference read as "the user's", and a DDW
update quietly left the repo running a mix of two versions.

## The orchestrator

`.ddw/orchestrator.md` is a strict state machine. Its boot sequence (silent, every turn):

1. Read `.ddw-state.json`. If it does not exist → assume `phase: IDLE`.
2. Load `.ddw/rules/state.instructions.md` (the state schema).
3. Find the "Router: Phase `{phase}`" section and load **only** the files listed there.

Every file reference uses repo-relative paths (`.ddw/...`), which the model resolves with the Read
tool from the project root.

## Pipeline state

`.ddw-state.json` (per-repo, gitignored). `.ddw/scripts/session-boot.py` materializes it — at
session start, and again before the first write — and keeps the runtime files out of git. Schema in `.ddw/rules/state.instructions.md`. Transitions are **append-only**
over `history` and atomic (phase + gate + history entry in a single `Write`).

The `.ddw/scripts/transition.py` helper builds the next state's JSON for a transition and
self-validates it with the same `validate()` the hook uses before emitting it. It is read-only: the
actual write is done by the model with `Write`.

## Hooks

Wired in `.claude/settings.json` with `${CLAUDE_PROJECT_DIR}/.claude/hooks/...` paths.

| Hook | Event | Description |
|---|---|---|
| `session-start.sh` | `SessionStart` | Nudges the model to run the boot sequence. Defense in depth over the `CLAUDE.md` import. |
| `enforce.sh` | `PreToolUse` (Edit/Write/NotebookEdit) | Housekeeping via `session-boot.py --quiet`: materializes the state, keeps `.gitignore` current, refreshes this session's marker. |
| `validate-state-transition.sh` | `PreToolUse` (Edit/Write/NotebookEdit) | Validates that every write to the state is a legal FSM transition (per-tier graph + gates + append-only). `exit 2` blocks. |
| `validate-state-postwrite.sh` | `PostToolUse` (Bash/Edit/Write/NotebookEdit) | Safety net: revalidates the state ON DISK after any tool (including Bash/jq, which PreToolUse cannot see). |
| `pre-compact.sh` | `PreCompact` | Reminds the model to re-run the boot sequence after compaction. |

### One nudge, six event names

Compaction throws away the middle of the conversation, and what it throws away is
what the boot sequence read: the phase router and the state. The model keeps
answering from a summary of the pipeline rather than the pipeline, which is the
one thing the orchestrator forbids inferring. Every one of the six tools compacts
and every one of them calls it something else:

| Tool | Event | Channel |
|---|---|---|
| Claude Code | `PreCompact` | stdout (the runtime rejects a JSON verdict here) |
| Codex CLI | `PreCompact` | `hookSpecificOutput.additionalContext` |
| Cursor | `preCompact` | `additional_context` |
| Gemini CLI | `PreCompress` | `hookSpecificOutput.additionalContext` |
| Copilot CLI | `preCompact` | `additionalContext` |
| OpenCode | `session.compacted` | the next user message's prefix — its plugin's stdout reaches the terminal, not the model |

The reminder itself is the method's, so it lives once in `session-boot.py
--compact`; the adapter supplies `--event` and `--format` and nothing else. All
six events are **advisory** — none of them can block, Claude's included — so this
is a nudge, not a gate, and it is documented as one.

### One gate, six dialects

Every adapter — Claude Code, Codex CLI, Copilot CLI, Cursor, Gemini CLI, OpenCode — calls the same
entry point, `.ddw/scripts/hook-gate.py`. It parses that tool's event shape, asks
`validate-transition.py` the one question worth asking, and answers in that tool's refusal dialect
(exit 2 everywhere; a JSON verdict as well, where the harness reads one).

The QUICK-FIX ceiling — sensitive paths, and ten added lines over the branch's base — is decided
there too, in `quickfix_scope_denied`. It was a Claude-only hook once, which meant the tier's budget
held for one tool and for nobody else: the same ticket was refused or waved through depending on
which agent was open. The tier is a field in the state and the limit is a line in the rules, so it
is the method's decision, and an adapter that decides it is a second copy of the method.

An adapter that carries its own copy of that glue can get it wrong in a way nothing notices: it
consumed the event before the validator could read it, so the validator saw an empty envelope,
exited 0, and every illegal write went through. Both tools looked installed and enforced nothing.
Hence the rule: **an adapter contains no logic, only the two facts that are true of its tool** —
where the repo root comes from, and how that harness spells "no".

### Shared guard (`hooks/lib/guard.sh`)

`ddw_guard`: exits 0 (silently) if `CLAUDE_PROJECT_DIR` is unset or the directory is not a git repo.
There is no master switch: in drop-in mode DDW is active by virtue of its hooks being wired in
`settings.json`.

### FSM validator (`.ddw/scripts/validate-transition.py`)

Two modes over the same graph and the same `validate()`:

- `--mode pre` (PreToolUse): reconstructs the text the tool is about to write and validates
  disk→new **before** the write lands.
- `--mode post` (PostToolUse): revalidates the state's current run on disk as a complete chain from
  IDLE — tool-agnostic and path-agnostic, covering the Bash bypass. It checks the **path** for the
  whole run and the **gates on the last edge only**: all it has is a snapshot, and gates
  legitimately disappear along the way (the corrective loop `VERIFY → CODE` clears `tests` and
  `sast` on purpose). Replaying an earlier edge against today's gates would not re-check history, it
  would invent a verdict, and reject the pipeline's own recovery path as illegal.

`exit 0` allows, `exit 2` blocks with the reason on stderr.

### Gate evidence

`validate()` asks whether a gate is **claimed**, which is a question about the state and nothing
else — that is what keeps it a pure function the suite can drive with synthetic runs. Whether
anything outside the model **backs** the claim is a different question, it needs the repository, and
it lives in `GATE_EVIDENCE` next to `decide_pre`/`decide_post`.

Two gates have an entry. `define` wants a receipt naming the PRD's current bytes; `commit` asks git
whether tracked changes are still in the working tree. Both run on the write that makes the claim —
not on every later write, or editing a PRD two phases on would brick the session — and on both
paths: pre-write for the write tools, and in post mode for the edge the journal has not recorded
yet, which is how a `jq`/`sed` write is caught.

`transition.py` calls the same function rather than carrying its own copy. It used to hold the only
one, which is precisely how the hook came to allow what the helper refused.

Which gates get an entry and which stay self-declared is
[decision 16](RATIONALE.md#16-a-gate-is-an-attestation-and-they-are-not-all-the-same-strength), not
a to-do list.

## One write, one transition

The pre-write mode caps a single write at **one** appended history entry. Without the cap, one
`Write` could append the whole pipeline — IDLE through RELEASE, every gate asserted at the end — and
pass: no gate is missing, and the sequencing that is the entire point of a state machine evaporates.

## Agents

| Agent | Role |
|---|---|
| `ddw-implementer` | Implements ONE block of the spec in an isolated context (CODE phase) |
| `ddw-impact-scanner` | Runs the 5 impact checks over the codebase (PLAN phase) |
| `ddw-arch-auditor` | Architecture auditor (PLAN and CODE phases) |
| `ddw-sec-auditor` | Security auditor (CODE and VERIFY phases) |
| `ddw-module-verifier` | Module verifier (VERIFY phase) |

They are spawned with the `Agent` tool (`subagent_type="<name>"`) and never read as files. They live
in `.claude/agents/`.

The division of labor is deliberate: `ddw-implementer` writes; the other four never do. Reviewing is
worth something only when the reviewer is not the author.

## Rules

Per-phase instructions in `.ddw/rules/`. The orchestrator loads them dynamically based on the
current phase. The transition graph lives in `transition-graph.json`.

## Language

The method's files are written in English, but they are **prompts**, not documentation. The
`AGENTS.template.md` that installs into the project carries the directive that the agent answers —
and writes every artifact — in the language the user writes in. A project can pin a fixed working
language in its own `AGENTS.md`, and that wins.

This means translating `ddw/` is not required to work in another language. Do not hardcode a
language into the rules.

## How to add a new tier

A tier is **declarative**: the FSM validator indexes by tier generically (`_effective_edges` merges
`common` + `tiers[<tier>]`), so you do not touch the `.py`. Adding a tier means editing:

1. `rules/transition-graph.json` — an entry under `tiers` with its edges and gates.
2. `rules/classify.instructions.md` — the detection heuristic and the tier→phase mapping.
3. `ddw/orchestrator.md` — emoji + status-line example + router section.
4. `rules/validation-rules.instructions.md` — the rules' conditionality for that tier.
5. The skill producing the DEFINE artifact (`skills/ddw-create-prd`), if it uses an artifact other
   than the PRD.

**Three ways to reach IDLE.** A **closeout** ships the work and owes the edge's gates —
`RELEASE → IDLE` requires `commit` and `pr`, so a ticket cannot be marked done without them.
**Abandoning** and **pausing** owe nothing, because the work is not going to ship, but they must be
declared: the history entry's `action` starts with `abandon` or `pause` (matched on the first word —
an unanchored prefix once made "abandonware cleanup" a valid exit).

Walking away is allowed from anywhere except the phases the graph lists under `no_walkaway`, which
today is `RELEASE`: at that point nothing is left to decide, only steps to finish. Without that
rule the word `abandon` is a skeleton key — relabel the exit and ship with no commit and no PR.

Since closing resets `tier` and `gates`, the validator evaluates those edges against the state as it
was *before* the reset. That fallback is narrow on purpose — it applies only when the destination is
IDLE, so a gate cleared by a corrective loop can never count as still met. The reset itself is
**enforced**: reaching IDLE with a non-null `tier` or a non-empty `gates` is refused, because
otherwise the next ticket inherits gates this one paid for and can walk the whole pipeline having
earned nothing.

**`extends`.** A tier whose pipeline has the same shape as another declares
`"FIX": {"extends": "FEATURE"}` instead of repeating its edges. `_effective_edges` resolves the
chain (with a cycle guard) and a tier's own edges override what it inherits.

---

## How this repo is kept honest

DDW is mostly prompts, and prompts do not crash. A rule that cites a gate which
no longer exists, a router that contradicts the phase it routes, an adapter
written against an envelope its tool does not send — none of these throw. The
model simply reads the wrong instruction and does the wrong thing, and every
test stays green because there is nothing to execute.

That is not a reason to test less. It is a reason to be specific about what each
layer can catch, because each of these was added the day something got through.

### 1. `scripts/verify_install.sh` — behaviour, through the real entry points

Installs DDW into throwaway repos and drives **the hooks each tool actually
runs**, with that tool's own envelope shape. The distinction is the whole point:
for a long time this suite called the validator as a Python library, so it was
green while two adapters consumed the event before the validator could read it
and enforced nothing at all.

The rules it works by:

- **A missing dependency is a failure, not a skip.** A skip prints as a green ✓
  and lowers the total, and nobody can eyeball a total they never memorised.
- **The total is pinned** (`EXPECT_CHECKS`), and the last check settles the
  account. Several environment conditions can otherwise delete checks in
  silence.
- **Counts of the payload are pinned too.** Counting the source and comparing it
  to itself can never notice a deleted skill.
- **Drive the entry point, not the library.** If production calls it, the test
  calls it the same way, with the same arguments.

### 2. `scripts/lint_method.py` — the prose against the data

The graph, the rule catalog and the filesystem are the three places that hold
truth. This fails on any claim the prose makes that they do not support: a
`gates.X` no edge requires, a rule ID that is not in the catalog, a skill or
agent that does not exist, an artifact path outside `docs/ddw/`, a stated count
that does not match what is on disk.

It is cheap and it covers a class nothing else can. A renamed gate outlives its
rename in prose, and a deleted control outlives its deletion, because neither
breaks anything loudly enough for a test to hear.

### 3. `scripts/mutate.py` — the meter

**Break the code on purpose, one fault at a time, and check that something goes
red.** A suite that always passes and a suite that cannot fail look identical
from outside; this is the only way to tell them apart.

Every mutation in the list is a defect that actually shipped, or one of its
family. The output is a number, and that number is the project's real coverage:

    python3 scripts/mutate.py

A first run of this meter lands far below 100%, and every survivor is a check
that does not exist yet. That is the point of running it: the number is the only
honest answer to "are we covered", and it is usually worse than it feels.

Two traps worth knowing about, because both produced a figure that was wrong in
the flattering direction:

- **A stale `EXPECT_CHECKS` makes everything look caught.** If the pinned total
  is out of date, every run fails on that check alone, so every mutation reads
  as killed. Re-pin the total before trusting a score.
- **A mutation can be refused for the wrong reason.** Replacing `realpath` with
  `abspath` survived because the test path was rejected by the source guard
  before path resolution mattered at all. A check has to fail for ONE reason,
  and the fixture has to be built so that reason is the only one available.

And one honest exception to "never shrink a mutation": an **equivalent mutant**
— one that provably cannot change behaviour — is not a hole. `max_appended`'s
default is unreachable because both callers pass it explicitly, so mutating the
default proved nothing. That one was re-aimed at the call site, not deleted.

**When a mutation survives, the fix is a new check.** Never a smaller mutation
list, and never a narrower mutation. The list only grows: each bug that gets
past everything else earns its entry, so it can never come back unnoticed.

### 4. `check_versions.py` and `check_commits.py` — the claims outside the method

Two narrow checkers for two things that rot without breaking anything. The first
reads the version and the licence from the files that own them and compares every
copy — a manifest saying `UNLICENSED` next to an Apache-2.0 `LICENSE` is what npm
reads, and no test notices. The second holds a **range** of commits to
`commits.instructions.md`: `AI-assisted:` or `AI-full:` where a model helped, and
never `Co-Authored-By`, which credits the tool as an author and spreads
responsibility onto something that cannot hold it. Only a range, never the
history behind it — that cannot be rewritten without breaking every clone.

CI runs both on pull requests, which is where the range exists.

### 5. CI — on two operating systems

`.github/workflows/verify.yml`, on every push. The second OS is not ceremony: a
`find` without `-printf` deleted 41% of the checks on macOS and exited 0.

### What still cannot be automated

Driving each of the six tools for real. The suite proves an adapter refuses the
right event and lets the right one through; it cannot prove the tool sends that
event in the first place. That gap closes by hand, once, before publishing — see
the acceptance ritual — and it is the honest reason the README calls the tools
nobody has driven *verified at the boundary, unverified in the wild*. Which tools
those are is the record's answer, not this file's: `scripts/acceptance.md` holds
it, and a check compares the README's sentence to the table so that neither can
drift ahead of the other.
