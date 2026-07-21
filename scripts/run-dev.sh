#!/usr/bin/env bash
# Start backend (:8000) and frontend (:5173) together. Ctrl-C stops both.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

"$SCRIPT_DIR/run-backend.sh" &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

"$SCRIPT_DIR/run-frontend.sh"
