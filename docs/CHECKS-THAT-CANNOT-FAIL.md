# Checks that cannot fail

Generated against the suite by `scripts/kill_map_ledger.py`, and **compared** by
CI rather than trusted: this file is what somebody has already looked at, not a
report nobody regenerates.

Every line is a `bad "…"` of `scripts/verify_install.sh` that **no fault in
`scripts/mutate.py` provokes**. That does not prove it cannot fail — it proves
nothing measures whether it can. Either write a fault that makes it fire, or say
here why there is not one.

A check that cannot fail reports green because it has no other thing to say.

<!-- 541 fault(s) across 25 shard(s) -->
- [ ] `$TOOL is missing — the checks that need it would skip, and a skip reads as a pass`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito — y ahí un skip se cuenta aparte y no suma a un verde.
- [ ] `node is missing — ${f#$SELF/} was NOT parsed; that is a gap, not a pass`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito — y ahí un skip se cuenta aparte y no suma a un verde.
- [ ] `python < 3.11 — the Codex TOML checks would skip in silence`
      **Entorno.** Depende de la versión del intérprete, que ninguna mutación cambia.
- [ ] `pyyaml is missing — frontmatter is the contract every tool reads; it must be validated`
      **Entorno.** Sólo falla si la herramienta no está en la máquina, y ninguna mutación del árbol puede provocar eso. Su valor está en el CI, que la instala a propósito — y ahí un skip se cuenta aparte y no suma a un verde.
- [ ] `the commit-gate fixture never committed: the three checks below measure the fixture, not the gate`
      **Guardia de fixture.** Las dos condiciones que lo hacen fallar —`commit.gpgsign` y la identidad de git— las neutraliza el propio fixture dos líneas antes, y nada en este repo instala hooks de git. No hay camino de producto que lo encienda.
- [ ] `the template still writes ACs the validator cannot match on`
      **Fault escrito en esta rama**, todavía sin medir en la nube: la palabra `SHALL` aparece cuatro veces en el skill y el check pregunta si está en el archivo, así que hacía falta romper las cuatro. Verificado en local: 1/1.
