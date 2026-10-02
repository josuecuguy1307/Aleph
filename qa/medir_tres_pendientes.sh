#!/bin/bash
# LAS TRES QUE QUEDARON [no medible] hasta tener binario. Se corren CONTRA LA .app INSTALADA.
#
#   1. `Skipped src.tools.mcp` — es un aviso de RUNTIME de Finanzas (src/tools/__init__.py:52),
#      NO una línea del log de build. Medirlo en el log de build da 0 en los dos binarios y
#      "prueba" cualquier cosa. Se mide levantando el pack y leyendo SU stderr.
#   2. `GET /provider/auth` de Legal tiene que dar 0 llamadas: si el stack sigue pidiendo su
#      propia puerta de auth, la credencial de la casa no está llegando a destino.
#   3. La prueba con Exa la dispara el dueño desde la cara; acá sólo se deja el lector.
set -uo pipefail
APP="/Applications/Aleph.app"
# ⚠️ LA RUTA LA CORRIGIÓ EL DUEÑO, y mi versión medía sobre un dir que NO EXISTE — o sea que
# habría dado «0 hits» para todo y eso se lee como «desapareció el aviso». Un contador sobre
# un archivo inexistente no es una medición: es un cero fabricado. El log real es UNO:
LOG="$HOME/Library/Logs/app.aleph.desktop/Aleph.log"

echo "── 1 · Skipped src.tools.mcp (la bitácora DEL PACK, no la de Aleph) ───"
# ⚠️ DOS RUTAS EQUIVOCADAS ANTES DE ESTA. Primero apunté a un dir que no existe (cero
# fabricado). Después a `Aleph.log`, que es la voz del SIDECAR: medido, no lleva el stderr de
# los packs — las únicas dos menciones a Finanzas en 44.000 líneas eran errores de PyInstaller.
# `pack.py:181` abre la bitácora del pack en modo "ab" y le manda stdout+stderr del hijo. Ahí
# vive el aviso, y ahí se cuenta.
PACK="$HOME/Library/Application Support/Aleph/workspaces/finanzas/log/pack.log"
if [ -f "$PACK" ]; then
  hist=$(grep -c "Skipped src.tools.mcp" "$PACK" || true)
  # CONTROL POSITIVO: si el archivo NUNCA cargó el aviso, un 0 no dice que se arregló — dice
  # que estamos contando en un canal que no lo transporta. Es la misma trampa que las dos
  # rutas anteriores, con otra cara.
  echo "   apariciones históricas (todas las corridas): $hist"
  if [ "$hist" = "0" ]; then
    echo "   [no medible] este archivo nunca cargó el aviso: sin control positivo, un 0 no prueba nada."
  else
    # `ab` = la bitácora ACUMULA arranques. Se cuenta desde el último "Started server process",
    # que es el spawn que corrió bajo el binario instalado ahora.
    INI=$(grep -n "Started server process" "$PACK" | tail -1 | cut -d: -f1)
    if [ -z "$INI" ]; then
      echo "   [no medible] el pack no arrancó todavía: abrí Finanzas y volvé a correr esto."
    else
      n=$(tail -n +"$INI" "$PACK" | grep -c "Skipped src.tools.mcp" || true)
      echo "   arranque actual: línea $INI de $(wc -l < "$PACK" | tr -d ' ')"
      echo "   apariciones DESDE ese arranque: $n   (esperado: 0)"
      [ "$n" != "0" ] && tail -n +"$INI" "$PACK" | grep "Skipped src.tools.mcp" | head -2
    fi
  fi
else
  echo "   [no medible] no existe $PACK — Finanzas no se abrió nunca en este equipo."
fi

echo "── 2 · GET /provider/auth de Legal ────────────────────────────────────"
if [ -f "$LOG" ]; then
  n=$(grep -c "provider/auth" "$LOG" 2>/dev/null || true)
  echo "   llamadas registradas: $n   (esperado: 0)"
  [ "$n" != "0" ] && grep "provider/auth" "$LOG" 2>/dev/null | tail -3
  echo "   ⚠️  igual que arriba: 0 sin haber ENTRADO a Legal no es una medición."
fi

echo ""
echo "── 3 · el veredicto que la cara va a leer ─────────────────────────────"
DB="$HOME/Library/Application Support/Aleph/motor_estado.json"
if [ -f "$DB" ]; then
  python3 - "$DB" <<'PY'
import json, sys, time
d = json.load(open(sys.argv[1])).get("estados", {})
ks = [v for v in d.values() if v.get("tipo") == "key"]
print(f"   veredictos de llave en el registro del motor: {len(ks)}")
for v in ks:
    ts = v.get("probado_ts") or v.get("ts")
    cuando = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts))) if ts else "—"
    print(f"     {str(v.get('ref')):16s} {str(v.get('estado')):14s} {cuando}  {str((v.get('evidencia') or {}).get('prueba') or '')}")
if not ks:
    print("     (ninguno: nadie guardó una llave todavía en este binario)")
PY
else
  echo "   [no medible] todavía no hay $DB"
fi
