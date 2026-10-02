#!/usr/bin/env bash
# Aleph · Gate 4 · Fase 6 · §6.a.bis — PRODUCIR EL RUNTIME DE LA BÚSQUEDA DE LA SALA.
#
# Qué produce para la distribución (SearXNG se instala por separado):
#
#   1. third_party/vane/node_modules/          deps de Vane            (yarn.lock)
#   2. third_party/vane/.next/standalone/      el motor servible       (next build)
#   3. third_party/vane/.playwright/           chromium-headless-shell (para LEER páginas)
#   3.bis node_modules/@huggingface/…/.cache   los pesos del embedding (sin red en runtime)
#   4. platform/sala/research/runtime/         el Python que viaja     ← los DOS modos
#
# El modo histórico `searxng` sólo sirve para desarrollo local; `todo` jamás lo instala.
#
# Es idempotente: correrlo dos veces no rehace lo que ya está sano.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
VANE="$RAIZ/third_party/vane"
SX="$RAIZ/platform/sala/busqueda/searxng"
RT="$RAIZ/platform/sala/research/runtime"   # el Python que viaja, compartido por los dos modos
PYVER="3.13"
#: El de embeddings que declara la costura (`platform/sala/busqueda/config.py`).
EMBED_MODEL="Xenova/all-MiniLM-L6-v2"
SOLO="${1:-todo}"

decir() { echo "▸ $*"; }
morir() { echo "producir_busqueda: $*" >&2; exit 1; }

# ── 0 · las herramientas, ANTES de gastar media hora ──────────────────────────
command -v node    >/dev/null || morir "falta node"
command -v python3 >/dev/null || morir "falta python3"
if [ "$SOLO" = "searxng" ]; then command -v git >/dev/null || morir "falta git"; fi
# Vane trae `yarn.lock` (lockfile v1 = Yarn Classic) y ahí se midieron sus 874 licencias
# (`third_party/vane/IMPORT.md`). Cambiarlo por npm produciría OTRO árbol de dependencias
# y dejaría ese censo sin valor, así que se usa yarn — por corepack si no está suelto.
if command -v yarn >/dev/null; then YARN="yarn"
elif command -v corepack >/dev/null; then corepack prepare yarn@1.22.22 --activate >/dev/null 2>&1 || true
                                         YARN="corepack yarn"
else morir "falta yarn (y corepack para instalarlo)"; fi

# ── 1 · las dependencias de Vane ──────────────────────────────────────────────
if [ "$SOLO" = "todo" ] || [ "$SOLO" = "vane" ]; then
  decir "vane · yarn install"
  ( cd "$VANE" && $YARN install --frozen-lockfile )

  # ── 2 · el build standalone ─────────────────────────────────────────────────
  decir "vane · next build (standalone)"
  ( cd "$VANE" && $YARN build )
  [ -f "$VANE/.next/standalone/server.js" ] || morir "el build no dejó .next/standalone/server.js"

  # Next NO copia los estáticos al standalone: lo dice su propia doc y lo hace a mano el
  # `Dockerfile.slim:29-30` de upstream. Sin esto el motor levanta igual —las rutas /api
  # no los necesitan— pero cualquier ruta que sirva un asset devuelve 404.
  decir "vane · estáticos al standalone (Dockerfile.slim:29-30)"
  mkdir -p "$VANE/.next/standalone/.next"
  cp -R "$VANE/public"      "$VANE/.next/standalone/"       2>/dev/null || true
  cp -R "$VANE/.next/static" "$VANE/.next/standalone/.next/" 2>/dev/null || true

  # ── 3 · el navegador que LEE las páginas ────────────────────────────────────
  # `src/lib/scraper.ts:16-20` lanza `chromium` con `channel: 'chromium-headless-shell'`,
  # y lo usa el camino crítico de la búsqueda (`actions/search/baseSearch.ts:368`).
  # Degrada con gracia si falta (el `.catch` de :368 saltea el resultado), pero entonces
  # la Sala nunca puede mostrar la etapa «leyendo Y» que §6.a.bis pide por nombre: se
  # quedaría en «buscando X → N resultados» con los puros snippets del metabuscador.
  decir "vane · chromium-headless-shell"
  ( cd "$VANE" && PLAYWRIGHT_BROWSERS_PATH="$VANE/.playwright" $YARN playwright install --only-shell chromium )

  # ── 3.bis · LOS PESOS DEL EMBEDDING, VENDORIZADOS ───────────────────────────
  # Vane exige un modelo de embeddings para su reranker y usa el proveedor `transformers`
  # local (decisión del dueño, registrada en `platform/sala/busqueda/config.py`). Sus
  # pesos NO venían con nada: `@huggingface/transformers` los resolvía **en el primer
  # uso**, o sea que la primera búsqueda de una instalación recién abierta salía a la red
  # de Hugging Face. Sin llave, pero a un tercero, y con la búsqueda parada esperándolo.
  #
  # Se bajan acá, en el build. Y no hace falta tocar una línea de Vane para que los
  # encuentre: su caché por defecto es `path.join(dirname__, "/.cache/")`
  # (`node_modules/@huggingface/transformers/src/env.js:96`), o sea **adentro del propio
  # node_modules**, que ya es artefacto de build y ya viaja. Cero código, cero upstream.
  decir "vane · pesos del embedding (vendorizados)"
  ( cd "$VANE" && node --input-type=module -e "
      import { pipeline } from '@huggingface/transformers';
      const p = await pipeline('feature-extraction', '$EMBED_MODEL', { dtype: 'fp32' });
      const o = await p(['aleph'], { pooling: 'mean', normalize: true });
      console.error('    dims=' + o.tolist()[0].length);
    " )
  _cache="$VANE/node_modules/@huggingface/transformers/.cache"
  [ -d "$_cache" ] || morir "los pesos no quedaron en $_cache"

  # ⚠️ Y HAY QUE COPIARLOS AL STANDALONE A MANO. Medido: `@huggingface/transformers` SÍ
  # entra al `.next/standalone` (Next lo traza como dependencia), pero **su `.cache` no**
  # —Next traza CÓDIGO, no cachés— así que el binario viajaría con la librería y sin los
  # pesos, y la primera búsqueda saldría a Hugging Face igual que antes. Cambiar el orden
  # no alcanza: no es una carrera, es que ese directorio no está en el grafo.
  _dest="$VANE/.next/standalone/node_modules/@huggingface/transformers"
  if [ -d "$_dest" ]; then
    rm -rf "$_dest/.cache"
    cp -R "$_cache" "$_dest/.cache"
    decir "vane · pesos copiados al standalone ($(du -sh "$_dest/.cache" | cut -f1))"
  else
    morir "el standalone no trae @huggingface/transformers: revisá el build"
  fi
fi

# ── 4 · EL RUNTIME DE PYTHON QUE VIAJA — compartido por los DOS modos de la Sala ──────
# Vive bajo `research/` porque es donde los dos launchers ya lo buscan:
# `research/arranque.sh:26` (`$AQUI/runtime/bin/python3`) y `busqueda/arranque.sh`
# (`$AQUI/../research/runtime/bin/python3`). El diseño ya era compartido; esto lo produce.
#
# NO SIRVE EL PYTHON DEL SIDECAR, y se midió antes de escribir esto: el bundle usa
# `ALEPH_SIDECAR_ONEFILE=1` (Tauri `externalBin` exige UN archivo), y un onefile de
# PyInstaller se extrae a un `_MEIxxxxxx` **con nombre distinto en cada arranque**. Nada
# puede colgar de una ruta que cambia en cada ejecución.
#
# ⚠️ Y COPIAR EL PYTHON NO ALCANZA: medido, un python-build-standalone movido a otra ruta
# arranca pero calcula `sys.prefix` desde donde fue INSTALADO, así que cargaría su stdlib
# de un directorio inexistente. Lo que lo hace relocatable es `PYTHONHOME`, y eso lo pone
# el launcher.
if [ "$SOLO" = "todo" ] || [ "$SOLO" = "searxng" ]; then
  if [ ! -x "$RT/bin/python3" ]; then
    command -v uv >/dev/null || morir "falta uv para bajar el runtime de Python (https://astral.sh/uv)"
    decir "runtime · python-build-standalone $PYVER (uv)"
    rm -rf "$RT"; mkdir -p "$RT/.uv"
    uv python install --install-dir "$RT/.uv" "$PYVER" >/dev/null
    # uv deja `cpython-X.Y.Z-<plat>/` adentro; el launcher espera `runtime/bin/python3`.
    _src="$(find "$RT/.uv" -maxdepth 1 -type d -name 'cpython-*' | head -1)"
    [ -n "$_src" ] || morir "uv no dejó un cpython-* en $RT/.uv"
    ( cd "$_src" && tar cf - . ) | ( cd "$RT" && tar xf - )
    rm -rf "$RT/.uv"
  else
    decir "runtime · ya está"
  fi
  PYTHONHOME="$RT" "$RT/bin/python3" -c "import ssl, sqlite3" \
    || morir "el runtime de Python no trae ssl/sqlite3"
fi

# ── 5 · SearXNG sólo por invocación explícita de desarrollo ──────────────────
if [ "$SOLO" = "searxng" ]; then
  if [ ! -d "$SX/src/.git" ]; then
    decir "searxng · clonando (queda FUERA de git: .gitignore lo declara)"
    mkdir -p "$SX"
    git clone --depth 1 https://github.com/searxng/searxng "$SX/src"
  else
    decir "searxng · el clon ya está"
  fi

  # SIN VENV. Un venv graba su `home` en `pyvenv.cfg` y la ruta del árbol de build en cada
  # shebang de `bin/*`; copiarlo a la `.app` produce algo que no arranca en la máquina del
  # usuario. `pip install --target` deja un **directorio plano sin una sola ruta grabada**,
  # que el launcher alcanza por `PYTHONPATH`.
  #
  # EL ORDEN ES DE UPSTREAM Y NO ES DECORATIVO (`Dockerfile:60-62`): el `setup.py` de
  # SearXNG importa `searx/__init__.py`, que importa `msgspec` — necesita sus dependencias
  # instaladas para poder declarar sus dependencias. Sin pre-sembrar el target y sin
  # `--no-build-isolation`, pip muere en «Getting requirements to build editable».
  decir "searxng · pip --target (sin venv)"
  PYTHONHOME="$RT" "$RT/bin/python3" -m pip install -q --target "$SX/lib" \
      msgspec pyyaml typing_extensions setuptools wheel
  PYTHONHOME="$RT" PYTHONPATH="$SX/lib" "$RT/bin/python3" -m pip install -q --target "$SX/lib" \
      --use-pep517 --no-build-isolation --upgrade "$SX/src"

  # Los scripts de consola SÍ llevan la ruta del build en el shebang. No los usa nadie
  # —el launcher entra por `-m flask`— y dejarlos sería sembrar rutas fantasma en la .app.
  rm -rf "$SX/lib/bin"
fi

# ── 5 · el contrato del launcher, verificado ──────────────────────────────────
# Se chequea lo MISMO que `platform/sala/busqueda/arranque.sh` chequea, con las mismas
# rutas: si este script dice verde, el launcher no puede salir por `exit 69` por falta de
# piezas. Una verificación que no mira lo que mira el consumidor no verifica nada.
decir "verificando el contrato del launcher"
[ -f "$VANE/.next/standalone/server.js" ] || morir "falta .next/standalone/server.js (arranque.sh)"
[ -d "$VANE/drizzle" ]                    || morir "faltan las migraciones drizzle/ (arranque.sh)"
if [ "$SOLO" = "todo" ] || [ "$SOLO" = "searxng" ]; then
  [ -x "$RT/bin/python3" ]     || morir "falta el runtime de Python (research/runtime/bin/python3)"
fi
if [ "$SOLO" = "searxng" ]; then
  [ -d "$SX/lib/searx" ]       || morir "falta searxng/lib/searx (arranque.sh camino 2)"
  PYTHONHOME="$RT" PYTHONPATH="$SX/lib" "$RT/bin/python3" -c "import searx, flask" 2>/dev/null \
    || morir "el runtime no importa 'searx' desde el directorio plano"
fi
echo "✓ runtime de la búsqueda producido"
