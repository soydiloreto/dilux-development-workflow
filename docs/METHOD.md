# How a request flows

You ask for something in plain language. You never invoke a phase by hand.

1. **CLASSIFY** — works out what you are asking for, reads your stack, opens a ticket and a branch.
   *You confirm the classification.*
2. **DEFINE** — the what and the why: the PRD. *Gate: the PRD validates.*
3. **PLAN** — the how, and what could go wrong: the spec and a threat model.
   🔒 *Gate enforced by a hook: no approved spec, no code. Not a convention — a refusal.*
4. **CODE** — implemented block by block, each with its tests. *Gate: suite green, SAST clean.*
5. **VERIFY** — cross-checked by an agent that did **not** write the code, against the PRD and the
   spec, and the verdict written to a report. If it fails, back to CODE. Never patched here.
6. **CLOSEOUT** — CHANGELOG, PR, ticket, closeout.

Every arrow needs your explicit approval — unless you asked for `minimal` autonomy when the work was
classified, in which case the arrows stop asking and nothing else changes (see *Minimal
intervention*, below). The machine closes the phase, shows you a summary, and
waits.

**Each phase commits what it produced, as it closes it.** The PRD lands before the spec, the spec
before the code — so the history says what happened in what order instead of asserting it, and a
ticket that gets dropped still leaves its thinking behind on the branch.

The canonical tables — every phase, every tier, every gate — are in
[`ddw/rules/README.md`](../ddw/rules/README.md). This page is the why.

## Not every request deserves all of that

Fixing a typo cannot cost you a PRD. A process that expensive is a process people quietly stop
using. So CLASSIFY assigns a tier, and the tier picks the pipeline: a question gets an answer, a
ten-line fix gets a short lane with no PLAN and no VERIFY, a defect or a feature gets the full run,
and DISCOVERY thinks an idea through without touching your source.

The short lane has a guard of its own: a hook stops it the moment the change reaches a sensitive path
or grows past ten lines, and tells you to reclassify.

## And a tier for not using any of it

**No product code is written with no ticket open.** That is the promise, and until 0.20.0 it was a
promise the agent kept out of good manners: `IDLE` — where every session starts and where a
repository with nothing open sits — was not covered by the rule that stops source writes. Asked
plainly for a file, an agent classified the request and refused, exactly as the rules say. Told *"no
ticket, just write it"*, it wrote the file, both hooks green, nothing recorded anywhere.

Making that impossible outright would have been the wrong fix. A pipeline you cannot step out of is
one people uninstall, and an uninstalled pipeline enforces nothing at all. The problem was never
that code gets written without gates — it is that it was written **without anybody deciding to**.

So there is a tier for deciding to: **`FREE`**. Classify into it and nothing is asked of the work —
no gates, no artifacts, no reviews — and every session start says, in the first line it prints,
`ESTÁS TRABAJANDO SIN WORKFLOW`, with the way back on the same line. Both ends are transitions, so
the history says when you stepped out and why.

Three things it is not. It is not a way out of a ticket already in flight: no working phase has an
edge into it, and the tier cannot change outside CLASSIFY, so gates already asked for cannot be shed
by relabelling the work. It is not a licence to disarm the pipeline: DDW's own files, the journal and
the state are as sealed in `FREE` as anywhere else. And it is not quiet.

What a repository at rest still writes with nothing open: everything under `docs/`, your context
files, the CHANGELOG, and each tool's wiring — so installing, ejecting, reading and writing documents
never need a ticket. `RATIONALE.md` decision 20 has the reasoning and what it costs.

And you can always **walk away**. Abandon a ticket, or pause it for later, from any phase, owing
nothing — as long as you say which one it is. The one exception is CLOSEOUT, where nothing is left to
decide and only steps remain: an exit there is a closeout and owes its gates, or the word "abandon"
would be a skeleton key. Everywhere else, bailing out is allowed; doing it silently is not, because
the history is what someone reads six months from now to find out why this was dropped.

## About that PRD

Most organisations write the PRD before anyone opens an editor, and DDW does not ask you to write it
twice. It **takes the one you have** — a ticket, a document, a paragraph in a chat — validates it
against the codebase it is about to be built in, and materialises it in the repo next to the code.

That last part is deliberate. An agent cannot read your wiki in the middle of a session, and a
requirement it cannot read is a requirement it will invent. The same goes for everything else the
pipeline produces: the spec, the threat model, the SAST report, the verification report. They live
under `docs/ddw/` because that is the only place the agent is certain to find them at the moment it
needs them.

**Where they live is a convention, not a law.** One table defines every artifact path
(`ddw/rules/branches.instructions.md`), and a fork that wants them somewhere else changes them there.
If you do mirror them out, generate the mirror and keep the repo as the source of truth. Inverted,
the copy in the repo ages, and the agent builds against a PRD that stopped being true.

What is not negotiable is that work **starts** from one. A feature, a bug, a one-line change: if
nobody can say what "done" means, there is nothing for the pipeline to gate.

## Security is a phase, not a footnote

Two controls, at two moments, each catching what the other cannot:

| Control | Looks at | Phase | Blind to |
|---|---|---|---|
| **Threat modeling** | The design, before it exists | PLAN | Implementation bugs |
| **SAST** | The code, without running it | CODE | Business logic, authorization |

Both produce a **report**, not just a flag — including what you dismissed and why.

There is deliberately no dynamic scan in the pipeline. Running one properly needs a live environment
with credentials and data, which a tool inside your repo cannot honestly promise. A gate that cannot
be satisfied gets marked satisfied anyway, and one gate you can lie to is enough to make every other
gate a suggestion.

## What a gate is actually worth

A gate is a condition the state machine refuses to move past. That refusal is real: the transition is
rejected in code, outside the model, and so is a write of product source from a phase that forbids
it.

What each gate rests on is not uniform, and the difference is graded on purpose:

| Gate | What backs it |
|---|---|
| `define`, `spec`, `threat`, `sast`, `tests`, `verify` | A **receipt** naming that document's current bytes, written only by a validation run with zero FAILs |
| `commit` | **git**, asked directly — tracked changes still in the working tree contradict the claim |
| `pr` | **the forge**, asked through `gh` — the branch has a pull request or it does not |

None of these can be produced by saying so, and the check runs in the hook, so writing the state by
hand does not get around it. Edit the document after validating and its receipt stops matching: the
hash is of the bytes, not of the filename.

**What they do not attest is that the work is right, and that distinction is the whole design.** DDW
does not run your suite and does not scan your code. The `tests` receipt says the account of the run
is complete — runner, exact command, counts that add up, failures named, three coverage numbers
against a floor quoted from your project, skips explained. The `sast` receipt says the report judged
every catalogued category and did not declare PASSED above a Critical. **A complete report can still
be a false one.** What it can no longer be is absent, vague or arithmetically impossible — which is
what "the model's record" meant, and what `tests: true` used to be: one word, on a run nobody could
reproduce.

Where the line falls and what the industry calls this ladder is
[`RATIONALE.md` decision 16](RATIONALE.md#16-a-gate-is-an-attestation-and-they-are-not-all-the-same-strength).

---

## Minimal intervention

Classification records **how much of the run waits for you**, alongside the tier.

**`assisted`** is the default and is everything above: every arrow asks.

**`minimal`** stops the arrows asking. Nothing else changes — the same eight gates, the same
receipts, refused by the same hook over the same bytes. What goes away is being asked to approve a
transition whose evidence is already on disk, which is a rubber stamp, and rubber stamps are how
approvals come to mean nothing.

**What it costs:** nobody reads the tables. The receipts still refuse an incomplete PRD, an
unvalidated spec, a SAST report that never judged SSRF, a test run whose numbers do not add up — but
*complete* is not *true*, and the person who would have caught the difference is the one who stepped
out of the loop.

**Three things stop the run in either mode, and they are not configurable:**

1. **A decision nobody wrote down.** A ❌ the script names is a defect to fix; a question born of
   missing information is not. Inventing a requirement to clear a check is a worse defect than the
   one it silenced.
2. **A corrective loop at its ceiling** — `PRD loops`, `Spec loops`, CODE's three attempts.
3. **A corrupt state.**

Every transition taken without a human carries `"autonomy": "minimal"` in its history entry. A record
that reads the same for a run you watched and one that had nobody to watch it lies by omission.
