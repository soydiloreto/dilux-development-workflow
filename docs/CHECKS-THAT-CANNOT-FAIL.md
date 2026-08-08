# Checks that cannot fail

Generated against the suite by `scripts/kill_map_ledger.py`, and **compared** by
CI rather than trusted: this file is what somebody has already looked at, not a
report nobody regenerates.

Every line is a `bad "…"` of `scripts/verify_install.sh` that **no fault in
`scripts/mutate.py` provokes**. That does not prove it cannot fail — it proves
nothing measures whether it can. Either write a fault that makes it fire, or say
here why there is not one.

A check that cannot fail reports green because it has no other thing to say.

<!-- 471 fault(s) across 25 shard(s) -->
- [ ] `$TOOL is missing — the checks that need it would skip, and a skip reads as a pass`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito — y ahí un skip cuenta aparte.
- [ ] `$label: a forged state produced no report, and its post hook cannot block either`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `.ddw/skills should NOT exist (adapters place them)`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `.gitignore was mangled by the uninstall`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `AGENTS.md was either destroyed or left with a DDW block pointing at nothing`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `CLAUDE.md carries the instructions too — two copies to keep in step, and one will drift`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `CLAUDE.md was left behind as an empty husk`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `Copilot's hook config changed shape — recheck what reaches the gate`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `DDW's hooks are still wired to scripts that were just deleted — every session fails on a missing command`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `DEFINE->CODE should need gates`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `DISCOVERY closed without commit+pr`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `F-PRD-09 is catalogued but the PRD validator never evaluates it`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `IDLE->DEFINE should be rejected`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `NOT idempotent`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `OpenCode: an illegal transition was ALLOWED through the plugin`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `QUICK-FIX DEFINE->CODE should need the brief gate`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `QUICK-FIX should have no PLAN phase`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `W-SAST-01 stopped firing on a report with three undocumented Low findings`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `'mkdir .ddw' turns every Claude hook off — one command, no privileges, and the refusal becomes exit 0`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `'rm .ddw-installed.json' unseals every hook script and leaves a tampered repo reading like a clean one`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a FIX reached CODE with no rollback plan and nothing said so`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a block with no tests sailed through the mechanical spec validator`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a blocked phase rewrote $TARGET — the guard exempts its own rulebook`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a branch resumed days later is worked on without anyone checking how far behind it is`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a component analysed against five of the six STRIDE categories passed`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a corrupt state disabled the guard — a phase it cannot read is one it cannot vouch for`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a first install says neither that it is installing nor that it is updating`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a hook writes its own compaction reminder — the method's message now has a fork`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a lint result under its own '## Lint' heading is reported as no lint result at all`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a rule file can be rewritten while its own version stands still`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a symlink in the path bypassed the FSM entirely`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `a typed-but-wrong path emptied the check and allowed the write`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `adapter recipes`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `an adapter installs its hooks somewhere the validator does not seal`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `an ambiguous verb sailed through the mechanical validator`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `closed WITHOUT commit+pr`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `closed with commit but no pr`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `corrective loop reused cleared gates`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `coverage written as '| Line | 88% |' — the shape every coverage tool prints — read as absent`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `expected $EXPECT_ADAPTERS adapters, found $(n`
      **Conteo fijado.** Sólo falla borrando un archivo del árbol: es una mutación de FORMA (`delete()`), no de contenido, y la lista todavía no tiene ninguna. Queda anotado como pendiente, no como imposible.
- [ ] `expected $EXPECT_AGENTS agents, found $(n`
      **Conteo fijado.** Sólo falla borrando un archivo del árbol: es una mutación de FORMA (`delete()`), no de contenido, y la lista todavía no tiene ninguna. Queda anotado como pendiente, no como imposible.
- [ ] `expected $EXPECT_RULES rule files, found $(n`
      **Conteo fijado.** Sólo falla borrando un archivo del árbol: es una mutación de FORMA (`delete()`), no de contenido, y la lista todavía no tiene ninguna. Queda anotado como pendiente, no como imposible.
- [ ] `expected $EXPECT_SKILLS skills, found $(n`
      **Conteo fijado.** Sólo falla borrando un archivo del árbol: es una mutación de FORMA (`delete()`), no de contenido, y la lista todavía no tiene ninguna. Queda anotado como pendiente, no como imposible.
- [ ] `git pull is not ruled out, so the agent will reach for it and merge on a tree it did not check`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `graphs with no format_version are refused — that is every repo that installed DDW earlier`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `installing over a pre-existing AGENTS.md destroyed it`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `inventing a 'pause:' entry in the state file is a key to any phase, with no gates and no ticket`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `leaving 'ticket' off the entries turns the whole evidence layer off — the forger holds the switch`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `marketplace.json fails validation — /plugin marketplace add will refuse it`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `missing from the repository root:${MISSING_FRONT}`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `no ddw_method in lib/guard.sh — every hook resolves the method its own way again`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `node is missing — ${f#$SELF/} was NOT parsed; that is a gap, not a pass`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito — y ahí un skip cuenta aparte.
- [ ] `one of the four: an unknown tool writes the state unexamined, 'gh pr view' takes any PR, the tier chain is inverted, or the linter stopped reading the prose`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `package.json's entry point does not resolve to a file — the npm install would hook nothing`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `python < 3.11 — the Codex TOML checks would skip in silence`
      **Entorno.** Depende de la versión del intérprete, que ninguna mutación cambia.
- [ ] `pyyaml is missing — frontmatter is the contract every tool reads; it must be validated`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito — y ahí un skip cuenta aparte.
- [ ] `reached IDLE off-graph without declaring the abandon`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `reports false collisions`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `skill frontmatter`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `syntax error: ${f#$SELF/}`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the Copilot uninstall leaves user-level hooks pointing at nothing; measured live, that denies ALL tools in ALL repos`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the attribution check rejects a commit that carries the trailer it asks for`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the check total is not pinned (EXPECT_CHECKS=$EXPECT_CHECKS) — set it to $((CHECKS + 1)) at the top of this file`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the commit-gate fixture never committed: the three checks below measure the fixture, not the gate`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the corrective loop returned to VERIFY on gates it had already invalidated`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the drop-in boot carries the plugin's prohibitions — noise for the install that chose files`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the heading warning fires on a file created from DDW's own template`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the installer rewrote the user's own AGENTS.md instead of reporting what was missing`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the manifest is still inside .ddw/, which is what made the method differ`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the method survived an uninstall`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the nudge points at .ddw/orchestrator.md, which does not exist under a plugin`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the pr gate reads a network failure as a verdict, or takes a closed PR as an open one`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the record that says nobody was watching cannot be written by the sanctioned path`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the skill can block: an inference about someone else's stack became a gate`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the skill is gone — a repo's linter, CI commands and pre-commit go unnoticed again`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the spec validator rejects a sound spec or writes no receipt — the spec gate has nothing to rest on`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the template still writes ACs the validator cannot match on`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the test-report validator rejects a complete report or writes no receipt`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the threat validator rejects a sound model or writes no receipt`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the upgrade overwrote AGENTS.md — the user's stack and conventions are gone`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the user-level hook double-judges a drop-in repo`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the verify validator rejects a complete verdict or writes no receipt`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `validate_$RCP_V.py returned a verdict for a tier whose phase does not exist`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
