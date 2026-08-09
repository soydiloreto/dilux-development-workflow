# Lint checks that cannot fail

Generated against `scripts/lint_method.py` by `scripts/lint_kill_map.py`, and
**compared** by CI rather than trusted.

The suite has one check for the whole prose linter, so in
[CHECKS-THAT-CANNOT-FAIL.md](CHECKS-THAT-CANNOT-FAIL.md) every check inside it
collapses into a single line: while any fault keeps the linter red, a check of
the linter that stopped finding what it was written for still reports green.
This file is that question asked one level down.

Every line is a `fail(…)` of `lint_method.py` that **no fault in
`scripts/mutate.py` provokes**. Either write a fault that makes it fire, or say
here why there is not one.

<!-- 44 site(s), 206 fault(s) measured -->

- [ ] `check_boot_reads_every_state_field[0]`
      **Guardia de forma, y la forma es una tabla entera.** Salta cuando
      `ddw/rules/state.instructions.md` existe y no se le puede leer NI UN campo
      —la tabla dejó de tener la forma `| \`campo\` | …`—, y eso son todas sus
      filas a la vez, no una línea. Un fault de una edición no puede expresarlo,
      y uno que reescriba la tabla completa mide el fault, no el check. El caso
      de al lado —el archivo directamente ausente— sí tiene fault y sale por
      otra rama.
- [ ] `check_rationale[1]`
      **Guardia de forma, ídem.** Pide que `docs/RATIONALE.md` exista y no tenga
      NINGUNA decisión numerada: hoy son veinte encabezados `## N.`, así que el
      fault tendría que borrarlos todos. Que el archivo falte lo cubre el sitio
      anterior, que sí tiene fault.
