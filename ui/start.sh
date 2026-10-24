#!/usr/bin/env bash
# Spec: docs/specs/ui.md
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -d .venv ]; then
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    echo "python3 3.11 or later is required." >&2
    exit 1
  fi
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[test]'
fi

# Port 7991 unless the caller passes --port.
port=7991
args=("$@")
for i in "${!args[@]}"; do
  case "${args[$i]}" in
    --port=*) port="${args[$i]#--port=}" ;;
    --port) port="${args[$((i + 1))]:-}" ;;
  esac
done
case " $* " in
  *" --port"*) set -- "$@" ;;
  *) set -- --port "$port" "$@" ;;
esac

# Stop whatever listens on the port: SIGTERM first, so a UI server stops its jobs, then SIGKILL after 5 seconds.
pids=$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$pids" ]; then
  echo "Stopping process $(echo $pids) on port $port"
  kill -TERM $pids 2>/dev/null || true
  for _ in $(seq 50); do
    pids=$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    [ -z "$pids" ] && break
    sleep 0.1
  done
  [ -n "$pids" ] && kill -KILL $pids 2>/dev/null || true
fi

exec .venv/bin/python -m ui.server "$@"
