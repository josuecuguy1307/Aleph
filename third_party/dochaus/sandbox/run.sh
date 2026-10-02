#!/usr/bin/env bash
# Fresh-clone test: build an image from only the files git tracks, install all
# four workspaces the way start.sh does (stage 1, in the build), then boot the
# whole stack and assert every port binds (stage 2). Proves a stranger who
# clones the repo and runs ./start.sh gets a working first run (#42, #23).
#
#   ./sandbox/run.sh                 # full: install + boot smoke at HEAD
#   REF=<commit> ./sandbox/run.sh    # test any ref
#   SKIP_BOOT=1 ./sandbox/run.sh     # install proof only (skip boot smoke)
set -euo pipefail
cd "$(dirname "$0")/.."

REF="${REF:-HEAD}"
echo "doc.haus sandbox: archiving tracked files at $REF"

# git archive emits ONLY tracked content — no working-tree node_modules, no
# untracked manifests — so the container starts from a true fresh clone.
git archive --format=tar "$REF" -o sandbox/fresh.tar
trap 'rm -f sandbox/fresh.tar' EXIT

echo "doc.haus sandbox: stage 1 — install (start.sh loop, all workspaces)"
docker build -f sandbox/Dockerfile -t dochaus-freshclone sandbox/

if [ -n "${SKIP_BOOT:-}" ]; then
  echo
  echo "doc.haus sandbox: PASS (install only) — fresh clone of $REF installs cleanly."
  exit 0
fi

echo
echo "doc.haus sandbox: stage 2 — boot smoke (engine + ingest + web)"
# --init so the container reaps the process tree start.sh spawns on exit.
docker run --rm --init dochaus-freshclone bash /usr/local/bin/verify-boot.sh

echo
echo "doc.haus sandbox: PASS — fresh clone of $REF installs AND boots."
