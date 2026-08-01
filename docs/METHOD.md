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
6. **RELEASE** — CHANGELOG, PR, ticket, closeout.

Every arrow needs your explicit approval. The machine closes the phase, shows you a summary, and
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

And you can always **walk away**. Abandon a ticket, or pause it for later, from any phase, owing
nothing — as long as you say which one it is. The one exception is RELEASE, where nothing is left to
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
| `define` | A **receipt** naming the PRD's current bytes, written only by a validation run that passed |
| `commit` | **git**, asked directly — tracked changes still in the working tree contradict the claim |
| `spec`, `threat`, `verify`, `tests`, `sast`, `pr` | The model's record of what it did |

The two on top cannot be produced by saying so, and the check runs in the hook, so writing the state
by hand does not get around it. The rest are records: the machine enforces that the claim exists,
before the move, in the phase that owns it, and that it lands in an append-only history. **It does
not run your test suite**, and a framework that implied otherwise would be doing the thing this one
was built to stop.

That is worth considerably more than a prompt and less than a test run. Where the line falls, why
`tests` and `sast` stay on the lower rung deliberately, and what the industry calls this ladder, is
[`RATIONALE.md` decision 16](RATIONALE.md#16-a-gate-is-an-attestation-and-they-are-not-all-the-same-strength).
