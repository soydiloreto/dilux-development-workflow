# Checks that cannot fail

Generated against the suite by `scripts/kill_map_ledger.py`, and **compared** by
CI rather than trusted: this file is what somebody has already looked at, not a
report nobody regenerates.

Every line is a `bad "…"` of `scripts/verify_install.sh` that **no fault in
`scripts/mutate.py` provokes**. That does not prove it cannot fail — it proves
nothing measures whether it can. Either write a fault that makes it fire, or say
here why there is not one.

A check that cannot fail reports green because it has no other thing to say.

<!-- 536 fault(s) across 25 shard(s) -->
- [ ] `$TOOL is missing — the checks that need it would skip, and a skip reads as a pass`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito.
- [ ] `F-PRD-09 is catalogued but the PRD validator never evaluates it`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `closed with commit but no pr`
      **Fixture reparado en esta rama**, todavía sin medir: mandaba el mismo input que su vecino porque `--gate` se rechaza en `--to IDLE`. La próxima corrida del mapa dice si ya se dispara.
- [ ] `node is missing — ${f#$SELF/} was NOT parsed; that is a gap, not a pass`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito.
- [ ] `python < 3.11 — the Codex TOML checks would skip in silence`
      **Entorno.** Depende de la versión del intérprete, que ninguna mutación cambia.
- [ ] `pyyaml is missing — frontmatter is the contract every tool reads; it must be validated`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito.
- [ ] `the commit-gate fixture never committed: the three checks below measure the fixture, not the gate`
      **Guardia de fixture.** Las dos condiciones que lo hacen fallar —`commit.gpgsign`, identidad de git— las neutraliza el propio fixture dos líneas antes, y nada en el repo instala hooks de git. No hay camino de producto que lo encienda.
- [ ] `the corrective loop returned to VERIFY on gates it had already invalidated`
      **Fixture reparado en esta rama**, todavía sin medir: no ganaba sus compuertas y se quedaba en DEFINE. La próxima corrida del mapa dice si ya se dispara.
- [ ] `the phase that writes source rewrote $TARGET — the guard exempts its own rulebook`
      **Check reparado en esta rama**, todavía sin medir: preguntaba en PLAN, donde el guardia de código fuente lo tapaba. Ahora pregunta en CODE, y tiene su fault.
- [ ] `the skill can block: an inference about someone else's stack became a gate`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the skill is gone — a repo's linter, CI commands and pre-commit go unnoticed again`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
- [ ] `the template still writes ACs the validator cannot match on`
      **Sin justificar.** Escribile un fault en `scripts/mutate.py`, o decí acá por qué no lo tiene.
