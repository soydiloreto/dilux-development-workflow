#!/usr/bin/env bash
# DDW — Copilot CLI · postToolUse: revalidate the state on disk.
#
# The net under the net: it catches writes no pre-write matcher sees, which in
# practice means a Bash/jq/sed edit of the state file. It refuses (exit 2)
# rather than merely reporting — an inconsistent state that is only mentioned is
# an inconsistent state that stays.
set -uo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

cat > /dev/null            # drain the event; post mode reads the disk, not stdin

# Repo first, plugin second; the user-level copy stands down where the repo
# wires its own hook. Same reasoning as pre-tool-use.sh.
if [ -n "${DDW_PLUGIN_ROOT:-}" ] && [ -f "$REPO/.github/hooks/ddw/post-write.sh" ]; then
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

exec python3 "$GATE" --dialect copilot --mode post --state "$STATE" --graph "$GRAPH" --repo "$REPO"
