#!/usr/bin/env bash
# build_app.sh <public|founder|dev> — construye un .app de Aleph en salida aislada.
# para el build dado, parametrizando las TRES capas por ALEPH_BUILD:
#   1. el SIDECAR frozen  → ALEPH_BUILD decide si el MOAT (Motor B/forge) viaja (aleph_sidecar.spec).
#   2. la CONFIG de Tauri → productName/identifier por build, para que public y founder COEXISTAN.
#   3. tauri build         → el .app/.dmg.
#
# public/dev = ships() (sin forge, seguridad por AUSENCIA). founder = ships()+stays() (forge LOCAL,
# muro OFF). ⚠️ EL ARTEFACTO FOUNDER NUNCA SE DISTRIBUYE — es privado del dueño.
set -euo pipefail
[ "${ALEPH_DMG:-0}" != 1 ] || { echo "✗ DMG disabled in isolated build"; exit 1; }

# ── EL DISCO, ANTES DE EMPEZAR ──────────────────────────────────────────────────────────
#
# EL DISFRAZ QUE ESTO SACA. Sin espacio, este build NO dice «disco lleno»: dice
# `internal error in Code Signing subsystem`. Costó dos tardes creer que era la firma, y el
# 2026-08-29 costó tres arranques más — cada uno tirando abajo entre 10 y 20 minutos de
# trabajo antes de morir por una causa que no nombraba.
#
# EL NÚMERO NO ES UNA ESTIMACIÓN: se midió el 2026-08-29. Los temporales de PyInstaller
# llegan a **37 GB** ellos solos (`$TMPDIR` medido en pleno COLLECT del sidecar onedir), y
# encima va el bundle de 5 GB. Arrancar con 12–15 GB libres —que parecía holgado— es
# arrancar a morir.
#
# El mínimo de espacio es obligatorio: abortar antes de instalar o construir.
DISCO_MIN_GB=40
if [ "${ALEPH_WARM_VALIDATION_BUILD:-0}" = 1 ]; then
  # Narrow, explicit allowance for an isolated validation rebuild on this
  # already-warmed host. Three measured runs started around 40 GiB and never
  # dropped below 33 GiB; the release/default preflight remains 40 GiB.
  DISCO_MIN_GB=39
  echo "⚠ warm validation preflight: 39 GiB (default/release: 40 GiB)"
fi
DISCO_LIBRE_GB=$(df -g / 2>/dev/null | awk 'NR==2{print $4}')
if [ -n "$DISCO_LIBRE_GB" ] && [ "$DISCO_LIBRE_GB" -lt "$DISCO_MIN_GB" ]; then
  echo "⚠  DISCO: hay ${DISCO_LIBRE_GB} GB libres y este build necesita ~${DISCO_MIN_GB} GB"
  echo "   (PyInstaller usa ~37 GB de temporales + 5 GB del bundle, medido 2026-08-29)"
  echo "   Si falla más adelante con «internal error in Code Signing subsystem», ES ESTO."
  echo "   Para liberar: worktrees ya mergeados (git worktree list) y target/ de builds viejos."
  echo
  exit 1
fi

BUILD="${1:-public}"
case "$BUILD" in
  public|founder|dev) ;;
  *) echo "uso: $0 <public|founder|dev>"; exit 1 ;;
esac

HERE="$(cd "$(dirname "$0")" && pwd)"
# Cargo target/output lives in an explicit isolated directory.
ALEPH_BUILD_OUTPUT="${ALEPH_BUILD_OUTPUT:-$HERE/isolated-output}"
case "$ALEPH_BUILD_OUTPUT" in /*) ;; *) echo "✗ ALEPH_BUILD_OUTPUT must be absolute"; exit 1;; esac
ALEPH_BUILD_OUTPUT="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ALEPH_BUILD_OUTPUT")"
case "$ALEPH_BUILD_OUTPUT/" in /Applications/*|//|/Users/|"$HOME/"|/Users/*/Desktop/puppet-ai/*|/Users/*/Desktop/sala-research/*) echo "✗ unsafe build output"; exit 1;; esac
export CARGO_TARGET_DIR="$ALEPH_BUILD_OUTPUT/target"
REPO="$(cd "$HERE/../.." && pwd)"
SHELL_DIR="$HERE/aleph-shell"

# Generated Python/search dependencies are not source-controlled. Remove local
# build paths and the vendored fallback Pexels credential on EVERY build,
# including builds that reuse a previously materialized runtime.
python3 "$REPO/deploy/fase6/sanitize_generated_runtime.py" --without-search

# ── ESTÁ FRESCO, O NO ESTÁ ────────────────────────────────────────────────────────────
# LO QUE ESTO EVITA, MEDIDO EL 2026-08-29. Cinco pasos de este script cacheaban POR
# EXISTENCIA: si el artefacto estaba, se reusaba. Ese día se mergearon 27 commits que
# tocaban LOS SEIS stacks y los `dist` horneados eran del 22 de agosto — siete días más
# viejos que el código. El build habría terminado bien, con 0 cortes, y la persona no
# habría visto UN SOLO cambio: ni el Ajustes único, ni los backticks de Finanzas, ni el
# castellano de Oficina. Un build verde que entrega la app de la semana pasada es peor que
# uno que falla, porque nadie lo mira dos veces.
#
# El criterio es el único honesto: ¿hay algún archivo FUENTE más nuevo que lo horneado?
# Se saltean los dirs que son salida o dependencias (`node_modules`, `dist`, `.next`,
# `release`, `target`, `.git`), que cambian por el propio build y dirían siempre que sí.
esta_fresco() {
  local artefacto="$1"; shift
  [ -e "$artefacto" ] || return 1
  local nuevo
  nuevo="$(find "$@" -type f -newer "$artefacto" \
             -not -path '*/node_modules/*' -not -path '*/dist/*' \
             -not -path '*/.next/*'        -not -path '*/release/*' \
             -not -path '*/target/*'       -not -path '*/.git/*' \
             -print -quit 2>/dev/null)"
  [ -z "$nuevo" ]
}

# Dice POR QUÉ se rehornea, nombrando el archivo culpable. Sin esto, «rehorneando» sin
# motivo es indistinguible de un caché que no funciona.
por_que_rehornea() {
  # ⚠️ ESTA FUNCIÓN MATABA EL BUILD, MUDA, Y POR DOS CAMINOS DISTINTOS.
  #
  # Se la llama FUERA de un `if`, así que con `set -e` su código de salida es el del build.
  #
  #   1. EL ARTEFACTO AUSENTE. `esta_fresco` devuelve 1 cuando no existe —correcto— y acto
  #      seguido se llamaba a ésta con la MISMA ruta inexistente. `find -newer <que-no-está>`
  #      falla, el `2>/dev/null` se come el motivo, y `set -e` corta en la asignación.
  #      Es exactamente el caso de un worktree fresco, donde NADA está horneado todavía:
  #      medido, el build moría después de «frontera Legal: procedencia auditada» con
  #      exit 1 y sin una sola línea. Dos corridas idénticas antes de encontrarlo.
  #   2. SIN CULPABLE. `[ -n "$culpable" ] && echo …` era la ÚLTIMA orden de la función, así
  #      que con la lista vacía devolvía 1 — o sea que «no hay nada más nuevo» también
  #      mataba el build. No se veía porque el caso 1 llega antes.
  #
  # Que una función cuyo único trabajo es EXPLICAR pudiera terminar el build sin explicar
  # nada es lo contrario del contrato del repo. Ahora dice el motivo en los dos casos y
  # devuelve 0 siempre: informar no decide.
  local artefacto="$1"; shift
  if [ ! -e "$artefacto" ]; then
    echo "   no existe todavía: ${artefacto#$REPO/}"
    return 0
  fi
  local culpable
  culpable="$(find "$@" -type f -newer "$artefacto" \
                -not -path '*/node_modules/*' -not -path '*/dist/*' \
                -not -path '*/.next/*'        -not -path '*/release/*' \
                -not -path '*/target/*'       -not -path '*/.git/*' \
                -print -quit 2>/dev/null || true)"
  if [ -n "$culpable" ]; then
    echo "   fuente más nueva que lo horneado: ${culpable#$REPO/}"
  else
    echo "   se rehornea sin fuente más nueva (artefacto ilegible o incompleto)"
  fi
  return 0
}
# Backend environment must belong to this isolated build, never a historical worktree.
VENV_DIR="${ALEPH_BACKEND_VENV:-$REPO/product/backend/.venv}"
VENV_PY="$VENV_DIR/bin/pyinstaller"
VENV_PYTHON="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] && [ -x "$VENV_PYTHON" ] || { echo "✗ falta venv PyInstaller del backend ($VENV_DIR)"; exit 1; }
command -v cargo >/dev/null 2>&1 || source "$HOME/.cargo/env"
TRIPLE="$(rustc -vV | awk '/host/{print $2}')"

# ── [Gate 4 · Fase 6 · Legal · O1] RUNTIME DEL PACK ────────────────────────
# Legal no tiene un binario autocontenido como Ciencia: su launcher corre el stack entero
# sobre Bun. Por eso se materializa el lock CONGELADO y el Vite dist antes del freeze, y el
# spec recibe el Bun exacto que debe viajar junto al árbol. Si cualquiera falta, el build
# muere antes de producir una .app que sólo funcionaría en la Mac que la construyó.
DOCHAUS_ROOT="$REPO/third_party/dochaus"
DOCHAUS_BUN="${ALEPH_DOCHAUS_BUN:-$(command -v bun || true)}"
[ -d "$DOCHAUS_ROOT" ] || { echo "✗ falta el árbol Legal: $DOCHAUS_ROOT"; exit 1; }
[ -n "$DOCHAUS_BUN" ] && [ -x "$DOCHAUS_BUN" ] || { echo "✗ falta Bun para el pack Legal"; exit 1; }

# ── [Gate 4 · Fase 6 · Legal · C] FRONTERA DE REDISTRIBUCIÓN ────────────────
# Un `public` es un build distribuible. Nunca se habilita por una frase: el marcador que
# vive junto a las atribuciones se verifica aquí y, si la alternativa de exclusión está
# activa, el spec recibe el manifiesto que materialmente saca esos directorios del bundle.
LEGAL_ATTRIBUTIONS="$DOCHAUS_ROOT/ATTRIBUTIONS"
LEGAL_EXCLUSIONS="$DOCHAUS_ROOT/REDISTRIBUTION_EXCLUSIONS"
if [ "$BUILD" = "public" ]; then
  if rg -q '^<!-- ALEPH_REDISTRIBUTION_GATE=AUDITED -->$' "$LEGAL_ATTRIBUTIONS"; then
    echo "── frontera Legal: procedencia auditada ──"
  elif rg -q '^<!-- ALEPH_REDISTRIBUTION_GATE=EXCLUSION_MANIFEST -->$' "$LEGAL_ATTRIBUTIONS" \
       && rg -q '^<!-- ALEPH_REDISTRIBUTION_MANIFEST=third_party/dochaus/REDISTRIBUTION_EXCLUSIONS -->$' "$LEGAL_ATTRIBUTIONS" \
       && [ -s "$LEGAL_EXCLUSIONS" ]; then
    export ALEPH_DOCHAUS_REDISTRIBUTION_EXCLUSIONS="$LEGAL_EXCLUSIONS"
    echo "── frontera Legal: contenido no auditado EXCLUIDO por manifiesto ──"
  else
    echo "✗ build distribuible PROHIBIDO: falta auditoría de procedencia o lista de exclusión aplicada"
    echo "  revisar third_party/dochaus/ATTRIBUTIONS"
    exit 70
  fi
fi
# ── [receta · 2026-08-16] PACK DE CIENCIA: LOS TRES PASOS, HORNEADOS ACÁ ─────────────────
# El spec exige el binario del pack de Ciencia y falla fuerte si falta, pero producirlo era
# un paso MANUAL que vivía en dos actas. **Costó un build entero el 2026-08-16** y no por
# algo sutil: `third_party/openscience` es un workspace de Bun cuyas deps NO están en git, y
# sin `bun install` su propio build muere con `Cannot find module '@synsci/script'`.
#
# Mismo idioma que el runtime de Diseño de más abajo: si el artefacto ya está, no se rehace.
#
# ⚠️ Y LA PODA NO ES OPCIONAL. `bun run build` compila ONCE plataformas y este spec usa UNA:
# son 1,6 GiB de desperdicio en un build que ya vive cerca del umbral. El
# `internal error in Code Signing subsystem` que aparece más adelante NO es un problema de
# firma — es el disfraz del disco lleno (medido dos veces, en dos tandas distintas).
SCI_ROOT="$REPO/third_party/openscience"
SCI_DIST="$SCI_ROOT/backend/cli/dist/@synsci"
SCI_BIN="$SCI_DIST/openscience-darwin-arm64/bin/openscience"
[ -d "$SCI_ROOT" ] || { echo "✗ falta el árbol de Ciencia: $SCI_ROOT"; exit 1; }
if esta_fresco "$SCI_BIN" "$SCI_ROOT/backend" "$SCI_ROOT/frontend"; then
  echo "── [0/3·a] pack de Ciencia ya horneado ($(du -h "$SCI_BIN" | cut -f1)) ──"
else
  por_que_rehornea "$SCI_BIN" "$SCI_ROOT/backend" "$SCI_ROOT/frontend"
  echo "── [0/3·a] pack de Ciencia (Bun $($DOCHAUS_BUN --version)) ──"
  (
    cd "$SCI_ROOT"
    # (1) las deps del workspace, que no están en git
    "$DOCHAUS_BUN" install
    # (2) el binario, con el snapshot de models.dev del árbol (sin red)
    cd backend/cli
    MODELS_DEV_API_JSON="$HERE/datos/models-dev-snapshot.json" "$DOCHAUS_BUN" run build
  )
  [ -x "$SCI_BIN" ] || { echo "✗ el build de Ciencia no produjo $SCI_BIN"; exit 1; }
fi
# (3) la poda, SIEMPRE — también cuando el binario ya estaba: lo que sobra puede haber
# quedado de un build anterior, y el que paga es el `codesign` de este.
if [ -d "$SCI_DIST" ]; then
  # Sin `xargs -r`: en el xargs de macOS esa bandera no está documentada y con entrada vacía
  # el comportamiento cambia entre versiones. `find -exec` no tiene esa ambigüedad.
  find "$SCI_DIST" -maxdepth 1 -type d -name 'openscience-*' \
       ! -name 'openscience-darwin-arm64' -exec rm -rf {} +
  echo "   plataformas de más podadas · dist queda en $(du -sh "$SCI_DIST" | cut -f1)"
fi

# ── [0/3·a·bis] LA CARA DE CIENCIA ────────────────────────────────────────────────────
# El spec embarca `third_party/openscience/frontend/workspace/dist` y hasta hoy NINGÚN paso
# lo horneaba: el que viajaba lo había hecho alguien a mano el 22 de agosto. El merge del
# 2026-08-29 cambió cinco archivos de sus Ajustes y no habrían llegado nunca a la pantalla.
# Es el mismo agujero que la cara de Oficina en [0/3·e], en el otro stack.
SCI_WS="$SCI_ROOT/frontend/workspace"
if esta_fresco "$SCI_WS/dist/index.html" "$SCI_WS/src" "$SCI_WS/public" "$SCI_WS/index.html"; then
  echo "── [0/3·a·bis] cara de Ciencia ya horneada ($(du -sh "$SCI_WS/dist" | cut -f1)) ──"
else
  por_que_rehornea "$SCI_WS/dist/index.html" "$SCI_WS/src" "$SCI_WS/public" "$SCI_WS/index.html"
  echo "── [0/3·a·bis] cara de Ciencia (Bun) ──"
  ( cd "$SCI_WS" && "$DOCHAUS_BUN" run build )
  [ -f "$SCI_WS/dist/index.html" ] || {
    echo "✗ el build de Ciencia no produjo frontend/workspace/dist/index.html"; exit 1; }
fi

# EL KERNEL DE CIENCIA TAMBIÉN ES ENTORNO. El binario de Ciencia arranca su intérprete por
# PATH (`backend/cli/src/tool/notebook.ts:202`) y una `.app` lanzada desde el Finder no
# hereda el PATH del shell. `pack.py:preparar_interprete` le deja un shim delante, pero el
# shim no puede inventar un intérprete que no exista: si en esta máquina ninguno importa
# matplotlib/numpy/scipy, el tiro parabólico no va a producir su PNG y hay que saberlo ACÁ,
# no en la cara del dueño. Se pregunta con LA MISMA función que usa el runtime.
PYTHONPATH="$REPO:$REPO/platform" "$VENV_PYTHON" - <<'PYGATE' || exit 1
import sys
from workspaces import pack
ruta, completo = pack.interprete_del_kernel("third_party/openscience")
if completo:
    print(f"   ✓ kernel de Ciencia: {ruta} importa matplotlib · numpy · scipy")
    sys.exit(0)
print("✗ el pack de Ciencia viajaría sin kernel usable"
      + (f": {ruta} existe pero NO importa matplotlib/numpy/scipy" if ruta
         else ": no hay ningún python3 alcanzable"))
print("      Se resuelve de una de estas dos formas:")
print("      1) instalar las tres en un intérprete que el shim alcance, p. ej.")
print("         /opt/miniconda3/bin/python3 -m pip install matplotlib numpy scipy")
print("      2) declarar cuál usar:  export ALEPH_CIENCIA_PYTHON=/ruta/a/python3")
print("      (los candidatos y su orden están en pack.py:_CANDIDATOS_PYTHON)")
sys.exit(1)
PYGATE

echo "── [0/3] runtime Legal congelado (Bun $($DOCHAUS_BUN --version)) ──"
(
  cd "$DOCHAUS_ROOT"
  # Vite sólo sigue el SDK interno y sus tsconfig; materializamos ese cierre de compilación,
  # no el monorepo completo. Se crea luego el conjunto de runtime del motor usando su propio
  # filtro. `prepare` sólo instala hooks de contributor y queda inhibido.
  "$DOCHAUS_BUN" install --frozen-lockfile --ignore-scripts --filter './packages/sdk/js'
  (
    cd apps/web
    "$DOCHAUS_BUN" install --frozen-lockfile
    "$DOCHAUS_BUN" run build
  )
  (
    cd services/ingest
    "$DOCHAUS_BUN" install --frozen-lockfile --production
  )
  # EL TERCER DUEÑO DE `node_modules`, y lo destapó la vara de esta obra contra la .app
  # instalada. `dochaus/` —la capa de oficio— TAMPOCO es workspace del monorepo: tiene su
  # propio `package.json` y su `bun.lock`, y de ahí salen `fflate`, `docxodus`, `mammoth`,
  # `unpdf` y `@huggingface/transformers`, que sus 37 tools importan por
  # `dochaus/lib/*.ts`. Sin este install el registro de tools del motor muere entero con
  # `Cannot find package 'fflate'` y `/experimental/tool/ids` devuelve 500 — o sea CERO
  # tools, también las genéricas. Medido: 19 agentes cargaban y ninguna tool.
  # Es el mismo caso que `services/ingest` documenta abajo; upstream instala en los cuatro
  # (su `start.sh`: `for dir in . dochaus services/ingest apps/web`) y acá faltaba uno.
  (
    cd dochaus
    "$DOCHAUS_BUN" install --frozen-lockfile --production
    # search-document importa transformers dinámicamente; extract.ts importa
    # mammoth/unpdf cuando abre documentos. Son dependencias reales de tools,
    # además de ingesta: podarlas rompe búsqueda y extracción en la instalada.
    # Verificar los imports reales antes del freeze, sin cargar modelos ni datos.
    "$DOCHAUS_BUN" -e 'await Promise.all([import("@huggingface/transformers"), import("mammoth"), import("unpdf")]); console.log("cierre de búsqueda/extracción Legal: OK")'
  )
  # Bun conserva paquetes huérfanos al pedir --production sobre un install previo. Se borran
  # sólo los árboles generados de root/web y se reinstala el cierre transitivo de opencode;
  # así el paquete conserva fuentes, ingest y dist pero no empaqueta tooling de desarrollo.
  find "$DOCHAUS_ROOT/node_modules" -depth -delete
  find "$DOCHAUS_ROOT/apps/web/node_modules" -depth -delete
  # ── [Gate 4 · F6 · Legal] EL GRAFO DE RESOLUCIÓN TIENE QUE VIAJAR, NO SÓLO LOS BYTES ──
  #
  # El linker por defecto de Bun en un monorepo es `isolated`: deja un store en
  # `node_modules/.bun/<pkg>@<ver>/` y resuelve TODO lo demás con symlinks relativos —2.366
  # de ellos, medidos en este árbol. PyInstaller no preserva symlinks de directorio y su
  # `os.walk` tampoco los sigue, así que al congelar viajaban los bytes de cada paquete y
  # NO el mapa que los encuentra. El síntoma no aparece en el build ni en la firma: aparece
  # al arrancar el pack en la máquina del usuario, con un `Cannot find package 'yargs'` que
  # mata el motor (exit 1) y se lleva puestos a los tres procesos. Medido contra la `.app`
  # instalada, no en dev — en dev el árbol tiene los symlinks y todo parece sano.
  #
  # `--linker=hoisted` materializa el cierre PLANO en `node_modules/`, con directorios
  # reales: quedan 60 symlinks (50 de ellos `.bin`, que no participan de la resolución de
  # módulos). Cuesta +62 MiB y +3.9k entradas — lejos de las 144.052 que reventaban
  # `codesign` y que motivaron el filtro de este mismo bloque.
  #
  # Y ANTES hay que barrer los `packages/*/node_modules` que dejó cualquier install
  # `isolated` previo: quedan llenos de symlinks COLGADOS al store recién borrado (27
  # directorios, de 4 a 68 links rotos cada uno). Bun resuelve el `node_modules` más
  # cercano primero, así que un link roto ahí es peor que no tener nada — es exactamente
  # el segundo muerto que apareció al arreglar el primero (`packages/core/…/effect`).
  find "$DOCHAUS_ROOT/packages" -type d -name node_modules -prune -exec rm -rf {} +
  "$DOCHAUS_BUN" install --frozen-lockfile --production --ignore-scripts --linker=hoisted --filter './packages/opencode'
  "$DOCHAUS_BUN" run --cwd packages/core fix-node-pty
)
export ALEPH_DOCHAUS_BUN="$DOCHAUS_BUN"

# ── [Aleph] LA CARA DE OFICINA, HORNEADA ACÁ COMO LAS OTRAS CINCO ───────────────────────
#
# EL DEFECTO QUE ESTO CIERRA, y me lo comí el 2026-08-28 después de pasar el día cazándolo
# en otros lados: este script horneaba la cara de Ciencia, Legal, Diseño, Educación y
# Finanzas — y la de Oficina NO. El spec sólo COPIA `apps/app/dist` si existe
# (`aleph_sidecar.spec:708`), así que el build se llevaba el `dist` que hubiera quedado de
# cualquier compilación anterior. Resultado medido: la `.app` recién instalada traía
# `app-CUVnSJui.js`, compilado ANTES del arreglo de los enlaces de archivo — el arreglo
# estaba commiteado, verificado y no viajaba. Los cinco arreglos que sí verifiqué en el
# bundle pasaron porque sus stacks sí tienen su paso acá.
#
# MISMO IDIOMA QUE LOS OTROS CINCO: si el artefacto ya está, no se rehace; si falta, se
# hornea y se falla fuerte si no salió.
OW_ROOT="$REPO/third_party/openwork"
OW_DIST="$OW_ROOT/apps/app/dist"
if esta_fresco "$OW_DIST/index.html" "$OW_ROOT/apps" "$OW_ROOT/packages"; then
  echo "── [0/3·e] cara de Oficina ya horneada ($(du -sh "$OW_DIST" | cut -f1)) ──"
else
  por_que_rehornea "$OW_DIST/index.html" "$OW_ROOT/apps" "$OW_ROOT/packages"
  echo "── [0/3·e] cara de Oficina (pnpm) ──"
  ( cd "$OW_ROOT" && corepack pnpm install --frozen-lockfile && corepack pnpm --filter @openwork/app build )
  [ -f "$OW_DIST/index.html" ] || {
    echo "✗ el build de Oficina no produjo apps/app/dist/index.html"; exit 1; }
fi

# Office's API is a compiled Bun executable too. A fresh UI cannot repair an old
# server (for example, one without the Office preview route).
mkdir -p "$OW_ROOT/bin"
OW_BIN="$OW_ROOT/bin/openwork-server"
if ! esta_fresco "$OW_BIN" "$OW_ROOT/apps/server/src" "$OW_ROOT/apps/server/package.json"; then
  echo "── servidor de Oficina (Bun) ──"
  ( cd "$OW_ROOT/apps/server" && "$DOCHAUS_BUN" run build:bin )
  codesign --force --sign - "$OW_ROOT/apps/server/dist/bin/openwork-server"
  codesign --verify --strict "$OW_ROOT/apps/server/dist/bin/openwork-server"
  cp "$OW_ROOT/apps/server/dist/bin/openwork-server" "$OW_BIN"
fi

# ── [Gate 4 · Fase 6 · Diseño · O1] RUNTIME DEL PACK: EL `.app` ELECTRON, HORNEADO ────────
# Diseño corre sobre un `.app` Electron compilado, no sobre su árbol. Ese `.app` NO está en
# git (el `.gitignore` del proyecto de origen ignora `release/`), así que un checkout limpio
# —o sea, main— no lo tiene: sin este paso el pack muere al entrar con «No hay runtime
# empaquetado de Diseño», que es la misma clase de muerte que costó la fase de Legal (los
# bytes no viajan solos). Se hornea acá y el spec lo empaqueta como ZIP opaco.
#
# Los árboles de compilación se barren DESPUÉS de hornear: `node_modules` son 906 MiB con el
# propio Electron adentro (PyInstaller re-firma sus Mach-O y muere), y `out/` son 15 MiB de
# la misma UI que ya viaja dentro del `.app`. Ninguno de los dos participa del runtime.
CODESIGN_ROOT="$REPO/third_party/codesign"
CODESIGN_ZIP="$CODESIGN_ROOT/apps/desktop/release/aleph-diseno-mac-arm64.zip"
[ -d "$CODESIGN_ROOT" ] || { echo "✗ falta el árbol Diseño: $CODESIGN_ROOT"; exit 1; }
if esta_fresco "$CODESIGN_ZIP" "$CODESIGN_ROOT/apps" "$CODESIGN_ROOT/packages" "$HERE/build_app.sh"; then
  echo "── [0/3·b] runtime Diseño ya horneado ($(du -h "$CODESIGN_ZIP" | cut -f1)) ──"
else
  command -v pnpm >/dev/null 2>&1 || { echo "✗ falta pnpm para hornear el runtime Diseño"; exit 1; }
  echo "── [0/3·b] runtime Diseño congelado (Electron · pnpm $(pnpm --version)) ──"
  (
    cd "$CODESIGN_ROOT"
    pnpm install --frozen-lockfile
    # Plataforma y arquitectura EXPLÍCITAS: `build:dir` deja que electron-builder infiera del
    # host, y lo que se hornea acá tiene que ser el mismo artefacto que se probó.
    pnpm --filter @open-codesign/desktop run build
    CSC_IDENTITY_AUTO_DISCOVERY=false pnpm --filter @open-codesign/desktop exec electron-builder --dir --mac --arm64 --publish never
    cd apps/desktop
    [ -d "release/mac-arm64/Aleph Diseno.app" ] || {
      echo "✗ electron-builder no produjo 'Aleph Diseno.app'"; exit 1; }
    # El bundle de validación no debe descubrir ni incrustar la identidad personal
    # de Developer ID de este host. Firma ad hoc real y verifica antes de empaquetar.
    codesign --force --deep --sign - "release/mac-arm64/Aleph Diseno.app"
    codesign --verify --deep --strict "release/mac-arm64/Aleph Diseno.app"
    codesign -dv --verbose=4 "release/mac-arm64/Aleph Diseno.app" 2>&1 | grep 'Signature=adhoc' >/dev/null || {
      echo "✗ Diseño no quedó firmado ad hoc"; exit 1; }
    /usr/bin/ditto -c -k --sequesterRsrc --keepParent \
      "release/mac-arm64/Aleph Diseno.app" "release/aleph-diseno-mac-arm64.zip"
  )
fi
rm -rf "$CODESIGN_ROOT/apps/desktop/release/mac-arm64" "$CODESIGN_ROOT/apps/desktop/out"
find "$CODESIGN_ROOT" -type d -name node_modules -prune -exec rm -rf {} + 2>/dev/null || true
echo "── [0/3] backend congelado de Educación + avisos PDFium ──"
EDU_ROOT="$REPO/third_party/deeptutor"
EDU_PYTHON_BIN="${ALEPH_DEEPTUTOR_PYTHON:-$(command -v python3.13 || true)}"
UV_BIN="${ALEPH_UV:-$HOME/.local/bin/uv}"
[ -x "$EDU_PYTHON_BIN" ] || {
  echo "✗ falta Python 3.13 para congelar Educación (usar ALEPH_DEEPTUTOR_PYTHON)"; exit 1; }
[ -x "$UV_BIN" ] || {
  echo "✗ falta uv para provisionar el runtime de Educación: $UV_BIN"; exit 1; }
[ -s "$EDU_ROOT/requirements-lock.txt" ] || {
  echo "✗ falta el lock de Educación: $EDU_ROOT/requirements-lock.txt"; exit 1; }
TMP_EDU_VENV="$(mktemp -d)"; TMP_EDU_DIST="$(mktemp -d)"; TMP_EDU_WORK="$(mktemp -d)"
PYI_CFG="$(mktemp -d)"
trap 'rm -rf "$TMP_EDU_VENV" "$TMP_EDU_DIST" "$TMP_EDU_WORK" "$PYI_CFG"' EXIT
"$UV_BIN" venv --python "$EDU_PYTHON_BIN" "$TMP_EDU_VENV"
"$UV_BIN" pip sync --python "$TMP_EDU_VENV/bin/python" "$EDU_ROOT/requirements-lock.txt"
"$UV_BIN" pip install --python "$TMP_EDU_VENV/bin/python" "pyinstaller==6.21.0"

# Los avisos salen del mismo entorno efímero que congela el backend; la ruta no se hornea.
PDFIUM_LICENSES="$(ls -d "$TMP_EDU_VENV"/lib/python*/site-packages/pypdfium2-*.dist-info/licenses 2>/dev/null | head -1)"
[ -n "$PDFIUM_LICENSES" ] && [ -d "$PDFIUM_LICENSES" ] || {
  echo "✗ faltan avisos pypdfium2/PDFium en el venv de Educación"; exit 1; }
mkdir -p "$SHELL_DIR/src-tauri/resources"
rm -rf "$SHELL_DIR/src-tauri/resources/PDFIUM-NOTICES"
cp -R "$PDFIUM_LICENSES" "$SHELL_DIR/src-tauri/resources/PDFIUM-NOTICES"

PYINSTALLER_CONFIG_DIR="$PYI_CFG" "$TMP_EDU_VENV/bin/pyinstaller" --clean --noconfirm --distpath "$TMP_EDU_DIST" --workpath "$TMP_EDU_WORK" \
  "$HERE/deeptutor_pack.spec"
EDU_BACKEND="$TMP_EDU_DIST/deeptutor_backend"
[ -x "$EDU_BACKEND/deeptutor_backend" ] || {
  echo "✗ no se produjo backend onedir de Educación"; exit 1; }
"$VENV_PYTHON" "$HERE/verificar_entorno_packs.py" educacion \
  "$EDU_BACKEND/deeptutor_backend" \
  pypdfium2 fastapi uvicorn pydantic httpx deeptutor numpy || exit 1
NODE_BIN="$(command -v node)"
[ -x "$NODE_BIN" ] || { echo "✗ falta node para el standalone de Educación"; exit 1; }

# ── [Gate 4 · Fase 6 · Educación] LA CARA DEL TUTOR, HORNEADA ──────────────────────────────
# El `standalone` de Next (`server.js` + su cierre mínimo) NO está en git —el `.gitignore` del
# proyecto de origen ignora `.next/`— así que un checkout limpio, o sea main, no lo tiene y el
# spec muere. Es la misma clase de muerte que la del runtime de Diseño: los bytes no viajan
# solos. Se hornea acá, y sólo si falta: rehacerlo en cada build cuesta minutos y no cambia
# nada cuando el árbol no se tocó.
EDU_WEB="$REPO/third_party/deeptutor/web"
# `server.js` alone is not a runnable standalone: Next can leave a stale output
# with its server entry but without the traced `node_modules/next` closure (for
# example after a cleanup or a version change). Validate the dependency that the
# installed launcher actually resolves, and rebuild when the closure is absent.
if [ -d "$EDU_WEB/.next/standalone/node_modules/next" ] \
   && esta_fresco "$EDU_WEB/.next/standalone/server.js" "$EDU_WEB/app" "$EDU_WEB/src" "$EDU_WEB/components" "$EDU_WEB/public" "$EDU_WEB/locales"; then
  echo "── [0/3·c] cara de Educación ya horneada ──"
else
  por_que_rehornea "$EDU_WEB/.next/standalone/server.js" "$EDU_WEB/app" "$EDU_WEB/src" "$EDU_WEB/components" "$EDU_WEB/public" "$EDU_WEB/locales"
  echo "── [0/3·c] cara de Educación congelada (Next standalone) ──"
  (
    cd "$EDU_WEB"
    [ -d node_modules ] || npm ci --no-audit --no-fund
    npm run build
  )
  [ -f "$EDU_WEB/.next/standalone/server.js" ] || {
    echo "✗ el build de Educación no produjo .next/standalone/server.js"; exit 1; }
fi

# ── [Aleph · 2026-08-11] EL STANDALONE NO SE LLEVA SU CARA ─────────────────────────────────
# `next build` deja el `standalone` con el servidor y su cierre de node_modules, pero NO copia
# `.next/static` ni `public`: es un paso manual que Next documenta y que este script no hacía
# —medido: `grep -c static` daba 0—. En el árbol no se nota, porque el server encuentra los
# assets por la ruta del proyecto; empaquetado en el `.app` Educación arrancaba SIN css, sin
# js y sin imágenes. Misma clase de muerte que el standalone que no está en git: los bytes no
# viajan solos.
#
# Se copia siempre, no sólo cuando se hornea: un `.next/standalone` cacheado de un build
# anterior a este arreglo tampoco los tiene, y entonces el bug sobreviviría al arreglo.
echo "── [0/3·c·bis] assets de Educación junto al standalone ──"
[ -d "$EDU_WEB/.next/static" ] || {
  echo "✗ Educación no produjo .next/static"; exit 1; }
# Se borra el destino antes de copiar: `cp -R origen destino` con el destino YA existente
# anida (`static/static`) en vez de reemplazar, y este script se corre muchas veces.
mkdir -p "$EDU_WEB/.next/standalone/.next"
rm -rf "$EDU_WEB/.next/standalone/.next/static" "$EDU_WEB/.next/standalone/public"
cp -R "$EDU_WEB/.next/static" "$EDU_WEB/.next/standalone/.next/static"
[ -d "$EDU_WEB/public" ] && cp -R "$EDU_WEB/public" "$EDU_WEB/.next/standalone/public"
[ -d "$EDU_WEB/.next/standalone/.next/static" ] || {
  echo "✗ no se copió .next/static al standalone de Educación"; exit 1; }
echo "  ✓ static$([ -d "$EDU_WEB/public" ] && echo ' + public') junto a server.js"

echo "── [0/3·d] backend congelado de Finanzas + UI ──"
VIBE_ROOT="$REPO/third_party/vibetrading"
VIBE_WEB="$VIBE_ROOT/frontend"
VIBE_PYTHON_BIN="${ALEPH_VIBETRADING_PYTHON:-/opt/homebrew/bin/python3.13}"
UV_BIN="${ALEPH_UV:-$HOME/.local/bin/uv}"
[ -d "$VIBE_ROOT" ] || { echo "✗ falta el árbol Finanzas: $VIBE_ROOT"; exit 1; }
[ -x "$VIBE_PYTHON_BIN" ] || {
  echo "✗ falta Python 3.13 para congelar Finanzas: $VIBE_PYTHON_BIN"; exit 1; }
[ -x "$UV_BIN" ] || {
  echo "✗ falta uv para provisionar el runtime de Finanzas: $UV_BIN"; exit 1; }
if esta_fresco "$VIBE_WEB/dist/index.html" "$VIBE_WEB/src" "$VIBE_WEB/public"; then
  echo "  · cara de Finanzas ya horneada"
else
  por_que_rehornea "$VIBE_WEB/dist/index.html" "$VIBE_WEB/src" "$VIBE_WEB/public"
  echo "  · horneando cara de Finanzas (Vite)"
  (
    cd "$VIBE_WEB"
    [ -d node_modules ] || npm ci --no-audit --no-fund
    npm run build
  )
  [ -f "$VIBE_WEB/dist/index.html" ] || {
    echo "✗ el build de Finanzas no produjo frontend/dist/index.html"; exit 1; }
fi

# El venv sólo es insumo de compilación. El backend se entrega como onedir dentro del
# onefile exterior de Aleph: conserva intérprete y dependencias, pero evita que al entrar
# al workspace PyInstaller vuelva a descomprimir un segundo onefile completo.
TMP_VIBE_VENV="$(mktemp -d)"; TMP_VIBE_DIST="$(mktemp -d)"; TMP_VIBE_WORK="$(mktemp -d)"
"$UV_BIN" venv --python "$VIBE_PYTHON_BIN" "$TMP_VIBE_VENV"
"$UV_BIN" pip sync --python "$TMP_VIBE_VENV/bin/python" "$VIBE_ROOT/requirements-lock.txt"
"$UV_BIN" pip install --python "$TMP_VIBE_VENV/bin/python" "pyinstaller==6.21.0"
PYINSTALLER_CONFIG_DIR="$PYI_CFG" "$TMP_VIBE_VENV/bin/pyinstaller" --clean --noconfirm \
  --distpath "$TMP_VIBE_DIST" --workpath "$TMP_VIBE_WORK" "$HERE/vibetrading_pack.spec"
VIBE_BACKEND="$TMP_VIBE_DIST/vibe_trading_backend"
[ -x "$VIBE_BACKEND/vibe_trading_backend" ] || {
  echo "✗ no se produjo backend onedir de Finanzas"; exit 1; }
# EL PACK NO SE HORNEA PELADO. Que el binario exista no dice que lleve adentro lo que sus
# tools importan: los módulos de Python puro viven en el PYZ, no en el disco del onedir, y
# un `find` da AUSENTE para cosas que sí viajan. Se le pregunta al binario.
"$VENV_PYTHON" "$HERE/verificar_entorno_packs.py" finanzas \
  "$VIBE_BACKEND/vibe_trading_backend" \
  fastmcp defusedxml yfinance ccxt langchain_core pptx pandas numpy src backtest || exit 1

echo "── guest integrity: stage, freeze, then sign and hash final bytes ──"
GUEST_SOURCE_RUNTIME="$REPO/deploy/guest/runtime"
GUEST_ENTITLEMENTS="$REPO/deploy/guest/Virtualization.entitlements"
GUEST_BUILD_RUNTIME="$(mktemp -d)"
cp "$GUEST_SOURCE_RUNTIME/aleph-guest-runner" "$GUEST_BUILD_RUNTIME/aleph-guest-runner"
cp "$GUEST_SOURCE_RUNTIME/Image.arm64" "$GUEST_BUILD_RUNTIME/Image.arm64"
cp "$GUEST_SOURCE_RUNTIME/rootfs.arm64.cpio.gz" "$GUEST_BUILD_RUNTIME/rootfs.arm64.cpio.gz"
"$VENV_PYTHON" "$REPO/deploy/guest/generate_manifest.py" \
  --runtime "$GUEST_BUILD_RUNTIME" \
  --output "$GUEST_BUILD_RUNTIME/guest-manifest.json"
export ALEPH_GUEST_RUNTIME="$GUEST_BUILD_RUNTIME"

echo "── [1/3] sidecar $([ \"${ALEPH_SIDECAR_ONEFILE:-0}\" = 1 ] && echo onefile || echo onedir) (ALEPH_BUILD=$BUILD) ──"
TMP_DIST="$(mktemp -d)"; TMP_WORK="$(mktemp -d)"
# Los temporales de Educación entran en ESTE trap: `trap ... EXIT` REEMPLAZA al anterior, así
# que sin nombrarlos acá un build que muriera entre este paso y el guard dejaba tirados el
# dist y el workpath del backend congelado de Educación — cientos de MiB, en una máquina
# donde el disco lleno ya se disfrazó dos veces de error de firma.
trap 'rm -rf "$TMP_DIST" "$TMP_WORK" "$TMP_EDU_VENV" "$TMP_EDU_DIST" "$TMP_EDU_WORK" "$TMP_VIBE_VENV" "$TMP_VIBE_DIST" "$TMP_VIBE_WORK" "$PYI_CFG" "$GUEST_BUILD_RUNTIME"' EXIT
# LA PERILLA, PASABLE POR ENTORNO. El spec tiene las DOS ramas
# (`ALEPH_SIDECAR_ONEFILE=1` → EXE onefile; si no → EXE+COLLECT onedir).
# Default 0 = ONEDIR. Estuvo en 1 y mordió dos veces el mismo día: el onefile
# descomprime ~200 MB en `/var/folders/…/T/_MEIxxxx` en CADA arranque, y eso son
# 53 s medidos desde el spawn hasta que /health contesta 200 — contra un onedir,
# que sirve desde `Contents/Frameworks/` y abre al toque. Además deja los `_MEI`
# tirados: 8,8 GiB de huérfanos de procesos muertos en una máquina donde el disco
# lleno ya se disfrazó de error de firma. Para volver al onefile: exportar
# ALEPH_SIDECAR_ONEFILE=1 a propósito.
ONEFILE="${ALEPH_SIDECAR_ONEFILE:-0}"
PYINSTALLER_CONFIG_DIR="$PYI_CFG" ALEPH_SIDECAR_ONEFILE="$ONEFILE" ALEPH_BUILD="$BUILD" ALEPH_DEEPTUTOR_BACKEND="$EDU_BACKEND" ALEPH_DEEPTUTOR_NODE="$NODE_BIN" ALEPH_VIBETRADING_BACKEND="$VIBE_BACKEND" "$VENV_PY" --clean --noconfirm \
  --distpath "$TMP_DIST" --workpath "$TMP_WORK" "$HERE/aleph_sidecar.spec"
# El EJECUTABLE, que en onedir no está donde en onefile. Todo lo que sigue —el chequeo del
# secreto, el gate del bundle— habla con el binario, no con el layout.
if [ "$ONEFILE" = "1" ]; then
  SIDE_BIN="$TMP_DIST/aleph_sidecar"
else
  SIDE_BIN="$TMP_DIST/aleph_sidecar/aleph_sidecar"
fi
[ -x "$SIDE_BIN" ] || { echo "✗ PyInstaller no dejó ejecutable en $SIDE_BIN"; exit 1; }
if [ "$ONEFILE" = "1" ]; then
  mkdir -p "$SHELL_DIR/src-tauri/binaries"
  cp "$SIDE_BIN" "$SHELL_DIR/src-tauri/binaries/aleph_sidecar-$TRIPLE"
  chmod +x "$SHELL_DIR/src-tauri/binaries/aleph_sidecar-$TRIPLE"
  echo "  ✓ sidecar $BUILD → binaries/aleph_sidecar-$TRIPLE ($(du -h "$SHELL_DIR/src-tauri/binaries/aleph_sidecar-$TRIPLE" | cut -f1))"
else
  # ONEDIR · CERO CAMBIOS EN RUST, y no es un truco: `resolve_sidecar()` ya busca
  # `<dir del ejecutable>/aleph_sidecar`, y PyInstaller onedir pide exactamente eso —
  # el stub con su `_internal/` AL LADO. Así que el stub entra por `externalBin` como
  # siempre (Tauri lo copia a `Contents/MacOS/` y lo firma) y `_internal/` se copia
  # ahí mismo DESPUÉS del `tauri build`. El `--parent-pid`, el log y el cierre con
  # SIGTERM siguen siendo los de siempre.
  mkdir -p "$SHELL_DIR/src-tauri/binaries"
  cp "$SIDE_BIN" "$SHELL_DIR/src-tauri/binaries/aleph_sidecar-$TRIPLE"
  chmod +x "$SHELL_DIR/src-tauri/binaries/aleph_sidecar-$TRIPLE"
  echo "  ✓ sidecar $BUILD ONEDIR → stub $(du -h "$SIDE_BIN" | cut -f1) + _internal $(du -sh "$TMP_DIST/aleph_sidecar/_internal" | cut -f1)"
fi

# El artefacto ya está copiado: los workpaths de PyInstaller y los venvs temporales de
# Educación y Finanzas no participan en el gate. Liberarlos ANTES de extraer el onefile es esencial
# porque el gate necesita espacio para el sidecar entero más su `_MEI` de prueba.
rm -rf "$TMP_WORK" "$TMP_EDU_VENV" "$TMP_EDU_DIST" "$TMP_EDU_WORK" \
  "$TMP_VIBE_VENV" "$TMP_VIBE_DIST" "$TMP_VIBE_WORK"

# Desde acá el sidecar ya es autocontenido: el gate siguiente lo extrae desde el
# binario y Tauri tampoco lee el árbol Legal. Los node_modules materializados sólo
# fueron insumo de PyInstaller; conservarlos durante la extracción duplica ~1 GiB
# y convierte un gate de runtime en un falso fallo de disco. Son regenerables desde
# bun.lock y se podan únicamente después de copiar el sidecar terminado.
find "$DOCHAUS_ROOT" -maxdepth 1 -type d -name node_modules -prune -exec rm -rf {} +
find "$DOCHAUS_ROOT/services/ingest" -maxdepth 1 -type d -name node_modules -prune -exec rm -rf {} +
find "$DOCHAUS_ROOT/dochaus" -maxdepth 1 -type d -name node_modules -prune -exec rm -rf {} +
find "$VIBE_WEB" -maxdepth 1 -type d -name node_modules -prune -exec rm -rf {} +

# OAuth gate uses an explicit isolated test config, never the user's local override.
# It also rejects private config filenames inside the artifact.
"$VENV_PYTHON" "$REPO/qa/assert_no_onshape_secret.py" \
  --local-config "${ALEPH_ONSHAPE_TEST_CONFIG:-$ALEPH_BUILD_OUTPUT/onshape-test.local.json}" \
  --target "$SIDE_BIN"

# ─────────── [FIX-P1B · §8] GATE: ¿VIAJARON TODOS LOS ARCHIVOS NUESTROS? ───────────
# PyInstaller pierde CALLADO los módulos que el producto abre por ruta: no hay ImportError
# en el build, sólo un archivo que no está y un crash tres pantallas más tarde, que la UI
# le cobraba al proveedor («Error del proveedor» por un assembler.py que no viajó — el caso
# índice). El gate levanta ESTE binario y le pregunta a él (`/v1/motor/arranque`): es la
# única respuesta que vale, porque _MEIPASS reubica datos y el PYZ se traga módulos.
# Se corre acá, con el sidecar recién hecho, ANTES de gastar un tauri build de minutos.
echo "── gate: el bundle está completo ──"
if ! "$VENV_PYTHON" "$REPO/qa/gate_bundle_aleph.py" \
      --sidecar "$SIDE_BIN" --port "${ALEPH_GATE_PORT:-8278}"; then
  echo
  # ⚠️ EL GATE DETECTA BIEN Y DIAGNOSTICABA MAL. Este mensaje decía «falta código NUESTRO
  # adentro del bundle», que es UNA de las causas y no la única. Medido el 2026-08-18: el
  # sidecar de §6.f no arrancó porque el binario pesaba 2,09 GB y dyld no pudo mapear el
  # shared cache —«dyld cache '(null)' not loaded»—, o sea que murió ANTES de ejecutar una
  # línea nuestra. No faltaba código: faltaba que el ejecutable cargara. Con el mensaje
  # viejo la sesión se va a buscar un archivo perdido, que es exactamente el lugar donde
  # no está el problema.
  echo "✗✗ EL SIDECAR NO SE CERTIFICA: el bundle recién hecho no pasó su propia sonda."
  echo "   Se aborta antes del .app: distribuirlo así le cobra nuestro bug al usuario."
  echo
  echo "   Las dos causas, y se distinguen mirando la salida de arriba:"
  echo "   · si hay traza de Python o un 404 de /v1/motor/arranque → EL BINARIO ARRANCÓ y"
  echo "     le falta algo adentro: un módulo que se abre por ruta y no viajó."
  echo "   · si el proceso murió con un error de dyld (\"dyld cache not loaded\","
  echo "     \"Library not loaded\") → NO LLEGÓ A ARRANCAR, y no falta código: el"
  echo "     ejecutable no carga. Suele ser el TAMAÑO — este es un onefile y todo lo que"
  echo "     el spec mete va adentro del binario. Comparar con uno que sí arranca:"
  echo "       ls -l \"$TMP_DIST/aleph_sidecar\" <reference-sidecar>"
  exit 1
fi

# [TANDA 3] Parada para MEDIR el sidecar solo (tamaño / arranque) sin pagar el build de
# Tauri. El dist temporal se conserva a propósito: es lo que se va a medir.
if [ "${ALEPH_BUILD_SOLO_SIDECAR:-0}" = "1" ]; then
  # ⚠️ FUERA DE TODO SEGMENTO DE ANCLAJE. `aleph_paths._TOP_LEVEL` incluye `deploy`,
  # `platform`, `product`, `qa`… y `load_module_by_path` reubica desde el PRIMER segmento
  # que matchea. Con el onedir en `deploy/fase4/…`, `resource_root()/deploy/fase4/…/platform/x.py`
  # anclaba en `deploy` y salía la ruta DUPLICADA — medido 2026-08-22, el sidecar moría en
  # `connect_engine.py`. En onefile no puede pasar (`_MEIPASS` es `/var/folders/…/_MEIxxxx`);
  # en onedir la raíz es una ruta real y el lugar donde se instala IMPORTA.
  KEEP="$ALEPH_BUILD_OUTPUT/sidecar"
  [ ! -e "$KEEP" ] || { echo "✗ sidecar output already exists: $KEEP"; exit 1; }
  mkdir -p "$(dirname "$KEEP")"
  mv "$TMP_DIST/aleph_sidecar" "$KEEP"
  echo "── SOLO SIDECAR: certificado y movido a $KEEP"
  du -sh "$KEEP"
  exit 0
fi

echo "── [2/3] config de Tauri por build ──"
# public es el default de tauri.conf.json (productName=Aleph, id=app.aleph.desktop). founder/dev
# se distinguen para coexistir en la misma máquina sin pisarse.
case "$BUILD" in
  founder) CONF='{"productName":"Aleph Founder","identifier":"app.aleph.desktop.founder"}' ;;
  dev)     CONF='{"productName":"Aleph Dev","identifier":"app.aleph.desktop.dev"}' ;;
  *)       CONF='{}' ;;
esac
case "$BUILD" in
  founder) APP_BUNDLE_NAME='Aleph Founder.app' ;;
  dev)     APP_BUNDLE_NAME='Aleph Dev.app' ;;
  *)       APP_BUNDLE_NAME='Aleph.app' ;;
esac
echo "  config override: $CONF"

# Isolated app bundles only: DMG tooling is excluded from this entry point.
[ "${ALEPH_DMG:-0}" != 1 ] || { echo "✗ DMG disabled in isolated build"; exit 1; }
BUNDLES="app"
trap 'rm -rf "$TMP_DIST" "$TMP_WORK" "$TMP_EDU_DIST" "$TMP_EDU_WORK" "$PYI_CFG"' EXIT

echo "── [3/3] tauri build (bundles: $BUNDLES) ──"
cd "$SHELL_DIR"
# El shell tiene lock npm propio. El sidecar no puede asumir que una rama/worktree conserve
# node_modules: se materializa exactamente desde package-lock antes de invocar el CLI local.
if [ ! -x "$SHELL_DIR/node_modules/.bin/tauri" ]; then
  echo "  · materializando CLI Tauri desde package-lock"
  npm ci
fi
if [ "$CONF" = "{}" ]; then
  npx --no-install tauri build --bundles "$BUNDLES"
else
  npx --no-install tauri build --bundles "$BUNDLES" --config "$CONF"
fi

# ── ONEDIR · `_internal/` AL LADO DEL STUB, DENTRO DEL .app ────────────────────────────
# Va DESPUÉS del `tauri build` a propósito: Tauri firma lo que copia, y estos 5 GB no
# necesitan firma propia (el bundle es adhoc y `Sealed Resources=none` — medido en la
# instalada). Si esto no está, el stub arranca y muere buscando su `_internal`.
if [ "$ONEFILE" != "1" ]; then
  APP_C="$CARGO_TARGET_DIR/release/bundle/macos/$APP_BUNDLE_NAME/Contents"
  [ -d "$APP_C/MacOS" ] || { echo "✗ tauri no dejó el .app donde se esperaba: $APP_C"; exit 1; }
  # ⚠️ `Contents/Frameworks`, NO `Contents/MacOS/_internal`. MEDIDO 2026-08-22: el
  # bootloader de PyInstaller detecta que su ejecutable está en `…/Contents/MacOS/` y
  # aplica el layout de APP BUNDLE de macOS — busca sus cosas en `Contents/Frameworks`,
  # no en `_internal/` al lado. Con `_internal` el sidecar moría antes de una línea:
  #   [PYI-ERROR] Failed to load Python shared library '…/Contents/Frameworks/Python'
  rm -rf "$APP_C/Frameworks"
  cp -R "$TMP_DIST/aleph_sidecar/_internal" "$APP_C/Frameworks"
  APP_MACOS="$APP_C/Frameworks"
  # FALLO VISIBLE: sin esta comprobación un `cp` a medias produce un .app que arranca y
  # muere tres pantallas después, que es justo lo que este repo no permite.
  [ -f "$APP_MACOS/base_library.zip" ] || {
    echo "✗ el _internal copiado no tiene base_library.zip — copia incompleta"; exit 1; }
  echo "  ✓ onedir: payload plantado en Contents/Frameworks ($(du -sh "$APP_MACOS" | cut -f1))"
fi

echo "── firma final: sellando el bundle completo, incluido Frameworks ──"
FINAL_APP="$CARGO_TARGET_DIR/release/bundle/macos/$APP_BUNDLE_NAME"
"$VENV_PYTHON" "$HERE/ordenar_payload_macos.py" "$FINAL_APP"
codesign --force --sign - "$FINAL_APP"
codesign --verify --strict "$FINAL_APP"

echo "── gate: guest bytes equal packaged expected hashes ──"
"$VENV_PYTHON" "$REPO/qa/verify_guest_packaged_hash.py" --app "$FINAL_APP"
"$VENV_PYTHON" "$REPO/qa/verify_bundle_without_searxng.py" --app "$FINAL_APP"

"$VENV_PYTHON" "$REPO/qa/assert_no_onshape_secret.py" \
  --local-config "${ALEPH_ONSHAPE_TEST_CONFIG:-$ALEPH_BUILD_OUTPUT/onshape-test.local.json}" \
  --target "$CARGO_TARGET_DIR/release/bundle/macos"

echo "── LISTO: build=$BUILD ──"
[ "$BUILD" = "founder" ] && echo "⚠️  RECORDATORIO: el artefacto founder NUNCA se distribuye (privado del dueño)."
echo "artefactos en: $CARGO_TARGET_DIR/release/bundle/"
