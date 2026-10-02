#!/usr/bin/env bash
# Aleph · Búsqueda base — launcher del pack de LA SALA (§6.a.bis).
#
# El pack es dueño del grupo de procesos. Este launcher inicia Vane y el puente local;
# SearXNG se configura como servidor independiente por URL.
#
# Contrato con el pack (`platform/workspaces/pack.py`):
#   · recibe `--port <n>` y nada más (`pack.py:474`)
#   · el dir de config y el de datos llegan por env (`pack.py:477-482`)
#   · tiene que contestar 200 en la señal de salud antes de ARRANQUE_S (`pack.py:122-127`)
#   · morir con el grupo (`start_new_session=True` + `killpg`, `pack.py:183,216-245`)
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../../.." && pwd)"
VANE="$RAIZ/third_party/vane"

# ── argumentos ────────────────────────────────────────────────────────────────
PUERTO=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    # `shift 2` con un solo argumento devuelve 1 y, con `set -e`, MATA el script
    # antes del chequeo de abajo que sí tiene copy: el pack.log quedaba vacío y el
    # pack sólo podía decir `pack_no_arranco` genérico, teniendo el mensaje escrito
    # dos líneas más abajo. Se valida antes de correr el argumento.
    --port)
      [ "$#" -ge 2 ] || { echo "Aleph Búsqueda: --port vino sin valor" >&2; exit 64; }
      PUERTO="$2"; shift 2 ;;
    *) echo "Aleph Búsqueda: argumento desconocido: $1" >&2; exit 64 ;;
  esac
done
[ -n "$PUERTO" ] || { echo "Aleph Búsqueda: falta --port del pack" >&2; exit 64; }

# ── lo que el pack tiene que haber puesto ─────────────────────────────────────
export ALEPH_BUSQUEDA_CONFIG_DIR="${ALEPH_BUSQUEDA_CONFIG_DIR:?Aleph Búsqueda requiere ALEPH_BUSQUEDA_CONFIG_DIR}"
export DATA_DIR="${DATA_DIR:?Aleph Búsqueda requiere DATA_DIR}"
mkdir -p "$ALEPH_BUSQUEDA_CONFIG_DIR" "$DATA_DIR/data"

# ── LAS MIGRACIONES DE LA BASE, SEMBRADAS EN DATA_DIR ─────────────────────────
# `third_party/vane/src/lib/db/migrate.ts:10` busca las migraciones en
# `path.join(DATA_DIR, 'drizzle')` y las corre en su `instrumentation` al arrancar. En el
# contenedor de upstream las dos rutas coinciden por accidente: `Dockerfile.slim:30` copia
# `drizzle/` al workdir, que es donde DATA_DIR cae por default. Acá NO coinciden, y no
# pueden: DATA_DIR es del usuario y escribible, las migraciones vienen del build y en la
# `.app` son de sólo lectura. Así que las siembra el launcher.
#
# MEDIDO, y es la clase de fallo que esta casa persigue: sin esto el motor **arranca
# igual**, escupe «Failed to run database migrations» en su log, y `/api/providers`
# contesta **200**. O sea que el pack declara el modo sano con la base SIN TABLAS, y lo
# que falla es el primer turno. Salud verde y capacidad muerta.
[ -d "$VANE/drizzle" ] || {
  echo "Aleph Búsqueda: faltan las migraciones de Vane ($VANE/drizzle). El workspace no viajó completo." >&2
  exit 69; }
mkdir -p "$DATA_DIR/drizzle"
cp -R "$VANE/drizzle/." "$DATA_DIR/drizzle/"

# ── el runtime de Node ────────────────────────────────────────────────────────
# En la `.app` viaja al lado del launcher (patrón O1, igual que el Bun de Legal). En
# desarrollo se cae al `node` del shell A PROPÓSITO; una instalación distribuida jamás
# depende de ese estado.
ALEPH_NODE="$AQUI/runtime/bin/node"
if [ ! -x "$ALEPH_NODE" ]; then ALEPH_NODE="$(command -v node || true)"; fi
[ -n "$ALEPH_NODE" ] && [ -x "$ALEPH_NODE" ] || {
  echo "Aleph Búsqueda: falta el runtime de Node del pack" >&2; exit 69; }

# El motor se sirve desde el build standalone de Next (`next.config.mjs`,
# `output: 'standalone'`). Es artefacto de build, como el `dist` de Ciencia: no se
# commitea y viaja por el spec del sidecar. Si no está, el workspace no viajó completo.
SERVER="$VANE/.next/standalone/server.js"
[ -f "$SERVER" ] || {
  echo "Aleph Búsqueda: falta el build de Vane ($SERVER). Se produce con 'yarn build' en third_party/vane." >&2
  exit 69; }

# ── el intérprete de Python ───────────────────────────────────────────────────
# Este launcher lo usa dos veces (puerto libre y la costura de config), y su hermano
# `platform/sala/research/arranque.sh` dedica once líneas a resolverlo. Acá se hacía
# `python3` a secas: con `set -e`, si faltaba, el launcher moría SIN mensaje propio —salía
# el error de bash, no «Aleph Búsqueda: …»— y el pack sólo podía decir `pack_no_arranco`
# genérico. En una `.app` de macOS sin Command Line Tools, `/usr/bin/python3` es un stub.
#
# ⚠️ `PYTHONHOME`, Y SIN ESTO EL RUNTIME NO VIAJA. Medido: un Python de
# python-build-standalone copiado a otra ruta arranca, pero calcula `sys.prefix` desde
# **la ruta donde fue instalado**, no desde dónde está — o sea que en la máquina del
# usuario cargaría su stdlib de un directorio que no existe. `PYTHONHOME` lo ata a su copia.
#
# Sólo se exporta cuando usamos EL NUESTRO: si caemos al `python3` del sistema, apuntarle
# `PYTHONHOME` a un directorio ajeno lo rompería.
ALEPH_RUNTIME="$AQUI/../research/runtime"
ALEPH_PY="$ALEPH_RUNTIME/bin/python3"
if [ -x "$ALEPH_PY" ]; then
  export PYTHONHOME="$ALEPH_RUNTIME"
else
  ALEPH_PY="$(command -v python3 || true)"
  unset PYTHONHOME || true
fi
[ -n "$ALEPH_PY" ] && [ -x "$ALEPH_PY" ] || {
  echo "Aleph Búsqueda: falta un intérprete de Python para la costura de config" >&2
  exit 69; }

puerto_libre() {
  "$ALEPH_PY" - <<'PUERTO'
import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()
PUERTO
}

# ── SearXNG es un proveedor EXTERNO, nunca un proceso del bundle ─────────
[ -n "${ALEPH_SEARXNG_URL:-}" ] || {
  echo "Aleph Búsqueda: configure un proveedor SearXNG antes de buscar" >&2
  exit 69; }
export SEARXNG_API_URL="$ALEPH_SEARXNG_URL"
# EL TRAP TIENE QUE SOBREVIVIR AL MOTOR. La primera versión terminaba en
# `exec node server.js`, y `exec` **reemplaza el proceso del shell**: el trap dejaba de
# existir justo cuando empezaba a hacer falta, o sea durante el 100% de la vida del modo.
#
# Hay dos hijos locales; el trap los cierra cuando uno falla o se detiene el pack.
limpiar() {
  [ -n "${SERVIDOR_PID:-}" ] && kill "$SERVIDOR_PID" 2>/dev/null || true
  [ -n "${NODE_PID:-}" ] && kill "$NODE_PID" 2>/dev/null || true
}
trap limpiar EXIT INT TERM

esperar_un_hijo() {
  local estado=0 pid
  if help wait 2>/dev/null | grep -q '\-n'; then
    wait -n "$@" || estado=$?
    return "$estado"
  fi
  while :; do
    for pid in "$@"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        estado=0
        wait "$pid" || estado=$?
        return "$estado"
      fi
    done
    sleep 0.1
  done
}

# ── EL CANDADO DE LA LEY 12 ───────────────────────────────────────────────────
# El pack le pasa al proceso el entorno del padre mergeado con el suyo
# (`platform/workspaces/pack.py:181`, `env={**os.environ, **self._env}`), así que **la
# shell del usuario entra acá**. Y Vane siembra un proveedor NUEVO por cada juego de env
# vars que encuentre configurado, al arrancar (`src/lib/config/index.ts:175-227`).
#
# O sea: un `OPENAI_API_KEY` suelto en el shell le fabricaría a Vane un SEGUNDO proveedor
# apuntado a la OpenAI de verdad, al lado del nuestro, elegible desde su selector. Eso es
# la LEY DEL CEREBRO ÚNICO rota por accidente y sin que nadie lo note.
#
# Se borran las nueve que su catálogo declara (medidas: `grep -rhoE "env: '[A-Z_]+'"
# src/lib/models/providers/`). El cerebro entra por `config.py`, por el archivo, y por
# ningún otro lado.
unset OPENAI_API_KEY OPENAI_BASE_URL \
      ANTHROPIC_API_KEY GEMINI_API_KEY GROQ_API_KEY \
      LEMONADE_API_KEY LEMONADE_BASE_URL \
      LM_STUDIO_BASE_URL OLLAMA_BASE_URL

# ── LA COSTURA AL CEREBRO ─────────────────────────────────────────────────────
# Traduce el archivo del pack (dialecto de la casa) al `data/config.json` que Vane lee.
# No alcanza con `OPENAI_BASE_URL`: con una baseURL que no es la de OpenAI, el proveedor
# devuelve lista de modelos VACÍA (`src/lib/models/providers/openai/index.ts:138-150`) y
# hay que declarar el modelo a mano. El porqué completo está en `config.py`.
"$ALEPH_PY" "$AQUI/config.py"

# ── el motor ──────────────────────────────────────────────────────────────────
# Next standalone toma su puerto de `PORT`, no de `--port`: traducir eso es el trabajo de
# un launcher, igual que el de Legal traduce el suyo para sus tres hijos. Ese `PORT` se
# fija más abajo y **ya no es el del pack**: el del pack lo atiende `servidor.py`.
export HOSTNAME="127.0.0.1"
export NODE_ENV=production
# `DATA_DIR` es la env var que **el propio Vane ya respeta** para su config y su SQLite
# (`third_party/vane/src/lib/config/index.ts:8-11`): con ella sus datos dejan de vivir en
# el árbol importado y pasan al dir del usuario que Aleph administra.

# ── EL MOTOR VA A UN PUERTO INTERNO, Y EL DEL PACK ES DEL SERVIDOR DE LA CASA ──
# Hasta acá el pack hablaba **directo** con Vane, y eso obligaba a que quien llamara
# supiera su dialecto: los `providerId` que la costura acuña en cada `enter`, el modo, y
# —lo que se llevó una sesión entera— `sources: ["web"]`, sin el cual el motor contesta
# 200 y cero fuentes. Ahora el puerto del pack lo atiende `servidor.py`, que habla el
# NDJSON de la casa, y Vane queda del otro lado del loopback donde nadie lo navega.
export PORT="$(puerto_libre)"
export ALEPH_VANE_URL="http://127.0.0.1:$PORT"
echo "Aleph Búsqueda: motor=vane interno=$PORT pack=$PUERTO searxng=$SEARXNG_API_URL datos=$DATA_DIR"
"$ALEPH_NODE" "$SERVER" &
NODE_PID=$!

# ESPERAR A VANE ANTES DE LEVANTAR EL SERVIDOR: el
# pack declara el modo sano en cuanto `/health` contesta, y `/health` es del servidor, que
# levanta en milisegundos. Sin esta espera diría «listo» con el motor todavía arrancando y
# la PRIMERA búsqueda fallaría, arreglándose sola al segundo intento — la peor forma de
# fallar. `/api/providers` es la misma señal que el registro usaba antes (GET, JSON, y
# prueba que su capa de config cargó).
intentos=0
until "$ALEPH_PY" -c "import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1)" \
        "$ALEPH_VANE_URL/api/providers" >/dev/null 2>&1; do
  intentos=$((intentos+1))
  if [ "$intentos" -ge 50 ]; then
    echo "Aleph Búsqueda: el motor no contestó en 25s ($ALEPH_VANE_URL)" >&2
    exit 69
  fi
  sleep 0.5
done
echo "Aleph Búsqueda: motor listo tras $intentos intento(s)"

"$ALEPH_PY" "$AQUI/servidor.py" --port "$PUERTO" &
SERVIDOR_PID=$!

# Si CUALQUIERA se muere, muere el launcher — y el trap se lleva a los otros. Es la
# misma línea con la que termina el launcher de Legal (`third_party/dochaus/start.sh`).
esperar_un_hijo "$SERVIDOR_PID" "$NODE_PID"
exit $?
