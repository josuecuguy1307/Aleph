#!/usr/bin/env bash
# Install only already-compiled locale/UI assets, with recoverable backups.
# Never restart an app/server or rewrite native/core binaries or user data.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$REPO/deploy/fase4/aleph-shell/src-tauri/target/release/bundle/macos/Aleph.app"
INST=/Applications/Aleph.app
CORE=b1c51ba7017ccee57348a9ea78849a098b52ea4dc0303943e6ea23a19020034f
NATIVE=54fe34922dd9225d18b8e3d56e4938db6b9f8c45fdaaeddea674bb0244bf5a00
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
guard() {
  for app in "$STAGE" "$INST"; do
    [ "$(sha "$app/Contents/MacOS/aleph_sidecar")" = "$CORE" ]
    [ "$(sha "$app/Contents/MacOS/app")" = "$NATIVE" ]
  done
}
guard
SCIENCE="$REPO/third_party/openscience/backend/cli/dist/@synsci/openscience-darwin-arm64/bin/openscience"
DESIGN="$REPO/third_party/codesign/apps/desktop/release/aleph-diseno-mac-arm64.zip"
EDU="$REPO/third_party/deeptutor/web/.next/standalone"
[ -x "$SCIENCE" ] && [ -f "$DESIGN" ] && [ -f "$EDU/server.js" ]
codesign --verify --strict "$SCIENCE"
[ -d "$EDU/node_modules/next" ] && [ -d "$EDU/.next/static" ] && [ -f "$EDU/public/aleph-piel.js" ]
BACKUP=$(mktemp -d /Applications/Aleph.vocabulario-pre-20260912-XXXXXX)
replace() {
  local source=$1 relative=$2
  [ -e "$source" ]
  for kind in stage installed; do
    local app="$INST"
    [ "$kind" != stage ] || app="$STAGE"
    local dest="$app/Contents/Frameworks/$relative"
    local saved="$BACKUP/$kind/$relative"
    mkdir -p "$(dirname "$saved")" "$(dirname "$dest")"
    [ ! -e "$saved" ]
    if [ -e "$dest" ]; then mv "$dest" "$saved"; fi
    if [ -d "$source" ]; then
      if cp -pR "$source" "$dest" && diff -qr "$source" "$dest"; then
        continue
      fi
    else
      if cp -p "$source" "$dest" && cmp "$source" "$dest"; then
        continue
      fi
    fi
    # Restore this destination if copying or verification fails (e.g. full disk).
    # Keep the incomplete copy beside the backup for diagnosis; do not delete data.
    [ ! -e "$dest" ] || mv "$dest" "$saved.partial"
    [ ! -e "$saved" ] || mv "$saved" "$dest"
    echo "Installation failed; restored $dest" >&2
    return 1
  done
}
if [ "${1:-}" = --office-only ]; then
  replace "$REPO/third_party/openwork/apps/app/dist" third_party/openwork/apps/app/dist
  guard
  echo "Verified compiled Office interface. Backup: $BACKUP"
  exit 0
fi
if [ "${1:-}" = --finance-only ]; then
  replace "$REPO/third_party/vibetrading/frontend/dist" third_party/vibetrading/frontend/dist
  guard
  echo "Verified compiled Finance interface. Backup: $BACKUP"
  exit 0
fi
if [ "${1:-}" = --legal-only ]; then
  replace "$REPO/third_party/dochaus/apps/web/dist" third_party/dochaus/apps/web/dist
  guard
  echo "Verified compiled Legal interface. Backup: $BACKUP"
  exit 0
fi
if [ "${1:-}" = --design-only ]; then
  replace "$DESIGN" third_party/codesign/apps/desktop/release/aleph-diseno-mac-arm64.zip
  guard
  echo "Verified compiled Design archive. Backup: $BACKUP"
  exit 0
fi
if [ "${1:-}" = --education-only ]; then
  replace "$EDU" third_party/deeptutor/web/.next/standalone
  guard
  echo "Verified compiled Education interface. Backup: $BACKUP"
  exit 0
fi
if [ "${1:-}" = --science-only ]; then
  replace "$REPO/third_party/openscience/frontend/workspace/dist" third_party/openscience/frontend/workspace/dist
  replace "$SCIENCE" third_party/openscience/bin/openscience
  guard
  echo "Verified compiled Science interface and embedded assets. Backup: $BACKUP"
  exit 0
fi
for name in Settings.dc.html i18n.js espacios-tabla.js; do
  replace "$REPO/product/app/design/$name" "product/app/design/$name"
done
for stack in openwork/apps/app dochaus/apps/web vibetrading/frontend openscience/frontend/workspace; do
  replace "$REPO/third_party/$stack/dist" "third_party/$stack/dist"
done
replace "$EDU" third_party/deeptutor/web/.next/standalone
replace "$SCIENCE" third_party/openscience/bin/openscience
replace "$DESIGN" third_party/codesign/apps/desktop/release/aleph-diseno-mac-arm64.zip
for stack in codesign/apps/desktop/src/renderer dochaus/apps/web; do
  replace "$REPO/third_party/$stack/public/aleph-piel.js" "third_party/$stack/public/aleph-piel.js"
done
guard
echo "Verified compiled interfaces in installed and staged app. Backup: $BACKUP"
