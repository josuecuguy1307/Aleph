#!/usr/bin/env bash
# Stage 1 — install. Runs the EXACT install loop from start.sh against a fresh
# clone (tracked files only) and asserts the dochaus config-layer deps + the
# docxodus patch land. If any package.json/lockfile is untracked, the matching
# --frozen-lockfile install fails here and the image build fails.
set -euo pipefail

echo "== fresh clone manifest check =="
for d in . dochaus services/ingest apps/web; do
  test -f "$d/package.json" || { echo "FAIL: $d/package.json missing from fresh clone"; exit 1; }
  test -f "$d/bun.lock"     || { echo "FAIL: $d/bun.lock missing from fresh clone"; exit 1; }
  echo "OK: $d carries package.json + bun.lock"
done
test -f dochaus/patches/docxodus@6.4.0.patch || { echo "FAIL: docxodus patch missing"; exit 1; }

echo "== start.sh install loop (bun install --frozen-lockfile) =="
# Byte-for-byte the dirs and flag start.sh uses (start.sh:39-42).
for dir in . dochaus services/ingest apps/web; do
  echo "-- installing $dir --"
  (cd "$dir" && bun install --frozen-lockfile)
done

echo "== assert dochaus config-layer deps resolved =="
for dep in @xenova/transformers docxodus mammoth unpdf @opencode-ai/plugin; do
  test -d "dochaus/node_modules/$dep" || { echo "FAIL: $dep did not install"; exit 1; }
  echo "OK: $dep"
done

echo "== assert docxodus patch applied =="
boot=dochaus/node_modules/docxodus/dist/wasm/_framework/blazor.boot.json
test -f "$boot" || { echo "FAIL: $boot missing"; exit 1; }
grep -q '"wasmSymbols"' "$boot" && { echo "FAIL: docxodus patch did not apply"; exit 1; }
echo "OK: docxodus patch applied (wasmSymbols removed)"

echo
echo "PASS: fresh clone installs all four workspaces cleanly."
