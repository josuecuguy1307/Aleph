#!/usr/bin/env bash
# verify_por_que_rehornea — la función que EXPLICA no puede matar el build.
#
# `por_que_rehornea` se llama FUERA de un `if`, así que con `set -e` su código de salida es
# el del build entero. Tenía dos caminos por los que devolvía 1 sin imprimir nada:
#
#   1. artefacto AUSENTE → `find -newer <que-no-está>` falla y el `2>/dev/null` se come el
#      motivo. Es el caso de todo worktree fresco. MEDIDO: el build moría después de
#      «frontera Legal: procedencia auditada» con exit 1 y sin una línea.
#   2. sin culpable → `[ -n "$culpable" ] && echo …` era la última orden de la función.
#
# Esta vara corre la función AISLADA, con `set -e` prendido, en los tres casos. Cae con el
# código anterior (caso 1, exit 1, mudo) y pasa con el actual.
#
# Uso:  bash qa/verify_por_que_rehornea.sh [ruta/a/build_app.sh]
set -e
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FUENTE="${1:-$AQUI/deploy/fase4/build_app.sh}"
REPO=/tmp/no-importa
eval "$(sed -n '/^por_que_rehornea()/,/^}/p' "$FUENTE")"

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/src"; echo hola > "$T/src/a.txt"

echo "── 1 · artefacto AUSENTE (worktree fresco) ──"
por_que_rehornea "$T/no-existe" "$T/src"; echo "   exit $? ✓"
echo "── 2 · artefacto más nuevo que la fuente (nada que rehornear) ──"
sleep 1; touch "$T/bin"
por_que_rehornea "$T/bin" "$T/src"; echo "   exit $? ✓"
echo "── 3 · fuente más nueva (el caso que ya funcionaba) ──"
sleep 1; touch "$T/src/a.txt"
por_que_rehornea "$T/bin" "$T/src"; echo "   exit $? ✓"
echo "✓ 3/3 — con set -e prendido, ninguno corta el build"
