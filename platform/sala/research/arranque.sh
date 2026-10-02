#!/usr/bin/env bash
# Aleph · Deep Research — launcher del pack de LA SALA.
#
# El pack (F4) es dueño del grupo de procesos; este launcher es dueño de UN solo hijo:
# el servidor de `servidor.py`. Nada se escribe adentro del árbol importado.
#
# Contrato con el pack (`platform/workspaces/pack.py`):
#   · recibe `--port <n>` y nada más (`pack.py:474`)
#   · el pack le pasa el dir de config y el de datos por env (`pack.py:477-482`)
#   · tiene que contestar 200 en `/health` antes de ARRANQUE_S (`pack.py:122-127`)
#   · morir con el grupo (el pack usa `start_new_session=True` + `killpg`, `pack.py:183,216-245`)
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../../.." && pwd)"

# ── el intérprete ─────────────────────────────────────────────────────────────
# En la `.app` el runtime de Python del modo viaja al lado del launcher, igual que el Bun
# de Legal viaja en `third_party/dochaus/runtime/bun`. En desarrollo se cae al `python3`
# del shell A PROPÓSITO; una instalación distribuida jamás depende de ese estado.
#
# DEUDA DECLARADA (no la paga esta rama): ese runtime todavía no se construye. El motor
# necesita sus 312 dependencias de `pdm.lock`, y el sidecar de Aleph es un PyInstaller
# congelado — meterlas adentro es obra de empaquetado (`deploy/`), con el precedente de
# `_LEGAL_NM_DUENOS` en `deploy/fase4/aleph_sidecar.spec:126`. Hasta entonces este pack
# levanta en dev y en la `.app` dice la verdad: no viajó.
ALEPH_PY="$AQUI/runtime/bin/python3"
if [ ! -x "$ALEPH_PY" ]; then
  ALEPH_PY="${ALEPH_RESEARCH_PYTHON:-}"
fi
if [ -z "$ALEPH_PY" ] || [ ! -x "$ALEPH_PY" ]; then
  ALEPH_PY="$(command -v python3 || true)"
fi
[ -n "$ALEPH_PY" ] && [ -x "$ALEPH_PY" ] || {
  echo "Aleph Deep Research: falta el runtime de Python del pack" >&2
  exit 69
}

# ── argumentos ────────────────────────────────────────────────────────────────
PUERTO=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    # `shift 2` con un solo argumento devuelve 1 y, con `set -e`, MATA el script
    # antes del chequeo de abajo que sí tiene copy: el pack.log quedaba vacío y el
    # pack sólo podía decir `pack_no_arranco` genérico, teniendo el mensaje escrito
    # dos líneas más abajo. Se valida antes de correr el argumento.
    --port)
      [ "$#" -ge 2 ] || { echo "Aleph Deep Research: --port vino sin valor" >&2; exit 64; }
      PUERTO="$2"; shift 2 ;;
    *) echo "Aleph Deep Research: argumento desconocido: $1" >&2; exit 64 ;;
  esac
done
[ -n "$PUERTO" ] || { echo "Aleph Deep Research: falta --port del pack" >&2; exit 64; }

# ── lo que el pack tiene que haber puesto ─────────────────────────────────────
export ALEPH_RESEARCH_CONFIG_DIR="${ALEPH_RESEARCH_CONFIG_DIR:?Aleph Deep Research requiere ALEPH_RESEARCH_CONFIG_DIR}"
export LDR_DATA_DIR="${LDR_DATA_DIR:?Aleph Deep Research requiere LDR_DATA_DIR}"
mkdir -p "$ALEPH_RESEARCH_CONFIG_DIR" "$LDR_DATA_DIR"

# Deep Research sólo consume una instancia SearXNG configurada por el usuario.
# El router solicita configuración antes de levantar este pack.
[ -n "${ALEPH_SEARXNG_URL:-}" ] || {
  echo "Aleph Deep Research: configure un proveedor SearXNG antes de investigar" >&2
  exit 69; }
export ALEPH_SEARXNG_URL
limpiar() {
  [ -n "${SERVIDOR_PID:-}" ] && kill "$SERVIDOR_PID" 2>/dev/null || true
}
trap limpiar EXIT INT TERM

# El motor vive en `third_party/`, y se importa como librería. No se instala, no se
# mueve, no se toca: sólo se pone su `src/` en el camino de importación.
#
# SUS DEPENDENCIAS SÍ SE INSTALAN, Y VAN AL LADO, NO ADENTRO. El intérprete
# relocatable se comparte, y cada modo cuelga sus wheels de un directorio
# propio. Sin esta línea el pack arrancaba —`servidor.py` sólo usa la stdlib— y **moría en
# la primera obra** con `motor_no_instalado`: 279 paquetes instalados que nadie ponía en
# el camino. Medido: 1,9 GiB, y sin esto son 1,9 GiB invisibles.
export PYTHONPATH="$RAIZ/third_party/ldr/src:$AQUI/lib${PYTHONPATH:+:$PYTHONPATH}"

# Sin buffer: el stdout de este proceso va al `pack.log` y una traza que llega tarde no
# sirve para diagnosticar un arranque que falló.
export PYTHONUNBUFFERED=1

echo "Aleph Deep Research: motor=local-deep-research puerto=$PUERTO datos=$LDR_DATA_DIR"
# El trap mantiene el control del proceso hijo durante el cierre del pack.
"$ALEPH_PY" "$AQUI/servidor.py" --port "$PUERTO" &
SERVIDOR_PID=$!
wait "$SERVIDOR_PID"
exit $?
