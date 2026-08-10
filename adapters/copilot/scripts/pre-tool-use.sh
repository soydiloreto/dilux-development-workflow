#!/usr/bin/env bash
# DDW — Copilot CLI · preToolUse: refuse a write that would break the FSM.
#
# The whole job is: hand the event to the shared gate without touching it. The
# previous version read stdin into a variable first, so by the time the
# validator ran there was nothing left to read; it saw an empty envelope, exited
# 0, and every illegal transition went through. Copilot looked installed and
# enforced nothing.
#
# `--dialect copilot` covers the second half: Copilot's envelope is camelCase
# (`toolName`/`toolArgs`), and its refusal is a JSON verdict on stdout as well
# as exit 2.
set -uo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# Repo first, plugin second — the same order every adapter resolves in. As the
# user-level copy (DDW_PLUGIN_ROOT set, wired in ~/.copilot/config.json) this
# script stands down when the repo wires its own hook: otherwise every write
# would be judged twice, once per level.
if [ -n "${DDW_PLUGIN_ROOT:-}" ] && [ -f "$REPO/.github/hooks/ddw/pre-tool-use.sh" ]; then
  echo '{}'
  exit 0
fi
DDW="$REPO/.ddw"
if [ ! -f "$DDW/scripts/hook-gate.py" ]; then
  if [ -n "${DDW_PLUGIN_ROOT:-}" ] && [ -f "$DDW_PLUGIN_ROOT/ddw/scripts/hook-gate.py" ]; then
    DDW="$DDW_PLUGIN_ROOT/ddw"
  else                      # DDW is not reachable from here
    echo '{}'
    exit 0
  fi
fi
# Sin python3 no hay nada que juzgue esta escritura, y un hook que no puede
# juzgar tiene que rechazar. Copilot lee cualquier exit distinto de 2 como un
# error no bloqueante: sin este bloque el `exec` de abajo sale 127 y la
# escritura entra. Los otros cinco adaptadores lo tenían; estos dos no, que
# son justamente los dos que deciden escrituras.
#
# DESPUÉS del chequeo de alcanzabilidad, como en los otros cinco: puesto
# antes, un repo que no tiene DDW instalado se queda sin poder escribir por
# una herramienta que no necesita.
command -v python3 >/dev/null 2>&1 || {
  echo "DDW cannot enforce anything without python3 on PATH. Refusing the write." >&2
  exit 2
}

GATE="$DDW/scripts/hook-gate.py"
STATE="$REPO/.ddw-state.json"
GRAPH="$DDW/rules/transition-graph.json"

exec python3 "$GATE" --dialect copilot --mode pre --state "$STATE" --graph "$GRAPH" --repo "$REPO" --method "$DDW"
