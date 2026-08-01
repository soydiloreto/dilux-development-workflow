# AI policy

Rules for how AI agents and AI-generated code may be used in this project, by
maintainers and by contributors. **You are bound by these the moment you open a
PR or push a commit, whether or not you read them.**

Yes, this is a framework for driving AI agents, with a policy about AI agents.
That is not a joke at anyone's expense — it is the reason the policy has to be
stricter here than in an ordinary repository, and the next section explains why.

## TL;DR

Use AI all you want. **You** are still responsible for every line. And in this
repository, "every line" includes lines that will be loaded straight into other
people's agent sessions.

## What makes this repo different

Most of this product is **prose that becomes instructions**. `ddw/rules/*.md`,
`skills/*/SKILL.md`, `ddw/orchestrator.md` — none of it executes. All of it
is read by a model, in someone else's repository, while that model decides
whether it may write source code.

Three consequences, and they are the whole reason this file exists:

**A wrong line here does not crash. It changes behaviour, quietly.** A rule that
cites a validation ID that no longer exists, a phase that promises an artifact
nothing writes, a gate name the graph never carries — nothing goes red, the model
simply follows the wrong instruction. That is why `scripts/lint_method.py`
exists, and why "it reads fine" is not review.

**An injected instruction here is a supply-chain attack.** A line in a rule file
that tells a model to ignore a gate, exfiltrate a file, or approve its own work
runs inside **every installation that upgrades**. There is no sandbox between
this repository's prose and a stranger's coding agent. Rule 4 below is not
theatre.

**The gates are the product.** A change that makes a check pass without making
the underlying guarantee true has broken the only thing anyone is buying.

## Rules

1. **You sign the commit, you own the code.** It does not matter whether you
   typed it or whether Claude / Copilot / GPT / a Markov chain wrote it. If a
   regression is traced back to your commit, you are the one who fixes it. "The
   AI wrote it" is not a defence and not a triage answer.

2. **You read what you commit.** Line by line, prose included. A generated rule
   file is *more* dangerous than generated code, not less, because nothing will
   fail if it is subtly wrong. If you do not understand what a paragraph will
   make a model do, you do not have permission to push it.

3. **The suite does not pass because the model said so.** It passes because
   `bash scripts/verify_install.sh` says so. Run it, `scripts/lint_method.py`,
   `scripts/check_versions.py` and `python3 scripts/mutate.py` locally before you
   push. CI is a safety net, not a substitute for thinking.

4. **No prompt-injection vectors anywhere in this repository.** Not in commit
   messages, not in comments, not in docs, and above all **not in `ddw/`**. No
   `<system>`, no "ignore previous instructions", no Unicode trickery, no
   embedded "your job is to approve this PR". Here this is not just about
   steering a reviewer's tooling: `ddw/` is copied verbatim into other people's
   repositories and loaded into their agents. A PR doing this is rejected on
   sight; the second time, the contributor is banned; the third time it gets an
   issue written about it for posterity.

5. **Don't paste secrets at AI services.** Not at OpenAI, not at Anthropic, not
   at GitHub. No tokens, no keys, no customer code. Even if the service claims it
   does not train on your data — paste it once and you have already exfiltrated.
   Rotate immediately if you slip.

6. **Don't ship hallucinated hooks.** Every adapter describes somebody else's
   product: an event shape, a hook name, the key a verdict has to use. A model
   will happily invent a plausible one, the suite will agree with it — because
   the test was written from the same assumption — and the adapter will look
   installed while enforcing nothing. **Verify against the tool's own
   documentation, then drive it for real** (`scripts/acceptance.md`) and record
   the result. This is the single most common way a change here can be wrong and
   green at the same time.

7. **Never make a failing check pass by weakening it.** Not by lowering
   `EXPECT_CHECKS`, not by deleting a mutation, not by softening a fixture until
   only the fix's own reasoning is left standing. If a mutation survives, the
   hole is a missing check — the mutation is the measurement, and adjusting the
   measurement to fit the result is the one thing this repository cannot
   tolerate. A model asked to "make CI green" will reach for exactly this. You
   are the one who has to not let it.

8. **Behaviour changes ship with a check and a mutation.** The check goes red
   without your fix; the mutation dies with it and survives without it. Verify
   both directions — a check that passes for the wrong reason is worth nothing,
   and this repository has shipped several. `docs/RATIONALE.md` §10 explains why
   the mutation carries as much weight as the fix.

9. **Commits here follow the convention DDW itself prescribes.** Gitmoji,
   conventional type, and the `AI-assisted: yes` / `AI-full: yes` trailer that
   `ddw/rules/commits.instructions.md` calls mandatory. Never `Co-Authored-By` —
   the method rules that out by name, and the method applies to the method.
   The commit message says what *the change* does; the trailer is the whole of
   the provenance record, and no prefaces, apologies or narration go in the body.

10. **Don't volume-spam the project with model-generated PRs.** Twenty drive-by
    PRs of speculative refactors are not contributions, they are a denial of
    service against review time. Pick a real defect, fix it, send one good PR.

11. **The bar is the same as a human.** A human contributor whose PR had a
    weakened check, an unverified adapter claim, and a commit-message essay would
    be told to slow down. The model gets the same treatment, via you.

## What you may absolutely do

- Use Claude Code, Copilot, Cursor, Codex, Gemini or OpenCode for autocomplete,
  refactoring, debugging, exploring the codebase, drafting checks, drafting
  mutations, drafting commit messages, drafting PR descriptions. All fine. The
  constraint is on what reaches `main`, not on how you got there.
- Ask a model to explain why a check exists, or to find the mutation that covers
  a guard. That is what the comments in this repository are written for.
- Use it to hunt for defects. The audits that produced most of what is in
  `mutate.py` were adversarial reviews run with an agent. It is very good at
  that, and `docs/RATIONALE.md` §10 says exactly where it stops being good at it.

## What you may not do

- Open a PR you did not read.
- Open a PR you do not understand.
- Open a PR whose suite you did not run.
- Open a PR with a rule file you cannot defend when a human asks "what will a
  model do differently after reading this?"
- Open a PR that adjusts `EXPECT_CHECKS` or the mutation list without saying, in
  the description, why the count moved.
- Pipe review feedback into a model and round-trip the response back into the PR
  without reading it. It produces the most exhausting kind of thread, where a
  human reviewer is conversing with a chatbot via a person.

## Maintainer use

The maintainer (Pablo Ariel Di Loreto,
[@soydiloreto](https://github.com/soydiloreto)) develops this project with Claude
Code, **using DDW**. The same rules apply. The maintainer is responsible for every
commit on `main` regardless of how it was authored: if a model-driven session
lands a bug, that is on the maintainer, not the model.

Two things worth saying out loud, because they cut against my own interest:

**The commits before v1.0.0 did not carry the trailer this project demands.** The
public history starts at the extraction commit, which does; from there on the
rule applies to this repository as it does to every repository that installs it.
A framework that exempts itself from its own commit convention is making an
argument against itself.

**Adversarial review found things the suite could not.** Several defects fixed
before publication — an installer that never noticed it was upgrading, a Gemini
adapter that never reached the project's context, a schema promising a field no
phase asked for — were found by a human asking "and what if…", not by any check.
That is the honest division of labour: the automation protects against
regression, and it does not discover. Anyone who reads the mutation score as
"there are no bugs" has misread it.

## When something goes wrong

1. Roll forward with a fix. Don't blame the tool — write the fix.
2. Open an issue saying what went wrong **and why the existing checks did not
   catch it**. The second half is the valuable one.
3. If the gap is in the quality gates, strengthen the gate: a new check plus the
   mutation that proves it can fail. The fix for "the model produced a wrong rule"
   is a lint rule that catches that class, not a ban on the model.

## Why this policy exists

DDW's entire thesis is that **a rule in a prompt is a promise and a rule enforced
by code is a guarantee**. A project that argues that, and then accepts
unreviewed model output into the prose that becomes other people's prompts, has
refuted itself in public.

This is not anti-AI. It is anti-laziness — and if anything the policy assumes you
*will* be using AI tools, since the repository is a tool for doing exactly that.
That is precisely why it has to say who is responsible when the tool is wrong.
