#!/usr/bin/env bash
# Runs alembic upgrade head, then execs the container's CMD. Set
# `SKIP_MIGRATIONS=1` to bypass (useful for one-off shell containers or when
# a sibling container already handled it).
set -euo pipefail

if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
else
  echo "[entrypoint] skipping migrations (SKIP_MIGRATIONS=1)"
fi

# tini is PID 1 (set by Dockerfile ENTRYPOINT); exec so signals still reach us.
exec "$@"
