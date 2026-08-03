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

- Six phases — `CLASSIFY → DEFINE → PLAN → CODE → VERIFY → RELEASE` — with a
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
