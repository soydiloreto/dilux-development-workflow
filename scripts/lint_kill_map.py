#!/usr/bin/env python3
"""Which check of `lint_method.py` does each fault provoke — the kill map, one
level down.

`scripts/verify_install.sh` has ONE check for the whole prose linter ("the
method's prose claims something the repo does not support"). So in
`docs/CHECKS-THAT-CANNOT-FAIL.md` the linter's thirty-odd `fail()` sites collapse
into a single line: as long as any fault keeps `lint_method.py` red, a check
inside it that stopped finding what it was written for goes on reporting green,
and the ledger says the check is covered. That is the exact defect the ledger
exists to catch, one layer below where it can see.

So this asks the same question the kill map asks, about the linter itself:

    apply each fault to a copy → run the linter → record WHICH message came out

What never comes out is a check of the linter that no fault provokes. That does
not prove it cannot fail — it proves nothing measures whether it can. Either
write a fault that makes it fire, or write here why there is not one. Same
contract as the other ledger, same reason.

    python3 scripts/lint_kill_map.py --repo .            # measure and compare
    python3 scripts/lint_kill_map.py --repo . --write    # regenerate the ledger

Exit 0 = every site either fires or carries a written reason. Exit 1 = a site
fires nothing and nobody has said why, or the ledger excuses a site that now
fires. Exit 2 = the instrument could not measure.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Lo único que se saltea: los faults sobre un `.py`. El linter no lee código —
# lee prosa, el grafo, los hooks de compactación y el SISTEMA DE ARCHIVOS — y
# correr los quinientos y pico multiplica por tres lo que tarda esto.
#
# La primera versión listaba en cambio las extensiones que el linter SÍ lee
# (`.md`, `.json`, `.sh`), y con eso se comía todos los faults que borran un
# DIRECTORIO: `delete("skills/ddw-test")` no termina en ninguna de las tres. Los
# dos guardias que ese fault existe para encender siguieron saliendo como «no
# los provoca nada» después de haberles escrito el fault, y por veinte minutos
# el hueco parecía del producto. Un filtro por lista blanca esconde lo que no
# previó; uno por lista negra deja pasar de más, que acá cuesta segundos.
SKIP_EXT = (".py",)

LEDGER_HEADER = """# Lint checks that cannot fail

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
"""


def sites_of(path):
    """Cada `fail(...)` de cada `check_*`, por LÍNEA.

    La primera versión de esto reconocía cada sitio por un trozo literal de su
    mensaje, y tenía dos agujeros que se midieron:

      · Un `fail()` con `%s` adentro NO imprime `%s`, imprime el valor. Tomando
        el format string entero como literal, ese sitio no puede matchear nunca
        y sale "no lo provoca ninguna mutación" con la mutación existiendo —
        pasó con el check del boot, que tiene la suya desde b605648. Es el mismo
        error de medición que el mapa de kills cometió cinco veces.
      · Partiendo por los placeholders, DIEZ sitios se quedaban sin ningún tramo
        literal largo: mensajes que son casi todo interpolación. Pedirle al
        ledger una excusa por ellos habría sido registrar como hueco del
        producto un techo del instrumento.

    Así que no se reconoce por texto: se instrumenta `fail` y se anota la línea
    desde la que se llamó. Un sitio nuevo entra a la cuenta el día que se
    escribe, diga lo que diga su mensaje.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    by_line = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("check_"):
            continue
        calls = sorted((n for n in ast.walk(node)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == "fail"), key=lambda n: n.lineno)
        for i, call in enumerate(calls):
            by_line[call.lineno] = f"{node.name}[{i}]"
    return by_line


def load(root, name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(root, rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def fault_target(apply_fn):
    """El archivo que el fault toca, leído de su propio probe."""
    probe = getattr(apply_fn, "probe", None)
    if probe and len(probe) > 1:
        return probe[1]
    return None


def lint_lines(tree, n):
    """Corre el linter sobre `tree` y devuelve las LÍNEAS de los `fail()` que
    salieron.

    El linter se importa, no se lanza como subproceso: así se le puede envolver
    `fail` y anotar desde dónde se llamó, que es lo único que identifica un
    sitio sin depender de cómo esté escrito su mensaje. De paso, quinientas
    corridas dejan de pagar quinientos intérpretes.
    """
    mod = load(tree, f"ddw_lint_{n}", "scripts/lint_method.py")
    hit = set()
    real = mod.fail

    def spy(where, msg):
        hit.add(sys._getframe(1).f_lineno)
        return real(where, msg)

    mod.fail = spy
    mod.FINDINGS.clear()
    argv = sys.argv
    sys.argv = ["lint_method.py", "--repo", tree]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            mod.main()
    finally:
        sys.argv = argv
        sys.modules.pop(f"ddw_lint_{n}", None)
    return hit


def measure(root, sites):
    mut = load(root, "ddw_mutate", "scripts/mutate.py")
    work = tempfile.mkdtemp(prefix="lintmap-")
    tree = os.path.join(work, "tree")
    shutil.copytree(root, tree,
                    ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__",
                                                  ".pytest_cache", ".ddw-sessions"))
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=e@x", "-c", "user.name=e",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "base"]):
        subprocess.run(cmd, cwd=tree, check=True, capture_output=True)

    if lint_lines(tree, 0):
        # Un árbol base sucio mide su propia suciedad: todo sitio que ya esté
        # saliendo cuenta como provocado por el primer fault que se aplique.
        print("FATAL: lint_method is not green on this tree, so nothing below would "
              "measure the faults.", file=sys.stderr)
        shutil.rmtree(work, ignore_errors=True)
        return None, 0, 0

    fired, ran, skipped = {}, 0, 0
    for n, (desc, apply_fn) in enumerate(mut.MUTATIONS, 1):
        target = fault_target(apply_fn) or ""
        if target.endswith(SKIP_EXT):
            skipped += 1
            continue
        problem = apply_fn(tree)
        if not problem:
            ran += 1
            for line in lint_lines(tree, n):
                name = sites.get(line)
                if name:
                    fired.setdefault(name, []).append(desc)
        subprocess.run(["git", "checkout", "-q", "--", "."], cwd=tree, check=True)
        subprocess.run(["git", "clean", "-qfd"], cwd=tree, check=True)
    shutil.rmtree(work, ignore_errors=True)
    return fired, ran, skipped


_LEDGER_LINE = re.compile(r"^- \[ \] `([^`]+)`", re.M)


def read_ledger(path):
    if not os.path.exists(path):
        return set()
    return set(_LEDGER_LINE.findall(open(path, encoding="utf-8").read()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), ".."))
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--write", action="store_true",
                    help="regenerate the ledger instead of comparing against it")
    args = ap.parse_args()
    root = os.path.abspath(args.repo)
    ledger_path = args.ledger or os.path.join(root, "docs/LINT-CHECKS-THAT-CANNOT-FAIL.md")

    sites = sites_of(os.path.join(root, "scripts/lint_method.py"))
    if not sites:
        print("FATAL: no fail() site could be read out of lint_method.py — a run that "
              "examined nothing is not a pass.", file=sys.stderr)
        return 2
    names = set(sites.values())

    fired, ran, skipped = measure(root, sites)
    if fired is None:
        return 2
    if ran == 0:
        print("FATAL: no fault touched a file the linter reads; nothing was measured.",
              file=sys.stderr)
        return 2

    naked = sorted(names - set(fired))
    print(f"lint_kill_map: {len(fired)} of {len(names)} fail() site(s) are provoked by some "
          f"fault ({ran} fault(s) run, {skipped} skipped for touching a file the linter "
          f"never reads)")

    if args.write:
        body = [LEDGER_HEADER, f"<!-- {len(names)} site(s), {ran} fault(s) measured -->\n"]
        old = open(ledger_path, encoding="utf-8").read() if os.path.exists(ledger_path) else ""
        for name in naked:
            reason = ""
            m = re.search(r"^- \[ \] `%s`\n( +.*)$" % re.escape(name), old, re.M)
            if m:
                reason = m.group(1)
            body.append(f"- [ ] `{name}`\n{reason or '      **Sin razón escrita todavía.**'}")
        open(ledger_path, "w", encoding="utf-8").write("\n".join(body) + "\n")
        print(f"  wrote {ledger_path} — {len(naked)} site(s) with no fault")
        return 0

    excused = read_ledger(ledger_path)
    unexcused = [n for n in naked if n not in excused]
    stale = sorted(excused - set(naked))
    for name in unexcused:
        print(f"  ✗ {name}\n      nothing provokes it and the ledger does not say why")
    for name in stale:
        print(f"  ✗ {name}\n      the ledger excuses it, but a fault provokes it now — "
              "delete the entry, or the excuse outlives the reason")
    if unexcused or stale:
        return 1
    print(f"  every site either fires or carries a written reason ({len(naked)} excused)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
