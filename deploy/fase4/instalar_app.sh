#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# instalar_app.sh — instala en /Applications el bundle construido por build_app.sh.
#
# UN solo install canónico, con las lecciones que costaron un día entero:
#
#   1. `$SUDO` CONDICIONAL. En esta Mac /Applications es drwxrwxr-x root:admin y
#      Aleph.app puede pertenecer al usuario local: no asumir que sudo hace falta.
#      NO es "más seguro": en una shell SIN TTY no puede pedir la clave y el bloque
#      muere a mitad de camino (le pasó a P2). Se usa sólo si de verdad hace falta.
#
#   2. `rm -rf` ANTES de copiar. `cp -R nuevo.app /Applications/` sobre un bundle
#      existente NO reemplaza: FUSIONA árbol con árbol (hallazgo de P1A). Quedan
#      archivos de la versión vieja conviviendo con los de la nueva — un bundle que no
#      es ninguna de las dos. Se borra primero, siempre.
#
#   3. GUARDA CROSS-SESIÓN. Varias sesiones comparten esta máquina y /Applications es
#      global. Se fotografía el estado ANTES (nombre + sha256 del sidecar de cada
#      bundle) y se re-verifica JUSTO ANTES del paso destructivo: si otra sesión tocó
#      /Applications mientras corríamos, se ABORTA sin escribir nada.
#
#   4. RESPALDO DURABLE. La instalada anterior se guarda como Aleph.pre-<etiqueta>.app
#      y NO se pisa un respaldo previo. Es lo que hace reversible todo lo de abajo.
#
#   5. Se para de una si algo no está como espera. Fallo visible, jamás mudo: nada
#      avanza a ciegas después de un paso que no cerró.
#
# Uso:
#   bash deploy/fase4/instalar_app.sh [etiqueta]      # etiqueta default: pre-install
#   ALEPH_APP_SRC=/ruta/al/Aleph.app bash deploy/fase4/instalar_app.sh tanda-p
#
# Rollback (bloque independiente, pegable solo):
#   pkill -f '/Applications/Aleph.app' || true; sleep 2
#   rm -rf /Applications/Aleph.app
#   mv /Applications/Aleph.pre-<etiqueta>.app /Applications/Aleph.app
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ETIQUETA="${1:-pre-install}"
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NUEVA="${ALEPH_APP_SRC:-$AQUI/aleph-shell/src-tauri/target/release/bundle/macos/Aleph.app}"
INST="/Applications/Aleph.app"
BAK="/Applications/Aleph.pre-${ETIQUETA}.app"

# LA HUELLA DEL SIDECAR · vale para los DOS layouts. [TANDA 3]
#
# Con onefile, hashear `Contents/MacOS/aleph_sidecar` alcanzaba: TODO estaba adentro de ese
# archivo. Con ONEDIR el ejecutable es un stub de 46 MB y el payload —5 GB de datos, los
# tres binarios de terceros, los dos backends anidados— vive en `Contents/Frameworks/`.
#
# El stub NO deja de discriminar: lleva el PYZ, así que cambia cuando cambia el código
# Python (verificado: `CArchiveReader(stub).toc` trae su `.pyz`). Lo que NO vería es un dato
# o un binario ajeno distinto. Así que la huella suma un CENSO de `Frameworks`: cantidad de
# archivos y bytes totales, que es un `find` y no una lectura de 5 GB. Detecta agregados,
# borrados y cambios de tamaño; un cambio de contenido a IGUAL tamaño se le escapa, y eso se
# dice acá en vez de fingir que la huella es un hash del árbol.
#
# ⚠️ Y LA CÁSCARA TAMBIÉN CUENTA. [2026-08-29] La huella miraba el sidecar y `Frameworks`, y
# NO el binario de Tauri (`Contents/MacOS/app`), que es donde vive el Rust de la cáscara. Un
# build cuyo único cambio era ése salía con huella IDÉNTICA, y el instalador contestaba «YA
# es este build — nada que hacer» y no copiaba nada. Medido con el arreglo que manda los
# links externos al navegador: build verde, install «exitoso», y la app sin el arreglo. El
# instalador no mintió: comparó lo que sabía comparar. Le faltaba una tercera pata.
sha_side() {
  local stub="$1/Contents/MacOS/aleph_sidecar"
  local h; h="$(shasum -a 256 "$stub" 2>/dev/null | cut -d' ' -f1)"
  [ -n "$h" ] || return 0
  local cascara; cascara="$(shasum -a 256 "$1/Contents/MacOS/app" 2>/dev/null | cut -d' ' -f1)"
  h="$h/${cascara:0:12}"
  local fw="$1/Contents/Frameworks"
  if [ -d "$fw" ]; then
    # PyInstaller BUNDLE cross-links Frameworks and Resources. Census the whole
    # bundle once; the UI hash below follows links to the actual text assets.
    local censo; censo="$(find "$1/Contents" -type f -print0 2>/dev/null | xargs -0 stat -f '%z' 2>/dev/null \
      | awk '{n++; b+=$1} END {printf "%d:%d", n, b}')"
    # ⚠️ 🔧 EL CENSO CUENTA Y PESA, PERO NO LEE — Y ESO DEJÓ PASAR UN BUILD DISTINTO.
    #
    # Medido el 2026-09-11: un cambio en la cara de Oficina movió `px-6` de un lado al otro de
    # un ternario. Los MISMOS caracteres en otro orden: mismo tamaño de archivo, misma cantidad
    # de archivos, mismo total de bytes. El censo dio idéntico —`134004:5038234726` en los dos
    # builds— y este instalador dijo «YA es este build — nada que hacer» sobre un bundle que SÍ
    # era distinto. La .app se quedó con la cara vieja y la pantalla no cambiaba, sin una sola
    # señal de que no se había instalado nada.
    #
    # No es un defecto de la idea: es su punto ciego. Un censo de tamaño ve TODO lo que crece o
    # encoge y es ciego a lo que se reordena. Así que se le suma una huella que LEE: el sha de
    # los shas de los assets de texto de los stacks, que es donde vive su cara.
    #
    # Sólo `.js`, `.css` y `.html` de `third_party/`: medido, 23.877 archivos en ~4 s. Los
    # binarios ya los cubren el sha del sidecar, el de la cáscara y el censo de tamaño —a un
    # binario no se le reordenan los bytes sin cambiarle el peso—. Cuatro segundos contra copiar
    # 5 GB es nada, y el costo de NO tenerlo ya se pagó una vez.
    #
    # Esto sólo puede volver el chequeo MÁS estricto: en el peor caso reinstala algo que ya
    # estaba, que es barato. Al revés —decir «ya está» cuando no está— es el que miente.
    # ⚠️ SE HASHEAN LOS HASHES, NO LA SALIDA DE `shasum`. Esa salida es «<hash>  <ruta>», y la
    # ruta del bundle no es la de /Applications: dejarla adentro hacía que la huella NO
    # coincidiera NUNCA, ni con una copia idéntica. Lo cazó este mismo instalador en su chequeo
    # de después de copiar, la primera vez que corrió. El `sort` va sobre las rutas —que sólo
    # difieren en el prefijo, así que el orden relativo es el mismo— y el `awk` se queda con el
    # hash solo.
    local cara; cara="$(find -L "$fw/third_party" \( -name '*.js' -o -name '*.css' -o -name '*.html' \) \
      -type f -print0 2>/dev/null | sort -z | xargs -0 shasum -a 256 2>/dev/null \
      | awk '{print $1}' | shasum -a 256 | cut -c1-12)"
    printf '%s+%s+%s\n' "$h" "$censo" "${cara:-sin-cara}"
  else
    printf '%s\n' "$h"
  fi
}
foto()     { for b in /Applications/Aleph*.app; do [ -e "$b" ] || continue; echo "$(basename "$b") $(sha_side "$b")"; done | sort; }

# ── 0 · precondiciones ───────────────────────────────────────────────────────
[ -d "$NUEVA" ] || { echo "✗ no existe el build: $NUEVA"; echo "  construilo: bash deploy/fase4/build_app.sh public"; exit 1; }
[ -x "$NUEVA/Contents/MacOS/aleph_sidecar" ] || { echo "✗ el build no trae sidecar ejecutable"; exit 1; }
[ -e "$BAK" ] && { echo "✗ ya existe un respaldo en $BAK — movelo o borralo antes (no lo piso)"; exit 1; }

SHA_NUEVA="$(sha_side "$NUEVA")"
[ -n "$SHA_NUEVA" ] || { echo "✗ no pude hashear el sidecar del build"; exit 1; }
if [ -d "$INST" ] && [ "$(sha_side "$INST")" = "$SHA_NUEVA" ]; then
  echo "✓ /Applications/Aleph.app YA es este build ($SHA_NUEVA) — nada que hacer."
  exit 0
fi

# ── 1 · guarda cross-sesión: foto ANTES ──────────────────────────────────────
FOTO_ANTES="$(foto)"
echo "── /Applications ANTES ──"; echo "$FOTO_ANTES" | sed 's/^/   /'
echo "── build a instalar: $SHA_NUEVA"

# ── 2 · cerrar lo que esté corriendo de la INSTALADA ─────────────────────────
# Sólo la instalada: jamás un sidecar de otro worktree (el nombre del binario es
# idéntico en todos y un pkill por nombre barre el trabajo de una sesión hermana).
pkill -f '/Applications/Aleph.app/Contents/MacOS' 2>/dev/null || true
sleep 2

# ── 3 · sudo SÓLO si hace falta ──────────────────────────────────────────────
if [ -w /Applications ] && { [ ! -e "$INST" ] || [ -w "$INST" ]; }; then SUDO=""; else SUDO="sudo"; fi
[ -n "$SUDO" ] && { sudo -n true 2>/dev/null || echo "  · hace falta sudo: te va a pedir la clave"; }

# ── 4 · re-verificar la foto JUSTO ANTES de escribir ─────────────────────────
FOTO_AHORA="$(foto)"
if [ "$FOTO_AHORA" != "$FOTO_ANTES" ]; then
  echo "✗✗ /Applications CAMBIÓ mientras corríamos — otra sesión lo tocó. NO escribo nada."
  diff <(echo "$FOTO_ANTES") <(echo "$FOTO_AHORA") || true
  exit 1
fi

# ── 5 · RESPALDO ─────────────────────────────────────────────────────────────
if [ -d "$INST" ]; then
  $SUDO cp -Rc "$INST" "$BAK" 2>/dev/null || $SUDO cp -R "$INST" "$BAK"
  echo "✓ respaldo en $BAK  ($(sha_side "$BAK"))"
else
  echo "· no había instalada previa — sin respaldo que hacer"
fi

# ── 6 · INSTALAR — rm ANTES de cp (cp -R sobre un bundle existente FUSIONA) ──
$SUDO rm -rf "$INST"
[ -e "$INST" ] && { echo "✗ no pude borrar $INST"; exit 1; }
$SUDO cp -Rc "$NUEVA" /Applications/ 2>/dev/null || $SUDO cp -R "$NUEVA" /Applications/
$SUDO xattr -dr com.apple.quarantine "$INST" 2>/dev/null || true

# ── 7 · verificar que lo instalado ES el build ───────────────────────────────
SHA_INST="$(sha_side "$INST")"
[ "$SHA_INST" = "$SHA_NUEVA" ] || { echo "✗ lo instalado NO coincide con el build ($SHA_INST ≠ $SHA_NUEVA)"; exit 1; }
echo "✓ instalada — $INST  ($SHA_INST)"
echo "── /Applications DESPUÉS ──"; foto | sed 's/^/   /'
echo
echo "· rollback:  rm -rf $INST && mv $BAK $INST"
