#!/usr/bin/env python3
"""El libro de cuentas de los checks que ningún fault caza.

`scripts/mutate.py --kill-map` anota, por cada fault, QUÉ check de la suite lo
cazó. Cruzado con todo `bad` que `scripts/verify_install.sh` sabe decir, lo que
queda son los checks que ningún fault provoca. De ésos no se sabe si pueden
fallar — y un check que no puede fallar informa verde por no saber decir otra
cosa, no porque haya mirado algo. Cinco shippearon en este repositorio: se
buscaban a sí mismos, y aparecieron de casualidad corriendo mutaciones.

Este archivo NO es un reporte. Un reporte generado que se commitea y nadie
regenera miente a las dos semanas, y una afirmación sin respaldo es exactamente
lo que el resto de este repositorio persigue. Es una EXPECTATIVA: la lista que
alguien ya miró, con la razón al lado, y el CI la compara contra la realidad.

  · Aparece uno que no está en la lista  → rojo. Se escribe por qué, o se le
    escribe un fault.
  · Desaparece uno que está en la lista  → rojo. Ya se puede medir; sale.

Es el idioma de las supresiones de SAST, y por el mismo motivo: no prohíbe
nada, obliga a decirlo en voz alta.

    python3 scripts/kill_map_ledger.py --parts <dir> --ledger docs/CHECKS-THAT-CANNOT-FAIL.md
    python3 scripts/kill_map_ledger.py --parts <dir> --ledger <f> --write   # regenerar
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITE = os.path.join(ROOT, "scripts", "verify_install.sh")
HEAD = """# Checks that cannot fail

Generated against the suite by `scripts/kill_map_ledger.py`, and **compared** by
CI rather than trusted: this file is what somebody has already looked at, not a
report nobody regenerates.

Every line is a `bad "…"` of `scripts/verify_install.sh` that **no fault in
`scripts/mutate.py` provokes**. That does not prove it cannot fail — it proves
nothing measures whether it can. Either write a fault that makes it fire, or say
here why there is not one.

A check that cannot fail reports green because it has no other thing to say.

"""


def declared_bads(text):
    """Todo `bad "…"` que la suite sabe decir."""
    return {m.group(1).strip() for m in re.finditer(r'\bbad\s+"((?:[^"\\]|\\.)*)"', text)}


def fired_from(parts_dir):
    """Los checks que cazaron algo, uniendo los parciales de cada shard."""
    fired, seen_faults = set(), 0
    files = sorted(f for f in os.listdir(parts_dir) if f.endswith(".json"))
    if not files:
        raise SystemExit("kill_map_ledger: no hay parciales en %s — una corrida que no "
                         "examinó nada no es un pase" % parts_dir)
    for name in files:
        with open(os.path.join(parts_dir, name), encoding="utf-8") as fh:
            part = json.load(fh)
        for killers in (part.get("kills") or {}).values():
            seen_faults += 1
            fired |= set(killers if isinstance(killers, list) else [killers])
    if seen_faults == 0:
        raise SystemExit("kill_map_ledger: los parciales no registran un solo fault")
    return fired, seen_faults, len(files)


def _longest_literal(msg):
    """El tramo literal más largo de un mensaje declarado.

    Comparar el mensaje ENTERO no sirve, y no por las variables: el shell se
    come pedazos. `bad "inventing a 'pause:' entry…"` sale impreso como
    «inventing a  entry…», sin lo entrecomillado. Exigir el texto completo daba
    ese check por nunca disparado cuando el fault 454 lo dispara — la tercera
    vez en esta sesión que un número suena a hallazgo y mide el formateo.

    El tramo más largo es distintivo sin ser frágil: sobrevive a que el shell
    coma un pedazo por cualquiera de sus dos causas, y no es tan corto como para
    matchear cualquier cosa.
    """
    parts = re.split(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\d+|'[^']*'|\\?\"", msg)
    best = max((p.strip() for p in parts), key=len, default="")
    return best if len(best) >= 12 else ""


def _as_pattern(msg):
    """El mensaje declarado, como expresión: cada `$VAR` es lo que se interpola.

    Comparar por el prefijo hasta el primer `$` parece razonable y no lo es:
    un mensaje que EMPIEZA con una variable —«$label blocks…», y hay muchos—
    tiene prefijo vacío, y todo mensaje de prefijo vacío contaba como nunca
    disparado. La primera corrida real dijo 92 y una parte era eso: otro número
    que suena a hallazgo y mide el formateo. Ahora la variable es un comodín y
    lo que se compara es la forma entera.
    """
    parts = re.split(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\d+", msg)
    rx = ".*".join(re.escape(p) for p in parts if p != "")
    return re.compile(rx if rx else r"(?!x)x")   # sin literales, no matchea nada


def never_fired(declared, fired):
    """Los `bad` que ninguna línea ✗ observada satisface."""
    out = []
    for msg in sorted(declared):
        pat = _as_pattern(msg)
        if any(pat.search(f) for f in fired):
            continue
        lit = _longest_literal(msg)
        if lit and any(lit in f for f in fired):
            continue
        out.append(msg)
    return out


def read_ledger(path):
    if not os.path.exists(path):
        return None
    entries = set()
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^- \[( |x)\] `(.+?)`\s*$", line.rstrip())
        if m:
            entries.add(m.group(2))
    return entries


def render(entries, previous_reasons, faults, shards):
    lines = [HEAD, "<!-- %d fault(s) across %d shard(s) -->\n" % (faults, shards)]
    for msg in sorted(entries):
        lines.append("- [ ] `%s`\n" % msg.replace("`", "'"))
        reason = previous_reasons.get(msg)
        lines.append("      %s\n" % (reason or "**Sin justificar.** Escribile un fault en "
                                               "`scripts/mutate.py`, o decí acá por qué no lo "
                                               "tiene."))
    return "".join(lines)


def reasons_from(path):
    out, current = {}, None
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^- \[( |x)\] `(.+?)`\s*$", line.rstrip())
        if m:
            current = m.group(2)
        elif current and line.startswith("      "):
            out[current] = line.strip()
            current = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True, help="directorio con los kill-map-*.json")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--write", action="store_true", help="regenerar en vez de comparar")
    args = ap.parse_args()

    suite = open(SUITE, encoding="utf-8").read()
    declared = declared_bads(suite)
    fired, faults, shards = fired_from(args.parts)
    dead = set(never_fired(declared, fired))

    with open("kill-map-merged.json", "w", encoding="utf-8") as fh:
        json.dump({"declared": len(declared), "fired": sorted(fired),
                   "never_fired": sorted(dead), "faults": faults, "shards": shards},
                  fh, indent=2)

    print("%d de %d `bad` se dispararon con algún fault; %d no."
          % (len(declared) - len(dead), len(declared), len(dead)))

    if args.write:
        os.makedirs(os.path.dirname(args.ledger) or ".", exist_ok=True)
        with open(args.ledger, "w", encoding="utf-8") as fh:
            fh.write(render(dead, reasons_from(args.ledger), faults, shards))
        print("escrito %s con %d entrada(s)" % (args.ledger, len(dead)))
        return 0

    known = read_ledger(args.ledger)
    if known is None:
        print("\nNo existe %s. Generalo con --write y justificá cada línea." % args.ledger,
              file=sys.stderr)
        return 1

    new = sorted(dead - known)
    gone = sorted(known - dead)
    if not new and not gone:
        print("el libro de cuentas describe la suite: %d entrada(s)." % len(known))
        return 0
    if new:
        print("\n%d check(s) que ningún fault caza y no están en el libro. Escribiles un "
              "fault, o el motivo:" % len(new), file=sys.stderr)
        for m in new:
            print("  + %s" % m[:110], file=sys.stderr)
    if gone:
        print("\n%d entrada(s) del libro que YA se pueden medir. Sacalas:" % len(gone),
              file=sys.stderr)
        for m in gone:
            print("  - %s" % m[:110], file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
