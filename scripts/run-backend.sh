#!/usr/bin/env bash
# Start the FastAPI backend on :8000 with the render toolchain on PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

VENV="$ROOT/.venv"
if [ ! -x "$VENV/bin/uvicorn" ]; then
  echo "No virtualenv at $VENV (or uvicorn missing)." >&2
  echo "Set it up first:" >&2
  echo "  cd \"$ROOT/backend\" && python3 -m venv ../.venv && ../.venv/bin/pip install -e \".[dev]\"" >&2
  exit 1
fi

# LaTeX (number-line labels) + Homebrew (ffmpeg) must be on PATH for rendering.
export PATH="/Library/TeX/texbin:/opt/homebrew/bin:$PATH"

cd "$ROOT/backend"
echo "Backend → http://localhost:8000"
exec "$VENV/bin/uvicorn" app.main:app --port 8000 --reload
