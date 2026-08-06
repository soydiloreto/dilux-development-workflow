# Changelog

All notable changes to DDW are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## What semantic versioning covers here

DDW is a method plus the wiring that plugs it into a coding agent, and those two
move at different speeds. So the promise is specific:

- **Covered.** The method itself: the phases, the transition graph's format, the
  gate names, the artifact layout under `docs/ddw/`, the state schema, and the
  adapter recipe schema. A breaking change to any of these is a major version.
- **Not covered.** The wiring for each individual tool. When Claude Code, Codex,
  Copilot, Cursor, Gemini or OpenCode changes its hook contract, that adapter
  follows it — in a patch release if it can, immediately either way. Tracking
  someone else's product is not a promise DDW can make on a version number.

---

## [0.19.0] — Unreleased

The round that went looking in the places nobody had looked: the agents, the
skills nobody validates, and the price of the measurement itself.

### Fixed

- **`/ddw-eject` told the model to do what the hook refuses.** The skill copies
  the method out of the plugin and into `.ddw/`, and every write to `.ddw/` is
  refused in every phase — the seal that stops a pipeline editing the rules that
  stop it, which cannot tell installing the method apart from disarming it. The
  model did exactly what it was told, mid-ticket, with the panel already shown.
  Ejecting is now what installing and uninstalling already are: a command the
  user runs (`install.sh --method-only`), which lands the method, records it in
  the manifest — an ejected method nothing records is invisible to the drift
  check, and it is the one people go on to edit — and touches no wiring.
- **The agents' tool lists were nobody's business.** Four of the five exist to
  look and report, each spawned to judge something a gate will rest on, and the
  only thing keeping them from editing what they judge is one line of
  frontmatter that nothing read.

### Changed

- **The mutation run stops paying a full pass per fault.** `mutate.py` asks
  whether the suite went red; `DDW_STOP_ON_FIRST_FAILURE` lets it stop there.
  Read from `bad` and nowhere else, and it exits 1 — no value of it turns a red
  run green. The baseline run does not use it, because that one has to be able
  to say "the suite passes", which is a statement about every check.
- **A pull request runs the faults its diff can speak to.** `--changed BASE`
  selects the mutations whose file the diff touches — five of four hundred for a
  change to one validator — and everything when the diff touches the suite or
  the runner. The shards keep their names, so the required checks do not move;
  `main` and the weekly schedule run the list whole, and that run is the
  coverage figure.

### Added

- **`install.sh --method-only`** — the method, recorded, without the wiring.

---

## [0.18.0] — Unreleased

A pre-merge audit: twelve specialists, each given a subsystem and told to run it
rather than read it, each followed by a skeptic told to refute what it found. 45
defects survived that. The three worst were not in the pipeline's logic — they
were in the pipeline's belief that it was enforcing anything.

### Fixed

- **In CODE, the agent could rewrite the rules that stop it.** The guard against
  writing DDW's own files lived inside the phase rule, and that rule returns
  early for CODE and CLOSEOUT — so it covered exactly the phases where nothing
  can be written anyway and stood down in the one where the work happens.
  Measured end to end on a real install: rewrite `transition-graph.json` to add
  an edge, rewrite `validate-transition.py`, replace the tool's hook with
  `exit 0`, or simply `Write` a receipt into `.ddw-sessions/` and open six gates
  with a touch — and close a FEATURE that never claimed `tests`, `sast`,
  `verify`, `commit` or `pr`, with both hooks green. The method, the receipts,
  the journal, the manifest and each tool's wiring are now unwritable in **every**
  phase, and `.ddw-state.json`, `.ddw-paused/` and `docs/` stay writable.
- **A whole FEATURE could reach CLOSEOUT with no artifacts at all.** No PRD, no
  spec, no threat model, no test report, no SAST report, no verdict — six gates
  true, nothing on disk. `_receipt_missing` returned "nothing to check" when the
  document was absent, and that sentence is false at every call site: the
  function is reached only for a gate being **claimed**. A missing document is a
  refusal now, and so is one that cannot be read as UTF-8.
- **A receipt could be written by hand.** The tool path is closed above; a shell
  is not (decision 11). So the six validators now record, in the append-only
  journal, that they wrote each receipt — and the gate asks for both. Forging
  takes two coordinated writes instead of one, and the second one lands in a
  record that outlives deleting the state.
- **The install manifest named files that were not there** — 22 of 28 entries
  used the source layout instead of the repo's, and nothing at runtime had ever
  read it back. It is repo-relative now, which is what makes the two fixes above
  precise, and what lets the session boot report an install whose enforcement no
  longer matches what was installed.
- **`transition.py --write` overwrote a corrupt state with a fresh IDLE**,
  destroying the history — in precisely the situation the orchestrator says to
  stop and report. It reads the state the way the hook does now, and refuses
  where the hook refuses.
- **Installing a second tool destroyed that tool's pre-existing hooks.** The
  upgrade test asked the whole manifest instead of this tool's part of it, so a
  target that had never been installed was treated as an upgrade, and files DDW
  never wrote were replaced with no backup, no warning and exit 0.
- **The sanctioned helper could not close a ticket in any tier.** `CLOSEOUT→IDLE`
  wants `commit` and `pr`; reaching IDLE wipes the gates, so `--gate` there was
  silently discarded and the refusal blamed a missing `--tier`, a flag that edge
  ignores. `transition.py --claim <gate>` earns a gate in the phase that owns it,
  and the refusal now says so.
- **A skip counted as a pass.** Two plugin manifests had therefore never been
  validated against the real schema in CI. Skips are counted apart, a run with
  one does not go green, and CI installs the CLI those checks need.
- **CI's steps could be deleted while every required check stayed green** — the
  required contexts are job names, not the steps inside them. The suite now
  asserts the content of both workflows, and the release workflow, which nothing
  had ever checked existed.
- **`F-PRD-03` was structurally incapable of failing.** It asked whether a
  non-functional requirement contained a number, and read the whole bullet —
  `NFR-01` contains digits. It printed a green row on every run since it was
  written; "the load should be fast" passed as a measured requirement.
- **`/ddw-self-check` reported two inconsistencies on every correct install of
  all six tools** — one `grep` handed three filenames exits 2 for the missing
  operand even after a match, and one `ls` over six globs fails when any is
  empty, which five of six always are. A diagnostic that cries wolf on a healthy
  repo is what people learn to ignore before the real one.
- **Uninstall left every generated slash command behind** (most of an OpenCode
  install), deleted the manifest its own `--force` advice needs, and left behind
  an empty `.gitignore` the installer had created.
- Eight catalogued rules across four validators had never been exercised by a
  document that violates them; the linter never read `skills/` or `agents/` — the
  two directories that name skills and agents most; four SAST rule IDs shown to
  users were in no catalog; the loop counters, the QUICK-FIX way back from
  CLOSEOUT, the pause-vs-prefix match and the tier chain's direction had no
  mutation. Plus eleven documentation claims that were false about the code.

#### Round two: the ticket that closes without answering the question

- **The closing edge asked for nothing, in all three places that judge it.**
  `transition.py` asked `gate_evidence_missing` only about the gates named in
  `--gate`, and `--gate` is refused on `--to IDLE` — so the sanctioned helper,
  the path the method tells the model to take, asked nothing exactly where the
  evidence matters, and closed a ticket over uncommitted work with exit 0. Post
  mode had the mirror of it: `scope == "none"` gated the evidence arm too, so a
  forged run refused at CLOSEOUT was blessed in full by one more write to IDLE.
- **Two runs of the helper in one turn lost an edge.** Read and write were not
  one critical section: both read the same phase, both validated, both wrote,
  and the second `os.replace` dropped the first one's transition while both
  exited 0. A write now refuses to land over a state that moved under it.
- **The uninstaller deleted the repository.** `claude:.` in a committed manifest
  resolves to the repo itself, passed a containment check written as "is it
  inside?", and reached `shutil.rmtree` — working tree, `.git`, and every file
  the user had ever written. A mutation for the traversal case existed and
  killed nothing, because no check ever drove it.
- **A journal line written twice slid the index** that finds what just landed,
  so post mode owed evidence for nothing; and deleting the journal outright
  turned the receipt-witness check off, so a hand-written receipt opened its
  gate again in one command.
- **`pid-$$` is not a session.** The pre-write hook runs on every edit and
  identified itself by its own shell, so a repo with one person in it grew one
  live session per write and then warned about twelve of them.

#### An entry point that answers with a stack

- **The installer assumed the shape of your settings file.** A `hooks` that is
  null, a string, a top-level array, or a `PreToolUse` that is a mapping where
  the tool's own schema says list — each reached `cur.append(blk)` and came out
  an `AttributeError`, with `.claude/` and `.ddw/` already on disk, no manifest
  and no hooks wired: a repo that looks installed, is not, and whose drift
  detector is off for good. Same for a context file that is not UTF-8, which is
  what a Spanish `AGENTS.md` saved as cp1252 is.
- **The uninstaller was worse in one case**: `PreToolUse: "oops"` was iterated as
  a sequence, so the file came back rewritten one character per list element,
  exit 0, "Done." A tool that corrupts what it was asked to clean and reports
  success is worse than one that refuses.
- **Four validators read their companion document through a bare `except
  OSError`**, so the everyday case of a PRD in the wrong encoding exited 1 with
  a stack; the method linter took the whole run down on one rule file saved the
  same way.
- **A worktree is a repository whose `.git` is a file.** The root walk asked
  whether it was a directory, so the layout the boot itself recommends could not
  resolve a root at all, and a worktree nested in another checkout resolved to
  the enclosing one — the ticket's state landing beside somebody else's work.
- **`--check-anchors` now compiles what each mutation would produce.** A
  mutation that leaves the file unparseable measures the file not compiling:
  every check dies on the import and the run records a kill. One had shipped and
  lived through two audits.

#### The document a phase is told to write has to pass the gate it is written for

- **Three plausible renderings of a complete test run were refused for their
  layout** — a coverage table whose rows are labelled `Line`, a lint result under
  its own heading, a failure named by test rather than by `path::test`, and
  `sad-path` with the hyphen English actually uses. Each read to the user as
  "your report is incomplete" about a report that was not.
- **Neither the test report nor the verification verdict had a canonical shape
  anywhere**, so there was nothing to copy and every draft was a guess. Both
  skills now carry the document, and the suite extracts each one and runs it
  through the validator that reads it.
- **The three refusals a real run hits most named the fact and not the move.**
  "gate 'spec' required for X is not true" says what is wrong and nothing about
  what to do, and what the model does next is edit the state by hand — which the
  hook then refuses just as finally.

#### Round three: the instrument, and the gates that opened on the wrong evidence

- **The mutation figure was arithmetic over a run that never happened.** The CI
  job never installed the Claude CLI; the suite's preflight calls `bad()` for a
  missing tool; the runner reads any non-zero exit as "the fault was caught". So
  every shard reported every mutation killed without examining one, and printed
  100%. The same shape arrived locally through `commit.gpgsign` — the one
  fixture that commits without disabling signing could not commit at all on a
  contributor's machine, and three checks blamed the commit gate for a tree that
  was never committed. The runner now asks an **unmutated** copy first and
  refuses to inject anything into a suite that cannot pass, saying which of the
  two it was; both CI jobs install the CLI; and every workflow job that runs the
  suite is held to the preflight's own tool list.
- **`--tier` decided which rules ran and nothing recorded which one was asked
  for.** The same PRD failed as a FEATURE and passed as a QUICK-FIX, and the
  receipt — named by a digest of the content alone — came out byte-identical
  either way, so the gate had nothing to compare against. Receipts record the
  tier they were earned under, the gate refuses one that is not the ticket's,
  and `--tier` accepts only the tiers the graph defines. Receipts written before
  this carry no tier line and are still honoured.
- **`mkdir .ddw` turned every Claude hook off.** The method was chosen by the
  directory being there rather than the gate being there, so an empty folder won
  the lookup and each hook bowed out at its `[ -f "$DDW/scripts/hook-gate.py" ]
  || exit 0` — two lines below a python3 branch that deliberately fails closed.
  Under a plugin install the fallback it skipped is the only copy of the method
  there is. One command, no privileges, no content, and a write refused with
  exit 2 was allowed with exit 0.
- **Under a plugin install the method was writable from inside a ticket.** Every
  guard on DDW's own files asked "is this under the repo root?", and a plugin
  root is not — so writes to the plugin's graph, gate and validator all returned
  0 while `src/app.ts` in the same event returned 2. With `"PLAN->CLOSEOUT":
  {"gates": []}` injected into that graph, a FEATURE reached CLOSEOUT with no
  spec, threat, tests, sast or verify — and the plugin root is shared, so one
  write disarms DDW in **every** repository using it. The hooks now hand the gate
  the method root they already resolve, and it is judged before the guard that
  bows out for paths outside the repo.
- **`.ddw/` was not in the install manifest.** A clean install recorded 28
  entries and none of them under the method, so the drift check — the detection
  half of "prevention where a path is visible, detection where it is not" —
  could not see a shell rewriting `transition-graph.json`, `hook-gate.py` or
  `validate-transition.py`. Three separate comments in the code named exactly
  that vector as the one the manifest covers. The method tree is fingerprinted
  file by file now, and the drift check drives those three by name rather than
  whichever entry sorts first.
- **`rm .ddw-installed.json` unsealed every hook script and silenced the drift
  report for good.** The hook scripts were protected by the manifest alone, and
  a manifest that cannot be read returned an empty set; a missing one was read
  as "plugin mode, or never installed", which are the two cases that have no
  `.ddw/` in the repository. Each adapter's hook destination is sealed by name
  now, and a repo that plainly has `.ddw/` in it reports a missing manifest as
  loudly as a changed file.
- **A state truncated to zero bytes read as a fresh IDLE.** Not absent, so the
  deletion net did not fire; not garbage, so the parse guard did not either —
  and a blank state is a fresh install's ordinary state. `: > .ddw-state.json`
  therefore put the repository at IDLE with no ticket and no history, and the
  write to product source that DEFINE had just refused went through. An empty
  state with transitions in the journal is now the erasure it is; an empty one
  with nothing recorded is still the run that has not started.
- **A gate could be claimed from any phase.** `--claim` checked that the name is
  a known gate and that its evidence exists, and never read the phase; a raw
  write that appends no history returned early in the validator, so nothing
  covered that path either. Under QUICK-FIX the closing edge costs `define`,
  `tests` and `sast` — three booleans that could all be set while sitting in
  DEFINE, before a line of the fix existed. The owning phases are derived from
  the graph: an edge `A->B` asking for `g` is the statement that `g` is what
  leaving A costs.
- **The corrective loop cost nothing.** `clears` was a boolean operation and
  nothing outlived the write that performed it. For `define`, `spec`, `threat`
  and `verify` that is enough — the artifact IS what changed, so its hash moves.
  For `tests` and `sast` it is not: the artifact is a report ABOUT code that is
  about to change, and its bytes are identical after the fix, so VERIFY→CODE and
  back re-presented the same receipts. The journal now records a gate as spent
  when a loop clears it, and a receipt written before that no longer opens it.
- **A write could drop `tier` to null**, and the next write then set any tier it
  liked: FEATURE → null → QUICK-FIX, two writes, both exit 0, neither saying
  anything, and the ticket walks a graph with no PLAN and no VERIFY. Null reads
  as "unchanged" everywhere it is consulted, exactly like the `""` and `0` the
  check already refused — it just arrives as the value a caller may legitimately
  send.
- **`❌` was unmatchable in the document it was designed for.** It is not a word
  character, so inside a `\b(...)\b` group it demanded one on both sides, and
  every shape the verify skill teaches (`- AC-01 ❌`, `| AC-01 | ❌ |`) has a space
  or a pipe there. A verdict marking every criterion failed read as "all AC carry
  a passing verdict" and wrote its receipt.
- **A verdict could be checked against documents that were not the ticket's.**
  `--prd` and `--spec` are chosen by whoever runs the validator; pointing both at
  a file with no criteria and no blocks printed "all 0 AC", "all 0 spec
  block(s)", "all 0 test(s)" and PASSED — three green rules whose subject was
  empty. Zero criteria is now a refusal, and the documents have to name the
  ticket the report does.
- **A `.ddw` symlinked out of the repository was not sealed.** Paths are resolved
  through symlinks before being judged, which is what stops a guarded file being
  written under an unguarded name — but the sealed lists are about names, so
  resolving first answers a different question. Both readings are judged now.
  (`.ddw-sessions/` and `.ddw-installed.json` were never affected, and
  `install.sh` never builds that topology.)
- **A refused edge to IDLE prescribed a claim that changes nothing.** The hint
  "run `--claim commit --claim pr` first" was pasted onto every refusal on the
  way to IDLE, including the ones where no such edge exists: from CODE both
  claims exit 0 and the retry prints the same sentence word for word. A fixed
  point, and the only conclusion left to the reader is that the tool is broken.
  The hint comes from the graph now — the gates where the edge asks for them,
  and which phase closes a ticket where it does not.
- **Out of IDLE, a paused ticket was told to reclassify.** The refusal said the
  only transition from IDLE is `--to CLASSIFY`, and the suite's own happy path is
  a counterexample: a paused ticket re-enters the phase it was paused in, and
  that edge exits 0 on the same state. Following the hint means abandoning a
  ticket that was one flag away from continuing — the advice the pause was added
  to make unnecessary.
- **The fix-plan template could not pass the gate it is written for.** A plan
  written exactly as `ddw-create-spec` teaches was refused by F-SPEC-10 for its
  layout: the template puts error handling in prose, and the validator counts
  errors as a list, because F-SPEC-16 pairs each one with the test that names it.
  The skill carries a worked fix-plan now, and the suite runs it through
  `validate_spec.py --tier FIX` — the same guard the PRD, the test report and the
  verdict already had.
- **The SAST receipt recorded no clock.** `--today` decides which suppressions
  have expired and the caller chooses it, so a report whose reviews lapsed months
  ago passed by naming a day they were still fresh, and left a receipt
  byte-identical to one earned this morning. The receipt records the day, and the
  gate refuses one earned against another.
- **A session's liveness marker expired under five of the six tools.** Only the
  Claude adapter had a second PreToolUse shim to refresh it; everywhere else the
  marker was written at session start and swept two hours later, so the
  concurrency warning went quiet for exactly the sessions worth warning about.
  The write gate every tool runs refreshes it now.
- **The catalog's own summary counted rules it does not contain** — 69 FAIL and
  84 in total where the tables define 65 and 80, with `ddw/rules/README.md`
  repeating the 84. Rules were merged and removed over three rounds and nobody
  recounted; the linter recounts now, per area and in total.
- **`code.instructions.md` asked for `F-TEST-01` to `F-TEST-06`** with 07 and 08
  implemented, and `check_rule_ranges` could never see it: the pattern demanded
  whitespace straight after `-01`, and every rule ID in this method's prose is
  written in backticks. It ran green for months over ranges that were all correct
  while blind to the single stale one — and it read the rule files without
  reading the skills that run them.
- **Three of the instrument's own.** The check that every validator prints its
  demand guarded itself with `assert cases` over a list literal three lines
  above: every fixture could be missing and it passed having asked nothing. Two
  entries in the mutation list injected the same edit — one fault counted twice,
  in a list that IS the coverage figure. And the empty shard the suite drives was
  typed as `400/400` when the list held 393, so the day it passed four hundred
  that check ran a real mutation, which ran the suite, which reached the same
  line again: a recursion that forks until the machine gives up. All three are
  derived from the tree now instead of typed.

### Added

- **`transition.py --claim <gate>`** — marking a gate in the phase that earns it,
  with the same evidence the hook demands and no history entry.
- **Enforcement-drift reporting at session start**: every file the installer
  recorded, hashed against the manifest, so a change made through a shell is
  told to the next session instead of never being noticed.
- **A baseline run in `scripts/mutate.py`**, and argument validation ahead of it:
  the runner asks whether the suite passes on an unmutated copy before injecting
  anything, so a red suite is a refusal rather than a fabricated 100%.
- **The tier on every receipt**, in the file and in the journal, so a gate can
  ask which rules earned the evidence it is being handed.
- **A `spent` record in the journal** when a corrective loop clears a gate, which
  is what makes re-earning `tests` and `sast` cost a real re-run.
- **The clock on the SAST receipt**, alongside the tier, so the gate can ask
  which day the suppressions were aged against.
- 101 checks and 144 mutations over the four rounds: **532 checks, 404
  mutations**. Among them, one check per skill's load-bearing claim — ten of the
  seventeen could have their entire body replaced with "TODO." and the suite
  stayed green.

---

## [0.17.0] — Unreleased

Everything 0.15.0 added, audited by driving it instead of reading it. Four of the
holes below made the release's own headline feature unusable; the rest were ways
around gates that no check had a shape for.

### Fixed

- **Choosing an autonomy mode bricked the session.** Post mode replays the whole
  run as one batch against a synthetic IDLE prior, and the autonomy check asked
  whether `appended[0]` came from CLASSIFY — which, in that batch, it never does.
  So every ticket that picked a mode and walked past DEFINE was refused by the
  post hook, on every tool call, forever. The field the feature exists for made
  the pipeline unusable and nothing drove it end to end. Any edge touching
  CLASSIFY now satisfies it; on the pre path, where a write carries one edge,
  that is the same question it always asked.
- **Pausing worked only if you never worked on anything else.** `_paused_at`
  read the entry immediately before the resume, assuming the pause was the last
  thing that ever happened — the one thing a pause is for **not** being. Pause A,
  run B end to end, come back for A, and the resume was refused as having no
  paused ticket. It now searches backwards for the last **unresumed** pause, and
  pairs each resume already in the history with the pause it consumed, so one
  pause cannot be resumed twice. Another ticket's pause is not your way back in.
- **`ticket: null` opened all six receipt gates at once.** Every receipt resolves
  its document through the ticket, and "no document on disk" reads as "no claim
  to check" — so clearing one field, one `jq` away, satisfied `define`, `spec`,
  `threat`, `tests`, `sast` and `verify` together. A state claiming a receipt
  gate must now name the ticket it earned it for, and naming it is the way out.
- **A gate could be turned on without declaring a transition.** Post mode owed
  evidence only for the gates the landed **edges** declared, so `jq '.gates.tests
  = true'` — which appends no history entry — owed nothing; and the pre path did
  not catch it either, because by then the forged `true` was already the prior
  and nothing was newly claimed. The journal now carries a snapshot of the gates
  as post mode last blessed them, and what changed since it is asked for its
  evidence. It lives inside the journal so that removing it costs the transitions
  too — and a journal that comes back empty makes post mode stricter, not weaker.
- **The step back from CLOSEOUT kept the commit and the PR.** `CLOSEOUT→VERIFY`
  gave up `verify` and nothing else, so a ticket sent back by a reviewer walked
  forward again still holding `commit` and `pr` — the two gates that say the work
  shipped. It now gives up all three, and QUICK-FIX's `CLOSEOUT→CODE` gives up
  `tests`, `sast`, `commit` and `pr`.
- **The counter the ceiling reads was one no template wrote.** `Loops since last
  human decision` was in the rules, in the validators and in nothing that emits a
  document, so every PRD and spec fell back to the running total — the exact
  distinction 0.15.0 introduced, present everywhere except where it counts. Both
  templates emit it, the skills say when it resets, and a `since` above the total
  is refused: it counts a subset of the rounds the total counts, so it cannot be
  the larger of the two.
- **The pending-PR notice could take the session boot down with it.** A shape
  from `gh` that was not a list of objects crashed on `pr.get`, and the boot's
  phase line — the one line that has to survive — went with it. It also called
  the forge on quiet runs and in repos that had never run DDW, reported every
  failure as a timeout including the ones that were not, dropped the ninth and
  later pull requests in silence, and answered a broken `git` with the same
  silence as "you have no open PRs".
- **The helper could not name a ticket.** With `--write` there is no later Write
  to fill it in, so the sanctioned path produced exactly the state the rule above
  now refuses. `transition.py --ticket` sets it, and stamps it on the history
  entry — the closeout wipes the header's ticket, so an unstamped entry is
  unattributable from then on.

### Added

- **`transition.py --ticket <ID>`**, and the helper stamps the ticket on the
  history entry alongside the tier.
- **One check walks a whole ticket the way a user walks it** — classify, define,
  plan, code, pause, an unrelated ticket start to finish, resume, a corrective
  loop, closeout — through `transition.py --write` and then the post hook after
  every step. Three of the defects above were invisible to every check that
  drives a function or builds a state to reach it, and visible in the first
  minute of walking the thing. 9 checks and 33 mutations in total: 462 checks,
  258 mutations.

- **Eleven mutations that had been reported killed were not.** Three were
  regressions this release caused and hid: the new ticket rule refused the
  suite's negative fixtures *before* the rule under test could, so deleting
  append-only, deleting timestamp validation, or uncapping transitions-per-write
  left the suite green — a fixture refused for the wrong reason proves nothing.
  The other eight were checks that tested the function instead of the path: the
  pending-PR notice was driven directly and never through the boot, so deleting
  the line that calls it was invisible; QUICK-FIX's own way back from CLOSEOUT
  had no check at all; and the pause exception was never replayed by post mode,
  which is the one place it can brick a repo.

### Changed

- **Resuming a paused ticket asks which mode to come back in.** Reaching IDLE
  clears `autonomy`, so without a second moment to choose it the setting was
  lost across every pause, recoverable only by abandoning the ticket. Resuming
  is now the one other place it may be set, and the pause protocol makes the
  assistant put the previous value to the user before restoring anything. It
  needs a real, unresumed pause of that ticket, from the exact phase, out of
  IDLE — the first draft matched the word `resume:` on any edge, which granted
  the mode on an ordinary forward step; the check written alongside it caught
  that before it shipped. What the hook cannot see is whether the question was
  asked: that stop is the method's, like the loop ceiling, and it is checked as
  prose because that is what it is.

---

## [0.16.0] — Unreleased

### Changed — BREAKING

- **The `RELEASE` phase is now `CLOSEOUT`.** The phase does not release anything:
  it commits the artifacts, opens the pull request, updates the tracker and says
  where the branch lands. The release — the merge, the deploy — happens after,
  done by other people, possibly days later. The name promised the one thing the
  phase does not do, and the pause added in 0.15.0 made the gap plain: you can
  now sit there for two days having released nothing.

  The method was already using the right word for it everywhere else — *"an exit
  there is a closeout and owes its gates"* — so the phase and the act it performs
  had two names for one thing. Now they have one.

  **What breaks:** any `.ddw-state.json` carrying `phase: "RELEASE"`, and any
  history entry naming it. Done now, before 1.0.0, because this is the cheapest
  this rename will ever be: after publishing it is a migration and a broken
  promise instead of a correction.

  `ddw/rules/release.instructions.md` is `closeout.instructions.md`. The pipeline
  diagram is regenerated, and its footer stops claiming every arrow waits for
  you — under `minimal` it does not.

---

## [0.15.0] — Unreleased

A pull request waits for people. The pipeline could not.

### Added

- **Step back one phase, always** — `CLOSEOUT→VERIFY`, `CODE→PLAN` (and
  `CLOSEOUT→CODE`, `CODE→DEFINE` for QUICK-FIX) join the two that existed.
  Each backward edge declares in the graph what it **gives up**, and the
  validator refuses a backward write that still holds those gates. Four steps
  from CLOSEOUT to DEFINE, each one a history entry saying why.
- **Pause at CLOSEOUT**, once `commit` and `pr` are both paid for. An abandon
  there is still refused. Resuming gives both back false and asks again — days
  passed, and a gate already true is never re-asked.
- **The forge is asked what is waiting for you**, when the phase is IDLE and the
  repo has a remote. Deterministic: those two conditions → ask, every time;
  anything else → never. When it cannot look it says why — `gh` missing, not
  authenticated, no answer in five seconds — because an empty answer and an
  unanswerable question are different things.

### Fixed

- **The corrective loop laundered rewritten artifacts.** `PLAN→DEFINE` cleared
  nothing, so you could step back, rewrite the PRD, and step forward claiming
  `define` with no receipt asked for — evidence is owed only when a gate is
  claimed for the first time, and this one never stopped being true. The helper
  refused it; the hook did not. Reachable before this release.

### Changed

- **The loop ceiling counts two numbers.** `PRD loops` stays the running total
  and nobody resets it. The ceiling measures rounds since a human last decided
  something — a review comment is already the decision it exists to provoke.

---

## [0.14.2] — Unreleased

### Fixed

- **A rule that could be taken apart in halves without anything noticing.**
  `F-SAST-VERDICT` was written as two overlapping branches — "the result says
  PASSED" and "the result does not say BLOCKED" — which caught the same report,
  so disabling either left the other catching it and no mutation could tell the
  rule was half gone. CI found it: the mutation survived on the sharded run. One
  condition now.

---

## [0.14.1] — Unreleased

### Changed

- **The documentation described a product that had stopped existing.** Three
  statements were false about enforcement, and each was the first thing a reader
  reaches on its page: `docs/DEVELOPMENT.md` said two gates have an entry in the
  evidence table (all eight do, and it contradicted itself nine lines later);
  `docs/RATIONALE.md` decision 3 said only one gate is verified against anything
  outside the model's report; and the catalog told readers `ddw-test` has no
  rules in the catalog while carrying eight of them, in the same file.
- **The counts.** 84 rules, not 69. 17 skills, not 15. Five Claude hooks, not
  six. The catalog's own summary table was wrong in four cells and missing a row;
  it is computed from the rule tables now rather than maintained beside them.
- **The artifact table that calls itself the single definition of where every
  artifact lives** omitted both files under `docs/ddw/reports/` — the two that
  two gate receipts are named after.
- **`ddw-help` now answers what `/ddw-status` sends people there for**: what a
  gate rests on, and how much of the run waits for you.
- **`.github/INSTALL.md` claimed 4/4 for a run the record shows as three passes
  and one "detected, not prevented".** Two files in one repository giving
  different results for the same session.

---

## [0.14.0] — Unreleased

An adversarial review of the two newest validators, written against them rather
than about them: every hole below came with a report that slipped through.

### Fixed — reports that were not complete and passed anyway

- **A `⚠️` was a free pass out of every severity rule.** Only `❌` fed the
  location, verdict and suppression checks, so a hardcoded secret filed as a
  warning owed no file:line, no BLOCKED and no suppression. The cheapest bypass
  either script had, and the skill's own output box puts the three markers on one
  line. `F-SAST-SEVERITY` refuses it: the catalog fixes the severity per
  category, and a marker does not change it.
- **`BLOCKED` anywhere in the file defused the contradiction check.** The skill's
  template header (`— [PASSED | BLOCKED]`, copied verbatim) or a Spanish "no
  bloqueado" satisfied it, and the row then told the reader the contradiction had
  been checked. Both verdicts are read from the stated result line now, and a
  Critical above `Result: PASSED` fails.
- **Critical and High were suppressible.** §4.1 says they are not; nothing
  enforced it, so the seven fields were validated for a finding that has to be
  fixed. `F-SAST-SUPPRESS`.
- **A red test run earned the `tests` gate.** `ddw-test`'s own criterion is zero
  failing tests and the validator that writes the receipt never checked it:
  seven failures, named, arithmetic consistent, receipt written. `F-TEST-08`.
- **A per-suite report was read as its first suite.** A green unit suite above a
  red integration suite passed as one green run, with five failures on the page
  nobody counted. `F-TEST-07`.
- **`F-TEST-03` counted anything path-shaped anywhere** — the skip list and a
  coverage-by-file table both satisfied it. Scoped to a failures heading.
- **`F-TEST-06` cleared every skip with one word.** "For that reason the
  integration suite was not touched" excused seven silent skips. One reason per
  skip now.
- **The coverage floor was whatever the report said.** `0.8` read as 0.8% made
  every comparison vacuous; a report quoting 20% passed itself. Ratios are
  normalised and a floor under the pipeline's own minimum is a warning.
- **`1,204` tests parsed as 1.204** — a thousands separator read as a decimal
  comma, which passed silently whenever failed and skipped were zero.
- **A Medium was cleared by the word "fixed", including "not fixed".**
- **A dependency finding satisfied the location rule with a version number.**
  `urllib3 2.0.7: 2` matched; the regex also backtracked quadratically, so a
  minified line in a report was a multi-second hang (381 ms at 1600 tokens, now
  0.6 ms).

### Fixed — correct reports that were rejected

- **`## Suppressions` with no suppressions failed a clean report**: the section
  heading matched the block pattern and became a suppression titled `s` with
  every field missing. The model could not fix it by adding information, only by
  deleting the section, which no message suggested.
- **Suppression fields were English-only**, in an artifact the method tells the
  model to write in the user's language — and `ACCEPTED_RISK`, which does match
  `riesgo aceptado`, was read out of a cell that could never be found in Spanish.
- **A bullet-list report failed four rules at once.** `ddw-test`'s skill gives no
  table template, so bullets are a likely first draft.
- **A marker set narrower than what models write**: `⚠` without the variation
  selector, `✔`, `🔴/🟡/🟢` — the emoji the severity section itself uses.
- **An impossible date crashed with a traceback** and exit 1, outside the file's
  documented contract, with no rule ID to loop on.

---

## [0.13.0] — Unreleased

### Fixed

- **`minimal` did not take effect anywhere.** Eight phase files and six router
  exits still said "wait for the user", with no mention of the mode, and the
  router loads exactly one phase file per turn — so in every phase the model read
  a phase-specific imperative contradicting the general rule. Each arrow now
  carries the carve-out.
- **The mode was forgotten by every compaction.** The boot sequence listed the
  fields to re-derive the pipeline from and `autonomy` was not one of them, so it
  survived only while the CLASSIFY turn stayed in context. The runs `minimal`
  exists for are the long ones, and the long ones are the ones that compact.
- **The corrective loop's ceiling was a number in four documents and a comparison
  in none.** `PRD loops` and `Spec loops` were incremented by the skills and
  measured against nothing, which made one of the three stops that hold under
  `minimal` unreachable. `F-PRD-LOOP` and `F-SPEC-LOOP` compare it at 3 — and
  failing there shuts the gate, which forces the one thing a loop cannot produce
  for itself: a person deciding.
- **The history's "strict shape" forbade the fields the method requires.** The
  orchestrator told the model to omit `tier` and `ticket`, which the helper
  stamps and the post-write replay depends on.

### Changed

- **What `minimal` does not touch, said where it is read:** merging a pull
  request and closing a tracker ticket are not arrows — they are irreversible
  acts on systems other people read, no receipt attests that the user wanted
  them, and they keep their confirmation in both modes.

---

## [0.12.0] — Unreleased

Five independent reviews of the previous release. What they found is in the
commit; what matters most is that **the mutation score was measuring itself**.

### Fixed

- **The mutation run was crediting 180 of 217 faults with a kill they did not
  earn.** The anchor check added one release earlier ran inside `verify_install.sh`
  — which `mutate.py` executes from inside the MUTATED copy of the tree, where
  the fault under test has just deleted its own anchor. The suite went red by
  construction and the fault was recorded as caught, whether or not any real
  check had noticed. Measured: with that one line neutralised, the `pr` gate and
  the `autonomy` field were both surviving while reported killed. The check now
  runs in `mutate.py` itself, before anything is injected, against the tree as it
  is, plus its own CI job; the suite asserts the suite does not run it.
- **Checks that could not fail.** Every validator prints a rule's ID on the ✅ row
  and the ❌ row, so a `case` grepping for the bare ID matched either. Five did.
  One of them — the fix-plan rollback rule — was also built from a fixture that
  `grep -v -A 2` had left byte-identical to the sound one, so it asserted the
  opposite of its own message and could not go red for two independent reasons.
- **`autonomy` was inert and unsafe.** The field a model has the most reason to
  set for itself had none of `tier`'s protection: `assisted → minimal` mid-run
  was accepted, `"banana"` was accepted, and `minimal` survived the closeout into
  the next ticket. It is now an enum, immutable outside CLASSIFY, cleared at IDLE,
  writable through `transition.py --autonomy`, and stamped on every edge taken
  without a human.
- **A report with Windows line endings could never satisfy its gate.** The gate
  hashed raw bytes and every validator hashed decoded text, so `\r\n` produced
  two digests: the validator PASSED, wrote a receipt under one, and the gate
  looked for the other. The refusal said "validate it again", and validating
  again could not help. Routine under WSL.
- **A receipt was portable between tickets.** The digest is of content alone, so
  two byte-identical documents — what a split produces — shared one receipt.
  The receipt records the filename it was written for; now that is read back.
- **The `pr` gate read every `gh` failure as "there is no pull request".**
  Offline, rate-limited, a fork with no default remote, authenticated elsewhere:
  each refused a closeout while asserting a fact the guard never established. It
  now distinguishes an answer from an error, uses `gh pr list --head` (so a
  branch named `123` stops resolving to PR #123), and a pull request closed
  without merging no longer counts as one that was opened.

### Added

- Checks for `autonomy` (enum, immutability, IDLE reset, the helper's stamp, the
  materialised state) and for the `pr` gate (seven `gh` outcomes through a stub,
  plus the gate table itself), neither of which had a single check before.

---

## [0.11.1] — Unreleased

### Changed

- **`/ddw-status` shows `autonomy`.** A mode that decides whether the pipeline
  waits for you is not something to learn by reading a JSON file, and the status
  panel is where people look.
- **`docs/METHOD.md` describes the gates that exist.** Its table still said
  `spec`, `threat` and `verify` rest on the model's record — wrong before this
  release and wronger after it — on the canonical page a reader is sent to for
  what a gate is worth. It now carries the real table, *Minimal intervention* in
  full, and the sentence a reader will overreach on: a complete report can still
  be a false one.
- **The acceptance ritual gains a sixth observation and a `mode` column.**
  `minimal` is a separate code path; a tool passing `assisted` says nothing about
  it. Watching it stop asking is half — the half that matters is watching it stop
  ANYWAY on a hole nobody decided.

---

## [0.11.0] — Unreleased

### Added

- **The `tests` gate rests on a receipt over the run report.** DDW still does not
  run your suite — it does not know your runner, your directory or your
  environment, and decision 2 refuses to pretend. What `tests: true` meant until
  now was one word, on a run nobody could reproduce. There is an artifact now
  (`docs/ddw/reports/tests-{ticket}.md`), a rule family (`F-TEST-01`…`06`,
  `W-TEST-01`) and `validate_tests.py`: the runner and the exact command, counts
  that add up, every failure named by test ID, line/branch/function coverage
  against a floor **quoted from the project** rather than chosen by the report,
  every skip explained. The numbers stay the model's account of a run it did.

- **The `pr` gate asks the forge.** `gh` is asked whether the branch has a pull
  request, which is the one piece of evidence in the pipeline the model cannot
  produce by writing a file. Three states, distinguished rather than blurred: no
  remote means none is owed; a remote with `gh` answering is a verdict; a remote
  with `gh` missing is not verifiable here and falls back to the record, said out
  loud rather than passed silently.

- **`autonomy`, set at classification time.** `assisted` (the default, and what a
  state written before this field says) waits for you on every arrow. `minimal`
  stops waiting and changes nothing else — same gates, same receipts, same hook,
  same bytes. Three things still stop the run in either mode and are not
  configurable: a decision nobody wrote down, a corrective loop at its ceiling,
  and a corrupt state. Every transition taken without a human carries
  `"autonomy": "minimal"` in its history entry, because a record that reads
  identically for a watched run and an unwatched one lies by omission.

  **All eight gates now rest on something outside the model's word** — and the
  grading did not disappear when the labels improved, it moved down a level:
  from *is there evidence* to *what is the evidence of*. Six of the eight are
  receipts over documents the model wrote. A complete report can be a complete
  fiction; what it can no longer be is absent, vague or arithmetically
  impossible.

---

## [0.10.0] — Unreleased

### Added

- **The `sast` gate rests on a receipt now — over the report, never over the
  code.** Nineteen FAIL rules were catalogued for SAST in this repository, with a
  severity fixed per category and a seven-field suppression protocol, and **not
  one of them had ever been executed**. A model could file a hardcoded secret as
  Medium, suppress it with three of the seven fields, write PASSED underneath,
  and the gate turned true.

  `validate_sast.py` answers the structural half and says so on every run: every
  catalogued category carries a verdict, every finding names a file and a line,
  the stated result is consistent with the severities listed, every Medium is
  fixed or formally suppressed, every suppression has its fields and is inside
  its review window. It does not scan your code and it does not know whether a
  finding is right — that judgement stays the model's, exactly as
  `validate_verify.py` leaves the numbers to the model while refusing an
  incomplete verdict.

  `docs/RATIONALE.md` decision 16 refused this receipt and the refusal is now
  narrowed rather than reversed: a receipt claiming the *code* is safe is still
  impossible and still refused. What the old paragraph never noticed is that it
  was defending the code while leaving the report undefended.


---

## [0.9.3] — Unreleased

### Fixed

- **The rule that a validation shows its whole table was in files the model had
  not opened.** 0.9.2 put it in the catalog and in each validation skill. On the
  next live run it collapsed again — `Validación: ✅ PASSED (7 checks)` — because
  that run reached the validator directly (`Ran 1 shell command`, no skill
  loaded), so neither copy of the rule was in the room. Both collapses have now
  happened on the re-validation path, and both times the instruction existed
  somewhere the model was not reading.

  So every validator now prints the demand **as part of its own output**, under
  the table it governs: show this in full, including on a re-validation of
  something unchanged, because the receipt says the bytes are the same and not
  that anyone read what was checked. That is the one place guaranteed to be in
  the context of whoever ran it — a rule that depends on which files were loaded
  this turn is a rule with a coin flip in front of it.

---

## [0.9.2] — Unreleased

Four defects from the first real session against Claude Code. None of them was
findable by the suite as it stood: each is about what a person sees or is left
with after using the thing, which is the whole argument for driving it by hand.

### Fixed

- **The corrupt-state refusal ordered a write it also forbade.** Shown a forged
  state, the guard tells the model to compute the corrected file, save it to a
  scratch path **outside the repo**, and hand the user one copy command — and
  then refused that write too, because a corrupt state raises before any target
  is looked at. The model did exactly what it had just been told to do and was
  stopped for it, which is the second painted door found in this same advice.
  An event whose every path is outside the repository is now none of DDW's
  business, as it already was in the normal path. Nothing inside the repository
  moved: product source, and the state itself, stay refused until a human
  restores them — including an envelope that names one outside path next to the
  state, which is the decoy shape that has bought a free write here before.
- **A re-validation stopped printing its checklist.** The protocol says paste
  the script's output verbatim, and a live run pasted five complete tables and
  then collapsed the sixth — a re-validation of an unchanged PRD — to
  `PASSED (7 checks)`, at exactly the moment approval was being asked for. The
  rule never named that case, so the model reasoned its way out of it: *you
  already saw this* is a claim about a previous screen, and *the receipt still
  matches* answers a different question. Now stated in the catalog and in each
  validation skill, because the skill is what gets loaded and executed.
- **The refusal doubled its own prefix.** The gate's reason carried a `DDW: `
  while every caller adds one of its own, so the user read `DDW blocked this
  write: DDW: the define gate…`. `transition.py` had been stripping it back out
  by hand — a workaround in one caller, and nothing in the other. The prefix
  belongs to whoever is speaking; the reason no longer carries one.
- **DDW dirtied the user's `git status` with its own bytecode.** Running the
  method's scripts leaves `.ddw/scripts/__pycache__/`, and a drop-in is meant to
  be committed — so the choice was commit `.pyc` files or read the noise
  forever. Both writers of the managed `.gitignore` block now cover it.

Eleven checks and six mutations, so none of the four can come back quietly.

> Numbered 0.9.2 and not 0.9.1 because the fourth fix landed on top of the first
> three under the number they had already shipped under — one product version
> describing two different products, which is the failure the rule was written
> for. `check_versions` said so, in CI, on the commit that did it. The rule was
> applied to the run that broke it rather than argued with.

---

## [0.9.0] — Unreleased

**Pre-release.** The version says what the evidence says. Five of the eight gates
rest on something outside the model — `define`, `spec`, `threat` and `verify` on
receipts bound to their artifact's bytes, `commit` on git — and `tests`, `sast`
and `pr` stay declared on purpose, for the reason `docs/RATIONALE.md` decision 16
gives. **1.0.0 is what this becomes once that work is verified against the live
tools**, not a number claimed ahead of it.

### Fixed

- **Claude Code reported a plugin error on every session.** It scans
  `hooks/hooks.json` at the plugin root whatever the manifest declares, and that
  path held Gemini's extension hooks — whose event names Claude cannot parse.
  Gemini's file moved to `adapters/gemini/`, and the root path is now asserted
  empty rather than asserted correct. Found by installing the plugin and reading
  the screen, which is what `scripts/acceptance.md` exists for.
- **The suite ran a smaller version of itself on macOS.** `find -printf`,
  `sed -i` and `shopt -s globstar` are GNU-only; on bash 3.2 they silently
  removed 21 checks and made one pass by comparing nothing to nothing.

### Added

- **The spec, the threat model and the verification verdict now earn receipts.**
  `validate_spec.py`, `validate_threat.py` and `validate_verify.py` join
  `validate_prd.py`: each prints a checklist with every rule ID and its ✅ / ⚠️ /
  ❌, writes it next to the artifact as `<artifact>.validation.md`, and on a run
  with zero FAILs writes a receipt bound to that artifact's bytes. The `spec`,
  `threat` and `verify` gates now demand those receipts, which is what
  `docs/RATIONALE.md` decision 16 said they would the day their validators
  existed. Five of the eight gates now rest on something outside the model.
- **The scope of each receipt is stated on every run**, in the script's output
  and in the skill. `validate_verify.py` does not run your suite — it checks the
  verdict is complete, and says so where a reader cannot miss it.
- **A canonical threat model template**, because a document nothing can parse is
  a document nothing can check. `ddw-threat-modeling` emits it, and F-TM-06 —
  the rule against a generic model unattached to the design — is now answered by
  counting what the model cites from the spec.

### Changed

- **A validation shows its whole checklist, then fixes, then asks.** The catalog
  gained *How a validation runs* — the four steps every validation skill follows:
  run the script, loop on every ❌ until it is gone (fixing only what the rule
  names), ask about what genuinely needs a human decision with options, and paste
  the full table plus the link to the report on disk. A live run had compressed
  seven checks into two lines with the rule names dropped; the receipt is what
  makes the table structural instead of a courtesy, since there is no route to
  the next phase that goes around it.
- **One product, one version.** All five manifests and the CHANGELOG must state
  the same number, a change to anything shipped has to move it, and each rule
  file still carries its own. `CONTRIBUTING.md` has the rule and
  `check_versions.py` enforces it, on pushes as well as pull requests.

### What this release is

The method has been in daily internal use since **February 2026**. This is its
first public extraction: the same pipeline, separated from the projects it grew
in, with the tool-specific wiring generalised from one agent to six.

### The method

- Six phases — `CLASSIFY → DEFINE → PLAN → CODE → VERIFY → CLOSEOUT` — with a
  gate between each pair and state that survives closing the session.
- Five tiers, so the ceremony matches the size of the request: `QUERY`,
  `QUICK-FIX`, `FIX`, `FEATURE`, `DISCOVERY`.
- Gates enforced by a hook running outside the model, not asked for in a prompt.
- Gates graded by what backs them, and the grade written down: the PRD's rests on
  a content-hashed receipt, the commit gate asks git, and the rest are the model's
  record. `tests` and `sast` stay self-declared deliberately — see RATIONALE 16.
- An artifact per phase, under `docs/ddw/`, committed as that phase closes.
- Seventeen skills and five subagents, including auditors that did not write the
  code they review.
- Security as two phases of the pipeline rather than a review afterwards: threat
  modeling in PLAN, SAST in CODE. Deliberately no dynamic scan — see the README
  for why a gate that cannot be satisfied honestly is worse than no gate.

### Tools

Claude Code, Codex CLI, Copilot CLI, Cursor, Gemini CLI and OpenCode. One
method, six recipes: `.ddw/` is byte-identical in every installation, and a
recipe declares only where its tool looks for things and what dialect it speaks.

Claude Code and OpenCode have been exercised end to end against the live tool,
and Copilot CLI for three of the four checks — its fourth is detected rather than
prevented, which is that tool's ceiling and not DDW's. Codex CLI, Cursor and
Gemini CLI are verified at the boundary — the test suite drives each tool's real
hook with that tool's own event format — and unverified in the wild.
`scripts/acceptance.md` holds every row, and reports are welcome.

After a compaction, each of the six is reminded to re-read the state and the
phase router instead of answering from the summary. Advisory on all six, which
is what their compaction events are.

### Quality tooling

- `scripts/verify_install.sh` — installs into throwaway repos and drives the
  hooks each tool actually runs.
- `scripts/lint_method.py` — checks the prose against the graph, the rule
  catalog and the filesystem.
- `scripts/mutate.py` — injects known defects one at a time and reports whether
  the suite notices.
- `scripts/check_versions.py` — the version and the licence, read from the files
  that own them and compared against every copy.
- `scripts/check_commits.py` — a range of commits against the attribution rule
  DDW ships: `AI-assisted:` where a model helped, never `Co-Authored-By`.
- CI on Linux and macOS, because a platform difference once removed a large
  share of the checks without changing the exit code.
