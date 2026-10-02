#!/usr/bin/env bash
# Historical test name retained for callers. Current contract: both Sala launchers
# use an independently configured URL and never discover/start a bundled server.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
for launcher in "$RAIZ/platform/sala/busqueda/arranque.sh" "$RAIZ/platform/sala/research/arranque.sh"; do
  grep -Fq '[ -n "${ALEPH_SEARXNG_URL:-}" ]' "$launcher" || {
    echo "FAIL: missing external-provider guard in $launcher" >&2; exit 1; }
  if grep -Eq 'searxng/lib|searx\.webapp|SEARXNG_PID' "$launcher"; then
    echo "FAIL: bundled SearXNG launch path remains in $launcher" >&2; exit 1
  fi
done
if grep -Eq '_SEARXNG_LIB|third_party/vane/searxng' "$RAIZ/deploy/fase4/aleph_sidecar.spec"; then
  echo "FAIL: SearXNG server is declared in the bundle spec" >&2; exit 1
fi
echo "PASS: both Sala launchers require an external URL; no bundled SearXNG path"
