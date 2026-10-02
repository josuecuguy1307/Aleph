#!/usr/bin/env bash
# Stage 2 — boot smoke. Launches the real start.sh and asserts all three
# processes bind their ports, exactly as a first-time user's run must. Deps are
# already installed in the image, so SKIP_INSTALL=1; NO_OPEN=1 stops it trying
# to open a browser in the container. Provider creds are NOT set on purpose:
# a fresh user has none and picks a provider in the UI, so boot must not need them.
set -uo pipefail

export SKIP_INSTALL=1 NO_OPEN=1
echo "== launching ./start.sh (no install, no browser) =="
./start.sh >/tmp/start.log 2>&1 &
START_PID=$!

# Poll the three fixed ports start.sh binds: engine 4096, ingest 4500, web 5173.
ports=(4096 4500 5173)
names=(engine ingest web)
deadline=$((SECONDS + 90))
declare -a up=(0 0 0)
while [ $SECONDS -lt $deadline ]; do
  all=1
  for i in "${!ports[@]}"; do
    # Probe both stacks: vite binds localhost (IPv6 ::1) while the engine and
    # ingest bind 127.0.0.1 — same dual probe start.sh uses (start.sh:109).
    if [ "${up[$i]}" -eq 0 ] && { (exec 3<>/dev/tcp/127.0.0.1/"${ports[$i]}") 2>/dev/null \
                                  || (exec 3<>/dev/tcp/::1/"${ports[$i]}") 2>/dev/null; }; then
      up[$i]=1
      echo "OK: ${names[$i]} listening on ${ports[$i]}"
    fi
    [ "${up[$i]}" -eq 0 ] && all=0
  done
  [ $all -eq 1 ] && break
  # Bail early if start.sh itself died.
  kill -0 "$START_PID" 2>/dev/null || { echo "FAIL: start.sh exited early"; break; }
  sleep 1
done

# Tear the stack down regardless of outcome.
kill "$START_PID" 2>/dev/null || true
pkill -P "$START_PID" 2>/dev/null || true

fail=0
for i in "${!ports[@]}"; do
  [ "${up[$i]}" -eq 1 ] || { echo "FAIL: ${names[$i]} never bound ${ports[$i]}"; fail=1; }
done

if [ $fail -ne 0 ]; then
  echo "== start.sh log =="
  cat /tmp/start.log
  exit 1
fi

echo
echo "PASS: fresh clone boots engine + ingest + web with no provider creds."
