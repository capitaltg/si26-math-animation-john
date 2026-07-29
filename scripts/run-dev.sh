#!/usr/bin/env bash
# Start backend (:8000), frontend (:5173), and the meta-template worker.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

"$SCRIPT_DIR/run-backend.sh" &
BACKEND_PID=$!

"$SCRIPT_DIR/run-meta-worker.sh" &
WORKER_PID=$!

cleanup() {
  trap - EXIT INT TERM
  kill "$BACKEND_PID" "$WORKER_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  wait "$WORKER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$SCRIPT_DIR/run-frontend.sh"
