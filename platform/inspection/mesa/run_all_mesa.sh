#!/usr/bin/env bash
# run_all_mesa.sh — corre TODOS los harnesses de la Mesa de Construcción (§6).
#
#   1. backend in-process (25/25): preguntas ambos sentidos, proyección cero-teatro,
#      borrador retomable, candado manual, credencial fuera de banda.
#   2. e2e HTTP (19/19): motor real contra fixture + cerebro-stub → 6 estaciones →
#      pieza construida; pausa-vivo P3 + retomar; candado manual vivo; write gateado.
#   3. front Playwright (15/15): diff evento↔dibujo, pregunta ambos sentidos, paridad
#      de modos, cero-emoji.
#
# Puertos propios; jamás :8080/:8091/:8097/:8923. Cero red externa, cero tokens.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
PY="$ROOT/product/backend/.venv/bin/python"; [ -x "$PY" ] || PY=python3
export PYTHONPATH="$ROOT/platform:$ROOT/product/backend"

fail=0
echo "════════ Mesa · backend in-process ════════"
"$PY" "$ROOT/platform/inspection/mesa/verify_mesa_backend.py" || fail=1
echo "════════ Mesa · e2e HTTP ════════"
"$PY" "$ROOT/platform/inspection/mesa/verify_mesa_e2e.py" || fail=1
echo "════════ Mesa · front (Playwright) ════════"
( cd "$ROOT/product/app/design/cuarto" && node verify_mesa_front.mjs ) || fail=1

echo
if [ "$fail" -eq 0 ]; then echo "MESA · TODO VERDE"; else echo "MESA · HAY ROJOS"; fi
exit $fail
