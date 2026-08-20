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

<!-- 56 site(s), 234 fault(s) measured -->

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
- [ ] `check_autonomy_prose_matches_the_hook[0]`
      **Rama defensiva sobre el instrumento, no sobre el producto.** Salta si
      `ddw/scripts/validate-transition.py` no se puede importar, que es la
      condición en la que ningún check del linter mide nada y la suite entera ya
      está roja por otras cien razones. Un fault que la provoque mide el fault.
- [ ] `check_autonomy_prose_matches_the_hook[1]`
      **Pide un fault en un `.py`, y el mapa los saltea por construcción**
      (`SKIP_EXT = (".py",)` en `scripts/lint_kill_map.py`: este check es el
      primero del linter que lee código y no prosa). Lo que el sitio afirma —que
      el guard refusa la segunda flecha bajo `assisted`— sí está medido, una
      capa más abajo, por `test_dos_flechas_en_un_turno_son_rechazadas`. Lo que
      queda sin fault es el AVISO del linter, no la conducta.
- [ ] `check_autonomy_prose_matches_the_hook[2]`
      **Guardia de forma.** Salta cuando `ddw/orchestrator.md` no tiene sección
      `## Autonomy` en absoluto — borrar la sección entera, no una línea. Un
      fault de una edición no puede expresarlo, y uno que la borre mide el
      fault.
- [ ] `check_autonomy_prose_matches_the_hook[4]`
      **El mismo techo que `[1]`**: la dirección inversa del mismo par (la
      prosa dice que el hook exceptúa `minimal` y el guard refusa igual) también
      necesita tocar el `.py` que el mapa saltea. La conducta está medida por
      `test_en_minimal_las_flechas_no_esperan`.
- [ ] `check_minimal_exemption_reaches_the_phase_rules[0]`
      **Guardia de forma, y la forma son seis routers a la vez.** Salta cuando
      NINGUNA salida del orquestador se declara exenta bajo `minimal`, o sea
      seis ediciones en un fault. La que importa —una fase que sí está exenta y
      cuyo archivo de reglas no lo dice— es el sitio de al lado, y ese sí tiene
      su fault.
