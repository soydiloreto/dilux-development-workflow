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
