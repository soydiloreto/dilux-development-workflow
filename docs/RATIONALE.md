# Why DDW decides what it decides

A framework without its reasoning is a configuration file: you either adopt it whole or you argue
with it in the dark. This is the other document — every decision the method makes that a reasonable
engineer could have made differently, why it went the way it did, what it is standing on, and what
it costs you.

It is here so you can read it **before** you adopt DDW, and disagree on the merits.

Two ground rules for this file. Every entry names its cost — a decision presented with only its
upside is advocacy, not reasoning. And a claim that rests on somebody else's evidence cites it, so
you can go and check whether I read it right.

`docs/DEVELOPMENT.md` is the neighbouring document and answers a different question: how this
repository is built and kept honest. This one is about the method.

---

## 1. A rule that matters is enforced outside the model

**The decision.** Gates are enforced by a hook that runs before every write, outside the model's
context. Not by instructions asking the model to behave.

**Why.** A rule written in a prompt is a *promise*: the model can forget it, misread it, or decide
this once does not count. A rule enforced by code is a *guarantee* — the decision never reaches the
model at all. Try to write source with no approved spec and the write does not happen, which is a
different thing from the agent apologising and continuing.

This is the line every other decision here is drawn from: **if a rule matters, it is executable. If
it cannot be executed, it does not get to call itself a gate.**

**The cost.** Six tools, six hook dialects, and each one is somebody else's product that can change
under you. That is real maintenance, and it is why the adapters are recipes with no logic and every
tool calls one shared gate — so there is one decision to get right rather than six to keep in sync.

---

## 2. There is no DAST gate

**The decision.** Security is two phases — a threat model in PLAN, SAST in CODE. There is no
dynamic-analysis gate.

**Why.** DAST needs a running deployment, and DDW cannot know whether you have one, where it is, or
whether it is safe to attack. A gate that cannot be satisfied honestly gets satisfied dishonestly:
somebody marks it green to move on, and now every gate in the pipeline is a suggestion. **One gate
nobody believes is worse than one gate fewer.**

**The cost.** A whole class of vulnerability — the ones that only appear at runtime — is outside
what DDW checks. It says so rather than implying coverage it does not have.

---

## 3. Gate, or mandatory step

**The decision.** Two different things, deliberately not merged. A **gate** is a condition the state
machine refuses to move past. A **mandatory step** is resolved out loud in front of you and recorded,
but nothing in the repo can verify it happened.

Gates: the PRD validates, the spec is approved, the threat model is complete, the suite is green,
SAST is clean, the verdict accounts for every criterion, there is a commit, the PR step was
resolved. Mandatory steps: updating the tracker, and where the branch lands.

**And a gate is not automatically evidence.** When this was written only one of them was verified
against anything outside the model's own report — the PRD's — and the rest were a field in the state
that the model set. All eight rest on something now (decision 16 has the table), and the distinction
did not disappear with them: it moved down a level. Six of the eight are receipts over documents the
model wrote, so what is attested is that the *document* is complete, not that the work it describes
was done. **Nothing here runs your test suite or scans your code**, a framework that implied
otherwise would be doing the exact thing it was built to stop, and a complete report can still be a
false one.

What that buys is narrower than it sounds and worth stating exactly: the claim has to be made before
the move rather than after it, in the phase that owns it, backed by an artifact whose bytes the
receipt names, and it lands in an append-only history that says who claimed what and when.

**Why.** A gate can only demand what the repo can see. Whether a human merged a branch, or moved a
ticket in Jira, depends on people and systems outside it. Calling those gates would mean either
blocking on something you cannot control, or accepting the model's word for it — and a gate that
accepts the model's word is decoration.

**The cost.** Mandatory steps are enforced by prose, which is weaker, and honestly so. What keeps
them from evaporating is that the closeout summary carries the answer and cannot be presented
without it — plus, one ticket later, the branch check that notices the base never got the code.

---

## 4. TDD proven by evidence, not by trust

**The decision.** The test is written before the code, every tier, every block — and the implementer
has to **show the failure**: which test, which assertion. Missing evidence fails the block however
good the code looks.

**Why.** A green suite looks exactly the same whether the tests came before the code or after. The
observed failure is the only thing that distinguishes them. Without it, "we do TDD" is a claim
nobody can check, including the person making it.

**The cost.** It is slower, and it makes the implementer's report longer. It also cannot apply
retroactively: a test written for an error path that already works documents the status quo. That
limitation is exactly why the next entry exists.

---

## 5. Error paths are demanded in PLAN, not VERIFY

**The decision.** `F-SPEC-16`: every error a block documents must appear in that block's test list,
checked when the spec is validated. And acceptance criteria are written in **EARS**, whose fifth
pattern — `IF <trigger>, THEN THE <system> SHALL <response>` — exists for faults and misuse.

**Why.** This one comes from a defect in DDW's own acceptance run. The rules were all there: the PRD
warned about missing error scenarios, the spec had to document error handling, and VERIFY demanded a
sad-path test for every input. Nothing joined the middle two. A spec passed PLAN with a full
error-handling section and a happy-path-only test list; VERIFY caught it two phases later, when the
code already existed and the missing tests could no longer be written first.

The upstream half is notation. In free prose, an acceptance criterion that omits the failure case
reads exactly like a feature that has none — the absence is invisible. EARS gives it a shape, so it
becomes countable. It comes out of safety-critical engineering at Rolls-Royce, and AWS's Kiro adopted
it for spec-driven work with agents for the same reason.

**The cost.** EARS is more rigid than prose and its `SHALL` reads bureaucratic to people who do not
write requirements for a living. DISCOVERY and QUICK-FIX are exempt for that reason.

**Sources.** [EARS](https://en.wikipedia.org/wiki/Easy_Approach_to_Requirements_Syntax) ·
[Kiro feature specs](https://kiro.dev/docs/specs/feature-specs/)

---

## 6. A branch is never cut from a stale base

**The decision.** Fetch and branch from `origin/{base}` — never `git pull` to freshen it. Measure the
drift when resuming a branch and again before the PR. Report and ask; never rebase or merge unasked.

**Why.** DORA's research puts the useful lifetime of a branch at under a day, and treats integrating
at least daily as a capability of high-performing teams. GitHub encodes the same idea as a merge
requirement. DDW cannot merge for you, so it does the part it can: never start you from a stale base,
and never let you find out late.

`git pull` is ruled out by name because it needs a clean tree on the base branch and can trigger a
merge nobody asked for. Branching from a fetched ref does one thing, the same way every time.

**The cost.** A `git fetch` at three points in the pipeline, which costs a second and is noise in a
repo with no remote — where the check says so and moves on.

**Sources.** [DORA — trunk-based development](https://dora.dev/capabilities/trunk-based-development/) ·
[Short-lived feature branches](https://trunkbaseddevelopment.com/short-lived-feature-branches/) ·
[GitHub merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)

---

## 7. Artifacts live in the repository

**The decision.** PRD, spec, threat model, SAST report, verification report — all under `docs/ddw/`,
committed by the phase that produced them. The ADR is the deliberate exception: `docs/adr/`, because
an architecture decision belongs to the project, not to the tool that helped write it.

**Why.** Documentation that lives outside the development workflow drifts from reality; that argument
predates agents and is why documentation-as-code won for technical content. The consensus on ADRs is
blunter: keep them elsewhere if you like, but the copy in the repository is the source of truth.

Agentic work sharpens it for a mechanical reason. The agent's reading surface is the working copy. A
document that is not in the repo is not context — it is a call to an external system that may not
exist in this session. And there is a governance benefit that disappears the moment you move them
out: the pull request becomes the mechanism by which a decision gets reviewed.

**If your team will not have them in the repo: publish, do not relocate.** Generate the mirror from
the repo. Inverted, the repo copy ages, and the agent builds against a PRD that stopped being true.

**The cost.** Your repository gains a `docs/ddw/` directory that grows with every ticket. Reviewers
who only want code have more to scroll past.

**Sources.** [Documentation-as-code](https://dev.to/zenika/documentation-as-code-has-silently-won-for-tech-content-e5o) ·
[Architecture Decision Records](https://andydote.co.uk/2019/06/29/architecture-decision-records/)

---

## 8. The context file stays minimal

**The decision.** `ddw-context-check` reports only knowledge the agent **cannot discover on its own**
— the commands DDW is about to run: pre-commit, the CI invocations, the real test and lint commands.
It never proposes prose, conventions or architecture.

**Why.** This one runs against the intuition. A study of repository context files across 138 real
repositories found **no improvement in task success rate and over 20% more inference cost**, with
LLM-generated context files actively hurting. The authors' conclusion is that these files should be
minimal rather than comprehensive.

So the value is not "tell the agent more". It is "tell the agent the handful of things it would
otherwise get wrong" — which is exactly the category the AGENTS.md guidance says belongs there.
Without that restriction the skill becomes the problem the study describes.

**The cost.** DDW will not warn you about a convention it cannot see evidence for. It reports that
your repo has a linter configured and the context file names no lint command; it will not tell you
that you ought to have a linter.

**Sources.**
[Gloaguen et al., 2026 — Evaluating AGENTS.md (ETH Zurich)](https://www.sri.inf.ethz.ch/publications/gloaguen2026agentsmd) ·
[AGENTS.md guidance](https://www.augmentcode.com/guides/how-to-build-agents-md)

---

## 9. One block, one commit

**The decision.** In CODE, each block of the spec is committed as it goes green. The implementer
subagent never commits — that belongs to the orchestrator, and so does the state.

**Why.** A block that has passed its two reviews and its tests is a state worth keeping, and the
session rule lets you stop between blocks. Holding three blocks back so they can share one commit
means an interruption after the second loses both — the exact loss the per-phase commit exists to
prevent, one level down.

The invariant that does not move is **who** commits. If a subagent could write the state or the
history, the machine would break from the inside.

**The cost.** More commits per ticket. In exchange the history says what happened in what order,
which is the same bargain the per-phase commits make.

---

## 10. Mutation testing is the meter, not the detector

**The decision.** `scripts/mutate.py` injects known faults one at a time and checks the suite goes
red. It is the coverage figure this project reports.

**Why.** A suite that always passes and a suite that cannot fail look identical from outside. The
only way to tell them apart is to break something on purpose. It found this suite at 44% when it read
as green.

**The limit, stated because it matters.** Every mutation encodes a defect somebody already knew
about, so by construction **it cannot find a new one**. It measures protection against regression,
not discovery. Finding the unknown still takes adversarial review by someone trying to break the
thing. Anyone who reads a 100% mutation score as "there are no bugs" has misread it — including me,
once, when a stale expected-check count made every mutation look killed.

**The cost.** Every fix has to arrive with a mutation, or the fix is protected by nothing.

---

## 11. The shell is detected, not prevented

**The decision.** The pre-write guard refuses source from a phase that forbids it, through the write
tools. It does **not** cover shell commands. Instead, the post-write net — which already runs after
every one of them — reports source that changed in a phase that does not write source.

**Why not prevent it.** Catching a shell write means parsing shell: `cat >`, `tee`, `sed -i`,
`python -c`, a heredoc, a redirect built from a variable. Every spelling not anticipated fails open,
silently. That is not a partial guard — it is a guard **that looks total and is not**, and someone
reading "no approved spec, no code" would believe it holds everywhere. Same reasoning as decision 2:
a gate nobody can honestly satisfy is worse than one fewer gate.

**Why it reports rather than refuses.** DDW cannot tell the agent's shell from yours. Editing your
own code in another terminal while a ticket sits in PLAN is an ordinary thing to do; being refused
for it would be a defect. Reporting a fact is useful. Blocking on an inference about who typed it is
not.

**The cost.** Source written through a shell in a phase that forbids it lands. You are told, on the
next tool call, and you decide. The README says this where it makes the promise rather than leaving
the reader to discover it.

---

## 12. What each tool's hooks can actually do is not uniform

**The decision.** The post-write net refuses where a tool's post hook can refuse,
and **reports** where it cannot. It is not pretended to be the same everywhere.

**Why.** GitHub documents Copilot CLI's `postToolUse` as able to modify a result
or add context and nothing more: `permissionDecision` belongs to `preToolUse`,
and a non-zero exit is logged and skipped. DDW was sending it a refusal it
ignores — so a `.ddw-state.json` forged with `sed` was detected correctly, by a
hook whose verdict went nowhere, while the suite reported the check as passing.

What Copilot's post hook *can* do is put the finding in front of the model. That
is enough for the one thing this net exists for: the orchestrator's rule on a
corrupt state is to stop and report, and a model that has been told will follow
it. On Claude that is a refusal the model cannot talk past. On Copilot it is a
message it is expected to heed.

**The cost.** The `sed`/`jq` bypass is *prevented* on the tools whose post hook
can refuse and only *detected* on the ones that cannot. That difference is in the
per-tool row of `scripts/acceptance.md` rather than averaged away, because
someone choosing a tool deserves to know which one they are getting.

---

## 13. One repository per method, not one that accumulates

*(A teaching decision, from the course this method is taught in.)*

**The decision.** When DDW is used to compare tools, each tool rebuilds the same application in its
own repository. Only the PRD travels.

**Why.** An incremental repo makes the second tool look better than the first for a reason that has
nothing to do with the tool: it inherited working code. Holding the requirement constant and the
starting point empty is the only way the comparison says anything.

**The cost.** You build the same thing more than once. That is the price of the comparison being
worth reading.

---

## 14. A corrupt state is reported to a human, never repaired by the agent

**The decision.** When DDW finds a `.ddw-state.json` that cannot be true, the agent is told to stop
and report it. It is not told to fix it, and it is refused if it tries. Recovery is the user's:
their own backup, or `transition.py` from the last state the history supports. Not `git checkout` —
the install gitignores the state, so git never has a copy. The first live run on OpenCode proved
why the advice has to say so: the refusal used to recommend exactly that command, the agent offered
it to the user, the pathspec failed, and the agent read the failure as "the committed file is
corrupt too" — a guessed fact born from a door the method itself had painted on.

**Why.** For most of DDW's life the refusal said the opposite — *"fix the state and redo the
transition with the write tool"* — and blamed `Bash/jq/sed` for it. Both halves were wrong in ways
that only showed up under a real agent:

- **The accusation was a guess printed as a fact.** The write had been made with `Write`, through
  the sanctioned path. A model told it used a shell it never used goes looking for a mistake that
  is not there.
- **The order could not be carried out.** Restoring the header alone is refused for missing its
  history entry; adding the entry is refused because that edge is not in the graph. Both doors
  closed, by design, and the message pointed at them anyway.

An agent that obeys an impossible instruction does not stop — it escalates. In the run that
produced this entry it wrote the state eight times, then found the one move that always worked:
`rm -f .ddw-state.json`, which took the run's history with it. The net had caught the corruption
correctly and then rewarded the only action that destroyed the evidence of it.

**The cost.** A human is now in the loop for a class of problem an agent could sometimes have
resolved alone. That is the intended trade: a state file is the record of what was authorised, and
an agent editing its own audit trail to get unstuck is not a recovery, it is the failure.

**What it buys.** The instruction is now the same on every dialect — the tools that can refuse and
the tools that can only speak say one thing. The history survives deletion (see below). And the
finding is stated once per corrupt file rather than on every subsequent tool call: twenty
repetitions of an eight-line refusal is how the one instruction that matters gets buried.

---

## 15. The journal outlives the state file

**The decision.** Every transition that passes post-write validation is appended to
`.ddw-journal.jsonl`, written by the hook and never by the model. If the state disappears, or comes
back with fewer entries than were recorded, the next write is refused.

**Why.** The state file was the only record of itself, which made deleting it a complete escape:
with nothing on disk to compare against, the next write starts from a blank `IDLE` and every rule
that compares old to new has nothing to compare. Append-only is not a property of a file that can
be replaced with a shorter one.

**The cost.** A second runtime file, and a check that fires if a user deletes the state
deliberately — they have to say so rather than just doing it. Both are gitignored; neither is
committed.

**What it buys.** The cheapest way out of the pipeline stops working. Someone determined can still
delete both files, and that is fine: the guarantee is not that the history is indestructible, it is
that destroying it takes a deliberate act rather than one impatient `rm`.

---

## 16. A gate is an attestation, and they are not all the same strength

**The decision.** Every gate is refused-without and recorded. What backs the claim is graded, on
purpose, and the grade is written down rather than implied:

| Gate | What it rests on |
|---|---|
| `define` | A **receipt** naming the PRD's current bytes, written only by a validation run that passed |
| `spec` | A **receipt** naming the spec's (or fix-plan's) current bytes |
| `threat` | A **receipt** naming the threat model's current bytes |
| `verify` | A **receipt** naming the verification verdict's current bytes |
| `sast` | A **receipt** naming the SAST report's current bytes — the report, never the code |
| `tests` | A **receipt** naming the run report's current bytes — the account of the run, never the run |
| `commit` | **git**, asked directly: tracked changes in the working tree contradict "this is committed" |
| `pr` | **the forge**, asked through `gh`: the branch has a pull request or it does not |

**What the five added receipts say, and what they do not.** Each one attests that a validator ran
over those exact bytes and found zero FAILs against the catalog's rules for that artifact — that the
spec covers every FR and every AC has a test, that every component got all six STRIDE categories and
every threat a treatment, that the verdict accounts for every criterion and states its coverage, that the SAST report judges every catalogued category and locates what it found. None
of them attests that the analysis is *right*. `validate_verify.py` in particular does not run your
suite: it checks that the verdict is complete, and the numbers in it remain the model's report of
what it ran. Every one of these scripts prints, on every run, which rules it answered and which it
left to the model — because a receipt whose scope is unstated is read as covering everything.

This is not DDW's invention and the vocabulary is not ours. Software supply chain calls the artifact
an **attestation** and the graded version **provenance**, and the ladder is
[SLSA](https://slsa.dev/spec/v1.0/requirements): at level 1 provenance may be self-declared by
whoever did the work; from level 2 it is produced and signed by the platform, and the party doing
the work cannot forge it. A required status check on a pull request is the same idea in the shape
everyone already uses daily — you cannot merge until **the CI** reports the check, and you cannot
report it on CI's behalf.

Read against that ladder, DDW's gates were all level 1. `commit` and `pr` are level 2 — a system
answers, and the party doing the work cannot forge the answer. The six receipts are a kind of their
own — the receipt is produced by a script the model does not write, over a
document the model does. Level 2 for the shape of the record, level 1 for its content, and the run
says which is which rather than leaving the reader to assume the better of the two. Saying so is
the point: a framework whose gates all look alike, while some are evidence and the rest are records,
is teaching its own users something false about their pipeline.

**What could not be raised, and was not.** Two claims cannot be made honestly by anything in this
repository, and pretending otherwise is the failure it names everywhere else: that your code is safe,
and that your suite passed. Neither is attested by anything here. What was raised is the report of
each — complete, located, arithmetically possible, measured against a floor the project set — which
is a different claim and is labelled as one on every run.

**`sast` was on this list, and the argument for keeping it there was answering a question nobody
asked.** It read: a receipt would take "the model reported it looked" and write it into a file that
reads as proof. True — of the *code*. DDW does not scan anything and no file will make its reading a
proof, so that receipt is still refused, and always will be.

What the paragraph never noticed is that it was defending the code and leaving the **report**
undefended. Nineteen FAIL rules are catalogued for SAST in this repository, with severities fixed per
category and a seven-field suppression protocol, and **not one of them was ever executed**. A model
could file a hardcoded secret as Medium, suppress it with three of the seven fields, write PASSED
underneath, and the `sast` gate turned true. The rules existed, the report existed, and the distance
between them was the model's goodwill.

`validate_sast.py` closes exactly that distance and nothing more: every catalogued category carries a
verdict, every finding names a file and a line, the stated result is consistent with the severities
listed, every Medium is fixed or formally suppressed, every suppression has its fields and is inside
its review window. Whether a finding is *right* stays the model's judgement, the script says so on
every run, and the receipt is bound to the report's bytes so editing it afterwards costs another run.

This is the same split `validate_verify.py` already makes and the same one this section already
blessed: the numbers stay the model's, the completeness stops being optional. Applying it to `sast`
was not a change of principle. It was noticing that the principle had been used to justify checking
nothing, which is the more comfortable of the two readings and was never the honest one.

`tests` is the one people will ask for, and the one that would make DDW something it must not
become. Verifying it means DDW runs your suite: knowing whether this is pytest or jest or a
monorepo with five runners, in what directory, with which environment, and being right about it in
somebody else's repository. CI can do that because CI **is** the environment. DDW lives inside your
project and cannot honestly promise it — the same reasoning as decision 2, where the missing DAST
gate is missing on purpose.

`tests` was the last one, and its paragraph made the same move `sast`'s did: it defended the *run*
and left the *report* undefended. DDW running your suite is still refused and still impossible for
the reasons above. What `tests: true` meant in the meantime was one word — no runner, no command, no
counts, no names, nothing reproducible. `validate_tests.py` refuses that: the runner and the exact
command, counts that add up, every failure named, three coverage numbers against a floor quoted from
the project rather than chosen by the report, every skip explained. The numbers stay the model's
account of a run it did. What they can no longer be is absent.

`pr` went the other way and is now the strongest of the eight: it asks the forge through `gh`, and
that is evidence the model cannot produce by writing a file. Three states, distinguished rather than
blurred — no remote means no pull request is owed; a remote with `gh` answering is a verdict; a
remote with `gh` missing is not verifiable here and falls back to the record, which the skill says
out loud. **The cycle is complete; the evidence is not uniform, and the table above is where you
find out which is which.**

**The cost.** Six of the eight rest on a receipt over a document the model wrote, and **a complete
report can be a complete fiction — the receipt will not know.** That is the sentence this section
exists for, and it is more important now than when three gates were honestly labelled "the model's
record": a reader who sees eight gates all backed by something will assume more than is there. The
grading did not disappear when the labels improved. It moved down a level, from *is there evidence*
to *what is the evidence of*. A reader who skims the word "gate" will assume more than is there, and
the README now spends a paragraph correcting that assumption instead of enjoying it.

The second cost is subtler and belongs to the three that were raised: a receipt is a stronger claim
than a boolean, and a reader will extend it past its scope unless the scope is repeated. So it is
repeated — in the script's own output, in the skill, and in the table above. A gate that says more
than it knows is the failure this section exists to name, and raising a gate is a new chance to
commit it.

`spec`, `threat` and `verify` followed `define` the day their validators wrote receipts, and `sast`
followed them the day someone asked why nineteen catalogued rules had no script. Each was one row in
`validate-transition.py`'s table plus a validator — the mechanism this section promised, used four
times, exactly as promised.

Both landed. `tests` got the artifact it had none of — `docs/ddw/reports/tests-{ticket}.md`, with
`F-TEST-01`…`08` — and `pr` turned out to be the strongest of the eight, because a forge answering
about a branch is the one piece of evidence in this pipeline a model cannot produce by writing a
file.

**What it buys.** The evidence check now runs where the model cannot route around it. It used to
live only in the helper the model is asked to call, so the same state written with the write tool
went through: exit 2 through `transition.py`, exit 0 through the hook. A guarantee with a polite way
around it is a promise wearing the word "gate", which is the exact thing decision 1 exists to
prevent.

---

## 17. A pull request waits for people, and the pipeline has to wait with it

**The decision.** You can step back one phase, always, and stepping back gives up what that phase
granted. A ticket can be **paused at CLOSEOUT** once its commit and its pull request exist. Resuming
there asks about both again. And when the phase is IDLE and the repo has a remote, DDW asks the
forge what is waiting for you.

**The complaint this answers.** You finish, you open the pull request, and the review takes two
days. There is one state per directory, so the ticket sat in CLOSEOUT and you could not start
anything else — and when the review came back asking for changes, the method's own advice was to
open a *new* ticket, on a *new* branch, for work that belongs to the same pull request. That is
bookkeeping nobody believes, and people route around a method that asks them to lie in it.

**Why stepping back is one phase at a time, declared in the graph.** The alternative was a rule in
code — "any earlier phase is legal" — and the graph would have stopped being the authority. Instead
each backward edge is data, with a `clears` list naming exactly what it takes away, and the
validator refuses a backward write that still holds them. Four steps to get from CLOSEOUT to DEFINE,
and each one is a history entry saying why. The record ends up saying how far back a review sent
you, which is worth more than the convenience of one jump.

**And it closes a hole that predates the feature.** `PLAN→DEFINE` already existed and cleared
nothing, so you could step back, rewrite the PRD, and step forward claiming `define` — with no
receipt asked for, because evidence is owed only when a gate is claimed for the *first* time and
this one never stopped being true. The helper refused it. The hook did not. That is the same shape
as decision 16's own worst moment, in the pipeline's documented recovery path, and it was reachable
until the `clears` rule landed in `validate()`.

**Why the pause exception is exactly this narrow.** `no_walkaway` exists so `"abandon"` cannot be a
skeleton key: relabel the exit and ship with no commit and no PR. That reasoning does not cover a
ticket whose commit and pull request are already paid for and whose only remaining dependency is
another person. So: a **pause** is allowed there, an **abandon** is not, and both gates are read
from the state *before* the write so the same write cannot grant them and spend them.

Resuming gives `commit` and `pr` back false. A gate already true is never re-asked, and days passed
— the pull request may have been closed, the branch may have moved. Two instant questions, one to
git and one to the forge, against a closeout that would otherwise be satisfied by evidence earned
before the wait.

**Why the ceiling counts two numbers.** `PRD loops` is the running total and nobody resets it: six
months on, "this document cost five rounds" is worth being able to read. The ceiling measures
something else — rounds since a person last decided anything — because a round the model drove and
a round a reviewer asked for are not the same event, and a review comment is already the decision
the ceiling exists to provoke. Charging it would spend the model's budget on the one case where a
human was demonstrably in the loop.

**Why the forge is asked at IDLE and nowhere else.** The rule is deterministic on purpose: phase is
IDLE and the repo has a remote → ask, every time; anything else → never. A network call on every
session start, in every repo DDW is installed in, is a cost this project should refuse to hide; and
mid-ticket the answer is not one you need. IDLE is where you decide what is next, and it is also the
only moment a fresh clone on another machine can be told anything — the pause lives in
`.ddw-paused/`, which never leaves the machine that wrote it.

**The cost.** Three things this does not do, said plainly. Two machines on one ticket are not
coordinated: git is the arbiter, and DDW only reports that your branch fell behind. The `history`
does not travel between machines — the shared record of that work is the commits and the pull
request. And resuming on a second machine means re-walking the pipeline over the committed
artifacts, re-earning each receipt, because writing a state that claims eight gates is the forged
state the hook exists to refuse.

---

## Disagreeing

If one of these is wrong, the useful form of the argument is: which entry, what does it cost that is
not listed, and what would you put in its place. `CONTRIBUTING.md` says where to put that.
