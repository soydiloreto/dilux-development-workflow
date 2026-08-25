---
name: ddw-commit
description: >
  Creates a commit following Gitmoji + Conventional Commits, with mandatory AI attribution.
  Trigger: /ddw-commit, when a DDW phase closes and has artifacts to commit (DEFINE, PLAN, CODE,
  DISCOVERY, CLOSEOUT).
---

# Skill: /ddw-commit

## Description
Creates a commit following Gitmoji + Conventional Commits, with mandatory AI attribution.

## Inputs
- The staged changes in git.
- `.ddw-state.json` for the ticket and tier.
- `.ddw/rules/commits.instructions.md` for the format and the gitmoji reference table.

## Execution Protocol

1. Run `git status` and `git diff --staged`.
2. If nothing is staged, look at the working tree:
   - **Dirty** → ask the user which files to include.
   - **Clean, in CLOSEOUT** → there is nothing left to commit, because the earlier phases already
     committed their own artifacts. Do NOT manufacture an empty commit: run
     `git log <base>..HEAD --oneline`, show the branch's commits, and report the gate as satisfied
     by them.
   - **Clean, in any other phase** → this phase produced nothing to commit. Say so and stop.
3. Check there are no files carrying secrets (.env, credentials).
4. Check the gates **this phase's commit depends on**, and note that CODE commits twice for
   different reasons:
   - **A block commit in CODE** — code plus its tests, as each block passes its reviews and its
     tests, which is what `.ddw/rules/commits.instructions.md` mandates — depends on **that
     block's** reviews and tests, not on the phase gates. `tests` and `sast` are earned over the
     whole phase and are still false while the blocks are being committed one at a time; demanding
     them here forbade the very commit the rules require.
   - **The phase's closing commit in CODE**, the one taken before leaving for VERIFY, is where
     `tests` and `sast` must both be `true`.
   - DEFINE, PLAN and DISCOVERY commit documentation and depend on no gate — at the moment they
     commit, the gate they are about to earn is not set yet, so demanding it would deadlock.
5. Analyze the changes to classify the type and scope.
6. Write the commit message with a gitmoji (see `.ddw/rules/commits.instructions.md` for the
   reference table):

```
<gitmoji> <type>(<scope>): <description in the imperative> (<ticket, if there is one>)

<executive summary (if the change is large)>

Refs: <ticket>
AI-assisted: yes
```

   - Pick the gitmoji that describes the change (e.g. ✨ feat, 🐛 fix, 🚑 urgent fix, 🔒
     security, 🔥 delete, ⚡ perf). The full palette is available in any tier — the tier only
     provides the default when nothing fits better.
   - Include the tracker ticket in parentheses at the end of the first line if
     `.ddw-state.json.tracker` is not null.

7. Write that exact message to `.ddw-work/commit-message.txt` and **present it — in full.**
   Under `assisted`, **end your turn**: the file is the message, it is what will be committed, so
   what they read and what lands are the same bytes, and the gate holds the commit until that
   exact text was on screen before their answer. Under `minimal`, the showing still happens and
   the asking does not (`.ddw/orchestrator.md` § Autonomy — a commit is local and reversible, not
   one of the acts that keep their confirmation in both modes): present the message and continue
   to step 8 in the same response. This step used to read as unconditional, and a live `minimal`
   run stopped at every one of its commits waiting for an "ok" the mode had already given —
   `assisted` with different words, in the exact place the orchestrator's exemption was not.
8. `git commit -F .ddw-work/commit-message.txt` — under `assisted`, only after they answer.
9. **NEVER push automatically.** Ask the user.

## Rules

Format, the gitmoji palette, trailers and prohibitions live in
`.ddw/rules/commits.instructions.md`, which this skill already loads as an input. **They are not
restated here** — a rule written twice is a rule that will be changed once.

The two worth repeating, because they are about *this* skill's behaviour:

- **Never `git add .ddw-state.json`.** It is the pipeline's runtime, it is gitignored, and a
  committed state file makes someone else's checkout claim your phase.
- **Never push automatically.** Ask.

- **Step 7 is enforced, not promised.** While `autonomy` is `assisted`, the commit gate reads
  `.ddw-work/commit-message.txt` and allows the commit only if that exact text was on disk
  before the user's last turn. Showing the message and creating the commit therefore cannot happen
  in one response, and a message that changed after they read it is refused — the file is compared,
  not trusted. It was a sentence alone for a long time, and the pre-write hook covered only the
  write tools, so the one act the pipeline never checked was the one that writes history. Presenting
  the message is still yours: the gate can hold the commit, it cannot show them the reasoning.

## Updating .ddw-state.json
- `gates.commit` → `true` **when this commit is the one a closeout edge depends on — that is, in CLOSEOUT for any tier, and at the DISCOVERY closeout. Anywhere else, do not touch `gates`.** The closeout checks it
  before resetting to IDLE.
- **In any other phase, do not touch `gates`.** DEFINE, PLAN, CODE and DISCOVERY commit their own
  artifacts (see `.ddw/rules/commits.instructions.md`), and if any of them set `commit` the closeout
  gate would be true from the first phase onward and would stop meaning anything. The gate does not
  say "a commit exists" — it says "the closeout step was completed".

## Language

Write the commit message in the language the user is working in, keeping the Conventional Commits
type, the scope and the trailers as specified above.
