#!/usr/bin/env bash
# Native-only compiled update: never rewrite Frameworks, core, user data or locales.
# Baselines are the measured global bundle; old native binary stays recoverable.
set -euo pipefail
NUEVA="${1:?ruta del Mach-O compilado fuera del bundle}"
INST="/Applications/Aleph.app/Contents/MacOS/app"
CORE="/Applications/Aleph.app/Contents/MacOS/aleph_sidecar"
COPY="/Applications/Aleph.app/Contents/Frameworks/product/app/design/i18n.js"
BASE="${2:-140f68086acf27640b6df2410cd7408026883b384270977de220d8fd885d675a}"
case "$BASE" in
  140f68086acf27640b6df2410cd7408026883b384270977de220d8fd885d675a|bf5aa0a59d2b7f7a95d9d2666802eb3f2bcfe229e5159c07d21d262fceb5546d) ;;
  *) echo '✗ base nativa desconocida'; exit 1 ;;
esac
BAK="/Applications/Aleph.cascara-pre-idiomas-global-${BASE:0:12}"
PEND="/Applications/Aleph.app/Contents/MacOS/app.idiomas-pending"
BASE_CORE="057c9813c3a8ea817496181d016c23dffefde1fc058d7484b2873833945474b9"
BASE_COPY="3dad00f3b8388d85bf0fd5169b48d153de64c218847d097d4dc88c5c7825c256"
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
guard() {
  [ "$(sha "$INST")" = "$BASE" ] && [ "$(sha "$CORE")" = "$BASE_CORE" ] &&
    [ "$(sha "$COPY")" = "$BASE_COPY" ] || { echo '✗ cambió el bundle medido; no instalo'; exit 1; }
}
[ -x "$NUEVA" ] && [ -f "$INST" ] || { echo '✗ ejecutable ausente'; exit 1; }
file "$NUEVA" | rg -q 'Mach-O 64-bit executable arm64' || { echo '✗ arquitectura incorrecta'; exit 1; }
codesign --verify --strict "$NUEVA"
[ ! -e "$BAK" ] && [ ! -e "$PEND" ] || { echo '✗ no sobrescribo respaldo o pendiente'; exit 1; }
NUEVO_SHA="$(sha "$NUEVA")"
[ "$NUEVO_SHA" != "$BASE" ] || { echo '✗ la cáscara no cambió'; exit 1; }
guard
pkill -f '/Applications/Aleph.app/Contents/MacOS' 2>/dev/null || true
sleep 2
guard
cp -p "$INST" "$BAK"
[ "$(sha "$BAK")" = "$BASE" ] || { echo '✗ respaldo incorrecto'; exit 1; }
cp -p "$NUEVA" "$PEND"
[ "$(sha "$PEND")" = "$NUEVO_SHA" ] || { echo '✗ copia incorrecta'; exit 1; }
# The existing onedir app has unsealed Frameworks: bundle verification is not
# claimed. Verify the compiler's standalone Mach-O above and its exact bytes here.
guard
mv "$PEND" "$INST"
[ "$(sha "$INST")" = "$NUEVO_SHA" ] && [ "$(sha "$CORE")" = "$BASE_CORE" ] &&
  [ "$(sha "$COPY")" = "$BASE_COPY" ] || { echo '✗ verificación final falló'; exit 1; }
echo "✓ cáscara instalada: $NUEVO_SHA"
echo "✓ core y copy intactos; respaldo nativo: $BAK"
