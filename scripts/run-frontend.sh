#!/usr/bin/env bash
# Start the Vite dev server on :5173 (proxies /upload /render /clips to :8000).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

export PATH="/opt/homebrew/bin:$PATH"

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  echo "Installing frontend deps (first run)…"
  npm install
fi

echo "Frontend → http://localhost:5173"
exec npm run dev
