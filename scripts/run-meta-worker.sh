#!/usr/bin/env bash
# Poll the durable meta-template generation queue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

VENV="$ROOT/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "No virtualenv at $VENV (or python missing)." >&2
  echo "Set it up first:" >&2
  echo "  cd \"$ROOT/backend\" && python3 -m venv ../.venv && ../.venv/bin/pip install -e \".[dev]\"" >&2
  exit 1
fi

# Preview validation uses the same render toolchain as the backend.
export PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH"

cd "$ROOT/backend"
echo "Meta worker → polling queued template-generation jobs"
exec "$VENV/bin/python" -m scripts.meta_worker
