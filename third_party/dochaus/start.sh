#!/usr/bin/env bash
# Aleph Legal pack launcher. F4 owns this process group; this launcher owns exactly
# its three children: engine, ingest and visible Legal web. No inherited port or
# process is reaped, and stopping the group stops all three.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

log() {
  printf '%s\n' "LEGAL $*" >&2
}

# In the installed .app the runtime travels next to this launcher, as an O1 pack
# binary. Development deliberately falls back to the Bun selected by the shell; a
# distributed installation never relies on that shell state.
ALEPH_BUN="$ROOT/runtime/bun"
if [ ! -x "$ALEPH_BUN" ]; then
  ALEPH_BUN="$(command -v bun || true)"
fi
[ -n "$ALEPH_BUN" ] && [ -x "$ALEPH_BUN" ] || {
  echo "Aleph Legal: falta el runtime Bun embebido del pack" >&2
  exit 69
}

PUBLIC_PORT=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --port) PUBLIC_PORT="${2:-}"; shift 2 ;;
    *) echo "Aleph Legal: argumento desconocido: $1" >&2; exit 64 ;;
  esac
done
[ -n "$PUBLIC_PORT" ] || { echo "Aleph Legal: falta --port del pack" >&2; exit 64; }

READY_TIMEOUT_S="${ALEPH_LEGAL_READY_S:-${ALEPH_PACK_ARRANQUE_S:-25}}"
case "$READY_TIMEOUT_S" in
  ''|*[!0-9]*) log "invalid readiness timeout: $READY_TIMEOUT_S"; exit 64 ;;
esac

# The pack passes a per-user config directory as DOCHAUS_CONFIG_DIR and persistent
# matter storage as WORKSPACE_ROOT. Nothing is written into this imported tree.
export WORKSPACE_ROOT="${WORKSPACE_ROOT:?Aleph Legal requiere WORKSPACE_ROOT}"
export DOCHAUS_CONFIG_DIR="${DOCHAUS_CONFIG_DIR:?Aleph Legal requiere DOCHAUS_CONFIG_DIR}"
mkdir -p "$WORKSPACE_ROOT" "$DOCHAUS_CONFIG_DIR"

free_port() {
  python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

ENGINE_PORT="$(free_port)"
INGEST_PORT="$(free_port)"
if [ "$ENGINE_PORT" = "$INGEST_PORT" ]; then INGEST_PORT="$(free_port)"; fi

log "cwd=$ROOT"
log "assigned port public=$PUBLIC_PORT engine=$ENGINE_PORT ingest=$INGEST_PORT dynamic=true"
log "stdout/stderr for child processes are inherited by Aleph pack.log"

# The generated configuration carries the current Aleph sidecar URL and session.
# Complete it with Legal's tool/instruction layer at launch, in the user's config
# directory, never with an upstream provider or a key typed into the legal UI.
"$ALEPH_BUN" run "$ROOT/script/aleph-legal-config.ts" "$DOCHAUS_CONFIG_DIR/opencode.json" "$ROOT"

# PyInstaller does not preserve directory symlinks, and every workspace package of the
# monorepo lives in node_modules only as a symlink to its real directory under packages/
# (hoisted install; 10 links measured: `opencode` + `@opencode-ai/*`). The bytes travel —
# the map does not — so a frozen install dies with `Cannot find module '@opencode-ai/core'`.
# Re-weave the map at boot, generically and only where missing: scan the workspace globs,
# read each package name, link name -> real dir. Idempotent; a dev tree is untouched.
python3 - "$ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]
nm = os.path.join(root, "node_modules")
globs = ["packages", "packages/console", "packages/stats"]
candidates = [os.path.join(root, "packages", "sdk", "js"), os.path.join(root, "packages", "slack")]
for g in globs:
    base = os.path.join(root, g)
    if os.path.isdir(base):
        candidates.extend(os.path.join(base, d) for d in os.listdir(base))
for cand in candidates:
    pj = os.path.join(cand, "package.json")
    if not os.path.isfile(pj):
        continue
    try:
        name = json.load(open(pj)).get("name") or ""
    except Exception:
        continue
    if not name:
        continue
    dest = os.path.join(nm, *name.split("/"))
    if os.path.lexists(dest):
        continue
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.symlink(os.path.relpath(cand, os.path.dirname(dest)), dest)
PY

pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ENGINE_CMD="$ALEPH_BUN run packages/opencode/src/index.ts serve --port $ENGINE_PORT --hostname 127.0.0.1 --print-logs --log-level ${OPENCODE_LOG_LEVEL:-WARN}"
log "spawn command=$ENGINE_CMD"
log "spawn cwd=$ROOT env=OPENCODE_CONFIG_DIR=$DOCHAUS_CONFIG_DIR INGEST_URL=http://127.0.0.1:$INGEST_PORT"
OPENCODE_CONFIG_DIR="$DOCHAUS_CONFIG_DIR" INGEST_URL="http://127.0.0.1:$INGEST_PORT" \
  "$ALEPH_BUN" run packages/opencode/src/index.ts serve --port "$ENGINE_PORT" --hostname 127.0.0.1 \
  --print-logs --log-level "${OPENCODE_LOG_LEVEL:-WARN}" &
pids+=("$!")
ENGINE_PID="${pids[0]}"
log "pid=$ENGINE_PID role=engine"

INGEST_CMD="$ALEPH_BUN run src/server.ts"
log "spawn command=$INGEST_CMD"
log "spawn cwd=$ROOT/services/ingest env=INGEST_PORT=$INGEST_PORT WORKSPACE_ROOT=$WORKSPACE_ROOT"
(cd services/ingest && INGEST_PORT="$INGEST_PORT" "$ALEPH_BUN" run src/server.ts) &
pids+=("$!")
INGEST_PID="${pids[1]}"
log "pid=$INGEST_PID role=document-service"

compact() {
  printf '%s' "$1" | tr '\n' ' ' | cut -c1-1200
}

wait_http() {
  local role="$1"
  local url="$2"
  local pid="$3"
  local needle="${4:-}"
  local deadline last response
  deadline=$(( $(date +%s) + READY_TIMEOUT_S ))
  last=""
  log "health URL=$url role=$role"
  while :; do
    if ! kill -0 "$pid" 2>/dev/null; then
      set +e
      wait "$pid"
      local code=$?
      set -e
      log "exit role=$role pid=$pid exit_code=$code"
      return 1
    fi
    response="$(curl -sS --connect-timeout 1 --max-time 2 "$url" 2>&1)" && {
      if [ -n "$needle" ] && ! printf '%s' "$response" | grep -q "$needle"; then
        last="unexpected health shape: $(compact "$response")"
      else
        log "health response role=$role status=200 body=$(compact "$response")"
        return 0
      fi
    }
    last="${last:-$response}"
    if [ "$(date +%s)" -ge "$deadline" ]; then
      log "health failed role=$role url=$url detail=$(compact "$last")"
      return 1
    fi
    sleep 0.25
  done
}

# Do not expose the web surface as ready while either backend is dead.  The web
# app has its own probes, but publishing it first made the Aleph pack healthcheck
# return 200 while React stayed forever on BootScreen.
if ! wait_http "engine" "http://127.0.0.1:$ENGINE_PORT/global/health" "$ENGINE_PID" 'healthy'; then
  log "READY=false reason=engine-not-ready"
  exit 70
fi
if ! wait_http "engine-config" "http://127.0.0.1:$ENGINE_PORT/global/config" "$ENGINE_PID"; then
  log "READY=false reason=engine-config-not-ready"
  exit 70
fi
if ! wait_http "document-service" "http://127.0.0.1:$INGEST_PORT/matters" "$INGEST_PID"; then
  log "READY=false reason=document-service-not-ready"
  exit 70
fi

# La UI que viaja ya fue horneada por Vite. Servir `dist` con Bun conserva exactamente el
# tercer proceso del pack, pero no arrastra Vite ni su toolchain de contributor dentro de la
# .app instalada.
WEB_CMD="$ALEPH_BUN run script/serve-dist.ts --port $PUBLIC_PORT"
log "spawn command=$WEB_CMD"
log "spawn cwd=$ROOT/apps/web env=OPENCODE_URL=http://127.0.0.1:$ENGINE_PORT INGEST_URL=http://127.0.0.1:$INGEST_PORT"
(cd apps/web && OPENCODE_URL="http://127.0.0.1:$ENGINE_PORT" \
  INGEST_URL="http://127.0.0.1:$INGEST_PORT" "$ALEPH_BUN" run script/serve-dist.ts --port "$PUBLIC_PORT") &
pids+=("$!")
WEB_PID="${pids[2]}"
log "pid=$WEB_PID role=web"

if ! wait_http "web" "http://127.0.0.1:$PUBLIC_PORT/" "$WEB_PID"; then
  log "READY=false reason=web-not-ready"
  exit 70
fi

log "READY public=$PUBLIC_PORT engine=$ENGINE_PORT ingest=$INGEST_PORT"

echo "Aleph Legal: motor=$ENGINE_PORT legal=$PUBLIC_PORT ingest=$INGEST_PORT"

# Portable equivalent of `wait -n`; macOS ships Bash 3.2, which does not have
# that option.  A child exit is a pack failure, never a silent partial stack.
while :; do
  for pid in "${pids[@]}"; do
    state="$(ps -p "$pid" -o state= 2>/dev/null | tr -d ' ')"
    case "$state" in
      ''|Z*)
        set +e
        wait "$pid"
        code=$?
        set -e
        log "exit pid=$pid exit_code=$code"
        exit "$code"
        ;;
    esac
  done
  sleep 0.5
done
