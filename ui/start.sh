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
case " $* " in
  *" --port"*) exec .venv/bin/python -m ui.server "$@" ;;
  *) exec .venv/bin/python -m ui.server --port 7991 "$@" ;;
esac
