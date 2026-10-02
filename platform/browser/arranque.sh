#!/usr/bin/env bash
# arranque.sh — el pack de BROWSER USE. [Gate 4 · Fase 6 · §6.a]
# Mismo contrato que búsqueda y research: runtime PLANO (jamás venv), PYTHONHOME sólo cuando
# usamos el nuestro, y caída honesta al python3 del sistema en dev.
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── el runtime, COMPARTIDO ────────────────────────────────────────────────────────────
# `research/runtime` es el mismo que ya usan los otros dos (busqueda/arranque.sh:90-96 y
# research/arranque.sh:26). No se hace otro: el último commit de main costó justamente
# confundir la forma («el elif pedía un venv que ya no se produce»).
ALEPH_RUNTIME="$AQUI/../sala/research/runtime"
ALEPH_PY="$ALEPH_RUNTIME/bin/python3"
if [ -x "$ALEPH_PY" ]; then
  export PYTHONHOME="$ALEPH_RUNTIME"
else
  ALEPH_PY="$(command -v python3 || true)"
  unset PYTHONHOME || true
fi
[ -n "$ALEPH_PY" ] && [ -x "$ALEPH_PY" ] || {
  echo "Aleph Browser: falta un intérprete de Python" >&2; exit 69; }

# ── el navegador que ya viaja ─────────────────────────────────────────────────────────
# MEDIDO 2026-08-18: `chrome-headless-shell` habla CDP 1.3 y da un target `page` navegable,
# así que NO hace falta un Chrome completo. browser-use lo maneja por CDP (`cdp-use`), no
# por Playwright — por eso se apunta con `executable_path`, no con PLAYWRIGHT_BROWSERS_PATH.
if [ -z "${ALEPH_BROWSER_CHROMIUM:-}" ]; then
  # In a macOS .app the sandboxed Chromium and its ICU/pak siblings must be
  # real files together in Contents/Resources. PyInstaller's Frameworks links
  # are not usable by Chromium's child process.
  _chrome_root="$AQUI/../../third_party/vane/.playwright"
  if [ ! -d "$_chrome_root" ] && [ -d "$AQUI/../../../Resources/third_party/vane/.playwright" ]; then
    _chrome_root="$AQUI/../../../Resources/third_party/vane/.playwright"
  fi
  _shell="$(find "$_chrome_root" -type f -name 'chrome-headless-shell' 2>/dev/null | head -1 || true)"
  [ -n "$_shell" ] && export ALEPH_BROWSER_CHROMIUM="$_shell"
fi

# ── EL PYTHONPATH: EL ÁRBOL IMPORTADO **Y EL LIB COMPARTIDO** ────────────────────────
# ⚠️ Este era un defecto mío y lo destapó el build 5: acá iba SÓLO el árbol importado, así
# que `import browser_use` resolvía y `Agent` moría en `No module named bubus`. Sus 36
# dependencias viven en el MISMO lib que Deep Research (`platform/sala/research/lib`) —
# solapan en 15 de 25 y las 9 que faltaban las agrega `deploy/fase6/producir_browser.sh`.
# Un lib por modo habría sido ~200 MB duplicados adentro del onefile.
ALEPH_LIB="$AQUI/../sala/research/lib"
export PYTHONPATH="$AQUI/../../third_party/browser-use:$ALEPH_LIB${PYTHONPATH:+:$PYTHONPATH}"

# ── LA TELEMETRÍA, MUERTA POR ENTORNO Y SIN TOCAR EL ÁRBOL AJENO ─────────────────────
# `posthog` está declarada como extirpación (EXTIRPACIONES.md §1) y NO viaja. Su import es
# perezoso y guardado —`telemetry/service.py:82-85` sólo lo hace si `ANONYMIZED_TELEMETRY`—
# así que apagarla acá deja la línea inalcanzable: ley 0 respetada (árbol byte-idéntico) y
# un paquete menos. `BROWSER_USE_CLOUD_SYNC` deriva de la misma (`config.py:63`) y se apaga
# explícito igual, para no depender de esa derivación.
export ANONYMIZED_TELEMETRY=false
export BROWSER_USE_CLOUD_SYNC=false

PORT="${1:-0}"
[ "${1:-}" = "--port" ] && PORT="${2:-0}"
exec "$ALEPH_PY" "$AQUI/servidor.py" --port "$PORT"
